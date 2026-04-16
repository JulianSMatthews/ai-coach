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
FIRST_DAY_SENT_AT_PREF_KEY = "coaching_first_day_sent_at"
LEGACY_FIRST_DAY_PENDING_PREF_KEY = "coaching_first_day_pending"
PENDING_DAY_PROMPT_PREF_KEY = "coaching_pending_day_prompt"
PENDING_DAY_PROMPT_SET_AT_PREF_KEY = "coaching_pending_day_prompt_set_at"
OUT_OF_SESSION_DAY_SEND_COUNT_PREF_KEY = "out_of_session_day_send_count"
OUT_OF_SESSION_GENERAL_SEND_COUNT_PREF_KEY = "out_of_session_general_send_count"
LEGACY_DAY_PROMPTS_RETIRED = True
LEGACY_DAY_PROMPT_KEYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
from .nudges import (
    send_message,
    send_whatsapp_template,
    _get_session_reopen_sid,
    _get_day_reopen_sid,
    ensure_quick_reply_templates,
    build_session_reopen_template_variables,
    build_day_reopen_template_variables,
    get_default_session_reopen_message_text,
    get_default_day_reopen_message_text,
    get_default_session_reopen_coach_name,
)
from .debug_utils import debug_log, debug_enabled
from .llm import compose_prompt
from .coaching_delivery import preferred_channel_for_user
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
        .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
        .first()
    )


def _set_user_pref(session, user_id: int, key: str, value: str) -> None:
    rows = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == key)
        .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
        .all()
    )
    pref = rows[0] if rows else None
    if pref:
        pref.value = value
        for stale in rows[1:]:
            try:
                session.delete(stale)
            except Exception:
                pass
    else:
        session.add(UserPreference(user_id=user_id, key=key, value=value))


def _delete_user_pref_keys(session, user_id: int, keys: list[str] | tuple[str, ...]) -> None:
    rows = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == int(user_id), UserPreference.key.in_(list(keys)))
        .all()
    )
    for row in rows:
        try:
            session.delete(row)
        except Exception:
            pass


def _clear_coaching_runtime_state(session, user_id: int) -> None:
    """
    Remove runtime coaching flow state that can become stale across disable/enable cycles.
    This intentionally excludes long-lived profile/settings prefs.
    """
    runtime_keys = [
        # Deferred day-flow state
        PENDING_DAY_PROMPT_PREF_KEY,
        PENDING_DAY_PROMPT_SET_AT_PREF_KEY,
        # 24h template cadence + counters
        "out_of_session_day_last_sent_at",
        OUT_OF_SESSION_DAY_SEND_COUNT_PREF_KEY,
        "out_of_session_last_sent_at",
        OUT_OF_SESSION_GENERAL_SEND_COUNT_PREF_KEY,
        # Active chat/selection states
        "habit_setup_state",
        "sunday_state",
        "weekstart_state",
        "general_support_state",
    ]
    rows = (
        session.query(UserPreference)
        .filter(
            UserPreference.user_id == int(user_id),
            UserPreference.key.in_(runtime_keys),
        )
        .all()
    )
    for row in rows:
        try:
            session.delete(row)
        except Exception:
            pass


def _last_inbound_at(session, user_id: int) -> datetime | None:
    row = (
        session.query(MessageLog.created_at)
        .filter(MessageLog.user_id == user_id, MessageLog.direction == "inbound")
        .order_by(desc(MessageLog.created_at))
        .first()
    )
    return row[0] if row else None


def _to_utc_naive(dt: datetime | None) -> datetime | None:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        return dt
    try:
        return dt.astimezone(zoneinfo.ZoneInfo("UTC")).replace(tzinfo=None)
    except Exception:
        return dt.replace(tzinfo=None)


def _parse_pref_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _to_utc_naive(parsed)
    except Exception:
        return None


def _first_day_sent_at(session, user_id: int) -> datetime | None:
    pref = _get_user_pref(session, int(user_id), FIRST_DAY_SENT_AT_PREF_KEY)
    return _parse_pref_datetime(pref.value if pref else None)


def _coaching_day_key(day: str | None) -> str:
    raw = str(day or "").strip().lower()
    if raw in set(LEGACY_DAY_PROMPT_KEYS):
        return raw
    return "monday"


def _clear_retired_day_prompt_state(user_id: int, day_key: str | None = None) -> None:
    """Clear stale state left by the retired weekday prompt schedule."""
    try:
        with SessionLocal() as s:
            _delete_user_pref_keys(
                s,
                int(user_id),
                (
                    PENDING_DAY_PROMPT_PREF_KEY,
                    PENDING_DAY_PROMPT_SET_AT_PREF_KEY,
                    OUT_OF_SESSION_DAY_SEND_COUNT_PREF_KEY,
                    "out_of_session_day_last_sent_at",
                    "coaching_fast_minutes",
                ),
            )
            s.commit()
    except Exception:
        pass
    try:
        _audit(
            int(user_id),
            "legacy_day_prompt_retired",
            {"day": _coaching_day_key(day_key), "mode": "tracker_driven"},
        )
    except Exception:
        pass


def _outside_whatsapp_window(session, user: User, *, now_utc: datetime, after_hours: int) -> bool:
    last_inbound = _last_inbound_at(session, int(user.id))
    if not last_inbound:
        last_inbound = getattr(user, "last_inbound_message_at", None)
    last_inbound = _to_utc_naive(last_inbound)
    if not last_inbound:
        return False
    return (now_utc - last_inbound) >= timedelta(hours=max(1, int(after_hours)))


def _render_reopen_message_for_day(
    base_message: str | None,
    day: str,
    *,
    first_name: str | None = None,
    coach_name: str | None = None,
) -> str:
    day_label = _coaching_day_key(day).capitalize()
    raw = str(base_message or "").strip()
    if not raw:
        raw = (
        f"Your {day_label} coaching message is ready. "
        "Please tap below to continue your wellbeing journey."
        )
    coach = (str(coach_name or "").strip() or get_default_session_reopen_coach_name())
    fname = str(first_name or "").strip()
    rendered = raw.replace("{day}", day_label)
    rendered = rendered.replace("{first_name}", fname or "there")
    rendered = rendered.replace("{coach_name}", coach)
    return rendered


def send_out_of_session_messages() -> None:
    """
    Send a template message when a user has been inactive for >24 hours.
    Uses TWILIO_REOPEN_CONTENT_SID and the admin-configured message body.
    """
    after_hours = int(os.getenv("OUT_OF_SESSION_AFTER_HOURS", "24") or "24")
    cooldown_hours = int(os.getenv("OUT_OF_SESSION_COOLDOWN_HOURS", str(after_hours)) or str(after_hours))
    general_max_sends_raw = (os.getenv("OUT_OF_SESSION_GENERAL_MAX_SENDS") or "0").strip()
    try:
        general_max_sends = max(0, int(general_max_sends_raw))
    except Exception:
        general_max_sends = 0
    now = datetime.utcnow()
    with SessionLocal() as s:
        enabled, configured_message = _get_messaging_settings(s)
        if not enabled:
            return
        reopen_message = (configured_message or "").strip() or get_default_session_reopen_message_text()
        template_sid = _get_session_reopen_sid()
        if not template_sid:
            try:
                ensure_quick_reply_templates(always_log=False)
            except Exception:
                pass
            template_sid = _get_session_reopen_sid()
            if not template_sid:
                debug_log("out-of-session skipped: missing TWILIO_REOPEN_CONTENT_SID", tag="scheduler")
                return
        users = s.query(User).all()
        stats = {
            "users": 0,
            "missing_phone": 0,
            "onboarding_active": 0,
            "coaching_off": 0,
            "app_channel": 0,
            "no_inbound": 0,
            "inside_window": 0,
            "cooldown": 0,
            "max_reached": 0,
            "sent": 0,
            "failed": 0,
        }
        for user in users:
            stats["users"] += 1
            if not getattr(user, "phone", None):
                stats["missing_phone"] += 1
                continue
            if _user_onboarding_active(user.id):
                stats["onboarding_active"] += 1
                continue
            if not _coaching_enabled(s, user.id):
                stats["coaching_off"] += 1
                continue
            if _preferred_channel(s, int(user.id)) == "app":
                stats["app_channel"] += 1
                continue
            last_inbound = _last_inbound_at(s, user.id)
            if not last_inbound:
                last_inbound = getattr(user, "last_inbound_message_at", None)
            last_inbound = _to_utc_naive(last_inbound)
            if not last_inbound:
                stats["no_inbound"] += 1
                continue
            count_pref = _get_user_pref(s, int(user.id), OUT_OF_SESSION_GENERAL_SEND_COUNT_PREF_KEY)
            try:
                send_count = max(0, int((count_pref.value if count_pref else "0") or "0"))
            except Exception:
                send_count = 0
            if now - last_inbound < timedelta(hours=after_hours):
                # User replied and is back in-session: reset generic reopen send counter.
                if send_count:
                    _set_user_pref(s, int(user.id), OUT_OF_SESSION_GENERAL_SEND_COUNT_PREF_KEY, "0")
                    s.commit()
                stats["inside_window"] += 1
                continue
            pref = _get_user_pref(s, user.id, "out_of_session_last_sent_at")
            last_sent = _parse_pref_datetime(pref.value if pref else None)
            if last_sent and now - last_sent < timedelta(hours=cooldown_hours):
                stats["cooldown"] += 1
                continue
            if general_max_sends > 0 and send_count >= general_max_sends:
                stats["max_reached"] += 1
                continue
            try:
                send_whatsapp_template(
                    to=user.phone,
                    template_sid=template_sid,
                    variables=build_session_reopen_template_variables(
                        user_first_name=getattr(user, "first_name", None),
                        coach_name=None,
                        message_text=_render_reopen_message_for_day(
                            reopen_message,
                            datetime.now(_tz(user)).strftime("%A").lower(),
                            first_name=getattr(user, "first_name", None),
                            coach_name=None,
                        ),
                    ),
                    category="session-reopen",
                )
                _set_user_pref(s, user.id, "out_of_session_last_sent_at", now.isoformat())
                _set_user_pref(s, int(user.id), OUT_OF_SESSION_GENERAL_SEND_COUNT_PREF_KEY, str(send_count + 1))
                s.commit()
                stats["sent"] += 1
            except Exception as e:
                stats["failed"] += 1
                debug_log("out-of-session send failed", {"user_id": user.id, "error": repr(e)}, tag="scheduler")
        debug_log("out-of-session pass", stats, tag="scheduler")


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
    # Unified coaching send time: 08:00 local for every day.
    return {
        "sunday": (8, 0),
        "monday": (8, 0),
        "tuesday": (8, 0),
        "wednesday": (8, 0),
        "thursday": (8, 0),
        "friday": (8, 0),
        "saturday": (8, 0),
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
                defaults[day_key] = (8, 0)
    except Exception:
        pass
    return defaults


def _sync_global_schedule_to_unified_8am(session) -> None:
    """
    Normalize global schedule rows so UI + runtime both reflect unified 08:00 sends.
    Existing disabled rows stay disabled.
    """
    base = _base_default_times()
    rows = session.query(GlobalPromptSchedule).all()
    rows_by_day = {(getattr(r, "day_key", "") or "").strip().lower(): r for r in rows}
    changed = False
    for day_key in base.keys():
        row = rows_by_day.get(day_key)
        if row is None:
            session.add(
                GlobalPromptSchedule(
                    day_key=day_key,
                    time_local="08:00",
                    enabled=True,
                )
            )
            changed = True
            continue
        time_local = (getattr(row, "time_local", "") or "").strip()
        if time_local != "08:00":
            row.time_local = "08:00"
            changed = True
    if changed:
        session.commit()


def ensure_global_schedule_defaults() -> None:
    try:
        GlobalPromptSchedule.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        return
    try:
        with SessionLocal() as s:
            _sync_global_schedule_to_unified_8am(s)
    except Exception:
        pass


def _coaching_enabled(session, user_id: int) -> bool:
    # Prefer the canonical key first; fall back to legacy only if missing.
    # This avoids false negatives when both keys exist with conflicting values.
    coaching_pref = (
        session.query(UserPreference)
        .filter(
            UserPreference.user_id == user_id,
            UserPreference.key == "coaching",
        )
        .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
        .first()
    )
    if coaching_pref is not None:
        return str(coaching_pref.value or "").strip() == "1"
    legacy_pref = (
        session.query(UserPreference)
        .filter(
            UserPreference.user_id == user_id,
            UserPreference.key == "auto_daily_prompts",
        )
        .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
        .first()
    )
    return bool(legacy_pref and str(legacy_pref.value or "").strip() == "1")


def _preferred_channel(session, user_id: int) -> str:
    try:
        return preferred_channel_for_user(session, int(user_id))
    except Exception:
        return "whatsapp"


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
    """Retired weekday day-flow runner kept for stale jobs."""
    day_key = _coaching_day_key(day)
    _clear_retired_day_prompt_state(user_id, day_key)
    debug_log(
        f"skipped retired {day_key} prompt for user {user_id}; tracker-driven Gia flow is active",
        tag="scheduler",
    )



def _run_first_day_coaching_if_needed(user: User, day: str) -> bool:
    return False



def _run_day_prompt(user_id: int, day: str):
    """Retired weekday day-flow enqueue path kept for stale APScheduler jobs."""
    day_key = _coaching_day_key(day)
    _clear_retired_day_prompt_state(user_id, day_key)
    _unschedule_prompts_for_user(user_id)
    debug_log(
        f"skipped retired {day_key} prompt for user {user_id}; tracker-driven Gia flow is active",
        tag="scheduler",
    )



def _run_first_day_catchup(user_id: int, scheduled_day: str) -> None:
    """Retired one-off first-day catch-up runner kept for stale jobs."""
    _clear_retired_day_prompt_state(int(user_id), scheduled_day)
    _unschedule_prompts_for_user(int(user_id))



def _schedule_first_day_catchup_if_due(
    user: User,
    session,
    defaults: dict[str, tuple[int, int] | None],
) -> None:
    """First-day scheduled prompts are retired."""
    return None



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
    """Weekday prompt scheduling is retired."""
    return None



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
    """Fast-mode weekday prompt rotation is retired."""
    _clear_retired_day_prompt_state(int(user_id), None)
    _unschedule_prompts_for_user(int(user_id))



def _schedule_prompts_for_user(
    user: User,
    defaults: dict[str, tuple[int, int] | None],
    session,
    fast_minutes: int | None = None,
) -> None:
    if _coaching_enabled(session, user.id):
        try:
            _seed_weekly_focus_for_coaching_enable(session, user)
        except Exception as e:
            print(f"[scheduler] weekly focus seed failed for user {user.id}: {e}")
    _unschedule_prompts_for_user(user.id)
    debug_log(
        f"weekday prompt scheduling retired for user {user.id}; no APScheduler day jobs created",
        tag="scheduler",
    )



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
    """Retire legacy weekday prompt jobs for all users."""
    with SessionLocal() as s:
        users = s.query(User).all()
        for u in users:
            _unschedule_prompts_for_user(int(u.id))
            _delete_user_pref_keys(
                s,
                int(u.id),
                (
                    PENDING_DAY_PROMPT_PREF_KEY,
                    PENDING_DAY_PROMPT_SET_AT_PREF_KEY,
                    OUT_OF_SESSION_DAY_SEND_COUNT_PREF_KEY,
                    "out_of_session_day_last_sent_at",
                    "coaching_fast_minutes",
                ),
            )
        s.commit()
    debug_log("legacy weekday prompt jobs retired; schedule cleanup complete", tag="scheduler")


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
    """Enable coaching/Gia access for a user. Legacy weekday prompt jobs are not scheduled."""
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            return False
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key.in_(AUTO_PROMPT_PREF_KEYS))
            .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
            .first()
        )
        key = AUTO_PROMPT_PREF_KEYS[0]
        if pref:
            pref.key = key
            pref.value = "1"
        else:
            s.add(UserPreference(user_id=user_id, key=key, value="1"))
        legacy_pending = _get_user_pref(s, user_id, LEGACY_FIRST_DAY_PENDING_PREF_KEY)
        if legacy_pending:
            s.delete(legacy_pending)
        fast_pref_rows = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "coaching_fast_minutes")
            .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
            .all()
        )
        for pref_row in fast_pref_rows:
            try:
                s.delete(pref_row)
            except Exception:
                pass
        _delete_user_pref_keys(
            s,
            int(user_id),
            (
                PENDING_DAY_PROMPT_PREF_KEY,
                PENDING_DAY_PROMPT_SET_AT_PREF_KEY,
                OUT_OF_SESSION_DAY_SEND_COUNT_PREF_KEY,
                "out_of_session_day_last_sent_at",
            ),
        )
        set_virtual_mode(s, user_id, enabled=False)
        try:
            _seed_weekly_focus_for_coaching_enable(s, u)
        except Exception as e:
            print(f"[scheduler] weekly focus seed failed for user {user_id}: {e}")
        s.commit()
        _unschedule_prompts_for_user(user_id)
    return True


def disable_coaching(user_id: int) -> bool:
    """Disable coaching/Gia access for a user and clear legacy jobs. Returns True on success."""
    with SessionLocal() as s:
        u = s.get(User, user_id)
        if not u:
            return False
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key.in_(AUTO_PROMPT_PREF_KEYS))
            .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
            .first()
        )
        key = AUTO_PROMPT_PREF_KEYS[0]
        if pref:
            pref.key = key
            pref.value = "0"
        fast_pref_rows = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "coaching_fast_minutes")
            .order_by(UserPreference.updated_at.is_(None), UserPreference.updated_at.desc(), UserPreference.id.desc())
            .all()
        )
        for pref_row in fast_pref_rows:
            try:
                s.delete(pref_row)
            except Exception:
                pass
        legacy_pending = _get_user_pref(s, user_id, LEGACY_FIRST_DAY_PENDING_PREF_KEY)
        if legacy_pending:
            s.delete(legacy_pending)
        _clear_coaching_runtime_state(s, int(user_id))
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
