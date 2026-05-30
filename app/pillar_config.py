from __future__ import annotations

import os
from typing import Iterable

ALL_PILLAR_ORDER: tuple[str, ...] = (
    "nutrition",
    "training",
    "reflection",
    "purpose",
    "resilience",
    "recovery",
)

DEFAULT_ACTIVE_PILLARS: tuple[str, ...] = (
    "reflection",
    "purpose",
    "resilience",
    "recovery",
)

HOME_PILLAR_PREF_KEYS: dict[str, str] = {
    "nutrition": "home_pillar_nutrition",
    "training": "home_pillar_training",
}

PILLAR_LABELS: dict[str, str] = {
    "nutrition": "Nutrition",
    "training": "Training",
    "reflection": "Reflection",
    "purpose": "Purpose",
    "resilience": "Resilience",
    "recovery": "Recovery",
}


def normalize_pillar_key(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def pillar_label(pillar_key: str | None) -> str:
    key = normalize_pillar_key(pillar_key)
    return PILLAR_LABELS.get(key, key.replace("_", " ").title())


def _dedupe_known(keys: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    allowed = set(ALL_PILLAR_ORDER)
    for raw in keys:
        key = normalize_pillar_key(raw)
        if key in allowed and key not in seen:
            seen.add(key)
            out.append(key)
    return tuple(out)


def _resolve_home_pillar_keys(user_id: int | None) -> tuple[str, ...]:
    if user_id is None:
        return ()
    try:
        from .db import SessionLocal
        from .models import UserPreference
    except Exception:
        return ()
    with SessionLocal() as s:
        rows = (
            s.query(UserPreference)
            .filter(
                UserPreference.user_id == int(user_id),
                UserPreference.key.in_(tuple(HOME_PILLAR_PREF_KEYS.values())),
            )
            .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
            .all()
        )
    pref_map: dict[str, str] = {}
    for row in rows:
        key = str(getattr(row, "key", "") or "").strip().lower()
        if key in pref_map:
            continue
        pref_map[key] = str(getattr(row, "value", "") or "").strip()
    resolved: list[str] = []
    for pillar_key, pref_key in HOME_PILLAR_PREF_KEYS.items():
        raw = pref_map.get(pref_key, "")
        token = str(raw or "").strip().lower()
        if token in {"1", "true", "yes", "on"}:
            resolved.append(pillar_key)
        elif token in {"0", "false", "no", "off"}:
            continue
    return tuple(resolved)


def active_pillar_keys(user_id: int | None = None) -> tuple[str, ...]:
    raw = (
        os.getenv("COACHSENSE_ACTIVE_PILLARS")
        or os.getenv("HEALTHSENSE_ACTIVE_PILLARS")
        or os.getenv("ACTIVE_PILLARS")
        or ""
    )
    configured = _dedupe_known(raw.split(",")) if raw.strip() else ()
    base = list(configured or DEFAULT_ACTIVE_PILLARS)
    if user_id is not None:
        resolved_home_keys = _resolve_home_pillar_keys(user_id)
        for key in resolved_home_keys:
            if key not in base:
                base.append(key)
        for key in HOME_PILLAR_PREF_KEYS:
            if key not in resolved_home_keys and key in base and key not in DEFAULT_ACTIVE_PILLARS:
                base.remove(key)
    return _dedupe_known(base) or DEFAULT_ACTIVE_PILLARS


ACTIVE_PILLAR_KEYS: tuple[str, ...] = active_pillar_keys()
