# app/api.py
from __future__ import annotations

import os
from fastapi import FastAPI, Body, Request
from sqlalchemy import text, inspect

from .db import engine, SessionLocal, init_db  # ✅ bring in init_db
from .models import Base, User
from .scheduler import start_scheduler, schedule_timeout_followup
from .assessor import (
    start_combined_assessment,
    continue_combined_assessment,
    get_active_domain,
)
from .seed import seed_users  # single entrypoint for seeding
from .message_log import write_log, last_log
from .nudges import _normalize_whatsapp_phone, send_whatsapp  # ✅ keep imports together

app = FastAPI(title="AI Coach")

from .admin_routes import admin
app.include_router(admin)

# ──────────────────────────────────────────────────────────────────────────────
# Startup
# ──────────────────────────────────────────────────────────────────────────────
@app.on_event("startup")
def on_startup():
    # Optional dev reset
    if os.getenv("RESET_DB_ON_STARTUP") == "1":
        print("⚠️ RESET_DB_ON_STARTUP=1 → Dropping all tables…")
        Base.metadata.drop_all(bind=engine)

    # One-shot DB init:
    #  1) Base.metadata.create_all(...)
    #  2) ensure pgvector + indexes (Postgres only)
    #  3) auto-seed concepts & KB if empty
    init_db()

    # Debug
    print("DB URL:", engine.url)
    if engine.dialect.name == "sqlite":
        from app.config import DB_FILE
        print("SQLite DB file:", DB_FILE)
    print("Tables:", inspect(engine).get_table_names())

    # Seed users (idempotent, gated by SEED_TEST_USER=1 inside seed_users)
    seed_users()

    # Start scheduler
    start_scheduler()

    # Start combined onboarding for any existing users not yet complete
    started_for = []
    with SessionLocal() as s:
        not_done = s.query(User).filter(User.onboard_complete == False).all()  # noqa: E712
        for u in not_done:
            start_combined_assessment(u)
            started_for.append(u.phone)
    if started_for:
        print(f"▶️ Started onboarding for users: {started_for}")
    else:
        print("ℹ️ No users needing onboarding at startup.")

# Health
@app.get("/health")
def health():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return {"ok": True}

# ──────────────────────────────────────────────────────────────────────────────
# Create user: do NOT schedule nudges; just start combined assessment
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/users")
def create_user(
    name: str = Body(...),
    phone: str = Body(...),
    tz: str = Body(default="Europe/London"),
):
    phone_clean = (phone or "").replace("whatsapp:", "").strip()
    with SessionLocal() as s:
        # upsert by phone
        u = s.query(User).filter(User.phone == phone_clean).first()
        if not u:
            u = User(
                name=name,
                phone=phone_clean,
                tz=tz,
                onboard_complete=False,
            )
            s.add(u); s.commit(); s.refresh(u)

    # Start onboarding immediately (nudges will be scheduled after assessor marks complete)
    start_combined_assessment(u)
    return {"id": u.id, "onboard_started": True}

# ──────────────────────────────────────────────────────────────────────────────
# JSON webhook (local testing): body {"user_phone":"whatsapp:+44..","text":"hi"}
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/webhooks/inbound")
def inbound_message(
    user_phone: str = Body(...),
    text: str = Body(...)
):
    phone_clean = (user_phone or "").replace("whatsapp:", "").strip()
    msg = (text or "").strip().lower()

    # Only proceed if the phone exists in DB (seeded or created via /users)
    with SessionLocal() as s:
        u = s.query(User).filter(User.phone == phone_clean).first()

    if not u:
        # Do NOT create a user here — reply and exit.
        try:
            send_whatsapp(
                to=f"whatsapp:{phone_clean}",
                text=("Hi! You're not set up yet. "
                      "Ask the team to add your number, or share your invite link.")
            )
        except Exception:
            pass
        return {"ok": False, "reason": "user_not_found"}

    # If not onboarded → run combined assessment only (nudges applied later)
    if not u.onboard_complete:
        if msg in {"start", "restart", "assess", "assess all", "assess combined", "full assess"}:
            start_combined_assessment(u)
            return {"ok": True, "action": "combined_started"}

        progressed = continue_combined_assessment(u, (text or "").strip())
        if not progressed and get_active_domain(u) != "combined":
            start_combined_assessment(u)

        schedule_timeout_followup(u.id, after_minutes=1, context={"last_text": text})
        return {"ok": True, "action": "onboarding_in_progress"}

    # (Optional) post‑onboarding logic here
    return {"ok": True, "action": "received"}

# ──────────────────────────────────────────────────────────────────────────────
# Twilio WhatsApp webhook (production entry point)
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/webhooks/twilio")
async def twilio_inbound(request: Request):
    form = await request.form()
    from_number = (form.get("From", "") or "").replace("whatsapp:", "").strip()
    body = (form.get("Body", "") or "").strip()
    msg_sid = (form.get("SmsMessageSid", "") or "").strip()  # idempotency-friendly

    # 1) Log the inbound immediately
    try:
        write_log(
            phone_e164=from_number,     # bare E.164, no 'whatsapp:' prefix
            direction="inbound",        # 'inbound' | 'outbound'
            text=body,
            category="whatsapp",        # helpful tag for filtering
            twilio_sid=msg_sid          # lets you dedupe on Twilio retries
        )
    except Exception as e:
        print(f"[WARN] Failed to write inbound log: {e}")

    # 2) Continue your normal handling
    return inbound_message(user_phone=from_number, text=body)

# ──────────────────────────────────────────────────────────────────────────────
# Logs (admin/debug)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/logs/last")
def logs_last():
    rec = last_log()
    return {"ok": bool(rec), "record": rec}