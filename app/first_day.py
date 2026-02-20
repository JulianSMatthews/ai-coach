"""
First-day coaching flow:
- Sent once when coaching starts and the first scheduled day is not Sunday.
- Sends a short podcast plus a text summary of already-seeded habit steps.
"""
from __future__ import annotations

from datetime import datetime
import os

from .db import SessionLocal
from .kickoff import COACH_NAME
from .models import AssessmentRun, User, WeeklyFocus
from .nudges import append_button_cta, send_whatsapp, send_whatsapp_media
from .podcast import generate_podcast_audio
from .programme_timeline import week_no_for_date
from .prompts import build_prompt, kr_payload_list, run_llm_prompt
from .touchpoints import log_touchpoint
from .virtual_clock import get_effective_today
from . import general_support


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def _first_day_label() -> str:
    return "First day." if not _in_worker_process() else "First day"


def _first_day_tag() -> str:
    return f"*{_first_day_label()}*"


def _apply_first_day_marker(text: str | None) -> str | None:
    if not text:
        return text
    if text.startswith("*First day*"):
        return text.replace("*First day*", _first_day_tag(), 1)
    return text


def _send_first_day(*, text: str, to: str | None = None, category: str | None = None, quick_replies: list[str] | None = None) -> str:
    return send_whatsapp(
        text=_apply_first_day_marker(text) or text,
        to=to,
        category=category,
        quick_replies=quick_replies,
    )


def _resolve_week_context(session, user_id: int) -> tuple[int | None, int | None]:
    today = get_effective_today(session, user_id, default_today=datetime.utcnow().date())
    wf_current = (
        session.query(WeeklyFocus)
        .filter(
            WeeklyFocus.user_id == user_id,
            WeeklyFocus.starts_on <= today,
            WeeklyFocus.ends_on >= today,
        )
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )
    wf_latest = (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )
    wf = wf_current or wf_latest
    if wf and getattr(wf, "week_no", None):
        return int(wf.week_no), int(wf.id)

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
    try:
        week_no = week_no_for_date(programme_start, today)
    except Exception:
        week_no = 1
    return week_no, int(wf.id) if wf else None


def _habit_steps_summary_lines(krs: list[dict]) -> list[str]:
    lines: list[str] = []
    item_no = 0
    for kr in krs:
        steps_raw = kr.get("habit_steps") or []
        steps = [str(step).strip() for step in steps_raw if str(step or "").strip()]
        if not steps:
            continue
        item_no += 1
        lines.append(f"{item_no}) {'; '.join(steps)}")
    return lines


def _fallback_transcript(first_name: str, habit_step_lines: list[str]) -> str:
    opening = f"{_first_day_tag()} Hi {first_name}, welcome to your first day of coaching."
    if not habit_step_lines:
        return (
            f"{opening} We already set your habit steps from your assessment, and this week is about keeping them simple and consistent. "
            "Focus on steady repetition rather than perfection, and check in any time if you want to adjust anything."
        )
    joined = " ".join(habit_step_lines[:2])
    return (
        f"{opening} We already set your first habit steps from your assessment. "
        f"This week, focus on these: {joined} Keep it realistic, repeatable, and low pressure."
    )


def send_first_day_coaching(user: User, coach_name: str = COACH_NAME, scheduled_day: str | None = None) -> None:
    general_support.clear(user.id)
    with SessionLocal() as s:
        week_no, wf_id = _resolve_week_context(s, user.id)
        krs = kr_payload_list(user.id, session=s, week_no=week_no, max_krs=3)
        if not krs:
            krs = kr_payload_list(user.id, session=s, week_no=None, max_krs=3)
        if not krs:
            raise RuntimeError("No KRs available for first-day coaching")
        habit_step_lines = _habit_steps_summary_lines(krs)
        if not habit_step_lines:
            raise RuntimeError("No seeded habit steps available for first-day coaching")

        prompt_assembly = build_prompt(
            "podcast_first_day",
            user_id=user.id,
            coach_name=coach_name,
            user_name=user.first_name or "there",
            locale=getattr(user, "tz", "UK") or "UK",
            week_no=week_no,
            krs=krs,
            scheduled_day=scheduled_day,
        )
        transcript = run_llm_prompt(
            prompt_assembly.text,
            user_id=user.id,
            touchpoint="podcast_first_day",
            context_meta={"week_no": week_no, "scheduled_day": scheduled_day},
            prompt_variant=prompt_assembly.variant,
            task_label=prompt_assembly.task_label,
            prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
            block_order=prompt_assembly.block_order,
            log=True,
        )

    first_name = (user.first_name or "there").strip().title() or "there"
    transcript = (transcript or "").strip() or _fallback_transcript(first_name, habit_step_lines)
    audio_name = f"first_day_week{int(week_no)}.mp3" if week_no else "first_day.mp3"
    audio_url = generate_podcast_audio(
        transcript,
        user.id,
        filename=audio_name,
        usage_tag="weekly_flow",
    )

    intro_msg = (
        f"{_first_day_tag()} Hi {first_name}, {coach_name} here. "
        "Welcome to coaching. Here’s your first-day podcast."
    )
    if audio_url:
        try:
            send_whatsapp_media(
                to=user.phone,
                media_url=audio_url,
                caption=intro_msg,
            )
        except Exception:
            _send_first_day(to=user.phone, text=f"{intro_msg} {audio_url}")
    else:
        _send_first_day(to=user.phone, text=append_button_cta(intro_msg))

    steps_msg = (
        f"{_first_day_tag()} Habit steps for this week:\n"
        + "\n".join(habit_step_lines)
        + "\n\nReply if you want to adjust any step."
    )
    _send_first_day(
        to=user.phone,
        text=append_button_cta(steps_msg),
        quick_replies=["All good", "Need help"],
    )

    log_touchpoint(
        user_id=user.id,
        tp_type="first_day",
        weekly_focus_id=wf_id,
        week_no=week_no,
        kr_ids=[int(kr["id"]) for kr in krs if kr.get("id")],
        meta={
            "source": "first_day",
            "label": "first_day",
            "scheduled_day": scheduled_day,
        },
        generated_text=steps_msg,
        audio_url=audio_url,
    )
    general_support.activate(user.id, source="first_day", week_no=week_no, send_intro=False)
