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
from .pillar_tracker import get_pillar_tracker_detail, get_pillar_tracker_summary, tracker_today
from .prompts import build_prompt, ensure_builtin_prompt_templates, run_llm_prompt

_DAILY_HABITS_SCHEMA_READY = False
_PILLAR_ORDER = ("nutrition", "training", "resilience", "recovery")
_CURRENT_HABIT_PLAN_VERSION = 4


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
) -> str:
    payload = json.dumps(
        {
            "title": str(title or "").strip(),
            "detail": str(detail or "").strip(),
            "concept_key": str(concept_key or "").strip().lower() or None,
            "pillar_key": str(pillar_key or "").strip().lower() or None,
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
    today: date,
    *,
    pillar_key: str,
    pillar_label: str,
) -> list[dict[str, Any]]:
    today_iso = today.isoformat()
    yesterday_iso = (today - timedelta(days=1)).isoformat()
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
            }
        )
    return focus_rows


def _focus_signal_priority(signal: str) -> int:
    token = str(signal or "").strip().lower()
    if token == "missed_today":
        return 0
    if token == "missed_yesterday":
        return 1
    if token == "needs_support":
        return 2
    if token == "not_logged_today":
        return 3
    return 4


def _select_focus_concepts(
    user_id: int,
    summary: dict[str, Any],
    *,
    today: date,
    preferred_concept_key: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    focus_rows: list[dict[str, Any]] = []
    weakest = _select_weakest_pillar(summary)
    weakest_key = str(weakest.get("pillar_key") or "").strip().lower()
    for pillar_row in summary.get("pillars") or []:
        pillar_key = str(pillar_row.get("pillar_key") or "").strip().lower()
        if not pillar_key:
            continue
        pillar_label = str(pillar_row.get("label") or "").strip() or pillar_key.title()
        detail = get_pillar_tracker_detail(user_id, pillar_key, anchor=today)
        focus_rows.extend(
            _recent_concept_focuses(
                detail,
                today,
                pillar_key=pillar_key,
                pillar_label=pillar_label,
            )
        )
    focus_rows.sort(
        key=lambda item: (
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
            (item for item in visible if str(item.get("pillar_key") or "").strip().lower() == weakest_key),
            None,
        ) or visible[0]
    return visible, selected


def _build_generation_context(user_id: int, *, selected_concept_key: str | None = None) -> dict[str, Any]:
    today = tracker_today()
    summary = get_pillar_tracker_summary(user_id, anchor=today)
    weakest = _select_weakest_pillar(summary)
    focus_concepts, selected_focus = _select_focus_concepts(
        user_id,
        summary,
        today=today,
        preferred_concept_key=selected_concept_key,
    )
    selected_pillar_key = str(
        (selected_focus or {}).get("pillar_key") or weakest.get("pillar_key") or "nutrition"
    ).strip().lower()
    selected_pillar_label = str(
        (selected_focus or {}).get("pillar_label") or weakest.get("label") or selected_pillar_key.title()
    ).strip()
    okr_context = _load_pillar_okr_context(
        user_id,
        selected_pillar_key,
        concept_key=(selected_focus or {}).get("concept_key"),
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
        "weakest_pillar": {
            "pillar_key": str(weakest.get("pillar_key") or "nutrition").strip().lower(),
            "label": str(weakest.get("label") or "").strip() or str(weakest.get("pillar_key") or "nutrition").strip().title(),
            "score": _safe_int(weakest.get("score")),
            "tracker_score": _safe_int(weakest.get("tracker_score")),
            "baseline_score": _safe_int(weakest.get("baseline_score")),
        },
        "selected_pillar": {
            "pillar_key": selected_pillar_key,
            "label": selected_pillar_label or selected_pillar_key.title(),
        },
        "pillar_scores": pillars_payload,
        "focus_concepts": focus_concepts,
        "selected_focus_concept": selected_focus,
        "okr_context": okr_context,
    }


def build_daily_tracker_generation_context(
    user_id: int,
    *,
    selected_concept_key: str | None = None,
) -> dict[str, Any]:
    return _build_generation_context(user_id, selected_concept_key=selected_concept_key)


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
    item_id = str((raw_dict.get("id") if isinstance(raw_dict, dict) else None) or "").strip()
    if not item_id:
        item_id = _habit_item_id(
            title=normalized["title"],
            detail=normalized["detail"],
            concept_key=concept_key,
            pillar_key=pillar_key,
        )
    return {
        "id": item_id,
        "title": normalized["title"],
        "detail": normalized["detail"],
        "concept_key": concept_key,
        "concept_label": concept_label,
        "pillar_key": pillar_key,
        "pillar_label": pillar_label,
    }


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
            concept_key = _normalize_concept_token(raw_key)
            if not concept_key or not isinstance(raw_items, list):
                continue
            default_concept = concept_lookup.get(concept_key) or default_selected_concept
            items = [
                item
                for item in (
                    _normalize_habit_plan_item(raw_item, default_concept=default_concept)
                    for raw_item in raw_items
                )
                if item
            ]
            items = _items_for_concept(items, concept_key=concept_key)
            if items:
                option_sets[concept_key] = _dedupe_habit_plan_items(items)
    if option_sets:
        return option_sets
    selected_key = _normalize_concept_token((default_selected_concept or {}).get("concept_key"))
    if not selected_key or not isinstance(legacy_habits, list):
        return {}
    legacy_items = [
        item
        for item in (
            _normalize_habit_plan_item(raw_item, default_concept=default_selected_concept)
            for raw_item in legacy_habits
        )
        if item
    ]
    legacy_items = _items_for_concept(legacy_items, concept_key=selected_key)
    if legacy_items:
        option_sets[selected_key] = _dedupe_habit_plan_items(legacy_items)
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
    return _dedupe_habit_plan_items(items)


def _normalize_selected_ids_map(payload: dict[str, Any]) -> dict[str, list[str]]:
    raw_map = payload.get("selected_option_ids_by_concept") if isinstance(payload, dict) else None
    if not isinstance(raw_map, dict):
        return {}
    normalized: dict[str, list[str]] = {}
    for raw_key, raw_ids in raw_map.items():
        concept_key = _normalize_concept_token(raw_key)
        if not concept_key or not isinstance(raw_ids, list):
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
            normalized[concept_key] = ids
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
        concept_key = _normalize_concept_token(item.get("concept_key"))
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
    return _dedupe_habit_plan_items(items)


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
    selected_concept = context.get("selected_focus_concept") or {}
    selected_pillar = context.get("selected_pillar") or {}
    pillar_key = str(
        selected_concept.get("pillar_key") or selected_pillar.get("pillar_key") or "nutrition"
    ).strip().lower()
    pillar_label = str(
        selected_concept.get("pillar_label") or selected_pillar.get("label") or pillar_key.title()
    ).strip() or pillar_key.title()
    concept_label = str(selected_concept.get("label") or "Habit focus").strip() or "Habit focus"
    habits: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for step in (context.get("okr_context") or {}).get("habit_steps") or []:
        text = str(step or "").strip()
        if not text:
            continue
        title = text[:90]
        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        habits.append({"title": title, "detail": "Keep this practical and doable today."})
        if len(habits) >= 2:
            break
    for item in _fallback_habit_options_for_concept(selected_concept, pillar_key):
        key = str(item.get("title") or "").strip().lower()
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        habits.append(item)
        if len(habits) >= 5:
            break
    if not habits:
        habits = [
            {
                "title": f"Take one {pillar_label.lower()} step today",
                "detail": "Choose a small action you can complete before the day ends.",
            }
        ]
    return {
        "title": f"{concept_label} habit ideas",
        "summary": f"Choose one to three practical steps to support your {concept_label.lower()} today.",
        "habits": habits[:5],
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

    focus_concepts = [item for item in (context.get("focus_concepts") or []) if isinstance(item, dict)]
    selected_habits = [item for item in (context.get("selected_habits") or []) if isinstance(item, dict)]
    signals = [str(item.get("signal") or "").strip().lower() for item in focus_concepts]

    if "missed_today" in signals or "missed_yesterday" in signals:
        push("Get back on track", "What is the best way for me to get back on track today?")
    if "not_logged_today" in signals:
        push("Log it simply", "What's the simplest way for me to track properly today?")
    if "needs_support" in signals:
        push("Why is this slipping", "Why does this keep slipping for me and what should I change?")
    if selected_habits:
        push("Stick to my plan", "How can I stay consistent with the habits I've chosen today?")

    push("Best next step", "Based on my tracking, what's the most useful next step for me today?")
    push("Recover today", "What would help me recover well today without overcomplicating it?")
    push("Build consistency", "How do I make this feel easier to repeat tomorrow as well?")
    return suggestions[:4]


def _generate_plan_from_llm(user_id: int, context: dict[str, Any]) -> dict[str, Any] | None:
    selected_pillar = context.get("selected_pillar") or {}
    selected_concept = context.get("selected_focus_concept") or {}
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
        focus_concepts=context.get("focus_concepts") or [],
        selected_focus_concept=selected_concept,
        selected_pillar=selected_pillar,
        okr_context=context.get("okr_context") or {},
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
            "concept_key": str(selected_concept.get("concept_key") or "").strip().lower(),
            "plan_date": _today_iso(),
        },
        prompt_blocks=assembly.blocks,
        block_order=assembly.block_order,
    )
    parsed = _extract_json_object(raw)
    if not parsed:
        return None
    habits = [
        item
        for item in (_normalize_habit_item(row) for row in (parsed.get("habits") or []))
        if item
    ][:5]
    if len(habits) < 3:
        return None
    concept_label = str(selected_concept.get("label") or "").strip() or "habit focus"
    title = str(parsed.get("title") or "").strip() or f"{concept_label} habit ideas"
    summary = str(parsed.get("summary") or "").strip() or f"Choose one to three practical steps to support your {concept_label.lower()} today."
    return {
        "title": title[:200],
        "summary": summary[:500],
        "habits": habits,
        "source": "llm",
    }


def _generate_ask_suggestions_from_llm(
    user_id: int,
    context: dict[str, Any],
    selected_habits: list[dict[str, Any]],
) -> list[dict[str, str]] | None:
    selected_pillar = context.get("selected_pillar") or {}
    selected_concept = context.get("selected_focus_concept") or {}
    user_name = str(context.get("user_name") or "User").strip() or "User"
    ensure_builtin_prompt_templates(["daily_ask_suggestions"])
    assembly = build_prompt(
        "daily_ask_suggestions",
        user_id=user_id,
        coach_name="HealthSense",
        user_name=user_name,
        locale="UK",
        timeframe="today",
        plan_date=context.get("plan_date"),
        scores=context.get("pillar_scores") or [],
        weakest_pillar=context.get("weakest_pillar") or {},
        focus_concepts=context.get("focus_concepts") or [],
        selected_focus_concept=selected_concept,
        selected_pillar=selected_pillar,
        okr_context=context.get("okr_context") or {},
        selected_habits=selected_habits,
    )
    raw = run_llm_prompt(
        assembly.text,
        user_id=user_id,
        touchpoint="daily_ask_suggestions",
        prompt_variant=assembly.variant,
        task_label=assembly.task_label,
        context_meta={
            "page": "coach_home",
            "pillar_key": str(selected_pillar.get("pillar_key") or "").strip().lower(),
            "concept_key": str(selected_concept.get("concept_key") or "").strip().lower(),
            "plan_date": _today_iso(),
        },
        prompt_blocks=assembly.blocks,
        block_order=assembly.block_order,
    )
    parsed = _extract_json_object(raw)
    if not parsed:
        return None
    suggestions = [
        item
        for item in (_normalize_ask_suggestion(row) for row in (parsed.get("suggestions") or []))
        if item
    ]
    if len(suggestions) < 2:
        return None
    return suggestions[:4]


def _serialize_plan(
    row: DailyCoachHabitPlan,
    *,
    default_habits_view: str | None = None,
) -> dict[str, Any]:
    payload = row.context_payload if isinstance(getattr(row, "context_payload", None), dict) else {}
    available_concepts = [item for item in (payload.get("focus_concepts") or []) if isinstance(item, dict)]
    fallback_concept = payload.get("selected_focus_concept") if isinstance(payload.get("selected_focus_concept"), dict) else None
    selected_concept = _resolve_selected_concept(
        payload,
        available_concepts=available_concepts,
        fallback_concept=fallback_concept,
    )
    option_sets = _habit_option_sets_from_state(
        payload,
        available_concepts=available_concepts,
        legacy_habits=getattr(row, "habits", None) if isinstance(getattr(row, "habits", None), list) else None,
        default_selected_concept=selected_concept,
    )
    selected_ids_by_concept = _selected_ids_by_concept(
        payload,
        row=row,
        available_concepts=available_concepts,
        option_sets=option_sets,
    )
    selected_habits = _selected_habits_from_option_sets(option_sets, selected_ids_by_concept)
    ask_suggestions = _normalized_ask_suggestions(payload.get("ask_suggestions") or [])
    selected_ids = {str(item.get("id") or "").strip() for item in selected_habits}
    selected_concept_key = _normalize_concept_token((selected_concept or {}).get("concept_key"))
    current_options = []
    for item in option_sets.get(selected_concept_key or "", []):
        current_options.append({**item, "selected": str(item.get("id") or "").strip() in selected_ids})
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
        "habits": selected_habits,
        "options": current_options,
        "ask_suggestions": ask_suggestions[:4],
        "available_concepts": concepts_payload,
        "selected_concept_key": selected_concept_key,
        "selected_concept_label": str((selected_concept or {}).get("label") or "").strip() or None,
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
) -> dict[str, Any]:
    ensure_daily_habit_plan_schema()
    ensure_builtin_prompt_templates(["daily_habit_plan", "daily_ask_suggestions"])
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
        preferred_concept_key = _normalize_concept_token(concept_key) or _normalize_concept_token(seed_payload.get("selected_concept_key"))
        context = _build_generation_context(user_id, selected_concept_key=preferred_concept_key)
        hash_value = _context_hash(context)
        selected_concept = context.get("selected_focus_concept") or {}
        available_concepts = [item for item in (context.get("focus_concepts") or []) if isinstance(item, dict)]
        option_sets = _habit_option_sets_from_state(
            seed_payload,
            available_concepts=available_concepts,
            legacy_habits=(getattr(carryover, "habits", None) if carryover is not None else None),
            default_selected_concept=selected_concept,
        )
        selected_ids_by_concept = _selected_ids_by_concept(
            seed_payload,
            row=carryover,
            available_concepts=available_concepts,
            option_sets=option_sets,
        )
        selected_habits = _selected_habits_from_option_sets(option_sets, selected_ids_by_concept)
        selected_concept_key = _normalize_concept_token(selected_concept.get("concept_key"))
        existing_options_for_concept = option_sets.get(selected_concept_key or "", [])
        if (
            existing
            and not force
            and _habit_plan_version(existing_payload) >= _CURRENT_HABIT_PLAN_VERSION
            and selected_concept_key
            and existing_options_for_concept
        ):
            ask_suggestions = _normalized_ask_suggestions(existing_payload.get("ask_suggestions") or [])
            if not ask_suggestions:
                ask_suggestions = _generate_ask_suggestions_from_llm(user_id, context, selected_habits) or _fallback_ask_suggestions(
                    {**context, "selected_habits": selected_habits}
                )
            existing.context_payload = {
                **context,
                "habit_plan_version": _CURRENT_HABIT_PLAN_VERSION,
                "selected_concept_key": selected_concept_key,
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

        generated = _generate_plan_from_llm(user_id, context) or _fallback_plan(context)
        generated_items = [
            item
            for item in (
                _normalize_habit_plan_item(raw_item, default_concept=selected_concept)
                for raw_item in (generated.get("habits") or [])
            )
            if item
        ]
        generated_items = _items_for_concept(generated_items, concept_key=selected_concept_key)
        if selected_concept_key and generated_items:
            existing_options = option_sets.get(selected_concept_key, [])
            preserved_selected_for_concept = [
                item for item in selected_habits if _normalize_concept_token(item.get("concept_key")) == selected_concept_key
            ]
            option_sets[selected_concept_key] = _merge_concept_option_set(
                existing_items=existing_options,
                selected_items=preserved_selected_for_concept,
                generated_items=generated_items,
                force=bool(force),
            )
        row = existing or DailyCoachHabitPlan(user_id=int(user_id), plan_date=today)
        row.pillar_key = str((context.get("selected_pillar") or {}).get("pillar_key") or "").strip() or None
        row.pillar_label = str((context.get("selected_pillar") or {}).get("label") or "").strip() or None
        row.title = str(generated.get("title") or "").strip() or None
        row.summary = str(generated.get("summary") or "").strip() or None
        row.habits = selected_habits
        row.source = str(generated.get("source") or "fallback").strip() or "fallback"
        row.context_hash = hash_value
        ask_suggestions = _generate_ask_suggestions_from_llm(user_id, context, selected_habits) or _fallback_ask_suggestions(
            {**context, "selected_habits": selected_habits}
        )
        row.context_payload = {
            **context,
            "habit_plan_version": _CURRENT_HABIT_PLAN_VERSION,
            "selected_concept_key": selected_concept_key,
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
        available_concepts = [item for item in (payload.get("focus_concepts") or []) if isinstance(item, dict)]
        fallback_concept = payload.get("selected_focus_concept") if isinstance(payload.get("selected_focus_concept"), dict) else None
        selected_concept = _resolve_selected_concept(
            {"selected_concept_key": concept_key or payload.get("selected_concept_key")},
            available_concepts=available_concepts,
            fallback_concept=fallback_concept,
        )
        selected_concept_key = _normalize_concept_token((selected_concept or {}).get("concept_key"))
        if not selected_concept_key:
            raise ValueError("A habit concept must be selected.")
        option_sets = _habit_option_sets_from_state(
            payload,
            available_concepts=available_concepts,
            legacy_habits=getattr(row, "habits", None) if isinstance(getattr(row, "habits", None), list) else None,
            default_selected_concept=selected_concept,
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
        ask_context = {
            **payload,
            "selected_focus_concept": selected_concept,
            "selected_concept_key": selected_concept_key,
        }
        ask_suggestions = _generate_ask_suggestions_from_llm(
            user_id,
            ask_context,
            row.habits,
        ) or _fallback_ask_suggestions({**ask_context, "selected_habits": row.habits})
        row.context_payload = {
            **payload,
            "habit_plan_version": _CURRENT_HABIT_PLAN_VERSION,
            "selected_concept_key": selected_concept_key,
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
