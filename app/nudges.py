# app/nudges.py
from __future__ import annotations

import os
import queue
import re
import threading
import time
from datetime import datetime, time, timedelta

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
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
MIN_SEND_GAP_SEC = float(os.getenv("WHATSAPP_MIN_SEND_GAP", "0.4"))
_SEND_LOCK_GUARD = threading.Lock()
_SEND_LOCKS: dict[str, threading.Lock] = {}
_LAST_SEND_MONO: dict[str, float] = {}
_QUEUE_LOCK = threading.Lock()
_SEND_QUEUES: dict[str, "queue.Queue[dict]"] = {}
_QUEUE_THREADS: dict[str, threading.Thread] = {}


def _lock_for_destination(dest: str) -> threading.Lock:
    with _SEND_LOCK_GUARD:
        lock = _SEND_LOCKS.get(dest)
        if lock is None:
            lock = threading.Lock()
            _SEND_LOCKS[dest] = lock
        return lock


def _throttle_destination(dest: str):
    try:
        last = _LAST_SEND_MONO.get(dest, 0.0)
        gap = MIN_SEND_GAP_SEC - (time.monotonic() - last)
        if gap > 0:
            time.sleep(gap)
    except Exception:
        pass


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


def _perform_twilio_send(*, text: str, to_norm: str, category: str | None) -> str:
    client = _twilio_client()
    if client is None:
        raise RuntimeError("Twilio client unavailable")

    lock = _lock_for_destination(to_norm)
    with lock:
        _throttle_destination(to_norm)
        try:
            msg = client.messages.create(
                from_=settings.TWILIO_FROM,
                body=text,
                to=to_norm,
            )
        except TwilioRestException as exc:
            code = getattr(exc, "code", None)
            print(f"❌ Twilio send failed to {to_norm}: {exc.msg if hasattr(exc, 'msg') else exc} (code={code})")
            if code == 63016:
                print("💡 WhatsApp session expired (>24h). Send an approved template to reopen the window before freeform messages.")
            raise
        try:
            _LAST_SEND_MONO[to_norm] = time.monotonic()
        except Exception:
            pass

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


def _ensure_queue_worker(dest: str) -> queue.Queue:
    with _QUEUE_LOCK:
        q = _SEND_QUEUES.get(dest)
        if q is None:
            q = queue.Queue()
            _SEND_QUEUES[dest] = q
            t = threading.Thread(target=_queue_worker, args=(dest, q), daemon=True)
            _QUEUE_THREADS[dest] = t
            t.start()
        return q


def _queue_worker(dest: str, q: queue.Queue):
    while True:
        job = q.get()
        if job is None:
            q.task_done()
            break
        text = job["text"]
        category = job["category"]
        event = job["event"]
        result = job["result"]
        try:
            sid = _perform_twilio_send(text=text, to_norm=dest, category=category)
            result["sid"] = sid
        except Exception as e:
            result["error"] = e
        finally:
            event.set()
            q.task_done()


def _enqueue_and_send(*, to_norm: str, text: str, category: str | None) -> str:
    q = _ensure_queue_worker(to_norm)
    event = threading.Event()
    result: dict[str, str | Exception] = {}
    q.put({"text": text, "category": category, "event": event, "result": result})
    event.wait()
    if "error" in result:
        raise result["error"]
    return str(result.get("sid", ""))


def send_whatsapp(text: str, to: str | None = None, category: str | None = None) -> str:
    """
    Primary send function. Logs only after Twilio accepts.
    Requires an explicit `to`; will NOT fallback to any env recipient.
    """
    if not text or not str(text).strip():
        raise ValueError("Message text is empty")

    to_norm = _normalize_whatsapp_phone(to) if to else None
    if not to_norm:
        # Explicitly refuse to send without a valid recipient
        raise ValueError("Recipient phone missing or invalid (expected E.164). No fallback is permitted.")

    result_sid = _enqueue_and_send(to_norm=to_norm, text=text, category=category)

    # Optional local file logging (e.g., for weekflow review)
    log_path = os.getenv("WEEKFLOW_LOG_FILE", "").strip()
    if log_path:
        try:
            ts = datetime.utcnow().isoformat(timespec="seconds")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {text}\n")
        except Exception:
            pass

    return result_sid


# Explicit admin notification helper
def send_admin(text: str, category: str | None = None) -> str | None:
    """
    Explicit admin notification helper.
    Uses ADMIN_WHATSAPP or ADMIN_PHONE (E.164) from environment.
    Returns Twilio SID on success, or None if admin destination missing.
    """
    admin_raw = (os.getenv("ADMIN_WHATSAPP") or os.getenv("ADMIN_PHONE") or "").strip()
    to_norm = _normalize_whatsapp_phone(admin_raw)
    if not to_norm:
        return None
    return send_whatsapp(text=text, to=admin_raw, category=category)


def send_message(arg1: str, arg2: str | None = None, category: str | None = None) -> str:
    """
    Backwards-compat shim for legacy calls.
    - send_message(phone, text[, category])  → supported
    - send_message(text[, category])         → **DISALLOWED** (raises TypeError)
    """
    if arg2 is None:
        # Disallow ambiguous legacy usage that can misroute to admin
        raise TypeError("send_message(text) is not allowed. Call send_message(phone, text) or send_whatsapp(text, to=...).")
    # Legacy supported path: (phone, text)
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
