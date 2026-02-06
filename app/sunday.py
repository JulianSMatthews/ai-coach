"""
Sunday weekly review: habit-step check-in (weeks 1-2 of each pillar block) or KR update (week 3).
Stateful flow: action prompt → support follow-up.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime, timedelta
import os
from sqlalchemy.orm import Session

from .db import SessionLocal
from .job_queue import enqueue_job, should_use_worker
from .nudges import send_whatsapp, append_button_cta
from .checkins import record_checkin
from .models import WeeklyFocus, OKRKeyResult, User, UserPreference, OKRKrEntry, OKRKrHabitStep, AssessmentRun
from .kickoff import COACH_NAME
from . import llm as shared_llm
from .touchpoints import log_touchpoint, update_touchpoint
from .prompts import kr_payload_list, build_prompt, run_llm_prompt
from . import general_support

STATE_KEY = "sunday_state"


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def _sunday_label() -> str:
    return "Sunday." if not _in_worker_process() else "Sunday"


def _sunday_tag() -> str:
    return f"*{_sunday_label()}*"


def _apply_sunday_marker(text: str | None) -> str | None:
    if not text:
        return text
    if text.startswith("*Sunday*"):
        return text.replace("*Sunday*", _sunday_tag(), 1)
    return text


def _send_sunday(*, text: str, to: str | None = None, category: str | None = None, quick_replies: list[str] | None = None) -> str:
    return send_whatsapp(
        text=_apply_sunday_marker(text) or text,
        to=to,
        category=category,
        quick_replies=quick_replies,
    )


def _review_mode_for_week(week_no: int | None) -> str:
    if week_no and week_no > 0:
        within = ((week_no - 1) % 3) + 1
        return "habit" if within in {1, 2} else "kr"
    return "kr"


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def _infer_week_no(session: Session, user_id: int, wf: WeeklyFocus) -> int:
    base_start = None
    run = (
        session.query(AssessmentRun)
        .filter(AssessmentRun.user_id == user_id)
        .order_by(AssessmentRun.id.desc())
        .first()
    )
    if run:
        base_dt = getattr(run, "started_at", None) or getattr(run, "created_at", None)
        if isinstance(base_dt, datetime):
            base_start = base_dt.date() - timedelta(days=base_dt.date().weekday())
    if base_start is None:
        earliest = (
            session.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user_id)
            .order_by(WeeklyFocus.starts_on.asc())
            .first()
        )
        if earliest and getattr(earliest, "starts_on", None):
            try:
                base_start = earliest.starts_on.date()
            except Exception:
                base_start = None
    wf_start = None
    if getattr(wf, "starts_on", None):
        try:
            wf_start = wf.starts_on.date()
        except Exception:
            wf_start = None
    if base_start is None or wf_start is None:
        return 1
    try:
        return max(1, int(((wf_start - base_start).days // 7) + 1))
    except Exception:
        return 1


def _get_state(session: Session, user_id: int) -> Optional[dict]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if pref and pref.value:
        try:
            import json
            return json.loads(pref.value)
        except Exception:
            return None
    return None


def _set_state(session: Session, user_id: int, state: Optional[dict]) -> None:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if state is None:
        if pref:
            session.delete(pref)
        return
    import json
    if pref:
        pref.value = json.dumps(state)
    else:
        pref = UserPreference(user_id=user_id, key=STATE_KEY, value=json.dumps(state))
        session.add(pref)


def has_active_state(user_id: int) -> bool:
    with SessionLocal() as s:
        st = _get_state(s, user_id)
        return st is not None


def _is_standard_button_reply(text: str) -> bool:
    cleaned = (text or "").strip().lower()
    return cleaned in {"all good", "need help", "all ok", "all okay"}


def _format_habit_steps(session: Session, user_id: int, kr_ids: list[int], week_no: int | None) -> str:
    if not kr_ids:
        return ""
    kr_desc = {
        kr.id: kr.description
        for kr in session.query(OKRKeyResult).filter(OKRKeyResult.id.in_(kr_ids)).all()
    }
    q = (
        session.query(OKRKrHabitStep)
        .filter(OKRKrHabitStep.user_id == user_id, OKRKrHabitStep.kr_id.in_(kr_ids))
        .filter(OKRKrHabitStep.status != "archived")
        .order_by(
            OKRKrHabitStep.kr_id.asc(),
            OKRKrHabitStep.week_no.asc().nullslast(),
            OKRKrHabitStep.sort_order.asc(),
            OKRKrHabitStep.id.asc(),
        )
    )
    if week_no is not None:
        q = q.filter(
            (OKRKrHabitStep.week_no == week_no) | (OKRKrHabitStep.week_no.is_(None))
        )
    steps_by_kr: dict[int, list[str]] = {}
    for step in q.all():
        if not step.step_text:
            continue
        steps_by_kr.setdefault(step.kr_id, []).append(step.step_text)
    if not steps_by_kr:
        return ""
    lines = []
    for kr_id in kr_ids:
        steps = steps_by_kr.get(kr_id) or []
        if steps:
            label = kr_desc.get(kr_id) or f"KR {kr_id}"
            lines.append(f"{label}: " + "; ".join(steps))
    return "\n".join(lines)


def _support_prompt(user: User, history: list[dict], user_message: str | None, review_mode: str, week_no: int | None):
    transcript = []
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role and content:
            transcript.append(f"{role.upper()}: {content}")
    if user_message:
        transcript.append(f"USER: {user_message}")
    return build_prompt(
        "sunday_support",
        user_id=user.id,
        coach_name=COACH_NAME,
        user_name=(user.first_name or ""),
        locale=getattr(user, "tz", "UK") or "UK",
        history="\n".join(transcript),
        review_mode=review_mode,
        week_no=week_no,
    )


def _support_conversation(
    history: list[dict],
    user_message: str | None,
    user: User,
    review_mode: str,
    week_no: int | None,
) -> tuple[str, list[dict]]:
    prompt_assembly = _support_prompt(user, history, user_message, review_mode, week_no)
    candidate = run_llm_prompt(
        prompt_assembly.text,
        user_id=user.id,
        touchpoint="sunday_support",
        context_meta={"review_mode": review_mode, "week_no": week_no},
        prompt_variant=prompt_assembly.variant,
        task_label=prompt_assembly.task_label,
        prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
        block_order=prompt_assembly.block_order,
        log=True,
    )
    text = candidate or ""
    if not text:
        if review_mode == "habit":
            text = "Thanks for the update. Want to tweak any of the habit steps for next week?"
        else:
            text = "Thanks for the update. Was anything in the way of hitting the targets this week?"
    if not text.lower().startswith("*sunday*"):
        text = "*Sunday* " + text
    new_history = list(history)
    if user_message:
        new_history.append({"role": "user", "content": user_message})
    new_history.append({"role": "assistant", "content": text})
    return text, new_history


def send_sunday_review(user: User, coach_name: str = COACH_NAME) -> None:
    if should_use_worker() and not _in_worker_process():
        job_id = enqueue_job("day_prompt", {"user_id": user.id, "day": "sunday"}, user_id=user.id)
        print(f"[sunday] enqueued day prompt user_id={user.id} job={job_id}")
        return
    general_support.clear(user.id)
    wf_id: int | None = None
    kr_ids: list[int] = []
    week_no: int | None = None
    review_mode = "kr"
    with SessionLocal() as s:
        wf = _latest_weekly_focus(s, user.id)
        if not wf:
            _send_sunday(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
            return
        wf_id = wf.id
        week_no = getattr(wf, "week_no", None)
        if not week_no:
            week_no = _infer_week_no(s, user.id, wf)
            try:
                wf.week_no = week_no
                s.add(wf)
            except Exception:
                pass
        review_mode = _review_mode_for_week(week_no)
        kr_ids = [kr["id"] for kr in kr_payload_list(user.id, session=s, week_no=week_no, max_krs=3)]
        if not kr_ids:
            _send_sunday(to=user.phone, text="No key results found for this week. Say monday to set them up.")
            return
        habit_steps = _format_habit_steps(s, user.id, kr_ids, week_no) if review_mode == "habit" else ""
        prompt_assembly = build_prompt(
            "sunday_actions",
            user_id=user.id,
            coach_name=coach_name,
            user_name=(user.first_name or ""),
            locale=getattr(user, "tz", "UK") or "UK",
            week_no=week_no,
            review_mode=review_mode,
            habit_steps=habit_steps,
        )
        candidate = run_llm_prompt(
            prompt_assembly.text,
            user_id=user.id,
            touchpoint="sunday_actions",
            context_meta={"review_mode": review_mode, "week_no": week_no},
            prompt_variant=prompt_assembly.variant,
            task_label=prompt_assembly.task_label,
            prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
            block_order=prompt_assembly.block_order,
            log=True,
        )
        msg = candidate or ""
        if not msg:
            if review_mode == "habit":
                msg = "*Sunday* Quick check-in on your habit steps this week — how did they go, and would you like to tweak anything?"
            else:
                msg = "*Sunday* Quick check-in — please share your actuals for each goal (numbers), plus what worked and what didn’t."
        if not msg.lower().startswith("*sunday*"):
            msg = "*Sunday* " + msg
        _send_sunday(
            to=user.phone,
            text=append_button_cta(msg),
            quick_replies=["All good", "Need help"],
        )

        # Log touchpoint first so we can store tp_id in state (single write).
        tp_id = log_touchpoint(
            user_id=user.id,
            tp_type="sunday",
            weekly_focus_id=wf_id,
            week_no=week_no,
            generated_text=msg,
            meta={"source": "sunday", "label": "sunday", "review_mode": review_mode},
        )
        state = {
            "mode": "awaiting",
            "review_mode": review_mode,
            "kr_ids": kr_ids,
            "wf_id": wf_id,
            "week_no": week_no,
            "history": [],
        }
        if tp_id:
            state["tp_id"] = tp_id
        _set_state(s, user.id, state)
        s.commit()


def handle_message(user: User, body: str) -> None:
    text = (body or "").strip()
    if not text:
        return
    with SessionLocal() as s:
        state = _get_state(s, user.id)
        if not state:
            return
        if _is_standard_button_reply(text):
            week_no = state.get("week_no")
            _set_state(s, user.id, None)
            s.commit()
            general_support.activate(user.id, source="sunday", week_no=week_no, send_intro=True)
            return
        mode = state.get("mode", "awaiting")
        review_mode = state.get("review_mode", "kr")
        kr_ids = state.get("kr_ids") or []
        week_no = state.get("week_no")

        if mode == "awaiting":
            wf = s.query(WeeklyFocus).get(state.get("wf_id"))
            krs = s.query(OKRKeyResult).filter(OKRKeyResult.id.in_(kr_ids)).all() if kr_ids else []
            is_button_reply = _is_standard_button_reply(text)
            if review_mode == "kr" and not is_button_reply:
                # parse numbers in order of KR list
                numbers = []
                for token in text.replace(",", " ").split():
                    try:
                        numbers.append(float(token))
                    except Exception:
                        continue
                if len(numbers) < len(kr_ids):
                    _send_sunday(
                        to=user.phone,
                        text="*Sunday* Please reply with a number for each goal in order (e.g., 3 4 2).",
                    )
                    return
                progress_updates = []
                for idx, kr_id in enumerate(kr_ids):
                    val = numbers[idx]
                    kr = next((k for k in krs if k.id == kr_id), None)
                    if kr:
                        kr.actual_num = val
                        entry = OKRKrEntry(
                            key_result_id=kr.id,
                            occurred_at=datetime.utcnow(),
                            actual_num=val,
                            note="Sunday check-in",
                            source="sunday",
                        )
                        s.add(entry)
                        progress_updates.append({"kr_id": kr.id, "actual": val, "target": kr.target_num})
                s.commit()
                check_in_id = None
                try:
                    check_in_id = record_checkin(
                        user_id=user.id,
                        touchpoint_type="sunday",
                        progress_updates=progress_updates,
                        blockers=[],
                        commitments=[],
                        weekly_focus_id=wf.id if wf else None,
                        week_no=getattr(wf, "week_no", None) if wf else None,
                    )
                except Exception:
                    check_in_id = None
            else:
                # habit steps feedback or button reply
                check_in_id = None
                try:
                    check_in_id = record_checkin(
                        user_id=user.id,
                        touchpoint_type="sunday",
                        progress_updates=[],
                        blockers=[],
                        commitments=[{"note": text}],
                        weekly_focus_id=wf.id if wf else None,
                        week_no=getattr(wf, "week_no", None) if wf else None,
                    )
                except Exception:
                    check_in_id = None
                note_prefix = "Sunday check-in" if review_mode == "kr" else "Habit steps check-in"
                for kr_id in kr_ids:
                    entry = OKRKrEntry(
                        key_result_id=kr_id,
                        occurred_at=datetime.utcnow(),
                        actual_num=None,
                        note=f"{note_prefix}: {text}",
                        source="sunday",
                        check_in_id=check_in_id,
                    )
                    s.add(entry)
                s.commit()

            history = state.get("history") or []
            support_text, new_history = _support_conversation(history, text, user, review_mode, week_no)
            _send_sunday(to=user.phone, text=support_text)
            try:
                tp_id = state.get("tp_id") if isinstance(state, dict) else None
                if tp_id:
                    update_touchpoint(
                        tp_id,
                        generated_text=support_text,
                        meta={"source": "sunday", "label": "sunday", "review_mode": review_mode},
                        source_check_in_id=check_in_id,
                    )
            except Exception:
                pass
            _set_state(s, user.id, None)
            s.commit()
            general_support.activate(user.id, source="sunday", week_no=week_no, send_intro=False)
            return

        if mode == "support":
            history = state.get("history") or []
            support_text, new_history = _support_conversation(history, text, user, review_mode, week_no)
            _send_sunday(to=user.phone, text=support_text)
            _set_state(s, user.id, None)
            s.commit()
            general_support.activate(user.id, source="sunday", week_no=week_no, send_intro=False)
            return

        # default: clear if unknown
        _set_state(s, user.id, None)
        s.commit()
