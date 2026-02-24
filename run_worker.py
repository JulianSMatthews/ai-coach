#!/usr/bin/env python3
from __future__ import annotations
# Render sync marker: force fresh worker build/deploy from latest commit.

import os
import time
import socket
import traceback
import json
import urllib.request
from datetime import datetime, timedelta

from app.job_queue import (
    claim_job,
    ensure_job_table,
    mark_done,
    mark_error,
    enqueue_job,
    queue_requeue_delay_seconds,
)
from app import scheduler, assessor, monday, kickoff, thursday, friday
from app.prompts import run_llm_prompt
from app.usage import ensure_usage_schema
from app.prompts import _ensure_llm_prompt_log_schema
from app.message_log import _ensure_message_log_schema
from app.reporting import (
    generate_assessment_narratives,
    generate_assessment_core_narratives,
    generate_assessment_habit_narrative,
)
from app.db import SessionLocal, _table_exists, engine
from app.models import User, AssessSession, PillarResult, OKRKrHabitStep, BackgroundJob, OKRObjective
from app.okr import generate_and_update_okrs_for_pillar, seed_week1_habit_steps_for_assessment

os.environ.setdefault("PROMPT_WORKER_PROCESS", "1")


def _process_day_prompt(payload: dict) -> None:
    user_id = payload.get("user_id")
    day = payload.get("day")
    if not user_id or not day:
        raise ValueError("day_prompt requires user_id and day")
    scheduler._run_day_prompt_inline(int(user_id), str(day))


def _load_user(user_id: int) -> User:
    with SessionLocal() as s:
        user = s.get(User, user_id)
        if not user:
            raise ValueError(f"user not found: {user_id}")
        s.expunge(user)
        return user


def _process_assessment_start(payload: dict) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("assessment_start requires user_id")
    force_intro = bool(payload.get("force_intro", False))
    user = _load_user(int(user_id))
    assessor.start_combined_assessment(user, force_intro=force_intro)


def _process_assessment_continue(payload: dict) -> None:
    user_id = payload.get("user_id")
    text = payload.get("text")
    if not user_id or text is None:
        raise ValueError("assessment_continue requires user_id and text")
    user = _load_user(int(user_id))
    assessor.continue_combined_assessment(user, str(text))


def _process_assessment_narratives_seed(payload: dict) -> dict:
    run_id = payload.get("run_id")
    if not run_id:
        raise ValueError("assessment_narratives_seed requires run_id")
    return generate_assessment_narratives(int(run_id))


def _process_assessment_narratives_core_seed(payload: dict) -> dict:
    run_id = payload.get("run_id")
    if not run_id:
        raise ValueError("assessment_narratives_core_seed requires run_id")
    return generate_assessment_core_narratives(int(run_id))


def _process_assessment_narratives_habit_seed(payload: dict) -> dict:
    run_id = payload.get("run_id")
    if not run_id:
        raise ValueError("assessment_narratives_habit_seed requires run_id")
    return generate_assessment_habit_narrative(int(run_id))


def _process_pillar_okr_sync(payload: dict) -> dict:
    user_id = payload.get("user_id")
    run_id = payload.get("run_id")
    assess_session_id = payload.get("assess_session_id")
    pillar_result_id = payload.get("pillar_result_id")
    pillar_key = payload.get("pillar_key")
    if not user_id or not assess_session_id or not pillar_result_id or not pillar_key:
        raise ValueError("pillar_okr_sync requires user_id, assess_session_id, pillar_result_id, pillar_key")

    concept_scores = payload.get("concept_scores")
    if not isinstance(concept_scores, dict):
        concept_scores = {}

    pillar_score = payload.get("pillar_score")
    try:
        pillar_score_val = float(pillar_score) if pillar_score is not None else None
    except Exception:
        pillar_score_val = None

    write_progress_entries = bool(payload.get("write_progress_entries", True))
    quarter_label = payload.get("quarter_label")

    with SessionLocal() as s:
        user = s.get(User, int(user_id))
        assess_session = s.get(AssessSession, int(assess_session_id))
        pillar_result = s.get(PillarResult, int(pillar_result_id))
        if not user:
            raise ValueError(f"user not found: {user_id}")
        if not assess_session:
            raise ValueError(f"assess_session not found: {assess_session_id}")
        if not pillar_result:
            raise ValueError(f"pillar_result not found: {pillar_result_id}")

        res = generate_and_update_okrs_for_pillar(
            s,
            user_id=int(user_id),
            run_id=int(run_id) if run_id is not None else None,
            assess_session_id=int(assess_session_id),
            pillar_result_id=int(pillar_result_id),
            pillar_key=str(pillar_key),
            pillar_score=pillar_score_val,
            concept_scores=concept_scores,
            write_progress_entries=write_progress_entries,
            quarter_label=quarter_label,
        )
        s.commit()
        return {
            "ok": True,
            "objective_id": int(getattr(res.get("objective"), "id", 0) or 0) if isinstance(res, dict) else 0,
            "pillar_result_id": int(pillar_result_id),
            "pillar_key": str(pillar_key),
        }


def _process_assessment_week1_habit_seed(payload: dict) -> dict:
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("assessment_week1_habit_seed requires user_id")

    assess_session_id = payload.get("assess_session_id")
    run_id = payload.get("run_id")
    week_no = int(payload.get("week_no") or 1)
    require_seed = bool(payload.get("require_seed", True))

    requeue_count = int(payload.get("requeue_count") or 0)
    max_requeues = int(
        payload.get("max_requeues")
        or os.getenv("ASSESSMENT_WEEK1_HABIT_SEED_MAX_REQUEUES")
        or 30
    )

    def _safe_int(value):
        try:
            if value is None:
                return None
            return int(value)
        except Exception:
            return None

    def _pending_pillar_sync_count(session) -> int:
        target_user = _safe_int(user_id)
        target_session = _safe_int(assess_session_id)
        target_run = _safe_int(run_id)
        q = session.query(BackgroundJob).filter(
            BackgroundJob.kind == "pillar_okr_sync",
            BackgroundJob.status.in_(["pending", "running", "retry"]),
        )
        if target_user is not None:
            q = q.filter(BackgroundJob.user_id == target_user)
        pending = 0
        for job in q.all():
            body = job.payload if isinstance(job.payload, dict) else {}
            if not isinstance(body, dict):
                continue
            job_session = _safe_int(body.get("assess_session_id"))
            job_run = _safe_int(body.get("run_id"))
            if target_session is not None and job_session == target_session:
                pending += 1
                continue
            if target_run is not None and job_run == target_run:
                pending += 1
                continue
        return pending

    def _same_seed_payload(a: dict, b: dict) -> bool:
        return (
            _safe_int(a.get("user_id")) == _safe_int(b.get("user_id"))
            and _safe_int(a.get("assess_session_id")) == _safe_int(b.get("assess_session_id"))
            and _safe_int(a.get("run_id")) == _safe_int(b.get("run_id"))
            and int(a.get("week_no") or 1) == int(b.get("week_no") or 1)
        )

    def _enqueue_seed_retry_if_needed(reason: str) -> dict:
        if requeue_count >= max(1, max_requeues):
            if require_seed:
                raise RuntimeError(
                    f"week-1 habit seed exceeded requeue limit user_id={user_id} "
                    f"assess_session_id={assess_session_id} run_id={run_id} "
                    f"requeue_count={requeue_count} max_requeues={max_requeues} reason={reason}"
                )
            return {
                "ok": True,
                "seeded_count": 0,
                "week_no": week_no,
                "requeue_exhausted": True,
                "reason": reason,
                "requeue_count": requeue_count,
            }

        next_payload = dict(payload)
        next_payload["requeue_count"] = requeue_count + 1
        next_payload["max_requeues"] = max(1, max_requeues)
        next_payload["last_requeue_reason"] = reason

        delay_seconds = queue_requeue_delay_seconds(requeue_count)
        available_at = datetime.utcnow() + timedelta(seconds=delay_seconds)

        duplicate_found = False
        with SessionLocal() as s:
            candidates = (
                s.query(BackgroundJob.id, BackgroundJob.payload, BackgroundJob.available_at)
                .filter(
                    BackgroundJob.kind == "assessment_week1_habit_seed",
                    BackgroundJob.status.in_(["pending", "retry"]),
                    BackgroundJob.user_id == int(user_id),
                )
                .all()
            )
            for _, existing_payload, existing_available_at in candidates:
                body = existing_payload if isinstance(existing_payload, dict) else {}
                same_job = isinstance(body, dict) and _same_seed_payload(body, next_payload)
                if not same_job:
                    continue
                # If we already have one scheduled for later, don't enqueue another.
                if existing_available_at is None or existing_available_at >= available_at:
                    duplicate_found = True
                    break

        if not duplicate_found:
            enqueue_job(
                "assessment_week1_habit_seed",
                next_payload,
                user_id=int(user_id),
                available_at=available_at,
            )

        print(
            f"[worker] habit seed requeue user_id={user_id} "
            f"assess_session_id={assess_session_id} run_id={run_id} "
            f"week_no={week_no} requeue_count={requeue_count + 1}/{max(1, max_requeues)} "
            f"reason={reason} delay_seconds={delay_seconds} "
            f"available_at={available_at.isoformat()} duplicate_found={duplicate_found}"
        )
        return {
            "ok": True,
            "seeded_count": 0,
            "week_no": week_no,
            "requeued": True,
            "reason": reason,
            "requeue_count": requeue_count + 1,
            "requeue_delay_seconds": delay_seconds,
            "requeue_not_before": available_at.isoformat(),
            "duplicate_found": duplicate_found,
        }

    with SessionLocal() as s:
        pending_sync = _pending_pillar_sync_count(s)
        if pending_sync > 0:
            return _enqueue_seed_retry_if_needed(f"pending_pillar_okr_sync={pending_sync}")

        seeded_count = seed_week1_habit_steps_for_assessment(
            s,
            user_id=int(user_id),
            assess_session_id=int(assess_session_id) if assess_session_id else None,
            run_id=int(run_id) if run_id else None,
            week_no=week_no,
        )
        if seeded_count:
            s.commit()
            return {"ok": True, "seeded_count": int(seeded_count), "week_no": week_no}

        # If steps already exist, treat as success.
        existing = (
            s.query(OKRKrHabitStep.id)
            .filter(
                OKRKrHabitStep.user_id == int(user_id),
                OKRKrHabitStep.week_no == int(week_no),
                OKRKrHabitStep.status != "archived",
            )
            .first()
        )
        if existing:
            return {"ok": True, "seeded_count": 0, "already_exists": True, "week_no": week_no}

        nutrition_obj_query = (
            s.query(OKRObjective.id)
            .filter(
                OKRObjective.owner_user_id == int(user_id),
                OKRObjective.pillar_key == "nutrition",
            )
        )
        if assess_session_id:
            nutrition_obj_query = nutrition_obj_query.filter(
                OKRObjective.source_assess_session_id == int(assess_session_id)
            )
        nutrition_obj_exists = nutrition_obj_query.first()
        if not nutrition_obj_exists:
            return _enqueue_seed_retry_if_needed("nutrition_objective_missing")

        return _enqueue_seed_retry_if_needed("no_steps_seeded_yet")


def _process_llm_prompt(payload: dict) -> dict:
    prompt = payload.get("prompt")
    if not prompt:
        raise ValueError("llm_prompt requires prompt")
    text = run_llm_prompt(
        prompt,
        user_id=payload.get("user_id"),
        touchpoint=payload.get("touchpoint"),
        model=payload.get("model"),
        context_meta=payload.get("context_meta"),
        prompt_variant=payload.get("prompt_variant"),
        task_label=payload.get("task_label"),
        prompt_blocks=payload.get("prompt_blocks"),
        block_order=payload.get("block_order"),
        log=payload.get("log"),
    )
    return {"ok": True, "text": text}


def _process_weekstart_flow(payload: dict) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("weekstart_flow requires user_id")
    user = _load_user(int(user_id))
    monday.start_weekstart(
        user,
        notes=payload.get("notes"),
        debug=bool(payload.get("debug", False)),
        set_state=bool(payload.get("set_state", True)),
        week_no=payload.get("week_no"),
    )


def _process_kickoff_flow(payload: dict) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("kickoff_flow requires user_id")
    user = _load_user(int(user_id))
    kickoff.start_kickoff(
        user,
        notes=payload.get("notes"),
        debug=bool(payload.get("debug", False)),
    )


def _process_thursday_flow(payload: dict) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("thursday_flow requires user_id")
    user = _load_user(int(user_id))
    thursday.send_thursday_boost(user, week_no=payload.get("week_no"))


def _process_friday_flow(payload: dict) -> None:
    user_id = payload.get("user_id")
    if not user_id:
        raise ValueError("friday_flow requires user_id")
    user = _load_user(int(user_id))
    friday.send_boost(user, week_no=payload.get("week_no"))


def process_job(kind: str, payload: dict) -> dict:
    if kind == "day_prompt":
        _process_day_prompt(payload)
        return {"ok": True}
    if kind == "assessment_start":
        _process_assessment_start(payload)
        return {"ok": True}
    if kind == "assessment_continue":
        _process_assessment_continue(payload)
        return {"ok": True}
    if kind == "assessment_narratives_seed":
        return _process_assessment_narratives_seed(payload)
    if kind == "assessment_narratives_core_seed":
        return _process_assessment_narratives_core_seed(payload)
    if kind == "assessment_narratives_habit_seed":
        return _process_assessment_narratives_habit_seed(payload)
    if kind == "pillar_okr_sync":
        return _process_pillar_okr_sync(payload)
    if kind == "assessment_week1_habit_seed":
        return _process_assessment_week1_habit_seed(payload)
    if kind == "llm_prompt":
        return _process_llm_prompt(payload)
    if kind == "weekstart_flow":
        _process_weekstart_flow(payload)
        return {"ok": True}
    if kind == "kickoff_flow":
        _process_kickoff_flow(payload)
        return {"ok": True}
    if kind == "thursday_flow":
        _process_thursday_flow(payload)
        return {"ok": True}
    if kind == "friday_flow":
        _process_friday_flow(payload)
        return {"ok": True}
    raise ValueError(f"Unknown job kind: {kind}")


def main() -> None:
    os.environ.setdefault("PROMPT_WORKER_PROCESS", "1")
    _wait_for_api_ready()
    try:
        ensure_usage_schema()
    except Exception as e:
        print(f"[worker] WARN: ensure usage schema failed: {e}")
    try:
        _ensure_llm_prompt_log_schema()
    except Exception as e:
        print(f"[worker] WARN: ensure llm prompt log schema failed: {e}")
    try:
        _ensure_message_log_schema()
    except Exception as e:
        print(f"[worker] WARN: ensure message log schema failed: {e}")
    ensure_job_table()
    worker_id = os.getenv("WORKER_ID") or socket.gethostname()
    poll_seconds = int(os.getenv("WORKER_POLL_SECONDS", "2") or "2")
    lock_timeout = int(os.getenv("WORKER_LOCK_TIMEOUT_MINUTES", "30") or "30")
    max_attempts = int(os.getenv("WORKER_MAX_ATTEMPTS", "3") or "3")

    print(f"[worker] started id={worker_id} poll={poll_seconds}s lock_timeout={lock_timeout}m max_attempts={max_attempts}")
    while True:
        job = claim_job(worker_id=worker_id, lock_timeout_minutes=lock_timeout)
        if not job:
            time.sleep(max(1, poll_seconds))
            continue
        try:
            result = process_job(job.kind, job.payload or {})
            mark_done(job.id, result)
            print(f"[worker] done job={job.id} kind={job.kind}")
        except Exception as e:
            retry = int(job.attempts or 0) < max_attempts
            mark_error(job.id, str(e), retry=retry)
            print(f"[worker] error job={job.id} kind={job.kind} retry={retry}: {e}")
            print(traceback.format_exc())


def _env_true(name: str, default: str = "0") -> bool:
    raw = (os.getenv(name) or default).strip().lower()
    return raw in {"1", "true", "yes"}


def _api_health_url() -> str | None:
    explicit = (os.getenv("API_HEALTH_URL") or "").strip()
    if explicit:
        return explicit
    base = (os.getenv("API_BASE_URL") or os.getenv("PUBLIC_BASE_URL") or "").strip()
    if not base:
        return None
    return base.rstrip("/") + "/health"


def _wait_for_api_ready() -> None:
    if not _env_true("WORKER_WAIT_FOR_API", "1"):
        return
    timeout_s = int((os.getenv("WORKER_WAIT_FOR_API_TIMEOUT_SECONDS") or "120").strip() or "120")
    poll_s = int((os.getenv("WORKER_WAIT_FOR_API_POLL_SECONDS") or "3").strip() or "3")
    deadline = time.time() + max(5, timeout_s)
    health_url = _api_health_url()
    print(f"[worker] waiting for API readiness (timeout={timeout_s}s url={health_url or 'db'})")
    while time.time() < deadline:
        if health_url:
            try:
                req = urllib.request.Request(health_url, headers={"User-Agent": "healthsense-worker"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if 200 <= resp.status < 300:
                        try:
                            body = resp.read().decode("utf-8")
                            data = json.loads(body) if body else {}
                            if isinstance(data, dict) and data.get("ok") is True:
                                print("[worker] API health ok")
                                return
                        except Exception:
                            # If response is not JSON but status is OK, accept it.
                            print("[worker] API health ok (non-JSON)")
                            return
            except Exception:
                pass
        else:
            try:
                with engine.begin() as conn:
                    if _table_exists(conn, "apscheduler_jobs"):
                        print("[worker] apscheduler_jobs exists; API likely ready")
                        return
            except Exception:
                pass
        time.sleep(max(1, poll_s))
    print("[worker] API wait timeout reached; continuing startup")


if __name__ == "__main__":
    main()
