"""
Psychological/readiness mini-assessment (6 items, 1–5 Likert).
Runs post-wellbeing assessment to tailor KR sizing and coaching tone.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .db import SessionLocal
from .models import User, UserPreference, PsychProfile, AssessSession, AssessmentRun, JobAudit
from . import nudges


def _send_safe(user: User, text: str):
    """Send outbound; mocking is handled by script-level patches to nudges.send_whatsapp."""
    nudges.send_whatsapp(to=user.phone, text=text)

STATE_KEY = "psych_state"
PENDING_SUMMARY_KEY = "pending_assessment_summary"

QUESTIONS = [
    ("q1", "I feel ready to make changes to my daily habits right now."),
    ("q2", "Improving my wellbeing feels important to me at this point in my life."),
    ("q3", "I find it easy to stick to routines once I’ve started them."),
    ("q4", "Stress or overwhelm often makes it harder for me to stay consistent with routines."),
    ("q5", "I sometimes use food, screens, or other habits to cope with stress or low mood."),
    ("q6", "I prefer clear structure, guidance, and accountability to stay consistent."),
]

OPTIONS = "1️⃣ Strongly disagree | 2️⃣ Disagree | 3️⃣ Unsure | 4️⃣ Agree | 5️⃣ Strongly agree"
TOTAL_QUESTIONS = len(QUESTIONS)


def _get_state(session, user_id: int) -> Optional[dict]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if not pref or not pref.value:
        return None
    try:
        import json

        return json.loads(pref.value)
    except Exception:
        return None


def _set_state(session, user_id: int, state: Optional[dict]):
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if state is None:
        if pref:
            session.delete(pref)
        return
    import json

    data = json.dumps(state)
    if pref:
        pref.value = data
    else:
        session.add(UserPreference(user_id=user_id, key=STATE_KEY, value=data))


def store_pending_summary(user_id: int, msg: str):
    with SessionLocal() as s:
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == PENDING_SUMMARY_KEY)
            .one_or_none()
        )
        if pref:
            pref.value = msg
        else:
            s.add(UserPreference(user_id=user_id, key=PENDING_SUMMARY_KEY, value=msg))
        s.commit()


def pop_pending_summary(session, user_id: int) -> Optional[str]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == PENDING_SUMMARY_KEY)
        .one_or_none()
    )
    if not pref:
        return None
    msg = pref.value
    session.delete(pref)
    return msg


def has_active_state(user_id: int) -> bool:
    with SessionLocal() as s:
        return _get_state(s, user_id) is not None


def bind_assessment_run(user_id: int, assessment_run_id: Optional[int]) -> bool:
    """
    Attach/update assessment_run_id on an active psych state.
    Returns True when state was updated.
    """
    if not assessment_run_id:
        return False
    with SessionLocal() as s:
        state = _get_state(s, user_id)
        if not state:
            return False
        state["assessment_run_id"] = int(assessment_run_id)
        _set_state(s, user_id, state)
        s.commit()
        return True


def _resolve_latest_run_id(session, user_id: int) -> Optional[int]:
    try:
        run = (
            session.query(AssessmentRun)
            .filter(AssessmentRun.user_id == user_id)
            .order_by(
                AssessmentRun.finished_at.desc().nullslast(),
                AssessmentRun.id.desc(),
            )
            .first()
        )
        if run and getattr(run, "id", None):
            return int(run.id)
    except Exception:
        return None
    return None


def _ask_question(user: User, idx: int):
    key, text = QUESTIONS[idx]
    _send_safe(
        user,
        f"Q{idx+1}/{TOTAL_QUESTIONS}:\n{text}\n\n{OPTIONS}\n(Reply with 1-5.)",
    )


def _progress_line(idx: int) -> str:
    total = TOTAL_QUESTIONS
    # idx is 0-based for next question; we want completed = idx
    done = max(0, min(idx, total))
    bar_parts = []
    if done > 0:
        bar_parts.append("🟩" * done)
    if done < total:
        # Highlight the current position in orange to mirror the main assessment
        remaining = max(total - done - 1, 0)
        bar_parts.append("🟧")
        bar_parts.append("⬜️" * remaining)
    bar = f"[{''.join(bar_parts)}]"
    return f"Progress: {bar} {done}/{total}"


def _ack_answer(user: User, text: str, idx: int):
    snippet = (text or "").strip()
    name = (getattr(user, "first_name", "") or "").strip()
    prefix = f"Thanks {name}".strip() if name else "Thanks"
    hint = " (type *redo* to change or *restart* to begin again)"
    body = f'{prefix}, logged "{snippet}".{hint}'
    progress = _progress_line(idx)
    _send_safe(user, f"{body}\n\n{progress}")


def start(user: User, assessment_run_id: Optional[int] = None, close_assessment_sessions: bool = True):
    with SessionLocal() as s:
        if close_assessment_sessions:
            try:
                s.query(AssessSession).filter(
                    AssessSession.user_id == user.id,
                    AssessSession.is_active == True  # noqa: E712
                ).update({"is_active": False})
            except Exception:
                pass
        _set_state(s, user.id, {"idx": 0, "answers": {}, "assessment_run_id": assessment_run_id})
        s.commit()
    _send_safe(
        user,
        f"I’m going to ask {TOTAL_QUESTIONS} quick questions about your habits and how you approach change. It helps me tailor the plan and support for your 12-week programme. Takes about a minute.\n\nType *redo* to repeat the previous question or *restart* to start again at any time.",
    )
    _ask_question(user, 0)


def latest_profile(user_id: int) -> Optional[PsychProfile]:
    """Return the most recent psych profile for a user."""
    with SessionLocal() as s:
        return (
            s.query(PsychProfile)
            .filter(PsychProfile.user_id == user_id)
            .order_by(PsychProfile.completed_at.desc().nullslast(), PsychProfile.id.desc())
            .first()
        )


def _derive_profile(scores: dict) -> tuple[dict, dict, dict]:
    # Section averages (6-question version)
    sec = {
        "readiness": (scores.get("q1", 0) + scores.get("q2", 0)) / 2,
        "self_reg": (scores.get("q3", 0) + scores.get("q4", 0)) / 2,
        "emotional": scores.get("q5", 0),
        "confidence": scores.get("q6", 0),
    }
    flags = {
        "high_readiness": sec["readiness"] >= 4 and sec["confidence"] >= 4,
        "low_readiness": sec["readiness"] <= 2.5 or sec["confidence"] <= 2.5,
        "stress_sensitive": scores.get("q4", 0) >= 4 or scores.get("q5", 0) >= 4,
        "low_self_reg": scores.get("q3", 0) <= 2,
        "perfectionism": False,  # not captured in the 6-question set
        "high_accountability": scores.get("q6", 0) >= 4,
    }
    params = {
        "kr_scale_hint": 0.7 if flags["low_readiness"] else 1.0,
        "structure_level": "high" if flags["low_self_reg"] or flags["high_accountability"] else "normal",
        "tone": "gentle" if flags["low_readiness"] or flags["stress_sensitive"] or flags["perfectionism"] else "standard",
        "focus_bias": "resilience" if flags["stress_sensitive"] else "balanced",
    }
    return sec, flags, params


def handle_message(user: User, text: str):
    msg = (text or "").strip()
    lower = msg.lower()
    with SessionLocal() as s:
        state = _get_state(s, user.id)
        if state is None:
            # allow manual start
            start(user)
            return
        idx = state.get("idx", 0)
        answers = state.get("answers", {})
        if idx >= len(QUESTIONS):
            _set_state(s, user.id, None)
            s.commit()
            _send_safe(user, "Thanks, your readiness profile is already saved.")
            return
        if lower in {"restart", "reset"}:
            state = {"idx": 0, "answers": {}, "assessment_run_id": state.get("assessment_run_id")}
            _set_state(s, user.id, state); s.commit()
            _send_safe(user, "No problem—let’s restart. Here’s the first question.")
            _ask_question(user, 0)
            return
        if lower == "redo":
            prev_idx = max(0, idx - 1)
            if idx > 0:
                prev_key, _ = QUESTIONS[idx - 1]
                answers.pop(prev_key, None)
            state["idx"] = prev_idx
            state["answers"] = answers
            _set_state(s, user.id, state); s.commit()
            _send_safe(user, "Got it—let’s redo that one. (Reply 1-5; you can also type restart.)")
            _ask_question(user, prev_idx)
            return
        if msg not in {"1", "2", "3", "4", "5"}:
            _send_safe(user, "Please reply with 1, 2, 3, 4, or 5. (Or type redo / restart.)")
            return
        qkey, _ = QUESTIONS[idx]
        answers[qkey] = int(msg)
        _ack_answer(user, msg, idx + 1)
        idx += 1
        if idx >= len(QUESTIONS):
            completed_at = datetime.utcnow()
            sec, flags, params = _derive_profile(answers)
            profile = PsychProfile(
                user_id=user.id,
                assessment_run_id=state.get("assessment_run_id"),
                scores=answers,
                section_averages=sec,
                flags=flags,
                parameters=params,
                completed_at=completed_at,
            )
            s.add(profile)
            try:
                (
                    s.query(User)
                    .filter(User.id == user.id, User.first_assessment_completed.is_(None))
                    .update({"first_assessment_completed": completed_at}, synchronize_session=False)
                )
            except Exception:
                pass
            _set_state(s, user.id, None)
            pending = pop_pending_summary(s, user.id)
            s.commit()

            # Habit readiness is part of assessment completion. Once profile is saved,
            # trigger habit-readiness narrative generation.
            run_id = state.get("assessment_run_id")
            run_id_source = "state"
            if not run_id:
                run_id = _resolve_latest_run_id(s, int(user.id))
                run_id_source = "latest_run_lookup" if run_id else "missing"
            if run_id:
                try:
                    from .job_queue import enqueue_job
                    from .llm import should_use_worker

                    worker_enabled = bool(should_use_worker())
                    job_id = enqueue_job(
                        "assessment_narratives_habit_seed",
                        {"run_id": int(run_id), "user_id": int(user.id), "trigger": "psych_complete"},
                        user_id=int(user.id),
                    )
                    try:
                        s.add(
                            JobAudit(
                                job_name="assessment_narratives_habit_seed_enqueue_psych_complete",
                                status="ok",
                                payload={
                                    "run_id": int(run_id),
                                    "user_id": int(user.id),
                                    "job_id": int(job_id),
                                    "worker_mode_enabled": worker_enabled,
                                    "run_id_source": run_id_source,
                                },
                            )
                        )
                        s.commit()
                    except Exception:
                        s.rollback()
                except Exception as e:
                    try:
                        s.add(
                            JobAudit(
                                job_name="assessment_narratives_habit_seed_enqueue_psych_complete",
                                status="error",
                                payload={
                                    "run_id": int(run_id),
                                    "user_id": int(user.id),
                                    "run_id_source": run_id_source,
                                },
                                error=repr(e),
                            )
                        )
                        s.commit()
                    except Exception:
                        s.rollback()
            else:
                try:
                    s.add(
                        JobAudit(
                            job_name="assessment_narratives_habit_seed_enqueue_psych_complete",
                            status="error",
                            payload={"run_id": None, "user_id": int(user.id), "run_id_source": "missing"},
                            error="missing_run_id",
                        )
                    )
                    s.commit()
                except Exception:
                    s.rollback()
            if pending:
                _send_safe(user, pending)
            _send_safe(
                user,
                "Thanks—saved your readiness profile. I’ll use this to set the right KR load and coaching style.",
            )
            return
        state["idx"] = idx
        state["answers"] = answers
        _set_state(s, user.id, state)
        s.commit()
    _ask_question(user, idx)
