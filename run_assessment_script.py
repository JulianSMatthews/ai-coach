#!/usr/bin/env python3
"""
Run standardised assessment scenarios *in‑process* (no HTTP).

This script drives the combined assessment flow, generates OKRs, and writes the
report images/PDF under `public/reports/<user_id>/latest.{png,jpeg,pdf}`.

Quick start — single scenario
  python run_assessment_script.py competent_a
    Levels: novice | developing | competent | proficient | expert
    Variants: a | b | c | d  (phrasing styles)
    Mixed pillars: prefix with mix: e.g. "mix:training=expert,nutrition=competent|c"

Run all scenarios (40 total: 20 uniform + 20 mixed pillars)
  python run_assessment_script.py --batch
  # optional pacing between scenarios
  python run_assessment_script.py --batch --sleep 1.5
  # --start-from accepts any of the 40 keys, including mix: entries
  # auto-cycle users across two clubs (override via --club-ids or BATCH_CLUB_IDS)
  python run_assessment_script.py --batch --club-ids 1,2

User reuse vs unique user per run
  # unique user per run (default)
  python run_assessment_script.py --batch --unique
  # reuse same user record per scenario key
  python run_assessment_script.py --batch --reuse

Admin summary only (skip WhatsApp run)
  python run_assessment_script.py --admin-summary
  # optional: pass extra args if your reporting entrypoint expects them
  python run_assessment_script.py --admin-summary --admin-summary-args "tenant=1"

Environment notes
  MOCK_OUTBOUND=1 (default) prevents real WhatsApp/Twilio sends and prints previews.
  UNIQUE_TEST_USER is set by --unique/--reuse (don’t set manually unless needed).
  TEST_CLUB_ID / CLUB_ID select a default club for created users.
  BATCH_CLUB_IDS or --club-ids let you explicitly pick the clubs to cycle through.

Examples
  # Single run with compact delays
  python run_assessment_script.py expert_c

  # Mixed pillar levels (expert training, competent nutrition, defaults elsewhere)
  python run_assessment_script.py "mix:training=expert,nutrition=competent|b"

  # Batch, slower pacing for readability
  python run_assessment_script.py --batch --sleep 3

  # Reuse the same user per scenario so re-runs update the same records
  python run_assessment_script.py --batch --reuse
"""

from __future__ import annotations

# Ensure project root is on sys.path so `import app...` works anywhere
import os, sys
# Add project root (parent of this scripts/ folder) to sys.path so `import app...` works anywhere
ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
import sys, time, argparse, random
from typing import Dict, List, Tuple
import threading

# --- import your app bits ---
from app.seed import run_seed, CONCEPTS
from app.db import SessionLocal
from app.models import User, Club

# Optional models for completion/score checks (best-effort)
try:
    from app.models import AssessmentRun, PillarResult  # type: ignore
except Exception:
    AssessmentRun = None  # type: ignore
    PillarResult = None   # type: ignore
from app.assessor import continue_combined_assessment  # adjust if named differently
from app.assessor import start_combined_assessment  # ensures a new assessment session starts

# Admin summary reporting (best-effort import; may not exist in older trees)
try:
    from app import reporting as _reporting
except Exception:
    _reporting = None  # type: ignore

# --- mock outbound messaging so tests don't hit Twilio/HTTP ---
if os.environ.get("MOCK_OUTBOUND", "1") == "1":
    try:
        # Patch both assessor-level and nudges-level senders in case of direct imports
        from app import assessor as _assessor_mod
        from app import nudges as _nudges_mod

        def _noop_send_message(to: str, text: str, category: str | None = None):
            preview = (text or "")[:120].replace("\n", " ")
            print(f"[MOCK OUTBOUND] to={to} :: {preview}")
            return True

        _assessor_mod.send_message = _noop_send_message  # type: ignore
        _nudges_mod.send_message = _noop_send_message    # type: ignore
        _nudges_mod.send_whatsapp = lambda **kwargs: True  # type: ignore
    except Exception as _e:
        print(f"[warn] MOCK_OUTBOUND patch failed: {_e}")

# Optional models (best-effort) for consent/state detection
try:
    from app.models import AssessSession, MessageLog  # type: ignore
except Exception:
    AssessSession = None  # type: ignore
    MessageLog = None     # type: ignore

# Helper to fetch the latest assessment session id for a user
def _latest_session_id_for(user: "User"):
    if AssessSession is None:
        return None
    try:
        with SessionLocal() as s:
            sess = (
                s.query(AssessSession)
                 .filter(AssessSession.user_id == user.id)
                 .order_by(AssessSession.id.desc())
                 .first()
            )
            return getattr(sess, "id", None) if sess is not None else None
    except Exception:
        return None


# Debug: list recent sessions for this user
def _debug_list_sessions_for(user: "User", limit: int = 5):
    if AssessSession is None:
        print("[debug] AssessSession model unavailable")
        return
    try:
        with SessionLocal() as s:
            rows = (
                s.query(AssessSession)
                 .filter(AssessSession.user_id == user.id)
                 .order_by(AssessSession.id.desc())
                 .limit(limit)
                 .all()
            )
            if not rows:
                print("[debug] no AssessSession rows for user", getattr(user, "id", None))
                return
            print(f"[debug] recent AssessSession for user {getattr(user,'id',None)}:")
            for r in rows:
                cid = getattr(r, 'id', None)
                cts = getattr(r, 'created_at', None) or getattr(r, 'created', None)
                uts = getattr(r, 'updated_at', None) or getattr(r, 'updated', None)
                cg  = getattr(r, 'consent_given', None)
                cya = getattr(r, 'consent_yes_at', None)
                st  = getattr(r, 'status', None)
                print(f"  - id={cid} created={cts} updated={uts} consent={cg} yes_at={cya} status={st}")
    except Exception as e:
        print(f"[debug] error listing sessions: {e}")

# Wait for final completion message in MessageLog (best-effort)
def _wait_for_completion_message(user: "User", timeout_s: float = 10.0, poll_s: float = 0.5) -> bool:
    mock = os.environ.get("MOCK_OUTBOUND", "1") == "1"
    started = time.time()
    # If MessageLog model not available or we're mocking outbound, rely on DB completion signals.
    if MessageLog is None or mock:
        while time.time() - started < timeout_s:
            try:
                if AssessmentRun is not None and PillarResult is not None:
                    with SessionLocal() as s:
                        run = (
                            s.query(AssessmentRun)
                             .filter(AssessmentRun.user_id == user.id)
                             .order_by(AssessmentRun.id.desc())
                             .first()
                        )
                        if run is not None:
                            # Consider complete when all 4 pillar rows exist. Support either column name.
                            pr_fk_col = getattr(PillarResult, 'assessment_run_id', None) or getattr(PillarResult, 'run_id', None)
                            if pr_fk_col is not None:
                                pr_count = (
                                    s.query(PillarResult)
                                     .filter(pr_fk_col == getattr(run, 'id', None))
                                     .count()
                                )
                            else:
                                # Fallback: count by user_id and recency if no FK column present
                                created_col = getattr(PillarResult, 'created_at', None) or getattr(PillarResult, 'created', None)
                                q = s.query(PillarResult).filter(PillarResult.user_id == user.id)
                                if created_col is not None and hasattr(run, 'created_at'):
                                    q = q.filter(created_col >= getattr(run, 'created_at'))
                                pr_count = q.count()
                            if pr_count >= 4:
                                return True
                time.sleep(poll_s)
            except Exception:
                time.sleep(poll_s)
        return False

    # Otherwise, scan MessageLog for completion phrases
    started = time.time()
    target_snippets = (
        "assessment complete",
        "reports:",
        "pdf written to",
    )
    with SessionLocal() as s:
        while time.time() - started < timeout_s:
            try:
                q = (
                    s.query(MessageLog)
                     .filter(MessageLog.user_id == user.id)
                     .order_by(MessageLog.id.desc())
                     .limit(50)
                     .all()
                )
                for m in q:
                    body = (getattr(m, "body", None) or getattr(m, "text", None) or "").lower()
                    direction = (getattr(m, "direction", None) or getattr(m, "role", None) or "").lower()
                    if direction in ("assistant", "outbound") and any(t in body for t in target_snippets):
                        return True
                time.sleep(poll_s)
            except Exception:
                time.sleep(poll_s)
        return False

# Nudge the assessor once or twice to flush any pending transitions at the end
def _finalize_run(user: "User") -> None:
    try:
        # A couple of empty/neutral ticks to advance any finalization step
        _continue_with_timeout(user=user, text="", timeout_s=5.0)
        time.sleep(0.5)
        _continue_with_timeout(user=user, text=" ", timeout_s=5.0)
    except Exception:
        pass
def _continue_with_timeout(user: "User", text: str, timeout_s: float = 45.0) -> bool:
    """Call continue_combined_assessment with a hard timeout to avoid hangs.
    Returns False on timeout or exception; True/False based on underlying return otherwise.
    """
    result: dict = {}
    def _runner():
        try:
            result["ret"] = continue_combined_assessment(user=user, user_text=text)
        except Exception as e:
            result["err"] = e

    th = threading.Thread(target=_runner, daemon=True)
    th.start()
    th.join(timeout_s)
    if th.is_alive():
        print(f"[timeout] continue_combined_assessment exceeded {timeout_s}s; skipping input: {text[:40]!r}")
        return False
    if "err" in result:
        print(f"[warn] continue_combined_assessment error: {result['err']}")
        return False
    return bool(result.get("ret", True))

# --- phrasing helpers for natural language answers ---
INT_WORDS = {0: "0", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven"}
def _int_word(n: int) -> str:
    return INT_WORDS.get(int(n), str(int(n)))

def _choose(seed: int, options: list[str]) -> str:
    rnd = random.Random(seed)
    return rnd.choice(options)

def phrase_value(concept: str, value: float, seed_hint: str) -> str:
    """
    Return a natural-language variant for the numeric value given a concept.
    Deterministic per (concept, seed_hint).
    """
    seed = abs(hash((concept, seed_hint))) & 0xffffffff
    is_int = float(value).is_integer()
    v_int = int(round(value))
    v_str = f"{value:g}"

    if concept in ("hydration",):
        opts = [
            f"{v_str}",
            f"{v_str} L",
            f"{v_str}L",
            f"{v_str} liters",
            f"{v_str} litres",
            f"{_int_word(v_int)} liters" if is_int else f"{v_str} liters",
        ]
        return _choose(seed, opts)

    # nutrition (per day portions)
    if concept in ("fruit_veg", "protein_intake", "processed_food"):
        unit = "portion" if v_int == 1 else "portions"
        per = "per day"
        if v_int == 0:
            opts = ["0", "none", f"no {unit} {per}"]
        else:
            opts = [
                f"{v_str}",
                f"{v_int} {unit} {per}" if is_int else f"{v_str} {unit} {per}",
                f"{_int_word(v_int)} {unit} {per}" if is_int else f"{v_str} {unit} {per}",
                f"{v_int} per day" if is_int else f"{v_str} per day",
                f"{_int_word(v_int)} per day" if is_int else f"{v_str} per day",
            ]
        return _choose(seed, opts)

    # training/resilience/recovery use days or sessions
    if concept in ("cardio_frequency", "flexibility_mobility", "support_openness",
                   "emotional_regulation", "positive_connection", "stress_recovery",
                   "optimism_perspective",
                   "bedtime_consistency", "sleep_duration", "sleep_quality"):
        label = "days"
        if concept == "strength_training":
            label = "sessions"
        if v_int == 0:
            opts = ["0", "none", f"0 {label}"]
        else:
            opts = [
                f"{v_str}",
                f"{v_int} {label}" if is_int else f"{v_str} {label}",
                f"{_int_word(v_int)} {label}" if is_int else f"{v_str} {label}",
            ]
        return _choose(seed, opts)

    # fallback
    return v_str

# --- 5 levels with baseline numeric targets ---
LEVELS = {
    "novice": {
        "nutrition": {"fruit_veg": 1, "hydration": 1, "processed_food": 4, "protein_intake": 1},
        "training":  {"cardio_frequency": 1, "flexibility_mobility": 1, "strength_training": 0},
        "resilience":{"emotional_regulation": 2, "optimism_perspective": 2, "positive_connection": 2, "stress_recovery": 2, "support_openness": 2},
        "recovery":  {"bedtime_consistency": 2, "sleep_duration": 2, "sleep_quality": 2},
    },
    "developing": {
        "nutrition": {"fruit_veg": 2, "hydration": 2, "processed_food": 3, "protein_intake": 2},
        "training":  {"cardio_frequency": 2, "flexibility_mobility": 2, "strength_training": 1},
        "resilience":{"emotional_regulation": 3, "optimism_perspective": 3, "positive_connection": 3, "stress_recovery": 3, "support_openness": 3},
        "recovery":  {"bedtime_consistency": 3, "sleep_duration": 3, "sleep_quality": 3},
    },
    "competent": {
        "nutrition": {"fruit_veg": 3, "hydration": 2.5, "processed_food": 2, "protein_intake": 3},
        "training":  {"cardio_frequency": 3, "flexibility_mobility": 3, "strength_training": 2},
        "resilience":{"emotional_regulation": 4, "optimism_perspective": 4, "positive_connection": 4, "stress_recovery": 4, "support_openness": 4},
        "recovery":  {"bedtime_consistency": 4, "sleep_duration": 4, "sleep_quality": 4},
    },
    "proficient": {
        "nutrition": {"fruit_veg": 4, "hydration": 3, "processed_food": 1, "protein_intake": 4},
        "training":  {"cardio_frequency": 4, "flexibility_mobility": 4, "strength_training": 3},
        "resilience":{"emotional_regulation": 5, "optimism_perspective": 5, "positive_connection": 5, "stress_recovery": 5, "support_openness": 5},
        "recovery":  {"bedtime_consistency": 5, "sleep_duration": 5, "sleep_quality": 5},
    },
    "expert": {
        "nutrition": {"fruit_veg": 5, "hydration": 3.5, "processed_food": 0, "protein_intake": 4},
        "training":  {"cardio_frequency": 5, "flexibility_mobility": 5, "strength_training": 3},
        "resilience":{"emotional_regulation": 6, "optimism_perspective": 6, "positive_connection": 6, "stress_recovery": 6, "support_openness": 6},
        "recovery":  {"bedtime_consistency": 6, "sleep_duration": 6, "sleep_quality": 5},
    },
}

# Default level used when a pillar isn't explicitly supplied (e.g., mixed scenarios).
DEFAULT_LEVEL = "competent"

# Canonical pillar ordering for helper functions.
PILLAR_KEYS: tuple[str, ...] = ("nutrition", "training", "resilience", "recovery")

ALL_CONCEPTS = [
    ("nutrition",  "fruit_veg"),
    ("nutrition",  "hydration"),
    ("nutrition",  "processed_food"),
    ("nutrition",  "protein_intake"),
    ("training",   "cardio_frequency"),
    ("training",   "flexibility_mobility"),
    ("training",   "strength_training"),
    ("resilience", "emotional_regulation"),
    ("resilience", "optimism_perspective"),
    ("resilience", "positive_connection"),
    ("resilience", "stress_recovery"),
    ("resilience", "support_openness"),
    ("recovery",   "bedtime_consistency"),
    ("recovery",   "sleep_duration"),
    ("recovery",   "sleep_quality"),
]

def _uniform_level_map(level: str) -> Dict[str, str]:
    """Return a per-pillar mapping where every pillar uses the same level."""
    level_key = (level or DEFAULT_LEVEL).lower()
    if level_key not in LEVELS:
        raise ValueError(f"Unknown level '{level}'")
    return {pillar: level_key for pillar in PILLAR_KEYS}

def _complete_level_map(levels_by_pillar: Dict[str, str]) -> Dict[str, str]:
    """Ensure all pillars are present and level keys are valid."""
    completed: Dict[str, str] = {}
    for pillar in PILLAR_KEYS:
        level_val = (levels_by_pillar.get(pillar) or DEFAULT_LEVEL).lower()
        if level_val not in LEVELS:
            raise ValueError(f"Unknown level '{level_val}' for pillar '{pillar}'")
        completed[pillar] = level_val
    return completed

def _scenario_answers_for_level_map(levels_by_pillar: Dict[str, str], variant: str) -> Dict[str, str]:
    """Create phrased answers where each pillar can map to a different level."""
    variant_key = (variant or "a").lower()[0]
    if variant_key not in ("a", "b", "c", "d"):
        variant_key = "a"
    completed = _complete_level_map(levels_by_pillar)
    out: Dict[str, str] = {}
    for pillar, code in ALL_CONCEPTS:
        pillar_level = completed.get(pillar, DEFAULT_LEVEL)
        val = LEVELS[pillar_level][pillar][code]
        seed_hint = f"{pillar_level}:{variant_key}:{pillar}:{code}"
        out[code] = phrase_value(code, val, seed_hint=seed_hint)
    return out

def _scenario_answers_for(level: str, variant: str) -> Dict[str, str]:
    """Create a dict of concept_code -> phrased answer for the level, varied by variant key."""
    return _scenario_answers_for_level_map(_uniform_level_map(level), variant)

def build_20_scenarios() -> Dict[str, Dict[str, str]]:
    # 4 variants per level: a,b,c,d
    variants = ["a","b","c","d"]
    scenarios: Dict[str, Dict[str, str]] = {}
    for level in ("novice","developing","competent","proficient","expert"):
        for v in variants:
            name = f"{level}_{v}"
            scenarios[name] = _scenario_answers_for(level, v)
    return scenarios


SCENARIOS: Dict[str, Dict[str, str]] = build_20_scenarios()
BASE_SCENARIO_KEYS: tuple[str, ...] = tuple(sorted(SCENARIOS.keys()))

# --- encode scenario answers into surname (ultra‑compact string) ---
# Keep under Postgres users.surname varchar(120) (observed in terminal).
MAX_SURNAME_LEN = 118  # leave room for an ellipsis if needed
MAX_FIRST_NAME_LEN = 118  # mirror surname cap to avoid varchar(120) overflows

# Short 2‑letter aliases in runtime order
_SHORT_KEYS = {
    ("nutrition","fruit_veg"): "fv",
    ("nutrition","hydration"): "hy",
    ("nutrition","processed_food"): "pf",
    ("nutrition","protein_intake"): "pr",
    ("training","cardio_frequency"): "ca",
    ("training","flexibility_mobility"): "fm",
    ("training","strength_training"): "st",
    ("resilience","emotional_regulation"): "er",
    ("resilience","optimism_perspective"): "op",
    ("resilience","positive_connection"): "pc",
    ("resilience","stress_recovery"): "sr",
    ("resilience","support_openness"): "so",
    ("recovery","bedtime_consistency"): "bc",
    ("recovery","sleep_duration"): "sd",
    ("recovery","sleep_quality"): "sq",
}

def _format_compact_value(pillar: str, code: str, val: float) -> str:
    """Return a terse value+unit: hydration in L, strength in sessions 's', others in days 'd',
    nutrition portions per day as 'pd'.
    """
    # hydration uses litres
    if code == "hydration":
        return f"{val:g}L"
    # strength sessions
    if code == "strength_training":
        return f"{val:g}s"
    # nutrition portions/day
    if code in ("fruit_veg", "processed_food", "protein_intake"):
        return f"{val:g}pd"
    # default: day counts
    return f"{val:g}d"

def _answers_surname_string_for_levels(levels_by_pillar: Dict[str, str]) -> str:
    """Compact line summarizing numeric answers for the provided level map."""
    try:
        nums_map = _complete_level_map(levels_by_pillar)
    except ValueError:
        return ""
    parts: list[str] = []
    for pillar, code in build_order():
        pillar_level = nums_map.get(pillar, DEFAULT_LEVEL)
        pillar_values = LEVELS[pillar_level][pillar]
        if code not in pillar_values:
            continue
        key = _SHORT_KEYS.get((pillar, code), code[:2])
        val = float(pillar_values[code])
        parts.append(f"{key}={_format_compact_value(pillar, code, val)}")
    s = "|".join(parts)
    return s if len(s) <= MAX_SURNAME_LEN else (s[:MAX_SURNAME_LEN-1] + "…")

def _bounded_first_name(name: str) -> str:
    """Ensure scenario-driven first names fit under varchar(120)."""
    name = (name or "").strip()
    return name if len(name) <= MAX_FIRST_NAME_LEN else (name[:MAX_FIRST_NAME_LEN-1] + "…")

def _answers_surname_string(scenario: str) -> str:
    """Backward-compatible helper for uniform-level scenarios."""
    level, _variant = _parse_level_variant(scenario)
    if level not in LEVELS:
        return ""
    return _answers_surname_string_for_levels(_uniform_level_map(level))

def _normalize_pillar_key(name: str) -> str | None:
    """Map user-provided pillar aliases onto canonical keys."""
    normalized = (name or "").strip().lower()
    mapping = {
        "nutrition": "nutrition",
        "nut": "nutrition",
        "n": "nutrition",
        "training": "training",
        "train": "training",
        "t": "training",
        "resilience": "resilience",
        "res": "resilience",
        "r": "resilience",
        "recovery": "recovery",
        "rec": "recovery",
        "sleep": "recovery",
    }
    return mapping.get(normalized)

def _parse_mix_scenario_key(s: str) -> tuple[Dict[str, str], str] | None:
    """Parse mix:<pillar=level,...>[|variant] strings."""
    raw = (s or "").strip()
    if not raw.lower().startswith("mix:"):
        return None
    body = raw[4:]
    variant = "a"
    if "|" in body:
        body, variant_part = body.rsplit("|", 1)
        variant_part = (variant_part or "").strip().lower()
        if variant_part:
            variant = variant_part[0]
    variant = variant if variant in ("a", "b", "c", "d") else "a"
    level_map: Dict[str, str] = {}
    for chunk in body.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            raise ValueError(f"Expected '=' in mix scenario segment '{chunk}'")
        pillar_raw, level_raw = chunk.split("=", 1)
        pillar = _normalize_pillar_key(pillar_raw)
        if pillar is None:
            raise ValueError(f"Unknown pillar '{pillar_raw}' in mix scenario '{raw}'")
        level = (level_raw or "").strip().lower()
        if level not in LEVELS:
            raise ValueError(f"Unknown level '{level_raw}' in mix scenario '{raw}'")
        level_map[pillar] = level
    if not level_map:
        raise ValueError(f"No pillar assignments found in mix scenario '{raw}'")
    return _complete_level_map(level_map), variant

def build_mixed_batch_scenarios() -> List[str]:
    """Return curated mix: scenario strings appended to batch runs."""
    pillar_focus_levels = ("novice", "developing", "proficient", "expert")
    variants = ("a", "b", "c", "d")
    scenarios: List[str] = []
    variant_idx = 0
    for pillar in PILLAR_KEYS:
        for level in pillar_focus_levels:
            variant = variants[variant_idx % len(variants)]
            scenarios.append(f"mix:{pillar}={level}|{variant}")
            variant_idx += 1
    scenarios.extend([
        "mix:nutrition=expert,training=expert|a",
        "mix:training=developing,resilience=expert,recovery=proficient|b",
        "mix:nutrition=novice,resilience=proficient,recovery=expert|c",
        "mix:nutrition=developing,training=proficient,recovery=novice|d",
    ])
    return scenarios

MIX_BATCH_SCENARIOS: tuple[str, ...] = tuple(build_mixed_batch_scenarios())
DEFAULT_BATCH_SCENARIOS: tuple[str, ...] = BASE_SCENARIO_KEYS + MIX_BATCH_SCENARIOS

def _parse_club_ids(raw: str) -> List[int]:
    """Split comma/semicolon separated IDs into a list of ints."""
    out: List[int] = []
    for chunk in (raw or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if chunk.isdigit():
            out.append(int(chunk))
        else:
            print(f"[club] ignoring invalid club id '{chunk}'")
    return out

def _resolve_club_cycle(requested_ids: List[int], min_count: int = 1) -> List[Tuple[int | None, str | None]]:
    """
    Return [(club_id, club_label), ...] to cycle through when creating users.
    When requested_ids is empty and min_count == 1, fall back to default assignment later.
    """
    if not requested_ids and min_count <= 1:
        return [(None, None)]
    try:
        with SessionLocal() as s:
            clubs = (
                s.query(Club)
                 .order_by(Club.id.asc())
                 .all()
            )
    except Exception as exc:
        print(f"[club] unable to fetch clubs: {exc}")
        return [(None, None)]

    if not clubs:
        print("[club] no clubs available; seeding clubs first is recommended.")
        return [(None, None)]

    rows_by_id = {
        getattr(row, "id", None): row
        for row in clubs
        if getattr(row, "id", None) is not None
    }
    selected: List["Club"] = []
    missing: List[int] = []
    for cid in requested_ids:
        row = rows_by_id.get(cid)
        if row is None:
            missing.append(cid)
            continue
        if row not in selected:
            selected.append(row)

    if missing:
        missing_str = ", ".join(str(cid) for cid in missing)
        print(f"[club] warning: missing club ids: {missing_str}")

    target_rows: List["Club"]
    if selected:
        target_rows = selected
    else:
        desired = max(min_count, 1)
        target_rows = clubs[: min(len(clubs), desired)]

    result: List[Tuple[int | None, str | None]] = []
    for row in target_rows:
        cid = getattr(row, "id", None)
        label = (
            getattr(row, "name", None)
            or getattr(row, "slug", None)
            or (f"Club {cid}" if cid is not None else None)
        )
        result.append((cid, label))
    return result or [(None, None)]

# --- scenario naming helpers ---
def _parse_level_variant(s: str) -> tuple[str, str]:
    """Return (level, variant) from a scenario key like 'novice_a'. Defaults to ('scenario','a')."""
    s = (s or "").strip().lower()
    if "_" in s:
        a, b = s.split("_", 1)
        return a or "scenario", (b or "a")[0]
    return (s or "scenario"), "a"

def _variant_short(v: str) -> str:
    """Short label for a–d phrasing variants."""
    v = (v or "a").lower()[0]
    mapping = {
        "a": "digits",
        "b": "words",
        "c": "units",
        "d": "verbose mix",
    }
    return mapping.get(v, v)

def _is_uniform_level_map(level_map: Dict[str, str]) -> bool:
    """Return True when every pillar uses the same level."""
    completed = _complete_level_map(level_map)
    vals = {completed[p] for p in PILLAR_KEYS}
    return len(vals) == 1

def _scenario_display_name(level_map: Dict[str, str], variant: str) -> str:
    """Human-friendly scenario label reused for the user first_name."""
    variant_letter = (variant or "a").upper()
    suffix = _variant_short(variant)
    try:
        completed = _complete_level_map(level_map)
    except ValueError:
        completed = _uniform_level_map(DEFAULT_LEVEL)
    if _is_uniform_level_map(completed):
        level = completed.get("nutrition", DEFAULT_LEVEL)
        return f"{level.title()} {variant_letter} — {suffix} phrasing"
    parts = ", ".join(f"{pillar.title()} {completed[pillar].title()}" for pillar in PILLAR_KEYS)
    return f"Mixed {variant_letter} — {parts} ({suffix} phrasing)"

def resolve_scenario(scenario: str) -> tuple[Dict[str, str], Dict[str, str], str]:
    """Return (answers, per-pillar level map, variant) for the requested scenario key."""
    key = (scenario or "").strip().lower()
    if key in SCENARIOS:
        level, variant = _parse_level_variant(key)
        if level not in LEVELS:
            raise ValueError(f"Scenario '{scenario}' references unknown level '{level}'")
        return SCENARIOS[key], _uniform_level_map(level), variant
    mix = _parse_mix_scenario_key(key)
    if mix:
        levels_map, variant = mix
        answers = _scenario_answers_for_level_map(levels_map, variant)
        return answers, levels_map, variant
    raise ValueError(
        f"Unknown scenario '{scenario}'. Choose from: {', '.join(sorted(SCENARIOS.keys()))} "
        "or provide mix:<pillar=level,...>[|variant]"
    )

def consent_already_given(user: User) -> bool:
    """Return True if we can determine consent was already given, else False.
    Strategy:
      1) Look for latest AssessSession fields like `consent_given` or `consent_yes_at`.
      2) Fallback: scan recent MessageLog for an assistant message containing
         a known confirmation phrase (e.g., 'consent recorded').
    """
    try:
        with SessionLocal() as s:
            if AssessSession is not None:
                sess = (
                    s.query(AssessSession)
                     .filter(AssessSession.user_id == user.id)
                     .order_by(AssessSession.id.desc())
                     .first()
                )
                if sess is not None:
                    # Prefer explicit boolean/ts fields if present
                    if hasattr(sess, "consent_given") and getattr(sess, "consent_given"):
                        return True
                    if hasattr(sess, "consent_yes_at") and getattr(sess, "consent_yes_at") is not None:
                        return True
            if MessageLog is not None:
                logs = (
                    s.query(MessageLog)
                     .filter(MessageLog.user_id == user.id)
                     .order_by(MessageLog.id.desc())
                     .limit(50)
                     .all()
                )
                for m in logs:
                    txt = (getattr(m, "body", None) or getattr(m, "text", None) or "").lower()
                    direction = (getattr(m, "direction", None) or getattr(m, "role", None) or "").lower()
                    if direction in ("assistant", "outbound") and (
                        "consent recorded" in txt or "consent confirmed" in txt or "thank you — consent" in txt or "thank you - consent" in txt
                    ):
                        return True
    except Exception:
        # If anything goes wrong, assume not given (the script will send YES once)
        return False
    return False

# Helper to force consent flags (for mock mode and test loops)
def _mark_consent(user: User) -> None:
    """Force consent on latest AssessSession and/or on user to avoid looping when MOCK_OUTBOUND is used."""
    try:
        with SessionLocal() as s:
            # Flip user-level flag if present
            try:
                if hasattr(user, "consent_given") and not getattr(user, "consent_given"):
                    user.consent_given = True
                    setattr(user, "consent_at", getattr(user, "consent_at", None) or time.strftime("%Y-%m-%d %H:%M:%S"))
                    s.merge(user)
            except Exception:
                pass
            # Flip session-level consent on latest AssessSession
            if AssessSession is not None:
                sess = (
                    s.query(AssessSession)
                     .filter(AssessSession.user_id == user.id)
                     .order_by(AssessSession.id.desc())
                     .first()
                )
                if sess is not None:
                    if hasattr(sess, "consent_given"):
                        setattr(sess, "consent_given", True)
                    if hasattr(sess, "consent_yes_at") and getattr(sess, "consent_yes_at", None) is None:
                        setattr(sess, "consent_yes_at", time.strftime("%Y-%m-%d %H:%M:%S"))
                    s.add(sess)
            s.commit()
    except Exception:
        pass

def build_order() -> List[Tuple[str,str]]:
    """Create concept order matching the app's runtime question order.
    We keep the fixed pillar order and use per-pillar concept sequences observed in production prompts.
    """
    runtime_sequences = {
        # Nutrition prompt order observed in logs
        "nutrition": [
            "fruit_veg",
            "hydration",
            "processed_food",
            "protein_intake",
        ],
        # Training prompt order
        "training": [
            "cardio_frequency",
            "flexibility_mobility",
            "strength_training",
        ],
        # Resilience prompt order
        "resilience": [
            "emotional_regulation",
            "optimism_perspective",
            "positive_connection",
            "stress_recovery",
            "support_openness",
        ],
        # Recovery prompt order
        "recovery": [
            "bedtime_consistency",
            "sleep_duration",
            "sleep_quality",
        ],
    }

    order: List[Tuple[str, str]] = []
    for pillar_key in ("nutrition", "training", "resilience", "recovery"):
        desired = runtime_sequences.get(pillar_key, [])
        # Only include codes that actually exist in CONCEPTS, in desired order
        existing = set((CONCEPTS.get(pillar_key, {}) or {}).keys())
        for code in desired:
            if code in existing:
                order.append((pillar_key, code))
        # Fallback: append any remaining concepts (if seed added new ones) in their natural key order
        for code in (CONCEPTS.get(pillar_key, {}) or {}).keys():
            if code not in desired:
                order.append((pillar_key, code))
    return order

def get_or_create_user(
    scenario: str,
    level_map: Dict[str, str],
    variant: str,
    club_id: int | None = None,
    club_label: str | None = None,
) -> User:
    """
    Create (or fetch) a user whose name reflects the script/scenario.
    - first_name = scenario title-cased (e.g., 'Healthy')
    - surname    = compact scenario answers string
    - phone      = either stable per-scenario or unique per run based on env
    - club_id/club_label let batch mode pin scenarios to specific clubs
    """
    variant_key = (variant or "a").lower()[0]
    scenario_display = _scenario_display_name(level_map, variant_key)
    scenario_name = (
        scenario_display
        if not club_label
        else f"{scenario_display} ({club_label})"
    )
    scenario_name = _bounded_first_name(scenario_name)
    surname_value = _answers_surname_string_for_levels(level_map)
    unique_user = os.environ.get("UNIQUE_TEST_USER", "1") == "1"

    # Base: encode scenario into a short, stable suffix so each scenario can be reused.
    # If UNIQUE_TEST_USER=1, add a time-based suffix to force a new user each run.
    base_prefix = "+44771030"
    stable_suffix = abs(hash((scenario, club_id))) % 10000  # 4 digits stable per scenario+club
    phone = f"{base_prefix}{stable_suffix:04d}"

    if unique_user:
        # Use high-resolution timestamp + randomness to minimise collisions during fast batch loops.
        nonce = abs(hash((scenario, club_id, time.time_ns(), random.random()))) % 1_000_000
        phone = f"{base_prefix}{nonce:06d}"

    # Pick a default club for test users (avoids NOT NULL club_id errors)
    env_club_id = os.environ.get("TEST_CLUB_ID") or os.environ.get("CLUB_ID")
    default_club_id: int | None = (
        int(env_club_id) if env_club_id and env_club_id.isdigit() else None
    )

    with SessionLocal() as s:
        # Ensure the phone slot is unused when forcing unique users
        if unique_user:
            attempts = 0
            while True:
                existing_phone = (
                    s.query(User.id)
                     .filter(User.phone == phone)
                     .first()
                )
                if not existing_phone:
                    break
                attempts += 1
                nonce = abs(hash((scenario, club_id, time.time_ns(), random.random(), attempts))) % 1_000_000
                phone = f"{base_prefix}{nonce:06d}"
        print(
            "[user] scenario='{scenario}' name={name} phone={phone} unique_user={uniq} club_id={club}".format(
                scenario=scenario,
                name=scenario_name,
                phone=phone,
                uniq=unique_user,
                club=club_id,
            )
        )
        # Resolve a default club id if not provided via env
        nonlocal_club_id = club_id if club_id is not None else default_club_id
        if nonlocal_club_id is None:
            try:
                club_row = s.query(Club).order_by(Club.id.asc()).first()
                if club_row is not None:
                    nonlocal_club_id = getattr(club_row, "id", None)
            except Exception:
                nonlocal_club_id = None
        # Try match by first_name (+club when available) so we reuse scenario+club combinations when UNIQUE_TEST_USER=0
        query = s.query(User).filter(User.first_name == scenario_name)
        if nonlocal_club_id is not None:
            query = query.filter(User.club_id == nonlocal_club_id)
        user = query.one_or_none()
        if not user:
            # Fallback: try phone match (in case of prior runs)
            phone_query = s.query(User).filter(User.phone == phone)
            if nonlocal_club_id is not None:
                phone_query = phone_query.filter(User.club_id == nonlocal_club_id)
            user = phone_query.one_or_none()

        if not user:
            user = User(
                club_id=nonlocal_club_id,
                first_name=scenario_name,
                surname=surname_value,
                phone=phone,
                is_superuser=False,
            )
            s.add(user); s.commit(); s.refresh(user)
            print(f"[user] created id={getattr(user, 'id', None)} for scenario='{scenario}'")
        else:
            # Ensure the name reflects the scenario even if the record existed with older values
            changed = False
            # Backfill/align club_id
            if nonlocal_club_id is not None and getattr(user, "club_id", None) != nonlocal_club_id:
                user.club_id = nonlocal_club_id
                changed = True
            if getattr(user, "first_name", None) != scenario_name:
                user.first_name = scenario_name; changed = True
            desired_surname = surname_value
            if getattr(user, "surname", None) != desired_surname:
                user.surname = desired_surname; changed = True
            if changed:
                s.commit()
        return user

def main():
    parser = argparse.ArgumentParser(description="Run assessment scenarios (in-process).")
    parser.add_argument("scenario", nargs="?", help="Scenario key (e.g., novice_a). Use --batch to run all.")
    parser.add_argument("--batch", action="store_true", help="Run all scenarios in sequence.")
    parser.add_argument("--sleep", type=float, default=2.0, help="Seconds to sleep between scenarios in batch.")
    parser.add_argument("--unique", dest="unique", action="store_true", help="Force unique user per run (UNIQUE_TEST_USER=1).")
    parser.add_argument("--reuse", dest="unique", action="store_false", help="Reuse same user per scenario (UNIQUE_TEST_USER=0).")
    parser.add_argument("--admin-summary", action="store_true",
                        help="Generate the Admin summary report via app.reporting and exit (no WhatsApp run).")
    parser.add_argument("--admin-summary-args", default="",
                        help="Optional extra args for admin summary (reserved: e.g., 'tenant=1').")
    parser.add_argument("--start-from", default="", help="When --batch is set, start from this scenario key (e.g., developing_b)")
    parser.add_argument("--club-ids", default=os.environ.get("BATCH_CLUB_IDS", ""),
                        help="Comma/semicolon separated club IDs to cycle through (batch defaults to first two).")
    parser.add_argument("--call-timeout", type=float, default=45.0, help="Seconds to wait for each LLM/assessor call before skipping")
    parser.set_defaults(unique=True)
    args = parser.parse_args()

    requested_club_ids = _parse_club_ids(args.club_ids)
    needs_club_cycle = bool(requested_club_ids) or args.batch
    min_clubs = 2 if args.batch else 1
    club_cycle = (
        _resolve_club_cycle(requested_club_ids, min_count=min_clubs)
        if needs_club_cycle
        else [(None, None)]
    )
    if club_cycle and (len(club_cycle) > 1 or (club_cycle[0][0] is not None and needs_club_cycle)):
        summary = ", ".join(
            f"{cid}:{label}" if cid is not None else str(label)
            for cid, label in club_cycle
        )
        print(f"[club] cycling users across -> {summary}")

    # expose UNIQUE_TEST_USER behaviour to current process
    os.environ["UNIQUE_TEST_USER"] = "1" if args.unique else "0"

    # Ensure seed (bounds/questions/snippets) is current
    run_seed()

    # Early exit for admin summary report
    if args.admin_summary:
        if _reporting is None:
            print("[admin-summary] reporting module not available")
            return
        try:
            # Try common entry points in order of likelihood
            fn = None
            for cand in (
                "generate_admin_summary_report",
                "generate_summary_report_admin",
                "generate_summary_report",
            ):
                if hasattr(_reporting, cand):
                    fn = getattr(_reporting, cand)
                    break
            if fn is None:
                print("[admin-summary] no suitable summary function found in app.reporting")
                return
            # Best-effort: call without args; if it requires params, catch and print error
            try:
                out = fn()  # type: ignore[misc]
                print(f"[admin-summary] completed -> {out}")
            except TypeError:
                # Retry with known optional patterns (tenant-wide or default paths)
                out = fn(tenant_id=getattr(os.environ, "TENANT_ID", None))  # type: ignore[misc]
                print(f"[admin-summary] completed (tenant) -> {out}")
        except Exception as e:
            print(f"[admin-summary] error: {e}")
        return

    def run_one(scenario: str, club_choice: tuple[int | None, str | None] = (None, None)):
        club_id, club_label = club_choice
        try:
            answers, level_map, variant = resolve_scenario(scenario)
        except ValueError as exc:
            print(exc)
            sys.exit(2)
        order = build_order()
        user = get_or_create_user(
            scenario,
            level_map,
            variant,
            club_id=club_id,
            club_label=club_label,
        )

        # Start session
        try:
            session = start_combined_assessment(user=user)
            session_id = getattr(session, "id", None)
            if session_id is None:
                session_id = _latest_session_id_for(user)
            print(f"[session] id={session_id}")
            time.sleep(0.5)
            sid_boot = _latest_session_id_for(user)
            print(f"[session] after-start lookup id={sid_boot}")
            _debug_list_sessions_for(user)
            if session_id is None:
                print("[warn] start_combined_assessment returned no session id; will rely on DB to attach run after consent.")
            time.sleep(0.3)
        except Exception as e:
            print(f"[warn] Unable to start new assessment session automatically: {e}")
            session_id = _latest_session_id_for(user)
            print(f"[session] (fallback) id={session_id}")

        started = False
        club_desc = club_label or (f"id={club_id}" if club_id is not None else "")
        if club_desc:
            print(f"[run] scenario={scenario} club={club_desc}")
        else:
            print(f"[run] scenario={scenario}")
        for idx, (pillar, code) in enumerate(order, 1):
            msg = answers.get(code)
            if not started:
                if session_id is None:
                    start_combined_assessment(user=user)
                _continue_with_timeout(user=user, text="YES", timeout_s=args.call_timeout)
                _mark_consent(user)
                sid = _latest_session_id_for(user)
                if sid is not None:
                    print(f"[session] active id={sid}")
                time.sleep(0.5)
                sid2 = _latest_session_id_for(user)
                print(f"[session] post-consent lookup id={sid2}")
                _debug_list_sessions_for(user)
                if session_id is None:
                    session_id = _latest_session_id_for(user)
                started = True
                time.sleep(0.3)
            if msg is None:
                print(f"[skip] {pillar}.{code}: no scenario answer configured")
                continue
            ok = _continue_with_timeout(user=user, text=msg, timeout_s=args.call_timeout)
            status = "ok" if ok else "warn"
            print(f"{idx:02d}. {pillar}.{code:<22} -> '{msg}' [{status}]")
            time.sleep(0.25)

        # finalize
        _finalize_run(user)
        got_final = _wait_for_completion_message(user, timeout_s=8.0, poll_s=0.5)
        print(f"[finalize] completion_seen={got_final}")
        if not got_final:
            _continue_with_timeout(user=user, text="", timeout_s=args.call_timeout)
            time.sleep(0.75)
            got_final = _wait_for_completion_message(user, timeout_s=5.0, poll_s=0.5)
            print(f"[finalize] retry completion_seen={got_final}")

        sid_final = _latest_session_id_for(user)
        print(f"[summary] latest run id={sid_final}")
        _debug_list_sessions_for(user)
        # Print quick scores snapshot if models are present
        if AssessmentRun is not None and PillarResult is not None:
            try:
                with SessionLocal() as s:
                    run = (
                        s.query(AssessmentRun)
                         .filter(AssessmentRun.user_id == user.id)
                         .order_by(AssessmentRun.id.desc())
                         .first()
                    )
                    if run is not None:
                        pr_fk_col = getattr(PillarResult, 'assessment_run_id', None) or getattr(PillarResult, 'run_id', None)
                        if pr_fk_col is not None:
                            pr = (
                                s.query(PillarResult)
                                 .filter(pr_fk_col == getattr(run, 'id', None))
                                 .order_by(PillarResult.id.asc())
                                 .all()
                            )
                        else:
                            pr = (
                                s.query(PillarResult)
                                 .filter(PillarResult.user_id == user.id)
                                 .order_by(PillarResult.id.asc())
                                 .all()
                            )
                        # Be tolerant to schema drift: overall score may be stored under different names
                        def _first_attr(obj, names: list[str]):
                            for n in names:
                                if hasattr(obj, n):
                                    v = getattr(obj, n)
                                    if v is not None:
                                        return v
                            return None

                        overall = _first_attr(run, ['overall_score', 'score', 'combined_score', 'combined'])
                        print("[scores] overall=", overall)
                        for row in pr:
                            pillar_name = _first_attr(row, ['pillar_key', 'pillar', 'name'])
                            pillar_score = _first_attr(row, ['score', 'overall', 'value', 'total'])
                            print(f"   - {pillar_name}: {pillar_score}")
            except Exception as _e:
                print(f"[scores] error: {_e}")
        print("[done] scenario complete.")

    if args.batch:
        all_names = list(DEFAULT_BATCH_SCENARIOS)
        if args.start_from:
            key = args.start_from.strip().lower()
            try:
                start_idx = all_names.index(key)
                all_names = all_names[start_idx:]
            except ValueError:
                print(f"[batch] --start-from not found: {key}. Available: {', '.join(all_names)}")
                return
        print(f"[batch] running {len(all_names)} scenarios: {', '.join(all_names)}")
        for i, name in enumerate(all_names, 1):
            club_choice = club_cycle[(i - 1) % len(club_cycle)] if club_cycle else (None, None)
            club_desc = club_choice[1] or (f"id={club_choice[0]}" if club_choice[0] is not None else "")
            if club_desc:
                print(f"\n[batch] {i}/{len(all_names)} -> {name} [club={club_desc}]")
            else:
                print(f"\n[batch] {i}/{len(all_names)} -> {name}")
            run_one(name, club_choice)
            if i < len(all_names):
                time.sleep(max(0.0, args.sleep))
        return

    # single scenario
    scenario = (args.scenario or "competent_a").lower()
    solo_choice = club_cycle[0] if club_cycle else (None, None)
    run_one(scenario, solo_choice)

if __name__ == "__main__":
    main()
