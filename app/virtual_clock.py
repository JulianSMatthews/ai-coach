from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from .db import SessionLocal
from .models import UserPreference

VIRTUAL_ENABLED_KEY = "coaching_virtual_enabled"
VIRTUAL_DATE_KEY = "coaching_virtual_date"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _pref(session: Session, user_id: int, key: str) -> Optional[UserPreference]:
    return (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == key)
        .order_by(UserPreference.updated_at.desc())
        .first()
    )


def _set_pref(session: Session, user_id: int, key: str, value: str) -> None:
    row = _pref(session, user_id, key)
    if row:
        row.value = value
        session.add(row)
        return
    session.add(UserPreference(user_id=user_id, key=key, value=value))


def _delete_pref(session: Session, user_id: int, key: str) -> None:
    row = _pref(session, user_id, key)
    if row:
        session.delete(row)


def _parse_iso_date(value: object) -> Optional[date]:
    if value is None:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except Exception:
        return None


def is_virtual_enabled(session: Session, user_id: int) -> bool:
    row = _pref(session, user_id, VIRTUAL_ENABLED_KEY)
    if not row or row.value is None:
        return False
    return str(row.value).strip().lower() in _TRUE_VALUES


def get_virtual_date(session: Session, user_id: int) -> Optional[date]:
    if not is_virtual_enabled(session, user_id):
        return None
    row = _pref(session, user_id, VIRTUAL_DATE_KEY)
    if not row:
        return None
    return _parse_iso_date(row.value)


def get_effective_today(session: Session, user_id: int, default_today: Optional[date] = None) -> date:
    return get_virtual_date(session, user_id) or default_today or datetime.utcnow().date()


def set_virtual_mode(
    session: Session,
    user_id: int,
    *,
    enabled: bool,
    start_date: Optional[date] = None,
    keep_existing_date: bool = True,
) -> Optional[date]:
    if not enabled:
        _set_pref(session, user_id, VIRTUAL_ENABLED_KEY, "0")
        _delete_pref(session, user_id, VIRTUAL_DATE_KEY)
        return None
    _set_pref(session, user_id, VIRTUAL_ENABLED_KEY, "1")
    existing = get_virtual_date(session, user_id) if keep_existing_date else None
    chosen = existing or start_date or datetime.utcnow().date()
    _set_pref(session, user_id, VIRTUAL_DATE_KEY, chosen.isoformat())
    return chosen


def advance_virtual_date(session: Session, user_id: int, days: int = 1) -> Optional[date]:
    if not is_virtual_enabled(session, user_id):
        return None
    step = max(1, int(days))
    current = get_virtual_date(session, user_id) or datetime.utcnow().date()
    next_date = current + timedelta(days=step)
    _set_pref(session, user_id, VIRTUAL_DATE_KEY, next_date.isoformat())
    return next_date


def get_virtual_now(session: Session, user_id: int) -> Optional[datetime]:
    vdate = get_virtual_date(session, user_id)
    if not vdate:
        return None
    now = datetime.utcnow()
    return datetime(
        vdate.year,
        vdate.month,
        vdate.day,
        now.hour,
        now.minute,
        now.second,
        now.microsecond,
    )


def advance_virtual_date_for_user(user_id: int, days: int = 1) -> Optional[date]:
    with SessionLocal() as s:
        next_date = advance_virtual_date(s, user_id, days=days)
        s.commit()
        return next_date


def get_virtual_now_for_user(user_id: int) -> Optional[datetime]:
    with SessionLocal() as s:
        return get_virtual_now(s, user_id)
