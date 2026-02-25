# app/scheduler.py
from __future__ import annotations

from datetime import date, datetime, timedelta
import os
import zoneinfo
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor
from sqlalchemy import text, desc
import threading

from .config import settings
from .db import SessionLocal, engine, _table_exists, _is_postgres
from .models import (
    User,
    JobAudit,
    AssessSession,
    AssessmentRun,
    UserPreference,
    GlobalPromptSchedule,
    MessageLog,
    MessagingSettings,
)

# Preference key(s) for auto coaching prompts (new primary key: "coaching"; legacy: "auto_daily_prompts")
AUTO_PROMPT_PREF_KEYS = ("coaching", "auto_daily_prompts")
FIRST_DAY_PENDING_PREF_KEY = "coaching_first_day_pending"
FIRST_DAY_SENT_AT_PREF_KEY = "coaching_first_day_sent_at"
from .nudges import (
    send_message,
    send_whatsapp_template,
    _get_session_reopen_sid,
    build_session_reopen_template_variables,
    get_default_session_reopen_message_text,
)
from .debug_utils import debug_log, debug_enabled
from .llm import compose_prompt
from . import monday, tuesday, wednesday, thursday, friday, saturday, sunday, first_day
from .job_queue import enqueue_job, should_use_worker
from .programme_timeline import first_monday_on_or_after
from .weekly_plan import ensure_weekly_plan
from .reports_retention import run_reports_retention_from_env
from .virtual_clock import (
    advance_virtual_date_for_user,
    get_virtual_date,
    is_virtual_enabled,
    set_virtual_mode,
)

# ──────────────────────────────────────────────────────────────────────────────
# APScheduler setup
# ──────────────────────────────────────────────────────────────────────────────

# Use the shared SQLAlchemy engine to guarantee the same DB/connection settings.
jobstores = {"default": SQLAlchemyJobStore(engine=engine)}
try:
    _SCHEDULER_MAX_WORKERS = max(1, int((os.getenv("SCHEDULER_MAX_WORKERS") or "4").strip() or "4"))
except Exception:
    _SCHEDULER_MAX_WORKERS = 4
executors = {"default": ThreadPoolExecutor(_SCHEDULER_MAX_WORKERS)}
scheduler = AsyncIOScheduler(jobstores=jobstores, executors=executors, timezone="UTC")


_APSCHEDULER_TABLES_READY = False
_APSCHEDULER_TABLES_LOCK = threading.Lock()


def _apscheduler_debug() -> bool:
    return debug_enabled()


def ensure_apscheduler_tables() -> None:
    global _APSCHEDULER_TABLES_READY
    if _APSCHEDULER_TABLES_READY:
        try:
            with engine.begin() as conn:
                if _table_exists(conn, "apscheduler_jobs"):
                    return
        except Exception:
            return
        # Table was dropped after we marked ready; force recreate.
        _APSCHEDULER_TABLES_READY = False
    with _APSCHEDULER_TABLES_LOCK:
        if _APSCHEDULER_TABLES_READY:
            try:
                with engine.begin() as conn:
                    if _table_exists(conn, "apscheduler_jobs"):
                        return
            except Exception:
                return
            _APSCHEDULER_TABLES_READY = False
        if _apscheduler_debug():
            try:
                url_safe = engine.url.render_as_string(hide_password=True)
            except Exception:
                url_safe = "<unknown>"
            print(f"[scheduler][debug] ensure_apscheduler_tables start db={url_safe}")
        try:
            with engine.begin() as conn:
                exists = _table_exists(conn, "apscheduler_jobs")
                if _apscheduler_debug():
                    print(f"[scheduler][debug] apscheduler_jobs exists={exists}")
                if exists:
                    _APSCHEDULER_TABLES_READY = True
                    return
                if _is_postgres():
                    if _apscheduler_debug():
                        print("[scheduler][debug] creating apscheduler_jobs (postgres)")
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS apscheduler_jobs (
                                id VARCHAR(191) NOT NULL,
                                next_run_time DOUBLE PRECISION,
                                job_state BYTEA NOT NULL,
                                PRIMARY KEY (id)
                            )
                            """
                        )
                    )
                else:
                    if _apscheduler_debug():
                        print("[scheduler][debug] creating apscheduler_jobs (sqlite)")
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS apscheduler_jobs (
                                id VARCHAR(191) NOT NULL,
                                next_run_time REAL,
                                job_state BLOB NOT NULL,
                                PRIMARY KEY (id)
                            )
                            """
                        )
                    )
                try:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS apscheduler_jobs_next_run_time_idx ON apscheduler_jobs (next_run_time)"
                        )
                    )
                except Exception:
                    pass
        except Exception as e:
            print(f"[scheduler] failed to ensure apscheduler_jobs table: {e}")
            return
        _APSCHEDULER_TABLES_READY = True
        if _apscheduler_debug():
            print("[scheduler][debug] ensure_apscheduler_tables done")


def _safe_add_job(*args, **kwargs):
    """Ensure APScheduler tables exist before adding jobs, and retry once if missing."""
    if _apscheduler_debug():
        job_id = kwargs.get("id")
        print(f"[scheduler][debug] add_job start id={job_id}")
    try:
        ensure_apscheduler_tables()
        return scheduler.add_job(*args, **kwargs)
    except Exception as e:
        msg = str(e).lower()
        if "apscheduler_jobs" in msg or "undefinedtable" in msg or "relation" in msg:
            try:
                ensure_apscheduler_tables()
                return scheduler.add_job(*args, **kwargs)
            except Exception as e2:
                print(f"[scheduler] add_job failed after ensuring table: {e2}")
                raise
        print(f"[scheduler] add_job failed: {e}")
        raise


def start_scheduler():
    ensure_apscheduler_tables()
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
        # Table was dropped; ensure future calls re-create it.
        global _APSCHEDULER_TABLES_READY
        _APSCHEDULER_TABLES_READY = False
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


def _ensure_messaging_settings_table() -> None:
    try:
        MessagingSettings.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass


def _get_messaging_settings(session) -> tuple[bool, str | None]:
    _ensure_messaging_settings_table()
    row = session.query(MessagingSettings).order_by(MessagingSettings.id.asc()).first()
    if not row:
        return False, None
    return bool(row.out_of_session_enabled), (row.out_of_session_message or None)


def _get_user_pref(session, user_id: int, key: str) -> UserPreference | None:
    return (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == key)
        .order_by(UserPreference.updated_at.desc())
        .first()
    )


def _set_user_pref(session, user_id: int, key: str, value: str) -> None:
    pref = _get_user_pref(session, user_id, key)
    if pref:
        pref.value = value
    else:
        session.add(UserPreference(user_id=user_id, key=key, value=value))


def _last_inbound_at(session, user_id: int) -> datetime | None:
    row = (
        session.query(MessageLog.created_at)
        .filter(MessageLog.user_id == user_id, MessageLog.direction == "inbound")
        .order_by(desc(MessageLog.created_at))
        .first()
    )
    return row[0] if row else None


def _parse_pref_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def send_out_of_session_messages() -> None:
    """
    Send a template message when a user has been inactive for >24 hours.
    Uses TWILIO_REOPEN_CONTENT_SID and the admin-configured message body.
    """
    after_hours = int(os.getenv("OUT_OF_SESSION_AFTER_HOURS", "24") or "24")
    cooldown_hours = int(os.getenv("OUT_OF_SESSION_COOLDOWN_HOURS", str(after_hours)) or str(after_hours))
    now = datetime.utcnow()
    with SessionLocal() as s:
        enabled, message = _get_messaging_settings(s)
        if not enabled:
            return
        reopen_message = (message or "").strip() or get_default_session_reopen_message_text()
        template_sid = _get_session_reopen_sid()
        if not template_sid:
            debug_log("out-of-session skipped: missing TWILIO_REOPEN_CONTENT_SID", tag="scheduler")
            return
        users = s.query(User).all()
        for user in users:
            if not getattr(user, "phone", None):
                continue
            if _user_onboarding_active(user.id):
                continue
            if not _coaching_enabled(s, user.id):
                continue
            last_inbound = _last_inbound_at(s, user.id)
            if not last_inbound:
                continue
            if now - last_inbound < timedelta(hours=after_hours):
                continue
            pref = _get_user_pref(s, user.id, "out_of_session_last_sent_at")
            last_sent = _parse_pref_datetime(pref.value if pref else None)
            if last_sent and now - last_sent < timedelta(hours=cooldown_hours):
                continue
            try:
                send_whatsapp_template(
                    to=user.phone,
                    template_sid=template_sid,
                    variables=build_session_reopen_template_variables(
                        user_first_name=getattr(user, "first_name", None),
                        coach_name=None,
                        message_text=reopen_message,
                    ),
                    category="session-reopen",
                )
                _set_user_pref(s, user.id, "out_of_session_last_sent_at", now.isoformat())
                s.commit()
            except Exception as e:
                debug_log("out-of-session send failed", {"user_id": user.id, "error": repr(e)}, tag="scheduler")


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
        if not getattr(u, "first_assessment_completed", None):
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


def _coaching_anchor_date_local(session, user: User, tz: zoneinfo.ZoneInfo) -> date | None:
    """
    Resolve the local completion day to anchor first-day coaching.
    Order: first_assessment_completed -> latest assessment run times -> user.created_on.
    """
    user_id = int(getattr(user, "id", 0) or 0)
    if user_id <= 0:
        return None
    completed = getattr(user, "first_assessment_completed", None)
    if isinstance(completed, datetime):
        try:
            return completed.astimezone(tz).date()
        except Exception:
            return completed.date()
    if isinstance(completed, date):
        return completed

    run = (
        session.query(
            AssessmentRun.finished_at,
            AssessmentRun.started_at,
            AssessmentRun.created_at,
        )
        .filter(AssessmentRun.user_id == user_id)
        .order_by(AssessmentRun.id.desc())
        .first()
    )
    if run:
        for candidate in run:
            if isinstance(candidate, datetime):
                try:
                    return candidate.astimezone(tz).date()
                except Exception:
                    return candidate.date()
            if isinstance(candidate, date):
                return candidate

    created_on = getattr(user, "created_on", None)
    if isinstance(created_on, datetime):
        try:
            return created_on.astimezone(tz).date()
        except Exception:
            return created_on.date()
    if isinstance(created_on, date):
        return created_on
    return None


def _base_default_times() -> dict[str, tuple[int, int]]:
    # Defaults in 24h: Sunday 18:00, Monday 08:00, Tuesday 19:00, Wednesday 08:00,
    # Thursday 19:00, Friday 08:00, Saturday 10:00
    return {
        "sunday": (18, 0),
        "monday": (8, 0),
        "tuesday": (19, 0),
        "wednesday": (8, 0),
        "thursday": (19, 0),
        "friday": (8, 0),
        "saturday": (10, 0),
    }


def _default_times() -> dict[str, tuple[int, int] | None]:
    defaults: dict[str, tuple[int, int] | None] = _base_default_times()
    try:
        with SessionLocal() as s:
            rows = s.query(GlobalPromptSchedule).all()
            for row in rows:
                day_key = (getattr(row, "day_key", "") or "").strip().lower()
                if not day_key or day_key not in defaults:
                    continue
                if not getattr(row, "enabled", True):
                    defaults[day_key] = None
                    continue
                time_val = (getattr(row, "time_local", "") or "").strip()
                if not time_val:
                    continue
                try:
                    hh, mm = time_val.split(":")
                    hh_i = int(hh); mm_i = int(mm)
                    if not (0 <= hh_i <= 23 and 0 <= mm_i <= 59):
                        raise ValueError()
                except Exception:
                    continue
                defaults[day_key] = (hh_i, mm_i)
    except Exception:
        pass
    return defaults


def ensure_global_schedule_defaults() -> None:
    try:
        GlobalPromptSchedule.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        return
    try:
        with SessionLocal() as s:
            existing = s.query(GlobalPromptSchedule).count()
            if existing:
                return
            for day_key, (hh, mm) in _base_default_times().items():
                s.add(
                    GlobalPromptSchedule(
                        day_key=day_key,
                        time_local=f"{hh:02d}:{mm:02d}",
                        enabled=True,
                    )
                )
            s.commit()
    except Exception:
        pass


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


def _user_fast_minutes(session, user_id: int) -> int | None:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == "coaching_fast_minutes")
        .order_by(UserPreference.updated_at.desc())
        .first()
    )
    if not pref or not pref.value:
        return None
    try:
        n = int(str(pref.value).strip())
        return max(1, n)
    except Exception:
        return None


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
    _safe_add_job(
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
    _safe_add_job(
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

def _run_day_prompt_inline(user_id: int, day: str):
    """Invoke the day-specific handler for a user."""
    virtual_mode = False
    with SessionLocal() as s:
        user = s.get(User, user_id)
        if user:
            try:
                virtual_mode = is_virtual_enabled(s, user_id)
            except Exception:
                virtual_mode = False
        if not user:
            return
    if _user_onboarding_active(user_id):
        print(f"[scheduler] skip {day} prompt for user {user_id}: onboarding active")
        return
    try:
        if _run_first_day_coaching_if_needed(user, day):
            return
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
        elif day == "saturday":
            saturday.send_saturday_keepalive(user)
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
    finally:
        if virtual_mode:
            try:
                next_date = advance_virtual_date_for_user(user_id, days=1)
                if next_date:
                    debug_log(
                        f"virtual date advanced for user {user_id} -> {next_date.isoformat()}",
                        tag="scheduler",
                    )
            except Exception as e:
                print(f"[scheduler] virtual date advance failed for user {user_id}: {e}")


def _run_first_day_coaching_if_needed(user: User, day: str) -> bool:
    user_id = int(getattr(user, "id", 0) or 0)
    if user_id <= 0:
        return False
    with SessionLocal() as s:
        pref = _get_user_pref(s, user_id, FIRST_DAY_PENDING_PREF_KEY)
        pending = bool(pref and str(pref.value or "").strip() == "1")
        if not pending:
            return False
        if day == "sunday":
            # If the user's first scheduled day is Sunday, keep the normal Sunday flow.
            _set_user_pref(s, user_id, FIRST_DAY_PENDING_PREF_KEY, "0")
            s.commit()
            return False
    try:
        first_day.send_first_day_coaching(user, scheduled_day=day)
    except Exception as e:
        print(f"[scheduler] first-day coaching prompt failed for user {user_id}: {e}")
        # Keep pending flag as-is so we can retry on the next scheduled day.
        return False
    with SessionLocal() as s:
        _set_user_pref(s, user_id, FIRST_DAY_PENDING_PREF_KEY, "0")
        _set_user_pref(s, user_id, FIRST_DAY_SENT_AT_PREF_KEY, datetime.utcnow().isoformat())
        s.commit()
    _audit(user_id, "auto_prompt_first_day", {"day": day})
    return True


def _run_day_prompt(user_id: int, day: str):
    """Enqueue or run day-specific handler for a user."""
    with SessionLocal() as s:
        user = s.get(User, user_id)
    if not user:
        # Stale scheduler job for a deleted/reset user: unschedule all day jobs for this id.
        print(f"[scheduler] skip {day} prompt for missing user {user_id}; unscheduling stale jobs")
        _unschedule_prompts_for_user(user_id)
        return
    if _user_onboarding_active(user_id):
        print(f"[scheduler] skip {day} prompt for user {user_id}: onboarding active")
        return
    if should_use_worker():
        job_id = enqueue_job("day_prompt", {"user_id": user_id, "day": day}, user_id=user_id)
        print(f"[scheduler] enqueued {day} prompt for user {user_id} (job={job_id})")
        return
    _run_day_prompt_inline(user_id, day)


def _schedule_first_day_catchup_if_due(
    user: User,
    session,
    defaults: dict[str, tuple[int, int] | None],
) -> None:
    """
    If first-day coaching is pending and the intended next-day slot is already in the past,
    schedule a one-off near-immediate run so first-day does not drift by an extra day/week.
    """
    user_id = int(getattr(user, "id", 0) or 0)
    if user_id <= 0:
        return
    pref = _get_user_pref(session, user_id, FIRST_DAY_PENDING_PREF_KEY)
    pending = bool(pref and str(pref.value or "").strip() == "1")
    if not pending:
        return
    tz = _tz(user)
    completed_local_day = _coaching_anchor_date_local(session, user, tz)
    if not isinstance(completed_local_day, date):
        return
    now_local = datetime.now(tz)
    expected_day = completed_local_day + timedelta(days=1)
    day_names = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    expected_day_key = day_names[expected_day.weekday()]
    if expected_day_key == "sunday":
        # Sunday starts follow the normal Sunday flow (no first-day override).
        return
    pref_time = _user_pref_time(session, user_id, expected_day_key)
    default_time = defaults.get(expected_day_key)
    scheduled_time = pref_time or default_time
    if scheduled_time is None:
        return
    hh, mm = scheduled_time
    due_now = False
    if now_local.date() > expected_day:
        due_now = True
    elif now_local.date() == expected_day:
        due_now = (now_local.hour, now_local.minute) >= (hh, mm)
    if not due_now:
        return
    job_id = f"auto_prompt_first_day_catchup_{user_id}"
    try:
        scheduler.remove_job(job_id)
    except Exception:
        pass
    run_date = datetime.utcnow() + timedelta(minutes=1)
    _safe_add_job(
        _run_day_prompt,
        trigger="date",
        run_date=run_date,
        args=[user_id, expected_day_key],
        id=job_id,
        replace_existing=True,
        misfire_grace_time=3600,
        timezone="UTC",
    )
    debug_log(
        f"scheduled first-day catchup for user {user_id} day={expected_day_key} run_date={run_date.isoformat()}Z",
        tag="scheduler",
    )


def _next_weekday_occurrence(
    user: User,
    weekday_idx: int,
    hour: int,
    minute: int,
    earliest_date: date | None = None,
) -> datetime:
    """Return the next local occurrence for weekday_idx (Monday=0) at hour:minute on/after earliest_date."""
    tz = _tz(user)
    now = datetime.now(tz)
    base_day = earliest_date or now.date()
    days_ahead = (weekday_idx - base_day.weekday()) % 7
    run_day = base_day + timedelta(days=days_ahead)
    run_dt = datetime(run_day.year, run_day.month, run_day.day, hour, minute, tzinfo=tz)
    if run_dt <= now or run_day < base_day:
        run_dt = run_dt + timedelta(days=7)
    return run_dt


def _schedule_prompt_for_user(user: User, day: str, dow: str, hour: int, minute: int, start_date: datetime | None = None):
    tz = _tz(user)
    job_id = f"auto_prompt_{day}_{user.id}"
    _safe_add_job(
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
    debug_log(
        f"scheduled {day} prompt for user {user.id} at {hour:02d}:{minute:02d} ({tz}{sd_txt})",
        tag="scheduler",
    )


def _unschedule_prompts_for_user(user_id: int):
    job_ids = [
        f"auto_prompt_{day}_{user_id}"
        for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    ]
    job_ids.append(f"auto_prompt_first_day_catchup_{user_id}")
    for job_id in job_ids:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
    debug_log(f"unscheduled all prompts for user {user_id}", tag="scheduler")


def _run_fast_cycle(user_id: int, start_ts: datetime, fast_minutes: int, offset: int = 0):
    """
    Fast mode runner: rotate through day prompts every fast_minutes in order.
    """
    with SessionLocal() as s:
        user = s.get(User, user_id)
    tz = _tz(user) if user else zoneinfo.ZoneInfo("UTC")
    now = datetime.now(tz)
    elapsed = max(0, (now - start_ts).total_seconds() / 60.0)
    days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
    idx = (int(elapsed // fast_minutes) + offset) % len(days)
    day = days[idx]
    _run_day_prompt(user_id, day)


def _schedule_prompts_for_user(
    user: User,
    defaults: dict[str, tuple[int, int] | None],
    session,
    fast_minutes: int | None = None,
) -> None:
    # Skip if user not enabled
    if not _coaching_enabled(session, user.id):
        _unschedule_prompts_for_user(user.id)
        return
    try:
        _seed_weekly_focus_for_coaching_enable(session, user)
    except Exception as e:
        print(f"[scheduler] weekly focus seed failed for user {user.id}: {e}")
    resolved_fast = fast_minutes or _user_fast_minutes(session, user.id) or _fast_minutes_env()
    # If fast mode requested, schedule each day as interval jobs instead of daily cron.
    if resolved_fast:
        _unschedule_prompts_for_user(user.id)
        tz = _tz(user)
        now = datetime.now(tz)
        days = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        first_idx = (now.date().weekday() + 1) % len(days)  # next local day
        ordered_days = days[first_idx:] + days[:first_idx]
        interval_minutes = resolved_fast * len(days)
        # In fast mode, start on the next local day after activation, then rotate through each day.
        for idx, day in enumerate(ordered_days):
            job_id = f"auto_prompt_{day}_{user.id}"
            start_offset = timedelta(minutes=(idx + 1) * resolved_fast)
            _safe_add_job(
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
            debug_log(
                f"fast job {job_id} start={now + start_offset} interval={interval_minutes}m offset={start_offset}",
                tag="scheduler",
            )
        first_day = ordered_days[0] if ordered_days else "monday"
        print(
            f"[scheduler] scheduled FAST prompts every {interval_minutes}m "
            f"(start offset {resolved_fast}m, first_day={first_day}) for user {user.id} ({tz})"
        )
        return
    # Start next-day onward by default.
    # When first-day coaching is pending, anchor scheduling from the day after
    # assessment completion so delayed enablement does not push first-day out
    # by an extra day.
    tz = _tz(user)
    now_local = datetime.now(tz)
    today_local = now_local.date()
    tomorrow_local = today_local + timedelta(days=1)
    schedule_anchor_day = tomorrow_local
    try:
        first_day_pref = _get_user_pref(session, int(user.id), FIRST_DAY_PENDING_PREF_KEY)
        first_day_pending = bool(first_day_pref and str(first_day_pref.value or "").strip() == "1")
    except Exception:
        first_day_pending = False
    if first_day_pending:
        completed_local_day = _coaching_anchor_date_local(session, user, tz)
        if isinstance(completed_local_day, date):
            # Earliest valid day is assessment completion + 1; never schedule in the past.
            anchored_next_day = max(today_local, completed_local_day + timedelta(days=1))
            schedule_anchor_day = min(tomorrow_local, anchored_next_day)
    # Start each day prompt from the next local occurrence so bridge days are included.
    dow_idx = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
    for day, default_time in defaults.items():
        if default_time is None:
            continue
        hh_default, mm_default = default_time
        pref_time = _user_pref_time(session, user.id, day) or (hh_default, mm_default)
        dow = {
            "monday": "mon",
            "tuesday": "tue",
            "wednesday": "wed",
            "thursday": "thu",
            "friday": "fri",
            "saturday": "sat",
            "sunday": "sun",
        }.get(day)
        if not dow:
            continue
        earliest_day = schedule_anchor_day
        if day == "monday":
            earliest_day = first_monday_on_or_after(schedule_anchor_day) or schedule_anchor_day
        start_date = _next_weekday_occurrence(
            user,
            dow_idx.get(day, 0),
            pref_time[0],
            pref_time[1],
            earliest_date=earliest_day,
        )
        _schedule_prompt_for_user(user, day, dow, pref_time[0], pref_time[1], start_date=start_date)
    _schedule_first_day_catchup_if_due(user, session, defaults)
    print(f"[scheduler] scheduled weekly prompts for user {user.id} ({tz})")


def _seed_weekly_focus_for_coaching_enable(session, user: User) -> None:
    """
    Ensure at least one weekly focus exists as soon as coaching is enabled.
    This avoids Tue-Sun flows failing in the bridge period before first Monday.
    """
    reference_day = None
    if is_virtual_enabled(session, int(user.id)):
        reference_day = get_virtual_date(session, int(user.id))
    if reference_day is None:
        tz = _tz(user)
        reference_day = datetime.now(tz).date() + timedelta(days=1)
    ensure_weekly_plan(
        session,
        int(user.id),
        reference_day=reference_day,
        notes="auto-seeded on coaching enable",
    )
    # Persist seed immediately so bridge-day Sunday/Monday flows can always resolve it,
    # including fast mode where prompts fire soon after activation.
    session.commit()


def schedule_auto_daily_prompts():
    """Schedule day-specific prompts for all users based on their own preference."""
    defaults = _default_times()
    fast_minutes = _fast_minutes_env()
    with SessionLocal() as s:
        users = s.query(User).all()
        for u in users:
            # Skip if onboarding not complete
            if _user_onboarding_active(u.id):
                continue
            _schedule_prompts_for_user(u, defaults, s, fast_minutes=fast_minutes)


def schedule_out_of_session_messages():
    """Run a periodic check to send out-of-session template messages when needed."""
    interval_minutes = int(os.getenv("OUT_OF_SESSION_CHECK_MINUTES", "60") or "60")
    if interval_minutes <= 0:
        return
    try:
        _safe_add_job(
            send_out_of_session_messages,
            "interval",
            minutes=interval_minutes,
            id="out_of_session_check",
            replace_existing=True,
        )
    except Exception as e:
        print(f"[scheduler] failed to schedule out-of-session job: {e}")


def _reports_retention_clock_utc() -> tuple[int, int]:
    hour_raw = (os.getenv("REPORTS_RETENTION_HOUR_UTC") or "3").strip()
    minute_raw = (os.getenv("REPORTS_RETENTION_MINUTE_UTC") or "30").strip()
    try:
        hour = int(hour_raw)
    except Exception:
        hour = 3
    try:
        minute = int(minute_raw)
    except Exception:
        minute = 30
    hour = min(23, max(0, hour))
    minute = min(59, max(0, minute))
    return hour, minute


def run_reports_retention_job() -> None:
    result = run_reports_retention_from_env(dry_run=False)
    try:
        if result.get("skipped"):
            print(f"[scheduler] reports retention skipped ({result.get('reason')})")
        elif result.get("ok"):
            print(
                "[scheduler] reports retention complete "
                f"removed={result.get('files_removed', 0)} "
                f"reclaimed_mb={result.get('mb_reclaimed', 0)}"
            )
        else:
            print(f"[scheduler] reports retention failed: {result}")
    except Exception:
        print("[scheduler] reports retention completed (log formatting failed)")


def schedule_reports_retention() -> None:
    hour, minute = _reports_retention_clock_utc()
    try:
        _safe_add_job(
            run_reports_retention_job,
            trigger="cron",
            hour=hour,
            minute=minute,
            id="reports_retention_daily",
            replace_existing=True,
            misfire_grace_time=3600,
            timezone="UTC",
        )
        debug_log(
            f"scheduled reports retention at {hour:02d}:{minute:02d} UTC",
            tag="scheduler",
        )
    except Exception as e:
        print(f"[scheduler] failed to schedule reports retention job: {e}")


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
        was_enabled = bool(pref and str(pref.value or "").strip() == "1")
        key = AUTO_PROMPT_PREF_KEYS[0]
        if pref:
            pref.key = key
            pref.value = "1"
        else:
            s.add(UserPreference(user_id=user_id, key=key, value="1"))
        if not was_enabled:
            _set_user_pref(s, user_id, FIRST_DAY_PENDING_PREF_KEY, "1")
            _set_user_pref(s, user_id, FIRST_DAY_SENT_AT_PREF_KEY, "")
        # Persist per-user fast mode so it survives restarts and global schedule changes.
        fast_pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "coaching_fast_minutes")
            .order_by(UserPreference.updated_at.desc())
            .first()
        )
        if fast_minutes:
            tz = _tz(u)
            local_today = datetime.now(tz).date()
            virtual_start = local_today + timedelta(days=1)
            if fast_pref:
                fast_pref.value = str(max(1, int(fast_minutes)))
            else:
                s.add(
                    UserPreference(
                        user_id=user_id,
                        key="coaching_fast_minutes",
                        value=str(max(1, int(fast_minutes))),
                    )
                )
            set_virtual_mode(
                s,
                user_id,
                enabled=True,
                start_date=virtual_start,
                keep_existing_date=False,
            )
        else:
            if fast_pref:
                s.delete(fast_pref)
            set_virtual_mode(s, user_id, enabled=False)
        s.commit()
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
        fast_pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "coaching_fast_minutes")
            .order_by(UserPreference.updated_at.desc())
            .first()
        )
        if fast_pref:
            s.delete(fast_pref)
        _set_user_pref(s, user_id, FIRST_DAY_PENDING_PREF_KEY, "0")
        set_virtual_mode(s, user_id, enabled=False)
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
        _safe_add_job(
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
        _safe_add_job(
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
        _safe_add_job(
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
        _safe_add_job(
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

    _safe_add_job(
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
