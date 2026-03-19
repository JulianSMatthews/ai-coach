from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, desc, or_, select

from .db import SessionLocal
from .models import ContentLibraryItem
from .okr import _normalize_concept_key
from .pillar_tracker import get_pillar_tracker_detail, get_pillar_tracker_summary, tracker_today

_PILLAR_ORDER = ("nutrition", "training", "resilience", "recovery")
_INTRO_SOURCE_TYPES = ("app_intro", "assessment_intro")


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


def _load_library_rows(pillar_key: str) -> list[ContentLibraryItem]:
    with SessionLocal() as s:
        return (
            s.execute(
                select(ContentLibraryItem)
                .where(
                    ContentLibraryItem.status == "published",
                    ContentLibraryItem.pillar_key == str(pillar_key or "").strip().lower(),
                    ContentLibraryItem.podcast_url.isnot(None),
                    ContentLibraryItem.podcast_url != "",
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


def _normalized_library_concept(row: ContentLibraryItem) -> str | None:
    token = _normalize_concept_key(getattr(row, "concept_code", None))
    return token or None


def _select_library_item(
    rows: list[ContentLibraryItem],
    *,
    concept_key: str | None,
) -> tuple[ContentLibraryItem | None, str | None]:
    normalized_concept = _normalize_concept_key(concept_key) or None
    if normalized_concept:
        exact_rows = [row for row in rows if _normalized_library_concept(row) == normalized_concept]
        if exact_rows:
            return exact_rows[0], "concept"
    pillar_rows = [row for row in rows if not _normalized_library_concept(row)]
    if pillar_rows:
        return pillar_rows[0], "pillar"
    if rows:
        return rows[0], "pillar"
    return None, None


def get_coach_insight(user_id: int, *, anchor: date | None = None) -> dict[str, Any]:
    resolved_anchor = anchor or tracker_today()
    focus_concept, summary = _select_focus_concept(user_id, resolved_anchor)
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
                "created_at": getattr(selected_row, "created_at", None),
            }
            if selected_row is not None
            else None
        ),
    }
