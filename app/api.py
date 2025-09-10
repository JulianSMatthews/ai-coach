# app/api.py
# PATCH — proper API module + robust Twilio webhook (2025-09-04)

import os
import json
import urllib.request
from urllib.parse import parse_qs

from fastapi import FastAPI, APIRouter, Request, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .db import engine, SessionLocal
from .models import Base, User, MessageLog  # ensure model registered for metadata

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
    from .assessor import (
        start_combined_assessment,
        continue_combined_assessment,
    )
    _DBG("[INFO] assessor module imported successfully")
except Exception:
    # Minimal safe fallbacks (won't crash startup; just no-op if used)
    def start_combined_assessment(*_, **__):
        return None

    def continue_combined_assessment(*_, **__):
        return None

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

def _get_or_create_user(phone_e164: str) -> User:
    """Find or create a User record by E.164 phone (no whatsapp: prefix)."""
    with SessionLocal() as s:
        u = s.query(User).filter(User.phone == phone_e164).first()
        if not u:
            u = User(name=None, phone=phone_e164)
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

        # Pre-log visibility
        try:
            print(
                f"[DEBUG] inbound pre-log"
            )
        except Exception:
            pass

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
# Webhooks
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/webhooks/twilio")
async def twilio_inbound(request: Request):
    print("[webhook] ENTER /webhooks/twilio (new)")
    """
    Accepts x-www-form-urlencoded payloads from Twilio (SMS/WhatsApp).
    Parses the raw body for maximum compatibility, resolves/creates user, routes
    to the assessor, and only then logs inbound (success path).
    """
    try:
        raw = (await request.body()).decode("utf-8")
        data = parse_qs(raw, keep_blank_values=True)

        body = (data.get("Body", [""])[0] or "").strip()
        from_raw = (data.get("From", [""])[0] or "").strip()
        _dbg(f"parsed body={body!r} from={from_raw!r}")
        if not from_raw:
            return Response(content="", media_type="text/plain", status_code=400)

        phone = from_raw.replace("whatsapp:", "") if from_raw.startswith("whatsapp:") else from_raw
        channel = "whatsapp" if from_raw.startswith("whatsapp:") else "sms"
        _dbg(f"normalized phone={phone!r} channel={channel}")

        user = _get_or_create_user(phone)

        # Route to assessor
        if body.lower() in {"start", "hi", "hello"}:
            start_combined_assessment(user)
            _dbg("routed to assessor: start")
        else:
            continue_combined_assessment(user, body)
            _dbg("routed to assessor: continue")

        # ✅ successful receive → log inbound (via canonical logger) then return 200
        _log_inbound_direct(user, channel, body, from_raw)
        return Response(content="", media_type="text/plain", status_code=200)

    except Exception as e:
        print(f"❌ /webhooks/twilio failed: {e!r}")
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
# Static: serve generated PDFs at /reports/<user_id>/latest.pdf
# ──────────────────────────────────────────────────────────────────────────────
try:
    _reports_dir = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
    os.makedirs(_reports_dir, exist_ok=True)
    app.mount("/reports", StaticFiles(directory=_reports_dir), name="reports")
    print(f"📄 Reports mounted at /reports -> {_reports_dir}")
except Exception as e:
    print(f"⚠️  Failed to mount /reports: {e!r}")
