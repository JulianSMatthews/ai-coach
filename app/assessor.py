# app/assessor.py
# PATCHES
# CS-2025-08-26-002 — Add 'report' command for PDF link; ensure sess.updated_at is bumped on state writes

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import select, update

from .db import SessionLocal
from .models import User, AssessSession, UserConceptState  # NEW: concept state
from .nudges import send_message
from .llm import _llm
from .scheduler import (
    apply_nutrition_cadence,
    apply_training_cadence,
    apply_psych_cadence,   # rename to apply_resilience_cadence if you have it
)

# Optional RAG + Review (safe if missing)
try:
    from .retriever import retrieve_snippets, diversify
except Exception:  # pragma: no cover
    def retrieve_snippets(*args, **kwargs): return []
    def diversify(snips, **kwargs): return snips[:5]
try:
    from .review_log import start_run, log_turn, finish_pillar, finish_run
except Exception:  # pragma: no cover
    def start_run(*args, **kwargs): return None
    def log_turn(*args, **kwargs): return None
    def finish_pillar(*args, **kwargs): return None
    def finish_run(*args, **kwargs): return None


# ──────────────────────────────────────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────────────────────────────────────

# Per‑pillar question targets
MIN_QS = {
    "nutrition": 5,
    "training": 5,
    "resilience": 5,
    "goals": 5,
}

# Concept keys per pillar (used by selector + scores + RAG)
PILLAR_CONCEPTS: dict[str, list[str]] = {
    "nutrition": [
        "energy_balance", "protein_basics", "veg_fruit", "portioning",
        "label_literacy", "hunger_cues", "planning_prep", "hydration", "consistency"
    ],
    "training": [
        "structure_plan", "progressive_overload", "recovery",
        "tracking", "technique", "consistency", "session_quality"
    ],
    "resilience": [
        "setbacks_response", "reflection", "identity_habits",
        "stress_tools", "environment_cues", "early_signs"
    ],
}

SYSTEM_NUTRITION = """
You are a concise WhatsApp assessor for Nutrition.
- Ask ONE short question (<=200 chars) at a time.
- You receive 'already_asked' and 'already_asked_norm' to avoid repeats.
- You may receive 'retrieval' snippets to ground your judgment.
- Probe: balanced plate, protein portions, labels, energy balance, hunger cues, hydration, planning, consistency.
- If unsure about the user's reply, ask a brief clarifier (<20 words).
- Finish only when confident (≥0.8) AND after multiple distinct questions (>=5).
Return JSON only:
{
 "action":"ask"|"finish",
 "question":"",
 "level":"Low"|"Moderate"|"High",
 "confidence":0.0,
 "rationale":"",
 "scores": { "energy_balance":0.0, "protein_basics":0.0, "veg_fruit":0.0, "portioning":0.0, "label_literacy":0.0, "hunger_cues":0.0, "planning_prep":0.0, "hydration":0.0, "consistency":0.0 }
}
"""

SYSTEM_TRAINING = """
You are a concise WhatsApp assessor for Training/Exercise.
- Ask ONE short question (<=200 chars) at a time.
- You receive 'already_asked' and 'already_asked_norm' to avoid repeats.
- You may receive 'retrieval' snippets to ground your judgment.
- Probe: structure/plan, progressive overload, recovery, tracking, technique, consistency, session quality.
- If unsure about the user's reply, ask a brief clarifier (<20 words).
- Finish only when confident (≥0.8) AND after multiple distinct questions (>=5).
Return JSON only:
{
 "action":"ask"|"finish",
 "question":"",
 "level":"Low"|"Moderate"|"High",
 "confidence":0.0,
 "rationale":"",
 "scores": { "structure_plan":0.0, "progressive_overload":0.0, "recovery":0.0, "tracking":0.0, "technique":0.0, "consistency":0.0, "session_quality":0.0 }
}
"""

SYSTEM_RESILIENCE = """
You are a concise WhatsApp assessor for Resilience/Mindset.
- Ask ONE short question (<=200 chars) at a time.
- You receive 'already_asked' and 'already_asked_norm' to avoid repeats.
- You may receive 'retrieval' snippets to ground your judgment.
- Probe: setbacks response, reflection, identity habits, stress tools, environment cues, early signs.
- If unsure about the user's reply, ask a brief clarifier (<20 words).
- Finish only when confident (≥0.8) AND after multiple distinct questions (>=5).
Return JSON only:
{
 "action":"ask"|"finish",
 "question":"",
 "level":"Low"|"Moderate"|"High",
 "confidence":0.0,
 "rationale":"",
 "scores": { "setbacks_response":0.0, "reflection":0.0, "identity_habits":0.0, "stress_tools":0.0, "environment_cues":0.0, "early_signs":0.0 }
}
"""

FEEDBACK_SYSTEM = """
You are an AI coach giving a concise WhatsApp summary for a finished pillar.
Return ONLY the final WhatsApp message (no JSON).
Format:
- 1 short line of feedback (what they do well + gap)
- "Next steps:" + 2 bullets (<= 12 words), practical, non‑judgmental.
"""

# Goals pillar configuration
GOALS_QUESTION_BANK = [
    {"id": "primary_goal_1",    "text": "What is the most important goal for you right now?",                                   "captures": ["primary_goal"]},
    {"id": "primary_goal_2",    "text": "If you could only achieve one thing over the next 90 days, what would it be?",        "captures": ["primary_goal", "timeframe"]},
    {"id": "timeframe_1",       "text": "When would you like to reach this goal by?",                                          "captures": ["timeframe"]},
    {"id": "drivers_why_1",     "text": "Why is this goal important to you?",                                                  "captures": ["drivers"]},
    {"id": "drivers_meaning_1", "text": "What would reaching this goal mean for you?",                                         "captures": ["drivers"]},
    {"id": "motivation_1",      "text": "When things get tough, what can we say to reignite your motivation?",                 "captures": ["drivers"]},
    {"id": "barriers_1",        "text": "What usually gets in the way when you try to reach your goals?",                      "captures": ["barriers"]},
    {"id": "support_1",         "text": "What kind of support works best for you when you’re struggling? (Encouragement, challenge or reminders?)", "captures": ["support"]},
    {"id": "why_now_1",         "text": "Why have you decided to take action today?",                                          "captures": ["drivers"]},
    {"id": "help_now_1",        "text": "What do you need help with the most right now? (Nutrition, training or resilience?)", "captures": ["commitment", "support"]},
]
GOALS_PRIORITY = ["primary_goal", "timeframe", "drivers", "support", "commitment"]

# Order of pillars (goals last)
PILLAR_ORDER = ["nutrition", "training", "resilience", "goals"]


# ──────────────────────────────────────────────────────────────────────────────
# Helpers (parsing, anti‑repeat, formatting)
# ──────────────────────────────────────────────────────────────────────────────

def get_active_domain(user: User) -> str | None:
    with SessionLocal() as s:
        sess = (
            s.query(AssessSession)
            .filter(AssessSession.user_id == user.id, AssessSession.is_active == True)
            .order_by(AssessSession.id.desc())
            .first()
        )
        return sess.domain if sess else None

@dataclass
class StepResult:
    action: Literal["ask", "finish_domain"]  # normalized
    question: str
    level: str
    confidence: float
    rationale: str
    scores: dict  # optional per‑concept scores

def _parse_json(s: str) -> StepResult:
    """Parse model JSON and normalise action=finish -> finish_domain. Extract optional 'scores' dict."""
    try:
        m = re.search(r"\{.*\}", s or "", re.S)
        j = json.loads(m.group(0)) if m else {}
    except Exception:
        j = {}
    action = (j.get("action") or "ask").strip().lower()
    if action == "finish":
        action = "finish_domain"
    return StepResult(
        action=action if action in ("ask", "finish_domain") else "ask",
        question=(j.get("question") or "").strip(),
        level=str(j.get("level", "Low")),
        confidence=float(j.get("confidence", 0.0) or 0.0),
        rationale=(j.get("rationale") or "").strip(),
        scores=j.get("scores") if isinstance(j.get("scores"), dict) else {},
    )

def _as_dialogue_simple(items: list[dict]) -> list[dict]:
    out = []
    for t in items:
        role = t.get("role", "")
        txt = t.get("text") if t.get("text") is not None else t.get("question")
        if not txt:
            continue
        out.append({"role": role, "text": str(txt)})
    return out

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("—", "-").replace("–", "-").replace("‒", "-")
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    s = re.sub(r"\s+", " ", s)
    s = s.rstrip("?.! ")
    return s

def _tok_set(s: str) -> set[str]:
    stop = {
        "the","a","an","and","or","to","of","on","in","for","with",
        "when","how","what","do","you","your","is","are","it","that"
    }
    return {w for w in re.findall(r"[a-z0-9']+", (s or "").lower()) if w not in stop}

def _too_similar(a: str, b: str, thresh: float = 0.8) -> bool:
    A, B = _tok_set(a), _tok_set(b)
    if not A or not B:
        return False
    inter = len(A & B); uni = len(A | B)
    j = inter / uni if uni else 0.0
    if j >= thresh:
        return True
    an, bn = _norm(a), _norm(b)
    return an.startswith(bn) or bn.startswith(an)

def _nonrepeat_bank_for(pillar: str) -> list[str]:
    if pillar == "nutrition":
        return [
            "How many meals do you usually eat per day?",
            "What’s your go‑to breakfast on weekdays?",
            "How do you decide your portion sizes at dinner?",
            "How much protein do you aim for per meal?",
            "Do you read food labels? What do you check first?",
            "How many glasses of water do you drink daily?",
            "How do you notice you’re full and stop eating?",
            "Do you track intake now? If yes, how?",
            "What’s one change you’ve tried that worked well?",
        ]
    if pillar == "training":
        return [
            "How many days did you train in the last 2 weeks?",
            "What are your main training goals right now?",
            "Do you follow a plan or decide on the day?",
            "How do you track progress—app, logbook, memory?",
            "When do you usually add weight or reps?",
            "How long do your sessions typically last?",
            "Any movements you avoid or struggle with?",
            "How’s your recovery—sleep, soreness, energy?",
            "What’s scheduled for your next session?",
        ]
    if pillar == "resilience":
        return [
            "What early signs tell you you’re going off track?",
            "What quick tactic helps you reset on tough days?",
            "Who or what supports you best when stressed?",
            "Do you reflect weekly? How do you do it?",
            "What small habit anchors your routine?",
            "What environment cues help you stay consistent?",
            "How do you handle setbacks—what’s step one?",
            "What time of day are you most focused?",
            "What drains your energy most in a week?",
        ]
    if pillar == "goals":
        return [
            "Name the single outcome you want most now.",
            "What’s your target date to achieve it?",
            "Why does this matter to you personally?",
            "What would success change in your day‑to‑day?",
            "What support style helps you most—encourage, challenge, or reminders?",
            "What usually blocks your progress?",
            "If motivation dips, what message should we send you?",
            "Why start now rather than later?",
            "Where do you need the most help—nutrition, training, or resilience?",
            "On a scale of 1–10, how committed are you?",
        ]
    return []

def _next_from_bank(previous_turns: list[dict], pillar: str) -> str | None:
    asked_qs = [
        (t.get("question") or "").strip()
        for t in previous_turns
        if t.get("role") == "assistant" and t.get("pillar") == pillar and t.get("question")
    ]
    for cand in _nonrepeat_bank_for(pillar):
        if cand and not any(_too_similar(cand, q) or _norm(cand) == _norm(q) for q in asked_qs):
            return cand
    return None

def _count_user_replies_for_pillar(turns: list[dict], pillar: str) -> int:
    return sum(1 for t in turns if t.get("role") == "user" and t.get("pillar") == pillar)

def _count_unique_assistant_qs_for_pillar(turns: list[dict], pillar: str) -> int:
    seen: list[str] = []
    for t in turns:
        if t.get("role") != "assistant" or t.get("pillar") != pillar:
            continue
        q = (t.get("question") or "").strip()
        if not q:
            continue
        if any(_too_similar(q, prev) for prev in seen):
            continue
        seen.append(q)
    return len(seen)

def _dedupe_question(previous_turns: list[dict], proposed: str, pillar: str) -> str:
    proposed = (proposed or "").strip()
    if not proposed:
        return proposed
    asked_norm = {
        _norm(t.get("question") or t.get("text") or "")
        for t in previous_turns
        if t.get("role") == "assistant" and t.get("pillar") == pillar
    }
    prop_norm = _norm(proposed)
    if prop_norm in asked_norm:
        alt = _next_from_bank(previous_turns, pillar)
        if alt:
            return alt
        return proposed + " — from a different angle"
    return proposed

def _fallback_first_q(pillar: str) -> str:
    return {
        "training": "What does your typical training week look like?",
        "resilience":"When a week goes off‑track, how do you usually respond?",
        "nutrition": "How would you build a balanced lunch plate for yourself?",
        "goals":     "What is the most important goal for you right now?",
    }.get(pillar, "Could you share a bit more?")

def _fallback_followup_q(pillar: str) -> str:
    return {
        "nutrition": "How do you decide portions—tracking, visual cues, or habit?",
        "training":  "How consistent were you last 2 weeks? Do you log lifts?",
        "resilience":"What’s your go‑to reset when stressed or off‑track?",
        "goals":     "When would you like to reach this goal by?",
    }.get(pillar, "Tell me a bit more?")

def _send_to_user(user: User, text: str):
    try:
        send_message(user.phone, text)
    except TypeError:
        send_message(text)



def _commit_state(s, sess, state):
    """Write state JSON and bump updated_at safely, then commit."""
    try:
        sess.state = json.dumps(state)
    except Exception:
        sess.state = state
    try:
        setattr(sess, "updated_at", datetime.utcnow())
    except Exception:
        pass
    s.commit()
def _system_for(domain: str) -> str:
    d = (domain or "").lower()
    if d.startswith("train"): return SYSTEM_TRAINING
    if d.startswith(("resil", "psych")): return SYSTEM_RESILIENCE
    return SYSTEM_NUTRITION

def _generate_feedback(domain: str, level: str, convo_snippet: list[dict]) -> str:
    try:
        prompt = (
            f"{FEEDBACK_SYSTEM}\n\n"
            f"Pillar: {domain}\nLevel: {level}\n\n"
            f"Recent dialogue (JSON): {json.dumps(convo_snippet[-10:], ensure_ascii=False)}\n\n"
            "Return only the final message text (no JSON)."
        )
        txt = _llm.invoke(prompt).content.strip()
    except Exception:
        txt = ""
    if not txt:
        return (
            f"{domain}: Great effort. You’re at {level}.\n"
            "Next steps:\n• Keep what works.\n• Add one small upgrade this week."
        )
    return txt[:700]

def _next_pillar(current: str) -> str | None:
    try:
        i = PILLAR_ORDER.index(current)
        return PILLAR_ORDER[i + 1] if i + 1 < len(PILLAR_ORDER) else None
    except ValueError:
        return None

def _pick_sendable_question(turns: list[dict], pillar: str, candidate: str) -> str:
    asked = [
        (t.get("question") or "").strip()
        for t in turns
        if t.get("role") == "assistant" and t.get("pillar") == pillar and t.get("question")
    ]
    if candidate and not any(_too_similar(candidate, q) or _norm(candidate) == _norm(q) for q in asked):
        return candidate
    bank_alt = _next_from_bank(turns, pillar)
    if bank_alt:
        return bank_alt
    base = candidate or _fallback_followup_q(pillar)
    return base + " — from a different angle"


# ──────────────────────────────────────────────────────────────────────────────
# Concept selection & state tracking
# ──────────────────────────────────────────────────────────────────────────────

def _concept_keys_for(pillar: str) -> list[str]:
    return PILLAR_CONCEPTS.get(pillar, [])

def _get_user_concept_state(user_id: int, concept_key: str) -> UserConceptState:
    with SessionLocal() as s:
        row = (
            s.query(UserConceptState)
            .filter(UserConceptState.user_id == user_id, UserConceptState.notes == concept_key)  # use 'notes' to store key if you don't have concept table
            .first()
        )
        if not row:
            row = UserConceptState(
                user_id=user_id,
                concept_id=0,             # if you don't use Concept table, leave 0
                score=None,
                asked_count=0,
                last_asked_at=None,
                notes=concept_key,
                updated_at=datetime.utcnow(),
            )
            s.add(row); s.commit(); s.refresh(row)
        return row

def _bump_concept_asked(user_id: int, concept_key: str) -> None:
    with SessionLocal() as s:
        row = (
            s.query(UserConceptState)
            .filter(UserConceptState.user_id == user_id, UserConceptState.notes == concept_key)
            .first()
        )
        if not row:
            row = UserConceptState(
                user_id=user_id, concept_id=0, score=None, asked_count=1,
                last_asked_at=datetime.utcnow(), notes=concept_key, updated_at=datetime.utcnow()
            )
            s.add(row)
        else:
            row.asked_count = int(row.asked_count or 0) + 1
            row.last_asked_at = datetime.utcnow()
            row.updated_at = datetime.utcnow()
        s.commit()

def _update_concepts_from_scores(user_id: int, pillar: str, scores: dict) -> None:
    if not isinstance(scores, dict):
        return
    with SessionLocal() as s:
        for key in _concept_keys_for(pillar):
            if key not in scores:
                continue
            row = (
                s.query(UserConceptState)
                .filter(UserConceptState.user_id == user_id, UserConceptState.notes == key)
                .first()
            )
            if not row:
                row = UserConceptState(
                    user_id=user_id, concept_id=0, score=float(scores[key] or 0.0),
                    asked_count=0, last_asked_at=None, notes=key, updated_at=datetime.utcnow()
                )
                s.add(row)
            else:
                row.score = float(scores[key] or 0.0)
                row.updated_at = datetime.utcnow()
        s.commit()

def _select_concept(user_id: int, pillar: str, results: dict, turns: list[dict]) -> Optional[str]:
    """
    Heuristic:
      1) Prefer unassessed concepts (no score yet)
      2) Among those, pick the one with lowest asked_count in UserConceptState
      3) Else pick the lowest-scoring concept
      4) Tie-break: least recently asked in this session
    """
    keys = _concept_keys_for(pillar)
    if not keys:
        return None

    # Current pillar scores (if any) from in-progress results
    pillar_scores = (results.get(pillar) or {}).get("scores") or {}

    # Session asked counts for this pillar by concept (from turns)
    session_counts: dict[str, int] = {k: 0 for k in keys}
    for t in turns:
        if t.get("role") == "assistant" and t.get("pillar") == pillar:
            ck = t.get("concept")
            if ck in session_counts:
                session_counts[ck] += 1

    # Build candidate list with (known?, score, asked_count_global, asked_count_session, last_asked_at)
    cands = []
    with SessionLocal() as s:
        for k in keys:
            row = (
                s.query(UserConceptState)
                .filter(UserConceptState.user_id == user_id, UserConceptState.notes == k)
                .first()
            )
            asked_g = int(row.asked_count) if row and row.asked_count is not None else 0
            last_dt = row.last_asked_at.timestamp() if row and row.last_asked_at else 0.0
            score = pillar_scores.get(k)
            known = score is not None
            cands.append((k, known, float(score or 0.0), asked_g, session_counts.get(k, 0), last_dt))

    # 1) unknowns first, fewest asked globally, fewest asked in session, oldest last_asked_at
    unknowns = [c for c in cands if not c[1]]
    if unknowns:
        unknowns.sort(key=lambda x: (x[3], x[4], x[5]))  # asked_g, asked_session, last_asked_at
        return unknowns[0][0]

    # 2) else lowest score
    cands.sort(key=lambda x: (x[2], x[3], x[4], x[5]))
    return cands[0][0] if cands else None


# ──────────────────────────────────────────────────────────────────────────────
# Goals helpers (unchanged)
# ──────────────────────────────────────────────────────────────────────────────

def _asked_goal_ids(turns: list[dict]) -> set[str]:
    return {
        t.get("qid") for t in turns
        if t.get("pillar") == "goals" and t.get("role") == "assistant" and t.get("qid")
    }

def _goals_already_asked_texts(turns: list[dict]) -> list[str]:
    out: list[str] = []
    for t in turns:
        if t.get("pillar") != "goals" or t.get("role") != "assistant":
            continue
        q = (t.get("question") or "").strip()
        if q:
            out.append(q)
    return out

def _goals_outcomes_present(results: dict) -> set[str]:
    g = (results or {}).get("goals", {})
    have = set()
    for k in GOALS_PRIORITY:
        if (g.get(k) or "").strip():
            have.add(k)
    return have

def _choose_next_goals_question(turns: list[dict], results: dict) -> dict:
    asked_ids = _asked_goal_ids(turns)
    have = _goals_outcomes_present(results)
    for need in GOALS_PRIORITY:
        if need not in have:
            for q in GOALS_QUESTION_BANK:
                if q["id"] not in asked_ids and need in q["captures"]:
                    return q
    for q in GOALS_QUESTION_BANK:
        if q["id"] not in asked_ids:
            return q
    return {}

def _extract_goals_from_answer(user_text: str, existing: dict | None) -> dict:
    existing = existing or {}
    system = (
        "You extract structured goal-setting data from ONE user message. "
        'Return ONLY compact JSON with keys: primary_goal, timeframe, drivers, support, commitment. '
        'Values may be "", "-", or "unknown" if unknown. Each value <= 30 words.'
    )
    user = f"User answer:\n{user_text}\n\nReturn the JSON only."
    try:
        raw = _llm.invoke({"system": system, "user": user}).content.strip()
        m = re.search(r"\{.*\}", raw, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception:
        data = {}
    merged = {**existing}
    for k in GOALS_PRIORITY:
        v = (data.get(k) or "").strip()
        if v and v.lower() not in {"", "-", "unknown", "n/a"}:
            merged[k] = v
    return merged

def _goals_guidance(results: dict, turns: list[dict]) -> str:
    g = (results or {}).get("goals", {})
    system = (
        "You are a health coach. Create a concise end‑summary:\n"
        "1) One‑sentence primary goal + timeframe.\n"
        "2) Three bullets: weekly actions with metric + cadence + check‑in.\n"
        "3) Note an emotional cue and preferred support style.\n"
        "Keep <120 words; friendly and concrete. Return only the message."
    )
    payload = {
        "primary_goal": g.get("primary_goal", ""),
        "timeframe": g.get("timeframe", ""),
        "drivers": g.get("drivers", ""),
        "support": g.get("support", ""),
        "commitment": g.get("commitment", ""),
        "recent_goal_answers": [t.get("text","") for t in turns if t.get("pillar")=="goals" and t.get("role")=="user"][-5:]
    }
    try:
        txt = _llm.invoke({"system": system, "user": json.dumps(payload, ensure_ascii=False)}).content.strip()
    except Exception:
        txt = ""
    return txt or "Set one clear 12‑week goal, three weekly actions with metrics, and a weekly check‑in."


# ──────────────────────────────────────────────────────────────────────────────
# Flow (start + continue)
# ──────────────────────────────────────────────────────────────────────────────

def start_combined_assessment(user: User):
    """Start the multi-pillar assessment using per‑pillar systems."""
    with SessionLocal() as s:
        s.execute(
            update(AssessSession)
            .where(AssessSession.user_id == user.id,
                   AssessSession.domain == "combined",
                   AssessSession.is_active == True)
            .values(is_active=False)
        )
        sess = AssessSession(
            user_id=user.id,
            domain="combined",
            is_active=True,
            turn_count=0,
            state=json.dumps({"turns": [], "current": "nutrition", "results": {}}),
        )
        s.add(sess); s.commit(); s.refresh(sess)

        # create review run
        try:
            run_id = start_run(
                user_id=user.id,
                pillars=PILLAR_ORDER,
                model_name="gpt-5-thinking",
                kb_version="1.0.0",
                rubric_version="1.0.0",
            )
        except Exception:
            run_id = None

        intro = (
            "Hi! I’ll do a quick 4‑part check‑in to tailor your coaching: "
            "Nutrition, Training, Resilience, and your Goals. Let’s start with Nutrition."
        )
        try:
            system = _system_for("nutrition")
            user_msg = (
                "Start at Nutrition. Ask the best opening question in <=200 chars.\n"
                'Return JSON only: {"action":"ask"|"finish","question":"","level":"","confidence":0.0,"rationale":"","scores":{}}'
            )
            raw = _llm.invoke({"system": system, "user": user_msg}).content
        except Exception:
            raw = ""
        out = _parse_json(raw)
        if out.action != "ask" or not out.question:
            out.question = _fallback_first_q("nutrition")

        state = {
            "turns": [
                {"role": "assistant", "pillar": "nutrition", "text": intro},
                {"role": "assistant", "pillar": "nutrition", "question": out.question, "concept": None},
            ],
            "current": "nutrition",
            "results": {},
            "run_id": run_id,
            "turn_idx": 0
        }
        _commit_state(s, sess, state)

    _send_to_user(user, intro)
    _send_to_user(user, out.question)

    if run_id:
        try:
            log_turn(
                run_id=run_id,
                idx=0,
                pillar="nutrition",
                concept_key=None,
                assistant_q=out.question,
                user_a=None,
                retrieval=None,
                llm_raw=raw,
                action="ask",
                deltas=None,
                confidence=None,
                is_clarifier=False,
                before_after=None,
            )
        except Exception:
            pass


def continue_combined_assessment(user: User, user_text: str) -> bool:
    """Advance one step using the system for the current pillar (or goals bank)."""
    with SessionLocal() as s:
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

        # Quick command: PDF report link
        cmd = (user_text or "").strip().lower()
        if cmd in {"report", "pdf", "report please", "send report", "pdf report"}:
            base = os.getenv("PUBLIC_BASE_URL")
            link = f"https://{base}/reports/{user.id}/latest.pdf" if base else f"/reports/{user.id}/latest.pdf"
            _send_to_user(user, f"Here is your latest report: {link}")
            return True
        turns = state.get("turns", [])
        current = state.get("current", "nutrition")
        results = state.get("results", {})
        run_id = state.get("run_id")
        turn_idx = int(state.get("turn_idx", 0)) + 1

        # record user's reply
        user_text = (user_text or "").strip()
        turns.append({"role": "user", "pillar": current, "text": user_text})

        # Select concept + retrieve snippets (for core pillars)
        concept_key = None
        retrieval_ctx = None
        if current in ("nutrition", "training", "resilience"):
            concept_key = _select_concept(user.id, current, results, turns)
            if concept_key:
                try:
                    raw_snips = retrieve_snippets(pillar=current, concept_key=concept_key, query_text=user_text)
                    retrieval_ctx = diversify(raw_snips, max_total=5)
                except Exception:
                    retrieval_ctx = None

        # ─────────── Core pillars (LLM)
        if current in ("nutrition", "training", "resilience"):
            pillar_turns = [t for t in turns if t.get("pillar") == current]
            already_asked = [t.get("question") for t in pillar_turns if t.get("role") == "assistant" and t.get("question")]
            already_asked_norm = list({_norm(q) for q in already_asked if q})
            dialogue = _as_dialogue_simple(pillar_turns)
            payload = {
                "history": dialogue,
                "already_asked": already_asked,
                "already_asked_norm": already_asked_norm,
                "turns_so_far": _count_user_replies_for_pillar(turns, current),
                "retrieval": retrieval_ctx or [],
                "concept_focus": concept_key or "",
            }

            try:
                system = _system_for(current)
                user_msg = (
                    "Continue this pillar.\n"
                    f"Dialogue (JSON): {json.dumps(payload, ensure_ascii=False)}\n\n"
                    "Rules:\n"
                    "- Ask EXACTLY ONE short question (<=200 chars), OR finish when confident (>=0.8).\n"
                    "- Never repeat earlier assistant questions (see already_asked / already_asked_norm).\n"
                    "- If unsure, ask a tight clarifier (<20 words).\n"
                    f"- Prefer focusing on concept '{concept_key}' for this turn when crafting the next question.\n"
                    'Return JSON only: {"action":"ask"|"finish","question":"","level":"","confidence":0.0,"rationale":"","scores":{}}'
                )
                raw = _llm.invoke({"system": system, "user": user_msg}).content
            except Exception:
                raw = ""
            out = _parse_json(raw)

            usr_replies = _count_user_replies_for_pillar(turns, current)
            asked_unique = _count_unique_assistant_qs_for_pillar(turns, current)
            wants_finish_domain = (out.action == "finish_domain") or (out.confidence >= 0.8)
            hit_turn_cap = usr_replies >= (MIN_QS[current] + 3) or len(turns) >= 60
            must_ask_more = (usr_replies < MIN_QS[current]) or (asked_unique < MIN_QS[current])

            if (wants_finish_domain and must_ask_more) and not hit_turn_cap:
                proposed = (out.question or "").strip()
                next_q = _dedupe_question(turns, proposed, current) or _fallback_followup_q(current)
                next_q = _pick_sendable_question(turns, current, next_q)
                turns.append({"role": "assistant", "pillar": current, "question": next_q, "concept": concept_key})
                state["turns"] = turns
                state["turn_idx"] = turn_idx
                _commit_state(s, sess, state)
                _send_to_user(user, next_q)

                if concept_key:
                    _bump_concept_asked(user.id, concept_key)

                if run_id:
                    try:
                        log_turn(
                            run_id=run_id, idx=turn_idx, pillar=current, concept_key=concept_key,
                            assistant_q=next_q, user_a=user_text, retrieval=retrieval_ctx,
                            llm_raw=raw, action="ask", deltas=None, confidence=None,
                            is_clarifier=True if next_q and len(next_q) <= 110 else False,
                            before_after=None,
                        )
                    except Exception:
                        pass
                return True

            # Finish this pillar
            if wants_finish_domain or hit_turn_cap:
                # Persist pillar result + scores
                results[current] = {
                    "level": out.level,
                    "confidence": out.confidence,
                    "rationale": out.rationale,
                    "scores": out.scores or results.get(current, {}).get("scores", {}) or {},
                }
                # Update per-concept scores in UserConceptState
                _update_concepts_from_scores(user.id, current, results[current]["scores"])

                # Feedback to user
                recent_for_feedback = [t for t in turns if t.get("pillar") == current][-10:]
                pname = "Nutrition" if current == "nutrition" else ("Training" if current == "training" else "Resilience")
                feedback = _generate_feedback(pname, out.level, recent_for_feedback)
                _send_to_user(user, feedback)

                # Send scores dump if present (keep zeros as requested)
                sc = results[current].get("scores") or {}
                if sc:
                    lines = [f"• {k.replace('_',' ').title()}: {round(float(v or 0.0), 2)}" for k, v in sc.items()]
                    _send_to_user(user, f"{pname} concept scores:\n" + "\n".join(lines))

                if run_id:
                    try:
                        finish_pillar(
                            run_id=run_id, pillar=current, level=out.level,
                            confidence=float(out.confidence or 0.0),
                            coverage=results[current].get("scores") or {},
                            summary_msg=feedback
                        )
                    except Exception:
                        pass

                # Transition
                nxt = _next_pillar(current)
                state["results"] = results
                if nxt:
                    state["current"] = nxt
                    transition_msg = f"Great — {current.title()} done. Now a quick check on {nxt.title()} ⭐"
                    first_q = _dedupe_question(turns, _fallback_first_q(nxt), nxt) or _fallback_followup_q(nxt)
                    turns.append({"role": "assistant", "pillar": nxt, "text": transition_msg})
                    turns.append({"role": "assistant", "pillar": nxt, "question": first_q, "concept": None})
                    state["turns"] = turns
                    state["turn_idx"] = turn_idx
                    _commit_state(s, sess, state)
                    _send_to_user(user, transition_msg)
                    _send_to_user(user, first_q)
                    if run_id:
                        try:
                            log_turn(
                                run_id=run_id, idx=turn_idx, pillar=nxt, concept_key=None,
                                assistant_q=first_q, user_a=None, retrieval=None,
                                llm_raw=None, action="ask", deltas=None, confidence=None,
                                is_clarifier=False, before_after=None
                            )
                        except Exception:
                            pass
                    return True
                else:
                    state["turns"] = turns
                    state["turn_idx"] = turn_idx
                    _commit_state(s, sess, state)
                    return True

            # Ask another within current pillar
            proposed = (out.question or "").strip()
            next_q = _dedupe_question(turns, proposed, current) or _fallback_followup_q(current)
            next_q = _pick_sendable_question(turns, current, next_q)
            if not next_q:
                next_q = _fallback_followup_q(current)

            turns.append({"role": "assistant", "pillar": current, "question": next_q, "concept": concept_key})
            state["turns"] = turns
            state["turn_idx"] = turn_idx
            _commit_state(s, sess, state)
            _send_to_user(user, next_q)

            if concept_key:
                _bump_concept_asked(user.id, concept_key)

            if run_id:
                try:
                    log_turn(
                        run_id=run_id, idx=turn_idx, pillar=current, concept_key=concept_key,
                        assistant_q=next_q, user_a=user_text, retrieval=retrieval_ctx,
                        llm_raw=raw, action="ask", deltas=None, confidence=None,
                        is_clarifier=True if next_q and len(next_q) <= 110 else False,
                        before_after=None,
                    )
                except Exception:
                    pass
            return True

        # ─────────── GOALS pillar
        if current == "goals":
            results["goals"] = _extract_goals_from_answer(user_text, results.get("goals"))
            asked_unique = _count_unique_assistant_qs_for_pillar(turns, "goals")
            if asked_unique < MIN_QS["goals"]:
                asked_texts = _goals_already_asked_texts(turns)
                qd = _choose_next_goals_question(turns, results)
                q_text = (qd.get("text") or _fallback_followup_q("goals")).strip()
                if any(_too_similar(q_text, prev) for prev in asked_texts):
                    alt = _next_from_bank(turns, "goals")
                    q_text = alt or _dedupe_question(turns, q_text, "goals")
                turns.append({"role": "assistant", "pillar": "goals", "qid": qd.get("id"), "question": q_text})
                state["turns"] = turns; state["results"] = results
                state["turn_idx"] = turn_idx
                _commit_state(s, sess, state)
                _send_to_user(user, q_text)
                if run_id:
                    try:
                        log_turn(
                            run_id=run_id, idx=turn_idx, pillar="goals", concept_key=None,
                            assistant_q=q_text, user_a=user_text, retrieval=None,
                            llm_raw=json.dumps({"action":"ask"}), action="ask", deltas=None, confidence=None,
                            is_clarifier=False, before_after=None,
                        )
                    except Exception:
                        pass
                return True

            # Finish: guidance, persist to User, cadences, summary
            guidance = _goals_guidance(results, turns)
            turns.append({"role": "assistant", "pillar": "goals", "text": guidance})
            state["turns"] = turns; state["results"] = results
            sess.is_active = False
            state["turn_idx"] = turn_idx
            _commit_state(s, sess, state)

            # Persist pillar levels and goals to User, mark onboard complete
            u_db = s.get(User, user.id)
            u_db.nutrition_level  = results.get("nutrition", {}).get("level")
            u_db.training_level   = results.get("training", {}).get("level")
            try:
                getattr(u_db, "resilience_level")
                u_db.resilience_level = results.get("resilience", {}).get("level")
            except AttributeError:
                u_db.psych_level = results.get("resilience", {}).get("level")
            u_db.onboard_complete = True
            # Save goals snapshot
            g = results.get("goals", {}) or {}
            u_db.goal_primary     = (g.get("primary_goal") or "").strip() or None
            u_db.goal_timeframe   = (g.get("timeframe") or "").strip() or None
            u_db.goal_drivers     = (g.get("drivers") or "").strip() or None
            u_db.goal_support     = (g.get("support") or "").strip() or None
            u_db.goal_commitment  = (g.get("commitment") or "").strip() or None
            u_db.goals_updated_at = datetime.utcnow()
            s.commit()

            # Apply cadences
            n_level = (results.get("nutrition", {}) or {}).get("level") or u_db.nutrition_level or "Moderate"
            t_level = (results.get("training",  {}) or {}).get("level") or u_db.training_level  or "Moderate"
            r_level = (results.get("resilience",{}) or {}).get("level") or getattr(u_db, "resilience_level", None) or getattr(u_db, "psych_level", None) or "Moderate"
            apply_nutrition_cadence(user.id, n_level)
            apply_training_cadence(user.id,  t_level)
            apply_psych_cadence(user.id,     r_level)

            # Final summary incl. goal outcomes
            goal_primary   = (g.get("primary_goal") or "").strip()
            goal_timeframe = (g.get("timeframe") or "").strip()
            goal_support   = (g.get("support") or "").strip()
            goal_drivers   = (g.get("drivers") or "").strip()
            goal_commit    = (g.get("commitment") or "").strip()
            goal_line = goal_primary or "a clear primary goal"
            tf_part   = f" (target: {goal_timeframe})" if goal_timeframe else ""

            def _safe_conf(p): 
                try:
                    return round(float((results.get(p) or {}).get("confidence") or 0.0), 3)
                except Exception:
                    return 0.0
            def _lvl(p): return (results.get(p) or {}).get("level") or "Unknown"

            summary = (
                "All set! Levels & scores:\n"
                f"• Nutrition: {_lvl('nutrition')} (confidence {_safe_conf('nutrition')})\n"
                f"• Training: {_lvl('training')} (confidence {_safe_conf('training')})\n"
                f"• Resilience: {_lvl('resilience')} (confidence {_safe_conf('resilience')})\n"
                "\nYour goal:\n"
                f"• {goal_line}{tf_part}"
            ).rstrip()

            _send_to_user(user, guidance)
            _send_to_user(user, summary)

            if run_id:
                try:
                    finish_pillar(
                        run_id=run_id, pillar="goals", level="N/A",
                        confidence=1.0, coverage=g, summary_msg=guidance
                    )
                    finish_run(run_id)
                except Exception:
                    pass
            return True

        return False


# ──────────────────────────────────────────────────────────────────────────────
# Convenience
# ──────────────────────────────────────────────────────────────────────────────

def resend_last_question(user: User) -> bool:
    """Resend the last assistant question for the active session (if any)."""
    with SessionLocal() as s:
        sess: Optional[AssessSession] = s.execute(
            select(AssessSession).where(
                AssessSession.user_id == user.id,
                AssessSession.is_active == True,
            ).order_by(AssessSession.id.desc())
        ).scalars().first()
        if not sess:
            return False

        try:
            state = json.loads(sess.state or "{}")
        except Exception:
            return False

        if sess.domain == "combined":
            turns = state.get("turns", [])
            for t in reversed(turns):
                if t.get("role") == "assistant" and t.get("question"):
                    _send_to_user(user, t["question"])
                    return True
        else:
            hist = state.get("history", [])
            for t in reversed(hist):
                if t.get("role") == "assistant" and t.get("question"):
                    _send_to_user(user, t["question"])
                    return True
    return False
