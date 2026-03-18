from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from sqlalchemy import desc, select

from .db import SessionLocal, engine
from .models import AssessmentRun, DailyPillarTrackerEntry, PillarResult
from .seed import CONCEPTS

_TRACKER_SCHEMA_READY = False
_TRACKER_TIMEZONE = (os.getenv("PILLAR_TRACKER_TIMEZONE") or "Europe/London").strip() or "Europe/London"


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
            helper="today",
            options=tuple(PillarTrackerOption(float(v), str(v)) for v in range(1, 6)),
            target_value=4,
            target_direction="gte",
            score_mode="likert",
            score_floor=1,
            score_ceiling=5,
        ),
        PillarTrackerConceptDefinition(
            concept_key="positive_connection",
            label="Positive Connection",
            helper="today",
            options=tuple(PillarTrackerOption(float(v), str(v)) for v in range(1, 6)),
            target_value=4,
            target_direction="gte",
            score_mode="likert",
            score_floor=1,
            score_ceiling=5,
        ),
        PillarTrackerConceptDefinition(
            concept_key="stress_recovery",
            label="Stress Recovery",
            helper="today",
            options=tuple(PillarTrackerOption(float(v), str(v)) for v in range(1, 6)),
            target_value=4,
            target_direction="gte",
            score_mode="likert",
            score_floor=1,
            score_ceiling=5,
        ),
        PillarTrackerConceptDefinition(
            concept_key="optimism_perspective",
            label="Perspective",
            helper="today",
            options=tuple(PillarTrackerOption(float(v), str(v)) for v in range(1, 6)),
            target_value=4,
            target_direction="gte",
            score_mode="likert",
            score_floor=1,
            score_ceiling=5,
        ),
        PillarTrackerConceptDefinition(
            concept_key="support_openness",
            label="Support",
            helper="today",
            options=tuple(PillarTrackerOption(float(v), str(v)) for v in range(1, 6)),
            target_value=4,
            target_direction="gte",
            score_mode="likert",
            score_floor=1,
            score_ceiling=5,
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
            helper="this morning",
            options=tuple(PillarTrackerOption(float(v), str(v)) for v in range(1, 6)),
            target_value=4,
            target_direction="gte",
            score_mode="likert",
            score_floor=1,
            score_ceiling=5,
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
    try:
        tz = ZoneInfo(_TRACKER_TIMEZONE)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def parse_tracker_anchor(raw: str | None) -> date | None:
    token = str(raw or "").strip()
    if not token:
        return None
    try:
        return date.fromisoformat(token)
    except Exception:
        return None


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


def tracker_concepts_for_pillar(pillar_key: str) -> tuple[PillarTrackerConceptDefinition, ...]:
    key = str(pillar_key or "").strip().lower()
    concepts = PILLAR_TRACKER_CONFIG.get(key)
    if not concepts:
        raise ValueError(f"Unknown pillar: {pillar_key}")
    return concepts


def _to_value_label(defn: PillarTrackerConceptDefinition, value: float | None) -> str | None:
    if value is None:
        return None
    for option in defn.options:
        if float(option.value) == float(value):
            return option.label
    return str(value)


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


def _target_met(defn: PillarTrackerConceptDefinition, value: float) -> bool:
    if defn.target_direction == "lte":
        return value <= defn.target_value
    return value >= defn.target_value


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


def _day_complete(day_rows: dict[str, DailyPillarTrackerEntry], required_concepts: tuple[PillarTrackerConceptDefinition, ...]) -> bool:
    required_keys = {item.concept_key for item in required_concepts}
    return required_keys.issubset(set(day_rows.keys()))


def _day_score(day_rows: dict[str, DailyPillarTrackerEntry], required_concepts: tuple[PillarTrackerConceptDefinition, ...]) -> int | None:
    if not _day_complete(day_rows, required_concepts):
        return None
    scores = [int(getattr(day_rows[item.concept_key], "score", 0) or 0) for item in required_concepts]
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


def _concept_target_streak_days(
    entries_by_day: dict[date, dict[str, DailyPillarTrackerEntry]],
    concept_key: str,
    anchor: date,
) -> int:
    streak = 0
    for offset in range(0, 7):
        day = anchor - timedelta(days=offset)
        if day < start_of_week(anchor):
            break
        row = (entries_by_day.get(day) or {}).get(concept_key)
        if row is None or not bool(getattr(row, "target_met", False)):
            break
        streak += 1
    return streak


def _week_score(entries_by_day: dict[date, dict[str, DailyPillarTrackerEntry]], required_concepts: tuple[PillarTrackerConceptDefinition, ...]) -> int | None:
    scores = [_day_score(rows, required_concepts) for rows in entries_by_day.values()]
    completed_scores = [score for score in scores if score is not None]
    if not completed_scores:
        return None
    return int(round(sum(completed_scores) / max(1, len(completed_scores))))


def _summary_pillar_payload(
    *,
    pillar_key: str,
    entries_by_day: dict[date, dict[str, DailyPillarTrackerEntry]],
    anchor: date,
    baseline_score: int | None,
) -> dict[str, Any]:
    required_concepts = tracker_concepts_for_pillar(pillar_key)
    tracker_score = _week_score(entries_by_day, required_concepts)
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
    }


def get_pillar_tracker_summary(user_id: int, anchor: date | None = None) -> dict[str, Any]:
    ensure_pillar_tracker_schema()
    resolved_anchor = anchor or tracker_today()
    baseline_scores = _latest_assessment_scores_for_user(user_id)
    pillars = []
    for pillar_key in PILLAR_TRACKER_CONFIG.keys():
        entries_by_day = _load_week_entries(user_id, pillar_key, resolved_anchor)
        pillars.append(
            _summary_pillar_payload(
                pillar_key=pillar_key,
                entries_by_day=entries_by_day,
                anchor=resolved_anchor,
                baseline_score=baseline_scores.get(pillar_key),
            )
        )
    week_days = _week_days(resolved_anchor)
    return {
        "week": {
            "anchor_date": resolved_anchor.isoformat(),
            "start": week_days[0].isoformat(),
            "end": week_days[-1].isoformat(),
        },
        "pillars": pillars,
    }


def get_pillar_tracker_detail(user_id: int, pillar_key: str, anchor: date | None = None) -> dict[str, Any]:
    ensure_pillar_tracker_schema()
    resolved_anchor = anchor or tracker_today()
    key = str(pillar_key or "").strip().lower()
    required_concepts = tracker_concepts_for_pillar(key)
    entries_by_day = _load_week_entries(user_id, key, resolved_anchor)
    baseline_scores = _latest_assessment_scores_for_user(user_id)
    week_days = _week_days(resolved_anchor)
    tracker_score = _week_score(entries_by_day, required_concepts)
    completed_days = _completed_days(entries_by_day, required_concepts)
    current_summary = _summary_pillar_payload(
        pillar_key=key,
        entries_by_day=entries_by_day,
        anchor=resolved_anchor,
        baseline_score=baseline_scores.get(key),
    )
    concepts_payload = []
    today_rows = entries_by_day.get(resolved_anchor, {})
    for concept_def in required_concepts:
        current_row = today_rows.get(concept_def.concept_key)
        concepts_payload.append(
            {
                "concept_key": concept_def.concept_key,
                "label": concept_def.label,
                "helper": concept_def.helper,
                "options": [{"value": option.value, "label": option.label} for option in concept_def.options],
                "value": float(current_row.value_num) if current_row and current_row.value_num is not None else None,
                "value_label": str(getattr(current_row, "value_label", "") or "").strip() or None,
                "score": int(getattr(current_row, "score", 0) or 0) if current_row and current_row.score is not None else None,
                "target_met": bool(getattr(current_row, "target_met", False)) if current_row else None,
                "streak_days": _concept_target_streak_days(entries_by_day, concept_def.concept_key, resolved_anchor),
                "week": [
                    {
                        "date": day.isoformat(),
                        "label": day.strftime("%a")[:3],
                        "is_today": day == resolved_anchor,
                        "value_label": (
                            str(getattr((entries_by_day.get(day) or {}).get(concept_def.concept_key), "value_label", "") or "").strip()
                            or None
                        ),
                        "score": (
                            int(getattr((entries_by_day.get(day) or {}).get(concept_def.concept_key), "score", 0) or 0)
                            if (entries_by_day.get(day) or {}).get(concept_def.concept_key) is not None
                            and getattr((entries_by_day.get(day) or {}).get(concept_def.concept_key), "score", None) is not None
                            else None
                        ),
                        "target_met": (
                            bool(getattr((entries_by_day.get(day) or {}).get(concept_def.concept_key), "target_met", False))
                            if (entries_by_day.get(day) or {}).get(concept_def.concept_key) is not None
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
            "today": resolved_anchor.isoformat(),
        },
        "days": [
            {
                "date": day.isoformat(),
                "label": day.strftime("%a")[:3],
                "is_today": day == resolved_anchor,
                "complete": _day_complete(entries_by_day.get(day, {}), required_concepts),
                "score": _day_score(entries_by_day.get(day, {}), required_concepts),
            }
            for day in week_days
        ],
        "concepts": concepts_payload,
    }


def save_pillar_tracker_day(
    user_id: int,
    pillar_key: str,
    *,
    score_date: date | None = None,
    entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ensure_pillar_tracker_schema()
    resolved_date = score_date or tracker_today()
    key = str(pillar_key or "").strip().lower()
    required_concepts = tracker_concepts_for_pillar(key)
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
        try:
            value = float(raw.get("value"))
        except Exception as exc:
            raise ValueError(f"Invalid value for {concept_key}") from exc
        concept_def = config_by_key[concept_key]
        allowed_values = {float(option.value) for option in concept_def.options}
        if value not in allowed_values:
            raise ValueError(f"Unsupported option for {concept_key}")
        normalized_rows[concept_key] = {
            "value_num": value,
            "value_label": _to_value_label(concept_def, value),
            "score": _score_value(concept_def, value),
            "target_met": _target_met(concept_def, value),
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
            row.meta = {
                "saved_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            }
        s.commit()
    return get_pillar_tracker_detail(user_id, key, resolved_date)
