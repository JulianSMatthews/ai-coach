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
    "COACH_NAME",
    "WEEKSTART_PODCAST_MAX_WORDS",
    "REPORTS_BASE_URL",
    "TWILIO_STATUS_CALLBACK_URL",
]


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

    print("[env-check] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
