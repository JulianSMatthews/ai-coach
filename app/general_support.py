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
from .daily_habits import build_daily_tracker_generation_context
from .models import User, UserPreference, WeeklyFocus, AssessmentRun
from .coaching_delivery import send_coaching_text
from .programme_timeline import week_no_for_focus_start
from .prompts import build_prompt, run_llm_prompt
COACH_NAME = os.getenv("COACH_NAME", "Gia")

STATE_KEY = "general_support_state"


def _coach_message_prefix() -> str:
    label = (COACH_NAME or "").strip() or "Gia"
    return f"*{label}*"


def _coach_message_prefixes() -> tuple[str, ...]:
    current = _coach_message_prefix().lower()
    if current == "*coach*":
        return (current,)
    return (current, "*coach*")


def _has_coach_prefix(text: str | None) -> bool:
    raw = (text or "").strip().lower()
    return any(raw.startswith(prefix) for prefix in _coach_message_prefixes())


def _strip_coach_prefix(text: str | None) -> str:
    raw = (text or "").strip()
    lowered = raw.lower()
    for prefix in _coach_message_prefixes():
        if lowered.startswith(prefix):
            return raw[len(prefix):].lstrip(" \n\t:-").strip()
    return raw


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
        intro = f"{_coach_message_prefix()} Hi {name}, {COACH_NAME} here. I'm here if you want a hand, have a good day."
        print(f"[coach] prompt started source={source or 'unknown'} user_id={user_id}")
        send_coaching_text(user=user, text=intro, source="general_support")


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def _infer_week_no(session: Session, user_id: int, wf: WeeklyFocus) -> int:
    programme_start = None
    run = (
        session.query(AssessmentRun)
        .filter(AssessmentRun.user_id == user_id)
        .order_by(AssessmentRun.id.desc())
        .first()
    )
    if run:
        base_dt = (
            getattr(run, "finished_at", None)
            or getattr(run, "started_at", None)
            or getattr(run, "created_at", None)
        )
        if isinstance(base_dt, datetime):
            programme_start = base_dt.date()
    if programme_start is None:
        earliest = (
            session.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user_id)
            .order_by(WeeklyFocus.starts_on.asc())
            .first()
        )
        if earliest and getattr(earliest, "starts_on", None):
            try:
                programme_start = earliest.starts_on.date()
            except Exception:
                programme_start = None
    wf_start = None
    if getattr(wf, "starts_on", None):
        try:
            wf_start = wf.starts_on.date()
        except Exception:
            wf_start = None
    if wf_start is None:
        return 1
    try:
        return week_no_for_focus_start(programme_start, wf_start)
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


def _safe_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _combined_score(pillar_scores: list[dict]) -> int | None:
    values = [
        _safe_int(item.get("score"))
        for item in (pillar_scores or [])
        if isinstance(item, dict)
    ]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return int(round(sum(values) / max(len(values), 1)))


def _tracker_history_lines(tracker_context: dict) -> list[str]:
    lines: list[str] = []
    selected_focus = tracker_context.get("selected_focus_concept") or {}
    focus_concepts = tracker_context.get("focus_concepts") or []
    okr_context = tracker_context.get("okr_context") or {}
    if selected_focus:
        label = str(selected_focus.get("label") or selected_focus.get("concept_key") or "").strip()
        signal = str(selected_focus.get("signal") or "").strip()
        latest = str(selected_focus.get("latest_value") or "").strip()
        target = str(selected_focus.get("target_label") or "").strip()
        pillar = str(selected_focus.get("pillar_label") or selected_focus.get("pillar_key") or "").strip()
        score = _safe_int(selected_focus.get("score"))
        if label:
            bits = []
            if pillar:
                bits.append(f"pillar={pillar}")
            if signal:
                bits.append(f"signal={signal}")
            if latest:
                bits.append(f"latest={latest}")
            if target:
                bits.append(f"target={target}")
            if score is not None:
                bits.append(f"score={score}/100")
            suffix = f" ({'; '.join(bits)})" if bits else ""
            lines.append(f"Selected tracker focus: {label}{suffix}")
    if focus_concepts:
        lines.append("Recent tracker focus:")
        for item in focus_concepts[:4]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or item.get("concept_key") or "").strip()
            if not label:
                continue
            signal = str(item.get("signal") or "").strip()
            latest = str(item.get("latest_value") or "").strip()
            target = str(item.get("target_label") or "").strip()
            score = _safe_int(item.get("score"))
            bits = [signal] if signal else []
            if latest:
                bits.append(f"latest={latest}")
            if target:
                bits.append(target)
            if score is not None:
                bits.append(f"score={score}/100")
            suffix = f" ({'; '.join(bits)})" if bits else ""
            lines.append(f"- {label}{suffix}")
    if (okr_context or {}).get("habit_steps"):
        lines.append("Active KR habit steps:")
        for step in (okr_context.get("habit_steps") or [])[:5]:
            step_text = str(step or "").strip()
            if step_text:
                lines.append(f"- {step_text}")
    return lines


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
    tracker_context = build_daily_tracker_generation_context(int(user.id))
    pillar_scores = tracker_context.get("pillar_scores") or []
    combined_score = _combined_score(pillar_scores)
    plan_date = str(tracker_context.get("plan_date") or "").strip()
    if plan_date:
        extras_parts.append(f"tracker_date={plan_date}")
    selected_focus = tracker_context.get("selected_focus_concept") or {}
    if selected_focus:
        focus_label = str(selected_focus.get("label") or selected_focus.get("concept_key") or "").strip()
        focus_signal = str(selected_focus.get("signal") or "").strip()
        if focus_label:
            extras_parts.append(f"tracker_focus={focus_label}")
        if focus_signal:
            extras_parts.append(f"tracker_signal={focus_signal}")
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
        source=source,
        scores=pillar_scores,
        combined_score=combined_score,
        tracker_context=tracker_context,
        tracker_history=_tracker_history_lines(tracker_context),
    )


def _generate_support_reply(
    user: User,
    *,
    history: list[dict],
    user_message: str | None,
    week_no: int | None,
    source: str | None,
    include_prefix: bool = True,
) -> str:
    prompt_assembly = _support_prompt(user, history, user_message, week_no, source)

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

    text_out = candidate.strip() if candidate else ""
    if not text_out:
        text_out = "Sorry - I couldn't pull that response just now. Please try again."
    if include_prefix:
        if not _has_coach_prefix(text_out):
            text_out = f"{_coach_message_prefix()} {text_out}"
    else:
        text_out = _strip_coach_prefix(text_out)
    return text_out


def generate_tracker_summary_message(
    user: User,
    *,
    source: str = "app_tracker_summary",
    include_prefix: bool = False,
    user_message: str | None = None,
) -> str:
    with SessionLocal() as s:
        state = _get_state(s, int(user.id)) or {}
        history = list(state.get("history") or [])[-12:]
        week_no = _resolve_week_no(s, int(user.id), state.get("week_no"))
        resolved_source = str(source or state.get("source") or "app_tracker_summary").strip() or "app_tracker_summary"
    return _generate_support_reply(
        user,
        history=history,
        user_message=user_message or "Please give me today's coaching message based on my latest tracker results.",
        week_no=week_no,
        source=resolved_source,
        include_prefix=include_prefix,
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
            intro = f"{_coach_message_prefix()} Hi {name}, {COACH_NAME} here. I'm here if you want a hand, have a good day."
            print(f"[coach] prompt started source={source or 'unknown'} user_id={user.id}")
            send_coaching_text(user=user, text=intro, source="general_support")
            state["intro_sent"] = True
            _set_state(s, user.id, state)
            s.commit()
            return

    text_out = _generate_support_reply(
        user,
        history=history,
        user_message=msg,
        week_no=week_no,
        source=source,
        include_prefix=True,
    )

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

    send_coaching_text(user=user, text=text_out, source="general_support")
