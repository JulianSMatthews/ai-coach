# app/nudges.py
from __future__ import annotations

import os
import queue
import re
import threading
import time
import json
import base64
import urllib.request
import urllib.error
from datetime import datetime, time as dt_time, timedelta

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from .config import settings
from .debug_utils import debug_log, debug_enabled
from .message_log import write_log
from .usage import log_usage_event, estimate_whatsapp_cost
from .models import User
from .virtual_clock import get_virtual_now_for_user
from .db import SessionLocal, engine

BUSINESS_START = dt_time(9, 0)
BUSINESS_END   = dt_time(19, 0)


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
_MAX_QUICK_REPLIES = 3
_QUICK_REPLY_TITLE_LIMIT = 20
_SESSION_REOPEN_ENV = "TWILIO_REOPEN_CONTENT_SID"
_SESSION_REOPEN_TYPE = "session-reopen"
_QUICK_REPLY_TYPE = "quick-reply"
_BUTTON_CTA = "Please always respond by tapping a button (this keeps our support going)."
_SESSION_REOPEN_DEFAULT_SENTENCE = "Please tap below to continue your wellbeing journey."
_SESSION_REOPEN_DEFAULT_BUTTON_TITLE = "Continue coaching"
_SESSION_REOPEN_DEFAULT_BUTTON_ID = "continue_coaching"
_SESSION_REOPEN_DEFAULT_BODY = (
    "Hi {{1}}, {{2}} from HealthSense here. "
    "I'm ready to continue your coaching. {{3}}"
)
_QR_BOOTSTRAP_ATTEMPTS: dict[int, float] = {}
_QR_BOOTSTRAP_MIN_INTERVAL = 60.0


def _clean_quick_replies(replies: list[str] | None) -> list[str]:
    if not replies:
        return []
    cleaned = [str(r).strip() for r in replies if str(r or "").strip()]
    return cleaned[:_MAX_QUICK_REPLIES]


def _split_quick_reply(reply: str) -> tuple[str, str]:
    """
    Allow optional payload with 'title||payload'. Falls back to title for payload.
    """
    raw = (reply or "").strip()
    if "||" in raw:
        title, payload = raw.split("||", 1)
        title = title.strip()
        payload = payload.strip()
        return title, payload or title
    return raw, raw


def _truncate_quick_reply_title(title: str) -> str:
    t = (title or "").strip()
    if len(t) <= _QUICK_REPLY_TITLE_LIMIT:
        return t
    return t[:_QUICK_REPLY_TITLE_LIMIT].rstrip()


def _quick_reply_footer(replies: list[str] | None) -> str:
    cleaned = _clean_quick_replies(replies)
    if not cleaned:
        return ""
    titles = []
    for r in cleaned:
        title, _payload = _split_quick_reply(r)
        if title:
            titles.append(_truncate_quick_reply_title(title))
    if not titles:
        return ""
    return "Quick replies: " + " · ".join(titles)


def _append_quick_replies(text: str | None, replies: list[str] | None) -> str | None:
    if not text:
        return text
    footer = _quick_reply_footer(replies)
    if not footer:
        return text
    if "quick replies:" in text.lower():
        return text
    sep = "\n\n" if not text.endswith("\n") else "\n"
    return f"{text}{sep}{footer}"


def _sanitize_whatsapp_template_text(text: str | None) -> str | None:
    if not text:
        return text
    cleaned = str(text).replace("\r\n", "\n")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{2,}", "\n", cleaned)
    return cleaned.strip()


def get_default_session_reopen_message_text() -> str:
    raw = (os.getenv("TWILIO_REOPEN_DEFAULT_MESSAGE") or "").strip()
    return raw or _SESSION_REOPEN_DEFAULT_SENTENCE


def get_default_session_reopen_coach_name() -> str:
    raw = (os.getenv("COACH_NAME") or "").strip()
    return raw or "Gia"


def get_default_session_reopen_button_title() -> str:
    raw = (os.getenv("TWILIO_REOPEN_BUTTON_TITLE") or "").strip()
    return raw or _SESSION_REOPEN_DEFAULT_BUTTON_TITLE


def build_session_reopen_template_variables(
    *,
    user_first_name: str | None,
    coach_name: str | None = None,
    message_text: str | None = None,
) -> dict[str, str]:
    first = (user_first_name or "").strip().title() or "there"
    coach = (coach_name or "").strip() or get_default_session_reopen_coach_name()
    sentence = (message_text or "").strip() or get_default_session_reopen_message_text()
    return {
        "1": first,
        "2": coach,
        "3": sentence,
    }


def append_button_cta(text: str | None) -> str | None:
    if not text:
        return text
    lowered = text.lower()
    if "tap a button" in lowered or "button below" in lowered:
        return text
    sep = "\n\n" if not text.endswith("\n") else "\n"
    return f"{text}{sep}{_BUTTON_CTA}"


def _quick_reply_content_sid(count: int) -> str | None:
    if count <= 0:
        return None
    return (os.getenv(f"TWILIO_QR_CONTENT_SID_{count}") or "").strip() or None


def _maybe_bootstrap_quick_replies(count: int) -> bool:
    if count <= 0:
        return False
    now = time.monotonic()
    last = _QR_BOOTSTRAP_ATTEMPTS.get(count, 0.0)
    if now - last < _QR_BOOTSTRAP_MIN_INTERVAL:
        return False
    _QR_BOOTSTRAP_ATTEMPTS[count] = now
    try:
        ensure_quick_reply_templates(always_log=debug_enabled())
    except Exception:
        return True
    return True


def _quick_reply_content_vars(text: str, replies: list[str]) -> dict[str, str]:
    cleaned = _clean_quick_replies(replies)
    vars_map: dict[str, str] = {"1": text}
    idx = 2
    for raw in cleaned:
        title, payload = _split_quick_reply(raw)
        title = _truncate_quick_reply_title(title)
        vars_map[str(idx)] = title
        vars_map[str(idx + 1)] = payload or title
        idx += 2
    return vars_map


def _ensure_twilio_templates_table() -> None:
    try:
        from .models import TwilioTemplate
        TwilioTemplate.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass


def _get_twilio_template_row(template_type: str, button_count: int | None = None):
    try:
        from .models import TwilioTemplate
        with SessionLocal() as s:
            q = s.query(TwilioTemplate).filter(
                TwilioTemplate.provider == "twilio",
                TwilioTemplate.template_type == template_type,
            )
            if button_count is None:
                q = q.filter(TwilioTemplate.button_count.is_(None))
            else:
                q = q.filter(TwilioTemplate.button_count == int(button_count))
            return q.first()
    except Exception:
        return None


def _get_twilio_template_sid(template_type: str, button_count: int | None = None) -> str | None:
    row = _get_twilio_template_row(template_type, button_count)
    return getattr(row, "sid", None) if row else None


def _upsert_twilio_template(
    *,
    template_type: str,
    button_count: int | None,
    friendly_name: str | None,
    sid: str | None,
    status: str,
) -> None:
    try:
        from .models import TwilioTemplate
        with SessionLocal() as s:
            q = s.query(TwilioTemplate).filter(
                TwilioTemplate.provider == "twilio",
                TwilioTemplate.template_type == template_type,
            )
            if button_count is None:
                q = q.filter(TwilioTemplate.button_count.is_(None))
            else:
                q = q.filter(TwilioTemplate.button_count == int(button_count))
            row = q.first()
            if not row:
                row = TwilioTemplate(
                    provider="twilio",
                    template_type=template_type,
                    button_count=int(button_count) if button_count is not None else None,
                )
            row.friendly_name = friendly_name
            row.sid = sid
            row.status = status
            row.language = "en"
            row.payload = {"button_count": int(button_count)} if button_count is not None else {"purpose": template_type}
            row.last_synced_at = datetime.utcnow()
            s.add(row)
            s.commit()
    except Exception:
        pass


def _get_session_reopen_sid() -> str | None:
    sid = _get_twilio_template_sid(_SESSION_REOPEN_TYPE, None)
    if sid:
        return sid
    env_sid = (os.getenv(_SESSION_REOPEN_ENV) or "").strip() or None
    if env_sid:
        _upsert_twilio_template(
            template_type=_SESSION_REOPEN_TYPE,
            button_count=None,
            friendly_name=os.getenv("TWILIO_REOPEN_TEMPLATE_NAME", "hs_reopen"),
            sid=env_sid,
            status="active",
        )
    return env_sid


def _twilio_content_request(method: str, path: str, payload: dict | None = None) -> dict:
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
    token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
    if not sid or not token:
        raise RuntimeError("Twilio credentials missing")
    url = f"https://content.twilio.com/v1/{path.lstrip('/')}"
    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
    auth = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    req.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read().decode("utf-8")
    try:
        return json.loads(body) if body else {}
    except Exception:
        return {}


def _find_content_sid_by_name(name: str) -> str | None:
    if not name:
        return None
    try:
        data = _twilio_content_request("GET", "Content?PageSize=200")
    except Exception:
        return None
    items = data.get("contents") or data.get("items") or []
    for item in items:
        if (item.get("friendly_name") or "") == name:
            return item.get("sid") or item.get("content_sid")
    return None


def _get_content_detail(sid: str | None) -> dict:
    if not sid:
        return {}
    try:
        return _twilio_content_request("GET", f"Content/{sid}")
    except Exception:
        return {}


def _delete_content_detail(sid: str | None) -> bool:
    if not sid:
        return False
    try:
        _twilio_content_request("DELETE", f"Content/{sid}")
        return True
    except Exception:
        return False


def get_twilio_content_types(sid: str | None) -> list[str]:
    detail = _get_content_detail(sid)
    types = detail.get("types") or {}
    if not isinstance(types, dict):
        return []
    return sorted([k for k in types.keys() if k])


def _actions_need_upgrade(detail: dict) -> bool:
    types = detail.get("types") or {}
    qr = types.get("twilio/quick-reply") or {}
    actions = qr.get("actions") or []
    if not actions:
        return False
    for action in actions:
        title = (action.get("title") or "").strip()
        if not title:
            return True
        lower = title.lower()
        if lower.startswith("option ") or lower.startswith("button "):
            return True
        if "{{" not in title:
            return True
    return False


def _session_reopen_needs_upgrade(detail: dict) -> bool:
    types = detail.get("types") or {}
    qr = types.get("twilio/quick-reply") or {}
    body = (qr.get("body") or "").strip()
    actions = qr.get("actions") or []
    if body != _SESSION_REOPEN_DEFAULT_BODY:
        return True
    if not actions:
        return True
    first = actions[0] or {}
    if (first.get("title") or "").strip() != get_default_session_reopen_button_title():
        return True
    if (first.get("id") or "").strip() != _SESSION_REOPEN_DEFAULT_BUTTON_ID:
        return True
    return False


def _create_quick_reply_content(name: str, button_count: int) -> str | None:
    count = max(0, min(_MAX_QUICK_REPLIES, int(button_count)))
    if count <= 0:
        return None
    actions = []
    variables: dict[str, str] = {"1": "Message body"}
    for idx in range(count):
        title_key = str(2 + idx * 2)
        id_key = str(3 + idx * 2)
        variables[title_key] = f"Button {idx + 1} title"
        variables[id_key] = f"Button {idx + 1} id"
        actions.append({"title": f"{{{{{title_key}}}}}", "id": f"{{{{{id_key}}}}}"})
    payload = {
        "friendly_name": name,
        "language": "en",
        "variables": variables,
        "types": {
            "twilio/quick-reply": {
                "body": "{{1}}",
                "actions": actions,
            }
        },
    }
    try:
        data = _twilio_content_request("POST", "Content", payload=payload)
    except Exception:
        return None
    return data.get("sid") or data.get("content_sid")


def _create_session_reopen_content(name: str) -> str | None:
    payload = {
        "friendly_name": name,
        "language": "en",
        "variables": {
            "1": "User first name",
            "2": "Coach name",
            "3": "Prompt sentence",
        },
        "types": {
            "twilio/quick-reply": {
                "body": _SESSION_REOPEN_DEFAULT_BODY,
                "actions": [
                    {
                        "title": get_default_session_reopen_button_title(),
                        "id": _SESSION_REOPEN_DEFAULT_BUTTON_ID,
                    }
                ],
            }
        },
    }
    try:
        data = _twilio_content_request("POST", "Content", payload=payload)
    except Exception:
        return None
    return data.get("sid") or data.get("content_sid")


def ensure_quick_reply_templates(*, always_log: bool = False) -> None:
    log_lines: list[str] = []
    allow_upgrade = os.getenv("TWILIO_QR_UPGRADE", "1").strip().lower() in {"1", "true", "yes"}
    _ensure_twilio_templates_table()
    if os.getenv("TWILIO_QR_BOOTSTRAP", "1").strip().lower() not in {"1", "true", "yes"}:
        if always_log:
            print("[startup] Twilio quick replies: bootstrap disabled (TWILIO_QR_BOOTSTRAP=0).")
        return
    sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
    token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
    has_creds = bool(sid and token)
    if not has_creds and always_log:
        print("[startup] Twilio quick replies: missing TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN (syncing from DB/env only).")
    templates = {
        2: {
            "env": "TWILIO_QR_CONTENT_SID_2",
            "name": os.getenv("TWILIO_QR_TEMPLATE_NAME_2", "hs_qr_2"),
            "count": 2,
        },
        3: {
            "env": "TWILIO_QR_CONTENT_SID_3",
            "name": os.getenv("TWILIO_QR_TEMPLATE_NAME_3", "hs_qr_3"),
            "count": 3,
        },
    }
    for count, cfg in templates.items():
        env_key = cfg["env"]
        dyn_name = f"{cfg['name']}_dyn"
        db_row = _get_twilio_template_row(_QUICK_REPLY_TYPE, count)
        db_sid = getattr(db_row, "sid", None) if db_row else None
        if db_sid and not os.getenv(env_key):
            os.environ[env_key] = db_sid
            log_lines.append(f"{env_key}=db ({cfg['name']})")
        if os.getenv(env_key):
            if allow_upgrade and has_creds:
                detail = _get_content_detail(os.getenv(env_key))
                needs_upgrade = _actions_need_upgrade(detail) if detail else True
                already_dyn = bool(db_row and (getattr(db_row, "friendly_name", "") or "").endswith("_dyn"))
                if needs_upgrade and not already_dyn:
                    upgraded_name = f"{cfg['name']}_dyn"
                    upgraded_sid = _create_quick_reply_content(upgraded_name, cfg["count"])
                    if upgraded_sid:
                        os.environ[env_key] = upgraded_sid
                        log_lines.append(f"{env_key}=upgraded ({upgraded_name})")
                        _upsert_twilio_template(
                            template_type=_QUICK_REPLY_TYPE,
                            button_count=count,
                            friendly_name=upgraded_name,
                            sid=upgraded_sid,
                            status="active",
                        )
                        continue
            log_lines.append(f"{env_key}=set (env)")
            _upsert_twilio_template(
                template_type=_QUICK_REPLY_TYPE,
                button_count=count,
                friendly_name=cfg["name"],
                sid=os.getenv(env_key),
                status="active",
            )
            continue
        if not has_creds:
            log_lines.append(f"{env_key}=missing (no creds)")
            _upsert_twilio_template(
                template_type=_QUICK_REPLY_TYPE,
                button_count=count,
                friendly_name=cfg["name"],
                sid=None,
                status="missing",
            )
            continue
        # Prefer dynamic templates when available (handles DB reset using older static templates).
        found_dyn = _find_content_sid_by_name(dyn_name)
        if found_dyn:
            os.environ[env_key] = found_dyn
            debug_log("twilio content found", {"name": dyn_name, "sid": found_dyn}, tag="twilio")
            log_lines.append(f"{env_key}=found ({dyn_name})")
            _upsert_twilio_template(
                template_type=_QUICK_REPLY_TYPE,
                button_count=count,
                friendly_name=dyn_name,
                sid=found_dyn,
                status="active",
            )
            continue
        friendly = cfg["name"]
        found = _find_content_sid_by_name(friendly)
        if found:
            if allow_upgrade:
                detail = _get_content_detail(found)
                needs_upgrade = _actions_need_upgrade(detail) if detail else True
                if needs_upgrade:
                    upgraded_sid = _create_quick_reply_content(dyn_name, cfg["count"])
                    if upgraded_sid:
                        os.environ[env_key] = upgraded_sid
                        debug_log("twilio content upgraded", {"name": dyn_name, "sid": upgraded_sid}, tag="twilio")
                        log_lines.append(f"{env_key}=upgraded ({dyn_name})")
                        _upsert_twilio_template(
                            template_type=_QUICK_REPLY_TYPE,
                            button_count=count,
                            friendly_name=dyn_name,
                            sid=upgraded_sid,
                            status="active",
                        )
                        continue
            os.environ[env_key] = found
            debug_log("twilio content found", {"name": friendly, "sid": found}, tag="twilio")
            log_lines.append(f"{env_key}=found ({friendly})")
            _upsert_twilio_template(
                template_type=_QUICK_REPLY_TYPE,
                button_count=count,
                friendly_name=friendly,
                sid=found,
                status="active",
            )
            continue
        created = _create_quick_reply_content(friendly, cfg["count"])
        if created:
            os.environ[env_key] = created
            debug_log("twilio content created", {"name": friendly, "sid": created}, tag="twilio")
            log_lines.append(f"{env_key}=created ({friendly})")
            _upsert_twilio_template(
                template_type=_QUICK_REPLY_TYPE,
                button_count=count,
                friendly_name=friendly,
                sid=created,
                status="active",
            )
        else:
            log_lines.append(f"{env_key}=error ({friendly})")
            _upsert_twilio_template(
                template_type=_QUICK_REPLY_TYPE,
                button_count=count,
                friendly_name=friendly,
                sid=None,
                status="error",
            )
    reopen_name = os.getenv("TWILIO_REOPEN_TEMPLATE_NAME", "hs_reopen")
    reopen_dyn_name = f"{reopen_name}_dyn"
    reopen_row = _get_twilio_template_row(_SESSION_REOPEN_TYPE, None)
    reopen_db_sid = getattr(reopen_row, "sid", None) if reopen_row else None
    if reopen_db_sid and not os.getenv(_SESSION_REOPEN_ENV):
        os.environ[_SESSION_REOPEN_ENV] = reopen_db_sid
        log_lines.append(f"{_SESSION_REOPEN_ENV}=db ({reopen_name})")

    reopen_sid = (os.getenv(_SESSION_REOPEN_ENV) or "").strip()
    if reopen_sid:
        if allow_upgrade and has_creds:
            detail = _get_content_detail(reopen_sid)
            needs_upgrade = _session_reopen_needs_upgrade(detail) if detail else True
            already_dyn = bool(reopen_row and (getattr(reopen_row, "friendly_name", "") or "").endswith("_dyn"))
            if needs_upgrade and not already_dyn:
                upgraded_sid = _create_session_reopen_content(reopen_dyn_name)
                if upgraded_sid:
                    os.environ[_SESSION_REOPEN_ENV] = upgraded_sid
                    log_lines.append(f"{_SESSION_REOPEN_ENV}=upgraded ({reopen_dyn_name})")
                    _upsert_twilio_template(
                        template_type=_SESSION_REOPEN_TYPE,
                        button_count=None,
                        friendly_name=reopen_dyn_name,
                        sid=upgraded_sid,
                        status="active",
                    )
                    reopen_sid = upgraded_sid
        _upsert_twilio_template(
            template_type=_SESSION_REOPEN_TYPE,
            button_count=None,
            friendly_name=os.getenv("TWILIO_REOPEN_TEMPLATE_NAME", "hs_reopen"),
            sid=reopen_sid,
            status="active",
        )
        if f"{_SESSION_REOPEN_ENV}=upgraded ({reopen_dyn_name})" not in log_lines:
            log_lines.append(f"{_SESSION_REOPEN_ENV}=set (env)")
    elif not has_creds:
        log_lines.append(f"{_SESSION_REOPEN_ENV}=missing (no creds)")
        _upsert_twilio_template(
            template_type=_SESSION_REOPEN_TYPE,
            button_count=None,
            friendly_name=reopen_name,
            sid=None,
            status="missing",
        )
    else:
        found_dyn = _find_content_sid_by_name(reopen_dyn_name)
        if found_dyn:
            os.environ[_SESSION_REOPEN_ENV] = found_dyn
            debug_log("twilio content found", {"name": reopen_dyn_name, "sid": found_dyn}, tag="twilio")
            log_lines.append(f"{_SESSION_REOPEN_ENV}=found ({reopen_dyn_name})")
            _upsert_twilio_template(
                template_type=_SESSION_REOPEN_TYPE,
                button_count=None,
                friendly_name=reopen_dyn_name,
                sid=found_dyn,
                status="active",
            )
        else:
            found = _find_content_sid_by_name(reopen_name)
            if found:
                if allow_upgrade:
                    detail = _get_content_detail(found)
                    needs_upgrade = _session_reopen_needs_upgrade(detail) if detail else True
                    if needs_upgrade:
                        upgraded_sid = _create_session_reopen_content(reopen_dyn_name)
                        if upgraded_sid:
                            os.environ[_SESSION_REOPEN_ENV] = upgraded_sid
                            debug_log("twilio content upgraded", {"name": reopen_dyn_name, "sid": upgraded_sid}, tag="twilio")
                            log_lines.append(f"{_SESSION_REOPEN_ENV}=upgraded ({reopen_dyn_name})")
                            _upsert_twilio_template(
                                template_type=_SESSION_REOPEN_TYPE,
                                button_count=None,
                                friendly_name=reopen_dyn_name,
                                sid=upgraded_sid,
                                status="active",
                            )
                            found = ""
                if found:
                    os.environ[_SESSION_REOPEN_ENV] = found
                    debug_log("twilio content found", {"name": reopen_name, "sid": found}, tag="twilio")
                    log_lines.append(f"{_SESSION_REOPEN_ENV}=found ({reopen_name})")
                    _upsert_twilio_template(
                        template_type=_SESSION_REOPEN_TYPE,
                        button_count=None,
                        friendly_name=reopen_name,
                        sid=found,
                        status="active",
                    )
            else:
                created = _create_session_reopen_content(reopen_name)
                if created:
                    os.environ[_SESSION_REOPEN_ENV] = created
                    debug_log("twilio content created", {"name": reopen_name, "sid": created}, tag="twilio")
                    log_lines.append(f"{_SESSION_REOPEN_ENV}=created ({reopen_name})")
                    _upsert_twilio_template(
                        template_type=_SESSION_REOPEN_TYPE,
                        button_count=None,
                        friendly_name=reopen_name,
                        sid=created,
                        status="active",
                    )
                else:
                    log_lines.append(f"{_SESSION_REOPEN_ENV}=error ({reopen_name})")
                    _upsert_twilio_template(
                        template_type=_SESSION_REOPEN_TYPE,
                        button_count=None,
                        friendly_name=reopen_name,
                        sid=None,
                        status="error",
                    )
    if always_log:
        if log_lines:
            print("[startup] Twilio quick replies:", "; ".join(log_lines))
        else:
            print("[startup] Twilio quick replies: no changes.")


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

def _normalize_sms_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    s = str(raw).strip()
    if s.startswith("whatsapp:"):
        s = s.split("whatsapp:", 1)[1]
    if E164.match(s):
        return s if s.startswith("+") else f"+{s}"
    return None


def _lookup_user_id_for_whatsapp(to_norm: str | None) -> int | None:
    try:
        if not to_norm:
            return None
        phone = to_norm.replace("whatsapp:", "")
        with SessionLocal() as s:
            row = s.query(User).filter(User.phone == phone).one_or_none()
            return getattr(row, "id", None) if row else None
    except Exception:
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
        meta_payload: dict[str, str] = {"to": to_norm}
        created_at_override = None
        user_id = _lookup_user_id_for_whatsapp(to_norm)
        if user_id:
            virtual_now = get_virtual_now_for_user(int(user_id))
            if virtual_now is not None:
                meta_payload["virtual_date"] = virtual_now.date().isoformat()
                created_at_override = virtual_now
        write_log(
            phone_e164=phone_e164,
            direction="outbound",
            text=text,
            category=category,
            twilio_sid=twilio_sid,
            channel="whatsapp",
            meta=meta_payload,
            created_at=created_at_override,
        )
    except Exception as e:
        print(f"⚠️ outbound logging failed (non-fatal): {e!r}")


def _perform_twilio_send(
    *,
    text: str | None,
    to_norm: str,
    category: str | None,
    media_urls: list[str] | None = None,
    content_sid: str | None = None,
    content_variables: str | None = None,
) -> str:
    status_callback = (os.getenv("TWILIO_STATUS_CALLBACK_URL") or "").strip()
    if not status_callback:
        base = (os.getenv("API_PUBLIC_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip().rstrip("/")
        if base:
            status_callback = f"{base}/webhooks/twilio-status"
    if status_callback and not status_callback.startswith(("http://", "https://")):
        status_callback = f"https://{status_callback.lstrip('/')}"
    client = _twilio_client()
    if client is None:
        raise RuntimeError("Twilio client unavailable")
    if not content_sid and (not text or not str(text).strip()) and not media_urls:
        raise ValueError("Cannot send empty WhatsApp message (no text or media).")
    from_norm = _normalize_whatsapp_phone(getattr(settings, "TWILIO_FROM", None))
    if not from_norm:
        raise RuntimeError("TWILIO_FROM must be a valid WhatsApp-enabled number (e.g., whatsapp:+1415...)")

    lock = _lock_for_destination(to_norm)
    with lock:
        _throttle_destination(to_norm)
        try:
            if content_sid:
                msg = client.messages.create(
                    from_=from_norm,
                    to=to_norm,
                    content_sid=content_sid,
                    content_variables=content_variables,
                    status_callback=status_callback or None,
                )
            else:
                msg = client.messages.create(
                    from_=from_norm,
                    body=text,
                    media_url=media_urls,
                    to=to_norm,
                    status_callback=status_callback or None,
                )
        except TwilioRestException as exc:
            code = getattr(exc, "code", None)
            reopened = False
            if code == 63016:
                reopen_sid = _get_session_reopen_sid()
                if reopen_sid and reopen_sid != content_sid:
                    try:
                        user_id = _lookup_user_id_for_whatsapp(to_norm)
                        first_name = None
                        if user_id:
                            try:
                                with SessionLocal() as s:
                                    u = s.query(User).get(int(user_id))
                                    first_name = (getattr(u, "first_name", None) or None) if u else None
                            except Exception:
                                first_name = None
                        reopen_vars = json.dumps(
                            build_session_reopen_template_variables(
                                user_first_name=first_name,
                                coach_name=None,
                                message_text=text or get_default_session_reopen_message_text(),
                            )
                        )
                        msg = client.messages.create(
                            from_=from_norm,
                            to=to_norm,
                            content_sid=reopen_sid,
                            content_variables=reopen_vars,
                            status_callback=status_callback or None,
                        )
                        reopened = True
                        content_sid = reopen_sid
                        content_variables = reopen_vars
                    except TwilioRestException as exc2:
                        print(f"❌ Twilio reopen template failed to {to_norm}: {exc2.msg if hasattr(exc2, 'msg') else exc2}")
            if not reopened:
                print(f"❌ Twilio send failed to {to_norm}: {exc.msg if hasattr(exc, 'msg') else exc} (code={code})")
                if code == 63016:
                    print("💡 WhatsApp session expired (>24h). Configure TWILIO_REOPEN_CONTENT_SID for an approved template.")
                raise
        try:
            _LAST_SEND_MONO[to_norm] = time.monotonic()
        except Exception:
            pass

    phone_e164 = to_norm.replace("whatsapp:", "")
    try:
        _try_write_outbound_log(
            phone_e164=phone_e164,
            text=text or "(media)",
            category=category,
            twilio_sid=getattr(msg, "sid", None) or "",
            to_norm=to_norm,
        )
    except Exception as e:
        print(f"⚠️ outbound logging wrapper failed (non-fatal): {e!r}")

    debug_log(
        "twilio send accepted",
        {
            "sid": getattr(msg, "sid", None),
            "status": getattr(msg, "status", None),
            "to": to_norm,
            "media": bool(media_urls),
        },
        tag="twilio",
    )

    return getattr(msg, "sid", "")

def _perform_twilio_sms(*, text: str, to_norm: str) -> str:
    client = _twilio_client()
    if client is None:
        raise RuntimeError("Twilio client unavailable")
    if not text or not str(text).strip():
        raise ValueError("Cannot send empty SMS message.")
    sms_from = (os.getenv("TWILIO_SMS_FROM") or "").strip()
    if not sms_from or not E164.match(sms_from):
        raise RuntimeError("TWILIO_SMS_FROM must be a valid E.164 number for SMS.")
    msg = client.messages.create(
        from_=sms_from,
        to=to_norm,
        body=text,
    )
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
        media_urls = job.get("media_urls")
        content_sid = job.get("content_sid")
        content_variables = job.get("content_variables")
        event = job["event"]
        result = job["result"]
        try:
            sid = _perform_twilio_send(
                text=text,
                to_norm=dest,
                category=category,
                media_urls=media_urls,
                content_sid=content_sid,
                content_variables=content_variables,
            )
            result["sid"] = sid
        except Exception as e:
            result["error"] = e
        finally:
            event.set()
            q.task_done()


def _enqueue_and_send(
    *,
    to_norm: str,
    text: str | None,
    category: str | None,
    media_urls: list[str] | None = None,
    content_sid: str | None = None,
    content_variables: str | None = None,
) -> str:
    q = _ensure_queue_worker(to_norm)
    event = threading.Event()
    result: dict[str, str | Exception] = {}
    q.put(
        {
            "text": text,
            "category": category,
            "media_urls": media_urls,
            "content_sid": content_sid,
            "content_variables": content_variables,
            "event": event,
            "result": result,
        }
    )
    event.wait()
    if "error" in result:
        raise result["error"]
    return str(result.get("sid", ""))


def send_whatsapp(
    text: str,
    to: str | None = None,
    category: str | None = None,
    quick_replies: list[str] | None = None,
) -> str:
    """
    Primary send function. Logs only after Twilio accepts.
    Requires an explicit `to`; will NOT fallback to any env recipient.
    """
    def _chunk_text(raw: str, limit: int) -> list[str]:
        cleaned = (raw or "").replace("\r\n", "\n").strip()
        if not cleaned:
            return []
        if len(cleaned) <= limit:
            return [cleaned]
        chunks: list[str] = []
        remaining = cleaned
        while len(remaining) > limit:
            cut = remaining.rfind("\n", 0, limit + 1)
            if cut < max(40, int(limit * 0.4)):
                cut = remaining.rfind(" ", 0, limit + 1)
            if cut <= 0:
                cut = limit
            chunk = remaining[:cut].rstrip()
            if not chunk:
                chunk = remaining[:limit].rstrip()
            chunks.append(chunk)
            remaining = remaining[cut:].lstrip()
        if remaining:
            chunks.append(remaining)
        return chunks

    def _track_usage(
        *,
        sid: str,
        to_norm: str,
        unit_type: str,
        text_len: int | None = None,
        category: str | None = None,
        meta: dict | None = None,
    ) -> None:
        try:
            user_id = _lookup_user_id_for_whatsapp(to_norm)
            cost_est, rate, rate_source = estimate_whatsapp_cost(unit_type, units=1.0)
            payload = {
                "category": category,
                "text_len": text_len,
                "rate": rate,
                "rate_source": rate_source,
            }
            if meta:
                payload.update(meta)
            log_usage_event(
                user_id=user_id,
                provider="twilio",
                product="whatsapp",
                model=None,
                units=1.0,
                unit_type=unit_type,
                cost_estimate=cost_est if cost_est else None,
                request_id=sid,
                tag=None,
                meta=payload,
            )
        except Exception as e:
            print(f"[usage] whatsapp log failed: {e}")

    def _send_single(
        message_text: str,
        *,
        to_norm: str,
        category: str | None,
        quick_replies: list[str] | None,
    ) -> str:
        sid = None
        content_vars = None
        qr_list = _clean_quick_replies(quick_replies)
        if qr_list:
            qr_count = len(qr_list)
            env_sid = _quick_reply_content_sid(qr_count)
            db_sid = None if env_sid else _get_twilio_template_sid(_QUICK_REPLY_TYPE, qr_count)
            sid = env_sid or db_sid
            bootstrap_attempted = False
            if not sid:
                bootstrap_attempted = _maybe_bootstrap_quick_replies(qr_count)
                env_sid = _quick_reply_content_sid(qr_count)
                db_sid = None if env_sid else _get_twilio_template_sid(_QUICK_REPLY_TYPE, qr_count)
                sid = env_sid or db_sid
            debug_log(
                "quick reply selection",
                {
                    "to": to_norm,
                    "count": qr_count,
                    "env_sid": env_sid,
                    "db_sid": db_sid,
                    "selected_sid": sid,
                    "bootstrap_attempted": bootstrap_attempted,
                    "titles": [_split_quick_reply(r)[0] for r in qr_list],
                },
                tag="twilio",
            )
        if sid:
            message_text = _sanitize_whatsapp_template_text(message_text) or message_text
            vars_map = _quick_reply_content_vars(message_text, qr_list)
            content_vars = json.dumps(vars_map)
        else:
            message_text = _append_quick_replies(message_text, quick_replies) or message_text
        if not message_text or not str(message_text).strip():
            raise ValueError("Message text is empty")
        sid = _enqueue_and_send(
            to_norm=to_norm,
            text=message_text,
            category=category,
            media_urls=None,
            content_sid=sid,
            content_variables=content_vars if sid else None,
        )
        _track_usage(
            sid=sid,
            to_norm=to_norm,
            unit_type="message_text",
            text_len=len(message_text or ""),
            category=category,
            meta={"has_quick_replies": bool(qr_list)},
        )
        return sid

    if not text or not str(text).strip():
        raise ValueError("Message text is empty")

    to_norm = _normalize_whatsapp_phone(to) if to else None
    if not to_norm:
        # Explicitly refuse to send without a valid recipient
        raise ValueError("Recipient phone missing or invalid (expected E.164). No fallback is permitted.")

    max_chars = int(os.getenv("TWILIO_WHATSAPP_MAX_CHARS", "1600") or "1600")
    chunks = _chunk_text(str(text), max_chars)
    if len(chunks) > 1:
        last_sid = ""
        for chunk in chunks:
            last_sid = _send_single(chunk, to_norm=to_norm, category=category, quick_replies=None)
        if quick_replies:
            last_sid = _send_single(
                "Tap a button to reply.",
                to_norm=to_norm,
                category=category,
                quick_replies=quick_replies,
            )
        result_sid = last_sid
    else:
        result_sid = _send_single(str(text), to_norm=to_norm, category=category, quick_replies=quick_replies)

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


def send_sms(text: str, to: str | None = None) -> str:
    if not text or not str(text).strip():
        raise ValueError("Message text is empty")
    to_norm = _normalize_sms_phone(to) if to else None
    if not to_norm:
        raise ValueError("Recipient phone missing or invalid (expected E.164).")
    return _perform_twilio_sms(text=text, to_norm=to_norm)


def send_whatsapp_media(
    *,
    media_url: str,
    to: str | None = None,
    caption: str | None = None,
    category: str | None = None,
    quick_replies: list[str] | None = None,
) -> str:
    """
    Send a WhatsApp media message (e.g., audio) with optional caption.
    Requires a valid HTTPS-accessible media_url.
    """
    _ = quick_replies  # quick replies are not supported on media messages
    to_norm = _normalize_whatsapp_phone(to) if to else None
    if not to_norm:
        raise ValueError("Recipient phone missing or invalid (expected E.164). No fallback is permitted.")
    media_url = (media_url or "").strip()
    if not media_url:
        raise ValueError("media_url is required for send_whatsapp_media")
    result_sid = _enqueue_and_send(
        to_norm=to_norm,
        text=caption,
        category=category,
        media_urls=[media_url],
    )
    try:
        cost_est, rate, rate_source = estimate_whatsapp_cost("message_media", units=1.0)
        user_id = _lookup_user_id_for_whatsapp(to_norm)
        log_usage_event(
            user_id=user_id,
            provider="twilio",
            product="whatsapp",
            model=None,
            units=1.0,
            unit_type="message_media",
            cost_estimate=cost_est if cost_est else None,
            request_id=result_sid,
            tag=None,
            meta={
                "category": category,
                "caption_len": len(caption or ""),
                "rate": rate,
                "rate_source": rate_source,
                "media_url": media_url,
            },
        )
    except Exception as e:
        print(f"[usage] whatsapp media log failed: {e}")
    return result_sid


def send_whatsapp_template(
    *,
    to: str | None,
    template_sid: str,
    variables: dict[str, str] | None = None,
    category: str | None = None,
) -> str:
    """
    Send a WhatsApp template message via Twilio Content API.
    Variables should be a dict of string keys to values, e.g. {"1": "Message body"}.
    """
    to_norm = _normalize_whatsapp_phone(to) if to else None
    if not to_norm:
        raise ValueError("Recipient phone missing or invalid (expected E.164). No fallback is permitted.")
    if not template_sid:
        raise ValueError("template_sid is required for send_whatsapp_template")
    vars_payload = json.dumps(variables or {})
    result_sid = _enqueue_and_send(
        to_norm=to_norm,
        text=None,
        category=category,
        content_sid=template_sid,
        content_variables=vars_payload,
    )
    try:
        cost_est, rate, rate_source = estimate_whatsapp_cost("message_template", units=1.0)
        user_id = _lookup_user_id_for_whatsapp(to_norm)
        log_usage_event(
            user_id=user_id,
            provider="twilio",
            product="whatsapp",
            model=None,
            units=1.0,
            unit_type="message_template",
            cost_estimate=cost_est if cost_est else None,
            request_id=result_sid,
            tag=None,
            meta={
                "category": category,
                "template_sid": template_sid,
                "rate": rate,
                "rate_source": rate_source,
            },
        )
    except Exception as e:
        print(f"[usage] whatsapp template log failed: {e}")
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
