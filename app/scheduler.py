# app/scheduler.py
from __future__ import annotations

from datetime import datetime, timedelta
import os
import zoneinfo
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from .config import settings
from .db import SessionLocal
from .models import User, JobAudit, AssessSession
from .nudges import send_message
from .llm import compose_prompt

# ──────────────────────────────────────────────────────────────────────────────
# APScheduler setup
# ──────────────────────────────────────────────────────────────────────────────

jobstores = {"default": SQLAlchemyJobStore(url=settings.DATABASE_URL)}
executors = {"default": ThreadPoolExecutor(10)}
scheduler = AsyncIOScheduler(jobstores=jobstores, executors=executors, timezone="UTC")


def start_scheduler():
    if not scheduler.running:
        scheduler.start()


# ──────────────────────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────────────────────

def _get_user(user_id: int) -> User | None:
    with SessionLocal() as s:
        return s.get(User, user_id)


def _audit(user_id: int, kind: str, payload: dict[str, Any] | None = None):
    with SessionLocal() as s:
        s.add(JobAudit(user_id=user_id, kind=kind, payload=payload or {}))
        s.commit()


def _tz(user: User) -> zoneinfo.ZoneInfo:
    try:
        return zoneinfo.ZoneInfo(user.tz or "UTC")
    except Exception:
        return zoneinfo.ZoneInfo("UTC")


def _fast_minutes_env() -> int | None:
    """
    If FAST_MODE_MINUTES is set (e.g., 1, 5), we transform daily/weekly schedules
    into "every N minutes" for rapid testing.
    """
    v = os.getenv("FAST_MODE_MINUTES")
    if not v:
        return None
    try:
        n = int(v)
        return max(1, n)
    except ValueError:
        return None


def _user_onboarding_active(user_id: int) -> bool:
    """
    True if the user has not completed onboarding OR has an active combined assessment.
    We suppress nudges while onboarding is active.
    """
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            return True
        if not getattr(u, "onboard_complete", False):
            return True
        # also suppress if combined assessment is still running
        active = (
            s.query(AssessSession)
            .filter(
                AssessSession.user_id == user_id,
                AssessSession.domain == "combined",
                AssessSession.is_active == True,
            )
            .first()
        )
        return active is not None


# ──────────────────────────────────────────────────────────────────────────────
# Core send
# ──────────────────────────────────────────────────────────────────────────────

def run_nudge(user_id: int, kind: str, context: dict | None = None):
    user = _get_user(user_id)
    if not user:
        return

    # ✅ HARD GUARD: never send nudges before onboarding is complete
    if _user_onboarding_active(user_id):
        print(f"[scheduler] suppress nudge '{kind}' for user {user_id}: onboarding active")
        return

    # Compose & send
    msg = compose_prompt(kind, context or {})
    send_message(user.phone, msg)
    _audit(user_id, kind, {"context": context or {}, "msg": msg})


# ──────────────────────────────────────────────────────────────────────────────
# One‑off + timeout follow‑ups
# ──────────────────────────────────────────────────────────────────────────────

def schedule_one_off_nudge(
    user_id: int,
    delay_seconds: int = 10,
    kind: str = "daily_micro_nudge",
    context: dict | None = None,
):
    run_time = datetime.utcnow() + timedelta(seconds=delay_seconds)
    scheduler.add_job(
        run_nudge,
        trigger="date",
        run_date=run_time,
        args=[user_id, kind, context or {}],
        id=f"oneoff_{user_id}_{kind}_{int(run_time.timestamp())}",
        replace_existing=False,
        misfire_grace_time=3600,
    )


def schedule_timeout_followup(
    user_id: int,
    after_minutes: int = 180,
    context: dict | None = None,
):
    run_time = datetime.utcnow() + timedelta(minutes=after_minutes)
    job_id = f"timeout_{user_id}"
    # ensure single live timeout follow‑up
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    scheduler.add_job(
        run_nudge,
        trigger="date",
        run_date=run_time,
        args=[user_id, "timeout_followup", context or {}],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=7200,
    )


def cancel_timeout_followup(user_id: int):
    job_id = f"timeout_{user_id}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Recurring schedules (with FAST mode)
# ──────────────────────────────────────────────────────────────────────────────

def schedule_daily_micro_nudge(
    user_id: int,
    pillar: str,
    hour_local: int = 8,
    minute_local: int = 0,
    fast_minutes: int | None = None,
):
    """
    Normal: every day at hour:minute in user's timezone.
    FAST mode (via arg or FAST_MODE_MINUTES env): every N minutes instead.
    """
    user = _get_user(user_id)
    if not user:
        return
    tz = _tz(user)

    n = fast_minutes or _fast_minutes_env()
    job_id = f"daily_micro_{user_id}_{pillar}"

    if n:
        # Every N minutes (testing)
        scheduler.add_job(
            run_nudge,
            trigger="interval",
            minutes=n,
            args=[user_id, "daily_micro_nudge", {"pillar": pillar}],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
            timezone=tz,
        )
    else:
        # Real daily cron
        scheduler.add_job(
            run_nudge,
            trigger="cron",
            hour=hour_local,
            minute=minute_local,
            args=[user_id, "daily_micro_nudge", {"pillar": pillar}],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
            timezone=tz,
        )


def schedule_weekly_reflection(
    user_id: int,
    weekday: str = "sun",
    hour_local: int = 19,
    minute_local: int = 0,
    fast_minutes: int | None = None,
):
    """
    Normal: weekly on weekday at hour:minute in user's timezone.
    FAST mode: every N minutes.
    """
    user = _get_user(user_id)
    if not user:
        return
    tz = _tz(user)

    n = fast_minutes or _fast_minutes_env()
    job_id = f"weekly_refl_{user_id}"

    if n:
        scheduler.add_job(
            run_nudge,
            trigger="interval",
            minutes=n,
            args=[user_id, "weekly_reflection", {}],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
            timezone=tz,
        )
    else:
        scheduler.add_job(
            run_nudge,
            trigger="cron",
            day_of_week=weekday,
            hour=hour_local,
            minute=minute_local,
            args=[user_id, "weekly_reflection", {}],
            id=job_id,
            replace_existing=True,
            misfire_grace_time=3600,
            timezone=tz,
        )


def schedule_review_30d(user_id: int):
    """
    One‑off 30‑day review at ~09:00 local time. (You can speed test by calling
    schedule_one_off_nudge instead.)
    """
    user = _get_user(user_id)
    if not user:
        return
    tz = _tz(user)
    run_time_local = (datetime.now(tz).replace(hour=9, minute=0, second=0, microsecond=0)
                      + timedelta(days=30))
    run_time_utc = run_time_local.astimezone(zoneinfo.ZoneInfo("UTC"))

    scheduler.add_job(
        run_nudge,
        trigger="date",
        run_date=run_time_utc,
        args=[user_id, "review_30d", {}],
        id=f"review30_{user_id}_{int(run_time_utc.timestamp())}",
        replace_existing=False,
        misfire_grace_time=86400,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Apply cadence by level (called after onboarding completes)
# ──────────────────────────────────────────────────────────────────────────────

def _level_to_daily_pillar_hour(level: str, default_hour: int) -> int:
    """
    Example mapping by level → hour for daily micro nudges.
    Tweak as you like; this just staggers the send time a bit.
    """
    lv = (level or "").lower()
    if lv == "low":
        return default_hour
    if lv == "moderate":
        return (default_hour + 1) % 24
    if lv == "high":
        return (default_hour + 2) % 24
    return default_hour


def apply_nutrition_cadence(user_id: int, level: str):
    """
    Daily micro for Nutrition, weekly reflection shared.
    Honors FAST mode automatically.
    """
    hour = _level_to_daily_pillar_hour(level, default_hour=8)
    schedule_daily_micro_nudge(user_id, pillar="nutrition", hour_local=hour)
    schedule_weekly_reflection(user_id, weekday="sun", hour_local=19)
    schedule_review_30d(user_id)


def apply_training_cadence(user_id: int, level: str):
    hour = _level_to_daily_pillar_hour(level, default_hour=9)
    schedule_daily_micro_nudge(user_id, pillar="training", hour_local=hour)
    # you can add a training‑specific weekly if desired; using shared reflection
    schedule_weekly_reflection(user_id, weekday="sun", hour_local=19)


def apply_psych_cadence(user_id: int, level: str):
    hour = _level_to_daily_pillar_hour(level, default_hour=10)
    schedule_daily_micro_nudge(user_id, pillar="psych", hour_local=hour)
    schedule_weekly_reflection(user_id, weekday="sun", hour_local=19)