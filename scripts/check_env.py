#!/usr/bin/env python3
"""
Environment check for production deploys.
Usage: python scripts/check_env.py --service api
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable, List, Tuple


REQUIRED_API: List[Tuple[str, ...]] = [
    ("ENV",),
    ("DATABASE_URL",),
    ("OPENAI_API_KEY",),
    ("ADMIN_API_TOKEN",),
    ("TWILIO_ACCOUNT_SID",),
    ("TWILIO_AUTH_TOKEN",),
    ("TWILIO_FROM",),
    # One of these must be set for public links.
    ("PUBLIC_BASE_URL", "API_PUBLIC_BASE_URL"),
]

OPTIONAL_API = [
    "ASS_MODEL",
    "LLM_MODEL",
    "COACH_NAME",
    "WEEKSTART_PODCAST_MAX_WORDS",
    "REPORTS_BASE_URL",
    "HSAPP_PUBLIC_URL",
    "HSAPP_PUBLIC_DEFAULT_URL",
    "TWILIO_STATUS_CALLBACK_URL",
    "TWILIO_SMS_FROM",
    "AUTH_SMS_IF_NO_WHATSAPP_WINDOW",
    "AUTH_WHATSAPP_OPEN_WINDOW_HOURS",
    "TWILIO_REOPEN_CONTENT_SID",
    "USE_AZURE_SPEECH",
    "AZURE_SPEECH_KEY",
    "AZURE_SPEECH_REGION",
    "AZURE_SPEECH_ENDPOINT",
    "USE_AZURE_AVATAR",
    "USE_AZURE_AVATAR_REALTIME_SUMMARY",
    "AZURE_AVATAR_KEY",
    "AZURE_AVATAR_REGION",
    "AZURE_AVATAR_ENDPOINT",
    "AZURE_AVATAR_REALTIME_SUMMARY_MAX_SESSION_SECONDS",
    "AZURE_AVATAR_REALTIME_SUMMARY_MAX_REPLAYS",
    "AZURE_AVATAR_GBP_PER_MINUTE",
    "AZURE_AVATAR_CHARS_PER_MIN",
]


def _warn_auth_email_config() -> None:
    transport = (os.getenv("AUTH_EMAIL_TRANSPORT") or "auto").strip().lower() or "auto"
    graph_keys = (
        "AUTH_MS_GRAPH_TENANT_ID",
        "AUTH_MS_GRAPH_CLIENT_ID",
        "AUTH_MS_GRAPH_CLIENT_SECRET",
        "AUTH_MS_GRAPH_SENDER",
    )
    smtp_keys = (
        "AUTH_SMTP_HOST",
        "AUTH_SMTP_PORT",
        "AUTH_SMTP_USERNAME",
        "AUTH_SMTP_PASSWORD",
        "AUTH_SMTP_USE_TLS",
        "AUTH_SMTP_USE_SSL",
    )
    if transport == "microsoft_graph":
        using_graph = True
        using_smtp = False
    elif transport == "smtp":
        using_graph = False
        using_smtp = True
    else:
        using_graph = any(_is_set(k) for k in graph_keys)
        using_smtp = not using_graph and any(_is_set(k) for k in smtp_keys)

    if transport not in {"auto", "smtp", "microsoft_graph"}:
        print("[env-check] Auth email config warning:")
        print("  - AUTH_EMAIL_TRANSPORT must be auto, smtp, or microsoft_graph")
        return

    if using_graph:
        missing: List[str] = []
        if not _is_set("AUTH_MS_GRAPH_TENANT_ID"):
            missing.append("AUTH_MS_GRAPH_TENANT_ID")
        if not _is_set("AUTH_MS_GRAPH_CLIENT_ID"):
            missing.append("AUTH_MS_GRAPH_CLIENT_ID")
        if not _is_set("AUTH_MS_GRAPH_CLIENT_SECRET"):
            missing.append("AUTH_MS_GRAPH_CLIENT_SECRET")
        if not (_is_set("AUTH_MS_GRAPH_SENDER") or _is_set("AUTH_EMAIL_FROM")):
            missing.append("AUTH_MS_GRAPH_SENDER or AUTH_EMAIL_FROM")
        if missing:
            print("[env-check] Auth email Graph config warning:")
            for item in missing:
                print(f"  - {item}")

    if using_smtp:
        missing: List[str] = []
        if not _is_set("AUTH_SMTP_HOST"):
            missing.append("AUTH_SMTP_HOST")
        if not _is_set("AUTH_EMAIL_FROM"):
            missing.append("AUTH_EMAIL_FROM")
        if _is_set("AUTH_SMTP_USERNAME") != _is_set("AUTH_SMTP_PASSWORD"):
            missing.append("AUTH_SMTP_USERNAME and AUTH_SMTP_PASSWORD must both be set")
        if missing:
            print("[env-check] Auth email SMTP config warning:")
            for item in missing:
                print(f"  - {item}")


def _is_set(key: str) -> bool:
    return bool((os.getenv(key) or "").strip())


def _missing(groups: Iterable[Tuple[str, ...]]) -> List[str]:
    missing: List[str] = []
    for group in groups:
        if any(_is_set(k) for k in group):
            continue
        if len(group) == 1:
            missing.append(group[0])
        else:
            missing.append(" | ".join(group))
    return missing


def _warn_optional(keys: Iterable[str]) -> None:
    missing = [k for k in keys if not _is_set(k)]
    if not missing:
        return
    print("[env-check] Optional vars missing:")
    for k in missing:
        print(f"  - {k}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate required environment variables.")
    parser.add_argument(
        "--service",
        default="api",
        choices=["api"],
        help="Which service to validate (default: api)",
    )
    parser.add_argument(
        "--warn-optional",
        action="store_true",
        help="Also list optional variables that are missing",
    )
    args = parser.parse_args()

    if args.service != "api":
        print("[env-check] Unknown service")
        return 2

    missing = _missing(REQUIRED_API)
    if missing:
        print("[env-check] Missing required environment variables:")
        for item in missing:
            print(f"  - {item}")
        return 1

    if args.warn_optional:
        _warn_optional(OPTIONAL_API)
        _warn_auth_email_config()

    print("[env-check] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
