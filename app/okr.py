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
from datetime import datetime, timezone
from calendar import monthrange
import os

# --- Needed for new state context helper ---
from sqlalchemy.sql import text as _sql_text
from app.models import UserConceptState, Concept, PillarResult

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

# --- OpenAI client (optional) -------------------------------------------------
try:
    from openai import OpenAI  # openai>=1.0
    _client = OpenAI()
except Exception:
    _client = None

DEFAULT_OKR_MODEL   = os.getenv("OKR_MODEL", "gpt-4o-mini")
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
    "Return STRICT JSON with keys: objective (string), krs (array of 2–4 items). "
    "Each KR MUST be an observable behavior the user can perform weekly/daily, expressed in real-world units: "
    "sessions/week, days/week, nights/week, portions/day, litres/day, or percent. "
    "Use the provided behavior_context (labels, units, direction) to decide what to increase, maintain, or reduce. "
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
            rows_out.append({
                "concept":   c.code or c.name,
                "question":  st.question or "",
                "answer":    st.answer or "",
                "unit":      "",  # no explicit unit in schema; default unit will be inferred from _GUIDE
                "min_val":   c.zero_score,
                "max_val":   c.max_score,
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
                   COALESCE(c.max_score,  NULL)       AS max_val
            FROM user_concept_state ucs
            JOIN concepts c ON ucs.concept_id = c.id
            WHERE ucs.user_id = :uid
              AND (:rid IS NULL OR ucs.run_id = :rid)
              AND c.pillar_key = :pillar
            ORDER BY ucs.id ASC
        """
        try:
            rs = session.execute(_sql_text(sql), params).fetchall()
            for r in rs:
                rows_out.append({
                    "concept":  r[1],
                    "question": r[2] or "",
                    "answer":   r[3] or "",
                    "unit":     "",
                    "min_val":  r[4],
                    "max_val":  r[5],
                })
        except Exception:
            pass
        return rows_out


def make_structured_okr_llm(
    pillar_slug: str,
    pillar_score: float | None,
    concept_scores: Dict[str, float] | None = None,
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    qa_context: Optional[List[Dict[str, str]]] = None,
    state_context: Optional[List[Dict[str, str]]] = None,
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
            if min_v is not None: bounds.append(f"min={min_v}")
            if max_v is not None: bounds.append(f"max={max_v}")
            bounds_s = ", ".join(bounds)
            unit_s   = f", unit={unit}" if unit else ""
            meta_s   = f" ({bounds_s}{unit_s})" if (bounds_s or unit_s) else ""
            st_lines.append(f"- concept: {concept}\n  question: \"{q_text}\"\n  answer: \"{a_text}\"\n  meta: \"{meta_s}\"")
        state_block = "\n".join(st_lines)
    else:
        state_block = "state_context: []"

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

    prompt_user = {
        "role": "user",
        "content": (
            f"pillar: {pillar_slug}\n"
            f"{context_block}\n"
            f"{state_block}\n"
            f"{qa_block}\n\n"
            "Rules:\n"
            "- Base the Objective and ALL Key Results on the user's answers in state_context (prefer) or qa_context if state_context is empty.\n"
            "- Where bounds are given (min/max or unit), set realistic targets within bounds; do NOT exceed max. Respect units.\n"
            "- Write ONE objective focused on the main gaps implied by the answers.\n"
            "- Return 2–4 Key Results that are weekly/daily habits with concrete units (sessions/week, portions/day, L/day, nights/week, days/week, or %).\n"
            "- Forbidden in KR text: 'score', 'adherence', 'priority action(s)'. Use behaviors and units instead.\n"
            "- Prefer small, realistic progressions derived from the stated answers (e.g., from '1 session/week' move to '3 sessions/week').\n"
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
                })
        data["krs"] = normalized_krs
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

def ensure_cycle(session: Session, now: Optional[datetime] = None) -> OKRCycle:
    """Ensure the current quarter exists in okr_cycles and return it."""
    now     = now or datetime.now(timezone.utc)
    year    = now.year
    quarter = _quarter_for(now)

    cycle = (
        session.query(OKRCycle)
        .filter(OKRCycle.year == year, OKRCycle.quarter == quarter)
        .first()
    )
    if cycle:
        return cycle

    starts_on, ends_on = _quarter_bounds(year, quarter)
    cycle = OKRCycle(
        year=year,
        quarter=quarter,
        title=f"FY{year} {quarter}",
        starts_on=starts_on,
        ends_on=ends_on,
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
    cycle = ensure_cycle(session, datetime.now(timezone.utc))

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
    print(f"[OKR][DEBUG] pillar={pillar_key} run_id={run_id_for_pillar} user_id={user_id} state_ctx_rows={len(state_ctx)}")
    if not state_ctx:
        print("[OKR][DEBUG] state_ctx is empty — check user_concept_state rows for this user/run/pillar.")
    else:
        _prev = {k: state_ctx[0].get(k) for k in ("concept","question","answer","min_val","max_val")}
        print(f"[OKR][DEBUG] state_ctx first: { _prev }")
    okr_struct = make_structured_okr_llm(
        pillar_slug=pillar_key,
        pillar_score=pillar_score,
        concept_scores=concept_scores or {},
        qa_context=None,                 # not required when state_context is present
        state_context=state_ctx,
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
    okr_struct["krs"] = normalised_krs

    # Simple on-screen debug of what we'll write to llm_prompt
    _pt = okr_struct.get("prompt_text") or ""
    try:
        _preview = _pt[:240].replace("\n", " ")
    except Exception:
        _preview = str(_pt)[:240]
    print(f"[LLM_PROMPT] pillar={pillar_key} user_id={user_id} len={len(_pt)} preview=\"{_preview}\"")

    # Build a nice display block (keeps your current UX)
    def _kr_desc(kr):
        if isinstance(kr, dict):
            return kr.get("description") or ""
        return str(kr)
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
                "actual_num": None,
                "score": kr.get("score"),
                "weight": 1.0,
                "status": "active",
                "notes": None,
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
