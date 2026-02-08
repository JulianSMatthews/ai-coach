# ==============================================================================
# app/okr.py
# ------------------------------------------------------------------------------
# PURPOSE:
#   1) Generate presentable OKR text (LLM + deterministic fallback).
#   2) Persist OKRs at pillar completion:
#      - Ensure/create quarter in okr_cycles
#      - Upsert pillar-level objective in okr_objectives (linked to user, session, pillar result)
#      - Upsert child KRs in okr_key_results (+ optional entries in okr_kr_entries)
#      - Recompute objective.overall_score from KR scores (weighted)
#
# INTEGRATION:
#   • Call sync_okrs_for_completed_pillar(...) at the end of a pillar assessment.
#   • Optionally call make_quarterly_okr_llm(...) to get the text block to display.
#
# CREATED: 2025-10-24
# AUTHOR:  HealthSense / CoachSense Development Team
# ==============================================================================

from __future__ import annotations
from typing import Dict, Optional, List, Any
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from calendar import monthrange
import os
import json

# --- Needed for new state context helper ---
from sqlalchemy.sql import text as _sql_text
from app.db import SessionLocal
from app.debug_utils import debug_log
from app.models import UserConceptState, Concept, PillarResult, JobAudit, UserPreference, AssessSession
from . import psych

PILLAR_PREF_KEYS = {
    "training": "training_focus",
}

# --- KR key slug helper (cap to VARCHAR(32)) ---------------------------------
import re, hashlib

def _slug32(text: str, max_len: int = 32) -> str:
    """Lowercase slug [a-z0-9_-], collapse repeats, and hard-cap length.
    If truncated, append _ + 6-char md5 to keep total <= max_len.
    """
    base = re.sub(r"[^a-z0-9_-]+", "_", (text or "").strip().lower())
    base = re.sub(r"_+", "_", base).strip("_")
    if len(base) <= max_len:
        return base
    h = hashlib.md5(base.encode("utf-8")).hexdigest()[:6]
    keep = max_len - 1 - 6
    return f"{base[:keep]}_{h}"

def _normalize_concept_key(text: str | None) -> str:
    if not text:
        return ""
    import re
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    return slug.strip("_")

# --- OpenAI client (optional) -------------------------------------------------
try:
    from openai import OpenAI  # openai>=1.0
    _client = OpenAI()
except Exception:
    _client = None

DEFAULT_OKR_MODEL   = os.getenv("LLM_MODEL") or "gpt-5.1"
DEFAULT_OKR_QUARTER = os.getenv("OKR_QUARTER_LABEL", "This Quarter")


# Pure-LLM OKR mode (no scaffolding, no clamps, no fallback)
OKR_RAW_FROM_LLM = os.getenv("OKR_RAW_FROM_LLM", "0") == "1"
# Explicit override for raw mode (takes precedence if set)
OKR_FORCE_RAW = os.getenv("OKR_FORCE_RAW", "0") == "1"

SYSTEM_MSG = (
    "You are a health coach that writes quarterly OKRs from pillar assessments. "
    "Use the overall pillar score only as context for priority, but DO NOT set a key result that targets the pillar score itself. "
    "Review individual concept scores to identify the main gaps that, if improved, will raise the pillar. "
    "Write ONE objective that focuses on those gap concepts, and 2–3 Key Results that are measurable in user-recognisable units. "
    "Key Results must use concrete units such as: portions per day, litres per day, sessions per week, days per week, nights per week, or percent. "
    "Each KR should be a small, safe step from the baseline toward a sensible guideline cap; prefer weekly cadence. "
    "Output only the OKR block, no extra commentary."
)

def _baseline_debug(reason: str, detail: dict | None = None) -> None:
    debug_log(reason, detail or {}, tag="okr")


def _okr_audit(job: str, *, status: str = "ok", payload: dict | None = None, error: str | None = None) -> None:
    debug_log(f"{job} status={status}", {"payload": payload or {}, "error": error}, tag="okr")


def _fallback_okr(pillar_slug: str, pillar_score: float | None) -> str:
    """Deterministic OKR in case the LLM call fails or client is unavailable."""
    obj = {
        "nutrition":  "Improve daily nutrition habits",
        "training":   "Improve training consistency and quality",
        "resilience": "Strengthen stress recovery and emotional regulation",
        "recovery":   "Upgrade sleep and day-to-day recovery routines",
    }.get(pillar_slug, "Improve key behaviours for this pillar")
    return (
        f"🧭 {DEFAULT_OKR_QUARTER} Objective: {obj}\n"
        "Key Results:\n"
        "1) Complete 3 small health habits each week for 12 weeks\n"
        "2) Plan your week every Sunday and tick off at least 10 planned actions across the week\n"
        f"3) Keep one written note per week on what helped or hindered progress in {pillar_slug.title()}"
    )

def make_quarterly_okr_llm(
    pillar_slug: str,
    pillar_score: float | None,
    concept_scores: Dict[str, float] | None = None,
    *,
    model: Optional[str] = None,
    temperature: float = 0.3,
    quarter_label: Optional[str] = None,
) -> str:
    """
    Returns a formatted OKR block string ("🧭 <Quarter> Objective: ...\nKey Results:\n1) ...")
    using the LLM if available, otherwise a deterministic fallback.
    """
    mdl    = model or DEFAULT_OKR_MODEL
    qlabel = quarter_label or DEFAULT_OKR_QUARTER
    concept_scores = concept_scores or {}

    user_msg = {
        "role": "user",
        "content": (
            f"Write a concise quarterly OKR for the pillar '{pillar_slug}'.\n"
            f"- Pillar score: {pillar_score}\n"
            f"- Concept scores: {concept_scores}\n"
            f"- Use the label: {qlabel}\n"
            "- ONE Objective only.\n"
            "- 2 or 3 Key Results. Each KR must be measurable (numbers or %), weekly cadence preferred.\n"
            "- No extra commentary.\n\n"
            "Format exactly:\n"
            "🧭 {quarter} Objective: <objective>\n"
            "Key Results:\n"
            "1) <KR1>\n"
            "2) <KR2>\n"
            "3) <KR3>  # omit if only 2\n"
        ),
    }

    if not _client:
        return _fallback_okr(pillar_slug, pillar_score)

    try:
        resp = _client.chat.completions.create(
            model=mdl,
            temperature=temperature,
            messages=[
                {"role": "system", "content": SYSTEM_MSG},
                user_msg,
            ],
        )
        txt = (resp.choices[0].message.content or "").strip()
        if txt.startswith("🧭 ") and qlabel != "This Quarter":
            txt = txt.replace("🧭 This Quarter", f"🧭 {qlabel}")
        return txt or _fallback_okr(pillar_slug, pillar_score)
    except Exception:
        return _fallback_okr(pillar_slug, pillar_score)



STRUCTURED_OKR_SYSTEM = (
    "You produce STRICT JSON for a quarterly OKR derived from a single health pillar. "
    "Return an object with keys: objective (string), krs (array of 2-3 items). "
    "Each KR item MUST include: kr_key (snake_case, <=32 chars), description (short label), unit (full unit label), "
    "baseline_num (number or null), target_num (number or null), metric_label (string or null), score (number or null). "
    "OPTIONAL: concept_key (string identifying the underlying concept, e.g. 'nutrition.fruit_veg'). "
    "JSON only — no prose."
)

# Raw system prompt: removes all constraints and scaffolding language
STRUCTURED_OKR_SYSTEM_RAW = (
    "You produce STRICT JSON for a quarterly OKR derived from a single health pillar. "
    "Return an object with keys: objective (string), krs (array of 2-5 items). "
    "Each KR item MUST include: kr_key (snake_case, <=32 chars), description (short label), unit (free text), "
    "baseline_num (number or null), target_num (number or null), metric_label (string or null), score (number or null). "
    "OPTIONAL: concept_key (string such as 'nutrition.fruit_veg'). "
    "Do not include any prose, markdown or comments outside the JSON."
)

# Practical coaching variant: push the model toward concrete, weekly habits using per-concept guidance
PRACTICAL_OKR_SYSTEM = (
    "You are a pragmatic health coach helping people translate assessment scores into weekly habits. "
    "Return STRICT JSON with keys: objective (string), krs (array of 1–3 items). "
    "Each KR MUST be an observable behavior the user can perform weekly/daily, expressed in real-world units: "
    "sessions/week, days/week, nights/week, portions/day, litres/day, or percent. "
    "Use the provided behavior_context (labels, units, direction) to decide what to increase, maintain, or reduce. "
    "Skip any KR that would simply 'maintain' the current habit; only include behaviors that need to change versus the reported answers."
    "Forbidden terms in KR text: 'score', 'adherence', 'priority action(s)'. "
    "Prefer small, realistic progressions and specific habits (e.g., add a veg portion at lunch, 10‑min mobility after training, 2L water/day). "
    "Return JSON only. Within text fields, write plain-English habit descriptions."
)
_FORBIDDEN_TERMS = ("score", "adherence", "priority action")

def _sanitize_kr_phrasing(pillar_slug: str, data: dict) -> None:
    """
    If any KR description contains forbidden boilerplate terms, nudge it toward a habit phrasing.
    This is text-only; it does not alter numeric targets/units.
    """
    guide = _GUIDE.get(pillar_slug, {})
    for i, kr in enumerate(list(data.get("krs", []))):
        desc = (kr.get("description") or "").strip()
        if not desc:
            continue
        low = desc.lower()
        if any(t in low for t in _FORBIDDEN_TERMS) or "priority actions" in low:
            # Try to map to a known label/unit if available
            unit = kr.get("unit") or ""
            label = None
            # best effort: use metric_label, else pick first guide label
            label = (kr.get("metric_label") or "").strip() or None
            if not label and guide:
                try:
                    first_key = next(iter(guide))
                    label = guide[first_key].get("label") or first_key.replace("_"," ")
                    unit = unit or guide[first_key].get("unit") or unit
                except Exception:
                    pass
            label = label or "target habit"
            # rewrite phrasing into a habit statement while keeping units
            unit_suffix = f" ({unit})" if unit else ""
            data["krs"][i]["description"] = f"Commit to the target habit each week: {label}{unit_suffix}"

def _infer_unit_from_text(desc: str) -> str | None:
    if not desc:
        return None
    text = desc.lower()
    hints = {
        "hours/night": "hours/night",
        "hours per night": "hours/night",
        "nights/week": "nights/week",
        "nights per week": "nights/week",
        "sessions/week": "sessions/week",
        "sessions per week": "sessions/week",
        "days/week": "days/week",
        "days per week": "days/week",
        "per week": "per week",
        "portions/day": "portions/day",
        "portions per day": "portions/day",
        "l/day": "L/day",
        "litres per day": "L/day",
        "%": "%",
        "percent": "%",
    }
    for hint, unit in hints.items():
        if hint in text:
            return unit
    return None

_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}


def _infer_numbers_from_text(desc: str) -> list[float]:
    if not desc:
        return []
    matches = re.findall(r"\d+(?:\.\d+)?", desc)
    numbers = [float(m) for m in matches]
    if numbers:
        return numbers
    words = re.findall(r"[a-z]+", desc.lower())
    for w in words:
        if w in _NUMBER_WORDS:
            numbers.append(float(_NUMBER_WORDS[w]))
    return numbers

def _normalize_phrase(text: str | None) -> str:
    if not text:
        return ""
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _guess_concept_from_description(pillar_slug: str, desc: str) -> str | None:
    if not desc:
        return None
    text = _normalize_phrase(desc)
    for key, meta in (_GUIDE.get(pillar_slug, {}) or {}).items():
        label = _normalize_phrase(meta.get("label"))
        if label and label in text:
            return key
        slug = _normalize_phrase(key.replace("_", " "))
        if slug and slug in text:
            return key
    return None

def _enrich_kr_defaults(pillar_slug: str, kr: dict, concept_scores: dict[str, float], state_answers: dict[str, float]) -> dict:
    guide = _GUIDE.get(pillar_slug, {})
    concept_key = _normalize_concept_key((kr.get("concept_key") or "").split(".")[-1]) or _guess_concept_from_description(pillar_slug, kr.get("description", ""))
    meta = guide.get(concept_key)
    if meta:
        kr.setdefault("metric_label", meta.get("label"))
        kr.setdefault("unit", meta.get("unit"))
    if kr.get("unit") is None:
        inferred_unit = _infer_unit_from_text(kr.get("description", ""))
        if inferred_unit:
            kr["unit"] = inferred_unit
    if kr.get("metric_label") is None and kr.get("unit"):
        kr["metric_label"] = kr["unit"]

    text = kr.get("description", "") or ""
    numbers = _infer_numbers_from_text(text)
    unit = kr.get("unit") or ""
    unit_nums: list[float] = []
    if unit:
        pattern = re.escape(unit)
        matches = re.findall(r"(\d+(?:\.\d+)?)\s*" + pattern, text)
        unit_nums = [float(m) for m in matches]
    nums = unit_nums or numbers
    lower_text = text.lower()

    if kr.get("target_num") is None and nums:
        kr["target_num"] = nums[-1]

    if kr.get("baseline_num") is None:
        # Highest priority: numeric answer we captured from the assessment dialogue
        state_val = state_answers.get(concept_key) if concept_key else None
        if state_val is not None:
            kr["baseline_num"] = state_val
            kr["_baseline_source"] = "state"
            _baseline_debug("baseline_from_state", {"concept": concept_key, "value": state_val})
        # Next: concept score map (normalized 0-100) — only if present and numeric
        elif concept_key and concept_key in concept_scores and concept_scores[concept_key] is not None:
            try:
                kr["baseline_num"] = float(concept_scores[concept_key])
                kr["_baseline_source"] = "concept_score"
                _baseline_debug("baseline_from_concept_score", {"concept": concept_key, "value": kr["baseline_num"]})
            except Exception as exc:
                _baseline_debug("concept_score_cast_failed", {"concept": concept_key, "value": concept_scores.get(concept_key), "err": str(exc)})
                pass
        # Next: if description has multiple numbers, take the first as baseline
        elif len(nums) > 1:
            kr["baseline_num"] = nums[0]
            kr["_baseline_source"] = "text_first"
            _baseline_debug("baseline_from_text_first", {"concept": concept_key, "value": kr["baseline_num"], "text": text})
        # Next: any single number found
        elif numbers:
            kr["baseline_num"] = numbers[0]
            kr["_baseline_source"] = "text_any"
            _baseline_debug("baseline_from_text_any", {"concept": concept_key, "value": kr["baseline_num"], "text": text})
        else:
            kr["baseline_num"] = 0
            kr["_baseline_source"] = "default_zero"
            _baseline_debug("baseline_not_found_default_zero", {"concept": concept_key, "description": text})

    if kr.get("target_num") is None and kr.get("baseline_num") is not None:
        direction = (meta or {}).get("low", "increase")
        delta = 1
        base = float(kr["baseline_num"])
        kr["target_num"] = max(0, base - delta) if direction == "reduce" else base + delta

    if kr.get("actual_num") is None:
        if concept_key and concept_key in state_answers:
            kr["actual_num"] = state_answers[concept_key]
        else:
            kr["actual_num"] = kr.get("baseline_num")

    if not kr.get("concept_key") and concept_key:
        kr["concept_key"] = concept_key

    return kr

# Minimal guidance per pillar → concept (label, default unit, preferred direction when score is high/low)
_GUIDE: dict[str, dict[str, dict[str, str]]] = {
    "nutrition": {
        "fruit_veg":      {"label": "fruit & vegetable portions", "unit": "portions/day", "low": "increase", "high": "maintain"},
        "hydration":      {"label": "daily hydration",            "unit": "L/day",        "low": "increase", "high": "maintain"},
        "processed_food": {"label": "processed food intake",      "unit": "percent",      "low": "reduce",   "high": "reduce"},
        "protein_intake": {"label": "protein intake",             "unit": "g/day",        "low": "increase", "high": "maintain"},
    },
    "training": {
        "cardio_frequency":     {"label": "cardio sessions",           "unit": "sessions/week", "low": "increase", "high": "maintain"},
        "strength_training":    {"label": "strength sessions",         "unit": "sessions/week", "low": "increase", "high": "maintain"},
        "flexibility_mobility": {"label": "mobility/flexibility work", "unit": "sessions/week", "low": "increase", "high": "maintain"},
    },
    "resilience": {
        "emotional_regulation": {"label": "emotional regulation practice", "unit": "days/week", "low": "increase", "high": "maintain"},
        "optimism_perspective": {"label": "optimism/perspective drills",   "unit": "days/week", "low": "increase", "high": "maintain"},
        "stress_recovery":      {"label": "stress-recovery techniques",    "unit": "days/week", "low": "increase", "high": "maintain"},
        "positive_connection":  {"label": "positive connection actions",   "unit": "days/week", "low": "increase", "high": "maintain"},
        "support_openness":     {"label": "support/openness actions",      "unit": "days/week", "low": "increase", "high": "maintain"},
    },
    "recovery": {
        "bedtime_consistency": {"label": "consistent bedtimes", "unit": "nights/week", "low": "increase", "high": "maintain"},
        "sleep_duration":      {"label": "sleep duration",      "unit": "hours/night", "low": "increase", "high": "maintain"},
        "sleep_quality":       {"label": "sleep quality",       "unit": "percent",     "low": "increase", "high": "maintain"},
    },
}

def _behavior_context_block(pillar_slug: str, concept_scores: dict[str, float]) -> str:
    """
    Build a compact guidance block the LLM can use to pick practical KRs.
    For each concept: label, unit, and suggested direction (increase/maintain/reduce) derived from score bands.
    """
    guide = _GUIDE.get(pillar_slug, {})
    if not guide:
        return "behavior_context: []"
    lines = ["behavior_context: Each item below lists the key behaviors within this pillar. Use these to generate practical, habit-based Key Results."]
    for key, meta in guide.items():
        score = concept_scores.get(key)
        # simple bands: <70 low, 70-89 medium, >=90 high
        if score is None:
            direction = "increase" if meta.get("low") else "maintain"
            band = "unknown"
        else:
            if score < 70:
                direction, band = meta.get("low", "increase"), "low"
            elif score >= 90:
                direction, band = meta.get("high", "maintain"), "high"
            else:
                # medium band: small progression or maintain based on direction preference
                direction, band = ("increase" if meta.get("low") == "increase" else "maintain", "medium")
        label = meta.get("label", key)
        unit  = meta.get("unit", "")
        lines.append(
            f"- {key}: label='{label}', unit='{unit}', score={score}, band='{band}', direction='{direction}', "
            f"tip='Suggest realistic habits to {direction} this area (e.g., small weekly/daily actions using the given unit).'"
        )
    return "\n".join(lines)

def _fallback_structured_okr(pillar_slug: str, pillar_score: float | None):
    # Deterministic minimal structure if LLM unavailable.
    delta = 10 if (pillar_score or 0) < 50 else 5
    obj = {
        "nutrition":  "Improve daily nutrition habits",
        "training":   "Improve training consistency and quality",
        "resilience": "Strengthen stress recovery and emotional regulation",
        "recovery":   "Upgrade sleep and day-to-day recovery routines",
    }.get(pillar_slug, "Improve key behaviours for this pillar")
    return {
        "objective": obj,
        "krs": [
            {
                "kr_key": "KR1",
                "description": "Complete 3 priority actions per week",
                "metric_label": "Actions per week",
                "unit": "actions/week",
                "baseline_num": None,
                "target_num": 3,
                "score": None,
            },
            {
                "kr_key": "KR2",
                "description": "Maintain ≥85% adherence to plan",
                "metric_label": "Adherence",
                "unit": "%",
                "baseline_num": None,
                "target_num": 85,
                "score": None,
            },
            {
                "kr_key": "KR3",
                "description": f"Increase {pillar_slug} score by ~{delta}",
                "metric_label": "Pillar score delta",
                "unit": "points",
                "baseline_num": None,
                "target_num": delta,
                "score": None,
            },
        ],
    }

def _build_state_context_from_models(session: "Session", *, user_id: int, run_id: int | None, pillar_slug: str) -> list[dict]:
    """
    Pull rows from user_concept_state for the given user/run and pillar,
    joined to concepts to fetch bounds (zero_score → min, max_score → max).
    Returns: list of {concept, question, answer, unit, min_val, max_val}
    """
    rows_out: list[dict] = []
    try:
        q = (
            session.query(UserConceptState, Concept)
            .join(Concept, UserConceptState.concept_id == Concept.id)
            .filter(UserConceptState.user_id == user_id)
            .filter(Concept.pillar_key == pillar_slug)
        )
        if run_id is not None:
            q = q.filter(UserConceptState.run_id == run_id)
        q = q.order_by(UserConceptState.id.asc())
        for st, c in q.all():
            notes = getattr(st, "notes", {}) or {}
            parsed_val = None
            parsed_unit = ""
            if isinstance(notes, dict):
                pv = notes.get("parsed_value")
                if isinstance(pv, dict):
                    parsed_val = pv.get("value")
                    parsed_unit = pv.get("unit") or ""
            rows_out.append({
                "concept":   c.code or c.name,
                "concept_code": _normalize_concept_key(c.code) or _normalize_concept_key(c.name),
                "question":  st.question or "",
                "answer":    st.answer or "",
                "unit":      parsed_unit or "",
                "min_val":   c.zero_score,
                "max_val":   c.max_score,
                "value_num": parsed_val,
            })
        return rows_out
    except Exception:
        # Fallback raw SQL (tolerant to small naming differences)
        params = {"uid": user_id, "rid": run_id, "pillar": pillar_slug}
        sql = """
            SELECT c.pillar_key,
                   COALESCE(c.code, c.name)           AS concept_key,
                   COALESCE(ucs.question, '')         AS question_text,
                   COALESCE(ucs.answer, '')           AS answer_text,
                   COALESCE(c.zero_score, NULL)       AS min_val,
                   COALESCE(c.max_score,  NULL)       AS max_val,
                   ucs.notes                          AS notes_json
            FROM user_concept_state ucs
            JOIN concepts c ON ucs.concept_id = c.id
            WHERE ucs.user_id = :uid
              AND (:rid IS NULL OR ucs.run_id = :rid)
              AND c.pillar_key = :pillar
            ORDER BY ucs.id ASC
        """
        try:
            rs = session.execute(_sql_text(sql), params)
            for r in rs:
                concept_key = r["concept_key"] or (r["question_text"] or "")
                norm_code = _normalize_concept_key(concept_key)
                notes_obj = r["notes_json"]
                parsed_val = None
                parsed_unit = ""
                if isinstance(notes_obj, dict):
                    pv = notes_obj.get("parsed_value")
                elif isinstance(notes_obj, str) and notes_obj.strip():
                    try:
                        notes_dict = json.loads(notes_obj)
                        pv = notes_dict.get("parsed_value") if isinstance(notes_dict, dict) else None
                    except Exception:
                        pv = None
                else:
                    pv = None
                if isinstance(pv, dict):
                    parsed_val = pv.get("value")
                    parsed_unit = pv.get("unit") or ""

                rows_out.append({
                    "concept":  concept_key,
                    "concept_code": norm_code,
                    "question": r["question_text"] or "",
                    "answer":   r["answer_text"] or "",
                    "unit":     parsed_unit or "",
                    "min_val":  r["min_val"],
                    "max_val":  r["max_val"],
                    "value_num": parsed_val,
                })
        except Exception:
            pass
        return rows_out


def _answers_from_state_context(rows: list[dict]) -> dict[str, float]:
    out: dict[str, float] = {}
    for row in rows:
        concept = _normalize_concept_key(row.get("concept_code") or row.get("concept"))
        if not concept:
            _baseline_debug("missing_concept_code", row)
            continue
        val = row.get("value_num")
        if val is not None:
            try:
                out[concept] = float(val)
                continue
            except Exception as exc:
                _baseline_debug("value_num_cast_failed", {"concept": concept, "value": val, "err": str(exc)})
        ans = row.get("answer") or ""
        try:
            nums = _infer_numbers_from_text(ans)
            if nums:
                out[concept] = nums[-1]
            else:
                _baseline_debug("no_numeric_in_answer", {"concept": concept, "answer": ans})
        except Exception as exc:
            _baseline_debug("infer_numbers_error", {"concept": concept, "answer": ans, "err": str(exc)})
            continue
    return out

def make_structured_okr_llm(
    pillar_slug: str,
    pillar_score: float | None,
    concept_scores: Dict[str, float] | None = None,
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    qa_context: Optional[List[Dict[str, str]]] = None,
    state_context: Optional[List[Dict[str, str]]] = None,
    pillar_preference: Optional[str] = None,
    psych_profile: Optional[dict] = None,
) -> Dict[str, Any]:
    """
    Returns a dict:
      { "objective": str, "krs": [ {kr_key, description, metric_label, unit, baseline_num, target_num, score}, ... ] }
    In RAW mode (OKR_RAW_FROM_LLM=1), there is NO fallback or numeric scaffolding — errors will raise.
    """
    concept_scores = concept_scores or {}
    mdl = model or DEFAULT_OKR_MODEL
    if not _client:
        if OKR_RAW_FROM_LLM:
            raise RuntimeError("LLM client unavailable and OKR_RAW_FROM_LLM=1 (no fallback).")
        return _fallback_structured_okr(pillar_slug, pillar_score)

    # Build behavior context (kept) + Q&A from user_con_pt_state (with bounds)
    context_block = _behavior_context_block(pillar_slug, concept_scores)
    
    # Prefer precise state context (includes bounds)
    st_rows = state_context or []
    if st_rows:
        st_lines = ["state_context:  # from user_concept_state; includes bounds from Concept.zero_score/max_score"]
        for row in st_rows[:30]:  # cap length defensively
            concept  = (row.get("concept") or "").strip()
            q_text   = (row.get("question") or "").strip().replace("\n", " ")
            a_text   = (row.get("answer") or "").strip().replace("\n", " ")
            unit     = (row.get("unit") or "").strip()
            min_v    = row.get("min_val")
            max_v    = row.get("max_val")
            bounds   = []
            if min_v is not None: bounds.append(f"zero_score={min_v}")
            if max_v is not None: bounds.append(f"max_score={max_v}")
            if min_v is not None and max_v is not None and min_v > max_v:
                bounds.append("direction=lower_is_better")
            bounds_s = ", ".join(bounds)
            unit_s   = f", unit={unit}" if unit else ""
            meta_s   = f" ({bounds_s}{unit_s})" if (bounds_s or unit_s) else ""
            st_lines.append(f"- concept: {concept}\n  question: \"{q_text}\"\n  answer: \"{a_text}\"\n  meta: \"{meta_s}\"")
        state_block = "\n".join(st_lines)
    else:
        state_block = "state_context: []"
    state_answers = _answers_from_state_context(st_rows)

    psych_block = ""
    if psych_profile:
        import json as _json
        pp = {
            "section_averages": psych_profile.get("section_averages"),
            "flags": psych_profile.get("flags"),
            "parameters": psych_profile.get("parameters"),
        }
        psych_block = f"psych_profile: {_json.dumps(pp, ensure_ascii=False)}\n"

    # (Optional) keep the simpler qa_context for transparency, if present
    qa_rows = qa_context or []
    if qa_rows and not st_rows:
        qa_lines = ["qa_context:"]
        for row in qa_rows[:20]:
            concept = (row.get("concept") or "").strip()
            question = (row.get("question") or "").strip().replace("\n", " ")
            answer = (row.get("answer") or "").strip().replace("\n", " ")
            qa_lines.append(f"- concept: {concept}\n  question: \"{question}\"\n  answer: \"{answer}\"")
        qa_block = "\n".join(qa_lines)
    else:
        qa_block = "qa_context: []"

    focus_line = ""
    if pillar_preference:
        focus_line = f"user_focus: \"{pillar_preference.strip()}\"\n"
    prompt_user = {
        "role": "user",
        "content": (
            f"pillar: {pillar_slug}\n"
            f"{context_block}\n"
            f"{state_block}\n"
            f"{qa_block}\n"
            f"{focus_line}\n"
            f"{psych_block}"
            "Rules:\n"
            "- Base the Objective and ALL Key Results on the user's answers in state_context (prefer) or qa_context if state_context is empty.\n"
            "- Where bounds are given (min/max or unit), set realistic targets within bounds; do NOT exceed max. Respect units.\n"
            "- Write ONE objective focused on the main gaps implied by the answers.\n"
            "- Return 2–4 Key Results that are weekly/daily habits with concrete units (sessions/week, portions/day, L/day, nights/week, days/week, or %).\n"
            "- Forbidden in KR text: 'score', 'adherence', 'priority action(s)'. Use behaviors and units instead.\n"
            "- Prefer small, realistic progressions derived from the stated answers (e.g., from '1 session/week' move to '3 sessions/week').\n"
            "- DO NOT include a Key Result if the user is already at the recommended level or no improvement is needed; fewer KRs are preferred over maintenance targets.\n"
            "- Do NOT propose improvements for concepts already scoring ~100; focus on concepts materially below the top score.\n"
            "- Reuse the units mentioned in the user's answers (state_context meta); do not switch to different units like percentages if the question used days/week or portions/day.\n"
            "Return JSON only. Do not include markdown or code fences."
        ),
    }

    # Use the practical coaching system prompt (raw mode still uses RAW; otherwise PRACTICAL)
    system_msg = STRUCTURED_OKR_SYSTEM_RAW if OKR_FORCE_RAW else PRACTICAL_OKR_SYSTEM
    import json as _json
    messages = [
        {"role": "system", "content": system_msg},
        prompt_user,
    ]
    prompt_text = _json.dumps(messages, ensure_ascii=False)
    try:
        resp = _client.chat.completions.create(
            model=mdl,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=messages,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Guard: strip common markdown fences if present
        if raw.startswith("```"):
            raw = raw.strip().lstrip("`").rstrip("`")
            if raw.lower().startswith("json"):
                raw = raw[4:].lstrip()
        import json, re
        try:
            data = json.loads(raw)
        except Exception as e_primary:
            # Rescue: extract the first top-level JSON object for models that wrap output
            m = re.search(r"\{(?:[^{}]|(?R))*\}", raw, re.S)
            if m:
                data = json.loads(m.group(0))
            else:
                raise e_primary
        # Minimal schema checks
        if not isinstance(data, dict): raise ValueError("not an object")
        if "objective" not in data or "krs" not in data: raise ValueError("missing keys")
        if not isinstance(data["krs"], list) or len(data["krs"]) == 0: raise ValueError("empty krs")
        # Normalize KR fields (accept string or object)
        normalized_krs = []
        for i, kr in enumerate(data["krs"]):
            if isinstance(kr, str):
                desc = kr.strip()
                normalized_krs.append({
                    "kr_key": f"KR{i+1}",
                    "description": desc,
                    "metric_label": None,
                    "unit": None,
                    "baseline_num": None,
                    "target_num": None,
                    "score": None,
                    "concept_key": None,
                })
            elif isinstance(kr, dict):
                normalized_krs.append({
                    "kr_key": (kr.get("kr_key") or f"KR{i+1}"),
                    "description": (kr.get("description") or "").strip(),
                    "metric_label": kr.get("metric_label"),
                    "unit": kr.get("unit"),
                    "baseline_num": kr.get("baseline_num"),
                    "target_num": kr.get("target_num"),
                    "score": kr.get("score"),
                    "concept_key": kr.get("concept_key"),
                })
            else:
                # Fallback for unexpected types: coerce to string description
                normalized_krs.append({
                    "kr_key": f"KR{i+1}",
                    "description": str(kr),
                    "metric_label": None,
                    "unit": None,
                    "baseline_num": None,
                    "target_num": None,
                    "score": None,
                    "concept_key": None,
                })
        data["krs"] = [
            _enrich_kr_defaults(pillar_slug, kr, concept_scores or {}, state_answers)
            for kr in normalized_krs
        ]
        _sanitize_kr_phrasing(pillar_slug, data)
        # Store EXACTLY what we sent to the LLM (no footer, no mutation)
        data["prompt_text"] = prompt_text
        return data
    except Exception as e:
        # Debug: show why we are falling back (parse/model errors)
        try:
            _preview = (raw[:240] if isinstance(raw, str) else str(raw)[:240]).replace("\n", " ")
        except Exception:
            _preview = "<unavailable>"
        print(f"[OKR][LLM] parse_or_call_error pillar={pillar_slug} err={e} raw_preview=\"{_preview}\"")
        if OKR_RAW_FROM_LLM:
            # No fallback in raw mode — surface the error
            raise
        data = _fallback_structured_okr(pillar_slug, pillar_score)
        # Store EXACTLY what we intended to send (even though we fell back)
        data["prompt_text"] = prompt_text
        data["krs"] = [
            _enrich_kr_defaults(pillar_slug, kr, concept_scores or {}, state_answers)
            for kr in data.get("krs", [])
        ]
        _sanitize_kr_phrasing(pillar_slug, data)
        return data



# ------------------------------------------------------------------------------
# PERSISTENCE LAYER (uses SQLAlchemy models from app.models)
# ------------------------------------------------------------------------------

from sqlalchemy.orm import Session
from sqlalchemy import and_, func

# Import your ORM classes (must exist in app.models)
from app.models import (
    OKRCycle, OKRObjective, OKRKeyResult, OKRKrEntry, PillarResult,
    # AssessSession, User  # referenced by ForeignKeys in models.py
)

DEFAULT_PILLAR_WEIGHTS = {"nutrition": 0.30, "training": 0.40, "resilience": 0.30}

def _quarter_for(dt: datetime) -> str:
    return f"Q{((dt.month - 1) // 3) + 1}"

def _quarter_bounds(year: int, quarter: str):
    q = int(quarter[1])
    start_month = (q - 1) * 3 + 1
    end_month   = start_month + 2
    start = datetime(year, start_month, 1, 0, 0, 0, tzinfo=timezone.utc)
    last_day = monthrange(year, end_month)[1]
    end = datetime(year, end_month, last_day, 23, 59, 59, tzinfo=timezone.utc)
    return start, end

def _next_sunday_after(dt: datetime) -> datetime:
    """Return midnight (UTC) on the current/next Sunday (if already Sunday, use today)."""
    base_date = dt.date()
    delta = (6 - base_date.weekday()) % 7  # Monday=0, Sunday=6
    sunday = base_date + timedelta(days=delta)
    return datetime(sunday.year, sunday.month, sunday.day, 0, 0, 0, tzinfo=timezone.utc)


def ensure_cycle(session: Session, anchor: Optional[datetime] = None) -> OKRCycle:
    """
    Ensure an OKR cycle exists. Anchor to the current/next Sunday (same-day if Sunday) and run for roughly 90 days (13 weeks).
    """
    anchor   = anchor or datetime.now(timezone.utc)
    start    = _next_sunday_after(anchor)
    end      = start + timedelta(days=89)  # ~13 weeks
    year     = start.year
    quarter  = _quarter_for(start)

    cycle = (
        session.query(OKRCycle)
        .filter(OKRCycle.year == year, OKRCycle.quarter == quarter)
        .first()
    )
    if cycle:
        return cycle

    cycle = OKRCycle(
        year=year,
        quarter=quarter,
        title=f"FY{year} {quarter}",
        starts_on=start,
        ends_on=end,
        pillar_weights=DEFAULT_PILLAR_WEIGHTS,
    )
    session.add(cycle)
    session.flush()  # obtain cycle.id
    return cycle

def upsert_objective_from_pillar(
    session: Session,
    *,
    user_id: int,
    assess_session_id: int,
    pillar_result_id: int,
    pillar_key: str,
    pillar_score: float | None,
    advice_text: str | None = None,
    llm_prompt: Optional[str] = None,
) -> OKRObjective:
    """
    Create or update the OKR Objective for this user/pillar in the current quarter,
    linking back to the assessment session and specific pillar result.
    """
    # Anchor cycle to the assessment session creation time if available
    anchor_dt = None
    if assess_session_id:
        sess = session.query(AssessSession).filter(AssessSession.id == assess_session_id).one_or_none()
        anchor_dt = getattr(sess, "created_at", None)
    cycle = ensure_cycle(session, anchor_dt or datetime.now(timezone.utc))

    # 1) Try exact lineage idempotency
    obj = (
        session.query(OKRObjective)
        .filter(
            and_(
                OKRObjective.cycle_id == cycle.id,
                OKRObjective.owner_user_id == user_id,
                OKRObjective.pillar_key == pillar_key,
                OKRObjective.source_pillar_id == pillar_result_id,
            )
        )
        .first()
    )

    # 2) Fall back to "same user/pillar in this quarter"
    if obj is None:
        obj = (
            session.query(OKRObjective)
            .filter(
                and_(
                    OKRObjective.cycle_id == cycle.id,
                    OKRObjective.owner_user_id == user_id,
                    OKRObjective.pillar_key == pillar_key,
                )
            )
            .order_by(OKRObjective.id.desc())
            .first()
        )

    if obj is None:
        obj = OKRObjective(
            cycle_id=cycle.id,
            pillar_key=pillar_key,
            objective=advice_text or f"Improve {pillar_key}",
            owner_user_id=user_id,
            source_assess_session_id=assess_session_id,
            source_pillar_id=pillar_result_id,
            overall_score=pillar_score,
            weight=1.0,
            llm_prompt=llm_prompt,
        )
        session.add(obj)
        session.flush()
    else:
        if advice_text:
            obj.objective = advice_text
        obj.overall_score = pillar_score
        if not obj.source_assess_session_id:
            obj.source_assess_session_id = assess_session_id
        if not obj.source_pillar_id:
            obj.source_pillar_id = pillar_result_id
        if llm_prompt is not None:
            obj.llm_prompt = llm_prompt
        session.flush()

    # Remove any older objectives for the same quarter/user/pillar so only the latest set remains
    session.query(OKRObjective)\
        .filter(
            OKRObjective.cycle_id == cycle.id,
            OKRObjective.owner_user_id == user_id,
            OKRObjective.pillar_key == pillar_key,
            OKRObjective.id != obj.id,
        )\
        .delete(synchronize_session=False)
    session.flush()

    return obj

def upsert_kr(
    session: Session,
    *,
    objective_id: int,
    kr_key: Optional[str],
    description: str,
    metric_label: Optional[str] = None,
    unit: Optional[str] = None,
    baseline_num: Optional[float] = None,
    target_num: Optional[float] = None,
    actual_num: Optional[float] = None,
    score: Optional[float] = None,
    weight: float = 1.0,
    status: str = "active",
    notes: Optional[str] = None,
    add_progress_entry: bool = False,
    progress_note: Optional[str] = None,
    progress_source: Optional[str] = "system",
) -> OKRKeyResult:
    """
    Create or update a KR under an objective.
      Match order:
        1) (objective_id, kr_key) if kr_key provided
        2) (objective_id, description) as a fallback
    """
    kr_key_slug = _slug32(kr_key) if kr_key else None
    kr = None
    if kr_key:
        kr = (
            session.query(OKRKeyResult)
            .filter(
                and_(
                    OKRKeyResult.objective_id == objective_id,
                    OKRKeyResult.kr_key == kr_key_slug,
                )
            )
            .first()
        )
    if kr is None:
        kr = (
            session.query(OKRKeyResult)
            .filter(
                and_(
                    OKRKeyResult.objective_id == objective_id,
                    OKRKeyResult.description == description,
                )
            )
            .first()
        )

    if kr is None:
        kr = OKRKeyResult(
            objective_id=objective_id,
            kr_key=kr_key_slug,
            description=description,
            metric_label=metric_label,
            unit=unit,
            baseline_num=baseline_num,
            target_num=target_num,
            actual_num=actual_num,
            score=score,
            weight=weight,
            status=status,
            notes=notes,
        )
        session.add(kr)
        session.flush()
    else:
        kr.description  = description or kr.description
        kr.metric_label = metric_label
        kr.unit         = unit
        if baseline_num is not None: kr.baseline_num = baseline_num
        if target_num   is not None: kr.target_num   = target_num
        if actual_num   is not None: kr.actual_num   = actual_num
        if score        is not None: kr.score        = score
        if weight       is not None: kr.weight       = weight
        kr.status = status or kr.status
        kr.notes  = notes
        session.flush()

    # Optional progress entry
    if add_progress_entry and (actual_num is not None or progress_note):
        entry = OKRKrEntry(
            key_result_id=kr.id,
            actual_num=actual_num,
            note=progress_note,
            source=progress_source,
        )
        session.add(entry)
        session.flush()

    return kr

def recompute_objective_score_from_krs(session: Session, objective_id: int) -> Optional[float]:
    """Weighted average of KR scores for the objective (None if no scored KRs)."""
    rows = (
        session.query(OKRKeyResult.score, OKRKeyResult.weight)
        .filter(OKRKeyResult.objective_id == objective_id)
        .all()
    )
    if not rows:
        return None
    num, den = 0.0, 0.0
    for s, w in rows:
        if s is None or w is None or w == 0:
            continue
        num += float(s) * float(w)
        den += float(w)
    return round(num / den, 2) if den > 0 else None


# ──────────────────────────────────────────────────────────────────────────────
# Hotfix: non-transactional sync entrypoint used by generate_and_update_okrs_for_pillar
# Caller (assessor flow) controls commit/rollback; we only add()/flush().
# ──────────────────────────────────────────────────────────────────────────────
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session

def sync_okrs_for_completed_pillar(
    session: Session,
    *,
    user_id: int,
    assess_session_id: int,
    pillar_result_id: int,
    pillar_key: str,
    pillar_score: Optional[float],
    advice_text: Optional[str],
    kr_specs: Optional[List[Dict[str, Any]]] = None,
    write_progress_entries: bool = False,
    llm_prompt: Optional[str] = None,
):
    """
    Ensure cycle, upsert objective (linked to user/session/pillar), upsert KRs (+ optional entries),
    recompute objective.overall_score from KR scores if present. No session.begin()/commit() here.
    """
    # 1) upsert objective
    obj = upsert_objective_from_pillar(
        session,
        user_id=user_id,
        assess_session_id=assess_session_id,
        pillar_result_id=pillar_result_id,
        pillar_key=pillar_key,
        pillar_score=pillar_score,
        advice_text=advice_text,
        llm_prompt=llm_prompt,
    )
    session.flush()

    # 2) upsert KRs
    if kr_specs:
        session.query(OKRKeyResult).filter(OKRKeyResult.objective_id == obj.id).delete(synchronize_session=False)
        session.flush()
        for spec in kr_specs:
            upsert_kr(
                session,
                objective_id=obj.id,
                kr_key=spec.get("kr_key"),
                description=spec["description"],
                metric_label=spec.get("metric_label"),
                unit=spec.get("unit"),
                baseline_num=spec.get("baseline_num"),
                target_num=spec.get("target_num"),
                actual_num=spec.get("actual_num"),
                score=spec.get("score"),
                weight=spec.get("weight", 1.0),
                status=spec.get("status", "active"),
                notes=spec.get("notes"),
                add_progress_entry=write_progress_entries or spec.get("add_progress_entry", False),
                progress_note=spec.get("progress_note"),
                progress_source=spec.get("progress_source", "assessment"),
            )
        session.flush()

    # 3) objective roll-up from KR scores (weighted)
    rollup = recompute_objective_score_from_krs(session, obj.id)
    if rollup is not None:
        obj.overall_score = rollup
        session.flush()

    return obj



def generate_and_update_okrs_for_pillar(
    session: Session,
    *,
    user_id: int,
    assess_session_id: int,
    pillar_result_id: int,
    pillar_key: str,
    pillar_score: float | None,
    concept_scores: Dict[str, float] | None = None,
    write_progress_entries: bool = True,
    quarter_label: Optional[str] = None,   # still used for the pretty text block below
) -> Dict[str, Any]:
    """
    1) Get structured OKR (objective + KRs) from LLM (strict JSON) with deterministic fallback.
    2) Persist cycle, objective, KRs (and optional KR entries).
    3) Also produce a pretty text block for UI.
    Returns: {"objective": OKRObjective, "okr_text": str, "okr_struct": dict}
    """
    # Ensure pillar_score is populated (fallback to DB if missing)
    if pillar_score is None:
        try:
            from app.models import PillarResult  # import here to avoid circulars at module load
            pr = session.get(PillarResult, pillar_result_id)
            if pr is not None:
                pillar_score = (
                    getattr(pr, "overall", None)
                    or getattr(pr, "score", None)
                    or getattr(pr, "pillar_score", None)
                )
        except Exception:
            pass

    # 1) Ask LLM for structured OKR
    run_id_for_pillar = None
    try:
        pr = session.get(PillarResult, pillar_result_id) if pillar_result_id else None
        run_id_for_pillar = getattr(pr, "run_id", None) if pr is not None else None
    except Exception:
        pass
    state_ctx = _build_state_context_from_models(session, user_id=user_id, run_id=run_id_for_pillar, pillar_slug=pillar_key)
    pref_value = None
    pref_key = PILLAR_PREF_KEYS.get(pillar_key)
    if pref_key:
        pref_row = (
            session.query(UserPreference.value)
            .filter(UserPreference.user_id == user_id, UserPreference.key == pref_key)
            .scalar()
        )
        if pref_row:
            pref_value = pref_row
    psych_profile = None
    try:
        prof = psych.latest_profile(user_id)
        if prof:
            psych_profile = {
                "section_averages": getattr(prof, "section_averages", None),
                "flags": getattr(prof, "flags", None),
                "parameters": getattr(prof, "parameters", None),
            }
    except Exception:
        psych_profile = None
    okr_struct = make_structured_okr_llm(
        pillar_slug=pillar_key,
        pillar_score=pillar_score,
        concept_scores=concept_scores or {},
        qa_context=None,                 # not required when state_context is present
        state_context=state_ctx,
        pillar_preference=pref_value,
        psych_profile=psych_profile,
    )

    def _capitalise(text: Any) -> str:
        if text is None:
            return ""
        s = str(text).strip()
        if not s:
            return s
        return s[0].upper() + s[1:]

    okr_struct["objective"] = _capitalise(okr_struct.get("objective"))
    normalised_krs: list = []
    for kr in okr_struct.get("krs", []) or []:
        if isinstance(kr, dict):
            norm = dict(kr)
            norm["description"] = _capitalise(norm.get("description"))
            normalised_krs.append(norm)
        else:
            normalised_krs.append(_capitalise(kr))
    processed_krs: list = []
    for kr in normalised_krs:
        base = kr.get("baseline_num")
        target = kr.get("target_num")
        ckey = _normalize_concept_key((kr.get("concept_key") or "").split(".")[-1])
        # Skip maintenance KRs (no delta) or concepts already at/near 100
        try:
            if base is not None and target is not None and abs(float(base) - float(target)) < 1e-6:
                continue
        except Exception:
            pass
        try:
            if ckey and ckey in (concept_scores or {}):
                sc = concept_scores.get(ckey)
                if sc is not None and float(sc) >= 99:
                    continue
        except Exception:
            pass
        processed_krs.append(kr)
    okr_struct["krs"] = processed_krs

    # Build a nice display block (keeps your current UX)
    def _kr_desc(kr):
        if isinstance(kr, dict):
            return kr.get("description") or ""
        return str(kr)

    def _kr_notes_blob(kr: dict) -> str | None:
        payload: dict[str, Any] = {}
        ck = (kr.get("concept_key") or "").strip()
        if ck:
            payload["concept_key"] = ck
        src = (kr.get("_baseline_source") or "").strip()
        if src:
            payload["baseline_source"] = src
        return json.dumps(payload) if payload else None
    pretty_text = (
        f"🧭 {quarter_label or DEFAULT_OKR_QUARTER} Objective: {okr_struct['objective']}\n"
        "Key Results:\n" + "\n".join(
            f"{i+1}) {_kr_desc(kr)}" for i, kr in enumerate(okr_struct["krs"])
        )
    )

    # 2) Persist the objective with text (store the pretty text in advice_text)
    obj = sync_okrs_for_completed_pillar(
        session,
        user_id=user_id,
        assess_session_id=assess_session_id,
        pillar_result_id=pillar_result_id,
        pillar_key=pillar_key,
        pillar_score=pillar_score,
        advice_text=okr_struct["objective"],   # objective text only (cleaner for DB)
        kr_specs=[
            {
                "kr_key": kr.get("kr_key"),
                "description": kr.get("description"),
                "metric_label": kr.get("metric_label"),
                "unit": kr.get("unit"),
                "baseline_num": kr.get("baseline_num"),
                "target_num": kr.get("target_num"),
                "actual_num": kr.get("actual_num"),
                "score": kr.get("score"),
                "weight": 1.0,
                "status": "active",
                "notes": _kr_notes_blob(kr),
                "add_progress_entry": write_progress_entries,
                "progress_note": "Initialized from assessment",
                "progress_source": "assessment",
            }
            for kr in okr_struct["krs"]
        ],
        write_progress_entries=write_progress_entries,
        llm_prompt=okr_struct.get("prompt_text"),
    )

    return {"objective": obj, "okr_text": pretty_text, "okr_struct": okr_struct}
