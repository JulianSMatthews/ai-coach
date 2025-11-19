# app/api.py
# PATCH — proper API module + robust Twilio webhook (2025-09-04)
# PATCH — 2025-09-11: Add minimal superuser admin endpoints (create user, start, status, dashboard)
# PATCH — 2025-09-11: Admin hardening + WhatsApp admin commands (token+DB check; create/start/status/dashboard)

import os
import json
import time
import urllib.request
from urllib.parse import parse_qs
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import FastAPI, APIRouter, Request, Response, Depends, Header, HTTPException, status
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text, select, desc, func, or_
from pathlib import Path 

from .db import engine, SessionLocal
from .models import (
    Base,
    User,
    MessageLog,
    AssessSession,
    AssessmentRun,
    Club,
    ADMIN_ROLE_MEMBER,
    ADMIN_ROLE_CLUB,
    ADMIN_ROLE_GLOBAL,
)  # ensure model registered for metadata
from .nudges import send_whatsapp
from .reporting import (
    generate_detailed_report_pdf_by_user,
    generate_assessment_summary_pdf,
    generate_assessment_report_pdf,
    generate_assessment_dashboard_html,
    generate_global_users_html,
)

# Lazy import holder to avoid startup/reload ImportError if symbol is added later
_gen_okr_summary_report = None
try:
    from .reporting import generate_okr_summary_report as _gen_okr_summary_report  # type: ignore
except Exception:
    _gen_okr_summary_report = None

# Utility to robustly resolve the OKR summary generator, with diagnostics
def _resolve_okr_summary_gen():
    """Return callable generate_okr_summary_report or raise with useful diagnostics."""
    global _gen_okr_summary_report
    if _gen_okr_summary_report is not None:
        return _gen_okr_summary_report
    try:
        from . import reporting as _r
    except Exception as e:
        raise ImportError(f"Failed to import app.reporting: {e}")
    gen = getattr(_r, "generate_okr_summary_report", None)
    if callable(gen):
        _gen_okr_summary_report = gen
        return gen
    # Provide clear diagnostics of what's actually available
    okrish = [a for a in dir(_r) if "okr" in a.lower()]
    raise ImportError(
        "generate_okr_summary_report not found in app.reporting; "
        f"available attrs containing 'okr': {okrish}"
    )

ADMIN_USAGE = (
    "Admin commands:\n"
    "admin create <phone> <first_name> <surname>\n"
    "admin start <phone>\n"
    "admin status <phone>\n"
    "admin dashboard <phone>\n"
    "admin progress <phone>\n"
    "admin detailed <phone>\n"
    "admin summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "admin okr-summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "admin okr-summaryllm [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "admin users\n"
    "\nExample: admin create +447700900123 Julian Matthews"
)

GLOBAL_USAGE = (
    "Global admin commands:\n"
    "global set club <club_id|slug>\n"
    "global set user <phone> <club_id|slug>\n"
    "global summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "global okr-summary [range]\n"
    "global okr-summaryllm [range]\n"
    "global users\n"
    "\nExample: global summary last30d"
)


ENV = os.getenv("ENV", "development").lower()

# Application start time (UK)
UK_TZ = ZoneInfo("Europe/London")
APP_START_DT = datetime.now(UK_TZ)
# Format: dd/mm/yy␠HH:MM:SS (UK local time)
APP_START_UK_STR = APP_START_DT.strftime("%d/%m/%y %H:%M:%S")

def _uptime_seconds() -> int:
    try:
        from datetime import timezone as _tz, datetime as _dt
        return int((_dt.now(_tz.utc) - APP_START_DT).total_seconds())
    except Exception:
        return 0

# ──────────────────────────────────────────────────────────────────────────────
# Environment awareness (simple version)
# ──────────────────────────────────────────────────────────────────────────────
def _print_env_banner():
    try:
        print("\n" + "═" * 72)
        print(f"🚀 Starting HealthSense [{ENV.upper()}]")
        print(f"🕒 App start (UK): {APP_START_UK_STR}")
        print("═" * 72 + "\n")
    except Exception:
        pass

print(f"🚀 app.api loaded: v-2025-09-04E (ENV={ENV})")

# Seed import 
from .seed import run_seed  # fallback

# Assessor entrypoints

def _dbg(msg: str):
    try:
        print(f"[webhook] {msg}")
    except Exception:
        pass

try:
    from .assessor import (
        start_combined_assessment,
        continue_combined_assessment,
        get_active_domain,
        send_menu_options,
        send_dashboard_link,
    )
    _dbg("[INFO] Correct assessor module imported successfully (module path: " +
         f"{start_combined_assessment.__module__})")
except Exception as e:
    _dbg(f"[ERROR] Failed to import assessors — using fallback: {e}")
    raise  # Let it crash loud during startup so you catch it immediately

app = FastAPI(title="AI Coach")
router = APIRouter()


# ──────────────────────────────────────────────────────────────────────────────
# Startup helpers
# ──────────────────────────────────────────────────────────────────────────────

def _predrop_legacy_tables():
    """Drop legacy tables (if any) that can block drop_all() via FKs."""
    legacy_tables = [
        "review_feedback",      # legacy; FK -> assessment_runs, blocks drop_all
        "concept_deltas",
        "concept_rubrics",
        "concept_clarifiers",
    ]
    with engine.begin() as conn:
        for tbl in legacy_tables:
            try:
                conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))
            except Exception as e:
                print(f"⚠️  Pre-drop warning for {tbl}: {e}")


@app.on_event("startup")
def on_startup():
    if os.getenv("RESET_DB_ON_STARTUP") == "1":
        try:
            _predrop_legacy_tables()
        except Exception as e:
            print(f"⚠️  Legacy table pre-drop error: {e}")

        # Recreate schema
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

        # Seed
        run_seed()

        # Ensure reports dir exists even when not resetting DB
        try:
            reports_dir = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
            os.makedirs(reports_dir, exist_ok=True)
        except Exception as e:
            print(f"⚠️  Could not create reports dir: {e!r}")
    _maybe_set_public_base_via_ngrok()
    _print_env_banner()

def _maybe_set_public_base_via_ngrok() -> None:
    """
    If PUBLIC_BASE_URL is not set, try to detect an https ngrok tunnel from the
    local ngrok API (http://127.0.0.1:4040/api/tunnels) and set it.
    Result is a host like 'xxxx.ngrok-free.app' (no scheme), matching how links are built.
    Safe no-op on failure.
    """
    if os.getenv("PUBLIC_BASE_URL"):
        return
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1.5) as resp:
            data = json.load(resp)
        tunnels = (data or {}).get("tunnels", []) or []
        https = next((t for t in tunnels if str(t.get("public_url","")).startswith("https://")), None)
        target = https or (tunnels[0] if tunnels else None)
        if not target:
            return
        pub = str(target.get("public_url","")).strip()
        if pub.startswith("https://"):
            host = pub.replace("https://", "")
        elif pub.startswith("http://"):
            host = pub.replace("http://", "")
        else:
            host = pub
        if host:
            os.environ["PUBLIC_BASE_URL"] = host
            print(f"🌐 PUBLIC_BASE_URL auto-detected via ngrok: {host}")
    except Exception as e:
        print(f"⚠️  ngrok auto-detect failed: {e!r}")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

# Name display/split helpers (no legacy 'name' fallback)
def display_full_name(u: "User") -> str:
    """
    Prefer first_name + surname; fall back to phone only (no legacy name).
    """
    try:
        first = (getattr(u, "first_name", None) or "").strip()
        last = (getattr(u, "surname", None) or "").strip()
        if first or last:
            return f"{first} {last}".strip()
        return getattr(u, "phone", "") or ""
    except Exception:
        return getattr(u, "phone", "") or ""

def _split_name(maybe_name: str) -> tuple[str | None, str | None]:
    """
    Split a free-form name into (first_name, surname).
    - Empty/None -> (None, None)
    - One token -> (token, None)
    - Two+ tokens -> (first token, rest joined as surname)
    """
    if not maybe_name:
        return None, None
    cleaned = _strip_invisible(str(maybe_name)).strip()
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return None, None
    def _titlecase_chunk(chunk: str) -> str:
        return " ".join(word.capitalize() for word in chunk.split())
    if len(parts) == 1:
        return _titlecase_chunk(parts[0]), None
    first = _titlecase_chunk(parts[0])
    last = _titlecase_chunk(" ".join(parts[1:]))
    return first, last

def _require_name_fields(first: str | None, last: str | None) -> bool:
    return bool(first and first.strip()) and bool(last and last.strip())

_DEFAULT_CLUB_ID_CACHE: int | None = None
_FORMAT_CHAR_MAP = {
    ord(ch): None for ch in ("\u202a", "\u202c", "\u202d", "\u202e", "\ufeff", "\u200f", "\u200e")
}

def _strip_invisible(text: str | None) -> str:
    if not text:
        return ""
    return text.translate(_FORMAT_CHAR_MAP)

def _resolve_default_club_id(sess) -> int:
    """
    Resolve the default club id for newly created users. Order of precedence:
    1) DEFAULT_CLUB_ID env var
    2) CLUB_ID env var
    3) TEST_CLUB_ID env var
    4) First club row in the database
    Result is cached for the lifetime of the process.
    """
    global _DEFAULT_CLUB_ID_CACHE
    if _DEFAULT_CLUB_ID_CACHE is not None:
        return _DEFAULT_CLUB_ID_CACHE
    for var in ("DEFAULT_CLUB_ID", "CLUB_ID", "TEST_CLUB_ID"):
        raw = (os.getenv(var) or "").strip()
        if raw.isdigit():
            _DEFAULT_CLUB_ID_CACHE = int(raw)
            return _DEFAULT_CLUB_ID_CACHE
    club = (
        sess.query(Club)
            .order_by(Club.id.asc())
            .first()
    )
    if not club:
        raise RuntimeError("No clubs available to assign new users; seed clubs first.")
    _DEFAULT_CLUB_ID_CACHE = getattr(club, "id", None)
    if _DEFAULT_CLUB_ID_CACHE is None:
        raise RuntimeError("Failed to resolve default club id (club row missing id).")
    return _DEFAULT_CLUB_ID_CACHE


def _club_label(club: Club | None) -> str:
    if not club:
        return "unknown club"
    for attr in ("name", "slug"):
        val = getattr(club, attr, None)
        if val:
            return str(val)
    return f"club #{getattr(club, 'id', None)}"


def _find_club_by_identifier(sess, identifier: str) -> Club | None:
    token = (identifier or "").strip()
    if not token:
        return None
    if token.isdigit():
        return (
            sess.query(Club)
               .filter(Club.id == int(token))
               .one_or_none()
        )
    lowered = token.lower()
    return (
        sess.query(Club)
           .filter(
               or_(
                   func.lower(Club.slug) == lowered,
                   func.lower(Club.name) == lowered,
               )
           )
           .one_or_none()
    )


def _get_or_create_user(phone_e164: str) -> User:
    """Find or create a User record by E.164 phone (no whatsapp: prefix)."""
    phone_e164 = _norm_phone(phone_e164)
    with SessionLocal() as s:
        u = s.query(User).filter(User.phone == phone_e164).first()
        if not u:
            club_id = _resolve_default_club_id(s)
            now = datetime.utcnow()
            u = User(first_name=None, surname=None, phone=phone_e164, club_id=club_id,
                     created_on=now, updated_on=now)
            s.add(u)
            s.commit()
            s.refresh(u)
        return u


def _log_inbound_direct(user: User, channel: str, body: str, from_raw: str) -> None:
    """All inbound logging routed through app.message_log.write_log (no direct DB writes)."""
    try:
        # Import here to avoid any circulars
        from .message_log import write_log

        phone = getattr(user, "phone", None) or (from_raw.replace("whatsapp:", "") if from_raw else None)


        # Canonical logging (category/sid omitted for inbound unless you have them)
        write_log(
            phone_e164=phone,
            direction="inbound",
            text=body or "",
            category=None,
            twilio_sid=None,
            user=user,
            channel=channel,  # harmless if model lacks 'channel'
            meta={"from": from_raw}  # harmless if model lacks 'meta'
        )
    except Exception as e:
        print(f"⚠️ inbound direct-log failed (non-fatal): {e!r}")


# ──────────────────────────────────────────────────────────────────────────────
# WhatsApp Admin Command Helpers
# ──────────────────────────────────────────────────────────────────────────────


# Phone normalizer for admin commands
# PATCH — 2025-09-11: normalize local numbers using DEFAULT_COUNTRY_CODE (e.g., +44)
import re
_CC_RE = re.compile(r"^\+(\d{1,3})")

def _guess_default_cc() -> str:
    """
    Resolve default country code in priority order:
    1) DEFAULT_COUNTRY_CODE
    2) TWILIO_WHATSAPP_FROM (extract +CC)
    3) ADMIN_WHATSAPP / ADMIN_PHONE
    4) TWILIO_SMS_FROM
    5) Hard fallback '+44'
    """
    cand = (os.getenv("DEFAULT_COUNTRY_CODE") or "").strip()
    if cand.startswith("+"):
        return cand
    for var in ("TWILIO_WHATSAPP_FROM", "ADMIN_WHATSAPP", "ADMIN_PHONE", "TWILIO_SMS_FROM"):
        v = (os.getenv(var) or "").strip()
        if not v:
            continue
        v = v.replace("whatsapp:", "")
        m = _CC_RE.match(v)
        if m:
            return f"+{m.group(1)}"
    return "+44"

def _norm_phone(s: str) -> str:
    s = _strip_invisible(s).strip()
    if s.startswith("whatsapp:"):
        s = s[len("whatsapp:"):]
    # Remove common separators
    s = s.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    # Convert '00' international prefix to '+'
    if s.startswith("00") and len(s) > 2 and s[2:].isdigit():
        s = "+" + s[2:]
    # If already E.164, return
    if s.startswith("+"):
        return s
    # Determine default country code
    cc_env = (os.getenv("DEFAULT_COUNTRY_CODE") or "").strip()
    cc = cc_env if cc_env.startswith("+") else _guess_default_cc()
    # Accept pure digits after stripping separators
    if s.isdigit():
        # UK-style local numbers starting with 0 → drop trunk '0'
        if s.startswith("0"):
            return cc + s[1:]
        # No trunk '0' — still prefix with cc
        return cc + s
    return s


def _admin_lookup_user_by_phone(session, phone: str, admin_user: User) -> User | None:
    """
    Fetch a user for admin WhatsApp commands, restricting non-global admins to their club.
    Global admins (club_id=None) can target any club.
    """
    q = select(User).where(User.phone == phone)
    club_id = getattr(admin_user, "club_id", None)
    if club_id is not None:
        q = q.where(User.club_id == club_id)
    return session.execute(q).scalar_one_or_none()


def _user_admin_role(u: User) -> str:
    try:
        role = (getattr(u, "admin_role", None) or "").strip().lower()
        if role in {ADMIN_ROLE_MEMBER, ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}:
            return role
        # Backward compatibility: legacy superusers remain global admins
        if bool(getattr(u, "is_superuser", False)):
            return ADMIN_ROLE_GLOBAL
    except Exception as e:
        print(f"[admin] role lookup error: {e!r}")
    return ADMIN_ROLE_MEMBER


def _is_global_admin(u: User) -> bool:
    return _user_admin_role(u) == ADMIN_ROLE_GLOBAL


def _is_admin_user(u: User) -> bool:
    role = _user_admin_role(u)
    ok = role in {ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}
    try:
        print(
            "[admin] check user_id={uid} phone={phone} role={role} is_superuser={su} ok={ok}".format(
                uid=getattr(u, "id", None),
                phone=getattr(u, "phone", None),
                role=role,
                su=getattr(u, "is_superuser", None),
                ok=ok,
            )
        )
    except Exception:
        pass
    return ok

def _parse_summary_range(args: list[str]) -> tuple[str, str]:
    """
    Accepts tokens: today | last7d | last30d | thisweek | YYYY-MM-DD YYYY-MM-DD
    Returns (start_str, end_str) as ISO dates.
    """
    from datetime import date, timedelta
    today = date.today()
    if not args:
        # default to last7d inclusive
        start = today - timedelta(days=6)
        end = today
        return (start.isoformat(), end.isoformat())
    token = (args[0] or "").lower()
    if token == "today":
        return (today.isoformat(), today.isoformat())
    if token == "last7d":
        start = today - timedelta(days=6)
        return (start.isoformat(), today.isoformat())
    if token == "last30d":
        start = today - timedelta(days=29)
        return (start.isoformat(), today.isoformat())
    if token == "thisweek":
        # Monday..Sunday of current week
        weekday = today.weekday()  # Monday=0
        start = today - timedelta(days=weekday)
        end = start + timedelta(days=6)
        return (start.isoformat(), end.isoformat())
    if len(args) >= 2:
        # assume explicit dates
        a, b = args[0], args[1]
        # no validation here; reporting will raise if invalid
        return (a, b)
    # fallback
    start = today - timedelta(days=6)
    return (start.isoformat(), today.isoformat())


def _handle_admin_command(admin_user: User, text: str) -> bool:
    """
    Handle very small set of admin commands sent over WhatsApp by superusers (ids 1 & 2).
    Commands:
      admin create <phone> [<name...>]
      admin start <phone>
      admin status <phone>
      admin dashboard <phone>
      admin detailed <phone>
    Returns True if handled; False to allow normal flow.
    """
    msg = (text or "").strip()
    print(f"[admin] inbound cmd from {admin_user.id}/{admin_user.phone}: {msg}")
    if not msg.lower().startswith("admin"):
        return False
    parts = msg.split()
    # PATCH — 2025-09-11: Plain 'admin' or 'admin help/?' shows usage
    if len(parts) == 1 or (len(parts) >= 2 and parts[1].lower() in {"help", "?"}):
        send_whatsapp(to=admin_user.phone, text=ADMIN_USAGE)
        return True
    if len(parts) < 2:
        send_whatsapp(to=admin_user.phone, text=ADMIN_USAGE)
        return True
    cmd = parts[1].lower()
    args = parts[2:]
    admin_club_id = getattr(admin_user, "club_id", None)
    club_scope_id = admin_club_id
    try:
        if cmd in {"create", "start", "status", "report", "detailed", "summary", "okr-summary", "okr-summaryllm", "users"} and club_scope_id is None:
            send_whatsapp(
                to=admin_user.phone,
                text="Your admin profile is not linked to a club. Use 'admin set global <club>' first."
            )
            return True

        if cmd == "create":
            if len(parts) < 4:
                send_whatsapp(to=admin_user.phone, text="Usage: admin create <phone> <first_name> <surname>")
                return True
            # Parse phone which may be split across multiple tokens (e.g., "07808 951649")
            i = 2
            phone_tokens = []
            while i < len(parts):
                tok = parts[i]
                stripped = tok.replace("+", "").replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
                if stripped.isdigit():
                    phone_tokens.append(tok)
                    i += 1
                    continue
                break
            phone_raw = "".join(phone_tokens) if phone_tokens else parts[2]
            phone = _norm_phone(phone_raw)
            raw_name = _strip_invisible(" ".join(parts[i:])).strip() if i < len(parts) else ""
            first_name, surname = _split_name(raw_name)
            if not _require_name_fields(first_name, surname):
                send_whatsapp(to=admin_user.phone, text="Please provide both first and surname when creating a user.")
                return True
            with SessionLocal() as s:
                existing = s.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
                if existing:
                    send_whatsapp(to=admin_user.phone, text=f"User exists: id={existing.id}, phone={existing.phone}, name={display_full_name(existing)}")
                    return True
                now = datetime.utcnow()
                u = User(
                    first_name=first_name,
                    surname=surname,
                    phone=phone,
                    club_id=admin_club_id,
                    created_on=now,
                    updated_on=now,
                    consent_given=True,
                    consent_at=now,
                )
                if hasattr(u, "consent_yes_at"):
                    try:
                        setattr(u, "consent_yes_at", now)
                    except Exception:
                        pass
                s.add(u); s.commit(); s.refresh(u)
            # trigger consent/intro
            try:
                start_combined_assessment(u)
            except Exception as e:
                print(f"[wa admin create] start failed: {e!r}")
            send_whatsapp(to=admin_user.phone, text=f"Created user id={u.id} {display_full_name(u)} ({u.phone})")
            return True
        if cmd == "progress":
            if len(parts) < 3:
                send_whatsapp(to=admin_user.phone, text="Usage: admin progress <phone>")
                return True
            target_phone = _norm_phone(parts[2])
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                from .reporting import generate_progress_report_html
                generate_progress_report_html(u.id)
                url = _public_report_url(u.id, "progress.html")
                send_whatsapp(to=admin_user.phone, text=f"Progress report for {display_full_name(u)}: {url}")
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate progress report: {e}")
            return True
        elif cmd == "start":
            if len(parts) < 3:
                send_whatsapp(to=admin_user.phone, text="Usage: admin start <phone>")
                return True
            target_phone = _norm_phone(parts[2])
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            start_combined_assessment(u)
            send_whatsapp(to=admin_user.phone, text=f"Started assessment for {display_full_name(u)} ({u.phone})")
            return True
        elif cmd == "status":
            if len(parts) < 3:
                send_whatsapp(to=admin_user.phone, text="Usage: admin status <phone>")
                return True
            target_phone = _norm_phone(parts[2])
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
                active = get_active_domain(u)
                latest_run = s.execute(
                    select(AssessmentRun).where(AssessmentRun.user_id == u.id).order_by(desc(AssessmentRun.id))
                ).scalars().first()
            status_txt = "in_progress" if active else ("completed" if latest_run and getattr(latest_run, "finished_at", None) else "idle")
            send_whatsapp(to=admin_user.phone, text=f"Status for {display_full_name(u)} ({u.phone}): {status_txt}")
            return True
        elif cmd == "dashboard":
            if len(parts) < 3:
                send_whatsapp(to=admin_user.phone, text="Usage: admin dashboard <phone>")
                return True
            target_phone = _norm_phone(parts[2])
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
                latest_run = s.execute(
                    select(AssessmentRun).where(AssessmentRun.user_id == u.id).order_by(desc(AssessmentRun.id))
                ).scalars().first()
            if not latest_run:
                send_whatsapp(to=admin_user.phone, text=f"No assessment run found for {display_full_name(u)} ({u.phone}).")
                return True
            try:
                generate_assessment_dashboard_html(latest_run.id)
                dash_url = _public_report_url(u.id, "latest.html")
                bust = int(time.time())
                send_whatsapp(
                    to=admin_user.phone,
                    text=(
                        f"Dashboard refreshed for {display_full_name(u)} ({u.phone}) "
                        f"[run #{latest_run.id}]:\nLink: {dash_url}?ts={bust}"
                    )
                )
                return True
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to regenerate dashboard: {e}")
                return True
        elif cmd == "users":
            if club_scope_id is None:
                send_whatsapp(to=admin_user.phone, text="Set your club first via 'admin set global <club_id>'.")
                return True
            try:
                from .reporting import generate_club_users_html
                path = generate_club_users_html(club_scope_id)
                fname = os.path.basename(path)
                url = _public_report_url_global(fname)
                send_whatsapp(
                    to=admin_user.phone,
                    text=f"Club users report refreshed:\n{url}?ts={int(time.time())}"
                )
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate club users report: {e}")
            return True
        elif cmd == "detailed":
            if len(parts) < 3:
                send_whatsapp(to=admin_user.phone, text="Usage: admin detailed <phone|me>")
                return True
            arg = parts[2].lower()
            if arg in {"me", "my", "self"}:
                u = admin_user
            else:
                target_phone = _norm_phone(parts[2])
                with SessionLocal() as s:
                    u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                # Generate the detailed (grouped) PDF via reporting module
                _ = generate_detailed_report_pdf_by_user(u.id)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate detailed report: {e}")
                return True
            pdf = _public_report_url(u.id, "detailed.pdf")
            send_whatsapp(to=admin_user.phone, text=f"Detailed report for {display_full_name(u)} ({u.phone}):\nPDF: {pdf}")
            return True
        elif cmd == "summary":
            # Usage: admin summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]
            start_str, end_str = _parse_summary_range(args)
            try:
                pdf_path = generate_assessment_summary_pdf(start_str, end_str, club_id=club_scope_id)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate summary report: {e}")
                return True
            # Derive filename from path for public URL
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"Assessment summary {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
        elif cmd == "okr-summary":
            # Usage: admin okr-summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]
            # This variant EXCLUDES the llm prompt field
            start_str, end_str = _parse_summary_range(args)
            try:
                gen = _resolve_okr_summary_gen()
                # Ensure llm prompt field is NOT included for this command
                import os as _os
                _prev = _os.environ.get("OKR_SUMMARY_WITH_llm_PROMPT")
                _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = "0"
                pdf_path = gen(start_str, end_str, club_id=club_scope_id)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate OKR summary: {e}")
                return True
            finally:
                # Restore previous env
                try:
                    if _prev is None:
                        _os.environ.pop("OKR_SUMMARY_WITH_llm_PROMPT", None)
                    else:
                        _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = _prev
                except Exception:
                    pass
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"OKR summary (no llm prompt) {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
        elif cmd == "okr-summaryllm":
            # Usage: admin okr-summaryllm [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]
            # This variant INCLUDES the llm prompt field in the summary
            start_str, end_str = _parse_summary_range(args)
            try:
                gen = _resolve_okr_summary_gen()
                import os as _os
                _prev = _os.environ.get("OKR_SUMMARY_WITH_llm_PROMPT")
                _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = "1"
                pdf_path = gen(start_str, end_str, club_id=club_scope_id)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate OKR summary (with llm prompt): {e}")
                return True
            finally:
                try:
                    if _prev is None:
                        _os.environ.pop("OKR_SUMMARY_WITH_llm_PROMPT", None)
                    else:
                        _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = _prev
                except Exception:
                    pass
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"OKR summary (with llm prompt) {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
    except Exception as e:
        send_whatsapp(to=admin_user.phone, text=f"Admin error: {e}")
        return True
    # Unknown subcommand
    send_whatsapp(to=admin_user.phone, text="Unknown admin command. Try: create/start/status/report")
    return True


def _handle_global_command(admin_user: User, text: str) -> bool:
    msg = (text or "").strip()
    if not msg.lower().startswith("global"):
        return False
    if not _is_global_admin(admin_user):
        send_whatsapp(to=admin_user.phone, text="Global commands are restricted to global admins.")
        return True
    parts = msg.split()
    if len(parts) == 1 or (len(parts) >= 2 and parts[1].lower() in {"help", "?"}):
        send_whatsapp(to=admin_user.phone, text=GLOBAL_USAGE)
        return True
    cmd = parts[1].lower()
    args = parts[2:]
    try:
        if cmd == "set":
            if not args:
                send_whatsapp(
                    to=admin_user.phone,
                    text="Usage:\n- global set club <club_id|slug>\n- global set user <phone> <club_id|slug>"
                )
                return True
            sub = args[0].lower()
            if sub == "club":
                if len(args) < 2:
                    send_whatsapp(to=admin_user.phone, text="Usage: global set club <club_id|slug>")
                    return True
                club_token = args[1]
                with SessionLocal() as s:
                    club = _find_club_by_identifier(s, club_token)
                    if not club:
                        send_whatsapp(to=admin_user.phone, text=f"Club '{club_token}' not found.")
                        return True
                    row = s.query(User).filter(User.id == admin_user.id).one_or_none()
                    if not row:
                        send_whatsapp(to=admin_user.phone, text="Unable to reload your admin profile; try again.")
                        return True
                    row.club_id = getattr(club, "id", None)
                    s.commit()
                    admin_user.club_id = getattr(club, "id", None)
                send_whatsapp(
                    to=admin_user.phone,
                    text=f"Admin club updated to {_club_label(club)} (id={getattr(club, 'id', None)}).",
                )
                return True
            if sub == "user":
                if len(args) < 3:
                    send_whatsapp(to=admin_user.phone, text="Usage: global set user <phone> <club_id|slug>")
                    return True
                target_phone = _norm_phone(args[1])
                club_token = args[2]
                with SessionLocal() as s:
                    club = _find_club_by_identifier(s, club_token)
                    if not club:
                        send_whatsapp(to=admin_user.phone, text=f"Club '{club_token}' not found.")
                        return True
                    target = s.execute(select(User).where(User.phone == target_phone)).scalar_one_or_none()
                if not target:
                    send_whatsapp(to=admin_user.phone, text=f"User with phone {args[1]} not found.")
                    return True
                with SessionLocal() as s:
                    db_user = s.execute(select(User).where(User.id == target.id)).scalar_one_or_none()
                    if not db_user:
                        send_whatsapp(to=admin_user.phone, text="Unable to reload target user; try again.")
                        return True
                    db_user.club_id = getattr(club, "id", None)
                    s.commit()
                target.club_id = getattr(club, "id", None)
                send_whatsapp(
                    to=admin_user.phone,
                    text=f"Updated {display_full_name(target)} ({target.phone}) to {_club_label(club)} (id={getattr(club, 'id', None)}).",
                )
                return True
            send_whatsapp(
                to=admin_user.phone,
                text="Unknown global set command. Use:\n- global set club <club>\n- global set user <phone> <club>"
            )
            return True
        if cmd == "users":
            try:
                html_path = generate_global_users_html()
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate global users report: {e}")
                return True
            filename = os.path.basename(html_path)
            url = _public_report_url_global(filename)
            bust = int(time.time())
            send_whatsapp(
                to=admin_user.phone,
                text=f"Global users listing ready:\n{url}?ts={bust}"
            )
            return True
        if cmd == "summary":
            start_str, end_str = _parse_summary_range(args)
            try:
                pdf_path = generate_assessment_summary_pdf(start_str, end_str, club_id=None)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate global summary report: {e}")
                return True
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"Global assessment summary {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
        if cmd == "okr-summary":
            start_str, end_str = _parse_summary_range(args)
            try:
                gen = _resolve_okr_summary_gen()
                import os as _os
                _prev = _os.environ.get("OKR_SUMMARY_WITH_llm_PROMPT")
                _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = "0"
                pdf_path = gen(start_str, end_str, club_id=None)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate global OKR summary: {e}")
                return True
            finally:
                try:
                    if _prev is None:
                        _os.environ.pop("OKR_SUMMARY_WITH_llm_PROMPT", None)
                    else:
                        _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = _prev
                except Exception:
                    pass
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"Global OKR summary {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
        if cmd == "okr-summaryllm":
            start_str, end_str = _parse_summary_range(args)
            try:
                gen = _resolve_okr_summary_gen()
                import os as _os
                _prev = _os.environ.get("OKR_SUMMARY_WITH_llm_PROMPT")
                _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = "1"
                pdf_path = gen(start_str, end_str, club_id=None)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate global OKR summary (with llm prompt): {e}")
                return True
            finally:
                try:
                    if _prev is None:
                        _os.environ.pop("OKR_SUMMARY_WITH_llm_PROMPT", None)
                    else:
                        _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = _prev
                except Exception:
                    pass
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"Global OKR summary (with llm prompt) {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
    except Exception as e:
        send_whatsapp(to=admin_user.phone, text=f"Global admin error: {e}")
        return True
    send_whatsapp(to=admin_user.phone, text="Unknown global command. Try: global summary / global okr-summary")
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Webhooks
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/webhooks/twilio")
async def twilio_inbound(request: Request):
    """
    Accepts x-www-form-urlencoded payloads from Twilio (SMS/WhatsApp).
    Parses the raw body for maximum compatibility, resolves/creates user, logs
    inbound immediately upon receipt, and then routes to the assessor.
    """
    try:
        raw = (await request.body()).decode("utf-8")
        data = parse_qs(raw, keep_blank_values=True)

        body = (data.get("Body", [""])[0] or "").strip()
        from_raw = (data.get("From", [""])[0] or "").strip()
        if not from_raw:
            return Response(content="", media_type="text/plain", status_code=400)

        phone = from_raw.replace("whatsapp:", "") if from_raw.startswith("whatsapp:") else from_raw
        channel = "whatsapp" if from_raw.startswith("whatsapp:") else "sms"

        user = _get_or_create_user(phone)

        # Global admin commands (broader scope)
        if body.lower().startswith("global"):
            if _is_global_admin(user):
                if _handle_global_command(user, body):
                    return Response(content="", media_type="text/plain", status_code=200)
                return Response(content="", media_type="text/plain", status_code=200)
            else:
                print(f"[global] ignored command from non-global user_id={user.id}")
                try:
                    send_whatsapp(to=user.phone, text="Sorry, global commands are restricted to global admins.")
                except Exception:
                    pass
                return Response(content="", media_type="text/plain", status_code=200)

        # Admin commands must never fall through to normal flow
        if body.lower().startswith("admin"):
            if _is_admin_user(user):
                if _handle_admin_command(user, body):
                    return Response(content="", media_type="text/plain", status_code=200)
                return Response(content="", media_type="text/plain", status_code=200)
            else:
                print(f"[admin] ignored admin cmd from non-admin user_id={user.id} is_superuser={getattr(user,'is_superuser',None)}")
                try:
                    send_whatsapp(to=user.phone, text="Sorry, admin commands are restricted to superusers.")
                except Exception:
                    pass
                return Response(content="", media_type="text/plain", status_code=200)

        lower_body = body.lower()

        # ✅ log inbound immediately upon receipt (before processing)
        _log_inbound_direct(user, channel, body, from_raw)

        # Interactive menu commands
        if lower_body in {"menu", "help", "options"}:
            send_menu_options(user)
            return Response(content="", media_type="text/plain", status_code=200)

        if lower_body == "dashboard":
            try:
                print(f"[api] dashboard command received for user_id={user.id}")
            except Exception:
                pass
            send_dashboard_link(user)
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body == "progress":
            try:
                from .reporting import generate_progress_report_html
                path = generate_progress_report_html(user.id)
                url = _public_report_url(user.id, "progress.html")
                send_whatsapp(to=user.phone, text=f"Your progress report: {url}")
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Couldn't refresh your progress report: {e}")
            return Response(content="", media_type="text/plain", status_code=200)

        # Route to assessor
        if lower_body in {"start", "hi", "hello"}:
            start_combined_assessment(user, force_intro=True)
        else:
            continue_combined_assessment(user, body)

        return Response(content="", media_type="text/plain", status_code=200)

    except Exception as e:
        try:
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        return Response(content="", media_type="text/plain", status_code=500)


# ──────────────────────────────────────────────────────────────────────────────
# Health / Root
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "ok": True,
        "env": ENV,
        "timezone": "Europe/London",
        "app_start_uk": APP_START_UK_STR,
        "uptime_seconds": _uptime_seconds(),
    }

@app.get("/")
def root():
    return {
        "service": "ai-coach",
        "status": "ok",
        "env": ENV,
        "timezone": "Europe/London",
        "app_start_uk": APP_START_UK_STR,
        "uptime_seconds": _uptime_seconds(),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Debug routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/debug/routes")
def debug_routes():
    out = []
    try:
        for r in app.router.routes:
            try:
                out.append({
                    "path": getattr(r, "path", None),
                    "name": getattr(r, "name", None),
                    "methods": sorted(list(getattr(r, "methods", []) or [])),
                    "endpoint": f"{getattr(getattr(r, 'endpoint', None), '__module__', None)}.{getattr(getattr(r, 'endpoint', None), '__name__', None)}",
                })
            except Exception:
                out.append({"path": getattr(r, 'path', None), "name": getattr(r, 'name', None)})
    except Exception as e:
        out.append({"error": repr(e)})
    return out


# Mount routes
app.include_router(router)

# ──────────────────────────────────────────────────────────────────────────────
# Admin (superuser) endpoints
# ──────────────────────────────────────────────────────────────────────────────
admin = APIRouter(prefix="/admin", tags=["admin"])

def _require_admin(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
) -> User:
    expected = (os.getenv("ADMIN_API_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_TOKEN not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    if not x_admin_user_id:
        raise HTTPException(status_code=400, detail="X-Admin-User-Id header required")
    try:
        admin_user_id = int(x_admin_user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="X-Admin-User-Id must be an integer")
    with SessionLocal() as s:
        admin_user = s.execute(select(User).where(User.id == admin_user_id)).scalar_one_or_none()
        if not admin_user:
            raise HTTPException(status_code=404, detail="Admin user not found")
        if _user_admin_role(admin_user) not in {ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}:
            raise HTTPException(status_code=403, detail="User lacks admin privileges")
        if getattr(admin_user, "club_id", None) is None:
            raise HTTPException(status_code=400, detail="Admin user missing club association")
    return admin_user

def _ensure_club_scope(admin_user: User, target_user: User) -> None:
    if getattr(admin_user, "club_id", None) != getattr(target_user, "club_id", None):
        raise HTTPException(status_code=403, detail="User belongs to a different club")

@admin.post("/users")
def admin_create_user(payload: dict, admin_user: User = Depends(_require_admin)):
    """
    Create a new user and trigger consent/intro via start_combined_assessment.
    Body: { "first_name": "Julian", "surname": "Matthews", "phone": "+4477..." }
    """
    phone = _norm_phone((payload.get("phone") or "").strip())
    def _titlecase_chunk(chunk: str | None) -> str | None:
        if not chunk:
            return None
        chunk = _strip_invisible(chunk).strip()
        if not chunk:
            return None
        return " ".join(word.capitalize() for word in chunk.split())

    first_name = _titlecase_chunk(payload.get("first_name"))
    surname = _titlecase_chunk(payload.get("surname"))
    if not phone:
        raise HTTPException(status_code=400, detail="phone required")
    if not _require_name_fields(first_name, surname):
        raise HTTPException(status_code=400, detail="first_name and surname required")
    admin_club_id = getattr(admin_user, "club_id", None)
    if admin_club_id is None:
        raise HTTPException(status_code=400, detail="admin user missing club")
    with SessionLocal() as s:
        existing = s.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="user already exists")
        now = datetime.utcnow()
        u = User(
            first_name=first_name,
            surname=surname,
            phone=phone,
            club_id=admin_club_id,
            created_on=now,
            updated_on=now,
            consent_given=True,
            consent_at=now,
        )
        if hasattr(u, "consent_yes_at"):
            try:
                setattr(u, "consent_yes_at", now)
            except Exception:
                pass
        s.add(u); s.commit(); s.refresh(u)
    # Fire consent/intro; this will send the WhatsApp message
    try:
        start_combined_assessment(u)
    except Exception as e:
        # Do not fail creation if send fails
        print(f"[admin_create_user] start_combined_assessment failed: {e!r}")
    return {
        "id": u.id,
        "first_name": getattr(u, "first_name", None),
        "surname": getattr(u, "surname", None),
        "display_name": display_full_name(u),
        "phone": u.phone
    }

@admin.post("/users/{user_id}/start")
def admin_start_user(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Start (or restart) assessment for a user; will send consent/intro if needed.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
    start_combined_assessment(u)
    return {"status": "started", "user_id": user_id}

@admin.get("/users/{user_id}/status")
def admin_user_status(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Return assessment status and latest run info.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
        active = get_active_domain(u)
        latest_run = s.execute(
            select(AssessmentRun).where(AssessmentRun.user_id == user_id).order_by(desc(AssessmentRun.id))
        ).scalars().first()

    data = {
        "user": {
            "id": u.id,
            "first_name": getattr(u, "first_name", None),
            "surname": getattr(u, "surname", None),
            "display_name": display_full_name(u),
            "phone": u.phone,
            "consent_given": bool(getattr(u, "consent_given", False)),
            "consent_at": getattr(u, "consent_at", None),
        },
        "active_domain": active,
        "latest_run": None
    }

    if latest_run:
        data["latest_run"] = {
            "id": latest_run.id,
            "finished_at": getattr(latest_run, "finished_at", None),
            "combined_overall": getattr(latest_run, "combined_overall", None),
            "report_pdf": _public_report_url(user_id, "latest.pdf"),
            "report_image": _public_report_url(user_id, "latest.jpeg"),
        }

    if active:
        data["status"] = "in_progress"
    elif latest_run and getattr(latest_run, "finished_at", None):
        data["status"] = "completed"
    else:
        data["status"] = "idle"

    return data



@admin.get("/users/{user_id}/report")
def admin_user_report(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Return latest report URLs for the user.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
    return {
        "pdf": _public_report_url(user_id, "latest.pdf"),
        "image": _public_report_url(user_id, "latest.jpeg"),
    }


# Regenerate assessment report for a specific AssessmentRun and return public URLs.
@admin.post("/reports/run/{run_id}")
def admin_generate_report_for_run(run_id: int, admin_user: User = Depends(_require_admin)):
    """Regenerate assessment report for a specific AssessmentRun and return public URLs."""
    with SessionLocal() as s:
        run = s.execute(select(AssessmentRun).where(AssessmentRun.id == run_id)).scalars().first()
        if not run:
            raise HTTPException(status_code=404, detail="assessment run not found")
        user_id = int(getattr(run, "user_id", 0) or 0)
        if not user_id:
            raise HTTPException(status_code=500, detail="run has no user_id")
        user = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="user not found for run")
        _ensure_club_scope(admin_user, user)
    try:
        generate_assessment_report_pdf(run_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to generate report: {e}")
    return {
        "user_id": user_id,
        "run_id": run_id,
        "pdf": _public_report_url(user_id, "latest.pdf"),
        "image": _public_report_url(user_id, "latest.jpeg"),
    }


# Generate (or regenerate) reports for all completed AssessmentRuns in a date range.
@admin.post("/reports/batch")
def admin_generate_batch_reports(
    start: str | None = None,
    end: str | None = None,
    admin_user: User = Depends(_require_admin),
):
    """
    Generate (or regenerate) reports for all completed AssessmentRuns in a date range.
    Accepted query params:
      - start/end as ISO dates (YYYY-MM-DD) OR
      - start as a token: today | last7d | last30d | thisweek
    If neither is provided, defaults to today.
    """
    # Resolve date range
    def _resolve_range(start: str | None, end: str | None) -> tuple[str, str]:
        if start and start.lower() in {"today", "last7d", "last30d", "thisweek"}:
            return _parse_summary_range([start])
        if start and end:
            return _parse_summary_range([start, end])
        # default to today
        return _parse_summary_range(["today"])

    start_str, end_str = _resolve_range(start, end)
    try:
        start_dt = datetime.fromisoformat(start_str)
        # make end exclusive by adding one day
        end_dt = datetime.fromisoformat(end_str) + timedelta(days=1)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid start/end date; expected YYYY-MM-DD or token")

    items: list[dict] = []
    club_scope_id = getattr(admin_user, "club_id", None)
    with SessionLocal() as s:
        q = select(AssessmentRun).where(
            AssessmentRun.finished_at.isnot(None),
            AssessmentRun.finished_at >= start_dt,
            AssessmentRun.finished_at < end_dt,
        )
        if club_scope_id is not None:
            q = q.join(User, AssessmentRun.user_id == User.id).where(User.club_id == club_scope_id)
        q = q.order_by(desc(AssessmentRun.id))
        runs = list(s.execute(q).scalars().all())

    for run in runs:
        uid = int(getattr(run, "user_id", 0) or 0)
        rid = int(getattr(run, "id", 0) or 0)
        try:
            generate_assessment_report_pdf(rid)
            items.append({
                "user_id": uid,
                "run_id": rid,
                "pdf": _public_report_url(uid, "latest.pdf"),
                "image": _public_report_url(uid, "latest.jpeg"),
            })
        except Exception as e:
            # Include error per run but continue
            items.append({
                "user_id": uid,
                "run_id": rid,
                "error": str(e),
            })

    return {
        "range": {"start": start_str, "end": end_str},
        "count": len([i for i in items if "error" not in i]),
        "total": len(items),
        "items": items,
    }


# Optional: Admin endpoint to generate OKR summary PDF
@admin.get("/okr-summary")
def admin_okr_summary(
    start: str | None = None,
    end: str | None = None,
    include_llm_prompt: bool = False,
    admin_user: User = Depends(_require_admin),
):
    """Generate an OKR summary PDF for the given date range and return its public URL.
    - Set include_llm_prompt=true to include the llm prompt field.
    """
    import os as _os
    _prev = _os.environ.get("OKR_SUMMARY_WITH_llm_PROMPT")
    try:
        gen = _resolve_okr_summary_gen()
        club_scope_id = getattr(admin_user, "club_id", None)
        _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = "1" if include_llm_prompt else "0"
        pdf_path = gen(start, end, club_id=club_scope_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate OKR summary: {e}")
    finally:
        try:
            if _prev is None:
                _os.environ.pop("OKR_SUMMARY_WITH_llm_PROMPT", None)
            else:
                _os.environ["OKR_SUMMARY_WITH_llm_PROMPT"] = _prev
        except Exception:
            pass
    filename = os.path.basename(pdf_path)
    return {"pdf": _public_report_url_global(filename)}


# ──────────────────────────────────────────────────────────────────────────────
# Static: serve generated PDFs at /reports/<user_id>/latest.pdf
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# Static: serve generated PDFs at /reports/<user_id>/latest.pdf
# Rule:
#   - If REPORTS_DIR is set (env) ⇒ use it (Render/prod) and base = Render hostname if available
#   - Else (local dev) ⇒ auto-detect ngrok https; fallback http://localhost:8000
# ──────────────────────────────────────────────────────────────────────────────
try:
    reports_dir = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")
    print(f"📄 Reports mounted at /reports -> {reports_dir}")

    _REPORTS_BASE = None
    if os.getenv("REPORTS_DIR"):
        # Production/deployed: prefer Render external hostname
        render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if render_host:
            _REPORTS_BASE = f"https://{render_host}"
        else:
            _REPORTS_BASE = "http://localhost:8000"
        print(f"🔗 Reports base URL (REPORTS_DIR set): {_REPORTS_BASE}/reports")
    else:
        # Local dev: detect ngrok
        try:
            with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1.5) as resp:
                data = json.load(resp)
            tunnels = (data or {}).get("tunnels", []) or []
            https = next((t for t in tunnels if str(t.get("public_url", "")).startswith("https://")), None)
            if https:
                _REPORTS_BASE = str(https.get("public_url", "")).rstrip("/")
                print(f"🔗 Reports base URL (ngrok): {_REPORTS_BASE}/reports")
            else:
                _REPORTS_BASE = "http://localhost:8000"
                print("⚠️ ngrok https tunnel not found; using localhost.")
        except Exception as e:
            _REPORTS_BASE = "http://localhost:8000"
            print(f"⚠️ ngrok detect failed: {e!r}; using localhost.")
except Exception as e:
    print(f"⚠️  Failed to mount /reports: {e!r}")
    _REPORTS_BASE = "http://localhost:8000"


def _public_report_url(user_id: int, filename: str) -> str:
    """Return absolute URL to a user's report file."""
    return f"{_REPORTS_BASE}/reports/{user_id}/{filename}"

def _public_report_url_global(filename: str) -> str:
    """Return absolute URL to a global report file located directly under /reports."""
    return f"{_REPORTS_BASE}/reports/{filename}"
