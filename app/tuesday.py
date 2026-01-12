"""
Tuesday micro-check: lightweight habit prompt for one KR with a simple nudge.
"""
from __future__ import annotations

from typing import Optional
from sqlalchemy.orm import Session

from .db import SessionLocal
from .nudges import send_whatsapp
from .models import WeeklyFocus, User
from .kickoff import COACH_NAME
from .prompts import format_checkin_history, primary_kr_payload, build_prompt, run_llm_prompt
from .touchpoints import log_touchpoint
from .checkins import fetch_recent_checkins
from .checkins import record_checkin


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def send_tuesday_check(user: User, coach_name: str = COACH_NAME) -> None:
    with SessionLocal() as s:
        wf = _latest_weekly_focus(s, user.id)
        if not wf:
            send_whatsapp(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
            return
        kr = primary_kr_payload(user.id, session=s)
        if not kr:
            send_whatsapp(to=user.phone, text="No key results found for this week. Say monday to set them up.")
            return

        history_text = ""
        try:
            hist = fetch_recent_checkins(user.id, limit=3, weekly_focus_id=wf.id)
            history_text = format_checkin_history(hist)
        except Exception:
            history_text = ""

        message = None
        prompt_assembly = build_prompt(
            "tuesday",
            user_id=user.id,
            coach_name=coach_name,
            user_name=user.first_name or "there",
            locale=getattr(user, "tz", "UK") or "UK",
            history_text=history_text,
            timeframe="Tuesday",
        )
        candidate = run_llm_prompt(
            prompt_assembly.text,
            user_id=user.id,
            touchpoint="tuesday",
            context_meta={"wf_id": wf.id if wf else None},
            prompt_variant=prompt_assembly.variant,
            task_label=prompt_assembly.task_label,
            prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
            block_order=prompt_assembly.block_order,
            log=True,
        )
        if candidate:
            message = candidate if candidate.lower().startswith("*tuesday*") else "*Tuesday* " + candidate

        if not message:
            tgt = kr["target"] if kr.get("target") is not None else ""
            message = (
                f"*Tuesday* Quick check-in, { (user.first_name or 'there').strip().title() }. "
                f"How’s {kr['description']} going? Target {tgt}. "
                "Give me a quick yes/no or a number, and try one small nudge today to keep it moving."
            )

        send_whatsapp(to=user.phone, text=message)
        check_in_id = None
        try:
            check_in_id = record_checkin(
                user_id=user.id,
                touchpoint_type="tuesday",
                progress_updates=[],
                blockers=[],
                commitments=[],
                weekly_focus_id=wf.id,
                week_no=getattr(wf, "week_no", None),
            )
        except Exception:
            check_in_id = None
        log_touchpoint(
            user_id=user.id,
            tp_type="tuesday",
            weekly_focus_id=wf.id,
            week_no=getattr(wf, "week_no", None),
            kr_ids=[kr["id"]] if kr else [],
            meta={"source": "tuesday", "label": "tuesday"},
            generated_text=message,
            source_check_in_id=check_in_id,
        )
