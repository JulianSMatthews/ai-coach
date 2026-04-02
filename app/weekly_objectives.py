from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc

from .db import SessionLocal
from .models import OKRKeyResult, OKRObjective, UserPreference
from .okr import _GUIDE, _normalize_concept_key, ensure_cycle
from .pillar_tracker import (
    _pillar_label,
    _resolve_pillar_targets_for_user,
    start_of_week,
    tracker_concepts_for_pillar,
    tracker_today,
)

PILLAR_ORDER: tuple[str, ...] = ("nutrition", "training", "resilience", "recovery")
WELLBEING_KEY = "wellbeing"
FASTING_MODE_PREF_KEY = "weekly_objectives_fasting_mode"
FASTING_GOAL_DAYS_PREF_KEY = "weekly_objectives_fasting_goal_days"
ALCOHOL_TRACKING_PREF_KEY = "weekly_objectives_alcohol_tracking"
ALCOHOL_GOAL_UNITS_PREF_KEY = "weekly_objectives_alcohol_goal_units"

FASTING_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("off", "Off"),
    ("12:12", "12:12"),
    ("14:10", "14:10"),
    ("16:8", "16:8"),
    ("18:6", "18:6"),
)

BOOLEAN_TOGGLE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("off", "Off"),
    ("on", "On"),
)

FASTING_GOAL_DAYS_OPTIONS: tuple[tuple[str, str], ...] = tuple((str(value), str(value)) for value in range(0, 8))
ALCOHOL_GOAL_UNITS_OPTIONS: tuple[tuple[str, str], ...] = (
    ("0", "0"),
    ("2", "2"),
    ("4", "4"),
    ("6", "6"),
    ("8", "8"),
    ("10", "10"),
    ("12", "12"),
    ("14", "14"),
    ("16", "16"),
    ("18", "18"),
    ("21", "21"),
    ("28", "28"),
)


def _display_unit_label(unit: str | None) -> str | None:
    token = str(unit or "").strip()
    if not token:
        return None
    replacements = {
        "sessions/week": "sessions per week",
        "days/week": "days per week",
        "nights/week": "nights per week",
        "portions/day": "portions per day",
        "L/day": "L per day",
    }
    return replacements.get(token, token.replace("/", " per "))


def _concept_target_options(pillar_key: str, concept_key: str) -> list[dict[str, Any]]:
    concept_defs = {item.concept_key: item for item in tracker_concepts_for_pillar(pillar_key)}
    concept_def = concept_defs.get(concept_key)
    if concept_def is None:
        return []
    guide = (_GUIDE.get(pillar_key, {}) or {}).get(concept_key, {}) or {}
    unit = str(guide.get("unit") or "").strip().lower()
    if unit.endswith("/week") or unit.endswith("per week") or unit.endswith("week"):
        return [{"value": value, "label": str(value)} for value in range(0, 8)]
    return [
        {
            "value": float(option.value) if option.value is not None else None,
            "label": str(option.label or "").strip(),
        }
        for option in (concept_def.options or [])
    ]

def _current_cycle_objective(session, user_id: int, pillar_key: str) -> OKRObjective | None:
    cycle = ensure_cycle(session, datetime.now(timezone.utc))
    return (
        session.query(OKRObjective)
        .filter(
            OKRObjective.cycle_id == int(cycle.id),
            OKRObjective.owner_user_id == int(user_id),
            OKRObjective.pillar_key == str(pillar_key).strip().lower(),
        )
        .order_by(desc(OKRObjective.id))
        .first()
    )


def _kr_notes_dict(notes: str | None) -> dict[str, Any]:
    if not notes:
        return {}
    try:
        payload = json.loads(notes)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _kr_concept_key(pillar_key: str, kr: OKRKeyResult) -> str | None:
    notes_dict = _kr_notes_dict(getattr(kr, "notes", None))
    raw = notes_dict.get("concept_key")
    if raw:
        normalized = _normalize_concept_key(str(raw).split(".")[-1])
        return normalized or None
    kr_key = _normalize_concept_key(getattr(kr, "kr_key", None))
    if kr_key and kr_key.endswith("_target"):
        return kr_key[: -len("_target")] or None
    return None


def _primary_krs_by_concept(session, user_id: int, pillar_key: str) -> tuple[OKRObjective | None, dict[str, OKRKeyResult], list[OKRKeyResult]]:
    objective = _current_cycle_objective(session, int(user_id), pillar_key)
    if objective is None:
        return None, {}, []
    rows = (
        session.query(OKRKeyResult)
        .filter(OKRKeyResult.objective_id == int(objective.id))
        .order_by(desc(OKRKeyResult.updated_at), desc(OKRKeyResult.id))
        .all()
    )
    grouped: dict[str, list[OKRKeyResult]] = {}
    for row in rows:
        concept_key = _kr_concept_key(pillar_key, row)
        if not concept_key:
            continue
        grouped.setdefault(concept_key, []).append(row)
    primary: dict[str, OKRKeyResult] = {}
    duplicates: list[OKRKeyResult] = []
    for concept_key, concept_rows in grouped.items():
        primary[concept_key] = concept_rows[0]
        duplicates.extend(concept_rows[1:])
    return objective, primary, duplicates


def _objective_default_text(pillar_key: str) -> str:
    return f"Follow my {str(_pillar_label(pillar_key) or pillar_key).strip().lower()} objectives this week."


def _objective_concepts_payload(user_id: int, pillar_key: str) -> dict[str, Any]:
    required_concepts = tracker_concepts_for_pillar(pillar_key)
    resolved_targets = _resolve_pillar_targets_for_user(int(user_id), pillar_key, required_concepts)
    with SessionLocal() as s:
        objective, primary_krs, _duplicates = _primary_krs_by_concept(s, int(user_id), pillar_key)
        objective_text = str(getattr(objective, "objective", "") or "").strip() or _objective_default_text(pillar_key)
    concepts_payload: list[dict[str, Any]] = []
    configured_count = 0
    for concept_def in required_concepts:
        resolved_target = resolved_targets.get(concept_def.concept_key)
        primary_kr = primary_krs.get(concept_def.concept_key)
        selected_value = None
        if primary_kr is not None and getattr(primary_kr, "target_num", None) is not None:
            try:
                selected_value = float(getattr(primary_kr, "target_num"))
            except Exception:
                selected_value = None
        elif resolved_target is not None and getattr(resolved_target, "target_value", None) is not None:
            try:
                selected_value = float(getattr(resolved_target, "target_value"))
            except Exception:
                selected_value = None
        if selected_value is not None:
            configured_count += 1
        guide = (_GUIDE.get(pillar_key, {}) or {}).get(concept_def.concept_key, {}) or {}
        unit = str(getattr(primary_kr, "unit", None) or guide.get("unit") or getattr(resolved_target, "target_unit", None) or "").strip() or None
        metric_label = (
            str(getattr(primary_kr, "metric_label", None) or guide.get("label") or concept_def.label).strip()
            or concept_def.label
        )
        concepts_payload.append(
            {
                "concept_key": concept_def.concept_key,
                "label": concept_def.label,
                "helper": concept_def.helper,
                "metric_label": metric_label,
                "unit": unit,
                "unit_label": _display_unit_label(unit),
                "target_direction": getattr(resolved_target, "target_direction", None) or concept_def.target_direction,
                "target_source": getattr(resolved_target, "source", None),
                "target_label": getattr(resolved_target, "target_label", None),
                "selected_value": selected_value,
                "options": _concept_target_options(pillar_key, concept_def.concept_key),
            }
        )
    return {
        "pillar_key": pillar_key,
        "label": _pillar_label(pillar_key),
        "objective": objective_text,
        "concept_count": len(required_concepts),
        "configured_count": configured_count,
        "concepts": concepts_payload,
    }


def _pref_value(session, user_id: int, key: str) -> str | None:
    row = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == int(user_id), UserPreference.key == str(key))
        .one_or_none()
    )
    return str(getattr(row, "value", "") or "").strip() or None


def _set_pref_value(session, user_id: int, key: str, value: str) -> None:
    row = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == int(user_id), UserPreference.key == str(key))
        .one_or_none()
    )
    if row is None:
        session.add(UserPreference(user_id=int(user_id), key=str(key), value=str(value)))
        return
    row.value = str(value)
    session.add(row)


def _wellbeing_payload(user_id: int) -> dict[str, Any]:
    with SessionLocal() as s:
        fasting_mode = (_pref_value(s, int(user_id), FASTING_MODE_PREF_KEY) or "off").lower()
        if fasting_mode not in {value for value, _label in FASTING_MODE_OPTIONS}:
            fasting_mode = "off"
        fasting_goal_days = (_pref_value(s, int(user_id), FASTING_GOAL_DAYS_PREF_KEY) or "0").strip()
        if fasting_goal_days not in {value for value, _label in FASTING_GOAL_DAYS_OPTIONS}:
            fasting_goal_days = "0"
        if fasting_mode != "off" and fasting_goal_days == "0":
            fasting_goal_days = "7"
        alcohol_tracking = (_pref_value(s, int(user_id), ALCOHOL_TRACKING_PREF_KEY) or "off").lower()
        if alcohol_tracking not in {"on", "off"}:
            alcohol_tracking = "off"
        alcohol_goal_units = (_pref_value(s, int(user_id), ALCOHOL_GOAL_UNITS_PREF_KEY) or "0").strip()
        if alcohol_goal_units not in {value for value, _label in ALCOHOL_GOAL_UNITS_OPTIONS}:
            alcohol_goal_units = "0"
        if alcohol_tracking != "on":
            alcohol_goal_units = "0"
    items = [
        {
            "key": "fasting_mode",
            "label": "Fasting mode",
            "helper": "Optional weekly objective",
            "value": fasting_mode,
            "options": [{"value": value, "label": label} for value, label in FASTING_MODE_OPTIONS],
        },
        {
            "key": "fasting_goal_days",
            "label": "Fasting goal",
            "helper": "How many days this week to follow your fasting plan",
            "value": fasting_goal_days,
            "options": [{"value": value, "label": label} for value, label in FASTING_GOAL_DAYS_OPTIONS],
        },
        {
            "key": "alcohol_tracking",
            "label": "Alcohol tracking",
            "helper": "Turn alcohol tracking on or off",
            "value": alcohol_tracking,
            "options": [{"value": value, "label": label} for value, label in BOOLEAN_TOGGLE_OPTIONS],
        },
        {
            "key": "alcohol_goal_units",
            "label": "Alcohol goal",
            "helper": "Maximum alcohol units for the week",
            "value": alcohol_goal_units,
            "options": [{"value": value, "label": label} for value, label in ALCOHOL_GOAL_UNITS_OPTIONS],
        },
    ]
    configured_count = sum(
        1
        for item in items
        if (item["key"] == "fasting_mode" and item["value"] != "off")
        or (item["key"] == "fasting_goal_days" and item["value"] not in {"", "0"})
        or (item["key"] == "alcohol_tracking" and item["value"] == "on")
        or (item["key"] == "alcohol_goal_units" and item["value"] not in {"", "0"})
    )
    return {
        "title": "Wellbeing objectives",
        "configured_count": configured_count,
        "items": items,
    }


def get_weekly_objectives_config(user_id: int) -> dict[str, Any]:
    pillars = [_objective_concepts_payload(int(user_id), pillar_key) for pillar_key in PILLAR_ORDER]
    wellbeing = _wellbeing_payload(int(user_id))
    week_anchor = tracker_today()
    week_start = start_of_week(week_anchor)
    week_end = week_start + timedelta(days=6)
    sections = [
        {
            "key": pillar["pillar_key"],
            "label": pillar["label"],
            "type": "pillar",
            "configured_count": pillar["configured_count"],
            "total_count": pillar["concept_count"],
        }
        for pillar in pillars
    ]
    sections.append(
        {
            "key": WELLBEING_KEY,
            "label": "Wellbeing objectives",
            "type": "wellbeing",
            "configured_count": wellbeing["configured_count"],
            "total_count": len(wellbeing["items"]),
        }
    )
    return {
        "user_id": int(user_id),
        "week": {
            "anchor_date": week_anchor.isoformat(),
            "start": week_start.isoformat(),
            "end": week_end.isoformat(),
        },
        "sections": sections,
        "pillars": pillars,
        "wellbeing": wellbeing,
    }


def _normalize_numeric_choice(raw_value: Any, allowed_values: set[float]) -> float | None:
    if raw_value is None or raw_value == "":
        return None
    try:
        parsed = float(raw_value)
    except Exception:
        return None
    return parsed if parsed in allowed_values else None


def save_weekly_objectives_config(
    user_id: int,
    *,
    pillar_key: str | None = None,
    concept_targets: dict[str, Any] | None = None,
    wellbeing_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    section_key = str(pillar_key or "").strip().lower()
    if section_key == WELLBEING_KEY:
        values = wellbeing_values if isinstance(wellbeing_values, dict) else {}
        fasting_mode = str(values.get("fasting_mode") or "off").strip().lower()
        if fasting_mode not in {value for value, _label in FASTING_MODE_OPTIONS}:
            raise ValueError("Invalid fasting mode")
        fasting_goal_days = str(values.get("fasting_goal_days") or "0").strip()
        if fasting_goal_days not in {value for value, _label in FASTING_GOAL_DAYS_OPTIONS}:
            raise ValueError("Invalid fasting goal")
        alcohol_tracking = str(values.get("alcohol_tracking") or "off").strip().lower()
        if alcohol_tracking not in {"on", "off"}:
            raise ValueError("Invalid alcohol tracking value")
        alcohol_goal_units = str(values.get("alcohol_goal_units") or "0").strip()
        if alcohol_goal_units not in {value for value, _label in ALCOHOL_GOAL_UNITS_OPTIONS}:
            raise ValueError("Invalid alcohol goal")
        if fasting_mode == "off":
            fasting_goal_days = "0"
        elif fasting_goal_days == "0":
            fasting_goal_days = "7"
        if alcohol_tracking != "on":
            alcohol_goal_units = "0"
        with SessionLocal() as s:
            _set_pref_value(s, int(user_id), FASTING_MODE_PREF_KEY, fasting_mode)
            _set_pref_value(s, int(user_id), FASTING_GOAL_DAYS_PREF_KEY, fasting_goal_days)
            _set_pref_value(s, int(user_id), ALCOHOL_TRACKING_PREF_KEY, alcohol_tracking)
            _set_pref_value(s, int(user_id), ALCOHOL_GOAL_UNITS_PREF_KEY, alcohol_goal_units)
            s.commit()
        return get_weekly_objectives_config(int(user_id))

    if section_key not in PILLAR_ORDER:
        raise ValueError("Invalid objectives section")
    target_map = concept_targets if isinstance(concept_targets, dict) else {}
    concept_defs = tracker_concepts_for_pillar(section_key)
    guide = _GUIDE.get(section_key, {}) or {}
    with SessionLocal() as s:
        cycle = ensure_cycle(s, datetime.now(timezone.utc))
        objective, primary_krs, duplicates = _primary_krs_by_concept(s, int(user_id), section_key)
        if objective is None:
            objective = OKRObjective(
                cycle_id=int(cycle.id),
                pillar_key=section_key,
                objective=_objective_default_text(section_key),
                owner_user_id=int(user_id),
                overall_score=None,
                weight=1.0,
            )
            s.add(objective)
            s.flush()
        else:
            objective.cycle_id = int(cycle.id)
            objective.objective = str(getattr(objective, "objective", "") or "").strip() or _objective_default_text(section_key)
            s.add(objective)
            s.flush()

        for concept_def in concept_defs:
            concept_key = concept_def.concept_key
            concept_meta = guide.get(concept_key, {}) or {}
            unit = str(concept_meta.get("unit") or "").strip() or None
            metric_label = str(concept_meta.get("label") or concept_def.label).strip() or concept_def.label
            allowed_values = {
                float(option.get("value"))
                for option in _concept_target_options(section_key, concept_key)
                if option.get("value") is not None
            }
            selected_value = _normalize_numeric_choice(target_map.get(concept_key), allowed_values)
            primary = primary_krs.get(concept_key)
            baseline_num = getattr(primary, "baseline_num", None) if primary is not None else None
            actual_num = getattr(primary, "actual_num", None) if primary is not None else None
            score = getattr(primary, "score", None) if primary is not None else None
            if primary is None:
                primary = OKRKeyResult(
                    objective_id=int(objective.id),
                    kr_key=f"{concept_key}_target",
                )
            primary.objective_id = int(objective.id)
            primary.kr_key = f"{concept_key}_target"
            primary.description = f"{metric_label.title()} target"
            primary.metric_label = metric_label
            primary.unit = unit
            primary.baseline_num = baseline_num
            primary.target_num = selected_value
            primary.actual_num = actual_num
            primary.score = score
            primary.weight = 1.0
            primary.status = "active"
            primary.notes = json.dumps(
                {
                    "concept_key": f"{section_key}.{concept_key}",
                    "user_configured": True,
                    "configured_at": datetime.utcnow().replace(microsecond=0).isoformat(),
                }
            )
            s.add(primary)
            s.flush()

        for duplicate in duplicates:
            duplicate.status = "archived"
            s.add(duplicate)
        s.commit()
    return get_weekly_objectives_config(int(user_id))
