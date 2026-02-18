# app/api.py
# PATCH — proper API module + robust Twilio webhook (2025-09-04)
# PATCH — 2025-09-11: Add minimal superuser admin endpoints (create user, start, status, assessment)
# PATCH — 2025-09-11: Admin hardening + WhatsApp admin commands (token+DB check; create/start/status/assessment)
from __future__ import annotations
# Render sync marker: force fresh API build/deploy from latest commit.

import os
import json
import asyncio
import time
import math
import bisect
import urllib.request
import secrets
import hashlib
import base64
import re
import subprocess
import sys
import threading
import shutil
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta, date
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from fastapi import FastAPI, APIRouter, Request, Response, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text, select, desc, func, or_
from pathlib import Path 
from typing import Optional

# Ensure .env is loaded even when running uvicorn directly (without run.py)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(override=False)
except Exception:
    pass

from .db import engine, SessionLocal, _is_postgres
from .debug_utils import debug_log
from .models import (
    Base,
    User,
    MessageLog,
    AssessSession,
    AssessmentRun,
    AssessmentNarrative,
    AssessmentTurn,
    Club,
    ADMIN_ROLE_MEMBER,
    ADMIN_ROLE_CLUB,
    ADMIN_ROLE_GLOBAL,
    WeeklyFocus,
    WeeklyFocusKR,
    UserPreference,
    Touchpoint,
    TouchpointKR,
    EngagementEvent,
    ContentPromptGeneration,
    ContentLibraryItem,
    ContentPromptTemplate,
    ContentPromptSettings,
    AuthOtp,
    AuthSession,
    OKRObjective,
    OKRObjectiveReview,
    OKRKeyResult,
    OKRKrEntry,
    OKRKrHabitStep,
    OKRFocusStack,
    TwilioTemplate,
    GlobalPromptSchedule,
    MessagingSettings,
    Concept,
    KBSnippet,
    KBVector,
    ScriptRun,
    PromptTemplate,
    PromptSettings,
    PromptTemplateVersionLog,
    LLMPromptLog,
    UsageEvent,
    JobAudit,
    BackgroundJob,
    UserConceptState,
    PillarResult,
    PsychProfile,
    CheckIn,
    PreferenceInferenceAudit,
)  # ensure model registered for metadata
from . import monday, wednesday, thursday, friday, saturday, weekflow, tuesday, sunday, kickoff, admin_routes, general_support
from . import psych
from . import coachmycoach
from . import scheduler
from .nudges import send_whatsapp, send_whatsapp_media, send_sms
from .checkins import record_checkin
from . import prompts as prompts_module
from .prompts import build_prompt, assessment_scores_prompt, okr_narrative_prompt, coaching_approach_prompt, assessor_system_prompt
from .llm import embed_text
from .podcast import generate_podcast_audio_for_voice
from .usage import (
    get_tts_usage_summary,
    get_llm_usage_summary,
    get_whatsapp_usage_summary,
    get_usage_settings,
    save_usage_settings,
    estimate_tokens,
    resolve_llm_rates,
    log_usage_event,
)
from .usage_rates import fetch_provider_rates
from .okr import ensure_cycle
from .reporting import (
    generate_detailed_report_pdf_by_user,
    generate_assessment_summary_pdf,
    generate_assessment_report_pdf,
    generate_assessment_dashboard_html,
    generate_global_users_html,
    generate_club_users_html,
    user_schedule_report,
    generate_schedule_report_html,
    generate_llm_prompt_log_report_html,
    build_assessment_dashboard_data,
    build_progress_report_data,
    _reports_root_global,
)
from .reports_paths import resolve_reports_dir, resolve_reports_dir_with_source
from .job_queue import ensure_job_table, enqueue_job, should_use_worker, ensure_prompt_settings_schema
from .virtual_clock import get_virtual_date, get_virtual_now_for_user, set_virtual_mode

# Lazy import holder to avoid startup/reload ImportError if symbol is added later
_gen_okr_summary_report = None
try:
    from .reporting import generate_okr_summary_report as _gen_okr_summary_report  # type: ignore
except Exception:
    _gen_okr_summary_report = None

_gen_okr_summary_report_llm = None
try:
    from .reporting import generate_okr_summary_report_llm as _gen_okr_summary_report_llm  # type: ignore
except Exception:
    _gen_okr_summary_report_llm = None


def _normalize_reports_url(raw: str | None) -> str | None:
    """
    Return URL as stored by default.
    Optional read-time normalization can be enabled with
    NORMALIZE_REPORTS_URL_ON_READ=1.
    """
    if not raw:
        return None
    url = str(raw).strip()
    if not url:
        return None
    normalize_on_read = (os.getenv("NORMALIZE_REPORTS_URL_ON_READ") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not normalize_on_read:
        return url
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    path = parsed.path or ""
    if not path:
        return url
    normalized_path = path if path.startswith("/") else f"/{path}"
    if "/reports/" not in normalized_path:
        return url
    base = (_REPORTS_BASE or "").rstrip("/")
    if not base:
        return url
    def _is_local_host(host: str | None) -> bool:
        h = str(host or "").strip().lower()
        return h in {"localhost", "127.0.0.1", "0.0.0.0"} or h.endswith(".local")
    if parsed.netloc:
        base_host = urlparse(base).hostname
        raw_host = parsed.hostname
        # Preserve absolute non-local URLs if configured base is local/dev.
        if _is_local_host(base_host) and raw_host and not _is_local_host(raw_host):
            return url
        base_netloc = urlparse(base).netloc
        raw_netloc = parsed.netloc
        if base_netloc and raw_netloc == base_netloc:
            return url
    suffix = normalized_path
    if parsed.query:
        suffix += f"?{parsed.query}"
    if parsed.fragment:
        suffix += f"#{parsed.fragment}"
    return f"{base}{suffix}"

# Utility to robustly resolve the OKR summary generator, with diagnostics
def _resolve_okr_summary_gen():
    """Return callable generate_okr_summary_report or raise with useful diagnostics."""
    global _gen_okr_summary_report
    if _gen_okr_summary_report is not None:
        return _gen_okr_summary_report
    try:
        from . import reporting as _r
    except Exception as e:
        raise ImportError(f"Failed to import app.reporting: {e}")
    gen = getattr(_r, "generate_okr_summary_report", None)
    if callable(gen):
        _gen_okr_summary_report = gen
        return gen
    # Provide clear diagnostics of what's actually available
    okrish = [a for a in dir(_r) if "okr" in a.lower()]
    raise ImportError(
        "generate_okr_summary_report not found in app.reporting; "
        f"available attrs containing 'okr': {okrish}"
    )

def _resolve_okr_summary_gen_llm():
    """Return callable generate_okr_summary_report_llm or fallback to generate_okr_summary_report."""
    global _gen_okr_summary_report_llm
    if _gen_okr_summary_report_llm is not None:
        return _gen_okr_summary_report_llm
    try:
        from . import reporting as _r
        gen = getattr(_r, "generate_okr_summary_report_llm", None)
        if callable(gen):
            _gen_okr_summary_report_llm = gen
            return gen
    except Exception:
        pass
    return _resolve_okr_summary_gen()

ADMIN_USAGE = (
    "Admin commands:\n"
    "admin create <phone> <first_name> <surname>\n"
    "admin start [phone]\n"
    "admin status [phone]\n"
    "admin assessment [phone]\n"
    "admin progress [phone]\n"
    "admin llm-review [phone] [limit]\n"
    "admin detailed [phone]\n"
    "admin coaching [phone] on|off|faston|reset    # toggle scheduled coaching prompts (faston=every 2m test; reset clears jobs)\n"
    "admin vdate [phone] <YYYY-MM-DD|today|clear>  # set/clear virtual date for fast testing\n"
    "admin schedule [phone]           # show scheduled coaching prompts for user (HTML + summary)\n"
    "admin beta [phone] [live|beta|develop|clear]   # set prompt state override for testing\n"
    "admin prompt-audit [phone] <YYYY-MM-DD> [state] # generate prompt audit report for that user/date\n"
    "\nWeekly touchpoints (by day):\n"
    "admin monday [phone]\n"
    "admin tuesday [phone]\n"
    "admin wednesday [phone]\n"
    "admin thursday [phone]\n"
    "admin friday [phone]\n"
    "admin saturday [phone]\n"
    "admin sunday [phone]\n"
    "admin week [phone] <week_no>      # run full week flow (includes Sunday)\n"
    "\nReports:\n"
    "admin summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "admin okr-summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "admin okr-summaryllm [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "admin users\n"
    "\nExample: admin create +447700900123 Julian Matthews"
)

UNKNOWN_USER_NAME_PROMPT = (
    "Welcome to HealthSense. Before we begin, please reply with your first and last name "
    "(e.g., 'Sam Smith')."
)
UNKNOWN_USER_NAME_CONFIRM_PREFIX = "I captured your name as "
UNKNOWN_USER_NAME_CONFIRM_SUFFIX = (
    ". Reply YES to confirm, or reply with your first and last name again."
)

GLOBAL_USAGE = (
    "Global admin commands:\n"
    "global set club <club_id|slug>\n"
    "global set user <phone> <club_id|slug>\n"
    "global summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]\n"
    "global okr-summary [range]\n"
    "global okr-summaryllm [range]\n"
    "global users\n"
    "\nExample: global summary last30d"
)


ENV = os.getenv("ENV", "development").lower()

# Application start time (UK)
UK_TZ = ZoneInfo("Europe/London")
APP_START_DT = datetime.now(UK_TZ)
# Format: dd/mm/yy␠HH:MM:SS (UK local time)
APP_START_UK_STR = APP_START_DT.strftime("%d/%m/%y %H:%M:%S")

ROBOTS_TXT = "User-agent: *\nAllow: /\nDisallow: /admin\nDisallow: /reports\n"

def _uptime_seconds() -> int:
    try:
        from datetime import timezone as _tz, datetime as _dt
        return int((_dt.now(_tz.utc) - APP_START_DT).total_seconds())
    except Exception:
        return 0

# ──────────────────────────────────────────────────────────────────────────────
# Environment awareness (simple version)
# ──────────────────────────────────────────────────────────────────────────────
def _print_env_banner():
    try:
        print("\n" + "═" * 72)
        print(f"🚀 Starting HealthSense [{ENV.upper()}]")
        print(f"🕒 App start (UK): {APP_START_UK_STR}")
        print("═" * 72 + "\n")
    except Exception:
        pass

debug_log(f"🚀 app.api loaded: v-2025-09-04E (ENV={ENV})", tag="startup")

# Seed import 
from .seed import run_seed  # fallback

# Assessor entrypoints

def _dbg(msg: str):
    debug_log(msg, tag="webhook")

try:
    from .assessor import (
        start_combined_assessment,
        continue_combined_assessment,
        get_active_domain,
        send_menu_options,
        send_dashboard_link,
    )
    _dbg("[INFO] Correct assessor module imported successfully (module path: " +
         f"{start_combined_assessment.__module__})")
except Exception as e:
    _dbg(f"[ERROR] Failed to import assessors — using fallback: {e}")
    raise  # Let it crash loud during startup so you catch it immediately

app = FastAPI(title="AI Coach")
router = APIRouter()
_STARTUP_TASKS_DONE = threading.Event()


@app.on_event("startup")
async def _startup_init() -> None:
    try:
        from .nudges import ensure_quick_reply_templates

        def _bootstrap_quick_replies() -> None:
            try:
                ensure_quick_reply_templates(always_log=True)
            except Exception as e:
                print(f"[startup] Twilio quick replies failed: {e!r}")

        # Run bootstrap off the startup thread so we don't block port binding.
        threading.Thread(target=_bootstrap_quick_replies, daemon=True).start()
    except Exception as e:
        print(f"[startup] Twilio quick replies bootstrap skipped: {e!r}")
    # Wait for startup tasks (e.g., DB reset/seed) to finish before scheduler starts.
    try:
        wait_sec_raw = (os.getenv("STARTUP_TASKS_WAIT_SEC") or "30").strip()
        wait_secs = float(wait_sec_raw or "30")
    except Exception:
        wait_secs = 30.0
    if wait_secs > 0:
        debug_log(f"waiting for startup tasks (timeout={wait_secs}s)", tag="startup")
        try:
            await asyncio.to_thread(_STARTUP_TASKS_DONE.wait, wait_secs)
        except Exception:
            pass

    # Scheduler must start on the running event loop.
    try:
        try:
            scheduler.ensure_apscheduler_tables()
            debug_log("apscheduler tables ensured", tag="scheduler")
        except Exception as e:
            print(f"⚠️  ensure_apscheduler_tables failed: {e!r}")
        scheduler.start_scheduler()
        scheduler.schedule_auto_daily_prompts()
        scheduler.schedule_out_of_session_messages()
    except Exception as e:
        print(f"⚠️  Scheduler start failed: {e!r}")


# ──────────────────────────────────────────────────────────────────────────────
# Startup helpers
# ──────────────────────────────────────────────────────────────────────────────

def _predrop_legacy_tables():
    """Drop legacy tables (if any) that can block drop_all() via FKs."""
    legacy_tables = [
        "review_feedback",      # legacy; FK -> assessment_runs, blocks drop_all
        "concept_deltas",
        "concept_rubrics",
        "concept_clarifiers",
        "content_templates",
        "generation_runs",
        "edu_content",
    ]
    legacy_views = [
        "llm_prompt_logs_view",
    ]
    with engine.begin() as conn:
        for vw in legacy_views:
            try:
                conn.execute(text(f'DROP VIEW IF EXISTS "{vw}" CASCADE'))
            except Exception as e:
                print(f"⚠️  Pre-drop warning for view {vw}: {e}")
        for tbl in legacy_tables:
            try:
                conn.execute(text(f'DROP TABLE IF EXISTS "{tbl}" CASCADE'))
            except Exception as e:
                print(f"⚠️  Pre-drop warning for {tbl}: {e}")

def _drop_all_except(keep_tables: set[str]) -> None:
    """Drop all known tables except the ones listed (best-effort, FK-safe order)."""
    tables_to_drop = [t for t in Base.metadata.sorted_tables if t.name not in keep_tables]
    with engine.begin() as conn:
        for table in reversed(tables_to_drop):
            try:
                conn.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))
            except Exception as e:
                print(f"⚠️  Drop warning for {table.name}: {e}")


def _cleanup_reports_on_reset(*, keep_content: bool) -> None:
    reports_dir = resolve_reports_dir()
    if not os.path.isdir(reports_dir):
        return
    if keep_content:
        print(f"📄 Reports cleanup skipped (KEEP_CONTENT_ON_RESET enabled): {reports_dir}")
        return
    removed = 0
    for root, _dirs, files in os.walk(reports_dir):
        for name in files:
            path = os.path.join(root, name)
            try:
                os.remove(path)
                removed += 1
            except Exception as e:
                print(f"⚠️  Could not remove report file {path}: {e}")
    # Prune empty directories (except the root)
    for root, _dirs, _files in os.walk(reports_dir, topdown=False):
        if root == reports_dir:
            continue
        try:
            if not os.listdir(root):
                os.rmdir(root)
        except Exception:
            pass
    if removed:
        print(f"📄 Reports cleanup: removed={removed}")


@app.on_event("startup")
def on_startup():
    def _parse_bool_env(raw: str | None) -> bool | None:
        val = (raw or "").strip().lower()
        if val == "":
            return None
        if val in {"1", "true", "yes", "on"}:
            return True
        if val in {"0", "false", "no", "off"}:
            return False
        return None

    def _resolve_reset_requested() -> tuple[bool, str, dict[str, str]]:
        """
        Resolve DB reset intent with explicit precedence to avoid surprises:
        - If RESET_DB_ON_STARTUP is set, it is authoritative.
        - Otherwise fall back to legacy aliases.
        """
        keys = [
            "RESET_DB_ON_STARTUP",
            "RESET_DATABASE_ON_STARTUP",
            "reset_database_on_startup",
            "reset_db_on_startup",
        ]
        values: dict[str, str] = {k: (os.getenv(k) or "").strip() for k in keys}
        canonical = _parse_bool_env(values.get("RESET_DB_ON_STARTUP"))
        if canonical is not None:
            return bool(canonical), "RESET_DB_ON_STARTUP", values
        for legacy_key in keys[1:]:
            parsed = _parse_bool_env(values.get(legacy_key))
            if parsed is True:
                return True, legacy_key, values
        return False, "none", values

    def _startup_tasks() -> None:
        try:
            print("[startup] begin")
            # Ensure logging/usage schemas before handling traffic.
            try:
                from .usage import ensure_usage_schema
                ensure_usage_schema()
            except Exception as e:
                print(f"⚠️  Could not ensure usage schema: {e!r}")
            try:
                from .prompts import _ensure_llm_prompt_log_schema
                _ensure_llm_prompt_log_schema()
            except Exception as e:
                print(f"⚠️  Could not ensure llm prompt log schema: {e!r}")
            try:
                from .message_log import _ensure_message_log_schema
                _ensure_message_log_schema()
            except Exception as e:
                print(f"⚠️  Could not ensure message log schema: {e!r}")

            # Ensure job queue table exists (non-destructive)
            try:
                ensure_job_table()
            except Exception as e:
                print(f"⚠️  Could not ensure job table: {e!r}")

            reset_requested, reset_source, reset_values = _resolve_reset_requested()
            print(
                "[startup] reset flags: "
                + ", ".join(f"{k}='{v}'" for k, v in reset_values.items())
                + f" -> reset_requested={reset_requested} (source={reset_source})"
            )
            if reset_requested:
                keep_prompt_templates = bool(_parse_bool_env(os.getenv("KEEP_PROMPT_TEMPLATES_ON_RESET")))
                keep_content = bool(_parse_bool_env(os.getenv("KEEP_CONTENT_ON_RESET")))
                keep_kb = bool(_parse_bool_env(os.getenv("KEEP_KB_SNIPPETS_ON_RESET")))
                print(
                    "[startup] reset requested -> "
                    f"keep_prompt_templates={keep_prompt_templates} "
                    f"keep_content={keep_content} keep_kb={keep_kb}"
                )
                try:
                    _predrop_legacy_tables()
                except Exception as e:
                    print(f"⚠️  Legacy table pre-drop error: {e}")

                # Recreate schema
                if keep_prompt_templates or keep_content or keep_kb:
                    keep_tables: set[str] = set()
                    if keep_prompt_templates:
                        keep_tables.update({"prompt_templates", "prompt_template_versions", "prompt_settings"})
                    if keep_content:
                        keep_tables.update({
                            "content_prompt_templates",
                            "content_prompt_settings",
                            "content_prompt_generations",
                            "content_library_items",
                        })
                    if keep_kb:
                        keep_tables.update({
                            "kb_snippets",
                            "kb_vectors",
                            "concepts",
                            "concept_questions",
                        })
                    _drop_all_except(keep_tables)
                else:
                    Base.metadata.drop_all(bind=engine)
                Base.metadata.create_all(bind=engine)

                # Seed
                run_seed()

                # Clean reports after reset (optionally keep content files)
                try:
                    _cleanup_reports_on_reset(keep_content=keep_content)
                except Exception as e:
                    print(f"⚠️  Reports cleanup error: {e!r}")

                # Clear any persisted scheduler jobs so the job store is fresh
                try:
                    scheduler.reset_job_store(clear_table=True)
                except Exception as e:
                    print(f"⚠️  Could not reset APScheduler jobs: {e!r}")
                # Recreate APScheduler table after reset so scheduler can resume.
                try:
                    scheduler.ensure_apscheduler_tables()
                    debug_log("apscheduler tables ensured after reset", tag="scheduler")
                except Exception as e:
                    print(f"⚠️  ensure_apscheduler_tables after reset failed: {e!r}")

                # Ensure reports dir exists even when not resetting DB
                try:
                    reports_dir = resolve_reports_dir()
                    os.makedirs(reports_dir, exist_ok=True)
                except Exception as e:
                    print(f"⚠️  Could not create reports dir: {e!r}")
            else:
                try:
                    reports_dir = resolve_reports_dir()
                    os.makedirs(reports_dir, exist_ok=True)
                    print(f"[startup] DB reset skipped; reports dir preserved at {reports_dir}")
                except Exception as e:
                    print(f"⚠️  Could not ensure reports dir: {e!r}")

            _maybe_set_public_base_via_ngrok()
            _print_env_banner()
            try:
                scheduler.ensure_global_schedule_defaults()
            except Exception as e:
                print(f"⚠️  Could not init global prompt schedule defaults: {e!r}")
            print("[startup] end")
        finally:
            try:
                _STARTUP_TASKS_DONE.set()
            except Exception:
                pass

    # Run all startup tasks off-thread so we don't block port binding.
    threading.Thread(target=_startup_tasks, daemon=True).start()


def _record_freeform_checkin(user, body: str) -> None:
    """
    Capture unstructured inbound replies as a simple check-in, linked to the latest touchpoint/week if available.
    """
    txt = (body or "").strip()
    if not txt:
        return
    try:
        weekly_focus_id = None
        week_no = None
        tp_type = "user_reply"
        with SessionLocal() as s:
            wf = (
                s.query(WeeklyFocus)
                .filter(WeeklyFocus.user_id == user.id)
                .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
                .first()
            )
            if wf:
                weekly_focus_id = wf.id
                week_no = getattr(wf, "week_no", None)
            last_tp = (
                s.query(Touchpoint)
                .filter(Touchpoint.user_id == user.id)
                .order_by(Touchpoint.sent_at.desc().nullslast(), Touchpoint.created_at.desc())
                .first()
            )
            if last_tp and getattr(last_tp, "type", None):
                tp_type = last_tp.type
        record_checkin(
            user_id=user.id,
            touchpoint_type=tp_type,
            progress_updates=[{"note": txt}],
            blockers=[],
            commitments=[],
            weekly_focus_id=weekly_focus_id,
            week_no=week_no,
        )
    except Exception:
        pass


def _start_assessment_async(user: User, *, force_intro: bool = False) -> bool:
    if should_use_worker():
        job_id = enqueue_job(
            "assessment_start",
            {"user_id": user.id, "force_intro": bool(force_intro)},
            user_id=user.id,
        )
        print(f"[assessment] enqueued start user_id={user.id} job={job_id} force_intro={force_intro}")
        return True
    start_combined_assessment(user, force_intro=force_intro)
    return False


def _continue_assessment_async(user: User, user_text: str) -> bool:
    if should_use_worker():
        job_id = enqueue_job(
            "assessment_continue",
            {"user_id": user.id, "text": user_text},
            user_id=user.id,
        )
        print(f"[assessment] enqueued continue user_id={user.id} job={job_id}")
        return True
    continue_combined_assessment(user, user_text)
    return False

def _maybe_set_public_base_via_ngrok() -> None:
    """
    If PUBLIC_BASE_URL is not set, try to detect an https ngrok tunnel from the
    local ngrok API (http://127.0.0.1:4040/api/tunnels) and set it.
    Result is a host like 'xxxx.ngrok-free.app' (no scheme), matching how links are built.
    Safe no-op on failure.
    """
    api_public = (os.getenv("API_PUBLIC_BASE_URL") or "").strip()
    if api_public:
        if not os.getenv("PUBLIC_BASE_URL"):
            os.environ["PUBLIC_BASE_URL"] = api_public
        return
    if os.getenv("PUBLIC_BASE_URL"):
        return
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1.5) as resp:
            data = json.load(resp)
        tunnels = (data or {}).get("tunnels", []) or []
        https = next((t for t in tunnels if str(t.get("public_url","")).startswith("https://")), None)
        target = https or (tunnels[0] if tunnels else None)
        if not target:
            return
        pub = str(target.get("public_url","")).strip()
        if pub.startswith("https://"):
            host = pub.replace("https://", "")
        elif pub.startswith("http://"):
            host = pub.replace("http://", "")
        else:
            host = pub
        if host:
            os.environ["PUBLIC_BASE_URL"] = host
            print(f"🌐 PUBLIC_BASE_URL auto-detected via ngrok: {host}")
    except Exception as e:
        print(f"⚠️  ngrok auto-detect failed: {e!r}")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

# Name display/split helpers (no legacy 'name' fallback)
def display_full_name(u: "User") -> str:
    """
    Prefer first_name + surname; fall back to phone only (no legacy name).
    """
    try:
        first = (getattr(u, "first_name", None) or "").strip()
        last = (getattr(u, "surname", None) or "").strip()
        if first or last:
            return f"{first} {last}".strip()
        return getattr(u, "phone", "") or ""
    except Exception:
        return getattr(u, "phone", "") or ""

def _split_name(maybe_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Split a free-form name into (first_name, surname).
    - Empty/None -> (None, None)
    - One token -> (token, None)
    - Two+ tokens -> (first token, rest joined as surname)
    """
    if not maybe_name:
        return None, None
    cleaned = _strip_invisible(str(maybe_name)).strip()
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return None, None
    def _titlecase_chunk(chunk: str) -> str:
        return " ".join(word.capitalize() for word in chunk.split())
    if len(parts) == 1:
        return _titlecase_chunk(parts[0]), None
    first = _titlecase_chunk(parts[0])
    last = _titlecase_chunk(" ".join(parts[1:]))
    return first, last

def _require_name_fields(first: str | None, last: str | None) -> bool:
    return bool(first and first.strip()) and bool(last and last.strip())


_NAME_PARTICLES = {
    "al", "ap", "bin", "da", "de", "del", "della", "di", "du", "la", "le", "van", "von",
}
_NAME_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z'-]*$")


def _is_affirmative_name_confirm(text: str | None) -> bool:
    norm = " ".join(re.sub(r"[^a-z0-9\s]+", " ", (text or "").strip().lower()).split())
    yeses = {"yes", "y", "yeah", "yep", "confirm", "yes confirm", "confirmed", "ok", "okay"}
    return norm in yeses


def _extract_valid_name_from_reply(text: str | None) -> tuple[str, str] | tuple[None, None]:
    """
    Lightweight validation:
    - 2-4 words
    - only letters / apostrophe / hyphen in tokens
    - reject obvious non-name payloads (digits, URLs, emails)
    - token len >=2 unless known surname particle
    """
    cleaned = " ".join(_strip_invisible(text or "").strip().split())
    if not cleaned:
        return None, None
    low = cleaned.lower()
    if "http://" in low or "https://" in low or "www." in low or "@" in cleaned:
        return None, None
    if any(ch.isdigit() for ch in cleaned):
        return None, None

    parts = [p for p in cleaned.split(" ") if p]
    if len(parts) < 2 or len(parts) > 4:
        return None, None

    for token in parts:
        if not _NAME_TOKEN_RE.match(token):
            return None, None
        letters_only = re.sub(r"[^A-Za-z]", "", token)
        if len(letters_only) < 2 and token.lower() not in _NAME_PARTICLES:
            return None, None

    first, surname = _split_name(cleaned)
    if not _require_name_fields(first, surname):
        return None, None
    return first, surname


def _unknown_user_name_confirm_text(first_name: str, surname: str) -> str:
    full_name = f"{(first_name or '').strip()} {(surname or '').strip()}".strip()
    return f"{UNKNOWN_USER_NAME_CONFIRM_PREFIX}{full_name}{UNKNOWN_USER_NAME_CONFIRM_SUFFIX}"


def _extract_pending_confirmed_name(phone_e164: str) -> tuple[str, str] | tuple[None, None]:
    phone_norm = _norm_phone(phone_e164 or "")
    if not phone_norm:
        return None, None
    try:
        with SessionLocal() as s:
            last_row = (
                s.query(MessageLog)
                .filter(MessageLog.phone == phone_norm)
                .order_by(MessageLog.created_at.desc(), MessageLog.id.desc())
                .first()
            )
            if not last_row:
                return None, None
            if str(getattr(last_row, "direction", "") or "").lower() != "outbound":
                return None, None
            text = str(getattr(last_row, "text", "") or "").strip()
            if not text.startswith(UNKNOWN_USER_NAME_CONFIRM_PREFIX):
                return None, None
            if not text.endswith(UNKNOWN_USER_NAME_CONFIRM_SUFFIX):
                return None, None
            full_name = text[
                len(UNKNOWN_USER_NAME_CONFIRM_PREFIX): len(text) - len(UNKNOWN_USER_NAME_CONFIRM_SUFFIX)
            ].strip()
            return _extract_valid_name_from_reply(full_name)
    except Exception:
        return None, None

_DEFAULT_CLUB_ID_CACHE: int | None = None
_FORMAT_CHAR_MAP = {
    ord(ch): None for ch in ("\u202a", "\u202c", "\u202d", "\u202e", "\ufeff", "\u200f", "\u200e")
}

def _strip_invisible(text: str | None) -> str:
    if not text:
        return ""
    return text.translate(_FORMAT_CHAR_MAP)

def _resolve_default_club_id(sess) -> int:
    """
    Resolve the default club id for newly created users. Order of precedence:
    1) DEFAULT_CLUB_ID env var
    2) CLUB_ID env var
    3) TEST_CLUB_ID env var
    4) First club row in the database
    Result is cached for the lifetime of the process.
    """
    global _DEFAULT_CLUB_ID_CACHE
    if _DEFAULT_CLUB_ID_CACHE is not None:
        return _DEFAULT_CLUB_ID_CACHE
    for var in ("DEFAULT_CLUB_ID", "CLUB_ID", "TEST_CLUB_ID"):
        raw = (os.getenv(var) or "").strip()
        if raw.isdigit():
            _DEFAULT_CLUB_ID_CACHE = int(raw)
            return _DEFAULT_CLUB_ID_CACHE
    club = (
        sess.query(Club)
            .order_by(Club.id.asc())
            .first()
    )
    if not club:
        raise RuntimeError("No clubs available to assign new users; seed clubs first.")
    _DEFAULT_CLUB_ID_CACHE = getattr(club, "id", None)
    if _DEFAULT_CLUB_ID_CACHE is None:
        raise RuntimeError("Failed to resolve default club id (club row missing id).")
    return _DEFAULT_CLUB_ID_CACHE


def _club_label(club: Club | None) -> str:
    if not club:
        return "unknown club"
    for attr in ("name", "slug"):
        val = getattr(club, attr, None)
        if val:
            return str(val)
    return f"club #{getattr(club, 'id', None)}"


def _find_club_by_identifier(sess, identifier: str) -> Club | None:
    token = (identifier or "").strip()
    if not token:
        return None
    if token.isdigit():
        return (
            sess.query(Club)
               .filter(Club.id == int(token))
               .one_or_none()
        )
    lowered = token.lower()
    return (
        sess.query(Club)
           .filter(
               or_(
                   func.lower(Club.slug) == lowered,
                   func.lower(Club.name) == lowered,
               )
           )
           .one_or_none()
    )


def _get_or_create_user(
    phone_e164: str,
    *,
    create_if_missing: bool = True,
    first_name: str | None = None,
    surname: str | None = None,
) -> User | None:
    """Find a user by phone, and optionally create when missing."""
    phone_e164 = _norm_phone(phone_e164)
    with SessionLocal() as s:
        u = s.query(User).filter(User.phone == phone_e164).first()
        if not u and create_if_missing:
            club_id = _resolve_default_club_id(s)
            now = datetime.utcnow()
            u = User(first_name=first_name, surname=surname, phone=phone_e164, club_id=club_id,
                     created_on=now, updated_on=now)
            s.add(u)
            s.commit()
            s.refresh(u)
        return u


def _log_inbound_direct(user: User, channel: str, body: str, from_raw: str) -> None:
    """All inbound logging routed through app.message_log.write_log (no direct DB writes)."""
    try:
        # Import here to avoid any circulars
        from .message_log import write_log

        phone = getattr(user, "phone", None) or (from_raw.replace("whatsapp:", "") if from_raw else None)


        user_id = int(getattr(user, "id", 0) or 0)
        virtual_now = get_virtual_now_for_user(user_id)
        inbound_at = virtual_now or datetime.utcnow()
        meta_payload = {"from": from_raw}
        if virtual_now is not None:
            meta_payload["virtual_date"] = virtual_now.date().isoformat()

        # Canonical logging (category/sid omitted for inbound unless you have them)
        write_log(
            phone_e164=phone,
            direction="inbound",
            text=body or "",
            category=None,
            twilio_sid=None,
            user=user,
            channel=channel,  # harmless if model lacks 'channel'
            meta=meta_payload,  # harmless if model lacks 'meta'
            created_at=virtual_now,
        )

        # Persist the user's most recent inbound timestamp for admin visibility and channel policy.
        if user_id:
            try:
                with SessionLocal() as s:
                    db_user = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
                    if db_user:
                        db_user.last_inbound_message_at = inbound_at
                        s.commit()
            except Exception as e2:
                print(f"⚠️ failed to set last_inbound_message_at user_id={user_id}: {e2!r}")
    except Exception as e:
        print(f"⚠️ inbound direct-log failed (non-fatal): {e!r}")


def _awaiting_unknown_user_name_reply(phone_e164: str) -> bool:
    """
    True only when the last logged message for this phone is the name-capture prompt.
    This enforces a strict handshake:
      1) unknown inbound -> send prompt
      2) valid name reply -> send confirmation
      3) YES -> create user
    """
    phone_norm = _norm_phone(phone_e164 or "")
    if not phone_norm:
        return False
    try:
        with SessionLocal() as s:
            last_row = (
                s.query(MessageLog)
                .filter(MessageLog.phone == phone_norm)
                .order_by(MessageLog.created_at.desc(), MessageLog.id.desc())
                .first()
            )
            if not last_row:
                return False
            return (
                str(getattr(last_row, "direction", "") or "").lower() == "outbound"
                and str(getattr(last_row, "text", "") or "").strip() == UNKNOWN_USER_NAME_PROMPT
            )
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────────────
# WhatsApp Admin Command Helpers
# ──────────────────────────────────────────────────────────────────────────────


# Phone normalizer for admin commands
# PATCH — 2025-09-11: normalize local numbers using DEFAULT_COUNTRY_CODE (e.g., +44)
import re
_CC_RE = re.compile(r"^\+(\d{1,3})")

def _guess_default_cc() -> str:
    """
    Resolve default country code in priority order:
    1) DEFAULT_COUNTRY_CODE
    2) TWILIO_WHATSAPP_FROM / TWILIO_FROM (extract +CC)
    3) ADMIN_WHATSAPP / ADMIN_PHONE
    4) TWILIO_SMS_FROM
    5) Hard fallback '+44'
    """
    cand = (os.getenv("DEFAULT_COUNTRY_CODE") or "").strip()
    if cand.startswith("+"):
        return cand
    for var in ("TWILIO_WHATSAPP_FROM", "TWILIO_FROM", "ADMIN_WHATSAPP", "ADMIN_PHONE", "TWILIO_SMS_FROM"):
        v = (os.getenv(var) or "").strip()
        if not v:
            continue
        v = v.replace("whatsapp:", "")
        m = _CC_RE.match(v)
        if m:
            # Avoid over-capturing area-code digits from full phone numbers.
            digits = m.group(1)
            if digits.startswith("44"):
                return "+44"
            if digits.startswith("1"):
                return "+1"
            if digits.startswith("91"):
                return "+91"
            if digits.startswith("61"):
                return "+61"
            if digits.startswith("353"):
                return "+353"
            return f"+{digits}"
    return "+44"

def _norm_phone(s: str) -> str:
    s = _strip_invisible(s).strip()
    if s.startswith("whatsapp:"):
        s = s[len("whatsapp:"):]
    # Remove common separators
    s = s.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    # Convert '00' international prefix to '+'
    if s.startswith("00") and len(s) > 2 and s[2:].isdigit():
        s = "+" + s[2:]
    # If already E.164, return
    if s.startswith("+"):
        return s
    # Determine default country code
    cc_env = (os.getenv("DEFAULT_COUNTRY_CODE") or "").strip()
    cc = cc_env if cc_env.startswith("+") else _guess_default_cc()
    cc_digits = cc[1:] if cc.startswith("+") else cc
    # Accept pure digits after stripping separators
    if s.isdigit():
        # UK-style local numbers starting with 0 → drop trunk '0'
        if s.startswith("0"):
            return cc + s[1:]
        # If user typed country code without '+', treat as international format.
        if cc_digits and s.startswith(cc_digits) and len(s) > (len(cc_digits) + 6):
            return "+" + s
        # No trunk '0' — still prefix with cc
        return cc + s
    return s


# ──────────────────────────────────────────────────────────────────────────────
# Auth helpers (password + OTP + session)
# ──────────────────────────────────────────────────────────────────────────────
_PW_ITERATIONS = int(os.getenv("PASSWORD_HASH_ITERATIONS", "120000"))
_OTP_TTL_MINUTES = int(os.getenv("OTP_TTL_MINUTES", "5"))
_SESSION_TTL_DAYS = int(os.getenv("SESSION_TTL_DAYS", "7"))
_SESSION_TTL_DAYS_REMEMBER = int(os.getenv("SESSION_TTL_DAYS_REMEMBER", "30"))

def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")

def _b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PW_ITERATIONS)
    return f"pbkdf2_sha256${_PW_ITERATIONS}${_b64(salt)}${_b64(dk)}"

def _verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iter_str, salt_b64, dk_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = _b64d(salt_b64)
        expected = _b64d(dk_b64)
        calc = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return secrets.compare_digest(calc, expected)
    except Exception:
        return False

def _hash_otp(code: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(8)
    digest = hashlib.sha256(salt + code.encode("utf-8")).digest()
    return f"sha256${_b64(salt)}${_b64(digest)}"

def _verify_otp(code: str, stored: str) -> bool:
    try:
        algo, salt_b64, digest_b64 = stored.split("$", 2)
        if algo != "sha256":
            return False
        salt = _b64d(salt_b64)
        expected = _b64d(digest_b64)
        calc = hashlib.sha256(salt + code.encode("utf-8")).digest()
        return secrets.compare_digest(calc, expected)
    except Exception:
        return False

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _has_recent_whatsapp_inbound(
    user_id: int,
    *,
    user_phone: str | None = None,
    lookback_hours: int = 24,
) -> bool:
    """
    Best-effort signal that the user is inside the auth WhatsApp-style 24h window.

    Primary source is users.last_inbound_message_at (shown in User Management).
    Fallback source is recent inbound message_logs lookup for backward compatibility.
    """
    if not user_id:
        return False
    hours = max(1, int(lookback_hours or 24))
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    phone_norm = _norm_phone(str(user_phone or "")) if user_phone else None

    # Primary signal: persisted per-user inbound timestamp (same value surfaced in admin user management).
    try:
        with SessionLocal() as s:
            last_inbound = s.execute(
                select(User.last_inbound_message_at).where(User.id == user_id)
            ).scalar_one_or_none()
        if isinstance(last_inbound, datetime):
            if last_inbound.tzinfo is not None:
                last_inbound = last_inbound.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
            recent = last_inbound >= cutoff
            print(
                f"[auth][otp] wa_window source=user.last_inbound_message_at "
                f"user_id={user_id} last_inbound={last_inbound.isoformat()} cutoff={cutoff.isoformat()} recent={recent}"
            )
            return bool(recent)
    except Exception as e:
        print(f"[auth][otp] wa_window user_last_inbound_lookup_failed user_id={user_id} error={e}")

    def _query_recent(*, include_channel_filter: bool) -> bool:
        with SessionLocal() as s:
            q = s.query(MessageLog.id).filter(MessageLog.direction == "inbound").filter(MessageLog.created_at >= cutoff)
            if phone_norm:
                q = q.filter(or_(MessageLog.user_id == user_id, MessageLog.phone == phone_norm))
            else:
                q = q.filter(MessageLog.user_id == user_id)
            if include_channel_filter:
                q = q.filter(or_(MessageLog.channel == "whatsapp", MessageLog.channel.is_(None)))
            row = q.order_by(MessageLog.created_at.desc(), MessageLog.id.desc()).first()
            return row is not None

    try:
        recent = _query_recent(include_channel_filter=True)
        print(
            f"[auth][otp] wa_window source=message_logs user_id={user_id} include_channel_filter=true "
            f"cutoff={cutoff.isoformat()} recent={recent}"
        )
        return recent
    except Exception as e:
        # Fail-open: if schema drift exists (e.g., missing channel column), retry without channel filter.
        print(f"[auth][otp] recent_whatsapp_lookup_failed user_id={user_id} include_channel=true error={e}")
        try:
            recent = _query_recent(include_channel_filter=False)
            print(
                f"[auth][otp] wa_window source=message_logs user_id={user_id} include_channel_filter=false "
                f"cutoff={cutoff.isoformat()} recent={recent}"
            )
            return recent
        except Exception as e2:
            print(f"[auth][otp] recent_whatsapp_lookup_failed user_id={user_id} include_channel=false error={e2}")
            return False


def _send_auth_code(
    *,
    user_id: int,
    user_phone: str,
    code: str,
    channel: str,
    purpose_label: str,
) -> str:
    """
    Send login/reset code using requested channel policy.
    Returns actual channel used: "whatsapp" or "sms".
    """
    chosen = (channel or "auto").strip().lower()
    if chosen not in {"auto", "whatsapp", "sms"}:
        raise HTTPException(status_code=400, detail="channel must be auto|whatsapp|sms")

    text = f"Your HealthSense {purpose_label} is {code}. It expires in {_OTP_TTL_MINUTES} minutes."
    wa_window_raw = (os.getenv("AUTH_WHATSAPP_OPEN_WINDOW_HOURS", "24") or "24").strip()
    try:
        wa_window_hours = max(1, int(wa_window_raw))
    except Exception:
        print(
            f"[auth][otp] invalid AUTH_WHATSAPP_OPEN_WINDOW_HOURS='{wa_window_raw}', defaulting to 24"
        )
        wa_window_hours = 24
    sms_first_if_wa_closed = (os.getenv("AUTH_SMS_IF_NO_WHATSAPP_WINDOW", "0") or "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    wa_recent = _has_recent_whatsapp_inbound(
        user_id,
        user_phone=user_phone,
        lookback_hours=wa_window_hours,
    )
    print(
        f"[auth][otp] dispatch user_id={user_id} chosen={chosen} "
        f"sms_first_if_wa_closed={sms_first_if_wa_closed} wa_recent={wa_recent} wa_window_hours={wa_window_hours}"
    )

    def _try_sms() -> str:
        send_sms(to=user_phone, text=text)
        return "sms"

    def _try_whatsapp() -> str:
        send_whatsapp(to=user_phone, text=text)
        return "whatsapp"

    if chosen == "sms":
        print(f"[auth][otp] dispatch_result user_id={user_id} channel=sms reason=explicit")
        return _try_sms()
    if chosen == "whatsapp":
        print(f"[auth][otp] dispatch_result user_id={user_id} channel=whatsapp reason=explicit")
        return _try_whatsapp()

    # auto mode
    if sms_first_if_wa_closed and not wa_recent:
        try:
            print(f"[auth][otp] dispatch_result user_id={user_id} channel=sms reason=wa_window_closed")
            return _try_sms()
        except Exception as sms_err:
            try:
                print(
                    f"[auth][otp] dispatch_fallback user_id={user_id} from=sms to=whatsapp "
                    f"reason=sms_failed error={sms_err}"
                )
                return _try_whatsapp()
            except Exception as wa_err:
                raise RuntimeError(f"sms send failed: {sms_err}; whatsapp fallback failed: {wa_err}")

    try:
        print(f"[auth][otp] dispatch_result user_id={user_id} channel=whatsapp reason=auto_primary")
        return _try_whatsapp()
    except Exception as wa_err:
        try:
            print(
                f"[auth][otp] dispatch_fallback user_id={user_id} from=whatsapp to=sms "
                f"reason=whatsapp_failed error={wa_err}"
            )
            return _try_sms()
        except Exception as sms_err:
            raise RuntimeError(f"whatsapp send failed: {wa_err}; sms fallback failed: {sms_err}")

def _extract_session_token(request: Request) -> str | None:
    header = request.headers.get("X-Session-Token")
    if header:
        return header.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    cookie = request.cookies.get("hs_session")
    if cookie:
        return cookie.strip()
    return None

def _get_session_user(request: Request) -> User | None:
    token = _extract_session_token(request)
    if not token:
        return None
    token_hash = _hash_token(token)
    now = datetime.utcnow()
    with SessionLocal() as s:
        sess = (
            s.query(AuthSession)
            .filter(AuthSession.token_hash == token_hash, AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.id.desc())
            .first()
        )
        if not sess or sess.expires_at <= now:
            return None
        user = s.execute(select(User).where(User.id == sess.user_id)).scalar_one_or_none()
        return user

def _get_admin_if_valid(
    x_admin_token: str | None,
    x_admin_user_id: str | None,
) -> User | None:
    if not x_admin_token and not x_admin_user_id:
        return None
    expected = (os.getenv("ADMIN_API_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_TOKEN not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    if not x_admin_user_id:
        raise HTTPException(status_code=400, detail="X-Admin-User-Id header required")
    try:
        admin_user_id = int(x_admin_user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="X-Admin-User-Id must be an integer")
    with SessionLocal() as s:
        admin_user = s.execute(select(User).where(User.id == admin_user_id)).scalar_one_or_none()
        if not admin_user:
            raise HTTPException(status_code=404, detail="Admin user not found")
        if _user_admin_role(admin_user) not in {ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}:
            raise HTTPException(status_code=403, detail="User lacks admin privileges")
        if getattr(admin_user, "club_id", None) is None:
            raise HTTPException(status_code=400, detail="Admin user missing club association")
    return admin_user

def _resolve_user_access(
    *,
    request: Request,
    user_id: int,
    x_admin_token: str | None,
    x_admin_user_id: str | None,
) -> User:
    admin_user = _get_admin_if_valid(x_admin_token, x_admin_user_id)
    with SessionLocal() as s:
        target = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="user not found")
        if admin_user:
            _ensure_club_scope(admin_user, target)
            return target
    session_user = _get_session_user(request)
    if not session_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session required")
    if session_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return session_user


def _admin_lookup_user_by_phone(session, phone: str, admin_user: User) -> User | None:
    """
    Fetch a user for admin WhatsApp commands, restricting non-global admins to their club.
    Global admins (club_id=None) can target any club.
    """
    q = select(User).where(User.phone == phone)
    club_id = getattr(admin_user, "club_id", None)
    if club_id is not None:
        q = q.where(User.club_id == club_id)
    return session.execute(q).scalar_one_or_none()


def _user_admin_role(u: User) -> str:
    try:
        role = (getattr(u, "admin_role", None) or "").strip().lower()
        if role in {ADMIN_ROLE_MEMBER, ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}:
            return role
        # Backward compatibility: legacy superusers remain global admins
        if bool(getattr(u, "is_superuser", False)):
            return ADMIN_ROLE_GLOBAL
    except Exception as e:
        print(f"[admin] role lookup error: {e!r}")
    return ADMIN_ROLE_MEMBER


def _is_global_admin(u: User) -> bool:
    return _user_admin_role(u) == ADMIN_ROLE_GLOBAL


def _is_admin_user(u: User) -> bool:
    role = _user_admin_role(u)
    ok = role in {ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}
    try:
        print(
            "[admin] check user_id={uid} phone={phone} role={role} is_superuser={su} ok={ok}".format(
                uid=getattr(u, "id", None),
                phone=getattr(u, "phone", None),
                role=role,
                su=getattr(u, "is_superuser", None),
                ok=ok,
            )
        )
    except Exception:
        pass
    return ok

def _parse_summary_range(args: list[str]) -> tuple[str, str]:
    """
    Accepts tokens: today | last7d | last30d | thisweek | YYYY-MM-DD YYYY-MM-DD
    Returns (start_str, end_str) as ISO dates.
    """
    from datetime import date, timedelta
    today = date.today()
    if not args:
        # default to last7d inclusive
        start = today - timedelta(days=6)
        end = today
        return (start.isoformat(), end.isoformat())
    token = (args[0] or "").lower()
    if token == "today":
        return (today.isoformat(), today.isoformat())
    if token == "last7d":
        start = today - timedelta(days=6)
        return (start.isoformat(), today.isoformat())
    if token == "last30d":
        start = today - timedelta(days=29)
        return (start.isoformat(), today.isoformat())
    if token == "thisweek":
        # Monday..Sunday of current week
        weekday = today.weekday()  # Monday=0
        start = today - timedelta(days=weekday)
        end = start + timedelta(days=6)
        return (start.isoformat(), end.isoformat())
    if len(args) >= 2:
        # assume explicit dates
        a, b = args[0], args[1]
        # no validation here; reporting will raise if invalid
        return (a, b)
    # fallback
    start = today - timedelta(days=6)
    return (start.isoformat(), today.isoformat())


def _looks_like_phone_token(token: str) -> bool:
    if not token:
        return False
    token = token.strip()
    if not token:
        return False
    if re.match(r"^\d{4}-\d{2}-\d{2}$", token):
        return False
    stripped = (
        token.replace("+", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "")
    )
    return stripped.isdigit() and len(stripped) >= 7


def _resolve_admin_target_phone(admin_user: User, args: list[str], *, allow_notes: bool = False) -> tuple[str, list[str]]:
    """
    Resolve target phone for admin commands.
    If first arg looks like a phone, use it; otherwise default to admin user's phone.
    If allow_notes is True, any non-phone args are treated as notes.
    """
    if not args:
        return _norm_phone(admin_user.phone), []
    if _looks_like_phone_token(args[0]):
        return _norm_phone(args[0]), args[1:]
    if allow_notes:
        return _norm_phone(admin_user.phone), args
    return _norm_phone(admin_user.phone), args


def _handle_admin_command(admin_user: User, text: str, *, source_phone: str | None = None) -> bool:
    """
    Handle very small set of admin commands sent over WhatsApp by superusers (ids 1 & 2).
    Commands:
      admin create <phone> [<name...>]
      admin start <phone>
      admin status <phone>
      admin assessment <phone>
      admin detailed <phone>
    Returns True if handled; False to allow normal flow.
    """
    msg = (text or "").strip()
    print(f"[admin] inbound cmd from {admin_user.id}/{admin_user.phone}: {msg}")
    if not msg.lower().startswith("admin"):
        return False
    parts = msg.split()
    # PATCH — 2025-09-11: Plain 'admin' or 'admin help/?' shows usage
    if len(parts) == 1 or (len(parts) >= 2 and parts[1].lower() in {"help", "?"}):
        send_whatsapp(to=admin_user.phone, text=ADMIN_USAGE)
        return True
    if len(parts) < 2:
        send_whatsapp(to=admin_user.phone, text=ADMIN_USAGE)
        return True
    cmd = parts[1].lower()
    args = parts[2:]
    admin_club_id = getattr(admin_user, "club_id", None)
    club_scope_id = admin_club_id
    try:
        if cmd in {"create", "start", "status", "report", "detailed", "summary", "okr-summary", "okr-summaryllm", "users", "assessment", "llm-review", "llmreview"} and club_scope_id is None:
            send_whatsapp(
                to=admin_user.phone,
                text="Your admin profile is not linked to a club. Use 'admin set global <club>' first."
            )
            return True

        if cmd == "beta":
            if not args:
                target_phone_raw = _norm_phone(admin_user.phone)
                desired_state = "beta"
            elif _looks_like_phone_token(args[0]):
                target_phone_raw = args[0]
                desired_state = args[1].lower() if len(args) > 1 else "beta"
            else:
                target_phone_raw = _norm_phone(admin_user.phone)
                desired_state = args[0].lower()
            if desired_state == "clear":
                desired_state = "live"
            if desired_state not in {"live", "beta", "develop"}:
                send_whatsapp(to=admin_user.phone, text="State must be live|beta|develop|clear")
                return True
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone_raw, admin_user)
                if not u:
                    send_whatsapp(to=admin_user.phone, text=f"User not found for {target_phone_raw}")
                    return True
                pref = (
                    s.query(UserPreference)
                    .filter(UserPreference.user_id == u.id, UserPreference.key == "prompt_state_override")
                    .first()
                )
                if not pref:
                    pref = UserPreference(user_id=u.id, key="prompt_state_override")
                    s.add(pref)
                pref.value = desired_state
                s.commit()
                send_whatsapp(
                    to=admin_user.phone,
                    text=f"Prompt state override for {display_full_name(u)} ({u.phone}) set to {desired_state}.",
                )
            return True

        if cmd == "prompt-audit":
            if not args:
                send_whatsapp(to=admin_user.phone, text="Usage: admin prompt-audit [phone] <YYYY-MM-DD> [state]")
                return True
            if _looks_like_phone_token(args[0]):
                if len(args) < 2:
                    send_whatsapp(to=admin_user.phone, text="Usage: admin prompt-audit [phone] <YYYY-MM-DD> [state]")
                    return True
                target_phone_raw = args[0]
                as_of_date = args[1]
                state = args[2].lower() if len(args) > 2 else "live"
            else:
                target_phone_raw = _norm_phone(admin_user.phone)
                as_of_date = args[0]
                state = args[1].lower() if len(args) > 1 else "live"
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone_raw, admin_user)
                if not u:
                    send_whatsapp(to=admin_user.phone, text=f"User not found for {target_phone_raw}")
                    return True
                try:
                    from .reporting import generate_prompt_audit_report, _report_link
                    path = generate_prompt_audit_report(u.id, as_of_date=as_of_date, state=state, include_logs=True, logs_limit=3)
                    filename = os.path.basename(path)
                    url = _report_link(u.id, filename)
                    # Fallback if link generation failed to include the file
                    if filename not in url:
                        base = url.rstrip("/")
                        url = f"{base}/reports/{u.id}/{filename}" if base else f"/reports/{u.id}/{filename}"
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"Prompt audit report ready for {display_full_name(u)} ({u.phone}) @ {as_of_date} [{state}]: {url}",
                    )
                except Exception as e:
                    send_whatsapp(to=admin_user.phone, text=f"Failed to generate prompt audit: {e}")
            return True

        if cmd == "create":
            if len(parts) < 4:
                send_whatsapp(to=admin_user.phone, text="Usage: admin create <phone> <first_name> <surname>")
                return True
            # Parse phone which may be split across multiple tokens (e.g., "07808 951649")
            i = 2
            phone_tokens = []
            while i < len(parts):
                tok = parts[i]
                stripped = tok.replace("+", "").replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
                if stripped.isdigit():
                    phone_tokens.append(tok)
                    i += 1
                    continue
                break
            phone_raw = "".join(phone_tokens) if phone_tokens else parts[2]
            phone = _norm_phone(phone_raw)
            raw_name = _strip_invisible(" ".join(parts[i:])).strip() if i < len(parts) else ""
            first_name, surname = _split_name(raw_name)
            if not _require_name_fields(first_name, surname):
                send_whatsapp(to=admin_user.phone, text="Please provide both first and surname when creating a user.")
                return True
            with SessionLocal() as s:
                existing = s.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
                if existing:
                    send_whatsapp(to=admin_user.phone, text=f"User exists: id={existing.id}, phone={existing.phone}, name={display_full_name(existing)}")
                    return True
                now = datetime.utcnow()
                u = User(
                    first_name=first_name,
                    surname=surname,
                    phone=phone,
                    club_id=admin_club_id,
                    created_on=now,
                    updated_on=now,
                    consent_given=True,
                    consent_at=now,
                )
                if hasattr(u, "consent_yes_at"):
                    try:
                        setattr(u, "consent_yes_at", now)
                    except Exception:
                        pass
                s.add(u); s.commit(); s.refresh(u)
            # trigger consent/intro
            try:
                _start_assessment_async(u)
            except Exception as e:
                print(f"[wa admin create] start failed: {e!r}")
            send_whatsapp(to=admin_user.phone, text=f"Created user id={u.id} {display_full_name(u)} ({u.phone})")
            return True
        if cmd == "progress":
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                from .reporting import generate_progress_report_html
                generate_progress_report_html(u.id)
                url = _public_report_url(u.id, "progress.html")
                send_whatsapp(to=admin_user.phone, text=f"Progress report for {display_full_name(u)}: {url}")
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate progress report: {e}")
            return True
        if cmd in {"llm-review", "llmreview"}:
            target_phone, llm_args = _resolve_admin_target_phone(admin_user, args)
            try:
                limit = int(llm_args[0]) if llm_args else 100
            except Exception:
                limit = 100
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                link = generate_llm_prompt_log_report_html(u.id, limit=limit)
                bust = int(time.time())
                send_whatsapp(
                    to=admin_user.phone,
                    text=f"LLM prompt logs (limit {limit}) for {display_full_name(u)}: {link}?ts={bust}"
                )
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate LLM prompt log report: {e}")
            return True
        elif cmd in {"weekstart", "monday"}:
            # Usage: admin weekstart <phone> [notes] — auto-select top KRs
            target_phone, note_parts = _resolve_admin_target_phone(admin_user, args, allow_notes=True)
            notes = " ".join(note_parts).strip() if note_parts else ""
            notes = notes or None

            try:
                with SessionLocal() as s:
                    u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True

                # Trigger weekstart for that user
                monday.start_weekstart(u, notes=notes)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to plan weekstart: {e}")
            return True
        elif cmd == "kickoff":
            send_whatsapp(
                to=admin_user.phone,
                text="Kickoff flow is retired and no longer available.",
            )
            return True
        elif cmd in {"schedule", "jobs"}:
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            rows = user_schedule_report(u.id)
            if not rows:
                send_whatsapp(to=admin_user.phone, text=f"No scheduled jobs found for {target_phone}.")
                return True
            link = None
            try:
                link = generate_schedule_report_html(u.id)
            except Exception:
                link = None
            lines = []
            for row in rows[:15]:
                nid = row.get("id") or ""
                nxt_local = row.get("next_run_local") or "n/a"
                nxt_utc = row.get("next_run_utc") or "n/a"
                lines.append(f"- {nid}: local {nxt_local}, utc {nxt_utc}")
            body = "*Schedule* for {phone}:\n{lines}".format(
                phone=target_phone,
                lines="\n".join(lines),
            )
            if link:
                body += f"\n\nHTML: {link}"
            send_whatsapp(to=admin_user.phone, text=body)
            return True
        elif cmd in {"midweek", "wednesday"}:
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                wednesday.send_midweek_check(u)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to send midweek: {e}")
            return True
        elif cmd in {"autoprompts", "coaching"}:
            default_target_phone = _norm_phone(source_phone or admin_user.phone)
            if args and _looks_like_phone_token(args[0]):
                target_phone = _norm_phone(args[0])
                toggle_parts = args[1:]
            else:
                target_phone = default_target_phone
                toggle_parts = args
            if not toggle_parts:
                send_whatsapp(to=admin_user.phone, text="Usage: admin coaching [phone] on|off|faston|reset")
                return True
            toggle = toggle_parts[0].lower()
            if toggle not in {"on", "off", "faston", "reset"}:
                send_whatsapp(to=admin_user.phone, text="Usage: admin coaching [phone] on|off|faston|reset")
                return True
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            ok = False
            fast_minutes = 2 if toggle == "faston" else None
            if toggle == "reset":
                ok = scheduler.reset_coaching_jobs(u.id)
            elif toggle == "on":
                ok = scheduler.enable_coaching(u.id, fast_minutes=fast_minutes)
            elif toggle == "faston":
                ok = scheduler.enable_coaching(u.id, fast_minutes=fast_minutes)
            else:
                ok = scheduler.disable_coaching(u.id)
            if ok:
                msg = f"Coaching prompts turned {toggle} for {target_phone}."
                if toggle == "faston":
                    msg += f" (every {fast_minutes} minutes for testing)"
                if toggle == "reset":
                    msg = f"Coaching prompt jobs cleared for {target_phone} (preference unchanged)."
                send_whatsapp(to=admin_user.phone, text=msg)
            else:
                send_whatsapp(to=admin_user.phone, text="Failed to update coaching prompts (check AUTO_DAILY_PROMPTS env).")
            return True
        elif cmd in {"vdate", "virtualdate", "virtual-date"}:
            target_phone, v_args = _resolve_admin_target_phone(admin_user, args)
            if not v_args:
                send_whatsapp(to=admin_user.phone, text="Usage: admin vdate [phone] <YYYY-MM-DD|today|clear>")
                return True
            token = (v_args[0] or "").strip().lower()
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
                if token in {"clear", "off", "reset"}:
                    set_virtual_mode(s, u.id, enabled=False)
                    s.commit()
                    send_whatsapp(to=admin_user.phone, text=f"Virtual date cleared for {target_phone}.")
                    return True
                if token in {"today", "now"}:
                    chosen = date.today()
                else:
                    try:
                        chosen = date.fromisoformat((v_args[0] or "").strip()[:10])
                    except Exception:
                        send_whatsapp(to=admin_user.phone, text="Usage: admin vdate [phone] <YYYY-MM-DD|today|clear>")
                        return True
                set_virtual_mode(
                    s,
                    u.id,
                    enabled=True,
                    start_date=chosen,
                    keep_existing_date=False,
                )
                s.commit()
                current = get_virtual_date(s, u.id)
            send_whatsapp(
                to=admin_user.phone,
                text=f"Virtual date set for {target_phone}: {(current or chosen).isoformat()}",
            )
            return True
        elif cmd in {"tuesday"}:
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                tuesday.send_tuesday_check(u)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to send Tuesday check: {e}")
            return True
        elif cmd in {"boost", "friday"}:
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                friday.send_boost(u)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to send boost: {e}")
            return True
        elif cmd in {"saturday"}:
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                saturday.send_saturday_keepalive(u)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to send Saturday keepalive: {e}")
            return True
        elif cmd in {"sunday"}:
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                sunday.send_sunday_review(u)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to send Sunday review: {e}")
            return True
        elif cmd in {"thursday"}:
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                thursday.send_thursday_boost(u)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to send Thursday boost: {e}")
            return True
        elif cmd == "week":
            target_phone, week_args = _resolve_admin_target_phone(admin_user, args)
            if not week_args:
                send_whatsapp(to=admin_user.phone, text="Usage: admin week <phone> <week_no>")
                return True
            try:
                week_no = int(week_args[0])
            except Exception:
                send_whatsapp(to=admin_user.phone, text="Week number must be an integer.")
                return True
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            try:
                weekflow.run_week_flow(u, week_no=week_no)
                send_whatsapp(to=admin_user.phone, text=f"Week flow triggered for week {week_no} (includes Sunday review).")
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to run week flow: {e}")
            return True
        elif cmd == "start":
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
            _start_assessment_async(u)
            send_whatsapp(to=admin_user.phone, text=f"Started assessment for {display_full_name(u)} ({u.phone})")
            return True
        elif cmd == "status":
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
                active = get_active_domain(u)
                latest_run = s.execute(
                    select(AssessmentRun).where(AssessmentRun.user_id == u.id).order_by(desc(AssessmentRun.id))
                ).scalars().first()
            status_txt = "in_progress" if active else ("completed" if latest_run and getattr(latest_run, "finished_at", None) else "idle")
            send_whatsapp(to=admin_user.phone, text=f"Status for {display_full_name(u)} ({u.phone}): {status_txt}")
            return True
        elif cmd == "assessment":
            target_phone, _ = _resolve_admin_target_phone(admin_user, args)
            print(f"[admin][assessment] start admin_id={admin_user.id} target_phone={target_phone}")
            with SessionLocal() as s:
                u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                if not u:
                    scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                    print(f"[admin][assessment] user_not_found target_phone={target_phone} scope={scope_txt}")
                    send_whatsapp(
                        to=admin_user.phone,
                        text=f"User with phone {target_phone} not found{scope_txt}."
                    )
                    return True
                latest_run = s.execute(
                    select(AssessmentRun).where(AssessmentRun.user_id == u.id).order_by(desc(AssessmentRun.id))
                ).scalars().first()
            print(f"[admin][assessment] resolved user_id={u.id} latest_run_id={getattr(latest_run,'id',None)}")
            if not latest_run:
                send_whatsapp(to=admin_user.phone, text=f"No assessment run found for {display_full_name(u)} ({u.phone}).")
                return True
            try:
                print(f"[admin][assessment] generate start run_id={latest_run.id}")
                generate_assessment_dashboard_html(latest_run.id)
                print(f"[admin][assessment] generate ok run_id={latest_run.id}")
                dash_url = _public_report_url(u.id, "assessment.html")
                bust = int(time.time())
                send_whatsapp(
                    to=admin_user.phone,
                    text=(
                        f"Assessment refreshed for {display_full_name(u)} ({u.phone}) "
                        f"[run #{latest_run.id}]:\nLink: {dash_url}?ts={bust}"
                    )
                )
                return True
            except Exception as e:
                print(f"[admin][assessment] generate failed run_id={getattr(latest_run,'id',None)} err={e!r}")
                send_whatsapp(to=admin_user.phone, text=f"Failed to regenerate assessment report: {e}")
                return True
        elif cmd == "users":
            if club_scope_id is None:
                send_whatsapp(to=admin_user.phone, text="Set your club first via 'admin set global <club_id>'.")
                return True
            try:
                from .reporting import generate_club_users_html
                path = generate_club_users_html(club_scope_id)
                fname = os.path.basename(path)
                url = _public_report_url_global(fname)
                send_whatsapp(
                    to=admin_user.phone,
                    text=f"Club users report refreshed:\n{url}?ts={int(time.time())}"
                )
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate club users report: {e}")
            return True
        elif cmd == "detailed":
            if not args:
                u = admin_user
            else:
                arg = args[0].lower()
                if arg in {"me", "my", "self"}:
                    u = admin_user
                else:
                    target_phone, _ = _resolve_admin_target_phone(admin_user, args)
                    with SessionLocal() as s:
                        u = _admin_lookup_user_by_phone(s, target_phone, admin_user)
                    if not u:
                        scope_txt = " in your club" if getattr(admin_user, "club_id", None) is not None else ""
                        send_whatsapp(
                            to=admin_user.phone,
                            text=f"User with phone {target_phone} not found{scope_txt}."
                        )
                        return True
            try:
                # Generate the detailed (grouped) PDF via reporting module
                _ = generate_detailed_report_pdf_by_user(u.id)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate detailed report: {e}")
                return True
            pdf = _public_report_url(u.id, "detailed.pdf")
            send_whatsapp(to=admin_user.phone, text=f"Detailed report for {display_full_name(u)} ({u.phone}):\nPDF: {pdf}")
            return True
        elif cmd == "summary":
            # Usage: admin summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]
            start_str, end_str = _parse_summary_range(args)
            try:
                pdf_path = generate_assessment_summary_pdf(start_str, end_str, club_id=club_scope_id)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate summary report: {e}")
                return True
            # Derive filename from path for public URL
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"Assessment summary {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
        elif cmd == "okr-summary":
            # Usage: admin okr-summary [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]
            # This variant EXCLUDES the llm prompt field
            start_str, end_str = _parse_summary_range(args)
            try:
                gen = _resolve_okr_summary_gen()
                pdf_path = gen(start_str, end_str, club_id=club_scope_id)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate OKR summary: {e}")
                return True
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"OKR summary (no llm prompt) {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
        elif cmd == "okr-summaryllm":
            # Usage: admin okr-summaryllm [today|last7d|last30d|thisweek|YYYY-MM-DD YYYY-MM-DD]
            # This variant INCLUDES the llm prompt field in the summary
            start_str, end_str = _parse_summary_range(args)
            try:
                gen = _resolve_okr_summary_gen_llm()
                pdf_path = gen(start_str, end_str, club_id=club_scope_id)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate OKR summary (with llm prompt): {e}")
                return True
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"OKR summary (with llm prompt) {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
    except Exception as e:
        send_whatsapp(to=admin_user.phone, text=f"Admin error: {e}")
        return True
    # Unknown subcommand
    send_whatsapp(to=admin_user.phone, text="Unknown admin command. Try: create/start/status/report")
    return True


def _handle_global_command(admin_user: User, text: str) -> bool:
    msg = (text or "").strip()
    if not msg.lower().startswith("global"):
        return False
    if not _is_global_admin(admin_user):
        send_whatsapp(to=admin_user.phone, text="Global commands are restricted to global admins.")
        return True
    parts = msg.split()
    if len(parts) == 1 or (len(parts) >= 2 and parts[1].lower() in {"help", "?"}):
        send_whatsapp(to=admin_user.phone, text=GLOBAL_USAGE)
        return True
    cmd = parts[1].lower()
    args = parts[2:]
    try:
        if cmd == "set":
            if not args:
                send_whatsapp(
                    to=admin_user.phone,
                    text="Usage:\n- global set club <club_id|slug>\n- global set user <phone> <club_id|slug>"
                )
                return True
            sub = args[0].lower()
            if sub == "club":
                if len(args) < 2:
                    send_whatsapp(to=admin_user.phone, text="Usage: global set club <club_id|slug>")
                    return True
                club_token = args[1]
                with SessionLocal() as s:
                    club = _find_club_by_identifier(s, club_token)
                    if not club:
                        send_whatsapp(to=admin_user.phone, text=f"Club '{club_token}' not found.")
                        return True
                    row = s.query(User).filter(User.id == admin_user.id).one_or_none()
                    if not row:
                        send_whatsapp(to=admin_user.phone, text="Unable to reload your admin profile; try again.")
                        return True
                    row.club_id = getattr(club, "id", None)
                    s.commit()
                    admin_user.club_id = getattr(club, "id", None)
                send_whatsapp(
                    to=admin_user.phone,
                    text=f"Admin club updated to {_club_label(club)} (id={getattr(club, 'id', None)}).",
                )
                return True
            if sub == "user":
                if len(args) < 3:
                    send_whatsapp(to=admin_user.phone, text="Usage: global set user <phone> <club_id|slug>")
                    return True
                target_phone = _norm_phone(args[1])
                club_token = args[2]
                with SessionLocal() as s:
                    club = _find_club_by_identifier(s, club_token)
                    if not club:
                        send_whatsapp(to=admin_user.phone, text=f"Club '{club_token}' not found.")
                        return True
                    target = s.execute(select(User).where(User.phone == target_phone)).scalar_one_or_none()
                if not target:
                    send_whatsapp(to=admin_user.phone, text=f"User with phone {args[1]} not found.")
                    return True
                with SessionLocal() as s:
                    db_user = s.execute(select(User).where(User.id == target.id)).scalar_one_or_none()
                    if not db_user:
                        send_whatsapp(to=admin_user.phone, text="Unable to reload target user; try again.")
                        return True
                    db_user.club_id = getattr(club, "id", None)
                    s.commit()
                target.club_id = getattr(club, "id", None)
                send_whatsapp(
                    to=admin_user.phone,
                    text=f"Updated {display_full_name(target)} ({target.phone}) to {_club_label(club)} (id={getattr(club, 'id', None)}).",
                )
                return True
            send_whatsapp(
                to=admin_user.phone,
                text="Unknown global set command. Use:\n- global set club <club>\n- global set user <phone> <club>"
            )
            return True
        if cmd == "users":
            try:
                html_path = generate_global_users_html()
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate global users report: {e}")
                return True
            filename = os.path.basename(html_path)
            url = _public_report_url_global(filename)
            bust = int(time.time())
            send_whatsapp(
                to=admin_user.phone,
                text=f"Global users listing ready:\n{url}?ts={bust}"
            )
            return True
        if cmd == "summary":
            start_str, end_str = _parse_summary_range(args)
            try:
                pdf_path = generate_assessment_summary_pdf(start_str, end_str, club_id=None)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate global summary report: {e}")
                return True
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"Global assessment summary {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
        if cmd == "okr-summary":
            start_str, end_str = _parse_summary_range(args)
            try:
                gen = _resolve_okr_summary_gen()
                pdf_path = gen(start_str, end_str, club_id=None)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate global OKR summary: {e}")
                return True
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"Global OKR summary {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
        if cmd == "okr-summaryllm":
            start_str, end_str = _parse_summary_range(args)
            try:
                gen = _resolve_okr_summary_gen_llm()
                pdf_path = gen(start_str, end_str, club_id=None)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to generate global OKR summary (with llm prompt): {e}")
                return True
            filename = os.path.basename(pdf_path)
            url = _public_report_url_global(filename)
            send_whatsapp(
                to=admin_user.phone,
                text=(
                    f"Global OKR summary (with llm prompt) {start_str} → {end_str}\n"
                    f"PDF: {url}"
                ),
            )
            return True
    except Exception as e:
        send_whatsapp(to=admin_user.phone, text=f"Global admin error: {e}")
        return True
    send_whatsapp(to=admin_user.phone, text="Unknown global command. Try: global summary / global okr-summary")
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Webhooks
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/webhooks/twilio")
async def twilio_inbound(request: Request):
    """
    Accepts x-www-form-urlencoded payloads from Twilio (SMS/WhatsApp).
    Parses the raw body for maximum compatibility, resolves/creates user, logs
    inbound immediately upon receipt, and then routes to the assessor.
    """
    try:
        raw = (await request.body()).decode("utf-8")
        data = parse_qs(raw, keep_blank_values=True)

        body = (data.get("Body", [""])[0] or "").strip()
        button_payload = (data.get("ButtonPayload", [""])[0] or "").strip()
        button_text = (data.get("ButtonText", [""])[0] or "").strip()
        if button_payload:
            body = button_payload
        elif not body and button_text:
            body = button_text
        from_raw = (data.get("From", [""])[0] or "").strip()
        if not from_raw:
            return Response(content="", media_type="text/plain", status_code=400)

        phone = from_raw.replace("whatsapp:", "") if from_raw.startswith("whatsapp:") else from_raw
        channel = "whatsapp" if from_raw.startswith("whatsapp:") else "sms"

        user = _get_or_create_user(phone, create_if_missing=False)

        if not user:
            unknown_msg = " ".join((body or "").strip().split())
            unknown_lower = unknown_msg.lower()
            if unknown_lower.startswith("global") or unknown_lower.startswith("admin"):
                try:
                    send_whatsapp(to=phone, text="Sorry, admin commands are restricted to superusers.")
                except Exception:
                    pass
                return Response(content="", media_type="text/plain", status_code=200)

            pending_first, pending_surname = _extract_pending_confirmed_name(phone)
            if _require_name_fields(pending_first, pending_surname) and _is_affirmative_name_confirm(unknown_msg):
                created = _get_or_create_user(
                    phone,
                    create_if_missing=True,
                    first_name=pending_first,
                    surname=pending_surname,
                )
                if created:
                    user = created
                    _log_inbound_direct(user, channel, body, from_raw)
                    _start_assessment_async(user, force_intro=True)
                return Response(content="", media_type="text/plain", status_code=200)

            first_name, surname = _extract_valid_name_from_reply(unknown_msg)
            awaiting_name_reply = _awaiting_unknown_user_name_reply(phone)
            if _require_name_fields(first_name, surname) and (
                awaiting_name_reply or _require_name_fields(pending_first, pending_surname)
            ):
                try:
                    send_whatsapp(to=phone, text=_unknown_user_name_confirm_text(first_name, surname))
                except Exception:
                    pass
                return Response(content="", media_type="text/plain", status_code=200)

            if _require_name_fields(pending_first, pending_surname):
                try:
                    send_whatsapp(to=phone, text=_unknown_user_name_confirm_text(pending_first, pending_surname))
                except Exception:
                    pass
                return Response(content="", media_type="text/plain", status_code=200)

            try:
                send_whatsapp(to=phone, text=UNKNOWN_USER_NAME_PROMPT)
            except Exception:
                pass
            return Response(content="", media_type="text/plain", status_code=200)

        # Global admin commands (broader scope)
        if body.lower().startswith("global"):
            _log_inbound_direct(user, channel, body, from_raw)
            if _is_global_admin(user):
                if _handle_global_command(user, body):
                    return Response(content="", media_type="text/plain", status_code=200)
                return Response(content="", media_type="text/plain", status_code=200)
            else:
                print(f"[global] ignored command from non-global user_id={user.id}")
                try:
                    send_whatsapp(to=user.phone, text="Sorry, global commands are restricted to global admins.")
                except Exception:
                    pass
                return Response(content="", media_type="text/plain", status_code=200)

        # Admin commands must never fall through to normal flow
        if body.lower().startswith("admin"):
            _log_inbound_direct(user, channel, body, from_raw)
            if _is_admin_user(user):
                if _handle_admin_command(user, body, source_phone=phone):
                    return Response(content="", media_type="text/plain", status_code=200)
                return Response(content="", media_type="text/plain", status_code=200)
            else:
                print(f"[admin] ignored admin cmd from non-admin user_id={user.id} is_superuser={getattr(user,'is_superuser',None)}")
                try:
                    send_whatsapp(to=user.phone, text="Sorry, admin commands are restricted to superusers.")
                except Exception:
                    pass
                return Response(content="", media_type="text/plain", status_code=200)

        lower_body = body.lower()

        # ✅ log inbound immediately upon receipt (before processing)
        _log_inbound_direct(user, channel, body, from_raw)

        if lower_body in {"stop", "unsubscribe", "opt out", "opt-out", "cancel marketing"}:
            try:
                with SessionLocal() as s:
                    pref = (
                        s.query(UserPreference)
                        .filter(UserPreference.user_id == user.id, UserPreference.key == "marketing_opt_in")
                        .one_or_none()
                    )
                    if pref:
                        pref.value = "0"
                    else:
                        s.add(UserPreference(user_id=user.id, key="marketing_opt_in", value="0"))
                    s.commit()
                msg = "You’re unsubscribed from marketing updates. You’ll still receive essential coaching and account messages."
                if channel == "sms":
                    send_sms(to=user.phone, text=msg)
                else:
                    send_whatsapp(to=user.phone, text=msg)
            except Exception:
                pass
            return Response(content="", media_type="text/plain", status_code=200)

        # User coaching note command (available anytime)
        if lower_body.startswith("coachmycoach"):
            coachmycoach.handle(user, body)
            return Response(content="", media_type="text/plain", status_code=200)

        if lower_body.startswith("psych") or psych.has_active_state(user.id):
            try:
                psych.handle_message(user, body)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Psych check failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        if sunday.has_active_state(user.id):
            try:
                sunday.handle_message(user, body)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Sunday review failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)

        if lower_body.startswith("kickoff"):
            send_whatsapp(
                to=user.phone,
                text="Kickoff has been retired. We’ll continue with your standard weekly coaching flow.",
            )
            return Response(content="", media_type="text/plain", status_code=200)

        if lower_body.startswith("midweek") or lower_body.startswith("wednesday"):
            try:
                wednesday.send_midweek_check(user)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Midweek failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body.startswith("week"):
            parts = lower_body.split()
            week_no = 1
            if len(parts) > 1:
                try:
                    week_no = int(parts[1])
                except Exception:
                    week_no = 1
            try:
                weekflow.run_week_flow(user, week_no=week_no)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Week flow failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body.startswith("sunday"):
            try:
                sunday.send_sunday_review(user)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Sunday review failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body.startswith("tuesday"):
            try:
                tuesday.send_tuesday_check(user)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Tuesday check failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body.startswith("thursday"):
            try:
                thursday.send_thursday_boost(user)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Thursday boost failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body.startswith("saturday"):
            try:
                saturday.send_saturday_keepalive(user)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Saturday keepalive failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body.startswith("sunday"):
            try:
                sunday.send_sunday_review(user)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Sunday review failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)

        if lower_body.startswith("weekstart") or lower_body.startswith("monday") or monday.has_active_state(user.id):
            try:
                monday.handle_message(user, body)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Monday flow failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body.startswith("boost") or lower_body.startswith("friday"):
            try:
                friday.send_boost(user)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Boost failed: {e}")
            return Response(content="", media_type="text/plain", status_code=200)
        # Interactive menu commands
        if lower_body in {"menu", "help", "options"}:
            send_menu_options(user)
            return Response(content="", media_type="text/plain", status_code=200)

        if lower_body == "assessment":
            try:
                print(f"[api] assessment command received for user_id={user.id}")
            except Exception:
                pass
            send_dashboard_link(user)
            return Response(content="", media_type="text/plain", status_code=200)
        if lower_body == "progress":
            try:
                from .reporting import generate_progress_report_html
                path = generate_progress_report_html(user.id)
                url = _public_report_url(user.id, "progress.html")
                send_whatsapp(to=user.phone, text=f"Your progress report: {url}")
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Couldn't refresh your progress report: {e}")
            return Response(content="", media_type="text/plain", status_code=200)

        # Explicit assessment entry (including marketing CTA replies from WhatsApp/SMS)
        normalized_body = " ".join(re.sub(r"[^a-z0-9\s]+", " ", (body or "").strip().lower()).split())
        marketing_start_tokens = {
            "send",
            "start",
            "hit start",
            "hit send",
            "tap start",
            "tap send",
            "start free assessment",
            "hit start to start free assessment",
            "hit send to start free assessment",
            "free assessment",
            "start assessment",
            "hi",
            "hello",
        }
        looks_like_marketing_cta = (
            normalized_body in marketing_start_tokens
            or (
                "hit send" in normalized_body
                and "start" in normalized_body
                and "free assessment" in normalized_body
            )
        )
        if looks_like_marketing_cta:
            # Clear any stale active session and force fresh consent/name capture
            _start_assessment_async(user, force_intro=True)
            return Response(content="", media_type="text/plain", status_code=200)

        # Active assessment session handling (consent/name or in-progress)
        try:
            from .models import AssessSession
            with SessionLocal() as s:
                active_sess = (
                    s.query(AssessSession)
                    .filter(AssessSession.user_id == user.id, AssessSession.is_active == True)  # noqa: E712
                    .first()
                )
            if active_sess:
                _continue_assessment_async(user, body)
                return Response(content="", media_type="text/plain", status_code=200)
            # If no active session but consent not recorded, continue assessment flow to capture consent/name
            has_consent = bool(getattr(user, "consent_given", False)) \
                          or bool(getattr(user, "consent_at", None)) \
                          or bool(getattr(user, "consent_yes_at", None))
            if not has_consent:
                _continue_assessment_async(user, body)
                return Response(content="", media_type="text/plain", status_code=200)
        except Exception:
            pass

        if general_support.has_active_state(user.id):
            general_support.handle_message(user, body)
            return Response(content="", media_type="text/plain", status_code=200)

        # No explicit command matched; treat as a freeform check-in for history
        try:
            _record_freeform_checkin(user, body)
        except Exception:
            pass
        # Acknowledge silently
        return Response(content="", media_type="text/plain", status_code=200)

    except Exception as e:
        try:
            import traceback
            traceback.print_exc()
        except Exception:
            pass
        return Response(content="", media_type="text/plain", status_code=500)


# ──────────────────────────────────────────────────────────────────────────────
# Health / Root
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    reports_dir, reports_source = resolve_reports_dir_with_source()
    return {
        "ok": True,
        "env": ENV,
        "timezone": "Europe/London",
        "app_start_uk": APP_START_UK_STR,
        "uptime_seconds": _uptime_seconds(),
        "reports_dir": reports_dir,
        "reports_dir_source": reports_source,
        "reports_dir_exists": os.path.isdir(reports_dir),
    }

@app.get("/")
def root():
    return {
        "service": "ai-coach",
        "status": "ok",
        "env": ENV,
        "timezone": "Europe/London",
        "app_start_uk": APP_START_UK_STR,
        "uptime_seconds": _uptime_seconds(),
    }


@app.get("/robots.txt", include_in_schema=False)
def robots_txt():
    """Serve a small robots.txt so crawlers don't get a 404."""
    return Response(content=ROBOTS_TXT, media_type="text/plain")

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Serve a tiny placeholder favicon to suppress 404 noise."""
    path = os.path.join(os.getcwd(), "public", "favicon.png")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    return Response(status_code=204)

@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon():
    """Serve a tiny placeholder apple-touch-icon."""
    path = os.path.join(os.getcwd(), "public", "apple-touch-icon.png")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    return Response(status_code=204)

@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon_precomposed():
    """Serve a tiny placeholder apple-touch-icon-precomposed."""
    path = os.path.join(os.getcwd(), "public", "apple-touch-icon-precomposed.png")
    if os.path.exists(path):
        return FileResponse(path, media_type="image/png")
    return Response(status_code=204)


# ──────────────────────────────────────────────────────────────────────────────
# Debug routes
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/debug/routes")
def debug_routes():
    out = []
    try:
        for r in app.router.routes:
            try:
                out.append({
                    "path": getattr(r, "path", None),
                    "name": getattr(r, "name", None),
                    "methods": sorted(list(getattr(r, "methods", []) or [])),
                    "endpoint": f"{getattr(getattr(r, 'endpoint', None), '__module__', None)}.{getattr(getattr(r, 'endpoint', None), '__name__', None)}",
                })
            except Exception:
                out.append({"path": getattr(r, 'path', None), "name": getattr(r, 'name', None)})
    except Exception as e:
        out.append({"error": repr(e)})
    return out


@app.post("/webhooks/twilio-status")
async def twilio_status_callback(request: Request):
    """
    Twilio status callback for message delivery events.
    """
    try:
        form = await request.form()
    except Exception:
        form = {}
    payload = {
        "sid": form.get("MessageSid") or form.get("SmsSid"),
        "status": form.get("MessageStatus") or form.get("SmsStatus"),
        "to": form.get("To"),
        "from": form.get("From"),
        "error_code": form.get("ErrorCode"),
        "error_message": form.get("ErrorMessage"),
    }
    debug_log("twilio status", payload, tag="twilio")
    try:
        to_raw = (payload.get("to") or "").strip()
        to_phone = to_raw.split("whatsapp:", 1)[1] if to_raw.startswith("whatsapp:") else to_raw
        user_id = None
        if to_phone:
            with SessionLocal() as s:
                u = s.execute(select(User).where(User.phone == to_phone)).scalar_one_or_none()
                user_id = getattr(u, "id", None) if u else None
        status_val = str(payload.get("status") or "").strip().lower()
        failed_states = {"failed", "undelivered"}
        audit_status = "error" if payload.get("error_code") or status_val in failed_states else "ok"
        with SessionLocal() as s:
            s.add(
                JobAudit(
                    job_name="twilio_status",
                    status=audit_status,
                    payload={
                        **payload,
                        "user_id": user_id,
                    },
                    error=str(payload.get("error_message") or "") or None,
                )
            )
            s.commit()
    except Exception:
        pass
    return {"ok": True}


# Mount routes
app.include_router(router)
# Admin routes UI (no auth on this router; protect via network or middleware if needed)
app.include_router(admin_routes.admin)

# ──────────────────────────────────────────────────────────────────────────────
# Admin (superuser) endpoints
# ──────────────────────────────────────────────────────────────────────────────
admin = APIRouter(prefix="/admin", tags=["admin"])

def _require_admin(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
) -> User:
    expected = (os.getenv("ADMIN_API_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="ADMIN_API_TOKEN not configured")
    if x_admin_token != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin token")
    if not x_admin_user_id:
        raise HTTPException(status_code=400, detail="X-Admin-User-Id header required")
    try:
        admin_user_id = int(x_admin_user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="X-Admin-User-Id must be an integer")
    with SessionLocal() as s:
        admin_user = s.execute(select(User).where(User.id == admin_user_id)).scalar_one_or_none()
        if not admin_user:
            raise HTTPException(status_code=404, detail="Admin user not found")
        if _user_admin_role(admin_user) not in {ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}:
            raise HTTPException(status_code=403, detail="User lacks admin privileges")
        if getattr(admin_user, "club_id", None) is None:
            raise HTTPException(status_code=400, detail="Admin user missing club association")
    return admin_user

def _ensure_club_scope(admin_user: User, target_user: User) -> None:
    if getattr(admin_user, "club_id", None) != getattr(target_user, "club_id", None):
        raise HTTPException(status_code=403, detail="User belongs to a different club")

def _uk_range_bounds():
    """Return (day_start_utc, day_end_utc, week_start_utc, week_end_utc) as naive UTC datetimes."""
    now_uk = datetime.now(UK_TZ)
    day_start_uk = datetime(now_uk.year, now_uk.month, now_uk.day, tzinfo=UK_TZ)
    day_end_uk = day_start_uk + timedelta(days=1)
    week_start_uk = day_start_uk - timedelta(days=day_start_uk.weekday())
    week_end_uk = week_start_uk + timedelta(days=7)

    def _to_utc_naive(dt_val: datetime) -> datetime:
        return dt_val.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    return (
        _to_utc_naive(day_start_uk),
        _to_utc_naive(day_end_uk),
        _to_utc_naive(week_start_uk),
        _to_utc_naive(week_end_uk),
    )

def _parse_uk_date(value: str, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if "T" in raw:
            dt = datetime.fromisoformat(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UK_TZ)
        else:
            d = date.fromisoformat(raw)
            dt = datetime(d.year, d.month, d.day, tzinfo=UK_TZ)
            if end_of_day:
                dt = dt + timedelta(days=1)
        return dt.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
    except Exception:
        return None

def _parse_block_list(val: object | None) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if isinstance(val, str):
        try:
            return admin_routes._parse_list_field(val) or []  # type: ignore[attr-defined]
        except Exception:
            cleaned = val.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
            return [v.strip() for v in cleaned.split(",") if v.strip()]
    return [str(val).strip()] if str(val).strip() else []


LIVE_TEMPLATE_ALLOWED_MODELS = {"gpt-5-mini", "gpt-5.1"}


def _normalize_model_override(raw: object | None) -> str | None:
    val = str(raw or "").strip().lower()
    if not val:
        return None
    aliases = {
        "gpt5-mini": "gpt-5-mini",
        "gpt5.1": "gpt-5.1",
    }
    return aliases.get(val, val)


def _ensure_live_template_model_allowed(model_override: str | None, *, context: str) -> None:
    if not model_override:
        return
    if model_override in LIVE_TEMPLATE_ALLOWED_MODELS:
        return
    allowed = ", ".join(sorted(LIVE_TEMPLATE_ALLOWED_MODELS))
    raise HTTPException(
        status_code=400,
        detail=f"{context} model_override must be one of: {allowed}",
    )


def _parse_kb_tags(val: object | None) -> list[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v).strip() for v in val if str(v).strip()]
    if isinstance(val, str):
        raw = val.strip()
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(v).strip() for v in parsed if str(v).strip()]
        except Exception:
            pass
        return [v.strip() for v in re.split(r"[,\n]+", raw) if v.strip()]
    return [str(val).strip()] if str(val).strip() else []


APP_ENGAGEMENT_PROVIDER = "healthsense-app"
APP_ENGAGEMENT_PRODUCT = "app"
APP_ENGAGEMENT_TAG = "app_engagement"
INTRO_SOURCE_TYPE = "app_intro"
INTRO_PILLAR_KEY = "intro"
INTRO_CONCEPT_CODE = "welcome"
INTRO_TITLE_DEFAULT = "Welcome to HealthSense"
INTRO_WELCOME_TEMPLATE_DEFAULT = (
    "{first_name}, Welcome to HealthSense please listen to our introductory podcast "
    "to get started on your journey."
)
INTRO_BODY_DEFAULT = (
    "Welcome to HealthSense. Start by listening to the introduction, then review this guide "
    "to understand how your weekly coaching flow works."
)
ONBOARDING_PREF_KEYS = {
    "first_login": "first_app_login_at",
    "assessment_reviewed": "assessment_reviewed_at",
    "intro_presented": "intro_content_presented_at",
    "intro_listened": "intro_content_listened_at",
    "intro_read": "intro_content_read_at",
    "coaching_enabled_at": "coaching_auto_enabled_at",
}


def _log_app_engagement_event(
    *,
    user_id: int,
    unit_type: str,
    meta: dict | None = None,
) -> None:
    try:
        log_usage_event(
            user_id=user_id,
            provider=APP_ENGAGEMENT_PROVIDER,
            product=APP_ENGAGEMENT_PRODUCT,
            model=None,
            units=1.0,
            unit_type=unit_type,
            tag=APP_ENGAGEMENT_TAG,
            meta=meta or {},
        )
    except Exception as e:
        print(f"[usage] app engagement log failed: {e}")


def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _intro_flow_enabled() -> bool:
    return _is_truthy_env(os.getenv("APP_INTRO_FLOW_ENABLED"))


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _parse_pref_timestamp(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if ts.tzinfo is not None:
            ts = ts.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
        return ts
    except Exception:
        return None


def _pref_row(session, user_id: int, key: str) -> UserPreference | None:
    return (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == key)
        .order_by(UserPreference.updated_at.desc())
        .first()
    )


def _pref_value(session, user_id: int, key: str) -> str | None:
    row = _pref_row(session, user_id, key)
    if not row:
        return None
    val = str(row.value or "").strip()
    return val or None


def _set_pref_value(
    session,
    user_id: int,
    key: str,
    value: str,
    *,
    only_if_missing: bool = False,
) -> bool:
    row = _pref_row(session, user_id, key)
    if row:
        if only_if_missing and str(row.value or "").strip():
            return False
        row.value = value
        return True
    session.add(UserPreference(user_id=user_id, key=key, value=value))
    return True


def _coaching_enabled_for_user(session, user_id: int) -> bool:
    coaching_row = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == "coaching")
        .order_by(UserPreference.updated_at.desc())
        .first()
    )
    if coaching_row is not None:
        return str(coaching_row.value or "").strip() == "1"
    # Backward-compat fallback for older data.
    legacy_row = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == "auto_daily_prompts")
        .order_by(UserPreference.updated_at.desc())
        .first()
    )
    return bool(legacy_row and str(legacy_row.value or "").strip() == "1")

def _latest_assessment_completed_at(session, user_id: int) -> str | None:
    finished_at = (
        session.execute(
            select(AssessmentRun.finished_at)
            .where(AssessmentRun.user_id == user_id, AssessmentRun.finished_at.isnot(None))
            .order_by(desc(AssessmentRun.finished_at), desc(AssessmentRun.id))
        )
        .scalars()
        .first()
    )
    if not finished_at:
        return None
    try:
        return finished_at.replace(microsecond=0).isoformat()
    except Exception:
        return str(finished_at)


def _latest_intro_content_row(session, *, active_only: bool = True) -> ContentLibraryItem | None:
    q = (
        session.query(ContentLibraryItem)
        .filter(ContentLibraryItem.source_type == INTRO_SOURCE_TYPE)
        .order_by(desc(ContentLibraryItem.updated_at), desc(ContentLibraryItem.id))
    )
    if active_only:
        q = q.filter(ContentLibraryItem.status == "published")
    return q.first()


def _intro_message_template_from_row(row: ContentLibraryItem | None) -> str:
    if not row:
        return INTRO_WELCOME_TEMPLATE_DEFAULT
    tags = row.tags if isinstance(row.tags, dict) else {}
    raw = ""
    if isinstance(tags, dict):
        raw = str(tags.get("welcome_message_template") or "").strip()
    return raw or INTRO_WELCOME_TEMPLATE_DEFAULT


def _intro_body_from_row(row: ContentLibraryItem | None) -> str:
    if row and str(getattr(row, "body", "") or "").strip():
        return str(row.body).strip()
    return INTRO_BODY_DEFAULT


def _render_intro_message(template: str, user: User | None) -> str:
    first_name = ""
    if user:
        first_name = (getattr(user, "first_name", None) or "").strip()
        if not first_name:
            display = (display_full_name(user) or "").strip()
            first_name = (display.split(" ")[0] if display else "").strip()
    first_name = first_name or "there"
    rendered = str(template or "").replace("{first_name}", first_name)
    rendered = rendered.replace("{display_name}", display_full_name(user) if user else first_name)
    return rendered.strip() or INTRO_WELCOME_TEMPLATE_DEFAULT.replace("{first_name}", first_name)


def _get_onboarding_state(session, user_id: int) -> dict:
    assessment_completed_val = _latest_assessment_completed_at(session, user_id)
    first_login_val = _pref_value(session, user_id, ONBOARDING_PREF_KEYS["first_login"])
    assessment_val = _pref_value(session, user_id, ONBOARDING_PREF_KEYS["assessment_reviewed"])
    intro_presented_val = _pref_value(session, user_id, ONBOARDING_PREF_KEYS["intro_presented"])
    intro_listened_val = _pref_value(session, user_id, ONBOARDING_PREF_KEYS["intro_listened"])
    intro_read_val = _pref_value(session, user_id, ONBOARDING_PREF_KEYS["intro_read"])
    coaching_enabled_at_val = _pref_value(session, user_id, ONBOARDING_PREF_KEYS["coaching_enabled_at"])
    intro_completed_at_val = intro_listened_val or intro_read_val
    return {
        "assessment_completed_at": assessment_completed_val,
        "first_app_login_at": first_login_val,
        "assessment_reviewed_at": assessment_val,
        "intro_content_presented_at": intro_presented_val,
        "intro_content_listened_at": intro_listened_val,
        "intro_content_read_at": intro_read_val,
        "intro_content_completed_at": intro_completed_at_val,
        "coaching_auto_enabled_at": coaching_enabled_at_val,
    }


def _build_intro_payload(session, user: User, onboarding_state: dict | None = None) -> dict:
    onboarding = onboarding_state or _get_onboarding_state(session, int(user.id))
    enabled = _intro_flow_enabled()
    row = _latest_intro_content_row(session, active_only=True) if enabled else None
    first_login_at = str(onboarding.get("first_app_login_at") or "").strip() or None
    coaching_enabled = _coaching_enabled_for_user(session, int(user.id))
    coaching_enabled_at_raw = str(onboarding.get("coaching_auto_enabled_at") or "").strip() or None
    coaching_enabled_at = _parse_pref_timestamp(coaching_enabled_at_raw)
    coaching_recently_enabled = bool(
        coaching_enabled
        and coaching_enabled_at is not None
        and datetime.utcnow() <= (coaching_enabled_at + timedelta(hours=24))
    )
    should_show = bool(enabled and first_login_at and (not coaching_enabled or coaching_recently_enabled))
    title = str(getattr(row, "title", "") or "").strip() or INTRO_TITLE_DEFAULT
    message_template = _intro_message_template_from_row(row)
    message = _render_intro_message(message_template, user)
    body = _intro_body_from_row(row)
    return {
        "enabled": enabled,
        "should_show": should_show,
        "content_id": int(row.id) if row else None,
        "title": title,
        "message": message,
        "body": body,
        "podcast_url": _normalize_reports_url(getattr(row, "podcast_url", None)),
        "podcast_voice": getattr(row, "podcast_voice", None),
        "welcome_message_template": message_template,
        "coaching_enabled": coaching_enabled,
        "coaching_recently_enabled": coaching_recently_enabled,
        "onboarding": onboarding,
    }


def evaluate_and_enable_coaching(user_id: int) -> bool:
    with SessionLocal() as s:
        assessment_completed_at = _latest_assessment_completed_at(s, user_id)
        first_login_at = _pref_value(s, user_id, ONBOARDING_PREF_KEYS["first_login"])
        assessment_reviewed_at = _pref_value(s, user_id, ONBOARDING_PREF_KEYS["assessment_reviewed"])
        intro_listened_at = _pref_value(s, user_id, ONBOARDING_PREF_KEYS["intro_listened"])
        intro_read_at = _pref_value(s, user_id, ONBOARDING_PREF_KEYS["intro_read"])
        intro_completed = bool(intro_listened_at or intro_read_at)
        if not (assessment_completed_at and first_login_at and assessment_reviewed_at and intro_completed):
            return False
        if _coaching_enabled_for_user(s, user_id):
            return False
    try:
        ok = scheduler.enable_coaching(user_id)
    except Exception as e:
        print(f"[onboarding] coaching auto-enable failed user_id={user_id}: {e}")
        return False
    if not ok:
        return False
    with SessionLocal() as s:
        changed = _set_pref_value(
            s,
            user_id,
            ONBOARDING_PREF_KEYS["coaching_enabled_at"],
            _utc_now_iso(),
            only_if_missing=True,
        )
        if changed:
            s.commit()
    _log_app_engagement_event(
        user_id=user_id,
        unit_type="coaching_auto_enabled",
        meta={"source": "intro_activation_rule"},
    )
    return True

# ──────────────────────────────────────────────────────────────────────────────
# Public API (v1) – JSON reporting endpoints (admin-authenticated for now)
# ──────────────────────────────────────────────────────────────────────────────
api_v1 = APIRouter(prefix="/api/v1", tags=["api"])


@api_v1.post("/auth/login/request")
def api_auth_login_request(payload: dict, request: Request):
    phone_raw = (payload or {}).get("phone")
    password = (payload or {}).get("password")
    channel = (payload or {}).get("channel") or "auto"
    if not phone_raw:
        raise HTTPException(status_code=400, detail="phone required")
    phone_norm = _norm_phone(str(phone_raw))
    phone_variants = [phone_norm, f"whatsapp:{phone_norm}"]
    with SessionLocal() as s:
        user = s.execute(select(User).where(User.phone.in_(phone_variants))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        has_password = bool(getattr(user, "password_hash", None))
        if has_password:
            if not password or not _verify_password(str(password), getattr(user, "password_hash", None)):
                raise HTTPException(status_code=401, detail="invalid credentials")
        user_id = int(user.id)
        user_phone = str(user.phone)
        code = f"{secrets.randbelow(1_000_000):06d}"
        otp = AuthOtp(
            user_id=user_id,
            channel=channel,
            purpose="login_2fa",
            code_hash=_hash_otp(code),
            expires_at=datetime.utcnow() + timedelta(minutes=_OTP_TTL_MINUTES),
            ip=getattr(request.client, "host", None),
            user_agent=request.headers.get("user-agent"),
        )
        s.add(otp)
        s.commit()
        s.refresh(otp)
        otp_id = int(otp.id)
        otp_expires_at = otp.expires_at
    try:
        channel_used = _send_auth_code(
            user_id=user_id,
            user_phone=user_phone,
            code=code,
            channel=channel,
            purpose_label="login code",
        )
    except Exception as e:
        print(
            f"[auth][otp] login send failed user_id={user_id} channel={channel} phone={user_phone} error={e}"
        )
        raise HTTPException(status_code=500, detail=f"failed to send otp: {e}")
    return {
        "otp_id": otp_id,
        "expires_at": otp_expires_at.isoformat(),
        "setup_required": not has_password,
        "channel": channel_used,
    }


@api_v1.post("/auth/login/verify")
def api_auth_login_verify(payload: dict, request: Request):
    phone_raw = (payload or {}).get("phone")
    otp_id = (payload or {}).get("otp_id")
    code = (payload or {}).get("code")
    remember_me = bool((payload or {}).get("remember_me"))
    if not phone_raw or not otp_id or not code:
        raise HTTPException(status_code=400, detail="phone, otp_id, and code required")
    try:
        otp_id = int(otp_id)
    except Exception:
        raise HTTPException(status_code=400, detail="otp_id must be an integer")
    phone_norm = _norm_phone(str(phone_raw))
    phone_variants = [phone_norm, f"whatsapp:{phone_norm}"]
    now = datetime.utcnow()
    first_login_marked = False
    with SessionLocal() as s:
        user = s.execute(select(User).where(User.phone.in_(phone_variants))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        setup_required = not bool(getattr(user, "password_hash", None))
        otp = s.query(AuthOtp).filter(AuthOtp.id == otp_id, AuthOtp.user_id == user.id).one_or_none()
        if not otp or otp.purpose != "login_2fa":
            raise HTTPException(status_code=404, detail="otp not found")
        if otp.consumed_at is not None:
            raise HTTPException(status_code=400, detail="otp already used")
        if otp.expires_at <= now:
            raise HTTPException(status_code=400, detail="otp expired")
        if not _verify_otp(str(code), otp.code_hash):
            raise HTTPException(status_code=401, detail="invalid otp")
        otp.consumed_at = now
        if getattr(user, "phone_verified_at", None) is None:
            user.phone_verified_at = now
        user_id = user.id
        session_token = secrets.token_urlsafe(32)
        ttl_days = _SESSION_TTL_DAYS_REMEMBER if remember_me else _SESSION_TTL_DAYS
        session = AuthSession(
            user_id=user_id,
            token_hash=_hash_token(session_token),
            created_at=now,
            expires_at=now + timedelta(days=ttl_days),
            ip=getattr(request.client, "host", None),
            user_agent=request.headers.get("user-agent"),
        )
        s.add(session)
        first_login_marked = _set_pref_value(
            s,
            int(user_id),
            ONBOARDING_PREF_KEYS["first_login"],
            _utc_now_iso(),
            only_if_missing=True,
        )
        s.commit()
        expires_at = session.expires_at
    _log_app_engagement_event(
        user_id=int(user_id),
        unit_type="app_login_success",
        meta={"source": "auth_login_verify"},
    )
    if first_login_marked:
        evaluate_and_enable_coaching(int(user_id))
    return {
        "session_token": session_token,
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
        "setup_required": setup_required,
        "remember_days": _SESSION_TTL_DAYS_REMEMBER if remember_me else _SESSION_TTL_DAYS,
    }


@api_v1.post("/auth/password/reset/request")
def api_auth_password_reset_request(payload: dict, request: Request):
    phone_raw = (payload or {}).get("phone")
    channel = (payload or {}).get("channel") or "auto"
    if not phone_raw:
        raise HTTPException(status_code=400, detail="phone required")
    phone_norm = _norm_phone(str(phone_raw))
    phone_variants = [phone_norm, f"whatsapp:{phone_norm}"]
    with SessionLocal() as s:
        user = s.execute(select(User).where(User.phone.in_(phone_variants))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        user_id = int(user.id)
        user_phone = str(user.phone)
        code = f"{secrets.randbelow(1_000_000):06d}"
        otp = AuthOtp(
            user_id=user_id,
            channel=channel,
            purpose="password_reset",
            code_hash=_hash_otp(code),
            expires_at=datetime.utcnow() + timedelta(minutes=_OTP_TTL_MINUTES),
            ip=getattr(request.client, "host", None),
            user_agent=request.headers.get("user-agent"),
        )
        s.add(otp)
        s.commit()
        s.refresh(otp)
        otp_id = int(otp.id)
        otp_expires_at = otp.expires_at
    try:
        channel_used = _send_auth_code(
            user_id=user_id,
            user_phone=user_phone,
            code=code,
            channel=channel,
            purpose_label="password reset code",
        )
    except Exception as e:
        print(
            f"[auth][otp] reset send failed user_id={user_id} channel={channel} phone={user_phone} error={e}"
        )
        raise HTTPException(status_code=500, detail=f"failed to send otp: {e}")
    return {
        "otp_id": otp_id,
        "expires_at": otp_expires_at.isoformat(),
        "channel": channel_used,
    }


@api_v1.post("/auth/password/reset/verify")
def api_auth_password_reset_verify(payload: dict, request: Request):
    phone_raw = (payload or {}).get("phone")
    otp_id = (payload or {}).get("otp_id")
    code = (payload or {}).get("code")
    password = (payload or {}).get("password")
    remember_me = bool((payload or {}).get("remember_me"))
    if not phone_raw or not otp_id or not code or password is None:
        raise HTTPException(status_code=400, detail="phone, otp_id, code, and password required")
    try:
        otp_id = int(otp_id)
    except Exception:
        raise HTTPException(status_code=400, detail="otp_id must be an integer")
    pw_val = str(password).strip()
    if len(pw_val) < 8:
        raise HTTPException(status_code=400, detail="password must be at least 8 characters")
    phone_norm = _norm_phone(str(phone_raw))
    phone_variants = [phone_norm, f"whatsapp:{phone_norm}"]
    now = datetime.utcnow()
    first_login_marked = False
    with SessionLocal() as s:
        user = s.execute(select(User).where(User.phone.in_(phone_variants))).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
        otp = s.query(AuthOtp).filter(AuthOtp.id == otp_id, AuthOtp.user_id == user.id).one_or_none()
        if not otp or otp.purpose != "password_reset":
            raise HTTPException(status_code=404, detail="otp not found")
        if otp.consumed_at is not None:
            raise HTTPException(status_code=400, detail="otp already used")
        if otp.expires_at <= now:
            raise HTTPException(status_code=400, detail="otp expired")
        if not _verify_otp(str(code), otp.code_hash):
            raise HTTPException(status_code=401, detail="invalid otp")
        otp.consumed_at = now
        if getattr(user, "phone_verified_at", None) is None:
            user.phone_verified_at = now
        user.password_hash = _hash_password(pw_val)
        user_id = user.id
        session_token = secrets.token_urlsafe(32)
        ttl_days = _SESSION_TTL_DAYS_REMEMBER if remember_me else _SESSION_TTL_DAYS
        session = AuthSession(
            user_id=user_id,
            token_hash=_hash_token(session_token),
            created_at=now,
            expires_at=now + timedelta(days=ttl_days),
            ip=getattr(request.client, "host", None),
            user_agent=request.headers.get("user-agent"),
        )
        s.add(session)
        first_login_marked = _set_pref_value(
            s,
            int(user_id),
            ONBOARDING_PREF_KEYS["first_login"],
            _utc_now_iso(),
            only_if_missing=True,
        )
        s.commit()
        expires_at = session.expires_at
    _log_app_engagement_event(
        user_id=int(user_id),
        unit_type="app_login_success",
        meta={"source": "auth_password_reset_verify"},
    )
    if first_login_marked:
        evaluate_and_enable_coaching(int(user_id))
    return {
        "session_token": session_token,
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
        "remember_days": _SESSION_TTL_DAYS_REMEMBER if remember_me else _SESSION_TTL_DAYS,
    }

@api_v1.get("/auth/me")
def api_auth_me(request: Request):
    t0 = time.perf_counter()
    user = _get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="session required")
    payload = {
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "surname": user.surname,
            "display_name": display_full_name(user),
            "phone": user.phone,
            "email": getattr(user, "email", None),
        }
    }
    debug_log(
        "auth me ok",
        {"user_id": user.id, "ms": int((time.perf_counter() - t0) * 1000)},
        tag="perf",
    )
    return payload


@api_v1.post("/auth/logout")
def api_auth_logout(request: Request):
    token = _extract_session_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="session token required")
    token_hash = _hash_token(token)
    now = datetime.utcnow()
    with SessionLocal() as s:
        sess = (
            s.query(AuthSession)
            .filter(AuthSession.token_hash == token_hash, AuthSession.revoked_at.is_(None))
            .order_by(AuthSession.id.desc())
            .first()
        )
        if not sess:
            raise HTTPException(status_code=404, detail="session not found")
        sess.revoked_at = now
        s.commit()
    return {"ok": True}

@api_v1.get("/users/{user_id}/assessment")
def api_user_assessment(
    user_id: int,
    request: Request,
    run_id: int | None = None,
    fast: bool = False,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    t0 = time.perf_counter()
    debug_log(
        "assessment start",
        {"user_id": user_id, "run_id": run_id, "fast": fast},
        tag="perf",
    )
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    assessment_review_marked = False
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        assessment_review_marked = _set_pref_value(
            s,
            user_id,
            ONBOARDING_PREF_KEYS["assessment_reviewed"],
            _utc_now_iso(),
            only_if_missing=True,
        )
        if assessment_review_marked:
            s.commit()
        rid = run_id
        if rid is None:
            latest_finished = s.execute(
                select(AssessmentRun)
                .where(AssessmentRun.user_id == user_id, AssessmentRun.finished_at.isnot(None))
                .order_by(desc(AssessmentRun.id))
            ).scalars().first()
            if latest_finished:
                rid = latest_finished.id
            else:
                latest = s.execute(
                    select(AssessmentRun).where(AssessmentRun.user_id == user_id).order_by(desc(AssessmentRun.id))
                ).scalars().first()
                if not latest:
                    raise HTTPException(status_code=404, detail="assessment run not found")
                rid = latest.id
    data = build_assessment_dashboard_data(int(rid), include_llm=not fast)
    narratives = data.get("narratives") or {}
    if isinstance(narratives, dict):
        narratives = {
            **narratives,
            "score_audio_url": _normalize_reports_url(narratives.get("score_audio_url")),
            "okr_audio_url": _normalize_reports_url(narratives.get("okr_audio_url")),
            "coaching_audio_url": _normalize_reports_url(narratives.get("coaching_audio_url")),
        }
        data["narratives"] = narratives
    data["reports"] = {
        "assessment_html": _public_report_url(user_id, "assessment.html"),
        "assessment_pdf": _public_report_url(user_id, "latest.pdf"),
        "assessment_image": _public_report_url(user_id, "latest.jpeg"),
    }
    _log_app_engagement_event(
        user_id=user_id,
        unit_type="page_view",
        meta={
            "page": "assessment_results",
            "run_id": int(rid),
            "fast": bool(fast),
        },
    )
    if assessment_review_marked:
        _log_app_engagement_event(
            user_id=user_id,
            unit_type="assessment_reviewed",
            meta={"run_id": int(rid)},
        )
        evaluate_and_enable_coaching(user_id)
    debug_log(
        "assessment ok",
        {"user_id": user_id, "run_id": rid, "ms": int((time.perf_counter() - t0) * 1000)},
        tag="perf",
    )
    return data


@api_v1.get("/public/users/{user_id}/assessment")
def api_public_user_assessment(user_id: int, run_id: int | None = None, fast: bool = False):
    t0 = time.perf_counter()
    debug_log(
        "public assessment start",
        {"user_id": user_id, "run_id": run_id, "fast": fast},
        tag="perf",
    )
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        rid = run_id
        if rid is None:
            latest_finished = s.execute(
                select(AssessmentRun)
                .where(AssessmentRun.user_id == user_id, AssessmentRun.finished_at.isnot(None))
                .order_by(desc(AssessmentRun.id))
            ).scalars().first()
            if latest_finished:
                rid = latest_finished.id
            else:
                latest = s.execute(
                    select(AssessmentRun).where(AssessmentRun.user_id == user_id).order_by(desc(AssessmentRun.id))
                ).scalars().first()
                if not latest:
                    raise HTTPException(status_code=404, detail="assessment run not found")
                rid = latest.id
    data = build_assessment_dashboard_data(int(rid), include_llm=not fast)
    narratives = data.get("narratives") or {}
    if isinstance(narratives, dict):
        narratives = {
            **narratives,
            "score_audio_url": _normalize_reports_url(narratives.get("score_audio_url")),
            "okr_audio_url": _normalize_reports_url(narratives.get("okr_audio_url")),
            "coaching_audio_url": _normalize_reports_url(narratives.get("coaching_audio_url")),
        }
        data["narratives"] = narratives
    data["reports"] = {
        "assessment_html": _public_report_url(user_id, "assessment.html"),
        "assessment_pdf": _public_report_url(user_id, "latest.pdf"),
        "assessment_image": _public_report_url(user_id, "latest.jpeg"),
    }
    debug_log(
        "public assessment ok",
        {"user_id": user_id, "run_id": rid, "ms": int((time.perf_counter() - t0) * 1000)},
        tag="perf",
    )
    return data


@api_v1.get("/users/{user_id}/progress")
def api_user_progress(
    user_id: int,
    request: Request,
    anchor_date: str | None = None,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    t0 = time.perf_counter()
    debug_log(
        "progress start",
        {"user_id": user_id, "anchor_date": anchor_date},
        tag="perf",
    )
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
    anchor = None
    if anchor_date:
        try:
            anchor = date.fromisoformat(anchor_date)
        except Exception:
            raise HTTPException(status_code=400, detail="anchor_date must be YYYY-MM-DD")
    data = build_progress_report_data(user_id, anchor_date=anchor)
    data["reports"] = {
        "progress_html": _public_report_url(user_id, "progress.html"),
    }
    _log_app_engagement_event(
        user_id=user_id,
        unit_type="page_view",
        meta={
            "page": "progress_home",
            "anchor_date": anchor_date,
        },
    )
    debug_log(
        "progress ok",
        {"user_id": user_id, "ms": int((time.perf_counter() - t0) * 1000)},
        tag="perf",
    )
    return data

@api_v1.get("/users/{user_id}/status")
def api_user_status_v1(
    user_id: int,
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    """
    Return assessment status and latest run info.
    """
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        active = get_active_domain(u)
        latest_run = s.execute(
            select(AssessmentRun).where(AssessmentRun.user_id == user_id).order_by(desc(AssessmentRun.id))
        ).scalars().first()
        pref_rows = (
            s.query(UserPreference)
            .filter(
                UserPreference.user_id == user_id,
                UserPreference.key.in_(
                    (
                        "coachmycoach_note",
                        "tts_voice_pref",
                        "coaching",
                        "auto_daily_prompts",
                        "coach_schedule_monday",
                        "coach_schedule_tuesday",
                        "coach_schedule_wednesday",
                        "coach_schedule_thursday",
                        "coach_schedule_friday",
                        "coach_schedule_saturday",
                        "coach_schedule_sunday",
                        "text_scale",
                        "preferred_channel",
                        "marketing_opt_in",
                        "prompt_state_override",
                    )
                ),
            )
            .order_by(UserPreference.updated_at.desc())
            .all()
        )
        pref_map = {row.key: row.value for row in pref_rows if row}
        auto_pref = next(
            (row for row in pref_rows if row.key in {"coaching", "auto_daily_prompts"}),
            None,
        )
        auto_val = (auto_pref.value or "").strip() if auto_pref else ""
        if auto_val == "1":
            auto_status = "on"
        elif auto_val == "0":
            auto_status = "off"
        else:
            auto_status = "not configured"
        schedule = {}
        for key in (
            "coach_schedule_monday",
            "coach_schedule_tuesday",
            "coach_schedule_wednesday",
            "coach_schedule_thursday",
            "coach_schedule_friday",
            "coach_schedule_saturday",
            "coach_schedule_sunday",
        ):
            if key in pref_map and pref_map[key]:
                schedule[key.replace("coach_schedule_", "")] = pref_map[key]
        training_objective = (
            s.query(OKRObjective)
            .filter(OKRObjective.owner_user_id == user_id, OKRObjective.pillar_key == "training")
            .order_by(desc(OKRObjective.created_at), desc(OKRObjective.id))
            .first()
        )
        onboarding_state = _get_onboarding_state(s, user_id)
        intro_payload = _build_intro_payload(s, u, onboarding_state)

    data = {
        "user": {
            "id": u.id,
            "first_name": getattr(u, "first_name", None),
            "surname": getattr(u, "surname", None),
            "display_name": display_full_name(u),
            "phone": u.phone,
            "email": getattr(u, "email", None),
            "consent_given": bool(getattr(u, "consent_given", False)),
            "consent_at": getattr(u, "consent_at", None),
        },
        "active_domain": active,
        "latest_run": None,
        "coaching_preferences": {
            "auto_prompts": auto_status,
            "note": pref_map.get("coachmycoach_note", ""),
            "voice": pref_map.get("tts_voice_pref", ""),
            "schedule": schedule,
            "text_scale": pref_map.get("text_scale", ""),
            "training_objective": training_objective.objective if training_objective else "",
            "preferred_channel": pref_map.get("preferred_channel", "whatsapp"),
            "marketing_opt_in": pref_map.get("marketing_opt_in", ""),
        },
        "prompt_state_override": pref_map.get("prompt_state_override", ""),
        "onboarding": onboarding_state,
        "intro": intro_payload,
    }

    if latest_run:
        data["latest_run"] = {
            "id": latest_run.id,
            "finished_at": getattr(latest_run, "finished_at", None),
            "combined_overall": getattr(latest_run, "combined_overall", None),
        }

    if active:
        data["status"] = "in_progress"
    elif latest_run and getattr(latest_run, "finished_at", None):
        data["status"] = "completed"
    else:
        data["status"] = "idle"

    return data


@api_v1.get("/users/{user_id}/intro-content")
def api_user_intro_content(
    user_id: int,
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        onboarding_state = _get_onboarding_state(s, user_id)
        intro = _build_intro_payload(s, u, onboarding_state)
    return {
        "user_id": user_id,
        "intro": intro,
    }


@api_v1.post("/users/{user_id}/preferences")
def api_user_preferences_update(
    user_id: int,
    payload: dict,
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    """
    Update coaching preferences for a user (note, voice, auto prompts, schedule).
    """
    allowed_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    allowed_channels = {"whatsapp", "sms", "email"}
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")

        email = payload.get("email") if isinstance(payload, dict) else None
        if email is not None:
            email_val = str(email).strip().lower()
            if not email_val:
                raise HTTPException(status_code=400, detail="email is required")
            if "@" not in email_val or "." not in email_val.split("@")[-1]:
                raise HTTPException(status_code=400, detail="invalid email")
            u.email = email_val

        note = payload.get("note") if isinstance(payload, dict) else None
        if note is not None:
            note_val = str(note).strip()
            pref = (
                s.query(UserPreference)
                .filter(UserPreference.user_id == user_id, UserPreference.key == "coachmycoach_note")
                .one_or_none()
            )
            if note_val:
                if pref:
                    pref.value = note_val
                else:
                    s.add(UserPreference(user_id=user_id, key="coachmycoach_note", value=note_val))
            else:
                if pref:
                    s.delete(pref)

        voice = payload.get("voice") if isinstance(payload, dict) else None
        if voice is not None:
            voice_val = str(voice).strip().lower()
            if voice_val and voice_val not in {"male", "female"}:
                raise HTTPException(status_code=400, detail="voice must be 'male' or 'female'")
            pref = (
                s.query(UserPreference)
                .filter(UserPreference.user_id == user_id, UserPreference.key == "tts_voice_pref")
                .one_or_none()
            )
            if voice_val:
                if pref:
                    pref.value = voice_val
                else:
                    s.add(UserPreference(user_id=user_id, key="tts_voice_pref", value=voice_val))
            else:
                if pref:
                    s.delete(pref)

        schedule = payload.get("schedule") if isinstance(payload, dict) else None
        if isinstance(schedule, dict):
            for day, value in schedule.items():
                day_key = str(day).strip().lower()
                if day_key not in allowed_days:
                    raise HTTPException(status_code=400, detail=f"invalid schedule day: {day}")
                time_val = ("" if value is None else str(value)).strip()
                pref_key = f"coach_schedule_{day_key}"
                pref = (
                    s.query(UserPreference)
                    .filter(UserPreference.user_id == user_id, UserPreference.key == pref_key)
                    .one_or_none()
                )
                if time_val:
                    try:
                        hh, mm = time_val.split(":")
                        hh_i = int(hh); mm_i = int(mm)
                        if not (0 <= hh_i <= 23 and 0 <= mm_i <= 59):
                            raise ValueError()
                    except Exception:
                        raise HTTPException(status_code=400, detail=f"invalid time for {day_key}: {time_val}")
                    val = f"{hh_i:02d}:{mm_i:02d}"
                    if pref:
                        pref.value = val
                    else:
                        s.add(UserPreference(user_id=user_id, key=pref_key, value=val))
                else:
                    if pref:
                        s.delete(pref)

        auto_prompts = payload.get("auto_prompts") if isinstance(payload, dict) else None
        if auto_prompts is not None:
            auto_val = str(auto_prompts).strip().lower()
            if auto_val in {"on", "off"}:
                key = "coaching"
                pref = (
                    s.query(UserPreference)
                    .filter(UserPreference.user_id == user_id, UserPreference.key.in_(("coaching", "auto_daily_prompts")))
                    .order_by(UserPreference.updated_at.desc())
                    .first()
                )
                if pref and pref.key != key:
                    s.delete(pref)
                pref = (
                    s.query(UserPreference)
                    .filter(UserPreference.user_id == user_id, UserPreference.key == key)
                    .one_or_none()
                )
                if pref:
                    pref.value = "1" if auto_val == "on" else "0"
                else:
                    s.add(UserPreference(user_id=user_id, key=key, value="1" if auto_val == "on" else "0"))
            elif auto_val:
                raise HTTPException(status_code=400, detail="auto_prompts must be 'on' or 'off'")

        password = payload.get("password") if isinstance(payload, dict) else None
        if password is not None:
            pw_val = str(password).strip()
            if pw_val:
                if len(pw_val) < 8:
                    raise HTTPException(status_code=400, detail="password must be at least 8 characters")
                u.password_hash = _hash_password(pw_val)

        text_scale = payload.get("text_scale") if isinstance(payload, dict) else None
        if text_scale is not None:
            scale_val = str(text_scale).strip()
            pref = (
                s.query(UserPreference)
                .filter(UserPreference.user_id == user_id, UserPreference.key == "text_scale")
                .one_or_none()
            )
            if scale_val:
                try:
                    scale_num = float(scale_val)
                except Exception:
                    raise HTTPException(status_code=400, detail="text_scale must be a number")
                if not (0.9 <= scale_num <= 1.5):
                    raise HTTPException(status_code=400, detail="text_scale must be between 0.9 and 1.5")
                scale_val = f"{scale_num:.2f}".rstrip("0").rstrip(".")
                if pref:
                    pref.value = scale_val
                else:
                    s.add(UserPreference(user_id=user_id, key="text_scale", value=scale_val))
            else:
                if pref:
                    s.delete(pref)

        training_objective = payload.get("training_objective") if isinstance(payload, dict) else None
        if training_objective is not None:
            obj_val = str(training_objective).strip()
            if obj_val:
                obj = (
                    s.query(OKRObjective)
                    .filter(OKRObjective.owner_user_id == user_id, OKRObjective.pillar_key == "training")
                    .order_by(desc(OKRObjective.created_at), desc(OKRObjective.id))
                    .first()
                )
                if not obj:
                    cycle = ensure_cycle(s, datetime.utcnow())
                    obj = OKRObjective(
                        cycle_id=cycle.id,
                        pillar_key="training",
                        objective=obj_val,
                        owner_user_id=user_id,
                    )
                    s.add(obj)
                else:
                    obj.objective = obj_val

        preferred_channel = payload.get("preferred_channel") if isinstance(payload, dict) else None
        if preferred_channel is not None:
            channel_val = str(preferred_channel).strip().lower()
            if channel_val and channel_val not in allowed_channels:
                raise HTTPException(status_code=400, detail="preferred_channel must be whatsapp|sms|email")
            pref = (
                s.query(UserPreference)
                .filter(UserPreference.user_id == user_id, UserPreference.key == "preferred_channel")
                .one_or_none()
            )
            if channel_val:
                if pref:
                    pref.value = channel_val
                else:
                    s.add(UserPreference(user_id=user_id, key="preferred_channel", value=channel_val))
            else:
                if pref:
                    s.delete(pref)

        marketing_opt_in = payload.get("marketing_opt_in") if isinstance(payload, dict) else None
        if marketing_opt_in is not None:
            opt_val = str(marketing_opt_in).strip().lower()
            enabled = opt_val in {"1", "true", "yes", "on"}
            pref = (
                s.query(UserPreference)
                .filter(UserPreference.user_id == user_id, UserPreference.key == "marketing_opt_in")
                .one_or_none()
            )
            if pref:
                pref.value = "1" if enabled else "0"
            else:
                s.add(UserPreference(user_id=user_id, key="marketing_opt_in", value="1" if enabled else "0"))
            if enabled:
                stamp = (
                    s.query(UserPreference)
                    .filter(UserPreference.user_id == user_id, UserPreference.key == "marketing_opt_in_at")
                    .one_or_none()
                )
                ts_val = datetime.utcnow().isoformat()
                if stamp:
                    stamp.value = ts_val
                else:
                    s.add(UserPreference(user_id=user_id, key="marketing_opt_in_at", value=ts_val))

        s.commit()

    return {"ok": True}


@api_v1.get("/users/{user_id}/library")
def api_user_library_content(
    user_id: int,
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    _log_app_engagement_event(
        user_id=user_id,
        unit_type="page_view",
        meta={"page": "library"},
    )
    with SessionLocal() as s:
        rows = (
            s.query(ContentLibraryItem)
            .filter(
                ContentLibraryItem.status == "published",
                or_(
                    ContentLibraryItem.source_type.is_(None),
                    ContentLibraryItem.source_type != INTRO_SOURCE_TYPE,
                ),
            )
            .order_by(ContentLibraryItem.pillar_key.asc(), ContentLibraryItem.created_at.desc())
            .all()
        )
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row.pillar_key, []).append(
            {
                "id": row.id,
                "pillar_key": row.pillar_key,
                "concept_code": row.concept_code,
                "title": row.title,
                "body": row.body,
                "created_at": row.created_at,
                "podcast_url": _normalize_reports_url(row.podcast_url),
                "podcast_voice": row.podcast_voice,
            }
        )
    return {"user_id": user_id, "items": grouped}


@api_v1.post("/users/{user_id}/engagement")
def api_user_engagement_event(
    user_id: int,
    payload: dict,
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    event_type = str(payload.get("event_type") or "").strip().lower()
    valid_event_types = {
        "podcast_play",
        "podcast_complete",
        "intro_presented",
        "intro_listened",
        "intro_read",
    }
    if event_type not in valid_event_types:
        allowed = ", ".join(sorted(valid_event_types))
        raise HTTPException(status_code=400, detail=f"event_type must be one of: {allowed}")

    raw_meta = payload.get("meta")
    event_meta = _meta_to_dict(raw_meta) if raw_meta is not None else None
    if event_meta is None:
        event_meta = {}
    if payload.get("surface") is not None and event_meta.get("surface") is None:
        event_meta["surface"] = str(payload.get("surface")).strip().lower()
    if payload.get("podcast_id") is not None and event_meta.get("podcast_id") is None:
        event_meta["podcast_id"] = str(payload.get("podcast_id")).strip()

    if event_type.startswith("intro_"):
        now_iso = _utc_now_iso()
        with SessionLocal() as s:
            changed = False
            if event_type == "intro_presented":
                changed = _set_pref_value(
                    s,
                    user_id,
                    ONBOARDING_PREF_KEYS["intro_presented"],
                    now_iso,
                    only_if_missing=True,
                ) or changed
            elif event_type == "intro_listened":
                changed = _set_pref_value(
                    s,
                    user_id,
                    ONBOARDING_PREF_KEYS["intro_presented"],
                    now_iso,
                    only_if_missing=True,
                ) or changed
                changed = _set_pref_value(
                    s,
                    user_id,
                    ONBOARDING_PREF_KEYS["intro_listened"],
                    now_iso,
                    only_if_missing=True,
                ) or changed
            elif event_type == "intro_read":
                changed = _set_pref_value(
                    s,
                    user_id,
                    ONBOARDING_PREF_KEYS["intro_presented"],
                    now_iso,
                    only_if_missing=True,
                ) or changed
                changed = _set_pref_value(
                    s,
                    user_id,
                    ONBOARDING_PREF_KEYS["intro_read"],
                    now_iso,
                    only_if_missing=True,
                ) or changed
            if changed:
                s.commit()

    _log_app_engagement_event(
        user_id=user_id,
        unit_type=event_type,
        meta=event_meta,
    )
    if event_type in {"intro_listened", "intro_read"}:
        evaluate_and_enable_coaching(user_id)
    return {"ok": True}


@api_v1.get("/users/{user_id}/krs/{kr_id}/habit-steps")
def api_user_kr_habit_steps(
    user_id: int,
    kr_id: int,
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    with SessionLocal() as s:
        kr = (
            s.query(OKRKeyResult)
            .join(OKRObjective, OKRKeyResult.objective_id == OKRObjective.id)
            .filter(OKRKeyResult.id == kr_id, OKRObjective.owner_user_id == user_id)
            .first()
        )
        if not kr:
            raise HTTPException(status_code=404, detail="kr not found")
        steps = (
            s.query(OKRKrHabitStep)
            .filter(OKRKrHabitStep.user_id == user_id, OKRKrHabitStep.kr_id == kr_id)
            .filter(OKRKrHabitStep.status != "archived")
            .order_by(
                OKRKrHabitStep.week_no.asc().nullslast(),
                OKRKrHabitStep.sort_order.asc(),
                OKRKrHabitStep.id.asc(),
            )
            .all()
        )
        return {
            "kr_id": kr_id,
            "steps": [
                {"id": row.id, "text": row.step_text, "status": row.status, "week_no": row.week_no}
                for row in steps
            ],
        }


@api_v1.put("/users/{user_id}/krs/{kr_id}/habit-steps")
def api_user_kr_habit_steps_update(
    user_id: int,
    kr_id: int,
    payload: dict,
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")
    raw_steps = payload.get("steps", [])
    if raw_steps is None:
        raw_steps = []
    if not isinstance(raw_steps, list):
        raise HTTPException(status_code=400, detail="steps must be a list")
    root_week = payload.get("week_no")
    root_focus_id = payload.get("weekly_focus_id")
    if root_week is not None:
        try:
            root_week = int(root_week)
        except Exception:
            raise HTTPException(status_code=400, detail="week_no must be an integer")
    if root_focus_id is not None:
        try:
            root_focus_id = int(root_focus_id)
        except Exception:
            raise HTTPException(status_code=400, detail="weekly_focus_id must be an integer")

    normalized: list[dict] = []
    week_scope: set[int | None] = set()
    for idx, item in enumerate(raw_steps):
        if isinstance(item, str):
            text_val = item.strip()
            week_no = root_week
            status = "active"
            sort_order = idx
        elif isinstance(item, dict):
            text_val = str(item.get("text") or item.get("step") or "").strip()
            status = str(item.get("status") or "active").strip().lower() or "active"
            sort_order = item.get("sort_order", idx)
            week_no = item.get("week_no", root_week)
            if week_no is not None:
                try:
                    week_no = int(week_no)
                except Exception:
                    raise HTTPException(status_code=400, detail="week_no must be an integer")
        else:
            continue
        if not text_val:
            continue
        if week_no is not None:
            week_scope.add(week_no)
        normalized.append(
            {
                "text": text_val,
                "status": status,
                "sort_order": int(sort_order) if str(sort_order).isdigit() else idx,
                "week_no": week_no,
            }
        )

    with SessionLocal() as s:
        kr = (
            s.query(OKRKeyResult)
            .join(OKRObjective, OKRKeyResult.objective_id == OKRObjective.id)
            .filter(OKRKeyResult.id == kr_id, OKRObjective.owner_user_id == user_id)
            .first()
        )
        if not kr:
            raise HTTPException(status_code=404, detail="kr not found")

        delete_query = s.query(OKRKrHabitStep).filter(
            OKRKrHabitStep.user_id == user_id,
            OKRKrHabitStep.kr_id == kr_id,
        )
        if week_scope:
            delete_query = delete_query.filter(OKRKrHabitStep.week_no.in_(week_scope))
        else:
            delete_query = delete_query.filter(OKRKrHabitStep.week_no.is_(None))
        delete_query.delete(synchronize_session=False)

        for step in normalized:
            s.add(
                OKRKrHabitStep(
                    user_id=user_id,
                    kr_id=kr_id,
                    weekly_focus_id=root_focus_id,
                    week_no=step.get("week_no"),
                    sort_order=step.get("sort_order", 0),
                    step_text=step.get("text") or "",
                    status=step.get("status") or "active",
                    source="user",
                )
            )
        s.commit()

        saved = (
            s.query(OKRKrHabitStep)
            .filter(OKRKrHabitStep.user_id == user_id, OKRKrHabitStep.kr_id == kr_id)
            .filter(OKRKrHabitStep.status != "archived")
            .order_by(
                OKRKrHabitStep.week_no.asc().nullslast(),
                OKRKrHabitStep.sort_order.asc(),
                OKRKrHabitStep.id.asc(),
            )
            .all()
        )
        return {
            "kr_id": kr_id,
            "steps": [
                {"id": row.id, "text": row.step_text, "status": row.status, "week_no": row.week_no}
                for row in saved
            ],
        }


@api_v1.put("/users/{user_id}/krs/{kr_id}")
def api_user_kr_update(
    user_id: int,
    kr_id: int,
    payload: dict,
    request: Request,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    def _parse_optional_number(raw_value, *, field_name: str):
        if raw_value is None:
            return None, False
        if isinstance(raw_value, str):
            trimmed = raw_value.strip()
            if not trimmed:
                return None, True
            try:
                return float(trimmed), True
            except Exception:
                raise HTTPException(status_code=400, detail=f"{field_name} must be numeric")
        try:
            return float(raw_value), True
        except Exception:
            raise HTTPException(status_code=400, detail=f"{field_name} must be numeric")

    actual_num, has_actual = _parse_optional_number(payload.get("actual_num"), field_name="actual_num")
    note = str(payload.get("note") or "").strip() or "KR updated in app"
    if not has_actual:
        raise HTTPException(status_code=400, detail="actual_num is required")

    with SessionLocal() as s:
        kr = (
            s.query(OKRKeyResult)
            .join(OKRObjective, OKRKeyResult.objective_id == OKRObjective.id)
            .filter(OKRKeyResult.id == kr_id, OKRObjective.owner_user_id == user_id)
            .first()
        )
        if not kr:
            raise HTTPException(status_code=404, detail="kr not found")

        if has_actual:
            kr.actual_num = actual_num
            s.add(
                OKRKrEntry(
                    key_result_id=kr.id,
                    occurred_at=datetime.utcnow(),
                    actual_num=actual_num,
                    note=note,
                    source="app",
                )
            )

        s.add(kr)
        s.commit()
        s.refresh(kr)
        return {
            "kr_id": kr.id,
            "description": kr.description,
            "baseline_num": kr.baseline_num,
            "target_num": kr.target_num,
            "actual_num": kr.actual_num,
            "metric_label": kr.metric_label,
            "unit": kr.unit,
            "updated_at": kr.updated_at,
        }


@api_v1.get("/users/{user_id}/coaching-history")
def api_user_coaching_history(
    user_id: int,
    request: Request,
    limit: int = 50,
    x_admin_token: str | None = Header(None, alias="X-Admin-Token"),
    x_admin_user_id: str | None = Header(None, alias="X-Admin-User-Id"),
):
    """
    Return recent coaching touchpoints and dialog history for a user.
    """
    _resolve_user_access(request=request, user_id=user_id, x_admin_token=x_admin_token, x_admin_user_id=x_admin_user_id)
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")

        touchpoints = (
            s.query(Touchpoint)
            .filter(Touchpoint.user_id == user_id)
            .order_by(desc(Touchpoint.sent_at), desc(Touchpoint.created_at))
            .limit(limit)
            .all()
        )
        wf_ids = {tp.weekly_focus_id for tp in touchpoints if tp.weekly_focus_id}
        wf_map = {}
        if wf_ids:
            wf_rows = (
                s.query(WeeklyFocus.id, WeeklyFocus.week_no)
                .filter(WeeklyFocus.id.in_(list(wf_ids)))
                .all()
            )
            wf_map = {row.id: row.week_no for row in wf_rows if row and row.id}
        messages = (
            s.query(MessageLog)
            .filter(MessageLog.user_id == user_id)
            .order_by(desc(MessageLog.created_at))
            .limit(limit)
            .all()
        )

    def _tp_title(tp: Touchpoint) -> str:
        if tp.audio_url:
            return "Podcast"
        return ""

    def _preview(text: str | None) -> str:
        if not text:
            return ""
        cleaned = " ".join(str(text).split())
        return cleaned[:180] + ("…" if len(cleaned) > 180 else "")

    def _is_truncated(text: str | None) -> bool:
        if not text:
            return False
        cleaned = " ".join(str(text).split())
        return len(cleaned) > 180

    def _meta_dict(value) -> dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, dict) else {}
            except Exception:
                return {}
        return {}

    def _message_ts_iso(msg: MessageLog) -> tuple[str | None, str | None]:
        ts = getattr(msg, "created_at", None)
        meta = _meta_dict(getattr(msg, "meta", None))
        raw_virtual = str(meta.get("virtual_date") or "").strip()
        if raw_virtual:
            try:
                vday = date.fromisoformat(raw_virtual[:10])
                base = ts or datetime.utcnow()
                virtual_ts = datetime(
                    vday.year,
                    vday.month,
                    vday.day,
                    base.hour,
                    base.minute,
                    base.second,
                    base.microsecond,
                )
                return virtual_ts.isoformat(), vday.isoformat()
            except Exception:
                pass
        return (ts.isoformat() if ts else None), None

    items = []
    for tp in touchpoints:
        ts = tp.sent_at or tp.created_at
        inferred_week = tp.week_no or (wf_map.get(tp.weekly_focus_id) if tp.weekly_focus_id else None)
        items.append(
            {
                "id": tp.id,
                "ts": ts.isoformat() if ts else None,
                "type": "podcast" if tp.audio_url else "prompt",
                "title": _tp_title(tp),
                "preview": _preview(tp.generated_text),
                "full_text": (tp.generated_text or "").strip(),
                "is_truncated": _is_truncated(tp.generated_text),
                "audio_url": tp.audio_url,
                "channel": tp.channel,
                "touchpoint_type": tp.type,
                "week_no": inferred_week,
            }
        )
    for msg in messages:
        msg_ts, msg_virtual_date = _message_ts_iso(msg)
        items.append(
            {
                "id": msg.id,
                "ts": msg_ts,
                "type": "dialog",
                "title": "Message",
                "preview": _preview(msg.text),
                "full_text": (msg.text or "").strip(),
                "is_truncated": _is_truncated(msg.text),
                "direction": msg.direction,
                "channel": msg.channel,
                "virtual_date": msg_virtual_date,
            }
        )

    items.sort(key=lambda r: r.get("ts") or "", reverse=True)
    items = items[: max(1, min(int(limit), 200))]

    return {
        "user": {
            "id": u.id,
            "display_name": display_full_name(u),
        },
        "items": items,
    }


@admin.post("/users")
def admin_create_user(payload: dict, admin_user: User = Depends(_require_admin)):
    """
    Create a new user and trigger consent/intro via start_combined_assessment.
    Body: { "first_name": "Julian", "surname": "Matthews", "phone": "+4477..." }
    """
    phone = _norm_phone((payload.get("phone") or "").strip())
    def _titlecase_chunk(chunk: str | None) -> str | None:
        if not chunk:
            return None
        chunk = _strip_invisible(chunk).strip()
        if not chunk:
            return None
        return " ".join(word.capitalize() for word in chunk.split())

    first_name = _titlecase_chunk(payload.get("first_name"))
    surname = _titlecase_chunk(payload.get("surname"))
    if not phone:
        raise HTTPException(status_code=400, detail="phone required")
    if not _require_name_fields(first_name, surname):
        raise HTTPException(status_code=400, detail="first_name and surname required")
    admin_club_id = getattr(admin_user, "club_id", None)
    if admin_club_id is None:
        raise HTTPException(status_code=400, detail="admin user missing club")
    with SessionLocal() as s:
        existing = s.execute(select(User).where(User.phone == phone)).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="user already exists")
        now = datetime.utcnow()
        u = User(
            first_name=first_name,
            surname=surname,
            phone=phone,
            club_id=admin_club_id,
            created_on=now,
            updated_on=now,
            consent_given=True,
            consent_at=now,
        )
        if hasattr(u, "consent_yes_at"):
            try:
                setattr(u, "consent_yes_at", now)
            except Exception:
                pass
        s.add(u); s.commit(); s.refresh(u)
    # Fire consent/intro; this will send the WhatsApp message
    try:
        _start_assessment_async(u)
    except Exception as e:
        # Do not fail creation if send fails
        print(f"[admin_create_user] start_combined_assessment failed: {e!r}")
    return {
        "id": u.id,
        "first_name": getattr(u, "first_name", None),
        "surname": getattr(u, "surname", None),
        "display_name": display_full_name(u),
        "phone": u.phone
    }

def _percentile(values: list[float], p: float) -> float | None:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return None
    if len(clean) == 1:
        return clean[0]
    pct = max(0.0, min(100.0, float(p)))
    rank = (pct / 100.0) * (len(clean) - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return clean[lo]
    frac = rank - lo
    return clean[lo] + ((clean[hi] - clean[lo]) * frac)


def _threshold_state(
    value: float | int | None,
    *,
    warn: float,
    critical: float,
    lower_is_bad: bool = False,
) -> str:
    if value is None:
        return "unknown"
    val = float(value)
    if lower_is_bad:
        if val < critical:
            return "critical"
        if val < warn:
            return "warn"
        return "ok"
    if val > critical:
        return "critical"
    if val > warn:
        return "warn"
    return "ok"


def _as_payload_dict(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


DEFAULT_MONITORING_LLM_P50_WARN_MS = 4000.0
DEFAULT_MONITORING_LLM_P50_CRITICAL_MS = 8000.0
DEFAULT_MONITORING_LLM_P95_WARN_MS = 8000.0
DEFAULT_MONITORING_LLM_P95_CRITICAL_MS = 15000.0


def _positive_float_or_none(raw: object) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        cleaned = raw.strip()
        if not cleaned:
            return None
        try:
            val = float(cleaned)
        except Exception:
            return None
    else:
        try:
            val = float(raw)
        except Exception:
            return None
    if not math.isfinite(val) or val <= 0:
        return None
    return float(val)


def _monitoring_llm_latency_threshold_values(row: PromptSettings | None) -> dict[str, float]:
    def _resolve_pair(
        warn_raw: object,
        critical_raw: object,
        default_warn: float,
        default_critical: float,
    ) -> tuple[float, float]:
        warn = _positive_float_or_none(warn_raw) or default_warn
        critical = _positive_float_or_none(critical_raw) or default_critical
        if critical < warn:
            critical = warn
        return float(warn), float(critical)

    p50_warn, p50_critical = _resolve_pair(
        getattr(row, "monitoring_llm_p50_warn_ms", None),
        getattr(row, "monitoring_llm_p50_critical_ms", None),
        DEFAULT_MONITORING_LLM_P50_WARN_MS,
        DEFAULT_MONITORING_LLM_P50_CRITICAL_MS,
    )
    p95_warn, p95_critical = _resolve_pair(
        getattr(row, "monitoring_llm_p95_warn_ms", None),
        getattr(row, "monitoring_llm_p95_critical_ms", None),
        DEFAULT_MONITORING_LLM_P95_WARN_MS,
        DEFAULT_MONITORING_LLM_P95_CRITICAL_MS,
    )
    interactive_p50_warn, interactive_p50_critical = _resolve_pair(
        getattr(row, "monitoring_llm_interactive_p50_warn_ms", None),
        getattr(row, "monitoring_llm_interactive_p50_critical_ms", None),
        p50_warn,
        p50_critical,
    )
    interactive_p95_warn, interactive_p95_critical = _resolve_pair(
        getattr(row, "monitoring_llm_interactive_p95_warn_ms", None),
        getattr(row, "monitoring_llm_interactive_p95_critical_ms", None),
        p95_warn,
        p95_critical,
    )
    worker_p50_warn, worker_p50_critical = _resolve_pair(
        getattr(row, "monitoring_llm_worker_p50_warn_ms", None),
        getattr(row, "monitoring_llm_worker_p50_critical_ms", None),
        p50_warn,
        p50_critical,
    )
    worker_p95_warn, worker_p95_critical = _resolve_pair(
        getattr(row, "monitoring_llm_worker_p95_warn_ms", None),
        getattr(row, "monitoring_llm_worker_p95_critical_ms", None),
        p95_warn,
        p95_critical,
    )
    return {
        "llm_p50_warn_ms": float(p50_warn),
        "llm_p50_critical_ms": float(p50_critical),
        "llm_p95_warn_ms": float(p95_warn),
        "llm_p95_critical_ms": float(p95_critical),
        "llm_interactive_p50_warn_ms": float(interactive_p50_warn),
        "llm_interactive_p50_critical_ms": float(interactive_p50_critical),
        "llm_interactive_p95_warn_ms": float(interactive_p95_warn),
        "llm_interactive_p95_critical_ms": float(interactive_p95_critical),
        "llm_worker_p50_warn_ms": float(worker_p50_warn),
        "llm_worker_p50_critical_ms": float(worker_p50_critical),
        "llm_worker_p95_warn_ms": float(worker_p95_warn),
        "llm_worker_p95_critical_ms": float(worker_p95_critical),
    }


def _worst_state(*states: str) -> str:
    rank = {"unknown": 0, "ok": 1, "warn": 2, "critical": 3}
    best = "unknown"
    best_rank = -1
    for state in states:
        key = str(state or "unknown").strip().lower() or "unknown"
        val = rank.get(key, 0)
        if val > best_rank:
            best_rank = val
            best = key
    return best


@admin.get("/assessment/health")
def admin_assessment_health(
    days: int | None = None,
    stale_minutes: int | None = None,
    admin_user: User = Depends(_require_admin),
):
    """
    Aggregated operational health metrics for assessment flow monitoring.
    """
    try:
        days_val = int(days or 7)
    except Exception:
        days_val = 7
    days_val = max(1, min(days_val, 30))
    try:
        stale_mins = int(stale_minutes or 30)
    except Exception:
        stale_mins = 30
    stale_mins = max(5, min(stale_mins, 240))

    now_utc = datetime.utcnow()
    start_utc = now_utc - timedelta(days=days_val)
    end_utc = now_utc
    club_scope_id = getattr(admin_user, "club_id", None)

    thresholds = {
        "completion_rate_pct": {"warn": 70.0, "critical": 55.0, "lower_is_bad": True},
        "median_completion_minutes": {"warn": 18.0, "critical": 25.0, "lower_is_bad": False},
        "stale_runs": {"warn": 5.0, "critical": 15.0, "lower_is_bad": False},
        "llm_p50_ms": {"warn": DEFAULT_MONITORING_LLM_P50_WARN_MS, "critical": DEFAULT_MONITORING_LLM_P50_CRITICAL_MS, "lower_is_bad": False},
        "llm_p95_ms": {"warn": DEFAULT_MONITORING_LLM_P95_WARN_MS, "critical": DEFAULT_MONITORING_LLM_P95_CRITICAL_MS, "lower_is_bad": False},
        "llm_interactive_p50_ms": {"warn": DEFAULT_MONITORING_LLM_P50_WARN_MS, "critical": DEFAULT_MONITORING_LLM_P50_CRITICAL_MS, "lower_is_bad": False},
        "llm_interactive_p95_ms": {"warn": DEFAULT_MONITORING_LLM_P95_WARN_MS, "critical": DEFAULT_MONITORING_LLM_P95_CRITICAL_MS, "lower_is_bad": False},
        "llm_worker_p50_ms": {"warn": DEFAULT_MONITORING_LLM_P50_WARN_MS, "critical": DEFAULT_MONITORING_LLM_P50_CRITICAL_MS, "lower_is_bad": False},
        "llm_worker_p95_ms": {"warn": DEFAULT_MONITORING_LLM_P95_WARN_MS, "critical": DEFAULT_MONITORING_LLM_P95_CRITICAL_MS, "lower_is_bad": False},
        "okr_fallback_rate_pct": {"warn": 5.0, "critical": 15.0, "lower_is_bad": False},
        "queue_backlog": {"warn": 20.0, "critical": 50.0, "lower_is_bad": False},
        "twilio_failure_rate_pct": {"warn": 2.0, "critical": 5.0, "lower_is_bad": False},
        "coaching_week_completion_pct": {"warn": 60.0, "critical": 40.0, "lower_is_bad": True},
        "coaching_sunday_reply_pct": {"warn": 50.0, "critical": 30.0, "lower_is_bad": True},
        "coaching_response_p95_min": {"warn": 720.0, "critical": 1440.0, "lower_is_bad": False},
        "coaching_outside_24h_pct": {"warn": 30.0, "critical": 50.0, "lower_is_bad": False},
    }
    coaching_payload = {
        "touchpoints_sent": 0,
        "users_reached": 0,
        "kickoff": {
            "sent": 0,
            "responded_24h": 0,
            "response_rate_pct": None,
            "with_audio": 0,
            "audio_rate_pct": None,
        },
        "day_funnel": {
            "started": 0,
            "completed_sunday": 0,
            "sunday_replied": 0,
            "week_completion_rate_pct": None,
            "sunday_reply_rate_pct": None,
            "steps": [],
        },
        "week_funnel": {
            "weeks": [],
        },
        "response_time_minutes": {
            "p50": None,
            "p95": None,
            "sample_size": 0,
        },
        "engagement_window": {
            "users_tracked": 0,
            "inside_24h": 0,
            "outside_24h": 0,
            "outside_24h_rate_pct": None,
            "outside_24h_state": "unknown",
            "no_inbound_history": 0,
            "last_inbound_age_hours_p50": None,
            "last_inbound_age_hours_p95": None,
            "current_streak_days_p50": None,
            "current_streak_days_p95": None,
            "current_streak_days_max": None,
        },
        "day_stats": [],
    }

    with SessionLocal() as s:
        run_q = (
            s.query(AssessmentRun.id, AssessmentRun.user_id, AssessmentRun.started_at, AssessmentRun.finished_at)
            .filter(AssessmentRun.started_at.isnot(None))
            .filter(AssessmentRun.started_at >= start_utc, AssessmentRun.started_at < end_utc)
        )
        if club_scope_id is not None:
            run_q = run_q.join(User, AssessmentRun.user_id == User.id).filter(User.club_id == club_scope_id)
        run_rows = run_q.all()
        run_ids = [int(run_id) for run_id, _uid, _started_at, _finished_at in run_rows]
        user_ids = sorted({int(uid) for _run_id, uid, _started_at, _finished_at in run_rows if uid is not None})

        turn_max_idx_by_run: dict[int, int] = {}
        if run_ids:
            turn_idx_rows = (
                s.query(AssessmentTurn.run_id, func.max(AssessmentTurn.idx))
                .filter(AssessmentTurn.run_id.in_(run_ids))
                .group_by(AssessmentTurn.run_id)
                .all()
            )
            turn_max_idx_by_run = {int(rid): int(max_idx or 0) for rid, max_idx in turn_idx_rows}

        pillar_map: dict[int, set[str]] = {}
        if run_ids:
            pillar_rows = (
                s.query(PillarResult.run_id, PillarResult.pillar_key)
                .filter(PillarResult.run_id.in_(run_ids))
                .all()
            )
            for rid, pillar_key in pillar_rows:
                rid_i = int(rid)
                key = str(pillar_key or "").strip().lower()
                if not key:
                    continue
                pillar_map.setdefault(rid_i, set()).add(key)

        consent_map: dict[int, bool] = {}
        if user_ids:
            consent_rows = (
                s.query(User.id, User.consent_given)
                .filter(User.id.in_(user_ids))
                .all()
            )
            consent_map = {int(uid): bool(consent_given) for uid, consent_given in consent_rows if uid is not None}

        started_count = len(run_rows)
        completed_count = 0
        completion_minutes: list[float] = []
        incomplete_run_ids: list[int] = []
        for run_id, _uid, started_at, finished_at in run_rows:
            if finished_at is not None:
                completed_count += 1
                if started_at is not None and finished_at >= started_at:
                    completion_minutes.append((finished_at - started_at).total_seconds() / 60.0)
            else:
                incomplete_run_ids.append(int(run_id))

        completion_rate = (completed_count / started_count * 100.0) if started_count else None
        median_completion = _percentile(completion_minutes, 50)
        p95_completion = _percentile(completion_minutes, 95)

        step_defs = [
            {"key": "started", "label": "Started assessment", "description": "Run created and assessment flow started."},
            {"key": "consent", "label": "Consent recorded", "description": "User consent recorded before assessment."},
            {"key": "q1_answered", "label": "First question answered", "description": "At least one scored assessment turn captured."},
            {"key": "nutrition_done", "label": "Nutrition completed", "description": "Nutrition pillar result persisted."},
            {"key": "training_done", "label": "Training completed", "description": "Training pillar result persisted."},
            {"key": "resilience_done", "label": "Resilience completed", "description": "Resilience pillar result persisted."},
            {"key": "recovery_done", "label": "Recovery completed", "description": "Recovery pillar result persisted."},
            {"key": "assessment_done", "label": "Assessment completed", "description": "Assessment run marked finished."},
        ]

        reached_by_run: dict[int, int] = {}
        for run_id, uid, _started_at, finished_at in run_rows:
            rid = int(run_id)
            pillars = pillar_map.get(rid, set())
            max_idx = int(turn_max_idx_by_run.get(rid, 0) or 0)
            q1_answered = max_idx >= 1
            consented = bool(consent_map.get(int(uid), False)) if uid is not None else False
            # If answers exist, treat consent as implicitly passed to keep funnel contiguous.
            if q1_answered and not consented:
                consented = True

            nutrition_done = "nutrition" in pillars
            training_done = "training" in pillars
            resilience_done = "resilience" in pillars
            recovery_done = "recovery" in pillars
            assessment_done = finished_at is not None

            reached = 0
            if consented:
                reached = 1
            if reached >= 1 and q1_answered:
                reached = 2
            if reached >= 2 and nutrition_done:
                reached = 3
            if reached >= 3 and training_done:
                reached = 4
            if reached >= 4 and resilience_done:
                reached = 5
            if reached >= 5 and recovery_done:
                reached = 6
            if reached >= 6 and assessment_done:
                reached = 7
            reached_by_run[rid] = reached

        funnel_steps = []
        for i, step in enumerate(step_defs):
            count_i = sum(1 for reached in reached_by_run.values() if reached >= i)
            prev = funnel_steps[i - 1]["count"] if i > 0 else None
            conversion = (count_i / prev * 100.0) if (prev is not None and prev > 0) else None
            dropoff = (prev - count_i) if prev is not None else 0
            percent_of_start = (count_i / started_count * 100.0) if started_count else None
            funnel_steps.append(
                {
                    "key": step["key"],
                    "label": step["label"],
                    "description": step["description"],
                    "count": int(count_i),
                    "percent_of_start": round(percent_of_start, 2) if percent_of_start is not None else None,
                    "conversion_pct_from_prev": round(conversion, 2) if conversion is not None else None,
                    "dropoff_from_prev": int(dropoff),
                }
            )

        stale_cutoff = now_utc - timedelta(minutes=stale_mins)
        stale_q = (
            s.query(func.count(AssessmentRun.id))
            .filter(AssessmentRun.finished_at.is_(None))
            .filter(AssessmentRun.started_at.isnot(None))
            .filter(AssessmentRun.started_at >= start_utc, AssessmentRun.started_at <= stale_cutoff)
        )
        if club_scope_id is not None:
            stale_q = stale_q.join(User, AssessmentRun.user_id == User.id).filter(User.club_id == club_scope_id)
        stale_runs = int(stale_q.scalar() or 0)

        question_dropoff: dict[int, int] = {}
        point_dropoff: dict[str, int] = {}
        avg_last_question_idx = None
        if incomplete_run_ids:
            idx_rows = (
                s.query(AssessmentTurn.run_id, func.max(AssessmentTurn.idx))
                .filter(AssessmentTurn.run_id.in_(incomplete_run_ids))
                .group_by(AssessmentTurn.run_id)
                .all()
            )
            idx_map = {int(rid): int(max_idx or 0) for rid, max_idx in idx_rows}
            if idx_map:
                vals = [v for v in idx_map.values() if v > 0]
                avg_last_question_idx = (sum(vals) / len(vals)) if vals else None
                for idx in vals:
                    question_dropoff[idx] = question_dropoff.get(idx, 0) + 1

            last_turn_by_run: dict[int, tuple[str, str]] = {}
            turn_rows = (
                s.query(AssessmentTurn.run_id, AssessmentTurn.idx, AssessmentTurn.pillar, AssessmentTurn.concept_key)
                .filter(AssessmentTurn.run_id.in_(incomplete_run_ids))
                .order_by(AssessmentTurn.run_id.asc(), AssessmentTurn.idx.desc())
                .all()
            )
            for rid, _idx, pillar, concept_key in turn_rows:
                rid_i = int(rid)
                if rid_i in last_turn_by_run:
                    continue
                last_turn_by_run[rid_i] = ((pillar or "unknown").strip().lower(), (concept_key or "").strip().lower())
            for _rid, (pillar, concept_key) in last_turn_by_run.items():
                label = f"{pillar}.{concept_key}" if concept_key else pillar
                point_dropoff[label] = point_dropoff.get(label, 0) + 1

        prompt_q = (
            s.query(LLMPromptLog.duration_ms, LLMPromptLog.model, LLMPromptLog.touchpoint)
            .filter(LLMPromptLog.created_at >= start_utc, LLMPromptLog.created_at < end_utc)
        )
        if club_scope_id is not None:
            prompt_q = prompt_q.join(User, LLMPromptLog.user_id == User.id).filter(User.club_id == club_scope_id)
        prompt_rows = prompt_q.all()
        coaching_touchpoints = {
            "kickoff",
            "monday",
            "tuesday",
            "wednesday",
            "midweek",
            "thursday",
            "friday",
            "saturday",
            "sunday",
            "sunday_actions",
            "sunday_support",
            "habit_steps_generator",
            "weekstart_actions",
            "weekstart_support",
            "weekstart",
        }

        def _llm_scope(touchpoint: object) -> str | None:
            key = str(touchpoint or "").strip().lower()
            if not key:
                return None
            if key == "assessor_system":
                return "assessment"
            if key == "initial_habit_steps_generator":
                return "assessment"
            if key.startswith("podcast_"):
                return "coaching"
            if key in coaching_touchpoints:
                return "coaching"
            return None

        llm_durations_by_scope: dict[str, list[int]] = {
            "assessment": [],
            "coaching": [],
            "combined": [],
        }
        llm_model_counts_by_scope: dict[str, dict[str, int]] = {
            "assessment": {},
            "coaching": {},
            "combined": {},
        }
        llm_prompt_counts: dict[str, int] = {
            "assessment": 0,
            "coaching": 0,
            "combined": 0,
        }

        for dur, model, touchpoint in prompt_rows:
            scope = _llm_scope(touchpoint)
            if scope is None:
                continue
            llm_prompt_counts[scope] += 1
            llm_prompt_counts["combined"] += 1
            model_key = (model or "unknown").strip()
            scope_models = llm_model_counts_by_scope[scope]
            scope_models[model_key] = scope_models.get(model_key, 0) + 1
            combined_models = llm_model_counts_by_scope["combined"]
            combined_models[model_key] = combined_models.get(model_key, 0) + 1
            if dur is None:
                continue
            try:
                dur_i = int(dur)
            except Exception:
                continue
            if dur_i < 0:
                continue
            llm_durations_by_scope[scope].append(dur_i)
            llm_durations_by_scope["combined"].append(dur_i)

        llm_durations_ms = llm_durations_by_scope["combined"]
        model_counts = llm_model_counts_by_scope["combined"]
        llm_p50 = _percentile([float(v) for v in llm_durations_ms], 50)
        llm_p95 = _percentile([float(v) for v in llm_durations_ms], 95)
        llm_assessment_p50 = _percentile([float(v) for v in llm_durations_by_scope["assessment"]], 50)
        llm_assessment_p95 = _percentile([float(v) for v in llm_durations_by_scope["assessment"]], 95)
        llm_coaching_p50 = _percentile([float(v) for v in llm_durations_by_scope["coaching"]], 50)
        llm_coaching_p95 = _percentile([float(v) for v in llm_durations_by_scope["coaching"]], 95)

        okr_q = (
            s.query(JobAudit.job_name, JobAudit.payload)
            .filter(JobAudit.job_name.in_(["okr_llm_call", "okr_llm_success", "okr_llm_fallback", "okr_llm_error"]))
            .filter(JobAudit.created_at >= start_utc, JobAudit.created_at < end_utc)
        )
        okr_rows = okr_q.all()
        if club_scope_id is not None and okr_rows:
            scoped_user_ids = {
                int(uid)
                for (uid,) in s.query(User.id).filter(User.club_id == club_scope_id).all()
                if uid is not None
            }
            scoped_okr_rows = []
            for job_name, payload in okr_rows:
                body = _as_payload_dict(payload)
                uid = body.get("user_id")
                try:
                    uid_i = int(uid)
                except Exception:
                    uid_i = None
                if uid_i is not None and uid_i in scoped_user_ids:
                    scoped_okr_rows.append((job_name, body))
            okr_rows = scoped_okr_rows
        else:
            okr_rows = [(job_name, _as_payload_dict(payload)) for job_name, payload in okr_rows]
        okr_call_count = sum(1 for job_name, _payload in okr_rows if job_name == "okr_llm_call")
        okr_success_count = sum(1 for job_name, _payload in okr_rows if job_name == "okr_llm_success")
        okr_fallback_count = sum(1 for job_name, _payload in okr_rows if job_name == "okr_llm_fallback")
        okr_error_count = sum(1 for job_name, _payload in okr_rows if job_name == "okr_llm_error")
        okr_denom = okr_call_count or (okr_success_count + okr_fallback_count + okr_error_count)
        okr_fallback_rate = (okr_fallback_count / okr_denom * 100.0) if okr_denom else None

        jobs_q = s.query(BackgroundJob.status, func.count(BackgroundJob.id))
        if club_scope_id is not None:
            jobs_q = jobs_q.join(User, BackgroundJob.user_id == User.id).filter(User.club_id == club_scope_id)
        jobs_rows = jobs_q.group_by(BackgroundJob.status).all()
        job_counts = {str(status or "unknown"): int(count or 0) for status, count in jobs_rows}
        pending_count = int(job_counts.get("pending", 0))
        retry_count = int(job_counts.get("retry", 0))
        running_count = int(job_counts.get("running", 0))
        error_count = int(job_counts.get("error", 0))
        backlog = pending_count + retry_count

        oldest_q = (
            s.query(func.min(BackgroundJob.created_at))
            .filter(BackgroundJob.status.in_(["pending", "retry"]))
        )
        if club_scope_id is not None:
            oldest_q = oldest_q.join(User, BackgroundJob.user_id == User.id).filter(User.club_id == club_scope_id)
        oldest_pending_at = oldest_q.scalar()
        oldest_pending_age_min = (
            (now_utc - oldest_pending_at).total_seconds() / 60.0 if oldest_pending_at else None
        )

        one_hour_ago = now_utc - timedelta(hours=1)
        recent_q = (
            s.query(BackgroundJob.status, func.count(BackgroundJob.id))
            .filter(BackgroundJob.updated_at >= one_hour_ago, BackgroundJob.updated_at < now_utc)
            .filter(BackgroundJob.status.in_(["done", "error"]))
        )
        if club_scope_id is not None:
            recent_q = recent_q.join(User, BackgroundJob.user_id == User.id).filter(User.club_id == club_scope_id)
        recent_rows = recent_q.group_by(BackgroundJob.status).all()
        recent_map = {str(status or "unknown"): int(count or 0) for status, count in recent_rows}
        recent_done = int(recent_map.get("done", 0))
        recent_error = int(recent_map.get("error", 0))
        recent_processed = recent_done + recent_error
        queue_error_rate_1h = (recent_error / recent_processed * 100.0) if recent_processed else None

        msg_q = (
            s.query(MessageLog.direction, func.count(MessageLog.id))
            .filter(MessageLog.created_at >= start_utc, MessageLog.created_at < end_utc)
        )
        if club_scope_id is not None:
            msg_q = msg_q.join(User, MessageLog.user_id == User.id).filter(User.club_id == club_scope_id)
        msg_rows = msg_q.group_by(MessageLog.direction).all()
        msg_map = {str(direction or "unknown"): int(count or 0) for direction, count in msg_rows}
        outbound_messages = int(msg_map.get("outbound", 0))
        inbound_messages = int(msg_map.get("inbound", 0))

        tw_q = (
            s.query(JobAudit.payload)
            .filter(JobAudit.job_name == "twilio_status")
            .filter(JobAudit.created_at >= start_utc, JobAudit.created_at < end_utc)
        )
        tw_rows = tw_q.all()
        tw_statuses: list[dict] = []
        if club_scope_id is not None and tw_rows:
            scoped_user_ids = {
                int(uid)
                for (uid,) in s.query(User.id).filter(User.club_id == club_scope_id).all()
                if uid is not None
            }
            for (payload,) in tw_rows:
                body = _as_payload_dict(payload)
                uid = body.get("user_id")
                try:
                    uid_i = int(uid)
                except Exception:
                    uid_i = None
                if uid_i is not None and uid_i in scoped_user_ids:
                    tw_statuses.append(body)
        else:
            tw_statuses = [_as_payload_dict(payload) for (payload,) in tw_rows]
        tw_total = len(tw_statuses)
        tw_failed = 0
        for body in tw_statuses:
            status_val = str(body.get("status") or "").strip().lower()
            if body.get("error_code") or status_val in {"failed", "undelivered"}:
                tw_failed += 1
        tw_failure_rate = (tw_failed / tw_total * 100.0) if tw_total else None

        coaching_types = ["kickoff", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        weekly_types = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        tp_q = (
            s.query(
                Touchpoint.id,
                Touchpoint.user_id,
                Touchpoint.type,
                Touchpoint.week_no,
                Touchpoint.sent_at,
                Touchpoint.created_at,
                Touchpoint.source_check_in_id,
                Touchpoint.audio_url,
            )
            .filter(Touchpoint.type.in_(coaching_types))
            .filter(func.coalesce(Touchpoint.sent_at, Touchpoint.created_at) >= start_utc)
            .filter(func.coalesce(Touchpoint.sent_at, Touchpoint.created_at) < end_utc)
        )
        if club_scope_id is not None:
            tp_q = tp_q.join(User, Touchpoint.user_id == User.id).filter(User.club_id == club_scope_id)
        tp_rows = tp_q.all()

        touchpoints: list[dict] = []
        touchpoint_user_ids: set[int] = set()
        for tp_id, user_id, tp_type, week_no, sent_at, created_at, source_check_in_id, audio_url in tp_rows:
            try:
                uid = int(user_id)
            except Exception:
                continue
            kind = str(tp_type or "").strip().lower()
            if kind not in coaching_types:
                continue
            ts = sent_at or created_at
            if ts is None:
                continue
            touchpoints.append(
                {
                    "id": int(tp_id),
                    "user_id": uid,
                    "type": kind,
                    "week_no": int(week_no) if week_no is not None else None,
                    "ts": ts,
                    "source_check_in_id": source_check_in_id,
                    "audio_url": audio_url,
                }
            )
            touchpoint_user_ids.add(uid)

        inbound_by_user: dict[int, list[datetime]] = {}
        if touchpoint_user_ids:
            inbound_rows = (
                s.query(MessageLog.user_id, MessageLog.created_at)
                .filter(MessageLog.direction == "inbound")
                .filter(MessageLog.user_id.in_(touchpoint_user_ids))
                .filter(MessageLog.created_at >= start_utc)
                .filter(MessageLog.created_at < (end_utc + timedelta(days=1)))
                .all()
            )
            for uid, created_at in inbound_rows:
                if uid is None or created_at is None:
                    continue
                try:
                    uid_i = int(uid)
                except Exception:
                    continue
                inbound_by_user.setdefault(uid_i, []).append(created_at)
            for uid_i in list(inbound_by_user.keys()):
                inbound_by_user[uid_i].sort()

        coaching_users = sorted(touchpoint_user_ids)
        users_tracked = len(coaching_users)
        inside_24h_count = 0
        outside_24h_count = 0
        no_inbound_history_count = 0
        outside_24h_rate = None
        last_inbound_age_hours: list[float] = []
        streak_days: list[float] = []

        def _to_uk_day(ts: datetime) -> date:
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=ZoneInfo("UTC"))
            else:
                ts = ts.astimezone(ZoneInfo("UTC"))
            return ts.astimezone(UK_TZ).date()

        def _daily_streak(day_set: set[date], anchor_day: date) -> int:
            if anchor_day not in day_set:
                return 0
            streak = 0
            day_cur = anchor_day
            while day_cur in day_set:
                streak += 1
                day_cur = day_cur - timedelta(days=1)
                if streak >= 3650:
                    break
            return streak

        if coaching_users:
            last_inbound_rows = (
                s.query(MessageLog.user_id, func.max(MessageLog.created_at))
                .filter(MessageLog.direction == "inbound")
                .filter(MessageLog.user_id.in_(coaching_users))
                .group_by(MessageLog.user_id)
                .all()
            )
            last_inbound_map: dict[int, datetime] = {}
            for uid, last_ts in last_inbound_rows:
                if uid is None or last_ts is None:
                    continue
                try:
                    uid_i = int(uid)
                except Exception:
                    continue
                last_inbound_map[uid_i] = last_ts

            streak_lookback_days = max(14, min(90, days_val + 30))
            streak_start_utc = now_utc - timedelta(days=streak_lookback_days)
            streak_rows = (
                s.query(MessageLog.user_id, MessageLog.created_at)
                .filter(MessageLog.direction == "inbound")
                .filter(MessageLog.user_id.in_(coaching_users))
                .filter(MessageLog.created_at >= streak_start_utc, MessageLog.created_at < (end_utc + timedelta(days=1)))
                .all()
            )
            streak_days_by_user: dict[int, set[date]] = {}
            for uid, created_at in streak_rows:
                if uid is None or created_at is None:
                    continue
                try:
                    uid_i = int(uid)
                except Exception:
                    continue
                streak_days_by_user.setdefault(uid_i, set()).add(_to_uk_day(created_at))

            anchor_day_uk = _to_uk_day(now_utc)
            for uid_i in coaching_users:
                last_ts = last_inbound_map.get(uid_i)
                if last_ts is None:
                    no_inbound_history_count += 1
                    outside_24h_count += 1
                    streak_days.append(0.0)
                    continue
                if last_ts.tzinfo is not None:
                    last_ts = last_ts.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)
                age_hours = (now_utc - last_ts).total_seconds() / 3600.0
                if age_hours < 0:
                    age_hours = 0.0
                last_inbound_age_hours.append(age_hours)
                if age_hours > 24.0:
                    outside_24h_count += 1
                else:
                    inside_24h_count += 1
                user_streak = _daily_streak(streak_days_by_user.get(uid_i, set()), anchor_day_uk)
                streak_days.append(float(user_streak))

            if users_tracked:
                outside_24h_rate = (outside_24h_count / users_tracked * 100.0)

        touchpoints.sort(key=lambda row: (row["user_id"], row["ts"], row["id"]))
        next_ts_by_touchpoint_id: dict[int, datetime | None] = {}
        for idx, row in enumerate(touchpoints):
            next_ts = None
            if idx + 1 < len(touchpoints) and touchpoints[idx + 1]["user_id"] == row["user_id"]:
                next_ts = touchpoints[idx + 1]["ts"]
            next_ts_by_touchpoint_id[int(row["id"])] = next_ts

        def _first_inbound_between(user_id: int, start_at: datetime, end_at: datetime) -> datetime | None:
            stamps = inbound_by_user.get(user_id) or []
            if not stamps:
                return None
            pos = bisect.bisect_left(stamps, start_at)
            if pos < len(stamps) and stamps[pos] < end_at:
                return stamps[pos]
            return None

        response_minutes: list[float] = []
        for row in touchpoints:
            start_at = row["ts"]
            end_at = start_at + timedelta(hours=24)
            next_ts = next_ts_by_touchpoint_id.get(int(row["id"]))
            if next_ts is not None and next_ts < end_at:
                end_at = next_ts
            first_inbound = _first_inbound_between(int(row["user_id"]), start_at, end_at)
            responded_24h = first_inbound is not None
            # Sunday may have check-in linkage even if inbound log capture was delayed/missed.
            if not responded_24h and row["type"] == "sunday" and row.get("source_check_in_id"):
                responded_24h = True
            row["responded_24h"] = responded_24h
            if first_inbound is not None:
                mins = (first_inbound - start_at).total_seconds() / 60.0
                if mins >= 0:
                    row["response_minutes"] = mins
                    response_minutes.append(mins)
                else:
                    row["response_minutes"] = None
            else:
                row["response_minutes"] = None

        day_stats_map: dict[str, dict[str, object]] = {
            day: {"day": day, "sent": 0, "users": set(), "replied_24h": 0, "with_audio": 0}
            for day in coaching_types
        }
        for row in touchpoints:
            day = str(row["type"])
            stats = day_stats_map.get(day)
            if not stats:
                continue
            stats["sent"] = int(stats["sent"]) + 1
            users_set = stats["users"]
            if isinstance(users_set, set):
                users_set.add(int(row["user_id"]))
            if bool(row.get("responded_24h")):
                stats["replied_24h"] = int(stats["replied_24h"]) + 1
            if row.get("audio_url"):
                stats["with_audio"] = int(stats["with_audio"]) + 1

        day_stats_rows = []
        for day in coaching_types:
            stats = day_stats_map.get(day) or {}
            sent_n = int(stats.get("sent") or 0)
            replied_n = int(stats.get("replied_24h") or 0)
            with_audio_n = int(stats.get("with_audio") or 0)
            users_set = stats.get("users")
            users_n = len(users_set) if isinstance(users_set, set) else 0
            day_stats_rows.append(
                {
                    "day": day,
                    "sent": sent_n,
                    "users": users_n,
                    "replied_24h": replied_n,
                    "reply_rate_pct": round((replied_n / sent_n * 100.0), 2) if sent_n else None,
                    "with_audio": with_audio_n,
                    "audio_rate_pct": round((with_audio_n / sent_n * 100.0), 2) if sent_n else None,
                }
            )

        user_weekly_flow: dict[int, dict[str, object]] = {}
        for row in touchpoints:
            day = str(row["type"])
            if day not in weekly_types:
                continue
            uid = int(row["user_id"])
            rec = user_weekly_flow.setdefault(uid, {"days": set(), "sunday_replied": False})
            days_set = rec["days"]
            if isinstance(days_set, set):
                days_set.add(day)
            if day == "sunday" and bool(row.get("responded_24h")):
                rec["sunday_replied"] = True

        weekly_step_defs = [
            {
                "key": "monday_sent",
                "label": "Monday sent",
                "description": "Weekly planning/check-in prompt sent.",
            },
            {
                "key": "tuesday_sent",
                "label": "Tuesday sent",
                "description": "Tuesday follow-up prompt sent.",
            },
            {
                "key": "wednesday_sent",
                "label": "Wednesday sent",
                "description": "Midweek check prompt sent.",
            },
            {
                "key": "thursday_sent",
                "label": "Thursday sent",
                "description": "Thursday boost prompt sent.",
            },
            {
                "key": "friday_sent",
                "label": "Friday sent",
                "description": "Friday boost prompt sent.",
            },
            {
                "key": "saturday_sent",
                "label": "Saturday sent",
                "description": "Weekend keepalive prompt sent.",
            },
            {
                "key": "sunday_sent",
                "label": "Sunday sent",
                "description": "Sunday review prompt sent.",
            },
            {
                "key": "sunday_replied",
                "label": "Sunday replied (24h)",
                "description": "User replied within 24 hours of Sunday review.",
            },
        ]

        def _reached_stage(days: set[str], sunday_replied: bool) -> int:
            reached = -1
            if "monday" in days:
                reached = 0
            if reached >= 0 and "tuesday" in days:
                reached = 1
            if reached >= 1 and "wednesday" in days:
                reached = 2
            if reached >= 2 and "thursday" in days:
                reached = 3
            if reached >= 3 and "friday" in days:
                reached = 4
            if reached >= 4 and "saturday" in days:
                reached = 5
            if reached >= 5 and "sunday" in days:
                reached = 6
            if reached >= 6 and sunday_replied:
                reached = 7
            return reached

        reached_by_user: dict[int, int] = {}
        for uid, rec in user_weekly_flow.items():
            days_set = rec.get("days")
            if not isinstance(days_set, set):
                days_set = set()
            reached_by_user[uid] = _reached_stage(days_set, bool(rec.get("sunday_replied")))

        weekly_started = sum(1 for reached in reached_by_user.values() if reached >= 0)
        weekly_funnel_steps = []
        for idx, step in enumerate(weekly_step_defs):
            count_i = sum(1 for reached in reached_by_user.values() if reached >= idx)
            prev = weekly_funnel_steps[idx - 1]["count"] if idx > 0 else None
            conversion = (count_i / prev * 100.0) if (prev is not None and prev > 0) else None
            dropoff = (prev - count_i) if prev is not None else 0
            pct_of_start = (count_i / weekly_started * 100.0) if weekly_started else None
            weekly_funnel_steps.append(
                {
                    "key": step["key"],
                    "label": step["label"],
                    "description": step["description"],
                    "count": int(count_i),
                    "percent_of_start": round(pct_of_start, 2) if pct_of_start is not None else None,
                    "conversion_pct_from_prev": round(conversion, 2) if conversion is not None else None,
                    "dropoff_from_prev": int(dropoff),
                }
            )

        week_user_flow: dict[int, dict[int, dict[str, object]]] = {}
        for row in touchpoints:
            day = str(row["type"])
            if day not in weekly_types:
                continue
            week_no = row.get("week_no")
            if week_no is None:
                continue
            try:
                week_i = int(week_no)
            except Exception:
                continue
            if week_i <= 0:
                continue
            uid = int(row["user_id"])
            users_for_week = week_user_flow.setdefault(week_i, {})
            rec = users_for_week.setdefault(uid, {"days": set(), "sunday_replied": False})
            days_set = rec.get("days")
            if isinstance(days_set, set):
                days_set.add(day)
            if day == "sunday" and bool(row.get("responded_24h")):
                rec["sunday_replied"] = True

        week_rows = []
        for week_i in sorted(week_user_flow.keys()):
            recs = week_user_flow.get(week_i) or {}
            reached_by_uid: dict[int, int] = {}
            for uid, rec in recs.items():
                days_set = rec.get("days")
                if not isinstance(days_set, set):
                    days_set = set()
                reached_by_uid[uid] = _reached_stage(days_set, bool(rec.get("sunday_replied")))
            started_users = sum(1 for reached in reached_by_uid.values() if reached >= 0)
            steps = []
            for idx, step in enumerate(weekly_step_defs):
                count_i = sum(1 for reached in reached_by_uid.values() if reached >= idx)
                prev = steps[idx - 1]["count"] if idx > 0 else None
                conversion = (count_i / prev * 100.0) if (prev is not None and prev > 0) else None
                dropoff = (prev - count_i) if prev is not None else 0
                pct_of_start = (count_i / started_users * 100.0) if started_users else None
                steps.append(
                    {
                        "key": step["key"],
                        "label": step["label"],
                        "count": int(count_i),
                        "percent_of_start": round(pct_of_start, 2) if pct_of_start is not None else None,
                        "conversion_pct_from_prev": round(conversion, 2) if conversion is not None else None,
                        "dropoff_from_prev": int(dropoff),
                    }
                )
            completed_users = steps[6]["count"] if len(steps) > 6 else 0
            sunday_replied_users = steps[7]["count"] if len(steps) > 7 else 0
            completion_rate_pct = (completed_users / started_users * 100.0) if started_users else None
            sunday_reply_rate_pct = (sunday_replied_users / completed_users * 100.0) if completed_users else None
            week_rows.append(
                {
                    "week_no": int(week_i),
                    "cohort_users": int(started_users),
                    "completed_sunday": int(completed_users),
                    "sunday_replied": int(sunday_replied_users),
                    "completion_rate_pct": round(completion_rate_pct, 2) if completion_rate_pct is not None else None,
                    "sunday_reply_rate_pct": round(sunday_reply_rate_pct, 2) if sunday_reply_rate_pct is not None else None,
                    "steps": steps,
                }
            )

        kickoff_sent = next((row["sent"] for row in day_stats_rows if row.get("day") == "kickoff"), 0)
        kickoff_replied = next((row["replied_24h"] for row in day_stats_rows if row.get("day") == "kickoff"), 0)
        kickoff_audio = next((row["with_audio"] for row in day_stats_rows if row.get("day") == "kickoff"), 0)
        sunday_sent_count = weekly_funnel_steps[6]["count"] if len(weekly_funnel_steps) > 6 else 0
        sunday_replied_count = weekly_funnel_steps[7]["count"] if len(weekly_funnel_steps) > 7 else 0
        week_completion_rate = (sunday_sent_count / weekly_started * 100.0) if weekly_started else None
        sunday_reply_rate = (sunday_replied_count / sunday_sent_count * 100.0) if sunday_sent_count else None
        response_p50 = _percentile(response_minutes, 50)
        response_p95 = _percentile(response_minutes, 95)
        last_inbound_age_p50 = _percentile(last_inbound_age_hours, 50)
        last_inbound_age_p95 = _percentile(last_inbound_age_hours, 95)
        streak_p50 = _percentile(streak_days, 50)
        streak_p95 = _percentile(streak_days, 95)

        coaching_payload = {
            "touchpoints_sent": len(touchpoints),
            "users_reached": len({int(row["user_id"]) for row in touchpoints}),
            "kickoff": {
                "sent": int(kickoff_sent or 0),
                "responded_24h": int(kickoff_replied or 0),
                "response_rate_pct": round((kickoff_replied / kickoff_sent * 100.0), 2) if kickoff_sent else None,
                "with_audio": int(kickoff_audio or 0),
                "audio_rate_pct": round((kickoff_audio / kickoff_sent * 100.0), 2) if kickoff_sent else None,
            },
            "day_funnel": {
                "started": int(weekly_started),
                "completed_sunday": int(sunday_sent_count),
                "sunday_replied": int(sunday_replied_count),
                "week_completion_rate_pct": round(week_completion_rate, 2) if week_completion_rate is not None else None,
                "sunday_reply_rate_pct": round(sunday_reply_rate, 2) if sunday_reply_rate is not None else None,
                "steps": weekly_funnel_steps,
            },
            "week_funnel": {
                "weeks": week_rows,
            },
            "response_time_minutes": {
                "p50": round(response_p50, 2) if response_p50 is not None else None,
                "p95": round(response_p95, 2) if response_p95 is not None else None,
                "sample_size": len(response_minutes),
            },
            "engagement_window": {
                "users_tracked": int(users_tracked),
                "inside_24h": int(inside_24h_count),
                "outside_24h": int(outside_24h_count),
                "outside_24h_rate_pct": round(outside_24h_rate, 2) if outside_24h_rate is not None else None,
                "outside_24h_state": "unknown",
                "no_inbound_history": int(no_inbound_history_count),
                "last_inbound_age_hours_p50": round(last_inbound_age_p50, 2) if last_inbound_age_p50 is not None else None,
                "last_inbound_age_hours_p95": round(last_inbound_age_p95, 2) if last_inbound_age_p95 is not None else None,
                "current_streak_days_p50": round(streak_p50, 2) if streak_p50 is not None else None,
                "current_streak_days_p95": round(streak_p95, 2) if streak_p95 is not None else None,
                "current_streak_days_max": int(max(streak_days)) if streak_days else None,
            },
            "day_stats": day_stats_rows,
        }

        ps = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()

    def _env_flag(name: str) -> bool:
        return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes"}

    worker_override = getattr(ps, "worker_mode_override", None) if ps else None
    podcast_override = getattr(ps, "podcast_worker_mode_override", None) if ps else None
    env_worker = _env_flag("PROMPT_WORKER_MODE")
    env_podcast = _env_flag("PODCAST_WORKER_MODE")
    worker_effective = worker_override if worker_override is not None else env_worker
    if worker_effective is False:
        podcast_effective = False
        podcast_source = "disabled_by_worker"
    else:
        podcast_effective = podcast_override if podcast_override is not None else env_podcast
        podcast_source = "override" if podcast_override is not None else "env"

    llm_latency_thresholds = _monitoring_llm_latency_threshold_values(ps)
    thresholds["llm_p50_ms"]["warn"] = llm_latency_thresholds["llm_p50_warn_ms"]
    thresholds["llm_p50_ms"]["critical"] = llm_latency_thresholds["llm_p50_critical_ms"]
    thresholds["llm_p95_ms"]["warn"] = llm_latency_thresholds["llm_p95_warn_ms"]
    thresholds["llm_p95_ms"]["critical"] = llm_latency_thresholds["llm_p95_critical_ms"]
    thresholds["llm_interactive_p50_ms"]["warn"] = llm_latency_thresholds["llm_interactive_p50_warn_ms"]
    thresholds["llm_interactive_p50_ms"]["critical"] = llm_latency_thresholds["llm_interactive_p50_critical_ms"]
    thresholds["llm_interactive_p95_ms"]["warn"] = llm_latency_thresholds["llm_interactive_p95_warn_ms"]
    thresholds["llm_interactive_p95_ms"]["critical"] = llm_latency_thresholds["llm_interactive_p95_critical_ms"]
    thresholds["llm_worker_p50_ms"]["warn"] = llm_latency_thresholds["llm_worker_p50_warn_ms"]
    thresholds["llm_worker_p50_ms"]["critical"] = llm_latency_thresholds["llm_worker_p50_critical_ms"]
    thresholds["llm_worker_p95_ms"]["warn"] = llm_latency_thresholds["llm_worker_p95_warn_ms"]
    thresholds["llm_worker_p95_ms"]["critical"] = llm_latency_thresholds["llm_worker_p95_critical_ms"]

    completion_state = _threshold_state(
        completion_rate,
        warn=thresholds["completion_rate_pct"]["warn"],
        critical=thresholds["completion_rate_pct"]["critical"],
        lower_is_bad=True,
    )
    median_state = _threshold_state(
        median_completion,
        warn=thresholds["median_completion_minutes"]["warn"],
        critical=thresholds["median_completion_minutes"]["critical"],
    )
    stale_state = _threshold_state(
        stale_runs,
        warn=thresholds["stale_runs"]["warn"],
        critical=thresholds["stale_runs"]["critical"],
    )
    llm_p50_state = _threshold_state(
        llm_p50,
        warn=thresholds["llm_p50_ms"]["warn"],
        critical=thresholds["llm_p50_ms"]["critical"],
    )
    llm_assessment_p50_state = _threshold_state(
        llm_assessment_p50,
        warn=thresholds["llm_interactive_p50_ms"]["warn"],
        critical=thresholds["llm_interactive_p50_ms"]["critical"],
    )
    llm_coaching_p50_state = _threshold_state(
        llm_coaching_p50,
        warn=thresholds["llm_worker_p50_ms"]["warn"],
        critical=thresholds["llm_worker_p50_ms"]["critical"],
    )
    llm_p95_state = _threshold_state(
        llm_p95,
        warn=thresholds["llm_p95_ms"]["warn"],
        critical=thresholds["llm_p95_ms"]["critical"],
    )
    llm_assessment_p95_state = _threshold_state(
        llm_assessment_p95,
        warn=thresholds["llm_interactive_p95_ms"]["warn"],
        critical=thresholds["llm_interactive_p95_ms"]["critical"],
    )
    llm_coaching_p95_state = _threshold_state(
        llm_coaching_p95,
        warn=thresholds["llm_worker_p95_ms"]["warn"],
        critical=thresholds["llm_worker_p95_ms"]["critical"],
    )
    llm_combined_state = _worst_state(llm_p50_state, llm_p95_state)
    llm_assessment_state = _worst_state(llm_assessment_p50_state, llm_assessment_p95_state)
    llm_coaching_state = _worst_state(llm_coaching_p50_state, llm_coaching_p95_state)
    fallback_state = _threshold_state(
        okr_fallback_rate,
        warn=thresholds["okr_fallback_rate_pct"]["warn"],
        critical=thresholds["okr_fallback_rate_pct"]["critical"],
    )
    backlog_state = _threshold_state(
        backlog,
        warn=thresholds["queue_backlog"]["warn"],
        critical=thresholds["queue_backlog"]["critical"],
    )
    twilio_state = _threshold_state(
        tw_failure_rate,
        warn=thresholds["twilio_failure_rate_pct"]["warn"],
        critical=thresholds["twilio_failure_rate_pct"]["critical"],
    )
    coaching_week_completion = (
        ((coaching_payload.get("day_funnel") or {}).get("week_completion_rate_pct"))
        if isinstance(coaching_payload, dict)
        else None
    )
    coaching_sunday_reply = (
        ((coaching_payload.get("day_funnel") or {}).get("sunday_reply_rate_pct"))
        if isinstance(coaching_payload, dict)
        else None
    )
    coaching_response_p95 = (
        ((coaching_payload.get("response_time_minutes") or {}).get("p95"))
        if isinstance(coaching_payload, dict)
        else None
    )
    coaching_outside_24h = (
        ((coaching_payload.get("engagement_window") or {}).get("outside_24h_rate_pct"))
        if isinstance(coaching_payload, dict)
        else None
    )
    coaching_week_completion_state = _threshold_state(
        coaching_week_completion,
        warn=thresholds["coaching_week_completion_pct"]["warn"],
        critical=thresholds["coaching_week_completion_pct"]["critical"],
        lower_is_bad=True,
    )
    coaching_sunday_reply_state = _threshold_state(
        coaching_sunday_reply,
        warn=thresholds["coaching_sunday_reply_pct"]["warn"],
        critical=thresholds["coaching_sunday_reply_pct"]["critical"],
        lower_is_bad=True,
    )
    coaching_response_state = _threshold_state(
        coaching_response_p95,
        warn=thresholds["coaching_response_p95_min"]["warn"],
        critical=thresholds["coaching_response_p95_min"]["critical"],
    )
    coaching_outside_24h_state = _threshold_state(
        coaching_outside_24h,
        warn=thresholds["coaching_outside_24h_pct"]["warn"],
        critical=thresholds["coaching_outside_24h_pct"]["critical"],
    )
    if isinstance(coaching_payload, dict):
        if isinstance(coaching_payload.get("day_funnel"), dict):
            coaching_payload["day_funnel"]["week_completion_state"] = coaching_week_completion_state
            coaching_payload["day_funnel"]["sunday_reply_state"] = coaching_sunday_reply_state
        if isinstance(coaching_payload.get("response_time_minutes"), dict):
            coaching_payload["response_time_minutes"]["state"] = coaching_response_state
        if isinstance(coaching_payload.get("engagement_window"), dict):
            coaching_payload["engagement_window"]["outside_24h_state"] = coaching_outside_24h_state

    alerts = []
    metric_states = {
        "completion_rate_pct": completion_state,
        "median_completion_minutes": median_state,
        "stale_runs": stale_state,
        "llm_interactive_p95_ms": llm_assessment_p95_state,
        "llm_worker_p95_ms": llm_coaching_p95_state,
        "okr_fallback_rate_pct": fallback_state,
        "queue_backlog": backlog_state,
        "twilio_failure_rate_pct": twilio_state,
        "coaching_week_completion_pct": coaching_week_completion_state,
        "coaching_sunday_reply_pct": coaching_sunday_reply_state,
        "coaching_response_p95_min": coaching_response_state,
        "coaching_outside_24h_pct": coaching_outside_24h_state,
    }
    metric_values = {
        "completion_rate_pct": completion_rate,
        "median_completion_minutes": median_completion,
        "stale_runs": stale_runs,
        "llm_interactive_p95_ms": llm_assessment_p95,
        "llm_worker_p95_ms": llm_coaching_p95,
        "okr_fallback_rate_pct": okr_fallback_rate,
        "queue_backlog": backlog,
        "twilio_failure_rate_pct": tw_failure_rate,
        "coaching_week_completion_pct": coaching_week_completion,
        "coaching_sunday_reply_pct": coaching_sunday_reply,
        "coaching_response_p95_min": coaching_response_p95,
        "coaching_outside_24h_pct": coaching_outside_24h,
    }
    for key, state in metric_states.items():
        if state in {"warn", "critical"}:
            alerts.append(
                {
                    "metric": key,
                    "state": state,
                    "value": metric_values.get(key),
                    "warn": thresholds.get(key, {}).get("warn"),
                    "critical": thresholds.get(key, {}).get("critical"),
                }
            )

    question_dropoff_rows = [
        {"question_idx": int(idx), "count": int(count)}
        for idx, count in sorted(question_dropoff.items(), key=lambda item: (-item[1], item[0]))[:12]
    ]
    point_dropoff_rows = [
        {"label": label, "count": int(count)}
        for label, count in sorted(point_dropoff.items(), key=lambda item: (-item[1], item[0]))[:12]
    ]

    return {
        "as_of_utc": now_utc.replace(microsecond=0).isoformat() + "Z",
        "window": {
            "days": days_val,
            "start_utc": start_utc.replace(microsecond=0).isoformat() + "Z",
            "end_utc": end_utc.replace(microsecond=0).isoformat() + "Z",
            "stale_minutes": stale_mins,
        },
        "thresholds": thresholds,
        "funnel": {
            "started": started_count,
            "completed": completed_count,
            "incomplete": max(0, started_count - completed_count),
            "completion_rate_pct": round(completion_rate, 2) if completion_rate is not None else None,
            "completion_rate_state": completion_state,
            "median_completion_minutes": round(median_completion, 2) if median_completion is not None else None,
            "p95_completion_minutes": round(p95_completion, 2) if p95_completion is not None else None,
            "median_completion_state": median_state,
            "stale_runs": stale_runs,
            "stale_runs_state": stale_state,
            "steps": funnel_steps,
        },
        "dropoff": {
            "incomplete_runs": len(incomplete_run_ids),
            "avg_last_question_idx": round(avg_last_question_idx, 2) if avg_last_question_idx is not None else None,
            "question_idx_top": question_dropoff_rows,
            "points_top": point_dropoff_rows,
        },
        "llm": {
            "assessor_prompts": llm_prompt_counts["assessment"],
            "duration_ms_p50": round(llm_p50, 2) if llm_p50 is not None else None,
            "duration_ms_p95": round(llm_p95, 2) if llm_p95 is not None else None,
            "duration_ms_p50_state": llm_p50_state,
            "duration_ms_p95_state": llm_p95_state,
            "duration_ms_state": llm_combined_state,
            "models": model_counts,
            "slow_over_warn": sum(1 for v in llm_durations_ms if float(v) > thresholds["llm_p95_ms"]["warn"]),
            "slow_over_critical": sum(1 for v in llm_durations_ms if float(v) > thresholds["llm_p95_ms"]["critical"]),
            "assessment": {
                "prompts": llm_prompt_counts["assessment"],
                "duration_ms_p50": round(llm_assessment_p50, 2) if llm_assessment_p50 is not None else None,
                "duration_ms_p95": round(llm_assessment_p95, 2) if llm_assessment_p95 is not None else None,
                "duration_ms_p50_state": llm_assessment_p50_state,
                "duration_ms_p95_state": llm_assessment_p95_state,
                "duration_ms_state": llm_assessment_state,
                "models": llm_model_counts_by_scope["assessment"],
                "slow_over_warn": sum(
                    1 for v in llm_durations_by_scope["assessment"] if float(v) > thresholds["llm_interactive_p95_ms"]["warn"]
                ),
                "slow_over_critical": sum(
                    1 for v in llm_durations_by_scope["assessment"] if float(v) > thresholds["llm_interactive_p95_ms"]["critical"]
                ),
            },
            "coaching": {
                "prompts": llm_prompt_counts["coaching"],
                "duration_ms_p50": round(llm_coaching_p50, 2) if llm_coaching_p50 is not None else None,
                "duration_ms_p95": round(llm_coaching_p95, 2) if llm_coaching_p95 is not None else None,
                "duration_ms_p50_state": llm_coaching_p50_state,
                "duration_ms_p95_state": llm_coaching_p95_state,
                "duration_ms_state": llm_coaching_state,
                "models": llm_model_counts_by_scope["coaching"],
                "slow_over_warn": sum(
                    1 for v in llm_durations_by_scope["coaching"] if float(v) > thresholds["llm_worker_p95_ms"]["warn"]
                ),
                "slow_over_critical": sum(
                    1 for v in llm_durations_by_scope["coaching"] if float(v) > thresholds["llm_worker_p95_ms"]["critical"]
                ),
            },
            "interactive": {
                "prompts": llm_prompt_counts["assessment"],
                "duration_ms_p50": round(llm_assessment_p50, 2) if llm_assessment_p50 is not None else None,
                "duration_ms_p95": round(llm_assessment_p95, 2) if llm_assessment_p95 is not None else None,
                "duration_ms_p50_state": llm_assessment_p50_state,
                "duration_ms_p95_state": llm_assessment_p95_state,
                "duration_ms_state": llm_assessment_state,
                "models": llm_model_counts_by_scope["assessment"],
                "slow_over_warn": sum(
                    1 for v in llm_durations_by_scope["assessment"] if float(v) > thresholds["llm_interactive_p95_ms"]["warn"]
                ),
                "slow_over_critical": sum(
                    1 for v in llm_durations_by_scope["assessment"] if float(v) > thresholds["llm_interactive_p95_ms"]["critical"]
                ),
            },
            "worker": {
                "prompts": llm_prompt_counts["coaching"],
                "duration_ms_p50": round(llm_coaching_p50, 2) if llm_coaching_p50 is not None else None,
                "duration_ms_p95": round(llm_coaching_p95, 2) if llm_coaching_p95 is not None else None,
                "duration_ms_p50_state": llm_coaching_p50_state,
                "duration_ms_p95_state": llm_coaching_p95_state,
                "duration_ms_state": llm_coaching_state,
                "models": llm_model_counts_by_scope["coaching"],
                "slow_over_warn": sum(
                    1 for v in llm_durations_by_scope["coaching"] if float(v) > thresholds["llm_worker_p95_ms"]["warn"]
                ),
                "slow_over_critical": sum(
                    1 for v in llm_durations_by_scope["coaching"] if float(v) > thresholds["llm_worker_p95_ms"]["critical"]
                ),
            },
            "combined": {
                "prompts": llm_prompt_counts["combined"],
                "duration_ms_p50": round(llm_p50, 2) if llm_p50 is not None else None,
                "duration_ms_p95": round(llm_p95, 2) if llm_p95 is not None else None,
                "duration_ms_p50_state": llm_p50_state,
                "duration_ms_p95_state": llm_p95_state,
                "duration_ms_state": llm_combined_state,
                "models": llm_model_counts_by_scope["combined"],
                "slow_over_warn": sum(1 for v in llm_durations_ms if float(v) > thresholds["llm_p95_ms"]["warn"]),
                "slow_over_critical": sum(
                    1 for v in llm_durations_ms if float(v) > thresholds["llm_p95_ms"]["critical"]
                ),
            },
            "okr_generation": {
                "calls": okr_call_count,
                "success": okr_success_count,
                "fallback": okr_fallback_count,
                "errors": okr_error_count,
                "fallback_rate_pct": round(okr_fallback_rate, 2) if okr_fallback_rate is not None else None,
                "fallback_rate_state": fallback_state,
            },
        },
        "queue": {
            "pending": pending_count,
            "retry": retry_count,
            "running": running_count,
            "error": error_count,
            "backlog": backlog,
            "backlog_state": backlog_state,
            "oldest_pending_age_min": round(oldest_pending_age_min, 2) if oldest_pending_age_min is not None else None,
            "error_rate_1h_pct": round(queue_error_rate_1h, 2) if queue_error_rate_1h is not None else None,
            "processed_1h": recent_processed,
        },
        "messaging": {
            "outbound_messages": outbound_messages,
            "inbound_messages": inbound_messages,
            "twilio_callbacks": tw_total,
            "twilio_failures": tw_failed,
            "twilio_failure_rate_pct": round(tw_failure_rate, 2) if tw_failure_rate is not None else None,
            "twilio_failure_state": twilio_state,
        },
        "worker": {
            "worker_mode_override": worker_override,
            "podcast_worker_mode_override": podcast_override,
            "worker_mode_env": env_worker,
            "podcast_worker_mode_env": env_podcast,
            "worker_mode_effective": worker_effective,
            "podcast_worker_mode_effective": podcast_effective,
            "worker_mode_source": "override" if worker_override is not None else "env",
            "podcast_worker_mode_source": podcast_source,
        },
        "coaching": coaching_payload,
        "alerts": alerts,
    }


@admin.post("/assessment/health/settings")
def admin_assessment_health_settings_update(
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    ensure_prompt_settings_schema()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")

    def _parse_optional_positive(name: str) -> float | None:
        if name not in payload:
            return None
        raw = payload.get(name)
        if raw is None:
            return None
        if isinstance(raw, str):
            cleaned = raw.strip()
            if not cleaned:
                return None
            raw = cleaned
        try:
            val = float(raw)
        except Exception:
            raise HTTPException(status_code=400, detail=f"{name} must be a number")
        if not math.isfinite(val) or val <= 0:
            raise HTTPException(status_code=400, detail=f"{name} must be > 0")
        return float(val)

    p50_warn = _parse_optional_positive("llm_p50_warn_ms") if "llm_p50_warn_ms" in payload else None
    p50_critical = _parse_optional_positive("llm_p50_critical_ms") if "llm_p50_critical_ms" in payload else None
    p95_warn = _parse_optional_positive("llm_p95_warn_ms") if "llm_p95_warn_ms" in payload else None
    p95_critical = _parse_optional_positive("llm_p95_critical_ms") if "llm_p95_critical_ms" in payload else None
    interactive_p50_warn = (
        _parse_optional_positive("llm_interactive_p50_warn_ms") if "llm_interactive_p50_warn_ms" in payload else None
    )
    interactive_p50_critical = (
        _parse_optional_positive("llm_interactive_p50_critical_ms") if "llm_interactive_p50_critical_ms" in payload else None
    )
    interactive_p95_warn = (
        _parse_optional_positive("llm_interactive_p95_warn_ms") if "llm_interactive_p95_warn_ms" in payload else None
    )
    interactive_p95_critical = (
        _parse_optional_positive("llm_interactive_p95_critical_ms") if "llm_interactive_p95_critical_ms" in payload else None
    )
    worker_p50_warn = _parse_optional_positive("llm_worker_p50_warn_ms") if "llm_worker_p50_warn_ms" in payload else None
    worker_p50_critical = (
        _parse_optional_positive("llm_worker_p50_critical_ms") if "llm_worker_p50_critical_ms" in payload else None
    )
    worker_p95_warn = _parse_optional_positive("llm_worker_p95_warn_ms") if "llm_worker_p95_warn_ms" in payload else None
    worker_p95_critical = (
        _parse_optional_positive("llm_worker_p95_critical_ms") if "llm_worker_p95_critical_ms" in payload else None
    )

    with SessionLocal() as s:
        row = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()
        if not row:
            row = PromptSettings()
            s.add(row)

        if "llm_p50_warn_ms" in payload:
            row.monitoring_llm_p50_warn_ms = p50_warn
        if "llm_p50_critical_ms" in payload:
            row.monitoring_llm_p50_critical_ms = p50_critical
        if "llm_p95_warn_ms" in payload:
            row.monitoring_llm_p95_warn_ms = p95_warn
        if "llm_p95_critical_ms" in payload:
            row.monitoring_llm_p95_critical_ms = p95_critical
        if "llm_interactive_p50_warn_ms" in payload:
            row.monitoring_llm_interactive_p50_warn_ms = interactive_p50_warn
        if "llm_interactive_p50_critical_ms" in payload:
            row.monitoring_llm_interactive_p50_critical_ms = interactive_p50_critical
        if "llm_interactive_p95_warn_ms" in payload:
            row.monitoring_llm_interactive_p95_warn_ms = interactive_p95_warn
        if "llm_interactive_p95_critical_ms" in payload:
            row.monitoring_llm_interactive_p95_critical_ms = interactive_p95_critical
        if "llm_worker_p50_warn_ms" in payload:
            row.monitoring_llm_worker_p50_warn_ms = worker_p50_warn
        if "llm_worker_p50_critical_ms" in payload:
            row.monitoring_llm_worker_p50_critical_ms = worker_p50_critical
        if "llm_worker_p95_warn_ms" in payload:
            row.monitoring_llm_worker_p95_warn_ms = worker_p95_warn
        if "llm_worker_p95_critical_ms" in payload:
            row.monitoring_llm_worker_p95_critical_ms = worker_p95_critical

        def _clamp_pair(warn_attr: str, critical_attr: str) -> None:
            warn_val = getattr(row, warn_attr, None)
            critical_val = getattr(row, critical_attr, None)
            if (
                warn_val is not None
                and critical_val is not None
                and float(critical_val) < float(warn_val)
            ):
                setattr(row, critical_attr, float(warn_val))

        _clamp_pair("monitoring_llm_p50_warn_ms", "monitoring_llm_p50_critical_ms")
        _clamp_pair("monitoring_llm_p95_warn_ms", "monitoring_llm_p95_critical_ms")
        _clamp_pair("monitoring_llm_interactive_p50_warn_ms", "monitoring_llm_interactive_p50_critical_ms")
        _clamp_pair("monitoring_llm_interactive_p95_warn_ms", "monitoring_llm_interactive_p95_critical_ms")
        _clamp_pair("monitoring_llm_worker_p50_warn_ms", "monitoring_llm_worker_p50_critical_ms")
        _clamp_pair("monitoring_llm_worker_p95_warn_ms", "monitoring_llm_worker_p95_critical_ms")

        s.commit()
        s.refresh(row)
        resolved = _monitoring_llm_latency_threshold_values(row)
        return {
            "ok": True,
            "settings": {
                "llm_p50_warn_ms": row.monitoring_llm_p50_warn_ms,
                "llm_p50_critical_ms": row.monitoring_llm_p50_critical_ms,
                "llm_p95_warn_ms": row.monitoring_llm_p95_warn_ms,
                "llm_p95_critical_ms": row.monitoring_llm_p95_critical_ms,
                "llm_interactive_p50_warn_ms": row.monitoring_llm_interactive_p50_warn_ms,
                "llm_interactive_p50_critical_ms": row.monitoring_llm_interactive_p50_critical_ms,
                "llm_interactive_p95_warn_ms": row.monitoring_llm_interactive_p95_warn_ms,
                "llm_interactive_p95_critical_ms": row.monitoring_llm_interactive_p95_critical_ms,
                "llm_worker_p50_warn_ms": row.monitoring_llm_worker_p50_warn_ms,
                "llm_worker_p50_critical_ms": row.monitoring_llm_worker_p50_critical_ms,
                "llm_worker_p95_warn_ms": row.monitoring_llm_worker_p95_warn_ms,
                "llm_worker_p95_critical_ms": row.monitoring_llm_worker_p95_critical_ms,
                "resolved": resolved,
            },
        }


@admin.get("/stats")
def admin_stats(admin_user: User = Depends(_require_admin)):
    """
    Return admin dashboard counts (totals + today + this week) in UK local time.
    """
    day_start_utc, day_end_utc, week_start_utc, week_end_utc = _uk_range_bounds()
    club_scope_id = getattr(admin_user, "club_id", None)

    with SessionLocal() as s:
        user_q = select(func.count(User.id))
        assessment_q = select(func.count(AssessmentRun.id)).where(AssessmentRun.finished_at.isnot(None))
        touchpoint_q = select(func.count(Touchpoint.id)).where(
            or_(Touchpoint.status == "sent", Touchpoint.sent_at.isnot(None))
        )

        if club_scope_id is not None:
            user_q = user_q.where(User.club_id == club_scope_id)
            assessment_q = assessment_q.join(User, AssessmentRun.user_id == User.id).where(User.club_id == club_scope_id)
            touchpoint_q = touchpoint_q.join(User, Touchpoint.user_id == User.id).where(User.club_id == club_scope_id)

        total_users = s.execute(user_q).scalar() or 0
        total_assessments = s.execute(assessment_q).scalar() or 0
        total_interactions = s.execute(touchpoint_q).scalar() or 0

        users_today = s.execute(
            user_q.where(User.created_on.isnot(None), User.created_on >= day_start_utc, User.created_on < day_end_utc)
        ).scalar() or 0
        users_week = s.execute(
            user_q.where(User.created_on.isnot(None), User.created_on >= week_start_utc, User.created_on < week_end_utc)
        ).scalar() or 0

        assessments_today = s.execute(
            assessment_q.where(AssessmentRun.finished_at >= day_start_utc, AssessmentRun.finished_at < day_end_utc)
        ).scalar() or 0
        assessments_week = s.execute(
            assessment_q.where(AssessmentRun.finished_at >= week_start_utc, AssessmentRun.finished_at < week_end_utc)
        ).scalar() or 0

        touchpoint_ts = func.coalesce(Touchpoint.sent_at, Touchpoint.created_at)
        interactions_today = s.execute(
            touchpoint_q.where(touchpoint_ts >= day_start_utc, touchpoint_ts < day_end_utc)
        ).scalar() or 0
        interactions_week = s.execute(
            touchpoint_q.where(touchpoint_ts >= week_start_utc, touchpoint_ts < week_end_utc)
        ).scalar() or 0

    return {
        "as_of_uk": datetime.now(UK_TZ).isoformat(),
        "users": {"total": total_users, "today": users_today, "week": users_week},
        "assessments": {"total": total_assessments, "today": assessments_today, "week": assessments_week},
        "interactions": {"total": total_interactions, "today": interactions_today, "week": interactions_week},
    }


@admin.get("/usage/weekly")
def admin_usage_weekly(admin_user: User = Depends(_require_admin)):
    """
    Usage + cost estimates for the last UK week window.
    Focused on TTS usage (weekly flow + total).
    """
    _, _, week_start_utc, week_end_utc = _uk_range_bounds()
    weekly_flow = get_tts_usage_summary(
        start_utc=week_start_utc,
        end_utc=week_end_utc,
        tag="weekly_flow",
    )
    total_tts = get_tts_usage_summary(
        start_utc=week_start_utc,
        end_utc=week_end_utc,
        tag=None,
    )
    llm_weekly = get_llm_usage_summary(
        start_utc=week_start_utc,
        end_utc=week_end_utc,
        tag="weekly_flow",
    )
    llm_total = get_llm_usage_summary(
        start_utc=week_start_utc,
        end_utc=week_end_utc,
        tag=None,
    )
    whatsapp_total = get_whatsapp_usage_summary(
        start_utc=week_start_utc,
        end_utc=week_end_utc,
        tag=None,
    )
    return {
        "as_of_uk": datetime.now(UK_TZ).isoformat(),
        "window": {"start_utc": week_start_utc.isoformat(), "end_utc": week_end_utc.isoformat()},
        "weekly_flow": weekly_flow,
        "total_tts": total_tts,
        "llm_weekly": llm_weekly,
        "llm_total": llm_total,
        "whatsapp_total": whatsapp_total,
    }


@admin.get("/usage/settings")
def admin_usage_settings(admin_user: User = Depends(_require_admin)):
    return get_usage_settings()


@admin.post("/usage/settings")
def admin_usage_settings_update(payload: dict, admin_user: User = Depends(_require_admin)):
    return save_usage_settings(payload)


def _meta_to_dict(value):
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _coerce_prompt_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                for key in ("text", "content"):
                    v = item.get(key)
                    if isinstance(v, str):
                        parts.append(v)
                        break
                else:
                    parts.append(json.dumps(item))
                continue
            parts.append(str(item))
        joined = "\n".join(p for p in parts if p)
        return joined or json.dumps(value)
    if isinstance(value, dict):
        for key in ("text", "content"):
            v = value.get(key)
            if isinstance(v, str):
                return v
        return json.dumps(value)
    return str(value)


def _extract_prompt_user_id(prompt: LLMPromptLog) -> int | None:
    if getattr(prompt, "user_id", None) is not None:
        try:
            return int(prompt.user_id)
        except Exception:
            return None
    meta = _meta_to_dict(prompt.context_meta)
    if meta:
        for key in ("user_id", "userId", "uid"):
            if key not in meta:
                continue
            raw = meta.get(key)
            if raw in {None, ""}:
                continue
            try:
                return int(str(raw).strip())
            except Exception:
                continue
    return None


def _build_prompt_cost_rows(
    *,
    start_utc: datetime,
    end_utc: datetime,
    user_id: int | None,
    limit_val: int,
    default_rate_in: float,
    default_rate_out: float,
    default_rate_source: str,
    llm_settings: dict | None = None,
    tag: str | None = None,
    fetch_limit: int | None = None,
):
    def _prompt_id_from_event(evt: UsageEvent) -> int | None:
        raw = evt.request_id
        meta = evt.meta
        if raw is None and isinstance(meta, dict):
            raw = meta.get("prompt_log_id")
        if raw is None and isinstance(meta, str):
            try:
                meta_obj = json.loads(meta)
                if isinstance(meta_obj, dict):
                    raw = meta_obj.get("prompt_log_id")
            except Exception:
                pass
        if raw is None:
            return None
        try:
            return int(str(raw).strip())
        except Exception:
            return None

    prompt_fetch_limit = fetch_limit if fetch_limit is not None else min(max(limit_val * 20, 200), 2000)

    with SessionLocal() as s:
        event_query = (
            s.query(UsageEvent)
            .filter(
                UsageEvent.product == "llm",
                UsageEvent.unit_type.in_(["tokens_in", "tokens_out"]),
                UsageEvent.created_at >= start_utc,
                UsageEvent.created_at < end_utc,
            )
        )
        if tag:
            event_query = event_query.filter(UsageEvent.tag == tag)
        events = event_query.all()
        event_pairs: list[tuple[UsageEvent, int]] = []
        prompt_ids_from_events: set[int] = set()
        for evt in events:
            pid = _prompt_id_from_event(evt)
            if pid is None:
                continue
            prompt_ids_from_events.add(pid)
            event_pairs.append((evt, pid))

        prompt_map: dict[int, LLMPromptLog] = {}
        if prompt_ids_from_events:
            prompt_rows = s.query(LLMPromptLog).filter(LLMPromptLog.id.in_(prompt_ids_from_events)).all()
            prompt_map = {p.id: p for p in prompt_rows}

        if not tag:
            prompt_rows = (
                s.query(LLMPromptLog)
                .filter(LLMPromptLog.created_at >= start_utc, LLMPromptLog.created_at < end_utc)
                .order_by(LLMPromptLog.created_at.desc())
                .limit(prompt_fetch_limit)
                .all()
            )
            if user_id:
                prompt_rows = [
                    row for row in prompt_rows if _extract_prompt_user_id(row) == user_id
                ]
            for prompt in prompt_rows:
                prompt_map.setdefault(prompt.id, prompt)

    allowed_prompt_ids: set[int] | None = None
    if user_id is not None:
        allowed_prompt_ids = set()
        for pid, prompt in prompt_map.items():
            if _extract_prompt_user_id(prompt) == user_id:
                allowed_prompt_ids.add(pid)
        for evt, pid in event_pairs:
            if evt.user_id == user_id:
                allowed_prompt_ids.add(pid)

    by_prompt: dict[int, dict] = {}
    for prompt in prompt_map.values():
        pid = int(prompt.id)
        if allowed_prompt_ids is not None and pid not in allowed_prompt_ids:
            continue
        resolved_user_id = _extract_prompt_user_id(prompt)
        prompt_text_full = _coerce_prompt_text(prompt.assembled_prompt or prompt.prompt_text or "")
        response_text_full = _coerce_prompt_text(prompt.response_preview) if prompt.response_preview else ""
        prompt_title = prompt.task_label or prompt.prompt_variant or prompt.touchpoint or "prompt"
        by_prompt[pid] = {
            "prompt_id": pid,
            "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
            "user_id": resolved_user_id,
            "touchpoint": prompt.touchpoint,
            "model": prompt.model,
            "prompt_variant": prompt.prompt_variant,
            "task_label": prompt.task_label,
            "prompt_title": prompt_title,
            "prompt_text_full": prompt_text_full,
            "response_text_full": response_text_full,
            "tokens_in": 0.0,
            "tokens_out": 0.0,
            "rate_in": None,
            "rate_out": None,
            "rate_source": None,
            "cost_est_gbp": 0.0,
            "match_user": True if user_id is None else (resolved_user_id == user_id),
        }

    for evt, pid in event_pairs:
        entry = by_prompt.get(pid)
        if not entry:
            continue
        if user_id is not None and not (entry["match_user"] or evt.user_id == user_id):
            continue
        if user_id is not None and evt.user_id == user_id:
            entry["match_user"] = True
        units = float(evt.units or 0.0)
        if evt.unit_type == "tokens_in":
            entry["tokens_in"] += units
        elif evt.unit_type == "tokens_out":
            entry["tokens_out"] += units
        if evt.cost_estimate is not None:
            entry["cost_est_gbp"] += float(evt.cost_estimate)
        meta = _meta_to_dict(evt.meta)
        if meta:
            if entry.get("rate_in") is None and meta.get("rate_in") is not None:
                entry["rate_in"] = float(meta.get("rate_in"))
            if entry.get("rate_out") is None and meta.get("rate_out") is not None:
                entry["rate_out"] = float(meta.get("rate_out"))
            if entry.get("rate_source") is None and meta.get("rate_source"):
                entry["rate_source"] = meta.get("rate_source")

    resolved_settings = dict(llm_settings or {})
    if "llm_gbp_per_1m_input_tokens" not in resolved_settings:
        resolved_settings["llm_gbp_per_1m_input_tokens"] = default_rate_in
    if "llm_gbp_per_1m_output_tokens" not in resolved_settings:
        resolved_settings["llm_gbp_per_1m_output_tokens"] = default_rate_out
    model_rate_cache: dict[str, tuple[float, float, str]] = {}

    def _fallback_rates_for_model(model_name: str | None) -> tuple[float, float, str]:
        cache_key = (model_name or "").strip()
        if cache_key in model_rate_cache:
            return model_rate_cache[cache_key]
        rate_in, rate_out, rate_source, _ = resolve_llm_rates(
            model=model_name,
            settings=resolved_settings,
        )
        model_rate_cache[cache_key] = (float(rate_in or 0.0), float(rate_out or 0.0), rate_source or default_rate_source)
        return model_rate_cache[cache_key]

    rows_out: list[dict] = []
    for entry in by_prompt.values():
        if user_id is not None and not entry.get("match_user"):
            continue
        fallback_in, fallback_out, fallback_source = _fallback_rates_for_model(entry.get("model"))
        # Always price prompt rows using CURRENT usage settings so fetched/saved rates
        # immediately propagate to individual transaction costing.
        rate_in = float(fallback_in or default_rate_in or 0.0)
        rate_out = float(fallback_out or default_rate_out or 0.0)
        if not entry["tokens_in"] and entry.get("prompt_text_full"):
            entry["tokens_in"] = float(estimate_tokens(entry.get("prompt_text_full")))
        if not entry["tokens_out"] and entry.get("response_text_full"):
            entry["tokens_out"] = float(estimate_tokens(entry.get("response_text_full")))
        calc_cost = (entry["tokens_in"] / 1_000_000.0) * rate_in + (entry["tokens_out"] / 1_000_000.0) * rate_out
        logged_cost = float(entry.get("cost_est_gbp") or 0.0)
        cost_est = calc_cost if calc_cost else logged_cost
        rate_source = fallback_source or default_rate_source
        entry["rate_in"] = rate_in or None
        entry["rate_out"] = rate_out or None
        entry["rate_source"] = rate_source
        entry["calc_cost_gbp"] = round(calc_cost, 6)
        entry["cost_est_gbp"] = round(cost_est, 6)
        entry["working"] = (
            f"({entry['tokens_in']:.0f}/1M * £{rate_in:.6f}) + "
            f"({entry['tokens_out']:.0f}/1M * £{rate_out:.6f}) = £{entry['calc_cost_gbp']:.6f}"
        )
        entry.pop("prompt_text_full", None)
        entry.pop("response_text_full", None)
        entry.pop("match_user", None)
        rows_out.append(entry)

    rows_out.sort(key=lambda r: r.get("cost_est_gbp") or 0.0, reverse=True)
    total_cost = sum(r.get("cost_est_gbp") or 0.0 for r in rows_out)
    total_tokens_in = sum(r.get("tokens_in") or 0.0 for r in rows_out)
    total_tokens_out = sum(r.get("tokens_out") or 0.0 for r in rows_out)
    return rows_out, {
        "tokens_in": total_tokens_in,
        "tokens_out": total_tokens_out,
        "cost_est_gbp": total_cost,
    }


@admin.get("/usage/summary")
def admin_usage_summary(
    days: int | None = None,
    start: str | None = None,
    end: str | None = None,
    user_id: int | None = None,
    tag: str | None = None,
    admin_user: User = Depends(_require_admin),
):
    target_user = None
    if user_id:
        with SessionLocal() as s:
            target_user = s.get(User, user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, target_user)

    end_utc = _parse_uk_date(end, end_of_day=True) if end else None
    if not end_utc:
        end_utc = datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)
    start_utc = _parse_uk_date(start, end_of_day=False) if start else None
    if not start_utc:
        try:
            days_val = int(days or 7)
        except Exception:
            days_val = 7
        days_val = max(1, min(days_val, 365))
        start_utc = end_utc - timedelta(days=days_val)
    if end_utc <= start_utc:
        end_utc = start_utc + timedelta(days=1)

    def _llm_summary_for_user() -> dict:
        rates = get_usage_settings()
        rate_in, rate_out, rate_source, _ = resolve_llm_rates(settings=rates)
        _rows_all, totals = _build_prompt_cost_rows(
            start_utc=start_utc,
            end_utc=end_utc,
            user_id=user_id,
            limit_val=200,
            default_rate_in=rate_in,
            default_rate_out=rate_out,
            default_rate_source=rate_source,
            llm_settings=rates,
            tag=tag,
            fetch_limit=5000,
        )
        tokens_in = totals.get("tokens_in") or 0.0
        tokens_out = totals.get("tokens_out") or 0.0
        cost_final = totals.get("cost_est_gbp") or 0.0
        return {
            "tokens_in": int(tokens_in or 0.0),
            "tokens_out": int(tokens_out or 0.0),
            "cost_est_gbp": round(cost_final, 4),
            "rate_gbp_per_1m_input_tokens": rate_in,
            "rate_gbp_per_1m_output_tokens": rate_out,
            "rate_source": rate_source,
            "tag": tag,
        }

    total_tts = get_tts_usage_summary(
        start_utc=start_utc,
        end_utc=end_utc,
        tag=tag,
        user_id=user_id,
    )
    llm_total = (
        _llm_summary_for_user()
        if user_id
        else get_llm_usage_summary(
            start_utc=start_utc,
            end_utc=end_utc,
            tag=tag,
            user_id=user_id,
        )
    )
    whatsapp_total = get_whatsapp_usage_summary(
        start_utc=start_utc,
        end_utc=end_utc,
        tag=tag,
        user_id=user_id,
    )
    combined = (
        float(total_tts.get("cost_est_gbp") or 0.0)
        + float(llm_total.get("cost_est_gbp") or 0.0)
        + float(whatsapp_total.get("cost_est_gbp") or 0.0)
    )
    return {
        "as_of_uk": datetime.now(UK_TZ).isoformat(),
        "window": {"start_utc": start_utc.isoformat(), "end_utc": end_utc.isoformat()},
        "user": {"id": target_user.id, "display_name": target_user.display_name, "phone": target_user.phone}
        if target_user
        else None,
        "total_tts": total_tts,
        "llm_total": llm_total,
        "whatsapp_total": whatsapp_total,
        "combined_cost_gbp": round(combined, 4),
    }


@admin.get("/usage/app-engagement")
def admin_usage_app_engagement(
    days: int | None = None,
    start: str | None = None,
    end: str | None = None,
    user_id: int | None = None,
    admin_user: User = Depends(_require_admin),
):
    target_user = None
    if user_id:
        with SessionLocal() as s:
            target_user = s.get(User, user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, target_user)

    end_utc = _parse_uk_date(end, end_of_day=True) if end else None
    if not end_utc:
        end_utc = datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)
    start_utc = _parse_uk_date(start, end_of_day=False) if start else None
    if not start_utc:
        try:
            days_val = int(days or 7)
        except Exception:
            days_val = 7
        days_val = max(1, min(days_val, 365))
        start_utc = end_utc - timedelta(days=days_val)
    if end_utc <= start_utc:
        end_utc = start_utc + timedelta(days=1)

    club_scope_id = getattr(admin_user, "club_id", None)
    with SessionLocal() as s:
        event_q = (
            s.query(UsageEvent.user_id, UsageEvent.created_at, UsageEvent.unit_type, UsageEvent.meta)
            .filter(
                UsageEvent.created_at >= start_utc,
                UsageEvent.created_at < end_utc,
                UsageEvent.product == APP_ENGAGEMENT_PRODUCT,
            )
        )
        if user_id is not None:
            event_q = event_q.filter(UsageEvent.user_id == user_id)
        elif club_scope_id is not None:
            event_q = event_q.join(User, UsageEvent.user_id == User.id).filter(User.club_id == club_scope_id)
        event_rows = event_q.order_by(UsageEvent.created_at.asc()).all()

        completion_q = (
            s.query(AssessmentRun.user_id, AssessmentRun.finished_at)
            .filter(
                AssessmentRun.finished_at.isnot(None),
                AssessmentRun.finished_at >= start_utc,
                AssessmentRun.finished_at < end_utc,
            )
        )
        if user_id is not None:
            completion_q = completion_q.filter(AssessmentRun.user_id == user_id)
        elif club_scope_id is not None:
            completion_q = completion_q.join(User, AssessmentRun.user_id == User.id).filter(User.club_id == club_scope_id)
        completion_rows = completion_q.all()

        onboarding_pref_keys = tuple(ONBOARDING_PREF_KEYS.values())
        pref_q = (
            s.query(UserPreference.user_id, UserPreference.key, UserPreference.value)
            .filter(UserPreference.key.in_(onboarding_pref_keys))
        )
        if user_id is not None:
            pref_q = pref_q.filter(UserPreference.user_id == user_id)
        elif club_scope_id is not None:
            pref_q = pref_q.join(User, UserPreference.user_id == User.id).filter(User.club_id == club_scope_id)
        onboarding_pref_rows = pref_q.all()

    active_users: set[int] = set()
    home_users: set[int] = set()
    library_users: set[int] = set()
    assessment_users: set[int] = set()
    podcast_play_users: set[int] = set()
    podcast_complete_users: set[int] = set()

    home_views = 0
    library_views = 0
    assessment_views = 0
    podcast_plays = 0
    podcast_completes = 0
    library_podcast_plays = 0
    assessment_podcast_plays = 0
    library_podcast_completes = 0
    assessment_podcast_completes = 0

    results_views_by_user: dict[int, list[datetime]] = {}
    daily_map: dict[str, dict] = {}
    for uid, created_at, unit_type, raw_meta in event_rows:
        if created_at is None:
            continue
        meta = _meta_to_dict(raw_meta) or {}
        page = str(meta.get("page") or "").strip().lower()
        surface = str(meta.get("surface") or "").strip().lower()
        user_id_int = int(uid) if uid is not None else None
        if user_id_int is not None:
            active_users.add(user_id_int)

        day_key = created_at.replace(tzinfo=ZoneInfo("UTC")).astimezone(UK_TZ).date().isoformat()
        day_entry = daily_map.setdefault(
            day_key,
            {
                "day": day_key,
                "home_views": 0,
                "assessment_views": 0,
                "library_views": 0,
                "podcast_plays": 0,
                "podcast_completes": 0,
                "_users": set(),
            },
        )
        if user_id_int is not None:
            day_entry["_users"].add(user_id_int)

        if unit_type == "page_view":
            if page == "progress_home":
                home_views += 1
                day_entry["home_views"] += 1
                if user_id_int is not None:
                    home_users.add(user_id_int)
            elif page == "assessment_results":
                assessment_views += 1
                day_entry["assessment_views"] += 1
                if user_id_int is not None:
                    assessment_users.add(user_id_int)
            elif page == "library":
                library_views += 1
                day_entry["library_views"] += 1
                if user_id_int is not None:
                    library_users.add(user_id_int)

            if page in {"progress_home", "assessment_results"} and user_id_int is not None:
                results_views_by_user.setdefault(user_id_int, []).append(created_at)
            continue

        if unit_type == "podcast_play":
            podcast_plays += 1
            day_entry["podcast_plays"] += 1
            if user_id_int is not None:
                podcast_play_users.add(user_id_int)
            if surface == "library":
                library_podcast_plays += 1
            elif surface == "assessment":
                assessment_podcast_plays += 1
            continue

        if unit_type == "podcast_complete":
            podcast_completes += 1
            day_entry["podcast_completes"] += 1
            if user_id_int is not None:
                podcast_complete_users.add(user_id_int)
            if surface == "library":
                library_podcast_completes += 1
            elif surface == "assessment":
                assessment_podcast_completes += 1

    completion_by_user: dict[int, datetime] = {}
    for uid, finished_at in completion_rows:
        if uid is None or finished_at is None:
            continue
        uid_int = int(uid)
        prev = completion_by_user.get(uid_int)
        if prev is None or finished_at > prev:
            completion_by_user[uid_int] = finished_at

    completed_users = len(completion_by_user)
    post_assessment_results_view_users = 0
    for uid_int, finished_at in completion_by_user.items():
        views = results_views_by_user.get(uid_int) or []
        if any(viewed_at >= finished_at for viewed_at in views):
            post_assessment_results_view_users += 1

    active_user_count = len(active_users)
    avg_home_views_per_active_user = (
        round(home_views / active_user_count, 2) if active_user_count else 0.0
    )
    post_assessment_view_rate_pct = (
        round((post_assessment_results_view_users / completed_users) * 100.0, 1)
        if completed_users
        else None
    )
    podcast_listener_rate_pct = (
        round((len(podcast_play_users) / active_user_count) * 100.0, 1)
        if active_user_count
        else None
    )

    daily_rows = []
    for row in sorted(daily_map.values(), key=lambda val: val["day"]):
        users_in_day = row.pop("_users", set())
        row["active_users"] = len(users_in_day)
        daily_rows.append(row)

    onboarding_by_user: dict[int, dict[str, datetime]] = {}
    for uid, key, raw_val in onboarding_pref_rows:
        if uid is None or not key:
            continue
        user_key = int(uid)
        ts = _parse_pref_timestamp(raw_val)
        if ts is None:
            continue
        row = onboarding_by_user.setdefault(user_key, {})
        prev = row.get(key)
        if prev is None or ts > prev:
            row[key] = ts

    def _in_window(ts: datetime | None) -> bool:
        return bool(ts and start_utc <= ts < end_utc)

    first_login_key = ONBOARDING_PREF_KEYS["first_login"]
    assessment_key = ONBOARDING_PREF_KEYS["assessment_reviewed"]
    intro_presented_key = ONBOARDING_PREF_KEYS["intro_presented"]
    intro_listened_key = ONBOARDING_PREF_KEYS["intro_listened"]
    intro_read_key = ONBOARDING_PREF_KEYS["intro_read"]
    coaching_enabled_key = ONBOARDING_PREF_KEYS["coaching_enabled_at"]

    first_login_users_window: set[int] = set()
    assessment_reviewed_users_window: set[int] = set()
    intro_presented_users_window: set[int] = set()
    intro_listened_users_window: set[int] = set()
    intro_read_users_window: set[int] = set()
    intro_completed_users_window: set[int] = set()
    coaching_auto_enabled_users_window: set[int] = set()

    first_login_cohort = set()
    assessment_after_first = 0
    intro_presented_after_first = 0
    intro_completed_after_first = 0
    coaching_enabled_after_first = 0

    for uid, pref_map in onboarding_by_user.items():
        first_login_ts = pref_map.get(first_login_key)
        assessment_ts = pref_map.get(assessment_key)
        intro_presented_ts = pref_map.get(intro_presented_key)
        intro_listened_ts = pref_map.get(intro_listened_key)
        intro_read_ts = pref_map.get(intro_read_key)
        coaching_enabled_ts = pref_map.get(coaching_enabled_key)
        intro_completed_ts = intro_listened_ts or intro_read_ts

        if _in_window(first_login_ts):
            first_login_users_window.add(uid)
            first_login_cohort.add(uid)
        if _in_window(assessment_ts):
            assessment_reviewed_users_window.add(uid)
        if _in_window(intro_presented_ts):
            intro_presented_users_window.add(uid)
        if _in_window(intro_listened_ts):
            intro_listened_users_window.add(uid)
            intro_completed_users_window.add(uid)
        if _in_window(intro_read_ts):
            intro_read_users_window.add(uid)
            intro_completed_users_window.add(uid)
        if _in_window(coaching_enabled_ts):
            coaching_auto_enabled_users_window.add(uid)

        if uid not in first_login_cohort or first_login_ts is None:
            continue
        if assessment_ts and assessment_ts >= first_login_ts:
            assessment_after_first += 1
        if intro_presented_ts and intro_presented_ts >= first_login_ts:
            intro_presented_after_first += 1
        if (
            (intro_listened_ts and intro_listened_ts >= first_login_ts)
            or (intro_read_ts and intro_read_ts >= first_login_ts)
        ):
            intro_completed_after_first += 1
        if coaching_enabled_ts and coaching_enabled_ts >= first_login_ts:
            coaching_enabled_after_first += 1

    onboarding_first_login_count = len(first_login_cohort)

    def _rate(numerator: int, denominator: int) -> float | None:
        if denominator <= 0:
            return None
        return round((numerator / denominator) * 100.0, 1)

    def _funnel_step(
        *,
        key: str,
        label: str,
        count: int,
        previous: int | None,
        first_login_total: int,
    ) -> dict:
        conversion = None
        dropoff = None
        if previous is not None and previous > 0:
            conversion = round((count / previous) * 100.0, 1)
            dropoff = max(0, previous - count)
        return {
            "key": key,
            "label": label,
            "count": count,
            "percent_of_first_login": _rate(count, first_login_total),
            "conversion_pct_from_prev": conversion,
            "dropoff_from_prev": dropoff,
        }

    onboarding_funnel = []
    onboarding_funnel.append(
        _funnel_step(
            key="first_login",
            label="Logged in",
            count=onboarding_first_login_count,
            previous=None,
            first_login_total=onboarding_first_login_count,
        )
    )
    onboarding_funnel.append(
        _funnel_step(
            key="assessment_reviewed",
            label="Reviewed assessment",
            count=assessment_after_first,
            previous=onboarding_first_login_count,
            first_login_total=onboarding_first_login_count,
        )
    )
    onboarding_funnel.append(
        _funnel_step(
            key="intro_presented",
            label="Intro presented",
            count=intro_presented_after_first,
            previous=assessment_after_first,
            first_login_total=onboarding_first_login_count,
        )
    )
    onboarding_funnel.append(
        _funnel_step(
            key="intro_completed",
            label="Intro completed (listen/read)",
            count=intro_completed_after_first,
            previous=intro_presented_after_first,
            first_login_total=onboarding_first_login_count,
        )
    )
    onboarding_funnel.append(
        _funnel_step(
            key="coaching_auto_enabled",
            label="Coaching auto-enabled",
            count=coaching_enabled_after_first,
            previous=intro_completed_after_first,
            first_login_total=onboarding_first_login_count,
        )
    )

    return {
        "as_of_uk": datetime.now(UK_TZ).isoformat(),
        "window": {"start_utc": start_utc.isoformat(), "end_utc": end_utc.isoformat()},
        "user": {"id": target_user.id, "display_name": target_user.display_name, "phone": target_user.phone}
        if target_user
        else None,
        "top_kpis": {
            "active_app_users": active_user_count,
            "home_page_views": home_views,
            "avg_home_views_per_active_user": avg_home_views_per_active_user,
            "post_assessment_results_view_rate_pct": post_assessment_view_rate_pct,
            "post_assessment_users_completed": completed_users,
            "post_assessment_users_viewed_results": post_assessment_results_view_users,
            "podcast_listener_rate_pct": podcast_listener_rate_pct,
            "podcast_listeners": len(podcast_play_users),
            "onboarding_first_login_users": onboarding_first_login_count,
            "onboarding_intro_completion_rate_pct": _rate(intro_completed_after_first, onboarding_first_login_count),
            "onboarding_coaching_auto_enabled_rate_pct": _rate(coaching_enabled_after_first, onboarding_first_login_count),
        },
        "detail": {
            "home": {"views": home_views, "users": len(home_users)},
            "assessment_results": {"views": assessment_views, "users": len(assessment_users)},
            "library": {"views": library_views, "users": len(library_users)},
            "podcasts": {
                "plays": podcast_plays,
                "completes": podcast_completes,
                "listeners": len(podcast_play_users),
                "completed_listeners": len(podcast_complete_users),
                "library_plays": library_podcast_plays,
                "assessment_plays": assessment_podcast_plays,
                "library_completes": library_podcast_completes,
                "assessment_completes": assessment_podcast_completes,
            },
            "post_assessment": {
                "users_completed": completed_users,
                "users_viewed_results_after_completion": post_assessment_results_view_users,
                "rate_pct": post_assessment_view_rate_pct,
            },
            "onboarding": {
                "first_login_users": len(first_login_users_window),
                "assessment_reviewed_users": len(assessment_reviewed_users_window),
                "intro_presented_users": len(intro_presented_users_window),
                "intro_listened_users": len(intro_listened_users_window),
                "intro_read_users": len(intro_read_users_window),
                "intro_completed_users": len(intro_completed_users_window),
                "coaching_auto_enabled_users": len(coaching_auto_enabled_users_window),
                "first_login_cohort_users": onboarding_first_login_count,
                "assessment_after_first_login_users": assessment_after_first,
                "intro_presented_after_first_login_users": intro_presented_after_first,
                "intro_completed_after_first_login_users": intro_completed_after_first,
                "coaching_auto_enabled_after_first_login_users": coaching_enabled_after_first,
                "assessment_after_first_login_rate_pct": _rate(assessment_after_first, onboarding_first_login_count),
                "intro_presented_after_first_login_rate_pct": _rate(intro_presented_after_first, onboarding_first_login_count),
                "intro_completed_after_first_login_rate_pct": _rate(intro_completed_after_first, onboarding_first_login_count),
                "coaching_auto_enabled_after_first_login_rate_pct": _rate(coaching_enabled_after_first, onboarding_first_login_count),
                "funnel": onboarding_funnel,
            },
            "daily": daily_rows,
        },
    }


@admin.get("/usage/prompt-costs")
def admin_usage_prompt_costs(
    days: int | None = None,
    start: str | None = None,
    end: str | None = None,
    user_id: int | None = None,
    limit: int | None = None,
    admin_user: User = Depends(_require_admin),
):
    target_user = None
    if user_id:
        with SessionLocal() as s:
            target_user = s.get(User, user_id)
        if not target_user:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, target_user)

    end_utc = _parse_uk_date(end, end_of_day=True) if end else None
    if not end_utc:
        end_utc = datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)
    start_utc = _parse_uk_date(start, end_of_day=False) if start else None
    if not start_utc:
        try:
            days_val = int(days or 7)
        except Exception:
            days_val = 7
        days_val = max(1, min(days_val, 365))
        start_utc = end_utc - timedelta(days=days_val)
    if end_utc <= start_utc:
        end_utc = start_utc + timedelta(days=1)

    try:
        limit_val = int(limit or 50)
    except Exception:
        limit_val = 50
    limit_val = max(1, min(limit_val, 200))

    rates = get_usage_settings()
    default_rate_in, default_rate_out, default_rate_source, _ = resolve_llm_rates(settings=rates)
    rows_all, totals = _build_prompt_cost_rows(
        start_utc=start_utc,
        end_utc=end_utc,
        user_id=user_id,
        limit_val=limit_val,
        default_rate_in=default_rate_in,
        default_rate_out=default_rate_out,
        default_rate_source=default_rate_source,
        llm_settings=rates,
        fetch_limit=None,
    )
    rows_out = rows_all[:limit_val] if len(rows_all) > limit_val else rows_all
    total_cost = round(float(totals.get("cost_est_gbp") or 0.0), 6)
    return {
        "as_of_uk": datetime.now(UK_TZ).isoformat(),
        "window": {"start_utc": start_utc.isoformat(), "end_utc": end_utc.isoformat()},
        "user": {"id": target_user.id, "display_name": target_user.display_name, "phone": target_user.phone}
        if target_user
        else None,
        "rows": rows_out,
        "total_cost_gbp": total_cost,
        "limit": limit_val,
    }


@admin.post("/usage/settings/fetch")
def admin_usage_settings_fetch(admin_user: User = Depends(_require_admin)):
    current = get_usage_settings()
    fetch_models = ["gpt-5-mini", "gpt-5.1"]
    rates = fetch_provider_rates(model_names=fetch_models)
    keys = [
        "tts_gbp_per_1m_chars",
        "tts_chars_per_min",
        "llm_gbp_per_1m_input_tokens",
        "llm_gbp_per_1m_output_tokens",
        "llm_model_rates",
        "wa_gbp_per_message",
        "wa_gbp_per_media_message",
        "wa_gbp_per_template_message",
    ]
    updated_keys = []
    for key in keys:
        val = rates.get(key)
        if isinstance(val, dict):
            if val:
                updated_keys.append(key)
            continue
        if val is not None:
            updated_keys.append(key)
    warnings = rates.get("warnings") or []
    if updated_keys:
        rates["status"] = "partial" if warnings else "ok"
    else:
        rates["status"] = "failed"
    rates["updated_keys"] = updated_keys
    def _env_float(name: str) -> float | None:
        raw = (os.getenv(name) or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except Exception:
            return None
    env_fallbacks = {
        "tts_gbp_per_1m_chars": _env_float("USAGE_TTS_GBP_PER_1M_CHARS"),
        "tts_chars_per_min": _env_float("USAGE_TTS_CHARS_PER_MIN"),
        "llm_gbp_per_1m_input_tokens": _env_float("USAGE_LLM_GBP_PER_1M_INPUT_TOKENS"),
        "llm_gbp_per_1m_output_tokens": _env_float("USAGE_LLM_GBP_PER_1M_OUTPUT_TOKENS"),
        "wa_gbp_per_message": _env_float("USAGE_WA_GBP_PER_MESSAGE"),
        "wa_gbp_per_media_message": _env_float("USAGE_WA_GBP_PER_MEDIA_MESSAGE"),
        "wa_gbp_per_template_message": _env_float("USAGE_WA_GBP_PER_TEMPLATE_MESSAGE"),
    }
    def _pick(key: str):
        val = rates.get(key)
        if val is not None:
            return val
        current_val = current.get(key)
        if current_val is not None:
            return current_val
        return env_fallbacks.get(key)
    payload = {
        "tts_gbp_per_1m_chars": _pick("tts_gbp_per_1m_chars"),
        "tts_chars_per_min": _pick("tts_chars_per_min"),
        "llm_gbp_per_1m_input_tokens": _pick("llm_gbp_per_1m_input_tokens"),
        "llm_gbp_per_1m_output_tokens": _pick("llm_gbp_per_1m_output_tokens"),
        "wa_gbp_per_message": _pick("wa_gbp_per_message"),
        "wa_gbp_per_media_message": _pick("wa_gbp_per_media_message"),
        "wa_gbp_per_template_message": _pick("wa_gbp_per_template_message"),
        "meta": rates,
    }
    merged_model_rates: dict[str, dict[str, float]] = {}
    current_model_rates = current.get("llm_model_rates")
    if isinstance(current_model_rates, dict):
        for model_name in fetch_models:
            existing_rates = current_model_rates.get(model_name)
            if not isinstance(existing_rates, dict):
                continue
            existing_entry: dict[str, float] = {}
            if existing_rates.get("input") is not None:
                existing_entry["input"] = float(existing_rates["input"])
            if existing_rates.get("output") is not None:
                existing_entry["output"] = float(existing_rates["output"])
            if existing_entry:
                merged_model_rates[model_name] = existing_entry
    fetched_model_rates = rates.get("llm_model_rates")
    if isinstance(fetched_model_rates, dict):
        for model_name in fetch_models:
            model_rates = fetched_model_rates.get(model_name)
            if not isinstance(model_rates, dict):
                continue
            model_entry = dict(merged_model_rates.get(model_name) or {})
            if model_rates.get("input") is not None:
                model_entry["input"] = float(model_rates["input"])
            if model_rates.get("output") is not None:
                model_entry["output"] = float(model_rates["output"])
            if model_entry:
                merged_model_rates[str(model_name)] = model_entry
    payload["llm_model_rates"] = merged_model_rates
    return save_usage_settings(payload)


@admin.get("/prompts/templates")
def admin_prompt_templates_list(
    state: str | None = None,
    touchpoint: str | None = None,
    q: str | None = None,
    limit: int = 200,
    admin_user: User = Depends(_require_admin),
):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    try:
        limit = int(limit)
    except Exception:
        limit = 200
    limit = max(1, min(limit, 400))
    with SessionLocal() as s:
        query = s.query(PromptTemplate)
        if state:
            st = prompts_module._canonical_state(state)
            query = query.filter(PromptTemplate.state.in_([st, "stage" if st == "beta" else st, "production" if st == "live" else st]))
        if touchpoint:
            query = query.filter(PromptTemplate.touchpoint == touchpoint)
        if q:
            like = f"%{q.strip()}%"
            query = query.filter(PromptTemplate.touchpoint.ilike(like))
        rows = (
            query.order_by(PromptTemplate.touchpoint.asc(), PromptTemplate.version.desc(), PromptTemplate.id.desc())
            .limit(limit)
            .all()
        )
    items = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "touchpoint": row.touchpoint,
                "state": prompts_module._canonical_state(getattr(row, "state", None)),
                "version": row.version,
                "is_active": bool(getattr(row, "is_active", True)),
                "okr_scope": getattr(row, "okr_scope", None),
                "programme_scope": getattr(row, "programme_scope", None),
                "response_format": getattr(row, "response_format", None),
                "model_override": getattr(row, "model_override", None),
                "note": getattr(row, "note", None),
                "updated_at": getattr(row, "updated_at", None),
            }
        )
    return {"count": len(items), "templates": items}


@admin.get("/prompts/templates/{template_id}")
def admin_prompt_template_detail(
    template_id: int,
    admin_user: User = Depends(_require_admin),
):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    with SessionLocal() as s:
        row = s.get(PromptTemplate, template_id)
        if not row:
            raise HTTPException(status_code=404, detail="prompt template not found")
    return {
        "id": row.id,
        "touchpoint": row.touchpoint,
        "state": prompts_module._canonical_state(getattr(row, "state", None)),
        "version": row.version,
        "is_active": bool(getattr(row, "is_active", True)),
        "okr_scope": getattr(row, "okr_scope", None),
        "programme_scope": getattr(row, "programme_scope", None),
        "response_format": getattr(row, "response_format", None),
        "model_override": getattr(row, "model_override", None),
        "block_order": getattr(row, "block_order", None),
        "include_blocks": getattr(row, "include_blocks", None),
        "task_block": getattr(row, "task_block", None),
        "note": getattr(row, "note", None),
        "updated_at": getattr(row, "updated_at", None),
    }


@admin.post("/prompts/templates")
def admin_prompt_template_create(
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    touchpoint = str(payload.get("touchpoint") or "").strip()
    if not touchpoint:
        raise HTTPException(status_code=400, detail="touchpoint required")
    state = prompts_module._canonical_state(payload.get("state") or "develop")
    if state != "develop":
        raise HTTPException(status_code=400, detail="new templates must start in develop state")
    block_order = [b for b in _parse_block_list(payload.get("block_order")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    include_blocks = [b for b in _parse_block_list(payload.get("include_blocks")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    if not include_blocks and block_order:
        include_blocks = list(block_order)
    with SessionLocal() as s:
        row = PromptTemplate(touchpoint=touchpoint)
        row.state = state
        row.version = 1
        row.okr_scope = (payload.get("okr_scope") or None) or None
        row.programme_scope = (payload.get("programme_scope") or None) or None
        row.response_format = (payload.get("response_format") or None) or None
        row.model_override = (str(payload.get("model_override") or "").strip() or None)
        row.block_order = block_order or None
        row.include_blocks = include_blocks or block_order or None
        row.task_block = (payload.get("task_block") or None) or None
        row.note = (payload.get("note") or None) or None
        row.is_active = bool(payload.get("is_active", True))
        s.add(row)
        s.commit()
        s.refresh(row)
    return {"id": row.id, "touchpoint": row.touchpoint}


@admin.post("/prompts/templates/{template_id}")
def admin_prompt_template_update(
    template_id: int,
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    block_order = [b for b in _parse_block_list(payload.get("block_order")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    include_blocks = [b for b in _parse_block_list(payload.get("include_blocks")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    if not include_blocks and block_order:
        include_blocks = list(block_order)
    with SessionLocal() as s:
        row = s.get(PromptTemplate, template_id)
        if not row:
            raise HTTPException(status_code=404, detail="prompt template not found")
        if prompts_module._canonical_state(getattr(row, "state", "develop")) != "develop":
            raise HTTPException(status_code=400, detail="only develop templates can be edited")
        if "okr_scope" in payload:
            row.okr_scope = payload.get("okr_scope") or None
        if "programme_scope" in payload:
            row.programme_scope = payload.get("programme_scope") or None
        if "response_format" in payload:
            row.response_format = payload.get("response_format") or None
        if "model_override" in payload:
            row.model_override = (str(payload.get("model_override") or "").strip() or None)
        if "task_block" in payload:
            row.task_block = payload.get("task_block") or None
        if "note" in payload:
            row.note = payload.get("note") or None
        if "is_active" in payload:
            row.is_active = bool(payload.get("is_active"))
        if block_order or include_blocks:
            row.block_order = block_order or None
            row.include_blocks = include_blocks or block_order or None
        s.commit()
    return {"ok": True}


@admin.post("/prompts/templates/{template_id}/promote")
def admin_prompt_template_promote(
    template_id: int,
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    to_state = prompts_module._canonical_state(payload.get("to_state") or "")
    if to_state not in {"beta", "live"}:
        raise HTTPException(status_code=400, detail="to_state must be beta or live")
    note = (payload.get("note") or "").strip() or None
    with SessionLocal() as s:
        row = s.get(PromptTemplate, template_id)
        if not row:
            raise HTTPException(status_code=404, detail="prompt template not found")
        model_override = _normalize_model_override(getattr(row, "model_override", None))
        if to_state == "live":
            _ensure_live_template_model_allowed(
                model_override,
                context=f"touchpoint '{row.touchpoint}' live promotion",
            )
        max_version = (
            s.query(func.max(PromptTemplate.version))
            .filter(
                PromptTemplate.touchpoint == row.touchpoint,
                PromptTemplate.state.in_([to_state, "stage" if to_state == "beta" else to_state, "production" if to_state == "live" else to_state]),
            )
            .scalar()
            or 0
        )
        new_row = PromptTemplate(
            touchpoint=row.touchpoint,
            state=to_state,
            version=max_version + 1,
            note=note or row.note,
            task_block=row.task_block,
            block_order=row.block_order,
            include_blocks=row.include_blocks,
            okr_scope=row.okr_scope,
            programme_scope=row.programme_scope,
            response_format=row.response_format,
            model_override=model_override,
            is_active=True,
            parent_id=row.id,
        )
        s.add(new_row)
        s.flush()
        try:
            admin_routes._enforce_single_active_states(s, {to_state})  # type: ignore[attr-defined]
        except Exception:
            pass
        s.commit()
    return {"ok": True, "id": new_row.id, "state": to_state, "version": new_row.version}


@admin.post("/prompts/templates/promote-all")
def admin_prompt_templates_promote_all(payload: dict, admin_user: User = Depends(_require_admin)):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    from_state = (payload.get("from_state") or "").strip()
    to_state = (payload.get("to_state") or "").strip()
    note = (payload.get("note") or "").strip() or None
    if not from_state or not to_state:
        raise HTTPException(status_code=400, detail="from_state and to_state required")
    created = admin_routes._promote_templates_batch(from_state, to_state, note)  # type: ignore[attr-defined]
    return {"created": created, "from_state": from_state, "to_state": to_state, "note": note}


@admin.get("/prompts/settings")
def admin_prompt_settings(admin_user: User = Depends(_require_admin)):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    ensure_prompt_settings_schema()
    def _env_flag(name: str) -> bool:
        return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes"}
    with SessionLocal() as s:
        row = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()
    if not row:
        env_worker = _env_flag("PROMPT_WORKER_MODE")
        env_podcast = _env_flag("PODCAST_WORKER_MODE")
        return {
            "system_block": None,
            "locale_block": None,
            "default_block_order": prompts_module.DEFAULT_PROMPT_BLOCK_ORDER,
            "worker_mode_override": None,
            "podcast_worker_mode_override": None,
            "worker_mode_env": env_worker,
            "podcast_worker_mode_env": env_podcast,
            "worker_mode_effective": env_worker,
            "podcast_worker_mode_effective": env_worker and env_podcast,
            "worker_mode_source": "env",
            "podcast_worker_mode_source": "env" if env_worker else "disabled_by_worker",
        }
    order = [b for b in (row.default_block_order or prompts_module.DEFAULT_PROMPT_BLOCK_ORDER) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    worker_override = getattr(row, "worker_mode_override", None)
    podcast_override = getattr(row, "podcast_worker_mode_override", None)
    env_worker = _env_flag("PROMPT_WORKER_MODE")
    env_podcast = _env_flag("PODCAST_WORKER_MODE")
    effective_worker = worker_override if worker_override is not None else env_worker
    if effective_worker is False:
        effective_podcast = False
        podcast_source = "disabled_by_worker"
    else:
        effective_podcast = podcast_override if podcast_override is not None else env_podcast
        podcast_source = "override" if podcast_override is not None else "env"
    return {
        "system_block": getattr(row, "system_block", None),
        "locale_block": getattr(row, "locale_block", None),
        "default_block_order": order,
        "worker_mode_override": worker_override,
        "podcast_worker_mode_override": podcast_override,
        "worker_mode_env": env_worker,
        "podcast_worker_mode_env": env_podcast,
        "worker_mode_effective": effective_worker,
        "podcast_worker_mode_effective": effective_podcast,
        "worker_mode_source": "override" if worker_override is not None else "env",
        "podcast_worker_mode_source": podcast_source,
    }


@admin.get("/prompts/versions")
def admin_prompt_versions(limit: int = 20, admin_user: User = Depends(_require_admin)):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    max_limit = max(1, min(int(limit), 100))
    with SessionLocal() as s:
        logs = (
            s.query(PromptTemplateVersionLog)
            .order_by(PromptTemplateVersionLog.created_at.desc())
            .limit(max_limit)
            .all()
        )
    return {
        "items": [
            {
                "id": log.id,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "version": log.version,
                "from_state": log.from_state,
                "to_state": log.to_state,
                "note": log.note,
            }
            for log in logs
        ]
    }


@admin.get("/prompts/history")
def admin_prompt_history(
    limit: int = 20,
    user_id: int | None = None,
    touchpoint: str | None = None,
    start: str | None = None,
    end: str | None = None,
    admin_user: User = Depends(_require_admin),
):
    from .prompts import _ensure_llm_prompt_log_schema

    _ensure_llm_prompt_log_schema()
    max_limit = max(1, min(int(limit), 100))
    clauses = ["1=1"]
    params: dict[str, object] = {"limit": max_limit}
    if user_id:
        clauses.append("user_id = :user_id")
        params["user_id"] = int(user_id)
    if touchpoint:
        clauses.append("touchpoint = :touchpoint")
        params["touchpoint"] = touchpoint
    if start:
        try:
            start_dt = datetime.fromisoformat(start)
            clauses.append("created_at >= :start_dt")
            params["start_dt"] = start_dt
        except Exception:
            pass
    if end:
        try:
            end_dt = datetime.fromisoformat(end) + timedelta(days=1)
            clauses.append("created_at < :end_dt")
            params["end_dt"] = end_dt
        except Exception:
            pass
    where_sql = " AND ".join(clauses)
    query = text(
        f"""
        SELECT l.id, l.created_at, l.touchpoint, l.user_id, l.model, l.duration_ms,
               l.template_state, l.template_version, l.response_preview,
               u.first_name, u.surname, u.phone
        FROM llm_prompt_logs_view l
        LEFT JOIN users u ON u.id = l.user_id
        WHERE {where_sql}
        ORDER BY created_at DESC
        LIMIT :limit
        """
    )
    with SessionLocal() as s:
        rows = s.execute(query, params).mappings().all()
    items = []
    for row in rows:
        item = dict(row)
        name = " ".join([str(item.get("first_name") or "").strip(), str(item.get("surname") or "").strip()]).strip()
        item["user_name"] = name or None
        items.append(item)
    return {"items": items}


@admin.get("/prompts/history/{log_id}")
def admin_prompt_history_detail(log_id: int, admin_user: User = Depends(_require_admin)):
    from .prompts import _ensure_llm_prompt_log_schema

    _ensure_llm_prompt_log_schema()
    podcast_type_map = {
        "podcast_kickoff": "kickoff",
        "podcast_weekstart": "monday",
        "podcast_thursday": "thursday",
        "podcast_friday": "friday",
    }
    query = text(
        """
        SELECT l.*, u.first_name, u.surname, u.phone
        FROM llm_prompt_logs_view l
        LEFT JOIN users u ON u.id = l.user_id
        WHERE l.id = :log_id
        LIMIT 1
        """
    )
    with SessionLocal() as s:
        row = s.execute(query, {"log_id": int(log_id)}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="prompt log not found")
    item = dict(row)
    name = " ".join([str(item.get("first_name") or "").strip(), str(item.get("surname") or "").strip()]).strip()
    item["user_name"] = name or None
    audio_url = None
    touchpoint = (item.get("touchpoint") or "").lower()
    user_id = item.get("user_id")
    if touchpoint.startswith("podcast_") and user_id:
        tp_type = podcast_type_map.get(touchpoint)
        if not tp_type:
            tp_type = touchpoint.replace("podcast_", "", 1) or None
        context_meta = item.get("context_meta")
        if isinstance(context_meta, str):
            try:
                context_meta = json.loads(context_meta)
            except Exception:
                context_meta = None
        week_no = None
        if isinstance(context_meta, dict) and context_meta.get("week_no") is not None:
            try:
                week_no = int(context_meta.get("week_no"))
            except Exception:
                week_no = None
        if tp_type:
            with SessionLocal() as s:
                tp_query = (
                    s.query(Touchpoint)
                    .filter(Touchpoint.user_id == int(user_id))
                    .filter(Touchpoint.type == tp_type)
                )
                if week_no is not None:
                    tp_query = tp_query.filter(Touchpoint.week_no == week_no)
                tp_ts = func.coalesce(Touchpoint.sent_at, Touchpoint.created_at)
                tp = tp_query.order_by(desc(tp_ts)).first()
                audio_url = tp.audio_url if tp else None
    item["audio_url"] = audio_url
    return item


@admin.get("/touchpoints/history")
def admin_touchpoint_history(
    limit: int = 50,
    user_id: int | None = None,
    touchpoint: str | None = None,
    start: str | None = None,
    end: str | None = None,
    admin_user: User = Depends(_require_admin),
):
    """
    Return a merged list of touchpoints + message logs across users.
    Filters: date range, user_id, touchpoint type.
    """
    max_limit = max(1, min(int(limit), 200))
    club_scope_id = getattr(admin_user, "club_id", None)

    def _parse_dt(raw: str | None, is_end: bool = False) -> datetime | None:
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
            if is_end:
                dt = dt + timedelta(days=1)
            return dt
        except Exception:
            return None

    start_dt = _parse_dt(start)
    end_dt = _parse_dt(end, is_end=True)

    with SessionLocal() as s:
        tp_query = s.query(Touchpoint)
        if club_scope_id is not None:
            tp_query = tp_query.join(User, Touchpoint.user_id == User.id).filter(User.club_id == club_scope_id)
        if user_id:
            tp_query = tp_query.filter(Touchpoint.user_id == int(user_id))
        if touchpoint:
            tp_query = tp_query.filter(Touchpoint.type == touchpoint)
        tp_ts = func.coalesce(Touchpoint.sent_at, Touchpoint.created_at)
        if start_dt:
            tp_query = tp_query.filter(tp_ts >= start_dt)
        if end_dt:
            tp_query = tp_query.filter(tp_ts < end_dt)
        touchpoints = (
            tp_query.order_by(desc(tp_ts)).limit(max_limit * 2).all()
        )

        msg_query = s.query(MessageLog)
        if club_scope_id is not None:
            msg_query = msg_query.join(User, MessageLog.user_id == User.id).filter(User.club_id == club_scope_id)
        if user_id:
            msg_query = msg_query.filter(MessageLog.user_id == int(user_id))
        if start_dt:
            msg_query = msg_query.filter(MessageLog.created_at >= start_dt)
        if end_dt:
            msg_query = msg_query.filter(MessageLog.created_at < end_dt)
        messages = msg_query.order_by(desc(MessageLog.created_at)).limit(max_limit * 2).all()

        user_ids = {tp.user_id for tp in touchpoints if tp.user_id} | {m.user_id for m in messages if m.user_id}
        user_map: dict[int, User] = {}
        if user_ids:
            rows = s.execute(select(User).where(User.id.in_(list(user_ids)))).scalars().all()
            user_map = {u.id: u for u in rows if u}

    def _preview(text: str | None) -> str:
        if not text:
            return ""
        cleaned = " ".join(str(text).split())
        return cleaned[:180] + ("…" if len(cleaned) > 180 else "")

    def _is_truncated(text: str | None) -> bool:
        if not text:
            return False
        cleaned = " ".join(str(text).split())
        return len(cleaned) > 180

    items: list[dict[str, object]] = []
    for tp in touchpoints:
        ts = tp.sent_at or tp.created_at
        user = user_map.get(tp.user_id) if tp.user_id else None
        name = " ".join([str(getattr(user, "first_name", "") or "").strip(), str(getattr(user, "surname", "") or "").strip()]).strip()
        items.append(
            {
                "id": tp.id,
                "kind": "touchpoint",
                "ts": ts.isoformat() if ts else None,
                "touchpoint_type": tp.type,
                "week_no": tp.week_no,
                "channel": tp.channel,
                "audio_url": tp.audio_url,
                "preview": _preview(tp.generated_text),
                "full_text": (tp.generated_text or "").strip(),
                "is_truncated": _is_truncated(tp.generated_text),
                "user_id": tp.user_id,
                "user_name": name or None,
                "phone": getattr(user, "phone", None) if user else None,
            }
        )
    for msg in messages:
        user = user_map.get(msg.user_id) if msg.user_id else None
        name = " ".join([str(getattr(user, "first_name", "") or "").strip(), str(getattr(user, "surname", "") or "").strip()]).strip()
        items.append(
            {
                "id": msg.id,
                "kind": "message",
                "ts": msg.created_at.isoformat() if msg.created_at else None,
                "direction": msg.direction,
                "channel": msg.channel,
                "preview": _preview(msg.text),
                "full_text": (msg.text or "").strip(),
                "is_truncated": _is_truncated(msg.text),
                "user_id": msg.user_id,
                "user_name": name or None,
                "phone": getattr(user, "phone", None) if user else None,
            }
        )

    items.sort(key=lambda r: r.get("ts") or "", reverse=True)
    items = items[:max_limit]

    return {"items": items}

@admin.post("/prompts/settings")
def admin_prompt_settings_update(
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    ensure_prompt_settings_schema()
    block_order = [b for b in _parse_block_list(payload.get("default_block_order")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]

    def _parse_override(val):
        if val is None:
            return None
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str):
            cleaned = val.strip().lower()
            if cleaned in {"", "null"}:
                return None
            if cleaned in {"on", "true", "1", "yes"}:
                return True
            if cleaned in {"off", "false", "0", "no"}:
                return False
        return None
    with SessionLocal() as s:
        row = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()
        if not row:
            row = PromptSettings()
            s.add(row)
        if "system_block" in payload:
            row.system_block = payload.get("system_block") or None
        if "locale_block" in payload:
            row.locale_block = payload.get("locale_block") or None
        if block_order:
            row.default_block_order = block_order
        if "worker_mode_override" in payload:
            row.worker_mode_override = _parse_override(payload.get("worker_mode_override"))
        if "podcast_worker_mode_override" in payload:
            row.podcast_worker_mode_override = _parse_override(payload.get("podcast_worker_mode_override"))
        s.commit()
    return {"ok": True}


@admin.get("/worker/status")
def admin_worker_status(admin_user: User = Depends(_require_admin)):
    admin_routes._ensure_prompt_template_table()  # type: ignore[attr-defined]
    ensure_prompt_settings_schema()

    def _env_flag(name: str) -> bool:
        return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes"}

    with SessionLocal() as s:
        row = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()
    worker_override = getattr(row, "worker_mode_override", None) if row else None
    podcast_override = getattr(row, "podcast_worker_mode_override", None) if row else None
    env_worker = _env_flag("PROMPT_WORKER_MODE")
    env_podcast = _env_flag("PODCAST_WORKER_MODE")
    effective_worker = worker_override if worker_override is not None else env_worker
    if effective_worker is False:
        effective_podcast = False
        podcast_source = "disabled_by_worker"
    else:
        effective_podcast = podcast_override if podcast_override is not None else env_podcast
        podcast_source = "override" if podcast_override is not None else "env"
    return {
        "worker_mode_override": worker_override,
        "podcast_worker_mode_override": podcast_override,
        "worker_mode_env": env_worker,
        "podcast_worker_mode_env": env_podcast,
        "worker_mode_effective": effective_worker,
        "podcast_worker_mode_effective": effective_podcast,
        "worker_mode_source": "override" if worker_override is not None else "env",
        "podcast_worker_mode_source": podcast_source,
    }


@admin.get("/messaging/templates")
def admin_list_twilio_templates(admin_user: User = Depends(_require_admin)):
    try:
        from .nudges import _ensure_twilio_templates_table  # type: ignore
        _ensure_twilio_templates_table()
    except Exception:
        pass
    with SessionLocal() as s:
        rows = s.query(TwilioTemplate).order_by(TwilioTemplate.template_type.asc(), TwilioTemplate.button_count.asc()).all()
        if not rows:
            defaults = [
                TwilioTemplate(
                    provider="twilio",
                    template_type="quick-reply",
                    button_count=2,
                    friendly_name=os.getenv("TWILIO_QR_TEMPLATE_NAME_2", "hs_qr_2"),
                    status="missing",
                    language="en",
                    payload={"button_count": 2},
                ),
                TwilioTemplate(
                    provider="twilio",
                    template_type="quick-reply",
                    button_count=3,
                    friendly_name=os.getenv("TWILIO_QR_TEMPLATE_NAME_3", "hs_qr_3"),
                    status="missing",
                    language="en",
                    payload={"button_count": 3},
                ),
                TwilioTemplate(
                    provider="twilio",
                    template_type="session-reopen",
                    button_count=None,
                    friendly_name=os.getenv("TWILIO_REOPEN_TEMPLATE_NAME", "hs_reopen"),
                    status="missing",
                    language="en",
                    payload={"purpose": "session-reopen"},
                ),
            ]
            s.add_all(defaults)
            s.commit()
            rows = s.query(TwilioTemplate).order_by(TwilioTemplate.template_type.asc(), TwilioTemplate.button_count.asc()).all()
    items = []
    for row in rows:
        content_types = []
        if row.sid:
            try:
                from .nudges import get_twilio_content_types  # type: ignore
                content_types = get_twilio_content_types(row.sid)
            except Exception:
                content_types = []
        items.append(
            {
                "id": row.id,
                "provider": row.provider,
                "template_type": row.template_type,
                "button_count": row.button_count,
                "friendly_name": row.friendly_name,
                "sid": row.sid,
                "language": row.language,
                "status": row.status,
                "payload": row.payload,
                "last_synced_at": row.last_synced_at.isoformat() if row.last_synced_at else None,
                "content_types": content_types,
            }
        )
    return {"templates": items}


@admin.post("/messaging/templates")
def admin_update_twilio_templates(payload: dict, admin_user: User = Depends(_require_admin)):
    items = payload.get("templates") if isinstance(payload, dict) else None
    if not items:
        items = [payload]
    updated = []
    with SessionLocal() as s:
        for item in items:
            if not isinstance(item, dict):
                continue
            row = None
            row_id = item.get("id")
            if row_id:
                row = s.query(TwilioTemplate).get(row_id)
            template_type = (item.get("template_type") or "").strip() or None
            button_count = item.get("button_count")
            if row is None and template_type:
                q = s.query(TwilioTemplate).filter(
                    TwilioTemplate.provider == "twilio",
                    TwilioTemplate.template_type == template_type,
                )
                if button_count is None:
                    q = q.filter(TwilioTemplate.button_count.is_(None))
                else:
                    q = q.filter(TwilioTemplate.button_count == int(button_count))
                row = q.first()
            if row is None:
                row = TwilioTemplate(
                    provider="twilio",
                    template_type=template_type or "quick-reply",
                    button_count=int(button_count) if button_count is not None else None,
                )
            if "friendly_name" in item:
                row.friendly_name = item.get("friendly_name") or row.friendly_name
            if "sid" in item:
                row.sid = item.get("sid") or None
            if "status" in item:
                row.status = item.get("status") or row.status
            if "language" in item:
                row.language = item.get("language") or row.language
            row.last_synced_at = datetime.utcnow()
            s.add(row)
            s.commit()
            updated.append(row.id)
    return {"ok": True, "updated": updated}


@admin.post("/messaging/templates/delete")
def admin_delete_twilio_template(payload: dict, admin_user: User = Depends(_require_admin)):
    template_id = payload.get("id")
    if not template_id:
        raise HTTPException(status_code=400, detail="template id required")
    delete_remote = bool(payload.get("delete_remote", True))
    deleted = False
    remote_deleted = None
    with SessionLocal() as s:
        row = s.query(TwilioTemplate).get(int(template_id))
        if not row:
            raise HTTPException(status_code=404, detail="template not found")
        sid = row.sid
        if delete_remote and sid:
            try:
                from .nudges import _delete_content_detail  # type: ignore
                remote_deleted = _delete_content_detail(sid)
            except Exception:
                remote_deleted = False
        s.delete(row)
        s.commit()
        deleted = True
    return {"ok": deleted, "remote_deleted": remote_deleted}


def _ensure_messaging_settings_table() -> None:
    try:
        MessagingSettings.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass


@admin.get("/messaging/settings")
def admin_get_messaging_settings(admin_user: User = Depends(_require_admin)):
    _ensure_messaging_settings_table()
    with SessionLocal() as s:
        row = s.query(MessagingSettings).order_by(MessagingSettings.id.asc()).first()
        if not row:
            return {
                "out_of_session_enabled": False,
                "out_of_session_message": None,
            }
        return {
            "out_of_session_enabled": bool(row.out_of_session_enabled),
            "out_of_session_message": row.out_of_session_message,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }


@admin.post("/messaging/settings")
def admin_update_messaging_settings(payload: dict, admin_user: User = Depends(_require_admin)):
    _ensure_messaging_settings_table()
    enabled = bool(payload.get("out_of_session_enabled"))
    message = payload.get("out_of_session_message")
    with SessionLocal() as s:
        row = s.query(MessagingSettings).order_by(MessagingSettings.id.asc()).first()
        if not row:
            row = MessagingSettings()
            s.add(row)
        row.out_of_session_enabled = enabled
        row.out_of_session_message = message or None
        s.commit()
    return {"ok": True}


@admin.get("/profile")
def admin_get_profile(admin_user: User = Depends(_require_admin)):
    return {
        "user": {
            "id": admin_user.id,
            "display_name": display_full_name(admin_user),
            "phone": admin_user.phone,
        }
    }


@admin.post("/messaging/templates/sync")
def admin_sync_twilio_templates(admin_user: User = Depends(_require_admin)):
    try:
        from .nudges import ensure_quick_reply_templates
        ensure_quick_reply_templates(always_log=False)
    except Exception:
        pass
    return admin_list_twilio_templates(admin_user)


@admin.get("/messaging/schedule")
def admin_get_global_schedule(admin_user: User = Depends(_require_admin)):
    try:
        scheduler.ensure_global_schedule_defaults()
    except Exception:
        pass
    with SessionLocal() as s:
        rows = s.query(GlobalPromptSchedule).order_by(GlobalPromptSchedule.day_key.asc()).all()
    items = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "day_key": row.day_key,
                "time_local": row.time_local,
                "enabled": bool(row.enabled),
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
        )
    return {"items": items}


@admin.post("/messaging/schedule")
def admin_update_global_schedule(payload: dict, admin_user: User = Depends(_require_admin)):
    items = payload.get("items") if isinstance(payload, dict) else None
    if not items:
        raise HTTPException(status_code=400, detail="items required")
    valid_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
    with SessionLocal() as s:
        for item in items:
            if not isinstance(item, dict):
                continue
            day_key = (item.get("day_key") or "").strip().lower()
            if day_key not in valid_days:
                continue
            row = (
                s.query(GlobalPromptSchedule)
                .filter(GlobalPromptSchedule.day_key == day_key)
                .first()
            )
            if not row:
                row = GlobalPromptSchedule(day_key=day_key)
            if "time_local" in item:
                time_val = (item.get("time_local") or "").strip()
                if time_val:
                    try:
                        hh, mm = time_val.split(":")
                        hh_i = int(hh); mm_i = int(mm)
                        if not (0 <= hh_i <= 23 and 0 <= mm_i <= 59):
                            raise ValueError()
                        time_val = f"{hh_i:02d}:{mm_i:02d}"
                    except Exception:
                        raise HTTPException(status_code=400, detail=f"invalid time for {day_key}: {time_val}")
                    row.time_local = time_val
                else:
                    row.time_local = None
            if "enabled" in item:
                row.enabled = bool(item.get("enabled"))
            s.add(row)
        s.commit()
    try:
        scheduler.schedule_auto_daily_prompts()
    except Exception:
        pass
    return {"ok": True}


@admin.get("/content/settings")
def admin_content_prompt_settings(admin_user: User = Depends(_require_admin)):
    with SessionLocal() as s:
        row = s.query(ContentPromptSettings).order_by(ContentPromptSettings.id.asc()).first()
    if not row:
        return {
            "system_block": None,
            "locale_block": None,
            "default_block_order": ["system", "locale", "context", "task"],
        }
    order = [b for b in (row.default_block_order or ["system", "locale", "context", "task"]) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    return {
        "system_block": getattr(row, "system_block", None),
        "locale_block": getattr(row, "locale_block", None),
        "default_block_order": order,
    }


@admin.post("/content/settings")
def admin_content_prompt_settings_update(payload: dict, admin_user: User = Depends(_require_admin)):
    block_order = [b for b in _parse_block_list(payload.get("default_block_order")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    with SessionLocal() as s:
        row = s.query(ContentPromptSettings).order_by(ContentPromptSettings.id.asc()).first()
        if not row:
            row = ContentPromptSettings()
            s.add(row)
        if "system_block" in payload:
            row.system_block = payload.get("system_block") or None
        if "locale_block" in payload:
            row.locale_block = payload.get("locale_block") or None
        if block_order:
            row.default_block_order = block_order
        s.commit()
    return {"ok": True}


@admin.get("/content/templates")
def admin_content_prompt_templates_list(
    state: str | None = None,
    pillar: str | None = None,
    concept: str | None = None,
    q: str | None = None,
    limit: int = 200,
    admin_user: User = Depends(_require_admin),
):
    try:
        limit = int(limit)
    except Exception:
        limit = 200
    limit = max(1, min(limit, 400))
    with SessionLocal() as s:
        query = s.query(ContentPromptTemplate)
        if pillar:
            query = query.filter(ContentPromptTemplate.pillar_key == pillar)
        if concept:
            query = query.filter(ContentPromptTemplate.concept_code == concept)
        if q:
            like = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    ContentPromptTemplate.template_key.ilike(like),
                    ContentPromptTemplate.label.ilike(like),
                )
            )
        rows = (
            query.order_by(ContentPromptTemplate.template_key.asc(), ContentPromptTemplate.version.desc(), ContentPromptTemplate.id.desc())
            .limit(limit)
            .all()
        )
    items = []
    for row in rows:
        items.append(
            {
                "id": row.id,
                "template_key": row.template_key,
                "label": row.label,
                "pillar_key": row.pillar_key,
                "concept_code": row.concept_code,
                "state": getattr(row, "state", None),
                "version": row.version,
                "is_active": bool(getattr(row, "is_active", True)),
                "response_format": getattr(row, "response_format", None),
                "note": getattr(row, "note", None),
                "updated_at": getattr(row, "updated_at", None),
            }
        )
    return {"count": len(items), "templates": items}


@admin.get("/content/templates/{template_id}")
def admin_content_prompt_template_detail(
    template_id: int,
    admin_user: User = Depends(_require_admin),
):
    with SessionLocal() as s:
        row = s.get(ContentPromptTemplate, template_id)
        if not row:
            raise HTTPException(status_code=404, detail="content template not found")
    return {
        "id": row.id,
        "template_key": row.template_key,
        "label": row.label,
        "pillar_key": row.pillar_key,
        "concept_code": row.concept_code,
        "state": getattr(row, "state", None),
        "version": row.version,
        "is_active": bool(getattr(row, "is_active", True)),
        "response_format": getattr(row, "response_format", None),
        "block_order": getattr(row, "block_order", None),
        "include_blocks": getattr(row, "include_blocks", None),
        "task_block": getattr(row, "task_block", None),
        "note": getattr(row, "note", None),
        "updated_at": getattr(row, "updated_at", None),
    }


@admin.post("/content/templates")
def admin_content_prompt_template_create(
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    template_key = str(payload.get("template_key") or "").strip()
    if not template_key:
        raise HTTPException(status_code=400, detail="template_key required")
    block_order = [b for b in _parse_block_list(payload.get("block_order")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    include_blocks = [b for b in _parse_block_list(payload.get("include_blocks")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    if not include_blocks and block_order:
        include_blocks = list(block_order)
    with SessionLocal() as s:
        row = ContentPromptTemplate(template_key=template_key)
        row.label = (payload.get("label") or None) or None
        row.pillar_key = (payload.get("pillar_key") or None) or None
        row.concept_code = (payload.get("concept_code") or None) or None
        row.state = "published"
        row.version = 1
        row.response_format = (payload.get("response_format") or None) or None
        row.block_order = block_order or None
        row.include_blocks = include_blocks or block_order or None
        row.task_block = (payload.get("task_block") or None) or None
        row.note = (payload.get("note") or None) or None
        row.is_active = bool(payload.get("is_active", True))
        s.add(row)
        s.commit()
        s.refresh(row)
    return {"id": row.id, "template_key": row.template_key}


@admin.post("/content/templates/{template_id}")
def admin_content_prompt_template_update(
    template_id: int,
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    block_order = [b for b in _parse_block_list(payload.get("block_order")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    include_blocks = [b for b in _parse_block_list(payload.get("include_blocks")) if b not in admin_routes.BANNED_BLOCKS]  # type: ignore[attr-defined]
    if not include_blocks and block_order:
        include_blocks = list(block_order)
    with SessionLocal() as s:
        row = s.get(ContentPromptTemplate, template_id)
        if not row:
            raise HTTPException(status_code=404, detail="content template not found")
        if "label" in payload:
            row.label = payload.get("label") or None
        if "pillar_key" in payload:
            row.pillar_key = payload.get("pillar_key") or None
        if "concept_code" in payload:
            row.concept_code = payload.get("concept_code") or None
        if "response_format" in payload:
            row.response_format = payload.get("response_format") or None
        if "task_block" in payload:
            row.task_block = payload.get("task_block") or None
        if "note" in payload:
            row.note = payload.get("note") or None
        if "is_active" in payload:
            row.is_active = bool(payload.get("is_active"))
        if block_order or include_blocks:
            row.block_order = block_order or None
            row.include_blocks = include_blocks or block_order or None
        s.commit()
    return {"ok": True}


@admin.post("/content/templates/{template_id}/promote")
def admin_content_prompt_template_promote(
    template_id: int,
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    to_state = prompts_module._canonical_state(payload.get("to_state") or "")
    if to_state not in {"beta", "live"}:
        raise HTTPException(status_code=400, detail="to_state must be beta or live")
    note = (payload.get("note") or "").strip() or None
    with SessionLocal() as s:
        row = s.get(ContentPromptTemplate, template_id)
        if not row:
            raise HTTPException(status_code=404, detail="content template not found")
        max_version = (
            s.query(func.max(ContentPromptTemplate.version))
            .filter(
                ContentPromptTemplate.template_key == row.template_key,
                ContentPromptTemplate.state.in_([to_state, "stage" if to_state == "beta" else to_state, "production" if to_state == "live" else to_state]),
            )
            .scalar()
            or 0
        )
        new_row = ContentPromptTemplate(
            template_key=row.template_key,
            label=row.label,
            pillar_key=row.pillar_key,
            concept_code=row.concept_code,
            state=to_state,
            version=max_version + 1,
            note=note or row.note,
            task_block=row.task_block,
            block_order=row.block_order,
            include_blocks=row.include_blocks,
            response_format=row.response_format,
            is_active=True,
            parent_id=row.id,
        )
        s.add(new_row)
        s.commit()
    return {"ok": True, "id": new_row.id, "state": to_state, "version": new_row.version}


def _build_prompt_test_payload(
    touchpoint: str,
    user: User,
    user_id_int: int,
    state: str,
    test_date: str | None,
    run_llm: bool,
    model_override: str | None,
) -> dict:
    tp_lower = touchpoint.lower()

    def _assembly_to_payload(assembly, llm_result: dict | None = None):
        data = {
            "text": assembly.text,
            "blocks": assembly.blocks,
            "block_order": assembly.block_order or list(assembly.blocks.keys()),
            "meta": getattr(assembly, "meta", {}) or {},
        }
        if llm_result:
            data["llm"] = llm_result
        return data

    def _maybe_run_llm(assembly):
        if not run_llm:
            return None
        try:
            from . import llm as shared_llm
            template_model = ""
            meta = getattr(assembly, "meta", None)
            if isinstance(meta, dict):
                template_model = str(meta.get("template_model_override") or meta.get("model_override") or "").strip()
            effective_model = (model_override or "").strip() or template_model or None
            t0 = time.perf_counter()
            resolved_model = shared_llm.resolve_model_name_for_touchpoint(
                touchpoint=touchpoint,
                model_override=effective_model,
            )
            client = shared_llm.get_llm_client(
                touchpoint=touchpoint,
                model_override=effective_model,
            )
            resp = client.invoke(assembly.text)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            content = (getattr(resp, "content", "") or "").strip()
            return {
                "model": resolved_model,
                "duration_ms": duration_ms,
                "content": content,
            }
        except Exception as e:
            return {"error": str(e)}

    try:
        if tp_lower == "assessment_scores":
            run, pillars = kickoff._latest_assessment(user_id_int)
            combined = int(getattr(run, "combined_overall", 0) or 0) if run else 0
            scores_payload = [
                {"pillar": getattr(p, "pillar_key", ""), "score": int(getattr(p, "overall", 0) or 0)}
                for p in (pillars or [])
            ]
            assembly = assessment_scores_prompt(display_full_name(user), combined, scores_payload)
            return _assembly_to_payload(assembly, _maybe_run_llm(assembly))
        if tp_lower in {"assessment_okr", "okr_narrative"}:
            run = None
            with SessionLocal() as s:
                run = (
                    s.execute(
                        select(AssessmentRun).where(AssessmentRun.user_id == user_id_int).order_by(desc(AssessmentRun.id))
                    )
                    .scalars()
                    .first()
                )
            if not run:
                raise HTTPException(status_code=404, detail="assessment run not found")
            data = build_assessment_dashboard_data(run.id, include_llm=False)
            okrs = data.get("okrs") or []
            assembly = okr_narrative_prompt(display_full_name(user), okrs)
            return _assembly_to_payload(assembly, _maybe_run_llm(assembly))
        if tp_lower in {"assessment_approach", "coaching_approach"}:
            psych = kickoff._latest_psych(user_id_int)
            section_averages = getattr(psych, "section_averages", None) or {}
            flags = getattr(psych, "flags", None) or {}
            parameters = getattr(psych, "parameters", None) or {}
            assembly = coaching_approach_prompt(display_full_name(user), section_averages, flags, parameters)
            return _assembly_to_payload(assembly, _maybe_run_llm(assembly))
        if tp_lower == "assessor_system":
            sys_text = assessor_system_prompt("nutrition", "fruit_veg")
            settings = prompts_module._load_prompt_settings()
            template = prompts_module._load_prompt_template("assessor_system")
            parts = [
                ("system", settings.get("system_block") or prompts_module.common_prompt_header("Assessor", "User", "UK")),
                ("locale", settings.get("locale_block") or prompts_module.locale_block("UK")),
                ("context", "assessor system placeholder"),
                ("assessor", sys_text),
                ("task", "(task from template)"),
                ("user", "(user input)"),
            ]
            parts, order_override = prompts_module._apply_prompt_template(parts, template)
            blocks = {lbl: txt for lbl, txt in parts if txt}
            text = prompts_module.assemble_prompt([txt for _, txt in parts if txt])
            meta = {}
            if isinstance(template, dict):
                model_val = str(template.get("model_override") or "").strip()
                if model_val:
                    meta["template_model_override"] = model_val
            result = {
                "text": text,
                "blocks": blocks,
                "block_order": order_override or settings.get("default_block_order") or list(blocks.keys()),
                "meta": meta,
            }
            llm_result = _maybe_run_llm(
                SimpleNamespace(
                    text=text,
                    blocks=blocks,
                    block_order=order_override or settings.get("default_block_order"),
                    meta=meta,
                )
            )
            if llm_result:
                result["llm"] = llm_result
            return result
        # Default: build standard coaching prompt
        assembly = build_prompt(
            touchpoint=touchpoint,
            user_id=user_id_int,
            coach_name="Coach",
            user_name=display_full_name(user),
            locale="UK",
            use_state=state,
            as_of_date=test_date,
        )
        return _assembly_to_payload(assembly, _maybe_run_llm(assembly))
    except ValueError as e:
        if "Unsupported touchpoint" in str(e):
            settings = prompts_module._load_prompt_settings()
            template = prompts_module._load_prompt_template_with_state(touchpoint, state)
            sys_block = settings.get("system_block") or prompts_module.common_prompt_header("Coach", display_full_name(user), "UK")
            loc_block = settings.get("locale_block") or prompts_module.locale_block("UK")
            parts = [
                ("system", sys_block),
                ("locale", loc_block),
                ("context", "(runtime context placeholder)"),
                ("programme", "(programme block placeholder)"),
                ("history", "(history placeholder)"),
                ("okr", "(okr placeholder)"),
                ("scores", "(scores placeholder)"),
                ("habit", "(habit readiness placeholder)"),
                ("task", (template or {}).get("task_block") or "(task block)"),
                ("user", "(user input)"),
            ]
            parts, order_override = prompts_module._apply_prompt_template(parts, template)
            blocks = {lbl: txt for lbl, txt in parts if txt}
            text = prompts_module.assemble_prompt([txt for _, txt in parts if txt])
            result = {
                "text": text,
                "blocks": blocks,
                "block_order": order_override or settings.get("default_block_order") or list(blocks.keys()),
                "meta": {},
            }
            llm_result = _maybe_run_llm(SimpleNamespace(text=text, blocks=blocks, block_order=order_override or settings.get("default_block_order"), meta={}))
            if llm_result:
                result["llm"] = llm_result
            return result
        raise


@admin.post("/prompts/test")
def admin_prompt_test(payload: dict, admin_user: User = Depends(_require_admin)):
    touchpoint = str(payload.get("touchpoint") or "").strip()
    user_id = payload.get("user_id")
    if not touchpoint or not user_id:
        raise HTTPException(status_code=400, detail="touchpoint and user_id required")
    try:
        user_id_int = int(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="user_id must be an integer")
    state = (payload.get("state") or "published").strip().lower()
    test_date = payload.get("test_date")
    run_llm = bool(payload.get("run_llm"))
    model_override = (payload.get("model_override") or "").strip() or None
    generate_podcast = bool(payload.get("generate_podcast"))
    podcast_voice = (payload.get("podcast_voice") or "").strip() or None
    if generate_podcast and not run_llm:
        raise HTTPException(status_code=400, detail="run_llm must be enabled to generate podcast audio")
    with SessionLocal() as s:
        user = s.execute(select(User).where(User.id == user_id_int)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="user not found")
    result = _build_prompt_test_payload(
        touchpoint=touchpoint,
        user=user,
        user_id_int=user_id_int,
        state=state,
        test_date=test_date,
        run_llm=run_llm,
        model_override=model_override,
    )
    if generate_podcast:
        llm = (result or {}).get("llm") or {}
        content = (llm.get("content") or "").strip() if isinstance(llm, dict) else ""
        if not content:
            result["podcast_error"] = "LLM content is required to generate podcast audio."
        else:
            filename = f"prompt-test-{touchpoint}-{user_id_int}.mp3"
            try:
                audio_url = generate_podcast_audio_for_voice(
                    transcript=content,
                    user_id=user_id_int,
                    filename=filename,
                    voice_override=podcast_voice,
                    usage_tag="prompt_test",
                )
                if audio_url:
                    result["audio_url"] = audio_url
                else:
                    result["podcast_error"] = "Podcast audio generation failed."
            except Exception as e:
                result["podcast_error"] = str(e)
    return result

def _load_content_prompt_settings() -> dict:
    with SessionLocal() as s:
        row = s.query(ContentPromptSettings).order_by(ContentPromptSettings.id.asc()).first()
        if not row:
            return {
                "system_block": "",
                "locale_block": "",
                "default_block_order": ["system", "locale", "context", "task"],
            }
        return {
            "system_block": row.system_block or "",
            "locale_block": row.locale_block or "",
            "default_block_order": row.default_block_order or ["system", "locale", "context", "task"],
        }

def _build_content_prompt_payload(
    *,
    template: ContentPromptTemplate,
    pillar_key: str | None,
    concept_code: str | None,
    run_llm: bool,
    provider: str | None,
    model_override: str | None,
) -> dict:
    settings = _load_content_prompt_settings()
    system_block = settings.get("system_block") or prompts_module.common_prompt_header("Coach", "User", "UK")
    locale_block = settings.get("locale_block") or prompts_module.locale_block("UK")
    context_bits = ["Library content generation"]
    if pillar_key:
        context_bits.append(f"Pillar: {pillar_key}")
    if concept_code:
        context_bits.append(f"Concept: {concept_code}")
    context_block = " | ".join(context_bits)
    task_block = template.task_block or "Write a concise, practical coaching snippet for the specified pillar."

    parts = [
        ("system", system_block),
        ("locale", locale_block),
        ("context", context_block),
        ("task", task_block),
    ]
    template_payload = {
        "block_order": template.block_order,
        "include_blocks": template.include_blocks,
        "task_block": template.task_block,
    }
    parts, order_override = prompts_module._apply_prompt_template(parts, template_payload)
    has_task = any(lbl == "task" for lbl, _ in parts)
    if task_block and not has_task:
        parts.append(("task", task_block))
        has_task = True
    blocks = {lbl: txt for lbl, txt in parts if txt}
    text = prompts_module.assemble_prompt([txt for _, txt in parts if txt])
    block_order = order_override or settings.get("default_block_order") or list(blocks.keys())
    if "task" in blocks and "task" not in block_order:
        block_order = list(block_order) + ["task"]
    result = {
        "text": text,
        "blocks": blocks,
        "block_order": block_order,
        "meta": {
            "template_key": template.template_key,
            "template_state": template.state,
            "template_version": template.version,
            "pillar_key": pillar_key,
            "concept_code": concept_code,
            "provider": provider or "openai",
        },
    }

    if run_llm:
        if provider and provider != "openai":
            result["llm"] = {"error": f"provider '{provider}' not supported"}
            return result
        llm_result = None
        try:
            from . import llm as shared_llm
            t0 = time.perf_counter()
            resolved_model = shared_llm.resolve_model_name_for_touchpoint(
                touchpoint=template.template_key,
                model_override=model_override,
            )
            client = shared_llm.get_llm_client(
                touchpoint=template.template_key,
                model_override=model_override,
            )
            resp = client.invoke(text)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            content = (getattr(resp, "content", "") or "").strip()
            llm_result = {
                "model": resolved_model,
                "duration_ms": duration_ms,
                "content": content,
            }
        except Exception as e:
            llm_result = {"error": str(e)}
        if llm_result:
            result["llm"] = llm_result

    return result

@admin.post("/content/generations")
def admin_content_generation_create(payload: dict, admin_user: User = Depends(_require_admin)):
    template_id = payload.get("template_id")
    template_key = str(payload.get("template_key") or "").strip()
    touchpoint = str(payload.get("touchpoint") or "").strip()
    user_id = payload.get("user_id")
    user_id_int = None
    if user_id is not None and str(user_id).strip() != "":
        try:
            user_id_int = int(user_id)
        except Exception:
            raise HTTPException(status_code=400, detail="user_id must be an integer")
    state = (payload.get("state") or "published").strip().lower()
    pillar_key = (payload.get("pillar_key") or "").strip() or None
    concept_code = (payload.get("concept_code") or "").strip() or None
    provider = (payload.get("provider") or "").strip() or "openai"
    test_date = payload.get("test_date")
    run_llm = bool(payload.get("run_llm"))
    model_override = (payload.get("model_override") or "").strip() or None
    generate_podcast = bool(payload.get("generate_podcast"))
    podcast_voice = (payload.get("podcast_voice") or "").strip() or None
    parsed_date = None
    if test_date:
        try:
            parsed_date = datetime.strptime(str(test_date), "%Y-%m-%d").date()
        except Exception:
            parsed_date = None

    with SessionLocal() as s:
        user = None
        if user_id_int is not None:
            user = s.execute(select(User).where(User.id == user_id_int)).scalar_one_or_none()
            if not user:
                raise HTTPException(status_code=404, detail="user not found")
            _ensure_club_scope(admin_user, user)
        template = None
        if template_id:
            try:
                template_id = int(template_id)
            except Exception:
                template_id = None
        if template_id:
            template = (
                s.query(ContentPromptTemplate)
                .filter(ContentPromptTemplate.id == template_id)
                .one_or_none()
            )
        if not template and template_key:
            template = (
                s.query(ContentPromptTemplate)
                .filter(
                    ContentPromptTemplate.template_key == template_key,
                )
                .order_by(desc(ContentPromptTemplate.version))
                .first()
            )
        if not template:
            raise HTTPException(status_code=404, detail="content prompt template not found")
        state = template.state or None
        resolved_pillar = pillar_key or getattr(template, "pillar_key", None)
        resolved_concept = concept_code or getattr(template, "concept_code", None)
        result = _build_content_prompt_payload(
            template=template,
            pillar_key=resolved_pillar,
            concept_code=resolved_concept,
            run_llm=run_llm,
            provider=provider,
            model_override=model_override,
        )
        llm = result.get("llm") or {}
        status_val = "assembled"
        error_val = None
        if run_llm:
            if llm.get("error"):
                status_val = "error"
                error_val = llm.get("error")
            else:
                status_val = "ok"
        gen = ContentPromptGeneration(
            user_id=user_id_int,
            created_by=getattr(admin_user, "id", None),
            template_id=template.id,
            touchpoint=template.template_key,
            prompt_state=state,
            provider=provider,
            test_date=parsed_date,
            model_override=model_override,
            run_llm=bool(run_llm),
            assembled_prompt=result.get("text"),
            blocks=result.get("blocks"),
            block_order=result.get("block_order"),
            meta=result.get("meta"),
            llm_model=llm.get("model"),
            llm_duration_ms=llm.get("duration_ms"),
            llm_content=llm.get("content"),
            llm_error=llm.get("error"),
            status=status_val,
            error=error_val,
        )
        s.add(gen)
        s.commit()
        s.refresh(gen)
        podcast_url = None
        podcast_error = None
        if generate_podcast:
            if not gen.llm_content:
                podcast_error = "LLM content is required to generate podcast audio."
            else:
                is_intro_generation = str(resolved_pillar or "").strip().lower() == INTRO_PILLAR_KEY
                target_reports_dir = "content/intro" if is_intro_generation else "content/library"
                audio_user_id = gen.user_id or getattr(admin_user, "id", None)
                if not audio_user_id:
                    podcast_error = "No user available for audio generation."
                else:
                    filename = f"content-gen-{gen.id}.mp3"
                    try:
                        tts_result = generate_podcast_audio_for_voice(
                            transcript=gen.llm_content,
                            user_id=int(audio_user_id),
                            filename=filename,
                            voice_override=podcast_voice,
                            return_bytes=True,
                            persist_user_copy=False,
                            usage_tag="content_generation",
                        )
                        generated_audio_bytes = None
                        generated_audio_url = None
                        if isinstance(tts_result, tuple):
                            generated_audio_url, generated_audio_bytes = tts_result
                        elif isinstance(tts_result, str):
                            generated_audio_url = tts_result
                        if generated_audio_bytes:
                            podcast_url = _write_global_report_bytes(
                                f"{target_reports_dir}/{filename}",
                                generated_audio_bytes,
                            )
                        elif generated_audio_url:
                            podcast_url = (
                                _promote_intro_podcast_url(generated_audio_url)
                                if is_intro_generation
                                else _promote_library_podcast_url(generated_audio_url)
                            )
                        else:
                            podcast_error = "Podcast audio generation failed."
                    except Exception as e:
                        podcast_error = str(e)
            if podcast_url or podcast_error:
                gen.podcast_url = podcast_url
                gen.podcast_voice = podcast_voice
                gen.podcast_error = podcast_error
                s.add(gen)
                s.commit()
        return {
            "id": gen.id,
            "touchpoint": gen.touchpoint,
            "user_id": gen.user_id,
            "user_name": display_full_name(user),
            "prompt_state": gen.prompt_state,
            "test_date": gen.test_date,
            "run_llm": gen.run_llm,
            "model_override": gen.model_override,
            "status": gen.status,
            "created_at": gen.created_at,
            "podcast_url": _normalize_reports_url(gen.podcast_url),
            "podcast_voice": gen.podcast_voice,
            "podcast_error": gen.podcast_error,
            "result": result,
        }

@admin.get("/content/generations")
def admin_content_generation_list(
    user_id: int | None = None,
    touchpoint: str | None = None,
    state: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 50,
    admin_user: User = Depends(_require_admin),
):
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    limit = max(1, min(limit, 200))
    touchpoint = (touchpoint or "").strip() or None
    state = (state or "").strip() or None
    start_date = None
    end_date = None
    if start:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
        except Exception:
            start_date = None
    if end:
        try:
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except Exception:
            end_date = None

    with SessionLocal() as s:
        q = s.query(ContentPromptGeneration)
        if user_id:
            q = q.filter(ContentPromptGeneration.user_id == user_id)
        if touchpoint:
            q = q.filter(ContentPromptGeneration.touchpoint == touchpoint)
        if state:
            q = q.filter(ContentPromptGeneration.prompt_state == state)
        if start_date:
            q = q.filter(ContentPromptGeneration.created_at >= datetime.combine(start_date, datetime.min.time()))
        if end_date:
            q = q.filter(ContentPromptGeneration.created_at <= datetime.combine(end_date, datetime.max.time()))
        q = q.order_by(ContentPromptGeneration.id.desc()).limit(limit)
        rows = list(q.all())
        user_ids = {r.user_id for r in rows if r.user_id}
        users = {}
        if user_ids:
            for u in s.execute(select(User).where(User.id.in_(list(user_ids)))).scalars().all():
                users[u.id] = u
    items = []
    for row in rows:
        u = users.get(row.user_id)
        items.append(
            {
                "id": row.id,
                "user_id": row.user_id,
                "user_name": display_full_name(u) if u else None,
                "touchpoint": row.touchpoint,
                "prompt_state": row.prompt_state,
                "test_date": row.test_date,
                "run_llm": row.run_llm,
                "model_override": row.model_override,
                "status": row.status,
                "created_at": row.created_at,
            }
        )
    return {"count": len(items), "items": items}

@admin.get("/content/generations/{generation_id}")
def admin_content_generation_detail(
    generation_id: int,
    admin_user: User = Depends(_require_admin),
):
    with SessionLocal() as s:
        row = s.query(ContentPromptGeneration).filter(ContentPromptGeneration.id == generation_id).one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="generation not found")
        user = s.execute(select(User).where(User.id == row.user_id)).scalar_one_or_none()
        if user:
            _ensure_club_scope(admin_user, user)
    return {
        "id": row.id,
        "user_id": row.user_id,
        "user_name": display_full_name(user) if user else None,
        "touchpoint": row.touchpoint,
        "prompt_state": row.prompt_state,
        "provider": row.provider,
        "test_date": row.test_date,
        "run_llm": row.run_llm,
        "model_override": row.model_override,
        "status": row.status,
        "error": row.error,
        "created_at": row.created_at,
        "assembled_prompt": row.assembled_prompt,
        "blocks": row.blocks,
        "block_order": row.block_order,
        "meta": row.meta,
        "llm_model": row.llm_model,
        "llm_duration_ms": row.llm_duration_ms,
        "llm_content": row.llm_content,
        "llm_error": row.llm_error,
        "podcast_url": _normalize_reports_url(row.podcast_url),
        "podcast_voice": row.podcast_voice,
        "podcast_error": row.podcast_error,
    }


@admin.get("/library/content")
def admin_library_content_list(
    q: str | None = None,
    pillar: str | None = None,
    concept: str | None = None,
    status: str | None = None,
    source: str | None = None,
    limit: int = 200,
    admin_user: User = Depends(_require_admin),
):
    try:
        limit = int(limit)
    except Exception:
        limit = 200
    limit = max(1, min(limit, 500))
    q = (q or "").strip() or None
    pillar = (pillar or "").strip() or None
    concept = (concept or "").strip() or None
    status = (status or "").strip() or None
    source = (source or "").strip() or None

    with SessionLocal() as s:
        qbase = s.query(ContentLibraryItem)
        if pillar:
            qbase = qbase.filter(ContentLibraryItem.pillar_key == pillar)
        if concept:
            qbase = qbase.filter(ContentLibraryItem.concept_code == concept)
        if status:
            qbase = qbase.filter(ContentLibraryItem.status == status)
        if source:
            qbase = qbase.filter(ContentLibraryItem.source_type == source)
        if q:
            like = f"%{q}%"
            qbase = qbase.filter(
                or_(ContentLibraryItem.title.ilike(like), ContentLibraryItem.body.ilike(like))
            )
        rows = (
            qbase.order_by(desc(ContentLibraryItem.created_at), desc(ContentLibraryItem.id))
            .limit(limit)
            .all()
        )
    items = []
    for row in rows:
        preview = row.body or ""
        preview = preview if len(preview) <= 180 else f"{preview[:177]}…"
        items.append(
            {
                "id": row.id,
                "pillar_key": row.pillar_key,
                "concept_code": row.concept_code,
                "title": row.title,
                "status": row.status,
                "text_preview": preview,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "source_generation_id": row.source_generation_id,
                "podcast_url": _normalize_reports_url(row.podcast_url),
                "podcast_voice": row.podcast_voice,
                "source_type": row.source_type,
                "source_url": row.source_url,
                "license": row.license,
                "published_at": row.published_at,
                "level": row.level,
                "tags": row.tags,
            }
        )
    return {"count": len(items), "items": items}


@admin.get("/library/intro")
def admin_library_intro_detail(
    admin_user: User = Depends(_require_admin),
):
    with SessionLocal() as s:
        row = _latest_intro_content_row(s, active_only=False)
        tags = row.tags if isinstance(getattr(row, "tags", None), dict) else {}
        welcome_template = str((tags or {}).get("welcome_message_template") or "").strip()
        return {
            "content_id": int(row.id) if row else None,
            "active": bool(row and str(getattr(row, "status", "") or "").strip().lower() == "published"),
            "title": str(getattr(row, "title", "") or "").strip() or INTRO_TITLE_DEFAULT,
            "welcome_message_template": welcome_template or INTRO_WELCOME_TEMPLATE_DEFAULT,
            "body": _intro_body_from_row(row),
            "podcast_url": _normalize_reports_url(getattr(row, "podcast_url", None)),
            "podcast_voice": getattr(row, "podcast_voice", None),
            "source_type": INTRO_SOURCE_TYPE,
            "updated_at": getattr(row, "updated_at", None),
        }


@admin.post("/library/intro")
def admin_library_intro_update(
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be a JSON object")
    active_raw = payload.get("active")
    if isinstance(active_raw, bool):
        active = active_raw
    elif active_raw is None:
        active = True
    else:
        active = _is_truthy_env(str(active_raw))
    title = str(payload.get("title") or "").strip() or INTRO_TITLE_DEFAULT
    welcome_template = str(payload.get("welcome_message_template") or "").strip() or INTRO_WELCOME_TEMPLATE_DEFAULT
    body = str(payload.get("body") or "").strip() or INTRO_BODY_DEFAULT
    podcast_url = str(payload.get("podcast_url") or "").strip() or None
    podcast_url = _promote_intro_podcast_url(podcast_url)
    podcast_voice = str(payload.get("podcast_voice") or "").strip() or None

    with SessionLocal() as s:
        row = _latest_intro_content_row(s, active_only=False)
        if not row:
            row = ContentLibraryItem(
                pillar_key=INTRO_PILLAR_KEY,
                concept_code=INTRO_CONCEPT_CODE,
                source_type=INTRO_SOURCE_TYPE,
                created_by=getattr(admin_user, "id", None),
            )
            s.add(row)
        tags = row.tags if isinstance(getattr(row, "tags", None), dict) else {}
        tags = dict(tags or {})
        tags["welcome_message_template"] = welcome_template
        row.pillar_key = INTRO_PILLAR_KEY
        row.concept_code = INTRO_CONCEPT_CODE
        row.source_type = INTRO_SOURCE_TYPE
        row.title = title
        row.body = body
        row.podcast_url = podcast_url
        row.podcast_voice = podcast_voice
        row.status = "published" if active else "draft"
        row.tags = tags
        if active and row.published_at is None:
            row.published_at = datetime.utcnow()
        s.commit()
        s.refresh(row)
        return {
            "ok": True,
            "content_id": row.id,
            "active": bool(row.status == "published"),
            "updated_at": row.updated_at,
        }


@admin.get("/library/content/{content_id}")
def admin_library_content_detail(
    content_id: int,
    admin_user: User = Depends(_require_admin),
):
    with SessionLocal() as s:
        row = s.query(ContentLibraryItem).filter(ContentLibraryItem.id == content_id).one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="content not found")
        return {
            "id": row.id,
            "pillar_key": row.pillar_key,
            "concept_code": row.concept_code,
            "title": row.title,
            "body": row.body,
            "status": row.status,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "source_generation_id": row.source_generation_id,
            "podcast_url": _normalize_reports_url(row.podcast_url),
            "podcast_voice": row.podcast_voice,
            "source_type": row.source_type,
            "source_url": row.source_url,
            "license": row.license,
            "published_at": row.published_at,
            "level": row.level,
            "tags": row.tags,
        }


@admin.post("/library/content")
def admin_library_content_create(
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    pillar_key = (payload.get("pillar_key") or "").strip()
    title = (payload.get("title") or "").strip()
    body = (payload.get("body") or "").strip()
    concept_code = (payload.get("concept_code") or "").strip() or None
    status_val = (payload.get("status") or "").strip() or "draft"
    podcast_url = (payload.get("podcast_url") or "").strip() or None
    podcast_url = _promote_library_podcast_url(podcast_url)
    podcast_voice = (payload.get("podcast_voice") or "").strip() or None
    source_type = (payload.get("source_type") or "").strip() or None
    source_url = (payload.get("source_url") or "").strip() or None
    license_val = (payload.get("license") or "").strip() or None
    level_val = (payload.get("level") or "").strip() or None
    published_at_raw = (payload.get("published_at") or "").strip()
    tags_val = payload.get("tags")
    if tags_val is not None and isinstance(tags_val, str):
        tags_val = [t.strip() for t in tags_val.split(",") if t.strip()]
    if not tags_val:
        tags_val = None
    if not pillar_key:
        raise HTTPException(status_code=400, detail="pillar_key required")
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    if not body:
        raise HTTPException(status_code=400, detail="body required")
    source_generation_id = payload.get("source_generation_id")
    try:
        source_generation_id = int(source_generation_id) if source_generation_id else None
    except Exception:
        source_generation_id = None
    published_at = None
    if published_at_raw:
        try:
            published_at = datetime.fromisoformat(published_at_raw)
        except Exception:
            published_at = None
    if not source_type and source_generation_id:
        source_type = "generated"
    with SessionLocal() as s:
        row = ContentLibraryItem(
            pillar_key=pillar_key,
            concept_code=concept_code,
            title=title,
            body=body,
            status=status_val,
            podcast_url=podcast_url,
            podcast_voice=podcast_voice,
            source_type=source_type,
            source_url=source_url,
            license=license_val,
            published_at=published_at,
            level=level_val,
            tags=tags_val,
            source_generation_id=source_generation_id,
            created_by=getattr(admin_user, "id", None),
        )
        s.add(row)
        s.commit()
        s.refresh(row)
    return {"id": row.id}


@admin.post("/library/content/{content_id}")
def admin_library_content_update(
    content_id: int,
    payload: dict,
    admin_user: User = Depends(_require_admin),
):
    with SessionLocal() as s:
        row = s.query(ContentLibraryItem).filter(ContentLibraryItem.id == content_id).one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="content not found")
        if "pillar_key" in payload:
            pillar_key = (payload.get("pillar_key") or "").strip()
            if not pillar_key:
                raise HTTPException(status_code=400, detail="pillar_key required")
            row.pillar_key = pillar_key
        if "concept_code" in payload:
            concept_code = (payload.get("concept_code") or "").strip()
            row.concept_code = concept_code or None
        if "title" in payload:
            title = (payload.get("title") or "").strip()
            if not title:
                raise HTTPException(status_code=400, detail="title required")
            row.title = title
        if "body" in payload:
            body = (payload.get("body") or "").strip()
            if not body:
                raise HTTPException(status_code=400, detail="body required")
            row.body = body
        if "status" in payload:
            row.status = (payload.get("status") or "").strip() or row.status
        if "podcast_url" in payload:
            row.podcast_url = _promote_library_podcast_url((payload.get("podcast_url") or "").strip() or None)
        if "podcast_voice" in payload:
            row.podcast_voice = (payload.get("podcast_voice") or "").strip() or None
        if "source_type" in payload:
            row.source_type = (payload.get("source_type") or "").strip() or None
        if "source_url" in payload:
            row.source_url = (payload.get("source_url") or "").strip() or None
        if "license" in payload:
            row.license = (payload.get("license") or "").strip() or None
        if "level" in payload:
            row.level = (payload.get("level") or "").strip() or None
        if "published_at" in payload:
            raw = (payload.get("published_at") or "").strip()
            if raw:
                try:
                    row.published_at = datetime.fromisoformat(raw)
                except Exception:
                    row.published_at = None
            else:
                row.published_at = None
        if "tags" in payload:
            tags_val = payload.get("tags")
            if tags_val is not None and isinstance(tags_val, str):
                tags_val = [t.strip() for t in tags_val.split(",") if t.strip()]
            row.tags = tags_val or None
        s.commit()
    return {"id": content_id}


@admin.get("/reports/recent")
def admin_reports_recent(
    limit: int = 30,
    admin_user: User = Depends(_require_admin),
):
    try:
        limit = int(limit)
    except Exception:
        limit = 30
    limit = max(1, min(limit, 200))
    club_scope_id = getattr(admin_user, "club_id", None)
    with SessionLocal() as s:
        q = select(AssessmentRun).order_by(desc(AssessmentRun.id)).limit(limit)
        if club_scope_id is not None:
            q = q.join(User, AssessmentRun.user_id == User.id).where(User.club_id == club_scope_id)
        runs = list(s.execute(q).scalars().all())
        user_ids = {r.user_id for r in runs if getattr(r, "user_id", None)}
        users = {}
        if user_ids:
            for u in s.execute(select(User).where(User.id.in_(list(user_ids)))).scalars().all():
                users[u.id] = u
    items = []
    for run in runs:
        uid = int(getattr(run, "user_id", 0) or 0)
        u = users.get(uid)
        items.append(
            {
                "run_id": run.id,
                "user_id": uid,
                "user_name": display_full_name(u) if u else None,
                "finished_at": getattr(run, "finished_at", None),
                "combined_overall": getattr(run, "combined_overall", None),
                "report_html": _public_report_url(uid, "assessment.html"),
                "report_pdf": _public_report_url(uid, "latest.pdf"),
                "report_image": _public_report_url(uid, "latest.jpeg"),
            }
        )
    return {"count": len(items), "items": items}

@admin.get("/kb/snippets")
def admin_kb_snippets(
    q: str | None = None,
    pillar: str | None = None,
    concept: str | None = None,
    limit: int = 200,
    admin_user: User = Depends(_require_admin),
):
    try:
        limit = int(limit)
    except Exception:
        limit = 200
    limit = max(1, min(limit, 500))
    query = (q or "").strip()
    pillar = (pillar or "").strip()
    concept = (concept or "").strip()
    with SessionLocal() as s:
        qbase = s.query(KBSnippet)
        if pillar:
            qbase = qbase.filter(KBSnippet.pillar_key == pillar)
        if concept:
            qbase = qbase.filter(KBSnippet.concept_code == concept)
        if query:
            like = f"%{query}%"
            qbase = qbase.filter(or_(KBSnippet.title.ilike(like), KBSnippet.text.ilike(like)))
        rows = (
            qbase.order_by(desc(KBSnippet.created_at), desc(KBSnippet.id))
            .limit(limit)
            .all()
        )
    items = []
    for sn in rows:
        text_val = sn.text or ""
        preview = text_val if len(text_val) <= 160 else f"{text_val[:157]}…"
        items.append(
            {
                "id": sn.id,
                "pillar_key": sn.pillar_key,
                "concept_code": sn.concept_code,
                "title": sn.title,
                "tags": sn.tags or [],
                "text_preview": preview,
                "created_at": sn.created_at,
            }
        )
    return {"count": len(items), "items": items}


@admin.get("/concepts")
def admin_concepts(
    pillar: str | None = None,
    limit: int = 500,
    admin_user: User = Depends(_require_admin),
):
    try:
        limit = int(limit)
    except Exception:
        limit = 500
    limit = max(1, min(limit, 2000))
    pillar = (pillar or "").strip() or None
    with SessionLocal() as s:
        try:
            q = s.query(Concept)
            if pillar:
                q = q.filter(Concept.pillar_key == pillar)
            rows = q.order_by(Concept.pillar_key.asc(), Concept.code.asc()).limit(limit).all()
        except Exception:
            rows = []
    items = [
        {
            "pillar_key": row.pillar_key,
            "code": row.code,
            "name": row.name,
        }
        for row in rows
    ]
    return {"count": len(items), "items": items}

def _watch_script_run(run_id: int, proc: subprocess.Popen, log_fh):
    try:
        exit_code = proc.wait()
    except Exception:
        exit_code = -1
    try:
        log_fh.close()
    except Exception:
        pass
    with SessionLocal() as s:
        run = s.query(ScriptRun).filter(ScriptRun.id == run_id).one_or_none()
        if not run:
            return
        run.exit_code = exit_code
        run.status = "completed" if exit_code == 0 else "failed"
        run.finished_at = datetime.utcnow()
        s.commit()


def _start_script_run(kind: str, cmd: list[str], admin_user: User):
    log_dir = os.path.join(os.getcwd(), "logs", "script_runs")
    os.makedirs(log_dir, exist_ok=True)
    with SessionLocal() as s:
        run = ScriptRun(
            kind=kind,
            status="running",
            command=" ".join(cmd),
            created_by=getattr(admin_user, "id", None),
            started_at=datetime.utcnow(),
        )
        s.add(run)
        s.commit()
        s.refresh(run)
        log_path = os.path.join(log_dir, f"{kind}_{run.id}.log")
        run.log_path = log_path
        s.commit()
        run_id = run.id

    try:
        # Always start a fresh log file for this run (avoid appending stale output).
        log_fh = open(log_path, "wb")
    except Exception as e:
        with SessionLocal() as s:
            run = s.query(ScriptRun).filter(ScriptRun.id == run_id).one_or_none()
            if run:
                run.status = "failed"
                run.exit_code = -1
                run.finished_at = datetime.utcnow()
                s.commit()
        raise HTTPException(status_code=500, detail=f"failed to open log file: {e}")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=os.getcwd(),
            env=os.environ.copy(),
            stdout=log_fh,
            stderr=log_fh,
        )
    except Exception as e:
        try:
            log_fh.close()
        except Exception:
            pass
        with SessionLocal() as s:
            run = s.query(ScriptRun).filter(ScriptRun.id == run_id).one_or_none()
            if run:
                run.status = "failed"
                run.exit_code = -1
                run.finished_at = datetime.utcnow()
                s.commit()
        raise HTTPException(status_code=500, detail=f"failed to start script: {e}")

    with SessionLocal() as s:
        run = s.query(ScriptRun).filter(ScriptRun.id == run_id).one_or_none()
        if run:
            run.pid = proc.pid
            s.commit()

    t = threading.Thread(target=_watch_script_run, args=(run_id, proc, log_fh), daemon=True)
    t.start()

    return {"id": run_id, "pid": proc.pid, "log_path": log_path}

@admin.post("/scripts/assessment-simulate")
def admin_assessment_simulate(payload: dict, admin_user: User = Depends(_require_admin)):
    """
    Trigger run_assessment_script.py with selected options in the background.
    """
    payload = payload or {}
    args: list[str] = []
    scenario = str(payload.get("scenario") or "").strip()
    batch = bool(payload.get("batch"))
    if batch:
        args.append("--batch")
    if scenario and not batch:
        args.append(scenario)
    preset = str(payload.get("preset") or "").strip().lower()
    if preset in {"min", "mid", "max", "range"}:
        args.append(f"--{preset}")
    start_from = str(payload.get("start_from") or "").strip()
    if start_from and batch:
        args.extend(["--start-from", start_from])
    club_ids = str(payload.get("club_ids") or "").strip()
    if club_ids and batch:
        args.extend(["--club-ids", club_ids])
    sleep_val = str(payload.get("sleep") or "").strip()
    if sleep_val and batch:
        args.extend(["--sleep", sleep_val])
    unique = payload.get("unique")
    if unique is True:
        args.append("--unique")
    elif unique is False:
        args.append("--reuse")
    simulate_weeks = str(payload.get("simulate_weeks") or "").strip().lower()
    if simulate_weeks == "week1":
        args.append("--simulate-week-one")
    elif simulate_weeks in {"12", "weeks12", "week12"}:
        args.append("--simulate-12-weeks")
    julian_mode = str(payload.get("julian") or "").strip().lower()
    if julian_mode in {"julian", "julianlow", "julianhigh"}:
        args.append(f"--{julian_mode}")

    if not args:
        raise HTTPException(status_code=400, detail="No simulation options provided.")

    script_path = os.path.join(os.getcwd(), "run_assessment_script.py")
    cmd = [sys.executable, script_path, *args]
    print(f"[admin][scripts] assessment payload={payload} cmd={cmd}")
    run = _start_script_run("assessment", cmd, admin_user)
    return {"ok": True, "run_id": run["id"], "pid": run["pid"], "log_path": run["log_path"]}


@admin.post("/scripts/coaching-simulate")
def admin_coaching_simulate(payload: dict, admin_user: User = Depends(_require_admin)):
    """
    Trigger run_coaching_script.py with selected options in the background.
    """
    payload = payload or {}
    user_id = payload.get("user_id")
    try:
        user_id = int(user_id)
    except Exception:
        user_id = None
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")

    args: list[str] = ["--user-id", str(user_id)]
    week = str(payload.get("week") or "").strip()
    simulate_weeks = str(payload.get("simulate_weeks") or "").strip().lower()
    start_week = str(payload.get("start_week") or "").strip()
    sleep_val = str(payload.get("sleep") or "").strip()

    if week:
        args.extend(["--week", week])
    elif simulate_weeks == "week1":
        args.append("--simulate-week-one")
    elif simulate_weeks in {"12", "weeks12", "week12"}:
        args.append("--simulate-12-weeks")
        if start_week:
            args.extend(["--start-week", start_week])
        if sleep_val:
            args.extend(["--sleep", sleep_val])
    else:
        raise HTTPException(status_code=400, detail="choose week or simulate_weeks")

    script_path = os.path.join(os.getcwd(), "run_coaching_script.py")
    cmd = [sys.executable, script_path, *args]
    print(f"[admin][scripts] coaching payload={payload} cmd={cmd}")
    run = _start_script_run("coaching", cmd, admin_user)
    return {"ok": True, "run_id": run["id"], "pid": run["pid"], "log_path": run["log_path"]}


@admin.get("/scripts/runs")
def admin_script_runs(limit: int = 20, admin_user: User = Depends(_require_admin)):
    try:
        limit = int(limit)
    except Exception:
        limit = 20
    limit = max(1, min(limit, 200))
    with SessionLocal() as s:
        try:
            runs = (
                s.query(ScriptRun)
                .order_by(ScriptRun.started_at.desc())
                .limit(limit)
                .all()
            )
        except Exception:
            runs = []
    return {
        "items": [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "pid": r.pid,
                "command": r.command,
                "log_path": r.log_path,
                "exit_code": r.exit_code,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "created_by": r.created_by,
            }
            for r in runs
        ]
    }


@admin.get("/scripts/runs/{run_id}")
def admin_script_run_detail(run_id: int, admin_user: User = Depends(_require_admin)):
    with SessionLocal() as s:
        run = s.query(ScriptRun).filter(ScriptRun.id == run_id).one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        return {
            "id": run.id,
            "kind": run.kind,
            "status": run.status,
            "pid": run.pid,
            "command": run.command,
            "log_path": run.log_path,
            "exit_code": run.exit_code,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "created_by": run.created_by,
        }


@admin.get("/scripts/runs/{run_id}/log")
def admin_script_run_log(run_id: int, tail: int = 4000, admin_user: User = Depends(_require_admin)):
    try:
        tail = int(tail)
    except Exception:
        tail = 4000
    tail = max(200, min(tail, 200000))
    with SessionLocal() as s:
        run = s.query(ScriptRun).filter(ScriptRun.id == run_id).one_or_none()
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        log_path = run.log_path
    if not log_path or not os.path.exists(log_path):
        return {"log": "", "path": log_path, "tail": tail}
    with open(log_path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - tail), os.SEEK_SET)
        data = fh.read()
    return {"log": data.decode(errors="replace"), "path": log_path, "tail": tail}

@admin.get("/kb/snippets/{snippet_id}")
def admin_kb_snippet_detail(snippet_id: int, admin_user: User = Depends(_require_admin)):
    with SessionLocal() as s:
        sn = s.query(KBSnippet).filter(KBSnippet.id == snippet_id).one_or_none()
        if not sn:
            raise HTTPException(status_code=404, detail="snippet not found")
        return {
            "id": sn.id,
            "pillar_key": sn.pillar_key,
            "concept_code": sn.concept_code,
            "title": sn.title,
            "text": sn.text,
            "tags": sn.tags or [],
            "created_at": sn.created_at,
        }

@admin.post("/kb/snippets")
def admin_kb_snippet_create(payload: dict, admin_user: User = Depends(_require_admin)):
    pillar_key = (payload.get("pillar_key") or "").strip()
    concept_code = (payload.get("concept_code") or "").strip() or None
    title = (payload.get("title") or "").strip() or None
    text_val = (payload.get("text") or "").strip()
    if not pillar_key:
        raise HTTPException(status_code=400, detail="pillar_key required")
    if not text_val:
        raise HTTPException(status_code=400, detail="text required")
    tags = _parse_kb_tags(payload.get("tags")) or None
    with SessionLocal() as s:
        sn = KBSnippet(
            pillar_key=pillar_key,
            concept_code=concept_code,
            title=title,
            text=text_val,
            tags=tags,
        )
        s.add(sn)
        s.flush()
        embedding_source = f"{title}\n{text_val}" if title else text_val
        embedding = embed_text(embedding_source)
        s.add(KBVector(snippet_id=sn.id, embedding=embedding))
        s.commit()
        return {"id": sn.id}

@admin.post("/kb/snippets/{snippet_id}")
def admin_kb_snippet_update(snippet_id: int, payload: dict, admin_user: User = Depends(_require_admin)):
    with SessionLocal() as s:
        sn = s.query(KBSnippet).filter(KBSnippet.id == snippet_id).one_or_none()
        if not sn:
            raise HTTPException(status_code=404, detail="snippet not found")
        reembed = False
        if "pillar_key" in payload:
            pillar_key = (payload.get("pillar_key") or "").strip()
            if not pillar_key:
                raise HTTPException(status_code=400, detail="pillar_key required")
            sn.pillar_key = pillar_key
        if "concept_code" in payload:
            concept_code = (payload.get("concept_code") or "").strip()
            sn.concept_code = concept_code or None
        if "title" in payload:
            title = (payload.get("title") or "").strip()
            sn.title = title or None
            reembed = True
        if "text" in payload:
            text_val = (payload.get("text") or "").strip()
            if not text_val:
                raise HTTPException(status_code=400, detail="text required")
            sn.text = text_val
            reembed = True
        if "tags" in payload:
            tags = _parse_kb_tags(payload.get("tags"))
            sn.tags = tags or None
        s.flush()
        if reembed:
            s.query(KBVector).filter(KBVector.snippet_id == sn.id).delete()
            embedding_source = f"{sn.title}\n{sn.text}" if sn.title else sn.text
            embedding = embed_text(embedding_source)
            s.add(KBVector(snippet_id=sn.id, embedding=embedding))
        s.commit()
        return {"id": sn.id}

@admin.get("/users")
def admin_list_users(
    q: str | None = None,
    limit: int = 50,
    admin_user: User = Depends(_require_admin),
):
    """
    List users in the admin's club scope with optional search.
    Query params:
      - q: filter by name or phone
      - limit: max results (default 50, max 200)
    """
    try:
        limit = int(limit)
    except Exception:
        limit = 50
    limit = max(1, min(limit, 200))
    club_scope_id = getattr(admin_user, "club_id", None)
    with SessionLocal() as s:
        query = select(User)
        if club_scope_id is not None:
            query = query.where(User.club_id == club_scope_id)
        if q:
            like = f"%{q.strip()}%"
            query = query.where(
                or_(
                    User.first_name.ilike(like),
                    User.surname.ilike(like),
                    User.phone.ilike(like),
                )
            )
        query = query.order_by(desc(User.id)).limit(limit)
        users = list(s.execute(query).scalars().all())
        user_ids = [u.id for u in users]
        latest_runs: dict[int, int] = {}
        latest_finished: dict[int, datetime | None] = {}
        active_users: set[int] = set()
        prompt_overrides: dict[int, str] = {}
        coaching_pref: dict[int, tuple[datetime | None, str]] = {}
        coaching_fast_minutes: dict[int, int] = {}
        last_template_sent: dict[int, datetime | None] = {}
        if user_ids:
            run_rows = s.execute(
                select(AssessmentRun.user_id, func.max(AssessmentRun.id))
                .where(AssessmentRun.user_id.in_(user_ids))
                .group_by(AssessmentRun.user_id)
            ).all()
            latest_runs = {int(uid): int(rid) for uid, rid in run_rows if uid and rid}
            if latest_runs:
                finish_rows = s.execute(
                    select(AssessmentRun.id, AssessmentRun.finished_at)
                    .where(AssessmentRun.id.in_(list(latest_runs.values())))
                ).all()
                latest_finished = {int(rid): finished_at for rid, finished_at in finish_rows}
            active_rows = s.execute(
                select(AssessSession.user_id)
                .where(
                    AssessSession.user_id.in_(user_ids),
                    AssessSession.domain == "combined",
                    AssessSession.is_active == True,  # noqa: E712
                )
            ).all()
            active_users = {int(uid) for (uid,) in active_rows if uid}
            pref_rows = s.execute(
                select(UserPreference.user_id, UserPreference.value)
                .where(
                    UserPreference.user_id.in_(user_ids),
                    UserPreference.key == "prompt_state_override",
                )
            ).all()
            prompt_overrides = {int(uid): (val or "") for uid, val in pref_rows if uid}
            coaching_rows = s.execute(
                select(UserPreference.user_id, UserPreference.value, UserPreference.updated_at)
                .where(
                    UserPreference.user_id.in_(user_ids),
                    UserPreference.key.in_(("coaching", "auto_daily_prompts")),
                )
            ).all()
            fast_rows = s.execute(
                select(UserPreference.user_id, UserPreference.value, UserPreference.updated_at)
                .where(
                    UserPreference.user_id.in_(user_ids),
                    UserPreference.key == "coaching_fast_minutes",
                )
            ).all()
            for uid, val, updated_at in coaching_rows:
                if not uid:
                    continue
                existing = coaching_pref.get(int(uid))
                if existing and existing[0] and updated_at and updated_at <= existing[0]:
                    continue
                coaching_pref[int(uid)] = (updated_at, str(val or ""))
            for uid, val, _updated_at in fast_rows:
                if not uid:
                    continue
                try:
                    parsed = int(str(val or "").strip())
                    if parsed > 0:
                        coaching_fast_minutes[int(uid)] = parsed
                except Exception:
                    continue
            template_rows = s.execute(
                select(UsageEvent.user_id, func.max(UsageEvent.created_at))
                .where(
                    UsageEvent.user_id.in_(user_ids),
                    UsageEvent.provider == "twilio",
                    UsageEvent.product == "whatsapp",
                    UsageEvent.unit_type == "message_template",
                )
                .group_by(UsageEvent.user_id)
            ).all()
            last_template_sent = {int(uid): ts for uid, ts in template_rows if uid}

    payload = []
    for u in users:
        run_id = latest_runs.get(u.id)
        status = "idle"
        if u.id in active_users:
            status = "in_progress"
        elif run_id and latest_finished.get(run_id):
            status = "completed"
        payload.append(
            {
                "id": u.id,
                "first_name": getattr(u, "first_name", None),
                "surname": getattr(u, "surname", None),
                "display_name": display_full_name(u),
                "phone": getattr(u, "phone", None),
                "created_on": getattr(u, "created_on", None),
                "updated_on": getattr(u, "updated_on", None),
                "consent_given": bool(getattr(u, "consent_given", False)),
                "consent_at": getattr(u, "consent_at", None),
                "last_inbound_message_at": getattr(u, "last_inbound_message_at", None),
                "last_template_message_at": last_template_sent.get(u.id),
                "latest_run_id": run_id,
                "latest_run_finished_at": latest_finished.get(run_id) if run_id else None,
                "status": status,
                "prompt_state_override": prompt_overrides.get(u.id, ""),
                "coaching_enabled": (coaching_pref.get(u.id, (None, "0"))[1].strip() == "1"),
                "coaching_fast_minutes": coaching_fast_minutes.get(u.id),
            }
        )

    return {"count": len(payload), "users": payload}

@admin.get("/users/{user_id}")
def admin_user_details(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Return full user details, status, and latest run metadata.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
        active = get_active_domain(u)
        latest_run = (
            s.execute(
                select(AssessmentRun)
                .where(AssessmentRun.user_id == user_id)
                .order_by(desc(AssessmentRun.id))
            )
            .scalars()
            .first()
        )
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "prompt_state_override")
            .one_or_none()
        )
        onboarding_state = _get_onboarding_state(s, user_id)
        intro_row = _latest_intro_content_row(s, active_only=True)
        coaching_pref = _pref_value(s, user_id, "coaching")
        coaching_enabled = str(coaching_pref or "").strip() == "1"
        current_weekly_plan = None
        day_start = datetime.combine(datetime.utcnow().date(), datetime.min.time())
        day_end = day_start + timedelta(days=1)
        wf_source = "none"
        wf = (
            s.query(WeeklyFocus)
            .filter(
                WeeklyFocus.user_id == user_id,
                WeeklyFocus.starts_on < day_end,
                WeeklyFocus.ends_on >= day_start,
            )
            .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
            .first()
        )
        if wf:
            wf_source = "active"
        else:
            wf = (
                s.query(WeeklyFocus)
                .filter(
                    WeeklyFocus.user_id == user_id,
                    WeeklyFocus.starts_on < day_end,
                )
                .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
                .first()
            )
            if wf:
                wf_source = "latest_started"
            else:
                wf = (
                    s.query(WeeklyFocus)
                    .filter(WeeklyFocus.user_id == user_id)
                    .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
                    .first()
                )
                if wf:
                    wf_source = "latest"

        if wf:
            wfk_rows = (
                s.query(WeeklyFocusKR, OKRKeyResult, OKRObjective)
                .join(OKRKeyResult, WeeklyFocusKR.kr_id == OKRKeyResult.id)
                .join(OKRObjective, OKRKeyResult.objective_id == OKRObjective.id)
                .filter(WeeklyFocusKR.weekly_focus_id == wf.id)
                .order_by(WeeklyFocusKR.priority_order.asc(), WeeklyFocusKR.id.asc())
                .all()
            )
            kr_ids = [int(getattr(link, "kr_id")) for link, _kr, _obj in wfk_rows if getattr(link, "kr_id", None)]
            habits_by_kr: dict[int, list[dict]] = {}
            if kr_ids:
                habit_query = (
                    s.query(OKRKrHabitStep)
                    .filter(
                        OKRKrHabitStep.user_id == user_id,
                        OKRKrHabitStep.kr_id.in_(kr_ids),
                        OKRKrHabitStep.status != "archived",
                    )
                )
                wf_week_no = getattr(wf, "week_no", None)
                if wf_week_no is not None:
                    try:
                        wf_week_no_i = int(wf_week_no)
                    except Exception:
                        wf_week_no_i = None
                    if wf_week_no_i is not None:
                        habit_query = habit_query.filter(
                            or_(
                                OKRKrHabitStep.week_no == wf_week_no_i,
                                (OKRKrHabitStep.week_no.is_(None)) & (OKRKrHabitStep.weekly_focus_id == wf.id),
                            )
                        )
                    else:
                        habit_query = habit_query.filter(OKRKrHabitStep.weekly_focus_id == wf.id)
                else:
                    habit_query = habit_query.filter(OKRKrHabitStep.weekly_focus_id == wf.id)
                habit_rows = (
                    habit_query
                    .order_by(
                        OKRKrHabitStep.kr_id.asc(),
                        OKRKrHabitStep.week_no.asc().nullslast(),
                        OKRKrHabitStep.sort_order.asc(),
                        OKRKrHabitStep.id.asc(),
                    )
                    .all()
                )
                for row in habit_rows:
                    kr_i = int(getattr(row, "kr_id"))
                    habits_by_kr.setdefault(kr_i, []).append(
                        {
                            "id": int(row.id),
                            "text": row.step_text,
                            "status": row.status,
                            "week_no": row.week_no,
                            "weekly_focus_id": row.weekly_focus_id,
                        }
                    )

            current_weekly_plan = {
                "id": int(wf.id),
                "week_no": getattr(wf, "week_no", None),
                "starts_on": getattr(wf, "starts_on", None),
                "ends_on": getattr(wf, "ends_on", None),
                "notes": getattr(wf, "notes", None),
                "source": wf_source,
                "krs": [
                    {
                        "id": int(kr.id),
                        "priority_order": getattr(link, "priority_order", None),
                        "role": getattr(link, "role", None),
                        "pillar_key": getattr(obj, "pillar_key", None),
                        "description": getattr(kr, "description", None),
                        "metric_label": getattr(kr, "metric_label", None),
                        "unit": getattr(kr, "unit", None),
                        "target_num": getattr(kr, "target_num", None),
                        "actual_num": getattr(kr, "actual_num", None),
                        "status": getattr(kr, "status", None),
                        "habit_steps": habits_by_kr.get(int(kr.id), []),
                    }
                    for link, kr, obj in wfk_rows
                ],
            }
        last_template_message_at = s.execute(
            select(func.max(UsageEvent.created_at)).where(
                UsageEvent.user_id == user_id,
                UsageEvent.provider == "twilio",
                UsageEvent.product == "whatsapp",
                UsageEvent.unit_type == "message_template",
            )
        ).scalar_one_or_none()

    status = "idle"
    if active:
        status = "in_progress"
    elif latest_run and getattr(latest_run, "finished_at", None):
        status = "completed"

    assessment_completed_at = str(onboarding_state.get("assessment_completed_at") or "").strip() or None
    first_login_at = str(onboarding_state.get("first_app_login_at") or "").strip() or None
    assessment_reviewed_at = str(onboarding_state.get("assessment_reviewed_at") or "").strip() or None
    intro_presented_at = str(onboarding_state.get("intro_content_presented_at") or "").strip() or None
    intro_listened_at = str(onboarding_state.get("intro_content_listened_at") or "").strip() or None
    intro_read_at = str(onboarding_state.get("intro_content_read_at") or "").strip() or None
    intro_completed_at = str(onboarding_state.get("intro_content_completed_at") or "").strip() or None
    coaching_auto_enabled_at = str(onboarding_state.get("coaching_auto_enabled_at") or "").strip() or None
    intro_active = bool(_intro_flow_enabled())
    intro_content_published = bool(intro_row)
    intro_content_has_audio = bool(intro_row and str(getattr(intro_row, "podcast_url", "") or "").strip())
    intro_content_has_read = bool(intro_row and str(getattr(intro_row, "body", "") or "").strip())
    coaching_enabled_at_ts = _parse_pref_timestamp(coaching_auto_enabled_at)
    coaching_recently_enabled = bool(
        coaching_enabled
        and coaching_enabled_at_ts is not None
        and datetime.utcnow() <= (coaching_enabled_at_ts + timedelta(hours=24))
    )
    intro_should_show = bool(
        intro_active
        and intro_content_published
        and first_login_at
        and (not coaching_enabled or coaching_recently_enabled)
    )
    activation_ready = bool(assessment_completed_at and first_login_at and assessment_reviewed_at and intro_completed_at)

    return {
        "user": {
            "id": u.id,
            "club_id": getattr(u, "club_id", None),
            "first_name": getattr(u, "first_name", None),
            "surname": getattr(u, "surname", None),
            "display_name": display_full_name(u),
            "phone": getattr(u, "phone", None),
            "email": getattr(u, "email", None),
            "password_hash": getattr(u, "password_hash", None),
            "phone_verified_at": getattr(u, "phone_verified_at", None),
            "email_verified_at": getattr(u, "email_verified_at", None),
            "two_factor_enabled": bool(getattr(u, "two_factor_enabled", False)),
            "created_on": getattr(u, "created_on", None),
            "updated_on": getattr(u, "updated_on", None),
            "is_superuser": bool(getattr(u, "is_superuser", False)),
            "admin_role": getattr(u, "admin_role", None),
            "consent_given": bool(getattr(u, "consent_given", False)),
            "consent_at": getattr(u, "consent_at", None),
            "last_inbound_message_at": getattr(u, "last_inbound_message_at", None),
            "last_template_message_at": last_template_message_at,
            "onboard_complete": bool(getattr(u, "onboard_complete", False)),
            "prompt_state_override": (pref.value if pref else "") or "",
        },
        "status": status,
        "latest_run": {
            "id": latest_run.id,
            "finished_at": getattr(latest_run, "finished_at", None),
            "combined_overall": getattr(latest_run, "combined_overall", None),
        }
        if latest_run
        else None,
        "onboarding": {
            "assessment_completed_at": assessment_completed_at,
            "first_app_login_at": first_login_at,
            "assessment_reviewed_at": assessment_reviewed_at,
            "intro_content_presented_at": intro_presented_at,
            "intro_content_listened_at": intro_listened_at,
            "intro_content_read_at": intro_read_at,
            "intro_content_completed_at": intro_completed_at,
            "coaching_auto_enabled_at": coaching_auto_enabled_at,
            "checks": {
                "assessment_completed_met": bool(assessment_completed_at),
                "first_login_met": bool(first_login_at),
                "assessment_review_met": bool(assessment_reviewed_at),
                "intro_completed_met": bool(intro_completed_at),
                "coaching_activation_ready": activation_ready,
                "coaching_enabled_now": coaching_enabled,
                "coaching_auto_enabled_recorded": bool(coaching_auto_enabled_at),
                "intro_should_show_now": intro_should_show,
            },
            "intro_content": {
                "content_id": int(getattr(intro_row, "id", 0)) if intro_row else None,
                "title": str(getattr(intro_row, "title", "") or "").strip() if intro_row else None,
                "podcast_url": _normalize_reports_url(getattr(intro_row, "podcast_url", None)) if intro_row else None,
                "body_present": intro_content_has_read,
            },
        },
        "current_weekly_plan": current_weekly_plan,
    }

@admin.post("/users/{user_id}/prompt-state")
def admin_user_prompt_state(user_id: int, payload: dict, admin_user: User = Depends(_require_admin)):
    """
    Set prompt state override for a user.
    Body: { "state": "live|beta|clear" }
    """
    state_raw = (payload.get("state") or payload.get("prompt_state_override") or "").strip().lower()
    if not state_raw:
        raise HTTPException(status_code=400, detail="state required")
    if state_raw == "clear":
        state_raw = "live"
    if state_raw not in {"live", "beta"}:
        raise HTTPException(status_code=400, detail="state must be live|beta|clear")
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "prompt_state_override")
            .one_or_none()
        )
        if state_raw == "live":
            if pref:
                s.delete(pref)
                s.commit()
            return {"user_id": user_id, "prompt_state_override": ""}
        if not pref:
            pref = UserPreference(user_id=user_id, key="prompt_state_override")
            s.add(pref)
        pref.value = state_raw
        s.commit()
    return {"user_id": user_id, "prompt_state_override": state_raw}

@admin.post("/users/{user_id}/coaching")
def admin_user_coaching(user_id: int, payload: dict, admin_user: User = Depends(_require_admin)):
    """
    Enable/disable coaching using scheduler logic (same behavior as admin WhatsApp command).
    Body: { "enabled": true|false }
    """
    enabled_raw = payload.get("enabled")
    if enabled_raw is None:
        raise HTTPException(status_code=400, detail="enabled required")
    if isinstance(enabled_raw, bool):
        enabled = enabled_raw
    elif isinstance(enabled_raw, (int, float)):
        enabled = bool(int(enabled_raw))
    else:
        token = str(enabled_raw).strip().lower()
        if token in {"1", "true", "yes", "on", "enable", "enabled"}:
            enabled = True
        elif token in {"0", "false", "no", "off", "disable", "disabled"}:
            enabled = False
        else:
            raise HTTPException(status_code=400, detail="enabled must be boolean")

    fast_minutes: int | None = None
    fast_minutes_raw = payload.get("fast_minutes")
    if fast_minutes_raw is not None and str(fast_minutes_raw).strip() != "":
        try:
            parsed = int(str(fast_minutes_raw).strip())
        except Exception:
            raise HTTPException(status_code=400, detail="fast_minutes must be an integer")
        if parsed < 1 or parsed > 120:
            raise HTTPException(status_code=400, detail="fast_minutes must be between 1 and 120")
        fast_minutes = parsed

    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)

    ok = scheduler.enable_coaching(user_id, fast_minutes=fast_minutes) if enabled else scheduler.disable_coaching(user_id)
    if not ok:
        raise HTTPException(status_code=500, detail="failed to update coaching schedule")
    return {
        "status": "enabled" if enabled else "disabled",
        "user_id": user_id,
        "fast_minutes": fast_minutes if enabled else None,
    }

@admin.post("/users/{user_id}/start")
def admin_start_user(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Start (or restart) assessment for a user; will send consent/intro if needed.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
    _start_assessment_async(u)
    return {"status": "started", "user_id": user_id}

@admin.post("/users/{user_id}/app-session")
def admin_user_app_session(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Mint a short-lived app session token for opening the member app from admin.
    """
    ttl_minutes_raw = (os.getenv("ADMIN_APP_SESSION_TTL_MINUTES") or "30").strip()
    try:
        ttl_minutes = max(5, min(180, int(ttl_minutes_raw)))
    except Exception:
        ttl_minutes = 30
    now = datetime.utcnow()
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
        session_token = secrets.token_urlsafe(32)
        auth_session = AuthSession(
            user_id=u.id,
            token_hash=_hash_token(session_token),
            created_at=now,
            expires_at=now + timedelta(minutes=ttl_minutes),
            ip=None,
            user_agent=f"admin-app-session:{getattr(admin_user, 'id', 'unknown')}",
        )
        s.add(auth_session)
        s.commit()
    return {
        "user_id": user_id,
        "session_token": session_token,
        "expires_at": (now + timedelta(minutes=ttl_minutes)).isoformat(),
        "ttl_minutes": ttl_minutes,
    }

@admin.get("/users/{user_id}/status")
def admin_user_status(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Return assessment status and latest run info.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
        active = get_active_domain(u)
        latest_run = s.execute(
            select(AssessmentRun).where(AssessmentRun.user_id == user_id).order_by(desc(AssessmentRun.id))
        ).scalars().first()

    data = {
        "user": {
            "id": u.id,
            "first_name": getattr(u, "first_name", None),
            "surname": getattr(u, "surname", None),
            "display_name": display_full_name(u),
            "phone": u.phone,
            "consent_given": bool(getattr(u, "consent_given", False)),
            "consent_at": getattr(u, "consent_at", None),
        },
        "active_domain": active,
        "latest_run": None
    }

    if latest_run:
        data["latest_run"] = {
            "id": latest_run.id,
            "finished_at": getattr(latest_run, "finished_at", None),
            "combined_overall": getattr(latest_run, "combined_overall", None),
            "report_pdf": _public_report_url(user_id, "latest.pdf"),
            "report_image": _public_report_url(user_id, "latest.jpeg"),
        }

    if active:
        data["status"] = "in_progress"
    elif latest_run and getattr(latest_run, "finished_at", None):
        data["status"] = "completed"
    else:
        data["status"] = "idle"

    return data


@admin.post("/users/{user_id}/reset")
def admin_reset_user(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Reset a user's data for testing: deletes assessments, touchpoints, OKRs, messages, and related records.
    Leaves the user profile intact.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)

        user_phone = getattr(u, "phone", None)
        deleted: dict[str, int] = {}

        def _delete_rows(label: str, query):
            count = query.delete(synchronize_session=False)
            deleted[label] = int(count or 0)

        touchpoint_ids = [
            tid for (tid,) in s.execute(select(Touchpoint.id).where(Touchpoint.user_id == user_id)).all()
        ]
        weekly_focus_ids = [
            wid for (wid,) in s.execute(select(WeeklyFocus.id).where(WeeklyFocus.user_id == user_id)).all()
        ]
        objective_ids = [
            oid
            for (oid,) in s.execute(select(OKRObjective.id).where(OKRObjective.owner_user_id == user_id)).all()
        ]
        kr_ids: list[int] = []
        if objective_ids:
            kr_ids = [
                kid
                for (kid,) in s.execute(
                    select(OKRKeyResult.id).where(OKRKeyResult.objective_id.in_(objective_ids))
                ).all()
            ]
        run_ids = [
            rid for (rid,) in s.execute(select(AssessmentRun.id).where(AssessmentRun.user_id == user_id)).all()
        ]

        if touchpoint_ids:
            _delete_rows(
                "engagement_events",
                s.query(EngagementEvent).filter(EngagementEvent.touchpoint_id.in_(touchpoint_ids)),
            )
            _delete_rows(
                "touchpoint_krs",
                s.query(TouchpointKR).filter(TouchpointKR.touchpoint_id.in_(touchpoint_ids)),
            )
        _delete_rows("okr_focus_stack", s.query(OKRFocusStack).filter(OKRFocusStack.user_id == user_id))
        _delete_rows("touchpoints", s.query(Touchpoint).filter(Touchpoint.user_id == user_id))

        if weekly_focus_ids:
            _delete_rows(
                "weekly_focus_krs",
                s.query(WeeklyFocusKR).filter(WeeklyFocusKR.weekly_focus_id.in_(weekly_focus_ids)),
            )
        _delete_rows("weekly_focus", s.query(WeeklyFocus).filter(WeeklyFocus.user_id == user_id))

        if kr_ids:
            _delete_rows(
                "okr_kr_entries",
                s.query(OKRKrEntry).filter(OKRKrEntry.key_result_id.in_(kr_ids)),
            )
            _delete_rows("okr_kr_habit_steps", s.query(OKRKrHabitStep).filter(OKRKrHabitStep.kr_id.in_(kr_ids)))
        _delete_rows(
            "okr_objective_reviews",
            s.query(OKRObjectiveReview).filter(OKRObjectiveReview.objective_id.in_(objective_ids)),
        )
        _delete_rows("okr_key_results", s.query(OKRKeyResult).filter(OKRKeyResult.id.in_(kr_ids)))
        _delete_rows("okr_objectives", s.query(OKRObjective).filter(OKRObjective.owner_user_id == user_id))

        if run_ids:
            _delete_rows(
                "assessment_turns",
                s.query(AssessmentTurn).filter(AssessmentTurn.run_id.in_(run_ids)),
            )
            _delete_rows(
                "assessment_narratives",
                s.query(AssessmentNarrative).filter(AssessmentNarrative.run_id.in_(run_ids)),
            )
        _delete_rows("pillar_results", s.query(PillarResult).filter(PillarResult.user_id == user_id))
        _delete_rows("user_concept_state", s.query(UserConceptState).filter(UserConceptState.user_id == user_id))
        _delete_rows("psych_profiles", s.query(PsychProfile).filter(PsychProfile.user_id == user_id))
        _delete_rows("assessment_runs", s.query(AssessmentRun).filter(AssessmentRun.user_id == user_id))
        _delete_rows("assess_sessions", s.query(AssessSession).filter(AssessSession.user_id == user_id))

        _delete_rows("check_ins", s.query(CheckIn).filter(CheckIn.user_id == user_id))
        _delete_rows("preference_inference_audit", s.query(PreferenceInferenceAudit).filter(PreferenceInferenceAudit.user_id == user_id))
        _delete_rows("llm_prompt_logs", s.query(LLMPromptLog).filter(LLMPromptLog.user_id == user_id))
        _delete_rows("content_prompt_generations", s.query(ContentPromptGeneration).filter(ContentPromptGeneration.user_id == user_id))
        _delete_rows("auth_sessions", s.query(AuthSession).filter(AuthSession.user_id == user_id))
        _delete_rows("auth_otps", s.query(AuthOtp).filter(AuthOtp.user_id == user_id))
        _delete_rows("user_preferences", s.query(UserPreference).filter(UserPreference.user_id == user_id))

        if user_phone:
            _delete_rows(
                "message_logs",
                s.query(MessageLog).filter(or_(MessageLog.user_id == user_id, MessageLog.phone == user_phone)),
            )
        else:
            _delete_rows("message_logs", s.query(MessageLog).filter(MessageLog.user_id == user_id))

        s.commit()

    return {"status": "reset", "user_id": user_id, "deleted": deleted}


@admin.post("/users/{user_id}/delete")
def admin_delete_user(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Permanently delete a member user and related records.
    """
    with SessionLocal() as s:
        target = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not target:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, target)
        if int(getattr(target, "id", 0) or 0) == int(getattr(admin_user, "id", 0) or 0):
            raise HTTPException(status_code=400, detail="cannot delete your own admin user")
        if _user_admin_role(target) in {ADMIN_ROLE_CLUB, ADMIN_ROLE_GLOBAL}:
            raise HTTPException(status_code=400, detail="cannot delete admin users from user management")

    # Unschedule ongoing coaching jobs and clear fast mode before deletion.
    try:
        scheduler.disable_coaching(user_id)
    except Exception:
        pass

    reset_result = admin_reset_user(user_id=user_id, admin_user=admin_user)
    deleted_rows = reset_result.get("deleted", {}) if isinstance(reset_result, dict) else {}

    with SessionLocal() as s:
        target = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not target:
            return {"status": "deleted", "user_id": user_id, "deleted": deleted_rows}
        s.delete(target)
        s.commit()

    return {"status": "deleted", "user_id": user_id, "deleted": deleted_rows}



@admin.get("/users/{user_id}/report")
def admin_user_report(user_id: int, admin_user: User = Depends(_require_admin)):
    """
    Return latest report URLs for the user.
    """
    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
    return {
        "pdf": _public_report_url(user_id, "latest.pdf"),
        "image": _public_report_url(user_id, "latest.jpeg"),
    }


@admin.post("/reports/progress/{user_id}")
def admin_progress_report(user_id: int, anchor: str | None = None, admin_user: User = Depends(_require_admin)):
    from .reporting import generate_progress_report_html

    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
    anchor_date = None
    if anchor:
        try:
            anchor_date = date.fromisoformat(anchor)
        except Exception:
            anchor_date = None
    generate_progress_report_html(user_id, anchor_date=anchor_date)
    return {"html": _public_report_url(user_id, "progress.html")}


@admin.post("/reports/detailed/{user_id}")
def admin_detailed_report(user_id: int, admin_user: User = Depends(_require_admin)):
    from .reporting import generate_detailed_report_pdf_by_user

    with SessionLocal() as s:
        u = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not u:
            raise HTTPException(status_code=404, detail="user not found")
        _ensure_club_scope(admin_user, u)
    generate_detailed_report_pdf_by_user(user_id)
    return {"pdf": _public_report_url(user_id, "detailed.pdf")}


@admin.post("/reports/club-users")
def admin_club_users_report(admin_user: User = Depends(_require_admin)):
    from .reporting import generate_club_users_html

    club_scope_id = getattr(admin_user, "club_id", None)
    if club_scope_id is None:
        raise HTTPException(status_code=400, detail="admin user missing club")
    path = generate_club_users_html(club_scope_id)
    filename = os.path.basename(path)
    return {"html": _public_report_url_global(filename)}


@admin.post("/reports/summary")
def admin_summary_report(
    start: str | None = None,
    end: str | None = None,
    admin_user: User = Depends(_require_admin),
):
    club_scope_id = getattr(admin_user, "club_id", None)
    if start or end:
        start_str, end_str = _parse_summary_range([start or "today", end] if end else [start or "today"])
    else:
        start_str, end_str = _parse_summary_range(["today"])
    try:
        pdf_path = generate_assessment_summary_pdf(start_str, end_str, club_id=club_scope_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate summary report: {e}")
    filename = os.path.basename(pdf_path)
    return {"pdf": _public_report_url_global(filename), "range": {"start": start_str, "end": end_str}}


# Regenerate assessment report for a specific AssessmentRun and return public URLs.
@admin.post("/reports/run/{run_id}")
def admin_generate_report_for_run(run_id: int, admin_user: User = Depends(_require_admin)):
    """Regenerate assessment report for a specific AssessmentRun and return public URLs."""
    with SessionLocal() as s:
        run = s.execute(select(AssessmentRun).where(AssessmentRun.id == run_id)).scalars().first()
        if not run:
            raise HTTPException(status_code=404, detail="assessment run not found")
        user_id = int(getattr(run, "user_id", 0) or 0)
        if not user_id:
            raise HTTPException(status_code=500, detail="run has no user_id")
        user = s.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="user not found for run")
        _ensure_club_scope(admin_user, user)
    try:
        generate_assessment_report_pdf(run_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to generate report: {e}")
    return {
        "user_id": user_id,
        "run_id": run_id,
        "pdf": _public_report_url(user_id, "latest.pdf"),
        "image": _public_report_url(user_id, "latest.jpeg"),
    }


# Generate (or regenerate) reports for all completed AssessmentRuns in a date range.
@admin.post("/reports/batch")
def admin_generate_batch_reports(
    start: str | None = None,
    end: str | None = None,
    admin_user: User = Depends(_require_admin),
):
    """
    Generate (or regenerate) reports for all completed AssessmentRuns in a date range.
    Accepted query params:
      - start/end as ISO dates (YYYY-MM-DD) OR
      - start as a token: today | last7d | last30d | thisweek
    If neither is provided, defaults to today.
    """
    # Resolve date range
    def _resolve_range(start: str | None, end: str | None) -> tuple[str, str]:
        if start and start.lower() in {"today", "last7d", "last30d", "thisweek"}:
            return _parse_summary_range([start])
        if start and end:
            return _parse_summary_range([start, end])
        # default to today
        return _parse_summary_range(["today"])

    start_str, end_str = _resolve_range(start, end)
    try:
        start_dt = datetime.fromisoformat(start_str)
        # make end exclusive by adding one day
        end_dt = datetime.fromisoformat(end_str) + timedelta(days=1)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid start/end date; expected YYYY-MM-DD or token")

    items: list[dict] = []
    club_scope_id = getattr(admin_user, "club_id", None)
    with SessionLocal() as s:
        q = select(AssessmentRun).where(
            AssessmentRun.finished_at.isnot(None),
            AssessmentRun.finished_at >= start_dt,
            AssessmentRun.finished_at < end_dt,
        )
        if club_scope_id is not None:
            q = q.join(User, AssessmentRun.user_id == User.id).where(User.club_id == club_scope_id)
        q = q.order_by(desc(AssessmentRun.id))
        runs = list(s.execute(q).scalars().all())

    for run in runs:
        uid = int(getattr(run, "user_id", 0) or 0)
        rid = int(getattr(run, "id", 0) or 0)
        try:
            generate_assessment_report_pdf(rid)
            items.append({
                "user_id": uid,
                "run_id": rid,
                "pdf": _public_report_url(uid, "latest.pdf"),
                "image": _public_report_url(uid, "latest.jpeg"),
            })
        except Exception as e:
            # Include error per run but continue
            items.append({
                "user_id": uid,
                "run_id": rid,
                "error": str(e),
            })

    return {
        "range": {"start": start_str, "end": end_str},
        "count": len([i for i in items if "error" not in i]),
        "total": len(items),
        "items": items,
    }


# Optional: Admin endpoint to generate OKR summary PDF
@admin.get("/okr-summary")
def admin_okr_summary(
    start: str | None = None,
    end: str | None = None,
    include_llm_prompt: bool = False,
    admin_user: User = Depends(_require_admin),
):
    """Generate an OKR summary PDF for the given date range and return its public URL.
    - Set include_llm_prompt=true to include the llm prompt field.
    """
    try:
        gen = _resolve_okr_summary_gen_llm() if include_llm_prompt else _resolve_okr_summary_gen()
        club_scope_id = getattr(admin_user, "club_id", None)
        pdf_path = gen(start, end, club_id=club_scope_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate OKR summary: {e}")
    filename = os.path.basename(pdf_path)
    return {"pdf": _public_report_url_global(filename)}

# Mount admin API endpoints (after route declarations)
app.include_router(admin)


# ──────────────────────────────────────────────────────────────────────────────
# Static: serve generated PDFs at /reports/<user_id>/latest.pdf
# ──────────────────────────────────────────────────────────────────────────────
# ──────────────────────────────────────────────────────────────────────────────
# Static: serve generated PDFs at /reports/<user_id>/latest.pdf
# Rule:
#   - If REPORTS_DIR is set (env) ⇒ use it (Render/prod) and base = Render hostname if available
#   - Else (local dev) ⇒ auto-detect ngrok https; fallback http://localhost:8000
# ──────────────────────────────────────────────────────────────────────────────
try:
    reports_dir, reports_source = resolve_reports_dir_with_source()
    os.makedirs(reports_dir, exist_ok=True)
    app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")
    debug_log(f"📄 Reports mounted at /reports -> {reports_dir} ({reports_source})", tag="startup")

    _REPORTS_BASE = None
    reports_override = (os.getenv("REPORTS_BASE_URL") or os.getenv("PUBLIC_REPORT_BASE_URL") or "").strip()
    if reports_override:
        if not reports_override.startswith(("http://", "https://")):
            reports_override = f"https://{reports_override}"
        _REPORTS_BASE = reports_override.rstrip("/")
        debug_log(f"🔗 Reports base URL (override): {_REPORTS_BASE}/reports", tag="startup")
    else:
        # Prefer deployed host envs first (works even when REPORTS_DIR is not explicitly set).
        render_host = (os.getenv("RENDER_EXTERNAL_HOSTNAME") or "").strip()
        render_url = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
        fallback_base = (
            os.getenv("API_PUBLIC_BASE_URL")
            or os.getenv("PUBLIC_BASE_URL")
            or render_url
            or ""
        ).strip()
        if render_host:
            _REPORTS_BASE = f"https://{render_host}"
            debug_log(f"🔗 Reports base URL (render host): {_REPORTS_BASE}/reports", tag="startup")
        elif fallback_base:
            if not fallback_base.startswith(("http://", "https://")):
                fallback_base = f"https://{fallback_base}"
            _REPORTS_BASE = fallback_base.rstrip("/")
            debug_log(f"🔗 Reports base URL (fallback env): {_REPORTS_BASE}/reports", tag="startup")
        else:
            # Local dev fallback: detect ngrok
            try:
                with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels", timeout=1.5) as resp:
                    data = json.load(resp)
                tunnels = (data or {}).get("tunnels", []) or []
                https = next((t for t in tunnels if str(t.get("public_url", "")).startswith("https://")), None)
                if https:
                    _REPORTS_BASE = str(https.get("public_url", "")).rstrip("/")
                    debug_log(f"🔗 Reports base URL (ngrok): {_REPORTS_BASE}/reports", tag="startup")
                else:
                    _REPORTS_BASE = "http://localhost:8000"
                    print("⚠️ ngrok https tunnel not found; using localhost.")
            except Exception as e:
                _REPORTS_BASE = "http://localhost:8000"
                print(f"⚠️ ngrok detect failed: {e!r}; using localhost.")
except Exception as e:
    print(f"⚠️  Failed to mount /reports: {e!r}")
    _REPORTS_BASE = "http://localhost:8000"


def _public_report_url(user_id: int, filename: str) -> str:
    """Return absolute URL to a user's report file."""
    return f"{_REPORTS_BASE}/reports/{user_id}/{filename}"

def _public_report_url_global(filename: str) -> str:
    """Return absolute URL to a global report file located directly under /reports."""
    return f"{_REPORTS_BASE}/reports/{filename}"

def _write_global_report_bytes(path_under_reports: str, raw_bytes: bytes) -> str:
    """
    Persist bytes to a global path under /reports and return its public URL.
    """
    rel_path = str(path_under_reports or "").strip().replace("\\", "/").lstrip("/")
    if not rel_path or rel_path.endswith("/"):
        raise ValueError("invalid reports path")
    if ".." in rel_path.split("/"):
        raise ValueError("invalid reports path")
    root = _reports_root_global()
    out_path = os.path.join(root, *rel_path.split("/"))
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(raw_bytes)
    return _public_report_url_global(rel_path)

def _promote_reports_file_url(raw_url: str | None, *, target_rel_dir: str) -> str | None:
    """
    Ensure a /reports URL points at /reports/<target_rel_dir>/<filename>.
    If the source file exists under another reports path, copy it into target_rel_dir.
    """
    if not raw_url:
        return None
    normalized = _normalize_reports_url(raw_url) or str(raw_url).strip()
    if not normalized:
        return None
    target = str(target_rel_dir or "").strip().replace("\\", "/").strip("/")
    if not target or ".." in target.split("/"):
        return normalized
    try:
        parsed = urlparse(normalized)
        path = parsed.path or ""
    except Exception:
        return normalized
    if re.match(rf"^/reports/{re.escape(target)}/[^/]+$", path):
        return normalized
    m = re.match(r"^/reports/(.+)/([^/]+)$", path)
    if not m:
        return normalized
    rel_src = str(m.group(1) or "").strip().strip("/")
    filename = str(m.group(2) or "").strip()
    if not filename:
        return normalized
    reports_root = _reports_root_global()
    src_path = os.path.join(reports_root, rel_src, filename)
    dst_rel = f"{target}/{filename}"
    dst_path = os.path.join(reports_root, *target.split("/"), filename)
    try:
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        if os.path.isfile(src_path):
            if os.path.abspath(src_path) != os.path.abspath(dst_path):
                shutil.copyfile(src_path, dst_path)
            return _public_report_url_global(dst_rel)
        if os.path.isfile(dst_path):
            return _public_report_url_global(dst_rel)
    except Exception:
        return normalized
    return normalized

def _promote_library_podcast_url(raw_url: str | None) -> str | None:
    return _promote_reports_file_url(raw_url, target_rel_dir="content/library")

def _promote_intro_podcast_url(raw_url: str | None) -> str | None:
    """
    Ensure intro podcast URLs use /reports/content/intro/<filename>.
    If URL points to /reports/<...>/<filename> and the source file exists, copy it to content/intro/.
    """
    return _promote_reports_file_url(raw_url, target_rel_dir="content/intro")


@api_v1.post("/reports/upload")
def api_reports_upload(payload: dict, request: Request):
    """
    Internal helper to upload report audio bytes from worker to API host.
    Requires REPORTS_UPLOAD_TOKEN and X-Reports-Token header.
    """
    expected = (os.getenv("REPORTS_UPLOAD_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status_code=403, detail="uploads disabled")
    token = (request.headers.get("X-Reports-Token") or "").strip()
    if token != expected:
        raise HTTPException(status_code=401, detail="invalid upload token")
    user_id = payload.get("user_id")
    filename = (payload.get("filename") or "").strip()
    content_b64 = (payload.get("content_b64") or "").strip()
    try:
        user_id = int(user_id)
    except Exception:
        raise HTTPException(status_code=400, detail="user_id must be an integer")
    if user_id <= 0:
        raise HTTPException(status_code=400, detail="user_id must be positive")
    if not filename:
        raise HTTPException(status_code=400, detail="filename required")
    if "/" in filename or "\\" in filename or ".." in filename or filename != os.path.basename(filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    if not content_b64:
        raise HTTPException(status_code=400, detail="content_b64 required")
    try:
        raw = base64.b64decode(content_b64.encode("ascii"), validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid base64 content")
    reports_dir = resolve_reports_dir()
    user_dir = os.path.join(reports_dir, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    out_path = os.path.join(user_dir, filename)
    try:
        with open(out_path, "wb") as f:
            f.write(raw)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"write failed: {e}")
    return {"ok": True, "url": _public_report_url(user_id, filename), "bytes": len(raw)}


# Mount API router after all api_v1 routes are declared.
app.include_router(api_v1)
