from __future__ import annotations

import re
from typing import Any

from . import config

try:
    from twilio.base.exceptions import TwilioRestException
    from twilio.rest import Client
except Exception:  # pragma: no cover - keeps dry-run mode usable without Twilio installed.
    TwilioRestException = Exception  # type: ignore[assignment]
    Client = None  # type: ignore[assignment]


_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if value.lower().startswith("whatsapp:"):
        value = value.split(":", 1)[1].strip()
    if any(ch.isalpha() for ch in value):
        return None
    value = value.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if value.startswith("00"):
        value = "+" + value[2:]
    if value.startswith("+"):
        return value if _E164.match(value) else None
    digits = re.sub(r"\D+", "", value)
    if not digits:
        return None
    default_country = re.sub(r"\D+", "", config.DEFAULT_COUNTRY_CODE or "")
    if default_country and digits.startswith("0"):
        candidate = f"+{default_country}{digits[1:]}"
        return candidate if _E164.match(candidate) else None
    if default_country and len(digits) in {10, 11} and not digits.startswith(default_country):
        candidate = f"+{default_country}{digits}"
        return candidate if _E164.match(candidate) else None
    candidate = "+" + digits
    return candidate if _E164.match(candidate) else None


def _client() -> Client | None:
    if not config.TWILIO_ACCOUNT_SID or not config.TWILIO_AUTH_TOKEN:
        return None
    if Client is None:
        raise RuntimeError("Twilio package is not installed")
    return Client(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN)


def _sms_sender() -> str:
    value = str(config.TWILIO_FROM or "").strip()
    if value.lower().startswith("whatsapp:"):
        value = value.split(":", 1)[1].strip()
    normalized = normalize_phone(value)
    return normalized or value


def send_sms(to_phone: str, text: str) -> dict[str, Any]:
    to_addr = normalize_phone(to_phone)
    if not to_addr:
        raise ValueError("A valid mobile number is required")
    body = str(text or "").strip()
    if not body:
        raise ValueError("Cannot send an empty SMS message")
    if config.DRY_RUN_MESSAGES:
        print(f"[membersense][dry-run][sms] {to_addr}: {body}")
        return {"sid": f"dry-run-{abs(hash((to_addr, body))) % 100000000}", "status": "dry_run", "body": body}
    client = _client()
    if client is None:
        raise RuntimeError("Twilio credentials are missing")

    kwargs: dict[str, Any] = {"to": to_addr, "body": body}
    if config.TWILIO_MESSAGING_SERVICE_SID:
        kwargs["messaging_service_sid"] = config.TWILIO_MESSAGING_SERVICE_SID
    else:
        from_addr = _sms_sender()
        if not from_addr:
            raise RuntimeError("MEMBERSENSE_TWILIO_FROM, TWILIO_FROM, or MEMBERSENSE_TWILIO_MESSAGING_SERVICE_SID is required")
        kwargs["from_"] = from_addr
    if config.TWILIO_STATUS_CALLBACK_BASE:
        kwargs["status_callback"] = f"{config.TWILIO_STATUS_CALLBACK_BASE.rstrip('/')}/webhooks/twilio-status"
    try:
        message = client.messages.create(**kwargs)
    except TwilioRestException as exc:
        raise RuntimeError(f"Twilio SMS send failed: {getattr(exc, 'msg', str(exc))}") from exc
    return {
        "sid": getattr(message, "sid", None),
        "status": getattr(message, "status", None),
        "body": body,
    }
