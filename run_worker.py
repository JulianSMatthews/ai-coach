#!/usr/bin/env python3
from __future__ import annotations

import os
import time
import socket
import traceback

from app.job_queue import claim_job, ensure_job_table, mark_done, mark_error
from app import scheduler, assessor
from app.reporting import (
    generate_assessment_dashboard_html,
    generate_assessment_report_pdf,
    generate_progress_report_html,
)
from app.db import SessionLocal
from app.models import User


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


def _process_assessment_report(payload: dict) -> None:
    run_id = payload.get("run_id")
    if not run_id:
        raise ValueError("assessment_report requires run_id")
    user_id = payload.get("user_id")
    generate_assessment_dashboard_html(int(run_id))
    try:
        generate_assessment_report_pdf(int(run_id))
    except Exception:
        # PDF generation shouldn't block narrative availability
        pass
    if user_id:
        try:
            generate_progress_report_html(int(user_id))
        except Exception:
            pass


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
    if kind == "assessment_report":
        _process_assessment_report(payload)
        return {"ok": True}
    raise ValueError(f"Unknown job kind: {kind}")


def main() -> None:
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


if __name__ == "__main__":
    main()
