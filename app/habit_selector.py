from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from . import general_support
from . import habit_steps as habit_flow
from .db import SessionLocal
from .models import AssessmentRun, OKRKeyResult, OKRKrHabitStep, User, UserPreference, WeeklyFocus
from .coaching_delivery import send_coaching_text
from .programme_timeline import BLOCK_WEEKS, PILLAR_SEQUENCE, week_anchor_date, week_no_for_focus_start
from .prompts import kr_payload_list
from .touchpoints import log_touchpoint
from .virtual_clock import get_effective_today
from .weekly_plan import ensure_weekly_plan, resolve_programme_start_date

STATE_KEY = "habit_setup_state"
LEGACY_STATE_KEY = "sunday_state"
_DAY_KEYS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
_DAY_LABEL = {
    "monday": "Monday",
    "tuesday": "Tuesday",
    "wednesday": "Wednesday",
    "thursday": "Thursday",
    "friday": "Friday",
    "saturday": "Saturday",
    "sunday": "Sunday",
}


def _day_key(day_key: str | None) -> str:
    key = str(day_key or "").strip().lower()
    return key if key in _DAY_KEYS else "sunday"


def _habit_tag() -> str:
    return "*Habit steps*"


def _prefix_habit(text: str | None) -> str | None:
    if not text:
        return text
    out = str(text).strip()
    tag = _habit_tag()
    out = re.sub(
        r"^\*(?:habit\s+steps|sunday\.?|monday|tuesday|wednesday|thursday|friday|saturday)\*",
        tag,
        out,
        count=1,
        flags=re.IGNORECASE,
    )
    if not out.lower().startswith(tag.lower()):
        out = f"{tag} {out}"
    return out


def _send_habit(
    user: User,
    *,
    day_key: str | None,
    text: str,
    quick_replies: list[str] | None = None,
) -> str:
    return send_coaching_text(
        user=user,
        text=_prefix_habit(text) or text,
        category="habit-setup",
        quick_replies=quick_replies,
        source=f"habit_selector:{_day_key(day_key)}",
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


def _next_target_week(session: Session, user_id: int, wf: WeeklyFocus, today_date) -> tuple[int, int | None]:
    base_week = getattr(wf, "week_no", None)
    if not base_week:
        base_week = _infer_week_no(session, user_id, wf)
        try:
            wf.week_no = base_week
            session.add(wf)
        except Exception:
            pass

    calendar_week = None
    programme_start = resolve_programme_start_date(session, user_id)
    try:
        from .programme_timeline import week_no_for_date

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


def _pick_krs_for_target_week(
    session: Session,
    user_id: int,
    target_week: int,
    fallback_week: int | None,
) -> tuple[int, list[int]]:
    target_pillar = _pillar_for_week_no(target_week)
    payload = kr_payload_list(user_id, session=session, week_no=target_week, max_krs=3)
    kr_ids = _kr_ids_from_payload(payload, expected_pillar=target_pillar)
    if kr_ids:
        return target_week, kr_ids
    if fallback_week and fallback_week != target_week:
        fallback_pillar = _pillar_for_week_no(fallback_week)
        same_pillar = bool(target_pillar and fallback_pillar and target_pillar == fallback_pillar)
        if target_pillar is None or same_pillar:
            payload = kr_payload_list(user_id, session=session, week_no=fallback_week, max_krs=3)
            kr_ids = _kr_ids_from_payload(payload, expected_pillar=target_pillar or fallback_pillar)
            if kr_ids:
                return fallback_week, kr_ids
    return target_week, []


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


def _get_state(session: Session, user_id: int) -> tuple[Optional[dict], str]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if pref and pref.value:
        try:
            return json.loads(pref.value), STATE_KEY
        except Exception:
            pass

    # Legacy support for users currently mid-flow from previous implementation.
    legacy = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == LEGACY_STATE_KEY)
        .one_or_none()
    )
    if legacy and legacy.value:
        try:
            payload = json.loads(legacy.value)
            if str((payload or {}).get("mode") or "") == "habit_setting":
                return payload, LEGACY_STATE_KEY
        except Exception:
            pass
    return None, STATE_KEY


def _set_state(session: Session, user_id: int, state: Optional[dict], key: str = STATE_KEY) -> None:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == key)
        .one_or_none()
    )
    if state is None:
        if pref:
            session.delete(pref)
        return
    if pref:
        pref.value = json.dumps(state)
    else:
        session.add(UserPreference(user_id=user_id, key=key, value=json.dumps(state)))


def has_active_state(user_id: int) -> bool:
    with SessionLocal() as s:
        state, _key = _get_state(s, user_id)
        return bool(state and str(state.get("mode") or "") == "habit_setting")


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
        target_week, kr_ids = _pick_krs_for_target_week(session, user.id, target_week, active_week_i)
        return int(target_week), (int(target_wf_id) if target_wf_id else None), [int(v) for v in kr_ids]

    target_week = active_week_i
    target_wf = (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user.id, WeeklyFocus.week_no == target_week)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )
    target_wf_id = int(target_wf.id) if target_wf and getattr(target_wf, "id", None) else int(getattr(wf, "id", None) or 0) or None
    target_week, kr_ids = _pick_krs_for_target_week(session, user.id, target_week, None)
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


def _start_habit_setup_flow(
    session: Session,
    user: User,
    *,
    day_key: str,
    target_week: int,
    target_wf_id: int | None,
    kr_ids: list[int],
) -> bool:
    krs = _ordered_krs(session, kr_ids)
    if not krs:
        _send_habit(user, day_key=day_key, text="I couldn't load your key results right now. Please try again shortly.")
        return False

    options_by_index = _build_habit_options(user, krs, target_week)
    if not options_by_index or not options_by_index[0]:
        _send_habit(user, day_key=day_key, text="I couldn't prepare habit options right now. Please try again in a moment.")
        return False

    name = (getattr(user, "first_name", "") or "").strip().title() or "there"
    intro = (
        f"Hi {name}, before today’s {_DAY_LABEL.get(day_key, 'day')} message, "
        f"let's quickly set your habit steps for week {target_week}. "
        "Pick one option for each KR."
    )
    _send_habit(user, day_key=day_key, text=intro)
    first_msg = habit_flow.build_actions_for_kr(1, krs[0], options_by_index[0])
    _send_habit(user, day_key=day_key,
        text=first_msg,
        quick_replies=habit_flow.kr_quick_replies(1, options_by_index[0]),
    )
    tp_id = log_touchpoint(
        user_id=user.id,
        tp_type="habit_steps_setup",
        weekly_focus_id=target_wf_id,
        week_no=target_week,
        generated_text=intro,
        meta={
            "source": "daily_gate",
            "label": "habit_steps_setup",
            "flow": "habit_setting",
            "resume_day": day_key,
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
        "resume_day": day_key,
        "day_key": day_key,
    }
    if tp_id:
        state["tp_id"] = tp_id
    _set_state(session, user.id, state, STATE_KEY)
    session.commit()
    return True


def ensure_habit_steps_ready_for_day(user: User, day_key: str) -> bool:
    day = _day_key(day_key)
    with SessionLocal() as s:
        # If a habit-setting flow is already active, keep deferring day prompts
        # until the user completes selections. Do not restart or resend the opener.
        state, _state_key = _get_state(s, int(user.id))
        if state and str(state.get("mode") or "") == "habit_setting":
            return False
        general_support.clear(user.id)
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
        _start_habit_setup_flow(
            s,
            user,
            day_key=day,
            target_week=int(target_week),
            target_wf_id=target_wf_id,
            kr_ids=kr_ids,
        )
        return False


def handle_message(user: User, body: str) -> None:
    text = (body or "").strip()
    if not text:
        return
    with SessionLocal() as s:
        state, state_key = _get_state(s, user.id)
        if not state:
            return
        mode = str(state.get("mode") or "")
        if mode != "habit_setting":
            return
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
        resume_day = _day_key(state.get("resume_day"))
        day_key = _day_key(state.get("day_key") or resume_day)
        krs = _ordered_krs(s, kr_ids)
        if not krs:
            _set_state(s, user.id, None, state_key)
            s.commit()
            _send_habit(user, day_key=day_key, text="I couldn't load your KRs just now. Please try again.")
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
                _send_habit(user, day_key=day_key,
                    text=kr_msg,
                    quick_replies=habit_flow.kr_quick_replies(current_idx + 1, options),
                )
            else:
                _send_habit(user, day_key=day_key, text="Please choose an option (e.g., KR1 A).")
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
                notes=f"{day_key} habit setup week {week_no}" if week_no is not None else None,
                preferred_kr_ids=list(edits_to_apply.keys()) or kr_ids,
            )
            resolved_wf_id = int(resolved_wf.id) if resolved_wf and getattr(resolved_wf, "id", None) else wf_id
            if edits_to_apply:
                habit_flow.apply_habit_step_edits(s, user.id, resolved_wf_id, week_no, edits_to_apply)
                habit_flow.activate_habit_steps(s, user.id, week_no, list(edits_to_apply.keys()))
            s.commit()

            chosen = habit_flow.resolve_chosen_steps(krs, options_by_index, merged_selections, merged_edits)
            confirm_msg = habit_flow.confirmation_message(krs, chosen)
            _send_habit(user, day_key=day_key, text=confirm_msg)
            _set_state(s, user.id, None, state_key)
            s.commit()
            try:
                from . import scheduler  # local import to avoid circular imports at module load

                scheduler._run_day_prompt(int(user.id), resume_day)  # type: ignore[attr-defined]
            except Exception:
                _send_habit(user, day_key=day_key,
                    text=f"I saved your habit steps, but couldn't resume today’s {_DAY_LABEL.get(resume_day, 'day')} message. Please say {resume_day} to retry.",
                )
            return

        next_idx = current_idx
        if 0 <= current_idx < len(krs) and krs[current_idx].id in selected_ids:
            next_idx = current_idx + 1
        if next_idx < len(krs):
            next_options = options_by_index[next_idx] if next_idx < len(options_by_index) else []
            next_msg = habit_flow.build_actions_for_kr(next_idx + 1, krs[next_idx], next_options)
            _send_habit(user, day_key=day_key,
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
                    "day_key": day_key,
                },
                state_key,
            )
            s.commit()
            return
