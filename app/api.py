# app/api.py
# PATCH — proper API module + robust Twilio webhook (2025-09-04)
# PATCH — 2025-09-11: Add minimal superuser admin endpoints (create user, start, status, assessment)
# PATCH — 2025-09-11: Admin hardening + WhatsApp admin commands (token+DB check; create/start/status/assessment)
from __future__ import annotations

import os
import json
import time
import urllib.request
import secrets
import hashlib
import base64
import re
import subprocess
import sys
import threading
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
)
from .job_queue import ensure_job_table, enqueue_job, should_use_worker, ensure_prompt_settings_schema

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
    Normalize /reports URLs to the current reports base.
    This fixes stale localhost/ngrok/base URLs stored in DB.
    """
    if not raw:
        return None
    url = str(raw).strip()
    if not url:
        return None
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
    if parsed.netloc:
        base_host = urlparse(base).netloc
        if base_host and parsed.netloc == base_host:
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
    "admin kickoff [phone]            # send 12-week kickoff podcast/flow\n"
    "admin coaching [phone] on|off|faston|reset    # toggle scheduled coaching prompts (faston=every 2m test; reset clears jobs)\n"
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


@app.on_event("startup")
async def _startup_init() -> None:
    try:
        from .nudges import ensure_quick_reply_templates
        ensure_quick_reply_templates(always_log=True)
    except Exception:
        pass


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
    reports_dir = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
    if not os.path.isdir(reports_dir):
        return
    removed = 0
    kept = 0
    for root, _dirs, files in os.walk(reports_dir):
        for name in files:
            path = os.path.join(root, name)
            if keep_content and name.lower().startswith("content"):
                kept += 1
                continue
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
    if removed or kept:
        print(f"📄 Reports cleanup: removed={removed} kept={kept} keep_content={keep_content}")


@app.on_event("startup")
def on_startup():
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
    if os.getenv("RESET_DB_ON_STARTUP") == "1":
        keep_prompt_templates = os.getenv("KEEP_PROMPT_TEMPLATES_ON_RESET") == "1"
        keep_content = os.getenv("KEEP_CONTENT_ON_RESET") == "1"
        keep_kb = os.getenv("KEEP_KB_SNIPPETS_ON_RESET") == "1"
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
                keep_tables.update({"kb_snippets", "kb_vectors"})
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

        # Ensure reports dir exists even when not resetting DB
        try:
            reports_dir = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
            os.makedirs(reports_dir, exist_ok=True)
        except Exception as e:
            print(f"⚠️  Could not create reports dir: {e!r}")
    _maybe_set_public_base_via_ngrok()
    _print_env_banner()
    try:
        scheduler.ensure_global_schedule_defaults()
    except Exception as e:
        print(f"⚠️  Could not init global prompt schedule defaults: {e!r}")
    # Start scheduler (user-level auto prompts are handled per preference)
    try:
        scheduler.start_scheduler()
        scheduler.schedule_auto_daily_prompts()
        scheduler.schedule_out_of_session_messages()
    except Exception as e:
        print(f"⚠️  Scheduler start failed: {e!r}")


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


def _get_or_create_user(phone_e164: str) -> User:
    """Find or create a User record by E.164 phone (no whatsapp: prefix)."""
    phone_e164 = _norm_phone(phone_e164)
    with SessionLocal() as s:
        u = s.query(User).filter(User.phone == phone_e164).first()
        if not u:
            club_id = _resolve_default_club_id(s)
            now = datetime.utcnow()
            u = User(first_name=None, surname=None, phone=phone_e164, club_id=club_id,
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


        # Canonical logging (category/sid omitted for inbound unless you have them)
        write_log(
            phone_e164=phone,
            direction="inbound",
            text=body or "",
            category=None,
            twilio_sid=None,
            user=user,
            channel=channel,  # harmless if model lacks 'channel'
            meta={"from": from_raw}  # harmless if model lacks 'meta'
        )
    except Exception as e:
        print(f"⚠️ inbound direct-log failed (non-fatal): {e!r}")


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
    2) TWILIO_WHATSAPP_FROM (extract +CC)
    3) ADMIN_WHATSAPP / ADMIN_PHONE
    4) TWILIO_SMS_FROM
    5) Hard fallback '+44'
    """
    cand = (os.getenv("DEFAULT_COUNTRY_CODE") or "").strip()
    if cand.startswith("+"):
        return cand
    for var in ("TWILIO_WHATSAPP_FROM", "ADMIN_WHATSAPP", "ADMIN_PHONE", "TWILIO_SMS_FROM"):
        v = (os.getenv(var) or "").strip()
        if not v:
            continue
        v = v.replace("whatsapp:", "")
        m = _CC_RE.match(v)
        if m:
            return f"+{m.group(1)}"
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
    # Accept pure digits after stripping separators
    if s.isdigit():
        # UK-style local numbers starting with 0 → drop trunk '0'
        if s.startswith("0"):
            return cc + s[1:]
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


def _handle_admin_command(admin_user: User, text: str) -> bool:
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
            # Usage: admin kickoff <phone> [notes] — run 12-week kickoff flow/podcast
            target_phone, note_parts = _resolve_admin_target_phone(admin_user, args, allow_notes=True)
            notes = " ".join(note_parts).strip() if note_parts else ""
            notes = notes or None
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
                kickoff.start_kickoff(u, notes=notes)
            except Exception as e:
                send_whatsapp(to=admin_user.phone, text=f"Failed to run kickoff: {e}")
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
            target_phone, toggle_parts = _resolve_admin_target_phone(admin_user, args)
            if not toggle_parts:
                send_whatsapp(to=admin_user.phone, text="Usage: admin coaching <phone> on|off|faston|reset")
                return True
            toggle = toggle_parts[0].lower()
            if toggle not in {"on", "off", "faston", "reset"}:
                send_whatsapp(to=admin_user.phone, text="Usage: admin coaching <phone> on|off|faston|reset")
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

        user = _get_or_create_user(phone)

        # Global admin commands (broader scope)
        if body.lower().startswith("global"):
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
            if _is_admin_user(user):
                if _handle_admin_command(user, body):
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
            # Podcast-style kickoff: generate a personalised transcript
            try:
                general_support.clear(user.id)
                from .kickoff import generate_kickoff_podcast_audio
                audio_url, transcript = generate_kickoff_podcast_audio(user.id)
                transcript = transcript or "Generated your kickoff briefing."
                cta = "Please always respond by tapping a button (this keeps our support going)."
                quick_replies = ["All good", "Need help"]
                # Twilio text body limit is 1600 chars; chunk if needed
                if audio_url:
                    send_whatsapp_media(
                        to=user.phone,
                        media_url=audio_url,
                        caption=(
                            f"*Kickoff* Hi { (user.first_name or '').strip().title() or 'there' }, {os.getenv('COACH_NAME','Gia')} here. "
                            "This is your 12-week programme kickoff podcast—give it a listen."
                        ),
                    )
                    send_whatsapp(
                        to=user.phone,
                        text=cta,
                        quick_replies=quick_replies,
                    )
                else:
                    send_whatsapp(
                        to=user.phone,
                        text=(
                            f"*Kickoff* Hi { (user.first_name or '').strip().title() or 'there' }, {os.getenv('COACH_NAME','Gia')} here. "
                            "I couldn’t generate your kickoff audio just now, but the plan is ready—let’s proceed.\n\n"
                            f"{cta}"
                        ),
                        quick_replies=quick_replies,
                    )
                general_support.activate(user.id, source="kickoff", week_no=1, send_intro=False)
            except Exception as e:
                send_whatsapp(to=user.phone, text=f"Couldn't generate kickoff briefing: {e}")
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
                send_whatsapp(to=user.phone, text=f"Kickoff failed: {e}")
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

        # Explicit assessment entry
        if lower_body in {"start", "hi", "hello"}:
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
    return {
        "ok": True,
        "env": ENV,
        "timezone": "Europe/London",
        "app_start_uk": APP_START_UK_STR,
        "uptime_seconds": _uptime_seconds(),
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
        user_phone = user.phone
        code = f"{secrets.randbelow(1_000_000):06d}"
        otp = AuthOtp(
            user_id=user.id,
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
    if channel not in {"auto", "whatsapp", "sms"}:
        raise HTTPException(status_code=400, detail="channel must be auto|whatsapp|sms")
    try:
        channel_used = "whatsapp"
        if channel == "sms":
            send_sms(to=user_phone, text=f"Your HealthSense login code is {code}. It expires in {_OTP_TTL_MINUTES} minutes.")
            channel_used = "sms"
        else:
            try:
                send_whatsapp(to=user_phone, text=f"Your HealthSense login code is {code}. It expires in {_OTP_TTL_MINUTES} minutes.")
            except Exception:
                if channel == "auto":
                    send_sms(to=user_phone, text=f"Your HealthSense login code is {code}. It expires in {_OTP_TTL_MINUTES} minutes.")
                    channel_used = "sms"
                else:
                    raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to send otp: {e}")
    return {
        "otp_id": otp.id,
        "expires_at": otp.expires_at.isoformat(),
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
        s.commit()
        expires_at = session.expires_at
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
        user_phone = user.phone
        code = f"{secrets.randbelow(1_000_000):06d}"
        otp = AuthOtp(
            user_id=user.id,
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
    if channel not in {"auto", "whatsapp", "sms"}:
        raise HTTPException(status_code=400, detail="channel must be auto|whatsapp|sms")
    try:
        channel_used = "whatsapp"
        if channel == "sms":
            send_sms(
                to=user_phone,
                text=f"Your HealthSense password reset code is {code}. It expires in {_OTP_TTL_MINUTES} minutes.",
            )
            channel_used = "sms"
        else:
            try:
                send_whatsapp(
                    to=user_phone,
                    text=f"Your HealthSense password reset code is {code}. It expires in {_OTP_TTL_MINUTES} minutes.",
                )
            except Exception:
                if channel == "auto":
                    send_sms(
                        to=user_phone,
                        text=f"Your HealthSense password reset code is {code}. It expires in {_OTP_TTL_MINUTES} minutes.",
                    )
                    channel_used = "sms"
                else:
                    raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"failed to send otp: {e}")
    return {
        "otp_id": otp.id,
        "expires_at": otp.expires_at.isoformat(),
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
        s.commit()
        expires_at = session.expires_at
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
    with SessionLocal() as s:
        rows = (
            s.query(ContentLibraryItem)
            .filter(ContentLibraryItem.status == "published")
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
        items.append(
            {
                "id": msg.id,
                "ts": msg.created_at.isoformat() if msg.created_at else None,
                "type": "dialog",
                "title": "Message",
                "preview": _preview(msg.text),
                "full_text": (msg.text or "").strip(),
                "is_truncated": _is_truncated(msg.text),
                "direction": msg.direction,
                "channel": msg.channel,
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
            if user_id:
                prompt_rows = (
                    s.query(LLMPromptLog)
                    .filter(
                        LLMPromptLog.created_at >= start_utc,
                        LLMPromptLog.created_at < end_utc,
                        LLMPromptLog.user_id == user_id,
                    )
                    .order_by(LLMPromptLog.created_at.desc())
                    .limit(prompt_fetch_limit)
                    .all()
                )
                prompt_rows_null = (
                    s.query(LLMPromptLog)
                    .filter(
                        LLMPromptLog.created_at >= start_utc,
                        LLMPromptLog.created_at < end_utc,
                        LLMPromptLog.user_id.is_(None),
                    )
                    .order_by(LLMPromptLog.created_at.desc())
                    .limit(prompt_fetch_limit)
                    .all()
                )
                prompt_rows.extend(prompt_rows_null)
            else:
                prompt_rows = (
                    s.query(LLMPromptLog)
                    .filter(LLMPromptLog.created_at >= start_utc, LLMPromptLog.created_at < end_utc)
                    .order_by(LLMPromptLog.created_at.desc())
                    .limit(prompt_fetch_limit)
                    .all()
                )
            for prompt in prompt_rows:
                prompt_map.setdefault(prompt.id, prompt)

    by_prompt: dict[int, dict] = {}
    for prompt in prompt_map.values():
        pid = int(prompt.id)
        resolved_user_id = _extract_prompt_user_id(prompt)
        prompt_text_full = _coerce_prompt_text(prompt.assembled_prompt or prompt.prompt_text or "")
        response_text_full = _coerce_prompt_text(prompt.response_preview) if prompt.response_preview else ""
        by_prompt[pid] = {
            "prompt_id": pid,
            "created_at": prompt.created_at.isoformat() if prompt.created_at else None,
            "user_id": resolved_user_id,
            "touchpoint": prompt.touchpoint,
            "model": prompt.model,
            "prompt_variant": prompt.prompt_variant,
            "task_label": prompt.task_label,
            "prompt_preview": (prompt_text_full or "")[:400],
            "response_preview": (response_text_full or "")[:400] if response_text_full else None,
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

    rows_out: list[dict] = []
    for entry in by_prompt.values():
        if user_id is not None and not entry.get("match_user"):
            continue
        rate_in = float(entry.get("rate_in") or default_rate_in or 0.0)
        rate_out = float(entry.get("rate_out") or default_rate_out or 0.0)
        if not entry["tokens_in"] and entry.get("prompt_text_full"):
            entry["tokens_in"] = float(estimate_tokens(entry.get("prompt_text_full")))
        if not entry["tokens_out"] and entry.get("response_text_full"):
            entry["tokens_out"] = float(estimate_tokens(entry.get("response_text_full")))
        calc_cost = (entry["tokens_in"] / 1_000_000.0) * rate_in + (entry["tokens_out"] / 1_000_000.0) * rate_out
        cost_est = entry.get("cost_est_gbp") or 0.0
        if not cost_est and calc_cost:
            cost_est = calc_cost
        rate_source = entry.get("rate_source") or default_rate_source
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
        rate_in = float(rates.get("llm_gbp_per_1m_input_tokens") or 0.0)
        rate_out = float(rates.get("llm_gbp_per_1m_output_tokens") or 0.0)
        rate_source = "db" if rates.get("llm_gbp_per_1m_input_tokens") is not None else "env"
        _rows_all, totals = _build_prompt_cost_rows(
            start_utc=start_utc,
            end_utc=end_utc,
            user_id=user_id,
            limit_val=200,
            default_rate_in=rate_in,
            default_rate_out=rate_out,
            default_rate_source=rate_source,
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
    default_rate_in = float(rates.get("llm_gbp_per_1m_input_tokens") or 0.0)
    default_rate_out = float(rates.get("llm_gbp_per_1m_output_tokens") or 0.0)
    default_rate_source = "db" if rates.get("llm_gbp_per_1m_input_tokens") is not None else "env"
    rows_all, totals = _build_prompt_cost_rows(
        start_utc=start_utc,
        end_utc=end_utc,
        user_id=user_id,
        limit_val=limit_val,
        default_rate_in=default_rate_in,
        default_rate_out=default_rate_out,
        default_rate_source=default_rate_source,
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
    rates = fetch_provider_rates()
    keys = [
        "tts_gbp_per_1m_chars",
        "tts_chars_per_min",
        "llm_gbp_per_1m_input_tokens",
        "llm_gbp_per_1m_output_tokens",
        "wa_gbp_per_message",
        "wa_gbp_per_media_message",
        "wa_gbp_per_template_message",
    ]
    updated_keys = [k for k in keys if rates.get(k) is not None]
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
            touchpoint = str(payload.get("touchpoint") or "").strip()
            from_state = prompts_module._canonical_state(payload.get("from_state") or "")
            if touchpoint and from_state:
                state_candidates = [
                    from_state,
                    "stage" if from_state == "beta" else from_state,
                    "production" if from_state == "live" else from_state,
                ]
                row = (
                    s.query(PromptTemplate)
                    .filter(
                        PromptTemplate.touchpoint == touchpoint,
                        PromptTemplate.state.in_(state_candidates),
                    )
                    .order_by(PromptTemplate.version.desc(), PromptTemplate.id.desc())
                    .first()
                )
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
            from .llm import _llm as shared_llm, api_key as llm_api_key
            from langchain_openai import ChatOpenAI
            t0 = time.perf_counter()
            client = shared_llm
            if model_override:
                client = ChatOpenAI(model=model_override, temperature=0, api_key=llm_api_key)
            resp = client.invoke(assembly.text)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            content = (getattr(resp, "content", "") or "").strip()
            return {
                "model": model_override or getattr(shared_llm, "model_name", None),
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
            parts = [
                ("system", settings.get("system_block") or prompts_module.common_prompt_header("Assessor", "User", "UK")),
                ("locale", settings.get("locale_block") or prompts_module.locale_block("UK")),
                ("context", "assessor system placeholder"),
                ("assessor", sys_text),
                ("task", "(task from template)"),
                ("user", "(user input)"),
            ]
            parts, order_override = prompts_module._apply_prompt_template(parts, prompts_module._load_prompt_template("assessor_system"))
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
            from .llm import _llm as shared_llm, api_key as llm_api_key
            from langchain_openai import ChatOpenAI
            t0 = time.perf_counter()
            client = shared_llm
            if model_override:
                client = ChatOpenAI(model=model_override, temperature=0, api_key=llm_api_key)
            resp = client.invoke(text)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            content = (getattr(resp, "content", "") or "").strip()
            llm_result = {
                "model": model_override or getattr(shared_llm, "model_name", None),
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
                audio_user_id = gen.user_id or getattr(admin_user, "id", None)
                if not audio_user_id:
                    podcast_error = "No user available for audio generation."
                else:
                    filename = f"content-gen-{gen.id}.mp3"
                    try:
                        podcast_url = generate_podcast_audio_for_voice(
                            transcript=gen.llm_content,
                            user_id=int(audio_user_id),
                            filename=filename,
                            voice_override=podcast_voice,
                            usage_tag="content_generation",
                        )
                        if not podcast_url:
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
            row.podcast_url = (payload.get("podcast_url") or "").strip() or None
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
            for uid, val, updated_at in coaching_rows:
                if not uid:
                    continue
                existing = coaching_pref.get(int(uid))
                if existing and existing[0] and updated_at and updated_at <= existing[0]:
                    continue
                coaching_pref[int(uid)] = (updated_at, str(val or ""))

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
                "latest_run_id": run_id,
                "latest_run_finished_at": latest_finished.get(run_id) if run_id else None,
                "status": status,
                "prompt_state_override": prompt_overrides.get(u.id, ""),
                "coaching_enabled": (coaching_pref.get(u.id, (None, "0"))[1].strip() == "1"),
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

    status = "idle"
    if active:
        status = "in_progress"
    elif latest_run and getattr(latest_run, "finished_at", None):
        status = "completed"

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
    reports_dir = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    app.mount("/reports", StaticFiles(directory=reports_dir), name="reports")
    debug_log(f"📄 Reports mounted at /reports -> {reports_dir}", tag="startup")

    _REPORTS_BASE = None
    reports_override = (os.getenv("REPORTS_BASE_URL") or os.getenv("PUBLIC_REPORT_BASE_URL") or "").strip()
    if reports_override:
        if not reports_override.startswith(("http://", "https://")):
            reports_override = f"https://{reports_override}"
        _REPORTS_BASE = reports_override.rstrip("/")
        debug_log(f"🔗 Reports base URL (override): {_REPORTS_BASE}/reports", tag="startup")
    elif os.getenv("REPORTS_DIR"):
        # Production/deployed: prefer Render external hostname
        render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME")
        if render_host:
            _REPORTS_BASE = f"https://{render_host}"
        else:
            fallback_base = (
                os.getenv("API_PUBLIC_BASE_URL")
                or os.getenv("PUBLIC_BASE_URL")
                or os.getenv("RENDER_EXTERNAL_URL")
                or ""
            ).strip()
            if fallback_base:
                if not fallback_base.startswith(("http://", "https://")):
                    fallback_base = f"https://{fallback_base}"
                _REPORTS_BASE = fallback_base.rstrip("/")
            else:
                _REPORTS_BASE = "http://localhost:8000"
        debug_log(f"🔗 Reports base URL (REPORTS_DIR set): {_REPORTS_BASE}/reports", tag="startup")
    else:
        # Local dev: detect ngrok
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
    reports_dir = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
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
