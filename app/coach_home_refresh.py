from __future__ import annotations

import json
import os
import threading
from datetime import datetime
from typing import Any

from .coach_insight import get_or_generate_cached_coach_insight
from .daily_habits import (
    build_daily_tracker_generation_context_snapshot,
    get_or_generate_cached_daily_habit_plan,
)
from .db import SessionLocal
from .general_support import get_or_generate_cached_tracker_summary_message
from .job_queue import enqueue_job_once, should_use_worker
from .models import User, UserPreference

COACH_HOME_REFRESH_STATE_KEY = "coach_home_refresh_state"
COACH_HOME_REFRESH_JOB_KIND = "coach_home_tracker_refresh"


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


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
    job_id: int | None = None,
) -> dict[str, Any]:
    snapshot = build_daily_tracker_generation_context_snapshot(int(user_id))
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    context_hash = str(snapshot.get("context_hash") or "").strip() or None
    plan_date = str(context.get("plan_date") or "").strip() or None
    started_at = datetime.utcnow().replace(microsecond=0).isoformat()
    _update_refresh_state(
        int(user_id),
        status="running",
        trigger=str(trigger or "tracker_update").strip() or "tracker_update",
        job_id=int(job_id) if job_id is not None else None,
        started_at=started_at,
        error=None,
        context_hash=context_hash,
        plan_date=plan_date,
    )
    try:
        with SessionLocal() as s:
            user = s.get(User, int(user_id))
            if not user:
                raise ValueError(f"user not found: {user_id}")
            s.expunge(user)
        habit_result = get_or_generate_cached_daily_habit_plan(
            int(user_id),
            force=False,
            tracker_snapshot=snapshot,
        )
        gia_text = get_or_generate_cached_tracker_summary_message(
            user,
            source="app_tracker_summary",
            include_prefix=False,
            force=False,
            tracker_snapshot=snapshot,
        )
        insight_result = get_or_generate_cached_coach_insight(int(user_id), force=False)
        completed_at = datetime.utcnow().replace(microsecond=0).isoformat()
        result = {
            "ok": True,
            "user_id": int(user_id),
            "trigger": str(trigger or "tracker_update").strip() or "tracker_update",
            "plan_date": plan_date,
            "context_hash": context_hash,
            "habits_ready": isinstance(habit_result, dict) and bool(
                (habit_result.get("habits") if isinstance(habit_result, dict) else None)
                or (habit_result.get("options") if isinstance(habit_result, dict) else None)
            ),
            "habits_source": str((habit_result or {}).get("source") or "").strip() or None,
            "gia_ready": bool(str(gia_text or "").strip()),
            "insight_ready": isinstance(insight_result, dict) and bool(
                (insight_result.get("content") if isinstance(insight_result, dict) else None)
            ),
            "completed_at": completed_at,
        }
        _update_refresh_state(
            int(user_id),
            status="succeeded",
            trigger=str(trigger or "tracker_update").strip() or "tracker_update",
            job_id=int(job_id) if job_id is not None else None,
            completed_at=completed_at,
            error=None,
            context_hash=context_hash,
            plan_date=plan_date,
            result=result,
        )
        return result
    except Exception as exc:
        failed_at = datetime.utcnow().replace(microsecond=0).isoformat()
        _update_refresh_state(
            int(user_id),
            status="failed",
            trigger=str(trigger or "tracker_update").strip() or "tracker_update",
            job_id=int(job_id) if job_id is not None else None,
            completed_at=failed_at,
            error=str(exc),
            context_hash=context_hash,
            plan_date=plan_date,
        )
        raise


def queue_coach_home_tracker_refresh(
    user_id: int,
    *,
    trigger: str | None = None,
    pillar_key: str | None = None,
    score_date: str | None = None,
    background_tasks: Any | None = None,
) -> dict[str, Any]:
    snapshot = build_daily_tracker_generation_context_snapshot(int(user_id))
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    context_hash = str(snapshot.get("context_hash") or "").strip() or None
    plan_date = str(context.get("plan_date") or "").strip() or None
    payload = {
        "user_id": int(user_id),
        "trigger": str(trigger or "tracker_update").strip() or "tracker_update",
        "pillar_key": str(pillar_key or "").strip().lower() or None,
        "score_date": str(score_date or "").strip() or None,
        "context_hash": context_hash,
        "plan_date": plan_date,
    }
    queued_at = datetime.utcnow().replace(microsecond=0).isoformat()
    if should_use_worker() and not _in_worker_process():
        job_id, created = enqueue_job_once(
            COACH_HOME_REFRESH_JOB_KIND,
            payload,
            user_id=int(user_id),
            payload_match={
                "user_id": int(user_id),
                "context_hash": context_hash,
                "plan_date": plan_date,
            },
        )
        _update_refresh_state(
            int(user_id),
            status="queued",
            trigger=payload["trigger"],
            job_id=int(job_id),
            queued_at=queued_at,
            error=None,
            execution="worker",
            context_hash=context_hash,
            plan_date=plan_date,
        )
        return {
            "queued": True,
            "execution": "worker",
            "job_id": int(job_id),
            "created": bool(created),
        }
    if background_tasks is not None and hasattr(background_tasks, "add_task"):
        background_tasks.add_task(
            run_coach_home_tracker_refresh,
            int(user_id),
            trigger=payload["trigger"],
            job_id=None,
        )
        _update_refresh_state(
            int(user_id),
            status="queued",
            trigger=payload["trigger"],
            job_id=None,
            queued_at=queued_at,
            error=None,
            execution="api_background",
            context_hash=context_hash,
            plan_date=plan_date,
        )
        return {
            "queued": True,
            "execution": "api_background",
            "job_id": None,
            "created": True,
        }

    def _runner() -> None:
        try:
            run_coach_home_tracker_refresh(int(user_id), trigger=payload["trigger"], job_id=None)
        except Exception as exc:
            print(f"[coach-home-refresh] failed user_id={user_id}: {exc}")

    threading.Thread(target=_runner, daemon=True).start()
    _update_refresh_state(
        int(user_id),
        status="queued",
        trigger=payload["trigger"],
        job_id=None,
        queued_at=queued_at,
        error=None,
        execution="thread",
        context_hash=context_hash,
        plan_date=plan_date,
    )
    return {
        "queued": True,
        "execution": "thread",
        "job_id": None,
        "created": True,
    }
