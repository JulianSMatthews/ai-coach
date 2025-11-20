# app/message_log.py
# Canonical message logger — SINGLE SOURCE OF TRUTH.
# All modules must import and call write_log from here.

from typing import Optional

__all__ = ["write_log"]

def _console_echo(phone_e164: Optional[str], direction: Optional[str], text: Optional[str]) -> None:
    """
    Print a console echo for any message written to MessageLog.
    Format: [OUTBOUND] Julian #1 (+4477...) → first 120 chars
    """
    # Local imports to avoid circular deps
    try:
        from .db import SessionLocal  # type: ignore
        from .models import User as _User  # type: ignore
    except Exception:
        SessionLocal = None
        _User = None
    phone = (phone_e164 or "").strip()
    label = "Unknown"
    if SessionLocal and _User and phone:
        try:
            with SessionLocal() as _s:
                u = _s.query(_User).filter(_User.phone == phone).first()
                if u:
                    label = f"{getattr(u, 'name', 'User')} #{getattr(u, 'id', '?')}"
        except Exception:
            pass
    preview = (text or "")[:120]
    dir_up = (direction or "").upper()
    phone_disp = phone if phone else "n/a"
    try:
        print(f"[{dir_up}] {label} ({phone_disp}) → {preview}")
    except Exception:
        # Never let console echo break the write path
        pass

def write_log(*args, **kwargs) -> None:
    """
    Accepts either:
      LEGACY (most common in this codebase):
        write_log(phone_e164: str, direction: str, text: str,
                  category: Optional[str] = None, twilio_sid: Optional[str] = None,
                  user: Optional[User] = None)
      MODERN (supported for compatibility):
        write_log(user_id: Optional[int] = None, user_name: Optional[str] = None,
                  direction: str = "", channel: Optional[str] = None,
                  text: Optional[str] = None, body: Optional[str] = None,
                  meta: Optional[dict] = None, user: object | None = None)
    Normalizes to a single DB write.
    """
    # Local imports to avoid circular deps
    from .db import SessionLocal
    from .models import MessageLog, User as _User

    # 1) Normalize inputs
    phone_e164 = None
    direction  = None
    text       = None
    category   = None
    twilio_sid = None
    user_obj   = None

    if args and isinstance(args[0], str):
        # Legacy positional pattern
        phone_e164 = args[0] if len(args) > 0 else None
        direction  = args[1] if len(args) > 1 else kwargs.get("direction")
        text       = args[2] if len(args) > 2 else kwargs.get("text")
        category   = args[3] if len(args) > 3 else kwargs.get("category")
        twilio_sid = args[4] if len(args) > 4 else kwargs.get("twilio_sid")
        user_obj   = args[5] if len(args) > 5 else kwargs.get("user")
    else:
        # Keyword paths
        if "phone_e164" in kwargs:
            # Legacy kw form
            phone_e164 = kwargs.get("phone_e164")
            direction  = kwargs.get("direction")
            text       = kwargs.get("text")
            category   = kwargs.get("category")
            twilio_sid = kwargs.get("twilio_sid")
            user_obj   = kwargs.get("user")
        else:
            # Modern form with meta/body
            direction = kwargs.get("direction")
            text = kwargs.get("text")
            if text is None:
                text = kwargs.get("body")
            meta = kwargs.get("meta") or {}
            phone_e164 = meta.get("phone_e164") or meta.get("to", "").replace("whatsapp:", "")
            twilio_sid = meta.get("twilio_sid")
            category   = meta.get("category")
            user_obj   = kwargs.get("user")

            # Resolve user if user_id provided
            if user_obj is None and kwargs.get("user_id") is not None:
                try:
                    with SessionLocal() as s:
                        user_obj = s.get(_User, kwargs.get("user_id"))
                except Exception:
                    user_obj = None

    # 2) Best-effort user resolution if not provided
    if user_obj is None and phone_e164:
        try:
            with SessionLocal() as s:
                user_obj = s.query(_User).filter(_User.phone == phone_e164).first()
        except Exception:
            user_obj = None

    # 4) Persist (never raise)
    try:
        with SessionLocal() as s:
            row = MessageLog(
                user_id=getattr(user_obj, "id", None),
                direction=direction,
                # If your MessageLog has these columns, keep them; else remove.
                channel=kwargs.get("channel") or ("whatsapp" if category else None),
                phone=phone_e164 if hasattr(MessageLog, "phone") else None,
                user_name=getattr(user_obj, "name", None) if hasattr(MessageLog, "user_name") else None,
                text=text if hasattr(MessageLog, "text") else None,
                meta=kwargs.get("meta") if hasattr(MessageLog, "meta") else None,
            )
            s.add(row)
            s.commit()
            _console_echo(phone_e164, direction, text)
    except Exception as e:
        try:
            s.rollback()
        except Exception:
            pass
        print(f"[WARN] write_log failed (non-fatal): {e!r}")
