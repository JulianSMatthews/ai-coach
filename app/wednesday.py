"""
Wednesday midweek check-in: single-KR support with blockers and micro-adjustment.
"""
from __future__ import annotations

from typing import Optional

from .db import SessionLocal
from .models import WeeklyFocus, WeeklyFocusKR, OKRKeyResult, User
from .nudges import send_whatsapp
from . import llm as shared_llm
from .prompts import midweek_prompt, format_checkin_history
from .touchpoints import log_touchpoint
from .checkins import fetch_recent_checkins, record_checkin


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def _pick_primary_kr(session: Session, wf_id: int) -> Optional[OKRKeyResult]:
    row = (
        session.query(WeeklyFocusKR, OKRKeyResult)
        .join(OKRKeyResult, WeeklyFocusKR.kr_id == OKRKeyResult.id)
        .filter(WeeklyFocusKR.weekly_focus_id == wf_id)
        .order_by(WeeklyFocusKR.priority_order.asc())
        .first()
    )
    return row[1] if row else None


def send_midweek_check(user: User, coach_name: str = "Gia") -> None:
    with SessionLocal() as s:
        wf = _latest_weekly_focus(s, user.id)
        if not wf:
            send_whatsapp(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
            return
        kr = _pick_primary_kr(s, wf.id)
        if not kr:
            send_whatsapp(to=user.phone, text="No key results found for this week. Say monday to set them up.")
            return

        client = getattr(shared_llm, "_llm", None)
        message = None
        history_text = ""
        try:
            hist = fetch_recent_checkins(user.id, limit=3, weekly_focus_id=wf.id)
            history_text = format_checkin_history(hist)
        except Exception:
            history_text = ""
        if client:
            try:
                payload = {"description": kr.description, "target": kr.target_num, "actual": kr.actual_num}
                prompt = midweek_prompt(
                    coach_name=coach_name,
                    user_name=user.first_name or "",
                    kr=payload,
                    timeframe="midweek check",
                    history_text=history_text,
                )
                resp = client.invoke(prompt)
                message = (getattr(resp, "content", None) or "").strip()
                if message and not message.lower().startswith("*wednesday*"):
                    message = "*Wednesday* " + message
            except Exception:
                message = None

        if not message:
            tgt = kr.target_num if kr.target_num is not None else ""
            now = kr.actual_num if kr.actual_num is not None else ""
            message = (
                f"*Wednesday* Hi { (user.first_name or 'there').strip().title() }, quick midweek check-in.\n"
                f"How are you getting on?\n"
                f"Focus goal: {kr.description} (target {tgt}; now {now}).\n"
                "Any blockers? Try a small tweak this week—pick one simpler option that keeps you consistent."
            )

    send_whatsapp(to=user.phone, text=message)
    log_touchpoint(
        user_id=user.id,
        tp_type="wednesday",
        weekly_focus_id=wf.id,
        week_no=getattr(wf, "week_no", None),
        kr_ids=[kr.id] if kr else [],
        meta={"source": "wednesday", "label": "wednesday"},
        generated_text=message,
        source_check_in_id=record_checkin(
            user_id=user.id,
            touchpoint_type="wednesday",
            progress_updates=[],
            blockers=[],
            commitments=[],
            weekly_focus_id=wf.id,
            week_no=getattr(wf, "week_no", None),
        ),
    )
