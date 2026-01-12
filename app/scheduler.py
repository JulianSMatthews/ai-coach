# app/scheduler.py
from __future__ import annotations

from datetime import datetime, timedelta
import os
import zoneinfo
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from sqlalchemy import text

from .config import settings
from .db import SessionLocal, engine
from .models import User, JobAudit, AssessSession, UserPreference

# Preference key(s) for auto coaching prompts (new primary key: "coaching"; legacy: "auto_daily_prompts")
AUTO_PROMPT_PREF_KEYS = ("coaching", "auto_daily_prompts")
from .nudges import send_message
from . import kickoff
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


def reset_job_store(clear_table: bool = False):
    """
    Remove all scheduled jobs. Optionally wipe the APS table (used when DB is reset).
    """
    removed = False
    try:
        scheduler.remove_all_jobs()
        removed = True
    except Exception:
        pass
    if clear_table:
        try:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM apscheduler_jobs"))
        except Exception as e:
            print(f"[scheduler] failed to clear apscheduler_jobs rows: {e}")
        try:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM apscheduler_jobs_backup"))
        except Exception as e:
            # backup table may not exist; ignore
            pass
        # If rows remain or table is broken, drop so SQLAlchemyJobStore can recreate
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS apscheduler_jobs CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS apscheduler_jobs_backup CASCADE"))
        except Exception as e:
            print(f"[scheduler] failed to drop apscheduler_jobs tables: {e}")
    if clear_table or removed:
        print("[scheduler] job store reset requested; jobs cleared")


# ──────────────────────────────────────────────────────────────────────────────
# Utils
# ──────────────────────────────────────────────────────────────────────────────

def _get_user(user_id: int) -> User | None:
    with SessionLocal() as s:
        return s.get(User, user_id)


def _audit(user_id: int, kind: str, payload: dict[str, Any] | None = None):
    """
    Record a lightweight audit entry for scheduled jobs.
    JobAudit schema uses (job_name, status, payload, error), so we store user_id in payload.
    """
    with SessionLocal() as s:
        body = {"user_id": user_id}
        if payload:
            try:
                body.update(payload)
            except Exception:
                body["payload"] = payload
        s.add(JobAudit(job_name=kind, status="ok", payload=body))
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


def _coaching_enabled(session, user_id: int) -> bool:
    pref = (
        session.query(UserPreference)
        .filter(
            UserPreference.user_id == user_id,
            UserPreference.key.in_(AUTO_PROMPT_PREF_KEYS),
        )
        .order_by(UserPreference.updated_at.desc())  # prefer most recent if both exist
        .first()
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
        tp_type = "ad_hoc"  # fallback if not matched below
        if day == "monday":
            monday.start_weekstart(user)
            tp_type = "weekstart"
        elif day == "tuesday":
            tuesday.send_tuesday_check(user)
            tp_type = "adjust"
        elif day == "wednesday":
            wednesday.send_midweek_check(user)
            tp_type = "adjust"
        elif day == "thursday":
            thursday.send_thursday_boost(user)
            tp_type = "adjust"
        elif day == "friday":
            friday.send_boost(user)
            tp_type = "adjust"
        elif day == "sunday":
            sunday.send_sunday_review(user)
            tp_type = "wrap"
        else:
            print(f"[scheduler] unknown day prompt: {day}")
            return
        _audit(user_id, f"auto_prompt_{day}", {})
    except Exception as e:
        print(f"[scheduler] {day} prompt failed for user {user_id}: {e}")


def _next_monday_anchor(user: User, hour: int, minute: int) -> datetime:
    """Return the next Monday at hour:minute in the user's timezone (today if still upcoming)."""
    tz = _tz(user)
    now = datetime.now(tz)
    days_ahead = (0 - now.weekday()) % 7  # Monday=0
    anchor_date = (now + timedelta(days=days_ahead)).date()
    anchor_dt = datetime(anchor_date.year, anchor_date.month, anchor_date.day, hour, minute, tzinfo=tz)
    if anchor_dt <= now:
        anchor_dt = anchor_dt + timedelta(days=7)
    return anchor_dt


def _schedule_prompt_for_user(user: User, day: str, dow: str, hour: int, minute: int, start_date: datetime | None = None):
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
        start_date=start_date,
    )
    sd_txt = f", start={start_date.isoformat()}" if start_date else ""
    print(f"[scheduler] scheduled {day} prompt for user {user.id} at {hour:02d}:{minute:02d} ({tz}{sd_txt})")


def _unschedule_prompts_for_user(user_id: int):
    job_ids = [f"auto_prompt_{day}_{user_id}" for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "sunday")]
    for job_id in job_ids:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    print(f"[scheduler] unscheduled all prompts for user {user_id}")


def _run_fast_cycle(user_id: int, start_ts: datetime, fast_minutes: int, offset: int = 0):
    """
    Fast mode runner: rotate through day prompts every fast_minutes in order.
    """
    with SessionLocal() as s:
        user = s.get(User, user_id)
    tz = _tz(user) if user else zoneinfo.ZoneInfo("UTC")
    now = datetime.now(tz)
    elapsed = max(0, (now - start_ts).total_seconds() / 60.0)
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "sunday")
    idx = (int(elapsed // fast_minutes) + offset) % len(days)
    day = days[idx]
    _run_day_prompt(user_id, day)


def _schedule_prompts_for_user(
    user: User,
    defaults: dict[str, tuple[int, int]],
    session,
    fast_minutes: int | None = None,
) -> None:
    # Skip if user not enabled
    if not _coaching_enabled(session, user.id):
        _unschedule_prompts_for_user(user.id)
        return
    # If fast mode requested, schedule each day as interval jobs (2m) instead of daily cron.
    if fast_minutes:
        _unschedule_prompts_for_user(user.id)
        tz = _tz(user)
        now = datetime.now(tz)
        days = ("monday", "tuesday", "wednesday", "thursday", "friday", "sunday")
        interval_minutes = fast_minutes * len(days)
        # Kickoff fires immediately; start Monday after fast_minutes, then every fast_minutes thereafter.
        for idx, day in enumerate(days):
            job_id = f"auto_prompt_{day}_{user.id}"
            start_offset = timedelta(minutes=(idx + 1) * fast_minutes)
            scheduler.add_job(
                _run_day_prompt,
                trigger="interval",
                minutes=interval_minutes,
                start_date=now + start_offset,
                args=[user.id, day],
                id=job_id,
                replace_existing=True,
                misfire_grace_time=3600,
                timezone=tz,
            )
            print(
                f"[scheduler] fast job {job_id} start={now + start_offset} interval={interval_minutes}m offset={start_offset}"
            )
        print(f"[scheduler] scheduled FAST prompts every {interval_minutes}m (start offset {fast_minutes}m, 2m spacing) for user {user.id} ({tz})")
        return
    # Ensure first scheduled prompt is the Monday weekstart after enabling (avoid midweek out-of-sequence)
    mon_hour, mon_min = _user_pref_time(session, user.id, "monday") or defaults.get("monday", (8, 0))
    anchor_monday = _next_monday_anchor(user, mon_hour, mon_min)
    dow_idx = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "sunday": 6}
    anchor_date = anchor_monday.date()
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
        offset_days = dow_idx.get(day, 0)
        start_dt_date = anchor_date + timedelta(days=offset_days)
        tz = _tz(user)
        start_date = datetime(
            start_dt_date.year,
            start_dt_date.month,
            start_dt_date.day,
            pref_time[0],
            pref_time[1],
            tzinfo=tz,
        )
        _schedule_prompt_for_user(user, day, dow, pref_time[0], pref_time[1], start_date=start_date)


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


def enable_coaching(user_id: int, fast_minutes: int | None = None) -> bool:
    """Enable coaching prompts for a user and schedule them. Returns True on success."""
    defaults = _default_times()
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            return False
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key.in_(AUTO_PROMPT_PREF_KEYS))
            .order_by(UserPreference.updated_at.desc())
            .first()
        )
        key = AUTO_PROMPT_PREF_KEYS[0]
        if pref:
            pref.key = key
            pref.value = "1"
        else:
            s.add(UserPreference(user_id=user_id, key=key, value="1"))
        s.commit()
        # Trigger kickoff before scheduling prompts so the first Monday follows kickoff.
        try:
            kickoff.start_kickoff(u, notes="auto kickoff: coaching enabled")
        except Exception as e:
            print(f"[scheduler] kickoff on coaching enable failed for user {user_id}: {e}")
        _schedule_prompts_for_user(u, defaults, s, fast_minutes=fast_minutes)
    return True


def disable_coaching(user_id: int) -> bool:
    """Disable coaching prompts for a user and unschedule them. Returns True on success."""
    defaults = _default_times()
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            return False
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key.in_(AUTO_PROMPT_PREF_KEYS))
            .order_by(UserPreference.updated_at.desc())
            .first()
        )
        key = AUTO_PROMPT_PREF_KEYS[0]
        if pref:
            pref.key = key
            pref.value = "0"
            s.commit()
        _unschedule_prompts_for_user(user_id)
    return True


def reset_coaching_jobs(user_id: int) -> bool:
    """Remove all scheduled coaching prompt jobs (does not change preference)."""
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
