#!/usr/bin/env python3
"""
Run standardised assessment scenarios *in-process* (no HTTP).
The scenario name is also used as the test user's name (e.g., 'Healthy Script').
Usage:
  python scripts/run_assessment_scenarios.py healthy
  python scripts/run_assessment_scenarios.py average
  python scripts/run_assessment_scenarios.py poor
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

# --- import your app bits ---
from app.seed import run_seed, CONCEPTS
from app.db import SessionLocal
from app.models import User
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
    return

# Wait for final completion message in MessageLog (best-effort)
def _wait_for_completion_message(user: "User", timeout_s: float = 10.0, poll_s: float = 0.5) -> bool:
    if MessageLog is None:
        time.sleep(min(timeout_s, 1.0))
        return False
    started = time.time()
    target_snippets = (
        "assessment complete",
        "reports:",
        "pdf written to",
    )
    with SessionLocal() as s:
        last_seen_id = None
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
        continue_combined_assessment(user=user, user_text="")
        time.sleep(0.5)
        continue_combined_assessment(user=user, user_text=" ")
    except Exception:
        pass

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

def _scenario_answers_for(level: str, variant: str) -> Dict[str, str]:
    """Create a dict of concept_code -> phrased answer for the level, varied by variant key."""
    nums = LEVELS[level]
    out: Dict[str,str] = {}
    for pillar, code in ALL_CONCEPTS:
        val = nums[pillar][code]
        out[code] = phrase_value(code, val, seed_hint=f"{level}:{variant}:{code}")
    return out

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

# --- encode scenario answers into surname (ultra‑compact string) ---
# Keep under Postgres users.surname varchar(120) (observed in terminal).
MAX_SURNAME_LEN = 118  # leave room for an ellipsis if needed

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

def _answers_surname_string(scenario: str) -> str:
    """Compact single-line string of the scenario's baseline answers by level.
    Format: "fv=3pd|hy=2.5L|pf=2pd|pr=3pd|ca=3d|fm=3d|st=2s|er=4d|op=4d|pc=4d|sr=4d|so=4d|bc=4d|sd=4d|sq=4d"
    Always <= MAX_SURNAME_LEN.
    """
    level, _variant = _parse_level_variant(scenario)
    if level not in LEVELS:
        return ""
    nums = LEVELS[level]
    parts: list[str] = []
    for pillar, code in build_order():
        if code not in nums.get(pillar, {}):
            continue
        key = _SHORT_KEYS.get((pillar, code), code[:2])
        val = float(nums[pillar][code])
        parts.append(f"{key}={_format_compact_value(pillar, code, val)}")
    s = "|".join(parts)  # no spaces, no pipes inside values
    return s if len(s) <= MAX_SURNAME_LEN else (s[:MAX_SURNAME_LEN-1] + "…")

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

def get_or_create_user(scenario: str) -> User:
    """
    Create (or fetch) a user whose name reflects the script/scenario.
    - first_name = scenario title-cased (e.g., 'Healthy')
    - surname    = compact scenario answers string
    - phone      = either stable per-scenario or unique per run based on env
    """
    level_key, variant_key = _parse_level_variant(scenario)
    scenario_name = f"{level_key.title()} {variant_key.upper()} — {_variant_short(variant_key)} phrasing"
    unique_user = os.environ.get("UNIQUE_TEST_USER", "1") == "1"

    # Base: encode scenario into a short, stable suffix so each scenario can be reused.
    # If UNIQUE_TEST_USER=1, add a time-based suffix to force a new user each run.
    base_prefix = "+44771030"
    stable_suffix = abs(hash(scenario)) % 10000  # 4 digits stable per scenario
    phone = f"{base_prefix}{stable_suffix:04d}"

    if unique_user:
        # Time-based 3-digit suffix to ensure uniqueness for repeated runs
        phone = f"{base_prefix}{int(time.time()) % 1000:03d}"

    print(f"[user] scenario='{scenario}' name={scenario_name} phone={phone} unique_user={unique_user}")

    with SessionLocal() as s:
        # Try match by first_name only so we reuse the same user for the scenario when UNIQUE_TEST_USER=0
        user = (
            s.query(User)
             .filter(User.first_name == scenario_name)
             .one_or_none()
        )
        if not user:
            # Fallback: try phone match (in case of prior runs)
            user = s.query(User).filter(User.phone == phone).one_or_none()

        if not user:
            user = User(
                first_name=scenario_name,
                surname=_answers_surname_string(scenario),
                phone=phone,
                is_superuser=False,
            )
            s.add(user); s.commit(); s.refresh(user)
            print(f"[user] created id={getattr(user, 'id', None)} for scenario='{scenario}'")
        else:
            # Ensure the name reflects the scenario even if the record existed with older values
            changed = False
            if getattr(user, "first_name", None) != scenario_name:
                user.first_name = scenario_name; changed = True
            desired_surname = _answers_surname_string(scenario)
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
    parser.set_defaults(unique=True)
    args = parser.parse_args()

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

    def run_one(scenario: str):
        if scenario not in SCENARIOS:
            print(f"Unknown scenario '{scenario}'. Choose from: {', '.join(sorted(SCENARIOS.keys()))}")
            sys.exit(2)
        order = build_order()
        answers = SCENARIOS[scenario]
        user = get_or_create_user(scenario)

        # Start session
        try:
            session = start_combined_assessment(user=user)
            session_id = getattr(session, "id", None)
            if session_id is None:
                session_id = _latest_session_id_for(user)
            time.sleep(0.5)
            sid_boot = _latest_session_id_for(user)
            _debug_list_sessions_for(user)
            if session_id is None:
                print("[warn] start_combined_assessment returned no session id; will rely on DB to attach run after consent.")
            time.sleep(0.3)
        except Exception as e:
            print(f"[warn] Unable to start new assessment session automatically: {e}")
            session_id = _latest_session_id_for(user)

        started = False
        print(f"[run] scenario={scenario}")
        for idx, (pillar, code) in enumerate(order, 1):
            msg = answers.get(code)
            if not started:
                if session_id is None:
                    start_combined_assessment(user=user)
                continue_combined_assessment(user=user, user_text="YES")
                sid = _latest_session_id_for(user)
                time.sleep(0.5)
                sid2 = _latest_session_id_for(user)
                _debug_list_sessions_for(user)
                if session_id is None:
                    session_id = _latest_session_id_for(user)
                started = True
                time.sleep(0.3)
            if msg is None:
                print(f"[skip] {pillar}.{code}: no scenario answer configured")
                continue
            ok = continue_combined_assessment(user=user, user_text=msg)
            status = "ok" if ok else "warn"
            print(f"{idx:02d}. {pillar}.{code:<22} -> '{msg}' [{status}]")
            time.sleep(0.25)

        # finalize
        _finalize_run(user)
        got_final = _wait_for_completion_message(user, timeout_s=8.0, poll_s=0.5)
        print(f"[finalize] completion_seen={got_final}")
        if not got_final:
            continue_combined_assessment(user=user, user_text="")
            time.sleep(0.75)
            got_final = _wait_for_completion_message(user, timeout_s=5.0, poll_s=0.5)
            print(f"[finalize] retry completion_seen={got_final}")

        sid_final = _latest_session_id_for(user)
        print(f"[summary] latest run id={sid_final}")
        _debug_list_sessions_for(user)
        print("[done] scenario complete.")

    if args.batch:
        all_names = sorted(SCENARIOS.keys())
        print(f"[batch] running {len(all_names)} scenarios: {', '.join(all_names)}")
        for i, name in enumerate(all_names, 1):
            print(f"\n[batch] {i}/{len(all_names)} -> {name}")
            run_one(name)
            if i < len(all_names):
                time.sleep(max(0.0, args.sleep))
        return

    # single scenario
    scenario = (args.scenario or "competent_a").lower()
    run_one(scenario)

if __name__ == "__main__":
    main()
