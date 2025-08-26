from __future__ import annotations

from typing import Optional
from datetime import datetime
from .db import SessionLocal
from .models import MessageLog, User


def _resolve_user(phone_e164: str) -> Optional[User]:
    """
    Look up a user by bare E.164 phone (without 'whatsapp:' prefix).
    """
    with SessionLocal() as s:
        return s.query(User).filter(User.phone == phone_e164).first()


def write_log(
    *,
    phone_e164: str,
    direction: str,         # 'inbound' | 'outbound'
    text: str,
    category: Optional[str] = None,
    twilio_sid: Optional[str] = None,
    user: Optional[User] = None,
) -> int:
    """
    Insert a row into MessageLog and return its id. If `user` not provided, we’ll
    try to resolve by phone. Only call this for real events (no suppressed sends).
    """
    user_obj = user or _resolve_user(phone_e164)
    with SessionLocal() as s:
        row = MessageLog(
            user_id=user_obj.id if user_obj else None,
            user_name=user_obj.name if user_obj else None,
            phone=phone_e164,
            direction=direction,
            category=category,
            text=text,
            twilio_sid=twilio_sid,
            created_at=datetime.utcnow(),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
        # Build and print log message
        log_str = f"[{row.direction.upper()}][{row.phone}] [{row.user_name}] {row.text}"
        print(log_str)


        return row.id


def last_log() -> Optional[dict]:
    """
    Return the most recently created MessageLog as a dict, or None.
    """
    with SessionLocal() as s:
        row = s.query(MessageLog).order_by(MessageLog.created_at.desc()).first()
        if not row:
            return None
        return {
            "id": row.id,
            "created_at": row.created_at.isoformat() + "Z",
            "user_id": row.user_id,
            "user_name": row.user_name,
            "phone": row.phone,
            "direction": row.direction,
            "category": row.category,
            "twilio_sid": row.twilio_sid,
            "text": row.text,
        }
