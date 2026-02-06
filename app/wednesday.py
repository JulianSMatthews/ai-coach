"""
Wednesday midweek check-in: single-KR support with blockers and micro-adjustment.
"""
from __future__ import annotations

from typing import Optional

from .db import SessionLocal
from .job_queue import enqueue_job, should_use_worker
from .models import WeeklyFocus, User
from .nudges import send_whatsapp, append_button_cta
from .prompts import format_checkin_history, primary_kr_payload, build_prompt, run_llm_prompt
from .touchpoints import log_touchpoint
from .checkins import fetch_recent_checkins, record_checkin
from . import general_support
import os


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def _wednesday_label() -> str:
    return "Wednesday." if not _in_worker_process() else "Wednesday"


def _wednesday_tag() -> str:
    return f"*{_wednesday_label()}*"


def _apply_wednesday_marker(text: str | None) -> str | None:
    if not text:
        return text
    if text.startswith("*Wednesday*"):
        return text.replace("*Wednesday*", _wednesday_tag(), 1)
    return text


def _send_wednesday(*, text: str, to: str | None = None, category: str | None = None, quick_replies: list[str] | None = None) -> str:
    return send_whatsapp(
        text=_apply_wednesday_marker(text) or text,
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


def send_midweek_check(user: User, coach_name: str = "Gia") -> None:
    if should_use_worker() and not _in_worker_process():
        job_id = enqueue_job("day_prompt", {"user_id": user.id, "day": "wednesday"}, user_id=user.id)
        print(f"[wednesday] enqueued day prompt user_id={user.id} job={job_id}")
        return
    general_support.clear(user.id)
    with SessionLocal() as s:
        wf = _latest_weekly_focus(s, user.id)
        if not wf:
            _send_wednesday(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
            return
        kr = primary_kr_payload(user.id, session=s)
        if not kr:
            _send_wednesday(to=user.phone, text="No key results found for this week. Say monday to set them up.")
            return

        history_text = ""
        try:
            hist = fetch_recent_checkins(user.id, limit=3, weekly_focus_id=wf.id)
            history_text = format_checkin_history(hist)
        except Exception:
            history_text = ""

        message = None
        prompt_assembly = build_prompt(
            "midweek",
            user_id=user.id,
            coach_name=coach_name,
            user_name=user.first_name or "",
            locale=getattr(user, "tz", "UK") or "UK",
            timeframe="midweek check",
            history_text=history_text,
        )
        candidate = run_llm_prompt(
            prompt_assembly.text,
            user_id=user.id,
            touchpoint="midweek",
            context_meta={"wf_id": wf.id if wf else None},
            prompt_variant=prompt_assembly.variant,
            task_label=prompt_assembly.task_label,
            prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
            block_order=prompt_assembly.block_order,
            log=True,
        )
        if candidate:
            message = candidate if candidate.lower().startswith("*wednesday*") else "*Wednesday* " + candidate

        if not message:
            tgt = kr["target"] if kr.get("target") is not None else ""
            now = kr["actual"] if kr.get("actual") is not None else ""
            message = (
                f"*Wednesday* Hi { (user.first_name or 'there').strip().title() }, quick midweek check-in.\n"
                f"How are you getting on?\n"
                f"Focus goal: {kr['description']} (target {tgt}; now {now}).\n"
                "Any blockers? Try a small tweak this week—pick one simpler option that keeps you consistent."
            )

    _send_wednesday(
        to=user.phone,
        text=append_button_cta(message),
        quick_replies=["All good", "Need help"],
    )
    log_touchpoint(
        user_id=user.id,
        tp_type="wednesday",
        weekly_focus_id=wf.id,
        week_no=getattr(wf, "week_no", None),
        kr_ids=[kr["id"]] if kr else [],
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
    general_support.activate(user.id, source="wednesday", week_no=getattr(wf, "week_no", None), send_intro=False)
