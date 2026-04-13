"""
General coaching support chat, enabled after any weekly flow ends.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .db import SessionLocal
from .daily_habits import (
    build_daily_tracker_generation_context,
    build_daily_tracker_generation_context_snapshot,
)
from .models import User, UserPreference, WeeklyFocus, AssessmentRun
from .coaching_delivery import send_coaching_text
from .programme_timeline import week_no_for_focus_start
from .prompts import build_prompt, run_llm_prompt
COACH_NAME = os.getenv("COACH_NAME", "Gia")

STATE_KEY = "general_support_state"
TRACKER_SUMMARY_CACHE_KEY = "coach_home_tracker_summary_cache_v2"


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


def _get_json_pref(session: Session, user_id: int, key: str) -> Optional[dict]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == key)
        .one_or_none()
    )
    if not pref or not pref.value:
        return None
    try:
        return json.loads(pref.value)
    except Exception:
        return None


def _set_json_pref(session: Session, user_id: int, key: str, payload: Optional[dict]) -> None:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == key)
        .one_or_none()
    )
    if payload is None:
        if pref:
            session.delete(pref)
        return
    data = json.dumps(payload, default=str)
    if pref:
        pref.value = data
    else:
        session.add(UserPreference(user_id=user_id, key=key, value=data))


def _get_state(session: Session, user_id: int) -> Optional[dict]:
    return _get_json_pref(session, user_id, STATE_KEY)


def _set_state(session: Session, user_id: int, state: Optional[dict]) -> None:
    _set_json_pref(session, user_id, STATE_KEY, state)


def has_active_state(user_id: int) -> bool:
    with SessionLocal() as s:
        return _get_state(s, user_id) is not None


def clear(user_id: int) -> None:
    with SessionLocal() as s:
        _set_state(s, user_id, None)
        s.commit()


def _apply_prefix_preference(text: str | None, *, include_prefix: bool) -> str:
    normalized = _strip_coach_prefix(text)
    if include_prefix and normalized:
        return normalized if _has_coach_prefix(normalized) else f"{_coach_message_prefix()} {normalized}"
    return normalized


def _tracker_summary_cache_signature(
    user_id: int,
    tracker_snapshot: dict | None = None,
) -> tuple[str, str | None]:
    snapshot = tracker_snapshot if isinstance(tracker_snapshot, dict) else build_daily_tracker_generation_context_snapshot(int(user_id))
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    return (
        str(snapshot.get("context_hash") or "").strip(),
        str(context.get("plan_date") or "").strip() or None,
    )


def get_cached_tracker_summary_message(
    user_id: int,
    *,
    include_prefix: bool = False,
    tracker_snapshot: dict | None = None,
) -> str | None:
    context_hash, plan_date = _tracker_summary_cache_signature(int(user_id), tracker_snapshot=tracker_snapshot)
    if not context_hash or not plan_date:
        return None
    with SessionLocal() as s:
        cached = _get_json_pref(s, int(user_id), TRACKER_SUMMARY_CACHE_KEY) or {}
    if (
        str(cached.get("context_hash") or "").strip() != context_hash
        or str(cached.get("plan_date") or "").strip() != plan_date
    ):
        return None
    text = str(cached.get("text") or "").strip()
    if not text:
        return None
    return _apply_prefix_preference(text, include_prefix=include_prefix)


def cache_tracker_summary_message(
    user_id: int,
    text: str,
    *,
    context_hash: str | None = None,
    plan_date: str | None = None,
    source: str = "app_tracker_summary",
    tracker_snapshot: dict | None = None,
) -> None:
    clean_text = _strip_coach_prefix(text)
    if not clean_text:
        return
    resolved_hash = str(context_hash or "").strip()
    resolved_plan_date = str(plan_date or "").strip() or None
    if not resolved_hash or not resolved_plan_date:
        resolved_hash, resolved_plan_date = _tracker_summary_cache_signature(int(user_id), tracker_snapshot=tracker_snapshot)
    if not resolved_hash or not resolved_plan_date:
        return
    payload = {
        "text": clean_text,
        "context_hash": resolved_hash,
        "plan_date": resolved_plan_date,
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        "source": str(source or "app_tracker_summary").strip() or "app_tracker_summary",
    }
    with SessionLocal() as s:
        _set_json_pref(s, int(user_id), TRACKER_SUMMARY_CACHE_KEY, payload)
        s.commit()


def get_or_generate_cached_tracker_summary_message(
    user: User,
    *,
    source: str = "app_tracker_summary",
    include_prefix: bool = False,
    user_message: str | None = None,
    force: bool = False,
    tracker_snapshot: dict | None = None,
) -> str:
    resolved_source = str(source or "app_tracker_summary").strip() or "app_tracker_summary"
    use_cache = resolved_source == "app_tracker_summary" and not str(user_message or "").strip()
    if use_cache and not force:
        cached = get_cached_tracker_summary_message(
            int(user.id),
            include_prefix=include_prefix,
            tracker_snapshot=tracker_snapshot,
        )
        if cached:
            return cached
    text_out = generate_tracker_summary_message(
        user,
        source=resolved_source,
        include_prefix=False,
        user_message=user_message,
        tracker_snapshot=tracker_snapshot,
    )
    if use_cache and text_out:
        cache_tracker_summary_message(
            int(user.id),
            text_out,
            source=resolved_source,
            tracker_snapshot=tracker_snapshot,
        )
    return _apply_prefix_preference(text_out, include_prefix=include_prefix)


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


def _tracker_anchor_date(tracker_context: dict) -> date | None:
    for key in ("tracker_focus_date", "plan_date"):
        raw = str((tracker_context or {}).get(key) or "").strip()
        if not raw:
            continue
        try:
            return date.fromisoformat(raw[:10])
        except Exception:
            continue
    return None


def _education_programme_context(user_id: int, tracker_context: dict) -> dict | None:
    try:
        from .education_plan import get_today_education_plan

        payload = get_today_education_plan(
            int(user_id),
            anchor=_tracker_anchor_date(tracker_context),
        )
    except Exception as exc:
        print(f"[coach] education programme context unavailable user_id={user_id} error={exc}")
        return None
    if not isinstance(payload, dict):
        return None
    if not payload.get("available"):
        reason = str(payload.get("reason") or "").strip()
        return {
            "available": False,
            "reason": reason or "No active education programme is available today.",
        }
    programme = payload.get("programme") if isinstance(payload.get("programme"), dict) else {}
    lesson = payload.get("lesson") if isinstance(payload.get("lesson"), dict) else {}
    content = lesson.get("content") if isinstance(lesson.get("content"), dict) else {}
    avatar = content.get("avatar") if isinstance(content.get("avatar"), dict) else {}
    quiz = payload.get("quiz") if isinstance(payload.get("quiz"), dict) else {}
    progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
    questions = quiz.get("questions") if isinstance(quiz.get("questions"), list) else []
    duration_days = _safe_int(programme.get("duration_days"))
    return {
        "available": True,
        "programme_name": str(programme.get("name") or "").strip() or None,
        "programme_code": str(programme.get("code") or "").strip() or None,
        "pillar_key": str(payload.get("pillar_key") or "").strip() or None,
        "pillar_label": str(payload.get("pillar_label") or "").strip() or None,
        "concept_key": str(payload.get("concept_key") or programme.get("concept_key") or "").strip() or None,
        "concept_label": str(payload.get("concept_label") or programme.get("concept_label") or "").strip() or None,
        "day_index": _safe_int(payload.get("day_index")),
        "duration_days": duration_days,
        "level": str(payload.get("level") or "").strip() or None,
        "tracker_signal": str(payload.get("tracker_signal") or "").strip() or None,
        "tracker_state": str(payload.get("tracker_state") or "").strip() or None,
        "lesson_title": str(lesson.get("title") or "").strip() or None,
        "lesson_summary": str(lesson.get("summary") or "").strip() or None,
        "lesson_goal": str(lesson.get("goal") or "").strip() or None,
        "action_prompt": str(lesson.get("action_prompt") or content.get("action_prompt") or "").strip() or None,
        "has_video": bool(
            str(avatar.get("url") or "").strip()
            or str(content.get("video_url") or "").strip()
            or str(content.get("podcast_url") or "").strip()
        ),
        "quiz_question_count": len(questions),
        "completion_status": str(progress.get("completion_status") or "").strip() or None,
        "watch_pct": _safe_int(progress.get("watch_pct")),
        "quiz_score_pct": _safe_int(progress.get("quiz_score_pct")),
        "takeaway": str(payload.get("takeaway") or "").strip() or None,
    }


def _append_education_programme_lines(lines: list[str], tracker_context: dict) -> None:
    education = tracker_context.get("education_programme")
    if not isinstance(education, dict):
        return
    if not education.get("available"):
        reason = str(education.get("reason") or "").strip()
        if reason:
            lines.append(f"Education programme: unavailable ({reason})")
        return
    programme_name = str(education.get("programme_name") or "").strip()
    concept_label = str(education.get("concept_label") or "").strip()
    day_index = _safe_int(education.get("day_index"))
    duration_days = _safe_int(education.get("duration_days"))
    day_label = (
        f"Day {day_index} of {duration_days}"
        if day_index and duration_days
        else f"Day {day_index}"
        if day_index
        else ""
    )
    heading_bits = [bit for bit in [programme_name, concept_label, day_label] if bit]
    lines.append("Education programme: " + " | ".join(heading_bits))
    lesson_title = str(education.get("lesson_title") or "").strip()
    lesson_summary = str(education.get("lesson_summary") or "").strip()
    lesson_goal = str(education.get("lesson_goal") or "").strip()
    action_prompt = str(education.get("action_prompt") or "").strip()
    if lesson_title:
        lines.append(f"- lesson: {lesson_title}")
    if lesson_summary:
        lines.append(f"- lesson summary: {lesson_summary}")
    if lesson_goal:
        lines.append(f"- lesson goal: {lesson_goal}")
    if action_prompt:
        lines.append(f"- education action: {action_prompt}")
    lines.append(
        "- lesson assets: "
        + "; ".join(
            [
                f"avatar/video={'available' if education.get('has_video') else 'not available'}",
                f"quiz_questions={_safe_int(education.get('quiz_question_count')) or 0}",
                f"completion={str(education.get('completion_status') or 'pending')}",
            ]
        )
    )
    takeaway = str(education.get("takeaway") or "").strip()
    if takeaway:
        lines.append(f"- quiz takeaway: {takeaway}")


def _tracker_history_lines(tracker_context: dict) -> list[str]:
    lines: list[str] = []
    tracker_review = tracker_context.get("tracker_review") or []
    okr_context = tracker_context.get("okr_context") or {}
    day_brief = tracker_context.get("day_brief") or {}
    if isinstance(tracker_review, list) and tracker_review:
        plan_date = str(tracker_context.get("plan_date") or "").strip()
        def _pillar_sort_key(raw: dict) -> tuple[int, int, str]:
            if not isinstance(raw, dict):
                return (2, 2, "")
            active_date = str(raw.get("active_date") or "").strip()
            active_label = str(raw.get("active_label") or "").strip().lower()
            day_rank = 0 if (active_date and active_date == plan_date) or active_label == "today" else 1
            state = str(raw.get("state") or "").strip().lower()
            state_rank = 0 if state == "weak" else 1 if state == "fair" else 2
            label = str(raw.get("pillar_label") or raw.get("pillar_key") or "").strip().lower()
            return (day_rank, state_rank, label)

        lines.append("Daily tracker review:")
        for pillar in sorted((item for item in tracker_review if isinstance(item, dict)), key=_pillar_sort_key)[:4]:
            if not isinstance(pillar, dict):
                continue
            pillar_label = str(pillar.get("pillar_label") or pillar.get("pillar_key") or "").strip()
            if not pillar_label:
                continue
            pillar_bits = []
            state = str(pillar.get("state") or "").strip()
            active_label = str(pillar.get("active_label") or "").strip()
            if active_label:
                pillar_bits.append(f"day={active_label}")
            if state:
                pillar_bits.append(f"state={state}")
            concept_summaries: list[str] = []
            for item in (pillar.get("concepts") or [])[:5]:
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label") or item.get("concept_key") or "").strip()
                if not label:
                    continue
                concept_bits = []
                signal = str(item.get("signal") or "").strip()
                latest = str(item.get("latest_value") or "").strip()
                target = str(item.get("target_label") or "").strip()
                if signal:
                    concept_bits.append(signal)
                if latest:
                    concept_bits.append(f"latest={latest}")
                if target:
                    concept_bits.append(f"target={target}")
                suffix = f" ({'; '.join(concept_bits)})" if concept_bits else ""
                concept_summaries.append(f"{label}{suffix}")
            pillar_suffix = f" ({'; '.join(pillar_bits)})" if pillar_bits else ""
            review_text = "; ".join(concept_summaries) if concept_summaries else "No tracker detail available."
            lines.append(f"- {pillar_label}{pillar_suffix}: {review_text}")
    if isinstance(day_brief, dict):
        two_day_read = day_brief.get("two_day_read") if isinstance(day_brief.get("two_day_read"), dict) else {}
        if two_day_read:
            lines.append("Two-day read:")
            strength = str(two_day_read.get("strength") or "").strip()
            carry = str(two_day_read.get("carry_over_issue") or "").strip()
            priority = str(two_day_read.get("today_priority") or "").strip()
            if strength:
                lines.append(f"- strength: {strength}")
            if carry:
                lines.append(f"- carry-over issue: {carry}")
            if priority:
                lines.append(f"- today priority: {priority}")
        readiness = day_brief.get("readiness") if isinstance(day_brief.get("readiness"), dict) else {}
        if readiness:
            bits = []
            for key in ("nutrition_state", "recovery_state", "resilience_state", "exercise_state"):
                value = str(readiness.get(key) or "").strip()
                if value:
                    bits.append(f"{key}={value}")
            reason = str(readiness.get("exercise_reason") or "").strip()
            if reason:
                bits.append(f"reason={reason}")
            if bits:
                lines.append("Exercise readiness: " + "; ".join(bits))
        key_moments = day_brief.get("key_moments") if isinstance(day_brief.get("key_moments"), list) else []
        if key_moments:
            lines.append("Key moments for today:")
            for item in key_moments[:4]:
                if not isinstance(item, dict):
                    continue
                moment_label = str(item.get("moment_label") or item.get("moment") or "").strip()
                title = str(item.get("title") or "").strip()
                detail = str(item.get("detail") or "").strip()
                if not (moment_label or title or detail):
                    continue
                prefix = moment_label or "Moment"
                payload = " ".join(part for part in [title, detail] if part).strip()
                lines.append(f"- {prefix}: {payload}".strip())
        today_aim = str(day_brief.get("today_aim") or "").strip()
        if today_aim:
            lines.append(f"Today aim: {today_aim}")
    if (okr_context or {}).get("habit_steps"):
        lines.append("Active KR habit steps:")
        for step in (okr_context.get("habit_steps") or [])[:5]:
            step_text = str(step or "").strip()
            if step_text:
                lines.append(f"- {step_text}")
    _append_education_programme_lines(lines, tracker_context)
    return lines


def _support_prompt(
    user: User,
    history: list[dict],
    user_message: str | None,
    week_no: int | None,
    source: str | None,
    tracker_snapshot: dict | None = None,
):
    tracker_summary_mode = str(source or "").strip().lower() == "app_tracker_summary"
    transcript = []
    if not tracker_summary_mode:
        for turn in history:
            role = (turn.get("role") or "").strip()
            content = (turn.get("content") or "").strip()
            if role and content:
                transcript.append(f"{role.upper()}: {content}")
    if user_message and not tracker_summary_mode:
        transcript.append(f"USER: {user_message}")

    extras_parts = []
    if source:
        extras_parts.append(f"flow={source}")
    if week_no:
        extras_parts.append(f"week_no={week_no}")
    tracker_context = (
        tracker_snapshot.get("context")
        if isinstance(tracker_snapshot, dict) and isinstance(tracker_snapshot.get("context"), dict)
        else build_daily_tracker_generation_context(int(user.id))
    )
    if tracker_summary_mode:
        education_context = _education_programme_context(int(user.id), tracker_context)
        if education_context:
            tracker_context = {
                **tracker_context,
                "education_programme": education_context,
            }
    pillar_scores = tracker_context.get("pillar_scores") or []
    combined_score = _combined_score(pillar_scores)
    tracker_focus_date = str(tracker_context.get("tracker_focus_date") or tracker_context.get("plan_date") or "").strip()
    if tracker_focus_date:
        extras_parts.append(f"tracker_date={tracker_focus_date}")
    if tracker_summary_mode:
        extras_parts.append("tracker_priority=today_first_then_yesterday")
        extras_parts.append("tracker_scope=all_pillars")
        if isinstance(tracker_context.get("education_programme"), dict):
            extras_parts.append("education_programme=active")
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
        okr_context=tracker_context.get("okr_context") or {},
    )


def _generate_support_reply(
    user: User,
    *,
    history: list[dict],
    user_message: str | None,
    week_no: int | None,
    source: str | None,
    include_prefix: bool = True,
    tracker_snapshot: dict | None = None,
) -> str:
    prompt_assembly = _support_prompt(user, history, user_message, week_no, source, tracker_snapshot=tracker_snapshot)

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
    tracker_snapshot: dict | None = None,
) -> str:
    with SessionLocal() as s:
        state = _get_state(s, int(user.id)) or {}
        week_no = _resolve_week_no(s, int(user.id), state.get("week_no"))
        resolved_source = str(source or state.get("source") or "app_tracker_summary").strip() or "app_tracker_summary"
        history = [] if resolved_source == "app_tracker_summary" else list(state.get("history") or [])[-12:]
    return _generate_support_reply(
        user,
        history=history,
        user_message=user_message or None,
        week_no=week_no,
        source=resolved_source,
        include_prefix=include_prefix,
        tracker_snapshot=tracker_snapshot,
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
