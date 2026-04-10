from __future__ import annotations

import os
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import desc, select

from .db import SessionLocal, engine
from .models import AssessmentRun, DailyPillarTrackerEntry, PillarResult, OKRObjective, OKRKeyResult, OKRKrEntry, User, UserPreference
from .okr import _GUIDE, _guess_concept_from_description, _normalize_concept_key
_TRACKER_SCHEMA_READY = False
_TRACKER_TIMEZONE = (os.getenv("PILLAR_TRACKER_TIMEZONE") or "Europe/London").strip() or "Europe/London"
_FASTING_MODE_PREF_KEY = "weekly_objectives_fasting_mode"
_FASTING_GOAL_DAYS_PREF_KEY = "weekly_objectives_fasting_goal_days"
_ALCOHOL_TRACKING_PREF_KEY = "weekly_objectives_alcohol_tracking"
_ALCOHOL_GOAL_UNITS_PREF_KEY = "weekly_objectives_alcohol_goal_units"
_LATEST_TRACKER_FOCUS_PREF_KEY = "coach_home_latest_tracker_focus"
try:
    _TRACKER_YESTERDAY_GRACE_HOUR = int((os.getenv("PILLAR_TRACKER_YESTERDAY_GRACE_HOUR") or "12").strip() or "12")
except Exception:
    _TRACKER_YESTERDAY_GRACE_HOUR = 12


@dataclass(frozen=True)
class PillarTrackerOption:
    value: float
    label: str


@dataclass(frozen=True)
class PillarTrackerConceptDefinition:
    concept_key: str
    label: str
    helper: str
    options: tuple[PillarTrackerOption, ...]
    target_value: float
    target_direction: str
    score_mode: str
    score_floor: float = 0.0
    score_ceiling: float = 1.0


@dataclass(frozen=True)
class PillarTrackerResolvedTarget:
    source: str
    target_value: float | None
    target_direction: str
    target_unit: str | None
    target_period: str | None
    target_label: str | None
    metric_label: str | None
    success_value: float
    success_direction: str
    start_date: date | None = None


PILLAR_TRACKER_CONFIG: dict[str, tuple[PillarTrackerConceptDefinition, ...]] = {
    "nutrition": (
        PillarTrackerConceptDefinition(
            concept_key="protein_intake",
            label="Protein",
            helper="portions today",
            options=tuple(PillarTrackerOption(float(v), label) for v, label in ((0, "0"), (1, "1"), (2, "2"), (3, "3"), (4, "4+"))),
            target_value=3,
            target_direction="gte",
            score_mode="scale",
            score_ceiling=4,
        ),
        PillarTrackerConceptDefinition(
            concept_key="fruit_veg",
            label="Fruit & Veg",
            helper="portions today",
            options=tuple(PillarTrackerOption(float(v), label) for v, label in ((0, "0"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5+"))),
            target_value=5,
            target_direction="gte",
            score_mode="scale",
            score_ceiling=5,
        ),
        PillarTrackerConceptDefinition(
            concept_key="hydration",
            label="Hydration",
            helper="litres today",
            options=tuple(
                PillarTrackerOption(float(v), label)
                for v, label in ((0, "0"), (0.5, "0.5L"), (1, "1L"), (1.5, "1.5L"), (2, "2L"), (2.5, "2.5L"), (3, "3L+"))
            ),
            target_value=2,
            target_direction="gte",
            score_mode="scale",
            score_ceiling=3,
        ),
        PillarTrackerConceptDefinition(
            concept_key="processed_food",
            label="Processed Food",
            helper="portions today",
            options=tuple(PillarTrackerOption(float(v), label) for v, label in ((0, "0"), (1, "1"), (2, "2"), (3, "3+"))),
            target_value=1,
            target_direction="lte",
            score_mode="reverse_scale",
            score_ceiling=3,
        ),
    ),
    "training": (
        PillarTrackerConceptDefinition(
            concept_key="cardio_frequency",
            label="Cardio",
            helper="20+ mins today",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
        PillarTrackerConceptDefinition(
            concept_key="strength_training",
            label="Strength",
            helper="session today",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
        PillarTrackerConceptDefinition(
            concept_key="flexibility_mobility",
            label="Mobility",
            helper="10+ mins today",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
    ),
    "resilience": (
        PillarTrackerConceptDefinition(
            concept_key="emotional_regulation",
            label="Calm & Control",
            helper="When stress or strong emotions showed up today, did you stay calm and in control?",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
        PillarTrackerConceptDefinition(
            concept_key="positive_connection",
            label="Positive Connection",
            helper="Did you have a positive moment of connection with someone today?",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
        PillarTrackerConceptDefinition(
            concept_key="stress_recovery",
            label="Stress Recovery",
            helper="Did you use a reset or recovery strategy today, such as breathing, walking, or a short pause?",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
        PillarTrackerConceptDefinition(
            concept_key="optimism_perspective",
            label="Perspective",
            helper="When something difficult came up today, did you avoid spiralling and keep perspective?",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
        PillarTrackerConceptDefinition(
            concept_key="support_openness",
            label="Support",
            helper="Did you open up, ask for support, or let someone help today?",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
    ),
    "recovery": (
        PillarTrackerConceptDefinition(
            concept_key="sleep_duration",
            label="7h+ Sleep",
            helper="last night",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
        PillarTrackerConceptDefinition(
            concept_key="sleep_quality",
            label="Rested",
            helper="Did you wake up rested and refreshed this morning?",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
        PillarTrackerConceptDefinition(
            concept_key="bedtime_consistency",
            label="Bedtime",
            helper="consistent last night",
            options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
            target_value=1,
            target_direction="gte",
            score_mode="binary",
        ),
    ),
}


def ensure_pillar_tracker_schema() -> None:
    global _TRACKER_SCHEMA_READY
    if _TRACKER_SCHEMA_READY:
        return
    try:
        DailyPillarTrackerEntry.__table__.create(bind=engine, checkfirst=True)
        _TRACKER_SCHEMA_READY = True
    except Exception:
        _TRACKER_SCHEMA_READY = False
        raise


def tracker_today() -> date:
    return tracker_now().date()


def tracker_now() -> datetime:
    try:
        tz = ZoneInfo(_TRACKER_TIMEZONE)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz)


def parse_tracker_anchor(raw: str | None) -> date | None:
    token = str(raw or "").strip()
    if not token:
        return None
    try:
        return date.fromisoformat(token)
    except Exception:
        return None


def _to_tracker_local_date(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if not isinstance(value, datetime):
        return None
    try:
        tz = ZoneInfo(_TRACKER_TIMEZONE)
    except Exception:
        tz = ZoneInfo("UTC")
    current = value
    if current.tzinfo is None:
        current = current.replace(tzinfo=ZoneInfo("UTC"))
    return current.astimezone(tz).date()


def _pillar_allows_yesterday_catchup(pillar_key: str) -> bool:
    key = str(pillar_key or "").strip().lower()
    return key in {"nutrition", "training", "resilience", "recovery"}


def _pillar_yesterday_catchup_is_time_limited(pillar_key: str) -> bool:
    key = str(pillar_key or "").strip().lower()
    return key in {"nutrition", "training", "resilience"}


def _yesterday_catchup_allowed(now: datetime | None = None) -> bool:
    current = now or tracker_now()
    return int(current.hour) < max(0, min(23, _TRACKER_YESTERDAY_GRACE_HOUR))


def _editable_tracker_dates_for_pillar(pillar_key: str, current_day: date | None = None) -> list[date]:
    today = current_day or tracker_today()
    dates = [today]
    if _pillar_allows_yesterday_catchup(pillar_key) and (
        not _pillar_yesterday_catchup_is_time_limited(pillar_key) or _yesterday_catchup_allowed()
    ):
        dates.insert(0, today - timedelta(days=1))
    return dates


def _last_week_anchor(current_day: date) -> date:
    return current_day - timedelta(days=7)


def _is_last_week_anchor(target_day: date, current_day: date) -> bool:
    return target_day == _last_week_anchor(current_day)


def _week_has_completed_tracker_days(user_id: int, pillar_key: str, anchor: date) -> bool:
    required_concepts = tracker_concepts_for_pillar(pillar_key, user_id=int(user_id))
    entries_by_day = _load_week_entries(user_id, pillar_key, anchor)
    return bool(_completed_days(entries_by_day, required_concepts))


def _viewable_tracker_dates_for_pillar(user_id: int, pillar_key: str, current_day: date | None = None) -> list[date]:
    today = current_day or tracker_today()
    dates: list[date] = []
    last_week = _last_week_anchor(today)
    if _week_has_completed_tracker_days(user_id, pillar_key, last_week):
        dates.append(last_week)
    dates.extend(_editable_tracker_dates_for_pillar(pillar_key, current_day=today))
    return dates


def _format_tracker_day_label(target_day: date, current_day: date) -> str:
    if target_day == current_day:
        return "Today"
    if target_day == current_day - timedelta(days=1):
        return "Yesterday"
    return f"{target_day.strftime('%a')} {target_day.day} {target_day.strftime('%b')}"


def _contextualize_helper_text(helper: str, pillar_key: str, target_day: date, current_day: date) -> str:
    text = str(helper or "").strip()
    if not text:
        return text
    if target_day == current_day:
        return text
    if target_day == current_day - timedelta(days=1) and _pillar_allows_yesterday_catchup(pillar_key):
        return (
            text.replace(" today?", " yesterday?")
            .replace(" Today?", " Yesterday?")
            .replace(" today", " yesterday")
            .replace(" Today", " Yesterday")
        )
    return text


def start_of_week(anchor: date) -> date:
    return anchor - timedelta(days=anchor.weekday())


def _week_days(anchor: date) -> list[date]:
    start = start_of_week(anchor)
    return [start + timedelta(days=offset) for offset in range(7)]


def _pillar_label(pillar_key: str) -> str:
    labels = {
        "nutrition": "Nutrition",
        "training": "Training",
        "resilience": "Resilience",
        "recovery": "Recovery",
    }
    key = str(pillar_key or "").strip().lower()
    return labels.get(key, key.replace("_", " ").title())


def _user_pref_value(session, user_id: int, key: str) -> str | None:
    row = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == int(user_id), UserPreference.key == str(key))
        .one_or_none()
    )
    return str(getattr(row, "value", "") or "").strip() or None


def _user_pref_json(session, user_id: int, key: str) -> dict[str, Any] | None:
    raw = _user_pref_value(session, int(user_id), key)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _set_user_pref_json(session, user_id: int, key: str, payload: dict[str, Any]) -> None:
    row = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == int(user_id), UserPreference.key == str(key))
        .one_or_none()
    )
    raw = json.dumps(payload, default=str)
    if row is None:
        session.add(UserPreference(user_id=int(user_id), key=str(key), value=raw))
        return
    row.value = raw
    session.add(row)


def _wellbeing_tracking_settings(user_id: int) -> tuple[str, str]:
    with SessionLocal() as s:
        fasting_mode = (_user_pref_value(s, int(user_id), _FASTING_MODE_PREF_KEY) or "off").strip().lower()
        alcohol_tracking = (_user_pref_value(s, int(user_id), _ALCOHOL_TRACKING_PREF_KEY) or "off").strip().lower()
    if fasting_mode not in {"off", "12:12", "14:10", "16:8", "18:6"}:
        fasting_mode = "off"
    if alcohol_tracking not in {"on", "off"}:
        alcohol_tracking = "off"
    return fasting_mode, alcohol_tracking


def _wellbeing_weekly_targets(user_id: int) -> tuple[str, str, int, int]:
    with SessionLocal() as s:
        fasting_mode = (_user_pref_value(s, int(user_id), _FASTING_MODE_PREF_KEY) or "off").strip().lower()
        alcohol_tracking = (_user_pref_value(s, int(user_id), _ALCOHOL_TRACKING_PREF_KEY) or "off").strip().lower()
        fasting_goal_days_raw = _user_pref_value(s, int(user_id), _FASTING_GOAL_DAYS_PREF_KEY) or "0"
        alcohol_goal_units_raw = _user_pref_value(s, int(user_id), _ALCOHOL_GOAL_UNITS_PREF_KEY) or "0"
    if fasting_mode not in {"off", "12:12", "14:10", "16:8", "18:6"}:
        fasting_mode = "off"
    if alcohol_tracking not in {"on", "off"}:
        alcohol_tracking = "off"
    try:
        fasting_goal_days = int(float(str(fasting_goal_days_raw).strip() or "0"))
    except Exception:
        fasting_goal_days = 0
    try:
        alcohol_goal_units = int(float(str(alcohol_goal_units_raw).strip() or "0"))
    except Exception:
        alcohol_goal_units = 0
    fasting_goal_days = max(0, min(7, fasting_goal_days))
    alcohol_goal_units = max(0, min(50, alcohol_goal_units))
    if fasting_mode != "off" and fasting_goal_days <= 0:
        fasting_goal_days = 7
    if alcohol_tracking != "on":
        alcohol_goal_units = 0
    return fasting_mode, alcohol_tracking, fasting_goal_days, alcohol_goal_units


def _optional_nutrition_tracker_concepts(user_id: int) -> tuple[PillarTrackerConceptDefinition, ...]:
    fasting_mode, alcohol_tracking = _wellbeing_tracking_settings(int(user_id))
    concepts: list[PillarTrackerConceptDefinition] = []
    if alcohol_tracking == "on":
        concepts.append(
            PillarTrackerConceptDefinition(
                concept_key="alcohol_units",
                label="Alcohol",
                helper="units today",
                options=tuple(
                    PillarTrackerOption(float(v), label)
                    for v, label in ((0, "0"), (1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5"), (6, "6+"))
                ),
                target_value=0,
                target_direction="lte",
                score_mode="reverse_scale",
                score_ceiling=6,
            )
        )
    if fasting_mode != "off":
        concepts.append(
            PillarTrackerConceptDefinition(
                concept_key="fasting_adherence",
                label="Fasting",
                helper=f"Follow your {fasting_mode} plan today?",
                options=(PillarTrackerOption(0, "No"), PillarTrackerOption(1, "Yes")),
                target_value=1,
                target_direction="gte",
                score_mode="binary",
            )
        )
    return tuple(concepts)


def _saved_tracker_focus_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
    target_met = item.get("target_met")
    score = _safe_float(item.get("score"))
    return (
        0 if target_met is False else 1,
        score if score is not None else 999.0,
        str(item.get("concept_key") or ""),
    )


def _record_latest_tracker_focus(
    session,
    *,
    user_id: int,
    pillar_key: str,
    score_date: date,
    session_day: date,
    normalized_rows: dict[str, dict[str, Any]],
) -> None:
    ranked = sorted(
        [
            {
                "concept_key": concept_key,
                "score": payload.get("score"),
                "target_met": payload.get("target_met"),
            }
            for concept_key, payload in normalized_rows.items()
        ],
        key=_saved_tracker_focus_sort_key,
    )
    selected = ranked[0] if ranked else {}
    _set_user_pref_json(
        session,
        int(user_id),
        _LATEST_TRACKER_FOCUS_PREF_KEY,
        {
            "pillar_key": str(pillar_key or "").strip().lower() or None,
            "score_date": score_date.isoformat(),
            "concept_key": str(selected.get("concept_key") or "").strip().lower() or None,
            "session_day": session_day.isoformat(),
            "saved_at": datetime.utcnow().replace(microsecond=0).isoformat(),
        },
    )


def get_recent_tracker_save_focus(user_id: int, *, current_day: date | None = None) -> dict[str, Any] | None:
    today = current_day or tracker_today()
    with SessionLocal() as s:
        payload = _user_pref_json(s, int(user_id), _LATEST_TRACKER_FOCUS_PREF_KEY) or {}
    if not payload:
        return None
    session_day = parse_tracker_anchor(str(payload.get("session_day") or "").strip())
    if session_day != today:
        return None
    pillar_key = str(payload.get("pillar_key") or "").strip().lower()
    if pillar_key not in PILLAR_TRACKER_CONFIG:
        return None
    score_date = parse_tracker_anchor(str(payload.get("score_date") or "").strip())
    if score_date is None:
        return None
    concept_key = _normalize_concept_key(payload.get("concept_key")) or None
    return {
        "pillar_key": pillar_key,
        "score_date": score_date,
        "concept_key": concept_key,
        "session_day": session_day,
        "saved_at": str(payload.get("saved_at") or "").strip() or None,
    }


def tracker_concepts_for_pillar(pillar_key: str, user_id: int | None = None) -> tuple[PillarTrackerConceptDefinition, ...]:
    key = str(pillar_key or "").strip().lower()
    concepts = PILLAR_TRACKER_CONFIG.get(key)
    if not concepts:
        raise ValueError(f"Unknown pillar: {pillar_key}")
    if key == "nutrition" and user_id is not None:
        return concepts + _optional_nutrition_tracker_concepts(int(user_id))
    return concepts


def _to_value_label(defn: PillarTrackerConceptDefinition, value: float | None) -> str | None:
    if value is None:
        return None
    for option in defn.options:
        if float(option.value) == float(value):
            return option.label
    if defn.score_mode == "binary":
        return "Yes" if float(value) >= 1 else "No"
    return str(value)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _normalize_option_value(defn: PillarTrackerConceptDefinition, value: Any) -> float | None:
    normalized = _safe_float(value)
    if normalized is None:
        return None
    allowed_values = {float(option.value) for option in defn.options}
    if normalized in allowed_values:
        return normalized
    if defn.score_mode == "binary":
        return 1.0 if normalized >= 1.0 else 0.0
    return normalized


def _score_value(defn: PillarTrackerConceptDefinition, value: float) -> int:
    if defn.score_mode == "binary":
        return 100 if value >= 1 else 0
    if defn.score_mode == "likert":
        ceiling = max(defn.score_ceiling, defn.score_floor + 1)
        pct = (value - defn.score_floor) / (ceiling - defn.score_floor)
        return int(round(max(0.0, min(1.0, pct)) * 100))
    if defn.score_mode == "reverse_scale":
        ceiling = max(1.0, defn.score_ceiling)
        pct = 1.0 - (max(0.0, min(ceiling, value)) / ceiling)
        return int(round(max(0.0, min(1.0, pct)) * 100))
    ceiling = max(1.0, defn.score_ceiling)
    pct = max(0.0, min(ceiling, value)) / ceiling
    return int(round(max(0.0, min(1.0, pct)) * 100))


def _value_meets_threshold(direction: str, threshold: float, value: float) -> bool:
    if direction == "lte":
        return value <= threshold
    return value >= threshold


def _target_period_from_unit(unit: str | None) -> str | None:
    token = str(unit or "").strip().lower()
    if token.endswith("/week") or token.endswith("per week") or token.endswith("week"):
        return "week"
    if token.endswith("/day") or token.endswith("per day") or token.endswith("day"):
        return "day"
    return None


def _format_target_number(value: float | None) -> str | None:
    if value is None:
        return None
    rounded = round(float(value), 2)
    if abs(rounded - round(rounded)) < 1e-9:
        return str(int(round(rounded)))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _format_target_label(value: float | None, unit: str | None) -> str | None:
    number = _format_target_number(value)
    if not number:
        return None
    unit_text = str(unit or "").strip()
    if unit_text:
        return f"Target {number} {unit_text}"
    return f"Target {number}"


def _format_progress_label(prefix: str, value: float | None, unit: str | None) -> str | None:
    number = _format_target_number(value)
    if not number:
        return None
    unit_text = str(unit or "").strip()
    if unit_text:
        return f"{prefix} {number} {unit_text}"
    return f"{prefix} {number}"


def _format_week_progress_label(value: float | None, unit: str | None) -> str | None:
    number = _format_target_number(value)
    if not number:
        return None
    unit_text = str(unit or "").strip().lower()
    if unit_text.endswith("/week"):
        noun = unit_text[: -len("/week")].strip()
        if noun:
            return f"Recorded {number} {noun} so far this week"
    if unit_text.endswith("per week"):
        noun = unit_text[: -len("per week")].strip()
        if noun:
            return f"Recorded {number} {noun} so far this week"
    if unit_text:
        return f"Recorded {number} {unit_text} so far this week"
    return f"Recorded {number} so far this week"


def _user_tracker_start_date(user_id: int, user: User | None = None) -> date | None:
    row = user
    if row is None:
        with SessionLocal() as s:
            row = s.get(User, int(user_id))
    if row is None:
        return None
    anchor_raw = getattr(row, "first_assessment_completed", None) or getattr(row, "created_on", None)
    return _to_tracker_local_date(anchor_raw)


def _later_date(left: date | None, right: date | None) -> date | None:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _effective_okr_window_start(resolved_target: PillarTrackerResolvedTarget, week_days: list[date], anchor: date) -> date:
    effective_start = week_days[0]
    if resolved_target.start_date is not None and resolved_target.start_date > effective_start:
        effective_start = min(anchor, resolved_target.start_date)
    return effective_start


def _concept_okr_actual_achieved(
    evaluations_for_concept: dict[date, dict[str, Any]],
    resolved_target: PillarTrackerResolvedTarget,
    anchor: date,
    week_days: list[date],
) -> dict[str, Any]:
    effective_start = _effective_okr_window_start(resolved_target, week_days, anchor)
    logged_values = [
        _safe_float((evaluations_for_concept.get(day) or {}).get("value"))
        for day in week_days
        if effective_start <= day <= anchor
    ]
    elapsed_days = max(0, (anchor - effective_start).days + 1)
    return _okr_actual_achieved_from_logged_values(
        logged_values,
        resolved_target,
        elapsed_days=elapsed_days,
    )


def _okr_actual_achieved_from_logged_values(
    logged_values: list[float | None],
    resolved_target: PillarTrackerResolvedTarget,
    *,
    elapsed_days: int | None = None,
) -> dict[str, Any]:
    target_value = _safe_float(resolved_target.target_value)
    if target_value is None or resolved_target.target_period not in {"day", "week"}:
        return {
            "on_track": None,
            "actual_value": None,
            "detail_label": None,
            "logged_days": 0,
        }
    logged_values = [value for value in logged_values if value is not None]
    if not logged_values:
        return {
            "on_track": None,
            "actual_value": None,
            "detail_label": None,
            "logged_days": 0,
        }
    average_value_per_logged_day = sum(logged_values) / float(len(logged_values))
    if resolved_target.target_period == "week":
        actual_value = sum(logged_values)
        expected_value = target_value
        if elapsed_days is not None and elapsed_days > 0:
            expected_value = (target_value * min(max(int(elapsed_days), 0), 7)) / 7.0
        detail_label = _format_week_progress_label(actual_value, resolved_target.target_unit)
    else:
        actual_value = average_value_per_logged_day
        expected_value = target_value
        detail_label = _format_progress_label("Actual", actual_value, resolved_target.target_unit)
    return {
        "on_track": _value_meets_threshold(resolved_target.target_direction, expected_value, actual_value),
        "actual_value": actual_value,
        "detail_label": detail_label,
        "logged_days": len(logged_values),
    }


def _resolve_pillar_targets_for_user_with_session(
    s,
    user_id: int,
    pillar_key: str,
    required_concepts: tuple[PillarTrackerConceptDefinition, ...],
) -> tuple[dict[str, PillarTrackerResolvedTarget], dict[str, OKRKeyResult]]:
    key = str(pillar_key or "").strip().lower()
    resolved = {
        item.concept_key: _default_resolved_target_for_user(int(user_id), key, item)
        for item in required_concepts
    }
    user = s.get(User, int(user_id))
    user_start_date = _user_tracker_start_date(user_id, user=user)
    objective = (
        s.execute(
            select(OKRObjective)
            .where(
                OKRObjective.owner_user_id == int(user_id),
                OKRObjective.pillar_key == key,
            )
            .order_by(desc(OKRObjective.created_at), desc(OKRObjective.id))
        )
        .scalars()
        .first()
    )
    if objective is None:
        return resolved, {}
    objective_start_date = _to_tracker_local_date(getattr(objective, "created_at", None))
    rows = (
        s.execute(
            select(OKRKeyResult)
            .where(OKRKeyResult.objective_id == int(objective.id))
            .order_by(desc(OKRKeyResult.updated_at), desc(OKRKeyResult.id))
        )
        .scalars()
        .all()
    )
    best_by_concept: dict[str, OKRKeyResult] = {}
    for row in rows:
        concept_key = _extract_kr_concept_key(key, row)
        if not concept_key or concept_key not in resolved:
            continue
        current = best_by_concept.get(concept_key)
        if current is None or _kr_priority(row) > _kr_priority(current):
            best_by_concept[concept_key] = row
    for concept_key, kr in best_by_concept.items():
        current = resolved[concept_key]
        target_value = _safe_float(getattr(kr, "target_num", None))
        unit = str(getattr(kr, "unit", "") or "").strip() or current.target_unit
        target_period, start_date = _tracker_target_start_date(
            current=current,
            user_start_date=user_start_date,
            objective_start_date=objective_start_date,
            kr=kr,
            unit=unit,
        )
        resolved[concept_key] = PillarTrackerResolvedTarget(
            source="okr" if target_value is not None else current.source,
            target_value=target_value if target_value is not None else current.target_value,
            target_direction=current.target_direction,
            target_unit=unit,
            target_period=target_period,
            target_label=_format_target_label(target_value, unit) if target_value is not None else current.target_label,
            metric_label=str(getattr(kr, "metric_label", "") or "").strip() or current.metric_label,
            success_value=current.success_value,
            success_direction=current.success_direction,
            start_date=start_date,
        )
    return resolved, best_by_concept


def _sync_pillar_tracker_actuals_to_okrs(
    s,
    *,
    user_id: int,
    pillar_key: str,
    anchor_date: date,
    required_concepts: tuple[PillarTrackerConceptDefinition, ...],
) -> None:
    key = str(pillar_key or "").strip().lower()
    resolved_targets, best_by_concept = _resolve_pillar_targets_for_user_with_session(
        s,
        user_id=user_id,
        pillar_key=key,
        required_concepts=required_concepts,
    )
    if not best_by_concept:
        return
    concept_defs = {item.concept_key: item for item in required_concepts}
    week_days = _week_days(anchor_date)
    tracker_rows = (
        s.execute(
            select(DailyPillarTrackerEntry)
            .where(
                DailyPillarTrackerEntry.user_id == int(user_id),
                DailyPillarTrackerEntry.pillar_key == key,
            )
            .order_by(DailyPillarTrackerEntry.score_date.asc(), DailyPillarTrackerEntry.id.asc())
        )
        .scalars()
        .all()
    )
    rows_by_concept: dict[str, list[DailyPillarTrackerEntry]] = {}
    for row in tracker_rows:
        concept_key = str(getattr(row, "concept_key", "") or "").strip().lower()
        if concept_key in best_by_concept:
            rows_by_concept.setdefault(concept_key, []).append(row)
    sync_time = datetime.utcnow().replace(microsecond=0)
    sync_note = f"daily_tracker_sync:{anchor_date.isoformat()}"
    for concept_key, kr in best_by_concept.items():
        resolved_target = resolved_targets.get(concept_key)
        concept_def = concept_defs.get(concept_key)
        if resolved_target is None or concept_def is None:
            continue
        effective_start = _effective_okr_window_start(resolved_target, week_days, anchor_date)
        logged_values: list[float | None] = []
        for row in rows_by_concept.get(concept_key, []):
            row_date = getattr(row, "score_date", None)
            if not isinstance(row_date, date):
                continue
            if row_date > anchor_date:
                continue
            if row_date < effective_start:
                continue
            value = _normalize_option_value(concept_def, getattr(row, "value_num", None))
            logged_values.append(value)
        elapsed_days = max(0, (anchor_date - effective_start).days + 1)
        actual_progress = _okr_actual_achieved_from_logged_values(
            logged_values,
            resolved_target,
            elapsed_days=elapsed_days,
        )
        actual_value = _safe_float(actual_progress.get("actual_value"))
        kr.actual_num = actual_value
        kr.updated_at = sync_time
        existing_entry = (
            s.execute(
                select(OKRKrEntry)
                .where(
                    OKRKrEntry.key_result_id == int(kr.id),
                    OKRKrEntry.source == "pillar_tracker",
                    OKRKrEntry.note == sync_note,
                )
                .order_by(desc(OKRKrEntry.occurred_at), desc(OKRKrEntry.id))
            )
            .scalars()
            .first()
        )
        if existing_entry is None:
            existing_entry = OKRKrEntry(
                key_result_id=int(kr.id),
                occurred_at=sync_time,
                source="pillar_tracker",
                note=sync_note,
            )
            s.add(existing_entry)
        existing_entry.actual_num = actual_value
        existing_entry.occurred_at = sync_time
        s.add(kr)


def _score_against_daily_target(
    defn: PillarTrackerConceptDefinition,
    value: float,
    *,
    target_value: float | None,
    target_direction: str,
) -> int:
    target = _safe_float(target_value)
    if target is None or target <= 0:
        return _score_value(defn, value)
    if target_direction == "lte":
        if value <= target:
            return 100
        ceiling = max(target + 1.0, float(defn.score_ceiling or 0) or (target + 1.0))
        span = max(1.0, ceiling - target)
        pct = 1.0 - min(max(value - target, 0.0), span) / span
        return int(round(max(0.0, min(1.0, pct)) * 100))
    pct = max(0.0, min(1.0, value / target))
    return int(round(pct * 100))


def _kr_notes_dict(notes: str | None) -> dict[str, Any]:
    if not notes:
        return {}
    try:
        data = json.loads(notes)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _guide_meta(pillar_key: str, concept_key: str) -> dict[str, str]:
    return ((_GUIDE.get(str(pillar_key or "").strip().lower(), {}) or {}).get(str(concept_key or "").strip().lower(), {}) or {})


def _extract_kr_concept_key(pillar_key: str, kr: OKRKeyResult) -> str | None:
    notes_dict = _kr_notes_dict(getattr(kr, "notes", None))
    concept_key = notes_dict.get("concept_key")
    if concept_key:
        concept_key = str(concept_key).split(".")[-1]
    if not concept_key:
        concept_key = _guess_concept_from_description(pillar_key, getattr(kr, "description", "") or "")
    normalized = _normalize_concept_key(concept_key) if concept_key else ""
    return normalized or None


def _kr_priority(kr: OKRKeyResult) -> tuple[int, int, int]:
    status_token = str(getattr(kr, "status", "") or "").strip().lower()
    target_present = 1 if _safe_float(getattr(kr, "target_num", None)) is not None else 0
    active = 1 if status_token in {"", "active"} else 0
    return (active, target_present, int(getattr(kr, "id", 0) or 0))


def _tracker_target_start_date(
    *,
    current: PillarTrackerResolvedTarget,
    user_start_date: date | None,
    objective_start_date: date | None,
    kr: OKRKeyResult,
    unit: str | None,
) -> tuple[str | None, date | None]:
    target_period = _target_period_from_unit(unit) or current.target_period
    if target_period == "week":
        # Tracker views should always reflect the whole recorded week to date for
        # the currently active weekly target, not only rows after the objective/KR
        # was created midweek.
        return target_period, user_start_date or current.start_date
    return target_period, _later_date(user_start_date, objective_start_date) or current.start_date


def _weekly_expected_value(
    resolved_target: PillarTrackerResolvedTarget,
    *,
    elapsed_days: int,
) -> float:
    target_value = _safe_float(resolved_target.target_value) or 0.0
    unit = str(resolved_target.target_unit or "").strip().lower()
    if unit in {"sessions/week", "days/week", "nights/week"}:
        return float(_week_target_expected(target_value, elapsed_days))
    return (target_value * min(max(int(elapsed_days), 0), 7)) / 7.0


def _weekly_score_against_target(
    *,
    actual_value: float,
    expected_value: float,
    resolved_target: PillarTrackerResolvedTarget,
) -> int:
    direction = str(resolved_target.target_direction or "gte").strip().lower()
    target_value = _safe_float(resolved_target.target_value) or 0.0
    if direction == "lte":
        if expected_value <= 0:
            return 100 if actual_value <= 0 else 0
        if actual_value <= expected_value:
            return 100
        ceiling = max(target_value, expected_value, 1.0)
        span = max(1.0, ceiling - expected_value)
        pct = 1.0 - min(max(actual_value - expected_value, 0.0), span) / span
        return int(round(max(0.0, min(1.0, pct)) * 100))
    if expected_value <= 0:
        return 100
    pct = max(0.0, min(1.0, actual_value / expected_value))
    return int(round(pct * 100))


def _default_resolved_target(pillar_key: str, defn: PillarTrackerConceptDefinition) -> PillarTrackerResolvedTarget:
    guide = _guide_meta(pillar_key, defn.concept_key)
    unit = guide.get("unit")
    period = _target_period_from_unit(unit)
    default_target = defn.target_value if period != "week" else None
    return PillarTrackerResolvedTarget(
        source="default",
        target_value=default_target,
        target_direction=defn.target_direction,
        target_unit=unit,
        target_period=period,
        target_label=_format_target_label(default_target, unit),
        metric_label=guide.get("label"),
        success_value=defn.target_value,
        success_direction=defn.target_direction,
        start_date=None,
    )


def _default_resolved_target_for_user(
    user_id: int,
    pillar_key: str,
    defn: PillarTrackerConceptDefinition,
) -> PillarTrackerResolvedTarget:
    key = str(pillar_key or "").strip().lower()
    if key == "nutrition" and defn.concept_key == "alcohol_units":
        _fasting_mode, _alcohol_tracking, _fasting_goal_days, alcohol_goal_units = _wellbeing_weekly_targets(int(user_id))
        return PillarTrackerResolvedTarget(
            source="default",
            target_value=float(alcohol_goal_units),
            target_direction="lte",
            target_unit="units/week",
            target_period="week",
            target_label=(
                "Keep alcohol at 0 units this week"
                if alcohol_goal_units <= 0
                else f"Keep alcohol within {alcohol_goal_units} units this week"
            ),
            metric_label="alcohol units",
            success_value=0.0,
            success_direction="lte",
            start_date=None,
        )
    if key == "nutrition" and defn.concept_key == "fasting_adherence":
        fasting_mode, _alcohol_tracking, fasting_goal_days, _alcohol_goal_units = _wellbeing_weekly_targets(int(user_id))
        label = "Follow your fasting plan this week"
        if fasting_mode and fasting_mode != "off":
            label = f"Hit {fasting_goal_days} {fasting_mode} fasting days this week"
        return PillarTrackerResolvedTarget(
            source="default",
            target_value=float(fasting_goal_days),
            target_direction="gte",
            target_unit="days/week",
            target_period="week",
            target_label=label,
            metric_label="fasting adherence",
            success_value=1.0,
            success_direction="gte",
            start_date=None,
        )
    return _default_resolved_target(key, defn)


def _resolve_pillar_targets_for_user(
    user_id: int,
    pillar_key: str,
    required_concepts: tuple[PillarTrackerConceptDefinition, ...],
) -> dict[str, PillarTrackerResolvedTarget]:
    key = str(pillar_key or "").strip().lower()
    resolved = {
        item.concept_key: _default_resolved_target_for_user(int(user_id), key, item)
        for item in required_concepts
    }
    with SessionLocal() as s:
        user = s.get(User, int(user_id))
        user_start_date = _user_tracker_start_date(user_id, user=user)
        objective = (
            s.execute(
                select(OKRObjective)
                .where(
                    OKRObjective.owner_user_id == int(user_id),
                    OKRObjective.pillar_key == key,
                )
                .order_by(desc(OKRObjective.created_at), desc(OKRObjective.id))
            )
            .scalars()
            .first()
        )
        if objective is None:
            return resolved
        objective_start_date = _to_tracker_local_date(getattr(objective, "created_at", None))
        rows = (
            s.execute(
                select(OKRKeyResult)
                .where(OKRKeyResult.objective_id == int(objective.id))
                .order_by(desc(OKRKeyResult.updated_at), desc(OKRKeyResult.id))
            )
            .scalars()
            .all()
        )
    best_by_concept: dict[str, OKRKeyResult] = {}
    for row in rows:
        concept_key = _extract_kr_concept_key(key, row)
        if not concept_key or concept_key not in resolved:
            continue
        current = best_by_concept.get(concept_key)
        if current is None or _kr_priority(row) > _kr_priority(current):
            best_by_concept[concept_key] = row
    for concept_key, kr in best_by_concept.items():
        current = resolved[concept_key]
        target_value = _safe_float(getattr(kr, "target_num", None))
        unit = str(getattr(kr, "unit", "") or "").strip() or current.target_unit
        target_period, start_date = _tracker_target_start_date(
            current=current,
            user_start_date=user_start_date,
            objective_start_date=objective_start_date,
            kr=kr,
            unit=unit,
        )
        resolved[concept_key] = PillarTrackerResolvedTarget(
            source="okr" if target_value is not None else current.source,
            target_value=target_value if target_value is not None else current.target_value,
            target_direction=current.target_direction,
            target_unit=unit,
            target_period=target_period,
            target_label=_format_target_label(target_value, unit) if target_value is not None else current.target_label,
            metric_label=str(getattr(kr, "metric_label", "") or "").strip() or current.metric_label,
            success_value=current.success_value,
            success_direction=current.success_direction,
            start_date=start_date,
        )
    return resolved


def _target_met_for_value(
    defn: PillarTrackerConceptDefinition,
    value: float,
    resolved_target: PillarTrackerResolvedTarget,
) -> bool:
    if resolved_target.target_period == "day" and resolved_target.target_value is not None:
        return _value_meets_threshold(resolved_target.target_direction, resolved_target.target_value, value)
    return _value_meets_threshold(resolved_target.success_direction, resolved_target.success_value, value)


def _score_for_value(
    defn: PillarTrackerConceptDefinition,
    value: float,
    resolved_target: PillarTrackerResolvedTarget,
) -> int:
    if resolved_target.target_period == "day" and resolved_target.target_value is not None:
        return _score_against_daily_target(
            defn,
            value,
            target_value=resolved_target.target_value,
            target_direction=resolved_target.target_direction,
        )
    return _score_value(defn, value)


def _daily_display_status_for_value(
    defn: PillarTrackerConceptDefinition,
    value: float,
    resolved_target: PillarTrackerResolvedTarget,
) -> str:
    if defn.score_mode == "binary":
        return "success" if value >= 1 else "danger"
    score = _score_for_value(defn, value, resolved_target)
    if score >= 100:
        return "success"
    if score >= 50:
        return "warning"
    return "danger"


def _week_target_expected(target_value: float, day_number: int) -> int:
    if target_value <= 0:
        return 0
    return max(0, int(math.ceil((float(target_value) * float(day_number)) / 7.0 - 1e-9)))


def _build_concept_week_evaluations(
    entries_by_day: dict[date, dict[str, DailyPillarTrackerEntry]],
    required_concepts: tuple[PillarTrackerConceptDefinition, ...],
    resolved_targets: dict[str, PillarTrackerResolvedTarget],
    week_days: list[date],
) -> dict[str, dict[date, dict[str, Any]]]:
    evaluations: dict[str, dict[date, dict[str, Any]]] = {}
    for concept_def in required_concepts:
        concept_key = concept_def.concept_key
        resolved_target = resolved_targets.get(concept_key) or _default_resolved_target("", concept_def)
        effective_start = _effective_okr_window_start(resolved_target, week_days, week_days[-1])
        concept_rows: dict[date, dict[str, Any]] = {}
        cumulative_value = 0.0
        for day in week_days:
            row = (entries_by_day.get(day) or {}).get(concept_key)
            value = None
            value_label = None
            target_reached = None
            daily_status = None
            daily_positive = None
            if row is not None and getattr(row, "value_num", None) is not None:
                value = _normalize_option_value(concept_def, getattr(row, "value_num", 0))
            if value is not None:
                value_label = _to_value_label(concept_def, value) or str(getattr(row, "value_label", "") or "").strip() or None
                target_reached = _value_meets_threshold(
                    resolved_target.success_direction,
                    resolved_target.success_value,
                    value,
                )
                daily_status = _daily_display_status_for_value(concept_def, value, resolved_target)
                daily_positive = daily_status == "success"
                if day >= effective_start:
                    cumulative_value += float(value)
            if resolved_target.target_period == "week" and resolved_target.target_value is not None:
                elapsed_days = max(0, (day - effective_start).days + 1) if day >= effective_start else 0
                expected = _weekly_expected_value(resolved_target, elapsed_days=elapsed_days)
                if value is not None:
                    score = _weekly_score_against_target(
                        actual_value=cumulative_value,
                        expected_value=expected,
                        resolved_target=resolved_target,
                    )
                    target_met = _value_meets_threshold(resolved_target.target_direction, expected, cumulative_value)
                    if daily_status is None:
                        daily_status = "success" if score >= 100 else "warning" if score >= 50 else "danger"
                else:
                    score = None
                    target_met = None
            elif value is not None:
                score = _score_for_value(concept_def, value, resolved_target)
                target_met = _target_met_for_value(concept_def, value, resolved_target)
            else:
                score = None
                target_met = None
            concept_rows[day] = {
                "row": row,
                "value": value,
                "value_label": value_label,
                "score": score,
                "target_met": target_met,
                "target_reached": target_reached,
                "daily_status": daily_status,
                "daily_positive": daily_positive,
                "okr_on_track": target_met if resolved_target.source == "okr" else None,
            }
        evaluations[concept_key] = concept_rows
    return evaluations


def _latest_assessment_scores_for_user(user_id: int) -> dict[str, int]:
    with SessionLocal() as s:
        latest_run = (
            s.execute(
                select(AssessmentRun)
                .where(AssessmentRun.user_id == int(user_id), AssessmentRun.finished_at.isnot(None))
                .order_by(desc(AssessmentRun.id))
            )
            .scalars()
            .first()
        )
        if latest_run is None:
            return {}
        rows = (
            s.execute(
                select(PillarResult).where(PillarResult.run_id == int(latest_run.id)).order_by(PillarResult.id.asc())
            )
            .scalars()
            .all()
        )
    scores: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, "pillar_key", "") or "").strip().lower()
        if not key:
            continue
        score = int(round(float(getattr(row, "overall", 0) or 0)))
        scores[key] = score
    return scores


def _load_week_entries(user_id: int, pillar_key: str, anchor: date) -> dict[date, dict[str, DailyPillarTrackerEntry]]:
    week_days = _week_days(anchor)
    week_start = week_days[0]
    week_end = week_days[-1]
    with SessionLocal() as s:
        rows = (
            s.execute(
                select(DailyPillarTrackerEntry)
                .where(
                    DailyPillarTrackerEntry.user_id == int(user_id),
                    DailyPillarTrackerEntry.pillar_key == str(pillar_key).strip().lower(),
                    DailyPillarTrackerEntry.score_date >= week_start,
                    DailyPillarTrackerEntry.score_date <= week_end,
                )
                .order_by(DailyPillarTrackerEntry.score_date.asc(), DailyPillarTrackerEntry.id.asc())
            )
            .scalars()
            .all()
        )
    grouped: dict[date, dict[str, DailyPillarTrackerEntry]] = {}
    for row in rows:
        day_map = grouped.setdefault(row.score_date, {})
        day_map[str(row.concept_key or "").strip().lower()] = row
    return grouped


def _resolve_tracker_detail_anchor(user_id: int, pillar_key: str, requested_anchor: date | None, current_day: date) -> date:
    viewable_dates = _viewable_tracker_dates_for_pillar(user_id, pillar_key, current_day=current_day)
    editable_dates = _editable_tracker_dates_for_pillar(pillar_key, current_day=current_day)
    if requested_anchor in viewable_dates:
        return requested_anchor
    if not viewable_dates:
        return current_day
    default_anchor = current_day
    if len(editable_dates) > 1:
        yesterday = editable_dates[0]
        required_concepts = tracker_concepts_for_pillar(pillar_key, user_id=int(user_id))
        yesterday_rows = _load_week_entries(user_id, pillar_key, yesterday).get(yesterday, {})
        if not _day_complete(yesterday_rows, required_concepts):
            default_anchor = yesterday
    return default_anchor


def _day_complete(day_rows: dict[str, DailyPillarTrackerEntry], required_concepts: tuple[PillarTrackerConceptDefinition, ...]) -> bool:
    required_keys = {item.concept_key for item in required_concepts}
    return required_keys.issubset(set(day_rows.keys()))


def _day_score(
    day_rows: dict[str, DailyPillarTrackerEntry],
    required_concepts: tuple[PillarTrackerConceptDefinition, ...],
    evaluations_by_concept: dict[str, dict[date, dict[str, Any]]],
    day: date,
) -> int | None:
    if not _day_complete(day_rows, required_concepts):
        return None
    scores: list[int] = []
    for item in required_concepts:
        score = (
            evaluations_by_concept.get(item.concept_key, {})
            .get(day, {})
            .get("score")
        )
        if score is None:
            return None
        scores.append(int(score))
    if not scores:
        return None
    return int(round(sum(scores) / max(1, len(scores))))


def _completed_days(entries_by_day: dict[date, dict[str, DailyPillarTrackerEntry]], required_concepts: tuple[PillarTrackerConceptDefinition, ...]) -> list[date]:
    return [day for day, rows in entries_by_day.items() if _day_complete(rows, required_concepts)]


def _completion_streak_days(
    entries_by_day: dict[date, dict[str, DailyPillarTrackerEntry]],
    required_concepts: tuple[PillarTrackerConceptDefinition, ...],
    anchor: date,
) -> int:
    streak = 0
    for offset in range(0, 7):
        day = anchor - timedelta(days=offset)
        if day < start_of_week(anchor):
            break
        if _day_complete(entries_by_day.get(day, {}), required_concepts):
            streak += 1
            continue
        break
    return streak


def _concept_target_streak_days(evaluations_for_concept: dict[date, dict[str, Any]], anchor: date) -> int:
    streak = 0
    for offset in range(0, 7):
        day = anchor - timedelta(days=offset)
        if day < start_of_week(anchor):
            break
        if not bool((evaluations_for_concept.get(day) or {}).get("target_met")):
            break
        streak += 1
    return streak


def _concept_positive_streak_days(evaluations_for_concept: dict[date, dict[str, Any]], anchor: date) -> int:
    streak = 0
    for offset in range(0, 7):
        day = anchor - timedelta(days=offset)
        if day < start_of_week(anchor):
            break
        if not bool((evaluations_for_concept.get(day) or {}).get("daily_positive")):
            break
        streak += 1
    return streak


def _concept_okr_status(
    defn: PillarTrackerConceptDefinition,
    evaluations_for_concept: dict[date, dict[str, Any]],
    resolved_target: PillarTrackerResolvedTarget,
    anchor: date,
    week_days: list[date],
) -> dict[str, Any]:
    if resolved_target.source != "okr":
        return {
            "okr_on_track": None,
            "okr_status_label": None,
            "okr_status_detail": None,
        }
    progress = _concept_okr_actual_achieved(
        evaluations_for_concept,
        resolved_target,
        anchor,
        week_days,
    )
    if progress.get("on_track") is None:
        return {
            "okr_on_track": None,
            "okr_status_label": None,
            "okr_status_detail": None,
        }
    return {
        "okr_on_track": bool(progress.get("on_track")),
        "okr_status_label": "On track" if progress.get("on_track") else "Behind pace",
        "okr_status_detail": progress.get("detail_label"),
    }
    return {
        "okr_on_track": None,
        "okr_status_label": None,
        "okr_status_detail": None,
    }


def _week_score(
    entries_by_day: dict[date, dict[str, DailyPillarTrackerEntry]],
    required_concepts: tuple[PillarTrackerConceptDefinition, ...],
    evaluations_by_concept: dict[str, dict[date, dict[str, Any]]],
    week_days: list[date],
) -> int | None:
    scores = [
        _day_score(entries_by_day.get(day, {}), required_concepts, evaluations_by_concept, day)
        for day in week_days
    ]
    completed_scores = [score for score in scores if score is not None]
    if not completed_scores:
        return None
    return int(round(sum(completed_scores) / max(1, len(completed_scores))))


def _summary_pillar_payload(
    *,
    pillar_key: str,
    entries_by_day: dict[date, dict[str, DailyPillarTrackerEntry]],
    required_concepts: tuple[PillarTrackerConceptDefinition, ...],
    evaluations_by_concept: dict[str, dict[date, dict[str, Any]]],
    week_days: list[date],
    anchor: date,
    current_day: date,
    baseline_score: int | None,
) -> dict[str, Any]:
    tracker_score = _week_score(entries_by_day, required_concepts, evaluations_by_concept, week_days)
    completed_days = _completed_days(entries_by_day, required_concepts)
    return {
        "pillar_key": pillar_key,
        "label": _pillar_label(pillar_key),
        "score": tracker_score if tracker_score is not None else baseline_score,
        "tracker_score": tracker_score,
        "baseline_score": baseline_score,
        "source": "tracker" if tracker_score is not None else "assessment",
        "completed_days_count": len(completed_days),
        "streak_days": _completion_streak_days(entries_by_day, required_concepts, anchor),
        "today_complete": _day_complete(entries_by_day.get(current_day, {}), required_concepts),
    }


def get_pillar_tracker_summary(user_id: int, anchor: date | None = None) -> dict[str, Any]:
    ensure_pillar_tracker_schema()
    resolved_anchor = anchor or tracker_today()
    current_day = tracker_today()
    baseline_scores = _latest_assessment_scores_for_user(user_id)
    week_days = _week_days(resolved_anchor)
    pillars = []
    for pillar_key in PILLAR_TRACKER_CONFIG.keys():
        required_concepts = tracker_concepts_for_pillar(pillar_key, user_id=int(user_id))
        entries_by_day = _load_week_entries(user_id, pillar_key, resolved_anchor)
        resolved_targets = _resolve_pillar_targets_for_user(user_id, pillar_key, required_concepts)
        evaluations_by_concept = _build_concept_week_evaluations(entries_by_day, required_concepts, resolved_targets, week_days)
        pillars.append(
            _summary_pillar_payload(
                pillar_key=pillar_key,
                entries_by_day=entries_by_day,
                required_concepts=required_concepts,
                evaluations_by_concept=evaluations_by_concept,
                week_days=week_days,
                anchor=resolved_anchor,
                current_day=current_day,
                baseline_score=baseline_scores.get(pillar_key),
            )
        )
    total_pillars = len(PILLAR_TRACKER_CONFIG)
    today_completed_pillars_count = sum(1 for pillar in pillars if pillar.get("today_complete") is True)
    return {
        "week": {
            "anchor_date": resolved_anchor.isoformat(),
            "start": week_days[0].isoformat(),
            "end": week_days[-1].isoformat(),
        },
        "today": current_day.isoformat(),
        "today_complete": bool(total_pillars and today_completed_pillars_count >= total_pillars),
        "today_completed_pillars_count": today_completed_pillars_count,
        "total_pillars": total_pillars,
        "pillars": pillars,
    }


def get_pillar_tracker_detail(user_id: int, pillar_key: str, anchor: date | None = None) -> dict[str, Any]:
    ensure_pillar_tracker_schema()
    key = str(pillar_key or "").strip().lower()
    current_day = tracker_today()
    resolved_anchor = _resolve_tracker_detail_anchor(user_id, key, anchor, current_day)
    required_concepts = tracker_concepts_for_pillar(key, user_id=int(user_id))
    entries_by_day = _load_week_entries(user_id, key, resolved_anchor)
    baseline_scores = _latest_assessment_scores_for_user(user_id)
    week_days = _week_days(resolved_anchor)
    resolved_targets = _resolve_pillar_targets_for_user(user_id, key, required_concepts)
    evaluations_by_concept = _build_concept_week_evaluations(entries_by_day, required_concepts, resolved_targets, week_days)
    tracker_score = _week_score(entries_by_day, required_concepts, evaluations_by_concept, week_days)
    completed_days = _completed_days(entries_by_day, required_concepts)
    editable_dates = _editable_tracker_dates_for_pillar(key, current_day=current_day)
    viewable_dates = _viewable_tracker_dates_for_pillar(user_id, key, current_day=current_day)
    is_editable = resolved_anchor in editable_dates
    is_current_week = start_of_week(resolved_anchor) == start_of_week(current_day)
    current_summary = _summary_pillar_payload(
        pillar_key=key,
        entries_by_day=entries_by_day,
        required_concepts=required_concepts,
        evaluations_by_concept=evaluations_by_concept,
        week_days=week_days,
        anchor=resolved_anchor,
        current_day=current_day,
        baseline_score=baseline_scores.get(key),
    )
    concepts_payload = []
    today_rows = entries_by_day.get(resolved_anchor, {})
    for concept_def in required_concepts:
        current_row = today_rows.get(concept_def.concept_key)
        resolved_target = (
            resolved_targets.get(concept_def.concept_key)
            or _default_resolved_target_for_user(int(user_id), key, concept_def)
        )
        evaluations_for_concept = evaluations_by_concept.get(concept_def.concept_key, {})
        today_eval = evaluations_for_concept.get(resolved_anchor, {})
        okr_status = _concept_okr_status(concept_def, evaluations_for_concept, resolved_target, resolved_anchor, week_days)
        concepts_payload.append(
            {
                "concept_key": concept_def.concept_key,
                "label": concept_def.label,
                "helper": _contextualize_helper_text(concept_def.helper, key, resolved_anchor, current_day),
                "target_label": resolved_target.target_label,
                "target_source": resolved_target.source,
                "target_period": resolved_target.target_period,
                "target_unit": resolved_target.target_unit,
                "target_value": resolved_target.target_value,
                "options": [{"value": option.value, "label": option.label} for option in concept_def.options],
                "value": (
                    _normalize_option_value(concept_def, current_row.value_num)
                    if current_row and current_row.value_num is not None
                    else None
                ),
                "value_label": (
                    _to_value_label(
                        concept_def,
                        _normalize_option_value(concept_def, current_row.value_num),
                    )
                    if current_row and current_row.value_num is not None
                    else None
                ),
                "score": int(today_eval.get("score")) if today_eval.get("score") is not None else None,
                "target_met": bool(today_eval.get("target_met")) if today_eval.get("target_met") is not None else None,
                "target_reached": (
                    bool(today_eval.get("target_reached"))
                    if today_eval.get("target_reached") is not None
                    else None
                ),
                "daily_status": today_eval.get("daily_status"),
                "daily_positive": (
                    bool(today_eval.get("daily_positive"))
                    if today_eval.get("daily_positive") is not None
                    else None
                ),
                "okr_on_track": okr_status.get("okr_on_track"),
                "okr_status_label": okr_status.get("okr_status_label"),
                "okr_status_detail": okr_status.get("okr_status_detail"),
                "streak_days": _concept_positive_streak_days(evaluations_for_concept, resolved_anchor),
                "week": [
                    {
                        "date": day.isoformat(),
                        "label": day.strftime("%a")[:3],
                        "is_today": day == current_day,
                        "is_active": day == resolved_anchor,
                        "value_label": evaluations_for_concept.get(day, {}).get("value_label"),
                        "score": (
                            int(evaluations_for_concept.get(day, {}).get("score"))
                            if evaluations_for_concept.get(day, {}).get("score") is not None
                            else None
                        ),
                        "target_reached": (
                            bool(evaluations_for_concept.get(day, {}).get("target_reached"))
                            if evaluations_for_concept.get(day, {}).get("target_reached") is not None
                            else None
                        ),
                        "target_met": (
                            bool(evaluations_for_concept.get(day, {}).get("target_met"))
                            if evaluations_for_concept.get(day, {}).get("target_met") is not None
                            else None
                        ),
                        "daily_status": evaluations_for_concept.get(day, {}).get("daily_status"),
                        "daily_positive": (
                            bool(evaluations_for_concept.get(day, {}).get("daily_positive"))
                            if evaluations_for_concept.get(day, {}).get("daily_positive") is not None
                            else None
                        ),
                        "okr_on_track": (
                            bool(evaluations_for_concept.get(day, {}).get("okr_on_track"))
                            if evaluations_for_concept.get(day, {}).get("okr_on_track") is not None
                            else None
                        ),
                    }
                    for day in week_days
                ],
            }
        )
    return {
        "pillar": {
            "pillar_key": key,
            "label": _pillar_label(key),
            "score": current_summary.get("score"),
            "tracker_score": tracker_score,
            "baseline_score": baseline_scores.get(key),
            "source": current_summary.get("source"),
            "completed_days_count": len(completed_days),
            "streak_days": current_summary.get("streak_days"),
            "week_start": week_days[0].isoformat(),
            "week_end": week_days[-1].isoformat(),
            "today": current_day.isoformat(),
            "active_date": resolved_anchor.isoformat(),
            "active_label": "Last week" if _is_last_week_anchor(resolved_anchor, current_day) else _format_tracker_day_label(resolved_anchor, current_day),
            "current_date": current_day.isoformat(),
            "yesterday_catchup_available": len(editable_dates) > 1,
            "is_editable": is_editable,
            "is_current_week": is_current_week,
        },
        "days": [
            {
                "date": day.isoformat(),
                "label": day.strftime("%a")[:3],
                "is_today": day == current_day,
                "complete": _day_complete(entries_by_day.get(day, {}), required_concepts),
                "score": _day_score(entries_by_day.get(day, {}), required_concepts, evaluations_by_concept, day),
            }
            for day in week_days
        ],
        "concepts": concepts_payload,
        "editable_dates": [
            {
                "date": item.isoformat(),
                "label": "Last week" if _is_last_week_anchor(item, current_day) else _format_tracker_day_label(item, current_day),
                "is_active": item == resolved_anchor,
                "editable": item in editable_dates,
            }
            for item in viewable_dates
        ],
    }


def save_pillar_tracker_day(
    user_id: int,
    pillar_key: str,
    *,
    score_date: date | None = None,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ensure_pillar_tracker_schema()
    current_day = tracker_today()
    resolved_date = score_date or current_day
    key = str(pillar_key or "").strip().lower()
    editable_dates = _editable_tracker_dates_for_pillar(key, current_day=current_day)
    if resolved_date not in editable_dates:
        if _pillar_allows_yesterday_catchup(key):
            if not _pillar_yesterday_catchup_is_time_limited(key):
                raise ValueError(f"You can save {key} for today, or for yesterday.")
            raise ValueError(
                f"You can save {key} for today, or for yesterday before {_TRACKER_YESTERDAY_GRACE_HOUR}:00 local time."
            )
        raise ValueError("This pillar can only be saved for today.")
    required_concepts = tracker_concepts_for_pillar(key, user_id=int(user_id))
    resolved_targets = _resolve_pillar_targets_for_user(user_id, key, required_concepts)
    entries = entries or []
    if len(entries) != len(required_concepts):
        raise ValueError("A complete pillar tracker requires all concept values for the day.")
    config_by_key = {item.concept_key: item for item in required_concepts}
    normalized_rows: dict[str, dict[str, Any]] = {}
    for raw in entries:
        concept_key = str((raw or {}).get("concept_key") or "").strip().lower()
        if concept_key not in config_by_key:
            raise ValueError(f"Unknown concept for pillar {key}: {concept_key}")
        if concept_key in normalized_rows:
            raise ValueError(f"Duplicate concept value submitted: {concept_key}")
        value = _normalize_option_value(config_by_key[concept_key], (raw or {}).get("value"))
        if value is None:
            raise ValueError(f"Invalid value for {concept_key}")
        concept_def = config_by_key[concept_key]
        allowed_values = {float(option.value) for option in concept_def.options}
        if value not in allowed_values:
            raise ValueError(f"Unsupported option for {concept_key}")
        normalized_rows[concept_key] = {
            "value_num": value,
            "value_label": _to_value_label(concept_def, value),
            "score": _score_for_value(
                concept_def,
                value,
                resolved_targets.get(concept_key) or _default_resolved_target_for_user(int(user_id), key, concept_def),
            ),
            "target_met": _target_met_for_value(
                concept_def,
                value,
                resolved_targets.get(concept_key) or _default_resolved_target_for_user(int(user_id), key, concept_def),
            ),
        }
    if set(normalized_rows.keys()) != set(config_by_key.keys()):
        raise ValueError("Each pillar tracker save must include every concept.")
    with SessionLocal() as s:
        existing_rows = (
            s.execute(
                select(DailyPillarTrackerEntry).where(
                    DailyPillarTrackerEntry.user_id == int(user_id),
                    DailyPillarTrackerEntry.pillar_key == key,
                    DailyPillarTrackerEntry.score_date == resolved_date,
                )
            )
            .scalars()
            .all()
        )
        existing_by_concept = {
            str(getattr(row, "concept_key", "") or "").strip().lower(): row for row in existing_rows
        }
        for concept_key, payload in normalized_rows.items():
            row = existing_by_concept.get(concept_key)
            if row is None:
                row = DailyPillarTrackerEntry(
                    user_id=int(user_id),
                    score_date=resolved_date,
                    pillar_key=key,
                    concept_key=concept_key,
                )
                s.add(row)
            row.value_num = payload["value_num"]
            row.value_label = payload["value_label"]
            row.score = payload["score"]
            row.target_met = payload["target_met"]
            row.source = "self_report"
            resolved_target = resolved_targets.get(concept_key)
            row.meta = {
                "saved_at": datetime.utcnow().replace(microsecond=0).isoformat(),
                "target_source": getattr(resolved_target, "source", None),
                "target_value": getattr(resolved_target, "target_value", None),
                "target_unit": getattr(resolved_target, "target_unit", None),
                "target_period": getattr(resolved_target, "target_period", None),
            }
        _record_latest_tracker_focus(
            s,
            user_id=int(user_id),
            pillar_key=key,
            score_date=resolved_date,
            session_day=current_day,
            normalized_rows=normalized_rows,
        )
        _sync_pillar_tracker_actuals_to_okrs(
            s,
            user_id=int(user_id),
            pillar_key=key,
            anchor_date=resolved_date,
            required_concepts=required_concepts,
        )
        s.commit()
    return get_pillar_tracker_detail(user_id, key, resolved_date)
