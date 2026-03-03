"""
Sunday flow:
- Behaves like a regular daily prompt.
- If required habit steps are missing, run setup first.
- Once setup is complete, continue directly into the Sunday daily check-in.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import general_support
from . import habit_steps as habit_flow
from .db import SessionLocal
from .job_queue import enqueue_job, should_use_worker
from .kickoff import COACH_NAME
from .models import AssessmentRun, JobAudit, OKRKeyResult, OKRKrEntry, OKRKrHabitStep, User, UserPreference, WeeklyFocus
from .nudges import send_whatsapp
from .prompts import build_prompt, kr_payload_list, run_llm_prompt
from .programme_timeline import BLOCK_WEEKS, PILLAR_SEQUENCE, week_anchor_date, week_no_for_date, week_no_for_focus_start
from .touchpoints import log_touchpoint
from .virtual_clock import get_effective_today
from .weekly_plan import ensure_weekly_plan, resolve_programme_start_date

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
    outbound = _apply_sunday_marker(text) or text
    if outbound and not outbound.lower().startswith("*sunday"):
        outbound = f"{_sunday_tag()} {outbound}"
    return send_whatsapp(
        text=outbound,
        to=to,
        category=category,
        quick_replies=quick_replies,
    )


def _hsapp_base_url() -> str:
    base = (
        (os.getenv("HSAPP_PUBLIC_URL") or "").strip()
        or (os.getenv("HSAPP_BASE_URL") or "").strip()
        or (os.getenv("APP_BASE_URL") or "").strip()
        or (os.getenv("NEXT_PUBLIC_HSAPP_BASE_URL") or "").strip()
        or (os.getenv("NEXT_PUBLIC_APP_BASE_URL") or "").strip()
        or "https://app.healthsense.coach"
    )
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base.rstrip("/")


def _audit_hsapp_link_resolution(*, user_id: int | None, reason: str, payload: dict, status: str = "ok", error: str | None = None) -> None:
    try:
        with SessionLocal() as s:
            s.add(
                JobAudit(
                    job_name="hsapp_link_resolution",
                    status=status,
                    payload={
                        "user_id": user_id,
                        "reason": reason,
                        **(payload or {}),
                    },
                    error=error or None,
                )
            )
            s.commit()
    except Exception:
        pass


def _hsapp_login_url_with_debug(*, user_id: int | None, reason: str) -> str:
    candidates = {
        "HSAPP_PUBLIC_URL": (os.getenv("HSAPP_PUBLIC_URL") or "").strip(),
        "HSAPP_BASE_URL": (os.getenv("HSAPP_BASE_URL") or "").strip(),
        "APP_BASE_URL": (os.getenv("APP_BASE_URL") or "").strip(),
        "NEXT_PUBLIC_HSAPP_BASE_URL": (os.getenv("NEXT_PUBLIC_HSAPP_BASE_URL") or "").strip(),
        "NEXT_PUBLIC_APP_BASE_URL": (os.getenv("NEXT_PUBLIC_APP_BASE_URL") or "").strip(),
    }
    try:
        base = _hsapp_base_url()
        login_url = f"{base}/login"
        _audit_hsapp_link_resolution(
            user_id=user_id,
            reason=reason,
            payload={
                "resolved_base_url": base,
                "login_url": login_url,
                "candidates": candidates,
            },
            status="ok",
        )
        return login_url
    except Exception as e:
        _audit_hsapp_link_resolution(
            user_id=user_id,
            reason=reason,
            payload={"candidates": candidates},
            status="error",
            error=str(e),
        )
        raise


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


def _infer_week_no(session: Session, user_id: int, wf: WeeklyFocus) -> int:
    programme_start = None
    run = (
        session.query(AssessmentRun)
        .filter(AssessmentRun.user_id == user_id, AssessmentRun.finished_at.isnot(None))
        .order_by(AssessmentRun.finished_at.desc(), AssessmentRun.id.desc())
        .first()
    )
    if not run:
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


def _get_state(session: Session, user_id: int) -> Optional[dict]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if pref and pref.value:
        try:
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
    if pref:
        pref.value = json.dumps(state)
    else:
        session.add(UserPreference(user_id=user_id, key=STATE_KEY, value=json.dumps(state)))


def has_active_state(user_id: int) -> bool:
    with SessionLocal() as s:
        return _get_state(s, user_id) is not None


def _ordered_krs(session: Session, kr_ids: list[int]) -> list[OKRKeyResult]:
    if not kr_ids:
        return []
    rows = session.query(OKRKeyResult).filter(OKRKeyResult.id.in_(kr_ids)).all()
    by_id = {row.id: row for row in rows if row and row.id}
    return [by_id[kr_id] for kr_id in kr_ids if kr_id in by_id]


def _build_habit_options(user: User, krs: list[OKRKeyResult], week_no: int) -> list[list[str]]:
    _actions_text, options_by_index = habit_flow.build_sunday_habit_actions("", krs, user, week_no=week_no)
    out: list[list[str]] = []
    for idx, kr in enumerate(krs):
        opts = list(options_by_index[idx]) if idx < len(options_by_index) else []
        opts = [opt.strip() for opt in opts if opt and opt.strip()]
        if not opts:
            opts = habit_flow.fallback_options_for_kr(kr)
        if len(opts) > 3:
            opts = opts[:3]
        out.append(opts)
    return out


def _next_target_week(session: Session, user_id: int, wf: WeeklyFocus, today_date) -> tuple[int, int | None]:
    # Primary: current focus row week number.
    base_week = getattr(wf, "week_no", None)
    if not base_week:
        base_week = _infer_week_no(session, user_id, wf)
        try:
            wf.week_no = base_week
            session.add(wf)
        except Exception:
            pass

    # Guardrail: if weekly-focus rows are stale/missing, infer current programme week from calendar.
    calendar_week = None
    programme_start = resolve_programme_start_date(session, user_id)
    try:
        calendar_week = week_no_for_date(programme_start, today_date)
    except Exception:
        calendar_week = None

    try:
        base_week_i = int(base_week)
    except Exception:
        base_week_i = 1
    if calendar_week is not None:
        try:
            base_week_i = max(base_week_i, int(calendar_week))
        except Exception:
            pass

    target_week = max(1, int(base_week_i) + 1)
    # Bridge period (assessment complete -> first Monday): Sunday should set week 1 steps.
    try:
        anchor_week_start = week_anchor_date(programme_start, default_today=today_date)
        if today_date < anchor_week_start:
            target_week = 1
    except Exception:
        pass
    target_wf = (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id, WeeklyFocus.week_no == target_week)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )
    return target_week, (target_wf.id if target_wf else None)


def _pillar_for_week_no(week_no: int | None) -> str | None:
    if week_no is None:
        return None
    try:
        week_i = int(week_no)
    except Exception:
        return None
    if week_i <= 0:
        return None
    if not PILLAR_SEQUENCE:
        return None
    block_weeks = int(BLOCK_WEEKS or 3)
    block_index = min((week_i - 1) // max(1, block_weeks), len(PILLAR_SEQUENCE) - 1)
    try:
        return (str(PILLAR_SEQUENCE[block_index][0]).strip().lower() or None)
    except Exception:
        return None


def _kr_ids_from_payload(payload: list[dict], expected_pillar: str | None = None) -> list[int]:
    ids: list[int] = []
    for item in payload:
        kr_id = item.get("id")
        if not kr_id:
            continue
        pillar = (item.get("pillar") or "").strip().lower()
        if expected_pillar and pillar != expected_pillar:
            continue
        try:
            ids.append(int(kr_id))
        except Exception:
            continue
    return ids


def _pick_krs_for_sunday(session: Session, user_id: int, target_week: int, fallback_week: int | None) -> tuple[int, list[int]]:
    target_pillar = _pillar_for_week_no(target_week)
    payload = kr_payload_list(user_id, session=session, week_no=target_week, max_krs=3)
    kr_ids = _kr_ids_from_payload(payload, expected_pillar=target_pillar)
    if kr_ids:
        return target_week, kr_ids
    if fallback_week and fallback_week != target_week:
        fallback_pillar = _pillar_for_week_no(fallback_week)
        # Never fall back to a different pillar (e.g. week 3 -> week 4 transition).
        same_pillar = bool(target_pillar and fallback_pillar and target_pillar == fallback_pillar)
        if target_pillar is None or same_pillar:
            payload = kr_payload_list(user_id, session=session, week_no=fallback_week, max_krs=3)
            kr_ids = _kr_ids_from_payload(payload, expected_pillar=target_pillar or fallback_pillar)
            if kr_ids:
                return fallback_week, kr_ids
    return target_week, []


def _has_habit_steps_for_week(session: Session, user_id: int, week_no: int, kr_ids: list[int]) -> bool:
    if not kr_ids:
        return True
    rows = (
        session.query(OKRKrHabitStep.kr_id, OKRKrHabitStep.step_text)
        .filter(
            OKRKrHabitStep.user_id == int(user_id),
            OKRKrHabitStep.week_no == int(week_no),
            OKRKrHabitStep.kr_id.in_([int(v) for v in kr_ids]),
            OKRKrHabitStep.status != "archived",
        )
        .all()
    )
    covered = {
        int(kr_id)
        for kr_id, step_text in rows
        if kr_id is not None and str(step_text or "").strip()
    }
    return all(int(kr_id) in covered for kr_id in kr_ids)


def _start_habit_setup_flow(
    session: Session,
    user: User,
    *,
    target_week: int,
    target_wf_id: int | None,
    kr_ids: list[int],
    resume_day: str | None = None,
    setup_source: str = "sunday",
) -> bool:
    krs = _ordered_krs(session, kr_ids)
    if not krs:
        _send_sunday(to=user.phone, text="I couldn't load your key results right now. Please try again shortly.")
        return False

    options_by_index = _build_habit_options(user, krs, target_week)
    if not options_by_index or not options_by_index[0]:
        _send_sunday(to=user.phone, text="I couldn't prepare habit options right now. Please try again in a moment.")
        return False

    name = (getattr(user, "first_name", "") or "").strip().title() or "there"
    if resume_day and resume_day != "sunday":
        intro = (
            f"Hi {name}, before today’s {resume_day.capitalize()} message, "
            f"let's quickly set your habit steps for week {target_week}. "
            "Pick one option for each KR."
        )
    else:
        intro = (
            f"*Sunday* Hi {name}, let's set your habit steps for week {target_week}. "
            "Pick one option for each KR."
        )

    _send_sunday(to=user.phone, text=intro)
    first_msg = habit_flow.build_actions_for_kr(1, krs[0], options_by_index[0])
    _send_sunday(
        to=user.phone,
        text=first_msg,
        quick_replies=habit_flow.kr_quick_replies(1, options_by_index[0]),
    )

    tp_type = "sunday" if not (resume_day and resume_day != "sunday") else "habit_steps_setup"
    tp_id = log_touchpoint(
        user_id=user.id,
        tp_type=tp_type,
        weekly_focus_id=target_wf_id,
        week_no=target_week,
        generated_text=intro,
        meta={
            "source": setup_source,
            "label": "sunday" if tp_type == "sunday" else "habit_steps_setup",
            "flow": "habit_setting",
            "resume_day": resume_day,
        },
    )
    state: dict[str, object] = {
        "mode": "habit_setting",
        "kr_ids": kr_ids,
        "wf_id": target_wf_id,
        "week_no": target_week,
        "options": options_by_index,
        "current_idx": 0,
        "selections": {},
        "edits": {},
        "resume_day": (resume_day or ""),
    }
    if tp_id:
        state["tp_id"] = tp_id
    _set_state(session, user.id, state)
    session.commit()
    return True


def _resolve_habit_setup_target_for_day(
    session: Session,
    user: User,
    *,
    day_key: str,
    today_date,
) -> tuple[int, int | None, list[int]] | None:
    wf = _resolve_weekly_focus(session, user.id, today_date)
    if not wf:
        boot_wf, boot_kr_ids = ensure_weekly_plan(
            session,
            int(user.id),
            reference_day=today_date,
            notes=f"{day_key} bootstrap weekly plan",
        )
        if not boot_wf:
            return None
        session.commit()
        wf = boot_wf
        if day_key != "sunday":
            week_no = int(getattr(wf, "week_no", None) or 1)
            return week_no, int(getattr(wf, "id", None) or 0) or None, [int(v) for v in (boot_kr_ids or []) if v]

    active_week = getattr(wf, "week_no", None) or _infer_week_no(session, user.id, wf)
    try:
        active_week_i = max(1, int(active_week))
    except Exception:
        active_week_i = 1

    if day_key == "sunday":
        target_week, target_wf_id = _next_target_week(session, user.id, wf, today_date)
        target_week, kr_ids = _pick_krs_for_sunday(session, user.id, target_week, active_week_i)
        return int(target_week), (int(target_wf_id) if target_wf_id else None), [int(v) for v in kr_ids]

    target_week = active_week_i
    target_wf = (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user.id, WeeklyFocus.week_no == target_week)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )
    target_wf_id = int(target_wf.id) if target_wf and getattr(target_wf, "id", None) else int(getattr(wf, "id", None) or 0) or None
    target_week, kr_ids = _pick_krs_for_sunday(session, user.id, target_week, None)
    if not kr_ids:
        ensured_wf, ensured_kr_ids = ensure_weekly_plan(
            session,
            int(user.id),
            week_no=target_week,
            reference_day=today_date,
            notes=f"{day_key} habit setup week {target_week}",
        )
        if ensured_wf and getattr(ensured_wf, "id", None):
            target_wf_id = int(ensured_wf.id)
        kr_ids = [int(v) for v in (ensured_kr_ids or []) if v]
    return int(target_week), target_wf_id, [int(v) for v in kr_ids]


def ensure_habit_steps_ready_for_day(user: User, day_key: str) -> bool:
    day = str(day_key or "").strip().lower()
    if day not in {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}:
        return True
    general_support.clear(user.id)
    with SessionLocal() as s:
        today = get_effective_today(s, user.id, default_today=datetime.utcnow().date())
        resolved = _resolve_habit_setup_target_for_day(s, user, day_key=day, today_date=today)
        if not resolved:
            return True
        target_week, target_wf_id, kr_ids = resolved
        if not kr_ids:
            return True
        ensured_wf, ensured_kr_ids = ensure_weekly_plan(
            s,
            int(user.id),
            week_no=target_week,
            reference_day=today,
            notes=f"{day} habit setup week {target_week}",
            preferred_kr_ids=kr_ids,
        )
        if ensured_wf and getattr(ensured_wf, "id", None):
            target_wf_id = int(ensured_wf.id)
        kr_ids = [int(v) for v in (ensured_kr_ids or kr_ids) if v]
        if _has_habit_steps_for_week(s, int(user.id), int(target_week), kr_ids):
            return True
        resume_day = day if day != "sunday" else None
        _start_habit_setup_flow(
            s,
            user,
            target_week=int(target_week),
            target_wf_id=target_wf_id,
            kr_ids=kr_ids,
            resume_day=resume_day,
            setup_source="daily_gate" if resume_day else "sunday",
        )
        return False


def _habit_steps_prompt_context(session: Session, user_id: int, week_no: int, kr_ids: list[int]) -> str:
    if not kr_ids:
        return ""
    rows = (
        session.query(OKRKrHabitStep.kr_id, OKRKrHabitStep.step_text)
        .filter(
            OKRKrHabitStep.user_id == int(user_id),
            OKRKrHabitStep.week_no == int(week_no),
            OKRKrHabitStep.kr_id.in_([int(v) for v in kr_ids]),
            OKRKrHabitStep.status != "archived",
        )
        .order_by(OKRKrHabitStep.kr_id.asc(), OKRKrHabitStep.sort_order.asc(), OKRKrHabitStep.id.asc())
        .all()
    )
    lines: list[str] = []
    seen: set[tuple[int, str]] = set()
    for kr_id, step_text in rows:
        step = str(step_text or "").strip()
        if not step:
            continue
        key = (int(kr_id or 0), step)
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"KR{int(kr_id)}: {step}")
    return "\n".join(lines)


def send_sunday_daily(user: User, coach_name: str = COACH_NAME) -> None:
    general_support.clear(user.id)
    with SessionLocal() as s:
        today = get_effective_today(s, user.id, default_today=datetime.utcnow().date())
        wf = _resolve_weekly_focus(s, user.id, today)
        if not wf:
            _send_sunday(to=user.phone, text="Your weekly plan is still being prepared. Please try again shortly.")
            return

        week_no = getattr(wf, "week_no", None) or _infer_week_no(s, user.id, wf)
        try:
            week_no_i = max(1, int(week_no))
        except Exception:
            week_no_i = 1

        krs_payload = kr_payload_list(user.id, session=s, week_no=week_no_i, max_krs=3)
        kr_ids = [int(item.get("id")) for item in krs_payload if item.get("id")]
        habit_steps_txt = _habit_steps_prompt_context(s, int(user.id), week_no_i, kr_ids)
        prompt_assembly = build_prompt(
            "sunday_daily",
            user_id=user.id,
            coach_name=coach_name,
            user_name=(user.first_name or ""),
            locale=getattr(user, "tz", "UK") or "UK",
            week_no=week_no_i,
            review_mode="habit",
            timeframe="Sunday",
            krs=krs_payload,
            habit_steps=habit_steps_txt,
        )
        candidate = run_llm_prompt(
            prompt_assembly.text,
            user_id=user.id,
            touchpoint="sunday_daily",
            context_meta={"week_no": week_no_i},
            prompt_variant=prompt_assembly.variant,
            task_label=prompt_assembly.task_label,
            prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
            block_order=prompt_assembly.block_order,
            log=True,
        )
        message = (candidate or "").strip()
        if not message:
            message = (
                "Quick Sunday check-in: how did your habit steps feel this week, "
                "and is there one step you want to tweak for next week?"
            )

        _send_sunday(
            to=user.phone,
            text=message,
            quick_replies=["All good", "Need help"],
        )
        log_touchpoint(
            user_id=user.id,
            tp_type="sunday",
            weekly_focus_id=int(getattr(wf, "id", None) or 0) or None,
            week_no=week_no_i,
            kr_ids=kr_ids,
            meta={"source": "sunday", "label": "sunday", "flow": "daily_review"},
            generated_text=message,
        )
        if kr_ids:
            _send_sunday(
                to=user.phone,
                text="*Sunday* Would you like to update your KR numbers now?",
                quick_replies=["WhatsApp", "App", "Not now"],
            )
            _set_state(
                s,
                user.id,
                {
                    "mode": "okr_update_choice",
                    "kr_ids": kr_ids,
                    "wf_id": int(getattr(wf, "id", None) or 0) or None,
                    "week_no": week_no_i,
                },
            )
            s.commit()
            return
        general_support.activate(user.id, source="sunday", week_no=week_no_i, send_intro=False)


def send_sunday_review(user: User, coach_name: str = COACH_NAME) -> None:
    if should_use_worker() and not _in_worker_process():
        job_id = enqueue_job("day_prompt", {"user_id": user.id, "day": "sunday"}, user_id=user.id)
        print(f"[sunday] enqueued day prompt user_id={user.id} job={job_id}")
        return
    if not ensure_habit_steps_ready_for_day(user, "sunday"):
        return
    send_sunday_daily(user, coach_name=coach_name)


def _apply_okr_updates_in_whatsapp(session: Session, krs: list[OKRKeyResult], text: str) -> bool:
    numbers = []
    for token in text.replace(",", " ").split():
        try:
            numbers.append(float(token))
        except Exception:
            continue
    if len(numbers) < len(krs):
        return False
    for idx, kr in enumerate(krs):
        val = numbers[idx]
        kr.actual_num = val
        session.add(
            OKRKrEntry(
                key_result_id=kr.id,
                occurred_at=datetime.utcnow(),
                actual_num=val,
                note="Sunday KR update (WhatsApp)",
                source="sunday",
            )
        )
    return True


def handle_message(user: User, body: str) -> None:
    text = (body or "").strip()
    if not text:
        return
    with SessionLocal() as s:
        state = _get_state(s, user.id)
        if not state:
            return
        mode = str(state.get("mode") or "")
        kr_ids = [int(v) for v in (state.get("kr_ids") or []) if str(v).isdigit()]
        week_no = state.get("week_no")
        try:
            week_no = int(week_no) if week_no is not None else None
        except Exception:
            week_no = None
        wf_id = state.get("wf_id")
        try:
            wf_id = int(wf_id) if wf_id is not None else None
        except Exception:
            wf_id = None
        resume_day = str(state.get("resume_day") or "").strip().lower()
        krs = _ordered_krs(s, kr_ids)

        if mode == "habit_setting":
            if not krs:
                _set_state(s, user.id, None)
                s.commit()
                _send_sunday(to=user.phone, text="I couldn't load your KRs just now. Reply sunday to try again.")
                return
            options_by_index = state.get("options") or []
            current_idx = int(state.get("current_idx") or 0)
            stored_selections = habit_flow.normalize_state_selections(state.get("selections"), krs, options_by_index)
            stored_edits = habit_flow.normalize_state_edits(state.get("edits"))
            selections = habit_flow.parse_option_selections(text, options_by_index)
            edits = habit_flow.extract_step_edits(text, krs)

            if habit_flow.is_confirm_message(text):
                selections = {idx: 0 for idx in range(len(krs))}
                edits = {}

            if not selections and not edits:
                if 0 <= current_idx < len(krs):
                    options = options_by_index[current_idx] if current_idx < len(options_by_index) else []
                    kr_msg = habit_flow.build_actions_for_kr(current_idx + 1, krs[current_idx], options)
                    _send_sunday(
                        to=user.phone,
                        text=kr_msg,
                        quick_replies=habit_flow.kr_quick_replies(current_idx + 1, options),
                    )
                else:
                    _send_sunday(to=user.phone, text="Please choose an option (e.g., KR1 A).")
                return

            merged_selections = {**stored_selections, **selections}
            merged_edits = {**stored_edits, **edits}
            selected_ids = habit_flow.selected_kr_ids(krs, merged_selections, merged_edits)

            if selected_ids and len(selected_ids) == len(krs):
                edits_to_apply: dict[int, list[str]] = {}
                for idx, opt_idx in merged_selections.items():
                    opts = options_by_index[idx] if idx < len(options_by_index) else []
                    if opts and 0 <= opt_idx < len(opts):
                        edits_to_apply[krs[idx].id] = [opts[opt_idx]]
                for kr_id, steps in merged_edits.items():
                    edits_to_apply[kr_id] = steps
                resolved_wf, _resolved_kr_ids = ensure_weekly_plan(
                    s,
                    int(user.id),
                    week_no=week_no,
                    reference_day=get_effective_today(s, user.id, default_today=datetime.utcnow().date()),
                    notes=f"sunday habit setup week {week_no}" if week_no is not None else None,
                    preferred_kr_ids=list(edits_to_apply.keys()) or kr_ids,
                )
                resolved_wf_id = int(resolved_wf.id) if resolved_wf and getattr(resolved_wf, "id", None) else wf_id
                if edits_to_apply:
                    habit_flow.apply_habit_step_edits(s, user.id, resolved_wf_id, week_no, edits_to_apply)
                    habit_flow.activate_habit_steps(s, user.id, week_no, list(edits_to_apply.keys()))
                s.commit()

                chosen = habit_flow.resolve_chosen_steps(krs, options_by_index, merged_selections, merged_edits)
                confirm_msg = habit_flow.confirmation_message(krs, chosen)
                if not confirm_msg.lower().startswith("*sunday*"):
                    confirm_msg = "*Sunday* " + confirm_msg
                _send_sunday(to=user.phone, text=confirm_msg)
                if resume_day in {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}:
                    _set_state(s, user.id, None)
                    s.commit()
                    try:
                        from . import scheduler  # local import to avoid circular imports at module load

                        scheduler._run_day_prompt(int(user.id), resume_day)  # type: ignore[attr-defined]
                    except Exception:
                        _send_sunday(
                            to=user.phone,
                            text=f"I saved your habit steps, but couldn't resume today’s {resume_day.capitalize()} message. Please say {resume_day} to retry.",
                        )
                    return
                _send_sunday(
                    to=user.phone,
                    text="*Sunday* Would you like to update your KR numbers now?",
                    quick_replies=["WhatsApp", "App", "Not now"],
                )
                _set_state(
                    s,
                    user.id,
                    {
                        "mode": "okr_update_choice",
                        "kr_ids": kr_ids,
                        "wf_id": resolved_wf_id,
                        "week_no": week_no,
                    },
                )
                s.commit()
                return

            next_idx = current_idx
            if 0 <= current_idx < len(krs) and krs[current_idx].id in selected_ids:
                next_idx = current_idx + 1
            if next_idx < len(krs):
                next_options = options_by_index[next_idx] if next_idx < len(options_by_index) else []
                next_msg = habit_flow.build_actions_for_kr(next_idx + 1, krs[next_idx], next_options)
                _send_sunday(
                    to=user.phone,
                    text=next_msg,
                    quick_replies=habit_flow.kr_quick_replies(next_idx + 1, next_options),
                )
                _set_state(
                    s,
                    user.id,
                    {
                        "mode": "habit_setting",
                        "kr_ids": kr_ids,
                        "wf_id": wf_id,
                        "week_no": week_no,
                        "options": options_by_index,
                        "current_idx": next_idx,
                        "selections": merged_selections,
                        "edits": merged_edits,
                        "resume_day": resume_day,
                    },
                )
                s.commit()
                return

        if mode == "okr_update_choice":
            cleaned = re.sub(r"\s+", " ", text.strip().lower())
            if cleaned in {"not now", "no", "skip", "later", "no thanks"}:
                _send_sunday(to=user.phone, text="*Sunday* No problem. We can update KRs later.")
                _set_state(s, user.id, None)
                s.commit()
                general_support.activate(user.id, source="sunday", week_no=week_no, send_intro=False)
                return
            if "app" in cleaned:
                app_url = _hsapp_login_url_with_debug(
                    user_id=int(getattr(user, "id", 0) or 0) or None,
                    reason="sunday_okr_update_choice_app",
                )
                _send_sunday(
                    to=user.phone,
                    text=(
                        "*Sunday* Great. Update your KRs in the app using 'Update KRs' on Home.\n"
                        f"Log in here: {app_url}"
                    ),
                )
                _set_state(s, user.id, None)
                s.commit()
                general_support.activate(user.id, source="sunday", week_no=week_no, send_intro=False)
                return
            if "whatsapp" in cleaned or "what's app" in cleaned or "whats app" in cleaned:
                _send_sunday(
                    to=user.phone,
                    text="*Sunday* Reply with one number per KR in order (e.g., 3 4 2).",
                )
                _set_state(
                    s,
                    user.id,
                    {
                        "mode": "okr_update_whatsapp",
                        "kr_ids": kr_ids,
                        "wf_id": wf_id,
                        "week_no": week_no,
                    },
                )
                s.commit()
                return
            _send_sunday(
                to=user.phone,
                text="*Sunday* Choose how to update: WhatsApp, App, or Not now.",
                quick_replies=["WhatsApp", "App", "Not now"],
            )
            return

        if mode == "okr_update_whatsapp":
            if not krs:
                _set_state(s, user.id, None)
                s.commit()
                _send_sunday(to=user.phone, text="I couldn't load your KRs just now. Reply sunday to restart.")
                return
            ok = _apply_okr_updates_in_whatsapp(s, krs, text)
            if not ok:
                _send_sunday(to=user.phone, text="*Sunday* Please send one number per KR in order (e.g., 3 4 2).")
                return
            s.commit()
            _send_sunday(to=user.phone, text="*Sunday* Saved. Your KR updates are recorded.")
            _set_state(s, user.id, None)
            s.commit()
            general_support.activate(user.id, source="sunday", week_no=week_no, send_intro=False)
            return

        _set_state(s, user.id, None)
        s.commit()
