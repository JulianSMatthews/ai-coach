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


def active_pillar_keys() -> tuple[str, ...]:
    raw = os.getenv("HEALTHSENSE_ACTIVE_PILLARS") or os.getenv("ACTIVE_PILLARS") or ""
    configured = _dedupe_known(raw.split(",")) if raw.strip() else ()
    return configured or DEFAULT_ACTIVE_PILLARS


ACTIVE_PILLAR_KEYS: tuple[str, ...] = active_pillar_keys()
