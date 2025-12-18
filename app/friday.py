"""
Friday boost: short podcast/message focusing on one KR with a simple action.
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy.orm import Session

from .db import SessionLocal
from .nudges import send_whatsapp
from .models import WeeklyFocus, WeeklyFocusKR, OKRKeyResult, User
from .kickoff import COACH_NAME
from .prompts import boost_prompt
from .podcast import generate_podcast_audio
from . import llm as shared_llm
from .touchpoints import log_touchpoint


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


def send_boost(user: User, coach_name: str = COACH_NAME, week_no: int | None = None) -> None:
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
        transcript = None
        if client:
            try:
                prompt = boost_prompt(
                    coach_name=coach_name,
                    user_name=user.first_name or "there",
                    kr={"description": kr.description, "target": kr.target_num, "actual": kr.actual_num},
                )
                resp = client.invoke(prompt)
                transcript = (getattr(resp, "content", None) or "").strip()
            except Exception:
                transcript = None

        if not transcript:
            tgt = kr.target_num if kr.target_num is not None else ""
            transcript = (
                f"*Friday* Hi { (user.first_name or 'there').strip().title() }, here’s a quick boost. "
                f"Focus on this goal: {kr.description} (target {tgt}). "
                "Try one simple step over the next couple of days to stay consistent."
            )

        fname = f"friday_week{week_no}.mp3" if week_no else "friday.mp3"
        audio_url = generate_podcast_audio(transcript, user.id, filename=fname)
        if audio_url:
            message = (
                f"*Friday* Hi { (user.first_name or '').strip().title() or 'there' }, {coach_name} here. "
                f"Here’s your boost podcast—give it a quick listen: {audio_url}"
            )
        else:
            message = transcript if transcript.startswith("*Friday*") else f"*Friday* {transcript}"
        send_whatsapp(to=user.phone, text=message)
        log_touchpoint(
            user_id=user.id,
            tp_type="friday",
            weekly_focus_id=wf.id,
            week_no=getattr(wf, "week_no", None),
            kr_ids=[kr.id] if kr else [],
            meta={"source": "friday", "week_no": week_no, "label": "friday"},
            generated_text=message,
            audio_url=audio_url,
        )
