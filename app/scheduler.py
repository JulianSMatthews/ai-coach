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
from .models import User, JobAudit, AssessSession, UserPreference
from .nudges import send_message
from .llm import compose_prompt
from . import monday, tuesday, wednesday, thursday, friday, sunday

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


def _user_pref_time(session, user_id: int, day_key: str) -> tuple[int, int] | None:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == f"coach_schedule_{day_key}")
        .one_or_none()
    )
    if not pref or not pref.value:
        return None
    try:
        hh, mm = str(pref.value).split(":")
        return int(hh), int(mm)
    except Exception:
        return None


def _default_times() -> dict[str, tuple[int, int]]:
    # Defaults in 24h: Sunday 18:00, Monday 08:00, Tuesday 19:00, Wednesday 08:00, Thursday 19:00, Friday 08:00
    return {
        "sunday": (18, 0),
        "monday": (8, 0),
        "tuesday": (19, 0),
        "wednesday": (8, 0),
        "thursday": (19, 0),
        "friday": (8, 0),
    }


def _auto_prompts_enabled(session, user_id: int) -> bool:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == "auto_daily_prompts")
        .one_or_none()
    )
    return bool(pref and str(pref.value).strip() == "1")


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
# Automatic daily prompts (day-specific handlers)
# ──────────────────────────────────────────────────────────────────────────────

def _run_day_prompt(user_id: int, day: str):
    """Invoke the day-specific handler for a user."""
    with SessionLocal() as s:
        user = s.get(User, user_id)
        if not user:
            return
    if _user_onboarding_active(user_id):
        print(f"[scheduler] skip {day} prompt for user {user_id}: onboarding active")
        return
    try:
        if day == "monday":
            monday.start_kickoff(user)
        elif day == "tuesday":
            tuesday.send_tuesday_check(user)
        elif day == "wednesday":
            wednesday.send_midweek_check(user)
        elif day == "thursday":
            thursday.send_thursday_boost(user)
        elif day == "friday":
            friday.send_boost(user)
        elif day == "sunday":
            sunday.send_sunday_review(user)
        else:
            print(f"[scheduler] unknown day prompt: {day}")
            return
        _audit(user_id, f"auto_prompt_{day}", {})
    except Exception as e:
        print(f"[scheduler] {day} prompt failed for user {user_id}: {e}")


def _schedule_prompt_for_user(user: User, day: str, dow: str, hour: int, minute: int):
    tz = _tz(user)
    job_id = f"auto_prompt_{day}_{user.id}"
    scheduler.add_job(
        _run_day_prompt,
        trigger="cron",
        day_of_week=dow,
        hour=hour,
        minute=minute,
        args=[user.id, day],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=3600,
        timezone=tz,
    )
    print(f"[scheduler] scheduled {day} prompt for user {user.id} at {hour:02d}:{minute:02d} ({tz})")


def _unschedule_prompts_for_user(user_id: int):
    for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "sunday"):
        job_id = f"auto_prompt_{day}_{user_id}"
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass


def _schedule_prompts_for_user(user: User, defaults: dict[str, tuple[int, int]], session) -> None:
    # Skip if user not enabled
    if not _auto_prompts_enabled(session, user.id):
        _unschedule_prompts_for_user(user.id)
        return
    for day, (hh_default, mm_default) in defaults.items():
        pref_time = _user_pref_time(session, user.id, day) or (hh_default, mm_default)
        dow = {
            "monday": "mon",
            "tuesday": "tue",
            "wednesday": "wed",
            "thursday": "thu",
            "friday": "fri",
            "sunday": "sun",
        }.get(day)
        if not dow:
            continue
        _schedule_prompt_for_user(user, day, dow, pref_time[0], pref_time[1])


def schedule_auto_daily_prompts():
    """Schedule day-specific prompts for all users based on their own preference."""
    defaults = _default_times()
    with SessionLocal() as s:
        users = s.query(User).all()
        for u in users:
            # Skip if onboarding not complete
            if _user_onboarding_active(u.id):
                continue
            _schedule_prompts_for_user(u, defaults, s)


def enable_auto_prompts(user_id: int) -> bool:
    """Enable auto prompts for a user and schedule them. Returns True on success."""
    defaults = _default_times()
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            return False
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "auto_daily_prompts")
            .one_or_none()
        )
        if pref:
            pref.value = "1"
        else:
            s.add(UserPreference(user_id=user_id, key="auto_daily_prompts", value="1"))
        s.commit()
        _schedule_prompts_for_user(u, defaults, s)
    return True


def disable_auto_prompts(user_id: int) -> bool:
    """Disable auto prompts for a user and unschedule them. Returns True on success."""
    defaults = _default_times()
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            return False
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "auto_daily_prompts")
            .one_or_none()
        )
        if pref:
            pref.value = "0"
            s.commit()
        _unschedule_prompts_for_user(user_id)
    return True


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
