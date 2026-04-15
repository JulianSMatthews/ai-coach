from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from statistics import median
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests
from sqlalchemy import inspect, text

from .db import engine
from .models import UserPreference, WearableConnection, WearableDailyMetric, WearableSyncRun


OURA_AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"
OURA_API_BASE_URL = "https://api.ouraring.com"

WHOOP_AUTHORIZE_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE_URL = "https://api.prod.whoop.com/developer/v2"

FITBIT_AUTHORIZE_URL = "https://www.fitbit.com/oauth2/authorize"
FITBIT_TOKEN_URL = "https://api.fitbit.com/oauth2/token"
FITBIT_API_BASE_URL = "https://api.fitbit.com"

DEFAULT_OURA_SCOPE = "daily personal email"
DEFAULT_WHOOP_SCOPE = "offline read:profile read:recovery read:cycles read:sleep"
DEFAULT_FITBIT_SCOPE = "activity heartrate sleep profile offline_access"

DEFAULT_OURA_LOOKBACK_DAYS = 30
DEFAULT_WHOOP_LOOKBACK_DAYS = 30
DEFAULT_FITBIT_LOOKBACK_DAYS = 30
APPLE_HEALTH_PROVIDER = "apple_health"
APPLE_HEALTH_BASELINE_DAYS = 14
APPLE_HEALTH_BASELINE_MIN_POINTS = 7
APPLE_HEALTH_OPTIMUM_DELTA_BPM = -2.0
APPLE_HEALTH_ELEVATED_DELTA_BPM = 3.0
APPLE_HEALTH_HRV_MIN_DELTA_MS = 5.0
APPLE_HEALTH_HRV_DELTA_RATIO = 0.10
BIOMETRICS_PREF_KEY = "biometrics_preferences"
BIOMETRIC_METRIC_KEYS = ("resting_hr", "hrv", "steps", "exercise_minutes")
BIOMETRIC_DEVICE_OPTIONS = (
    "auto",
    "apple_watch",
    "iphone",
    "garmin",
    "whoop",
    "fitbit",
    "oura",
    "none",
)
BIOMETRIC_DEVICE_LABELS = {
    "auto": "Auto-detect",
    "apple_watch": "Apple Watch",
    "iphone": "iPhone",
    "garmin": "Garmin",
    "whoop": "WHOOP",
    "fitbit": "Fitbit",
    "oura": "Oura",
    "none": "Do not assume a device",
}
BIOMETRIC_METRIC_DEFINITIONS = {
    "resting_hr": {
        "label": "Resting HR",
        "preference_key": "use_resting_hr",
        "default_enabled": True,
    },
    "hrv": {
        "label": "HRV",
        "preference_key": "use_hrv",
        "default_enabled": True,
    },
    "steps": {
        "label": "Steps",
        "preference_key": "use_steps",
        "default_enabled": True,
    },
    "exercise_minutes": {
        "label": "Exercise minutes",
        "preference_key": "use_exercise_minutes",
        "default_enabled": True,
    },
}

WEARABLE_METRIC_FIELDS = (
    "sleep_seconds",
    "sleep_score",
    "readiness_score",
    "hrv_ms",
    "resting_hr_bpm",
    "steps",
    "active_minutes",
    "calories",
    "strain_score",
)

_WEARABLE_STATE_VERSION = 1
_WEARABLE_STATE_RUNTIME_SECRET = secrets.token_urlsafe(48)
_WEARABLE_SCHEMA_READY = False
_WEARABLE_DAILY_METRIC_COLUMN_TYPES = {
    "sleep_seconds": "integer",
    "sleep_score": "integer",
    "readiness_score": "integer",
    "hrv_ms": "double precision",
    "resting_hr_bpm": "double precision",
    "steps": "integer",
    "active_minutes": "integer",
    "calories": "integer",
    "strain_score": "double precision",
}


def ensure_wearables_schema() -> None:
    global _WEARABLE_SCHEMA_READY
    if _WEARABLE_SCHEMA_READY:
        return
    try:
        WearableConnection.__table__.create(bind=engine, checkfirst=True)
        WearableSyncRun.__table__.create(bind=engine, checkfirst=True)
        WearableDailyMetric.__table__.create(bind=engine, checkfirst=True)
        inspector = inspect(engine)
        existing_columns = {
            str(column.get("name") or "").strip().lower()
            for column in inspector.get_columns("wearable_daily_metrics")
        }
        missing_columns = [
            (name, column_type)
            for name, column_type in _WEARABLE_DAILY_METRIC_COLUMN_TYPES.items()
            if name not in existing_columns
        ]
        if missing_columns:
            with engine.begin() as conn:
                dialect = str(getattr(conn.dialect, "name", "") or "").strip().lower()
                for column_name, column_type in missing_columns:
                    if dialect == "postgresql":
                        conn.execute(
                            text(
                                f"ALTER TABLE wearable_daily_metrics "
                                f"ADD COLUMN IF NOT EXISTS {column_name} {column_type};"
                            )
                        )
                    else:
                        conn.execute(
                            text(
                                f"ALTER TABLE wearable_daily_metrics "
                                f"ADD COLUMN {column_name} {column_type};"
                            )
                        )
        _WEARABLE_SCHEMA_READY = True
    except Exception:
        _WEARABLE_SCHEMA_READY = False
        raise


@dataclass(frozen=True)
class WearableProviderDefinition:
    key: str
    label: str
    availability: str
    description: str
    supports_web_oauth: bool
    partnership_required: bool = False
    requires_native_app: bool = False
    connect_implemented: bool = False
    sync_implemented: bool = False
    default_note: str | None = None


PROVIDER_DEFINITIONS: dict[str, WearableProviderDefinition] = {
    "oura": WearableProviderDefinition(
        key="oura",
        label="Oura",
        availability="ready",
        description="Daily sleep, recovery, and readiness summaries via Oura Cloud API.",
        supports_web_oauth=True,
        connect_implemented=True,
        sync_implemented=True,
    ),
    "whoop": WearableProviderDefinition(
        key="whoop",
        label="WHOOP",
        availability="ready",
        description="Recovery, sleep, and strain data through the WHOOP developer API.",
        supports_web_oauth=True,
        connect_implemented=True,
        sync_implemented=True,
    ),
    "fitbit": WearableProviderDefinition(
        key="fitbit",
        label="Fitbit",
        availability="ready",
        description="Sleep, heart-rate, and activity summaries from the Fitbit Web API.",
        supports_web_oauth=True,
        connect_implemented=True,
        sync_implemented=True,
    ),
    "garmin": WearableProviderDefinition(
        key="garmin",
        label="Garmin",
        availability="pending_partnership",
        description="Garmin Connect / Health API access requires Garmin approval.",
        supports_web_oauth=True,
        partnership_required=True,
        default_note="Awaiting Garmin Connect Developer Program approval and credentials.",
    ),
    APPLE_HEALTH_PROVIDER: WearableProviderDefinition(
        key=APPLE_HEALTH_PROVIDER,
        label="Apple Health",
        availability="requires_app",
        description="Apple Health needs an iPhone app bridge using HealthKit.",
        supports_web_oauth=False,
        requires_native_app=True,
        default_note="Requires a native iPhone app or wrapper to read HealthKit data.",
    ),
}


def _default_biometrics_preferences() -> dict[str, Any]:
    return {
        "device": "auto",
        "metrics": {
            metric_key: {"enabled": bool(definition.get("default_enabled", True))}
            for metric_key, definition in BIOMETRIC_METRIC_DEFINITIONS.items()
        },
    }


def _coerce_pref_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    token = str(value).strip().lower()
    if token in {"1", "true", "yes", "on", "enabled", "include"}:
        return True
    if token in {"0", "false", "no", "off", "disabled", "exclude"}:
        return False
    return bool(default)


def _normalise_biometrics_preferences_payload(
    payload: dict[str, Any] | None,
    *,
    base: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    current = base if isinstance(base, dict) else _default_biometrics_preferences()
    current_metrics = current.get("metrics") if isinstance(current.get("metrics"), dict) else {}
    raw_device = (
        source.get("device")
        or source.get("biometric_device")
        or current.get("device")
        or "auto"
    )
    device = str(raw_device or "auto").strip().lower()
    if device not in BIOMETRIC_DEVICE_OPTIONS:
        device = "auto"

    metrics_payload = source.get("metrics") if isinstance(source.get("metrics"), dict) else {}
    metrics: dict[str, Any] = {}
    for metric_key, definition in BIOMETRIC_METRIC_DEFINITIONS.items():
        current_metric = current_metrics.get(metric_key) if isinstance(current_metrics.get(metric_key), dict) else {}
        default_enabled = bool(definition.get("default_enabled", True))
        current_enabled = _coerce_pref_bool(current_metric.get("enabled"), default_enabled)
        raw_metric_payload = metrics_payload.get(metric_key)
        raw_enabled: Any = None
        if isinstance(raw_metric_payload, dict):
            raw_enabled = raw_metric_payload.get("enabled")
        elif raw_metric_payload is not None:
            raw_enabled = raw_metric_payload
        preference_key = str(definition.get("preference_key") or "").strip()
        if preference_key and preference_key in source:
            raw_enabled = source.get(preference_key)
        metrics[metric_key] = {"enabled": _coerce_pref_bool(raw_enabled, current_enabled)}

    return {
        "device": device,
        "device_label": BIOMETRIC_DEVICE_LABELS.get(device, "Auto-detect"),
        "metrics": metrics,
    }


def get_biometrics_preferences(session, *, user_id: int) -> dict[str, Any]:
    row = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == int(user_id), UserPreference.key == BIOMETRICS_PREF_KEY)
        .one_or_none()
    )
    payload: dict[str, Any] = {}
    if row and getattr(row, "value", None):
        try:
            parsed = json.loads(str(row.value or ""))
            payload = parsed if isinstance(parsed, dict) else {}
        except Exception:
            payload = {}
    preferences = _normalise_biometrics_preferences_payload(payload)
    if row and getattr(row, "updated_at", None):
        preferences["updated_at"] = row.updated_at.isoformat()
    return preferences


def save_biometrics_preferences(
    session,
    *,
    user_id: int,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    current = get_biometrics_preferences(session, user_id=int(user_id))
    preferences = _normalise_biometrics_preferences_payload(payload, base=current)
    stored_preferences = {
        "device": preferences.get("device") or "auto",
        "metrics": preferences.get("metrics") if isinstance(preferences.get("metrics"), dict) else {},
    }
    row = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == int(user_id), UserPreference.key == BIOMETRICS_PREF_KEY)
        .one_or_none()
    )
    if row is None:
        session.add(
            UserPreference(
                user_id=int(user_id),
                key=BIOMETRICS_PREF_KEY,
                value=json.dumps(stored_preferences, separators=(",", ":"), sort_keys=True),
            )
        )
    else:
        row.value = json.dumps(stored_preferences, separators=(",", ":"), sort_keys=True)
        session.add(row)
    return preferences


def biometric_metric_enabled(preferences: dict[str, Any] | None, metric_key: str) -> bool:
    prefs = preferences if isinstance(preferences, dict) else {}
    metrics = prefs.get("metrics") if isinstance(prefs.get("metrics"), dict) else {}
    metric = metrics.get(metric_key) if isinstance(metrics.get(metric_key), dict) else {}
    default_enabled = bool((BIOMETRIC_METRIC_DEFINITIONS.get(metric_key) or {}).get("default_enabled", True))
    return _coerce_pref_bool(metric.get("enabled"), default_enabled)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(token: str) -> bytes:
    pad_len = (-len(token)) % 4
    return base64.urlsafe_b64decode(f"{token}{'=' * pad_len}".encode("ascii"))


def _oauth_state_secret() -> str:
    return (
        (os.getenv("WEARABLE_OAUTH_STATE_SECRET") or "").strip()
        or (os.getenv("ADMIN_API_TOKEN") or "").strip()
        or _WEARABLE_STATE_RUNTIME_SECRET
    )


def _sign_state_body(body_token: str) -> str:
    digest = hmac.new(
        _oauth_state_secret().encode("utf-8"),
        body_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64url_encode(digest)


def mint_wearable_oauth_state(
    *,
    user_id: int,
    provider: str,
    redirect_path: str | None = None,
    ttl_seconds: int = 900,
) -> str:
    payload = {
        "v": int(_WEARABLE_STATE_VERSION),
        "u": int(user_id),
        "p": str(provider).strip().lower(),
        "iat": int(time.time()),
        "exp": int(time.time()) + max(60, int(ttl_seconds)),
        "nonce": secrets.token_urlsafe(12),
        "redirect_path": str(redirect_path or "").strip() or None,
    }
    body = _b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = _sign_state_body(body)
    return f"{body}.{sig}"


def parse_wearable_oauth_state(token: str | None) -> dict[str, Any] | None:
    raw = str(token or "").strip()
    if not raw or "." not in raw:
        return None
    body, sig = raw.rsplit(".", 1)
    if not hmac.compare_digest(_sign_state_body(body), sig):
        return None
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    try:
        if int(payload.get("v") or 0) != int(_WEARABLE_STATE_VERSION):
            return None
        if int(payload.get("exp") or 0) < int(time.time()):
            return None
        payload["u"] = int(payload.get("u") or 0)
        payload["p"] = str(payload.get("p") or "").strip().lower()
    except Exception:
        return None
    if payload["u"] <= 0 or not payload["p"]:
        return None
    return payload


def get_provider_definition(provider: str) -> WearableProviderDefinition:
    key = str(provider or "").strip().lower()
    item = PROVIDER_DEFINITIONS.get(key)
    if not item:
        raise ValueError(f"Unknown wearable provider: {provider}")
    return item


def list_provider_definitions() -> list[WearableProviderDefinition]:
    return list(PROVIDER_DEFINITIONS.values())


def provider_client_id(provider: str) -> str:
    key = str(provider or "").strip().lower()
    if key == "oura":
        return (os.getenv("OURA_CLIENT_ID") or "").strip()
    if key == "whoop":
        return (os.getenv("WHOOP_CLIENT_ID") or "").strip()
    if key == "fitbit":
        return (os.getenv("FITBIT_CLIENT_ID") or "").strip()
    if key == "garmin":
        return (os.getenv("GARMIN_CLIENT_ID") or "").strip()
    return ""


def provider_client_secret(provider: str) -> str:
    key = str(provider or "").strip().lower()
    if key == "oura":
        return (os.getenv("OURA_CLIENT_SECRET") or "").strip()
    if key == "whoop":
        return (os.getenv("WHOOP_CLIENT_SECRET") or "").strip()
    if key == "fitbit":
        return (os.getenv("FITBIT_CLIENT_SECRET") or "").strip()
    if key == "garmin":
        return (os.getenv("GARMIN_CLIENT_SECRET") or "").strip()
    return ""


def provider_scope(provider: str) -> str:
    key = str(provider or "").strip().lower()
    if key == "oura":
        return (os.getenv("OURA_OAUTH_SCOPE") or DEFAULT_OURA_SCOPE).strip()
    if key == "whoop":
        return (os.getenv("WHOOP_OAUTH_SCOPE") or DEFAULT_WHOOP_SCOPE).strip()
    if key == "fitbit":
        return (os.getenv("FITBIT_OAUTH_SCOPE") or DEFAULT_FITBIT_SCOPE).strip()
    return ""


def provider_enabled(provider: str) -> bool:
    key = str(provider or "").strip().lower()
    specific = os.getenv(f"WEARABLE_{key.upper()}_ENABLED")
    if specific is not None and str(specific).strip() != "":
        return _env_flag(f"WEARABLE_{key.upper()}_ENABLED", False)
    return _env_flag("WEARABLES_ENABLED", True)


def provider_configured(provider: str) -> bool:
    key = str(provider or "").strip().lower()
    if key == APPLE_HEALTH_PROVIDER:
        return False
    if key == "garmin":
        return bool(provider_client_id(key) and provider_client_secret(key))
    if key in {"oura", "whoop", "fitbit"}:
        return bool(provider_client_id(key) and provider_client_secret(key))
    return False


def resolve_callback_base_url(request_base_url: str | None = None) -> str:
    base = (
        (os.getenv("WEARABLE_CALLBACK_BASE_URL") or "").strip()
        or (os.getenv("API_PUBLIC_BASE_URL") or "").strip()
        or (os.getenv("PUBLIC_BASE_URL") or "").strip()
        or (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
        or str(request_base_url or "").strip()
    )
    if not base:
        base = "http://localhost:8000"
    if not base.startswith(("http://", "https://")):
        base = f"https://{base}"
    return base.rstrip("/")


def build_callback_url(provider: str, request_base_url: str | None = None) -> str:
    base = resolve_callback_base_url(request_base_url)
    return f"{base}/api/v1/wearables/{str(provider or '').strip().lower()}/callback"


def _utcnow() -> datetime:
    return datetime.utcnow()


def _body_snippet(response: requests.Response) -> str:
    try:
        text = str(response.text or "").strip()
    except Exception:
        text = ""
    if not text:
        return "no response body"
    text = " ".join(text.split())
    return text[:300]


def _raise_http_error(label: str, action: str, response: requests.Response) -> None:
    raise ValueError(f"{label} {action} failed ({response.status_code}): {_body_snippet(response)}")


def _response_json_dict(response: requests.Response, *, label: str, action: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception as exc:
        raise ValueError(f"{label} {action} returned non-JSON data: {exc}")
    if not isinstance(payload, dict):
        raise ValueError(f"Unexpected {label} {action} response.")
    return payload


def _connection_meta(connection: WearableConnection) -> dict[str, Any]:
    return dict(connection.meta) if isinstance(connection.meta, dict) else {}


def _save_connection_meta(connection: WearableConnection, meta: dict[str, Any]) -> None:
    connection.meta = meta


def _get_pending_oauth_meta(connection: WearableConnection) -> dict[str, Any]:
    meta = _connection_meta(connection)
    pending = meta.get("oauth_pending")
    return dict(pending) if isinstance(pending, dict) else {}


def _set_pending_oauth_meta(connection: WearableConnection, payload: dict[str, Any] | None) -> None:
    meta = _connection_meta(connection)
    if payload:
        meta["oauth_pending"] = payload
    else:
        meta.pop("oauth_pending", None)
    _save_connection_meta(connection, meta)


def _mark_oauth_prepared(connection: WearableConnection, *, provider: str, redirect_path: str | None) -> None:
    _set_pending_oauth_meta(
        connection,
        {
            "provider": str(provider).strip().lower(),
            "redirect_path": str(redirect_path or "").strip() or None,
            "prepared_at": _utcnow().replace(microsecond=0).isoformat(),
        },
    )


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = _b64url_encode(secrets.token_bytes(64))
    verifier = verifier[:96]
    challenge = _b64url_encode(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _fitbit_pkce_verifier(connection: WearableConnection) -> str:
    pending = _get_pending_oauth_meta(connection)
    return str(pending.get("code_verifier") or "").strip()


def _find_or_create_connection(session, *, user_id: int, provider: str) -> WearableConnection:
    connection = (
        session.query(WearableConnection)
        .filter(WearableConnection.user_id == int(user_id), WearableConnection.provider == str(provider))
        .one_or_none()
    )
    if connection:
        return connection
    connection = WearableConnection(user_id=int(user_id), provider=str(provider))
    session.add(connection)
    session.flush()
    return connection


def prepare_connect_request(
    session,
    provider: str,
    *,
    user_id: int,
    request_base_url: str | None = None,
    redirect_path: str | None = None,
) -> tuple[WearableConnection, str]:
    definition = get_provider_definition(provider)
    if not definition.connect_implemented:
        raise ValueError(f"{definition.label} connect flow is not implemented yet.")
    if not provider_enabled(definition.key):
        raise ValueError(f"{definition.label} is disabled.")
    if not provider_configured(definition.key):
        raise ValueError(f"{definition.label} credentials are not configured.")

    connection = _find_or_create_connection(session, user_id=int(user_id), provider=definition.key)
    state = mint_wearable_oauth_state(
        user_id=int(user_id),
        provider=definition.key,
        redirect_path=redirect_path,
    )

    if definition.key == "oura":
        _mark_oauth_prepared(connection, provider="oura", redirect_path=redirect_path)
        query: dict[str, str] = {
            "response_type": "code",
            "client_id": provider_client_id("oura"),
            "redirect_uri": build_callback_url("oura", request_base_url),
            "state": state,
        }
        scope = provider_scope("oura")
        if scope:
            query["scope"] = scope
        return connection, f"{OURA_AUTHORIZE_URL}?{urlencode(query)}"

    if definition.key == "whoop":
        _mark_oauth_prepared(connection, provider="whoop", redirect_path=redirect_path)
        query = {
            "response_type": "code",
            "client_id": provider_client_id("whoop"),
            "redirect_uri": build_callback_url("whoop", request_base_url),
            "state": state,
        }
        scope = provider_scope("whoop")
        if scope:
            query["scope"] = scope
        return connection, f"{WHOOP_AUTHORIZE_URL}?{urlencode(query)}"

    if definition.key == "fitbit":
        verifier, challenge = _generate_pkce_pair()
        _set_pending_oauth_meta(
            connection,
            {
                "provider": "fitbit",
                "redirect_path": str(redirect_path or "").strip() or None,
                "prepared_at": _utcnow().replace(microsecond=0).isoformat(),
                "code_verifier": verifier,
            },
        )
        query = {
            "response_type": "code",
            "client_id": provider_client_id("fitbit"),
            "redirect_uri": build_callback_url("fitbit", request_base_url),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        scope = provider_scope("fitbit")
        if scope:
            query["scope"] = scope
        return connection, f"{FITBIT_AUTHORIZE_URL}?{urlencode(query)}"

    raise ValueError(f"{definition.label} connect flow is not implemented yet.")


def build_connect_url(
    provider: str,
    *,
    user_id: int,
    request_base_url: str | None = None,
    redirect_path: str | None = None,
) -> str:
    definition = get_provider_definition(provider)
    if definition.key == "fitbit":
        raise ValueError("Fitbit connect flow requires a session-aware preparation step.")
    state = mint_wearable_oauth_state(
        user_id=int(user_id),
        provider=definition.key,
        redirect_path=redirect_path,
    )
    if definition.key == "oura":
        query: dict[str, str] = {
            "response_type": "code",
            "client_id": provider_client_id("oura"),
            "redirect_uri": build_callback_url("oura", request_base_url),
            "state": state,
        }
        scope = provider_scope("oura")
        if scope:
            query["scope"] = scope
        return f"{OURA_AUTHORIZE_URL}?{urlencode(query)}"
    if definition.key == "whoop":
        query = {
            "response_type": "code",
            "client_id": provider_client_id("whoop"),
            "redirect_uri": build_callback_url("whoop", request_base_url),
            "state": state,
        }
        scope = provider_scope("whoop")
        if scope:
            query["scope"] = scope
        return f"{WHOOP_AUTHORIZE_URL}?{urlencode(query)}"
    raise ValueError(f"{definition.label} connect flow is not implemented yet.")


def _apply_token_payload(connection: WearableConnection, payload: dict[str, Any]) -> None:
    access_token = str(payload.get("access_token") or "").strip()
    if access_token:
        connection.access_token = access_token
    refresh_present = "refresh_token" in payload
    refresh_token = str(payload.get("refresh_token") or "").strip()
    if refresh_present and refresh_token:
        connection.refresh_token = refresh_token
    token_type_present = "token_type" in payload
    token_type = str(payload.get("token_type") or "").strip()
    if token_type_present and token_type:
        connection.token_type = token_type
    scope_present = "scope" in payload
    scope_value = payload.get("scope")
    if isinstance(scope_value, list):
        scope = " ".join(str(item).strip() for item in scope_value if str(item).strip())
    else:
        scope = str(scope_value or "").strip()
    if scope_present and scope:
        connection.scope = scope

    expires_in = payload.get("expires_in")
    if expires_in is None and payload.get("expires_at"):
        try:
            expires_at = datetime.fromisoformat(str(payload.get("expires_at")))
        except Exception:
            expires_at = None
        connection.expires_at = expires_at
    else:
        try:
            expires_in_seconds = int(expires_in) if expires_in is not None else None
        except Exception:
            expires_in_seconds = None
        connection.expires_at = (
            _utcnow() + timedelta(seconds=max(0, expires_in_seconds))
            if expires_in_seconds is not None
            else connection.expires_at
        )


def apply_token_payload(connection: WearableConnection, payload: dict[str, Any]) -> None:
    _apply_token_payload(connection, payload)


def exchange_code_for_tokens(
    provider: str,
    *,
    code: str,
    request_base_url: str | None = None,
    connection: WearableConnection | None = None,
) -> dict[str, Any]:
    definition = get_provider_definition(provider)
    client_id = provider_client_id(definition.key)
    client_secret = provider_client_secret(definition.key)
    if not client_id or not client_secret:
        raise ValueError(f"{definition.label} credentials are not configured.")

    if definition.key == "oura":
        response = requests.post(
            OURA_TOKEN_URL,
            auth=(client_id, client_secret),
            data={
                "grant_type": "authorization_code",
                "code": str(code or "").strip(),
                "redirect_uri": build_callback_url("oura", request_base_url),
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if response.status_code >= 400:
            _raise_http_error("Oura", "token exchange", response)
        return _response_json_dict(response, label="Oura", action="token exchange")

    if definition.key == "whoop":
        response = requests.post(
            WHOOP_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": str(code or "").strip(),
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": build_callback_url("whoop", request_base_url),
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if response.status_code >= 400:
            _raise_http_error("WHOOP", "token exchange", response)
        return _response_json_dict(response, label="WHOOP", action="token exchange")

    if definition.key == "fitbit":
        if not connection:
            raise ValueError("Fitbit token exchange requires a wearable connection.")
        verifier = _fitbit_pkce_verifier(connection)
        if not verifier:
            raise ValueError("Fitbit PKCE verifier is missing. Start the connect flow again.")
        response = requests.post(
            FITBIT_TOKEN_URL,
            auth=(client_id, client_secret),
            data={
                "grant_type": "authorization_code",
                "code": str(code or "").strip(),
                "redirect_uri": build_callback_url("fitbit", request_base_url),
                "client_id": client_id,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if response.status_code >= 400:
            _raise_http_error("Fitbit", "token exchange", response)
        return _response_json_dict(response, label="Fitbit", action="token exchange")

    raise ValueError(f"{definition.label} code exchange is not implemented yet.")


def refresh_connection_token(connection: WearableConnection, *, request_base_url: str | None = None) -> dict[str, Any] | None:
    del request_base_url
    provider = str(getattr(connection, "provider", "") or "").strip().lower()
    client_id = provider_client_id(provider)
    client_secret = provider_client_secret(provider)
    refresh_token = str(getattr(connection, "refresh_token", "") or "").strip()
    if not client_id or not client_secret or not refresh_token:
        return None

    if provider == "oura":
        response = requests.post(
            OURA_TOKEN_URL,
            auth=(client_id, client_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if response.status_code >= 400:
            _raise_http_error("Oura", "token refresh", response)
        payload = _response_json_dict(response, label="Oura", action="token refresh")
        _apply_token_payload(connection, payload)
        return payload

    if provider == "whoop":
        response = requests.post(
            WHOOP_TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if response.status_code >= 400:
            _raise_http_error("WHOOP", "token refresh", response)
        payload = _response_json_dict(response, label="WHOOP", action="token refresh")
        _apply_token_payload(connection, payload)
        return payload

    if provider == "fitbit":
        response = requests.post(
            FITBIT_TOKEN_URL,
            auth=(client_id, client_secret),
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if response.status_code >= 400:
            _raise_http_error("Fitbit", "token refresh", response)
        payload = _response_json_dict(response, label="Fitbit", action="token refresh")
        _apply_token_payload(connection, payload)
        return payload

    return None


def create_sync_run(
    session,
    *,
    connection: WearableConnection,
    trigger: str,
    job_id: int | None = None,
) -> WearableSyncRun:
    run = WearableSyncRun(
        user_id=int(connection.user_id),
        connection_id=int(connection.id),
        provider=str(connection.provider),
        status="queued",
        trigger=str(trigger or "manual"),
        job_id=int(job_id) if job_id is not None else None,
        request_payload={"provider": str(connection.provider), "trigger": str(trigger or "manual")},
    )
    session.add(run)
    session.flush()
    return run


def process_sync_run(session, *, run_id: int, job_id: int | None = None) -> dict[str, Any]:
    ensure_wearables_schema()
    run = session.get(WearableSyncRun, int(run_id))
    if not run:
        raise ValueError(f"wearable sync run not found: {run_id}")
    connection = session.get(WearableConnection, int(run.connection_id or 0))
    if not connection:
        raise ValueError("wearable connection not found")

    provider = str(connection.provider or "").strip().lower()
    definition = get_provider_definition(provider)
    now = _utcnow()
    run.status = "running"
    run.started_at = now
    run.finished_at = None
    run.error = None
    if job_id is not None:
        run.job_id = int(job_id)
    connection.last_sync_status = "running"
    connection.last_sync_error = None
    session.commit()

    try:
        if provider == "oura":
            result = _sync_oura_connection(session, connection)
        elif provider == "whoop":
            result = _sync_whoop_connection(session, connection)
        elif provider == "fitbit":
            result = _sync_fitbit_connection(session, connection)
        else:
            raise ValueError(f"{definition.label} sync adapter is not implemented yet.")
        finished_at = _utcnow()
        run.status = "succeeded"
        run.finished_at = finished_at
        run.records_synced = int(result.get("records_synced") or 0)
        run.result_payload = result
        connection.last_sync_status = "succeeded"
        connection.last_sync_error = None
        connection.last_sync_at = finished_at
        session.commit()
        return {
            "ok": True,
            "run_id": int(run.id),
            "provider": provider,
            "records_synced": int(run.records_synced or 0),
            "result": result,
        }
    except Exception as exc:
        finished_at = _utcnow()
        message = str(exc)
        run.status = "failed"
        run.finished_at = finished_at
        run.error = message
        run.result_payload = {"error": message}
        connection.last_sync_status = "failed"
        connection.last_sync_error = message
        connection.last_sync_at = finished_at
        session.commit()
        raise


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    token = raw.split("T", 1)[0].strip()
    if not token:
        return None
    try:
        return datetime.strptime(token, "%Y-%m-%d").date()
    except Exception:
        return None


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(round(float(value)))
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _clean_source_token(value: Any) -> str:
    return str(value or "").strip()


def _compact_source_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    compact: dict[str, Any] = {}
    for key, raw_value in value.items():
        if raw_value is None:
            continue
        if isinstance(raw_value, dict):
            nested = _compact_source_dict(raw_value)
            if nested:
                compact[str(key)] = nested
            continue
        if isinstance(raw_value, list):
            items = [
                _compact_source_dict(item) if isinstance(item, dict) else item
                for item in raw_value
                if item not in (None, "")
            ]
            if items:
                compact[str(key)] = items
            continue
        token = str(raw_value).strip() if isinstance(raw_value, str) else raw_value
        if token != "":
            compact[str(key)] = token
    return compact


def _normalise_metric_source_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    primary = _compact_source_dict(value.get("primary") if isinstance(value.get("primary"), dict) else {})
    raw_sources = value.get("sources") if isinstance(value.get("sources"), list) else []
    sources = [
        _compact_source_dict(item)
        for item in raw_sources
        if isinstance(item, dict) and _compact_source_dict(item)
    ]
    if not primary and sources:
        primary = sources[0]
    source_count = _coerce_int(value.get("sourceCount") or value.get("source_count"))
    payload = {
        "primary": primary or None,
        "sources": sources,
        "source_count": source_count if source_count is not None else len(sources) if sources else None,
    }
    compact = _compact_source_dict(payload)
    return compact or None


def _sample_metric_sources(sample: dict[str, Any]) -> dict[str, Any]:
    source_specs = {
        "resting_hr": ("resting_hr_source", "restingHeartRateSource"),
        "hrv": ("hrv_source", "heartRateVariabilitySource"),
        "steps": ("steps_source", "stepsSource"),
        "exercise_minutes": (
            "exercise_minutes_source",
            "active_minutes_source",
            "activeCardioMinutesSource",
        ),
    }
    sources: dict[str, Any] = {}
    raw_sources = sample.get("sources") if isinstance(sample.get("sources"), dict) else {}
    for metric_key, sample_keys in source_specs.items():
        raw_value = raw_sources.get(metric_key)
        for sample_key in sample_keys:
            if raw_value is not None:
                break
            raw_value = sample.get(sample_key)
        source_payload = _normalise_metric_source_payload(raw_value)
        if source_payload:
            sources[metric_key] = source_payload
    return sources


def _apple_health_record_from_row(row: WearableDailyMetric | None) -> dict[str, Any]:
    raw_payload = getattr(row, "raw_payload", None) if row is not None else None
    if not isinstance(raw_payload, dict):
        return {}
    record = raw_payload.get(APPLE_HEALTH_PROVIDER)
    return record if isinstance(record, dict) else {}


def _metric_source_payload_from_rows(
    rows: list[WearableDailyMetric],
    *,
    metric_key: str,
) -> dict[str, Any] | None:
    for row in rows:
        record = _apple_health_record_from_row(row)
        sources = record.get("sources") if isinstance(record.get("sources"), dict) else {}
        source_payload = _normalise_metric_source_payload(sources.get(metric_key))
        if source_payload:
            return source_payload
    return None


def _source_strings_from_payload(payload: dict[str, Any] | None) -> list[str]:
    if not isinstance(payload, dict):
        return []
    values: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                collect(nested)
            return
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        token = _clean_source_token(value)
        if token:
            values.append(token.lower())

    collect(payload)
    return values


def _detect_biometric_source_device(payload: dict[str, Any] | None) -> str:
    haystack = " ".join(_source_strings_from_payload(payload))
    if not haystack:
        return "unknown"
    if "apple watch" in haystack or "watch" in haystack:
        return "apple_watch"
    if "iphone" in haystack:
        return "iphone"
    if "garmin" in haystack:
        return "garmin"
    if "whoop" in haystack:
        return "whoop"
    if "fitbit" in haystack:
        return "fitbit"
    if "oura" in haystack:
        return "oura"
    if "apple" in haystack or "health" in haystack:
        return "apple_health"
    return "unknown"


def _source_primary_label(payload: dict[str, Any] | None, *, fallback_device: str | None = None) -> str:
    primary = payload.get("primary") if isinstance(payload, dict) and isinstance(payload.get("primary"), dict) else {}
    device = primary.get("device") if isinstance(primary.get("device"), dict) else {}
    for value in (
        device.get("name"),
        device.get("model"),
        primary.get("name"),
        primary.get("bundleIdentifier"),
        primary.get("bundle_identifier"),
    ):
        token = _clean_source_token(value)
        if token:
            return token
    if fallback_device and fallback_device in BIOMETRIC_DEVICE_LABELS:
        return BIOMETRIC_DEVICE_LABELS[fallback_device]
    return "No source detected"


def _confidence_label(confidence: str) -> str:
    if confidence == "high":
        return "Good"
    if confidence == "medium":
        return "OK"
    if confidence == "low":
        return "Limited"
    return "Unknown"


def _biometric_source_confidence(
    metric_key: str,
    *,
    has_data: bool,
    resolved_device: str,
) -> str:
    if not has_data:
        return "unknown"
    if metric_key == "resting_hr":
        if resolved_device in {"apple_watch", "garmin", "whoop", "fitbit", "oura"}:
            return "high"
        if resolved_device in {"iphone", "apple_health", "unknown"}:
            return "medium"
    if metric_key == "hrv":
        if resolved_device == "apple_watch":
            return "high"
        if resolved_device in {"garmin", "whoop", "fitbit", "oura"}:
            return "medium"
        return "low"
    if metric_key == "steps":
        if resolved_device in {"apple_watch", "iphone", "apple_health", "garmin", "fitbit", "oura"}:
            return "high"
        return "medium"
    if metric_key == "exercise_minutes":
        if resolved_device == "apple_watch":
            return "high"
        if resolved_device in {"garmin", "whoop", "fitbit", "oura"}:
            return "medium"
        return "low"
    return "unknown"


def _biometric_connection_options(metric_key: str) -> list[dict[str, Any]]:
    recommended = {
        "resting_hr": ("oura", "whoop", "fitbit"),
        "hrv": ("oura", "whoop"),
        "steps": ("fitbit", "oura", "garmin"),
        "exercise_minutes": ("fitbit", "whoop", "garmin"),
    }.get(metric_key, ("oura", "whoop", "fitbit"))
    options: list[dict[str, Any]] = []
    for provider_key in recommended:
        definition = PROVIDER_DEFINITIONS.get(provider_key)
        if definition is None:
            continue
        options.append(
            {
                "provider": provider_key,
                "label": definition.label,
                "connectable": bool(definition.connect_implemented),
                "availability": definition.availability,
                "note": definition.default_note,
            }
        )
    return options


def _biometric_source_advice(
    metric_key: str,
    *,
    enabled: bool,
    has_data: bool,
    confidence: str,
    resolved_device: str,
) -> str:
    if not enabled:
        return "Excluded from Gia's biometrics mix until this is switched back on."
    if not has_data:
        return "No recent Apple Health value has been retrieved for this biometric."
    if metric_key == "resting_hr":
        return "Apple Health Resting HR is reliable enough to use when present; a watch or direct wearable connection improves traceability."
    if metric_key == "hrv":
        if resolved_device == "apple_watch" and confidence == "high":
            return "HRV is suitable for readiness when Apple Health is fed by Apple Watch."
        return "HRV is only dependable through Apple Health when the source is Apple Watch; otherwise use a direct wearable connection."
    if metric_key == "steps":
        return "Steps from Apple Health are suitable for activity status from iPhone or Apple Watch."
    if metric_key == "exercise_minutes":
        if resolved_device == "apple_watch" and confidence == "high":
            return "Exercise minutes are suitable when Apple Health Exercise Time is fed by Apple Watch."
        return "Exercise minutes are harder to confirm unless Apple Watch is the source; use a direct wearable connection for stronger training-load context."
    return "Use source confidence to decide whether Gia should include this biometric."


def _build_biometric_source_summaries(
    *,
    preferences: dict[str, Any],
    metric_rows: dict[str, list[WearableDailyMetric]],
) -> dict[str, Any]:
    selected_device = str(preferences.get("device") or "auto").strip().lower()
    if selected_device not in BIOMETRIC_DEVICE_OPTIONS:
        selected_device = "auto"
    summaries: dict[str, Any] = {}
    for metric_key, definition in BIOMETRIC_METRIC_DEFINITIONS.items():
        rows = metric_rows.get(metric_key) or []
        source_payload = _metric_source_payload_from_rows(rows, metric_key=metric_key)
        detected_device = _detect_biometric_source_device(source_payload)
        fallback_device = selected_device if selected_device not in {"auto", "none"} else None
        resolved_device = detected_device if detected_device != "unknown" else fallback_device or "unknown"
        detection_method = (
            "apple_health_source"
            if detected_device != "unknown"
            else "user_selected"
            if fallback_device
            else "unknown"
        )
        has_data = bool(rows)
        enabled = biometric_metric_enabled(preferences, metric_key)
        confidence = _biometric_source_confidence(
            metric_key,
            has_data=has_data,
            resolved_device=resolved_device,
        )
        latest_row = rows[0] if rows else None
        summaries[metric_key] = {
            "metric": metric_key,
            "label": definition.get("label") or metric_key.replace("_", " "),
            "enabled": enabled,
            "has_data": has_data,
            "metric_date": latest_row.metric_date.isoformat() if latest_row and latest_row.metric_date else None,
            "source_label": _source_primary_label(source_payload, fallback_device=fallback_device),
            "detected_device": detected_device,
            "selected_device": selected_device,
            "resolved_device": resolved_device,
            "device_label": BIOMETRIC_DEVICE_LABELS.get(resolved_device, "Unknown"),
            "detection_method": detection_method,
            "confidence": confidence,
            "confidence_label": _confidence_label(confidence),
            "advice": _biometric_source_advice(
                metric_key,
                enabled=enabled,
                has_data=has_data,
                confidence=confidence,
                resolved_device=resolved_device,
            ),
            "source": source_payload,
            "connection_options": _biometric_connection_options(metric_key),
        }
    return summaries


def _merge_day_patch(
    day_map: dict[date, dict[str, Any]],
    *,
    metric_date: date | None,
    source_name: str,
    record: dict[str, Any],
    patch: dict[str, Any],
) -> None:
    if not metric_date:
        return
    bucket = day_map.setdefault(metric_date, {"raw_payload": {}})
    raw_payload = bucket.get("raw_payload") if isinstance(bucket.get("raw_payload"), dict) else {}
    raw_payload[source_name] = record
    bucket["raw_payload"] = raw_payload
    for key, value in patch.items():
        if value is not None:
            bucket[key] = value


def _upsert_daily_metrics(
    session,
    *,
    connection: WearableConnection,
    provider: str,
    day_map: dict[date, dict[str, Any]],
) -> int:
    if not day_map:
        return 0
    existing = {
        row.metric_date: row
        for row in session.query(WearableDailyMetric)
        .filter(
            WearableDailyMetric.user_id == int(connection.user_id),
            WearableDailyMetric.provider == str(provider),
            WearableDailyMetric.metric_date.in_(list(day_map.keys())),
        )
        .all()
    }
    synced_at = _utcnow()
    records_synced = 0
    for metric_date, payload in day_map.items():
        row = existing.get(metric_date)
        if not row:
            row = WearableDailyMetric(
                user_id=int(connection.user_id),
                connection_id=int(connection.id),
                provider=str(provider),
                metric_date=metric_date,
            )
            session.add(row)
            existing[metric_date] = row
        row.connection_id = int(connection.id)
        for field_name in WEARABLE_METRIC_FIELDS:
            value = payload.get(field_name)
            if value is not None:
                setattr(row, field_name, value)
        existing_raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        incoming_raw = payload.get("raw_payload") if isinstance(payload.get("raw_payload"), dict) else {}
        row.raw_payload = {**existing_raw, **incoming_raw}
        row.synced_at = synced_at
        records_synced += 1
    return records_synced


def _latest_metric_date(session, *, user_id: int, provider: str) -> date | None:
    return (
        session.query(WearableDailyMetric.metric_date)
        .filter(
            WearableDailyMetric.user_id == int(user_id),
            WearableDailyMetric.provider == str(provider),
        )
        .order_by(WearableDailyMetric.metric_date.desc())
        .limit(1)
        .scalar()
    )


def _provider_sync_window(
    session,
    *,
    user_id: int,
    provider: str,
    lookback_days: int,
) -> tuple[date, date]:
    today = date.today()
    latest_day = _latest_metric_date(session, user_id=int(user_id), provider=provider)
    if latest_day:
        start_date = max(today - timedelta(days=lookback_days), latest_day - timedelta(days=2))
    else:
        start_date = today - timedelta(days=lookback_days)
    return start_date, today


def _mark_native_connection_connected(
    connection: WearableConnection,
    *,
    native_source: str,
    last_sync_at: datetime | None = None,
) -> None:
    synced_at = last_sync_at or _utcnow()
    connection.status = "connected"
    connection.connected_at = connection.connected_at or synced_at
    connection.disconnected_at = None
    connection.last_sync_status = "succeeded"
    connection.last_sync_error = None
    connection.last_sync_at = synced_at
    meta = connection.meta if isinstance(connection.meta, dict) else {}
    meta["native_source"] = str(native_source or "").strip() or "native"
    meta["last_native_sync_at"] = synced_at.replace(microsecond=0).isoformat()
    connection.meta = meta


def upsert_apple_health_resting_hr_samples(
    session,
    *,
    user_id: int,
    samples: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    ensure_wearables_schema()
    normalized_samples = samples if isinstance(samples, list) else []
    connection = _find_or_create_connection(
        session,
        user_id=int(user_id),
        provider=APPLE_HEALTH_PROVIDER,
    )
    synced_at = _utcnow()
    day_map: dict[date, dict[str, Any]] = {}
    for sample in normalized_samples:
        if not isinstance(sample, dict):
            continue
        metric_date = _coerce_date(sample.get("metric_date") or sample.get("metricDate") or sample.get("date"))
        resting_hr_bpm = _coerce_float(
            sample.get("resting_hr_bpm")
            or sample.get("restingHeartRateBpm")
            or sample.get("value")
        )
        hrv_ms = _coerce_float(
            sample.get("hrv_ms")
            or sample.get("hrvMs")
            or sample.get("heart_rate_variability_ms")
            or sample.get("heartRateVariabilityMs")
        )
        steps = _coerce_int(sample.get("steps"))
        active_minutes = None
        for active_minutes_key in (
            "active_minutes",
            "activeMinutes",
            "active_cardio_minutes",
            "activeCardioMinutes",
            "appleExerciseMinutes",
        ):
            if sample.get(active_minutes_key) is not None:
                active_minutes = _coerce_int(sample.get(active_minutes_key))
                break
        if not metric_date or (
            (resting_hr_bpm is None or resting_hr_bpm <= 0)
            and (hrv_ms is None or hrv_ms <= 0)
            and steps is None
            and active_minutes is None
        ):
            continue
        normalized_bpm = round(float(resting_hr_bpm), 2) if resting_hr_bpm is not None and resting_hr_bpm > 0 else None
        normalized_hrv = round(float(hrv_ms), 2) if hrv_ms is not None and hrv_ms > 0 else None
        normalized_steps = int(max(0, steps)) if steps is not None else None
        normalized_active_minutes = int(max(0, active_minutes)) if active_minutes is not None else None
        metric_sources = _sample_metric_sources(sample)
        _merge_day_patch(
            day_map,
            metric_date=metric_date,
            source_name=APPLE_HEALTH_PROVIDER,
            record={
                "metric_date": metric_date.isoformat(),
                "resting_hr_bpm": normalized_bpm,
                "hrv_ms": normalized_hrv,
                "steps": normalized_steps,
                "active_minutes": normalized_active_minutes,
                "sources": metric_sources,
            },
            patch={
                "resting_hr_bpm": normalized_bpm,
                "hrv_ms": normalized_hrv,
                "steps": normalized_steps,
                "active_minutes": normalized_active_minutes,
            },
        )
    _mark_native_connection_connected(connection, native_source="ios_healthkit", last_sync_at=synced_at)
    records_synced = _upsert_daily_metrics(
        session,
        connection=connection,
        provider=APPLE_HEALTH_PROVIDER,
        day_map=day_map,
    )
    return {
        "provider": APPLE_HEALTH_PROVIDER,
        "records_synced": int(records_synced or 0),
        "latest_metric_date": max(day_map.keys()).isoformat() if day_map else None,
        "connected": True,
    }


def _apple_health_resting_hr_status(
    latest_value: float | None,
    baseline_value: float | None,
) -> tuple[str, str]:
    if latest_value is None:
        return "normal", "Normal"
    if baseline_value is None:
        return "normal", "Normal"
    delta = float(latest_value) - float(baseline_value)
    if delta <= APPLE_HEALTH_OPTIMUM_DELTA_BPM:
        return "optimum", "Optimal"
    if delta >= APPLE_HEALTH_ELEVATED_DELTA_BPM:
        return "elevated", "Elevated"
    return "normal", "Normal"


def _apple_health_hrv_status(
    latest_value: float | None,
    baseline_value: float | None,
) -> tuple[str, str]:
    if latest_value is None:
        return "normal", "Normal"
    if baseline_value is None or baseline_value <= 0:
        return "normal", "Normal"
    delta = float(latest_value) - float(baseline_value)
    threshold = max(APPLE_HEALTH_HRV_MIN_DELTA_MS, abs(float(baseline_value)) * APPLE_HEALTH_HRV_DELTA_RATIO)
    if delta >= threshold:
        return "optimum", "Optimal"
    if delta <= -threshold:
        return "elevated", "Suppressed"
    return "normal", "Normal"


def _apple_health_training_readiness_status(
    hrv_status: str | None,
    resting_hr_status: str | None,
) -> tuple[str, str, str, int | None]:
    resolved_hrv = str(hrv_status or "").strip().lower()
    resolved_rhr = str(resting_hr_status or "").strip().lower()
    if resolved_hrv not in {"optimum", "normal", "elevated"} or resolved_rhr not in {
        "optimum",
        "normal",
        "elevated",
    }:
        return "unknown", "No data", "Sync HRV and Resting HR", None
    if resolved_hrv == "optimum" and resolved_rhr in {"optimum", "normal"}:
        return "ready", "Ready", "Push intensity", 3
    if resolved_hrv == "elevated" and resolved_rhr == "elevated":
        return "low", "Low", "Recover / avoid intensity", 1
    return "moderate", "Moderate", "Train, but control intensity", 2


def _apple_health_activity_status(
    *,
    steps: int | None,
    active_minutes: int | None,
) -> tuple[str, str, int | None]:
    resolved_steps = int(steps) if steps is not None else None
    resolved_active_minutes = int(active_minutes) if active_minutes is not None else None
    if resolved_steps is None and resolved_active_minutes is None:
        return "unknown", "No data", None
    if (resolved_active_minutes is not None and resolved_active_minutes >= 30) or (
        resolved_steps is not None and resolved_steps >= 10000
    ):
        return "high", "High", 3
    if (resolved_active_minutes is not None and resolved_active_minutes >= 20) or (
        resolved_steps is not None and resolved_steps >= 7500
    ):
        return "moderate", "Moderate", 2
    return "low", "Low", 1


def _apple_health_readiness_activity_alignment(
    readiness_level: int | None,
    activity_level: int | None,
) -> tuple[str, str]:
    if readiness_level is None or activity_level is None:
        return "unknown", "No alignment yet"
    if int(readiness_level) == int(activity_level):
        return "aligned", "Aligned"
    if int(activity_level) > int(readiness_level):
        return "above_readiness", "Activity above readiness"
    return "below_readiness", "Activity below readiness"


def get_apple_health_resting_hr_summary(
    session,
    *,
    user_id: int,
) -> dict[str, Any]:
    ensure_wearables_schema()
    biometric_preferences = get_biometrics_preferences(session, user_id=int(user_id))
    use_resting_hr = biometric_metric_enabled(biometric_preferences, "resting_hr")
    use_hrv = biometric_metric_enabled(biometric_preferences, "hrv")
    use_steps = biometric_metric_enabled(biometric_preferences, "steps")
    use_exercise_minutes = biometric_metric_enabled(biometric_preferences, "exercise_minutes")
    connection = (
        session.query(WearableConnection)
        .filter(
            WearableConnection.user_id == int(user_id),
            WearableConnection.provider == APPLE_HEALTH_PROVIDER,
        )
        .one_or_none()
    )
    resting_hr_rows = (
        session.query(WearableDailyMetric)
        .filter(
            WearableDailyMetric.user_id == int(user_id),
            WearableDailyMetric.provider == APPLE_HEALTH_PROVIDER,
            WearableDailyMetric.resting_hr_bpm.isnot(None),
        )
        .order_by(WearableDailyMetric.metric_date.desc())
        .limit(max(APPLE_HEALTH_BASELINE_DAYS + 1, 7))
        .all()
    )
    rows = resting_hr_rows if use_resting_hr else []
    raw_hrv_rows = (
        session.query(WearableDailyMetric)
        .filter(
            WearableDailyMetric.user_id == int(user_id),
            WearableDailyMetric.provider == APPLE_HEALTH_PROVIDER,
            WearableDailyMetric.hrv_ms.isnot(None),
        )
        .order_by(WearableDailyMetric.metric_date.desc())
        .limit(max(APPLE_HEALTH_BASELINE_DAYS + 1, 14))
        .all()
    )
    hrv_rows = raw_hrv_rows if use_hrv else []
    latest_row = rows[0] if rows else None
    latest_value = (
        round(float(latest_row.resting_hr_bpm), 1)
        if latest_row and latest_row.resting_hr_bpm is not None
        else None
    )
    baseline_values = [
        float(row.resting_hr_bpm)
        for row in rows[1 : APPLE_HEALTH_BASELINE_DAYS + 1]
        if row.resting_hr_bpm is not None
    ]
    baseline_value = (
        round(float(median(baseline_values)), 1)
        if len(baseline_values) >= APPLE_HEALTH_BASELINE_MIN_POINTS
        else None
    )
    trend_status, trend_label = _apple_health_resting_hr_status(latest_value, baseline_value)
    delta_bpm = (
        round(float(latest_value) - float(baseline_value), 1)
        if latest_value is not None and baseline_value is not None
        else None
    )
    latest_hrv_row = hrv_rows[0] if hrv_rows else None
    latest_hrv_value = (
        round(float(latest_hrv_row.hrv_ms), 1)
        if latest_hrv_row and latest_hrv_row.hrv_ms is not None
        else None
    )
    hrv_baseline_values = [
        float(row.hrv_ms)
        for row in hrv_rows[1 : APPLE_HEALTH_BASELINE_DAYS + 1]
        if row.hrv_ms is not None
    ]
    hrv_baseline_value = (
        round(float(median(hrv_baseline_values)), 1)
        if len(hrv_baseline_values) >= APPLE_HEALTH_BASELINE_MIN_POINTS
        else None
    )
    hrv_trend_status, hrv_trend_label = _apple_health_hrv_status(latest_hrv_value, hrv_baseline_value)
    hrv_delta_ms = (
        round(float(latest_hrv_value) - float(hrv_baseline_value), 1)
        if latest_hrv_value is not None and hrv_baseline_value is not None
        else None
    )
    training_readiness_status, training_readiness_label, training_readiness_action, training_readiness_level = (
        _apple_health_training_readiness_status(
            hrv_trend_status if latest_hrv_row else None,
            trend_status if latest_row else None,
        )
    )
    connected = bool(
        connection and str(getattr(connection, "status", "") or "").strip().lower() == "connected"
    )
    raw_step_rows = (
        session.query(WearableDailyMetric)
        .filter(
            WearableDailyMetric.user_id == int(user_id),
            WearableDailyMetric.provider == APPLE_HEALTH_PROVIDER,
            WearableDailyMetric.steps.isnot(None),
        )
        .order_by(WearableDailyMetric.metric_date.desc())
        .limit(7)
        .all()
    )
    step_rows = raw_step_rows if use_steps else []
    latest_step_row = step_rows[0] if step_rows else None
    raw_active_minutes_rows = (
        session.query(WearableDailyMetric)
        .filter(
            WearableDailyMetric.user_id == int(user_id),
            WearableDailyMetric.provider == APPLE_HEALTH_PROVIDER,
            WearableDailyMetric.active_minutes.isnot(None),
        )
        .order_by(WearableDailyMetric.metric_date.desc())
        .limit(7)
        .all()
    )
    active_minutes_rows = raw_active_minutes_rows if use_exercise_minutes else []
    latest_active_minutes_row = active_minutes_rows[0] if active_minutes_rows else None
    biometric_sources = _build_biometric_source_summaries(
        preferences=biometric_preferences,
        metric_rows={
            "resting_hr": resting_hr_rows,
            "hrv": raw_hrv_rows,
            "steps": raw_step_rows,
            "exercise_minutes": raw_active_minutes_rows,
        },
    )
    today_row = (
        session.query(WearableDailyMetric)
        .filter(
            WearableDailyMetric.user_id == int(user_id),
            WearableDailyMetric.provider == APPLE_HEALTH_PROVIDER,
            WearableDailyMetric.metric_date == date.today(),
        )
        .order_by(WearableDailyMetric.metric_date.desc())
        .first()
    )
    steps_today = (
        int(today_row.steps)
        if use_steps and today_row and getattr(today_row, "steps", None) is not None
        else int(latest_step_row.steps)
        if use_steps and latest_step_row and getattr(latest_step_row, "steps", None) is not None
        else None
    )
    steps_metric_date = (
        today_row.metric_date.isoformat()
        if use_steps and today_row and getattr(today_row, "steps", None) is not None and getattr(today_row, "metric_date", None)
        else latest_step_row.metric_date.isoformat()
        if use_steps and latest_step_row and getattr(latest_step_row, "metric_date", None)
        else None
    )
    active_minutes_today = (
        int(today_row.active_minutes)
        if use_exercise_minutes and today_row and getattr(today_row, "active_minutes", None) is not None
        else int(latest_active_minutes_row.active_minutes)
        if use_exercise_minutes and latest_active_minutes_row and getattr(latest_active_minutes_row, "active_minutes", None) is not None
        else None
    )
    active_minutes_metric_date = (
        today_row.metric_date.isoformat()
        if use_exercise_minutes and today_row and getattr(today_row, "active_minutes", None) is not None and getattr(today_row, "metric_date", None)
        else latest_active_minutes_row.metric_date.isoformat()
        if use_exercise_minutes and latest_active_minutes_row and getattr(latest_active_minutes_row, "metric_date", None)
        else None
    )
    step_by_day = {
        row.metric_date: int(row.steps)
        for row in step_rows
        if getattr(row, "metric_date", None) is not None and getattr(row, "steps", None) is not None
    }
    active_minutes_by_day = {
        row.metric_date: int(row.active_minutes)
        for row in active_minutes_rows
        if getattr(row, "metric_date", None) is not None and getattr(row, "active_minutes", None) is not None
    }
    activity_dates = sorted(set(step_by_day.keys()) | set(active_minutes_by_day.keys()))
    latest_activity_date = (
        date.today()
        if date.today() in activity_dates
        else activity_dates[-1]
        if activity_dates
        else None
    )
    activity_status, activity_status_label, activity_level = _apple_health_activity_status(
        steps=step_by_day.get(latest_activity_date) if latest_activity_date else None,
        active_minutes=active_minutes_by_day.get(latest_activity_date) if latest_activity_date else None,
    )
    activity_alignment_status, activity_alignment_label = _apple_health_readiness_activity_alignment(
        training_readiness_level,
        activity_level,
    )
    history = [
        {
            "metric_date": row.metric_date.isoformat() if getattr(row, "metric_date", None) else None,
            "resting_hr_bpm": (
                round(float(row.resting_hr_bpm), 1)
                if getattr(row, "resting_hr_bpm", None) is not None
                else None
            ),
            "trend_status": (
                _apple_health_resting_hr_status(
                    round(float(row.resting_hr_bpm), 1)
                    if getattr(row, "resting_hr_bpm", None) is not None
                    else None,
                    baseline_value,
                )[0]
                if getattr(row, "resting_hr_bpm", None) is not None
                else None
            ),
            "trend_label": (
                _apple_health_resting_hr_status(
                    round(float(row.resting_hr_bpm), 1)
                    if getattr(row, "resting_hr_bpm", None) is not None
                    else None,
                    baseline_value,
                )[1]
                if getattr(row, "resting_hr_bpm", None) is not None
                else None
            ),
        }
        for row in reversed(rows[:7])
        if getattr(row, "metric_date", None) is not None and getattr(row, "resting_hr_bpm", None) is not None
    ]
    hrv_history = [
        {
            "metric_date": row.metric_date.isoformat() if getattr(row, "metric_date", None) else None,
            "hrv_ms": (
                round(float(row.hrv_ms), 1)
                if getattr(row, "hrv_ms", None) is not None
                else None
            ),
            "trend_status": (
                _apple_health_hrv_status(
                    round(float(row.hrv_ms), 1)
                    if getattr(row, "hrv_ms", None) is not None
                    else None,
                    hrv_baseline_value,
                )[0]
                if getattr(row, "hrv_ms", None) is not None
                else None
            ),
            "trend_label": (
                _apple_health_hrv_status(
                    round(float(row.hrv_ms), 1)
                    if getattr(row, "hrv_ms", None) is not None
                    else None,
                    hrv_baseline_value,
                )[1]
                if getattr(row, "hrv_ms", None) is not None
                else None
            ),
        }
        for row in reversed(hrv_rows[:7])
        if getattr(row, "metric_date", None) is not None and getattr(row, "hrv_ms", None) is not None
    ]
    resting_hr_by_day = {
        row.metric_date: round(float(row.resting_hr_bpm), 1)
        for row in rows
        if getattr(row, "metric_date", None) is not None and getattr(row, "resting_hr_bpm", None) is not None
    }
    hrv_by_day = {
        row.metric_date: round(float(row.hrv_ms), 1)
        for row in hrv_rows
        if getattr(row, "metric_date", None) is not None and getattr(row, "hrv_ms", None) is not None
    }
    readiness_dates = sorted(set(resting_hr_by_day.keys()) | set(hrv_by_day.keys()))[-7:]
    training_readiness_history = []
    for metric_day in readiness_dates:
        day_resting_hr = resting_hr_by_day.get(metric_day)
        day_hrv = hrv_by_day.get(metric_day)
        day_rhr_status, day_rhr_label = _apple_health_resting_hr_status(day_resting_hr, baseline_value)
        day_hrv_status, day_hrv_label = _apple_health_hrv_status(day_hrv, hrv_baseline_value)
        day_readiness_status, day_readiness_label, day_readiness_action, day_readiness_level = (
            _apple_health_training_readiness_status(
                day_hrv_status if day_hrv is not None else None,
                day_rhr_status if day_resting_hr is not None else None,
            )
        )
        training_readiness_history.append(
            {
                "metric_date": metric_day.isoformat(),
                "status": day_readiness_status,
                "label": day_readiness_label,
                "action": day_readiness_action,
                "level": day_readiness_level,
                "resting_hr_bpm": day_resting_hr,
                "resting_hr_status": day_rhr_status if day_resting_hr is not None else None,
                "resting_hr_label": day_rhr_label if day_resting_hr is not None else None,
                "hrv_ms": day_hrv,
                "hrv_status": day_hrv_status if day_hrv is not None else None,
                "hrv_label": day_hrv_label if day_hrv is not None else None,
            }
        )
    steps_history = [
        {
            "metric_date": row.metric_date.isoformat() if getattr(row, "metric_date", None) else None,
            "steps": int(row.steps) if getattr(row, "steps", None) is not None else None,
        }
        for row in reversed(step_rows[:7])
        if getattr(row, "metric_date", None) is not None and getattr(row, "steps", None) is not None
    ]
    active_minutes_history = [
        {
            "metric_date": row.metric_date.isoformat() if getattr(row, "metric_date", None) else None,
            "active_minutes": int(row.active_minutes) if getattr(row, "active_minutes", None) is not None else None,
        }
        for row in reversed(active_minutes_rows[:7])
        if getattr(row, "metric_date", None) is not None and getattr(row, "active_minutes", None) is not None
    ]
    readiness_history_by_day: dict[date, dict[str, Any]] = {}
    for item in training_readiness_history:
        if not isinstance(item, dict):
            continue
        metric_day = _coerce_date(item.get("metric_date"))
        if metric_day:
            readiness_history_by_day[metric_day] = item
    activity_dates_for_history = sorted(
        set(step_by_day.keys()) | set(active_minutes_by_day.keys()) | set(readiness_history_by_day.keys())
    )[-7:]
    activity_status_history = []
    readiness_activity_history = []
    for metric_day in activity_dates_for_history:
        day_activity_status, day_activity_label, day_activity_level = _apple_health_activity_status(
            steps=step_by_day.get(metric_day),
            active_minutes=active_minutes_by_day.get(metric_day),
        )
        readiness_item = readiness_history_by_day.get(metric_day) or {}
        day_alignment_status, day_alignment_label = _apple_health_readiness_activity_alignment(
            _coerce_int(readiness_item.get("level")) if isinstance(readiness_item, dict) else None,
            day_activity_level,
        )
        activity_item = {
            "metric_date": metric_day.isoformat(),
            "status": day_activity_status,
            "label": day_activity_label,
            "level": day_activity_level,
            "steps": step_by_day.get(metric_day),
            "active_minutes": active_minutes_by_day.get(metric_day),
        }
        activity_status_history.append(activity_item)
        readiness_activity_history.append(
            {
                "metric_date": metric_day.isoformat(),
                "training_readiness_status": readiness_item.get("status") if isinstance(readiness_item, dict) else None,
                "training_readiness_label": readiness_item.get("label") if isinstance(readiness_item, dict) else None,
                "training_readiness_level": readiness_item.get("level") if isinstance(readiness_item, dict) else None,
                "activity_status": day_activity_status,
                "activity_label": day_activity_label,
                "activity_level": day_activity_level,
                "alignment_status": day_alignment_status,
                "alignment_label": day_alignment_label,
                "steps": step_by_day.get(metric_day),
                "active_minutes": active_minutes_by_day.get(metric_day),
            }
        )
    return {
        "provider": APPLE_HEALTH_PROVIDER,
        "connected": connected,
        "biometric_preferences": biometric_preferences,
        "biometric_sources": biometric_sources,
        "metric_date": latest_row.metric_date.isoformat() if latest_row else None,
        "resting_hr_bpm": latest_value,
        "baseline_resting_hr_bpm": baseline_value,
        "baseline_window_days": APPLE_HEALTH_BASELINE_DAYS,
        "baseline_min_points": APPLE_HEALTH_BASELINE_MIN_POINTS,
        "delta_bpm": delta_bpm,
        "trend_status": trend_status if latest_row else None,
        "trend_label": trend_label if latest_row else None,
        "synced_at": latest_row.synced_at.isoformat() if latest_row and latest_row.synced_at else None,
        "available": (
            latest_row is not None
            or latest_hrv_row is not None
            or latest_step_row is not None
            or latest_active_minutes_row is not None
        ),
        "hrv_metric_date": latest_hrv_row.metric_date.isoformat() if latest_hrv_row else None,
        "hrv_ms": latest_hrv_value,
        "baseline_hrv_ms": hrv_baseline_value,
        "hrv_delta_ms": hrv_delta_ms,
        "hrv_trend_status": hrv_trend_status if latest_hrv_row else None,
        "hrv_trend_label": hrv_trend_label if latest_hrv_row else None,
        "hrv_synced_at": latest_hrv_row.synced_at.isoformat() if latest_hrv_row and latest_hrv_row.synced_at else None,
        "training_readiness_status": training_readiness_status,
        "training_readiness_label": training_readiness_label,
        "training_readiness_action": training_readiness_action,
        "training_readiness_level": training_readiness_level,
        "steps_today": steps_today,
        "steps_metric_date": steps_metric_date,
        "active_minutes_today": active_minutes_today,
        "active_minutes_metric_date": active_minutes_metric_date,
        "activity_metric_date": latest_activity_date.isoformat() if latest_activity_date else None,
        "activity_status": activity_status,
        "activity_status_label": activity_status_label,
        "activity_level": activity_level,
        "activity_alignment_status": activity_alignment_status,
        "activity_alignment_label": activity_alignment_label,
        "history": history,
        "hrv_history": hrv_history,
        "training_readiness_history": training_readiness_history,
        "steps_history": steps_history,
        "active_minutes_history": active_minutes_history,
        "activity_status_history": activity_status_history,
        "readiness_activity_history": readiness_activity_history,
    }


def _token_value(connection: WearableConnection) -> str:
    return str(getattr(connection, "access_token", "") or "").strip()


def _token_valid(connection: WearableConnection) -> bool:
    access_token = _token_value(connection)
    expires_at = getattr(connection, "expires_at", None)
    return bool(access_token and (not expires_at or expires_at > (_utcnow() + timedelta(minutes=2))))


def _ensure_access_token(connection: WearableConnection, *, label: str) -> str:
    access_token = _token_value(connection)
    if _token_valid(connection):
        return access_token
    payload = refresh_connection_token(connection)
    refreshed = str((payload or {}).get("access_token") or _token_value(connection)).strip()
    if not refreshed:
        raise ValueError(f"{label} access token is missing and could not be refreshed.")
    return refreshed


def _authorized_get_json(
    connection: WearableConnection,
    *,
    label: str,
    base_url: str,
    path: str,
    params: dict[str, Any] | None = None,
    required: bool = True,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    access_token = _ensure_access_token(connection, label=label)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    response = requests.get(
        f"{base_url}{path}",
        headers=headers,
        params=params or None,
        timeout=30,
    )
    if response.status_code == 401 and str(getattr(connection, "refresh_token", "") or "").strip():
        refresh_connection_token(connection)
        response = requests.get(
            f"{base_url}{path}",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {_token_value(connection)}",
            },
            params=params or None,
            timeout=30,
        )
    if response.status_code == 404 and not required:
        return None, {"status": "unavailable", "http_status": 404, "path": path}
    if response.status_code in {400, 403} and not required:
        return None, {"status": "unsupported", "http_status": response.status_code, "path": path}
    if response.status_code >= 400:
        if not required:
            return None, {
                "status": "error",
                "http_status": response.status_code,
                "path": path,
                "error": f"{label} {path} returned {response.status_code}: {_body_snippet(response)}",
            }
        _raise_http_error(label, path, response)
    return _response_json_dict(response, label=label, action=path), {
        "status": "ok",
        "http_status": response.status_code,
        "path": path,
    }


def _oura_fetch_collection(
    connection: WearableConnection,
    *,
    path: str,
    start_date: date,
    end_date: date,
    required: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    attempts = [
        {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        None,
    ]
    last_error: str | None = None
    for params in attempts:
        payload, meta = _authorized_get_json(
            connection,
            label="Oura",
            base_url=OURA_API_BASE_URL,
            path=path,
            params=params,
            required=required,
        )
        if payload is None:
            return [], meta
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            meta["count"] = len(data)
            return [item for item in data if isinstance(item, dict)], meta
        if isinstance(payload, dict):
            meta["count"] = 0
            meta["has_payload"] = True
            return [], meta
        last_error = f"Oura {path} returned an unexpected payload."
        if not required:
            return [], {"status": "error", "path": path, "error": last_error}
    if last_error:
        raise ValueError(last_error)
    return [], {"status": "ok", "path": path, "count": 0}


def _extract_oura_sleep_patch(record: dict[str, Any]) -> tuple[date | None, dict[str, Any]]:
    metric_date = (
        _coerce_date(record.get("day"))
        or _coerce_date(record.get("date"))
        or _coerce_date(record.get("bedtime_start"))
        or _coerce_date(record.get("timestamp"))
    )
    return metric_date, {
        "sleep_seconds": _coerce_int(record.get("total_sleep_duration") or record.get("total_sleep_time")),
        "sleep_score": _coerce_int(record.get("score") or record.get("sleep_score")),
        "hrv_ms": _coerce_float(record.get("average_hrv")),
        "resting_hr_bpm": _coerce_float(record.get("lowest_heart_rate") or record.get("resting_heart_rate")),
    }


def _extract_oura_activity_patch(record: dict[str, Any]) -> tuple[date | None, dict[str, Any]]:
    low = _coerce_int(record.get("low_activity_time"))
    medium = _coerce_int(record.get("medium_activity_time"))
    high = _coerce_int(record.get("high_activity_time"))
    active_minutes = _coerce_int(record.get("active_minutes"))
    if active_minutes is None:
        total_seconds = sum(v for v in (low, medium, high) if v is not None)
        active_minutes = int(round(total_seconds / 60)) if total_seconds else None
    return _coerce_date(record.get("day") or record.get("date") or record.get("timestamp")), {
        "steps": _coerce_int(record.get("steps")),
        "active_minutes": active_minutes,
        "calories": _coerce_int(
            record.get("active_calories")
            or record.get("cal_active")
            or record.get("cal_total")
        ),
        "strain_score": _coerce_float(record.get("score") or record.get("activity_score")),
    }


def _extract_oura_readiness_patch(record: dict[str, Any]) -> tuple[date | None, dict[str, Any]]:
    return _coerce_date(record.get("day") or record.get("date") or record.get("timestamp")), {
        "readiness_score": _coerce_int(record.get("score") or record.get("readiness_score")),
    }


def _sync_oura_connection(session, connection: WearableConnection) -> dict[str, Any]:
    start_date, end_date = _provider_sync_window(
        session,
        user_id=int(connection.user_id),
        provider="oura",
        lookback_days=DEFAULT_OURA_LOOKBACK_DAYS,
    )

    day_map: dict[date, dict[str, Any]] = {}
    source_meta: dict[str, Any] = {}
    source_specs = [
        ("sleep", "/v2/usercollection/sleep", _extract_oura_sleep_patch, True),
        ("activity", "/v2/usercollection/daily_activity", _extract_oura_activity_patch, False),
        ("readiness", "/v2/usercollection/daily_readiness", _extract_oura_readiness_patch, False),
    ]
    for source_name, path, extractor, required in source_specs:
        records, meta = _oura_fetch_collection(
            connection,
            path=path,
            start_date=start_date,
            end_date=end_date,
            required=required,
        )
        source_meta[source_name] = meta
        for record in records:
            metric_date, patch = extractor(record)
            _merge_day_patch(day_map, metric_date=metric_date, source_name=source_name, record=record, patch=patch)

    records_synced = _upsert_daily_metrics(session, connection=connection, provider="oura", day_map=day_map)
    session.commit()
    return {
        "provider": "oura",
        "records_synced": records_synced,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sources": source_meta,
    }


def _whoop_iso_start(value: date) -> str:
    return f"{value.isoformat()}T00:00:00Z"


def _whoop_iso_end(value: date) -> str:
    return f"{(value + timedelta(days=1)).isoformat()}T00:00:00Z"


def _whoop_fetch_collection(
    connection: WearableConnection,
    *,
    path: str,
    start_date: date,
    end_date: date,
    required: bool,
    limit: int = 25,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    meta: dict[str, Any] = {"status": "ok", "path": path, "pages": 0}
    next_token: str | None = None
    while True:
        params: dict[str, Any] = {"limit": int(limit)}
        if next_token:
            params["nextToken"] = next_token
        else:
            params["start"] = _whoop_iso_start(start_date)
            params["end"] = _whoop_iso_end(end_date)
        payload, page_meta = _authorized_get_json(
            connection,
            label="WHOOP",
            base_url=WHOOP_API_BASE_URL,
            path=path,
            params=params,
            required=required,
        )
        if payload is None:
            return [], page_meta
        page_records = payload.get("records")
        if not isinstance(page_records, list):
            raise ValueError(f"WHOOP {path} returned an unexpected payload.")
        records.extend(item for item in page_records if isinstance(item, dict))
        meta["pages"] = int(meta.get("pages") or 0) + 1
        next_token = str(payload.get("next_token") or "").strip() or None
        if not next_token:
            meta["http_status"] = page_meta.get("http_status")
            meta["count"] = len(records)
            return records, meta


def _whoop_fetch_profile(connection: WearableConnection) -> dict[str, Any] | None:
    payload, _meta = _authorized_get_json(
        connection,
        label="WHOOP",
        base_url=WHOOP_API_BASE_URL,
        path="/user/profile/basic",
        required=False,
    )
    return payload if isinstance(payload, dict) else None


def _whoop_cycle_patch(record: dict[str, Any]) -> tuple[date | None, dict[str, Any]]:
    score = record.get("score") if isinstance(record.get("score"), dict) else {}
    kilojoule = _coerce_float(score.get("kilojoule"))
    calories = int(round(kilojoule / 4.184)) if kilojoule is not None else None
    return _coerce_date(record.get("end") or record.get("start") or record.get("updated_at")), {
        "strain_score": _coerce_float(score.get("strain")),
        "calories": calories,
    }


def _whoop_sleep_seconds(record: dict[str, Any]) -> int | None:
    score = record.get("score") if isinstance(record.get("score"), dict) else {}
    stage_summary = score.get("stage_summary") if isinstance(score.get("stage_summary"), dict) else {}
    asleep_millis = 0
    found = False
    for key in (
        "total_light_sleep_time_milli",
        "total_slow_wave_sleep_time_milli",
        "total_rem_sleep_time_milli",
    ):
        value = _coerce_int(stage_summary.get(key))
        if value is not None:
            asleep_millis += value
            found = True
    if found:
        return int(round(asleep_millis / 1000))
    in_bed = _coerce_int(stage_summary.get("total_in_bed_time_milli"))
    awake = _coerce_int(stage_summary.get("total_awake_time_milli")) or 0
    if in_bed is not None:
        return int(round(max(0, in_bed - awake) / 1000))
    return None


def _whoop_sleep_patch(record: dict[str, Any]) -> tuple[date | None, dict[str, Any]]:
    score = record.get("score") if isinstance(record.get("score"), dict) else {}
    return _coerce_date(record.get("end") or record.get("start") or record.get("updated_at")), {
        "sleep_seconds": _whoop_sleep_seconds(record),
        "sleep_score": _coerce_int(score.get("sleep_performance_percentage")),
    }


def _whoop_recovery_patch(record: dict[str, Any]) -> tuple[date | None, dict[str, Any]]:
    score = record.get("score") if isinstance(record.get("score"), dict) else {}
    return _coerce_date(record.get("updated_at")), {
        "readiness_score": _coerce_int(score.get("recovery_score")),
        "hrv_ms": _coerce_float(score.get("hrv_rmssd_milli")),
        "resting_hr_bpm": _coerce_float(score.get("resting_heart_rate")),
    }


def _sync_whoop_connection(session, connection: WearableConnection) -> dict[str, Any]:
    start_date, end_date = _provider_sync_window(
        session,
        user_id=int(connection.user_id),
        provider="whoop",
        lookback_days=DEFAULT_WHOOP_LOOKBACK_DAYS,
    )
    source_meta: dict[str, Any] = {}
    day_map: dict[date, dict[str, Any]] = {}

    profile = _whoop_fetch_profile(connection)
    if profile:
        connection.provider_user_id = str(profile.get("user_id") or connection.provider_user_id or "").strip() or connection.provider_user_id
        connection.external_user_ref = (
            str(profile.get("email") or connection.external_user_ref or "").strip() or connection.external_user_ref
        )
        connection.raw_profile = profile
        source_meta["profile"] = {"status": "ok", "path": "/user/profile/basic"}

    cycle_records, cycle_meta = _whoop_fetch_collection(
        connection,
        path="/cycle",
        start_date=start_date,
        end_date=end_date,
        required=False,
    )
    source_meta["cycles"] = cycle_meta
    cycle_day_by_id: dict[int, date] = {}
    for record in cycle_records:
        metric_date, patch = _whoop_cycle_patch(record)
        cycle_id = _coerce_int(record.get("id"))
        if cycle_id and metric_date:
            cycle_day_by_id[int(cycle_id)] = metric_date
        _merge_day_patch(day_map, metric_date=metric_date, source_name="cycle", record=record, patch=patch)

    sleep_records, sleep_meta = _whoop_fetch_collection(
        connection,
        path="/activity/sleep",
        start_date=start_date,
        end_date=end_date,
        required=False,
    )
    source_meta["sleep"] = sleep_meta
    sleep_day_by_id: dict[int, date] = {}
    for record in sleep_records:
        metric_date, patch = _whoop_sleep_patch(record)
        sleep_id = _coerce_int(record.get("id"))
        cycle_id = _coerce_int(record.get("cycle_id"))
        if sleep_id and metric_date:
            sleep_day_by_id[int(sleep_id)] = metric_date
        if cycle_id and metric_date and int(cycle_id) not in cycle_day_by_id:
            cycle_day_by_id[int(cycle_id)] = metric_date
        _merge_day_patch(day_map, metric_date=metric_date, source_name="sleep", record=record, patch=patch)

    recovery_records, recovery_meta = _whoop_fetch_collection(
        connection,
        path="/recovery",
        start_date=start_date,
        end_date=end_date,
        required=False,
    )
    source_meta["recovery"] = recovery_meta
    for record in recovery_records:
        metric_date, patch = _whoop_recovery_patch(record)
        cycle_id = _coerce_int(record.get("cycle_id"))
        sleep_id = _coerce_int(record.get("sleep_id"))
        metric_date = (
            (cycle_day_by_id.get(int(cycle_id)) if cycle_id else None)
            or (sleep_day_by_id.get(int(sleep_id)) if sleep_id else None)
            or metric_date
        )
        _merge_day_patch(day_map, metric_date=metric_date, source_name="recovery", record=record, patch=patch)

    records_synced = _upsert_daily_metrics(session, connection=connection, provider="whoop", day_map=day_map)
    session.commit()
    return {
        "provider": "whoop",
        "records_synced": records_synced,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sources": source_meta,
    }


def _fitbit_fetch_json(
    connection: WearableConnection,
    *,
    path: str,
    required: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    return _authorized_get_json(
        connection,
        label="Fitbit",
        base_url=FITBIT_API_BASE_URL,
        path=path,
        required=required,
    )


def _fitbit_profile(connection: WearableConnection) -> dict[str, Any] | None:
    payload, _meta = _fitbit_fetch_json(connection, path="/1/user/-/profile.json", required=False)
    user = payload.get("user") if isinstance(payload, dict) and isinstance(payload.get("user"), dict) else None
    return user


def _fitbit_series_entries(payload: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    value = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _fitbit_merge_simple_series(
    day_map: dict[date, dict[str, Any]],
    *,
    source_name: str,
    records: list[dict[str, Any]],
    field_name: str,
) -> None:
    for record in records:
        metric_date = _coerce_date(record.get("dateTime"))
        patch = {field_name: _coerce_int(record.get("value"))}
        _merge_day_patch(day_map, metric_date=metric_date, source_name=source_name, record=record, patch=patch)


def _fitbit_merge_heart_series(day_map: dict[date, dict[str, Any]], *, records: list[dict[str, Any]]) -> None:
    for record in records:
        metric_date = _coerce_date(record.get("dateTime"))
        value = record.get("value")
        if isinstance(value, dict):
            resting_hr = _coerce_float(
                value.get("restingHeartRate")
                or value.get("resting_heart_rate")
                or value.get("value")
            )
        else:
            resting_hr = _coerce_float(value)
        patch = {"resting_hr_bpm": resting_hr}
        _merge_day_patch(day_map, metric_date=metric_date, source_name="heart", record=record, patch=patch)


def _sync_fitbit_connection(session, connection: WearableConnection) -> dict[str, Any]:
    start_date, end_date = _provider_sync_window(
        session,
        user_id=int(connection.user_id),
        provider="fitbit",
        lookback_days=DEFAULT_FITBIT_LOOKBACK_DAYS,
    )
    start_token = start_date.isoformat()
    end_token = end_date.isoformat()
    source_meta: dict[str, Any] = {}
    day_map: dict[date, dict[str, Any]] = {}

    profile = _fitbit_profile(connection)
    if profile:
        connection.provider_user_id = (
            str(profile.get("encodedId") or connection.provider_user_id or "").strip() or connection.provider_user_id
        )
        connection.external_user_ref = (
            str(profile.get("email") or connection.external_user_ref or "").strip() or connection.external_user_ref
        )
        connection.raw_profile = profile
        source_meta["profile"] = {"status": "ok", "path": "/1/user/-/profile.json"}

    series_specs = [
        ("steps", f"/1/user/-/activities/steps/date/{start_token}/{end_token}.json", "activities-steps", "steps"),
        ("calories", f"/1/user/-/activities/calories/date/{start_token}/{end_token}.json", "activities-calories", "calories"),
        ("sleep_minutes", f"/1/user/-/sleep/minutesAsleep/date/{start_token}/{end_token}.json", "sleep-minutesAsleep", "sleep_seconds"),
        ("sleep_efficiency", f"/1/user/-/sleep/efficiency/date/{start_token}/{end_token}.json", "sleep-efficiency", "sleep_score"),
    ]
    for source_name, path, response_key, field_name in series_specs:
        payload, meta = _fitbit_fetch_json(connection, path=path, required=False)
        source_meta[source_name] = meta
        if not payload:
            continue
        entries = _fitbit_series_entries(payload, response_key)
        if field_name == "sleep_seconds":
            for record in entries:
                metric_date = _coerce_date(record.get("dateTime"))
                minutes_asleep = _coerce_int(record.get("value"))
                patch = {"sleep_seconds": int(minutes_asleep * 60) if minutes_asleep is not None else None}
                _merge_day_patch(day_map, metric_date=metric_date, source_name=source_name, record=record, patch=patch)
        else:
            _fitbit_merge_simple_series(day_map, source_name=source_name, records=entries, field_name=field_name)

    heart_payload, heart_meta = _fitbit_fetch_json(
        connection,
        path=f"/1/user/-/activities/heart/date/{start_token}/{end_token}.json",
        required=False,
    )
    source_meta["heart"] = heart_meta
    if heart_payload:
        heart_entries = _fitbit_series_entries(heart_payload, "activities-heart")
        _fitbit_merge_heart_series(day_map, records=heart_entries)

    records_synced = _upsert_daily_metrics(session, connection=connection, provider="fitbit", day_map=day_map)
    session.commit()
    return {
        "provider": "fitbit",
        "records_synced": records_synced,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sources": source_meta,
    }
