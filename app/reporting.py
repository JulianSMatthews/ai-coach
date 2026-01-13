# app/reporting.py
from __future__ import annotations

import os
from datetime import datetime, date, timedelta, timezone
import html
import json
from collections import defaultdict
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:
    ZoneInfo = None  # type: ignore
from typing import Optional, Dict, Any, List, Tuple
import textwrap

from .db import SessionLocal
from .okr import (
    _build_state_context_from_models,
    _answers_from_state_context,
    _guess_concept_from_description,
    _normalize_concept_key,
)
from .models import (
    AssessmentRun,
    PillarResult,
    User,
    JobAudit,
    UserConceptState,
    AssessmentTurn,
    OKRCycle,
    OKRObjective,
    OKRKeyResult,
    WeeklyFocus,
    WeeklyFocusKR,
    PsychProfile,
    UserPreference,
    Club,
    OKRKrEntry,
    PromptTemplate,
    PromptSettings,
    LLMPromptLog,
)
from . import llm as shared_llm
from .prompts import (
    coaching_approach_prompt,
    assessment_scores_prompt,
    okr_narrative_prompt,
    log_llm_prompt,
    _ensure_llm_prompt_log_schema,
    build_prompt,
    kr_payload_list,
    _canonical_state,
    PromptAssembly,
)

# For raw SQL fallback when OKR models are unavailable
from sqlalchemy import text, select
from sqlalchemy.orm import selectinload

# Optional scheduler import for introspection helpers (guarded to avoid hard failures)
try:
    from . import scheduler as _sched  # type: ignore
except Exception:
    _sched = None  # type: ignore

# Optional OKR tables – support both naming variants in models.py
OkrObjective = None  # type: ignore
OkrKeyResult = None  # type: ignore
try:
    # Preferred snake-camel variant
    from .models import OkrObjective as _O1, OkrKeyResult as _K1  # type: ignore
    OkrObjective, OkrKeyResult = _O1, _K1
except Exception:
    try:
        # Alternate ALLCAPS variant
        from .models import OKRObjective as _O2, OKRKeyResult as _K2  # type: ignore
        OkrObjective, OkrKeyResult = _O2, _K2
    except Exception:
        OkrObjective, OkrKeyResult = None, None  # type: ignore

# Audit/logging controls (silence console by default)
AUDIT_TO_CONSOLE = os.getenv("AUDIT_TO_CONSOLE", "0") == "1"
AUDIT_TO_DB = os.getenv("AUDIT_TO_DB", "1") == "1"
BRAND_NAME = (os.getenv("BRAND_NAME") or "HealthSense").strip()
BRAND_YEAR = os.getenv("BRAND_YEAR") or str(datetime.utcnow().year)
BRAND_FOOTER = f"© {BRAND_YEAR} {BRAND_NAME}. All rights reserved." if BRAND_NAME else ""
DEBUG_PROGRESS_BASELINES = os.getenv("DEBUG_PROGRESS_BASELINES", "0") == "1"
FONT_FACE = (
    "@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@500;600&family=Inter:wght@400;500;600&display=swap'); "
    "body { font-family: 'Inter', system-ui, -apple-system, sans-serif; color:#101828; } "
    "h1, h2, h3, h4, h5, h6 { font-family: 'Outfit', 'Inter', system-ui, sans-serif; }"
)

def _audit(job: str, status: str = "ok", payload: Dict[str, Any] | None = None, error: str | None = None) -> None:
    if AUDIT_TO_CONSOLE:
        try:
            print(f"[AUDIT] {job} status={status} payload={(payload or {})} err={error or ''}")
        except Exception:
            pass
    if not AUDIT_TO_DB:
        return
    try:
        with SessionLocal() as s:
            s.add(JobAudit(job_name=job, status=status, payload=payload or {}, error=error or None))
            s.commit()
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# Report generation (PDF via reportlab)
# ──────────────────────────────────────────────────────────────────────────────

def _reports_root_for_user(user_id: int) -> str:
    """
    Determine the filesystem directory where reports should be written.
    Uses REPORTS_DIR env var if set, otherwise ./public/reports/{user_id}.
    """
    base = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
    path = os.path.join(base, str(user_id))
    os.makedirs(path, exist_ok=True)
    return path

# Global reports output directory (not per-user)
def _reports_root_global() -> str:
    """
    Global reports output directory. Uses REPORTS_DIR if set, otherwise ./public/reports
    """
    base = os.getenv("REPORTS_DIR") or os.path.join(os.getcwd(), "public", "reports")
    os.makedirs(base, exist_ok=True)
    return base

def _date_from_str(val: str | None) -> date | None:
    if not val:
        return None
    try:
        return date.fromisoformat(val)
    except Exception:
        return None

def _assemble_prompt_for_report(touchpoint: str, user_id: int, as_of_date: date | None = None, state: str = "live") -> PromptAssembly:
    """
    Assemble a prompt for reporting purposes using the same builder/tester data sources.
    """
    try:
        from .kickoff import (
            _latest_assessment as kickoff_latest_assessment,
            _latest_psych as kickoff_latest_psych,
            _okr_by_pillar as kickoff_okr_by_pillar,
            _programme_blocks as kickoff_programme_blocks,
        )
        from .okr import okr_payload_list, okr_payload, okr_payload_primary

        tp_lower = touchpoint.lower()
        extra_kwargs = {}
        run, pillars = kickoff_latest_assessment(user_id)
        psych = kickoff_latest_psych(user_id)
        scores_payload = [
            {"pillar": getattr(p, "pillar_key", ""), "score": int(getattr(p, "overall", 0) or 0)}
            for p in (pillars or [])
        ]
        psych_payload = {}
        if psych:
            psych_payload = {
                "section_averages": getattr(psych, "section_averages", None),
                "flags": getattr(psych, "flags", None),
                "parameters": getattr(psych, "parameters", None),
            }
        programme = kickoff_programme_blocks(getattr(run, "started_at", None) or getattr(run, "created_at", None))
        first_block = programme[0] if programme else None

        if tp_lower in {"podcast_kickoff", "podcast_weekstart"}:
            extra_kwargs.update(
                {"scores": scores_payload, "psych_payload": psych_payload, "programme": programme, "first_block": first_block}
            )
            if tp_lower == "podcast_kickoff":
                extra_kwargs["okrs_by_pillar"] = {
                    k: [kr.description for kr in v] for k, v in (kickoff_okr_by_pillar(int(user_id)) or {}).items()
                }
            if tp_lower == "podcast_weekstart":
                extra_kwargs["week_no"] = 1
                if first_block and first_block.get("pillar_key"):
                    extra_kwargs["focus_pillar"] = first_block.get("pillar_key")

        krs_payload = kr_payload_list(int(user_id), max_krs=3)
        if tp_lower in {"weekstart_support"}:
            extra_kwargs.update({"scores": scores_payload, "psych_payload": psych_payload, "krs_payload": krs_payload, "history": []})
        if tp_lower == "weekstart_actions":
            extra_kwargs.update({"krs": krs_payload, "transcript": ""})
        if tp_lower in {"tuesday", "midweek", "sunday"}:
            # include KR payload for OKR block; history placeholder
            extra_kwargs.update({"scores": scores_payload, "psych_payload": psych_payload, "history_text": "", "krs": krs_payload})
        if tp_lower in {"podcast_thursday", "podcast_friday"}:
            extra_kwargs.update({"history_text": "", "krs": krs_payload})
        # Assessment/report prompts: build via dedicated helpers
        if tp_lower == "assessment_scores":
            from .prompts import assessment_scores_prompt
            combined = int(round(sum((p.get("score") or 0) for p in scores_payload) / max(len(scores_payload), 1))) if scores_payload else 0
            return assessment_scores_prompt("User", combined, scores_payload)
        if tp_lower == "assessment_approach":
            from .prompts import coaching_approach_prompt
            return coaching_approach_prompt(
                "User",
                section_averages=psych_payload.get("section_averages", {}) if psych_payload else {},
                flags=psych_payload.get("flags", {}) if psych_payload else {},
                parameters=psych_payload.get("parameters", {}) if psych_payload else {},
                locale="UK",
            )
        if tp_lower == "assessment_okr":
            from .prompts import okr_narrative_prompt
            okr_payload = okr_payload_list(user_id, week_no=None, max_krs=None)
            return okr_narrative_prompt("User", okr_payload)
        if tp_lower == "assessor_system":
            # No assembly; return placeholder
            return PromptAssembly(
                text="(assessor system prompts are generated at runtime per concept)",
                blocks={"system": "(assessor system prompt)"},
                variant=touchpoint,
                task_label=touchpoint,
                block_order=["system"],
                meta={},
            )

        assembly = build_prompt(
            touchpoint=touchpoint,
            user_id=int(user_id),
            coach_name="Coach",
            user_name="User",
            locale="UK",
            use_state=state,
            as_of_date=as_of_date,
            **extra_kwargs,
        )
        return assembly
    except Exception as e:
        return PromptAssembly(
            text=f"(failed to assemble prompt: {e})",
            blocks={},
            variant=touchpoint,
            task_label=touchpoint,
            block_order=[],
            meta={"error": str(e)},
        )


def _report_link(user_id: int, filename: str) -> str:
    """
    Build an HTTP-ish report link to a user report file.
    Priority: REPORTS_BASE_URL > PUBLIC_REPORT_BASE_URL > PUBLIC_BASE_URL > RENDER_EXTERNAL_URL.
    Falls back to relative /reports/... if none are set.
    """
    try:
        from .api import _public_report_url  # type: ignore
        return _public_report_url(user_id, filename)
    except Exception:
        pass
    base = (
        os.getenv("REPORTS_BASE_URL")
        or os.getenv("PUBLIC_REPORT_BASE_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or ""
    ).strip()
    path = f"/reports/{user_id}/{filename}".replace("//", "/")
    if base:
        prefix = base if base.startswith(("http://", "https://")) else f"https://{base}"
        return f"{prefix.rstrip('/')}{path}"
    return path


def _load_user_preferences(user_id: int) -> dict[str, str]:
    if not user_id:
        return {}
    prefs: dict[str, str] = {}
    with SessionLocal() as s:
        rows = (
            s.query(UserPreference.key, UserPreference.value)
             .filter(UserPreference.user_id == user_id)
             .all()
        )
        for key, value in rows:
            if key:
                prefs[key] = value or ""
    return prefs


def _short_text(text: str | None, limit: int = 200) -> str:
    if not text:
        return ""
    txt = text.strip()
    if len(txt) <= limit:
        return txt
    return txt[: limit - 1].rstrip() + "…"


def _kr_notes_dict(notes: str | None) -> dict:
    if not notes:
        return {}
    try:
        data = json.loads(notes)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _progress_debug(message: str, payload: dict | None = None) -> None:
    if not DEBUG_PROGRESS_BASELINES:
        return
    try:
        print(f"[REPORT][KR] {message} :: {payload or {}}")
    except Exception:
        pass


def _collect_run_dialogue(run_id: int, limit_per_pillar: int = 3) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    with SessionLocal() as s:
        rows = (
            s.query(AssessmentTurn)
             .filter(AssessmentTurn.run_id == run_id)
             .order_by(AssessmentTurn.idx.asc())
             .all()
        )
    for row in rows:
        if not getattr(row, "user_a", None):
            continue
        pillar = (getattr(row, "pillar", None) or "combined").lower()
        bucket = out[pillar]
        if len(bucket) >= limit_per_pillar:
            continue
        bucket.append({
            "question": _short_text(getattr(row, "assistant_q", ""), 220),
            "answer": _short_text(getattr(row, "user_a", ""), 220),
            "concept": getattr(row, "concept_key", None)
        })
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Scheduler reporting helpers
# ──────────────────────────────────────────────────────────────────────────────

def user_schedule_report(user_id: int) -> List[Dict[str, Any]]:
    """
    Return a readable snapshot of scheduled jobs for a user (job id suffix match).
    Includes trigger and next run time in UTC and the user's local timezone.
    """

    def _from_jobstore_table(tz_local):
        rows: List[Dict[str, Any]] = []
        try:
            with SessionLocal() as s:
                res = s.execute(text("SELECT id, next_run_time FROM apscheduler_jobs"))
                for rid, next_run in res.fetchall():
                    if not rid or not str(rid).endswith(f"_{user_id}"):
                        continue
                    try:
                        ts = float(next_run)
                        dt_utc = datetime.fromtimestamp(ts, tz=timezone.utc)
                        dt_local = dt_utc.astimezone(tz_local) if tz_local else None
                    except Exception:
                        dt_utc, dt_local = None, None
                    rows.append(
                        {
                            "id": rid,
                            "trigger": "jobstore",
                            "next_run_utc": dt_utc.isoformat() if dt_utc else None,
                            "next_run_local": dt_local.isoformat() if dt_local else None,
                        }
                    )
        except Exception:
            return []
        return rows

    def _tz_for_user(u: User | None):
        if not u:
            return None
        try:
            tz_name = getattr(u, "tz", None) or "UTC"
            return ZoneInfo(tz_name) if ZoneInfo else None
        except Exception:
            return None

    user = None
    try:
        with SessionLocal() as s:
            user = s.get(User, user_id)
    except Exception:
        user = None
    tz = _tz_for_user(user)

    out: List[Dict[str, Any]] = []
    if _sched and getattr(_sched, "scheduler", None):
        # Primary path: live scheduler instance (loads jobs into memory)
        try:
            for job in _sched.scheduler.get_jobs():
                parts = job.id.split("_")
                if not parts or parts[-1] != str(user_id):
                    continue
                next_utc = job.next_run_time
                next_local = next_utc.astimezone(tz) if next_utc and tz else None
                out.append(
                    {
                        "id": job.id,
                        "trigger": str(job.trigger),
                        "next_run_utc": next_utc.isoformat() if next_utc else None,
                        "next_run_local": next_local.isoformat() if next_local else None,
                    }
                )
        except Exception:
            out = []
    if not out:
        # Fallback: query the jobstore table directly (covers cases where scheduler is not started in this process)
        out = _from_jobstore_table(tz)
    return sorted(out, key=lambda r: r.get("next_run_utc") or "")


def generate_schedule_report_html(user_id: int, filename: str = "schedule.html") -> str:
    """
    Build a simple HTML report of scheduled jobs for a user and return the public link.
    """
    rows = user_schedule_report(user_id)
    with SessionLocal() as s:
        u = s.get(User, user_id)
    name = (getattr(u, "first_name", "") or "").strip() or "User"
    phone = getattr(u, "phone", "") or ""
    tz_name = getattr(u, "tz", None) or "UTC"
    table_rows = []
    for r in rows:
        table_rows.append(
            "<tr>"
            f"<td>{html.escape(r.get('id') or '')}</td>"
            f"<td>{html.escape(r.get('trigger') or '')}</td>"
            f"<td>{html.escape(r.get('next_run_local') or '—')}</td>"
            f"<td>{html.escape(r.get('next_run_utc') or '—')}</td>"
            "</tr>"
        )
    body = (
        "<p>No scheduled jobs found.</p>"
        if not table_rows
        else (
            "<table>"
            "<thead><tr><th>Job ID</th><th>Trigger</th><th>Next run (local)</th><th>Next run (UTC)</th></tr></thead>"
            f"<tbody>{''.join(table_rows)}</tbody></table>"
        )
    )
    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Schedule for {html.escape(name)}</title>
  <style>
    {FONT_FACE}
    body {{ padding: 16px; }}
    h1 {{ font-size: 20px; margin: 0 0 4px; }}
    .meta {{ color: #555; margin-bottom: 12px; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; font-size: 14px; }}
    th {{ background: #f5f5f5; text-align: left; }}
    tr:nth-child(even) {{ background: #fafafa; }}
  </style>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</head>
<body>
  <h1>Schedule for {html.escape(name)}</h1>
  <div class="meta">
    Phone: {html.escape(phone)} &nbsp;|&nbsp; TZ: {html.escape(tz_name)}<br/>
    Generated: {datetime.utcnow().isoformat()}Z
  </div>
  {body}
</body>
</html>
"""
    out_dir = _reports_root_for_user(user_id)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return _report_link(user_id, filename)


def _llm_text_to_html(text: str) -> str:
    parts = [ln.strip() for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]
    if not parts:
        return ""
    return "".join(f"<p>{html.escape(p)}</p>" for p in parts)


def generate_llm_prompt_log_report_html(user_id: int, limit: int = 100) -> str:
    """
    Render the latest LLM prompt logs for a user as an HTML report and return the public link.
    """
    _ensure_llm_prompt_log_schema()
    try:
        limit = int(limit)
    except Exception:
        limit = 100
    limit = max(1, min(limit, 500))

    with SessionLocal() as s:
        user = s.get(User, user_id)
        rows = s.execute(
            text(
                """
                SELECT id, created_at, touchpoint, model, prompt_variant, task_label,
                       block_order, system_block, developer_block, policy_block, tool_block,
                       locale_block, okr_block, okr_scope, scores_block, habit_block,
                       task_block, user_block, extra_blocks, assembled_prompt,
                       response_preview, context_meta
                FROM llm_prompt_logs_view
                WHERE user_id = :uid
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"uid": user_id, "lim": limit},
        ).fetchall()

    name = _display_full_name(user) if user else f"User {user_id}"
    phone = getattr(user, "phone", "") if user else ""

    def _esc(val: Any) -> str:
        if val is None:
            return ""
        return html.escape(str(val))

    def _pre(val: Any) -> str:
        if val is None:
            return ""
        if isinstance(val, (dict, list)):
            try:
                val = json.dumps(val, ensure_ascii=False, indent=2)
            except Exception:
                val = str(val)
        return f"<pre style='white-space:pre-wrap; margin:4px 0 0 0;'>{_esc(val)}</pre>"

    cards = []
    for r in rows:
        block_rows = []
        for label, key in [
            ("System", "system_block"),
            ("Developer", "developer_block"),
            ("Policy", "policy_block"),
            ("Tool", "tool_block"),
            ("Locale", "locale_block"),
            ("OKR", "okr_block"),
            ("OKR scope", "okr_scope"),
            ("Scores", "scores_block"),
            ("Habit", "habit_block"),
            ("Task", "task_block"),
            ("User", "user_block"),
        ]:
            val = getattr(r, key, None)
            if val:
                block_rows.append(f"<tr><th>{label}</th><td>{_pre(val)}</td></tr>")
        if getattr(r, "extra_blocks", None):
            block_rows.append(f"<tr><th>Extra blocks</th><td>{_pre(r.extra_blocks)}</td></tr>")

        block_order_val = getattr(r, "block_order", None)
        if isinstance(block_order_val, (list, dict)):
            try:
                block_order_val = json.dumps(block_order_val, ensure_ascii=False)
            except Exception:
                block_order_val = str(block_order_val)

        cards.append(
            "<div class='card'>"
            f"<div class='meta'>#{r.id} · {r.created_at} · { _esc(getattr(r, 'touchpoint', '') )}</div>"
            f"<div class='headline'><strong>Variant:</strong> {_esc(getattr(r, 'prompt_variant', ''))} &nbsp; "
            f"<strong>Task:</strong> {_esc(getattr(r, 'task_label', ''))} &nbsp; "
            f"<strong>Model:</strong> {_esc(getattr(r, 'model', ''))}</div>"
            f"<div class='meta'>Block order: {_esc(block_order_val)}</div>"
            "<table class='blocks'>" + "".join(block_rows) + "</table>"
            "<div class='section'><div class='label'>Assembled prompt</div>"
            f"{_pre(getattr(r, 'assembled_prompt', None))}</div>"
            "<div class='section'><div class='label'>Response preview</div>"
            f"{_pre(getattr(r, 'response_preview', None))}</div>"
            "<div class='section'><div class='label'>Context meta</div>"
            f"{_pre(getattr(r, 'context_meta', None))}</div>"
            "</div>"
        )

    cards_html = "".join(cards) if cards else "<p>No prompt logs found for this user.</p>"
    css = f"""
    <style>
      {FONT_FACE}
      body { margin:24px; }
      h1 { margin:0 0 6px 0; }
      .meta { color:#475467; margin:4px 0; font-size:0.9rem; }
      .card { border:1px solid #e4e7ec; border-radius:12px; padding:14px; margin:14px 0; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,0.04); }
      .headline { font-size:0.95rem; margin:6px 0; color:#0f172a; }
      table.blocks { width:100%; border-collapse: collapse; margin:10px 0; }
      table.blocks th { width:120px; text-align:left; vertical-align: top; padding:8px; background:#f8fafc; border:1px solid #e4e7ec; color:#0f172a; }
      table.blocks td { padding:8px; border:1px solid #e4e7ec; vertical-align: top; background:#fff; }
      .section { margin:10px 0; }
      .section .label { font-weight:700; color:#0f172a; margin-bottom:4px; }
      pre { font-family: ui-monospace, SFMono-Regular, SFMono, Menlo, Consolas, monospace; font-size:13px; background:#f9fafb; padding:8px; border-radius:8px; border:1px solid #e4e7ec; }
    </style>
    """
    html_doc = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>LLM Prompt Logs — {html.escape(name)}</title>
  {css}
  <meta name="viewport" content="width=device-width, initial-scale=1" />
</head>
<body>
  <h1>LLM Prompt Logs</h1>
  <div class="meta">User: {html.escape(name)} &nbsp;|&nbsp; Phone: {html.escape(phone)} &nbsp;|&nbsp; Limit: {limit} &nbsp;|&nbsp; Generated: {datetime.utcnow().isoformat()}Z</div>
  {cards_html}
  <div class="report-footer">{BRAND_FOOTER}</div>
</body>
</html>
"""
    out_dir = _reports_root_for_user(user_id)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "llm_review.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return _report_link(user_id, "llm_review.html")


def _coaching_approach_text(user_id: int, first_name: str | None = None) -> str:
    with SessionLocal() as s:
        prof = (
            s.query(PsychProfile)
            .filter(PsychProfile.user_id == user_id)
            .order_by(PsychProfile.completed_at.desc().nullslast(), PsychProfile.id.desc())
            .first()
        )
    if not prof:
        return ""
    flags = getattr(prof, "flags", {}) or {}
    params = getattr(prof, "parameters", {}) or {}
    sec = getattr(prof, "section_averages", {}) or {}
    name = (first_name or "").strip() or "you"
    client = getattr(shared_llm, "_llm", None)
    text = ""
    if client:
        assembly = coaching_approach_prompt(name, sec, flags, params)
        prompt = assembly.text
        try:
            import time
            t0 = time.perf_counter()
            resp = client.invoke(prompt)
            duration_ms = int((time.perf_counter() - t0) * 1000)
            candidate = (getattr(resp, "content", None) or "").strip()
            if candidate:
                text = candidate
            try:
                log_llm_prompt(
                    user_id=user_id,
                    touchpoint="coaching_approach",
                    prompt_text=prompt,
                    model=getattr(resp, "model", None),
                    response_preview=text[:200] if text else None,
                    context_meta={"profile_id": getattr(prof, "id", None)},
                    prompt_variant="coaching_approach",
                    task_label="coaching_approach",
                    prompt_blocks={**assembly.blocks, **(assembly.meta or {})},
                    block_order=assembly.block_order,
                    duration_ms=duration_ms,
                )
            except Exception:
                pass
        except Exception:
            text = ""
    if not text:
        parts = []
        if flags.get("low_readiness"):
            parts.append("We’ll keep goals small and build early wins.")
        if flags.get("stress_sensitive"):
            parts.append("We’ll use gentle pacing and add resilience support.")
        if flags.get("low_self_reg") or flags.get("high_accountability"):
            parts.append("I’ll bring more structure and simple scheduling prompts.")
        if flags.get("perfectionism"):
            parts.append("We’ll avoid all-or-nothing and allow slips.")
        if flags.get("high_readiness"):
            parts.append("If you want, we can progress faster.")
        text = " ".join(parts) or "I’ll tailor goals and support to your current capacity and style."
    return text




def _score_narrative_from_llm(user: User, combined: int, payload: list[dict]) -> str:
    if not payload:
        return ""
    name = (getattr(user, "first_name", None) or "the member").strip()
    assembly = assessment_scores_prompt(name, combined, payload)
    prompt = assembly.text
    try:
        import time
        t0 = time.perf_counter()
        resp = _llm.invoke(prompt)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        text = resp.content.strip() if hasattr(resp, "content") else str(resp).strip()
        try:
            log_llm_prompt(
                user_id=getattr(user, "id", None),
                touchpoint="assessment_scores",
                prompt_text=prompt,
                model=getattr(resp, "model", None),
                response_preview=text[:200] if text else None,
                context_meta={"combined": combined, "scores": payload},
                prompt_variant="assessment_scores",
                task_label="assessment_scores",
                prompt_blocks={**assembly.blocks, **(assembly.meta or {})},
                block_order=assembly.block_order,
                duration_ms=duration_ms,
            )
        except Exception:
            pass
    except Exception:
        return ""
    return _llm_text_to_html(text)


def _okr_narrative_from_llm(user: User, payload: list[dict]) -> str:
    if not payload:
        return ""
    name = (getattr(user, "first_name", None) or "you").strip()
    assembly = okr_narrative_prompt(name, payload)
    prompt = assembly.text
    try:
        import time
        t0 = time.perf_counter()
        resp = _llm.invoke(prompt)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        text = resp.content.strip() if hasattr(resp, "content") else str(resp).strip()
        try:
            log_llm_prompt(
                user_id=getattr(user, "id", None),
                touchpoint="assessment_okr",
                prompt_text=prompt,
                model=getattr(resp, "model", None),
                response_preview=text[:200] if text else None,
                context_meta={"okr_payload": payload},
                prompt_variant="assessment_okr",
                task_label="assessment_okr",
                prompt_blocks={**assembly.blocks, **(assembly.meta or {})},
                block_order=assembly.block_order,
                duration_ms=duration_ms,
            )
        except Exception:
            pass
    except Exception:
        return ""
    return _llm_text_to_html(text)


def _scores_narrative_fallback(combined: int, payload: list[dict]) -> str:
    parts = [
        (
            f"<p>Your combined wellbeing score is <strong>{int(round(combined))}/100</strong>. "
            "Keep leaning on the stronger habits while giving extra care to the areas that dip.</p>"
        )
    ]
    if payload:
        bullet = "".join(
            f"<li><strong>{html.escape(item['pillar_name'])}</strong>: "
            f"{item.get('score', '–')}/100</li>"
            for item in payload
        )
        parts.append(f"<p>Pillar snapshot:</p><ul>{bullet}</ul>")
    return "".join(parts)


def _okr_narrative_fallback(payload: list[dict]) -> str:
    if not payload:
        return "<p>Your Objectives and Key Results will appear once an assessment finishes.</p>"
    bullet = "".join(
        f"<li><strong>{html.escape(item['pillar_name'])}</strong>: "
        f"{html.escape(item.get('objective') or 'Objective coming soon.')}</li>"
        for item in payload
    )
    return "<p>Quarterly focus:</p><ul>" + bullet + "</ul>"


def generate_global_users_html() -> str:
    """
    Render a simple HTML table listing all users and core metadata (id, club_id, names, phone, roles, consent).
    Returns the absolute filesystem path to the generated HTML file.
    """
    with SessionLocal() as s:
        users = (
            s.execute(
                select(User).order_by(User.id.asc())
            )
            .scalars()
            .all()
        )
        user_ids = [getattr(u, "id", None) for u in users if getattr(u, "id", None) is not None]
        runs = []
        if user_ids:
            runs = (
                s.query(AssessmentRun)
                 .filter(AssessmentRun.finished_at.isnot(None))
                 .filter(AssessmentRun.user_id.in_(user_ids))
                 .order_by(AssessmentRun.user_id.asc(), AssessmentRun.finished_at.desc())
                 .all()
            )

    latest_run_by_user: dict[int, AssessmentRun] = {}
    for run in runs:
        uid = getattr(run, "user_id", None)
        if uid is None or uid in latest_run_by_user:
            continue
        latest_run_by_user[uid] = run

    def _esc(value) -> str:
        return html.escape("" if value is None else str(value))

    def _fmt_dt(value) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        return str(value)

    def _fmt_bool(flag) -> str:
        return "Yes" if bool(flag) else "No"

    headers = [
        "ID",
        "Club ID",
        "First Name",
        "Surname",
        "Phone",
        "Created On",
        "Updated On",
        "Superuser",
        "Admin Role",
        "Consent Given",
        "Consent At",
        "Last Assessment",
        "Assessment",
        "Progress",
    ]

    rows_html = []
    for u in users:
        latest_run = latest_run_by_user.get(getattr(u, "id", None))
        if latest_run:
            _ensure_dashboard_and_progress(u, latest_run)
            finished = getattr(latest_run, "finished_at", None)
            finished_str = _fmt_dt(finished)
            dash_link = _report_link(u.id, "latest.html")
            prog_link = _report_link(u.id, "progress.html")
            dash_cell = f"<a href=\"{html.escape(dash_link)}\" target=\"_blank\">assessment</a>" if dash_link else ""
            prog_cell = f"<a href=\"{html.escape(prog_link)}\" target=\"_blank\">progress</a>" if prog_link else ""
        else:
            finished_str = ""
            dash_cell = ""
            prog_cell = ""
        rows_html.append(
            "<tr>"
            f"<td>{_esc(u.id)}</td>"
            f"<td>{_esc(u.club_id)}</td>"
            f"<td>{_esc(getattr(u, 'first_name', None))}</td>"
            f"<td>{_esc(getattr(u, 'surname', None))}</td>"
            f"<td>{_esc(getattr(u, 'phone', None))}</td>"
            f"<td>{_esc(_fmt_dt(getattr(u, 'created_on', None)))}</td>"
            f"<td>{_esc(_fmt_dt(getattr(u, 'updated_on', None)))}</td>"
            f"<td>{_esc(_fmt_bool(getattr(u, 'is_superuser', False)))}</td>"
            f"<td>{_esc(getattr(u, 'admin_role', ''))}</td>"
            f"<td>{_esc(_fmt_bool(getattr(u, 'consent_given', False)))}</td>"
            f"<td>{_esc(_fmt_dt(getattr(u, 'consent_at', None)))}</td>"
            f"<td>{_esc(finished_str)}</td>"
            f"<td>{dash_cell}</td>"
            f"<td>{prog_cell}</td>"
            "</tr>"
        )

    css = f"""
    <style>
      {FONT_FACE}
      body { margin: 24px; color: #111; }
      h1 { margin-bottom: 4px; font-size: 20px; }
      .meta { color: #666; margin-bottom: 16px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { border: 1px solid #ddd; padding: 8px 6px; text-align: left; vertical-align: top; font-size: 14px; }
      th { background: #f5f5f5; font-weight: 600; }
      td:nth-child(5) { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
    </style>
    """

    html_doc = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<meta charset=\"utf-8\">",
        f"<title>{html.escape(BRAND_NAME or 'HealthSense')} · Global Users</title>",
        css,
        "<body>",
        f"<h1>{html.escape(BRAND_NAME or 'HealthSense')} · Global Users</h1>",
        f"<div class=\"meta\">Total users: {len(users)} · Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>",
        "<table>",
        "<thead><tr>" + "".join(f"<th>{_esc(h)}</th>" for h in headers) + "</tr></thead>",
        "<tbody>" + ("".join(rows_html) if rows_html else "<tr><td colspan=\"13\">No users found.</td></tr>") + "</tbody>",
        "</table>",
        f"<div style=\"text-align:right; margin-top:12px; color:#666; font-size:12px;\">{html.escape(BRAND_FOOTER)}</div>",
        "</body>",
        "</html>",
    ]

    out_root = _reports_root_global()
    out_path = os.path.join(out_root, "global-users.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_doc))

    try:
        _audit("global_users_html", "ok", {"count": len(users), "path": out_path})
    except Exception:
        pass

    return out_path


def generate_club_users_html(club_id: int) -> str:
    """
    Render an HTML users report filtered to a specific club, including latest assessment + links.
    """
    with SessionLocal() as s:
        club = s.query(Club).filter(Club.id == club_id).one_or_none()
        users = (
            s.query(User)
             .filter(User.club_id == club_id)
             .order_by(User.id.asc())
             .all()
        )
        user_ids = [getattr(u, "id", None) for u in users if getattr(u, "id", None) is not None]
        runs = []
        if user_ids:
            runs = (
                s.query(AssessmentRun)
                 .filter(AssessmentRun.finished_at.isnot(None))
                 .filter(AssessmentRun.user_id.in_(user_ids))
                 .order_by(AssessmentRun.user_id.asc(), AssessmentRun.finished_at.desc())
                 .all()
            )
    club_label = (
        getattr(club, "name", None)
        or getattr(club, "slug", None)
        or f"Club {club_id}"
    )
    latest_run_by_user: dict[int, AssessmentRun] = {}
    for run in runs:
        uid = getattr(run, "user_id", None)
        if uid is None or uid in latest_run_by_user:
            continue
        latest_run_by_user[uid] = run

    def _esc(value) -> str:
        return html.escape("" if value is None else str(value))

    def _fmt_dt(value) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        return str(value)

    headers = [
        "ID",
        "First Name",
        "Surname",
        "Phone",
        "Created On",
        "Updated On",
        "Consent Given",
        "Consent At",
        "Last Assessment",
        "Assessment",
        "Progress",
    ]

    rows_html = []
    for u in users:
        latest_run = latest_run_by_user.get(getattr(u, "id", None))
        finished_str = ""
        dash_cell = ""
        prog_cell = ""
        if latest_run:
            _ensure_dashboard_and_progress(u, latest_run)
            finished_str = _fmt_dt(getattr(latest_run, "finished_at", None))
            dash_link = _report_link(u.id, "latest.html")
            prog_link = _report_link(u.id, "progress.html")
            if dash_link:
                dash_cell = f"<a href=\"{html.escape(dash_link)}\" target=\"_blank\">assessment</a>"
            if prog_link:
                prog_cell = f"<a href=\"{html.escape(prog_link)}\" target=\"_blank\">progress</a>"
        rows_html.append(
            "<tr>"
            f"<td>{_esc(u.id)}</td>"
            f"<td>{_esc(getattr(u, 'first_name', None))}</td>"
            f"<td>{_esc(getattr(u, 'surname', None))}</td>"
            f"<td>{_esc(getattr(u, 'phone', None))}</td>"
            f"<td>{_esc(_fmt_dt(getattr(u, 'created_on', None)))}</td>"
            f"<td>{_esc(_fmt_dt(getattr(u, 'updated_on', None)))}</td>"
            f"<td>{_esc('Yes' if getattr(u, 'consent_given', False) else 'No')}</td>"
            f"<td>{_esc(_fmt_dt(getattr(u, 'consent_at', None)))}</td>"
            f"<td>{_esc(finished_str)}</td>"
            f"<td>{dash_cell}</td>"
            f"<td>{prog_cell}</td>"
            "</tr>"
        )

    css = """
    <style>
      {FONT_FACE}
      body { margin: 24px; color: #111; }
      h1 { margin-bottom: 4px; font-size: 20px; }
      .meta { color: #666; margin-bottom: 16px; }
      table { width: 100%; border-collapse: collapse; }
      th, td { border: 1px solid #ddd; padding: 8px 6px; text-align: left; vertical-align: top; font-size: 14px; }
      th { background: #f5f5f5; font-weight: 600; }
      td:nth-child(4) { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace; }
    </style>
    """

    html_doc = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<meta charset=\"utf-8\">",
        f"<title>{html.escape(BRAND_NAME or 'HealthSense')} · {html.escape(club_label)} · Users</title>",
        css,
        "<body>",
        f"<h1>{html.escape(BRAND_NAME or 'HealthSense')} · {html.escape(club_label)} · Users</h1>",
        f"<div class=\"meta\">Total users: {len(users)} · Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</div>",
        "<table>",
        "<thead><tr>" + "".join(f"<th>{_esc(h)}</th>" for h in headers) + "</tr></thead>",
        "<tbody>" + ("".join(rows_html) if rows_html else "<tr><td colspan=\"11\">No users found.</td></tr>") + "</tbody>",
        "</table>",
        f"<div style=\"text-align:right; margin-top:12px; color:#666; font-size:12px;\">{html.escape(BRAND_FOOTER)}</div>",
        "</body>",
        "</html>",
    ]

    out_root = _reports_root_global()
    out_path = os.path.join(out_root, f"club-{club_id}-users.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_doc))

    try:
        _audit("club_users_html", "ok", {"club_id": club_id, "count": len(users), "path": out_path})
    except Exception:
        pass

    return out_path


def _display_full_name(user: User) -> str:
    first = (getattr(user, "first_name", None) or "").strip()
    last = (getattr(user, "surname", None) or "").strip()
    full = f"{first} {last}".strip()
    if full:
        return full
    phone = (getattr(user, "phone", None) or "").strip()
    return phone or "User"

# Best-effort role display from user model
def _display_role(user: User) -> str:
    """Best-effort role display from user model; returns empty string if unavailable."""
    # Try common attribute names in priority order
    for attr in ("role", "job_title", "title", "position", "member_role"):
        try:
            val = getattr(user, attr, None)
        except Exception:
            val = None
        if val is None:
            continue
        s = str(val).strip()
        if s:
            return s
    return ""

# Normalise date range helper
def _normalise_date_range(start: date | str | None, end: date | str | None) -> tuple[datetime, datetime, str, str]:
    """
    Accepts ISO date strings or date objects.
    Returns (start_dt_utc, end_dt_utc_inclusive, start_str, end_str)
    """
    def _to_date(d):
        if d is None:
            return None
        if isinstance(d, date) and not isinstance(d, datetime):
            return d
        if isinstance(d, datetime):
            return d.date()
        # assume ISO string
        return datetime.fromisoformat(str(d)).date()

    s = _to_date(start) or datetime.utcnow().date()
    e = _to_date(end) or s
    if e < s:
        s, e = e, s

    # Interpret range in UTC; end inclusive -> set to 23:59:59.999999
    start_dt = datetime(s.year, s.month, s.day, 0, 0, 0)
    end_dt = datetime(e.year, e.month, e.day, 23, 59, 59, 999999)
    return start_dt, end_dt, s.isoformat(), e.isoformat()

# Safe float conversion helper
def _to_float(x, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default

def _today_str() -> str:
    # Use UTC so it's deterministic server-side
    return datetime.utcnow().strftime("%b %d, %Y")


# Format a finished_at timestamp for PDF display: dd/mm/yy HH:MM in report-local time
def _format_finished_for_pdf(val: Any, *, tz_env: str = "REPORT_TZ") -> str:
    """
    Format a finished_at timestamp into a compact local string (dd/mm/yy HH:MM).
    - If naive, assume UTC.
    - Convert to timezone in $REPORT_TZ (default Europe/London) when zoneinfo is available.
    - Hide seconds and microseconds.
    - Return empty string if parsing fails.
    """
    if not val:
        return ""
    try:
        if isinstance(val, datetime):
            dt = val
        else:
            # Accept ISO strings; fallback to strptime without tz if needed
            try:
                dt = datetime.fromisoformat(str(val))
            except Exception:
                # Fallback: strip microseconds if present
                raw = str(val).split(".")[0]
                dt = datetime.fromisoformat(raw)
        # Assume UTC if naive
        if dt.tzinfo is None:
            try:
                tz_utc = ZoneInfo("UTC") if ZoneInfo else None
            except Exception:
                tz_utc = None
            if tz_utc is not None:
                dt = dt.replace(tzinfo=tz_utc)
        # Convert to local/report TZ if possible
        tz_name = os.getenv(tz_env, "Europe/London")
        try:
            tz = ZoneInfo(tz_name) if ZoneInfo else None
        except Exception:
            tz = None
        if tz is not None:
            dt = dt.astimezone(tz)
        # dd/mm/yy HH:MM (per Julian's preference)
        return dt.strftime("%d/%m/%y %H:%M")
    except Exception:
        return str(val)

def _pillar_order() -> List[str]:
    return ["nutrition", "training", "resilience", "recovery"]

def _title_for_pillar(p: str) -> str:
    return (p or "").replace("_", " ").title()

def _concept_display(code: str) -> str:
    return (code or "").replace("_", " ").title()


# Utility: get first non-empty attribute (handles bytes, None)
def _first_non_empty_attr(obj: Any, fields: List[str]) -> str:
    for f in fields:
        try:
            val = getattr(obj, f, None)
        except Exception:
            val = None
        if val is None:
            continue
        if isinstance(val, (bytes, bytearray)):
            try:
                val = val.decode("utf-8", errors="ignore")
            except Exception:
                val = str(val)
        val = str(val).strip()
        if val:
            return val
    return ""

# ──────────────────────────────────────────────────────────────────────────────
# OKR helpers (prefer structured OKR tables; fallback to PillarResult.advice)
# ──────────────────────────────────────────────────────────────────────────────

def _fetch_okrs_for_run(run_id: int) -> Dict[str, Dict[str, Any]]:
    """
    Return a map: pillar_key -> { 'objective': str, 'krs': [str, ...] }
    Prefers dedicated OKR tables when available (OkrObjective/OkrKeyResult) and
    falls back to parsing PillarResult.advice if tables are not present.
    """
    out: Dict[str, Dict[str, Any]] = {}

    # Resolve user_id for this run_id (used for fallback when okr_objectives lacks run_id)
    _user_id_for_run = None
    try:
        with SessionLocal() as _s_uid:
            _row = _s_uid.execute(
                text("SELECT user_id FROM assessment_runs WHERE id = :rid"),
                {"rid": run_id}
            ).first()
            if _row and _row[0] is not None:
                _user_id_for_run = int(_row[0])
    except Exception:
        _user_id_for_run = None

    # Resolve assess_session_id for this run (used to link OKRs via okr_objectives.source_assess_session_id)
    _assess_session_id_for_run = None
    try:
        with SessionLocal() as _s_asid:
            # Try common column names in assessment_runs for the session id
            _row = None
            try:
                _row = _s_asid.execute(
                    text("SELECT assess_session_id FROM assessment_runs WHERE id = :rid"),
                    {"rid": run_id}
                ).first()
            except Exception:
                try:
                    _s_asid.rollback()
                except Exception:
                    pass
            if (not _row) or (_row[0] is None):
                try:
                    _row = _s_asid.execute(
                        text("SELECT session_id FROM assessment_runs WHERE id = :rid"),
                        {"rid": run_id}
                    ).first()
                except Exception:
                    try:
                        _s_asid.rollback()
                    except Exception:
                        pass
            if _row and _row[0] is not None:
                _assess_session_id_for_run = _row[0]
    except Exception:
        _assess_session_id_for_run = None

    # Audit linkage inputs for OKR fetch
    _audit('okr_link_inputs', 'ok', {
        'run_id': run_id,
        'user_id': _user_id_for_run,
        'assess_session_id': _assess_session_id_for_run,
        'orm_models': bool(OkrObjective is not None and OkrKeyResult is not None),
    })

    # Try structured OKR tables first
    if OkrObjective is not None and OkrKeyResult is not None:
        try:
            with SessionLocal() as s:
                # Fetch objectives linked to this assessment run via its assess_session_id (preferred)
                objs = []
                try:
                    assess_session_row = s.execute(
                        text("SELECT assess_session_id FROM assessment_runs WHERE id = :rid"),
                        {"rid": run_id}
                    ).first()
                    assess_session_id = assess_session_row[0] if assess_session_row and assess_session_row[0] is not None else None
                except Exception:
                    try:
                        s.rollback()
                    except Exception:
                        pass
                    assess_session_id = None

                if assess_session_id is not None:
                    objs = (
                        s.query(OkrObjective)
                         .filter(OkrObjective.source_assess_session_id == assess_session_id)
                         .all()
                    )
                    _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'orm_source_assess_session_id', 'rows': len(objs or [])})

                # Fallback: if no session-linked OKRs, try by owner_user_id (latest first)
                if not objs:
                    try:
                        user_row = s.execute(
                            text("SELECT user_id FROM assessment_runs WHERE id = :rid"),
                            {"rid": run_id}
                        ).first()
                        user_id = user_row[0] if user_row and user_row[0] is not None else None
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        user_id = None

                    if user_id is not None:
                        objs = (
                            s.query(OkrObjective)
                             .filter(OkrObjective.owner_user_id == user_id)
                             .order_by(OkrObjective.id.desc())
                             .all()
                        )
                        _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'orm_owner_user_id', 'rows': len(objs or [])})

                if objs:
                    # Map pillar_result.id -> pillar_key for this run (to ensure pillar comes from source_pillar_id)
                    pr_id_to_key: Dict[int, str] = {}
                    try:
                        _pr_rows = s.execute(
                            text("SELECT id, pillar_key FROM pillar_results WHERE run_id = :rid"),
                            {"rid": run_id}
                        ).fetchall()
                        for _r in _pr_rows or []:
                            try:
                                pr_id_to_key[int(_r[0])] = (str(_r[1] or "").strip().lower().replace(" ", "_"))
                            except Exception:
                                continue
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                    # Prefer relationship 'key_results' if present on the ORM model, else fallback query
                    by_obj: Dict[Any, List[Any]] = {}
                    rel_used = False
                    for o in objs:
                        oid = getattr(o, 'id', None)
                        if oid is None:
                            continue
                        rel_krs = getattr(o, 'key_results', None)
                        if isinstance(rel_krs, list) and rel_krs:
                            by_obj[oid] = rel_krs
                            rel_used = True
                    if not rel_used:
                        obj_ids = [getattr(o, 'id', None) for o in objs if getattr(o, 'id', None) is not None]
                        if obj_ids:
                            kr_rows = (
                                s.query(OkrKeyResult)
                                 .filter(getattr(OkrKeyResult, 'objective_id').in_(obj_ids))
                                 .all()
                            )
                            for kr in kr_rows:
                                by_obj.setdefault(getattr(kr, 'objective_id', None), []).append(kr)
                    _audit('okr_kr_orm_source', 'ok', {'run_id': run_id, 'via': 'relationship' if rel_used else 'query', 'objectives': len(objs or [])})

                    for obj in objs:
                        # Prefer deriving pillar from source_pillar_id -> pillar_results to ensure it matches this run
                        _spid = getattr(obj, 'source_pillar_id', None)
                        pk = ''
                        if _spid is not None and int(_spid) in pr_id_to_key:
                            pk = pr_id_to_key[int(_spid)]
                        if not pk:
                            pk = (getattr(obj, 'pillar_key', None) or getattr(obj, 'pillar', '') or '').strip().lower().replace(' ', '_')
                        if not pk:
                            continue
                        objective_text = (getattr(obj, 'objective', None) or getattr(obj, 'title', None) or getattr(obj, 'text', '') or '').strip()
                        krs: List[str] = []
                        for kr in by_obj.get(getattr(obj, 'id', None), []):
                            base_txt = _first_non_empty_attr(kr, ['text','description','title','kr_text','kr_description','details','body','content'])
                            # Try to extract numeric baseline/target and unit-ish labels from common field names
                            baseline_val = _first_non_empty_attr(kr, ['baseline', 'baseline_value', 'baseline_num', 'start_value', 'start'])
                            target_val   = _first_non_empty_attr(kr, ['target', 'target_value', 'target_num', 'target_text', 'goal_value', 'goal'])
                            unit_label   = _first_non_empty_attr(kr, ['unit', 'metric_unit', 'unit_label', 'metric_label'])
                            per_label    = _first_non_empty_attr(kr, ['per', 'unit_per', 'per_period'])  # e.g., 'day', 'week'

                            def _fmt_num(x: str) -> str:
                                try:
                                    f = float(x)
                                    if f.is_integer():
                                        return str(int(f))
                                    return str(f)
                                except Exception:
                                    return str(x).strip()

                            def _fmt_unit(u: str, per: str) -> str:
                                u = (u or '').strip()
                                per = (per or '').strip()
                                if not u and not per:
                                    return ''
                                # Special case percent
                                if u.lower() in ('percent', '%') and not per:
                                    return '%'
                                if u and per:
                                    # e.g., 'portions per day'
                                    return f' {u} per {per}'
                                if u and not per:
                                    return f' {u}'
                                if per and not u:
                                    return f' per {per}'
                                return ''

                            enriched = base_txt.strip() if base_txt else ''
                            if enriched:
                                krs.append(enriched)
                        out[pk] = {'objective': objective_text, 'krs': krs, 'llm_prompt': getattr(obj, 'llm_prompt', None)}
            # Audit successful fetch just before return
            _audit('okr_fetch_structured_summary', 'ok', {'run_id': run_id, 'objectives': len(out), 'has_okrs': bool(out)})
        except Exception as e:
            _audit('okr_fetch_structured_error', 'error', {'run_id': run_id}, error=str(e))

    # Audit if models are not importable (for logging)
    if OkrObjective is None or OkrKeyResult is None:
        _audit('okr_models_unavailable', 'warn', {'run_id': run_id}, error='OKR ORM models not importable')

    # Fallback: if OKR ORM models aren't importable, try raw SQL against okr_* tables
    if not out and (OkrObjective is None or OkrKeyResult is None):
        try:
            with SessionLocal() as s:
                rows = []
                # 1) Preferred: by okr_objectives.source_assess_session_id (links directly to the originating assessment session)
                if _assess_session_id_for_run is not None:
                    try:
                        rows = s.execute(
                            text("SELECT id, pillar_key, objective, source_pillar_id, llm_prompt FROM okr_objectives WHERE source_assess_session_id = :sid ORDER BY id ASC"),
                            {"sid": _assess_session_id_for_run}
                        ).fetchall()
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        rows = []
                        # fallback to without llm_prompt
                        try:
                            rows = s.execute(
                                text("SELECT id, pillar_key, objective, source_pillar_id FROM okr_objectives WHERE source_assess_session_id = :sid ORDER BY id ASC"),
                                {"sid": _assess_session_id_for_run}
                            ).fetchall()
                        except Exception:
                            try:
                                s.rollback()
                            except Exception:
                                pass
                            rows = []
                    _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'source_assess_session_id', 'rows': len(rows or [])})

                # 2) Next: by run_id (if column exists)
                if not rows:
                    try:
                        rows = s.execute(
                            text("SELECT id, pillar_key, objective, source_pillar_id, llm_prompt FROM okr_objectives WHERE run_id = :rid"),
                            {"rid": run_id}
                        ).fetchall()
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        rows = []
                        # fallback to without llm_prompt
                        try:
                            rows = s.execute(
                                text("SELECT id, pillar_key, objective, source_pillar_id FROM okr_objectives WHERE run_id = :rid"),
                                {"rid": run_id}
                            ).fetchall()
                        except Exception:
                            try:
                                s.rollback()
                            except Exception:
                                pass
                            rows = []
                    _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'run_id', 'rows': len(rows or [])})

                # 3) Fallback: by owner_user_id (if column exists) — keep latest per pillar
                if not rows and _user_id_for_run is not None:
                    try:
                        rows_all = s.execute(
                            text("SELECT id, pillar_key, objective, source_pillar_id, llm_prompt FROM okr_objectives WHERE owner_user_id = :uid ORDER BY id DESC"),
                            {"uid": _user_id_for_run}
                        ).fetchall()
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        rows_all = []
                        # fallback to without llm_prompt
                        try:
                            rows_all = s.execute(
                                text("SELECT id, pillar_key, objective, source_pillar_id FROM okr_objectives WHERE owner_user_id = :uid ORDER BY id DESC"),
                                {"uid": _user_id_for_run}
                            ).fetchall()
                        except Exception:
                            try:
                                s.rollback()
                            except Exception:
                                pass
                            rows_all = []
                    seen = set()
                    filtered = []
                    for r in rows_all:
                        pk_norm = (r[1] or "").strip().lower().replace(" ", "_")
                        if pk_norm and pk_norm not in seen:
                            filtered.append(r)
                            seen.add(pk_norm)
                    rows = filtered
                    _audit('okr_obj_select', 'ok', {'run_id': run_id, 'by': 'owner_user_id', 'rows': len(rows or [])})

                if rows:
                    # Map pillar_result.id -> pillar_key for this run for source_pillar_id mapping
                    pr_id_to_key: Dict[int, str] = {}
                    try:
                        _pr_rows = s.execute(
                            text("SELECT id, pillar_key FROM pillar_results WHERE run_id = :rid"),
                            {"rid": run_id}
                        ).fetchall()
                        for _r in _pr_rows or []:
                            try:
                                pr_id_to_key[int(_r[0])] = (str(_r[1] or "").strip().lower().replace(" ", "_"))
                            except Exception:
                                continue
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                    # Build KR map keyed by objective_id
                    okr_map = {}
                    for r in rows:
                        oid = r[0]
                        raw_pk = (r[1] or "").strip().lower().replace(" ", "_")
                        obj_txt = (r[2] or "").strip()
                        _spid = r[3] if len(r) > 3 else None
                        prompt_txt = (r[4] if len(r) > 4 else None) or None
                        pk = ''
                        try:
                            if _spid is not None and int(_spid) in pr_id_to_key:
                                pk = pr_id_to_key[int(_spid)]
                        except Exception:
                            pk = ''
                        if not pk:
                            pk = raw_pk
                        okr_map[oid] = (pk, obj_txt, prompt_txt)
                    by_obj = {oid: [] for oid in okr_map.keys()}
                    # Detect available textual columns in okr_key_results and build a COALESCE for KR text
                    kr_cols_available = []
                    try:
                        _cols = s.execute(
                            text("SELECT column_name FROM information_schema.columns WHERE table_name = 'okr_key_results'")
                        ).fetchall() or []
                        kr_cols_available = [str(c[0]) for c in _cols]
                    except Exception:
                        try:
                            s.rollback()
                        except Exception:
                            pass
                        kr_cols_available = []
                    # Candidate text-like columns in order of preference
                    _cand = ['text', 'description', 'title', 'kr_text', 'kr_description', 'details', 'body']
                    _present = [c for c in _cand if c in kr_cols_available]
                    if not _present and kr_cols_available:
                        _present = [kr_cols_available[0]]
                    coalesce_expr = "COALESCE(" + ",".join(_present) + ") AS kr" if _present else "NULL AS kr"

                    # Detect optional numeric/unit columns for enrichment
                    _b_cols = [c for c in ['baseline', 'baseline_value', 'baseline_num', 'start_value', 'start'] if c in kr_cols_available]
                    _t_cols = [c for c in ['target', 'target_value', 'target_num', 'target_text', 'goal_value', 'goal'] if c in kr_cols_available]
                    _u_cols = [c for c in ['unit', 'metric_unit', 'unit_label', 'metric_label'] if c in kr_cols_available]
                    _p_cols = [c for c in ['per', 'unit_per', 'per_period'] if c in kr_cols_available]

                    b_expr = _b_cols[0] if _b_cols else 'NULL'
                    t_expr = _t_cols[0] if _t_cols else 'NULL'
                    u_expr = _u_cols[0] if _u_cols else 'NULL'
                    p_expr = _p_cols[0] if _p_cols else 'NULL'

                    _audit('okr_kr_columns', 'ok', {
                        'run_id': run_id,
                        'present': _present,
                        'baseline_col': b_expr if b_expr != 'NULL' else None,
                        'target_col': t_expr if t_expr != 'NULL' else None,
                        'unit_col': u_expr if u_expr != 'NULL' else None,
                        'per_col': p_expr if p_expr != 'NULL' else None,
                    })

                    # Fetch KRs per objective id (simple loop to avoid dialect-specific IN binding)
                    for oid in okr_map.keys():
                        kr_rows = s.execute(
                            text(f"SELECT {coalesce_expr}, {b_expr} AS baseline, {t_expr} AS target, {u_expr} AS unit, {p_expr} AS per FROM okr_key_results WHERE objective_id = :oid ORDER BY id ASC"),
                            {"oid": oid}
                        ).fetchall()
                        if kr_rows:
                            by_obj[oid] = kr_rows
                    # Assemble output
                    for oid, (pk, obj_txt, prompt_txt) in okr_map.items():
                        krs: List[str] = []
                        for row in by_obj.get(oid, []):
                            # row indices: 0=text, 1=baseline, 2=target, 3=unit, 4=per (when selected above)
                            kr_txt = (row[0] or "")
                            if isinstance(kr_txt, bytes):
                                try:
                                    kr_txt = kr_txt.decode('utf-8', errors='ignore')
                                except Exception:
                                    kr_txt = str(kr_txt)
                            kr_txt = str(kr_txt).strip()
                            b = str(row[1]).strip() if len(row) > 1 and row[1] is not None else ''
                            t = str(row[2]).strip() if len(row) > 2 and row[2] is not None else ''
                            u = str(row[3]).strip() if len(row) > 3 and row[3] is not None else ''
                            p = str(row[4]).strip() if len(row) > 4 and row[4] is not None else ''

                            def _fmt_num(x_: str) -> str:
                                try:
                                    f = float(x_)
                                    if f.is_integer():
                                        return str(int(f))
                                    return str(f)
                                except Exception:
                                    return str(x_).strip()

                            def _fmt_unit(u_: str, p_: str) -> str:
                                if not u_ and not p_:
                                    return ''
                                if u_.lower() in ('percent', '%') and not p_:
                                    return '%'
                                if u_ and p_:
                                    return f' {u_} per {p_}'
                                if u_:
                                    return f' {u_}'
                                if p_:
                                    return f' per {p_}'
                                return ''

                            if kr_txt:
                                krs.append(kr_txt)
                        if pk:
                            out[pk] = {"objective": obj_txt, "krs": krs, "llm_prompt": prompt_txt}
                # Add a tag indicating which path was used
                _path = "source_assess_session_id" if _assess_session_id_for_run is not None and out else ("run_id" if rows else ("owner_user_id" if _user_id_for_run is not None else "unknown"))
                _audit('okr_fetch_structured_summary', 'ok', {'run_id': run_id, 'objectives': len(out), 'has_okrs': bool(out), 'fallback': True, 'path': _path})
        except Exception as e:
            try:
                # make sure this session isn't left in a failed state
                s.rollback()  # note: if 's' isn't defined in this scope, ignore
            except Exception:
                pass
            _audit('okr_models_unavailable', 'error', {'run_id': run_id}, error=str(e))

    return out


# ──────────────────────────────────────────────────────────────────────────────
# OKR Summary (admin) report – date range across users/runs, with OKRs
# ──────────────────────────────────────────────────────────────────────────────
def _collect_okr_summary_rows(start_dt: datetime, end_dt: datetime, club_id: int | None = None) -> list[dict]:
    """
    Collect assessment runs within range, combining pillar scores with OKRs.
    Returns rows: { name, finished_at, pillar, score, objective, key_results, user_id, run_id }
    """
    base = _collect_summary_rows(start_dt, end_dt, club_id=club_id)
    rows: list[dict] = []
    for b in base:
        run_id = b.get("run_id")
        if not run_id:
            continue
        okr_map = _fetch_okrs_for_run(int(run_id))
        try:
            _audit("okr_summary_run_okrs", "ok", {
                "run_id": int(run_id),
                "has_okrs": bool(okr_map),
                "has_any_llm_prompt": any(bool((v or {}).get("llm_prompt")) for v in (okr_map or {}).values())
            })
        except Exception:
            pass
        for pillar in _pillar_order():
            okr = okr_map.get(pillar)
            if not okr:
                continue
            krs = [str(x).strip() for x in (okr.get("krs") or []) if str(x).strip()]
            rows.append({
                "name": b.get("name"),
                "finished_at": b.get("finished_at"),
                "pillar": _title_for_pillar(pillar),
                "score": b.get(pillar),
                "objective": okr.get("objective") or "",
                "key_results": "\n".join(krs),
                "user_id": b.get("user_id"),
                "run_id": run_id,
                "llm_prompt": okr.get("llm_prompt"),
            })
    return rows


def generate_okr_summary_html(
    start: date | str | None = None,
    end: date | str | None = None,
    *,
    include_llm_prompt: bool = False,
    club_id: int | None = None,
) -> str:
    """Generate an OKR summary **HTML** file for [start, end] and return its absolute path.
    Uses _collect_okr_summary_rows(). Columns wrap; no Role column.
    """
    # Resolve date window and fetch rows
    start_dt, end_dt, s_str, e_str = _normalise_date_range(start, end)
    # Audit: entry + requested column
    try:
        _audit("okr_summary_html_start", "ok", {
            "include_llm_prompt": include_llm_prompt,
            "start": s_str,
            "end": e_str
        })
    except Exception:
        pass
    rows = _collect_okr_summary_rows(start_dt, end_dt, club_id=club_id)
    # Audit: how many rows have an llm_prompt payload
    total_rows = len(rows)
    llm_prompt_rows = sum(1 for r in rows if (r.get("llm_prompt") or "").strip())
    try:
        _audit("okr_summary_rows_stats", "ok", {
            "rows_total": total_rows,
            "rows_with_llm_prompt": llm_prompt_rows,
            "include_llm_prompt": include_llm_prompt
        })
    except Exception:
        pass

    # Escape helper
    def _esc(x: str | None) -> str:
        s = "" if x is None else str(x)
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    title = f"OKR Summary Report ({s_str} – {e_str})"

    # Header
    head = ["Name", "Pillar", "Score", "Objective", "Key Results"]
    if include_llm_prompt:
        head.append("LLM Prompt")
    thead = "<thead><tr>" + "".join(f"<th>{_esc(h)}</th>" for h in head) + "</tr></thead>"
    # Compute column count for colspan
    col_count = 6 if include_llm_prompt else 5

    # Body rows
    body_rows: list[str] = []
    for r in rows:
        name = _esc(str(r.get("name") or ""))
        pillar = _esc(str(r.get("pillar") or ""))
        sc = r.get("score")
        try:
            score = "" if sc is None else str(int(round(float(sc))))
        except Exception:
            score = _esc(str(sc) if sc is not None else "")
        objective = _esc(str(r.get("objective") or ""))

        # Key results: accept list or newline-separated string
        krs_blob = r.get("key_results")
        if isinstance(krs_blob, (list, tuple)):
            kr_items = [str(x) for x in krs_blob if str(x).strip()]
        else:
            krs_str = str(krs_blob or "").strip()
            kr_items = [li for li in krs_str.split("\n") if li.strip()] if krs_str else []
        krs_html = ("<ul>" + "".join(f"<li>{_esc(li)}</li>" for li in kr_items) + "</ul>") if kr_items else ""

        prompt_td = ""
        if include_llm_prompt:
            raw_prompt = str(r.get("llm_prompt") or "")
            prompt_td = f"<td class=\"prompt\"><pre>{_esc(raw_prompt)}</pre></td>"

        body_rows.append(
            f"<tr>"
            f"<td class=\"name\">{name}</td>"
            f"<td class=\"pillar\">{pillar}</td>"
            f"<td class=\"score num\">{score}</td>"
            f"<td class=\"objective\">{objective}</td>"
            f"<td class=\"krs\">{krs_html}</td>"
            + prompt_td +
            f"</tr>"
        )

    # CSS for fixed layout + wrapping
    css = f"""
    <style>
      {FONT_FACE}
      :root {{ --fg:#222; --muted:#666; --bg:#fff; --head:#f3f3f3; --grid:#ddd; }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 24px; color: var(--fg); background: var(--bg); }}
      h1 {{ font-size: 20px; margin: 0 0 10px 0; }}
      .meta {{ color: var(--muted); margin-bottom: 16px; }}
      table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
      thead th {{ background: var(--head); border: 1px solid var(--grid); padding: 8px 6px; text-align: left; font-weight: 600; }}
      tbody td {{ border: 1px solid var(--grid); padding: 8px 6px; vertical-align: top; overflow-wrap: anywhere; word-break: break-word; }}
      .num {{ text-align: right; white-space: nowrap; }}
      .name {{ width: 22%; }}
      .pillar {{ width: 10%; }}
      .score {{ width: 6%; }}
      .objective {{ width: 26%; }}
      .krs {{ width: 30%; }}
      .prompt {{ width: 30%; color: var(--fg); }}
      ul {{ margin: 0; padding-left: 18px; }}
      li {{ margin: 0 0 6px 0; }}
      pre {{ margin: 0; white-space: pre-wrap; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace; font-size: 12px; line-height: 1.35; }}
    </style>
    """

    # Assemble document
    html_doc = (
        "<!doctype html>\n<html lang=\"en\">\n<meta charset=\"utf-8\">\n"
        f"<title>{_esc(title)}</title>\n"
        f"{css}\n"
        f"<h1>{_esc(title)}</h1>\n"
        f"<div class=\"meta\">Generated: {_esc(_today_str())}</div>\n"
        f"<table>\n{thead}\n<tbody>\n"
        + ("".join(body_rows) if body_rows else f'<tr><td colspan="{col_count}">No data</td></tr>')
        + "\n</tbody>\n</table>\n"
    )

    # Write to /public/reports
    out_base = _reports_root_global()
    out_name = f"okr_summary_{s_str}_to_{e_str}.html"
    out_path = os.path.join(out_base, out_name)
    os.makedirs(out_base, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)

    try:
        _audit("okr_summary_html_saved", "ok", {
            "html_path": out_path,
            "rows": len(rows),
            "rows_total": total_rows,
            "rows_with_llm_prompt": llm_prompt_rows,
            "include_llm_prompt": include_llm_prompt
        })
    except Exception:
        pass
    return out_path


def _write_okr_summary_pdf(
    path: str,
    start_str: str,
    end_str: str,
    rows: list[dict],
    *,
    include_llm_prompt: bool = False
) -> None:
    """Landscape PDF listing OKRs per pillar across runs in the date window."""
    try:
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
    except Exception as e:
        raise RuntimeError(f"reportlab not available: {e!r}")

    styles = getSampleStyleSheet()
    from reportlab.lib.styles import ParagraphStyle
    wrap = ParagraphStyle('wrap', parent=styles['Normal'], fontSize=9, leading=12)
    doc = BaseDocTemplate(path, pagesize=landscape(A4), leftMargin=30, rightMargin=30, topMargin=30, bottomMargin=30)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='normal')
    doc.addPageTemplates([PageTemplate(id='main', frames=frame)])

    story = []
    story.append(Paragraph(f"OKR Summary Report ({start_str} – {end_str})", styles["Title"]))
    story.append(Spacer(1, 12))

    if include_llm_prompt:
        data = [["Name", "Pillar", "Score", "Objective", "Key Results", "LLM Prompt"]]
    else:
        data = [["Name", "Pillar", "Score", "Objective", "Key Results"]]

    for r in rows:
        # Sanitize Name field (no role column)
        _name_raw = str(r.get("name") or "").strip()
        _looks_polluted = (
            len(_name_raw) > 40 and (
                "|" in _name_raw.lower() or _name_raw.lower().startswith("system:") or _name_raw.lower().startswith("assistant:") or _name_raw.lower().startswith("user:") or "digits phrasing" in _name_raw.lower()
            )
        )
        if _looks_polluted or not _name_raw:
            try:
                uid = r.get("user_id")
                if uid:
                    with SessionLocal() as _s_fix:
                        _u = _s_fix.query(User).filter(User.id == int(uid)).first()
                        if _u is not None and (_looks_polluted or not _name_raw):
                            _name_raw = _display_full_name(_u)
            except Exception:
                pass
        if len(_name_raw) > 80:
            _name_raw = _name_raw[:80] + "…"
        name_cell = Paragraph(_name_raw.replace("<", "&lt;").replace(">", "&gt;"), wrap)
        pillar_cell = Paragraph(str(r.get("pillar") or ""), wrap)
        # Score: keep short
        score_val = r.get("score")
        try:
            score_disp = "" if score_val is None else str(int(round(float(score_val))))
        except Exception:
            score_disp = str(score_val) if score_val is not None else ""
        obj_cell = Paragraph(str(r.get("objective") or ""), wrap)
        krs_text = r.get("key_results") or ""
        krs_text = str(krs_text).replace("\n", "<br/>")  # Ensure newlines render in Paragraph
        krs_cell = Paragraph(krs_text, wrap)

        if include_llm_prompt:
            prompt_text = r.get("llm_prompt") or ""
            prompt_text = str(prompt_text).replace("\n", " ")
            prompt_text = prompt_text.replace("<", "&lt;").replace(">", "&gt;")
            MAX_PROMPT_CHARS = 100
            prompt_cell = Paragraph(prompt_text[:MAX_PROMPT_CHARS] + ("…" if len(prompt_text) > MAX_PROMPT_CHARS else ""), wrap)
            data.append([name_cell, pillar_cell, score_disp, obj_cell, krs_cell, prompt_cell])
        else:
            data.append([name_cell, pillar_cell, score_disp, obj_cell, krs_cell])

    try:
        _audit("okr_summary_pdf_data", "ok", {
            "row_count": len(data) - 1,  # minus header
            "include_llm_prompt": include_llm_prompt
        })
    except Exception:
        pass

    # Adjusted column widths (removed Role column)
    if include_llm_prompt:
        col_widths = [225, 100, 40, 260, 290, 220]
    else:
        col_widths = [245, 110, 44, 290, 320]

    table = Table(data, repeatRows=1, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("ALIGN", (3,1), (3,-1), "RIGHT"),   # Score column
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(table)
    doc.build(story)
    
def generate_okr_summary_report(start: date | str | None = None, end: date | str | None = None, *, club_id: int | None = None) -> str:
    """Generate an OKR summary **HTML** for the given date window and return its path."""
    return generate_okr_summary_html(start, end, include_llm_prompt=False, club_id=club_id)


def generate_okr_summary_report_redacted(start: date | str | None = None, end: date | str | None = None, *, club_id: int | None = None) -> str:
    """Generate an OKR summary **HTML** (no LMS prompt column) for the given date window and return its path."""
    return generate_okr_summary_html(start, end, include_llm_prompt=False, club_id=club_id)

# New public entry point: generate OKR summary HTML including LLM prompt
def generate_okr_summary_report_llm(start: date | str | None = None, end: date | str | None = None, *, club_id: int | None = None) -> str:
    """Generate an OKR summary **HTML** including the LLM prompt column for the given date window and return its path."""
    try:
        _audit("okr_summary_llm_entry", "ok", {"start": str(start), "end": str(end)})
    except Exception:
        pass
    return generate_okr_summary_html(start, end, include_llm_prompt=True, club_id=club_id)


# ---------------------------------------------------------------------------
# Prompt audit report
# ---------------------------------------------------------------------------
def generate_prompt_audit_report(user_id: int, as_of_date: date | str | None = None, state: str = "live", include_logs: bool = True, logs_limit: int = 3) -> str:
    """
    Generate an HTML report of all prompt templates (by state) with assembled prompts for a given user/date.
    Includes recent prompt logs per touchpoint if requested.
    """
    _ensure_llm_prompt_log_schema()
    state = _canonical_state(state or "live")
    as_of_date = _date_from_str(as_of_date) if isinstance(as_of_date, str) else (as_of_date or date.today())

    with SessionLocal() as s:
        templates = (
            s.query(PromptTemplate)
            .filter(PromptTemplate.state.in_([state, "stage" if state == "beta" else state, "production" if state == "live" else state]))
            .order_by(PromptTemplate.touchpoint.asc(), PromptTemplate.version.desc(), PromptTemplate.id.desc())
            .all()
        )
        s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()

        rows = []
        for tpl in templates:
            assembly = _assemble_prompt_for_report(tpl.touchpoint, user_id, as_of_date=as_of_date, state=state)
            recent = []
            if include_logs:
                recent = (
                    s.query(LLMPromptLog)
                    .filter(LLMPromptLog.touchpoint == tpl.touchpoint)
                    .order_by(LLMPromptLog.created_at.desc())
                    .limit(logs_limit)
                    .all()
                )
            rows.append((tpl, assembly, recent))

    def _esc(val):
        return html.escape("" if val is None else str(val))

    table_rows = []
    for tpl, assembly, recent in rows:
        blocks_html = "<ul>" + "".join(f"<li><strong>{_esc(lbl)}:</strong> {_esc(txt)}</li>" for lbl, txt in (assembly.blocks or {}).items()) + "</ul>"
        logs_html = ""
        if recent:
            log_items = []
            for log in recent:
                log_items.append(
                    "<details><summary>"
                    f"#{log.id} @ {_esc(log.created_at)} (state={_esc(log.template_state)}, v={_esc(log.template_version)}, model={_esc(log.model)}, ms={_esc(log.duration_ms)})"
                    "</summary>"
                    f"<div><strong>Prompt</strong><pre style='white-space:pre-wrap;'>{_esc(log.assembled_prompt)}</pre></div>"
                    f"<div><strong>Response</strong><pre style='white-space:pre-wrap;'>{_esc(log.response_preview)}</pre></div>"
                    "</details>"
                )
            logs_html = "<div>" + "".join(log_items) + "</div>"
        table_rows.append(
            "<tr>"
            f"<td>{_esc(tpl.touchpoint)}</td>"
            f"<td>{_esc(tpl.state)}</td>"
            f"<td>{_esc(tpl.version)}</td>"
            f"<td>{_esc(tpl.okr_scope or '')}</td>"
            f"<td>{_esc(tpl.programme_scope or '')}</td>"
            f"<td>{blocks_html}</td>"
            f"<td><pre style='white-space:pre-wrap;'>{_esc(assembly.text)}</pre></td>"
            f"<td>{logs_html or '<em>No logs</em>'}</td>"
            "</tr>"
        )

    report_html = f"""
    <html><head><meta charset="utf-8"><title>Prompt Audit</title>
    <style>
      body {{ font-family: 'Inter', system-ui, sans-serif; margin: 20px; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; vertical-align: top; }}
      th {{ background: #f5f7fb; }}
      pre {{ margin: 0; white-space: pre-wrap; word-break: break-word; }}
      details summary {{ cursor: pointer; font-weight: 600; }}
    </style>
    </head><body>
    <h2>Prompt Audit</h2>
    <div>State: {_esc(state)} · User: {_esc(user_id)} · As of: {_esc(as_of_date)}</div>
    <table>
      <tr><th>Touchpoint</th><th>State</th><th>Version</th><th>OKR Scope</th><th>Programme Scope</th><th>Blocks</th><th>Assembled Prompt</th><th>Recent Logs</th></tr>
      {''.join(table_rows)}
    </table>
    </body></html>
    """
    out_base = _reports_root_for_user(user_id)
    out_name = f"prompt_audit_user{user_id}_{state}_{as_of_date}.html"
    out_path = os.path.join(out_base, out_name)
    os.makedirs(out_base, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report_html)
    return out_path

def _collect_report_data(run_id: int) -> Tuple[Optional[User], Optional[AssessmentRun], List[PillarResult]]:
    with SessionLocal() as s:
        run = s.query(AssessmentRun).filter(AssessmentRun.id == run_id).first()
        if not run:
            return None, None, []
        user = s.query(User).filter(User.id == run.user_id).first()
        pillars = (
            s.query(PillarResult)
             .filter(PillarResult.run_id == run_id)
             .all()
        )
        return user, run, pillars

def _score_color_rgb(v: int) -> tuple:
    """Map a 0–100 score to RGB color (green/amber/red). Amber uses bright orange (#FFA500)."""
    try:
        v = float(v)
    except Exception:
        v = 0.0
    if v >= 80:
        return (0.2, 0.6, 0.2)   # green
    if v >= 60:
        return (1.0, 0.65, 0.0)  # bright orange (#FFA500)
    return (0.8, 0.2, 0.2)       # red


def _pillar_symbol(key: str) -> str:
    m = {
        "nutrition": "[N]",
        "training": "[T]",
        "resilience": "[R]",
        "recovery": "[Rc]",
    }
    return m.get((key or "").lower(), "[•]")


# Hard-wrap text to card width and cap lines so it never spills the box
def _wrap_block(text: str, width: int = 42, max_lines: int = 4, bullet: str | None = None) -> str:
    if not text:
        return ""
    initial_indent = (bullet or "")
    subsequent_indent = (" " * len(initial_indent)) if bullet else ""
    wrapped = textwrap.fill(
        text.strip(),
        width=width,
        initial_indent=initial_indent,
        subsequent_indent=subsequent_indent,
        break_long_words=True,
        break_on_hyphens=True,
        replace_whitespace=False,
    )
    lines = wrapped.splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip() + "…"
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# Detailed (admin) report – grouped by pillar with concept breakdown
# ──────────────────────────────────────────────────────────────────────────────

def _collect_detailed_report_data(user_id: int) -> Tuple[Optional[User], Optional[AssessmentRun], List[UserConceptState]]:
    """Fetch the latest AssessmentRun for the user and their concept state rows."""
    with SessionLocal() as s:
        run = (
            s.query(AssessmentRun)
             .filter(AssessmentRun.user_id == user_id)
             .order_by(AssessmentRun.started_at.desc())
             .first()
        )
        user = s.query(User).filter(User.id == user_id).first()
        rows: List[UserConceptState] = (
            s.query(UserConceptState)
             .filter(UserConceptState.user_id == user_id)
             .order_by(UserConceptState.updated_at.desc())
             .all()
        )
        return user, run, rows or []


def _write_detailed_pdf(path: str, user: User, run: AssessmentRun, rows: List[UserConceptState]) -> None:
    """
    Render a multi-page, portrait PDF grouped by pillar, with a concept table:
      Columns: Concept | Score | Question | Answer | Confidence
      – Wrap long text in Concept/Question/Answer
      – Footer page numbers
      – Shows user name in Run Overview (no report path)
      – Includes OKR (from PillarResult.advice) under each pillar table
    """
    # Lazy import so the app can start without reportlab installed.
    try:
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.units import mm
    except Exception as e:
        raise RuntimeError(f"reportlab not available: {e!r}")

    _audit("detailed_report_start", "ok", {"user_id": getattr(user, "id", None), "run_id": getattr(run, "id", None), "out_pdf": path})

    styles = getSampleStyleSheet()
    wrap = ParagraphStyle('wrap', parent=styles['Normal'], fontSize=9, leading=11)

    # Group rows by pillar using configured order, then any others
    by_pillar: Dict[str, List[UserConceptState]] = {}
    for r in rows:
        pk = (getattr(r, 'pillar_key', None) or 'unknown').lower()
        by_pillar.setdefault(pk, []).append(r)


    def _on_page(c, doc):
        c.setFont("Helvetica", 8)
        c.drawRightString(200*mm, 15*mm, f"Page {c.getPageNumber()}")

    # Ensure directory exists
    out_dir = os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)

    doc = BaseDocTemplate(path, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id='normal')
    doc.addPageTemplates([PageTemplate(id='with_page_numbers', frames=frame, onPage=_on_page)])

    story: List[Any] = []

    # Title
    story.append(Paragraph("Assessment Report", styles["Title"]))
    story.append(Spacer(1, 10))

    # Run overview (user name; omit report path)
    story.append(Paragraph("<b>Run Overview</b>", styles["Heading2"]))
    display_name = _display_full_name(user)
    started = getattr(run, 'started_at', None) or ""
    finished = getattr(run, 'finished_at', None) or ""
    combined = getattr(run, 'combined_overall', None) or ""

    ov_rows = [
        ("Name", display_name),
        ("Started", str(started)),
        ("Finished", str(finished)),
        ("Combined Overall", str(combined)),
    ]
    ov_table = Table(ov_rows, hAlign="LEFT", colWidths=[120, 350])
    ov_table.setStyle(TableStyle([["GRID", (0,0), (-1,-1), 0.25, colors.grey]]))
    story.append(ov_table)
    story.append(Spacer(1, 14))

    # Pillar sections
    ordered = _pillar_order()
    pillar_keys = [p for p in ordered if p in by_pillar] + [p for p in by_pillar.keys() if p not in ordered]

    # Fetch OKRs for this run (uses structured OKR tables if available)
    okr_map = _fetch_okrs_for_run(getattr(run, 'id', None))

    coaching_text = _coaching_approach_text(getattr(user, "id", None), first_name)
    coaching_block = ""
    if coaching_text:
        coaching_block = (
            "<div class='card coach-card'>"
            "<h2>Coaching approach</h2>"
            f"{_llm_text_to_html(coaching_text)}"
            "</div>"
        )

    for pk in pillar_keys:
        grp = by_pillar.get(pk, [])
        # heading with avg score
        scores = [float(getattr(r, 'score')) for r in grp if getattr(r, 'score') is not None]
        avg = round(sum(scores)/len(scores)) if scores else None
        avg_txt = f"{avg}/100" if avg is not None else "Unscored"
        story.append(Paragraph(f"{_title_for_pillar(pk)} – Overall: {avg_txt}", styles["Heading2"]))

        data: List[List[Any]] = [["Concept", "Score", "Question", "Answer", "Confidence"]]
        for item in grp:
            concept = Paragraph(str(getattr(item, 'concept', '') or ''), wrap)
            sc = getattr(item, 'score', None)
            sc_txt = f"{int(round(float(sc)))}/100" if sc is not None else "Unscored"
            q = Paragraph(str(getattr(item, 'question', '') or ''), wrap)
            a = Paragraph(str(getattr(item, 'answer', '') or ''), wrap)
            cf = getattr(item, 'confidence', None)
            cf_txt = f"{float(cf):.2f}" if cf is not None else ""
            data.append([concept, sc_txt, q, a, cf_txt])

        table = Table(data, repeatRows=1, colWidths=[90, 45, 160, 120, 55])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.lightgrey),
            ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("ALIGN", (1,1), (1,-1), "RIGHT"),
        ]))
        story.append(table)

        # --- OKR block per pillar (prefer structured tables) ------------------
        okr_obj = okr_map.get(pk, None)
        okr_text = ''
        kr_lines: List[str] = []
        if okr_obj:
            okr_text = (okr_obj.get('objective') or '').strip()
            kr_lines = [str(x).strip() for x in (okr_obj.get('krs') or []) if str(x).strip()]

        if okr_text:
            story.append(Spacer(1, 6))
            story.append(Paragraph('OKR', styles['Heading3']))
            # Objective (no leading symbol and use requested heading text)
            story.append(Paragraph('<b>Quarter Objective</b>', styles['Normal']))
            story.append(Paragraph((okr_text or '').replace('\n', '<br/>'), styles['Normal']))
            # Key Results / Next steps (if any)
            if kr_lines:
                story.append(Spacer(1, 4))
                story.append(Paragraph('<b>Key Results</b>', styles['Normal']))
                for i, kr in enumerate(kr_lines[:3], start=1):
                    # Constrain each KR to a single compact line; add ellipsis if too long
                    line = _wrap_block(str(kr), width=80, max_lines=1, bullet=f"{i}. ")
                    story.append(Paragraph(line.replace('\n', '<br/>'), styles['Normal']))                   
                    story.append(Spacer(1, 12))
    else:
            story.append(Spacer(1, 12))

    doc.build(story)
    _audit("detailed_report_pdf_saved", "ok", {"pdf_path": path})

# ──────────────────────────────────────────────────────────────────────────────
# Summary (admin) report – date range across users/runs
# ──────────────────────────────────────────────────────────────────────────────
def _ensure_dashboard_and_progress(user: User | None, run: AssessmentRun | None) -> None:
    """
    Ensure dashboard (latest.html) and progress (progress.html) reports exist for the user.
    Generates them on demand if missing.
    """
    if not user or not getattr(user, "id", None):
        return
    user_id = getattr(user, "id", None)
    run_id = getattr(run, "id", None)
    if user_id is None:
        return
    root = _reports_root_for_user(user_id)
    dash_path = os.path.join(root, "latest.html")
    if (not os.path.exists(dash_path)) and run_id:
        try:
            generate_assessment_dashboard_html(run_id)
        except Exception:
            pass
    prog_path = os.path.join(root, "progress.html")
    if not os.path.exists(prog_path):
        try:
            generate_progress_report_html(user_id)
        except Exception:
            pass


def _collect_summary_rows(start_dt: datetime, end_dt: datetime, club_id: int | None = None) -> list[dict]:
    """
    Collect assessment runs finished within [start_dt, end_dt] along with pillar scores.
    Returns list of dicts: {
      'name': str,
      'finished_at': datetime,
      'overall': float,
      'nutrition': float|None,
      'training': float|None,
      'resilience': float|None,
      'recovery': float|None,
      'user_id': int,
      'run_id': int,
    }
    """
    out: list[dict] = []
    with SessionLocal() as s:
        query = (
            s.query(AssessmentRun, User)
             .join(User, AssessmentRun.user_id == User.id)
             .filter(AssessmentRun.finished_at.isnot(None))
             .filter(AssessmentRun.finished_at >= start_dt)
             .filter(AssessmentRun.finished_at <= end_dt)
             .order_by(AssessmentRun.finished_at.desc())
        )
        if club_id is not None:
            query = query.filter(User.club_id == club_id)
        runs = query.all()
        if not runs:
            return out

        run_ids = [r.AssessmentRun.id for r in runs]
        # Load all pillar rows for these runs
        pillars = (
            s.query(PillarResult)
             .filter(PillarResult.run_id.in_(run_ids))
             .all()
        )
        by_run: dict[int, list[PillarResult]] = {}
        for pr in pillars:
            by_run.setdefault(getattr(pr, "run_id", 0), []).append(pr)

        for pair in runs:
            run: AssessmentRun = pair.AssessmentRun
            user: User = pair.User
            _ensure_dashboard_and_progress(user, run)
            plist = by_run.get(getattr(run, "id", 0), [])

            # Map pillar -> overall score for that pillar
            pmap: dict[str, float] = {}
            for pr in plist:
                key = (getattr(pr, "pillar_key", "") or "").lower()
                pmap[key] = _to_float(getattr(pr, "overall", None), None)

            # Overall: prefer stored combined_overall, else mean of available pillars
            combined = getattr(run, "combined_overall", None)
            if combined is None:
                vals = [v for v in [pmap.get("nutrition"), pmap.get("training"), pmap.get("resilience"), pmap.get("recovery")] if isinstance(v, (int, float))]
                combined = round(sum(vals) / max(1, len(vals)), 0) if vals else 0.0
            else:
                combined = round(_to_float(combined, 0.0)) if combined is not None else 0.0

            out.append({
                "name": _display_full_name(user),
                "role": _display_role(user),
                "finished_at": getattr(run, "finished_at", None),
                "overall": combined,
                "nutrition": pmap.get("nutrition"),
                "training": pmap.get("training"),
                "resilience": pmap.get("resilience"),
                "recovery": pmap.get("recovery"),
                "user_id": getattr(user, "id", None),
                "run_id": getattr(run, "id", None),
            "dashboard_url": _report_link(user.id, "latest.html"),
                "progress_url": _report_link(user.id, "progress.html"),
            })
    return out

def _write_summary_pdf(path: str, start_str: str, end_str: str, rows: list[dict]) -> None:
    """
    A4 landscape PDF listing assessments with per-pillar scores and overall.
    """
    try:
        from reportlab.platypus import BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
    except Exception as e:
        raise RuntimeError(f"reportlab not available: {e!r}")

    os.makedirs(os.path.dirname(path), exist_ok=True)

    doc = BaseDocTemplate(path, pagesize=landscape(A4), leftMargin=36, rightMargin=36, topMargin=30, bottomMargin=24)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="frame")

    def _on_page(c, _doc):
        c.setFont("Helvetica", 8)
        c.setFillGray(0.4)
        c.drawRightString(_doc.pagesize[0]-36, 18, f"Page {c.getPageNumber()}")

    doc.addPageTemplates([PageTemplate(id="with_footer", frames=[frame], onPage=_on_page)])
    styles = getSampleStyleSheet()
    from reportlab.lib.styles import ParagraphStyle
    wrap = ParagraphStyle('wrap', parent=styles['Normal'], fontSize=9, leading=11)
    story: list = []

    # Header
    title = Paragraph(f"<b>{BRAND_NAME} Assessment Summary Report</b>", styles["Title"])
    meta = Paragraph(f"Date range: {start_str} → {end_str}<br/>Generated: {_today_str()}", styles["Normal"])
    story += [title, Spacer(1, 6), meta, Spacer(1, 10)]

    # Summary stats
    total = len(rows)
    avg_overall = round(sum([_to_float(r.get("overall", 0.0), 0.0) for r in rows]) / max(1, total), 2) if rows else 0.0
    best = None
    if rows:
        best = max(rows, key=lambda r: _to_float(r.get("overall", 0.0), 0.0))
    best_line = f"Best performer: {best['name']} ({best['overall']})" if best else "Best performer: –"
    story += [Paragraph(f"Total assessments: {total}<br/>Average overall score: {avg_overall}<br/>{best_line}", styles["Normal"]), Spacer(1, 12)]

    # Table
    header = ["#", "Name", "Date Completed", "Overall", "Nutrition", "Training", "Resilience", "Recovery", "Assessment", "Progress"]
    data = [header]
    from reportlab.platypus import Paragraph
    for idx, r in enumerate(rows, start=1):
        dt = r.get("finished_at")
        date_str = ""
        if isinstance(dt, datetime):
            date_str = dt.strftime("%d-%b-%Y")
        # Wrap Name column so long user names don't overflow; escape HTML-sensitive chars
        name_text = str(r.get("name", "") or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        name_cell = Paragraph(name_text, wrap)
        dash_url = r.get("dashboard_url") or ""
        prog_url = r.get("progress_url") or ""
        dash_cell = Paragraph(f"<link href='{dash_url}' color='blue'>assessment</link>" if dash_url else "", wrap)
        prog_cell = Paragraph(f"<link href='{prog_url}' color='blue'>progress</link>" if prog_url else "", wrap)
        data.append([
            str(idx),
            name_cell,
            date_str,
            f"{_to_float(r.get('overall'), 0.0):.0f}",
            "" if r.get("nutrition") is None else f"{_to_float(r.get('nutrition'), 0.0):.0f}",
            "" if r.get("training")  is None else f"{_to_float(r.get('training'), 0.0):.0f}",
            "" if r.get("resilience") is None else f"{_to_float(r.get('resilience'), 0.0):.0f}",
            "" if r.get("recovery")  is None else f"{_to_float(r.get('recovery'), 0.0):.0f}",
            dash_cell,
            prog_cell,
        ])

    table = Table(data, repeatRows=1, colWidths=[24, 150, 90, 60, 60, 60, 70, 60, 90, 90])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#003366")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.whitesmoke),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("ALIGN", (0,0), (-1,-1), "CENTER"),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN", (1,1), (1,-1), "LEFT"),     # Name column
        ("VALIGN", (1,1), (1,-1), "TOP"),     # Name column
        ("GRID", (0,0), (-1,-1), 0.25, colors.grey),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
    ]))
    story.append(table)

    story.append(Spacer(1, 10))
    if BRAND_FOOTER:
        story.append(Paragraph(f"{BRAND_FOOTER}", styles["Normal"]))

    doc.build(story)

def _write_pdf(path: str, user: User, run: AssessmentRun, pillars: List[PillarResult]) -> None:
    """
    Render a landscape dashboard-style PDF:
      • Left: horizontal bar chart of pillar overalls (legend top-right inside chart)
      • Right: four feedback cards with pillar symbol, score-colored header, feedback + two next steps
      • Header title uses overall score (combined_overall if present; computed fallback)
      • Footer shows completion date (run.finished_at if present, else today UTC)

    Also writes a sibling JPEG (latest.jpeg) next to the PDF for web preview.
    """
    # Lazy imports so app can start even if report deps are missing
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyBboxPatch, Patch
    except Exception as e:
        raise RuntimeError(f"matplotlib not available: {e!r}")

    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.pdfgen import canvas
    except Exception as e:
        raise RuntimeError(f"reportlab not available: {e!r}")

    _audit("report_start", "ok", {"user_id": getattr(user, "id", None), "run_id": getattr(run, "id", None), "out_pdf": path})

    # ---------- Prepare data ----------
    ordered_keys = _pillar_order()
    # Map pillar_key -> PillarResult
    pr_map: Dict[str, PillarResult] = {getattr(pr, "pillar_key", ""): pr for pr in pillars}

    # Compute combined score (prefer DB field)
    combined = getattr(run, "combined_overall", None)
    if combined is None:
        vals = []
        for k in ordered_keys:
            pr = pr_map.get(k)
            if pr and getattr(pr, "overall", None) is not None:
                vals.append(int(getattr(pr, "overall", 0) or 0))
        combined = round(sum(vals) / max(1, len(vals))) if vals else 0
    combined = int(combined)

    # Fetch OKRs (structured if available) to populate cards
    okr_map = _fetch_okrs_for_run(getattr(run, 'id', None))

    # Build simple structure for plotting/cards
    cards: List[Dict[str, Any]] = []
    bar_labels: List[str] = []
    bar_values: List[int] = []
    bar_colors: List[tuple] = []

    for k in ordered_keys:
        pr = pr_map.get(k)
        if not pr:
            continue
        score = int(getattr(pr, "overall", 0) or 0)
        bar_labels.append(_title_for_pillar(k))
        bar_values.append(score)
        bar_colors.append(_score_color_rgb(score))

        # Prefer OKR tables for Objective/KRs only; no fallback to advice
        fb_line = ''
        bullets: List[str] = []
        okr_obj = okr_map.get(k, None)
        if okr_obj:
            fb_line = (okr_obj.get('objective') or '').strip()
            for t in (okr_obj.get('krs') or [])[:3]:
                t = (t or '').strip()
                if t:
                    bullets.append(t)
        cards.append({
            "pillar_key": k,
            "symbol": _pillar_symbol(k),
            "title": _title_for_pillar(k),
            "score": score,
            "feedback": fb_line,
            "steps": bullets,
        })



    # ---------- Draw dashboard to JPEG ----------
    # Figure sized for A4 landscape proportions (approx)
    fig = plt.figure(figsize=(16, 10))
    fig.patch.set_facecolor("white")

    # Bar chart aligned to card grid (top ≈ 0.89, bottom ≈ 0.22)
    ax_chart = fig.add_axes([0.06, 0.22, 0.38, 0.67])
    y_pos = range(len(bar_labels))
    ax_chart.barh(y_pos, bar_values, color=bar_colors)
    ax_chart.set_yticks(y_pos)
    ax_chart.set_yticklabels(bar_labels, fontsize=11)
    ax_chart.set_xlim(0, 100)
    ax_chart.invert_yaxis()
    ax_chart.set_xlabel("Score / 100")
    ax_chart.set_title("Pillar Overall Scores", fontsize=13, pad=8)

    # Legend (inside top-right)
    legend_elements = [
        Patch(facecolor=_score_color_rgb(85), label='Strong (≥ 80)'),
        Patch(facecolor=_score_color_rgb(70), label='Good (60–79)'),
        Patch(facecolor=_score_color_rgb(40), label='Needs focus (< 60)')
    ]
    ax_chart.legend(handles=legend_elements, loc='upper right', fontsize=9, frameon=True)

    # Feedback cards grid (2 x 2)
    card_w, card_h = 0.22, 0.31
    x0s = [0.50, 0.74]
    y0s = [0.58, 0.22]
    idx = 0
    for r in range(2):
        for c in range(2):
            if idx >= len(cards):
                break
            p = cards[idx]; idx += 1
            x0, y0 = x0s[c], y0s[r]
            ax_card = fig.add_axes([x0, y0, card_w, card_h])
            ax_card.axis("off")
            header_color = _score_color_rgb(p["score"]) 
            # Header strip
            ax_card.add_patch(FancyBboxPatch((0,0.83), 1, 0.17, boxstyle="round,pad=0.005,rounding_size=0.02",
                                             facecolor=header_color, edgecolor="none", transform=ax_card.transAxes))
            header_text = f"{p['symbol']} {p['title']} — {p['score']}/100"
            ax_card.text(0.03, 0.915, header_text, fontsize=11, fontweight="bold", color="white",
                         va="center", ha="left", transform=ax_card.transAxes)
            # Body box
            ax_card.add_patch(FancyBboxPatch((0,0), 1, 0.83, boxstyle="round,pad=0.02,rounding_size=0.02",
                                             facecolor=(0.97,0.97,0.97), edgecolor=(0.9,0.9,0.9), linewidth=1,
                                             transform=ax_card.transAxes))

            # Pull per-card content (avoid NameError)
            fb = (p.get("feedback") or "").strip()
            steps = (p.get("steps") or [])

            # Consistent vertical spacing between subheaders and their text blocks
            SUBHEAD_TO_TEXT_GAP = 0.09

            # Quarter Objective
            obj_subhead_y = 0.72
            ax_card.text(0.04, obj_subhead_y, "Quarter Objective", fontsize=10, fontweight="bold",
                         ha="left", va="top", transform=ax_card.transAxes)
            if fb:
                fb_block = _wrap_block(fb, width=44, max_lines=8, bullet=None)
                obj_text_y = obj_subhead_y - SUBHEAD_TO_TEXT_GAP
                ax_card.text(0.04, obj_text_y, fb_block, fontsize=9.5,
                             ha="left", va="top", transform=ax_card.transAxes)

            # Key Results
            if steps:
                kr_subhead_y = 0.49
                ax_card.text(0.04, kr_subhead_y, "Key Results", fontsize=10, fontweight="bold",
                             ha="left", va="top", transform=ax_card.transAxes)

                kr_lines = []
                for i, s in enumerate(steps[:3], start=1):
                    s = (s or "").strip()
                    if not s:
                        continue
                    kr_lines.append(_wrap_block(s, width=44, max_lines=2, bullet=f"{i}. "))
                if kr_lines:
                    kr_block = "\n".join(kr_lines)
                    kr_text_y = kr_subhead_y - SUBHEAD_TO_TEXT_GAP
                    ax_card.text(0.04, kr_text_y, kr_block, fontsize=9.5,
                                 ha="left", va="top", transform=ax_card.transAxes)


    # Page title: overall score + user name
    fig.suptitle(f"Overall Score: {combined}/100\nWellbeing Assessment for {_display_full_name(user)}",
                 fontsize=18, fontweight="bold")

    fig.tight_layout(rect=[0, 0.06, 1, 0.94])

    # Add completion footer directly to the figure (so PNG/JPEG include it)
    dt_fig = getattr(run, "finished_at", None) or datetime.utcnow()
    if not isinstance(dt_fig, datetime):
        dt_fig = datetime.utcnow()
    fig.text(0.01, 0.01, f"Completed on: {dt_fig.strftime('%B %d, %Y')}", fontsize=9, color=(0.3,0.3,0.3), ha='left', va='bottom')

    # Save dashboard image robustly (PNG → JPEG fallback)
    out_dir = os.path.dirname(path)
    os.makedirs(out_dir, exist_ok=True)
    png_path = os.path.join(out_dir, "latest.png")
    jpg_path = os.path.join(out_dir, "latest.jpeg")

    try:
        fig.savefig(png_path, dpi=180, bbox_inches="tight", format="png")
        _audit("report_png_saved", "ok", {"png_path": png_path})
    except Exception as e:
        _audit("report_png_saved", "error", {"png_path": png_path}, error=str(e))
        raise
    finally:
        plt.close(fig)

    # Convert PNG → JPEG
    try:
        from PIL import Image
        with Image.open(png_path) as im:
            if im.mode in ("RGBA", "LA"):
                from PIL import Image as _Image
                bg = _Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            im.save(jpg_path, "JPEG", quality=90, optimize=True, progressive=True)
        _audit("report_jpeg_saved", "ok", {"jpeg_path": jpg_path})
    except Exception as e:
        import shutil
        shutil.copyfile(png_path, jpg_path)
        _audit("report_jpeg_saved_fallback", "warn", {"jpeg_path": jpg_path, "png_path": png_path}, error=str(e))

    try:
        pdf = canvas.Canvas(path, pagesize=landscape(A4))
        width, height = landscape(A4)

        # ── Page 1: Introduction / How to read this report ────────────────
        left = 40
        right = width - 40
        top = height - 40
        line_w = right - left

        # Title
        pdf.setFont("Helvetica-Bold", 22)
        pdf.drawString(left, top, "Wellbeing Assessment – How to Read This Report")

        # Subtitle
        _nm = _display_full_name(user)
        _dt_disp = getattr(run, "finished_at", None) or datetime.utcnow()
        if not isinstance(_dt_disp, datetime):
            _dt_disp = datetime.utcnow()
        pdf.setFont("Helvetica", 11)
        pdf.setFillGray(0.35)
        pdf.drawString(left, top - 22, f"For: {_nm}   •   Completed: {_dt_disp.strftime('%d %b %Y')}")
        pdf.setFillGray(0.0)

        # Paragraph writer
        def _write_para(y, text, font_size=12, leading=16, indent=0):
            import textwrap as _tw
            pdf.setFont("Helvetica", font_size)
            wrapped = _tw.fill(text, width=max(20, int((line_w - indent) / 6.0)))
            t = pdf.beginText()
            t.setTextOrigin(left + indent, y)
            t.setLeading(leading)
            for ln in wrapped.split("\n"):
                t.textLine(ln)
            pdf.drawText(t)
            lines = wrapped.count("\n") + 1
            return y - lines * leading

        def _write_heading(y, text):
            pdf.setFont("Helvetica-Bold", 14)
            pdf.drawString(left, y, text)
            return y - 18

        y = top - 54
        y = _write_heading(y, "Purpose of This Report")
        y = _write_para(y, (
            "This report provides a snapshot of your current wellbeing across four key areas — "
            "Nutrition, Training, Resilience, and Recovery. It combines your assessment results "
            "with goal-oriented OKRs to help you focus on the habits that drive performance and wellbeing.")) - 8

        y = _write_heading(y, "How to Read Your Scores")
        y = _write_para(y, (
            "Overall Score summarises balance across all pillars (out of 100). Pillar bars show strengths and "
            "areas that need attention: Strong (≥ 80), Good (60–79), Needs Focus (< 60).")) - 8

        y = _write_heading(y, "Understanding Objectives and Key Results (OKRs)")
        y = _write_para(y, (
            "Each pillar includes a Quarter Objective — a focused aim for the next 12 weeks — and up to three "
            "Key Results (KRs), which are measurable actions or outcomes that indicate progress toward the objective.")) - 6
        # Example block
        pdf.setFont("Helvetica-Oblique", 11)
        pdf.drawString(left + 12, y, "Example:")
        y -= 16
        pdf.setFont("Helvetica", 11)
        y = _write_para(y, "Quarter Objective: Improve overall nutrition quality.", font_size=11, indent=12)
        y = _write_para(y, "1. Increase fruit and vegetable intake.", font_size=11, indent=12)
        y = _write_para(y, "2. Reduce processed food consumption.", font_size=11, indent=12)
        y = _write_para(y, "3. Maintain adequate protein intake.", font_size=11, indent=12) - 8

        y = _write_heading(y, "How to Use This Report")
        y = _write_para(y, (
            "Review your lowest pillar for the biggest impact, track progress using the listed KRs, and re-assess "
            "each quarter to measure improvement and adjust goals.")) - 8

        y = _write_heading(y, "Next Steps")
        y = _write_para(y, (
            "Focus on 1–2 pillars over the next quarter, embed the KRs as weekly habits, and revisit your goals in 12 weeks."))

        # Footer (intro page)
        pdf.setFillGray(0.35)
        pdf.setFont("Helvetica", 9)
        if BRAND_FOOTER:
            pdf.drawRightString(right, 18, f"{BRAND_FOOTER} — Confidential wellbeing report")
        pdf.setFillGray(0.0)
        pdf.showPage()

        # ── Page 2: Dashboard image ─────────────────────────────────────────
        pdf.drawImage(jpg_path, 0, 0, width=width, height=height, preserveAspectRatio=True, mask='auto')
        dt = getattr(run, "finished_at", None) or datetime.utcnow()
        if not isinstance(dt, datetime):
            dt = datetime.utcnow()
        pdf.setFillGray(0.3)
        pdf.setFont("Helvetica", 9)
        pdf.drawString(20, 14, f"Completed on: {dt.strftime('%B %d, %Y')}")
        pdf.setFillGray(0.0)

        pdf.showPage()
        pdf.save()
        _audit("report_pdf_saved", "ok", {"pdf_path": path})
        print(f"📄 PDF written to {path}")
    except Exception as e:
        _audit("report_pdf_saved", "error", {"pdf_path": path}, error=str(e))
        raise

def generate_assessment_report_pdf(run_id: int) -> str:
    """
    Public entry point to generate a PDF for the given assessment run.
    Returns the absolute path to the generated PDF.
    Raises if reportlab missing or if run not found.
    """
    user, run, pillars = _collect_report_data(run_id)
    if not user or not run:
        raise RuntimeError("Assessment run not found")
    root = _reports_root_for_user(user.id)
    out_path = os.path.join(root, "latest.pdf")
    _write_pdf(out_path, user, run, pillars)
    # audit success
    try:
        with SessionLocal() as s:
            s.add(JobAudit(job_name="report_generate", status="ok",
                           payload={"run_id": run_id, "user_id": user.id, "path": out_path}))
            s.commit()
    except Exception:
        pass
    return out_path

def generate_assessment_dashboard_html(run_id: int) -> str:
    _audit("dashboard_html_start", "ok", {"run_id": run_id})
    user, run, pillars = _collect_report_data(run_id)
    if not user or not run:
        raise ValueError("Assessment run not found")

    okr_map = _fetch_okrs_for_run(run.id)
    qa_by_pillar = _collect_run_dialogue(run.id)
    ordered_keys = _pillar_order()
    pr_map = {getattr(pr, "pillar_key", ""): pr for pr in pillars}
    user_prefs = _load_user_preferences(getattr(user, "id", None))

    combined = getattr(run, "combined_overall", None)
    if combined is None:
        vals = []
        for k in ordered_keys:
            pr = pr_map.get(k)
            if pr and getattr(pr, "overall", None) is not None:
                vals.append(int(getattr(pr, "overall", 0) or 0))
        combined = round(sum(vals) / max(1, len(vals))) if vals else 0
    combined = int(combined)

    def _score_bucket(pct: int) -> str:
        if pct >= 80:
            return "high"
        if pct >= 60:
            return "mid"
        return "low"

    def _concept_scores_for(pr: PillarResult | None) -> Dict[str, float]:
        raw = getattr(pr, "concept_scores", None)
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                data = json.loads(raw)
                if isinstance(data, dict):
                    return data
            except Exception:
                return {}
        try:
            return dict(raw)
        except Exception:
            return {}

    def _score_row(label: str, pct: int | None) -> str:
        if pct is None:
            return ""
        pct = max(0, min(100, int(round(pct))))
        bucket = _score_bucket(pct)
        return (
            "<div class='score-row'>"
            f"<div class='score-label'>{html.escape(label)}</div>"
            "<div class='score-track'>"
            f"<span class='score-fill {bucket}' style='width:{pct}%;'></span>"
            "</div>"
            f"<div class='score-value'>{pct}%</div>"
            "</div>"
        )

    def _concept_block(pr: PillarResult | None) -> str:
        scores = _concept_scores_for(pr)
        if not scores:
            return ""
        rows = []
        for code in sorted(scores.keys(), key=lambda c: _concept_display(c).lower()):
            val = scores.get(code)
            if val is None:
                continue
            pct = max(0, min(100, int(round(float(val)))))
            bucket = _score_bucket(pct)
            rows.append(
                "<div class='concept-row'>"
                f"<div class='concept-name'>{html.escape(_concept_display(code))}</div>"
                "<div class='concept-track'>"
                f"<span class='concept-fill {bucket}' style='width:{pct}%;'></span>"
                "</div>"
                f"<div class='concept-score'>{pct}%</div>"
                "</div>"
            )
        if not rows:
            return ""
        return f"<div class='concept-block'>{''.join(rows)}</div>"

    def _bucket_label(pct: int) -> tuple[str, str]:
        if pct >= 80:
            return "strong", "great momentum here—keep reinforcing the habits that already work."
        if pct >= 60:
            return "steady", "you’re on track; a few consistent tweaks will lift this pillar."
        return "emerging", "this pillar needs extra care; pick one doable habit to stabilise it."

    sections = []
    pillar_payload: list[dict] = []
    okr_payload: list[dict] = []
    today = _today_str()
    for key in ordered_keys:
        pr = pr_map.get(key)
        if not pr:
            continue
        score = int(getattr(pr, "overall", 0) or 0)
        okr = okr_map.get(key, {})
        objective = html.escape(okr.get("objective", "") or "Not available yet.")
        krs = okr.get("krs") or []
        kr_lines = "".join(f"<li>{html.escape(kr)}</li>" for kr in krs[:3] if kr) or "<li>No key results yet.</li>"

        score_pct = max(0, min(100, score))
        focus_note = ""
        if key == "training":
            focus_note = (user_prefs.get("training_focus") or "").strip()
        pillar_payload.append({
            "pillar_key": key,
            "pillar_name": _title_for_pillar(key),
            "score": score_pct,
            "concept_scores": _concept_scores_for(pr),
            "qa_samples": qa_by_pillar.get(key, []),
            "focus_note": focus_note,
        })
        okr_payload.append({
            "pillar_key": key,
            "pillar_name": _title_for_pillar(key),
            "score": score_pct,
            "objective": okr.get("objective", ""),
            "key_results": krs[:3],
            "focus_note": focus_note,
        })

        sections.append(
            f"<section data-pillar='{html.escape(key)}'>"
            "<div class='pillar-head'>"
            f"<h2>{html.escape(_title_for_pillar(key))}</h2>"
            "<div class='pillar-score'>"
            f"<span class='score-value'>{score_pct}%</span>"
            "<div class='score-track'>"
            f"<span class='score-fill {_score_bucket(score_pct)}' style='width:{score_pct}%'></span>"
            "</div>"
            "</div>"
            "</div>"
            f"{_concept_block(pr)}"
            "<div class='okr-card'>"
            "<h3>This Quarter Objective</h3>"
            f"<p>{objective}</p>"
            "<h3>Key Results</h3>"
            f"<ul>{kr_lines}</ul>"
            "</div>"
            "</section>"
        )

    first_name = (getattr(user, "first_name", None) or "").strip()
    first = first_name or "there"

    score_narrative = _score_narrative_from_llm(user, combined, pillar_payload) \
        or _scores_narrative_fallback(combined, pillar_payload)
    okr_narrative = _okr_narrative_from_llm(user, okr_payload) \
        or _okr_narrative_fallback(okr_payload)
    coaching_text = _coaching_approach_text(getattr(user, "id", None))
    coaching_block = ""
    if coaching_text:
        coaching_block = (
            "<div class='card coach-card'>"
            "<h2>Coaching approach</h2>"
            f"{_llm_text_to_html(coaching_text)}"
            "</div>"
        )
    score_rows = [
        _score_row("Combined", combined),
        _score_row("Nutrition", int(getattr(pr_map.get("nutrition"), "overall", None) or 0) if pr_map.get("nutrition") else None),
        _score_row("Training", int(getattr(pr_map.get("training"), "overall", None) or 0) if pr_map.get("training") else None),
        _score_row("Resilience", int(getattr(pr_map.get("resilience"), "overall", None) or 0) if pr_map.get("resilience") else None),
        _score_row("Recovery", int(getattr(pr_map.get("recovery"), "overall", None) or 0) if pr_map.get("recovery") else None),
    ]
    score_panel = "".join([row for row in score_rows if row]) or "<p class='score-empty'>Scores will appear here once available.</p>"
    reported_at = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")
    html_doc = f"""<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width, initial-scale=1'/>
  <title>Your Wellbeing Dashboard</title>
  <style>
    {FONT_FACE}
    body {{ margin: 0; padding: 16px; background: #f5f5f5; }}
    .card {{ background: #fff; border-radius: 12px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 6px rgba(0,0,0,0.06); }}
    .summary-card {{ display: flex; flex-direction: column; gap: 16px; }}
    .summary-main h1 {{ font-size: 1.45rem; margin-bottom: 4px; }}
    .summary-main p {{ margin: 4px 0; color: #333; }}
    .score-panel {{ background: #f7f9fc; border-radius: 12px; padding: 12px; }}
    .score-empty {{ margin: 0; color: #6b7280; font-size: 0.95rem; }}
    .score-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }}
    .score-row:last-child {{ margin-bottom: 0; }}
    .score-label {{ flex: 0 0 95px; font-weight: 600; color: #1f2933; }}
    .score-track {{ flex: 1; height: 8px; border-radius: 999px; background: #e4e8f1; overflow: hidden; }}
    .score-fill {{ display: block; height: 100%; border-radius: 999px; }}
    .score-fill.high {{ background: linear-gradient(90deg, #0ba360, #3cba92); }}
    .score-fill.mid {{ background: linear-gradient(90deg, #f6d365, #fda085); }}
    .score-fill.low {{ background: linear-gradient(90deg, #f76b1c, #f54b64); }}
    .score-value {{ width: 56px; text-align: right; font-weight: 600; color: #111827; font-variant-numeric: tabular-nums; }}
    .pillars-card section {{ margin-bottom: 32px; border-bottom: 1px solid #f0f0f0; padding-bottom: 24px; }}
    .pillars-card section:last-child {{ border-bottom: none; padding-bottom: 0; }}
    .pillar-head {{ display: flex; flex-direction: column; gap: 8px; }}
    .pillar-head h2 {{ font-size: 1.2rem; margin: 0; color: #0f172a; }}
    .pillar-score {{ display: flex; align-items: center; gap: 12px; }}
    .pillar-score .score-value {{ width: auto; }}
    .concept-block {{ margin: 12px 0 16px; border: 1px solid #edf1f7; border-radius: 12px; padding: 12px; background: #fafcff; }}
    .concept-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
    .concept-row:last-child {{ margin-bottom: 0; }}
    .concept-name {{ flex: 0 0 45%; font-weight: 600; color: #111827; }}
    .concept-track {{ flex: 1; height: 6px; border-radius: 999px; background: #e4e8f1; overflow: hidden; }}
    .concept-fill {{ display: block; height: 100%; border-radius: 999px; }}
    .concept-fill.high {{ background: linear-gradient(90deg, #0ba360, #3cba92); }}
    .concept-fill.mid {{ background: linear-gradient(90deg, #f6d365, #fda085); }}
    .concept-fill.low {{ background: linear-gradient(90deg, #f76b1c, #f54b64); }}
    .concept-score {{ width: 48px; text-align: right; font-weight: 600; font-variant-numeric: tabular-nums; color: #111827; }}
    .okr-card h3 {{ font-size: 1rem; margin: 12px 0 6px; color: #475467; }}
    .okr-card p {{ margin: 0 0 8px; color: #1f2933; line-height: 1.4; }}
    .okr-card ul {{ padding-left: 18px; margin: 0; color: #1f2933; }}
    .narrative-card h2 {{ margin-top: 0; font-size: 1.25rem; color: #0f172a; }}
    .narrative-card p {{ margin: 0 0 8px; color: #1f2933; line-height: 1.5; }}
    .narrative-card ul {{ margin: 0; padding-left: 18px; color: #111; }}
    .narrative-card li {{ margin-bottom: 6px; line-height: 1.4; }}
    .section {{ display: flex; flex-direction: column; gap: 16px; margin-bottom: 24px; }}
    .coach-card h2 {{ margin-top: 0; font-size: 1.15rem; color: #0f172a; }}
    .coach-card p {{ margin: 0; color: #1f2933; line-height: 1.5; }}
    @media (min-width: 720px) {{
      .section {{ flex-direction: row; align-items: flex-start; }}
      .section .narrative-card {{ flex: 1; }}
      .scores-section .summary-card {{ flex: 1; }}
      .okr-section .pillars-card {{ flex: 1; }}
      .pillar-head {{ flex-direction: row; justify-content: space-between; align-items: center; }}
      .summary-card {{ flex-direction: row; justify-content: space-between; align-items: flex-start; }}
      .summary-main {{ flex: 1; }}
      .score-panel {{ flex: 0 0 320px; }}
    }}
    @media (min-width: 720px) {{
      .section {{ margin-bottom: 32px; }}
    }}
  </style>
 </head>
 <body>
  <div class='section scores-section'>
    <div class='card summary-card'>
     <div class='summary-main'>
       <h1>HealthSense Wellbeing Assessment</h1>
       <p>Hi {html.escape(first)}, here's your latest assessment snapshot.</p>
       <p style='color:#475467;'>Updated {html.escape(today)}</p>
     </div>
     <div class='score-panel'>
       {score_panel}
     </div>
    </div>
    <div class='card narrative-card'>
      <h2>How you're doing</h2>
      {score_narrative}
    </div>
  </div>
  <div class='section okr-section'>
    <div class='card narrative-card'>
      <h2>Your OKR focus</h2>
      {okr_narrative}
    </div>
    <div class='card pillars-card'>
      {''.join(sections)}
    </div>
  </div>
  {coaching_block}
</body>
<div class='report-footer'>Positives on {reported_at} · {BRAND_FOOTER}</div>
</html>"""

    out_dir = _reports_root_for_user(user.id)
    out_path = os.path.join(out_dir, "latest.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return out_path

def generate_detailed_report_pdf_by_user(user_id: int) -> str:
    """Public entry point to generate the detailed (grouped) PDF for a user.
    Returns the absolute filesystem path to the generated PDF.
    """
    user, run, rows = _collect_detailed_report_data(user_id)
    if not user or not run:
        raise RuntimeError("Detailed report: user/run not found")
    root = _reports_root_for_user(user.id)
    out_path = os.path.join(root, "detailed.pdf")
    _write_detailed_pdf(out_path, user, run, rows)
    try:
        with SessionLocal() as s:
            s.add(JobAudit(job_name="detailed_report_generate", status="ok",
                           payload={"user_id": user.id, "run_id": getattr(run, 'id', None), "path": out_path}))
            s.commit()
    except Exception:
        pass
    return out_path

# Public entry point to generate summary PDF for a date range
def generate_assessment_summary_pdf(start: date | str, end: date | str, *, club_id: int | None = None) -> str:
    """
    Generate a PDF summarising assessments completed within the date range [start, end] (inclusive).
    Returns absolute filesystem path to the PDF.
    """
    start_dt, end_dt, start_str, end_str = _normalise_date_range(start, end)
    _audit("summary_report_start", "ok", {"start": start_str, "end": end_str})
    try:
        rows = _collect_summary_rows(start_dt, end_dt, club_id=club_id)
        out_root = _reports_root_global()
        filename = f"assessment-summary-{start_str}_{end_str}.pdf"
        out_path = os.path.join(out_root, filename)
        _write_summary_pdf(out_path, start_str, end_str, rows)
        with SessionLocal() as s:
            s.add(JobAudit(job_name="summary_report_generate", status="ok",
                           payload={"start": start_str, "end": end_str, "path": out_path, "count": len(rows)}))
            s.commit()
        return out_path
    except Exception as e:
        _audit("summary_report_generate", "error", {"start": start_str, "end": end_str}, error=str(e))
        raise
from .llm import _llm
def _collect_progress_rows(user_id: int) -> list[dict]:
    rows: list[dict] = []
    with SessionLocal() as s:
        objectives = (
            s.query(OKRObjective)
             .filter(OKRObjective.owner_user_id == user_id)
             .options(selectinload(OKRObjective.key_results), selectinload(OKRObjective.cycle))
             .order_by(OKRObjective.cycle_id.asc(), OKRObjective.pillar_key.asc(), OKRObjective.created_at.asc())
             .all()
        )
        state_cache: dict[int, dict[str, float]] = {}
        for obj in objectives:
            cycle = obj.cycle
            answers: dict[str, float] = {}
            src_pillar_id = getattr(obj, "source_pillar_id", None)
            if src_pillar_id:
                cached = state_cache.get(src_pillar_id)
                if cached is None:
                    try:
                        pr = s.get(PillarResult, src_pillar_id)
                    except Exception:
                        pr = None
                    if pr:
                        try:
                            ctx_rows = _build_state_context_from_models(
                                s,
                                user_id=getattr(obj, "owner_user_id", user_id),
                                run_id=getattr(pr, "run_id", None),
                                pillar_slug=obj.pillar_key,
                            )
                            cached = _answers_from_state_context(ctx_rows)
                        except Exception:
                            cached = {}
                    else:
                        cached = {}
                    state_cache[src_pillar_id] = cached
                answers = cached or {}

            kr_payload = []
            for kr in (getattr(obj, "key_results", []) or []):
                notes_dict = _kr_notes_dict(getattr(kr, "notes", None))
                concept_key = notes_dict.get("concept_key")
                if concept_key:
                    concept_key = concept_key.split(".")[-1]
                if not concept_key:
                    inferred = _guess_concept_from_description(obj.pillar_key, kr.description or "")
                    concept_key = inferred
                concept_key = _normalize_concept_key(concept_key) if concept_key else None
                state_val = answers.get(concept_key) if concept_key and answers else None
                # Prefer latest KR entry (e.g., Sunday check-in) over stored/state values
                cutoff = datetime.utcnow() - timedelta(days=8)
                latest_entry = (
                    s.query(OKRKrEntry)
                    .filter(OKRKrEntry.key_result_id == kr.id)
                    .filter(OKRKrEntry.occurred_at >= cutoff)
                    .order_by(OKRKrEntry.occurred_at.desc(), OKRKrEntry.id.desc())
                    .first()
                )
                entry_actual = getattr(latest_entry, "actual_num", None) if latest_entry else None
                baseline_val = kr.baseline_num if kr.baseline_num is not None else state_val
                actual_val = entry_actual if entry_actual is not None else (kr.actual_num if kr.actual_num is not None else state_val)
                _progress_debug(
                    "kr_baseline_choice",
                    {
                        "objective_id": getattr(obj, "id", None),
                        "kr_id": getattr(kr, "id", None),
                        "description": kr.description,
                        "concept_key": concept_key,
                        "notes_concept": notes_dict.get("concept_key"),
                        "state_val": state_val,
                        "stored_baseline": kr.baseline_num,
                        "stored_actual": kr.actual_num,
                        "entry_actual": entry_actual,
                        "final_baseline": baseline_val,
                        "final_actual": actual_val,
                    },
                )
                kr_payload.append({
                    "description": kr.description or "",
                    "id": kr.id,
                    "baseline": baseline_val,
                    "target": kr.target_num,
                    "unit": kr.unit,
                    "metric_label": kr.metric_label,
                    "actual": actual_val,
                })

            rows.append({
                "pillar": obj.pillar_key,
                "objective": obj.objective or "",
                "krs": kr_payload,
                "cycle_label": getattr(cycle, "title", None) or f"FY{getattr(cycle, 'year', '')} {getattr(cycle, 'quarter', '')}",
                "cycle_start": getattr(cycle, "starts_on", None),
                "cycle_end": getattr(cycle, "ends_on", None),
            })
    rows.sort(key=lambda r: (r.get("cycle_start") or datetime.min, r.get("pillar")))
    return rows

def _format_cycle_range(start: datetime | None, end: datetime | None) -> str:
    if isinstance(start, datetime) and isinstance(end, datetime):
        return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"
    if isinstance(start, datetime):
        return start.strftime("%d %b %Y")
    if isinstance(end, datetime):
        return end.strftime("%d %b %Y")
    return ""

def _format_number(val: float | None) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)) and float(val).is_integer():
        return str(int(val))
    return f"{val:.2f}".rstrip("0").rstrip(".")

def _render_progress_bar(current: float | None, target: float | None, baseline: float | None = None) -> str:
    try:
        cur = float(current) if current is not None else None
        tgt = float(target) if target is not None else None
    except Exception:
        cur = tgt = None
    percent = 0.0
    if cur is not None and tgt not in (None, 0, "0"):
        try:
            percent = max(0, min(100, (cur / float(tgt)) * 100))
        except Exception:
            percent = 0.0
    return (
        "<div class='progress-track'>"
        f"<div class='progress-fill' style='width:{percent}%;'></div>"
        "</div>"
    )

def _render_kr_table(krs: list[dict], focus_ids: set[int] | None = None, future_block: bool = False) -> str:
    if not krs:
        return "<p class='empty-kr'>No key results captured yet.</p>"
    focus_ids = focus_ids or set()
    rows = []
    for kr in krs:
        desc = html.escape(kr.get("description") or "Key Result")
        is_focus = kr.get("id") in focus_ids
        baseline = _format_number(kr.get("baseline"))
        target = _format_number(kr.get("target"))
        actual_val = kr.get("actual")
        actual = _format_number(actual_val)
        target_val = kr.get("target")
        pct = None
        status = "not started"
        if target_val is not None and actual_val is not None and target_val not in (0, "0"):
            try:
                pct = max(0, min(1, float(actual_val) / float(target_val)))
            except Exception:
                pct = None
        if future_block:
            status = "not started"
            pct_display = "–"
        else:
            if pct is None:
                status = "not started"
            elif pct >= 0.9:
                status = "on track"
            elif pct >= 0.5:
                status = "at risk"
            else:
                status = "off track"
            pct_display = f"{int(pct * 100)}%" if pct is not None else "–"
        badge = "<div class='focus-badge'>Focus KR</div>" if is_focus else ""
        rows.append(
            "<tr>"
            f"<td>{desc}{badge}"
            f"<div class='kr-unit'>Status: <span class='chip {status.replace(' ', '-')}'>{status.title()}</span></div></td>"
            f"<td>{baseline or '–'}</td>"
            f"<td>{actual or '–'}</td>"
            f"<td>{target or '–'}</td>"
            f"<td>"
            f"<div class='progress-row'><span class='pct'>{pct_display}</span>{_render_progress_bar(actual_val, target_val, kr.get('baseline'))}</div>"
            f"</td>"
            "</tr>"
        )
    return (
        "<table class='kr-table'>"
        "<thead><tr>"
        "<th>Description</th><th>Baseline</th><th>Current</th><th>Target</th><th>Progress</th>"
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )

def generate_progress_report_html(user_id: int, anchor_date: date | None = None) -> str:
    anchor_today = anchor_date or datetime.utcnow().date()
    anchor_label = anchor_today.strftime("%d %b %Y")
    def _habit_readiness_panel(u_id: int, first_name: str) -> str:
        with SessionLocal() as ss:
            prof = (
                ss.query(PsychProfile)
                .filter(PsychProfile.user_id == u_id)
                .order_by(PsychProfile.completed_at.desc().nullslast(), PsychProfile.id.desc())
                .first()
            )
        if not prof:
            return ""
        sec = getattr(prof, "section_averages", {}) or {}
        vals = [v for v in sec.values() if isinstance(v, (int, float))]
        avg = sum(vals) / len(vals) if vals else None
        if avg is None:
            return ""
        if avg < 2.6:
            label = "Low"
            tint = "#fff4e5"
            border = "#f8b84a"
            note = "We’ll keep things light, add structure, and focus on simple wins this week."
        elif avg < 3.6:
            label = "Moderate"
            tint = "#e6f4ff"
            border = "#8ac2ff"
            note = "We’ll balance guidance with autonomy and check in on any sticking points."
        else:
            label = "High"
            tint = "#e8f7f0"
            border = "#5cbf82"
            note = "You can handle more autonomy; we’ll keep nudges concise and goal-focused."
        readiness_str = f"{int(round(avg))}/5" if isinstance(avg, (int, float)) else "N/A"
        return (
            f"<div class='readiness-card' style='border:1px solid {border}; background:{tint}; border-radius:12px; padding:12px; margin:16px 0;'>"
            f"<div style='display:flex; justify-content:space-between; align-items:center;'>"
            f"<div><strong>Habit readiness</strong></div>"
            f"<div style='font-weight:700;'>{label}</div>"
            f"</div>"
            f"<div style='color:#475467; margin-top:6px;'>Profile: {readiness_str} · Tailoring: {note}</div>"
            "</div>"
        )

    with SessionLocal() as s:
        user = s.query(User).filter(User.id == user_id).one_or_none()
        if not user:
            raise RuntimeError("User not found")
        # Latest weekly focus for this user (use anchor_today to pick current)
        today = anchor_today
        wf = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id, WeeklyFocus.starts_on <= today, WeeklyFocus.ends_on >= today)
            .order_by(WeeklyFocus.starts_on.desc())
            .first()
        ) or (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id)
            .order_by(WeeklyFocus.starts_on.desc())
            .first()
        )
        focus_kr_ids = []
        if wf:
            focus_kr_ids = [
                row.kr_id for row in s.query(WeeklyFocusKR).filter(WeeklyFocusKR.weekly_focus_id == wf.id).all()
            ]
    rows = _collect_progress_rows(user_id)
    reported_at = datetime.utcnow().strftime("%d %b %Y %H:%M UTC")
    css = """
    <style>
      {FONT_FACE}
      body { margin:24px; color:#101828; }
      h1 { margin-bottom: 4px; }
      .meta { color:#475467; margin-bottom:16px; }
      .scorecard { border:1px solid #e4e7ec; border-radius:12px; padding:16px; margin: 16px 0 24px 0; background:#f8fafc; }
      .scorecard h2 { margin:0 0 8px 0; font-size:1.05rem; }
      .scorecard .summary { display:flex; gap:12px; flex-wrap:wrap; color:#344054; }
      .status-grid { display:flex; flex-wrap:wrap; gap:10px; }
      .status-box { flex:1 1 150px; padding:10px 12px; border-radius:10px; border:1px solid #e4e7ec; }
      .status-box .label { font-weight:700; color:#0f172a; }
      .status-box .value { font-weight:700; font-size:1.1rem; }
      .status-on { background:#ecfdf3; border-color:#c6f6d5; color:#065f46; }
      .status-risk { background:#fff7ed; border-color:#fed7aa; color:#9a3412; }
      .status-off { background:#fef2f2; border-color:#fecdd3; color:#b91c1c; }
      .status-not { background:#eff6ff; border-color:#bfdbfe; color:#1d4ed8; }
      .chip { padding:2px 8px; border-radius:999px; font-size:0.8rem; font-weight:600; display:inline-block; }
      .chip.on-track { background:#ecfdf3; color:#027a48; }
      .chip.at-risk { background:#fff7ed; color:#c2410c; }
      .chip.off-track { background:#fef2f2; color:#b42318; }
      .chip.not-started { background:#f4f4f5; color:#52525b; }
      .timeline { border-left: 3px solid #d0d5dd; margin-left: 8px; padding-left: 24px; }
      .entry { margin-bottom: 24px; position: relative; border-radius:10px; padding:10px; }
      .entry::before { content: ''; width: 10px; height: 10px; background:#0ba5ec; border-radius:50%; position:absolute; left:-29px; top:6px; }
      .entry h2 { margin:0; font-size:1.1rem; color:#0f172a; }
      .objective { font-weight:600; margin:8px 0; }
      .cycle { color:#475467; font-size:0.95rem; margin-bottom:6px; }
      ul { margin:0 0 0 18px; color:#1d2939; }
      .empty-kr { color:#98a2b3; font-style:italic; margin:4px 0 0 0; }
      .focus-strip { margin:8px 0; color:#0f172a; }
      .focus-pill { display:inline-block; background:#fef3c7; color:#92400e; padding:4px 8px; border-radius:8px; margin:4px 4px 0 0; font-weight:600; font-size:0.9rem; }
      .kr-table { width:100%; border-collapse: collapse; margin-top:10px; }
      .kr-table th, .kr-table td { border:1px solid #e4e7ec; padding:8px 10px; text-align:left; font-size:0.95rem; vertical-align: top; }
      .kr-table th { background:#f8fafc; font-weight:600; color:#0f172a; }
      .progress-track { width:100%; height:8px; background:#e4e7ec; border-radius:999px; overflow:hidden; }
      .progress-fill { height:100%; background:linear-gradient(90deg,#0ba5ec,#3cba92); border-radius:999px; }
      .progress-row { display:flex; align-items:center; gap:8px; }
      .pct { font-weight:600; color:#101828; }
      .kr-unit { color:#98a2b3; font-size:0.8rem; margin-top:2px; }
      .focus-badge { display:inline-block; background:#fef3c7; color:#92400e; padding:2px 6px; border-radius:6px; font-size:0.75rem; font-weight:700; margin-left:6px; }
    .report-footer { margin-top: 24px; font-size: 0.85rem; color: #98a2b3; text-align: right; }
      .programme { border:1px solid #e4e7ec; border-radius:12px; padding:14px; margin:16px 0; background:#fff; }
      .programme h3 { margin:0 0 8px 0; font-size:1rem; }
      .programme-row { display:flex; flex-wrap:wrap; gap:8px; }
      .programme-pill { flex:1 1 160px; border:1px solid #e4e7ec; border-radius:10px; padding:10px; background:#f8fafc; }
      .programme-pill .label { font-weight:700; color:#0f172a; }
      .programme-pill .weeks { color:#475467; font-size:0.9rem; }
      .programme-pill .focus { margin-top:4px; color:#111827; }
      .programme-pill.nutrition { border-color:#0ba5ec; background:#ebf8ff; }
      .programme-pill.recovery { border-color:#a855f7; background:#f5f3ff; }
      .programme-pill.training { border-color:#22c55e; background:#ecfdf3; }
      .programme-pill.resilience { border-color:#f97316; background:#fff7ed; }
      .entry.nutrition { background:#f0f9ff; }
      .entry.nutrition::before { background:#0ba5ec; }
      .entry.recovery { background:#f8f5ff; }
      .entry.recovery::before { background:#a855f7; }
      .entry.training { background:#ecfdf3; }
      .entry.training::before { background:#22c55e; }
      .entry.resilience { background:#fff7ed; }
      .entry.resilience::before { background:#f97316; }
    </style>
    """
    def _coaching_approach_text(user_id: int) -> str:
        return ""
    # Simple scorecard summary (counts by status)
    programme_offsets = {"nutrition": 0, "recovery": 3, "training": 6, "resilience": 9}
    def _future_block(pillar_key: str, start_dt):
        blk_start = None
        if isinstance(start_dt, datetime):
            blk_start = (start_dt + timedelta(weeks=programme_offsets.get(pillar_key, 0))).date()
        elif isinstance(start_dt, date):
            blk_start = start_dt + timedelta(weeks=programme_offsets.get(pillar_key, 0))
        if blk_start is None:
            return False
        return anchor_today < blk_start

    status_counts = {"on track": 0, "at risk": 0, "off track": 0, "not started": 0}
    total_krs = 0
    for row in rows:
        future = _future_block(row.get("pillar") or "", row.get("cycle_start"))
        for kr in row.get("krs") or []:
            total_krs += 1
            if future:
                status_counts["not started"] += 1
                continue
            target_val = kr.get("target")
            actual_val = kr.get("actual") if kr.get("actual") is not None else kr.get("baseline")
            pct = None
            if target_val is not None and actual_val is not None and target_val not in (0, "0"):
                try:
                    pct = max(0, min(1, float(actual_val) / float(target_val)))
                except Exception:
                    pct = None
            if pct is None:
                status_counts["not started"] += 1
            elif pct >= 0.9:
                status_counts["on track"] += 1
            elif pct >= 0.5:
                status_counts["at risk"] += 1
            else:
                status_counts["off track"] += 1

    # Programme overview (12-week, 3-week blocks by pillar)
    blocks = [
        ("Weeks 1–3", "Nutrition", "nutrition"),
        ("Weeks 4–6", "Recovery", "recovery"),
        ("Weeks 7–9", "Training", "training"),
        ("Weeks 10–12", "Resilience", "resilience"),
    ]
    programme_html = (
        "<div class='programme'>"
        "<h3>12-week programme (3-week focus blocks)</h3>"
        "<div class='programme-row'>"
        + "".join(
            f"<div class='programme-pill {css_class}'>"
            f"<div class='label'>{label}</div>"
            f"<div class='weeks'>{weeks}</div>"
            f"<div class='focus'>Focus: {label}</div>"
            "</div>"
            for weeks, label, css_class in blocks
        )
        + "</div></div>"
    )

    focus_titles = []
    items = []
    # Group rows by pillar for ordering and cycle labeling
    by_pillar: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_pillar[row.get("pillar", "")].append(row)
    programme_order = ["nutrition", "recovery", "training", "resilience"]
    # Programme weeks and static date labels (can be adjusted to actual calendar if available)
    weeks_map = {
        "nutrition": "Weeks 1–3",
        "recovery": "Weeks 4–6",
        "training": "Weeks 7–9",
        "resilience": "Weeks 10–12",
    }
    ordered_rows = []
    for p in programme_order:
        ordered_rows.extend(by_pillar.get(p, []))
    # add any remaining pillars not in the standard order
    for p, vals in by_pillar.items():
        if p not in programme_order:
            ordered_rows.extend(vals)

    programme_offsets = {"nutrition": 0, "recovery": 3, "training": 6, "resilience": 9}
    for row in ordered_rows:
        cycle_bits = [row.get("cycle_label"), _format_cycle_range(row.get("cycle_start"), row.get("cycle_end"))]
        default_cycle = " · ".join([b for b in cycle_bits if b])
        pillar_key = row.get("pillar") or ""
        # Show week window + dates if we have them
        week_label = weeks_map.get(pillar_key)
        date_label = ""
        start_dt = row.get("cycle_start")
        future_block = False
        blk_start = None
        if isinstance(start_dt, datetime):
            offset_weeks = programme_offsets.get(pillar_key, 0)
            blk_start = (start_dt + timedelta(weeks=offset_weeks)).date()
        elif isinstance(start_dt, date):
            blk_start = start_dt + timedelta(weeks=programme_offsets.get(pillar_key, 0))
        if blk_start:
            blk_end = blk_start + timedelta(days=20)  # 3-week block
            date_label = f"{blk_start.strftime('%d %b %Y')} – {blk_end.strftime('%d %b %Y')}"
            if anchor_today < blk_start:
                future_block = True
        cycle_text = " · ".join([lbl for lbl in [week_label, date_label] if lbl]) or default_cycle
        krs = row.get("krs") or []
        kr_block = _render_kr_table(krs, focus_ids=set(focus_kr_ids), future_block=future_block)
        for kr in krs:
            if kr.get("id") in focus_kr_ids:
                focus_titles.append(kr.get("description") or "")
        items.append(
            f"<div class='entry {html.escape(pillar_key)}'>"
            f"<div class='cycle'>{html.escape(cycle_text or '')}</div>"
            f"<h2>{html.escape(_title_for_pillar(row['pillar']))}</h2>"
            f"<div class='objective'>Objective: {html.escape(row['objective'] or 'TBA')}</div>"
            f"{kr_block}"
            "</div>"
        )
    focus_strip = ""
    if focus_titles:
        pills = "".join(f"<span class='focus-pill'>{html.escape(t)}</span>" for t in focus_titles)
        focus_strip = f"<div class='focus-strip'><strong>This week’s focus KRs:</strong> {pills}</div>"
    display_name = (getattr(user, "first_name", None) or "").strip() or "there"
    readiness_html = _habit_readiness_panel(user_id, display_name)
    programme_html = (
        "<div class='programme'>"
        "<h3>12-week programme (3-week focus blocks)</h3>"
        "<div class='programme-row'>"
        "<div class='programme-pill nutrition'><div class='label'>Nutrition</div><div class='weeks'>Weeks 1–3</div><div class='focus'>Focus: Nutrition</div></div>"
        "<div class='programme-pill recovery'><div class='label'>Recovery</div><div class='weeks'>Weeks 4–6</div><div class='focus'>Focus: Recovery</div></div>"
        "<div class='programme-pill training'><div class='label'>Training</div><div class='weeks'>Weeks 7–9</div><div class='focus'>Focus: Training</div></div>"
        "<div class='programme-pill resilience'><div class='label'>Resilience</div><div class='weeks'>Weeks 10–12</div><div class='focus'>Focus: Resilience</div></div>"
        "</div></div>"
    )
    display_name = (getattr(user, "first_name", None) or "").strip() or "there"
    html_doc = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>{html.escape(display_name)} your HealthSense progress report — {anchor_label}</title>
{css}
<div style="text-align:center; background:#e6f4ff; border:1px solid #bee3ff; border-radius:12px; padding:12px;">
<h1 style="margin:0;">{html.escape(display_name)} your HealthSense progress report</h1>
<div class="meta">Report date: {anchor_label} (generated {reported_at})</div>
</div>
<div class="scorecard">
   <h2>This week your key results at a glance</h2>
   <div class="status-grid">
     <div class="status-box status-on"><div class="label">On track</div><div class="value">{status_counts['on track']}</div></div>
     <div class="status-box status-risk"><div class="label">At risk</div><div class="value">{status_counts['at risk']}</div></div>
     <div class="status-box status-off"><div class="label">Off track</div><div class="value">{status_counts['off track']}</div></div>
     <div class="status-box status-not"><div class="label">Not started</div><div class="value">{status_counts['not started']}</div></div>
     <div class="status-box"><div class="label">Total</div><div class="value">{total_krs}</div></div>
   </div>
 </div>
{readiness_html}
{programme_html}
{focus_strip}
<div class="timeline">
{''.join(items) if items else '<p>No key results recorded yet.</p>'}
</div>
<div class="report-footer">{BRAND_FOOTER} · Reported on {reported_at}</div>
</html>"""
    out_dir = _reports_root_for_user(user_id)
    out_path = os.path.join(out_dir, "progress.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return out_path
