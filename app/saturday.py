"""
Saturday keepalive: short message to keep the WhatsApp session active.
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import WeeklyFocus, User
from .nudges import send_whatsapp, append_button_cta
from .kickoff import COACH_NAME
from .prompts import format_checkin_history, primary_kr_payload, build_prompt, run_llm_prompt
from .touchpoints import log_touchpoint
from .checkins import fetch_recent_checkins, record_checkin
from . import general_support
import os


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def _saturday_label() -> str:
    return "Saturday." if _in_worker_process() else "Saturday"


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


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def send_saturday_keepalive(user: User, coach_name: str = COACH_NAME) -> None:
    general_support.clear(user.id)
    with SessionLocal() as s:
        wf = _latest_weekly_focus(s, user.id)
        kr = primary_kr_payload(user.id, session=s) if wf else None
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
                week_no=getattr(wf, "week_no", None) if wf else None,
            )
        except Exception:
            check_in_id = None

        log_touchpoint(
            user_id=user.id,
            tp_type="saturday",
            weekly_focus_id=wf.id if wf else None,
            week_no=getattr(wf, "week_no", None) if wf else None,
            kr_ids=[kr["id"]] if kr else [],
            meta={"source": "saturday", "label": "saturday"},
            generated_text=message,
            source_check_in_id=check_in_id,
        )
        general_support.activate(
            user.id,
            source="saturday",
            week_no=getattr(wf, "week_no", None) if wf else None,
            send_intro=False,
        )
