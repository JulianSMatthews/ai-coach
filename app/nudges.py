# app/nudges.py
from __future__ import annotations

import os
import re
from datetime import datetime, time, timedelta

from twilio.rest import Client
from .config import settings
from .message_log import write_log

BUSINESS_START = time(9, 0)
BUSINESS_END   = time(19, 0)


def in_business_hours(now_local: datetime) -> bool:
    t = now_local.time()
    return BUSINESS_START <= t <= BUSINESS_END

# ──────────────────────────────────────────────────────────────────────────────
# WhatsApp sending (multi-user safe)
# ──────────────────────────────────────────────────────────────────────────────

E164 = re.compile(r"^\+?[1-9]\d{7,14}$")  # simple E.164 validator


def _normalize_whatsapp_phone(raw: str | None) -> str | None:
    """
    Return a number in the 'whatsapp:+441234567890' format, or None.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("whatsapp:"):
        num = s.split("whatsapp:", 1)[1]
        if E164.match(num):
            return s
        return None
    if E164.match(s):
        return f"whatsapp:{s if s.startswith('+') else '+' + s}"
    return None


def _twilio_client() -> Client | None:
    try:
        return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
    except Exception as e:
        print(f"❌ Twilio client init failed: {e!r}")
        return None


# NOTE: write_log is defined ONLY in app.message_log and imported here; do not redefine.
def _try_write_outbound_log(*, phone_e164: str, text: str, category: str | None, twilio_sid: str, to_norm: str):
    """Log using the single canonical write_log from app.message_log; never raise."""
    try:
        write_log(
            phone_e164=phone_e164,
            direction="outbound",
            text=text,
            category=category,
            twilio_sid=twilio_sid,
        )
    except Exception as e:
        print(f"⚠️ outbound logging failed (non-fatal): {e!r}")


def send_whatsapp(text: str, to: str | None = None, category: str | None = None) -> str:
    """
    Primary send function. Logs only after Twilio accepts.
    """
    to_norm = _normalize_whatsapp_phone(to) if to else None

    if not to_norm:
        if os.getenv("FORCE_FALLBACK_TO_ENV_TO") == "1":
            env_to = _normalize_whatsapp_phone(os.getenv("TWILIO_TO"))
            if not env_to:
                raise ValueError("TWILIO_TO is missing or invalid; cannot fallback.")
            to_norm = env_to
        else:
            raise ValueError("Recipient phone missing. Refusing to fallback.")

    client = _twilio_client()
    if client is None:
        raise RuntimeError("Twilio client unavailable")

    # Send
    msg = client.messages.create(
        from_=settings.TWILIO_FROM,
        body=text,
        to=to_norm,
    )

    # ✅ Log — success only
    phone_e164 = to_norm.replace("whatsapp:", "")
    try:
        _try_write_outbound_log(
            phone_e164=phone_e164,
            text=text,
            category=category,
            twilio_sid=getattr(msg, "sid", None) or "",
            to_norm=to_norm,
        )
    except Exception as e:
        print(f"⚠️ outbound logging wrapper failed (non-fatal): {e!r}")

    return getattr(msg, "sid", "")


def send_message(arg1: str, arg2: str | None = None, category: str | None = None) -> str:
    """
    Backwards-compat shim for legacy calls.
    - send_message(phone, text[, category])  → preferred legacy style
    - send_message(text[, category])         → legacy dev style (needs FORCE_FALLBACK_TO_ENV_TO=1)
    """
    if arg2 is None:
        # old pattern: send_message(text)
        return send_whatsapp(text=arg1, to=None, category=category)
    else:
        # old pattern: send_message(phone, text)
        return send_whatsapp(text=arg2, to=arg1, category=category)


# ──────────────────────────────────────────────────────────────────────────────
# (Optional) business-hours helper
# ──────────────────────────────────────────────────────────────────────────────

def maybe_delay_to_business_hours(dt_local: datetime) -> datetime:
    if in_business_hours(dt_local):
        return dt_local
    # move to next business start
    next_day = dt_local
    if dt_local.time() > BUSINESS_END:
        next_day = (dt_local + timedelta(days=1)).replace(hour=BUSINESS_START.hour, minute=0, second=0, microsecond=0)
    else:
        next_day = dt_local.replace(hour=BUSINESS_START.hour, minute=0, second=0, microsecond=0)
    return next_day