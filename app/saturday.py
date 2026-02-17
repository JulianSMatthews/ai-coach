"""
Saturday keepalive: short message to keep the WhatsApp session active.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session

from .db import SessionLocal
from .job_queue import enqueue_job, should_use_worker
from .models import WeeklyFocus, User, AssessmentRun
from .nudges import send_whatsapp, append_button_cta
from .kickoff import COACH_NAME
from .prompts import format_checkin_history, primary_kr_payload, build_prompt, run_llm_prompt
from .programme_timeline import week_no_for_focus_start
from .touchpoints import log_touchpoint
from .checkins import fetch_recent_checkins, record_checkin
from . import general_support
from .virtual_clock import get_effective_today
import os


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def _saturday_label() -> str:
    return "Saturday." if not _in_worker_process() else "Saturday"


def _saturday_tag() -> str:
    return f"*{_saturday_label()}*"


def _apply_saturday_marker(text: str | None) -> str | None:
    if not text:
        return text
    if text.startswith("*Saturday*"):
        return text.replace("*Saturday*", _saturday_tag(), 1)
    return text


def _send_saturday(*, text: str, to: str | None = None, category: str | None = None, quick_replies: list[str] | None = None) -> str:
    return send_whatsapp(
        text=_apply_saturday_marker(text) or text,
        to=to,
        category=category,
        quick_replies=quick_replies,
    )


def _resolve_weekly_focus(session: Session, user_id: int, today_date) -> Optional[WeeklyFocus]:
    day_start = datetime.combine(today_date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    active = (
        session.query(WeeklyFocus)
        .filter(
            WeeklyFocus.user_id == user_id,
            WeeklyFocus.starts_on < day_end,
            WeeklyFocus.ends_on >= day_start,
        )
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )
    if active:
        return active
    latest_started = (
        session.query(WeeklyFocus)
        .filter(
            WeeklyFocus.user_id == user_id,
            WeeklyFocus.starts_on < day_end,
        )
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )
    if latest_started:
        return latest_started
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def _infer_week_no(session, user_id: int, wf: WeeklyFocus) -> int:
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


def send_saturday_keepalive(user: User, coach_name: str = COACH_NAME) -> None:
    if should_use_worker() and not _in_worker_process():
        job_id = enqueue_job("day_prompt", {"user_id": user.id, "day": "saturday"}, user_id=user.id)
        print(f"[saturday] enqueued day prompt user_id={user.id} job={job_id}")
        return
    general_support.clear(user.id)
    with SessionLocal() as s:
        today = get_effective_today(s, user.id, default_today=datetime.utcnow().date())
        wf = _resolve_weekly_focus(s, user.id, today)
        week_no = None
        if wf:
            week_no = getattr(wf, "week_no", None)
            if not week_no:
                week_no = _infer_week_no(s, user.id, wf)
                try:
                    wf.week_no = week_no
                    s.add(wf)
                except Exception:
                    pass
        kr = primary_kr_payload(user.id, session=s, week_no=week_no) if wf else None
        history_text = ""
        try:
            if wf:
                hist = fetch_recent_checkins(user.id, limit=3, weekly_focus_id=wf.id)
                history_text = format_checkin_history(hist)
        except Exception:
            history_text = ""

        message = "*Saturday* Hey, just checking in for the weekend - how are things feeling with food right now?"

        _send_saturday(
            to=user.phone,
            text=append_button_cta(message),
            quick_replies=["All good", "Need help"],
        )

        check_in_id = None
        try:
            check_in_id = record_checkin(
                user_id=user.id,
                touchpoint_type="saturday",
                progress_updates=[],
                blockers=[],
                commitments=[],
                weekly_focus_id=wf.id if wf else None,
                week_no=week_no,
            )
        except Exception:
            check_in_id = None

        log_touchpoint(
            user_id=user.id,
            tp_type="saturday",
            weekly_focus_id=wf.id if wf else None,
            week_no=week_no,
            kr_ids=[kr["id"]] if kr else [],
            meta={"source": "saturday", "label": "saturday"},
            generated_text=message,
            source_check_in_id=check_in_id,
        )
        general_support.activate(
            user.id,
            source="saturday",
            week_no=week_no,
            send_intro=False,
        )
