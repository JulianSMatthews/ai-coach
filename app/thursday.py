"""
Thursday educational boost: short podcast/text tied to active goals.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .db import SessionLocal
from .job_queue import enqueue_job, should_use_podcast_worker
from .nudges import send_whatsapp, send_whatsapp_media, append_button_cta
from .models import User, WeeklyFocus, AssessmentRun
from .kickoff import COACH_NAME
from .prompts import primary_kr_payload, build_prompt, run_llm_prompt
from .programme_timeline import week_no_for_date
from .podcast import generate_podcast_audio
from .touchpoints import log_touchpoint
from . import general_support
import os


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def _podcast_worker_enabled() -> bool:
    return should_use_podcast_worker() and not _in_worker_process()


def _thursday_label() -> str:
    return "Thursday." if not _in_worker_process() else "Thursday"


def _thursday_tag() -> str:
    return f"*{_thursday_label()}*"


def _apply_thursday_marker(text: str | None) -> str | None:
    if not text:
        return text
    if text.startswith("*Thursday*"):
        return text.replace("*Thursday*", _thursday_tag(), 1)
    return text


def _send_thursday(*, text: str, to: str | None = None, category: str | None = None, quick_replies: list[str] | None = None) -> str:
    return send_whatsapp(
        text=_apply_thursday_marker(text) or text,
        to=to,
        category=category,
        quick_replies=quick_replies,
    )

def _resolve_week_context(session, user_id: int, week_no: int | None) -> tuple[int | None, int | None]:
    if week_no is not None:
        wf = (
            session.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user_id, WeeklyFocus.week_no == week_no)
            .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
            .first()
        )
        return week_no, getattr(wf, "id", None) if wf else None
    today = datetime.utcnow().date()
    wf_current = (
        session.query(WeeklyFocus)
        .filter(
            WeeklyFocus.user_id == user_id,
            WeeklyFocus.starts_on <= today,
            WeeklyFocus.ends_on >= today,
        )
        .order_by(WeeklyFocus.starts_on.desc())
        .first()
    )
    wf_latest = (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc())
        .first()
    )
    wf = wf_current or wf_latest
    if wf and getattr(wf, "week_no", None):
        return wf.week_no, wf.id
    programme_start = None
    run = (
        session.query(AssessmentRun)
        .filter(AssessmentRun.user_id == user_id)
        .order_by(AssessmentRun.id.desc())
        .first()
    )
    if run:
        base_dt = getattr(run, "started_at", None) or getattr(run, "created_at", None)
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
    try:
        label_week = week_no_for_date(programme_start, today)
    except Exception:
        label_week = 1
    return label_week, getattr(wf, "id", None) if wf else None


def send_thursday_boost(user: User, coach_name: str = COACH_NAME, week_no: int | None = None) -> None:
    if _podcast_worker_enabled():
        job_id = enqueue_job(
            "thursday_flow",
            {"user_id": user.id, "week_no": week_no},
            user_id=user.id,
        )
        print(f"[thursday] enqueued thursday flow user_id={user.id} job={job_id}")
        return
    general_support.clear(user.id)
    with SessionLocal() as s:
        resolved_week_no, wf_id = _resolve_week_context(s, user.id, week_no)
        week_no = resolved_week_no
        primary = primary_kr_payload(user.id, session=s, week_no=week_no)
    if not primary:
        _send_thursday(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
        return
    touchpoint_week_no = week_no

    prompt_assembly = build_prompt(
        "podcast_thursday",
        user_id=user.id,
        coach_name=coach_name,
        user_name=user.first_name or "there",
        locale=getattr(user, "tz", "UK") or "UK",
        week_no=week_no,
    )
    transcript = run_llm_prompt(
        prompt_assembly.text,
        user_id=user.id,
        touchpoint="podcast_thursday",
        context_meta={"week_no": week_no},
        prompt_variant=prompt_assembly.variant,
        task_label=prompt_assembly.task_label,
        prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
        block_order=prompt_assembly.block_order,
        log=True,
    )

    if not transcript:
        tgt = primary["target"] if primary.get("target") is not None else ""
        transcript = (
            f"*Thursday* Hi { (user.first_name or 'there').strip().title() }, here’s a quick boost. "
            f"Focus on this goal: {primary['description']} (target {tgt}). "
            "Try one simple mini-challenge today and keep it light."
        )

    fname_suffix = f"_week{touchpoint_week_no}" if touchpoint_week_no else ""
    combined_url = generate_podcast_audio(
        transcript,
        user.id,
        filename=f"thursday{fname_suffix}.mp3",
        usage_tag="weekly_flow",
    )

    if combined_url:
        message = (
            f"{_thursday_tag()} Hi { (user.first_name or '').strip().title() or 'there' }, {coach_name} here. "
            "Here’s your Thursday boost podcast—give it a quick listen."
        )
        try:
            send_whatsapp_media(
                to=user.phone,
                media_url=combined_url,
                caption=message,
            )
        except Exception:
            _send_thursday(
                to=user.phone,
                text=f"{message} {combined_url}",
            )
        checkin = f"{_thursday_tag()} Quick check-in: what stood out from today’s boost?"
        _send_thursday(
            to=user.phone,
            text=append_button_cta(checkin),
            quick_replies=["All good", "Need help"],
        )
    else:
        message = transcript if transcript.startswith("*Thursday*") else f"*Thursday* {transcript}"
        _send_thursday(
            to=user.phone,
            text=append_button_cta(message),
            quick_replies=["All good", "Need help"],
        )
    log_touchpoint(
        user_id=user.id,
        tp_type="thursday",
        weekly_focus_id=wf_id,
        week_no=touchpoint_week_no,
        kr_ids=[primary["id"]] if primary else [],
        meta={
            "source": "thursday",
            "week_no": touchpoint_week_no,
            "label": "thursday",
        },
        generated_text=message,
        audio_url=combined_url,
    )
    general_support.activate(user.id, source="thursday", week_no=touchpoint_week_no, send_intro=False)
