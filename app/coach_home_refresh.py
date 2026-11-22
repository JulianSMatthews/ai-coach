from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .db import SessionLocal
from .models import UserPreference

COACH_HOME_REFRESH_STATE_KEY = "coach_home_refresh_state"
COACH_HOME_REFRESH_JOB_KIND = "coach_home_tracker_refresh"


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


def get_coach_home_refresh_state(user_id: int) -> dict[str, Any]:
    return _get_json_pref(int(user_id), COACH_HOME_REFRESH_STATE_KEY) or {}


def _update_refresh_state(user_id: int, **updates: Any) -> dict[str, Any]:
    current = get_coach_home_refresh_state(int(user_id))
    next_payload = {
        **current,
        **updates,
        "user_id": int(user_id),
        "updated_at": datetime.utcnow().replace(microsecond=0).isoformat(),
    }
    _set_json_pref(int(user_id), COACH_HOME_REFRESH_STATE_KEY, next_payload)
    return next_payload


def run_coach_home_tracker_refresh(
    user_id: int,
    *,
    trigger: str | None = None,
    pillar_key: str | None = None,
    score_date: str | None = None,
    job_id: int | None = None,
) -> dict[str, Any]:
    """Finish legacy queued jobs without generating automatic coaching."""
    completed_at = datetime.utcnow().replace(microsecond=0).isoformat()
    result = {
        "ok": True,
        "skipped": True,
        "reason": "on_demand_coaching_only",
        "user_id": int(user_id),
        "trigger": str(trigger or "tracker_update").strip() or "tracker_update",
        "pillar_key": str(pillar_key or "").strip().lower() or None,
        "score_date": str(score_date or "").strip() or None,
        "completed_at": completed_at,
    }
    _update_refresh_state(
        int(user_id),
        status="succeeded",
        trigger=result["trigger"],
        pillar_key=result["pillar_key"],
        score_date=result["score_date"],
        job_id=int(job_id) if job_id is not None else None,
        completed_at=completed_at,
        error=None,
        result=result,
    )
    return result


def queue_coach_home_tracker_refresh(
    user_id: int,
    *,
    trigger: str | None = None,
    pillar_key: str | None = None,
    score_date: str | None = None,
    background_tasks: Any | None = None,
) -> dict[str, Any]:
    """Compatibility entry point: coaching now runs only on a concept request."""
    return {
        "queued": False,
        "execution": "on_demand",
        "job_id": None,
        "created": False,
    }
