from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests

from .models import WearableConnection, WearableDailyMetric, WearableSyncRun


OURA_AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
OURA_TOKEN_URL = "https://api.ouraring.com/oauth/token"
OURA_API_BASE_URL = "https://api.ouraring.com"
DEFAULT_OURA_SCOPE = "daily personal email"
DEFAULT_OURA_LOOKBACK_DAYS = 30
_WEARABLE_STATE_VERSION = 1
_WEARABLE_STATE_RUNTIME_SECRET = secrets.token_urlsafe(48)


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
        availability="coming_soon",
        description="WHOOP OAuth/web integration planned on the same wearable foundation.",
        supports_web_oauth=True,
        default_note="Provider card is live, but the WHOOP adapter is not wired yet.",
    ),
    "fitbit": WearableProviderDefinition(
        key="fitbit",
        label="Fitbit",
        availability="coming_soon",
        description="Fitbit OAuth/web integration planned on the same wearable foundation.",
        supports_web_oauth=True,
        default_note="Provider card is live, but the Fitbit adapter is not wired yet.",
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
    "apple_health": WearableProviderDefinition(
        key="apple_health",
        label="Apple Health",
        availability="requires_app",
        description="Apple Health needs an iPhone app bridge using HealthKit.",
        supports_web_oauth=False,
        requires_native_app=True,
        default_note="Requires a native iPhone app or wrapper to read HealthKit data.",
    ),
}


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
    return ""


def provider_enabled(provider: str) -> bool:
    key = str(provider or "").strip().lower()
    specific = os.getenv(f"WEARABLE_{key.upper()}_ENABLED")
    if specific is not None and str(specific).strip() != "":
        return _env_flag(f"WEARABLE_{key.upper()}_ENABLED", False)
    return _env_flag("WEARABLES_ENABLED", True)


def provider_configured(provider: str) -> bool:
    key = str(provider or "").strip().lower()
    if key == "apple_health":
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


def build_connect_url(
    provider: str,
    *,
    user_id: int,
    request_base_url: str | None = None,
    redirect_path: str | None = None,
) -> str:
    definition = get_provider_definition(provider)
    if not definition.connect_implemented:
        raise ValueError(f"{definition.label} connect flow is not implemented yet.")
    if not provider_enabled(definition.key):
        raise ValueError(f"{definition.label} is disabled.")
    if not provider_configured(definition.key):
        raise ValueError(f"{definition.label} credentials are not configured.")

    if definition.key == "oura":
        query: dict[str, str] = {
            "response_type": "code",
            "client_id": provider_client_id("oura"),
            "redirect_uri": build_callback_url("oura", request_base_url),
            "state": mint_wearable_oauth_state(
                user_id=int(user_id),
                provider="oura",
                redirect_path=redirect_path,
            ),
        }
        scope = provider_scope("oura")
        if scope:
            query["scope"] = scope
        return f"{OURA_AUTHORIZE_URL}?{urlencode(query)}"

    raise ValueError(f"{definition.label} connect flow is not implemented yet.")


def exchange_code_for_tokens(
    provider: str,
    *,
    code: str,
    request_base_url: str | None = None,
) -> dict[str, Any]:
    definition = get_provider_definition(provider)
    if definition.key != "oura":
        raise ValueError(f"{definition.label} code exchange is not implemented yet.")
    client_id = provider_client_id("oura")
    client_secret = provider_client_secret("oura")
    if not client_id or not client_secret:
        raise ValueError("Oura credentials are not configured.")
    resp = requests.post(
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
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Oura token response.")
    return payload


def refresh_connection_token(connection: WearableConnection, *, request_base_url: str | None = None) -> dict[str, Any] | None:
    provider = str(getattr(connection, "provider", "") or "").strip().lower()
    if provider != "oura":
        return None
    client_id = provider_client_id("oura")
    client_secret = provider_client_secret("oura")
    refresh_token = str(getattr(connection, "refresh_token", "") or "").strip()
    if not client_id or not client_secret or not refresh_token:
        return None
    resp = requests.post(
        OURA_TOKEN_URL,
        auth=(client_id, client_secret),
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict):
        raise ValueError("Unexpected Oura refresh-token response.")
    _apply_token_payload(connection, payload)
    return payload


def _utcnow() -> datetime:
    return datetime.utcnow()


def _apply_token_payload(connection: WearableConnection, payload: dict[str, Any]) -> None:
    expires_in = payload.get("expires_in")
    try:
        expires_in_seconds = int(expires_in) if expires_in is not None else None
    except Exception:
        expires_in_seconds = None
    connection.access_token = str(payload.get("access_token") or "").strip() or None
    connection.refresh_token = str(payload.get("refresh_token") or "").strip() or None
    connection.token_type = str(payload.get("token_type") or "").strip() or None
    connection.scope = str(payload.get("scope") or "").strip() or None
    connection.expires_at = (
        _utcnow() + timedelta(seconds=max(0, expires_in_seconds))
        if expires_in_seconds is not None
        else None
    )


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


def _oura_headers(access_token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }


def _ensure_oura_access_token(connection: WearableConnection) -> str:
    access_token = str(getattr(connection, "access_token", "") or "").strip()
    expires_at = getattr(connection, "expires_at", None)
    if access_token and (not expires_at or expires_at > (_utcnow() + timedelta(minutes=2))):
        return access_token
    payload = refresh_connection_token(connection)
    refreshed = str((payload or {}).get("access_token") or getattr(connection, "access_token", "") or "").strip()
    if not refreshed:
        raise ValueError("Oura access token is missing and could not be refreshed.")
    return refreshed


def _oura_api_get(connection: WearableConnection, path: str, *, params: dict[str, Any] | None = None) -> requests.Response:
    access_token = _ensure_oura_access_token(connection)
    response = requests.get(
        f"{OURA_API_BASE_URL}{path}",
        headers=_oura_headers(access_token),
        params=params or None,
        timeout=30,
    )
    if response.status_code == 401 and str(getattr(connection, "refresh_token", "") or "").strip():
        refresh_connection_token(connection)
        response = requests.get(
            f"{OURA_API_BASE_URL}{path}",
            headers=_oura_headers(str(getattr(connection, "access_token", "") or "").strip()),
            params=params or None,
            timeout=30,
        )
    return response


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
        resp = _oura_api_get(connection, path, params=params)
        if resp.status_code == 404 and not required:
            return [], {"status": "unavailable", "http_status": 404, "path": path}
        if resp.status_code == 400 and not required:
            return [], {"status": "unsupported", "http_status": 400, "path": path}
        if resp.status_code >= 400:
            last_error = f"Oura {path} returned {resp.status_code}: {resp.text[:300]}"
            if not required:
                return [], {"status": "error", "http_status": resp.status_code, "path": path, "error": last_error}
            if params is None:
                raise ValueError(last_error)
            continue
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else payload
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)], {
                "status": "ok",
                "http_status": resp.status_code,
                "path": path,
                "count": len(data),
            }
        if isinstance(payload, dict):
            return [], {
                "status": "ok",
                "http_status": resp.status_code,
                "path": path,
                "count": 0,
                "has_payload": True,
            }
        return [], {"status": "ok", "http_status": resp.status_code, "path": path, "count": 0}
    if last_error:
        raise ValueError(last_error)
    return [], {"status": "ok", "http_status": 200, "path": path, "count": 0}


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
    today = date.today()
    latest_day = (
        session.query(WearableDailyMetric.metric_date)
        .filter(
            WearableDailyMetric.user_id == int(connection.user_id),
            WearableDailyMetric.provider == "oura",
        )
        .order_by(WearableDailyMetric.metric_date.desc())
        .limit(1)
        .scalar()
    )
    if latest_day:
        start_date = max(today - timedelta(days=DEFAULT_OURA_LOOKBACK_DAYS), latest_day - timedelta(days=2))
    else:
        start_date = today - timedelta(days=DEFAULT_OURA_LOOKBACK_DAYS)
    end_date = today

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
            if not metric_date:
                continue
            bucket = day_map.setdefault(metric_date, {"raw_payload": {}})
            raw_payload = bucket.get("raw_payload") if isinstance(bucket.get("raw_payload"), dict) else {}
            raw_payload[source_name] = record
            bucket["raw_payload"] = raw_payload
            for key, value in patch.items():
                if value is not None:
                    bucket[key] = value

    if not day_map:
        return {
            "provider": "oura",
            "records_synced": 0,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "sources": source_meta,
        }

    existing = {
        row.metric_date: row
        for row in session.query(WearableDailyMetric)
        .filter(
            WearableDailyMetric.user_id == int(connection.user_id),
            WearableDailyMetric.provider == "oura",
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
                provider="oura",
                metric_date=metric_date,
            )
            session.add(row)
            existing[metric_date] = row
        row.connection_id = int(connection.id)
        row.sleep_seconds = payload.get("sleep_seconds") if payload.get("sleep_seconds") is not None else row.sleep_seconds
        row.sleep_score = payload.get("sleep_score") if payload.get("sleep_score") is not None else row.sleep_score
        row.readiness_score = (
            payload.get("readiness_score") if payload.get("readiness_score") is not None else row.readiness_score
        )
        row.hrv_ms = payload.get("hrv_ms") if payload.get("hrv_ms") is not None else row.hrv_ms
        row.resting_hr_bpm = (
            payload.get("resting_hr_bpm") if payload.get("resting_hr_bpm") is not None else row.resting_hr_bpm
        )
        row.steps = payload.get("steps") if payload.get("steps") is not None else row.steps
        row.active_minutes = payload.get("active_minutes") if payload.get("active_minutes") is not None else row.active_minutes
        row.calories = payload.get("calories") if payload.get("calories") is not None else row.calories
        row.strain_score = payload.get("strain_score") if payload.get("strain_score") is not None else row.strain_score
        existing_raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        incoming_raw = payload.get("raw_payload") if isinstance(payload.get("raw_payload"), dict) else {}
        row.raw_payload = {**existing_raw, **incoming_raw}
        row.synced_at = synced_at
        records_synced += 1

    session.commit()
    return {
        "provider": "oura",
        "records_synced": records_synced,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "sources": source_meta,
    }
