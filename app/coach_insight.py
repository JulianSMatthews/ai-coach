from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, or_, select

from .db import SessionLocal
from .daily_habits import build_daily_tracker_generation_context_snapshot
from .models import ContentLibraryItem, UserPreference
from .okr import _normalize_concept_key
from .pillar_tracker import get_pillar_tracker_detail, get_pillar_tracker_summary, tracker_today

_PILLAR_ORDER = ("nutrition", "training", "resilience", "recovery")
_INTRO_SOURCE_TYPES = ("app_intro", "assessment_intro")
_INSIGHT_CACHE_KEY = "coach_home_insight_cache"


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


def _select_weakest_pillar(summary: dict[str, Any]) -> dict[str, Any]:
    pillars = list(summary.get("pillars") or [])
    if not pillars:
        return {"pillar_key": "nutrition", "label": "Nutrition", "score": None}

    def _sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
        score = _safe_int(row.get("score"))
        return (
            score if score is not None else 999,
            _pillar_rank(str(row.get("pillar_key") or "")),
            str(row.get("label") or ""),
        )

    return sorted(pillars, key=_sort_key)[0]


def _concept_candidate(
    pillar_row: dict[str, Any],
    concept_row: dict[str, Any],
    *,
    anchor: date,
) -> dict[str, Any]:
    week_by_date = {
        str((day or {}).get("date") or "").strip(): day
        for day in (concept_row.get("week") or [])
        if isinstance(day, dict)
    }
    today_iso = anchor.isoformat()
    yesterday_iso = (anchor - timedelta(days=1)).isoformat()
    today_row = week_by_date.get(today_iso) or {}
    yesterday_row = week_by_date.get(yesterday_iso) or {}
    recent_rows = [today_row, yesterday_row]
    recent_scores = [
        _safe_int((day or {}).get("score"))
        for day in week_by_date.values()
        if _safe_int((day or {}).get("score")) is not None
    ]
    recent_misses = sum(1 for row in recent_rows if row.get("target_met") is False)
    recent_missing = sum(1 for row in recent_rows if row.get("target_met") is None)
    current_score = _safe_int(concept_row.get("score"))
    recent_average = (
        int(round(sum(recent_scores) / max(1, len(recent_scores))))
        if recent_scores
        else None
    )
    return {
        "pillar_key": str(pillar_row.get("pillar_key") or "").strip().lower(),
        "pillar_label": str(pillar_row.get("label") or "").strip(),
        "pillar_score": _safe_int(pillar_row.get("score")),
        "concept_key": str(concept_row.get("concept_key") or "").strip().lower(),
        "concept_label": str(concept_row.get("label") or "").strip(),
        "current_score": current_score,
        "recent_average": recent_average,
        "recent_misses": recent_misses,
        "recent_missing": recent_missing,
        "has_signal": bool(recent_misses or current_score is not None or recent_average is not None),
    }


def _select_focus_concept(user_id: int, anchor: date) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    summary = get_pillar_tracker_summary(user_id, anchor=anchor)
    candidates: list[dict[str, Any]] = []
    for pillar_row in summary.get("pillars") or []:
        pillar_key = str(pillar_row.get("pillar_key") or "").strip().lower()
        if not pillar_key:
            continue
        detail = get_pillar_tracker_detail(user_id, pillar_key, anchor=anchor)
        for concept_row in detail.get("concepts") or []:
            candidates.append(_concept_candidate(pillar_row, concept_row, anchor=anchor))
    signal_rows = [row for row in candidates if row.get("has_signal")]
    if not signal_rows:
        return None, summary

    def _sort_key(row: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
        current_score = _safe_int(row.get("current_score"))
        recent_average = _safe_int(row.get("recent_average"))
        pillar_score = _safe_int(row.get("pillar_score"))
        return (
            -int(row.get("recent_misses") or 0),
            current_score if current_score is not None else 999,
            recent_average if recent_average is not None else 999,
            pillar_score if pillar_score is not None else 999,
            _pillar_rank(str(row.get("pillar_key") or "")),
            str(row.get("concept_label") or ""),
        )

    return sorted(signal_rows, key=_sort_key)[0], summary


def _select_focus_concepts(
    user_id: int,
    anchor: date,
    *,
    preferred_concept_key: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
    summary = get_pillar_tracker_summary(user_id, anchor=anchor)
    candidates: list[dict[str, Any]] = []
    for pillar_row in summary.get("pillars") or []:
        pillar_key = str(pillar_row.get("pillar_key") or "").strip().lower()
        if not pillar_key:
            continue
        detail = get_pillar_tracker_detail(user_id, pillar_key, anchor=anchor)
        for concept_row in detail.get("concepts") or []:
            candidates.append(_concept_candidate(pillar_row, concept_row, anchor=anchor))
    signal_rows = [row for row in candidates if row.get("has_signal")]
    if not signal_rows:
        return [], None, summary

    def _sort_key(row: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
        current_score = _safe_int(row.get("current_score"))
        recent_average = _safe_int(row.get("recent_average"))
        pillar_score = _safe_int(row.get("pillar_score"))
        return (
            -int(row.get("recent_misses") or 0),
            current_score if current_score is not None else 999,
            recent_average if recent_average is not None else 999,
            pillar_score if pillar_score is not None else 999,
            _pillar_rank(str(row.get("pillar_key") or "")),
            str(row.get("concept_label") or ""),
        )

    ranked_rows = sorted(signal_rows, key=_sort_key)
    preferred = _normalize_concept_key(preferred_concept_key) or None
    selected = next((row for row in ranked_rows if row.get("concept_key") == preferred), None)
    visible = ranked_rows[:8]
    if selected and not any(str(item.get("concept_key") or "").strip().lower() == selected.get("concept_key") for item in visible):
        visible = [selected, *visible[:7]]
    if selected is None:
        selected = visible[0] if visible else None
    return visible, selected, summary


def _load_library_rows(pillar_key: str) -> list[ContentLibraryItem]:
    with SessionLocal() as s:
        return (
            s.execute(
                select(ContentLibraryItem)
                .where(
                    ContentLibraryItem.status == "published",
                    ContentLibraryItem.pillar_key == str(pillar_key or "").strip().lower(),
                    or_(
                        ContentLibraryItem.source_type.is_(None),
                        and_(
                            ContentLibraryItem.source_type != _INTRO_SOURCE_TYPES[0],
                            ContentLibraryItem.source_type != _INTRO_SOURCE_TYPES[1],
                        ),
                    ),
                )
                .order_by(
                    desc(ContentLibraryItem.published_at),
                    desc(ContentLibraryItem.updated_at),
                    desc(ContentLibraryItem.created_at),
                )
            )
            .scalars()
            .all()
        )


def _library_avatar_payload(row: ContentLibraryItem) -> dict[str, Any] | None:
    tags = row.tags if isinstance(getattr(row, "tags", None), dict) else {}
    if not isinstance(tags, dict):
        return None
    raw_url = str(tags.get("library_avatar_url") or "").strip()
    raw_title = str(tags.get("library_avatar_title") or "").strip()
    raw_script = str(tags.get("library_avatar_script") or "").strip()
    raw_poster = str(tags.get("library_avatar_poster_url") or "").strip()
    raw_character = str(tags.get("library_avatar_character") or "").strip()
    raw_style = str(tags.get("library_avatar_style") or "").strip()
    raw_voice = str(tags.get("library_avatar_voice") or "").strip()
    raw_status = str(tags.get("library_avatar_status") or "").strip()
    raw_job_id = str(tags.get("library_avatar_job_id") or "").strip()
    raw_error = str(tags.get("library_avatar_error") or "").strip()
    raw_generated_at = str(tags.get("library_avatar_generated_at") or "").strip()
    raw_source = str(tags.get("library_avatar_source") or "").strip()
    raw_summary_url = str(tags.get("library_avatar_summary_url") or "").strip()
    if not any(
        [
            raw_url,
            raw_title,
            raw_script,
            raw_poster,
            raw_status,
            raw_job_id,
            raw_error,
            raw_generated_at,
            raw_source,
            raw_summary_url,
        ]
    ):
        return None
    return {
        "url": raw_url or None,
        "title": raw_title or str(getattr(row, "title", "") or "").strip() or None,
        "script": raw_script or str(getattr(row, "body", "") or "").strip() or None,
        "poster_url": raw_poster or None,
        "character": raw_character or None,
        "style": raw_style or None,
        "voice": raw_voice or None,
        "status": raw_status or None,
        "job_id": raw_job_id or None,
        "error": raw_error or None,
        "generated_at": raw_generated_at or None,
        "source": raw_source or None,
        "summary_url": raw_summary_url or None,
    }


def _normalized_library_concept(row: ContentLibraryItem) -> str | None:
    token = _normalize_concept_key(getattr(row, "concept_code", None))
    return token or None


def _select_library_item(
    rows: list[ContentLibraryItem],
    *,
    concept_key: str | None,
) -> tuple[ContentLibraryItem | None, str | None]:
    def _row_priority(row: ContentLibraryItem) -> tuple[int]:
        avatar = _library_avatar_payload(row)
        has_avatar = bool(str((avatar or {}).get("url") or "").strip())
        has_audio = bool(str(getattr(row, "podcast_url", "") or "").strip())
        has_body = bool(str(getattr(row, "body", "") or "").strip())
        if has_avatar:
            return (0,)
        if has_audio:
            return (1,)
        if has_body:
            return (2,)
        return (3,)

    normalized_concept = _normalize_concept_key(concept_key) or None
    if normalized_concept:
        exact_rows = sorted(
            [row for row in rows if _normalized_library_concept(row) == normalized_concept],
            key=_row_priority,
        )
        if exact_rows:
            return exact_rows[0], "concept"
    pillar_rows = sorted(
        [row for row in rows if not _normalized_library_concept(row)],
        key=_row_priority,
    )
    if pillar_rows:
        return pillar_rows[0], "pillar"
    ranked_rows = sorted(rows, key=_row_priority)
    if ranked_rows:
        return ranked_rows[0], "pillar"
    return None, None


def get_coach_insight(
    user_id: int,
    *,
    anchor: date | None = None,
    concept_key: str | None = None,
) -> dict[str, Any]:
    if anchor is None and not str(concept_key or "").strip():
        snapshot = build_daily_tracker_generation_context_snapshot(int(user_id))
        context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
        selected_pillar = context.get("selected_pillar") if isinstance(context.get("selected_pillar"), dict) else {}
        focus_concept = context.get("selected_focus_concept") if isinstance(context.get("selected_focus_concept"), dict) else {}
        selected_pillar_key = str(selected_pillar.get("pillar_key") or "nutrition").strip().lower() or "nutrition"
        selected_pillar_label = str(selected_pillar.get("label") or selected_pillar_key.title()).strip() or selected_pillar_key.title()
        rows = _load_library_rows(selected_pillar_key)
        selected_row, matched_by = _select_library_item(
            rows,
            concept_key=(focus_concept or {}).get("concept_key"),
        )
        return {
            "user_id": int(user_id),
            "insight_date": str(context.get("tracker_focus_date") or tracker_today().isoformat()).strip() or tracker_today().isoformat(),
            "pillar_key": selected_pillar_key,
            "pillar_label": selected_pillar_label,
            "concept_key": str((focus_concept or {}).get("concept_key") or "").strip() or None,
            "concept_label": str((focus_concept or {}).get("label") or "").strip() or None,
            "available_concepts": [
                {
                    "pillar_key": str(item.get("pillar_key") or "").strip().lower() or None,
                    "pillar_label": str(item.get("pillar_label") or "").strip() or None,
                    "concept_key": str(item.get("concept_key") or "").strip().lower() or None,
                    "label": str(item.get("label") or "").strip() or None,
                    "is_selected": str(item.get("concept_key") or "").strip().lower()
                    == str((focus_concept or {}).get("concept_key") or "").strip().lower(),
                }
                for item in (context.get("focus_concepts") or [])
                if isinstance(item, dict) and str(item.get("concept_key") or "").strip()
            ],
            "matched_by": matched_by,
            "content": (
                {
                    "id": int(getattr(selected_row, "id", 0) or 0),
                    "pillar_key": str(getattr(selected_row, "pillar_key", "") or "").strip() or None,
                    "concept_code": _normalized_library_concept(selected_row),
                    "title": str(getattr(selected_row, "title", "") or "").strip() or None,
                    "body": str(getattr(selected_row, "body", "") or "").strip() or None,
                    "podcast_url": str(getattr(selected_row, "podcast_url", "") or "").strip() or None,
                    "podcast_voice": str(getattr(selected_row, "podcast_voice", "") or "").strip() or None,
                    "avatar": _library_avatar_payload(selected_row),
                    "created_at": getattr(selected_row, "created_at", None),
                }
                if selected_row is not None
                else None
            ),
        }
    resolved_anchor = anchor or tracker_today()
    available_concepts, focus_concept, summary = _select_focus_concepts(
        user_id,
        resolved_anchor,
        preferred_concept_key=concept_key,
    )
    weakest_pillar = _select_weakest_pillar(summary)
    selected_pillar_key = str(
        (focus_concept or {}).get("pillar_key") or weakest_pillar.get("pillar_key") or "nutrition"
    ).strip().lower()
    selected_pillar_label = str(
        (focus_concept or {}).get("pillar_label") or weakest_pillar.get("label") or selected_pillar_key.title()
    ).strip()
    rows = _load_library_rows(selected_pillar_key)
    selected_row, matched_by = _select_library_item(
        rows,
        concept_key=(focus_concept or {}).get("concept_key"),
    )
    return {
        "user_id": int(user_id),
        "insight_date": resolved_anchor.isoformat(),
        "pillar_key": selected_pillar_key,
        "pillar_label": selected_pillar_label,
        "concept_key": str((focus_concept or {}).get("concept_key") or "").strip() or None,
        "concept_label": str((focus_concept or {}).get("concept_label") or "").strip() or None,
        "available_concepts": [
            {
                "pillar_key": str(item.get("pillar_key") or "").strip().lower() or None,
                "pillar_label": str(item.get("pillar_label") or "").strip() or None,
                "concept_key": str(item.get("concept_key") or "").strip().lower() or None,
                "label": str(item.get("concept_label") or "").strip() or None,
                "is_selected": str(item.get("concept_key") or "").strip().lower()
                == str((focus_concept or {}).get("concept_key") or "").strip().lower(),
            }
            for item in available_concepts
            if str(item.get("concept_key") or "").strip()
        ],
        "matched_by": matched_by,
        "content": (
            {
                "id": int(getattr(selected_row, "id", 0) or 0),
                "pillar_key": str(getattr(selected_row, "pillar_key", "") or "").strip() or None,
                "concept_code": _normalized_library_concept(selected_row),
                "title": str(getattr(selected_row, "title", "") or "").strip() or None,
                "body": str(getattr(selected_row, "body", "") or "").strip() or None,
                "podcast_url": str(getattr(selected_row, "podcast_url", "") or "").strip() or None,
                "podcast_voice": str(getattr(selected_row, "podcast_voice", "") or "").strip() or None,
                "avatar": _library_avatar_payload(selected_row),
                "created_at": getattr(selected_row, "created_at", None),
            }
            if selected_row is not None
            else None
        ),
    }


def _get_json_pref(user_id: int, key: str) -> dict[str, Any] | None:
    with SessionLocal() as s:
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == int(user_id), UserPreference.key == str(key))
            .one_or_none()
        )
        if not pref or not pref.value:
            return None
        try:
            data = json.loads(pref.value)
            return data if isinstance(data, dict) else None
        except Exception:
            return None


def _set_json_pref(user_id: int, key: str, payload: dict[str, Any]) -> None:
    with SessionLocal() as s:
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == int(user_id), UserPreference.key == str(key))
            .one_or_none()
        )
        raw = json.dumps(payload, default=str)
        if pref:
            pref.value = raw
        else:
            s.add(UserPreference(user_id=int(user_id), key=str(key), value=raw))
        s.commit()


def _insight_cache_signature(user_id: int) -> tuple[str, str | None]:
    snapshot = build_daily_tracker_generation_context_snapshot(int(user_id))
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    return (
        str(snapshot.get("context_hash") or "").strip(),
        str(context.get("plan_date") or "").strip() or None,
    )


def cache_coach_insight(
    user_id: int,
    result: dict[str, Any],
    *,
    context_hash: str | None = None,
    plan_date: str | None = None,
) -> None:
    if not isinstance(result, dict) or not result:
        return
    resolved_hash = str(context_hash or "").strip()
    resolved_plan_date = str(plan_date or "").strip() or None
    if not resolved_hash or not resolved_plan_date:
        resolved_hash, resolved_plan_date = _insight_cache_signature(int(user_id))
    if not resolved_hash or not resolved_plan_date:
        return
    _set_json_pref(
        int(user_id),
        _INSIGHT_CACHE_KEY,
        {
            "context_hash": resolved_hash,
            "plan_date": resolved_plan_date,
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat(),
            "result": result,
        },
    )


def get_or_generate_cached_coach_insight(
    user_id: int,
    *,
    anchor: date | None = None,
    concept_key: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    if anchor is not None or str(concept_key or "").strip():
        return get_coach_insight(user_id, anchor=anchor, concept_key=concept_key)
    context_hash, plan_date = _insight_cache_signature(int(user_id))
    if not force and context_hash and plan_date:
        cached = _get_json_pref(int(user_id), _INSIGHT_CACHE_KEY) or {}
        if (
            str(cached.get("context_hash") or "").strip() == context_hash
            and str(cached.get("plan_date") or "").strip() == plan_date
            and isinstance(cached.get("result"), dict)
        ):
            return dict(cached.get("result") or {})
    result = get_coach_insight(user_id, anchor=anchor, concept_key=concept_key)
    cache_coach_insight(
        int(user_id),
        result,
        context_hash=context_hash,
        plan_date=plan_date,
    )
    return result
