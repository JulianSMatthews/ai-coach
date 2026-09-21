"""Explicitly configured store-review credentials; ordinary login remains unchanged."""

import os
import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ReviewLogin:
    first_name: str
    code: str


def review_login(*, phone_raw: object, email_raw: object, normalize_phone: Callable[[str], str]) -> ReviewLogin | None:
    if email_raw or not phone_raw:
        return None
    try:
        phone = normalize_phone(str(phone_raw))
    except Exception:
        return None
    matches = []
    for prefix, name in (("APP_REVIEW_DEMO", "Apple"), ("GOOGLE_PLAY_REVIEW_DEMO", "Google")):
        if os.getenv(f"{prefix}_ENABLED", "").strip().lower() not in {"1", "true", "yes", "on"}:
            continue
        configured_phone = os.getenv(f"{prefix}_PHONE", "").strip()
        if not configured_phone:
            continue
        try:
            if normalize_phone(configured_phone) != phone:
                continue
        except Exception:
            continue
        # Preserve the existing Apple configuration; Google requires an explicit code.
        code = os.getenv(f"{prefix}_CODE", "").strip()
        if not code and prefix == "APP_REVIEW_DEMO":
            code = "123456"
        if not re.fullmatch(r"[0-9]{6}", code):
            return None
        matches.append(ReviewLogin(name, code))
    # A duplicate phone configuration must not select the wrong store's credentials.
    return matches[0] if len(matches) == 1 else None
