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
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import config
from .models import StaffUser


SESSION_COOKIE_NAME = "membersense_staff_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
PASSWORD_ITERATIONS = 180_000
STAFF_ROLE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("member_advisor", "Member Advisor"),
    ("assistant_manager", "Assistant Manager"),
    ("club_manager", "Club Manager"),
    ("staff", "Staff"),
    ("admin", "Admin"),
    ("owner", "Owner"),
)
STAFF_ROLE_KEYS = {key for key, _label in STAFF_ROLE_OPTIONS}


def normalize_email(value: str | None) -> str:
    return str(value or "").strip().lower()


def normalize_username(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    return "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-", "."})


def default_staff_email(username: str) -> str:
    key = normalize_username(username)
    return f"{key or 'staff'}@membersense.local"


def normalize_staff_role(value: str | None, fallback: str = "member_advisor") -> str:
    token = "_".join(str(value or "").strip().lower().replace("-", " ").split())
    if token in STAFF_ROLE_KEYS:
        return token
    if token in {"memberadvisor", "membership_advisor"}:
        return "member_advisor"
    if token in {"assistantmanager", "assistant"}:
        return "assistant_manager"
    if token in {"clubmanager", "manager"}:
        return "club_manager"
    return fallback if fallback in STAFF_ROLE_KEYS else "member_advisor"


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
    email: str | None = None,
    username: str | None = None,
    mobile: str | None = None,
    name: str,
    password: str,
    role: str = "staff",
    is_active: bool = True,
) -> StaffUser:
    normalized_username = normalize_username(username)
    normalized_email = normalize_email(email) or default_staff_email(normalized_username)
    display_name = str(name or "").strip() or normalized_username or normalized_email
    mobile_text = str(mobile or "").strip()
    password_text = str(password or "")
    role_key = normalize_staff_role(role, fallback="staff")
    if username is not None and not normalized_username:
        raise ValueError("Enter a valid staff username.")
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("Enter a valid staff email address.")
    if len(password_text) < 8:
        raise ValueError("Password must be at least 8 characters.")
    duplicate_checks = [StaffUser.email == normalized_email]
    if normalized_username:
        duplicate_checks.append(StaffUser.username == normalized_username)
    existing = session.execute(select(StaffUser).where(or_(*duplicate_checks))).scalar_one_or_none()
    if existing is not None:
        raise ValueError("A staff account already exists for that username or email.")
    row = StaffUser(
        username=normalized_username or None,
        email=normalized_email,
        name=display_name,
        mobile=mobile_text or None,
        password_hash=hash_password(password_text),
        role=role_key,
        is_active=bool(is_active),
    )
    session.add(row)
    session.flush()
    return row


def update_staff_user(
    session: Session,
    staff: StaffUser,
    *,
    email: str | None = None,
    username: str | None = None,
    mobile: str | None = None,
    name: str,
    password: str | None = None,
    role: str = "member_advisor",
) -> StaffUser:
    normalized_username = normalize_username(username)
    normalized_email = normalize_email(email)
    display_name = str(name or "").strip()
    mobile_text = str(mobile or "").strip()
    password_text = str(password or "")
    if username and not normalized_username:
        raise ValueError("Enter a valid staff username.")
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("Enter a valid staff email address.")
    if not display_name:
        raise ValueError("Enter a staff name.")
    if password_text and len(password_text) < 8:
        raise ValueError("Password must be at least 8 characters.")
    duplicate_checks = [StaffUser.email == normalized_email]
    if normalized_username:
        duplicate_checks.append(StaffUser.username == normalized_username)
    existing = (
        session.execute(
            select(StaffUser).where(or_(*duplicate_checks), StaffUser.id != int(staff.id))
        )
        .scalars()
        .first()
    )
    if existing is not None:
        raise ValueError("A staff account already exists for that username or email.")
    staff.username = normalized_username or None
    staff.email = normalized_email
    staff.name = display_name
    staff.mobile = mobile_text or None
    staff.role = normalize_staff_role(role, fallback=getattr(staff, "role", "member_advisor"))
    if password_text:
        staff.password_hash = hash_password(password_text)
    session.add(staff)
    session.flush()
    return staff


def authenticate_staff(session: Session, login: str, password: str) -> StaffUser | None:
    normalized_email = normalize_email(login)
    normalized_username = normalize_username(login)
    checks = [StaffUser.email == normalized_email]
    if normalized_username:
        checks.append(StaffUser.username == normalized_username)
    row = session.execute(select(StaffUser).where(or_(*checks))).scalar_one_or_none()
    if row is None or not bool(getattr(row, "is_active", False)):
        return None
    if not verify_password(password, getattr(row, "password_hash", None)):
        return None
    row.last_login_at = datetime.utcnow().replace(microsecond=0)
    session.add(row)
    session.flush()
    return row


def bootstrap_staff_user(session: Session) -> StaffUser | None:
    username = normalize_username(getattr(config, "BOOTSTRAP_STAFF_USERNAME", ""))
    password = str(getattr(config, "BOOTSTRAP_STAFF_PASSWORD", "") or "")
    if not username or not password:
        return None
    email = normalize_email(getattr(config, "BOOTSTRAP_STAFF_EMAIL", "")) or default_staff_email(username)
    existing = (
        session.execute(
            select(StaffUser).where(or_(StaffUser.username == username, StaffUser.email == email))
        )
        .scalars()
        .first()
    )
    if existing is not None:
        return existing
    row = create_staff_user(
        session,
        username=username,
        email=email,
        name=str(getattr(config, "BOOTSTRAP_STAFF_NAME", "") or username).strip(),
        password=password,
        role="owner",
        is_active=True,
    )
    session.commit()
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
