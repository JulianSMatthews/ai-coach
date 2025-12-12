"""
Tuesday micro-check: lightweight habit prompt for one KR with a simple nudge.
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy.orm import Session

from .db import SessionLocal
from .nudges import send_whatsapp
from .models import WeeklyFocus, WeeklyFocusKR, OKRKeyResult, User
from .kickoff import COACH_NAME
from .prompts import tuesday_prompt
from . import llm as shared_llm


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


def send_tuesday_check(user: User, coach_name: str = COACH_NAME) -> None:
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
        if client:
            try:
                prompt = tuesday_prompt(
                    coach_name=coach_name,
                    user_name=user.first_name or "there",
                    kr={"description": kr.description, "target": kr.target_num, "actual": kr.actual_num},
                )
                resp = client.invoke(prompt)
                message = (getattr(resp, "content", None) or "").strip()
                if message and not message.lower().startswith("*tuesday*"):
                    message = "*Tuesday* " + message
            except Exception:
                message = None

        if not message:
            tgt = kr.target_num if kr.target_num is not None else ""
            message = (
                f"*Tuesday* Quick check-in, { (user.first_name or 'there').strip().title() }. "
                f"How’s {kr.description} going? Target {tgt}. "
                "Give me a quick yes/no or a number, and try one small nudge today to keep it moving."
            )

        send_whatsapp(to=user.phone, text=message)
