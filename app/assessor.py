# app/assessor.py
# PATCH NOTES — 2025-09-06 (consolidated replacement)
# • Concepts loaded from DB per pillar; cached in session state.
# • One main question per concept (primary only), pillars: nutrition → training → resilience → recovery.
# • Clarifiers: LLM-generated only; do NOT count toward the 5; no deterministic fallback.
# • Strict de-duplication of assistant questions.
# • Writes AssessmentRun/AssessmentTurn; per-concept summary rows with dialogue & kb_used and clarifier_count tracked.
# • Inbound/outbound MessageLog restored; robust Twilio send with whatsapp: normalization.
# • Review_log hooks and scheduler follow-ups preserved.
# • Quick commands: "report"/"pdf" returns latest report link.
# • NEW: Deep diagnostics around all LLM calls (request/response/exception) into JobAudit + terminal prints.
# • NEW: Numeric-signal helper (_has_numeric_signal) recognizes digits, ranges, and number-words for sufficiency.
# • No behavior changes beyond logging and sufficiency hint robustness.

from __future__ import annotations

import json
import os
import re
import traceback
import time 
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from .db import SessionLocal
from .models import (
    User,
    AssessSession,
    Concept,
    UserConceptState,
    AssessmentRun,
    AssessmentTurn,
    ConceptQuestion,
    MessageLog,
    JobAudit,
    PillarResult,
    OKRObjective,
    OKRKeyResult,
    UserPreference,
)

# Messaging + LLM
from .nudges import send_message
from .llm import _llm

# ==============================================================================
# OKR Integration (LLM-generated feedback replacement)
# ------------------------------------------------------------------------------
# This section replaces the old pillar feedback functions with an LLM-generated
# Quarterly OKR produced by app/okr.py.
# - Keeps interface compatibility (generate_feedback_summary, etc.)
# - Requires OPENAI_API_KEY to be set
# - Falls back to deterministic OKR text if the model call fails
# ==============================================================================

from .okr import make_quarterly_okr_llm
from .seed import PILLAR_PREAMBLE_QUESTIONS

# --- Unified helper -----------------------------------------------------------
def feedback_to_okr(
    pillar_slug: str,
    pillar_score: float,
    concept_scores: Optional[dict] = None
) -> str:
    """
    Generate a Quarterly OKR block from pillar results using the LLM.
    Safe to call anywhere you previously returned feedback prose.
    """
    return make_quarterly_okr_llm(
        pillar_slug=pillar_slug,
        pillar_score=pillar_score,
        concept_scores=concept_scores or {},
    )


# --- Override legacy feedback functions ---------------------------------------
def _okr_wrapper(pillar_slug: str, score: float, concept_scores: Optional[dict] = None) -> str:
    return feedback_to_okr(pillar_slug, score, concept_scores)


# 1) generate_feedback_summary(...)
def generate_feedback_summary(
    pillar_slug: str, score: float, concept_scores: Optional[dict] = None
) -> str:
    """Overrides old function to return LLM-based OKR instead of text feedback."""
    return _okr_wrapper(pillar_slug, score, concept_scores)


# 2) format_pillar_feedback(...)
def format_pillar_feedback(
    pillar_slug: str, score: float, concept_scores: Optional[dict] = None
) -> str:
    """Overrides old function to return LLM-based OKR instead of text feedback."""
    return _okr_wrapper(pillar_slug, score, concept_scores)


# 3) build_pillar_feedback(...)
def build_pillar_feedback(
    pillar_slug: str, score: float, concept_scores: Optional[dict] = None
) -> str:
    """Overrides old function to return LLM-based OKR instead of text feedback."""
    return _okr_wrapper(pillar_slug, score, concept_scores)

# Report 

from .reporting import generate_assessment_dashboard_html, generate_progress_report_html, _fetch_okrs_for_run

# Optional integrations (fail-safe no-ops if missing)
try:
    from .review_log import start_run as _rv_start_run, log_turn as _rv_log_turn, finish_run as _rv_finish_run
except Exception:  # pragma: no cover
    def _rv_start_run(*_, **__): return None
    def _rv_log_turn(*_, **__): return None
    def _rv_finish_run(*_, **__): return None

try:
    from .scheduler import schedule_day3_followup, schedule_week2_followup
except Exception:  # pragma: no cover
    def schedule_day3_followup(*_, **__): return None
    def schedule_week2_followup(*_, **__): return None

# Retriever (safe fallbacks)
try:
    from .retriever import retrieve_snippets, diversify
except Exception:  # pragma: no cover
    def retrieve_snippets(*_, **__): return []
    def diversify(snips, **__): return (snips or [])[:5]

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

PILLAR_ORDER = ["nutrition", "training", "resilience", "recovery"]  # explicit order
MAIN_QUESTIONS_PER_PILLAR = 5
CLARIFIER_SOFT_CAP = 6
TURN_HARD_CAP = 60

SYSTEM_TEMPLATE = """You are a concise WhatsApp assessor for __PILLAR__.
Active concept: __CONCEPT__.
Ask a main question (<=300 chars, can be detailed with examples) or a clarifier (<=320 chars) when the user's answer is vague. You have latitude to infer when the user's phrasing strongly implies a quantitative pattern.
If the user's reply contains a NUMBER **or** strongly implies a count/timeframe (e.g., "daily", "every evening", "twice daily", "each morning"), you may TREAT IT AS SUFFICIENT and finish with a score. When you infer from habitual phrasing, state a brief rationale and set an appropriate confidence.
Only finish the concept once you can assign a score (0–100) for this concept (zero is allowed).
Return JSON only with these fields:
{"action":"ask"|"finish","question":"","level":"Low"|"Moderate"|"High","confidence":<float 0.0–1.0>,
"rationale":"","scores":{},
"status":"scorable"|"needs_clarifier"|"insufficient",
"why":"",
"missing":[],
"parsed_value":{"value":null,"unit":"","timeframe_ok":false}}
Notes:
- Scoring priority: If numeric bounds (zero_score, max_score) are provided for this concept, they DEFINE polarity (higher-is-better vs lower-is-better) and the mapping to 0–100. Bounds override heuristics and any KB snippets. If no bounds are provided, use your general health/nutrition expertise to choose a sensible polarity and mapping; treat retrieved KB snippets as optional context only.
- Always output integer scores on a 0–100 scale. Choose a reasonable mapping that reflects how clearly good/poor the reported pattern is.
- Polarity inference: When the behavior is one people should limit/avoid (e.g., processed foods), LOWER frequency is BETTER. When it’s a recommended behavior (e.g., fruit/veg portions, hydration, protein), HIGHER adherence is BETTER.
- Zero handling follows the bounds polarity. If zero_score <= max_score (higher is better), 0 maps to a low score. If zero_score > max_score (lower is better), 0 maps to a high score. Treat 'none', 'no', 'zero' as numeric 0.
- Language-to-number heuristic: map categorical habitual phrases when reasonable (e.g., "daily"/"every evening" in a 7‑day window → 7). Also map number words: “once or twice / occasionally” ≈ 1–2; “few days / some days” ≈ 3–4; “most days / regularly / often” ≈ 5–7.
- Clarifiers: You **may** ask a clarifier if needed to score. Avoid verbatim repetition of the main question; rephrase when you re-ask. You can ask for more than one detail if truly necessary, but prefer concise, high-signal questions.
- status=scorable → you can finish now; needs_clarifier → ask a clarifier; insufficient → ask a main question.
- missing: list the specific fields you need (e.g., ["unit","days_per_week"]).
- parsed_value: include the numeric you inferred (e.g., 3), unit label, and whether timeframe is satisfied.
- IMPORTANT: Return `scores` as integers on a 0–100 scale (NOT 0–10). Use your rubric mapping to 0–100.
- Confidence calibration: If numeric AND timeframe explicit → set confidence 0.75–0.95. If inferred from categorical phrasing (e.g., "every evening"), choose 0.65–0.85 based on certainty. If numeric but timeframe inferred/loose → 0.55–0.75.
- If uncertain, ask a clarifier instead of finishing.
- Do NOT copy example values; set confidence per these rules.
"""

FEEDBACK_SYSTEM = (
    "Write one short feedback line and two short next steps based on pillar dialog.\n"
    "Format:\n"
    "- 1 short feedback line (what they do well + gap)\n"
    '- \"Next steps:\" + 2 bullets (<= 12 words), practical, non-judgmental.'
)

# ──────────────────────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────────────────────

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

def _asked_norm_set(turns: list[dict], pillar: str) -> set[str]:
    return {
        _norm(t.get("question") or t.get("text") or "")
        for t in turns
        if t.get("role") == "assistant" and t.get("pillar") == pillar
    }

# Helper to build display name from first_name + surname only (no legacy name fallback)
def _display_full_name(user: User) -> str:
    first = (getattr(user, "first_name", None) or "").strip()
    return first

# Helper to detect restatements (token-level Jaccard or heavy containment)
def _too_similar(a: str, b: str, jaccard_threshold: float = 0.7) -> bool:
    """Return True when a and b are likely restatements (token-level Jaccard or heavy containment)."""
    aa = _norm(a)
    bb = _norm(b)
    if not aa or not bb:
        return False
    # Heavy containment: one string covers >=80% of the other
    if (len(aa) and len(bb)) and (aa in bb or bb in aa):
        shorter = aa if len(aa) <= len(bb) else bb
        longer = bb if shorter is aa else aa
        if len(shorter) / max(1, len(longer)) >= 0.8:
            return True
    aset = set(aa.split())
    bset = set(bb.split())
    if not aset or not bset:
        return False
    jacc = len(aset & bset) / max(1, len(aset | bset))
    return jacc >= jaccard_threshold

def _as_dialogue_simple(items: list[dict]) -> list[dict]:
    out = []
    for t in items:
        role = t.get("role")
        txt = t.get("text") if t.get("text") is not None else t.get("question")
        if role and txt:
            out.append({"role": role, "text": str(txt)})
    return out

# Detect whether a user message contains a usable numeric value (digits, ranges, or number-words)
_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12
}
_FEW_WORDS = {"few": 3, "couple": 2, "couple of": 2, "several": 4}

def _has_numeric_signal(text: str) -> bool:
    """
    True if text contains a number (digits), a simple range (e.g., 2-3),
    or a small-count word number like 'three', 'couple', 'few'.
    """
    if not text:
        return False
    t = (text or "").lower().strip()
    if re.search(r"\d+(\.\d+)?", t):
        return True
    if re.search(r"\d+\s*[-–]\s*\d+", t):
        return True
    for w in _NUM_WORDS.keys():
        if re.search(rf"\b{re.escape(w)}\b", t):
            return True
    for w in _FEW_WORDS.keys():
        if re.search(rf"\b{re.escape(w)}\b", t):
            return True
    return False


def _parse_number(text: str) -> float | None:
    if not text:
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    if nums:
        try:
            return float(nums[-1])
        except Exception:
            return None
    words = {**_NUM_WORDS, "none": 0, "no": 0, "couple": 2, "few": 3, "several": 4}
    for w in text.lower().split():
        if w in words:
            return float(words[w])
    return None


def _score_from_bounds(zero: float, maxv: float, val: float) -> float:
    if zero > maxv:
        span = zero - maxv
        pct = ((zero - val) / span) * 100 if span else 0
    else:
        span = maxv - zero
        pct = ((val - zero) / span) * 100 if span else 0
    return max(0.0, min(100.0, pct))


def _normalize_value_for_concept(pillar: str, concept: str, val: float, unit: str | None, answer_text: str | None) -> float:
    """
    Normalize raw numeric answers to the expected unit for scoring.
    - Hydration: convert ml→L, glasses→L (0.25L/glass)
    """
    u = (unit or "").lower()
    ans = (answer_text or "").lower()
    if pillar == "nutrition" and concept == "hydration":
        if "ml" in u or "ml" in ans:
            return val / 1000.0
        if "glass" in u or "glass" in ans:
            return val * 0.25
    return val

_WEEK_WINDOW_PATTERNS = [
    r"\blast\s+7\s+days?\b",
    r"\bpast\s+7\s+days?\b",
    r"\bin\s+the\s+last\s+7\s+days?\b",
    r"\bin\s+the\s+past\s+7\s+days?\b",
    r"\blast\s+week\b",
    r"\bpast\s+week\b",
    r"\bin\s+the\s+last\s+week\b",
    r"\bin\s+the\s+past\s+week\b",
]

def _has_recent_week_window(text: str) -> bool:
    """
    Detects whether the question already framed a recent-week timeframe
    (covers 'last 7 days', 'past 7 days', 'last week', etc.).
    """
    if not text:
        return False
    t = (text or "").lower()
    return any(re.search(pattern, t) for pattern in _WEEK_WINDOW_PATTERNS)

def _shorten_ack_text(text: str, limit: int = 160) -> str:
    """Bound acknowledgement echo length so we don’t spam the user with full essays."""
    snippet = (text or "").strip()
    if len(snippet) <= limit:
        return snippet
    return snippet[:limit - 1].rstrip() + "…"


def _format_acknowledgement(msg: str, state: dict, pillar: str | None, user: User | None) -> str:
    """
    Build a short acknowledgement so the user knows we logged their reply.
    """
    text = (msg or "").strip()
    if not text:
        return ""
    snippet = _shorten_ack_text(text)
    name = (getattr(user, "first_name", "") or "").strip()
    prefix = f"Thanks {name}".strip() if name else "Thanks"
    hint = " (type *redo* to change or *restart* to begin again)"
    if _has_numeric_signal(text):
        body = f'{prefix}, logged "{snippet}".{hint}'
    else:
        body = f'{prefix} — noted "{snippet}".{hint}'
    progress = _pillar_progress_line(state, pillar, active_increment=1)
    if progress:
        body = f"{body}\n\n{progress}"
    return body

def _user_has_full_name(user: User) -> bool:
    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "surname", "") or "").strip()
    return bool(first and last)

def _capture_name_from_text(db_session, user: User, text: str) -> bool:
    tokens = [t for t in (text or "").replace(",", " ").split() if t.strip()]
    if len(tokens) < 2:
        return False
    def _titlecase_chunk(chunk: str) -> str:
        return " ".join(word.capitalize() for word in (chunk or "").split())
    first = _titlecase_chunk(tokens[0].strip())
    last = _titlecase_chunk(" ".join(tokens[1:]).strip())
    if not first or not last:
        return False
    user.first_name = first
    user.surname = last
    try:
        user.updated_on = datetime.utcnow()
    except Exception:
        pass
    try:
        db_session.commit()
    except Exception:
        db_session.rollback()
        return False
    return True

def _compose_ack_with_message(ack_text: str | None, message: str | None) -> tuple[str, str]:
    """
    Merge the acknowledgement with the next outbound message so WhatsApp preserves ordering.
    Returns (composed_message, remaining_ack_text).
    """
    ack = (ack_text or "").strip()
    body = (message or "").strip()
    if ack and body:
        return f"{ack}\n\n{body}", ""
    if ack:
        return ack, ""
    return body, ""

# Prettify concept code for user-facing messages
def _pretty_concept(code: str) -> str:
    return (code or "").replace("_", " ").title()

def _system_for(pillar: str, concept_code: str) -> str:
    return (
        SYSTEM_TEMPLATE
        .replace("__PILLAR__", pillar.title())
        .replace("__CONCEPT__", concept_code.replace("_"," ").title())
    )

def _ensure_total_questions(state: dict) -> int:
    """
    Ensure state['total_questions'] reflects the number of main questions
    we plan to ask (sum of pillar concept counts, capped).
    """
    if not isinstance(state, dict):
        return len(PILLAR_ORDER) * MAIN_QUESTIONS_PER_PILLAR
    try:
        current = int(state.get("total_questions") or 0)
    except Exception:
        current = 0
    if current > 0:
        state["total_questions"] = current
        return current
    pillar_concepts = state.get("pillar_concepts") or {}
    total = sum(len(codes or []) for codes in pillar_concepts.values())
    if total <= 0:
        total = len(PILLAR_ORDER) * MAIN_QUESTIONS_PER_PILLAR
    state["total_questions"] = total
    return total

def _ensure_question_number(state: dict, pillar: str | None, concept_code: str | None, question_text: str | None = None) -> int:
    """
    Assign (or retrieve) the sequential question number for this concept.
    Re-asking the same concept reuses its original number.
    """
    if not isinstance(state, dict):
        return 1
    qnums = state.setdefault("question_numbers", {})
    pillar_key = pillar or "__global__"
    pillar_map = qnums.setdefault(pillar_key, {})
    concept_key = concept_code or (question_text or "__anon__")
    if concept_key in pillar_map:
        return int(pillar_map[concept_key])
    try:
        seq = int(state.get("question_seq") or 0) + 1
    except Exception:
        seq = 1
    state["question_seq"] = seq
    pillar_map[concept_key] = seq
    return seq

def _pillar_progress_line(state: dict, active_pillar: str | None = None, active_increment: int = 0) -> str:
    pillar_concepts = state.get("pillar_concepts") or {}
    if not pillar_concepts:
        return ""
    concept_idx = state.get("concept_idx", {}) or {}
    blocks: list[str] = []
    for pk in PILLAR_ORDER:
        codes = pillar_concepts.get(pk) or []
        total = len(codes)
        if total <= 0:
            continue
        done = min(int(concept_idx.get(pk, 0) or 0) + (active_increment if pk == active_pillar else 0), total)
        completed = "🟩" * done
        remaining = "⬜" * max(total - done, 0)
        if pk == active_pillar and done < total:
            remaining = ("🟧" + remaining[1:]) if remaining else "🟧"
        next_block = completed + remaining
        blocks.append(f"{pk.title()} [{next_block}]")
    return f"Pillar progress: {'  '.join(blocks)}" if blocks else ""

def _score_bar(label: str, score: float | None, slots: int = 5) -> str:
    """
    Render a colored emoji bar for a given score (0-100). Uses traffic-light colors.
    """
    if score is None:
        return f"{label.title():<10} [No score yet]"
    try:
        pct = int(round(float(score)))
    except Exception:
        pct = 0
    pct = max(0, min(100, pct))
    filled = min(slots, max(0, round(pct / 100 * slots)))
    color = "🟩" if pct >= 80 else "🟧" if pct >= 60 else "🟥"
    bar = color * filled + "⬜" * max(slots - filled, 0)
    return f"[{bar}] {pct}% - *{label.title()}*"

def _compose_final_summary_message(user: User, state: dict) -> str:
    results_map = state.get("results") or {}
    def _pill_score(p):
        v = results_map.get(p, {}) or {}
        return v.get("overall")
    n_sc = _pill_score("nutrition")
    t_sc = _pill_score("training")
    r_sc = _pill_score("resilience")
    rc_sc = _pill_score("recovery")
    per_list = [x for x in [n_sc, t_sc, r_sc, rc_sc] if x is not None]
    combined = round(sum(per_list) / max(1, len(per_list))) if per_list else 0
    bars = []
    if n_sc is not None: bars.append(_score_bar("Nutrition", n_sc))
    if t_sc is not None: bars.append(_score_bar("Training", t_sc))
    if r_sc is not None: bars.append(_score_bar("Resilience", r_sc))
    if rc_sc is not None: bars.append(_score_bar("Recovery", rc_sc))
    breakdown = "\n".join(bars) if bars else "No pillar scores available"
    name = (getattr(user, "first_name", "") or "").strip()
    intro = f"🎯 *Assessment complete, {name}!*" if name else "🎯 *Assessment complete!*"
    combined_bar = _score_bar("Combined", combined)
    msg = f"{intro} Your combined score is:\n{combined_bar}\n\n{breakdown}"
    try:
        html_link = _report_url(user.id, "latest.html")
        bust = int(time.time())
        msg += f"\n\nYour wellbeing dashboard: {html_link}?ts={bust} (type 'dashboard' anytime)"
    except Exception:
        pass
    return msg

def _compose_pillar_message(state: dict, run_id: int | None, pillar: str) -> str:
    res = (state.get("results") or {}).get(pillar)
    if not res:
        return f"I don’t have {pillar.title()} results yet."
    filled_scores = res.get("scores") or {}
    breakdown = "\n".join(
        _score_bar(k.replace("_", " ").title(), v)
        for k, v in filled_scores.items()
    ) or "(no sub-scores)"
    overall = res.get("overall") or 0
    okr_summary_txt = _pillar_okr_summary_from_run(run_id, pillar)
    summary_text = okr_summary_txt or (res.get("rationale") or "")
    return f"✅ *{pillar.title()}* complete — *{int(round(overall))}/100*\n\n{breakdown}\n\n{summary_text}"

def _normalize_pillar_name(token: str) -> str | None:
    token = (token or "").strip().lower()
    if not token:
        return None
    mapping = {
        "nutrition": ["nutrition", "nutri", "n"],
        "training": ["training", "train", "t"],
        "resilience": ["resilience", "resil", "r"],
        "recovery": ["recovery", "recov", "rec", "c"],
    }
    for slug, aliases in mapping.items():
        if token in aliases:
            return slug
    for slug in PILLAR_ORDER:
        if token in slug:
            return slug
    return None

def _pillar_okr_summary_from_run(run_id: int | None, pillar_key: str | None) -> str:
    if not (run_id and pillar_key):
        return ""
    try:
        okr_map = _fetch_okrs_for_run(run_id)
    except Exception:
        return ""
    data = okr_map.get(pillar_key)
    if not data:
        return ""
    lines = []
    obj_text = (data.get("objective") or "").strip()
    if obj_text:
        lines.append(f"*This Quarter Objective:* {obj_text}")
    krs = data.get("krs") or []
    if krs:
        lines.append("")
        lines.append("*Key Results:*")
        for kr in krs[:3]:
            desc = (kr or "").strip()
            if not desc:
                continue
            lines.append(f"• {desc}")
    return "\n".join(lines).strip()

def _format_main_question_for_user(state: dict, pillar: str | None, concept_code: str | None, question_text: str) -> str:
    if not question_text:
        return ""
    num = _ensure_question_number(state, pillar, concept_code, question_text)
    total = _ensure_total_questions(state)
    label = pillar.title() if pillar else "Assessment"
    prefix = f"Q{num}/{total} · {label}"
    return f"{prefix}: {question_text.strip()}"

# --- OKR sync helper: call this AFTER you have saved & committed a PillarResult ---
from app.okr import generate_and_update_okrs_for_pillar
from .config import settings

def _sync_okrs_after_pillar(db, user, assess_session, pillar_result, concept_score_map=None):
    """
    Generates + persists OKRs for a finished pillar.
    Assumes pillar_result is committed and has id, pillar_key, score, advice (optional).
    """
    try:
        res = generate_and_update_okrs_for_pillar(
            db,
            user_id=user.id,
            assess_session_id=assess_session.id,
            pillar_result_id=pillar_result.id,
            pillar_key=pillar_result.pillar_key,
            pillar_score=getattr(pillar_result, "score", None),
            concept_scores=concept_score_map or {},
            write_progress_entries=True,
            quarter_label="This Quarter",
        )
        return res  # { "objective": OKRObjective, "okr_text": str, "okr_struct": dict }
    except Exception as e:
        # Clear any failed transaction on the session we were given so the rest of the flow can continue
        try:
            if hasattr(db, "rollback"):
                db.rollback()
        except Exception:
            pass
        print(f"[okr] WARN: failed to sync OKRs for pillar_id={pillar_result.id}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# Consent helpers
# ──────────────────────────────────────────────────────────────────────────────
def _is_affirmative(text: str) -> bool:
    t = (text or "").strip().lower()
    yeses = {"yes", "y", "yeah", "yep", "agree", "i agree", "ok", "okay", "start", "go", "let's go", "lets go", "sure"}
    return any(t == y or t.startswith(y + " ") for y in yeses)

def _is_negative(text: str) -> bool:
    t = (text or "").strip().lower()
    nos = {"no", "n", "nope", "decline", "stop", "cancel"}
    return any(t == n or t.startswith(n + " ") for n in nos)

def _send_consent_intro(user: User) -> None:
    first_name = (getattr(user, "first_name", None) or "").strip()
    greet = f"Hey {first_name}! " if first_name else "Hey! "
    msg1 = (
        f"{greet}😊 Welcome to your wellbeing journey! 👋🏻\n\n"
        "In a moment we’ll be taking you through a short check-in over WhatsApp. Nothing heavy - just a quick snapshot of how the last 7 days have been across four wellbeing pillars:\n\n"
        "• *Nutrition* – what you’ve been eating and drinking day to day\n"
        "• *Training* – how you’ve been moving and staying active\n"
        "• *Resilience* – how you’re feeling emotionally and coping with stress (share only what feels comfortable — we’re here to support you)\n"
        "• *Recovery* – how you’ve been resting and recharging\n\n"
        "These questions help us build a clear picture of your routine so we can tailor the next steps that actually matter for you."
    )
    msg2 = (
        "Before we get started, I just need to confirm your consent.\n\n"
        "🔒 Your data:\n"
        "Your answers are stored securely and only used to personalise your wellbeing programme.\n"
        "We never share your information with third parties, and you can stop at any time.\n"
        "Replying is optional, and you can request deletion of your data whenever you want.\n\n"
        "If you’re happy to continue, *reply YES* to give consent.\n"
        "If not, *reply NO* to opt out."
    )
    _send_to_user(user, msg1)
    time.sleep(0.2)
    _send_to_user(user, msg2)

def _touch_user_timestamps(s, user: User) -> None:
    now = datetime.utcnow()
    try:
        if getattr(user, "created_on", None) is None:
            setattr(user, "created_on", now)
        setattr(user, "updated_on", now)
        s.commit()
    except Exception:
        pass


def _send_to_user(user: User, text: str) -> bool:
    """Robust send with WhatsApp normalization + logging + clear error surfacing."""
    to = getattr(user, "phone", None)
    msg = (text or "").strip()
    if not msg:
        return False

    channel = (os.getenv("TWILIO_CHANNEL") or "whatsapp").lower().strip()
    to_fmt = to
    if channel == "whatsapp" and to and not str(to).startswith("whatsapp:"):
        to_fmt = f"whatsapp:{to}"

    try:
        # Preferred: (to, message)
        send_message(to_fmt, msg)
        return True
    except TypeError:
        # Some legacy builds expect (message, to)
        try:
            send_message(msg, to_fmt)
            return True
        except TypeError:
            # Try keyword-based call if supported
            try:
                send_message(to=to_fmt, text=msg)
                return True
            except TypeError:
                try:
                    send_message(to=to_fmt, message=msg)
                    return True
                except Exception as e:
                    raise e
    except Exception as e:
        print(f"❌ send_message failed: {e!r} | to={to_fmt} msg={msg[:120]}")
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="send_message", status="error",
                                payload={"to": to_fmt, "text": msg, "admin_target": getattr(user, "phone", None)}, error=str(e)))
                ss.commit()
        except Exception:
            pass
        return False

# Public report URL helper — call api._public_report_url at runtime to avoid import cycles
def _report_url(user_id: int, filename: str) -> str:
    """
    Use the canonical builder from app.api every time; fallback to PUBLIC_BASE_URL/relative.
    """
    try:
        from .api import _public_report_url  # dynamic import prevents circular imports
        return _public_report_url(user_id, filename)
    except Exception:
        base = (os.getenv("PUBLIC_BASE_URL") or "").rstrip("/")
        path = f"/reports/{user_id}/{filename}"
        return f"{base}{path}" if base else path

# Pillar preference mappings (for preamble collection)
PILLAR_PREFERENCE_KEYS = {
    "training": "training_focus",
}


def _get_user_preference_value(user_id: int, key: str) -> Optional[str]:
    if not user_id or not key:
        return None
    with SessionLocal() as db:
        row = db.execute(
            select(UserPreference).where(
                UserPreference.user_id == user_id,
                UserPreference.key == key,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return row.value


def _set_user_preference_value(user_id: int, key: str, value: str | None) -> None:
    if not user_id or not key:
        return
    with SessionLocal() as db:
        row = db.execute(
            select(UserPreference).where(
                UserPreference.user_id == user_id,
                UserPreference.key == key,
            )
        ).scalar_one_or_none()
        if row is None:
            row = UserPreference(user_id=user_id, key=key, value=value or "")
            db.add(row)
        else:
            row.value = value or ""
        try:
            db.commit()
        except Exception:
            db.rollback()

# DB helpers

def _resolve_concept_id(session, pillar_key: str | None, concept_code: str | None) -> Optional[int]:
    if not concept_code:
        return None
    q = select(Concept.id).where(Concept.pillar_key == pillar_key, Concept.code == concept_code)
    return session.execute(q).scalar_one_or_none()

# Resolve concept id and human-readable name
def _resolve_concept_meta(session, pillar_key: str | None, concept_code: str | None):
    if not concept_code:
        return None, None
    row = session.execute(
        select(Concept.id, Concept.name).where(Concept.pillar_key == pillar_key,
                                               Concept.code == concept_code)
    ).first()
    if not row:
        return None, None
    return row[0], row[1]

def _concept_primary_question(session, pillar: str, concept_code: str) -> Optional[str]:
    cid = _resolve_concept_id(session, pillar, concept_code)
    if not cid:
        return None
    row = session.execute(
        select(ConceptQuestion.text)
        .where(ConceptQuestion.concept_id == cid, ConceptQuestion.is_primary == True)
        .limit(1)
    ).scalar_one_or_none()
    return (row or None)


def _concept_bounds(session, pillar: str, concept_code: str):
    """
    Return (zero_score, max_score) for the given concept if both are set, else None.
    zero_score and max_score are integers stored on Concept and define the quantity→score mapping:
    - If zero_score <= max_score: map zero_score→0 and max_score (or more)→100 (linear; clamp outside).
    - If zero_score > max_score: LOWER IS BETTER; map zero_score→0 and max_score (or less)→100 (linear; clamp outside).
    """
    cid = _resolve_concept_id(session, pillar, concept_code)
    if not cid:
        return None
    row = session.execute(
        select(Concept.zero_score, Concept.max_score).where(Concept.id == cid)
    ).first()
    if not row:
        return None
    z, m = row
    if z is None or m is None:
        return None
    try:
        return (int(z), int(m))
    except Exception:
        return None

def _concept_alternates(session, pillar: str, concept_code: str) -> list[str]:
    cid = _resolve_concept_id(session, pillar, concept_code)
    if not cid:
        return []
    rows = session.execute(
        select(ConceptQuestion.text)
        .where(ConceptQuestion.concept_id == cid, ConceptQuestion.is_primary == False)
        .limit(10)
    ).scalars().all()
    return [r for r in rows if (r or "").strip()]

def _load_pillar_concepts(session, cap: int = 5) -> dict[str, list[str]]:
    """
    Returns mapping pillar_key -> list of concept codes (ordered, capped).
    Order: concept.code asc (fallback to name).
    """
    rows = session.execute(select(Concept.pillar_key, Concept.code, Concept.name)).all()
    buckets: dict[str, list[tuple[str, str]]] = {}
    for pillar_key, code, name in rows:
        buckets.setdefault(pillar_key, []).append((code or "", name or ""))
    out: dict[str, list[str]] = {}
    for pk, items in buckets.items():
        items.sort(key=lambda t: (t[0].lower(), t[1].lower()))
        codes = [c for c, _ in items][:cap] if cap else [c for c, _ in items]
        out[pk] = codes
    return out

def _bump_concept_asked(user_id: int, run_id: int, pillar_key: str | None, concept_code: str | None) -> None:
    if not concept_code:
        return
    now = datetime.utcnow()
    with SessionLocal() as s:
        cid, cname = _resolve_concept_meta(s, pillar_key, concept_code)
        if not cid:
            return
        row = s.execute(
            select(UserConceptState).where(
                UserConceptState.user_id == user_id,
                UserConceptState.run_id == run_id,
                UserConceptState.concept_id == cid
            )
        ).scalar_one_or_none()
        if not row:
            row = UserConceptState(
                user_id=user_id,
                run_id=run_id,
                concept_id=cid,
                score=None,
                asked_count=1,
                last_asked_at=now,
                notes=concept_code,
                updated_at=now
            )
            # denormalized fields for grouping/reporting
            try:
                row.pillar_key = pillar_key
            except Exception:
                pass
            try:
                row.concept = cname or _pretty_concept(concept_code)
            except Exception:
                pass
            s.add(row)
        else:
            row.asked_count = int(row.asked_count or 0) + 1
            row.last_asked_at = now
            row.updated_at = now
            # keep denormalized fields fresh
            try:
                row.pillar_key = pillar_key
            except Exception:
                pass
            try:
                row.concept = cname or _pretty_concept(concept_code)
            except Exception:
                pass
        s.commit()


def _maybe_prompt_preamble_question(user: User, state: dict, pillar: str, turns: list[dict]) -> bool:
    question = PILLAR_PREAMBLE_QUESTIONS.get(pillar)
    if not question:
        return False
    pref_map = state.setdefault("pillar_preamble", {})
    status = pref_map.get(pillar) or {}
    if status.get("answered"):
        return False
    awaiting = state.get("awaiting_preamble")
    if awaiting:
        return awaiting == pillar
    pref_map[pillar] = {"asked": True, "answered": False}
    state["awaiting_preamble"] = pillar
    turns.append({
        "role": "assistant",
        "pillar": pillar,
        "question": question,
        "concept": "__preamble__",
        "is_main": False,
    })
    _send_to_user(user, question)
    return True


def _send_first_concept_question_for_pillar(user: User, state: dict, pillar: str, turns: list[dict], db_session) -> bool:
    next_pcodes = state.get("pillar_concepts", {}).get(pillar) or []
    if not next_pcodes:
        _send_to_user(user, f"Setup note: I don’t have {pillar.title()} concepts. Please seed the DB and try again.")
        return False
    next_concept = next_pcodes[0]
    with SessionLocal() as lookup:
        q_next = _concept_primary_question(lookup, pillar, next_concept) or (
            f"Quick start on {next_concept.replace('_', ' ')} — what’s your current approach?"
        )
    display_q = _format_main_question_for_user(state, pillar, next_concept, q_next)
    turns.append({
        "role": "assistant",
        "pillar": pillar,
        "question": q_next,
        "concept": next_concept,
        "is_main": True,
    })
    _send_to_user(user, display_q)
    try:
        _bump_concept_asked(user.id, state.get("run_id"), pillar, next_concept)
    except Exception:
        pass
    try:
        _log_turn(db_session, state, pillar, next_concept, False, q_next, None, None, None, action="ask")
    except Exception:
        pass
    return True

def _update_concepts_from_scores(user_id: int, pillar_key: str, scores: dict[str, float],
                                 q_by_code: dict[str, str] | None = None,
                                 a_by_code: dict[str, str] | None = None,
                                 conf_by_code: dict[str, float] | None = None,
                                 notes_by_code: dict[str, dict] | None = None,
                                 run_id: int | None = None) -> None:
    """
    # NOTE: This function now records the latest score for each concept (no running average).
    """
    if not run_id:
        # Without run_id we cannot maintain per-run rows; bail safely
        return
    now = datetime.utcnow()
    with SessionLocal() as s:
        for code, val in (scores or {}).items():
            cid, cname = _resolve_concept_meta(s, pillar_key, code)
            if not cid:
                continue
            try:
                v = float(val or 0.0)
            except Exception:
                v = 0.0
            row = s.execute(
                select(UserConceptState).where(
                    UserConceptState.user_id == user_id,
                    UserConceptState.run_id == run_id,
                    UserConceptState.concept_id == cid
                )
            ).scalar_one_or_none()
            if not row:
                row = UserConceptState(
                    user_id=user_id, concept_id=cid, run_id=run_id, score=v, asked_count=0,
                    last_asked_at=None, notes=code, updated_at=now
                )
                # denormalized grouping fields
                try:
                    row.pillar_key = pillar_key
                except Exception:
                    pass
                try:
                    row.concept = cname or _pretty_concept(code)
                except Exception:
                    pass
                if q_by_code and code in q_by_code:
                    try:
                        row.question = q_by_code.get(code) or ""
                    except Exception:
                        pass
                if a_by_code and code in a_by_code:
                    try:
                        row.answer = a_by_code.get(code) or ""
                    except Exception:
                        pass
                if conf_by_code and code in conf_by_code:
                    try:
                        val_conf = conf_by_code.get(code)
                        row.confidence = float(val_conf) if val_conf is not None else None
                    except Exception:
                        pass
                if notes_by_code and code in notes_by_code:
                    import json as _json  # local alias to avoid top-level import edits
                    base_notes = {}
                    try:
                        if getattr(row, "notes", None):
                            s_val = str(row.notes).strip()
                            if s_val.startswith("{"):
                                base_notes = _json.loads(s_val)
                    except Exception:
                        base_notes = {}
                    try:
                        add_notes = notes_by_code.get(code) or {} if notes_by_code else {}
                        if isinstance(add_notes, dict):
                            base_notes.update(add_notes)
                    except Exception:
                        pass
                    try:
                        row.notes = _json.dumps(base_notes)
                    except Exception:
                        row.notes = str(base_notes)
                s.add(row)
            else:
                # Store the latest score (no averaging). `asked_count` remains an engagement metric only.
                row.score = v
                row.updated_at = now
                row.run_id = run_id
                # denormalized grouping fields
                try:
                    row.pillar_key = pillar_key
                except Exception:
                    pass
                try:
                    row.concept = cname or _pretty_concept(code)
                except Exception:
                    pass
                if q_by_code and code in q_by_code:
                    try:
                        row.question = q_by_code.get(code) or ""
                    except Exception:
                        pass
                if a_by_code and code in a_by_code:
                    try:
                        row.answer = a_by_code.get(code) or ""
                    except Exception:
                        pass
                if conf_by_code and code in conf_by_code:
                    try:
                        val_conf = conf_by_code.get(code)
                        row.confidence = float(val_conf) if val_conf is not None else None
                    except Exception:
                        pass
                if notes_by_code and code in notes_by_code:
                    import json as _json  # local alias to avoid top-level import edits
                    base_notes = {}
                    try:
                        if getattr(row, "notes", None):
                            s_val = str(row.notes).strip()
                            if s_val.startswith("{"):
                                base_notes = _json.loads(s_val)
                    except Exception:
                        base_notes = {}
                    try:
                        add_notes = notes_by_code.get(code) or {} if notes_by_code else {}
                        if isinstance(add_notes, dict):
                            base_notes.update(add_notes)
                    except Exception:
                        pass
                    try:
                        row.notes = _json.dumps(base_notes)
                    except Exception:
                        row.notes = str(base_notes)
        s.commit()


# Persist/Update a PillarResult row for the current run/pillar
# Persist/Update a PillarResult row for the current run/pillar (isolated session + full JobAudit)
def _upsert_pillar_result(_unused_session, run_id: int, pillar_key: str, overall: int,
                          concept_scores: dict, feedback_text: str, user_id: Optional[int] = None) -> None:
    """
    Defensive upsert for PillarResult keyed by (run_id, pillar_key).
    - Always sets user_id (NOT NULL in schema).
    - Uses its own session so failures don't roll back the caller's session.
    - Writes native dicts to JSON/JSONB columns.
    - Emits JobAudit 'ok' with row_id on success; 'error' with details on failure.
    """
    try:
        with SessionLocal() as ss:
            row = ss.execute(
                select(PillarResult).where(
                    PillarResult.run_id == run_id,
                    PillarResult.pillar_key == pillar_key
                )
            ).scalars().first()
            created = False
            if not row:
                row = PillarResult(run_id=run_id, pillar_key=pillar_key)
                ss.add(row)
                created = True

            # Required fields
            if hasattr(row, "user_id"):
                setattr(row, "user_id", int(user_id) if user_id is not None else None)
            if hasattr(row, "overall"):
                setattr(row, "overall", int(overall) if overall is not None else None)
            if hasattr(row, "concept_scores"):
                # Prefer native dict for JSON/JSONB columns
                setattr(row, "concept_scores", concept_scores or {})

            # Optional explanatory fields
            if hasattr(row, "advice"):
                setattr(row, "advice", feedback_text or "")
            if hasattr(row, "updated_at"):
                setattr(row, "updated_at", datetime.utcnow())

            if created:
                ss.flush()  # assign PK
            ss.refresh(row)
            ss.commit()

        # Success audit
        try:
            with SessionLocal() as log_s:
                log_s.add(JobAudit(
                    job_name="pillar_result_upsert",
                    status="ok",
                    payload={
                        "row_id": getattr(row, "id", None),
                        "run_id": run_id,
                        "pillar": pillar_key,
                        "user_id": int(user_id) if user_id is not None else None,
                        "overall": int(overall) if overall is not None else None
                    }
                ))
                log_s.commit()
        except Exception:
            pass
    except Exception as e:
        # Error audit; never break the user flow
        try:
            with SessionLocal() as log_s:
                log_s.add(JobAudit(
                    job_name="pillar_result_upsert",
                    status="error",
                    payload={
                        "run_id": run_id,
                        "pillar": pillar_key,
                        "user_id": int(user_id) if user_id is not None else None,
                        "overall": int(overall) if overall is not None else None
                    },
                    error=str(e)
                ))
                log_s.commit()
        except Exception:
            pass

# pillar_result: your saved PillarResult row
# assess_session: the current AssessSession
# user: the owner user

# Feedback
def _generate_feedback(pillar_name: str, level: str, recent_turns: list[dict]) -> str:
    try:
        content = _llm.invoke([
            {"role": "system", "content": FEEDBACK_SYSTEM},
            {"role": "user", "content": json.dumps({
                "pillar": pillar_name,
                "level": level,
                "recent": recent_turns[-10:],
            }, ensure_ascii=False)},
        ]).content
    except Exception:
        content = ""
    msg = (content or "").strip()
    if not msg:
        return f"Feedback: {pillar_name} looks {level}. Next steps: keep it simple and consistent."
    return msg[:700]

# Clarifier regeneration (LLM-only; no deterministic text)
def _regen_clarifier(pillar: str, concept_code: str, payload: dict) -> str:
    """Ask the LLM explicitly to produce a fresh clarifier question (<=320 chars).
    Returns an empty string on error."""
    CLARIFIER_SYSTEM = (
        "You are drafting clarifying questions in a health-assessment chat.\n"
        "When a user's reply is vague or incomplete, ask a clarifying question that moves the dialog forward.\n"
        "Guidance (give the model freedom, but avoid repetition):\n"
        "- Prefer asking for what seems missing (e.g., number of days, portions per day, amount per day, timeframe).\n"
        "- Do not simply repeat or paraphrase the original main question; change the angle and narrow the ask.\n"
        "- Focus the question so the next reply is scorable (ideally a numeric value with a recent timeframe).\n"
        "- Keep it concise (<= 280 chars), plain language.\n"
        "- It's okay to ask more than one detail **only if truly necessary**, but avoid piling on.\n"
        "\n"
        "Examples (good):\n"
        "Main: 'In the last 7 days, how many days did you eat processed foods, and how many portions per day?'\n"
        "User: 'Occasionally'\n"
        "Clarifier: 'Over the past 7 days, on about how many days did you have processed foods?'\n"
        "\n"
        "Main: 'How many glasses of water per day did you usually drink in the last 7 days?'\n"
        "User: 'A few'\n"
        "Clarifier: 'Roughly how many glasses per day did you drink over those 7 days?'\n"
        "\n"
        "Main: 'In the last 7 days, on how many days did you do cardio for 20+ minutes?'\n"
        "User: 'Most days'\n"
        "Clarifier: 'Approximately how many days (0–7) did you do 20+ minutes of cardio?'\n"
        "\n"
        "Bad (avoid): Repeating the full main question verbatim; asking two or more different things when one will do.\n"
    )
    try:
        # Log request shape
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="clarifier_request", status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                         "hist_len": len(payload.get("history", [])),
                                         "asked_len": len(payload.get("already_asked", []))}))
                ss.commit()
        except Exception:
            pass

        resp_obj = _llm.invoke([
            {"role": "system", "content": CLARIFIER_SYSTEM},
            {"role": "user", "content": json.dumps({
                "pillar": pillar,
                "concept": concept_code,
                "history": payload.get("history", []),
                "already_asked": payload.get("already_asked", []),
                "already_asked_norm": payload.get("already_asked_norm", []),
                "retrieval": payload.get("retrieval", []),
                "main_question": payload.get("main_question", ""),
                "last_user_reply": payload.get("last_user_reply", ""),
                "what_seems_missing": payload.get("missing", [])
            }, ensure_ascii=False)},
        ])
        resp = getattr(resp_obj, "content", "") or ""
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="clarifier_response", status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                         "has_content": bool(resp), "len": len(resp or "")}))
                ss.commit()
        except Exception:
            pass
    except Exception as e:
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="clarifier_exception", status="error",
                                payload={"pillar": pillar, "concept": concept_code},
                                error=f"{e!r}\n{traceback.format_exc(limit=2)}"))
                ss.commit()
        except Exception:
            pass
        return ""
    q = (resp or "").strip().strip('"').strip()
    return q[:320]

# Force-finish when numeric answer + timeframe are present, but the model hesitates
def _force_finish(pillar: str, concept_code: str, payload: dict, extra_rules: str = "", bounds=None) -> str:
    """
    Ask the LLM to return a FINISH JSON when the user's answer appears sufficient (numeric + timeframe).
    Returns raw JSON string (model content) or empty string on error.
    """
    FORCE_SYSTEM = (
        "You already have enough to score this concept.\n"
        "The user's reply contains a NUMBER and the main question supplied the timeframe (e.g., last 7 days).\n"
        "Return JSON for FINISH with: {\"action\":\"finish\",\"question\":\"\",\"level\":\"Low|Moderate|High\",\"confidence\":<float 0.0–1.0>,\"rationale\":\"\",\"scores\":{}}.\n"
        "Set confidence 0.80–0.95 in this force-finish case (numeric + explicit timeframe). Do NOT copy example values; set confidence per this rule.\n"
        "Do NOT ask another question. Do NOT include extra text outside JSON."
    )
    try:
        # Log request
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="force_finish_request", status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                        "hist_len": len(payload.get("history", [])),
                                        "retrieval_len": len(payload.get("retrieval", [])),
                                        "has_range_guide": bool(extra_rules),
                                        "range_bounds": list(bounds) if bounds else None}))
                ss.commit()
        except Exception:
            pass

        resp_obj = _llm.invoke([
            {"role": "system", "content": FORCE_SYSTEM},
            {"role": "user", "content": json.dumps({
                "pillar": pillar,
                "concept": concept_code,
                "history": payload.get("history", []),
                "retrieval": payload.get("retrieval", []),
                "extra_rules": (extra_rules or "")      
            }, ensure_ascii=False)},
        ])
        resp = getattr(resp_obj, "content", "") or ""
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="force_finish_response", status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                         "has_content": bool(resp), "len": len(resp or "")}))
                ss.commit()
        except Exception:
            pass
        return (resp or "")
    except Exception as e:
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="_force_finish", status="error",
                                payload={"pillar": pillar, "concept": concept_code},
                                error=f"{e!r}\n{traceback.format_exc(limit=2)}"))
                ss.commit()
        except Exception:
            pass
        return ""

# ──────────────────────────────────────────────────────────────────────────────
# LLM
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class StepResult:
    action: Literal["ask", "finish_domain"]
    question: str
    level: str
    confidence: float
    rationale: str
    scores: dict
    status: str = ""
    why: str = ""
    missing: list = None
    parsed_value: dict = None

def _parse_llm_json(s: str) -> StepResult:
    try:
        m = re.search(r"\{.*\}", s or "", re.S)
        j = json.loads(m.group(0)) if m else {}
    except Exception:
        j = {}
    act = j.get("action", "ask")
    if act == "finish":
        act = "finish_domain"
    return StepResult(
        action=act if act in ("ask", "finish_domain") else "ask",
        question=(j.get("question") or "").strip(),
        level=(j.get("level") or "Moderate"),
        confidence=float(j.get("confidence", 0.0) or 0.0),
        rationale=(j.get("rationale") or "").strip(),
        scores=j.get("scores") if isinstance(j.get("scores"), dict) else {},
        status=(j.get("status") or "").strip(),
        why=(j.get("why") or "").strip(),
        missing=j.get("missing") if isinstance(j.get("missing"), list) else [],
        parsed_value=j.get("parsed_value") if isinstance(j.get("parsed_value"), dict) else {}
    )

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def get_active_domain(user: User) -> Optional[str]:
    with SessionLocal() as s:
        sess = (
            s.query(AssessSession)
             .filter(AssessSession.user_id == user.id,
                     AssessSession.domain == "combined",
                     AssessSession.is_active == True)
             .order_by(AssessSession.id.desc())
             .first()
        )
        return "combined" if sess else None

def _start_or_get_run(s, user: User, state: dict) -> int:
    run_id = state.get("run_id")
    if run_id:
        return run_id
    run = AssessmentRun(user_id=user.id, domain="combined")
    s.add(run); s.commit(); s.refresh(run)
    state["run_id"] = run.id
    state["turn_idx"] = 0
    try:
        _rv_start_run(run_id=run.id, user_id=user.id, domain="combined")
    except Exception:
        pass
    return run.id

def _log_turn(s, state, pillar, concept_code, is_clarifier, assistant_q, user_a, retrieval, llm_raw, action=None, confidence=None):
    run_id = state.get("run_id")
    idx = int(state.get("turn_idx", 0)) + 1
    t = AssessmentTurn(
        run_id=run_id, idx=idx, pillar=pillar, concept_key=concept_code,
        is_clarifier=bool(is_clarifier),
        assistant_q=assistant_q, user_a=user_a,
        retrieval=retrieval, llm_raw=llm_raw, action=action, confidence=confidence
    )
    try:
        s.add(t); s.commit()
    except IntegrityError as e:
        s.rollback()
        existing = s.execute(
            select(AssessmentTurn).where(
                AssessmentTurn.run_id == run_id,
                AssessmentTurn.idx == idx
            )
        ).scalars().first()
        if existing:
            existing.pillar = pillar
            existing.concept_key = concept_code
            existing.is_clarifier = bool(is_clarifier)
            existing.assistant_q = assistant_q
            existing.user_a = user_a
            existing.retrieval = retrieval
            existing.llm_raw = llm_raw
            existing.action = action
            existing.confidence = confidence
            s.commit()
        else:
            raise e
    # Log meta for debugging
    try:
        with SessionLocal() as ss:
            ss.add(JobAudit(job_name="assessor_meta",
                            status="ok",
                            payload={"pillar": pillar, "concept": concept_code,
                                     "action": action, "confidence": confidence}))
            ss.commit()
    except Exception:
        pass
    state["turn_idx"] = idx
    try:
        _rv_log_turn(run_id=run_id, idx=idx, pillar=pillar, concept_key=concept_code,
                     assistant_q=assistant_q, user_a=user_a, retrieval=retrieval,
                     llm_raw=llm_raw, action=action, confidence=confidence)
    except Exception:
        pass

def _commit_state(s, sess: AssessSession, state: dict) -> None:
    try:
        sess.state = json.dumps(state)
    except Exception:
        sess.state = state
    try:
        setattr(sess, "updated_at", datetime.utcnow())
    except Exception:
        pass
    s.commit()


def _next_pillar(curr: str) -> Optional[str]:
    try:
        i = PILLAR_ORDER.index(curr)
    except ValueError:
        return None
    return PILLAR_ORDER[i + 1] if i + 1 < len(PILLAR_ORDER) else None

def start_combined_assessment(user: User, *, force_intro: bool = False):
    """Start combined assessment (Nutrition → Training → Resilience → Recovery)."""
    with SessionLocal() as s:
        _touch_user_timestamps(s, user)

        # Consent gate: fetch fresh user in this session to avoid stale consent flag
        u = s.query(User).get(getattr(user, "id", None)) or user
        if not _user_has_full_name(u):
            _send_to_user(u, "Before we begin, please reply with your first and last name (e.g., 'Sam Smith'). Once we have that, I'll walk you through a few quick consent steps and the first question.")
            return False

        # Accept any of these as valid consent signals (back-compat safe):
        # - consent_given is True
        # - consent_at timestamp exists (new field)
        # - consent_yes_at timestamp exists (legacy field)
        has_consent = bool(getattr(u, "consent_given", False)) \
                      or bool(getattr(u, "consent_at", None)) \
                      or bool(getattr(u, "consent_yes_at", None))

        # If forcing intro, clear consent so we wait for a fresh YES/NO before proceeding.
        if force_intro:
            try:
                u.consent_given = False
                if hasattr(u, "consent_at"):
                    setattr(u, "consent_at", None)
                if hasattr(u, "consent_yes_at"):
                    setattr(u, "consent_yes_at", None)
                s.commit()
            except Exception:
                s.rollback()
            has_consent = False

        # If consent is missing, send intro and wait for YES/NO before proceeding.
        if not has_consent:
            _send_consent_intro(u)
            return True

        # Deactivate existing combined sessions
        s.execute(
            update(AssessSession)
            .where(AssessSession.user_id == user.id,
                   AssessSession.domain == "combined",
                   AssessSession.is_active == True)
            .values(is_active=False, updated_at=datetime.utcnow())
        )

        # Init state
        state = {
            "turns": [],
            "current": "nutrition",
            "results": {},
            "turn_idx": 0,
            "run_id": None,
            "concept_idx": {"nutrition": 0, "training": 0, "resilience": 0, "recovery": 0},
            "concept_scores": {"nutrition": {}, "training": {}, "resilience": {}, "recovery": {}},
            "kb_used": {"nutrition": {}, "training": {}, "resilience": {}, "recovery": {}},
            "pillar_concepts": {},  # will be loaded from DB
            "concept_progress": {"nutrition": {}, "training": {}, "resilience": {}, "recovery": {}},
            "question_seq": 0,
            "question_numbers": {},
            "total_questions": 0,
        }
        sess = AssessSession(user_id=user.id, domain="combined", is_active=True, turn_count=0, state=state)
        s.add(sess); s.commit(); s.refresh(sess)

        # Load concepts from DB once for this session
        with SessionLocal() as s_lookup:
            state["pillar_concepts"] = _load_pillar_concepts(s_lookup, cap=MAIN_QUESTIONS_PER_PILLAR)
            _ensure_total_questions(state)

        # Start run
        _start_or_get_run(s, user, state)

        # First concept + main question
        pillar = "nutrition"
        concepts_for_pillar = state["pillar_concepts"].get(pillar) or []
        if not concepts_for_pillar:
            _send_to_user(user, "Setup note: I don’t have Nutrition concepts. Please seed the DB and try again.")
            _commit_state(s, sess, state)
            return True

        first_concept = concepts_for_pillar[0]
        # init progress for first concept
        state["concept_progress"]["nutrition"][first_concept] = {
            "main_asked": True,
            "clarifiers": 0,
            "scored": False,
            "summary_logged": False,
        }
        with SessionLocal() as s2:
            q = _concept_primary_question(s2, pillar, first_concept) or "How many meals and snacks do you typically have on a usual day?"
        display_q = _format_main_question_for_user(state, pillar, first_concept, q)
        state["turns"].append({"role": "assistant", "pillar": pillar, "question": q, "concept": first_concept, "is_main": True})
        _commit_state(s, sess, state)
        _send_to_user(user, display_q)
        # Mark this concept as asked so user_concept_state.last_asked_at is set for the first concept
        try:
            _bump_concept_asked(user.id, state.get("run_id"), pillar, first_concept)
        except Exception:
            pass
        _log_turn(s, state, pillar, first_concept, False, q, None, None, None, action="ask")
        _commit_state(s, sess, state)
        return True

def continue_combined_assessment(user: User, user_text: str) -> bool:
    with SessionLocal() as s:
        _touch_user_timestamps(s, user)

        # Ensure name captured before proceeding
        db_user = s.query(User).get(getattr(user, "id", None)) or s.merge(user)
        if not _user_has_full_name(db_user):
            if _capture_name_from_text(s, db_user, user_text):
                first = (getattr(db_user, "first_name", "") or "").strip()
                _send_to_user(user, f"Thanks {first}! Reply 'start' to kick things off.")
            else:
                _send_to_user(user, "Please include both first and last name (e.g., 'Sam Smith') so we can continue.")
            return True

        # If consent hasn't been recorded in DB, interpret this message as the consent response.
        has_consent = bool(getattr(db_user, "consent_given", False)) \
                      or bool(getattr(db_user, "consent_at", None)) \
                      or bool(getattr(db_user, "consent_yes_at", None))

        if not has_consent:
            msg = (user_text or "").strip()
            if _is_affirmative(msg):
                try:
                    # Persist consent with both new and legacy fields for back-compat.
                    db_user.consent_given = True
                    now_ts = datetime.utcnow()
                    try:
                        db_user.consent_at = now_ts
                    except Exception:
                        pass
                    try:
                        db_user.consent_yes_at = now_ts
                    except Exception:
                        pass
                    s.commit()
                except Exception:
                    s.rollback()
                confirm_name = (getattr(db_user, "first_name", "") or "").strip()
                prefix = f"Thanks {confirm_name}! " if confirm_name else "Thanks! "
                _send_to_user(user, f"{prefix}Your consent is recorded — I’ll start with Nutrition now. These are short check-in questions about the last 7 days; you can type *redo* or *restart* any time.")
                return start_combined_assessment(user, force_intro=False)
            elif _is_negative(msg):
                _send_to_user(user, "No problem. If you change your mind, just reply YES to begin.")
                return True
            else:
                # Re-prompt consent with context
                _send_consent_intro(user)
                return True

        sess: Optional[AssessSession] = s.execute(
            select(AssessSession).where(
                AssessSession.user_id == user.id,
                AssessSession.domain == "combined",
                AssessSession.is_active == True,
            )
        ).scalars().first()
        if not sess:
            return False

        try:
            state = json.loads(sess.state or "{}")
        except Exception:
            state = {"turns": [], "current": "nutrition", "results": {}}
        if not isinstance(state.get("question_numbers"), dict):
            state["question_numbers"] = {}
        try:
            state["question_seq"] = int(state.get("question_seq") or 0)
        except Exception:
            state["question_seq"] = 0
        if not isinstance(state.get("pillar_concepts"), dict):
            state["pillar_concepts"] = {}
        _ensure_total_questions(state)
        if not isinstance(state.get("turns"), list):
            state["turns"] = []
        turns = state["turns"]
        if not isinstance(state.get("pillar_preamble"), dict):
            state["pillar_preamble"] = {}
        if "awaiting_preamble" not in state:
            state["awaiting_preamble"] = None
        pref_cache = state["pillar_preamble"]

        # quick commands
        cmd = (user_text or "").strip().lower()

        if cmd in {"report", "pdf", "report please", "send report", "pdf report", "dashboard", "image report"}:
            dash_link = _report_url(user.id, "latest.html")
            _send_to_user(
                user,
                f"Your Wellbeing dashboard: {dash_link}\n(*Type 'Dashboard' any time to view it again.*)",
            )
            return True

        # Quick correction command — "redo last"
        # Re-asks the most recent main question so the next reply overwrites that concept's answer.
        if cmd in {"redo", "redo last", "redo last question", "redo question"}:
            turns = state["turns"]
            concept_progress = state.setdefault("concept_progress", {
                "nutrition": {}, "training": {}, "resilience": {}, "recovery": {}
            })
            concept_scores = state.setdefault("concept_scores", {
                "nutrition": {}, "training": {}, "resilience": {}, "recovery": {}
            })
            concept_idx_map = state.setdefault("concept_idx", {
                "nutrition": 0, "training": 0, "resilience": 0, "recovery": 0
            })
            qa_snapshots = state.setdefault("qa_snapshots", {})

            last_answer_idx = None
            last_answer_pillar = None
            for idx in range(len(turns) - 1, -1, -1):
                t = turns[idx]
                if t.get("role") == "user":
                    last_answer_idx = idx
                    last_answer_pillar = t.get("pillar") or state.get("current", "nutrition")
                    break
            search_range = range(len(turns) - 1, -1, -1)
            if last_answer_idx is not None:
                search_range = range(last_answer_idx - 1, -1, -1)
            last_main = None
            last_any_q = None
            target_idx = None
            for i in search_range:
                t = turns[i]
                if t.get("role") != "assistant" or not t.get("question"):
                    continue
                if last_answer_pillar and t.get("pillar") not in {None, last_answer_pillar}:
                    continue
                if last_any_q is None:
                    last_any_q = t
                    target_idx = i
                if t.get("is_main"):
                    last_main = t
                    target_idx = i
                    break
            target = last_main or last_any_q
            if target and target.get("question"):
                target_pillar = target.get("pillar") or state.get("current", "nutrition")
                target_concept = target.get("concept")
                q_text = target.get("question")
                # Drop any turns captured after the original question so we get a clean redo
                if target_idx is not None:
                    turns[:] = turns[:target_idx]
                state["current"] = target_pillar

                # Reset progress + scores for this concept so the new answer replaces the old one
                pillar_prog = concept_progress.setdefault(target_pillar, {})
                if target_concept is None:
                    # Use a placeholder when concept metadata is missing
                    concept_key = "__anon__"
                else:
                    concept_key = target_concept
                cprog = pillar_prog.setdefault(concept_key, {
                    "main_asked": True, "clarifiers": 0, "scored": False, "summary_logged": False
                })
                cprog["clarifiers"] = 0
                cprog["scored"] = False
                cprog["summary_logged"] = False
                cprog["main_asked"] = True

                if target_concept:
                    concept_scores.setdefault(target_pillar, {}).pop(target_concept, None)
                    try:
                        qa_snapshots.get(target_pillar, {}).pop(target_concept, None)
                    except Exception:
                        pass

                pillar_concepts = (state.get("pillar_concepts") or {}).get(target_pillar, []) or []
                if target_concept and target_concept in pillar_concepts:
                    concept_idx_map[target_pillar] = pillar_concepts.index(target_concept)
                else:
                    concept_idx_map[target_pillar] = max(0, int(concept_idx_map.get(target_pillar, 0)) - 1)

                _send_to_user(user, "Okay — let’s redo that one. Please answer again:")

                turns.append({
                    "role": "assistant",
                    "pillar": target_pillar,
                    "question": q_text,
                    "concept": target_concept,
                    "is_main": True
                })
                display_q = _format_main_question_for_user(state, target_pillar, target_concept, q_text)
                _commit_state(s, sess, state)
                _send_to_user(user, display_q)
                try:
                    _log_turn(s, state, target_pillar, target_concept, False, q_text, None, None, None, action="ask", confidence=None)
                except Exception:
                    pass
                return True
            else:
                _send_to_user(user, "Sorry — I couldn't find the last question to redo. We'll continue from here.")
                _commit_state(s, sess, state)
                return True

        if cmd in {"restart", "restart assessment", "start over", "reset"}:
            try:
                if sess:
                    sess.is_active = False
                    _commit_state(s, sess, state)
            except Exception:
                pass
            _send_to_user(user, "Okay — restarting from the beginning. Let's start fresh.")
            start_combined_assessment(user, force_intro=True)
            return True

        awaiting_pillar = state.get("awaiting_preamble")
        if awaiting_pillar:
            reply = (user_text or "").strip()
            if not reply:
                _send_to_user(user, "Just a short note on your focus will help tailor this pillar—feel free to type it or say skip.")
                return True
            if reply.lower() in {"skip", "no", "none"}:
                reply = ""
            pref_key = PILLAR_PREFERENCE_KEYS.get(awaiting_pillar)
            if pref_key:
                _set_user_preference_value(user.id, pref_key, reply)
            pref_map = state.setdefault("pillar_preamble", {})
            pref_map[awaiting_pillar] = {"asked": True, "answered": True, "answer": reply}
            state["awaiting_preamble"] = None
            turns.append({"role": "user", "pillar": awaiting_pillar, "text": reply, "is_preamble": True})
            ack = "Thanks — I’ll keep that in mind."
            if awaiting_pillar == "training":
                ack = "Thanks — I'll shape Training around that focus."
            _send_to_user(user, ack)
            if not _send_first_concept_question_for_pillar(user, state, awaiting_pillar, turns, s):
                _commit_state(s, sess, state)
                return True
            _commit_state(s, sess, state)
            return True

        pillar = state.get("current", "nutrition")
        concept_idx_map = state.get("concept_idx", {})
        concept_scores = state.get("concept_scores", {})
        kb_used = state.get("kb_used", {})
        turns = state["turns"]
        concept_progress = state.get("concept_progress", {})
        if not concept_progress:
            concept_progress = {"nutrition": {}, "training": {}, "resilience": {}, "recovery": {}}
            state["concept_progress"] = concept_progress

        # Ensure pillar_concepts present (reload if missing)
        pcmap = state.get("pillar_concepts") or {}
        if not pcmap:
            with SessionLocal() as s_lookup:
                pcmap = _load_pillar_concepts(s_lookup, cap=MAIN_QUESTIONS_PER_PILLAR)
                state["pillar_concepts"] = pcmap

        pillar_concepts = pcmap.get(pillar) or []
        if not pillar_concepts:
            nxt = _next_pillar(pillar)
            if nxt:
                state["current"] = nxt
                _send_to_user(user, f"Skipping {pillar.title()} (no concepts configured). Moving to {nxt.title()}.")
                _commit_state(s, sess, state)
                return True
            else:
                _send_to_user(user, "No concepts configured. Please seed the DB and try again.")
                _commit_state(s, sess, state)
                return True

        if _maybe_prompt_preamble_question(user, state, pillar, turns):
            _commit_state(s, sess, state)
            return True

        # Start run if needed
        _start_or_get_run(s, user, state)

        # Active concept = last assistant main in this pillar; if none, first unasked
        concept_code = None
        for t in reversed(turns):
            if t.get("pillar") == pillar and t.get("role") == "assistant" and t.get("is_main"):
                concept_code = t.get("concept"); break
        if not concept_code:
            # pick first concept whose main hasn't been asked yet
            seen = concept_progress.get(pillar, {})
            concept_code = next((c for c in pillar_concepts if not seen.get(c, {}).get("main_asked")), pillar_concepts[0])
            # mark main asked to anchor flow
            concept_progress.setdefault(pillar, {}).setdefault(concept_code, {
                "main_asked": True, "clarifiers": 0, "scored": False, "summary_logged": False
            })

        # Record user reply (+ inbound log)
        msg = (user_text or "").strip()
        ack_text = _format_acknowledgement(msg, state, pillar, user)
        turns.append({"role": "user", "pillar": pillar, "text": msg})
        # Log the user's answer bound to the last asked question for this pillar/concept
        try:
            last_q_for_log = None
            for t in reversed([t for t in turns if t.get("pillar") == pillar]):
                if t.get("role") == "assistant" and (t.get("question") or t.get("text")):
                    last_q_for_log = t.get("question") or t.get("text")
                    break
            if last_q_for_log:
                _log_turn(s, state, pillar, concept_code, False, last_q_for_log, msg, None, None, action="answer")
        except Exception:
            pass
     
        # Retrieval for this concept
        retrieval_ctx = []
        try:
            last_q = ""
            for t in reversed(turns):
                if t.get("pillar") == pillar and t.get("question"):
                    last_q = t.get("question"); break
            raw_snips = retrieve_snippets(pillar=pillar, concept_key=concept_code, query_text=f"{last_q} {msg}")
            retrieval_ctx = diversify(raw_snips, max_total=5) or []
        except Exception:
            retrieval_ctx = []

        # Accumulate KB used (de-duped)
        kb_bucket = kb_used.setdefault(pillar, {}).setdefault(concept_code, [])
        seen = set((sni.get("id") or (sni.get("title"), sni.get("text"))) for sni in kb_bucket)
        for sni in (retrieval_ctx or []):
            k = sni.get("id") or (sni.get("title"), sni.get("text"))
            if k in seen:
                continue
            kb_bucket.append(sni); seen.add(k)
        kb_used[pillar][concept_code] = kb_bucket

        # LLM payload
        pillar_turns = [t for t in turns if t.get("pillar") == pillar]
        already_asked = [t.get("question") for t in pillar_turns if t.get("role") == "assistant" and t.get("question")]
        already_asked_norm = list({_norm(q) for q in already_asked if q})
        dialogue = _as_dialogue_simple(pillar_turns)
        # Sufficiency hint: if the user gave a number and the main question already had a last-7-days timeframe,
        # nudge the LLM to prefer finishing with a score.
        try:
            # Find the last assistant question for this pillar/concept
            last_q = ""
            for t in reversed(pillar_turns):
                if t.get("role") == "assistant" and (t.get("question") or t.get("text")):
                    last_q = t.get("question") or t.get("text")
                    break
        except Exception:
            last_q = ""
        has_number = _has_numeric_signal(msg or "")
        q_has_week = _has_recent_week_window(last_q or "")
        payload = {
            "history": dialogue[-10:],
            "already_asked": already_asked,
            "already_asked_norm": already_asked_norm,
            "turns_so_far": sum(1 for t in turns if t.get("pillar") == pillar and t.get("role") == "user"),
            "retrieval": retrieval_ctx,
            "concept_focus": concept_code,
            "sufficient_for_scoring": bool(has_number and q_has_week),
        }

        # Audit payload for debugging
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="assessor_payload", status="ok", payload={"pillar": pillar, "concept": concept_code, "payload": payload}))
                ss.commit()
        except Exception:
            pass

        # Build system/user messages (for logging sizes) and invoke with diagnostics
        _system_msg = _system_for(pillar, concept_code)

        # If the concept defines numeric bounds (zero_score/max_score), add a concise scoring guide
        bm_tuple = None
        range_rule_text = ""
        try:
            with SessionLocal() as s_bounds:
                bm_tuple = _concept_bounds(s_bounds, pillar, concept_code)
            if bm_tuple:
                z, m = bm_tuple
                if z <= m:
                    range_rule_text = (
                        "SCORING_RANGE_GUIDE:\n"
                        "- Higher is better; map linearly to 0–100.\n"
                        f"- {z} → 0; {m}+ → 100; clamp outside bounds.\n"
                        "- Treat 'none', 'no', 'zero', or 0 as numeric 0.\n"
                        "- Parse number words (e.g., 'three', 'couple') when digits not given.\n"
                        f"- In your JSON, put only the active concept key: \"scores\": {{ \"{concept_code}\": <0-100 integer> }}.\n"
                    )
                else:
                    # Example target for directional clarity (e.g., processed_food 4→0,0→100 => 1 ≈ 75)
                    example_val = m + ((z - m) * 0.25)
                    try:
                        example_score = max(0, min(100, round(((z - example_val) / (z - m)) * 100)))
                    except Exception:
                        example_score = 75
                    range_rule_text = (
                        "SCORING_RANGE_GUIDE:\n"
                        "- Lower is better; map linearly to 0–100.\n"
                        f"- {z} → 0; {m} or less → 100; clamp outside bounds.\n"
                        "- Treat 'none', 'no', 'zero', or 0 as numeric 0 (which should map near 100 here).\n"
                        "- Parse number words (e.g., 'three', 'couple') when digits not given.\n"
                        f"- Example: if the answer is ~{example_val:.1f}, score around {example_score}.\n"
                        f"- In your JSON, put only the active concept key: \"scores\": {{ \"{concept_code}\": <0-100 integer> }}.\n"
                    )
            else:
                print(f"[range] no bounds for {pillar}.{concept_code}")
        except Exception as e:
            print(f"[range] failed to load bounds for {pillar}.{concept_code}: {e!r}")
            bm_tuple = None
            range_rule_text = ""

        # General scoring rules (wrapped to avoid dangling string literals)
        general_rules = (
            "GENERAL_SCORING_RULES:\n"
            "- If bounds (zero_score, max_score) are provided, they OVERRIDE heuristics and KB for polarity (higher vs lower is better).\n"
            "- When bounds are provided AND the user's answer is numeric (or parsed_number is present), compute the score linearly using those bounds; do not choose your own rubric.\n"
            "- Treat 'none', 'no', 'zero', or 0 as numeric 0.\n"
            "- Zero scores are valid; do NOT up-bias zero to a non-zero.\n"
            "- Always clamp outputs to the provided range.\n"
            "- Do not invent ranges; use exactly what is passed in.\n"
        )
        extra_rules = (range_rule_text + ("\n" if range_rule_text else "") + general_rules).strip()
        
        # Furtrher rules 

        _user_msg = (
            "Continue this concept.\n"
            f"Payload (JSON): {json.dumps(payload, ensure_ascii=False)}\n"
            "Rules:\n"
            "- Ask a clear main question (<=300 chars) or a clarifier (<=320 chars) when needed.\n"
            "- Clarifiers do NOT count toward the 5-per-pillar main questions.\n"
            "- If payload.sufficient_for_scoring is true OR the user's reply strongly implies a count/timeframe (e.g., 'daily', 'every evening'), you may prefer action:'finish' with a score.\n"
            "- You may infer numeric counts from habitual phrasing (e.g., 'every evening' in a 7-day window → 7); include a brief rationale and set confidence accordingly.\n"
            "- Treat number words (e.g., 'three', 'two to three') as numeric answers when the timeframe is already given.\n"
            "- Avoid verbatim repetition of the original main question; if you re-ask, rephrase and narrow to the highest-signal detail(s).\n"
            "- Always populate: status, why, missing, parsed_value in your JSON.\n"
            "- Finish this concept when you can assign an appropriate score (including 0).\n"
            "- Set confidence based on certainty: numeric + explicit timeframe → 0.80–0.95; inferred from categorical habit → 0.65–0.85; numeric but inferred timeframe → 0.55–0.75; otherwise ask a clarifier.\n"
            f"{range_rule_text}"
            'Return JSON only: {"action":"ask"|"finish","question":"","level":"","confidence":<float 0.0–1.0>,"rationale":"","scores":{},'
            '"status":"","why":"","missing":[],"parsed_value":{"value":null,"unit":"","timeframe_ok":false}}'
        )
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="assessor_llm_request", status="ok",
                                 payload={
                                     "pillar": pillar,
                                     "concept": concept_code,
                                     "system_len": len(_system_msg or ""),
                                     "user_len": len(_user_msg or ""),
                                     "sufficient_for_scoring": payload.get("sufficient_for_scoring"),
                                     "has_range_guide": bool(range_rule_text),
                                     "range_bounds": list(bm_tuple) if bm_tuple else None,
                                 }))
                ss.commit()
        except Exception:
            pass
        try:
            _resp = _llm.invoke([
                {"role": "system", "content": _system_msg},
                {"role": "user", "content": _user_msg},
            ])
            raw = getattr(_resp, "content", "") or ""
            try:
                preview = (raw[:220] + "…") if len(raw) > 220 else raw
                with SessionLocal() as ss:
                    ss.add(JobAudit(job_name="assessor_llm_response", status="ok",
                                    payload={"pillar": pillar, "concept": concept_code,
                                             "type": type(_resp).__name__,
                                             "has_content": bool(raw), "content_len": len(raw or ""), "preview": preview}))
                    ss.commit()
            except Exception:
                pass
        except Exception as e:
            raw = ""
            tb = traceback.format_exc(limit=2)
            try:
                with SessionLocal() as ss:
                    ss.add(JobAudit(job_name="assessor_llm_exception", status="error",
                                    payload={"pillar": pillar, "concept": concept_code},
                                    error=f"{e!r}\n{tb}"))
                    ss.commit()
            except Exception:
                pass

        # Log empty/short LLM responses for debugging
        if not raw or len((raw or "").strip()) < 5:
            try:
                with SessionLocal() as ss:
                    ss.add(JobAudit(job_name="assessor_llm_empty", status="warn",
                                    payload={"pillar": pillar, "concept": concept_code},
                                    error="empty_or_short_llm_response"))
                    ss.commit()
            except Exception:
                pass

        out = _parse_llm_json(raw)
        # Optional: quick audit of the meta so you can see why it didn’t finish
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="assessor_llm_meta",
                                status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                         "status": out.status, "why": out.why,
                                         "missing": out.missing, "parsed_value": out.parsed_value}))
                ss.commit()
        except Exception:
            pass

        # Extract score for this concept if present
        c_scores = out.scores or {}
        this_concept_score = 0.0
        if isinstance(c_scores, dict):
            if concept_code in c_scores:
                try:
                    this_concept_score = float(c_scores.get(concept_code) or 0.0)
                except Exception:
                    this_concept_score = 0.0
            else:
                try:
                    vals = [float(v or 0.0) for v in c_scores.values()]
                    this_concept_score = vals[0] if vals else 0.0
                except Exception:
                    this_concept_score = 0.0

        # If not done yet, but the input looks sufficient, try a force-finish pass first
        wants_finish = (out.action == "finish_domain") or (this_concept_score > 0.0)
        if not wants_finish and payload.get("sufficient_for_scoring"):
            raw_ff = _force_finish(pillar, concept_code, payload, extra_rules=range_rule_text, bounds=bm_tuple)           
            if raw_ff:
                out_ff = _parse_llm_json(raw_ff)
                c_scores_ff = out_ff.scores or {}
                try:
                    this_concept_score = float(next(iter(c_scores_ff.values()))) if c_scores_ff else 0.0
                except Exception:
                    this_concept_score = 0.0
                if out_ff.action == "finish_domain" or this_concept_score > 0.0:
                    out = out_ff
                    wants_finish = True

        if not wants_finish:
            # bump clarifier count for this concept
            cprog = concept_progress.setdefault(pillar, {}).setdefault(concept_code, {
                "main_asked": True, "clarifiers": 0, "scored": False, "summary_logged": False
            })
            cprog["clarifiers"] = int(cprog.get("clarifiers", 0)) + 1

            # LLM clarifier regeneration logic
            # Find last main question for this concept (for similarity checks and payload)
            last_main_q = ""
            for t in reversed(pillar_turns):
                if t.get("role") == "assistant" and t.get("is_main") and t.get("concept") == concept_code and t.get("question"):
                    last_main_q = t.get("question")
                    break
            asked = _asked_norm_set(turns, pillar)
            cand = (out.question or "").strip()
            # Avoid re-asking a near-duplicate of the main question
            if cand and last_main_q and _too_similar(cand, last_main_q):
                cand = ""

            if (not cand) or (_norm(cand) in asked):
                # Enrich payload for a better clarifier
                regen_payload = dict(payload)
                regen_payload["main_question"] = last_main_q
                regen_payload["last_user_reply"] = msg
                regen_payload["missing"] = (out.missing or [])

                regen = _regen_clarifier(pillar, concept_code, regen_payload)
                if regen and _norm(regen) not in asked and not _too_similar(regen, last_main_q):
                    cand = regen
                else:
                    # One more attempt with the same enriched payload (still LLM-authored)
                    regen2 = _regen_clarifier(pillar, concept_code, regen_payload)
                    if regen2 and _norm(regen2) not in asked and not _too_similar(regen2, last_main_q):
                        cand = regen2
                    else:
                        cand = ""

            if not cand:
                pending_msg, ack_text = _compose_ack_with_message(ack_text, None)
                if pending_msg:
                    try:
                        _send_to_user(user, pending_msg)
                    except Exception:
                        pass
                try:
                    with SessionLocal() as ss:
                        ss.add(JobAudit(job_name="assessor_no_clarifier", status="warn",
                                        payload={"pillar": pillar, "concept": concept_code, "asked_norm": list(asked)},
                                        error="llm_failed_to_generate_clarifier"))
                        ss.commit()
                except Exception:
                    pass
                # (Optional) Audit: log when we reject a clarifier as “too similar”
                try:
                    with SessionLocal() as ss:
                        ss.add(JobAudit(job_name="clarifier_rejected_as_duplicate", status="warn",
                                        payload={"pillar": pillar, "concept": concept_code,
                                                 "main_q": last_main_q[:200], "attempt": (out.question or "")[:200]}))
                        ss.commit()
                except Exception:
                    pass
                _commit_state(s, sess, state)
                return True

            # If we've hit the clarifier soft cap and still no score, log summary and advance
            if int(cprog.get("clarifiers", 0)) >= CLARIFIER_SOFT_CAP and this_concept_score <= 0.0:
                concept_dialogue = []
                for t in reversed(turns):
                    if t.get("pillar") != pillar:
                        continue
                    concept_dialogue.append(t)
                    if t.get("is_main") and t.get("concept") == concept_code:
                        break
                concept_dialogue = list(reversed(concept_dialogue))

                run_id = state.get("run_id")
                idx_next = int(state.get("turn_idx", 0)) + 1
                summary = AssessmentTurn(
                    run_id=run_id, idx=idx_next, pillar=pillar, concept_key=concept_code,
                    is_clarifier=False, assistant_q=None, user_a=None,
                    retrieval=None, llm_raw=None, action="concept_complete",
                    confidence=out.confidence,
                    is_concept_summary=True, concept_score=None,
                    dialogue=concept_dialogue, kb_used=kb_used.get(pillar, {}).get(concept_code, []),
                    clarifier_count=int(concept_progress.get(pillar, {}).get(concept_code, {}).get("clarifiers", 0))
                )
                s.add(summary); s.commit()
                state["turn_idx"] = idx_next

                cprog["summary_logged"] = True
                cprog["scored"] = False
                concept_idx_map[pillar] = int(concept_idx_map.get(pillar, 0)) + 1

                fallback_text = "Thanks — we don’t have enough detail to score that one yet, so we’ll move on."
                composed_msg, ack_text = _compose_ack_with_message(ack_text, fallback_text)
                if composed_msg:
                    _send_to_user(user, composed_msg)
                _commit_state(s, sess, state)
                return True

            # Otherwise, ask the clarifier
            turns.append({"role": "assistant", "pillar": pillar, "question": cand, "concept": concept_code, "is_main": False})
            _commit_state(s, sess, state)
            composed_msg, ack_text = _compose_ack_with_message(ack_text, cand)
            if composed_msg:
                _send_to_user(user, composed_msg)
            _log_turn(s, state, pillar, concept_code, True, cand, None, retrieval_ctx, raw, action="ask", confidence=out.confidence)
            _commit_state(s, sess, state)
            return True

        # Concept can be finished
        # Use the latest computed score; override with deterministic bounds if available + numeric answer
        final_score = float(this_concept_score or 0.0)

        # Emit concept summary turn
        concept_dialogue = []
        for t in reversed(turns):
            if t.get("pillar") != pillar:
                continue
            concept_dialogue.append(t)
            if t.get("is_main") and t.get("concept") == concept_code:
                break
        concept_dialogue = list(reversed(concept_dialogue))

        last_user_a = ""
        for item in reversed(concept_dialogue):
            if item.get("role") == "user":
                last_user_a = item.get("text") or ""
                break

        num_val = None
        raw_unit = None
        try:
            if isinstance(out.parsed_value, dict):
                num_val = out.parsed_value.get("value")
                raw_unit = (out.parsed_value.get("unit") or "") if isinstance(out.parsed_value, dict) else ""
        except Exception:
            num_val = None
        if num_val is None:
            num_val = _parse_number(last_user_a)
        # Fallback: parse any user turn for this concept from the full turn history
        if num_val is None:
            for t in reversed(turns):
                if t.get("pillar") == pillar and t.get("concept") == concept_code and t.get("role") == "user":
                    num_val = _parse_number(t.get("text", ""))
                    if num_val is not None:
                        break
        if num_val is None:
            try:
                qa_snap = state.get("qa_snapshots", {}).get(pillar, {}).get(concept_code, {})
                num_val = _parse_number(qa_snap.get("a", ""))
            except Exception:
                num_val = None
        normalized_val = None
        if num_val is not None:
            try:
                normalized_val = _normalize_value_for_concept(pillar, concept_code, float(num_val), raw_unit, last_user_a)
            except Exception:
                normalized_val = num_val
        if bm_tuple is None:
            try:
                bm_tuple = _concept_bounds(s, pillar, concept_code)
            except Exception:
                bm_tuple = None
        if bm_tuple and normalized_val is not None:
            try:
                final_score = _score_from_bounds(float(bm_tuple[0]), float(bm_tuple[1]), float(normalized_val))
            except Exception:
                pass

        concept_scores.setdefault(pillar, {})[concept_code] = final_score
        concept_progress.setdefault(pillar, {}).setdefault(concept_code, {
            "main_asked": True, "clarifiers": 0, "scored": False, "summary_logged": False
        })
        concept_progress[pillar][concept_code]["scored"] = True

        run_id = state.get("run_id")
        idx_next = int(state.get("turn_idx", 0)) + 1
        summary = AssessmentTurn(
            run_id=run_id, idx=idx_next, pillar=pillar, concept_key=concept_code,
            is_clarifier=False, assistant_q=None, user_a=None,
            retrieval=None, llm_raw=None, action="concept_complete",
            confidence=out.confidence,
            is_concept_summary=True, concept_score=final_score,
            dialogue=concept_dialogue, kb_used=kb_used.get(pillar, {}).get(concept_code, []),
            clarifier_count=int(concept_progress.get(pillar, {}).get(concept_code, {}).get("clarifiers", 0))
        )
        s.add(summary); s.commit()
        state["turn_idx"] = idx_next

        # Stash per-concept snapshot in state for pillar-level upsert
        try:
            qa_snap = state.setdefault("qa_snapshots", {}).setdefault(pillar, {})
            # Extract main question and latest user answer for this concept
            last_main_q = ""
            last_user_a = ""
            for item in concept_dialogue:
                if item.get("role") == "assistant" and item.get("is_main") and item.get("concept") == concept_code:
                    last_main_q = item.get("question") or item.get("text") or last_main_q
                if item.get("role") == "user":
                    last_user_a = item.get("text") or last_user_a
            qa_snap[concept_code] = {
                "q": last_main_q,
                "a": last_user_a,
                "conf": out.confidence,
                "notes": {
                    "parsed_value": out.parsed_value if isinstance(out.parsed_value, dict) else {},
                    "rationale": out.rationale,
                    "why": out.why,
                    "status": out.status,
                }
            }
            _commit_state(s, sess, state)
        except Exception:
            pass

        # Advance concept index
        concept_idx_map[pillar] = int(concept_idx_map.get(pillar, 0)) + 1

        finished_pillar = concept_idx_map[pillar] >= min(MAIN_QUESTIONS_PER_PILLAR, len(pillar_concepts))

        if finished_pillar:
            # Pillar summary
            codes = pillar_concepts[:MAIN_QUESTIONS_PER_PILLAR]
            raw_vals = [concept_scores.get(pillar, {}).get(k, None) for k in codes]
            kept = [float(v) for v in raw_vals if v is not None]
            if not kept:
                kept = [0.0]
            filled_scores = {k: (float(concept_scores.get(pillar, {}).get(k)) if concept_scores.get(pillar, {}).get(k) is not None else None) for k in codes}
            overall = round(sum(kept) / max(1, len(kept)))

            # Persist concept scores with Q/A/Confidence/Notes from snapshots
            try:
                snap_pillar = (state.get("qa_snapshots", {}) or {}).get(pillar) or {}
                q_by = {k: v.get("q") for k, v in snap_pillar.items()}
                a_by = {k: v.get("a") for k, v in snap_pillar.items()}
                conf_by = {k: v.get("conf") for k, v in snap_pillar.items()}
                notes_by = {k: v.get("notes") for k, v in snap_pillar.items()}
                _update_concepts_from_scores(user.id, pillar, filled_scores,
                                             q_by_code=q_by, a_by_code=a_by,
                                             conf_by_code=conf_by, notes_by_code=notes_by,
                                             run_id=state.get("run_id"))
            except Exception:
                pass

            recent = [t for t in turns if t.get("pillar") == pillar][-10:]
            feedback_line = feedback_to_okr(
                pillar_slug=pillar,
                pillar_score=float(overall) if overall is not None else 0.0,
                concept_scores=filled_scores
            )
            breakdown = "\n".join(
                _score_bar(k.replace('_',' ').title(), v)
                for k, v in filled_scores.items()
            ) or "(no sub-scores)"
            # Write/Update PillarResult for this pillar
            try:
                _upsert_pillar_result(
                    s,
                    run_id=state.get("run_id"),
                    pillar_key=pillar,
                    overall=int(overall),
                    concept_scores=filled_scores,
                    feedback_text=feedback_line,
                    user_id=user.id
                )
            except Exception:
                # swallow to avoid impacting the user flow
                pass

            # ── OKR: update objective + KRs for this finished pillar ─────────────────────
            try:
                # Fetch the just-upserted PillarResult so we have its id for lineage
                pr = s.execute(
                    select(PillarResult).where(
                        PillarResult.run_id == state.get("run_id"),
                        PillarResult.pillar_key == pillar
                    )
                ).scalars().first()

                if pr is not None:
                    _sync_okrs_after_pillar(
                        db=s,
                        user=user,
                        assess_session=sess,
                        pillar_result=pr,
                        concept_score_map=filled_scores,  # pass per-concept scores if available
                    )
                try:
                    s.commit()
                except Exception:
                    s.rollback()
            except Exception as _okr_e:
                print(f"[okr] WARN: OKR sync failed for run_id={state.get('run_id')} pillar={pillar}: {_okr_e}")
            # ─────────────────────────────────────────────────────────────────────────────

            # No pillar score message during assessment; save breakdown for final report

            nxt = _next_pillar(pillar)
            state["results"][pillar] = {"level": out.level, "confidence": out.confidence,
                                        "rationale": out.rationale, "scores": filled_scores, "overall": overall}

            if nxt:
                state["current"] = nxt
                first_name = (getattr(user, "first_name", "") or "").strip()
                if first_name:
                    tr_msg = f"*Great {first_name}* — {pillar.title()} done. Now a quick check on {nxt.title()} ⭐"
                else:
                    tr_msg = f"*Great* — {pillar.title()} done. Now a quick check on {nxt.title()} ⭐"
                turns.append({"role": "assistant", "pillar": nxt, "text": tr_msg})
                _send_to_user(user, tr_msg)
                if _maybe_prompt_preamble_question(user, state, nxt, turns):
                    _commit_state(s, sess, state)
                    return True
                if not _send_first_concept_question_for_pillar(user, state, nxt, turns, s):
                    _commit_state(s, sess, state)
                    return True
                _commit_state(s, sess, state)
                return True
            else:

                # ── Finalize: compute combined score, show breakdown, persist, and finish run ──
                results_map = state.get("results", {}) or {}
                def _pill_score(p):
                    v = results_map.get(p, {}) or {}
                    return v.get("overall")
                n_sc = _pill_score("nutrition")
                t_sc = _pill_score("training")
                r_sc = _pill_score("resilience")
                rc_sc = _pill_score("recovery")
                per_list = [x for x in [n_sc, t_sc, r_sc, rc_sc] if x is not None]
                combined = round(sum(per_list) / max(1, len(per_list))) if per_list else 0

                # Build dashboard link
                dash_link = _report_url(user.id, "latest.html")

                # Per-pillar breakdown with colored bars
                bars = []
                if n_sc is not None: bars.append(_score_bar("Nutrition", n_sc))
                if t_sc is not None: bars.append(_score_bar("Training", t_sc))
                if r_sc is not None: bars.append(_score_bar("Resilience", r_sc))
                if rc_sc is not None: bars.append(_score_bar("Recovery", rc_sc))
                breakdown = "\n".join(bars) if bars else "No pillar scores available"

                # Send final message
                name = (getattr(user, "first_name", "") or "").strip()
                intro = f"🎯 *Assessment complete, {name}!*" if name else "🎯 *Assessment complete!*"
                final_msg = (
                    f"{intro} Your combined score is *{combined}/100*\n"
                    f"\n{breakdown}\n\n"
                    f"Your Wellbeing dashboard: {dash_link}\n"
                    f"(*Type 'Dashboard' any time to view it again.*)"
                )
                _send_to_user(user, final_msg)

                # Generate PDF report to disk
                # Generate dashboard HTML only (PDF skipped)
                try:
                    _dash_abs = generate_assessment_dashboard_html(state.get("run_id"))
                except Exception as e:
                    _dash_abs = None
                    try:
                        with SessionLocal() as ss:
                            ss.add(JobAudit(job_name="dashboard_generate", status="error",
                                            payload={"run_id": state.get("run_id")}, error=str(e)))
                            ss.commit()
                    except Exception:
                        pass

                # Generate/update progress report HTML
                try:
                    generate_progress_report_html(user.id)
                except Exception as e:
                    try:
                        with SessionLocal() as ss:
                            ss.add(JobAudit(job_name="progress_generate", status="error",
                                            payload={"user_id": user.id}, error=str(e)))
                            ss.commit()
                    except Exception:
                        pass

                # Persist combined score + dashboard path onto AssessmentRun (for reporting)
                try:
                    rpt_path = f"/reports/{user.id}/latest.html"
                    s.execute(
                        update(AssessmentRun)
                        .where(AssessmentRun.id == state.get("run_id"))
                        .values(combined_overall=int(combined),
                                finished_at=datetime.utcnow(),
                                report_path=rpt_path)
                    )
                    s.commit()
                except Exception:
                    pass

                # Finish run in review_log
                try:
                    _rv_finish_run(run_id=state.get("run_id"), results=state.get("results"))
                except Exception:
                    pass

                # Schedule follow-ups
                try:
                    schedule_day3_followup(user.id)
                    schedule_week2_followup(user.id)
                except Exception:
                    pass

                # Deactivate session
                try:
                    sess.is_active = False; s.commit()
                except Exception:
                    pass

                _commit_state(s, sess, state)
                return True     

        # Not finished pillar: ask next concept main question
        next_index = int(concept_idx_map[pillar])
        if next_index >= len(pillar_concepts):
            pending_msg, ack_text = _compose_ack_with_message(ack_text, None)
            if pending_msg:
                try:
                    _send_to_user(user, pending_msg)
                except Exception:
                    pass
            _commit_state(s, sess, state)
            return True
        next_concept = pillar_concepts[next_index]
        concept_progress.setdefault(pillar, {}).setdefault(next_concept, {
            "main_asked": True, "clarifiers": 0, "scored": False, "summary_logged": False
        })
        with SessionLocal() as sx:
            next_q = _concept_primary_question(sx, pillar, next_concept)
        if not (next_q and next_q.strip()):
            next_q = (f"Quick check on {_pretty_concept(next_concept)} — tell me about the last 7 days.")

        display_next = _format_main_question_for_user(state, pillar, next_concept, next_q)
        turns.append({"role": "assistant", "pillar": pillar, "question": next_q, "concept": next_concept, "is_main": True})
        _commit_state(s, sess, state)
        composed_msg, ack_text = _compose_ack_with_message(ack_text, display_next)
        if composed_msg:
            _send_to_user(user, composed_msg)
        try:
            _bump_concept_asked(user.id, state.get("run_id"), pillar, next_concept)
        except Exception:
            pass

        _log_turn(s, state, pillar, next_concept, False, next_q, None, retrieval_ctx, raw, action="ask", confidence=out.confidence)
        _commit_state(s, sess, state)
        return True
def send_menu_options(user: User) -> None:
    _send_to_user(user, "Type 'dashboard' anytime to open your interactive tracker link.")

def send_dashboard_link(user: User) -> None:
    run_id = None
    try:
        with SessionLocal() as s:
            run = (
                s.query(AssessmentRun)
                 .filter(AssessmentRun.user_id == user.id)
                 .order_by(AssessmentRun.finished_at.desc().nullslast(), AssessmentRun.started_at.desc())
                 .first()
            )
            if run:
                run_id = run.id
    except Exception:
        run_id = None

    if not run_id:
        _send_to_user(user, "No assessment history yet. Start a new assessment to view your tracker.")
        return

    try:
        print(f"[dashboard] regenerating HTML for run_id={run_id}")
        generate_assessment_dashboard_html(run_id)
        print(f"[dashboard] wrote HTML for run_id={run_id}")
    except Exception as e:
        print(f"[dashboard_error] {e}")
    link = _report_url(user.id, "latest.html")
    bust = int(time.time())
    _send_to_user(user, f"Your wellbeing dashboard: {link}?ts={bust}")
