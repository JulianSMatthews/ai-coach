"""
General coaching support chat, enabled after any weekly flow ends.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import User, UserPreference, WeeklyFocus, AssessmentRun
from .nudges import send_whatsapp
from .prompts import build_prompt, run_llm_prompt
COACH_NAME = os.getenv("COACH_NAME", "Gia")

STATE_KEY = "general_support_state"


def _get_state(session: Session, user_id: int) -> Optional[dict]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if not pref or not pref.value:
        return None
    try:
        return json.loads(pref.value)
    except Exception:
        return None


def _set_state(session: Session, user_id: int, state: Optional[dict]) -> None:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if state is None:
        if pref:
            session.delete(pref)
        return
    data = json.dumps(state)
    if pref:
        pref.value = data
    else:
        session.add(UserPreference(user_id=user_id, key=STATE_KEY, value=data))


def has_active_state(user_id: int) -> bool:
    with SessionLocal() as s:
        return _get_state(s, user_id) is not None


def clear(user_id: int) -> None:
    with SessionLocal() as s:
        _set_state(s, user_id, None)
        s.commit()


def activate(
    user_id: int,
    source: str | None = None,
    week_no: int | None = None,
    history: list[dict] | None = None,
    send_intro: bool = True,
) -> None:
    state = {
        "source": source,
        "week_no": week_no,
        "history": history or [],
        "intro_sent": bool(send_intro),
    }
    with SessionLocal() as s:
        _set_state(s, user_id, state)
        s.commit()
        user = s.query(User).get(user_id)
    if send_intro and user and getattr(user, "phone", None):
        name = (getattr(user, "first_name", None) or "there").strip().title()
        intro = f"*Coach* Hi {name}, {COACH_NAME} here. I'm here if you want a hand, have a good day."
        print(f"[coach] prompt started source={source or 'unknown'} user_id={user_id}")
        send_whatsapp(to=user.phone, text=intro)


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def _infer_week_no(session: Session, user_id: int, wf: WeeklyFocus) -> int:
    base_start = None
    run = (
        session.query(AssessmentRun)
        .filter(AssessmentRun.user_id == user_id)
        .order_by(AssessmentRun.id.desc())
        .first()
    )
    if run:
        base_dt = getattr(run, "started_at", None) or getattr(run, "created_at", None)
        if isinstance(base_dt, datetime):
            base_start = base_dt.date() - timedelta(days=base_dt.date().weekday())
    if base_start is None:
        earliest = (
            session.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user_id)
            .order_by(WeeklyFocus.starts_on.asc())
            .first()
        )
        if earliest and getattr(earliest, "starts_on", None):
            try:
                base_start = earliest.starts_on.date()
            except Exception:
                base_start = None
    wf_start = None
    if getattr(wf, "starts_on", None):
        try:
            wf_start = wf.starts_on.date()
        except Exception:
            wf_start = None
    if base_start is None or wf_start is None:
        return 1
    try:
        return max(1, int(((wf_start - base_start).days // 7) + 1))
    except Exception:
        return 1


def _resolve_week_no(session: Session, user_id: int, state_week_no: int | None) -> int | None:
    if state_week_no:
        return state_week_no
    wf = _latest_weekly_focus(session, user_id)
    if not wf:
        return None
    if getattr(wf, "week_no", None):
        return wf.week_no
    return _infer_week_no(session, user_id, wf)


def _support_prompt(
    user: User,
    history: list[dict],
    user_message: str | None,
    week_no: int | None,
    source: str | None,
):
    transcript = []
    for turn in history:
        role = (turn.get("role") or "").strip()
        content = (turn.get("content") or "").strip()
        if role and content:
            transcript.append(f"{role.upper()}: {content}")
    if user_message:
        transcript.append(f"USER: {user_message}")

    extras_parts = []
    if source:
        extras_parts.append(f"flow={source}")
    if week_no:
        extras_parts.append(f"week_no={week_no}")
    extras = "; ".join(extras_parts)
    timeframe = f"Week {week_no}" if week_no else "current week"

    return build_prompt(
        "general_support",
        user_id=user.id,
        coach_name=COACH_NAME,
        user_name=(user.first_name or ""),
        locale=getattr(user, "tz", "UK") or "UK",
        history=transcript,
        week_no=week_no,
        timeframe=timeframe,
        extras=extras,
    )


def handle_message(user: User, text: str) -> None:
    msg = (text or "").strip()
    if not msg:
        return
    with SessionLocal() as s:
        state = _get_state(s, user.id)
        if not state:
            return
        history = state.get("history") or []
        history = history[-12:]
        week_no = _resolve_week_no(s, user.id, state.get("week_no"))
        source = state.get("source")
        cleaned = msg.strip().lower()
        intro_sent = bool(state.get("intro_sent"))
        if not intro_sent and cleaned in {"all good", "all ok", "all okay", "need help"}:
            name = (getattr(user, "first_name", None) or "there").strip().title()
            intro = f"*Coach* Hi {name}, {COACH_NAME} here. I'm here if you want a hand, have a good day."
            print(f"[coach] prompt started source={source or 'unknown'} user_id={user.id}")
            send_whatsapp(to=user.phone, text=intro)
            state["intro_sent"] = True
            _set_state(s, user.id, state)
            s.commit()
            return

    prompt_assembly = _support_prompt(user, history, msg, week_no, source)

    print(f"[prompts] logging LLM prompt touchpoint=general_support user_id={user.id}")
    candidate = run_llm_prompt(
        prompt_assembly.text,
        user_id=user.id,
        touchpoint="general_support",
        context_meta={"source": source, "week_no": week_no},
        prompt_variant=prompt_assembly.variant,
        task_label=prompt_assembly.task_label,
        prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
        block_order=prompt_assembly.block_order,
        log=True,
    )

    text_out = None
    if candidate:
        text_out = candidate.strip()
    if not text_out:
        text_out = "Sorry - I couldn't pull that response just now. Please try again."
    if not text_out.lower().startswith("*coach*"):
        text_out = "*Coach* " + text_out

    new_history = list(history)
    new_history.append({"role": "user", "content": msg})
    new_history.append({"role": "assistant", "content": text_out})
    new_history = new_history[-12:]

    with SessionLocal() as s:
        _set_state(
            s,
            user.id,
            {"source": source, "week_no": week_no, "history": new_history},
        )
        s.commit()

    send_whatsapp(to=user.phone, text=text_out)
