from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .focus import select_top_krs_for_user
from .models import AssessmentRun, WeeklyFocus, WeeklyFocusKR
from .programme_timeline import coaching_start_date, week_anchor_date, week_no_for_date


def resolve_programme_start_date(session: Session, user_id: int) -> date | None:
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
            return base_dt.date()
    earliest = (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.asc(), WeeklyFocus.id.asc())
        .first()
    )
    if earliest and getattr(earliest, "starts_on", None):
        try:
            return earliest.starts_on.date()
        except Exception:
            return None
    return None


def _clean_kr_ids(kr_ids: list[int] | None) -> list[int]:
    if not kr_ids:
        return []
    out: list[int] = []
    seen: set[int] = set()
    for raw in kr_ids:
        try:
            kr_id = int(raw)
        except Exception:
            continue
        if kr_id <= 0 or kr_id in seen:
            continue
        seen.add(kr_id)
        out.append(kr_id)
    return out


def _week_window(programme_start: date | None, week_no: int, reference_day: date) -> tuple[date, date]:
    anchor = week_anchor_date(programme_start, default_today=reference_day)
    start_day = anchor + timedelta(days=7 * (week_no - 1))
    end_day = start_day + timedelta(days=6)
    if week_no == 1:
        bridge_start = coaching_start_date(programme_start) or reference_day
        if bridge_start < start_day:
            start_day = bridge_start
        bridge_end = anchor + timedelta(days=6)
        if bridge_end > end_day:
            end_day = bridge_end
    return start_day, end_day


def ensure_weekly_plan(
    session: Session,
    user_id: int,
    *,
    week_no: Optional[int] = None,
    reference_day: Optional[date] = None,
    notes: str | None = None,
    preferred_kr_ids: list[int] | None = None,
    force_refresh_kr_links: bool = False,
    max_krs: int = 3,
) -> tuple[WeeklyFocus | None, list[int]]:
    """
    Create/update weekly plan row (WeeklyFocus + WeeklyFocusKR links) in one place.
    Used by coaching-start seed, Sunday next-week setup, and Monday weekstart.
    """
    ref_day = reference_day or datetime.utcnow().date()
    programme_start = resolve_programme_start_date(session, user_id)
    if week_no is None:
        try:
            week_i = max(1, int(week_no_for_date(programme_start, ref_day)))
        except Exception:
            week_i = 1
    else:
        try:
            week_i = max(1, int(week_no))
        except Exception:
            week_i = 1

    start_day, end_day = _week_window(programme_start, week_i, ref_day)
    start_dt = datetime.combine(start_day, datetime.min.time())
    end_dt = datetime.combine(end_day, datetime.max.time())

    wf = (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id, WeeklyFocus.week_no == week_i)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )
    if not wf:
        wf = WeeklyFocus(
            user_id=user_id,
            starts_on=start_dt,
            ends_on=end_dt,
            week_no=week_i,
            notes=notes,
        )
        session.add(wf)
        session.flush()
    else:
        if getattr(wf, "starts_on", None) != start_dt:
            wf.starts_on = start_dt
        if getattr(wf, "ends_on", None) != end_dt:
            wf.ends_on = end_dt
        if getattr(wf, "week_no", None) != week_i:
            wf.week_no = week_i
        if notes:
            wf.notes = notes
        session.add(wf)
        session.flush()

    existing_rows = (
        session.query(WeeklyFocusKR)
        .filter(WeeklyFocusKR.weekly_focus_id == wf.id)
        .order_by(WeeklyFocusKR.priority_order.asc(), WeeklyFocusKR.id.asc())
        .all()
    )
    existing_kr_ids = [int(row.kr_id) for row in existing_rows if getattr(row, "kr_id", None)]
    preferred_clean = _clean_kr_ids(preferred_kr_ids)

    should_replace_links = bool(preferred_kr_ids is not None or force_refresh_kr_links or not existing_kr_ids)
    if preferred_kr_ids is not None:
        kr_ids = preferred_clean
    elif existing_kr_ids and not force_refresh_kr_links:
        kr_ids = existing_kr_ids
    else:
        selected = select_top_krs_for_user(session, user_id, limit=max_krs, week_no=week_i)
        kr_ids = _clean_kr_ids([kr_id for kr_id, _ in (selected or [])])

    if should_replace_links:
        session.query(WeeklyFocusKR).filter(WeeklyFocusKR.weekly_focus_id == wf.id).delete(synchronize_session=False)
        for idx, kr_id in enumerate(kr_ids):
            session.add(
                WeeklyFocusKR(
                    weekly_focus_id=wf.id,
                    kr_id=kr_id,
                    priority_order=idx,
                    role="primary" if idx == 0 else "secondary",
                )
            )
        session.flush()

    return wf, kr_ids
