from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, desc, or_, select

from .db import SessionLocal
from .daily_habits import _guidance_anchor_for_pillar
from .models import ContentLibraryItem, UserPreference
from .okr import _normalize_concept_key
from .pillar_tracker import get_pillar_tracker_detail, get_pillar_tracker_summary, tracker_today
from .pillar_config import ACTIVE_PILLAR_KEYS, pillar_label

_PILLAR_ORDER = ACTIVE_PILLAR_KEYS
_INTRO_SOURCE_TYPES = ("app_intro", "assessment_intro")
_INSIGHT_CACHE_KEY = "coach_home_insight_cache"
_INSIGHT_REVIEW_VERSION = 3
_INSIGHT_WORD_LIMIT = 100


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
        fallback = _PILLAR_ORDER[0] if _PILLAR_ORDER else "reflection"
        return {"pillar_key": fallback, "label": pillar_label(fallback), "score": None}

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
    not_applicable = bool(today_row.get("not_applicable") or (not today_row and concept_row.get("not_applicable")))
    recent_rows = [today_row, yesterday_row]
    recent_scores = [
        _safe_int((day or {}).get("score"))
        for day_date, day in week_by_date.items()
        if day_date <= today_iso
        if not day.get("not_applicable") and _safe_int((day or {}).get("score")) is not None
    ]
    recent_misses = sum(1 for row in recent_rows if not row.get("not_applicable") and row.get("target_met") is False)
    recent_missing = sum(1 for row in recent_rows if not row.get("not_applicable") and row.get("target_met") is None)
    current_score = None if not_applicable else _safe_int(today_row.get("score", concept_row.get("score")))
    recent_average = (
        int(round(sum(recent_scores) / max(1, len(recent_scores))))
        if recent_scores
        else None
    )
    active_row = today_row or concept_row
    target_met = active_row.get("target_met")
    if target_met is None:
        target_met = active_row.get("okr_on_track")
    has_record = any(active_row.get(key) is not None for key in ("value", "value_label", "score", "target_met", "okr_on_track"))
    if not_applicable:
        status = "not_applicable"
    elif not has_record:
        status = "unlogged"
    elif target_met is not None:
        # The user's actual target takes precedence over a generic score band.
        status = "on_track" if target_met is True else "off_track"
    elif current_score is not None:
        status = "on_track" if current_score >= 80 else "off_track"
    else:
        status = "unlogged"
    signal = status
    if status == "off_track":
        signal = (
            "missed_today" if anchor == tracker_today() else "missed_yesterday"
        ) if target_met is False else "needs_support"
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
        "not_applicable": not_applicable,
        "has_signal": not not_applicable and bool(recent_misses or current_score is not None or recent_average is not None),
        "status": status,
        "signal": signal,
        "anchor_date": today_iso,
        "target_label": str(concept_row.get("target_label") or "").strip() or None,
        "latest_value": str(active_row.get("value_label") or "").strip() or None,
    }


def _review_concepts(user_id: int, anchor: date | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    current_day = tracker_today()
    summary = get_pillar_tracker_summary(user_id, anchor=anchor or current_day)
    candidates: list[dict[str, Any]] = []
    for pillar_row in summary.get("pillars") or []:
        pillar_key = str(pillar_row.get("pillar_key") or "").strip().lower()
        if not pillar_key:
            continue
        requested_anchor = anchor or _guidance_anchor_for_pillar(user_id, pillar_key, current_day)
        detail = get_pillar_tracker_detail(user_id, pillar_key, anchor=requested_anchor)
        active_date = str((detail.get("pillar") or {}).get("active_date") or "").strip()
        try:
            resolved_anchor = date.fromisoformat(active_date) if active_date else requested_anchor
        except ValueError:
            resolved_anchor = requested_anchor
        for concept_row in detail.get("concepts") or []:
            candidates.append(_concept_candidate(pillar_row, concept_row, anchor=resolved_anchor))
    return candidates, summary


def _rank_off_track_concepts(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [row for row in candidates if row.get("status") == "off_track"],
        key=lambda row: (
            row.get("current_score") if row.get("current_score") is not None else 999,
            -int(row.get("recent_misses") or 0),
            _pillar_rank(str(row.get("pillar_key") or "")),
            str(row.get("concept_label") or ""),
        ),
    )


def _select_focus_concept(user_id: int, anchor: date) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    _, selected, summary = _select_focus_concepts(user_id, anchor)
    return selected, summary


def _select_focus_concepts(
    user_id: int,
    anchor: date,
    *,
    preferred_concept_key: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, dict[str, Any]]:
    candidates, summary = _review_concepts(user_id, anchor)
    ranked_rows = _rank_off_track_concepts(candidates)
    preferred = _normalize_concept_key(preferred_concept_key) or None
    selected = next((row for row in ranked_rows if row.get("concept_key") == preferred), None)
    if selected is None:
        selected = ranked_rows[0] if ranked_rows else None
    return ranked_rows, selected, summary


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
        return None, None
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


def _content_payload(row: ContentLibraryItem | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "pillar_key": str(getattr(row, "pillar_key", "") or "").strip() or None,
        "concept_code": _normalized_library_concept(row),
        "title": str(getattr(row, "title", "") or "").strip() or None,
        "body": str(getattr(row, "body", "") or "").strip() or None,
        "podcast_url": str(getattr(row, "podcast_url", "") or "").strip() or None,
        "podcast_voice": str(getattr(row, "podcast_voice", "") or "").strip() or None,
        "avatar": _library_avatar_payload(row),
        "created_at": getattr(row, "created_at", None),
    }


def _limit_insight_words(value: str, limit: int) -> str:
    text = value.strip()
    words = list(re.finditer(r"\S+", text))
    if len(words) <= limit:
        return text
    if limit <= 0:
        return ""
    prefix = text[:words[limit - 1].end()]
    endings = list(re.finditer(r'''[.!?][”’"')\]]*(?=\s|$)''', prefix))
    if endings:
        return prefix[:endings[-1].end()]
    return prefix.rstrip(".,;:!?…") + "…"


def _limit_insight_narrative(reason: str, guidance: str) -> tuple[str, str]:
    """Keep each concept's displayed narrative within one shared word budget."""
    if len(reason.split()) + len(guidance.split()) <= _INSIGHT_WORD_LIMIT:
        return reason, guidance
    # Long recorded values can appear in the reason; retain room for advice.
    reason = _limit_insight_words(reason, 25)
    guidance = _limit_insight_words(guidance, _INSIGHT_WORD_LIMIT - len(reason.split()))
    return reason, guidance


def _build_insight_result(
    user_id: int,
    candidates: list[dict[str, Any]],
    *,
    anchor: date | None = None,
    concept_key: str | None = None,
) -> dict[str, Any]:
    off_track = _rank_off_track_concepts(candidates)
    counts = {
        status: sum(1 for item in candidates if item.get("status") == status)
        for status in ("off_track", "on_track", "unlogged", "not_applicable")
    }
    status = "insufficient_data"
    if counts["off_track"]:
        status = "off_track"
    elif counts["on_track"] and not counts["unlogged"]:
        status = "on_track"
    preferred = _normalize_concept_key(concept_key) or None
    selected = next((item for item in off_track if item.get("concept_key") == preferred), None)
    if selected is None:
        selected = off_track[0] if off_track else None
    library_by_pillar: dict[str, list[ContentLibraryItem]] = {}
    available = []
    for item in off_track:
        pillar_key = str(item.get("pillar_key") or "")
        if pillar_key not in library_by_pillar:
            library_by_pillar[pillar_key] = _load_library_rows(pillar_key)
        row, matched_by = _select_library_item(library_by_pillar[pillar_key], concept_key=item.get("concept_key"))
        content = _content_payload(row)
        label = str(item.get("concept_label") or item.get("concept_key") or "This concept").strip()
        target = str(item.get("target_label") or "").strip()
        value = str(item.get("latest_value") or "").strip()
        reason = "Your latest check-in is outside your target."
        if item.get("signal") == "needs_support":
            reason = "Your latest check-in is below the on-track score range."
        if value:
            reason = f"{reason} Recorded: {value}."
        # Published advice must match this exact concept. A missing lesson must
        # never turn into advice for another concept in the same pillar.
        guidance = str((content or {}).get("body") or "").strip()
        if not guidance:
            guidance = (
                f"Choose one manageable change to support {label.lower()} before your next check-in. "
                + (f"Use your target ({target}) to decide what to change." if target else "Reflect on what got in the way and choose a small step you can repeat.")
            )
        reason, guidance = _limit_insight_narrative(reason, guidance)
        available.append({
            "pillar_key": pillar_key,
            "pillar_label": item.get("pillar_label") or pillar_label(pillar_key),
            "concept_key": item.get("concept_key"),
            "label": label,
            "is_selected": item is selected,
            "status": "off_track",
            "signal": item.get("signal"),
            "anchor_date": item.get("anchor_date"),
            "score": item.get("current_score"),
            "target_label": item.get("target_label"),
            "latest_value": item.get("latest_value"),
            "reason": reason,
            "guidance": guidance,
            "matched_by": matched_by,
            "content": content,
        })
    selected_payload = next((item for item in available if item["is_selected"]), {})
    return {
        "user_id": int(user_id),
        "insight_date": (anchor or tracker_today()).isoformat(),
        "pillar_key": selected_payload.get("pillar_key"),
        "pillar_label": selected_payload.get("pillar_label"),
        "concept_key": selected_payload.get("concept_key"),
        "concept_label": selected_payload.get("label"),
        "review": {
            "status": status,
            "reviewed_count": len(candidates),
            "off_track_count": counts["off_track"],
            "on_track_count": counts["on_track"],
            "unlogged_count": counts["unlogged"],
            "not_applicable_count": counts["not_applicable"],
        },
        "available_concepts": available,
        "matched_by": selected_payload.get("matched_by"),
        "content": selected_payload.get("content"),
    }


def get_coach_insight(
    user_id: int,
    *,
    anchor: date | None = None,
    concept_key: str | None = None,
) -> dict[str, Any]:
    candidates, _ = _review_concepts(int(user_id), anchor)
    return _build_insight_result(int(user_id), candidates, anchor=anchor, concept_key=concept_key)


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


def _review_cache_signature(candidates: list[dict[str, Any]], summary: dict[str, Any]) -> tuple[str, str]:
    plan_date = tracker_today().isoformat()
    payload = json.dumps(
        {"review_version": _INSIGHT_REVIEW_VERSION, "plan_date": plan_date, "concepts": candidates, "summary": summary},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return (
        hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        plan_date,
    )


def _insight_cache_signature(user_id: int) -> tuple[str, str]:
    candidates, summary = _review_concepts(int(user_id))
    return _review_cache_signature(candidates, summary)


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
            "review_version": _INSIGHT_REVIEW_VERSION,
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
    candidates, summary = _review_concepts(int(user_id))
    context_hash, plan_date = _review_cache_signature(candidates, summary)
    if not force and context_hash and plan_date:
        cached = _get_json_pref(int(user_id), _INSIGHT_CACHE_KEY) or {}
        if (
            cached.get("review_version") == _INSIGHT_REVIEW_VERSION
            and str(cached.get("context_hash") or "").strip() == context_hash
            and str(cached.get("plan_date") or "").strip() == plan_date
            and isinstance(cached.get("result"), dict)
        ):
            return dict(cached.get("result") or {})
    result = _build_insight_result(int(user_id), candidates, anchor=anchor, concept_key=concept_key)
    cache_coach_insight(
        int(user_id),
        result,
        context_hash=context_hash,
        plan_date=plan_date,
    )
    return result
