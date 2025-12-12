"""
Helpers to select and create weekly KR focus sets and touchpoints.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Tuple, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import (
    OKRKeyResult,
    OKRObjective,
    OKRCycle,
    WeeklyFocus,
    WeeklyFocusKR,
    Touchpoint,
    TouchpointKR,
)


def _urgency_multiplier(ends_on) -> float:
    if not ends_on:
        return 1.0
    now = datetime.utcnow()
    days_left = (ends_on - now).days
    if days_left <= 0:
        return 1.6
    # ramp up as we approach end of cycle; cap at 1.6
    return min(1.6, 1.0 + max(0.0, (60 - min(days_left, 60))) / 100.0)


def _status_bonus(status: str | None) -> float:
    st = (status or "").lower()
    if st == "off_track":
        return 1.3
    if st == "at_risk":
        return 1.15
    if st == "done":
        return 0.5
    return 1.0


def _gap_score(kr: OKRKeyResult) -> float:
    # Prefer target/actual if present; fall back to KR score
    try:
        if kr.target_num is not None and kr.actual_num is not None:
            denom = abs(kr.target_num) + 1e-6
            return min(2.0, abs(kr.target_num - kr.actual_num) / denom)
    except Exception:
        pass
    if kr.score is None:
        return 1.0
    return max(0.0, min(1.5, (100.0 - float(kr.score)) / 100.0))


def select_top_krs_for_user(session: Session, user_id: int, limit: int | None = 3, week_no: int | None = None) -> List[Tuple[int, str]]:
    """
    Returns a list of (kr_id, rationale) ordered by priority for the given user.
    """
    programme_order = ["nutrition", "recovery", "training", "resilience"]
    rows = (
        session.execute(
            select(OKRKeyResult, OKRObjective, OKRCycle)
            .join(OKRObjective, OKRKeyResult.objective_id == OKRObjective.id)
            .outerjoin(OKRCycle, OKRObjective.cycle_id == OKRCycle.id)
            .where(OKRObjective.owner_user_id == user_id)
            .where(OKRKeyResult.status == "active")
        )
        .all()
    )
    # Determine current 3-week block pillar (overrideable by week_no)
    if week_no and week_no > 0:
        block_idx = (week_no - 1) // 3
        start_dt = None
    else:
        cycle_starts = [getattr(cyc, "starts_on", None) for _, _, cyc in rows if getattr(cyc, "starts_on", None)]
        if cycle_starts:
            start_dt = max(cycle_starts)
        else:
            start_dt = datetime.utcnow()
        days_since_start = (datetime.utcnow().date() - start_dt.date()).days if start_dt else 0
        block_idx = max(0, days_since_start // 21)
    block_idx = min(block_idx, len(programme_order) - 1)
    focus_pillar = programme_order[block_idx]

    scored = []
    for kr, obj, cyc in rows:
        if (getattr(obj, "pillar_key", None) or "").lower() != focus_pillar:
            continue
        weight = kr.weight or 1.0
        urgency = _urgency_multiplier(getattr(cyc, "ends_on", None))
        gap = _gap_score(kr)
        status_adj = _status_bonus(getattr(kr, "status", None))
        score = weight * urgency * gap * status_adj
        rationale = []
        if getattr(cyc, "ends_on", None):
            days_left = (getattr(cyc, "ends_on") - datetime.utcnow()).days
            rationale.append(f"cycle ends in {days_left}d")
        rationale.append(f"gap={gap:.2f}")
        rationale.append(f"weight={weight:g}")
        if getattr(kr, "status", None):
            rationale.append(f"status={kr.status}")
        rationale.append(f"programme_focus={focus_pillar}")
        scored.append((kr.id, score, "; ".join(rationale)))
    # Fallback if no KRs match the focus pillar
    if not scored:
        for kr, obj, cyc in rows:
            weight = kr.weight or 1.0
            urgency = _urgency_multiplier(getattr(cyc, "ends_on", None))
            gap = _gap_score(kr)
            status_adj = _status_bonus(getattr(kr, "status", None))
            score = weight * urgency * gap * status_adj
            rationale = []
            if getattr(cyc, "ends_on", None):
                days_left = (getattr(cyc, "ends_on") - datetime.utcnow()).days
                rationale.append(f"cycle ends in {days_left}d")
            rationale.append(f"gap={gap:.2f}")
            rationale.append(f"weight={weight:g}")
            if getattr(kr, "status", None):
                rationale.append(f"status={kr.status}")
            scored.append((kr.id, score, "; ".join(rationale)))
    scored.sort(key=lambda x: x[1], reverse=True)
    if limit is not None:
        scored = scored[:limit]
    return [(kr_id, rationale) for kr_id, _, rationale in scored]


def create_weekly_focus_and_touchpoint(
    session: Session,
    user_id: int,
    tp_type: str,
    kr_ids: List[int],
    notes: str | None = None,
    starts_on: Optional[datetime] = None,
    ends_on: Optional[datetime] = None,
) -> tuple[WeeklyFocus, Touchpoint]:
    """
    Create WeeklyFocus(+KR) and Touchpoint(+KR) records. Caller must commit.
    """
    now = datetime.utcnow()
    if not starts_on or not ends_on:
        today = datetime.utcnow().date()
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        starts_on = datetime.combine(start, datetime.min.time())
        ends_on = datetime.combine(end, datetime.max.time())

    wf = WeeklyFocus(user_id=user_id, starts_on=starts_on, ends_on=ends_on, notes=notes, created_at=now)
    session.add(wf)
    session.flush()
    for idx, kr_id in enumerate(kr_ids):
        session.add(
            WeeklyFocusKR(
                weekly_focus_id=wf.id,
                kr_id=kr_id,
                priority_order=idx,
                role="primary" if idx == 0 else "secondary",
                rationale=notes,
            )
        )
    tp = Touchpoint(
        user_id=user_id,
        type=tp_type,
        weekly_focus_id=wf.id,
        status="planned",
        scheduled_at=now,
        meta={"created_by": "focus_helper", "kr_ids": kr_ids},
    )
    session.add(tp)
    session.flush()
    for idx, kr_id in enumerate(kr_ids):
        session.add(
            TouchpointKR(
                touchpoint_id=tp.id,
                kr_id=kr_id,
                priority_order=idx,
                role="primary" if idx == 0 else "secondary",
                ask_text=None,
            )
        )
    return wf, tp
