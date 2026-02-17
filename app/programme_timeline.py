from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

PILLAR_SEQUENCE: list[tuple[str, str]] = [
    ("nutrition", "Nutrition"),
    ("recovery", "Recovery"),
    ("training", "Training"),
    ("resilience", "Resilience"),
]

BLOCK_WEEKS = 3
BLOCK_DAYS = BLOCK_WEEKS * 7


def to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value))
    except Exception:
        return None


def first_monday_on_or_after(day_value: date | datetime | None) -> date | None:
    base = to_date(day_value)
    if base is None:
        return None
    return base + timedelta(days=(0 - base.weekday()) % 7)


def first_monday_after(day_value: date | datetime | None) -> date | None:
    base = to_date(day_value)
    if base is None:
        return None
    delta = (7 - base.weekday()) % 7
    if delta == 0:
        delta = 7
    return base + timedelta(days=delta)


def coaching_start_date(start_value: date | datetime | None) -> date | None:
    """
    Coaching timeline starts the day after assessment completion.
    """
    start_day = to_date(start_value)
    if start_day is None:
        return None
    return start_day + timedelta(days=1)


def week_anchor_date(start_value: date | datetime | None, default_today: date | None = None) -> date:
    start_day = coaching_start_date(start_value)
    if start_day is not None:
        anchor = first_monday_after(start_day)
        if anchor is not None:
            return anchor
    base_today = default_today or datetime.utcnow().date()
    fallback = first_monday_after(base_today)
    return fallback or base_today


def week_no_for_date(start_value: date | datetime | None, current_value: date | datetime | None) -> int:
    current_day = to_date(current_value) or datetime.utcnow().date()
    current_week_start = current_day - timedelta(days=current_day.weekday())
    anchor = week_anchor_date(start_value, default_today=current_day)
    if current_week_start < anchor:
        return 1
    return max(1, int(((current_week_start - anchor).days // 7) + 1))


def week_no_for_focus_start(start_value: date | datetime | None, focus_start_value: date | datetime | None) -> int:
    focus_start = to_date(focus_start_value)
    if focus_start is None:
        return 1
    focus_week_start = focus_start - timedelta(days=focus_start.weekday())
    anchor = week_anchor_date(start_value, default_today=focus_start)
    if focus_week_start < anchor:
        return 1
    return max(1, int(((focus_week_start - anchor).days // 7) + 1))


def programme_blocks(start_value: date | datetime | None) -> list[dict[str, Any]]:
    start_day = coaching_start_date(start_value)
    if start_day is None:
        return []
    first_monday = first_monday_after(start_day) or start_day
    bridge_days = max(0, (first_monday - start_day).days)

    blocks: list[dict[str, Any]] = []
    prev_end: date | None = None
    for idx, (pillar_key, pillar_label) in enumerate(PILLAR_SEQUENCE):
        week_start = idx * BLOCK_WEEKS + 1
        week_end = week_start + BLOCK_WEEKS - 1
        if idx == 0:
            blk_start = start_day
            blk_end = first_monday + timedelta(days=BLOCK_DAYS - 1)
        else:
            blk_start = (prev_end or start_day) + timedelta(days=1)
            blk_end = blk_start + timedelta(days=BLOCK_DAYS - 1)
        prev_end = blk_end
        week_label = f"Weeks {week_start}-{week_end}"
        label = f"Bridge + {week_label}" if idx == 0 and bridge_days > 0 else week_label
        blocks.append(
            {
                "pillar_key": pillar_key,
                "pillar_label": pillar_label,
                "week_start": week_start,
                "week_end": week_end,
                "week_label": week_label,
                "label": label,
                "start": blk_start,
                "end": blk_end,
                "bridge_days": bridge_days if idx == 0 else 0,
            }
        )
    return blocks


def programme_block_map(start_value: date | datetime | None) -> dict[str, dict[str, Any]]:
    blocks = programme_blocks(start_value)
    return {str(block["pillar_key"]): block for block in blocks}


def programme_total_days(start_value: date | datetime | None) -> int:
    blocks = programme_blocks(start_value)
    if not blocks:
        return 0
    first_start = to_date(blocks[0].get("start"))
    last_end = to_date(blocks[-1].get("end"))
    if first_start is None or last_end is None:
        return 0
    return max(0, (last_end - first_start).days + 1)
