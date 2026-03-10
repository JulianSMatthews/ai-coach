from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Any

from .db import SessionLocal
from .models import User, UserPreference
from .nudges import send_whatsapp, send_whatsapp_media

_COACHING_DELIVERY_CTX: ContextVar[dict[str, Any] | None] = ContextVar(
    "_COACHING_DELIVERY_CTX",
    default=None,
)

_ALLOWED_CHANNELS = {"whatsapp", "app"}


@contextmanager
def coaching_delivery_context(
    *,
    channel: str = "whatsapp",
    outbox: list[dict[str, Any]] | None = None,
    source: str = "coaching",
):
    """Scope outbound coaching delivery for the current request."""
    ctx = {
        "channel": _normalize_channel(channel),
        "outbox": outbox if isinstance(outbox, list) else None,
        "source": str(source or "coaching").strip() or "coaching",
    }
    token = _COACHING_DELIVERY_CTX.set(ctx)
    try:
        yield
    finally:
        _COACHING_DELIVERY_CTX.reset(token)


def _get_context() -> dict[str, Any]:
    ctx = _COACHING_DELIVERY_CTX.get()
    return ctx if isinstance(ctx, dict) else {}


def _normalize_channel(raw: str | None) -> str:
    val = str(raw or "").strip().lower()
    if val == "app":
        return "app"
    return "whatsapp"


def preferred_channel_for_user(session, user_id: int, *, default: str = "whatsapp") -> str:
    """Resolve persisted preferred channel for coaching/assessment comms."""
    try:
        row = (
            session.query(UserPreference)
            .filter(UserPreference.user_id == int(user_id), UserPreference.key == "preferred_channel")
            .order_by(UserPreference.updated_at.desc())
            .first()
        )
        if not row:
            return _normalize_channel(default)
        val = str(getattr(row, "value", "") or "").strip().lower()
        return val if val in _ALLOWED_CHANNELS else _normalize_channel(default)
    except Exception:
        return _normalize_channel(default)


def preferred_channel_for_user_id(user_id: int, *, default: str = "whatsapp") -> str:
    if not user_id:
        return _normalize_channel(default)
    with SessionLocal() as s:
        return preferred_channel_for_user(s, int(user_id), default=default)


def is_app_channel_for_user(session, user_id: int) -> bool:
    return preferred_channel_for_user(session, int(user_id)) == "app"


def _quick_reply_footer(quick_replies: list[str] | None) -> str:
    if not quick_replies:
        return ""
    cleaned = [str(item).strip() for item in quick_replies if str(item or "").strip()]
    if not cleaned:
        return ""
    return "Quick replies: " + " · ".join(cleaned[:3])


def _append_quick_reply_footer(text: str, quick_replies: list[str] | None) -> str:
    footer = _quick_reply_footer(quick_replies)
    if not footer:
        return text
    if "quick replies:" in text.lower():
        return text
    sep = "\n\n" if text else ""
    return f"{text}{sep}{footer}".strip()


def _log_app_outbound(
    *,
    user: User,
    text: str,
    source: str,
    category: str | None = None,
    meta: dict[str, Any] | None = None,
    outbox: list[dict[str, Any]] | None = None,
) -> None:
    created_at = datetime.utcnow()
    if isinstance(outbox, list):
        outbox.append(
            {
                "direction": "outbound",
                "channel": "app",
                "text": text,
                "created_at": created_at.isoformat(),
            }
        )

    payload_meta: dict[str, Any] = {
        "source": source,
        "surface": "coaching_chat",
    }
    if category:
        payload_meta["category"] = category
    if isinstance(meta, dict):
        payload_meta.update(meta)

    try:
        from .message_log import write_log

        phone = str(getattr(user, "phone", "") or "").replace("whatsapp:", "").strip() or None
        write_log(
            phone_e164=phone,
            direction="outbound",
            text=text,
            category=category,
            twilio_sid=None,
            user=user,
            channel="app",
            meta=payload_meta,
            created_at=created_at,
        )
    except Exception as e:
        print(f"[delivery] app outbound logging failed: {e!r}")


def resolve_delivery_channel(user: User, *, force_channel: str | None = None) -> str:
    forced = _normalize_channel(force_channel)
    if force_channel:
        return forced

    ctx = _get_context()
    ctx_channel = _normalize_channel(ctx.get("channel"))
    if ctx_channel in _ALLOWED_CHANNELS and str(ctx.get("channel") or "").strip():
        return ctx_channel

    try:
        user_id = int(getattr(user, "id", 0) or 0)
    except Exception:
        user_id = 0
    if user_id <= 0:
        return "whatsapp"
    return preferred_channel_for_user_id(user_id)


def send_coaching_text(
    *,
    user: User,
    text: str,
    to: str | None = None,
    category: str | None = None,
    quick_replies: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    source: str | None = None,
    force_channel: str | None = None,
) -> str:
    msg = str(text or "").strip()
    if not msg:
        raise ValueError("Message text is empty")

    ctx = _get_context()
    channel = resolve_delivery_channel(user, force_channel=force_channel)
    if channel == "app":
        msg_out = _append_quick_reply_footer(msg, quick_replies)
        payload_meta = dict(meta or {})
        if quick_replies:
            payload_meta["quick_replies"] = [
                str(item).strip() for item in quick_replies if str(item or "").strip()
            ][:3]
        _log_app_outbound(
            user=user,
            text=msg_out,
            source=str(source or ctx.get("source") or "coaching"),
            category=category,
            meta=payload_meta,
            outbox=ctx.get("outbox"),
        )
        return "app"

    target = to or getattr(user, "phone", None)
    try:
        return send_whatsapp(
            text=msg,
            to=target,
            category=category,
            quick_replies=quick_replies,
        )
    except Exception as e:
        print(f"[delivery] whatsapp send failed for user_id={getattr(user, 'id', None)} err={e!r}")
        raise


def send_coaching_media(
    *,
    user: User,
    media_url: str,
    caption: str | None = None,
    to: str | None = None,
    category: str | None = None,
    quick_replies: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    source: str | None = None,
    force_channel: str | None = None,
) -> str:
    media = str(media_url or "").strip()
    if not media:
        raise ValueError("media_url is required")

    channel = resolve_delivery_channel(user, force_channel=force_channel)
    if channel == "app":
        caption_txt = str(caption or "").strip()
        text = f"{caption_txt}\n\n{media}".strip() if caption_txt else media
        meta_payload = dict(meta or {})
        meta_payload["media_url"] = media
        return send_coaching_text(
            user=user,
            text=text,
            to=to,
            category=category,
            quick_replies=quick_replies,
            meta=meta_payload,
            source=source,
            force_channel="app",
        )

    target = to or getattr(user, "phone", None)
    try:
        return send_whatsapp_media(
            to=target,
            media_url=media,
            caption=caption,
            category=category,
            quick_replies=quick_replies,
        )
    except Exception as e:
        print(f"[delivery] whatsapp media send failed for user_id={getattr(user, 'id', None)} err={e!r}")
        raise
