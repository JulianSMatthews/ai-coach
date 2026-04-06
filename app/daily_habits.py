from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select

from .db import SessionLocal, engine
from .models import DailyCoachHabitPlan, OKRKeyResult, OKRKrHabitStep, OKRObjective, User
from .okr import _guess_concept_from_description, _normalize_concept_key
from .pillar_tracker import (
    _wellbeing_weekly_targets,
    get_pillar_tracker_detail,
    get_pillar_tracker_summary,
    get_recent_tracker_save_focus,
    tracker_today,
)
from .prompts import build_prompt, ensure_builtin_prompt_templates, run_llm_prompt

_DAILY_HABITS_SCHEMA_READY = False
_PILLAR_ORDER = ("nutrition", "training", "resilience", "recovery")
_CURRENT_HABIT_PLAN_VERSION = 9
_DAY_PLAN_SCOPE_KEY = "__day_plan__"
_DAY_MOMENT_SEQUENCE = (
    ("morning", "Morning"),
    ("midday", "Midday"),
    ("afternoon", "Afternoon"),
    ("evening", "Evening"),
)


def ensure_daily_habit_plan_schema() -> None:
    global _DAILY_HABITS_SCHEMA_READY
    if _DAILY_HABITS_SCHEMA_READY:
        return
    try:
        DailyCoachHabitPlan.__table__.create(bind=engine, checkfirst=True)
        _DAILY_HABITS_SCHEMA_READY = True
    except Exception:
        _DAILY_HABITS_SCHEMA_READY = False
        raise


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _pillar_rank(pillar_key: str) -> int:
    token = str(pillar_key or "").strip().lower()
    try:
        return _PILLAR_ORDER.index(token)
    except Exception:
        return len(_PILLAR_ORDER) + 1


def _normalize_concept_token(value: Any) -> str | None:
    token = _normalize_concept_key(value)
    return token or None


def _normalize_plan_scope_key(value: Any) -> str | None:
    token = str(value or "").strip()
    if token == _DAY_PLAN_SCOPE_KEY:
        return _DAY_PLAN_SCOPE_KEY
    return _normalize_concept_token(token)


def _today_iso() -> str:
    return tracker_today().isoformat()


def _load_user_name(user_id: int) -> str:
    with SessionLocal() as s:
        user = s.get(User, int(user_id))
        first_name = str(getattr(user, "first_name", "") or "").strip() if user else ""
    return first_name or "User"


def _habit_item_id(
    *,
    title: str,
    detail: str,
    concept_key: str | None,
    pillar_key: str | None,
    moment_key: str | None = None,
) -> str:
    payload = json.dumps(
        {
            "title": str(title or "").strip(),
            "detail": str(detail or "").strip(),
            "concept_key": str(concept_key or "").strip().lower() or None,
            "pillar_key": str(pillar_key or "").strip().lower() or None,
            "moment_key": str(moment_key or "").strip().lower() or None,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _kr_notes_dict(notes: Any) -> dict[str, Any]:
    if not notes:
        return {}
    if isinstance(notes, dict):
        return notes
    try:
        data = json.loads(notes)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_kr_concept_key(pillar_key: str, kr: OKRKeyResult) -> str | None:
    notes_dict = _kr_notes_dict(getattr(kr, "notes", None))
    concept_key = notes_dict.get("concept_key")
    if concept_key:
        concept_key = str(concept_key).split(".")[-1]
    if not concept_key:
        concept_key = _guess_concept_from_description(pillar_key, getattr(kr, "description", "") or "")
    return _normalize_concept_token(concept_key)


def _load_pillar_okr_context(user_id: int, pillar_key: str, *, concept_key: str | None = None) -> dict[str, Any]:
    requested_concept_key = _normalize_concept_token(concept_key)
    with SessionLocal() as s:
        objective = (
            s.execute(
                select(OKRObjective)
                .where(
                    OKRObjective.owner_user_id == int(user_id),
                    OKRObjective.pillar_key == str(pillar_key or "").strip().lower(),
                )
                .order_by(desc(OKRObjective.created_at), desc(OKRObjective.id))
            )
            .scalars()
            .first()
        )
        if objective is None:
            return {"objective": None, "krs": [], "habit_steps": []}
        krs = (
            s.execute(
                select(OKRKeyResult)
                .where(OKRKeyResult.objective_id == int(objective.id))
                .order_by(desc(OKRKeyResult.updated_at), desc(OKRKeyResult.id))
            )
            .scalars()
            .all()
        )
        if requested_concept_key:
            krs = [
                row
                for row in krs
                if _extract_kr_concept_key(str(pillar_key or "").strip().lower(), row) == requested_concept_key
            ]
        kr_ids = [int(getattr(row, "id", 0) or 0) for row in krs if getattr(row, "id", None)]
        habit_rows = []
        if kr_ids:
            habit_rows = (
                s.execute(
                    select(OKRKrHabitStep)
                    .where(
                        OKRKrHabitStep.user_id == int(user_id),
                        OKRKrHabitStep.kr_id.in_(kr_ids),
                        OKRKrHabitStep.status != "archived",
                    )
                    .order_by(
                        OKRKrHabitStep.week_no.desc().nullslast(),
                        OKRKrHabitStep.sort_order.asc(),
                        OKRKrHabitStep.id.asc(),
                    )
                )
                .scalars()
                .all()
            )
    return {
        "objective": str(getattr(objective, "objective", "") or "").strip() if objective else None,
        "krs": [
            {
                "id": int(getattr(row, "id", 0) or 0),
                "description": str(getattr(row, "description", "") or "").strip(),
                "metric_label": str(getattr(row, "metric_label", "") or "").strip() or None,
                "target_num": getattr(row, "target_num", None),
                "unit": str(getattr(row, "unit", "") or "").strip() or None,
                "status": str(getattr(row, "status", "") or "").strip() or None,
            }
            for row in krs[:4]
            if str(getattr(row, "description", "") or "").strip()
        ],
        "habit_steps": [
            str(getattr(row, "step_text", "") or "").strip()
            for row in habit_rows[:5]
            if str(getattr(row, "step_text", "") or "").strip()
        ],
    }


def _select_weakest_pillar(summary: dict[str, Any]) -> dict[str, Any]:
    pillars = list(summary.get("pillars") or [])
    if not pillars:
        return {"pillar_key": "nutrition", "label": "Nutrition", "score": None}

    def _sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
        score = _safe_int(row.get("score"))
        return (
            score if score is not None else 999,
            _pillar_rank(str(row.get("pillar_key") or "")),
            0,
        )

    return sorted(pillars, key=_sort_key)[0]


def _recent_concept_focuses(
    detail: dict[str, Any],
    anchor: date,
    *,
    pillar_key: str,
    pillar_label: str,
) -> list[dict[str, Any]]:
    today_iso = anchor.isoformat()
    yesterday_iso = (anchor - timedelta(days=1)).isoformat()
    focus_rows: list[dict[str, Any]] = []
    for concept in detail.get("concepts") or []:
        week_rows = {
            str((row or {}).get("date") or "").strip(): row
            for row in (concept.get("week") or [])
            if isinstance(row, dict)
        }
        today_row = week_rows.get(today_iso) or {}
        yesterday_row = week_rows.get(yesterday_iso) or {}
        misses = sum(
            1
            for row in (today_row, yesterday_row)
            if isinstance(row, dict) and row.get("target_met") is False
        )
        missing = sum(
            1
            for row in (today_row, yesterday_row)
            if not isinstance(row, dict) or row.get("target_met") is None
        )
        latest_value = str(
            (today_row if today_row.get("value_label") else yesterday_row).get("value_label") or ""
        ).strip() or None
        current_score = _safe_int(concept.get("score"))
        signal = "on_track"
        if today_row.get("target_met") is False:
            signal = "missed_today"
        elif yesterday_row.get("target_met") is False:
            signal = "missed_yesterday"
        elif today_row.get("target_met") is None:
            signal = "not_logged_today"
        elif current_score is not None and current_score < 80:
            signal = "needs_support"
        focus_rows.append(
            {
                "pillar_key": str(pillar_key or "").strip().lower(),
                "pillar_label": str(pillar_label or "").strip() or str(pillar_key or "").strip().title(),
                "concept_key": str(concept.get("concept_key") or "").strip(),
                "label": str(concept.get("label") or "").strip(),
                "helper": str(concept.get("helper") or "").strip(),
                "target_label": str(concept.get("target_label") or "").strip() or None,
                "signal": signal,
                "misses": misses,
                "missing": missing,
                "latest_value": latest_value,
                "score": current_score,
                "anchor_date": anchor.isoformat(),
            }
        )
    return focus_rows


def _detail_day_complete(detail: dict[str, Any], target_day: date) -> bool:
    target_iso = target_day.isoformat()
    for item in detail.get("days") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("date") or "").strip() != target_iso:
            continue
        return bool(item.get("complete"))
    return False


def _guidance_anchor_for_pillar(user_id: int, pillar_key: str, current_day: date) -> date:
    key = str(pillar_key or "").strip().lower()
    yesterday = current_day - timedelta(days=1)
    if key in {"nutrition", "resilience"}:
        return yesterday
    if key == "recovery":
        return current_day
    if key == "training":
        today_detail = get_pillar_tracker_detail(user_id, key, anchor=current_day)
        return current_day if _detail_day_complete(today_detail, current_day) else yesterday
    return current_day


def _anchored_concept_focuses(
    detail: dict[str, Any],
    active_day: date,
    *,
    pillar_key: str,
    pillar_label: str,
) -> list[dict[str, Any]]:
    active_iso = active_day.isoformat()
    current_day = tracker_today()
    anchored_missed_signal = "missed_today" if active_day == current_day else "missed_yesterday"
    anchored_missing_signal = "not_logged_today" if active_day == current_day else "not_logged_yesterday"
    focus_rows: list[dict[str, Any]] = []
    for concept in detail.get("concepts") or []:
        week_rows = {
            str((row or {}).get("date") or "").strip(): row
            for row in (concept.get("week") or [])
            if isinstance(row, dict)
        }
        active_row = week_rows.get(active_iso) or {}
        latest_value = str(active_row.get("value_label") or "").strip() or None
        current_score = _safe_int(concept.get("score"))
        target_period = str(concept.get("target_period") or "").strip().lower()
        has_recorded_value = active_row.get("value_label") is not None
        recorded_positive = active_row.get("daily_positive")
        if recorded_positive is None:
            recorded_positive = active_row.get("target_reached")
        signal = "on_track"
        if not has_recorded_value:
            signal = anchored_missing_signal
        elif target_period == "week":
            if recorded_positive is False:
                signal = anchored_missed_signal
            elif recorded_positive is True:
                signal = "on_track"
            elif current_score is not None and current_score < 80:
                signal = "needs_support"
        elif active_row.get("target_met") is False:
            signal = anchored_missed_signal
        elif current_score is not None and current_score < 80:
            signal = "needs_support"
        misses = 1 if signal in {"missed_today", "missed_yesterday"} else 0
        missing = 1 if signal in {"not_logged_today", "not_logged_yesterday"} else 0
        focus_rows.append(
            {
                "pillar_key": str(pillar_key or "").strip().lower(),
                "pillar_label": str(pillar_label or "").strip() or str(pillar_key or "").strip().title(),
                "concept_key": str(concept.get("concept_key") or "").strip(),
                "label": str(concept.get("label") or "").strip(),
                "helper": str(concept.get("helper") or "").strip(),
                "target_label": str(concept.get("target_label") or "").strip() or None,
                "signal": signal,
                "misses": misses,
                "missing": missing,
                "latest_value": latest_value,
                "score": current_score,
                "anchor_date": active_iso,
            }
        )
    return focus_rows


def _focus_signal_priority(signal: str) -> int:
    token = str(signal or "").strip().lower()
    if token == "missed_today":
        return 0
    if token == "missed_yesterday":
        return 1
    if token == "not_logged_yesterday":
        return 2
    if token == "needs_support":
        return 3
    if token == "not_logged_today":
        return 4
    return 4


def _select_focus_concepts(
    user_id: int,
    summary: dict[str, Any],
    *,
    today: date,
    preferred_concept_key: str | None = None,
    preferred_pillar_key: str | None = None,
    preferred_anchor: date | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    focus_rows: list[dict[str, Any]] = []
    weakest = _select_weakest_pillar(summary)
    weakest_key = str(weakest.get("pillar_key") or "").strip().lower()
    for pillar_row in summary.get("pillars") or []:
        pillar_key = str(pillar_row.get("pillar_key") or "").strip().lower()
        if not pillar_key:
            continue
        pillar_label = str(pillar_row.get("label") or "").strip() or pillar_key.title()
        detail_anchor = (
            preferred_anchor
            if preferred_anchor is not None and pillar_key == str(preferred_pillar_key or "").strip().lower()
            else today
        )
        detail = get_pillar_tracker_detail(user_id, pillar_key, anchor=detail_anchor)
        focus_rows.extend(
            _recent_concept_focuses(
                detail,
                detail_anchor,
                pillar_key=pillar_key,
                pillar_label=pillar_label,
            )
        )
    focus_rows.sort(
        key=lambda item: (
            0
            if preferred_pillar_key and str(item.get("pillar_key") or "").strip().lower() == str(preferred_pillar_key).strip().lower()
            else 1,
            _focus_signal_priority(str(item.get("signal") or "")),
            -int(item.get("misses") or 0),
            -int(item.get("missing") or 0),
            item.get("score") if item.get("score") is not None else 999,
            0 if str(item.get("pillar_key") or "").strip().lower() == weakest_key else 1,
            _pillar_rank(str(item.get("pillar_key") or "")),
            str(item.get("label") or ""),
        )
    )
    if not focus_rows:
        return [], None
    preferred = _normalize_concept_token(preferred_concept_key)
    selected = next((item for item in focus_rows if _normalize_concept_token(item.get("concept_key")) == preferred), None)
    visible = focus_rows[:8]
    if selected and not any(
        _normalize_concept_token(item.get("concept_key")) == _normalize_concept_token(selected.get("concept_key"))
        for item in visible
    ):
        visible = [selected, *visible[:7]]
    if selected is None:
        selected = next(
            (
                item
                for item in visible
                if preferred_pillar_key
                and str(item.get("pillar_key") or "").strip().lower() == str(preferred_pillar_key).strip().lower()
            ),
            None,
        )
    if selected is None:
        selected = next(
            (item for item in visible if str(item.get("pillar_key") or "").strip().lower() == weakest_key),
            None,
        ) or visible[0]
    return visible, selected


def _score_state(score: int | None) -> str:
    if score is None:
        return "unknown"
    if score >= 80:
        return "strong"
    if score >= 60:
        return "fair"
    return "weak"


def _signal_rank(signal: str) -> int:
    token = str(signal or "").strip().lower()
    if token == "missed_today":
        return 0
    if token == "missed_yesterday":
        return 1
    if token == "not_logged_yesterday":
        return 2
    if token == "needs_support":
        return 3
    if token == "not_logged_today":
        return 4
    return 4


def _pillar_day_snapshot(user_id: int, pillar_row: dict[str, Any], today: date) -> dict[str, Any]:
    pillar_key = str(pillar_row.get("pillar_key") or "").strip().lower()
    pillar_label = str(pillar_row.get("label") or "").strip() or pillar_key.title()
    requested_anchor = _guidance_anchor_for_pillar(user_id, pillar_key, today)
    detail = get_pillar_tracker_detail(user_id, pillar_key, anchor=requested_anchor)
    resolved_anchor = str(((detail.get("pillar") or {}).get("active_date")) or "").strip()
    try:
        active_day = date.fromisoformat(resolved_anchor) if resolved_anchor else requested_anchor
    except Exception:
        active_day = requested_anchor
    active_label = str(((detail.get("pillar") or {}).get("active_label")) or "").strip()
    focus_rows = _anchored_concept_focuses(
        detail,
        active_day,
        pillar_key=pillar_key,
        pillar_label=pillar_label,
    )
    focus_rows.sort(
        key=lambda item: (
            _signal_rank(str(item.get("signal") or "")),
            item.get("score") if item.get("score") is not None else 999,
            str(item.get("label") or ""),
        )
    )
    primary_focus = focus_rows[0] if focus_rows else None
    score = _safe_int(pillar_row.get("score"))
    return {
        "pillar_key": pillar_key,
        "label": pillar_label,
        "score": score,
        "state": _score_state(score),
        "active_date": active_day.isoformat(),
        "active_label": active_label or active_day.isoformat(),
        "primary_focus": primary_focus,
        "review_concepts": focus_rows,
    }


def _focus_issue_text(focus: dict[str, Any] | None, *, fallback_label: str) -> str:
    focus = focus or {}
    label = str(focus.get("label") or fallback_label or "this area").strip() or "this area"
    signal = str(focus.get("signal") or "").strip().lower()
    concept_key = _normalize_concept_token(focus.get("concept_key"))
    if concept_key == "sleep_quality" and signal == "missed_today":
        return "You did not wake up well rested today, so recovery needs more protecting across the day."
    if concept_key == "sleep_duration" and signal == "missed_today":
        return "Sleep came up short, so today needs to stay more recovery-aware."
    if concept_key == "bedtime_consistency" and signal == "missed_today":
        return "Last night did not finish cleanly, so recovery needs tighter protection today."
    if signal == "missed_today":
        return f"{label} has already slipped today and needs tightening."
    if signal == "missed_yesterday":
        return f"{label} slipped yesterday and still needs protecting today."
    if signal == "not_logged_yesterday":
        return f"{label} still needs a proper check against yesterday's tracking."
    if signal == "not_logged_today":
        return f"{label} still needs an intentional check today."
    if signal == "needs_support":
        return f"{label} needs more support today."
    return f"{label} is the area to keep the closest eye on today."


def _best_pillar_strength(summary: dict[str, Any]) -> dict[str, Any] | None:
    pillars = [item for item in (summary.get("pillars") or []) if isinstance(item, dict)]
    if not pillars:
        return None
    ordered = sorted(
        pillars,
        key=lambda item: (
            -(_safe_int(item.get("score")) or -1),
            _pillar_rank(str(item.get("pillar_key") or "")),
        ),
    )
    return ordered[0] if ordered else None


def _latest_tracker_strength(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for pillar_key in _PILLAR_ORDER:
        snapshot = snapshots.get(pillar_key)
        if not isinstance(snapshot, dict):
            continue
        concepts = [item for item in (snapshot.get("review_concepts") or []) if isinstance(item, dict)]
        if not concepts:
            continue
        on_track = sum(1 for item in concepts if _concept_signal(item) == "on_track")
        missed_today = sum(1 for item in concepts if _concept_signal(item) == "missed_today")
        missed_yesterday = sum(1 for item in concepts if _concept_signal(item) == "missed_yesterday")
        candidates.append(
            {
                "pillar_key": pillar_key,
                "label": str(snapshot.get("label") or pillar_key.title()).strip() or pillar_key.title(),
                "on_track": on_track,
                "missed_today": missed_today,
                "missed_yesterday": missed_yesterday,
            }
        )
    if not candidates:
        return None
    ordered = sorted(
        candidates,
        key=lambda item: (
            int(item.get("missed_today") or 0),
            int(item.get("missed_yesterday") or 0),
            -(int(item.get("on_track") or 0)),
            _pillar_rank(str(item.get("pillar_key") or "")),
        ),
    )
    return ordered[0] if ordered else None


def _concept_signal(item: dict[str, Any] | None) -> str:
    return str((item or {}).get("signal") or "").strip().lower()


def _recovery_signal_profile(recovery_snapshot: dict[str, Any]) -> dict[str, bool]:
    rested = _snapshot_concept(recovery_snapshot, "sleep_quality") or {}
    sleep_duration = _snapshot_concept(recovery_snapshot, "sleep_duration") or {}
    bedtime = _snapshot_concept(recovery_snapshot, "bedtime_consistency") or {}
    rested_signal = _concept_signal(rested)
    sleep_signal = _concept_signal(sleep_duration)
    bedtime_signal = _concept_signal(bedtime)
    rested_today = rested_signal == "missed_today"
    sleep_today = sleep_signal == "missed_today"
    bedtime_today = bedtime_signal == "missed_today"
    return {
        "rested_today": rested_today,
        "sleep_today": sleep_today,
        "bedtime_today": bedtime_today,
        "acute_recovery_drag": rested_today or sleep_today,
    }


def _exercise_readiness(
    *,
    nutrition_snapshot: dict[str, Any],
    recovery_snapshot: dict[str, Any],
    resilience_snapshot: dict[str, Any],
) -> dict[str, str]:
    nutrition_state = _latest_daily_guidance_state(nutrition_snapshot, "nutrition")
    recovery_state = _latest_daily_guidance_state(recovery_snapshot, "recovery")
    resilience_state = _latest_daily_guidance_state(resilience_snapshot, "resilience")
    recovery_profile = _recovery_signal_profile(recovery_snapshot)
    if recovery_profile.get("rested_today") and recovery_profile.get("sleep_today"):
        exercise_state = "recover"
        reason = "You did not wake up rested and sleep was short, so today should stay recovery-first."
    elif recovery_profile.get("rested_today"):
        if nutrition_state == "weak":
            exercise_state = "recover"
            reason = "You did not wake up rested and nutrition also needs support, so keep today recovery-first."
        else:
            exercise_state = "light"
            reason = "You did not wake up rested, so keep movement in but make this a more recovery-conscious day."
    elif recovery_profile.get("sleep_today") and nutrition_state != "strong":
        exercise_state = "light"
        reason = "Sleep was short and the basics are not fully in place, so keep the day lighter and more supportive."
    elif nutrition_state == "weak" and recovery_state == "weak":
        exercise_state = "recover"
        reason = "Recovery and nutrition are both off, so today should stay recovery-first."
    elif nutrition_state == "weak" or recovery_state == "weak":
        exercise_state = "light"
        reason = "One of the key support areas is low, so keep movement in but reduce the intensity."
    elif nutrition_state == "strong" and recovery_state == "strong":
        if resilience_state == "weak":
            exercise_state = "steady"
            reason = "Recovery and nutrition are strong, but keep training controlled while mental load is higher."
        else:
            exercise_state = "push"
            reason = "Recovery and nutrition are both strong, so a solid planned training day makes sense."
    else:
        exercise_state = "steady"
        reason = "The basics are mixed rather than poor, so today suits a controlled session rather than a big push."
    return {
        "nutrition_state": nutrition_state,
        "recovery_state": recovery_state,
        "resilience_state": resilience_state,
        "exercise_state": exercise_state,
        "exercise_reason": reason,
    }


def _snapshot_focus_label(snapshot: dict[str, Any], fallback: str) -> str:
    focus = snapshot.get("primary_focus") if isinstance(snapshot, dict) else None
    label = str((focus or {}).get("label") or "").strip()
    return label or fallback


def _snapshot_concept(snapshot: dict[str, Any], concept_key: str) -> dict[str, Any] | None:
    target = _normalize_concept_token(concept_key)
    if not target or not isinstance(snapshot, dict):
        return None
    for item in (snapshot.get("review_concepts") or []):
        if not isinstance(item, dict):
            continue
        if _normalize_concept_token(item.get("concept_key")) == target:
            return item
    return None


def _latest_daily_guidance_state(snapshot: dict[str, Any], pillar_key: str) -> str:
    concepts = [item for item in (snapshot.get("review_concepts") or []) if isinstance(item, dict)]
    if not concepts:
        return str(snapshot.get("state") or "unknown").strip().lower() or "unknown"
    missed_today = sum(1 for item in concepts if _concept_signal(item) == "missed_today")
    missed_yesterday = sum(1 for item in concepts if _concept_signal(item) == "missed_yesterday")
    not_logged_yesterday = sum(1 for item in concepts if _concept_signal(item) == "not_logged_yesterday")
    needs_support = sum(1 for item in concepts if _concept_signal(item) == "needs_support")
    on_track = sum(1 for item in concepts if _concept_signal(item) == "on_track")
    token = str(pillar_key or "").strip().lower()
    if token == "recovery":
        recovery_profile = _recovery_signal_profile(snapshot)
        if recovery_profile.get("rested_today") or recovery_profile.get("sleep_today"):
            return "weak"
        if recovery_profile.get("bedtime_today") or missed_yesterday or not_logged_yesterday or needs_support:
            return "fair"
    elif token == "nutrition":
        critical_miss = any(
            _concept_signal(item) == "missed_today"
            and _normalize_concept_token(item.get("concept_key")) in {"hydration", "protein_intake", "fasting_adherence"}
            for item in concepts
        )
        if critical_miss or missed_today >= 2:
            return "weak"
        if missed_today or missed_yesterday or not_logged_yesterday or needs_support:
            return "fair"
    else:
        if missed_today >= 2:
            return "weak"
        if missed_today or missed_yesterday or not_logged_yesterday or needs_support:
            return "fair"
    if on_track:
        return "strong"
    return str(snapshot.get("state") or "unknown").strip().lower() or "unknown"


def _all_tracker_review_concepts(snapshots: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for snapshot in snapshots.values():
        if not isinstance(snapshot, dict):
            continue
        pillar_key = str(snapshot.get("pillar_key") or "").strip().lower()
        pillar_label = str(snapshot.get("label") or "").strip() or pillar_key.title()
        for raw_item in snapshot.get("review_concepts") or []:
            if not isinstance(raw_item, dict):
                continue
            items.append(
                {
                    **raw_item,
                    "pillar_key": str(raw_item.get("pillar_key") or pillar_key).strip().lower() or pillar_key,
                    "pillar_label": str(raw_item.get("pillar_label") or pillar_label).strip() or pillar_label,
                }
            )
    return items


def _primary_tracker_issue(snapshots: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    items = _all_tracker_review_concepts(snapshots)
    if not items:
        return None
    ordered = sorted(
        items,
        key=lambda item: (
            _focus_signal_priority(str(item.get("signal") or "")),
            item.get("score") if item.get("score") is not None else 999,
            _pillar_rank(str(item.get("pillar_key") or "")),
            str(item.get("label") or ""),
        ),
    )
    return ordered[0] if ordered else None


def _build_tracker_review(snapshots: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    review: list[dict[str, Any]] = []
    for pillar_key in _PILLAR_ORDER:
        snapshot = snapshots.get(pillar_key)
        if not isinstance(snapshot, dict):
            continue
        concepts = [
            {
                "concept_key": str(item.get("concept_key") or "").strip() or None,
                "label": str(item.get("label") or "").strip() or None,
                "helper": str(item.get("helper") or "").strip() or None,
                "signal": str(item.get("signal") or "").strip() or None,
                "target_label": str(item.get("target_label") or "").strip() or None,
                "latest_value": str(item.get("latest_value") or "").strip() or None,
                "score": _safe_int(item.get("score")),
                "anchor_date": str(item.get("anchor_date") or "").strip() or None,
            }
            for item in (snapshot.get("review_concepts") or [])
            if isinstance(item, dict) and str(item.get("label") or "").strip()
        ]
        review.append(
            {
                "pillar_key": pillar_key,
                "pillar_label": str(snapshot.get("label") or pillar_key.title()).strip() or pillar_key.title(),
                "active_date": str(snapshot.get("active_date") or "").strip() or None,
                "active_label": str(snapshot.get("active_label") or "").strip() or None,
                "state": _latest_daily_guidance_state(snapshot, pillar_key),
                "score": _safe_int(snapshot.get("score")),
                "concepts": concepts,
            }
        )
    return review


def _build_key_moments(
    *,
    user_id: int,
    readiness: dict[str, str],
    snapshots: dict[str, dict[str, Any]],
    wellbeing_targets: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    nutrition_snapshot = snapshots.get("nutrition") or {}
    training_snapshot = snapshots.get("training") or {}
    resilience_snapshot = snapshots.get("resilience") or {}
    recovery_snapshot = snapshots.get("recovery") or {}
    wellbeing_targets = wellbeing_targets if isinstance(wellbeing_targets, dict) else {}
    nutrition_state = _latest_daily_guidance_state(nutrition_snapshot, "nutrition")
    resilience_state = _latest_daily_guidance_state(resilience_snapshot, "resilience")
    recovery_state = _latest_daily_guidance_state(recovery_snapshot, "recovery")
    recovery_profile = _recovery_signal_profile(recovery_snapshot)
    training_focus_label = _snapshot_focus_label(training_snapshot, "training quality").lower()
    nutrition_focus_label = _snapshot_focus_label(nutrition_snapshot, "food and fluids").lower()
    resilience_focus_label = _snapshot_focus_label(resilience_snapshot, "your headspace").lower()
    recovery_focus_label = _snapshot_focus_label(recovery_snapshot, "recovery basics").lower()
    nutrition_focus_key = _normalize_concept_token((nutrition_snapshot.get("primary_focus") or {}).get("concept_key"))
    fasting_mode = str(wellbeing_targets.get("fasting_mode") or "off").strip().lower()
    fasting_goal_days = _safe_int(wellbeing_targets.get("fasting_goal_days")) or 0
    alcohol_goal_units = _safe_int(wellbeing_targets.get("alcohol_goal_units")) or 0
    alcohol_tracking = str(wellbeing_targets.get("alcohol_tracking") or "off").strip().lower()
    fasting_active = fasting_mode != "off" and _snapshot_concept(nutrition_snapshot, "fasting_adherence") is not None
    alcohol_active = alcohol_tracking == "on" and _snapshot_concept(nutrition_snapshot, "alcohol_units") is not None

    morning_title = "Set the day early"
    if fasting_active:
        morning_title = "Set the window cleanly"
        if recovery_profile.get("rested_today"):
            morning_detail = (
                f"Hydrate early, keep the start calm, and hold your {fasting_mode} window without turning the morning into a grind."
            )
        elif nutrition_state == "weak" or recovery_state == "weak":
            morning_detail = (
                f"Hydrate early, reset your {fasting_mode} fasting window, and avoid drifting into reactive eating later on."
            )
        else:
            morning_detail = (
                f"Hydrate early and be clear on your {fasting_mode} fasting window so the day starts controlled rather than automatic."
            )
    elif recovery_profile.get("rested_today"):
        morning_title = "Keep the start gentle"
        morning_detail = (
            "You did not wake up well rested, so keep the morning steady with fluids, food, and less rush than usual."
        )
    elif nutrition_focus_key == "hydration":
        morning_title = "Get fluids in early"
        morning_detail = (
            "Get fluids in early so energy, hunger, and training decisions are not driven by dehydration."
        )
    elif nutrition_focus_key in {"protein_intake", "fruit_veg", "processed_food"}:
        morning_title = "Set nutrition up early"
        morning_detail = (
            f"Plan the first proper meal early so {nutrition_focus_label} does not drift once the day speeds up."
        )
    elif nutrition_state == "weak" or recovery_state == "weak":
        morning_detail = (
            "Start with food, fluids, and a calmer pace so you are not trying to rescue energy later on."
        )
    else:
        morning_detail = (
            "Get food, fluids, and a steady start in early so the rest of the day has a solid base."
        )

    midday_title = "Keep the middle steady"
    if fasting_active:
        midday_title = "Keep the window deliberate"
        if recovery_profile.get("rested_today"):
            midday_detail = (
                f"Keep the middle of the day lighter, stay on top of fluids, and end your {fasting_mode} window deliberately rather than reactively."
            )
        elif nutrition_state == "weak":
            midday_detail = (
                f"Stay deliberate with your {fasting_mode} window, keep fluids up, and plan the first meal instead of improvising it."
            )
        else:
            midday_detail = (
                f"Use the middle of the day to stay on top of fluids and decide exactly how your {fasting_mode} window will end."
            )
    elif recovery_profile.get("rested_today"):
        midday_title = "Protect your energy"
        midday_detail = (
            "Use lunch and the middle of the day to refuel properly and keep the pace steadier than a normal push day."
        )
    elif nutrition_focus_key == "hydration":
        midday_title = "Top fluids up again"
        midday_detail = (
            "Top fluids up again around midday so the afternoon does not become a catch-up job."
        )
    elif nutrition_state == "weak":
        midday_detail = (
            f"Do not let {nutrition_focus_label} drift at lunch, and top fluids up before the afternoon gets busy."
        )
    elif resilience_state == "weak":
        midday_detail = (
            f"Use the middle of the day for a short reset so {resilience_focus_label} does not slide later on."
        )
    else:
        midday_detail = (
            f"Check food, fluids, and your headspace around midday so the second half of the day stays controlled."
        )

    exercise_state = str(readiness.get("exercise_state") or "steady").strip().lower()
    if exercise_state == "push":
        afternoon_title = "Train with intent"
        if fasting_active:
            afternoon_detail = (
                f"Use the planned session, but line it up with your {fasting_mode} plan so you are not forcing hard work under-fuelled."
            )
        else:
            afternoon_detail = (
                f"Use the afternoon for your planned session and keep {training_focus_label} purposeful rather than adding junk volume."
            )
    elif exercise_state == "steady":
        afternoon_title = "Keep training controlled"
        if fasting_active:
            afternoon_detail = (
                f"If you train today, keep it measured and make the timing fit your {fasting_mode} window rather than winging it."
            )
        else:
            afternoon_detail = (
                f"Train if planned, but keep the effort measured and let {training_focus_label} stay clean rather than forced."
            )
    elif exercise_state == "light":
        afternoon_title = "Keep movement supportive"
        if recovery_profile.get("rested_today"):
            afternoon_detail = (
                "Keep training lighter today and use walking, mobility, or an easier session rather than trying to force performance."
            )
        else:
            afternoon_detail = (
                f"Use lighter movement or mobility today and let {nutrition_focus_label} and {recovery_focus_label} catch up first."
            )
    else:
        afternoon_title = "Make recovery the session"
        if recovery_profile.get("acute_recovery_drag"):
            afternoon_detail = (
                "Skip the hard session today and put the effort into walking, mobility, and getting recovery back under you."
            )
        else:
            afternoon_detail = (
                f"Skip the hard session today and put the effort into walking, mobility, and settling {recovery_focus_label}."
            )

    evening_title = "Close the day cleanly"
    if alcohol_active:
        evening_title = "Protect the evening"
        alcohol_text = (
            "keep it alcohol-free"
            if alcohol_goal_units <= 0
            else f"keep alcohol within your {alcohol_goal_units}-unit weekly limit"
        )
        if fasting_active:
            evening_detail = (
                f"Close the day cleanly, {alcohol_text}, and finish eating deliberately so tomorrow's fasting window starts well."
            )
        elif recovery_state == "weak":
            evening_detail = (
                f"Keep the evening very simple, {alcohol_text}, and protect sleep so recovery is not dragged back further."
            )
        else:
            evening_detail = (
                f"Close things down cleanly, {alcohol_text}, and protect sleep so recovery keeps moving the right way."
            )
    elif fasting_active:
        if recovery_state == "weak":
            evening_detail = (
                f"Keep the evening simple, finish eating deliberately, and let tomorrow's {fasting_mode} window start cleanly."
            )
        else:
            evening_detail = (
                f"Finish the last meal deliberately and close the evening well so tomorrow's {fasting_mode} window starts cleanly."
            )
    elif recovery_profile.get("acute_recovery_drag"):
        evening_detail = (
            "Protect the evening properly tonight, keep stimulation low, and give yourself a better chance of waking up rested tomorrow."
        )
    elif recovery_state == "weak":
        evening_detail = (
            "Keep the evening very simple, protect sleep, and avoid anything that makes tomorrow harder."
        )
    elif resilience_state == "weak":
        evening_detail = (
            f"Use the evening for a short reset so {resilience_focus_label} feels steadier before bed."
        )
    else:
        evening_detail = (
            f"Close things down cleanly, keep {recovery_focus_label} steady, and finish with a short mental reset."
        )

    return [
        {"moment_key": "morning", "moment_label": "Morning", "title": morning_title, "detail": morning_detail[:180]},
        {"moment_key": "midday", "moment_label": "Midday", "title": midday_title, "detail": midday_detail[:180]},
        {"moment_key": "afternoon", "moment_label": "Afternoon", "title": afternoon_title, "detail": afternoon_detail[:180]},
        {"moment_key": "evening", "moment_label": "Evening", "title": evening_title, "detail": evening_detail[:180]},
    ]


def _day_plan_title(readiness: dict[str, str]) -> str:
    exercise_state = str(readiness.get("exercise_state") or "steady").strip().lower()
    return {
        "push": "Strong training day",
        "steady": "Controlled training day",
        "light": "Light movement day",
        "recover": "Recovery-first day",
    }.get(exercise_state, "Today's plan")


def _build_day_brief(
    *,
    user_id: int,
    summary: dict[str, Any],
    today: date,
) -> dict[str, Any]:
    snapshots: dict[str, dict[str, Any]] = {}
    for pillar_row in (summary.get("pillars") or []):
        if not isinstance(pillar_row, dict):
            continue
        pillar_key = str(pillar_row.get("pillar_key") or "").strip().lower()
        if not pillar_key:
            continue
        snapshots[pillar_key] = _pillar_day_snapshot(user_id, pillar_row, today)
    nutrition_snapshot = snapshots.get("nutrition") or {"state": "unknown", "label": "Nutrition"}
    recovery_snapshot = snapshots.get("recovery") or {"state": "unknown", "label": "Recovery"}
    resilience_snapshot = snapshots.get("resilience") or {"state": "unknown", "label": "Resilience"}
    fasting_mode, alcohol_tracking, fasting_goal_days, alcohol_goal_units = _wellbeing_weekly_targets(int(user_id))
    wellbeing_targets = {
        "fasting_mode": fasting_mode,
        "fasting_goal_days": fasting_goal_days,
        "alcohol_tracking": alcohol_tracking,
        "alcohol_goal_units": alcohol_goal_units,
    }
    readiness = _exercise_readiness(
        nutrition_snapshot=nutrition_snapshot,
        recovery_snapshot=recovery_snapshot,
        resilience_snapshot=resilience_snapshot,
    )
    recovery_profile = _recovery_signal_profile(recovery_snapshot)
    strength_row = _latest_tracker_strength(snapshots) or {}
    strength_label = str(strength_row.get("label") or "The basics").strip() or "The basics"
    strength_text = f"{strength_label} looks the steadiest in the latest tracking."
    primary_issue = _primary_tracker_issue(snapshots)
    if recovery_profile.get("rested_today"):
        carry_over_issue = "You did not wake up well rested today, so this needs to be a more recovery-aware day rather than a push day."
    elif recovery_profile.get("sleep_today"):
        carry_over_issue = "Sleep came up short, so today needs to stay more protective and less aggressive."
    else:
        carry_over_issue = _focus_issue_text(
            primary_issue,
            fallback_label="today's tracking",
        )
    exercise_state = str(readiness.get("exercise_state") or "steady").strip().lower()
    if exercise_state == "push":
        today_aim = "Use the good base you have, train properly if planned, and keep the rest of the day steady around it."
    elif exercise_state == "steady":
        today_aim = "Keep the day controlled, train with intent if planned, and do not let the basics drift."
    elif exercise_state == "light":
        today_aim = "Keep movement light, restore the basics, and make the day easier rather than heavier."
    else:
        today_aim = "Keep the day simple, recover properly, and take the pressure off until the basics feel steadier."
    key_moments = _build_key_moments(
        user_id=user_id,
        readiness=readiness,
        snapshots=snapshots,
        wellbeing_targets=wellbeing_targets,
    )
    today_priority = "The main job today is to match training, food, recovery, and headspace rather than let one area drag the rest off line."
    if recovery_profile.get("rested_today"):
        today_priority = "The main job today is to protect energy, keep training lighter, and set tonight up so recovery can catch back up."
    elif recovery_profile.get("sleep_today"):
        today_priority = "The main job today is to steady the basics, avoid forcing intensity, and give recovery a better chance tonight."
    return {
        "two_day_read": {
            "strength": strength_text,
            "carry_over_issue": carry_over_issue,
            "today_priority": today_priority,
        },
        "readiness": readiness,
        "wellbeing_targets": wellbeing_targets,
        "key_moments": key_moments,
        "today_aim": today_aim,
        "plan_title": _day_plan_title(readiness),
        "plan_summary": f"{readiness.get('exercise_reason')} {today_aim}".strip(),
    }


def _build_generation_context(user_id: int, *, selected_concept_key: str | None = None) -> dict[str, Any]:
    today = tracker_today()
    summary = get_pillar_tracker_summary(user_id, anchor=today)
    weakest = _select_weakest_pillar(summary)
    snapshots: dict[str, dict[str, Any]] = {}
    for pillar_row in (summary.get("pillars") or []):
        if not isinstance(pillar_row, dict):
            continue
        pillar_key = str(pillar_row.get("pillar_key") or "").strip().lower()
        if not pillar_key:
            continue
        snapshots[pillar_key] = _pillar_day_snapshot(user_id, pillar_row, today)
    tracker_review = _build_tracker_review(snapshots)
    selected_pillar_key = str(weakest.get("pillar_key") or "nutrition").strip().lower() or "nutrition"
    selected_pillar_label = str(weakest.get("label") or selected_pillar_key.title()).strip() or selected_pillar_key.title()
    okr_context: dict[str, Any] = {}
    selected_pillar_payload = {
        "pillar_key": selected_pillar_key,
        "label": selected_pillar_label or selected_pillar_key.title(),
    }
    day_brief = _build_day_brief(
        user_id=user_id,
        summary=summary,
        today=today,
    )
    pillars_payload = [
        {
            "pillar_key": str(item.get("pillar_key") or "").strip(),
            "label": str(item.get("label") or "").strip(),
            "score": _safe_int(item.get("score")),
            "tracker_score": _safe_int(item.get("tracker_score")),
            "baseline_score": _safe_int(item.get("baseline_score")),
        }
        for item in (summary.get("pillars") or [])
    ]
    return {
        "user_name": _load_user_name(user_id),
        "plan_date": today.isoformat(),
        "tracker_focus_date": today.isoformat(),
        "tracker_focus_source": "all_daily_tracking",
        "latest_tracker_save": None,
        "weakest_pillar": {
            "pillar_key": str(weakest.get("pillar_key") or "nutrition").strip().lower(),
            "label": str(weakest.get("label") or "").strip() or str(weakest.get("pillar_key") or "nutrition").strip().title(),
            "score": _safe_int(weakest.get("score")),
            "tracker_score": _safe_int(weakest.get("tracker_score")),
            "baseline_score": _safe_int(weakest.get("baseline_score")),
        },
        "selected_pillar": {
            **selected_pillar_payload,
        },
        "pillar_scores": pillars_payload,
        "focus_concepts": [],
        "selected_focus_concept": None,
        "okr_context": okr_context,
        "tracker_review": tracker_review,
        "day_brief": day_brief,
    }


def build_daily_tracker_generation_context(
    user_id: int,
    *,
    selected_concept_key: str | None = None,
) -> dict[str, Any]:
    return _build_generation_context(user_id, selected_concept_key=selected_concept_key)


def build_daily_tracker_generation_context_snapshot(
    user_id: int,
    *,
    selected_concept_key: str | None = None,
) -> dict[str, Any]:
    context = _build_generation_context(user_id, selected_concept_key=selected_concept_key)
    return {
        "context": context,
        "context_hash": _context_hash(context),
    }


def _context_hash(context: dict[str, Any]) -> str:
    payload = json.dumps(context, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _normalize_habit_item(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        title = raw.strip()
        if not title:
            return None
        return {"title": title[:90], "detail": ""}
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or raw.get("habit") or "").strip()
    detail = str(raw.get("detail") or raw.get("why") or raw.get("note") or "").strip()
    if not title and detail:
        title, detail = detail[:90], ""
    if not title:
        return None
    return {"title": title[:90], "detail": detail[:180]}


def _normalize_moment_key(value: Any) -> str | None:
    token = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    mapping = {
        "morning": "morning",
        "am": "morning",
        "start_of_day": "morning",
        "midday": "midday",
        "mid_day": "midday",
        "lunch": "midday",
        "pretraining": "afternoon",
        "pre_training": "afternoon",
        "afternoon": "afternoon",
        "training": "afternoon",
        "session": "afternoon",
        "evening": "evening",
        "pm": "evening",
        "night": "evening",
        "close_of_day": "evening",
    }
    return mapping.get(token) or None


def _moment_label_for_key(moment_key: Any) -> str | None:
    normalized = _normalize_moment_key(moment_key)
    lookup = {key: label for key, label in _DAY_MOMENT_SEQUENCE}
    return lookup.get(normalized) if normalized else None


def _normalize_ask_suggestion(raw: Any) -> dict[str, str] | None:
    if not isinstance(raw, dict):
        return None
    label = str(raw.get("label") or raw.get("title") or "").strip()
    text = str(raw.get("text") or raw.get("question") or raw.get("prompt") or "").strip()
    if not label or not text:
        return None
    return {
        "label": label[:40],
        "text": text[:220],
    }


def _normalized_ask_suggestions(items: Any) -> list[dict[str, str]]:
    if not isinstance(items, list):
        return []
    return [
        item
        for item in (_normalize_ask_suggestion(row) for row in items)
        if item
    ][:4]


def _normalize_habit_plan_item(
    raw: Any,
    *,
    default_concept: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    normalized = _normalize_habit_item(raw)
    if not normalized:
        return None
    raw_dict = raw if isinstance(raw, dict) else {}
    concept_key = _normalize_concept_token(
        raw_dict.get("concept_key") if isinstance(raw_dict, dict) else None
    ) or _normalize_concept_token((default_concept or {}).get("concept_key"))
    concept_label = str(
        (raw_dict.get("concept_label") if isinstance(raw_dict, dict) else None)
        or (default_concept or {}).get("label")
        or ""
    ).strip() or None
    pillar_key = str(
        (raw_dict.get("pillar_key") if isinstance(raw_dict, dict) else None)
        or (default_concept or {}).get("pillar_key")
        or ""
    ).strip().lower() or None
    pillar_label = str(
        (raw_dict.get("pillar_label") if isinstance(raw_dict, dict) else None)
        or (default_concept or {}).get("pillar_label")
        or ""
    ).strip() or None
    moment_key = (
        _normalize_moment_key(raw_dict.get("moment_key"))
        or _normalize_moment_key(raw_dict.get("moment"))
        or _normalize_moment_key(raw_dict.get("when"))
        or _normalize_moment_key(raw_dict.get("time_of_day"))
    )
    title_token = _normalize_moment_key(normalized.get("title"))
    if moment_key is None and title_token:
        moment_key = title_token
    moment_label = str(
        (raw_dict.get("moment_label") if isinstance(raw_dict, dict) else None)
        or _moment_label_for_key(moment_key)
        or ""
    ).strip() or None
    item_id = str((raw_dict.get("id") if isinstance(raw_dict, dict) else None) or "").strip()
    if not item_id:
        item_id = _habit_item_id(
            title=normalized["title"],
            detail=normalized["detail"],
            concept_key=concept_key,
            pillar_key=pillar_key,
            moment_key=moment_key,
        )
    return {
        "id": item_id,
        "title": normalized["title"],
        "detail": normalized["detail"],
        "concept_key": concept_key,
        "concept_label": concept_label,
        "pillar_key": pillar_key,
        "pillar_label": pillar_label,
        "moment_key": moment_key,
        "moment_label": moment_label,
    }


def _items_with_day_moments(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    used: set[str] = set()
    sequence = list(_DAY_MOMENT_SEQUENCE)
    for index, item in enumerate(items):
        row = dict(item)
        moment_key = _normalize_moment_key(row.get("moment_key"))
        if not moment_key:
            if index < len(sequence):
                moment_key = sequence[index][0]
            else:
                moment_key = f"step_{index + 1}"
        if moment_key in used:
            for candidate_key, _candidate_label in sequence:
                if candidate_key not in used:
                    moment_key = candidate_key
                    break
        used.add(moment_key)
        row["moment_key"] = moment_key
        row["moment_label"] = str(row.get("moment_label") or _moment_label_for_key(moment_key) or f"Step {index + 1}").strip()
        output.append(row)
    return output


def _has_complete_day_plan_items(items: list[dict[str, Any]]) -> bool:
    if len(items) < len(_DAY_MOMENT_SEQUENCE):
        return False
    keys = {
        _normalize_moment_key(item.get("moment_key"))
        for item in items
        if isinstance(item, dict)
    }
    required_keys = {key for key, _label in _DAY_MOMENT_SEQUENCE}
    return required_keys.issubset({key for key in keys if key})


def _dedupe_habit_plan_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        output.append(item)
    return output


def _concept_lookup_map(concepts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for concept in concepts:
        concept_key = _normalize_concept_token((concept or {}).get("concept_key"))
        if not concept_key or concept_key in lookup:
            continue
        lookup[concept_key] = concept
    return lookup


def _habit_plan_version(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        return 0
    return _safe_int(payload.get("habit_plan_version")) or 0


def _items_for_concept(
    items: list[dict[str, Any]],
    *,
    concept_key: str | None,
) -> list[dict[str, Any]]:
    normalized_key = _normalize_concept_token(concept_key)
    if not normalized_key:
        return []
    return [
        item
        for item in items
        if _normalize_concept_token(item.get("concept_key")) == normalized_key
    ]


def _habit_option_sets_from_state(
    payload: dict[str, Any],
    *,
    available_concepts: list[dict[str, Any]],
    legacy_habits: list[Any] | None = None,
    default_selected_concept: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    concept_lookup = _concept_lookup_map(available_concepts)
    option_sets: dict[str, list[dict[str, Any]]] = {}
    state_version = _habit_plan_version(payload)
    raw_sets = payload.get("habit_option_sets") if isinstance(payload, dict) else None
    if state_version >= _CURRENT_HABIT_PLAN_VERSION and isinstance(raw_sets, dict):
        for raw_key, raw_items in raw_sets.items():
            scope_key = _normalize_plan_scope_key(raw_key)
            if not scope_key or not isinstance(raw_items, list):
                continue
            default_concept = concept_lookup.get(scope_key) or default_selected_concept
            items = [
                item
                for item in (
                    _normalize_habit_plan_item(raw_item, default_concept=default_concept)
                    for raw_item in raw_items
                )
                if item
            ]
            if scope_key != _DAY_PLAN_SCOPE_KEY:
                items = _items_for_concept(items, concept_key=scope_key)
            if items:
                option_sets[scope_key] = _dedupe_habit_plan_items(items)
    if option_sets:
        return option_sets
    if not isinstance(legacy_habits, list):
        return {}
    legacy_items = [
        item
        for item in (
            _normalize_habit_plan_item(raw_item, default_concept=default_selected_concept)
            for raw_item in legacy_habits
        )
        if item
    ]
    if legacy_items:
        option_sets[_DAY_PLAN_SCOPE_KEY] = _dedupe_habit_plan_items(_items_with_day_moments(legacy_items))
    return option_sets


def _selected_habits_from_row(
    row: DailyCoachHabitPlan,
    *,
    available_concepts: list[dict[str, Any]],
    structured_state: bool,
) -> list[dict[str, Any]]:
    if not structured_state:
        return []
    concept_lookup = _concept_lookup_map(available_concepts)
    raw_items = getattr(row, "habits", None) or []
    if not isinstance(raw_items, list):
        return []
    items = []
    for raw_item in raw_items:
        default_concept = concept_lookup.get(
            _normalize_concept_token((raw_item or {}).get("concept_key")) if isinstance(raw_item, dict) else None
        )
        normalized = _normalize_habit_plan_item(raw_item, default_concept=default_concept)
        if normalized:
            items.append(normalized)
    return _items_with_day_moments(_dedupe_habit_plan_items(items))


def _normalize_selected_ids_map(payload: dict[str, Any]) -> dict[str, list[str]]:
    raw_map = payload.get("selected_option_ids_by_concept") if isinstance(payload, dict) else None
    if not isinstance(raw_map, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for raw_key, raw_ids in raw_map.items():
        scope_key = _normalize_plan_scope_key(raw_key)
        if not scope_key or not isinstance(raw_ids, list):
            continue
        ids: list[str] = []
        seen: set[str] = set()
        for raw_id in raw_ids:
            item_id = str(raw_id or "").strip()
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            ids.append(item_id)
        if ids:
            normalized[scope_key] = ids
    return normalized


def _recover_selected_ids_map_from_row(
    row: DailyCoachHabitPlan | None,
    *,
    available_concepts: list[dict[str, Any]],
    option_sets: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    if row is None:
        return {}
    recovered_items = _selected_habits_from_row(
        row,
        available_concepts=available_concepts,
        structured_state=True,
    )
    if not recovered_items:
        return {}
    recovered: dict[str, list[str]] = {}
    for item in recovered_items:
        concept_key = _normalize_plan_scope_key(item.get("concept_key")) or _DAY_PLAN_SCOPE_KEY
        item_id = str(item.get("id") or "").strip()
        if not concept_key or not item_id:
            continue
        recovered.setdefault(concept_key, []).append(item_id)
    cleaned: dict[str, list[str]] = {}
    for concept_key, ids in recovered.items():
        deduped_ids = list(dict.fromkeys(ids))
        option_ids = [
            str(item.get("id") or "").strip()
            for item in option_sets.get(concept_key, [])
            if str(item.get("id") or "").strip()
        ]
        if option_ids and len(option_ids) > 1 and set(deduped_ids) == set(option_ids):
            continue
        cleaned[concept_key] = deduped_ids
    return cleaned


def _selected_ids_by_concept(
    payload: dict[str, Any],
    *,
    row: DailyCoachHabitPlan | None,
    available_concepts: list[dict[str, Any]],
    option_sets: dict[str, list[dict[str, Any]]],
) -> dict[str, list[str]]:
    selected_map = (
        _normalize_selected_ids_map(payload)
        if _habit_plan_version(payload) >= _CURRENT_HABIT_PLAN_VERSION
        else {}
    )
    if selected_map:
        return selected_map
    return _recover_selected_ids_map_from_row(
        row,
        available_concepts=available_concepts,
        option_sets=option_sets,
    )


def _selected_habits_from_option_sets(
    option_sets: dict[str, list[dict[str, Any]]],
    selected_ids_by_concept: dict[str, list[str]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for concept_key, selected_ids in selected_ids_by_concept.items():
        if not selected_ids:
            continue
        option_lookup = {
            str(item.get("id") or "").strip(): item
            for item in option_sets.get(concept_key, [])
            if str(item.get("id") or "").strip()
        }
        for item_id in selected_ids:
            item = option_lookup.get(item_id)
            if item:
                items.append(item)
    return _items_with_day_moments(_dedupe_habit_plan_items(items))


def _merge_concept_option_set(
    *,
    existing_items: list[dict[str, Any]],
    selected_items: list[dict[str, Any]],
    generated_items: list[dict[str, Any]],
    force: bool,
) -> list[dict[str, Any]]:
    selected_text_keys = {
        (
            str(item.get("title") or "").strip().lower(),
            str(item.get("detail") or "").strip().lower(),
        )
        for item in selected_items
        if str(item.get("title") or "").strip() or str(item.get("detail") or "").strip()
    }
    selected_ids = {
        str(item.get("id") or "").strip()
        for item in selected_items
        if str(item.get("id") or "").strip()
    }
    filtered_generated = [
        item
        for item in generated_items
        if (
            str(item.get("title") or "").strip().lower(),
            str(item.get("detail") or "").strip().lower(),
        ) not in selected_text_keys
    ]
    generated_ids = {
        str(item.get("id") or "").strip()
        for item in filtered_generated
        if str(item.get("id") or "").strip()
    }
    if force:
        preserved_selected = [
            item
            for item in existing_items
            if str(item.get("id") or "").strip() in selected_ids
        ]
        return _dedupe_habit_plan_items([*preserved_selected, *filtered_generated])
    preserved_existing = [
        item
        for item in existing_items
        if str(item.get("id") or "").strip() not in generated_ids
    ]
    return _dedupe_habit_plan_items([*selected_items, *filtered_generated, *preserved_existing])


def _resolve_selected_concept(
    payload: dict[str, Any],
    *,
    available_concepts: list[dict[str, Any]],
    fallback_concept: dict[str, Any] | None,
) -> dict[str, Any] | None:
    selected_key = _normalize_concept_token(payload.get("selected_concept_key")) if isinstance(payload, dict) else None
    if selected_key:
        for concept in available_concepts:
            if _normalize_concept_token((concept or {}).get("concept_key")) == selected_key:
                return concept
    return fallback_concept or (available_concepts[0] if available_concepts else None)

def _fallback_habit_for_concept(concept: dict[str, Any], pillar_key: str) -> dict[str, str]:
    target_label = str(concept.get("target_label") or "").strip()
    concept_key = str(concept.get("concept_key") or "").strip().lower()
    label = str(concept.get("label") or "").strip() or "Habit"
    fallback_map = {
        "protein_intake": ("Add protein to your next meal", target_label or "Aim for a stronger protein spread through the day."),
        "fruit_veg": ("Add colour to two meals today", target_label or "Build in at least one extra fruit or veg portion."),
        "hydration": ("Finish one full bottle early", target_label or "Keep water visible and top it up twice today."),
        "processed_food": ("Swap one processed snack today", target_label or "Make one whole-food swap before the day ends."),
        "cardio_frequency": ("Fit in one cardio block today", target_label or "A brisk 20-minute walk counts."),
        "strength_training": ("Complete a short strength session", target_label or "Even one focused block moves this forward."),
        "flexibility_mobility": ("Do 10 minutes of mobility", target_label or "Use it as a reset before bed or after work."),
        "emotional_regulation": ("Take one reset pause today", "Use breathing or a short walk before your busiest moment."),
        "positive_connection": ("Create one positive connection", "Check in with someone or take 10 minutes for yourself."),
        "stress_recovery": ("Use one recovery tool today", "Schedule a short reset before stress spikes."),
        "optimism_perspective": ("Reframe one difficult moment", "Write one constructive response before the day ends."),
        "support_openness": ("Ask for one bit of support", "Be clear about one thing you need today."),
        "sleep_duration": ("Protect 7+ hours tonight", target_label or "Set your stop time early enough for full sleep."),
        "sleep_quality": ("Build a calmer wind-down tonight", "Keep the final 30 minutes low-stimulation."),
        "bedtime_consistency": ("Set a bedtime alarm tonight", "Start winding down at the same time as yesterday."),
    }
    title, detail = fallback_map.get(
        concept_key,
        (
            f"Take one {label.lower()} step today",
            target_label or f"Choose one action that supports your {pillar_key} score today.",
        ),
    )
    return {"title": title, "detail": detail}


def _fallback_habit_options_for_concept(concept: dict[str, Any], pillar_key: str) -> list[dict[str, str]]:
    label = str(concept.get("label") or "Habit").strip() or "Habit"
    target_label = str(concept.get("target_label") or "").strip()
    primary = _fallback_habit_for_concept(concept, pillar_key)
    options = [
        primary,
        {
            "title": f"Prep one easy {label.lower()} win",
            "detail": target_label or "Set something up early so this feels easier later today.",
        },
        {
            "title": f"Anchor {label.lower()} to one routine",
            "detail": "Tie it to something you already do today so you do not have to rely on memory.",
        },
        {
            "title": f"Do the smallest version of {label.lower()}",
            "detail": "Choose the easiest version that still counts and get that done first.",
        },
    ]
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in options:
        key = str(item.get("title") or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:5]


def _fallback_plan(context: dict[str, Any]) -> dict[str, Any]:
    day_brief = context.get("day_brief") or {}
    moments = [
        item
        for item in (
            _normalize_habit_plan_item(raw_item, default_concept=None)
            for raw_item in (day_brief.get("key_moments") or [])
        )
        if item
    ]
    moments = _items_with_day_moments(moments)
    if not moments:
        fallback_items = [
            _normalize_habit_plan_item(
                {
                    "title": "Set the day early",
                    "detail": "Choose one simple action that makes the rest of the day easier to manage.",
                    "moment_key": "morning",
                },
                default_concept=None,
            ),
            _normalize_habit_plan_item(
                {
                    "title": "Keep the middle steady",
                    "detail": "Use lunch and the middle of the day to keep food, fluids, and focus under control.",
                    "moment_key": "midday",
                },
                default_concept=None,
            ),
            _normalize_habit_plan_item(
                {
                    "title": "Keep the afternoon purposeful",
                    "detail": "Use the afternoon for the right level of movement for today, not extra noise.",
                    "moment_key": "afternoon",
                },
                default_concept=None,
            ),
            _normalize_habit_plan_item(
                {
                    "title": "Close the day cleanly",
                    "detail": "Finish with a short reset so tomorrow starts cleaner than today.",
                    "moment_key": "evening",
                },
                default_concept=None,
            ),
        ]
        moments = _items_with_day_moments([item for item in fallback_items if item])
    return {
        "title": str(day_brief.get("plan_title") or "Today's plan").strip() or "Today's plan",
        "summary": str(day_brief.get("plan_summary") or "Use these key moments to keep the day steady and practical.").strip()[:500],
        "habits": moments[:5],
        "source": "fallback",
    }


def _fallback_ask_suggestions(context: dict[str, Any]) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()

    def push(label: str, text: str) -> None:
        normalized_label = str(label or "").strip()
        normalized_text = str(text or "").strip()
        if not normalized_label or not normalized_text:
            return
        key = f"{normalized_label.lower()}::{normalized_text.lower()}"
        if key in seen:
            return
        seen.add(key)
        suggestions.append({"label": normalized_label[:40], "text": normalized_text[:220]})

    tracker_review = [item for item in (context.get("tracker_review") or []) if isinstance(item, dict)]
    selected_habits = [item for item in (context.get("selected_habits") or []) if isinstance(item, dict)]
    signals = [
        str(concept.get("signal") or "").strip().lower()
        for pillar in tracker_review
        for concept in (pillar.get("concepts") or [])
        if isinstance(concept, dict)
    ]

    if "missed_today" in signals or "missed_yesterday" in signals:
        push("Get back on track", "What is the best way for me to get back on track today?")
    if "not_logged_today" in signals:
        push("Log it simply", "What's the simplest way for me to track properly today?")
    if "needs_support" in signals:
        push("Why is this slipping", "Why does this keep slipping for me and what should I change?")
    if selected_habits:
        push("Stick to today's plan", "How do I stay consistent with the key moments I've set for today?")

    push("Best next step", "Based on my tracking, what's the most useful next step for me today?")
    push("Recover today", "What would help me recover well today without overcomplicating it?")
    push("Build consistency", "How do I make this feel easier to repeat tomorrow as well?")
    return suggestions[:4]


def _generate_plan_from_llm(user_id: int, context: dict[str, Any]) -> dict[str, Any] | None:
    try:
        selected_pillar = context.get("selected_pillar") or {}
        user_name = str(context.get("user_name") or "User").strip() or "User"
        ensure_builtin_prompt_templates(["daily_habit_plan"])
        assembly = build_prompt(
            "daily_habit_plan",
            user_id=user_id,
            coach_name="HealthSense",
            user_name=user_name,
            locale="UK",
            timeframe="today",
            plan_date=context.get("plan_date"),
            scores=context.get("pillar_scores") or [],
            weakest_pillar=context.get("weakest_pillar") or {},
            selected_pillar=selected_pillar,
            okr_context=context.get("okr_context") or {},
            tracker_review=context.get("tracker_review") or [],
            day_brief=context.get("day_brief") or {},
        )
        prompt = assembly.text
        raw = run_llm_prompt(
            prompt,
            user_id=user_id,
            touchpoint="daily_habit_plan",
            prompt_variant=assembly.variant,
            task_label=assembly.task_label,
            context_meta={
                "page": "coach_home",
                "pillar_key": str(selected_pillar.get("pillar_key") or "").strip().lower(),
                "plan_date": _today_iso(),
            },
            prompt_blocks=assembly.blocks,
            block_order=assembly.block_order,
        )
        parsed = _extract_json_object(raw)
        if not parsed:
            return None
        raw_items = parsed.get("moments") if isinstance(parsed.get("moments"), list) else parsed.get("habits")
        habits = [
            item
            for item in (
                _normalize_habit_plan_item(row, default_concept=None)
                for row in (raw_items or [])
            )
            if item
        ][:5]
        habits = _items_with_day_moments(habits)
        if len(habits) < len(_DAY_MOMENT_SEQUENCE):
            return None
        day_brief = context.get("day_brief") or {}
        title = str(parsed.get("title") or "").strip() or str(day_brief.get("plan_title") or "Today's plan").strip()
        summary = str(parsed.get("summary") or "").strip() or str(
            day_brief.get("plan_summary") or "Use these key moments to keep the day steady and practical."
        ).strip()
        return {
            "title": title[:200],
            "summary": summary[:500],
            "habits": habits,
            "source": "llm",
        }
    except Exception as exc:
        print(f"[daily-habits] WARN: llm day-plan generation failed for user_id={user_id}: {exc}")
        return None


def _serialize_plan(
    row: DailyCoachHabitPlan,
    *,
    default_habits_view: str | None = None,
) -> dict[str, Any]:
    payload = row.context_payload if isinstance(getattr(row, "context_payload", None), dict) else {}
    available_concepts: list[dict[str, Any]] = []
    option_sets = _habit_option_sets_from_state(
        payload,
        available_concepts=available_concepts,
        legacy_habits=getattr(row, "habits", None) if isinstance(getattr(row, "habits", None), list) else None,
        default_selected_concept=None,
    )
    selected_ids_by_concept = _selected_ids_by_concept(
        payload,
        row=row,
        available_concepts=available_concepts,
        option_sets=option_sets,
    )
    selected_habits = _items_with_day_moments(_selected_habits_from_option_sets(option_sets, selected_ids_by_concept))
    ask_suggestions = _normalized_ask_suggestions(payload.get("ask_suggestions") or [])
    selected_ids = {str(item.get("id") or "").strip() for item in selected_habits}
    selected_concept_key = None
    raw_current_options = [dict(item) for item in option_sets.get(_DAY_PLAN_SCOPE_KEY, [])]
    current_options = []
    for item in _items_with_day_moments(raw_current_options):
        current_options.append({**item, "selected": str(item.get("id") or "").strip() in selected_ids})
    if not _has_complete_day_plan_items(current_options):
        fallback_plan = _fallback_plan(payload)
        fallback_items = [
            item
            for item in (
                _normalize_habit_plan_item(raw_item, default_concept=None)
                for raw_item in ((fallback_plan or {}).get("habits") or [])
            )
            if item
        ]
        fallback_items = _items_with_day_moments(fallback_items)
        options_by_moment = {
            _normalize_moment_key(item.get("moment_key")): dict(item)
            for item in current_options
            if _normalize_moment_key(item.get("moment_key"))
        }
        for item in fallback_items:
            moment_key = _normalize_moment_key(item.get("moment_key"))
            if moment_key and moment_key not in options_by_moment:
                options_by_moment[moment_key] = {**item, "selected": False}
        current_options = [
            options_by_moment[moment_key]
            for moment_key, _label in _DAY_MOMENT_SEQUENCE
            if moment_key in options_by_moment
        ]
    display_habits = selected_habits
    if len(display_habits) < len(_DAY_MOMENT_SEQUENCE) and len(current_options) >= len(_DAY_MOMENT_SEQUENCE):
        display_habits = [dict(item) for item in current_options]
    elif not display_habits and current_options:
        display_habits = [dict(item) for item in current_options]
    concepts_payload = []
    for concept in available_concepts:
        concept_key = _normalize_concept_token(concept.get("concept_key"))
        concepts_payload.append(
            {
                **concept,
                "concept_key": concept_key,
                "is_selected": concept_key == selected_concept_key,
            }
        )
    return {
        "user_id": int(getattr(row, "user_id", 0) or 0),
        "plan_date": getattr(row, "plan_date", None).isoformat() if getattr(row, "plan_date", None) else None,
        "pillar_key": str(getattr(row, "pillar_key", "") or "").strip() or None,
        "pillar_label": str(getattr(row, "pillar_label", "") or "").strip() or None,
        "title": str(getattr(row, "title", "") or "").strip() or None,
        "summary": str(getattr(row, "summary", "") or "").strip() or None,
        "habits": display_habits,
        "options": current_options,
        "ask_suggestions": ask_suggestions[:4],
        "available_concepts": concepts_payload,
        "selected_concept_key": None,
        "selected_concept_label": None,
        "default_habits_view": (
            "selected_habits"
            if default_habits_view == "selected_habits" and selected_habits
            else "suggestions"
        ),
        "source": str(getattr(row, "source", "") or "").strip() or None,
        "generated_at": getattr(row, "generated_at", None).isoformat() if getattr(row, "generated_at", None) else None,
    }


def _latest_prior_daily_habit_plan(user_id: int, today: date) -> DailyCoachHabitPlan | None:
    with SessionLocal() as s:
        return (
            s.execute(
                select(DailyCoachHabitPlan)
                .where(
                    DailyCoachHabitPlan.user_id == int(user_id),
                    DailyCoachHabitPlan.plan_date < today,
                )
                .order_by(desc(DailyCoachHabitPlan.plan_date), desc(DailyCoachHabitPlan.id))
            )
            .scalars()
            .first()
        )


def get_or_generate_daily_habit_plan(
    user_id: int,
    *,
    force: bool = False,
    concept_key: str | None = None,
    allow_llm: bool = False,
) -> dict[str, Any]:
    ensure_daily_habit_plan_schema()
    today = tracker_today()
    with SessionLocal() as s:
        existing = (
            s.execute(
                select(DailyCoachHabitPlan)
                .where(
                    DailyCoachHabitPlan.user_id == int(user_id),
                    DailyCoachHabitPlan.plan_date == today,
                )
                .order_by(desc(DailyCoachHabitPlan.id))
            )
            .scalars()
                .first()
        )
        created_today = existing is None
        existing_payload = (
            existing.context_payload
            if existing and isinstance(getattr(existing, "context_payload", None), dict)
            else {}
        )
        carryover = existing or _latest_prior_daily_habit_plan(user_id, today)
        seed_payload = carryover.context_payload if carryover and isinstance(getattr(carryover, "context_payload", None), dict) else {}
        context = _build_generation_context(user_id, selected_concept_key=None)
        hash_value = _context_hash(context)
        available_concepts: list[dict[str, Any]] = []
        option_sets = _habit_option_sets_from_state(
            seed_payload,
            available_concepts=available_concepts,
            legacy_habits=(getattr(carryover, "habits", None) if carryover is not None else None),
            default_selected_concept=None,
        )
        selected_ids_by_concept = _selected_ids_by_concept(
            seed_payload,
            row=carryover,
            available_concepts=available_concepts,
            option_sets=option_sets,
        )
        selected_habits = _selected_habits_from_option_sets(option_sets, selected_ids_by_concept)
        plan_scope_key = _DAY_PLAN_SCOPE_KEY
        existing_options_for_concept = option_sets.get(plan_scope_key, [])
        if (
            existing
            and not force
            and _habit_plan_version(existing_payload) >= _CURRENT_HABIT_PLAN_VERSION
            and str(getattr(existing, "context_hash", "") or "").strip() == hash_value
            and existing_options_for_concept
            and _has_complete_day_plan_items(existing_options_for_concept)
        ):
            ask_suggestions = _normalized_ask_suggestions(existing_payload.get("ask_suggestions") or [])
            if not ask_suggestions:
                ask_suggestions = _fallback_ask_suggestions({**context, "selected_habits": selected_habits})
            existing.context_payload = {
                **context,
                "habit_plan_version": _CURRENT_HABIT_PLAN_VERSION,
                "habit_option_sets": option_sets,
                "selected_option_ids_by_concept": selected_ids_by_concept,
                "ask_suggestions": ask_suggestions,
            }
            existing.habits = selected_habits
            existing.context_hash = hash_value
            s.add(existing)
            s.commit()
            s.refresh(existing)
            return _serialize_plan(
                existing,
                default_habits_view="selected_habits" if selected_habits else "suggestions",
            )

        generated = (_generate_plan_from_llm(user_id, context) if allow_llm else None) or _fallback_plan(context)
        generated_items = [
            item
            for item in (
                _normalize_habit_plan_item(raw_item, default_concept=None)
                for raw_item in (generated.get("habits") or [])
            )
            if item
        ]
        generated_items = _items_with_day_moments(generated_items)
        if generated_items:
            existing_options = option_sets.get(plan_scope_key, [])
            option_sets[plan_scope_key] = _merge_concept_option_set(
                existing_items=existing_options,
                selected_items=selected_habits,
                generated_items=generated_items,
                force=bool(force),
            )
        current_option_set = option_sets.get(plan_scope_key, [])
        if not _has_complete_day_plan_items(current_option_set):
            fallback_items = [
                item
                for item in (
                    _normalize_habit_plan_item(raw_item, default_concept=None)
                    for raw_item in ((_fallback_plan(context) or {}).get("habits") or [])
                )
                if item
            ]
            fallback_items = _items_with_day_moments(fallback_items)
            if fallback_items:
                option_sets[plan_scope_key] = _merge_concept_option_set(
                    existing_items=current_option_set,
                    selected_items=selected_habits,
                    generated_items=fallback_items,
                    force=True,
                )
        row = existing or DailyCoachHabitPlan(user_id=int(user_id), plan_date=today)
        row.pillar_key = str((context.get("selected_pillar") or {}).get("pillar_key") or "").strip() or None
        row.pillar_label = str((context.get("selected_pillar") or {}).get("label") or "").strip() or None
        row.title = str(generated.get("title") or "").strip() or None
        row.summary = str(generated.get("summary") or "").strip() or None
        row.habits = selected_habits
        row.source = str(generated.get("source") or "fallback").strip() or "fallback"
        row.context_hash = hash_value
        ask_suggestions = _fallback_ask_suggestions({**context, "selected_habits": selected_habits})
        row.context_payload = {
            **context,
            "habit_plan_version": _CURRENT_HABIT_PLAN_VERSION,
            "habit_option_sets": option_sets,
            "selected_option_ids_by_concept": selected_ids_by_concept,
            "ask_suggestions": ask_suggestions,
        }
        row.generated_at = datetime.utcnow().replace(microsecond=0)
        s.add(row)
        s.commit()
        s.refresh(row)
        return _serialize_plan(
            row,
            default_habits_view=(
                "suggestions"
                if created_today
                else ("selected_habits" if selected_habits else "suggestions")
            ),
        )


def update_daily_habit_plan_selection(
    user_id: int,
    *,
    concept_key: str | None,
    selected_option_ids: list[Any],
) -> dict[str, Any]:
    get_or_generate_daily_habit_plan(user_id, force=False, concept_key=concept_key)
    today = tracker_today()
    with SessionLocal() as s:
        row = (
            s.execute(
                select(DailyCoachHabitPlan)
                .where(
                    DailyCoachHabitPlan.user_id == int(user_id),
                    DailyCoachHabitPlan.plan_date == today,
                )
                .order_by(desc(DailyCoachHabitPlan.id))
            )
            .scalars()
            .first()
        )
        if row is None:
            raise ValueError("No daily habit plan is available yet.")
        payload = row.context_payload if isinstance(getattr(row, "context_payload", None), dict) else {}
        available_concepts: list[dict[str, Any]] = []
        selected_concept_key = _DAY_PLAN_SCOPE_KEY
        option_sets = _habit_option_sets_from_state(
            payload,
            available_concepts=available_concepts,
            legacy_habits=getattr(row, "habits", None) if isinstance(getattr(row, "habits", None), list) else None,
            default_selected_concept=None,
        )
        options = option_sets.get(selected_concept_key, [])
        option_lookup = {str(item.get("id") or "").strip(): item for item in options}
        requested_ids = [
            str(raw_id or "").strip()
            for raw_id in (selected_option_ids or [])
            if str(raw_id or "").strip()
        ]
        selected_ids_by_concept = _selected_ids_by_concept(
            payload,
            row=row,
            available_concepts=available_concepts,
            option_sets=option_sets,
        )
        if requested_ids:
            selected_ids_by_concept[selected_concept_key] = [item_id for item_id in requested_ids if item_id in option_lookup]
        else:
            selected_ids_by_concept.pop(selected_concept_key, None)
        row.habits = _selected_habits_from_option_sets(option_sets, selected_ids_by_concept)
        ask_suggestions = _fallback_ask_suggestions({**payload, "selected_habits": row.habits})
        row.context_payload = {
            **payload,
            "habit_plan_version": _CURRENT_HABIT_PLAN_VERSION,
            "habit_option_sets": option_sets,
            "selected_option_ids_by_concept": selected_ids_by_concept,
            "ask_suggestions": ask_suggestions,
        }
        row.updated_at = datetime.utcnow().replace(microsecond=0)
        s.add(row)
        s.commit()
        s.refresh(row)
        return _serialize_plan(
            row,
            default_habits_view="selected_habits" if getattr(row, "habits", None) else "suggestions",
        )
