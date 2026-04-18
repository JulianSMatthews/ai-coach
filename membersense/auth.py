from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import config
from .models import StaffUser


SESSION_COOKIE_NAME = "membersense_staff_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
PASSWORD_ITERATIONS = 180_000


def normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def staff_count(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(StaffUser)) or 0)


def active_staff_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(StaffUser)
            .where(StaffUser.is_active.is_(True))
        )
        or 0
    )


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_ITERATIONS,
    )
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt}${encoded}"


def verify_password(password: str, stored_hash: str | None) -> bool:
    parts = str(stored_hash or "").split("$")
    if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
        return False
    try:
        iterations = int(parts[1])
    except Exception:
        return False
    salt = parts[2]
    expected = parts[3]
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return hmac.compare_digest(encoded, expected)


def create_staff_user(
    session: Session,
    *,
    email: str,
    name: str,
    password: str,
    role: str = "staff",
    is_active: bool = True,
) -> StaffUser:
    normalized_email = normalize_email(email)
    display_name = str(name or "").strip() or normalized_email
    password_text = str(password or "")
    role_key = str(role or "staff").strip().lower()
    if role_key not in {"owner", "admin", "staff"}:
        role_key = "staff"
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("Enter a valid staff email address.")
    if len(password_text) < 8:
        raise ValueError("Password must be at least 8 characters.")
    existing = session.execute(select(StaffUser).where(StaffUser.email == normalized_email)).scalar_one_or_none()
    if existing is not None:
        raise ValueError("A staff account already exists for that email.")
    row = StaffUser(
        email=normalized_email,
        name=display_name,
        password_hash=hash_password(password_text),
        role=role_key,
        is_active=bool(is_active),
    )
    session.add(row)
    session.flush()
    return row


def authenticate_staff(session: Session, email: str, password: str) -> StaffUser | None:
    row = session.execute(select(StaffUser).where(StaffUser.email == normalize_email(email))).scalar_one_or_none()
    if row is None or not bool(getattr(row, "is_active", False)):
        return None
    if not verify_password(password, getattr(row, "password_hash", None)):
        return None
    row.last_login_at = datetime.utcnow().replace(microsecond=0)
    session.add(row)
    session.flush()
    return row


def _session_secret() -> bytes:
    value = str(getattr(config, "SESSION_SECRET", "") or "").strip()
    if not value:
        value = "membersense-local-dev-secret-change-me"
    return value.encode("utf-8")


def _sign_session_payload(payload: str) -> str:
    return hmac.new(_session_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _encode_session(raw: str) -> str:
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_session(value: str) -> str:
    padded = str(value or "") + "=" * (-len(str(value or "")) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")


def make_session_cookie(staff: StaffUser) -> str:
    expires = int(time.time()) + SESSION_MAX_AGE_SECONDS
    payload = f"{int(staff.id)}:{expires}:{secrets.token_urlsafe(12)}"
    signature = _sign_session_payload(payload)
    return _encode_session(f"{payload}:{signature}")


def staff_from_request(request: Request, session: Session) -> StaffUser | None:
    cookie_value = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie_value:
        return None
    try:
        raw = _decode_session(cookie_value)
        staff_id, expires_raw, nonce, signature = raw.split(":", 3)
        payload = f"{staff_id}:{expires_raw}:{nonce}"
        if not hmac.compare_digest(signature, _sign_session_payload(payload)):
            return None
        if int(expires_raw) < int(time.time()):
            return None
        row = session.get(StaffUser, int(staff_id))
    except Exception:
        return None
    if row is None or not bool(getattr(row, "is_active", False)):
        return None
    return row


def set_staff_cookie(response: RedirectResponse, staff: StaffUser) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        make_session_cookie(staff),
        max_age=SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=bool(getattr(config, "SESSION_COOKIE_SECURE", False)),
        samesite="lax",
    )


def clear_staff_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME)


def safe_next_path(value: Any, fallback: str = "/admin") -> str:
    path = str(value or "").strip()
    if not path.startswith("/") or path.startswith("//"):
        return fallback
    if path.startswith("/admin/login") or path.startswith("/admin/setup"):
        return fallback
    return path
