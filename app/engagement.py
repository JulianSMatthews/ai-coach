"""Calendar-day app engagement, consistently measured in Europe/London."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections.abc import Iterable


UK_TZ = ZoneInfo("Europe/London")


def build_engagement_summary(timestamps: Iterable[datetime | None], *, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    today = now.astimezone(UK_TZ).date()
    instants = []
    for timestamp in timestamps:
        if timestamp is None:
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        if timestamp <= now:
            instants.append(timestamp)
    days = sorted({timestamp.astimezone(UK_TZ).date() for timestamp in instants})
    day_set = set(days)
    # Today's absence does not break yesterday's streak until today has ended.
    cursor = today if today in day_set else today - timedelta(days=1)
    current = 0
    while cursor in day_set:
        current += 1
        cursor -= timedelta(days=1)
    best = running = 0
    previous = None
    for day in days:
        running = running + 1 if previous is not None and day == previous + timedelta(days=1) else 1
        best = max(best, running)
        previous = day
    return {
        "interaction_days_count": len(days),
        "current_streak_days": current,
        "best_streak_days": best,
        "active_dates": [day.isoformat() for day in days],
        "active_today": today in day_set,
        "today": today.isoformat(),
        "latest_interaction_at": max(instants).astimezone(UK_TZ).isoformat() if instants else None,
    }
