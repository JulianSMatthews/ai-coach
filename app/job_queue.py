from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import and_, or_

from .db import SessionLocal, engine
from .models import BackgroundJob, Base


def ensure_job_table() -> None:
    try:
        Base.metadata.create_all(bind=engine, tables=[BackgroundJob.__table__])
    except Exception:
        # Fallback: create all if table list not supported
        Base.metadata.create_all(bind=engine)


def should_use_worker() -> bool:
    return (os.getenv("PROMPT_WORKER_MODE") or "").strip().lower() in {"1", "true", "yes"}


def enqueue_job(kind: str, payload: dict[str, Any], *, user_id: int | None = None) -> int:
    with SessionLocal() as s:
        job = BackgroundJob(
            kind=kind,
            payload=payload,
            status="pending",
            user_id=user_id,
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        return int(job.id)


def claim_job(
    *,
    worker_id: str | None = None,
    kinds: Iterable[str] | None = None,
    lock_timeout_minutes: int = 30,
) -> BackgroundJob | None:
    now = datetime.utcnow()
    stale = now - timedelta(minutes=max(1, lock_timeout_minutes))
    worker_id = worker_id or socket.gethostname()
    with SessionLocal() as s:
        q = s.query(BackgroundJob).filter(
            or_(
                BackgroundJob.status == "pending",
                BackgroundJob.status == "retry",
                and_(BackgroundJob.status == "running", BackgroundJob.locked_at.isnot(None), BackgroundJob.locked_at < stale),
            )
        )
        if kinds:
            q = q.filter(BackgroundJob.kind.in_(list(kinds)))
        job = (
            q.order_by(BackgroundJob.created_at.asc(), BackgroundJob.id.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if not job:
            return None
        job.status = "running"
        job.locked_at = now
        job.locked_by = worker_id
        job.attempts = int(job.attempts or 0) + 1
        s.add(job)
        s.commit()
        s.refresh(job)
        s.expunge(job)
        return job


def mark_done(job_id: int, result: dict[str, Any] | None = None) -> None:
    with SessionLocal() as s:
        job = s.get(BackgroundJob, job_id)
        if not job:
            return
        job.status = "done"
        job.result = result
        job.error = None
        job.locked_at = None
        job.locked_by = None
        s.add(job)
        s.commit()


def mark_error(job_id: int, error: str, *, retry: bool) -> None:
    with SessionLocal() as s:
        job = s.get(BackgroundJob, job_id)
        if not job:
            return
        job.error = error
        job.status = "retry" if retry else "error"
        s.add(job)
        s.commit()
