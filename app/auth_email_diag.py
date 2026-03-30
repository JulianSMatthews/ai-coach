from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode, urlparse


def _normalize_email(value: object) -> str:
    return str(value or "").strip().lower()


def _parse_error(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        payload = json.loads(text)
    except Exception:
        return text
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return text
    direct = payload.get("error_description") or payload.get("detail") or payload.get("message")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    nested = payload.get("error")
    if isinstance(nested, dict):
        code = str(nested.get("code") or "").strip()
        message = str(nested.get("message") or "").strip()
        if code and message:
            return f"{code}: {message}"
        if message:
            return message
        if code:
            return code
    if isinstance(nested, str) and nested.strip():
        return nested.strip()
    return text


def _normalize_url(value: str, *, default: str) -> str:
    raw = str(value or "").strip().rstrip("/")
    return raw or default


def _token_url_from_env(tenant_id: str) -> str:
    token_base = _normalize_url(
        os.getenv("AUTH_MS_GRAPH_TOKEN_BASE_URL") or "",
        default="https://login.microsoftonline.com",
    )
    return f"{token_base}/{tenant_id}/oauth2/v2.0/token"


def _graph_config_from_env() -> dict[str, Any]:
    transport = (os.getenv("AUTH_EMAIL_TRANSPORT") or "auto").strip().lower() or "auto"
    sender = _normalize_email(os.getenv("AUTH_MS_GRAPH_SENDER") or os.getenv("AUTH_EMAIL_FROM") or "")
    tenant_id = str(os.getenv("AUTH_MS_GRAPH_TENANT_ID") or "").strip()
    client_id = str(os.getenv("AUTH_MS_GRAPH_CLIENT_ID") or "").strip()
    client_secret = os.getenv("AUTH_MS_GRAPH_CLIENT_SECRET") or ""
    scope = str(os.getenv("AUTH_MS_GRAPH_SCOPE") or "https://graph.microsoft.com/.default").strip()
    api_base_url = _normalize_url(
        os.getenv("AUTH_MS_GRAPH_API_BASE_URL") or "",
        default="https://graph.microsoft.com/v1.0",
    )
    timeout_raw = str(
        os.getenv("AUTH_MS_GRAPH_TIMEOUT_SECONDS")
        or os.getenv("AUTH_SMTP_TIMEOUT_SECONDS")
        or "20"
    ).strip()
    try:
        timeout = max(1.0, float(timeout_raw))
    except Exception:
        timeout = 20.0
    graph_keys = (tenant_id, client_id, client_secret, sender)
    using_graph = transport == "microsoft_graph" or any(bool(v) for v in graph_keys)
    missing = []
    if using_graph:
        if not tenant_id:
            missing.append("AUTH_MS_GRAPH_TENANT_ID")
        if not client_id:
            missing.append("AUTH_MS_GRAPH_CLIENT_ID")
        if not client_secret:
            missing.append("AUTH_MS_GRAPH_CLIENT_SECRET")
        if not sender:
            missing.append("AUTH_MS_GRAPH_SENDER or AUTH_EMAIL_FROM")
    token_url = _token_url_from_env(tenant_id or "<missing-tenant>")
    return {
        "transport": transport,
        "using_graph": using_graph,
        "tenant_id": tenant_id,
        "client_id": client_id,
        "client_secret_present": bool(client_secret),
        "client_secret": client_secret,
        "sender": sender,
        "scope": scope,
        "api_base_url": api_base_url,
        "token_url": token_url,
        "timeout": timeout,
        "missing": missing,
    }


def _public_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        pass
    return url


def _http_error_summary(exc: urllib.error.HTTPError, *, url: str) -> dict[str, Any]:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    headers = getattr(exc, "headers", None)
    picked_headers: dict[str, str] = {}
    if headers is not None:
        for header_name in (
            "WWW-Authenticate",
            "request-id",
            "client-request-id",
            "x-ms-request-id",
            "Date",
        ):
            try:
                value = headers.get(header_name)
            except Exception:
                value = None
            normalized = " ".join(str(value or "").split()).strip()
            if normalized:
                picked_headers[header_name] = normalized
    return {
        "status": int(getattr(exc, "code", 0) or 0),
        "url": _public_url(url),
        "detail": _parse_error(body) or str(exc),
        "headers": picked_headers,
        "raw_body": body,
    }


def _decode_claims(token: str) -> dict[str, Any]:
    parts = str(token or "").split(".")
    if len(parts) < 2:
        return {}
    payload_part = parts[1]
    padding = "=" * (-len(payload_part) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_part + padding)
        payload = json.loads(decoded.decode("utf-8", errors="replace"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _selected_claims(token: str) -> dict[str, Any]:
    claims = _decode_claims(token)
    if not claims:
        return {}
    selected: dict[str, Any] = {}
    for key in ("aud", "iss", "tid", "appid", "azp", "sub", "scp", "roles"):
        value = claims.get(key)
        if value not in (None, "", []):
            selected[key] = value
    exp = claims.get("exp")
    try:
        if exp is not None:
            selected["exp_utc"] = datetime.fromtimestamp(int(exp), tz=timezone.utc).isoformat()
    except Exception:
        pass
    return selected


def request_graph_token(config: dict[str, Any]) -> dict[str, Any]:
    body = urlencode(
        {
            "client_id": config["client_id"],
            "scope": config["scope"],
            "client_secret": config["client_secret"],
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        str(config["token_url"]),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config["timeout"])) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        summary = _http_error_summary(exc, url=str(config["token_url"]))
        summary["ok"] = False
        return summary
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "url": _public_url(str(config["token_url"])),
            "detail": str(exc),
            "headers": {},
        }

    try:
        payload = json.loads(raw)
    except Exception:
        return {
            "ok": False,
            "status": 200,
            "url": _public_url(str(config["token_url"])),
            "detail": "token response was not valid JSON",
            "headers": {},
        }

    access_token = str((payload or {}).get("access_token") or "").strip()
    if not access_token:
        return {
            "ok": False,
            "status": 200,
            "url": _public_url(str(config["token_url"])),
            "detail": _parse_error(raw) or "missing access token",
            "headers": {},
        }

    return {
        "ok": True,
        "status": 200,
        "url": _public_url(str(config["token_url"])),
        "token": access_token,
        "claims": _selected_claims(access_token),
    }


def probe_graph_sendmail(config: dict[str, Any], *, access_token: str) -> dict[str, Any]:
    sender = str(config["sender"])
    send_url = f"{str(config['api_base_url'])}/users/{quote(sender, safe='')}/sendMail"
    request = urllib.request.Request(
        send_url,
        data=b"{}",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config["timeout"])) as response:
            status = int(getattr(response, "status", 202) or 202)
            response.read()
    except urllib.error.HTTPError as exc:
        summary = _http_error_summary(exc, url=send_url)
        status = int(summary.get("status") or 0)
        classification = "unknown"
        auth_ok = False
        if status == 400:
            classification = "authenticated_but_body_invalid"
            auth_ok = True
        elif status == 401:
            classification = "authentication_failed"
        elif status == 403:
            classification = "authenticated_but_not_authorized"
        elif status == 404:
            classification = "sender_not_found"
        summary["ok"] = auth_ok
        summary["classification"] = classification
        return summary
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "url": _public_url(send_url),
            "detail": str(exc),
            "headers": {},
            "classification": "request_failed",
        }

    return {
        "ok": status == 202,
        "status": status,
        "url": _public_url(send_url),
        "detail": "request accepted",
        "headers": {},
        "classification": "request_accepted",
    }


def probe_graph_sender_user(config: dict[str, Any], *, access_token: str) -> dict[str, Any]:
    sender = str(config["sender"])
    user_url = f"{str(config['api_base_url'])}/users/{quote(sender, safe='')}?$select=id,userPrincipalName,mail,accountEnabled"
    request = urllib.request.Request(
        user_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(config["timeout"])) as response:
            raw = response.read().decode("utf-8", errors="replace")
            status = int(getattr(response, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        summary = _http_error_summary(exc, url=user_url)
        status = int(summary.get("status") or 0)
        classification = "unknown"
        if status == 401:
            classification = "authentication_failed"
        elif status == 403:
            classification = "sender_lookup_forbidden"
        elif status == 404:
            classification = "sender_not_found"
        summary["ok"] = False
        summary["classification"] = classification
        return summary
    except Exception as exc:
        return {
            "ok": False,
            "status": None,
            "url": _public_url(user_url),
            "detail": str(exc),
            "headers": {},
            "classification": "request_failed",
        }

    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}

    if not isinstance(payload, dict):
        payload = {}

    user_summary = {
        "id": payload.get("id"),
        "userPrincipalName": payload.get("userPrincipalName"),
        "mail": payload.get("mail"),
        "accountEnabled": payload.get("accountEnabled"),
    }
    return {
        "ok": True,
        "status": status,
        "url": _public_url(user_url),
        "detail": "sender resolved",
        "headers": {},
        "classification": "sender_resolved",
        "user": user_summary,
    }


def run_auth_email_diagnostics(*, probe: str = "sendmail") -> dict[str, Any]:
    config = _graph_config_from_env()
    result: dict[str, Any] = {
        "transport": config["transport"],
        "using_graph": bool(config["using_graph"]),
        "config": {
            "sender": config["sender"],
            "scope": config["scope"],
            "token_url": _public_url(str(config["token_url"])),
            "api_base_url": _public_url(str(config["api_base_url"])),
            "client_id_present": bool(config["client_id"]),
            "client_secret_present": bool(config["client_secret_present"]),
            "tenant_id_present": bool(config["tenant_id"]),
            "missing": list(config["missing"]),
        },
        "probe": probe,
        "token": None,
        "sender_probe": None,
        "sendmail_probe": None,
        "ok": False,
    }
    if not config["using_graph"]:
        result["detail"] = "Microsoft Graph auth email is not enabled by current env."
        return result
    if config["missing"]:
        result["detail"] = "Missing Microsoft Graph auth email config."
        return result

    token_result = request_graph_token(config)
    result["token"] = {k: v for k, v in token_result.items() if k != "token"}
    if not token_result.get("ok"):
        result["detail"] = "Token request failed."
        return result

    if probe == "token":
        result["ok"] = True
        result["detail"] = "Token request succeeded."
        return result

    sender_probe = probe_graph_sender_user(config, access_token=str(token_result["token"]))
    result["sender_probe"] = sender_probe

    sendmail_result = probe_graph_sendmail(config, access_token=str(token_result["token"]))
    result["sendmail_probe"] = sendmail_result
    result["ok"] = bool(sendmail_result.get("ok"))
    result["detail"] = "SendMail probe succeeded." if result["ok"] else "SendMail probe failed."
    return result


def format_auth_email_diagnostic_report(result: dict[str, Any]) -> list[str]:
    lines = [
        (
            f"transport={result.get('transport')} using_graph={result.get('using_graph')} "
            f"probe={result.get('probe')} ok={result.get('ok')}"
        )
    ]
    config = result.get("config") or {}
    lines.append(
        "config "
        + " ".join(
            [
                f"sender={config.get('sender') or '<missing>'}",
                f"scope={config.get('scope') or '<missing>'}",
                f"token_url={config.get('token_url') or '<missing>'}",
                f"api_base_url={config.get('api_base_url') or '<missing>'}",
            ]
        )
    )
    missing = config.get("missing") or []
    if missing:
        lines.append("missing " + ", ".join(str(item) for item in missing))
    token = result.get("token") or {}
    if token:
        claims = token.get("claims") or {}
        claims_bits = []
        for key in ("aud", "tid", "appid", "azp", "roles", "scp", "exp_utc"):
            value = claims.get(key)
            if value not in (None, "", []):
                claims_bits.append(f"{key}={value}")
        lines.append(
            f"token status={token.get('status')} detail={token.get('detail') or 'ok'}"
            + (f" {' '.join(claims_bits)}" if claims_bits else "")
        )
    sender_probe = result.get("sender_probe") or {}
    if sender_probe:
        sender_bits = []
        user = sender_probe.get("user") or {}
        for key in ("id", "userPrincipalName", "mail", "accountEnabled"):
            value = user.get(key)
            if value not in (None, "", []):
                sender_bits.append(f"{key}={value}")
        header_bits = []
        headers = sender_probe.get("headers") or {}
        for key in ("WWW-Authenticate", "request-id", "client-request-id", "x-ms-request-id", "Date"):
            value = headers.get(key)
            if value:
                header_bits.append(f"{key}={value}")
        lines.append(
            f"sender_probe status={sender_probe.get('status')} "
            f"classification={sender_probe.get('classification')} "
            f"detail={sender_probe.get('detail')}"
            + (f" {' '.join(sender_bits)}" if sender_bits else "")
            + (f" {' '.join(header_bits)}" if header_bits else "")
        )
    sendmail_probe = result.get("sendmail_probe") or {}
    if sendmail_probe:
        header_bits = []
        headers = sendmail_probe.get("headers") or {}
        for key in ("WWW-Authenticate", "request-id", "client-request-id", "x-ms-request-id", "Date"):
            value = headers.get(key)
            if value:
                header_bits.append(f"{key}={value}")
        lines.append(
            f"sendmail_probe status={sendmail_probe.get('status')} "
            f"classification={sendmail_probe.get('classification')} "
            f"detail={sendmail_probe.get('detail')}"
            + (f" {' '.join(header_bits)}" if header_bits else "")
        )
    detail = str(result.get("detail") or "").strip()
    if detail:
        lines.append(f"summary {detail}")
    return lines
