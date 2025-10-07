# app/api.py
# PATCH — proper API module + robust Twilio webhook (2025-09-04)
# PATCH — 2025-09-11: Add minimal superuser admin endpoints (create user, start, status, report)
# PATCH — 2025-09-11: Admin hardening + WhatsApp admin commands (token+DB check; create/start/status/report)

import os
import json
import urllib.request
from urllib.parse import parse_qs
from datetime import datetime

from fastapi import FastAPI, APIRouter, Request, Response, Depends, Header, HTTPException, status
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy import select, desc
from pathlib import Path 

from .db import engine, SessionLocal
from .models import Base, User, MessageLog, AssessSession, AssessmentRun  # ensure model registered for metadata
from .nudges import send_whatsapp
from .reporting import generate_detailed_report_pdf_by_user, generate_assessment_summary_pdf

# PATCH — 2025-09-11: Admin usage helper text
ADMIN_USAGE = (
    "Admin commands:\n"
    "admin create <phone> [first_name [surname]]\n"
    "admin start <phone>\n"
    "admin status <phone>\n"
    "admin report <phone>\n"
    "admin detailed <phone>\n"
    "admin summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "\nExample: admin create +447700900123 Julian Matthews"
)

print("🚀 app.api loaded: v-2025-09-04E")

# Prefer compat shim; fall back to run_seed if needed
try:
    from .seed import seed_users  # legacy entrypoint shim
except Exception:  # pragma: no cover
    seed_users = None
try:
    from .seed import run_seed  # fallback
except Exception:  # pragma: no cover
    run_seed = None

# Assessor entrypoints

def _dbg(msg: str):
    try:
        print(f"[webhook] {msg}")
    except Exception:
        pass

try:
    from .assessor import start_combined_assessment, continue_combined_assessment, get_active_domain
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
        if callable(seed_users):
            seed_users()
        elif callable(run_seed):
            run_seed()
        else:
            print("⚠️  No seeding function available (seed_users/run_seed not found).")

        # Ensure reports dir exists even when not resetting DB
        try:
            reports_dir = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
            os.makedirs(reports_dir, exist_ok=True)
        except Exception as e:
            print(f"⚠️  Could not create reports dir: {e!r}")
        # Always try to set PUBLIC_BASE_URL from ngrok if not already set
    _maybe_set_public_base_via_ngrok()

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
    parts = [p for p in str(maybe_name).strip().split() if p]
    if not parts:
        return None, None
    if len(parts) == 1:
        return parts[0], None
    return parts[0], " ".join(parts[1:])

def _get_or_create_user(phone_e164: str) -> User:
    """Find or create a User record by E.164 phone (no whatsapp: prefix)."""
    with SessionLocal() as s:
        u = s.query(User).filter(User.phone == phone_e164).first()
        if not u:
            u = User(first_name=None, surname=None, phone=phone_e164)
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
def _norm_phone(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("whatsapp:"):
        s = s[len("whatsapp:"):]
    s = s.replace(" ", "")
    cc = (os.getenv("DEFAULT_COUNTRY_CODE") or "").strip()
    if s.startswith("+"):
        return s
    if s.isdigit():
        if s.startswith("0") and cc.startswith("+"):
            return cc + s[1:]
        if cc.startswith("+"):
            return cc + s
    return s


def _is_admin_user(u: User) -> bool:
    try:
        ok = bool(getattr(u, "is_superuser", False)) and int(getattr(u, "id", 0)) in (1, 2)
        print(f"[admin] check user_id={getattr(u,'id',None)} phone={getattr(u,'phone',None)} is_superuser={getattr(u,'is_superuser',None)} ok={ok}")
        return ok
    except Exception as e:
        print(f"[admin] check error: {e!r}")
        return False

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
      admin report <phone>
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
    if len(parts) < 3:
        send_whatsapp(to=admin_user.phone, text=ADMIN_USAGE)
        return True
    cmd = parts[1].lower()
    try:
        if cmd == "create":
            phone = _norm_phone(parts[2])
            raw_name = " ".join(parts[3:]) if len(parts) > 3 else None
            first_name, surname = _split_name(raw_name)
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
                    created_on=now,
                    updated_on=now,
                )
                s.add(u); s.commit(); s.refresh(u)
            # trigger consent/intro
            try:
                start_combined_assessment(u)
            except Exception as e:
                print(f"[wa admin create] start failed: {e!r}")
            send_whatsapp(to=admin_user.phone, text=f"Created user id={u.id} {display_full_name(u)} ({u.phone})")
            return True
        elif cmd == "start":
            target_phone = _norm_phone(parts[2])
            with SessionLocal() as s:
                u = s.execute(select(User).where(User.phone == target_phone)).scalar_one_or_none()
                if not u:
                    send_whatsapp(to=admin_user.phone, text=f"User with phone {target_phone} not found")
                    return True
            start_combined_assessment(u)
            send_whatsapp(to=admin_user.phone, text=f"Started assessment for {display_full_name(u)} ({u.phone})")
            return True
        elif cmd == "status":
            target_phone = _norm_phone(parts[2])
            with SessionLocal() as s:
                u = s.execute(select(User).where(User.phone == target_phone)).scalar_one_or_none()
                if not u:
                    send_whatsapp(to=admin_user.phone, text=f"User with phone {target_phone} not found")
                    return True
                active = get_active_domain(u)
                latest_run = s.execute(
                    select(AssessmentRun).where(AssessmentRun.user_id == u.id).order_by(desc(AssessmentRun.id))
                ).scalars().first()
            status_txt = "in_progress" if active else ("completed" if latest_run and getattr(latest_run, "finished_at", None) else "idle")
            send_whatsapp(to=admin_user.phone, text=f"Status for {display_full_name(u)} ({u.phone}): {status_txt}")
            return True
        elif cmd == "report":
            target_phone = _norm_phone(parts[2])
            with SessionLocal() as s:
                u = s.execute(select(User).where(User.phone == target_phone)).scalar_one_or_none()
                if not u:
                    send_whatsapp(to=admin_user.phone, text=f"User with phone {target_phone} not found")
                    return True
            pdf = _public_report_url(u.id, "latest.pdf")
            img = _public_report_url(u.id, "latest.jpeg")
            send_whatsapp(to=admin_user.phone, text=f"Report for {display_full_name(u)} ({u.phone}):\nPDF: {pdf}\nImage: {img}")
            return True
        elif cmd == "detailed":
            target_phone = _norm_phone(parts[2])
            with SessionLocal() as s:
                u = s.execute(select(User).where(User.phone == target_phone)).scalar_one_or_none()
                if not u and parts[2].lower() in {"me", "my", "self"}:
                    u = admin_user
                if not u:
                    send_whatsapp(to=admin_user.phone, text=f"User with phone {parts[2]} not found")
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
            args = parts[2:]
            start_str, end_str = _parse_summary_range(args)
            try:
                pdf_path = generate_assessment_summary_pdf(start_str, end_str)
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
    except Exception as e:
        send_whatsapp(to=admin_user.phone, text=f"Admin error: {e}")
        return True
    # Unknown subcommand
    send_whatsapp(to=admin_user.phone, text="Unknown admin command. Try: create/start/status/report")
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

        # ✅ log inbound immediately upon receipt (before processing)
        _log_inbound_direct(user, channel, body, from_raw)

        # Route to assessor
        if body.lower() in {"start", "hi", "hello"}:
            start_combined_assessment(user)
        else:
            continue_combined_assessment(user, body)

        return Response(content="", media_type="text/plain", status_code=200)

    except Exception as e:
        return Response(content="", media_type="text/plain", status_code=500)


# ──────────────────────────────────────────────────────────────────────────────
# Health / Root
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/")
def root():
    return {"service": "ai-coach", "status": "ok"}


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

def _require_admin(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    expected = (os.getenv("ADMIN_API_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_TOKEN not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    # Extra DB guard: ensure users 1 and 2 are provisioned as superusers
    with SessionLocal() as s:
        provisioned = s.query(User).filter(User.id.in_([1, 2]), User.is_superuser == True).count()
        if provisioned < 2:
            raise HTTPException(status_code=403, detail="Superusers (ids 1 & 2) not provisioned")

@admin.post("/users", dependencies=[Depends(_require_admin)])
def admin_create_user(payload: dict):
    """
    Create a new user and trigger consent/intro via start_combined_assessment.
    Body: { "first_name": "Julian", "surname": "Matthews", "phone": "+4477..." }
    """
    phone = (payload.get("phone") or "").strip()
    first_name = (payload.get("first_name") or "").strip() or None
    surname = (payload.get("surname") or "").strip() or None
    if not phone:
        raise HTTPException(status_code=400, detail="phone required")
    with SessionLocal() as s:
        existing = s.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="user already exists")
        now = datetime.utcnow()
        u = User(
            first_name=first_name,
            surname=surname,
            phone=phone,
            created_on=now,
            updated_on=now,
        )
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

@admin.post("/users/{user_id}/start", dependencies=[Depends(_require_admin)])
def admin_start_user(user_id: int):
    """
    Start (or restart) assessment for a user; will send consent/intro if needed.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
    start_combined_assessment(u)
    return {"status": "started", "user_id": user_id}

@admin.get("/users/{user_id}/status", dependencies=[Depends(_require_admin)])
def admin_user_status(user_id: int):
    """
    Return assessment status and latest run info.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
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

@admin.get("/users/{user_id}/report", dependencies=[Depends(_require_admin)])
def admin_user_report(user_id: int):
    """
    Return latest report URLs for the user.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
    return {
        "pdf": _public_report_url(user_id, "latest.pdf"),
        "image": _public_report_url(user_id, "latest.jpeg"),
    }


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




