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
)

# Messaging + LLM
from .nudges import send_message
from .llm import _llm

# Report 
from .reporting import generate_assessment_report_pdf

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
Ask ONE clear main question (<=300 chars, can be detailed with examples) OR a clarifier (<=320 chars) when the user's answer is vague.
If the user's reply contains a NUMBER that fits the asked timeframe (e.g., 'last 7 days'), TREAT IT AS SUFFICIENT and finish with a score.
Only finish the concept once you can assign a non-zero score on this concept.
Return JSON only with these fields:
{"action":"ask"|"finish","question":"","level":"Low"|"Moderate"|"High","confidence":0.0,
"rationale":"","scores":{},
"status":"scorable"|"needs_clarifier"|"insufficient",
"why":"",
"missing":[],
"parsed_value":{"value":null,"unit":"","timeframe_ok":false}}
Notes:
- Model-first scoring: Use your general health/nutrition expertise to judge what is good vs bad behavior for this concept. Treat retrieved KB snippets as optional context only. Do not wait for, or rely on, snippets to decide polarity or scores.
- Always output integer scores on a 0–100 scale. Choose a reasonable mapping that reflects how clearly good/poor the reported pattern is.
- Polarity inference: When the behavior is one people should limit/avoid (e.g., processed/sugary foods), LOWER frequency is BETTER. When it’s a recommended behavior (e.g., fruit/veg portions, hydration, protein), HIGHER adherence is BETTER.
- Zero-case rule: If the user indicates none/zero within the asked timeframe (e.g., “none”, “0 days”), set parsed_value.value=0, timeframe_ok=true (if the question provided it), and assign a HIGH score (≈95–100) when the behavior is to be limited/avoided.
- Language-to-number heuristic (if no number given): map “once or twice / occasionally” ≈ 1–2; “few days / some days” ≈ 3–4; “most days / regularly / often” ≈ 5–7.
- Clarifiers: Do not repeat the main question. Ask only for the single missing piece (number or timeframe) if needed to score; otherwise finish with a score and a one-line rationale.
- status=scorable → you can finish now; needs_clarifier → ask exactly one clarifier; insufficient → ask main question.
- missing: list the specific fields you need (e.g., ["unit","days_per_week"]).
- parsed_value: include the numeric you inferred (e.g., 3), unit label, and whether timeframe is satisfied.
- IMPORTANT: Return `scores` as integers on a 0–100 scale (NOT 0–10). Use your rubric mapping to 0–100.
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

# Prettify concept code for user-facing messages
def _pretty_concept(code: str) -> str:
    return (code or "").replace("_", " ").title()

def _system_for(pillar: str, concept_code: str) -> str:
    return (
        SYSTEM_TEMPLATE
        .replace("__PILLAR__", pillar.title())
        .replace("__CONCEPT__", concept_code.replace("_"," ").title())
    )

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
        # Preferred signature: (to, message)
        send_message(to_fmt, msg)
        return True
    except TypeError:
        # Legacy signature: (message)
        send_message(msg)
        return True
    except Exception as e:
        print(f"❌ send_message failed: {e!r} | to={to_fmt} msg={msg[:120]}")
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="send_message", status="error",
                                payload={"to": to_fmt, "text": msg}, error=str(e)))
                ss.commit()
        except Exception:
            pass
        return False

# DB helpers
def _resolve_concept_id(session, pillar_key: str | None, concept_code: str | None) -> Optional[int]:
    if not concept_code:
        return None
    q = select(Concept.id).where(Concept.pillar_key == pillar_key, Concept.code == concept_code)
    return session.execute(q).scalar_one_or_none()

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

def _bump_concept_asked(user_id: int, pillar_key: str | None, concept_code: str | None) -> None:
    if not concept_code:
        return
    now = datetime.utcnow()
    with SessionLocal() as s:
        cid = _resolve_concept_id(s, pillar_key, concept_code)
        if not cid:
            return
        row = s.execute(
            select(UserConceptState).where(
                UserConceptState.user_id == user_id,
                UserConceptState.concept_id == cid
            )
        ).scalar_one_or_none()
        if not row:
            row = UserConceptState(
                user_id=user_id, concept_id=cid, score=None,
                asked_count=1, last_asked_at=now, notes=concept_code, updated_at=now
            )
            s.add(row)
        else:
            row.asked_count = int(row.asked_count or 0) + 1
            row.last_asked_at = now
            row.updated_at = now
        s.commit()

def _update_concepts_from_scores(user_id: int, pillar_key: str, scores: dict[str, float]) -> None:
    now = datetime.utcnow()
    with SessionLocal() as s:
        for code, val in (scores or {}).items():
            cid = _resolve_concept_id(s, pillar_key, code)
            if not cid:
                continue
            try:
                v = float(val or 0.0)
            except Exception:
                v = 0.0
            row = s.execute(
                select(UserConceptState).where(
                    UserConceptState.user_id == user_id,
                    UserConceptState.concept_id == cid
                )
            ).scalar_one_or_none()
            if not row:
                row = UserConceptState(
                    user_id=user_id, concept_id=cid, score=v, asked_count=0,
                    last_asked_at=None, notes=code, updated_at=now
                )
                s.add(row)
            else:
                prev = float(row.score or 0.0)
                n = max(0, int(row.asked_count or 0))
                row.score = (prev * n + v) / max(1, n + 1)
                row.updated_at = now
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
        "You are clarifying the user's last answer so it can be scored.\n"
        "Write ONE clarifying question (<=320 chars) that directly asks for the MISSING detail.\n"
        "- Prefer a NUMBER (e.g., days/week, portions/day, sessions) and a RECENT TIMEFRAME if absent.\n"
        "- Do NOT repeat the original main question; move the user closer to a scorable answer.\n"
        "- No lists. No multiple questions. Return ONLY the question text."
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
            print(f"[JobAudit] clarifier_request pillar={pillar} concept={concept_code}")
        except Exception:
            pass

        resp_obj = _llm.invoke([
            {"role": "system", "content": CLARIFIER_SYSTEM},
            {"role": "user", "content": json.dumps({
                "pillar": pillar,
                "concept": concept_code,
                "history": payload.get("history", []),
                "already_asked": payload.get("already_asked", []),
                "retrieval": payload.get("retrieval", []),
            }, ensure_ascii=False)},
        ])
        resp = getattr(resp_obj, "content", "") or ""
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="clarifier_response", status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                         "has_content": bool(resp), "len": len(resp or "")}))
                ss.commit()
            print(f"[JobAudit] clarifier_response pillar={pillar} concept={concept_code} has_content={bool(resp)} len={len(resp or '')}")
        except Exception:
            pass
    except Exception as e:
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="clarifier_exception", status="error",
                                payload={"pillar": pillar, "concept": concept_code},
                                error=f"{e!r}\n{traceback.format_exc(limit=2)}"))
                ss.commit()
            print(f"[JobAudit] clarifier_exception pillar={pillar} concept={concept_code} err={e!r}")
        except Exception:
            pass
        return ""
    q = (resp or "").strip().strip('"').strip()
    return q[:320]

# Force-finish when numeric answer + timeframe are present, but the model hesitates
def _force_finish(pillar: str, concept_code: str, payload: dict) -> str:
    """
    Ask the LLM to return a FINISH JSON when the user's answer appears sufficient (numeric + timeframe).
    Returns raw JSON string (model content) or empty string on error.
    """
    FORCE_SYSTEM = (
        "You already have enough to score this concept.\n"
        "The user's reply contains a NUMBER and the main question supplied the timeframe (e.g., last 7 days).\n"
        "Return JSON for FINISH with: {\"action\":\"finish\",\"question\":\"\",\"level\":\"Low|Moderate|High\",\"confidence\":0.0,\"rationale\":\"\",\"scores\":{}}.\n"
        "Do NOT ask another question. Do NOT include extra text outside JSON."
    )
    try:
        # Log request
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="force_finish_request", status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                         "hist_len": len(payload.get("history", [])),
                                         "retrieval_len": len(payload.get("retrieval", []))}))
                ss.commit()
            print(f"[JobAudit] force_finish_request pillar={pillar} concept={concept_code}")
        except Exception:
            pass

        resp_obj = _llm.invoke([
            {"role": "system", "content": FORCE_SYSTEM},
            {"role": "user", "content": json.dumps({
                "pillar": pillar,
                "concept": concept_code,
                "history": payload.get("history", []),
                "retrieval": payload.get("retrieval", []),
            }, ensure_ascii=False)},
        ])
        resp = getattr(resp_obj, "content", "") or ""
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="force_finish_response", status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                         "has_content": bool(resp), "len": len(resp or "")}))
                ss.commit()
            print(f"[JobAudit] force_finish_response pillar={pillar} concept={concept_code} has_content={bool(resp)} len={len(resp or '')}")
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
            print(f"[JobAudit] _force_finish error pillar={pillar} concept={concept_code} err={e!r}")
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
    s.add(t); s.commit()
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

def start_combined_assessment(user: User):
    """Start combined assessment (Nutrition → Training → Resilience → Recovery)."""
    print(f"[DEBUG] Entered start_combined_assessment for user {user.id}")
    with SessionLocal() as s:
        _touch_user_timestamps(s, user)

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
        }
        sess = AssessSession(user_id=user.id, domain="combined", is_active=True, turn_count=0, state=state)
        s.add(sess); s.commit(); s.refresh(sess)
        print(f"[DEBUG] Created AssessSession with id={sess.id}")

        # Load concepts from DB once for this session
        with SessionLocal() as s_lookup:
            state["pillar_concepts"] = _load_pillar_concepts(s_lookup, cap=MAIN_QUESTIONS_PER_PILLAR)

        # Start run
        _start_or_get_run(s, user, state)

        intro = "We’ll do a quick check on Nutrition, Training, Resilience, then Recovery. Short questions—answer in your own words."
        _send_to_user(user, intro)
        state["turns"].append({"role": "assistant", "pillar": "nutrition", "text": intro})

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
        state["turns"].append({"role": "assistant", "pillar": pillar, "question": q, "concept": first_concept, "is_main": True})
        _commit_state(s, sess, state)
        _send_to_user(user, q)
        _log_turn(s, state, pillar, first_concept, False, q, None, None, None, action="ask")
        _commit_state(s, sess, state)
        return True

def continue_combined_assessment(user: User, user_text: str) -> bool:
    with SessionLocal() as s:
        _touch_user_timestamps(s, user)

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

        # quick commands
        cmd = (user_text or "").strip().lower()

        if cmd in {"report", "pdf", "report please", "send report", "pdf report", "dashboard", "image report"}:
            base = os.getenv("PUBLIC_BASE_URL")
            pdf_link = f"https://{base}/reports/{user.id}/latest.pdf" if base else f"/reports/{user.id}/latest.pdf"
            img_link = f"https://{base}/reports/{user.id}/latest.jpeg" if base else f"/reports/{user.id}/latest.jpeg"
            _send_to_user(user, f"Here are your latest reports:\n• PDF: {pdf_link}\n• Dashboard (image): {img_link}")
            return True

        pillar = state.get("current", "nutrition")
        concept_idx_map = state.get("concept_idx", {})
        concept_scores = state.get("concept_scores", {})
        kb_used = state.get("kb_used", {})
        turns = state.get("turns", [])
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
        turns.append({"role": "user", "pillar": pillar, "text": msg})
     
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
        q_has_week = "last 7" in (last_q or "").lower() or "week" in (last_q or "").lower()
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
        _user_msg = (
            "Continue this concept.\n"
            f"Payload (JSON): {json.dumps(payload, ensure_ascii=False)}\n"
            "Rules:\n"
            "- Ask ONE clear main question (<=300 chars) or a clarifier (<=320 chars) when needed.\n"
            "- Clarifiers do NOT count toward the 5-per-pillar main questions.\n"
            "- If payload.sufficient_for_scoring is true and your rubric mapping is clear, prefer action:\"finish\" with a score over asking another question.\n"
            "- Treat number words (e.g., 'three', 'two to three') as numeric answers when the timeframe is already given.\n"
            "- Do NOT repeat the original main question as a clarifier; ask for the missing number/timeframe only if needed.\n"
            "- Always populate: status, why, missing, parsed_value in your JSON.\n"
            "- Finish this concept ONLY when you can assign a non-zero score for this concept.\n"
            'Return JSON only: {"action":"ask"|"finish","question":"","level":"","confidence":0.0,"rationale":"","scores":{},'
            '"status":"","why":"","missing":[],"parsed_value":{"value":null,"unit":"","timeframe_ok":false}}'
        )
        try:
            with SessionLocal() as ss:
                ss.add(JobAudit(job_name="assessor_llm_request", status="ok",
                                payload={"pillar": pillar, "concept": concept_code,
                                         "system_len": len(_system_msg or ""), "user_len": len(_user_msg or ""),
                                         "sufficient_for_scoring": payload.get("sufficient_for_scoring")}))
                ss.commit()
            print(f"[JobAudit] assessor_llm_request pillar={pillar} concept={concept_code} system_len={len(_system_msg)} user_len={len(_user_msg)} suff={payload.get('sufficient_for_scoring')}")
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
                print(f"[JobAudit] assessor_llm_response pillar={pillar} concept={concept_code} has_content={bool(raw)} len={len(raw or '')}")
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
                print(f"[JobAudit] assessor_llm_exception pillar={pillar} concept={concept_code} err={e!r}")
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
            raw_ff = _force_finish(pillar, concept_code, payload)
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
            asked = _asked_norm_set(turns, pillar)
            cand = (out.question or "").strip()
            if (not cand) or (_norm(cand) in asked):
                regen = _regen_clarifier(pillar, concept_code, payload)
                if regen and _norm(regen) not in asked:
                    cand = regen
                else:
                    regen2 = _regen_clarifier(pillar, concept_code, payload)
                    if regen2 and _norm(regen2) not in asked:
                        cand = regen2
                    else:
                        cand = ""

            if not cand:
                try:
                    with SessionLocal() as ss:
                        ss.add(JobAudit(job_name="assessor_no_clarifier", status="warn",
                                        payload={"pillar": pillar, "concept": concept_code, "asked_norm": list(asked)},
                                        error="llm_failed_to_generate_clarifier"))
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

                _send_to_user(user, "Thanks — we don’t have enough detail to score that one yet, so we’ll move on.")
                _commit_state(s, sess, state)
                return True

            # Otherwise, ask the clarifier
            turns.append({"role": "assistant", "pillar": pillar, "question": cand, "concept": concept_code, "is_main": False})
            _commit_state(s, sess, state)
            _send_to_user(user, cand)
            _log_turn(s, state, pillar, concept_code, True, cand, msg, retrieval_ctx, raw, action="ask", confidence=out.confidence)
            _commit_state(s, sess, state)
            return True

        # Concept can be finished
        prev = float(concept_scores.get(pillar, {}).get(concept_code, 0.0) or 0.0)
        final_score = max(prev, float(this_concept_score or 0.0))
        concept_scores.setdefault(pillar, {})[concept_code] = final_score
        concept_progress.setdefault(pillar, {}).setdefault(concept_code, {
            "main_asked": True, "clarifiers": 0, "scored": False, "summary_logged": False
        })
        concept_progress[pillar][concept_code]["scored"] = True

        # Emit concept summary turn
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
            is_concept_summary=True, concept_score=final_score,
            dialogue=concept_dialogue, kb_used=kb_used.get(pillar, {}).get(concept_code, []),
            clarifier_count=int(concept_progress.get(pillar, {}).get(concept_code, {}).get("clarifiers", 0))
        )
        s.add(summary); s.commit()
        state["turn_idx"] = idx_next

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

            # Persist concept scores
            try:
                _update_concepts_from_scores(user.id, pillar, filled_scores)
            except Exception:
                pass

            recent = [t for t in turns if t.get("pillar") == pillar][-10:]
            feedback_line = _generate_feedback(pillar.title(), out.level, recent)
            def _fmt_score(v):
                return f"{round(float(v))}/100" if v is not None else "Unscored"
            breakdown = "\n".join(
                f"• {k.replace('_',' ').title()}: {_fmt_score(v)}"
                for k, v in filled_scores.items()
            ) or "• (no sub-scores)"
            final_msg = f"✅ {pillar.title()} complete — {overall}/100\n{breakdown}\n{feedback_line}"
            _send_to_user(user, final_msg)
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
     
            nxt = _next_pillar(pillar)
            state["results"][pillar] = {"level": out.level, "confidence": out.confidence,
                                        "rationale": out.rationale, "scores": filled_scores, "overall": overall}

            if nxt:
                state["current"] = nxt
                tr_msg = f"Great — {pillar.title()} done. Now a quick check on {nxt.title()} ⭐"
                turns.append({"role": "assistant", "pillar": nxt, "text": tr_msg})
                time.sleep(0.30) 
                _send_to_user(user, tr_msg)
                # Ask first concept in next pillar
                next_pcodes = state.get("pillar_concepts", {}).get(nxt) or []
                if not next_pcodes:
                    _send_to_user(user, f"Setup note: I don’t have {nxt.title()} concepts. Please seed the DB and try again.")
                    _commit_state(s, sess, state)
                    return True
                next_concept = next_pcodes[0]
                with SessionLocal() as s2:
                    q_next = _concept_primary_question(s2, nxt, next_concept) or f"Quick start on {next_concept.replace('_',' ')} — what’s your current approach?"
                turns.append({"role": "assistant", "pillar": nxt, "question": q_next, "concept": next_concept, "is_main": True})
                _send_to_user(user, q_next)
     
                _log_turn(s, state, nxt, next_concept, False, q_next, None, None, None, action="ask")
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

                # Build a report link
                base = os.getenv("PUBLIC_BASE_URL")
                pdf_link = f"https://{base}/reports/{user.id}/latest.pdf" if base else f"/reports/{user.id}/latest.pdf"
                img_link = f"https://{base}/reports/{user.id}/latest.jpeg" if base else f"/reports/{user.id}/latest.jpeg"

                # Per-pillar breakdown
                parts = []
                if n_sc is not None: parts.append(f"Nutrition {int(round(n_sc))}/100")
                if t_sc is not None: parts.append(f"Training {int(round(t_sc))}/100")
                if r_sc is not None: parts.append(f"Resilience {int(round(r_sc))}/100")
                if rc_sc is not None: parts.append(f"Recovery {int(round(rc_sc))}/100")
                breakdown = " · ".join(parts) if parts else "No pillar scores available"

                # Send final message
                final_msg = (
                    f"🎯 Assessment complete — Combined {combined}/100\n"
                    f"{breakdown}\n"
                    f"Reports:\n"
                    f"• PDF: {pdf_link}\n"
                    f"• Dashboard (image): {img_link}"
                )
                _send_to_user(user, final_msg)

                # Generate PDF report to disk
                try:
                    abs_path = generate_assessment_report_pdf(state.get("run_id"))
                except Exception as e:
                    abs_path = None
                    try:
                        with SessionLocal() as ss:
                            ss.add(JobAudit(job_name="report_generate", status="error",
                                            payload={"run_id": state.get("run_id")}, error=str(e)))
                            ss.commit()
                    except Exception:
                        pass

                # Persist combined score + report path onto AssessmentRun (for reporting)
                try:
                    rpt_path = f"/reports/{user.id}/latest.pdf"
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

        turns.append({"role": "assistant", "pillar": pillar, "question": next_q, "concept": next_concept, "is_main": True})
        _commit_state(s, sess, state)
        _send_to_user(user, next_q)
        try:
            _bump_concept_asked(user.id, pillar, next_concept)
        except Exception:
            pass

        _log_turn(s, state, pillar, next_concept, False, next_q, msg, retrieval_ctx, raw, action="ask", confidence=out.confidence)
        _commit_state(s, sess, state)
        return True