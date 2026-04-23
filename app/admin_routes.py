# app/admin_routes.py
from __future__ import annotations

import html
import os

import json
import time
from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, text as sa_text, case, false

from .db import SessionLocal, engine
from .models import (
    AssessmentRun,
    AssessmentTurn,
    Concept,
    EducationLessonVariant,
    EducationProgramme,
    EducationProgrammeDay,
    EducationQuiz,
    EducationQuizQuestion,
    PillarResult,
    PromptTemplate,
    PromptSettings,
    PromptTemplateVersionLog,
    UserEducationPlan,
)
from .job_queue import enqueue_job_once, ensure_job_table, ensure_prompt_settings_schema
from .prompts import (
    RETIRED_PROMPT_TOUCHPOINTS,
    _ensure_llm_prompt_log_schema,
    _canonical_state,
    _coerce_llm_content,
    log_llm_prompt,
)
from .prompts import build_prompt
from . import prompts as prompts_module
from .models import User
from .education_plan import (
    ensure_education_plan_schema,
    generate_all_education_programme_avatar_videos,
    generate_education_lesson_avatar,
    generate_education_programme_avatar_videos,
    refresh_all_education_programme_avatar_videos,
    refresh_education_lesson_avatar,
    refresh_education_programme_avatar_videos,
)
from .kickoff import _programme_blocks as kickoff_programme_blocks, _okr_by_pillar as kickoff_okr_by_pillar
from .kickoff import _latest_assessment as kickoff_latest_assessment, _latest_psych as kickoff_latest_psych
from .prompts import kr_payload_list, primary_kr_payload

admin = APIRouter(prefix="/admin", tags=["admin"])
_PROMPT_TEMPLATE_DEFAULTS = {
    "block_order": ["system","locale","context","programme","history","okr","scores","habit","task","user"],
    "include_blocks": None,
    "okr_scope": None,
    "is_active": True,
}
BANNED_BLOCKS = {"developer", "policy", "tool"}
LIVE_TEMPLATE_ALLOWED_MODELS = {"gpt-5-mini", "gpt-5.1"}
EDUCATION_DAY_LLM_TOUCHPOINT = "education_programme_day_generator"
EDUCATION_PROGRAMME_LLM_TOUCHPOINT = "education_concept_programme_generator"
LLM_MODEL_CHOICES = [
    "gpt-5.2-pro",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-4o",
    "gpt-4o-mini",
    "o3",
    "o4-mini",
    "gpt-3.5-turbo",
]


def _normalize_model_override(raw: str | None) -> str | None:
    val = (raw or "").strip().lower()
    if not val:
        return None
    aliases = {
        "gpt5-mini": "gpt-5-mini",
        "gpt5.1": "gpt-5.1",
    }
    return aliases.get(val, val)


def _ensure_live_template_model_allowed(model_override: str | None, *, context: str = "live templates") -> None:
    if not model_override:
        return
    if model_override in LIVE_TEMPLATE_ALLOWED_MODELS:
        return
    allowed = ", ".join(sorted(LIVE_TEMPLATE_ALLOWED_MODELS))
    raise HTTPException(400, f"{context} model_override must be one of: {allowed}")


def _enforce_single_active_states(session, state_names: set[str]):
    """
    Ensure only the latest version per touchpoint is active for the given states.
    States may include aliases (beta/stage, live/production).
    """
    if not state_names:
        return
    state_aliases = set()
    for st in state_names:
        stc = _canonical_state(st)
        state_aliases.add(stc)
        if stc == "beta":
            state_aliases.add("stage")
        if stc == "live":
            state_aliases.add("production")

    rows = (
        session.query(PromptTemplate)
        .filter(PromptTemplate.state.in_(list(state_aliases)))
        .order_by(PromptTemplate.touchpoint.asc(), PromptTemplate.version.desc(), PromptTemplate.id.desc())
        .all()
    )
    keep_ids: set[int] = set()
    seen: set[tuple[str, str]] = set()
    for r in rows:
        key = (r.touchpoint, _canonical_state(r.state))
        if key in seen:
            continue
        seen.add(key)
        keep_ids.add(r.id)

    if rows:
        session.query(PromptTemplate).filter(PromptTemplate.state.in_(list(state_aliases))).update(
            {PromptTemplate.is_active: False}, synchronize_session=False
        )
    if keep_ids:
        session.query(PromptTemplate).filter(PromptTemplate.id.in_(list(keep_ids))).update(
            {PromptTemplate.is_active: True}, synchronize_session=False
        )
    # For beta (and its alias), prune non-winners entirely to avoid clutter
    if "beta" in state_aliases or "stage" in state_aliases:
        if keep_ids:
            session.query(PromptTemplate).filter(
                PromptTemplate.state.in_(["beta", "stage"]),
                ~PromptTemplate.id.in_(list(keep_ids)),
            ).delete(synchronize_session=False)

PAGE_STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@500;600&family=Inter:wght@400;500;600&display=swap');
  :root {
    --bg: #f7f9fb;
    --card: #ffffff;
    --border: #d9e0e8;
    --text: #0f172a;
    --muted: #475467;
    --accent: #c54817;
    --accent-strong: #a53b13;
    --accent-soft: #fff0e8;
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 0; background: var(--bg); color: var(--text); font-family: 'Inter', system-ui, -apple-system, sans-serif; }
  h1, h2, h3, h4 { font-family: 'Outfit', 'Inter', system-ui, sans-serif; margin: 0 0 12px; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .page { max-width: 1100px; margin: 32px auto; padding: 0 20px 40px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04); }
  .meta { color: var(--muted); font-size: 0.95rem; }
  .admin-menu { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; padding: 10px 12px; background: var(--accent-soft); border: 1px solid #efb199; border-radius: 12px; }
  .admin-menu a { display: inline-flex; align-items: center; min-height: 36px; padding: 0 12px; background: #fff; border: 1px solid #d9e0e8; border-radius: 999px; color: var(--text); text-decoration: none; font-weight: 600; }
  .admin-menu a:hover { background: #f8fbff; text-decoration: none; }
  table { border-collapse: collapse; width: 100%; }
  th, td { border: 1px solid var(--border); padding: 10px; text-align: left; vertical-align: top; }
  th { background: #f3f5f8; font-weight: 600; }
  tr:nth-child(even) td { background: #f9fbfd; }
  input[type="text"], input[type="number"], textarea { width: 100%; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-family: 'Inter', system-ui, sans-serif; font-size: 14px; }
  textarea { resize: vertical; }
  .field { margin-bottom: 12px; }
  .actions { margin-top: 14px; }
  button { background: var(--accent); color: #fff; border: none; border-radius: 8px; padding: 10px 14px; font-weight: 600; cursor: pointer; }
  button:hover { background: var(--accent-strong); }
  .nav { margin-bottom: 12px; }
  .help { color: var(--muted); font-size: 0.9rem; margin: 4px 0 10px; }
  select { width: 100%; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-family: 'Inter', system-ui, sans-serif; font-size: 14px; background: #fff; }
  .grid-2 { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .grid-3 { display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .stack { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .section-title { margin: 0 0 6px; font-size: 1.05rem; }
  .subtle { color: var(--muted); font-size: 0.86rem; }
  .programme-day { border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: #fcfdff; margin-bottom: 12px; }
  .programme-days-shell { display: grid; gap: 14px; align-items: start; }
  .programme-day-list { display: grid; gap: 8px; }
  .programme-day-summary {
    width: 100%;
    display: grid;
    grid-template-columns: minmax(5rem, auto) minmax(0, 1fr) auto;
    gap: 10px;
    align-items: center;
    text-align: left;
    background: #fff;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    box-shadow: none;
  }
  .programme-day-summary:hover { background: #fff8f3; }
  .programme-day-summary.is-selected { border-color: var(--accent); box-shadow: 0 0 0 2px rgba(197, 72, 23, 0.14); }
  .programme-day-summary-index { color: var(--accent); font-weight: 800; }
  .programme-day-summary-title { display: block; font-weight: 700; margin-bottom: 4px; }
  .programme-day-summary-meta { display: block; color: var(--muted); font-size: 0.82rem; line-height: 1.35; }
  .programme-day-summary-status { display: inline-flex; align-items: center; min-height: 22px; border-radius: 999px; padding: 2px 8px; background: #ecfdf3; color: #027a48; font-size: 0.78rem; font-weight: 700; white-space: nowrap; }
  .programme-day-summary-status.needs-video { background: #fff7ed; color: #9a3412; }
  .programme-day-summary-status.pending { background: #fef9c3; color: #854d0e; }
  .programme-day-summary-status.failed { background: #fff0e8; color: var(--accent-strong); }
  .programme-day-summary-empty { border: 1px dashed var(--border); border-radius: 8px; padding: 12px; color: var(--muted); background: #fff; }
  .programme-day-detail-card { min-width: 0; scroll-margin-top: 16px; }
  .programme-day-llm { border: 1px solid #efb199; border-radius: 8px; padding: 12px; background: #fff8f3; margin-top: 12px; }
  .programme-day-llm summary { cursor: pointer; font-weight: 700; color: var(--accent-strong); }
  .programme-day-llm[open] summary { margin-bottom: 10px; }
  .programme-day-llm-status { min-height: 20px; }
  .programme-day-editor { min-width: 0; margin-top: 12px; }
  .lesson-variant { border: 1px solid #d7dfe8; border-radius: 10px; padding: 12px; background: #fff; margin-top: 10px; }
  .quiz-question { border: 1px dashed #c6d1dc; border-radius: 10px; padding: 12px; background: #fbfcfe; margin-top: 10px; }
  .danger { background: var(--accent); }
  .danger:hover { background: var(--accent-strong); }
  .secondary { background: var(--accent-soft); color: var(--accent-strong); border: 1px solid #efb199; }
  .secondary:hover { background: #ffd8c9; }
  @media (max-width: 860px) {
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
    .programme-day-summary { grid-template-columns: 1fr; }
  }
</style>
<style>
  .button-link {
    display: inline-block;
    background: var(--accent-soft);
    color: var(--accent-strong);
    border: 1px solid #efb199;
    border-radius: 8px;
    padding: 8px 12px;
    text-decoration: none;
    font-weight: 600;
  }
  .button-link:hover {
    background: #ffd8c9;
  }
</style>
"""


def _admin_menu_html() -> str:
    return (
        "<nav class='admin-menu'>"
        "<a href='/admin/runs'>Assessment Runs</a>"
        "<a href='/admin/prompt-templates'>Prompt Templates</a>"
        "<a href='/admin/education-programmes'>Education</a>"
        "</nav>"
    )


def _wrap_page(title: str, body_html: str) -> HTMLResponse:
    html_out = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  {PAGE_STYLE}
</head>
<body>
  <div class="page">
    {_admin_menu_html()}
    {body_html}
  </div>
</body>
</html>
"""
    return HTMLResponse(html_out)

def _build_version_label() -> str:
    commit = (
        os.getenv("APP_VERSION")
        or os.getenv("RENDER_GIT_COMMIT")
        or os.getenv("GIT_COMMIT")
        or os.getenv("COMMIT_SHA")
    )
    if not commit:
        return ""
    commit = str(commit).strip()
    short = commit[:8] if len(commit) > 8 else commit
    return f"<div class='meta'>Build: {html.escape(short)}</div>"

_PROMPT_SCHEMA_READY = False

def _ensure_prompt_template_table():
    global _PROMPT_SCHEMA_READY
    if _PROMPT_SCHEMA_READY:
        return
    try:
        PromptTemplate.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass
    try:
        with engine.connect() as conn:
            conn.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS programme_scope varchar(32);"))
            conn.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS response_format varchar(32);"))
            conn.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS model_override varchar(120);"))
            conn.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS state varchar(32) DEFAULT 'develop';"))
            conn.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS version integer DEFAULT 1;"))
            conn.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS note text;"))
            conn.execute(sa_text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS parent_id integer;"))
            try:
                conn.execute(sa_text("ALTER TABLE prompt_templates DROP CONSTRAINT IF EXISTS prompt_templates_touchpoint_key;"))
            except Exception:
                pass
            try:
                conn.execute(sa_text("DROP INDEX IF EXISTS prompt_templates_touchpoint_key;"))
            except Exception:
                pass
            try:
                conn.execute(sa_text("DROP INDEX IF EXISTS uq_prompt_templates_touchpoint;"))
            except Exception:
                pass
            conn.execute(sa_text("CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_templates_touchpoint_state_version ON prompt_templates(touchpoint,state,version);"))
            conn.execute(sa_text("UPDATE prompt_templates SET state='beta' WHERE state='stage';"))
            conn.execute(sa_text("UPDATE prompt_templates SET state='live' WHERE state='production';"))
            conn.execute(sa_text("UPDATE prompt_templates SET version=1 WHERE version IS NULL;"))
            conn.commit()
    except Exception:
        pass
    try:
        PromptSettings.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass
    try:
        ensure_prompt_settings_schema()
    except Exception:
        pass
    try:
        PromptTemplateVersionLog.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass
    try:
        with SessionLocal() as s:
            s.query(PromptTemplate).filter(
                PromptTemplate.touchpoint.in_(sorted(RETIRED_PROMPT_TOUCHPOINTS))
            ).delete(synchronize_session=False)
            s.commit()
    except Exception:
        pass
    _PROMPT_SCHEMA_READY = True

@admin.get("/runs", response_class=HTMLResponse)
def list_runs(limit: int = 50):
    with SessionLocal() as s:
        runs = s.query(AssessmentRun).order_by(AssessmentRun.id.desc()).limit(limit).all()
        rows = []
        for r in runs:
            rows.append(
                f"<tr>"
                f"<td><a href='/admin/runs/{r.id}'>#{r.id}</a></td>"
                f"<td>{r.user_id}</td>"
                f"<td>{r.started_at}</td>"
                f"<td>{'✓' if r.is_completed else '…'}</td>"
                f"<td>{','.join(r.pillars or [])}</td>"
                f"<td>{r.model_name}</td>"
                f"<td>{r.kb_version}</td>"
                f"</tr>"
            )
        html = (
            "<h2>Assessment Runs</h2>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>ID</th><th>User</th><th>Started</th><th>Done</th><th>Pillars</th><th>Model</th><th>KB</th></tr>"
            + "".join(rows) + "</table>"
        )
        return HTMLResponse(html)


@admin.get("/llm_review/{user_id}", response_class=HTMLResponse)
def llm_review(user_id: int, limit: int = 100):
    """
    Simple HTML viewer for LLM prompt logs for a given user.
    """
    _ensure_llm_prompt_log_schema()

    with SessionLocal() as s:
        rows = s.execute(
            sa_text(
                """
                SELECT id, created_at, touchpoint, model, duration_ms, prompt_variant, task_label,
                       block_order, system_block, locale_block, okr_block, okr_scope, scores_block, habit_block,
                       task_block, template_state, template_version, user_block, extra_blocks, payload_truncated, sent_payload, assembled_prompt,
                       response_preview, context_meta
                FROM llm_prompt_logs_view
                WHERE user_id = :u
                ORDER BY created_at DESC
                LIMIT :lim
                """
            ),
            {"u": user_id, "lim": limit},
        ).fetchall()

    def _esc(val):
        return html.escape("" if val is None else str(val))

    def _pre(val):
        if val is None:
            return ""
        return f"<pre style='white-space:pre-wrap'>{_esc(val)}</pre>"

    def _source_from_context_meta(val):
        meta = val
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                return ""
        if isinstance(meta, dict):
            src = str(meta.get("execution_source") or "").strip().lower()
            if src in {"worker", "api"}:
                return src
        return ""

    row_html = []
    for r in rows:
        source = _source_from_context_meta(getattr(r, "context_meta", None))
        row_html.append(
            "<tr>"
            f"<td>{r.id}</td>"
            f"<td>{r.created_at}</td>"
            f"<td>{_esc(r.touchpoint)}</td>"
            f"<td>{_esc(source)}</td>"
            f"<td>{_esc(r.model)}</td>"
            f"<td>{_esc(getattr(r,'duration_ms','') or '')}</td>"
            f"<td>{_esc(r.prompt_variant)}</td>"
            f"<td>{_esc(r.task_label)}</td>"
            f"<td>{_esc(r.block_order)}</td>"
            f"<td>{_pre(r.system_block)}</td>"
            f"<td>{_pre(r.locale_block)}</td>"
            f"<td>{_pre(r.okr_block)}</td>"
            f"<td>{_esc(getattr(r, 'okr_scope', ''))}</td>"
            f"<td>{_pre(r.scores_block)}</td>"
            f"<td>{_pre(r.habit_block)}</td>"
            f"<td>{_pre(r.task_block)}</td>"
            f"<td>{_esc(getattr(r,'template_state','') or '')}</td>"
            f"<td>{_esc(getattr(r,'template_version','') or '')}</td>"
            f"<td>{_esc(getattr(r,'duration_ms','') or '')}</td>"
            f"<td>{_pre(r.user_block)}</td>"
            f"<td>{_pre(r.extra_blocks)}</td>"
            f"<td>{_esc(getattr(r,'payload_truncated','') or '')}</td>"
            f"<td>{_pre(r.sent_payload)}</td>"
            f"<td>{_pre(r.assembled_prompt)}</td>"
            f"<td>{_pre(r.response_preview)}</td>"
            f"<td>{_pre(r.context_meta)}</td>"
            "</tr>"
        )

    html_out = (
        f"<h2>LLM Prompt Logs — user {user_id}</h2>"
        f"<p class='meta'>Showing newest {len(rows)} rows (limit={limit}).</p>"
        "<div class='card'>"
        "<table>"
        "<tr>"
        "<th>ID</th><th>Timestamp</th><th>Touchpoint</th><th>Source</th><th>Model</th><th>Duration (ms)</th>"
        "<th>Variant</th><th>Task</th><th>Block Order</th>"
        "<th>System</th><th>Locale</th><th>OKR</th><th>OKR Scope</th><th>Scores</th><th>Habit</th><th>Task Block</th><th>State</th><th>Version</th><th>Duration (ms)</th><th>User</th>"
        "<th>Extras</th><th>Payload Trimmed</th><th>Sent Payload</th><th>Assembled Prompt</th><th>Response Preview</th><th>Context Meta</th>"
        "</tr>"
        + "".join(row_html)
        + "</table>"
        "</div>"
    )
    return _wrap_page(f"LLM Prompt Logs — user {user_id}", html_out)


def _parse_list_field(val: str | None) -> list[str] | None:
    if not val:
        return None
    txt = val.strip()
    if not txt:
        return None
    try:
        parsed = json.loads(txt)
        if isinstance(parsed, list):
            return [str(x).strip() for x in parsed if str(x).strip()]
    except Exception:
        pass
    # Tolerate legacy/py-list strings like "['system', 'locale']".
    cleaned = txt.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
    return [p.strip() for p in cleaned.split(",") if p.strip()]


def _clone_template(row: PromptTemplate, target_state: str, version: int) -> PromptTemplate:
    """Clone a template into a new state/version."""
    return PromptTemplate(
        touchpoint=row.touchpoint,
        state=target_state,
        version=version,
        parent_id=row.id,
        task_block=row.task_block,
        block_order=row.block_order,
        include_blocks=row.include_blocks,
        okr_scope=row.okr_scope,
        programme_scope=row.programme_scope,
        response_format=row.response_format,
        model_override=getattr(row, "model_override", None),
        is_active=row.is_active,
        note=row.note,
    )


def _education_programme_payload(session, row: EducationProgramme | None) -> dict[str, object]:
    if row is None:
        return {
            "id": None,
            "pillar_key": "",
            "programme_concept_key": "",
            "programme_concept_label": "",
            "code": "",
            "name": "",
            "duration_days": 0,
            "is_active": True,
            "days": [],
        }
    day_rows = (
        session.query(EducationProgrammeDay)
        .filter(EducationProgrammeDay.programme_id == int(row.id))
        .order_by(EducationProgrammeDay.day_index.asc(), EducationProgrammeDay.id.asc())
        .all()
    )
    day_ids = [int(item.id) for item in day_rows]
    variant_rows = []
    if day_ids:
        variant_rows = (
            session.query(EducationLessonVariant)
            .filter(EducationLessonVariant.programme_day_id.in_(day_ids))
            .order_by(EducationLessonVariant.programme_day_id.asc(), EducationLessonVariant.level.asc(), EducationLessonVariant.id.asc())
            .all()
        )
    variant_ids = [int(item.id) for item in variant_rows]
    quiz_rows = []
    if variant_ids:
        quiz_rows = (
            session.query(EducationQuiz)
            .filter(EducationQuiz.lesson_variant_id.in_(variant_ids))
            .order_by(EducationQuiz.lesson_variant_id.asc(), EducationQuiz.id.asc())
            .all()
        )
    quiz_ids = [int(item.id) for item in quiz_rows]
    question_rows = []
    if quiz_ids:
        question_rows = (
            session.query(EducationQuizQuestion)
            .filter(EducationQuizQuestion.quiz_id.in_(quiz_ids))
            .order_by(EducationQuizQuestion.quiz_id.asc(), EducationQuizQuestion.question_order.asc(), EducationQuizQuestion.id.asc())
            .all()
        )
    quiz_by_variant = {int(item.lesson_variant_id): item for item in quiz_rows}
    questions_by_quiz: dict[int, list[EducationQuizQuestion]] = {}
    for item in question_rows:
        questions_by_quiz.setdefault(int(item.quiz_id), []).append(item)
    variants_by_day: dict[int, list[EducationLessonVariant]] = {}
    for item in variant_rows:
        variants_by_day.setdefault(int(item.programme_day_id), []).append(item)
    payload_days: list[dict[str, object]] = []
    for day in day_rows:
        payload_variants: list[dict[str, object]] = []
        for variant in variants_by_day.get(int(day.id), []):
            quiz = quiz_by_variant.get(int(variant.id))
            questions = []
            if quiz is not None:
                for question in questions_by_quiz.get(int(quiz.id), []):
                    questions.append(
                        {
                            "id": int(question.id),
                            "question_order": int(question.question_order or 0),
                            "question_text": str(question.question_text or ""),
                            "answer_type": str(question.answer_type or ""),
                            "options_json": question.options_json,
                            "correct_answer_json": question.correct_answer_json,
                            "explanation": str(question.explanation or ""),
                        }
                    )
            payload_variants.append(
                {
                    "id": int(variant.id),
                    "level": str(variant.level or ""),
                    "title": str(getattr(variant, "title", "") or ""),
                    "summary": str(getattr(variant, "summary", "") or ""),
                    "script": str(getattr(variant, "script", "") or ""),
                    "action_prompt": str(getattr(variant, "action_prompt", "") or ""),
                    "video_url": str(getattr(variant, "video_url", "") or ""),
                    "poster_url": str(getattr(variant, "poster_url", "") or ""),
                    "avatar_character": str(getattr(variant, "avatar_character", "") or ""),
                    "avatar_style": str(getattr(variant, "avatar_style", "") or ""),
                    "avatar_voice": str(getattr(variant, "avatar_voice", "") or ""),
                    "avatar_status": str(getattr(variant, "avatar_status", "") or ""),
                    "avatar_job_id": str(getattr(variant, "avatar_job_id", "") or ""),
                    "avatar_error": str(getattr(variant, "avatar_error", "") or ""),
                    "avatar_generated_at": getattr(variant, "avatar_generated_at", None).isoformat() if getattr(variant, "avatar_generated_at", None) else "",
                    "avatar_source": str(getattr(variant, "avatar_source", "") or ""),
                    "avatar_summary_url": str(getattr(variant, "avatar_summary_url", "") or ""),
                    "content_item_id": int(variant.content_item_id) if variant.content_item_id else None,
                    "takeaway_default": str(variant.takeaway_default or ""),
                    "takeaway_if_low_score": str(variant.takeaway_if_low_score or ""),
                    "takeaway_if_high_score": str(variant.takeaway_if_high_score or ""),
                    "is_active": bool(variant.is_active),
                    "quiz": {
                        "id": int(quiz.id) if quiz is not None else None,
                        "pass_score_pct": float(quiz.pass_score_pct) if quiz is not None and quiz.pass_score_pct is not None else None,
                        "questions": questions,
                    },
                }
            )
        payload_days.append(
            {
                "id": int(day.id),
                "day_index": int(day.day_index or 0),
                "concept_key": str(day.concept_key or ""),
                "concept_label": str(day.concept_label or ""),
                "lesson_goal": str(day.lesson_goal or ""),
                "default_title": str(day.default_title or ""),
                "default_summary": str(day.default_summary or ""),
                "variants": payload_variants,
            }
        )
    derived_duration = max((int(item.get("day_index") or 0) for item in payload_days), default=0)
    return {
        "id": int(row.id),
        "pillar_key": str(row.pillar_key or ""),
        "programme_concept_key": str(getattr(row, "concept_key", "") or ""),
        "programme_concept_label": str(getattr(row, "concept_label", "") or ""),
        "code": str(row.code or ""),
        "name": str(row.name or ""),
        "duration_days": derived_duration or int(row.duration_days or 0) or 0,
        "is_active": bool(row.is_active),
        "days": payload_days,
    }


def _education_editor_options(session) -> list[dict[str, object]]:
    concept_rows = (
        session.query(Concept)
        .order_by(Concept.pillar_key.asc(), Concept.code.asc())
        .all()
    )
    concepts = [
        {
            "pillar_key": str(row.pillar_key or "").strip().lower(),
            "code": str(row.code or "").strip().lower(),
            "name": str(row.name or "").strip() or str(row.code or "").strip().replace("_", " ").title(),
        }
        for row in concept_rows
    ]
    return concepts


def _json_script_content(value: object) -> str:
    return (
        json.dumps(value, ensure_ascii=False)
        .replace("</", "<\\/")
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )


def _llm_model_options_html(default_model_name: str | None = None) -> str:
    default_label = "Default"
    if default_model_name:
        default_label = f"Default (current: {default_model_name})"
    options = [("", default_label)] + [(model, model) for model in LLM_MODEL_CHOICES]
    return "".join(
        f"<option value='{html.escape(value)}'>{html.escape(label)}</option>"
        for value, label in options
    )


def _trim_llm_context_text(value: object, limit: int = 3000) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _compact_education_day_for_llm(raw_day: object) -> dict[str, object]:
    if not isinstance(raw_day, dict):
        return {}
    variants = []
    for raw_variant in (raw_day.get("variants") if isinstance(raw_day.get("variants"), list) else [])[:4]:
        if not isinstance(raw_variant, dict):
            continue
        quiz = raw_variant.get("quiz") if isinstance(raw_variant.get("quiz"), dict) else {}
        questions = []
        for raw_question in (quiz.get("questions") if isinstance(quiz.get("questions"), list) else [])[:3]:
            if not isinstance(raw_question, dict):
                continue
            questions.append(
                {
                    "question_order": raw_question.get("question_order"),
                    "question_text": _trim_llm_context_text(raw_question.get("question_text"), 500),
                    "answer_type": raw_question.get("answer_type"),
                    "options_json": raw_question.get("options_json"),
                    "correct_answer_json": raw_question.get("correct_answer_json"),
                    "explanation": _trim_llm_context_text(raw_question.get("explanation"), 500),
                }
            )
        variants.append(
            {
                "level": raw_variant.get("level"),
                "title": _trim_llm_context_text(raw_variant.get("title"), 300),
                "summary": _trim_llm_context_text(raw_variant.get("summary"), 800),
                "script": _trim_llm_context_text(raw_variant.get("script"), 3500),
                "action_prompt": _trim_llm_context_text(raw_variant.get("action_prompt"), 800),
                "takeaway_default": _trim_llm_context_text(raw_variant.get("takeaway_default"), 800),
                "takeaway_if_low_score": _trim_llm_context_text(raw_variant.get("takeaway_if_low_score"), 800),
                "takeaway_if_high_score": _trim_llm_context_text(raw_variant.get("takeaway_if_high_score"), 800),
                "quiz": {
                    "pass_score_pct": quiz.get("pass_score_pct"),
                    "questions": questions,
                },
            }
        )
    return {
        "day_index": raw_day.get("day_index"),
        "concept_key": raw_day.get("concept_key"),
        "concept_label": raw_day.get("concept_label"),
        "lesson_goal": _trim_llm_context_text(raw_day.get("lesson_goal"), 800),
        "default_title": _trim_llm_context_text(raw_day.get("default_title"), 300),
        "default_summary": _trim_llm_context_text(raw_day.get("default_summary"), 800),
        "variants": variants,
    }


def _compact_education_programme_for_llm(raw_programme: object) -> dict[str, object]:
    if not isinstance(raw_programme, dict):
        return {"days": []}
    raw_days = raw_programme.get("days") if isinstance(raw_programme.get("days"), list) else []
    return {
        "programme_name": _trim_llm_context_text(raw_programme.get("programme_name") or raw_programme.get("name"), 300),
        "programme_code": _trim_llm_context_text(raw_programme.get("programme_code") or raw_programme.get("code"), 160),
        "pillar_key": str(raw_programme.get("pillar_key") or "").strip().lower(),
        "programme_concept_key": str(raw_programme.get("programme_concept_key") or "").strip().lower(),
        "programme_concept_label": _trim_llm_context_text(
            raw_programme.get("programme_concept_label") or raw_programme.get("concept_label"),
            300,
        ),
        "duration_days": raw_programme.get("duration_days"),
        "days": [_compact_education_day_for_llm(day) for day in raw_days[:31] if isinstance(day, dict)],
    }


def _extract_llm_json_object(raw_text: str) -> dict[str, object]:
    cleaned = str(raw_text or "").strip()
    if not cleaned:
        raise ValueError("LLM returned an empty response")
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()
    candidates = [cleaned]
    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first >= 0 and last > first:
        candidates.append(cleaned[first : last + 1])
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
                return parsed[0]
        except Exception as exc:
            last_error = exc
    raise ValueError(f"LLM response was not valid JSON: {last_error or 'unknown parse error'}")


def _normalise_generated_question(raw_question: object, order: int) -> dict[str, object] | None:
    if not isinstance(raw_question, dict):
        return None
    question_text = str(
        raw_question.get("question_text")
        or raw_question.get("question")
        or raw_question.get("text")
        or ""
    ).strip()
    if not question_text:
        return None
    answer_type = str(raw_question.get("answer_type") or "single_choice").strip().lower()
    if answer_type not in {"single_choice", "multi_choice", "boolean"}:
        answer_type = "single_choice"
    options_val = raw_question.get("options_json", raw_question.get("options"))
    if isinstance(options_val, str):
        raw_options_text = options_val.strip()
        if raw_options_text:
            try:
                options_val = json.loads(raw_options_text)
            except Exception:
                options_val = [line.strip() for line in raw_options_text.splitlines() if line.strip()]
                if len(options_val) <= 1 and "," in raw_options_text:
                    options_val = [part.strip() for part in raw_options_text.split(",") if part.strip()]
        else:
            options_val = []
    if not isinstance(options_val, list):
        options_val = ["True", "False"] if answer_type == "boolean" else []
    correct_val = raw_question.get(
        "correct_answer_json",
        raw_question.get("correct_answer", raw_question.get("answer")),
    )
    try:
        question_order = int(raw_question.get("question_order") or order)
    except Exception:
        question_order = order
    return {
        "id": None,
        "question_order": question_order,
        "question_text": question_text,
        "answer_type": answer_type,
        "options_json": options_val,
        "correct_answer_json": correct_val if correct_val is not None else "",
        "explanation": str(raw_question.get("explanation") or "").strip(),
    }


def _normalise_generated_education_day(
    raw_generated: dict[str, object],
    *,
    day_index: int,
    concept_key: str,
    concept_label: str,
    existing_level: str,
) -> dict[str, object]:
    generated = raw_generated.get("day") if isinstance(raw_generated.get("day"), dict) else raw_generated
    raw_variants = generated.get("variants") if isinstance(generated.get("variants"), list) else []
    if not raw_variants and any(generated.get(key) for key in ("title", "summary", "script", "action_prompt", "quiz")):
        raw_variants = [generated]
    if not raw_variants:
        raise ValueError("LLM response did not include any lesson variants")

    variants = []
    for raw_variant in raw_variants[:4]:
        if not isinstance(raw_variant, dict):
            continue
        quiz = raw_variant.get("quiz") if isinstance(raw_variant.get("quiz"), dict) else {}
        raw_questions = quiz.get("questions") if isinstance(quiz.get("questions"), list) else []
        questions = [
            question
            for question in (
                _normalise_generated_question(raw_question, idx + 1)
                for idx, raw_question in enumerate(raw_questions[:3])
            )
            if question is not None
        ]
        if not questions:
            raise ValueError("LLM response did not include quiz questions")
        try:
            pass_score_pct = float(quiz.get("pass_score_pct") if quiz.get("pass_score_pct") not in (None, "") else 66.67)
        except Exception:
            pass_score_pct = 66.67
        level = str(raw_variant.get("level") or existing_level or "build").strip().lower() or "build"
        if level not in {"support", "foundation", "build", "perform"}:
            level = existing_level if existing_level in {"support", "foundation", "build", "perform"} else "build"
        is_active_raw = raw_variant.get("is_active", True)
        is_active = str(is_active_raw).strip().lower() not in {"0", "false", "no", "off"}
        variants.append(
            {
                "id": None,
                "level": level,
                "title": str(raw_variant.get("title") or raw_variant.get("default_title") or "").strip(),
                "summary": str(raw_variant.get("summary") or raw_variant.get("default_summary") or "").strip(),
                "script": str(raw_variant.get("script") or raw_variant.get("body") or "").strip(),
                "action_prompt": str(raw_variant.get("action_prompt") or raw_variant.get("daily_action") or "").strip(),
                "video_url": "",
                "poster_url": "",
                "avatar_character": str(raw_variant.get("avatar_character") or "").strip(),
                "avatar_style": str(raw_variant.get("avatar_style") or "").strip(),
                "avatar_voice": str(raw_variant.get("avatar_voice") or "").strip(),
                "avatar_status": "",
                "avatar_job_id": "",
                "avatar_error": "",
                "avatar_generated_at": "",
                "avatar_source": "",
                "avatar_summary_url": "",
                "content_item_id": None,
                "reset_avatar_media": True,
                "takeaway_default": str(raw_variant.get("takeaway_default") or "").strip(),
                "takeaway_if_low_score": str(raw_variant.get("takeaway_if_low_score") or "").strip(),
                "takeaway_if_high_score": str(raw_variant.get("takeaway_if_high_score") or "").strip(),
                "is_active": is_active,
                "quiz": {
                    "id": None,
                    "pass_score_pct": pass_score_pct,
                    "questions": questions,
                },
            }
        )
    if not variants:
        raise ValueError("LLM response did not include usable lesson variants")
    default_title = str(generated.get("default_title") or "").strip() or str(variants[0].get("title") or "").strip()
    default_summary = str(generated.get("default_summary") or "").strip() or str(variants[0].get("summary") or "").strip()
    try:
        generated_day_index = int(generated.get("day_index") or day_index or 1)
    except Exception:
        generated_day_index = int(day_index or 1)
    return {
        "id": None,
        "day_index": generated_day_index,
        "concept_key": concept_key,
        "concept_label": concept_label,
        "lesson_goal": str(generated.get("lesson_goal") or "").strip(),
        "default_title": default_title,
        "default_summary": default_summary,
        "variants": variants,
    }


def _normalise_generated_education_programme(
    raw_generated: dict[str, object],
    *,
    concept_key: str,
    concept_label: str,
    requested_days: int,
) -> dict[str, object]:
    generated = raw_generated.get("programme") if isinstance(raw_generated.get("programme"), dict) else raw_generated
    raw_days = generated.get("days") if isinstance(generated.get("days"), list) else []
    if not raw_days:
        raise ValueError("LLM response did not include any programme days")
    normalised_days: list[dict[str, object]] = []
    seen_indexes: set[int] = set()
    for idx, raw_day in enumerate(raw_days[:31], start=1):
        if not isinstance(raw_day, dict):
            continue
        raw_variants = raw_day.get("variants") if isinstance(raw_day.get("variants"), list) else []
        existing_level = "build"
        if raw_variants and isinstance(raw_variants[0], dict):
            existing_level = str(raw_variants[0].get("level") or "build").strip().lower() or "build"
        if existing_level not in {"support", "foundation", "build", "perform"}:
            existing_level = "build"
        day = _normalise_generated_education_day(
            raw_day,
            day_index=idx,
            concept_key=concept_key,
            concept_label=concept_label,
            existing_level=existing_level,
        )
        day_index = int(day.get("day_index") or idx)
        if day_index in seen_indexes:
            day_index = max(seen_indexes, default=0) + 1
            day["day_index"] = day_index
        seen_indexes.add(day_index)
        normalised_days.append(day)
    if not normalised_days:
        raise ValueError("LLM response did not include usable programme days")
    if requested_days > 0 and len(normalised_days) != requested_days:
        raise ValueError(f"LLM returned {len(normalised_days)} days; expected {requested_days}")
    try:
        duration_days = int(generated.get("duration_days") or len(normalised_days))
    except Exception:
        duration_days = len(normalised_days)
    return {
        "programme_name": str(generated.get("programme_name") or generated.get("name") or "").strip(),
        "programme_code": str(generated.get("programme_code") or generated.get("code") or "").strip(),
        "duration_days": duration_days,
        "days": sorted(normalised_days, key=lambda item: int(item.get("day_index") or 0)),
    }


def _truthy_form_value(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_positive_int(value: object) -> int | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(float(raw))
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _education_avatar_bulk_result_page(title: str, result: dict) -> HTMLResponse:
    programme_id = int(result.get("programme_id") or 0)
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    items = result.get("items") if isinstance(result.get("items"), list) else []
    count_summary = " · ".join(
        f"{html.escape(str(key).replace('_', ' ').title())}: {html.escape(str(value))}"
        for key, value in counts.items()
    )
    note = (
        "Generation starts Azure batch jobs. Use Refresh pending videos after a few minutes to pull completed files into Daily Focus."
        if "generation" in title.lower()
        else "Refresh checks Azure jobs and stores completed videos for Daily Focus."
    )
    rows = []
    for item in items:
        if not isinstance(item, dict):
            continue
        video_url = str(item.get("video_url") or "").strip()
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('day_index') or ''))}</td>"
            f"<td>{html.escape(str(item.get('level') or ''))}</td>"
            f"<td>{html.escape(str(item.get('title') or ''))}</td>"
            f"<td>{html.escape(str(item.get('status') or ''))}</td>"
            f"<td>{html.escape(str(item.get('avatar_status') or item.get('reason') or ''))}</td>"
            f"<td>{html.escape(str(item.get('job_id') or ''))}</td>"
            "<td>"
            + (
                f"<a href='{html.escape(video_url)}' target='_blank' rel='noopener'>Open video</a>"
                if video_url
                else ""
            )
            + "</td>"
            "</tr>"
        )
    body = (
        f"<h2>{html.escape(title)}</h2>"
        f"{_build_version_label()}"
        "<div class='card' style='margin-bottom:12px;'>"
        f"<p><strong>{html.escape(str(result.get('programme_name') or 'Education programme'))}</strong></p>"
        f"<p class='help'>{count_summary or 'No avatar changes were made.'}</p>"
        f"<p class='help'>{html.escape(note)}</p>"
        "<div class='stack'>"
        f"<a class='button-link' href='/admin/education-programmes/edit?id={programme_id}'>Back to programme</a>"
        "<a class='button-link' href='/admin/education-programmes'>Back to list</a>"
        "</div>"
        "</div>"
        "<div class='card'>"
        "<table>"
        "<tr><th>Day</th><th>Level</th><th>Lesson</th><th>Status</th><th>Detail</th><th>Job ID</th><th>Video</th></tr>"
        + ("".join(rows) if rows else "<tr><td colspan='7'><em>No active lesson variants found.</em></td></tr>")
        + "</table>"
        "</div>"
    )
    return _wrap_page(title, body)


def _education_avatar_all_result_page(title: str, result: dict) -> HTMLResponse:
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    programmes = result.get("programmes") if isinstance(result.get("programmes"), list) else []
    count_summary = " · ".join(
        f"{html.escape(str(key).replace('_', ' ').title())}: {html.escape(str(value))}"
        for key, value in counts.items()
    )
    is_generation = "generation" in title.lower()
    note = (
        "Sequential generation starts one Azure job, waits for it to complete, caches the video, then moves to the next missing lesson."
        if is_generation
        else "Refresh checks pending Azure jobs across active programmes and stores completed videos for Daily Focus."
    )
    programme_rows = []
    detail_rows = []
    for programme in programmes:
        if not isinstance(programme, dict):
            continue
        programme_id = int(programme.get("programme_id") or 0)
        raw_programme_name = str(programme.get("programme_name") or "").strip()
        programme_name = raw_programme_name or (f"Programme {programme_id}" if programme_id else "Programme")
        programme_counts = programme.get("counts") if isinstance(programme.get("counts"), dict) else {}
        programme_summary = " · ".join(
            f"{html.escape(str(key).replace('_', ' ').title())}: {html.escape(str(value))}"
            for key, value in programme_counts.items()
        )
        programme_rows.append(
            "<tr>"
            f"<td>{html.escape(str(programme_id or ''))}</td>"
            f"<td>{html.escape(programme_name)}</td>"
            f"<td>{'✓' if bool(programme.get('ok')) else '✕'}</td>"
            f"<td>{programme_summary or html.escape(str(programme.get('error') or ''))}</td>"
            "<td>"
            + (
                f"<a href='/admin/education-programmes/edit?id={programme_id}'>Open programme</a>"
                if programme_id
                else ""
            )
            + "</td>"
            "</tr>"
        )
        for item in programme.get("items") or []:
            if not isinstance(item, dict):
                continue
            video_url = str(item.get("video_url") or "").strip()
            detail_rows.append(
                "<tr>"
                f"<td>{html.escape(str(programme_id or ''))}</td>"
                f"<td>{html.escape(programme_name)}</td>"
                f"<td>{html.escape(str(item.get('day_index') or ''))}</td>"
                f"<td>{html.escape(str(item.get('level') or ''))}</td>"
                f"<td>{html.escape(str(item.get('title') or ''))}</td>"
                f"<td>{html.escape(str(item.get('status') or ''))}</td>"
                f"<td>{html.escape(str(item.get('avatar_status') or item.get('reason') or ''))}</td>"
                f"<td>{html.escape(str(item.get('job_id') or ''))}</td>"
                "<td>"
                + (
                    f"<a href='{html.escape(video_url)}' target='_blank' rel='noopener'>Open video</a>"
                    if video_url
                    else ""
                )
                + "</td>"
                "</tr>"
            )
    body = (
        f"<h2>{html.escape(title)}</h2>"
        f"{_build_version_label()}"
        "<div class='card' style='margin-bottom:12px;'>"
        f"<p><strong>{html.escape(str(result.get('programme_count') or 0))} programme(s)</strong></p>"
        f"<p class='help'>{count_summary or 'No avatar changes were made.'}</p>"
        f"<p class='help'>{html.escape(note)}</p>"
        "<div class='stack'>"
        "<a class='button-link' href='/admin/education-programmes'>Back to education programmes</a>"
        "</div>"
        "</div>"
        "<div class='card' style='margin-bottom:12px;'>"
        "<h3 class='section-title'>Programmes</h3>"
        "<table>"
        "<tr><th>ID</th><th>Programme</th><th>OK</th><th>Counts</th><th>Action</th></tr>"
        + ("".join(programme_rows) if programme_rows else "<tr><td colspan='5'><em>No programmes found.</em></td></tr>")
        + "</table>"
        "</div>"
        "<div class='card'>"
        "<h3 class='section-title'>Lesson variants</h3>"
        "<table>"
        "<tr><th>Programme ID</th><th>Programme</th><th>Day</th><th>Level</th><th>Lesson</th><th>Status</th><th>Detail</th><th>Job ID</th><th>Video</th></tr>"
        + ("".join(detail_rows) if detail_rows else "<tr><td colspan='9'><em>No active lesson variants found.</em></td></tr>")
        + "</table>"
        "</div>"
    )
    return _wrap_page(title, body)


def _education_avatar_batch_queued_page(job_id: int, *, created: bool, active_only: bool, regenerate: bool) -> HTMLResponse:
    status = "queued" if created else "already queued or running"
    scope = "active programmes" if active_only else "all programmes"
    body = (
        "<h2>Education Avatar Batch Queued</h2>"
        f"{_build_version_label()}"
        "<div class='card'>"
        f"<p><strong>Job {html.escape(str(job_id))}</strong> is {html.escape(status)}.</p>"
        f"<p class='help'>The worker will generate missing avatar videos across {html.escape(scope)} one at a time. "
        "Each video is started, waited for, cached, and then the next missing video is attempted.</p>"
        f"<p class='help'>Regenerate existing videos: {'yes' if regenerate else 'no'}.</p>"
        "<div class='stack'>"
        "<a class='button-link' href='/admin/education-programmes'>Back to education programmes</a>"
        "</div>"
        "</div>"
    )
    return _wrap_page("Education Avatar Batch Queued", body)


def _promote_templates_batch(source_state: str, target_state: str, note: str | None = None) -> int:
    """
    Promote all templates from one state to another.
    develop → beta: assign next version number (max + 1)
    beta → live: keep the same version number as beta
    """
    _ensure_prompt_template_table()
    source_state = (source_state or "").strip().lower()
    target_state = (target_state or "").strip().lower()
    if source_state == target_state:
        raise HTTPException(400, "source and target states must differ")
    if (source_state, target_state) not in {("develop", "beta"), ("beta", "live")}:
        raise HTTPException(400, "Unsupported promotion path; use develop→beta or beta→live")

    with SessionLocal() as s:
        rows = s.query(PromptTemplate).filter(PromptTemplate.state == source_state).all()
        if not rows:
            raise HTTPException(400, f"No templates found in state '{source_state}'")
        if target_state == "live":
            invalid = []
            for row in rows:
                model_override = _normalize_model_override(getattr(row, "model_override", None))
                if model_override and model_override not in LIVE_TEMPLATE_ALLOWED_MODELS:
                    invalid.append(f"{row.touchpoint}={model_override}")
            if invalid:
                allowed = ", ".join(sorted(LIVE_TEMPLATE_ALLOWED_MODELS))
                sample = ", ".join(invalid[:8])
                suffix = "..." if len(invalid) > 8 else ""
                raise HTTPException(
                    400,
                    "Cannot promote to live with unsupported model_override. "
                    f"Allowed: {allowed}. Update these templates first: {sample}{suffix}",
                )

        next_version = None
        if (source_state, target_state) == ("develop", "beta"):
            next_version = (s.query(func.max(PromptTemplate.version)).scalar() or 0) + 1
        promoted_version = next_version if next_version is not None else max((row.version or 1) for row in rows)

        created = 0
        for row in rows:
            # Bump develop versions when promoting to beta so the dev row reflects the promoted version
            if (source_state, target_state) == ("develop", "beta"):
                row.version = promoted_version
            version_val = next_version if next_version is not None else (row.version or 1)
            existing = (
                s.query(PromptTemplate)
                .filter(
                    PromptTemplate.touchpoint == row.touchpoint,
                    PromptTemplate.state == target_state,
                    PromptTemplate.version == version_val,
                )
                .order_by(PromptTemplate.id.desc())
                .first()
            )
            if existing:
                existing.parent_id = row.id
                existing.task_block = row.task_block
                existing.block_order = row.block_order
                existing.include_blocks = row.include_blocks
                existing.okr_scope = row.okr_scope
                existing.programme_scope = row.programme_scope
                existing.response_format = row.response_format
                existing.model_override = getattr(row, "model_override", None)
                existing.is_active = True
                existing.note = row.note
                continue
            clone = _clone_template(row, target_state, version_val)
            clone.is_active = True
            s.add(clone)
            created += 1

        s.add(
            PromptTemplateVersionLog(
                version=promoted_version,
                from_state=source_state,
                to_state=target_state,
                note=note or None,
            )
        )
        # Keep only the latest row per touchpoint active for develop/beta; live retains history
        for prune_state in {source_state, target_state}:
            if prune_state in {"develop", "beta", "live"}:
                _enforce_single_active_states(s, {prune_state})
        s.commit()
        return created


@admin.get("/prompt-settings", response_class=HTMLResponse)
def edit_prompt_settings():
    _ensure_prompt_template_table()
    ensure_prompt_settings_schema()
    with SessionLocal() as s:
        row = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()
        if not row:
            row = PromptSettings()
            s.add(row)
            s.commit()
            s.refresh(row)

    def _esc(val):
        return html.escape("" if val is None else str(val))

    def _sel(val, expected):
        return " selected" if val == expected else ""

    display_dbo = [b for b in (getattr(row, "default_block_order", []) or []) if b not in BANNED_BLOCKS]
    worker_override = getattr(row, "worker_mode_override", None)
    podcast_override = getattr(row, "podcast_worker_mode_override", None)
    worker_env = (os.getenv("PROMPT_WORKER_MODE") or "").strip() or "unset"
    podcast_env = (os.getenv("PODCAST_WORKER_MODE") or "").strip() or "unset"

    html_out = f"""
    <h2>Global Prompt Settings</h2>
    <div class='card'>
    <form method="post" action="/admin/prompt-settings/save">
      <div class="field">System block:<br/><textarea name="system_block" rows="4">{_esc(getattr(row,'system_block',''))}</textarea></div>
      <div class="help">Global system message: persona/tone rules applied to all prompts.</div>
      <div class="field">Locale block:<br/><textarea name="locale_block" rows="3">{_esc(getattr(row,'locale_block',''))}</textarea></div>
      <div class="help">Locale message: language/region guidance (e.g., British English voice).</div>
      <div class="field">Default block order (JSON array or comma list):<br/><input name="default_block_order" value="{_esc(display_dbo)}" /></div>
      <div class="help">Default block order for all prompts; touchpoints can override.</div>
      <div class="field">Worker mode override:<br/>
        <select name="worker_mode_override">
          <option value=""{_sel(worker_override, None)}>Use env (PROMPT_WORKER_MODE={_esc(worker_env)})</option>
          <option value="on"{_sel(worker_override, True)}>Force ON</option>
          <option value="off"{_sel(worker_override, False)}>Force OFF</option>
        </select>
      </div>
      <div class="help">Controls whether the API enqueues work to the worker service.</div>
      <div class="field">Podcast worker override:<br/>
        <select name="podcast_worker_mode_override">
          <option value=""{_sel(podcast_override, None)}>Use env (PODCAST_WORKER_MODE={_esc(podcast_env)})</option>
          <option value="on"{_sel(podcast_override, True)}>Force ON</option>
          <option value="off"{_sel(podcast_override, False)}>Force OFF</option>
        </select>
      </div>
      <div class="help">Controls whether podcast/voice jobs are queued to the worker. Worker override OFF disables podcasts too.</div>
      <div class="actions"><button type="submit">Save</button></div>
    </form>
    </div>
    <p class='nav'><a href="/admin/prompt-templates">Back to templates</a></p>
    """
    return _wrap_page("Global Prompt Settings", html_out)


@admin.post("/prompt-settings/save")
async def save_prompt_settings(
    system_block: str | None = Form(default=None),
    locale_block: str | None = Form(default=None),
    default_block_order: str | None = Form(default=None),
    worker_mode_override: str | None = Form(default=None),
    podcast_worker_mode_override: str | None = Form(default=None),
):
    _ensure_prompt_template_table()
    ensure_prompt_settings_schema()
    dbo_list = [b for b in _parse_list_field(default_block_order) if b not in BANNED_BLOCKS]

    def _parse_override(val: str | None) -> bool | None:
        if val is None:
            return None
        cleaned = val.strip().lower()
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
        row.system_block = system_block or None
        row.locale_block = locale_block or None
        row.default_block_order = dbo_list or None
        row.worker_mode_override = _parse_override(worker_mode_override)
        row.podcast_worker_mode_override = _parse_override(podcast_worker_mode_override)
        s.commit()
    return RedirectResponse(url="/admin/prompt-settings", status_code=303)


@admin.get("/prompt-templates", response_class=HTMLResponse)
def list_prompt_templates(state: str | None = None, q: str | None = None, active_only: bool | None = None, version: str | None = None):
    _ensure_prompt_template_table()
    # Housekeeping: ensure only latest develop/beta/live per touchpoint are active (history kept inactive)
    try:
        with SessionLocal() as s:
            _enforce_single_active_states(s, {"develop", "beta", "live"})
            s.commit()
    except Exception:
        pass
    if state is None:
        state_filter = "develop"  # default view
    else:
        state_filter = (state or "").strip().lower()
    if state_filter in {"production"}:
        state_filter = "live"
    if state_filter in {"stage"}:
        state_filter = "beta"
    state_case = case(
        (
            (PromptTemplate.state == "live")
            | (PromptTemplate.state == "production"),
            0,
        ),
        (
            (PromptTemplate.state == "beta")
            | (PromptTemplate.state == "stage"),
            1,
        ),
        (PromptTemplate.state == "develop", 2),
        else_=3,
    )
    with SessionLocal() as s:
        version_filter = (version or "").strip().lower()
        query = s.query(PromptTemplate)
        query = query.filter(~PromptTemplate.touchpoint.in_(sorted(RETIRED_PROMPT_TOUCHPOINTS)))
        if state_filter:
            query = query.filter(PromptTemplate.state == state_filter)
        if q:
            like = f"%{q}%"
            query = query.filter(PromptTemplate.touchpoint.ilike(like))
        if active_only:
            query = query.filter(PromptTemplate.is_active == True)
        if version_filter == "latest":
            # Constrain to the latest version per touchpoint+state
            subq = (
                s.query(
                    PromptTemplate.touchpoint.label("tp"),
                    PromptTemplate.state.label("st"),
                    func.max(PromptTemplate.version).label("mv"),
                )
                .group_by(PromptTemplate.touchpoint, PromptTemplate.state)
                .subquery()
            )
            query = (
                query.join(
                    subq,
                    (PromptTemplate.touchpoint == subq.c.tp)
                    & (PromptTemplate.state == subq.c.st)
                    & (PromptTemplate.version == subq.c.mv),
                )
            )
        rows = (
            query.order_by(PromptTemplate.touchpoint.asc(), state_case, PromptTemplate.version.desc(), PromptTemplate.id.desc())
            .all()
        )
        settings = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()
        version_logs = (
            s.query(PromptTemplateVersionLog)
            .order_by(PromptTemplateVersionLog.created_at.desc())
            .limit(8)
            .all()
        )
        changed = False
        for r in rows:
            new_order = [b for b in (r.block_order or []) if b not in BANNED_BLOCKS]
            new_include = [b for b in (r.include_blocks or []) if b not in BANNED_BLOCKS]
            if new_order != (r.block_order or []) or new_include != (r.include_blocks or []):
                r.block_order = new_order
                r.include_blocks = new_include
                changed = True
        if settings and getattr(settings, "default_block_order", None):
            sanitized_default = [b for b in settings.default_block_order if b not in BANNED_BLOCKS]
            if sanitized_default != settings.default_block_order:
                settings.default_block_order = sanitized_default
                changed = True
        if changed:
            s.commit()

    def _esc(val):
        return html.escape("" if val is None else str(val))

    table_rows = []
    for r in rows:
        merged = [b for b in (r.block_order or []) if b not in BANNED_BLOCKS]
        state_label = {"production": "live", "stage": "beta"}.get(getattr(r, "state", ""), getattr(r, "state", ""))
        is_develop = state_label == "develop"
        action_label = "Edit" if is_develop else "View"
        action_href = f"/admin/prompt-templates/edit?id={r.id}" + ("" if is_develop else "&mode=view")
        table_rows.append(
            "<tr>"
            f"<td>{r.id}</td>"
            f"<td>{_esc(r.touchpoint)}</td>"
            f"<td>{_esc(state_label)}</td>"
            f"<td>{_esc(getattr(r,'version',1))}</td>"
            f"<td>{_esc(r.okr_scope or '')}</td>"
            f"<td>{_esc(getattr(r,'programme_scope','') or '')}</td>"
            f"<td>{_esc(getattr(r,'response_format','') or '')}</td>"
            f"<td>{_esc(getattr(r,'model_override','') or '')}</td>"
            f"<td>{_esc(merged)}</td>"
            f"<td>{_esc('✓' if getattr(r,'is_active',True) else '✕')}</td>"
            f"<td><a href='{action_href}'>{action_label}</a></td>"
            "</tr>"
        )

    log_rows = []
    for log in version_logs:
        log_rows.append(
            "<tr>"
            f"<td>{_esc(log.id)}</td>"
            f"<td>{_esc(log.created_at)}</td>"
            f"<td>{_esc(log.version)}</td>"
            f"<td>{_esc(log.from_state)} → {_esc(log.to_state)}</td>"
            f"<td>{_esc(log.note or '')}</td>"
            "</tr>"
        )

    body = (
        "<h2>Prompt Templates</h2>"
        f"{_build_version_label()}"
        "<div class='nav'><a href='/admin/prompt-settings'>Edit global prompt settings</a> · "
        "<a href='/admin/prompt-templates/edit'>Create new</a></div>"
        "<div class='card' style='margin-bottom:12px;'>"
        "<form method='get' action='/admin/prompt-templates' style='display:flex; gap:10px; align-items:flex-end; flex-wrap:wrap;'>"
        "<div><label>State<br/><select name='state'>"
        f"<option value='' {'selected' if not state_filter else ''}>All</option>"
        f"<option value='develop' {'selected' if state_filter=='develop' else ''}>Develop</option>"
        f"<option value='beta' {'selected' if state_filter=='beta' else ''}>Beta</option>"
        f"<option value='live' {'selected' if state_filter=='live' else ''}>Live</option>"
        "</select></label></div>"
        f"<div><label>Touchpoint contains<br/><input name='q' value='{_esc(q or '')}'/></label></div>"
        f"<div><label>Version<br/><select name='version'>"
        f"<option value='' {'selected' if not version_filter else ''}>All</option>"
        f"<option value='latest' {'selected' if version_filter=='latest' else ''}>Latest per state</option>"
        "</select></label></div>"
        f"<div><label><input type='checkbox' name='active_only' value='1' {'checked' if active_only else ''}/> Active only</label></div>"
        "<div><button type='submit'>Filter</button></div>"
        "</form>"
        "</div>"
        "<div class='card' style='margin-bottom:12px;'>"
        "<strong>Promote all templates</strong><br/>"
        "<form method='post' action='/admin/prompt-templates/promote-all' style='margin:6px 0;'>"
        "<input type='hidden' name='from_state' value='develop'/>"
        "<input type='hidden' name='to_state' value='beta'/>"
        "Note: <input type='text' name='note' style='width:260px' placeholder='Version note (optional)'/> "
        "<button type='submit'>Promote develop → beta</button>"
        "</form>"
        "<form method='post' action='/admin/prompt-templates/promote-all'>"
        "<input type='hidden' name='from_state' value='beta'/>"
        "<input type='hidden' name='to_state' value='live'/>"
        "Note: <input type='text' name='note' style='width:260px' placeholder='Version note (optional)'/> "
        "<button type='submit'>Promote beta → live</button>"
        "</form>"
        "</div>"
        "<div class='card'>"
        "<table>"
        "<tr><th>ID</th><th>Touchpoint</th><th>State</th><th>Version</th><th>OKR Scope</th><th>Programme Scope</th><th>Response</th><th>Model</th><th>Order/Include</th><th>Active</th><th>Action</th></tr>"
        + "".join(table_rows)
        + "</table>"
        "</div>"
        "<div class='card' style='margin-top:12px;'>"
        "<h3>Version history</h3>"
        "<table>"
        "<tr><th>ID</th><th>When</th><th>Version</th><th>Path</th><th>Note</th></tr>"
        + "".join(log_rows)
        + "</table>"
        "</div>"
    )
    return _wrap_page("Prompt Templates", body)


@admin.post("/prompt-templates/promote-all")
async def promote_prompt_templates(
    from_state: str = Form(...),
    to_state: str = Form(...),
    note: str | None = Form(default=None),
):
    cleaned_note = (note or "").strip() or None
    _promote_templates_batch(from_state.strip(), to_state.strip(), cleaned_note)
    return RedirectResponse(url="/admin/prompt-templates", status_code=303)


@admin.get("/prompt-templates/test", response_class=HTMLResponse)
def test_prompt_template(
    touchpoint: str | None = None,
    user_id: int | None = None,
    state: str = "live",
    test_date: str | None = None,
    run_llm: bool = False,
    user_filter: str | None = None,
    model_override: str | None = None,
):
    _ensure_prompt_template_table()
    def _runtime_scores_and_psych(u_id: int):
        run, pillars = kickoff_latest_assessment(u_id)
        psych = kickoff_latest_psych(u_id)
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
        return scores_payload, psych_payload
    # Simple form
    users_options = ""
    try:
        with SessionLocal() as s:
            q = s.query(User).order_by(User.id.asc())
            if user_filter:
                raw_filter = user_filter.strip()
                like = f"%{raw_filter}%"
                numeric_filter = raw_filter.removeprefix("#")
                user_id_filter = None
                if numeric_filter.isdigit():
                    try:
                        user_id_filter = int(numeric_filter)
                    except Exception:
                        user_id_filter = None
                q = q.filter(
                    (User.id == user_id_filter if user_id_filter is not None else false())
                    | (User.first_name.ilike(like))
                    | (User.surname.ilike(like))
                    | (User.phone.ilike(like))
                    | (User.email.ilike(like))
                )
            users = q.limit(2000).all()
            options = []
            for u in users:
                label = f"#{u.id} — {u.first_name or ''} {u.surname or ''} ({u.phone})".strip()
                selected = "selected" if user_id and int(user_id) == int(u.id) else ""
                options.append(f"<option value='{u.id}' {selected}>{html.escape(label)}</option>")
            users_options = "".join(options)
    except Exception:
        users_options = "<option disabled>(user lookup failed)</option>"
    try:
        from . import llm as shared_llm
        default_model_name = shared_llm.resolve_model_name_for_touchpoint(touchpoint)
    except Exception:
        default_model_name = "gpt-5.1"
    form = """
    <h2>Test Prompt Template</h2>
    {version_label}
    <div class='card'>
      <form method="get" action="/admin/prompt-templates/test">
        <div class="field">Touchpoint: <input name="touchpoint" value="{tp}" required /></div>
        <div class="field">User: <select name="user_id" required>{user_opts}</select></div>
        <div class="field">Filter users (id/name/phone/email): <input name="user_filter" value="{uf}" placeholder="e.g. 123, Julian, +44 or julian@" /></div>
        <div class="help">Showing up to 2000 users matching the filter.</div>
        <div class="field">State:
          <select name="state">
            <option value="live" {sel_live}>live</option>
            <option value="beta" {sel_beta}>beta</option>
            <option value="develop" {sel_dev}>develop</option>
          </select>
        </div>
        <div class="field">As of date: <input name="test_date" type="date" value="{dt}" required /></div>
        <div class="field">Run LLM? <input type="checkbox" name="run_llm" {rl} /></div>
        <div class="field">Model:
          <select name="model_override">
            <option value="" {mo_default}>Default (current: {default_model})</option>
            <option value="gpt-5.2-pro" {mo_52pro}>gpt-5.2-pro</option>
            <option value="gpt-5.2" {mo_52}>gpt-5.2</option>
            <option value="gpt-5.1" {mo_51}>gpt-5.1</option>
            <option value="gpt-5-mini" {mo_5mini}>gpt-5-mini</option>
            <option value="gpt-5-nano" {mo_5nano}>gpt-5-nano</option>
            <option value="gpt-4.1" {mo_41}>gpt-4.1</option>
            <option value="gpt-4.1-mini" {mo_41mini}>gpt-4.1-mini</option>
            <option value="gpt-4.1-nano" {mo_41nano}>gpt-4.1-nano</option>
            <option value="gpt-4o" {mo_4o}>gpt-4o</option>
            <option value="gpt-4o-mini" {mo_4omini}>gpt-4o-mini</option>
            <option value="o3" {mo_o3}>o3</option>
            <option value="o4-mini" {mo_o4mini}>o4-mini</option>
            <option value="gpt-3.5-turbo" {mo_35}>gpt-3.5-turbo</option>
          </select>
        </div>
        <div class="actions"><button type="submit">Preview</button></div>
      </form>
    </div>
    """.format(
        version_label=_build_version_label(),
        tp=html.escape(touchpoint or ""),
        user_opts=users_options,
        uf=html.escape(user_filter or ""),
        sel_live="selected" if (state or "live") == "live" else "",
        sel_beta="selected" if (state or "live") == "beta" else "",
        sel_dev="selected" if (state or "live") == "develop" else "",
        dt=html.escape(test_date or ""),
        rl="checked" if run_llm else "",
        mo_default="selected" if not model_override else "",
        default_model=html.escape(default_model_name or "default"),
        mo_52pro="selected" if model_override == "gpt-5.2-pro" else "",
        mo_52="selected" if model_override == "gpt-5.2" else "",
        mo_51="selected" if model_override == "gpt-5.1" else "",
        mo_5mini="selected" if model_override == "gpt-5-mini" else "",
        mo_5nano="selected" if model_override == "gpt-5-nano" else "",
        mo_41="selected" if model_override == "gpt-4.1" else "",
        mo_41mini="selected" if model_override == "gpt-4.1-mini" else "",
        mo_41nano="selected" if model_override == "gpt-4.1-nano" else "",
        mo_4o="selected" if model_override == "gpt-4o" else "",
        mo_4omini="selected" if model_override == "gpt-4o-mini" else "",
        mo_o3="selected" if model_override == "o3" else "",
        mo_o4mini="selected" if model_override == "o4-mini" else "",
        mo_35="selected" if model_override == "gpt-3.5-turbo" else "",
    )
    if not touchpoint or not user_id:
        return _wrap_page("Test Prompt Template", form)

    # Helper: build assemblies for touchpoints not handled by build_prompt
    def _build_nonstandard(tp: str):
        tp = tp.lower()
        try:
            if tp == "assessment_scores":
                return prompts_module.assessment_scores_prompt("User", 0, [])
            if tp == "assessment_okr":
                return prompts_module.okr_narrative_prompt("User", [])
            if tp == "assessment_approach":
                return prompts_module.coaching_approach_prompt("User", {}, {}, {})
            if tp == "assessor_system":
                # placeholder pillar/concept
                txt = prompts_module.assessor_system_prompt("nutrition", "fruit_veg")
                return SimpleNamespace(
                    text=txt,
                    blocks={
                        "system": "(global system)",
                        "locale": "(global locale)",
                        "context": "assessor system placeholder",
                        "assessor": "pillar=nutrition, concept=fruit_veg",
                        "task": "(task from template)",
                        "user": "(user input)",
                    },
                    block_order=["system", "locale", "context", "assessor", "task", "user"],
                )
        except Exception:
            return None
        return None

    # Build prompt using desired state override
    try:
        extra_kwargs = {}
        tp_lower = (touchpoint or "").lower()
        scores_payload, psych_payload = _runtime_scores_and_psych(int(user_id))
        # Podcast kickoff/weekstart: full runtime context
        if tp_lower in {"podcast_kickoff", "podcast_weekstart"}:
            run, pillars = kickoff_latest_assessment(int(user_id))
            programme = kickoff_programme_blocks(
                getattr(run, "finished_at", None)
                or getattr(run, "started_at", None)
                or getattr(run, "created_at", None)
            )
            first_block = programme[0] if programme else None
            extra_kwargs.update(
                {
                    "scores": scores_payload,
                    "psych_payload": psych_payload,
                    "programme": programme,
                    "first_block": first_block,
                }
            )
            if tp_lower == "podcast_kickoff":
                extra_kwargs["okrs_by_pillar"] = {
                    k: [kr.description for kr in v] for k, v in (kickoff_okr_by_pillar(int(user_id)) or {}).items()
                }
            if tp_lower == "podcast_weekstart":
                # Default week_no/focus_pillar to current programme block if available
                extra_kwargs["week_no"] = 1
                if first_block and first_block.get("pillar_key"):
                    extra_kwargs["focus_pillar"] = first_block.get("pillar_key")
        # Other coaching prompts: inject scores/psych and KR context
        krs_payload = kr_payload_list(int(user_id), max_krs=3)
        primary_kr = primary_kr_payload(int(user_id))
        if tp_lower in {"weekstart_support"}:
            extra_kwargs.update(
                {
                    "scores": scores_payload,
                    "psych_payload": psych_payload,
                    "krs_payload": krs_payload,
                    "history": [],
                }
            )
        if tp_lower == "weekstart_actions":
            extra_kwargs.update({"krs": krs_payload, "transcript": ""})
        if tp_lower == "habit_steps_generator":
            extra_kwargs.update({"krs": krs_payload, "transcript": "", "week_no": 1})
        if tp_lower == "initial_habit_steps_generator":
            extra_kwargs.update({"krs": krs_payload, "week_no": 1})
        if tp_lower in {"tuesday", "midweek", "saturday", "sunday"}:
            extra_kwargs.update(
                {
                    "scores": scores_payload,
                    "psych_payload": psych_payload,
                    "history_text": "",
                }
            )
        if tp_lower in {"podcast_thursday", "podcast_friday"}:
            extra_kwargs.update({"history_text": ""})
        assembly = build_prompt(
            touchpoint=touchpoint,
            user_id=int(user_id),
            coach_name="Coach",
            user_name="User",
            locale="UK",
            use_state=state,
            as_of_date=test_date,
            **extra_kwargs,
        )
    except Exception as e:
        # Graceful fallback for unsupported touchpoints: show template blocks with placeholders
        err_msg = str(e)
        if isinstance(e, ValueError) and "Unsupported touchpoint" in err_msg:
            alt = _build_nonstandard(touchpoint)
            if alt:
                assembly = alt
            else:
                settings = {}
                try:
                    settings = prompts_module._load_prompt_settings()
                except Exception:
                    settings = {"system_block": None, "locale_block": None, "default_block_order": prompts_module.DEFAULT_PROMPT_BLOCK_ORDER}
                try:
                    template = prompts_module._load_prompt_template_with_state(touchpoint, state) or prompts_module._load_prompt_template(touchpoint)
                except Exception:
                    template = None
                sys_block = (settings.get("system_block") if isinstance(settings, dict) else None) or prompts_module.common_prompt_header("Coach", "User", "UK")
                loc_block = (settings.get("locale_block") if isinstance(settings, dict) else None) or prompts_module.locale_block("UK")
                base_parts = [
                    ("system", sys_block),
                    ("locale", loc_block),
                    ("context", "(runtime context placeholder)"),
                    ("programme", "(runtime programme block)"),
                    ("history", "(runtime history block)"),
                    ("okr", "(runtime OKRs/ KRs block)"),
                    ("scores", "(runtime scores block)"),
                    ("habit", "(runtime habit readiness block)"),
                    ("task", (template or {}).get("task_block") or "(task block from template)"),
                    ("user", "(user input)"),
                ]
                parts, order_override = prompts_module._apply_prompt_template(base_parts, template)
                blocks = {lbl: txt for lbl, txt in parts if txt}
                assembly_text = prompts_module.assemble_prompt([txt for _, txt in parts if txt])
                assembly = SimpleNamespace(
                    text=assembly_text,
                    blocks=blocks,
                    block_order=order_override or (settings.get("default_block_order") if isinstance(settings, dict) else prompts_module.DEFAULT_PROMPT_BLOCK_ORDER),
                )
        else:
            return _wrap_page("Test Prompt Template", form + f"<div class='card'><pre>{html.escape(err_msg)}</pre></div>")

    llm_preview = ""
    llm_raw = ""
    audio_link = ""
    if run_llm:
        try:
            # Lazy import to avoid cycles
            from . import llm as shared_llm
            import time
            t0 = time.perf_counter()
            resolved_model = shared_llm.resolve_model_name_for_touchpoint(
                touchpoint=touchpoint,
                model_override=model_override,
            )
            client = shared_llm.get_llm_client(
                touchpoint=touchpoint,
                model_override=model_override,
            )
            resp = client.invoke(assembly.text)
            duration = time.perf_counter() - t0
            content = (getattr(resp, "content", "") or "").strip()
            llm_raw = content
            llm_preview = f"<h3>LLM Response (took {duration:.2f}s, model={html.escape(resolved_model)})</h3><pre>{html.escape(content[:1000])}</pre>"
        except Exception as e:
            llm_preview = f"<h3>LLM Response</h3><pre>{html.escape(str(e))}</pre>"

    # Optional podcast audio generation
    auto_audio = (touchpoint or "").lower().startswith("podcast_")
    if auto_audio and user_id:
        try:
            from .podcast import generate_podcast_audio
            fname = f"test_podcast_{touchpoint}_{int(time.time())}.mp3"
            audio_source = llm_raw or assembly.text
            url = generate_podcast_audio(
                audio_source,
                int(user_id),
                filename=fname,
                usage_tag="admin_test",
            )
            audio_link = url or ""
        except Exception as e:
            audio_link = f"(audio generation failed: {e})"

    # Ensure preview shows only the blocks that are actually included, in order.
    placeholder_map = {
        "system": "(global system block)",
        "locale": "(global locale block)",
        "context": "(runtime data — touchpoint context, channel, timeframe)",
        "programme": "(runtime data — programme block)",
        "okr": "(runtime data — OKRs / KRs block)",
        "scores": "(runtime data — latest assessment scores if available)",
        "habit": "(runtime data — habit readiness parameters/flags)",
        "history": "(runtime data — recent interactions for this user)",
        "assessor": "(runtime data — assessor payload)",
        "task": "(task block from template)",
        "user": "(user input at runtime)",
    }
    blocks_map = dict(assembly.blocks or {})
    order_list = [lbl for lbl in list(assembly.block_order or []) if lbl in blocks_map]
    if not order_list:
        order_list = [lbl for lbl in prompts_module.DEFAULT_PROMPT_BLOCK_ORDER if lbl in blocks_map] or list(blocks_map.keys())
    # Fill placeholders only for blocks referenced in the order list
    for lbl in order_list:
        if not blocks_map.get(lbl):
            blocks_map[lbl] = placeholder_map.get(lbl, f"(placeholder for {lbl})")
    assembly.block_order = order_list
    assembly.blocks = {lbl: blocks_map[lbl] for lbl in order_list if blocks_map.get(lbl)}
    assembly.text = prompts_module.assemble_prompt([blocks_map[l] for l in order_list if blocks_map.get(l)])

    order_list = assembly.block_order or []
    order_html = ""
    if order_list:
        order_html = "<div class='card' style='margin-top:12px;'><strong>Block order used in assembly:</strong> " + html.escape(", ".join(order_list)) + "</div>"

    blocks_map = assembly.blocks or {}
    blocks_html = "<h3>Blocks (these are concatenated in the assembled prompt)</h3><div class='card'><table>"
    if not blocks_map:
        blocks_html += "<tr><td colspan='2'><em>No blocks found for this test run.</em></td></tr>"
    else:
        for lbl, txt in blocks_map.items():
            blocks_html += f"<tr><th>{html.escape(lbl)}</th><td><pre style='white-space:pre-wrap; overflow-wrap:break-word;'>{html.escape(txt)}</pre></td></tr>"
    blocks_html += "</table></div>"

    audio_html = ""
    if audio_link:
        audio_html = (
            "<div class='card' style='margin-top:12px;'>"
            "<strong>Podcast audio:</strong> "
            f"<a class='button-link' href='{audio_link}' target='_blank' rel='noopener'>Play/Download</a>"
            f"<div class='help'>{html.escape(audio_link)}</div>"
            "</div>"
        )

    assembled_html = (
        "<div class='card'><details open>"
        "<summary style='cursor:pointer; font-weight:600;'>Assembled prompt (full text)</summary>"
        "<div class='help'>All blocks below are concatenated in this order to form the prompt sent to the LLM.</div>"
        f"<pre style='white-space:pre-wrap; overflow-wrap:break-word;'>{html.escape(assembly.text)}</pre>"
        "</details></div>"
    )

    if llm_preview:
        llm_preview = (
            "<div class='card' style='margin-top:12px;'>"
            "<details open>"
            "<summary style='cursor:pointer; font-weight:600;'>LLM Response</summary>"
            f"{llm_preview}"
            "<div style='margin-top:8px;'><button type='button' class='button-link' onclick=\"openLLMResponse()\">Open in new tab</button></div>"
            "</details>"
            f"<pre id='llm-content' style='display:none;'>{html.escape(llm_raw) if llm_raw else ''}</pre>"
            "</div>"
            "<script>function openLLMResponse(){const txt=document.getElementById('llm-content').textContent||'';const w=window.open('','_blank');if(w){w.document.write('<pre style=\"white-space:pre-wrap;font-family:ui-monospace,monospace;\">'+txt+'</pre>');w.document.close();}}</script>"
        )

    body = form + assembled_html + audio_html + order_html + blocks_html + llm_preview
    return _wrap_page("Test Prompt Template", body)


@admin.get("/prompt-templates/edit", response_class=HTMLResponse)
def edit_prompt_template(id: int | None = None, mode: str | None = None):
    _ensure_prompt_template_table()
    try:
        _ensure_llm_prompt_log_schema()
    except Exception:
        pass
    row = None
    settings_row = None
    recent_logs = []
    if id is not None:
        with SessionLocal() as s:
            row = s.get(PromptTemplate, id)
            if not row:
                raise HTTPException(404, "PromptTemplate not found")
            try:
                recent_logs = (
                    s.execute(
                        sa_text(
                            """
                            SELECT id, user_id, created_at, template_state, template_version, model, duration_ms,
                                   assembled_prompt, response_preview
                            FROM llm_prompt_logs_view
                            WHERE touchpoint = :tp
                            ORDER BY created_at DESC
                            LIMIT 5
                            """
                        ),
                        {"tp": row.touchpoint},
                    ).fetchall()
                )
            except Exception:
                recent_logs = []
    with SessionLocal() as s:
        settings_row = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()
    def _esc(val):
        return html.escape("" if val is None else str(val))
    def _val(field, default=""):
        return html.escape(str(getattr(row, field, default) or ""))
    def _js(val: str) -> str:
        return json.dumps(val or "")
    system_txt = (settings_row.system_block if settings_row else "") or "(runtime default system block)"
    locale_txt = (settings_row.locale_block if settings_row else "") or "(runtime default locale block)"
    default_order = [b for b in ((settings_row.default_block_order if settings_row else None) or _PROMPT_TEMPLATE_DEFAULTS["block_order"]) if b not in BANNED_BLOCKS]
    block_order_val = _esc([b for b in (getattr(row, "block_order", []) or []) if b not in BANNED_BLOCKS])
    include_val = _esc([b for b in (getattr(row, "include_blocks", []) or []) if b not in BANNED_BLOCKS]) or block_order_val
    view_only = bool((mode or "").lower() == "view" or (row and getattr(row, "state", "") != "develop"))
    readonly = "readonly" if view_only else ""
    disabled = "disabled" if view_only else ""
    script_js = """
    <script>
      function parseList(val) {{
        if (!val) return [];
        // Try JSON first (handles proper arrays)
        try {{ const j = JSON.parse(val); if (Array.isArray(j)) return j; }} catch(e) {{}}
        // Fallback: strip brackets/quotes and split on commas
        const cleaned = val.replace(/[\\[\\]\\"]/g, '').replace(/'/g, '');
        return cleaned.split(',').map(s => s.trim()).filter(Boolean);
      }}
      function previewPrompt() {{
        const f = document.getElementById('tpl-form');
        const banned = ["developer","policy","tool"];
        // keep include in sync with order (single field UX)
        if (f.include_blocks) f.include_blocks.value = f.block_order.value;
        const okrScope = (f.okr_scope.value || '').trim() || '(default)';
        let okrDesc = '(runtime data — OKRs/KRs based on selected scope)';
        if (okrScope === 'all') okrDesc = '(runtime data — OKRs across all pillars)';
        else if (okrScope === 'pillar') okrDesc = '(runtime data — OKRs limited to current pillar)';
        else if (okrScope === 'week') okrDesc = '(runtime data — this week’s active KRs)';
        else if (okrScope === 'single') okrDesc = '(runtime data — primary KR only)';

        const programmeScope = (f.programme_scope.value || '').trim() || 'none';
        let programmeDesc = '(runtime data — programme blocks)';
        if (programmeScope === 'pillar') programmeDesc = '(runtime data — current block only)';
        else if (programmeScope === 'full') programmeDesc = '(runtime data — full programme schedule)';
        else if (programmeScope === 'none') programmeDesc = '(programme block omitted)';

        const blocks = {{
          system: {system},
          locale: {locale},
          context: '(runtime data — touchpoint context, channel, timeframe)',
          history: '(runtime data — recent interactions for this user)',
          okr: okrDesc + ' (scope=' + okrScope + ')',
          programme: programmeDesc + ' (scope=' + programmeScope + ')',
          scores: '(runtime data — latest assessment scores if available)',
          habit: '(runtime data — habit readiness parameters/flags)',
          task: f.task_block.value || '(task)',
          user: '(user input as provided at run time)',
        }};
        // merged field: order == include; we still allow defaults fallback
        const include = parseList(f.block_order.value).filter(lbl => !banned.includes(lbl));
        const baseOrder = include.length ? include : {default_order};
        const effectiveOrder = baseOrder.filter(lbl => !banned.includes(lbl) && blocks[lbl]);
        const text = effectiveOrder
          .map(lbl => blocks[lbl] ? lbl.toUpperCase() + "\\n" + blocks[lbl] : '')
          .filter(Boolean)
          .join("\\n\\n");
        const finalText = text || Object.keys(blocks).map(lbl => lbl.toUpperCase() + "\\n" + blocks[lbl]).join("\\n\\n");
        document.getElementById('preview-content').textContent = finalText || '(nothing to preview)';
        document.getElementById('preview-modal').style.display = 'block';
      }}
      function closePreview() {{
        document.getElementById('preview-modal').style.display = 'none';
      }}
    </script>
    """.format(
        system=_js(system_txt),
        locale=_js(locale_txt),
        default_order=_js(default_order),
    )
    state_label = {"production": "live", "stage": "beta"}.get(_val("state", "develop"), _val("state", "develop"))
    title_action = "View" if view_only else ("Edit" if row else "Create")
    tp_label = _val("touchpoint")
    title_text = f"{title_action} Prompt Template"
    if tp_label:
        title_text += f": {tp_label}"
    title_text += f" — {state_label}"
    html_out = f"""
    <h2>{title_text}</h2>
    {_build_version_label()}
    <div class='card'>
    <form method="post" action="/admin/prompt-templates/save" id="tpl-form">
      <input type="hidden" name="id" value="{_val('id')}" />
      <div class="field">Touchpoint (read-only once created): <input name="touchpoint" value="{_val('touchpoint')}" required {"readonly" if row else ""} {readonly} /></div>
      <div class="help">Touchpoint: key used by the app to select this template (e.g., podcast_kickoff, tuesday). State is fixed ({state_label}); promote via the list page.</div>
      <input type="hidden" name="state" value="{_val('state','develop')}" />
      <div class="field">OKR scope (all|pillar|week|single): <input name="okr_scope" value="{_val('okr_scope')}" {readonly} /></div>
      <div class="help">OKR scope controls which OKRs are shown in the prompt (all pillars, a single pillar, the current week, or a single KR).</div>
      <div class="field">Programme scope (full|pillar|none): <input name="programme_scope" value="{_val('programme_scope')}" {readonly} /></div>
      <div class="help">Programme scope: full = show 12-week schedule; pillar = show current block only; none = omit.</div>
      <div class="field">Default model override (optional): <input name="model_override" value="{_val('model_override')}" {readonly} /></div>
      <div class="help">If set, this model is used at runtime for this touchpoint unless a request-level override is supplied.</div>
      <div class="field">
        Blocks (order = include) (JSON array or comma list):
        <input name="block_order" id="block_order" style="width:100%" value="{block_order_val}" {readonly} />
        <input type="hidden" name="include_blocks" id="include_blocks" value="{include_val}" />
      </div>
      <div class="help">Enter blocks in the order you want them applied; this same list is the include set. Leave blank to use global default.</div>
      <div class="field">Task block:<br/><textarea name="task_block" rows="8" {readonly}>{_val('task_block')}</textarea></div>
      <div class="help">Task: the main instruction for the LLM for this touchpoint.</div>
      <div class="field">Active? <input type="checkbox" name="is_active" {"checked" if getattr(row,'is_active',True) else ""} {disabled}></div>
      <div class="actions">
        {"<button type='submit'>Save</button>" if not view_only else ""}
        <button type="button" onclick="previewPrompt()" style="margin-left:8px; background:#0f172a;">Preview</button>
        {"<a class='button-link' href='/admin/prompt-templates/test?touchpoint=" + _val('touchpoint') + "&state=develop' style='margin-left:8px;'>Test (develop)</a>" if row else ""}
      </div>
    </form>
    </div>
    """
    if row:
        log_rows = []
        def _fmt(val, default="-"):
            return html.escape("" if val is None else str(val)) if val not in (None, "") else default
        for log in recent_logs:
            m = getattr(log, "_mapping", log)
            assembled = (getattr(log, "assembled_prompt", None) or m.get("assembled_prompt") or "")
            response = (getattr(log, "response_preview", None) or m.get("response_preview") or "")
            log_rows.append(
                "<tr>"
                f"<td>{_fmt(m.get('id'))}</td>"
                f"<td>{_fmt(m.get('user_id'))}</td>"
                f"<td>{_fmt(m.get('created_at'))}</td>"
                f"<td>{_fmt(m.get('template_state'))}</td>"
                f"<td>{_fmt(m.get('template_version'))}</td>"
                f"<td>{_fmt(m.get('model'))}</td>"
                f"<td>{_fmt(m.get('duration_ms'))}</td>"
                "<td>"
                f"<details><summary>Prompt</summary><pre style='white-space:pre-wrap; overflow-wrap:break-word;'>{html.escape(assembled)}</pre></details>"
                f"<details><summary>LLM response</summary><pre style='white-space:pre-wrap; overflow-wrap:break-word;'>{html.escape(response)}</pre></details>"
                "</td>"
                "</tr>"
            )
        if log_rows:
            html_out += (
                "<div class='card'><h3>Recent prompt runs (last 5)</h3>"
                "<table>"
                "<tr><th>ID</th><th>User</th><th>When</th><th>State</th><th>Version</th><th>Model</th><th>Duration (ms)</th><th>Preview</th></tr>"
                + "".join(log_rows)
                + "</table></div>"
            )
        else:
            html_out += (
                "<div class='card'><h3>Recent prompt runs (last 5)</h3>"
                "<div class='help'>No prompt logs found yet for this touchpoint.</div>"
                "</div>"
            )
    html_out += """
    <p class='nav'><a href="/admin/prompt-templates">Back to list</a></p>
    <div id="preview-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.5); padding:20px; z-index:999;">
      <div style="max-width:800px; margin:40px auto; background:#fff; border-radius:12px; padding:18px; box-shadow:0 12px 32px rgba(0,0,0,0.15);">
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <h3 style="margin:0; font-family:'Outfit','Inter',sans-serif;">Prompt Preview</h3>
          <button onclick="closePreview()" style="background:#999;">Close</button>
        </div>
        <pre id="preview-content" style="white-space:pre-wrap; margin-top:12px; font-family:ui-monospace,Menlo,Consolas,monospace;"></pre>
      </div>
    </div>
    """
    html_out += script_js
    return _wrap_page(title_text, html_out)


@admin.post("/prompt-templates/save")
async def save_prompt_template(
    request: Request,
    id: int | None = Form(default=None),
    touchpoint: str = Form(...),
    state: str | None = Form(default="develop"),
    okr_scope: str | None = Form(default=None),
    programme_scope: str | None = Form(default=None),
    response_format: str | None = Form(default=None),
    model_override: str | None = Form(default=None),
    block_order: str | None = Form(default=None),
    include_blocks: str | None = Form(default=None),
    task_block: str | None = Form(default=None),
    is_active: str | None = Form(default=None),
):
    _ensure_prompt_template_table()
    bo_list = [b for b in _parse_list_field(block_order) if b not in BANNED_BLOCKS]
    inc_list = [b for b in (_parse_list_field(include_blocks) or bo_list) if b not in BANNED_BLOCKS]
    active_flag = True if is_active is not None else None

    with SessionLocal() as s:
        if id:
            row = s.get(PromptTemplate, id)
            if not row:
                raise HTTPException(404, "PromptTemplate not found")
            if getattr(row, "state", "") != "develop":
                raise HTTPException(400, "Only 'develop' templates can be edited")
        else:
            row = PromptTemplate(touchpoint=touchpoint)
            s.add(row)
        if not getattr(row, "version", None):
            row.version = 1
        if active_flag is None:
            active_flag = getattr(row, "is_active", True)
        state_val = (state or getattr(row, "state", "develop") or "develop").strip().lower()
        if state_val not in {"develop", "beta", "live"}:
            raise HTTPException(400, "State must be develop|beta|live")
        model_override_val = _normalize_model_override(model_override)
        if state_val == "live":
            _ensure_live_template_model_allowed(
                model_override_val,
                context=f"touchpoint '{touchpoint}' live state",
            )
        row.touchpoint = touchpoint
        row.state = state_val
        row.okr_scope = okr_scope or None
        row.programme_scope = programme_scope or None
        row.response_format = response_format or None
        row.model_override = model_override_val
        row.block_order = bo_list
        # include_blocks now mirrors block_order (single merged field)
        row.include_blocks = inc_list or bo_list
        row.task_block = task_block or None
        row.is_active = active_flag
        s.commit()
    return RedirectResponse(url="/admin/prompt-templates", status_code=303)


@admin.get("/education-programmes", response_class=HTMLResponse)
def list_education_programmes():
    ensure_education_plan_schema()
    with SessionLocal() as s:
        rows = (
            s.query(EducationProgramme)
            .order_by(EducationProgramme.updated_at.desc(), EducationProgramme.id.desc())
            .all()
        )
        day_lengths = {
            int(programme_id): int(max_day or 0)
            for programme_id, max_day in (
                s.query(EducationProgrammeDay.programme_id, func.max(EducationProgrammeDay.day_index))
                .group_by(EducationProgrammeDay.programme_id)
                .all()
            )
        }
    items = []
    for row in rows:
        duration_days = int(day_lengths.get(int(row.id), 0) or 0)
        row_id = int(row.id)
        row_code = str(row.code or "")
        row_name = str(row.name or "")
        items.append(
            "<tr>"
            f"<td>{row_id}</td>"
            f"<td>{html.escape(str(getattr(row, 'concept_label', None) or getattr(row, 'concept_key', None) or ''))}</td>"
            f"<td>{html.escape(str(row.pillar_key or ''))}</td>"
            f"<td>{html.escape(row_code)}</td>"
            f"<td>{html.escape(row_name)}</td>"
            f"<td>{duration_days}</td>"
            f"<td>{'✓' if bool(row.is_active) else '✕'}</td>"
            f"<td>{html.escape(str(row.updated_at or ''))}</td>"
            "<td>"
            f"<a href='/admin/education-programmes/edit?id={row_id}'>Edit</a>"
            "<form method='post' action='/admin/education-programmes/delete' "
            "style='display:inline; margin-left:8px;' "
            "onsubmit=\"return confirm('Delete this education programme? This cannot be undone.');\">"
            f"<input type='hidden' name='id' value='{row_id}' />"
            f"<input type='hidden' name='expected_code' value='{html.escape(row_code)}' />"
            "<button type='submit' class='danger' style='padding:6px 10px;'>Delete</button>"
            "</form>"
            "</td>"
            "</tr>"
        )
    body = (
        "<h2>Education Programmes</h2>"
        f"{_build_version_label()}"
        "<div class='nav'><a href='/admin/education-programmes/edit'>Create new programme</a></div>"
        "<div class='card'>"
        "<h3 class='section-title'>Avatar video batch</h3>"
        "<p class='help'>Run avatar video jobs across every active education programme. The safe batch completes one video before starting the next.</p>"
        "<div class='stack'>"
        "<form method='post' action='/admin/education-programmes/avatar/generate-all' "
        "onsubmit=\"return confirm('Generate all missing avatar videos sequentially? This can take a long time because each video must complete before the next starts.');\">"
        "<input type='hidden' name='active_only' value='1' />"
        "<input type='hidden' name='wait_for_completion' value='1' />"
        "<input type='hidden' name='enqueue' value='1' />"
        "<button type='submit' class='secondary'>Generate all missing videos sequentially</button>"
        "</form>"
        "<form method='post' action='/admin/education-programmes/avatar/refresh-all' "
        "onsubmit=\"return confirm('Refresh all pending avatar jobs for every active education programme?');\">"
        "<input type='hidden' name='active_only' value='1' />"
        "<button type='submit' class='secondary'>Refresh pending videos for all active programmes</button>"
        "</form>"
        "<form method='post' action='/admin/education-programmes/avatar/generate-all' "
        "onsubmit=\"return confirm('Start up to two missing Azure jobs without waiting? Use this only if Azure quota allows concurrent jobs.');\">"
        "<input type='hidden' name='active_only' value='1' />"
        "<input type='hidden' name='max_new_jobs' value='2' />"
        "<button type='submit' class='secondary'>Start up to 2 jobs without waiting</button>"
        "</form>"
        "</div>"
        "</div>"
        "<div class='card'>"
        "<table>"
        "<tr><th>ID</th><th>Concept</th><th>Derived Pillar</th><th>Code</th><th>Name</th><th>Days</th><th>Active</th><th>Updated</th><th>Action</th></tr>"
        + ("".join(items) if items else "<tr><td colspan='9'><em>No education programmes configured yet.</em></td></tr>")
        + "</table>"
        "</div>"
    )
    return _wrap_page("Education Programmes", body)


@admin.post("/education-programmes/delete")
def delete_education_programme(
    id: int = Form(...),
    expected_code: str | None = Form(default=None),
):
    ensure_education_plan_schema()
    with SessionLocal() as s:
        row = s.get(EducationProgramme, int(id))
        if row is None:
            raise HTTPException(404, "Education programme not found")
        code = str(getattr(row, "code", "") or "").strip()
        expected = str(expected_code or "").strip()
        if expected and expected != code:
            raise HTTPException(400, "Programme code confirmation did not match")
        plan_count = (
            s.query(UserEducationPlan)
            .filter(UserEducationPlan.programme_id == int(row.id))
            .count()
        )
        if plan_count:
            row.is_active = False
            s.add(row)
            s.commit()
            body = (
                "<h2>Programme not deleted</h2>"
                "<div class='card'>"
                f"<p>Programme <strong>{html.escape(code)}</strong> has {int(plan_count)} user education plan(s) attached.</p>"
                "<p>It has been deactivated instead, so it will no longer be selected for new users.</p>"
                "<p class='nav'><a href='/admin/education-programmes'>Back to education programmes</a></p>"
                "</div>"
            )
            return _wrap_page("Programme not deleted", body)
        s.delete(row)
        s.commit()
    return RedirectResponse(url="/admin/education-programmes", status_code=303)


@admin.post("/education-programmes/avatar/generate-all", response_class=HTMLResponse)
def generate_all_education_programme_avatars(
    active_only: str | None = Form(default="1"),
    regenerate: str | None = Form(default=None),
    max_new_jobs: str | None = Form(default=None),
    wait_for_completion: str | None = Form(default=None),
    enqueue: str | None = Form(default=None),
):
    active_only_flag = _truthy_form_value(active_only)
    regenerate_flag = _truthy_form_value(regenerate)
    wait_for_completion_flag = _truthy_form_value(wait_for_completion)
    max_new_jobs_value = _optional_positive_int(max_new_jobs)
    if _truthy_form_value(enqueue):
        ensure_job_table()
        payload = {
            "active_only": active_only_flag,
            "regenerate": regenerate_flag,
            "max_new_jobs": max_new_jobs_value,
            "wait_for_completion": True,
            "trigger": "admin_education_avatar_generate_all",
        }
        job_id, created = enqueue_job_once(
            "education_avatar_generate_all",
            payload,
            payload_match={
                "trigger": "admin_education_avatar_generate_all",
                "active_only": active_only_flag,
                "regenerate": regenerate_flag,
            },
            running_stale_minutes=240,
        )
        return _education_avatar_batch_queued_page(
            int(job_id),
            created=bool(created),
            active_only=active_only_flag,
            regenerate=regenerate_flag,
        )
    try:
        result = generate_all_education_programme_avatar_videos(
            regenerate=regenerate_flag,
            active_only=active_only_flag,
            max_new_jobs=max_new_jobs_value,
            wait_for_completion=wait_for_completion_flag,
        )
    except RuntimeError as exc:
        message = str(exc)
        status_code = 503 if "not enabled" in message.lower() else 400
        raise HTTPException(status_code, message)
    return _education_avatar_all_result_page("Education Programme Avatar Generation Batch", result)


@admin.post("/education-programmes/avatar/refresh-all", response_class=HTMLResponse)
def refresh_all_education_programme_avatars(
    active_only: str | None = Form(default="1"),
):
    try:
        result = refresh_all_education_programme_avatar_videos(
            active_only=_truthy_form_value(active_only),
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return _education_avatar_all_result_page("Education Programme Avatar Refresh Batch", result)


@admin.post("/education-programmes/{programme_id}/avatar/generate", response_class=HTMLResponse)
def generate_education_programme_avatars(
    programme_id: int,
    regenerate: str | None = Form(default=None),
):
    try:
        result = generate_education_programme_avatar_videos(
            int(programme_id),
            regenerate=_truthy_form_value(regenerate),
        )
    except RuntimeError as exc:
        message = str(exc)
        status_code = 503 if "not enabled" in message.lower() else 400
        raise HTTPException(status_code, message)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    title = "Education Programme Avatar Generation"
    return _education_avatar_bulk_result_page(title, result)


@admin.post("/education-programmes/{programme_id}/avatar/refresh", response_class=HTMLResponse)
def refresh_education_programme_avatars(programme_id: int):
    try:
        result = refresh_education_programme_avatar_videos(int(programme_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))
    return _education_avatar_bulk_result_page("Education Programme Avatar Refresh", result)


@admin.post("/education-programmes/lesson-variants/{variant_id}/avatar/generate")
async def generate_education_programme_lesson_avatar(variant_id: int, request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    try:
        return generate_education_lesson_avatar(int(variant_id), payload if isinstance(payload, dict) else {})
    except RuntimeError as exc:
        message = str(exc)
        status_code = 503 if "not enabled" in message.lower() else 400
        raise HTTPException(status_code, message)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@admin.post("/education-programmes/lesson-variants/{variant_id}/avatar/refresh")
async def refresh_education_programme_lesson_avatar(variant_id: int):
    try:
        return refresh_education_lesson_avatar(int(variant_id))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except RuntimeError as exc:
        raise HTTPException(400, str(exc))


@admin.post("/education-programmes/programme/llm-regenerate")
async def regenerate_education_concept_programme_with_llm(request: Request):
    ensure_education_plan_schema()
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(400, f"Invalid JSON payload: {exc}")
    if not isinstance(payload, dict):
        raise HTTPException(400, "JSON payload must be an object")

    model_override = _normalize_model_override(str(payload.get("model_override") or ""))
    brief = str(payload.get("brief") or "").strip()
    existing_programme = payload.get("existing_programme") if isinstance(payload.get("existing_programme"), dict) else {}
    concept_key = str(payload.get("programme_concept_key") or existing_programme.get("programme_concept_key") or "").strip().lower()
    concept_label = str(payload.get("programme_concept_label") or existing_programme.get("programme_concept_label") or "").strip()
    pillar_key = str(payload.get("pillar_key") or existing_programme.get("pillar_key") or "").strip().lower()
    if not concept_key:
        raise HTTPException(400, "programme_concept_key is required")
    try:
        requested_days = int(payload.get("duration_days") or existing_programme.get("duration_days") or 0)
    except Exception:
        requested_days = 0
    if requested_days <= 0:
        raw_days = existing_programme.get("days") if isinstance(existing_programme.get("days"), list) else []
        requested_days = len(raw_days) if raw_days else 7
    requested_days = max(1, min(31, requested_days))

    programme_context = {
        "programme_name": str(payload.get("programme_name") or existing_programme.get("programme_name") or "").strip(),
        "programme_code": str(payload.get("programme_code") or existing_programme.get("programme_code") or "").strip(),
        "pillar_key": pillar_key,
        "programme_concept_key": concept_key,
        "programme_concept_label": concept_label,
        "requested_days": requested_days,
        "task_description": brief or "Regenerate a complete concept programme for this concept.",
        "existing_programme": _compact_education_programme_for_llm(existing_programme),
    }
    output_schema = {
        "programme": {
            "programme_name": "string",
            "programme_code": "string",
            "duration_days": requested_days,
            "days": [
                {
                    "day_index": 1,
                    "lesson_goal": "string",
                    "default_title": "string",
                    "default_summary": "string",
                    "variants": [
                        {
                            "level": "build",
                            "title": "string",
                            "summary": "string",
                            "script": "string",
                            "action_prompt": "string",
                            "poster_url": "",
                            "avatar_character": "",
                            "avatar_style": "",
                            "avatar_voice": "",
                            "takeaway_default": "string",
                            "takeaway_if_low_score": "string",
                            "takeaway_if_high_score": "string",
                            "is_active": True,
                            "quiz": {
                                "pass_score_pct": 66.67,
                                "questions": [
                                    {
                                        "question_order": 1,
                                        "question_text": "string",
                                        "answer_type": "single_choice",
                                        "options_json": ["string", "string", "string", "string"],
                                        "correct_answer_json": "one exact option string",
                                        "explanation": "string",
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
        }
    }
    prompt = (
        "You are creating a complete HealthSense concept-based education programme for the admin editor.\n"
        "Return a single valid JSON object only. Do not use markdown, code fences, comments, or prose outside JSON.\n\n"
        "Task:\n"
        "- Regenerate the full concept programme from the task_description and selected concept.\n"
        "- Use the existing programme only for context and continuity; replace the day plan, lesson goals, lesson scripts, daily actions, takeaways, and quizzes.\n"
        f"- Return exactly {requested_days} programme days, numbered 1 to {requested_days}.\n"
        "- Keep every day on the selected programme concept; do not drift into other concepts unless the task explicitly asks for a supporting contrast.\n"
        "- Generate one active variant per day unless the task_description explicitly asks for multiple variants.\n"
        "- Use level='build' unless the task_description asks for another level or a clear level progression.\n"
        "- Include exactly 3 quiz questions for each variant.\n"
        "- Use answer_type='single_choice' unless the task_description clearly requires boolean or multi_choice.\n"
        "- For single_choice questions, options_json must be an array of 4 short answer options.\n"
        "- correct_answer_json must exactly match the correct option string for single_choice questions.\n"
        "- Leave video_url, avatar_status, avatar_job_id, avatar_error, avatar_generated_at, avatar_source, and avatar_summary_url absent or empty.\n"
        "- Use UK English, clear coaching language, practical daily actions, and avoid diagnosis or medical claims.\n\n"
        "CONTEXT_JSON:\n"
        f"{json.dumps(programme_context, ensure_ascii=False, default=str)}\n\n"
        "OUTPUT_SCHEMA_JSON:\n"
        f"{json.dumps(output_schema, ensure_ascii=False)}\n"
    )

    try:
        from . import llm as shared_llm

        t0 = time.perf_counter()
        resolved_model = shared_llm.resolve_model_name_for_touchpoint(
            touchpoint=EDUCATION_PROGRAMME_LLM_TOUCHPOINT,
            model_override=model_override,
        )
        client = shared_llm.get_llm_client(
            touchpoint=EDUCATION_PROGRAMME_LLM_TOUCHPOINT,
            model_override=model_override,
        )
        response = client.invoke(prompt)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        content = _coerce_llm_content(getattr(response, "content", None)).strip()
    except Exception as exc:
        raise HTTPException(500, f"LLM programme generation failed: {exc}")

    try:
        raw_generated = _extract_llm_json_object(content)
        generated_programme = _normalise_generated_education_programme(
            raw_generated,
            concept_key=concept_key,
            concept_label=concept_label,
            requested_days=requested_days,
        )
    except Exception as exc:
        raise HTTPException(502, f"LLM response could not be used: {exc}")

    try:
        log_llm_prompt(
            user_id=None,
            touchpoint=EDUCATION_PROGRAMME_LLM_TOUCHPOINT,
            prompt_text=prompt,
            model=resolved_model,
            duration_ms=duration_ms,
            response_preview=content[:4000],
            context_meta={
                "programme_name": programme_context["programme_name"],
                "programme_code": programme_context["programme_code"],
                "pillar_key": pillar_key,
                "programme_concept_key": concept_key,
                "requested_days": requested_days,
                "model_override": model_override,
            },
            prompt_variant="admin_programme_editor",
            task_label=(brief or f"Regenerate {concept_label or concept_key} programme")[:160],
            prompt_blocks={
                "context": json.dumps(programme_context, ensure_ascii=False, default=str),
                "task": brief,
            },
            block_order=["context", "task"],
        )
    except Exception:
        pass

    return {"ok": True, "model": resolved_model, "programme": generated_programme}


@admin.post("/education-programmes/day/llm-generate")
async def generate_education_programme_day_with_llm(request: Request):
    ensure_education_plan_schema()
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(400, f"Invalid JSON payload: {exc}")
    if not isinstance(payload, dict):
        raise HTTPException(400, "JSON payload must be an object")

    brief = str(payload.get("brief") or "").strip()
    if not brief:
        raise HTTPException(400, "brief is required")
    existing_day = payload.get("existing_day") if isinstance(payload.get("existing_day"), dict) else {}
    try:
        day_index = int(payload.get("day_index") or existing_day.get("day_index") or 1)
    except Exception:
        day_index = 1
    raw_existing_variants = existing_day.get("variants") if isinstance(existing_day.get("variants"), list) else []
    existing_level = ""
    if raw_existing_variants and isinstance(raw_existing_variants[0], dict):
        existing_level = str(raw_existing_variants[0].get("level") or "").strip().lower()
    if existing_level not in {"support", "foundation", "build", "perform"}:
        existing_level = "build"

    model_override = _normalize_model_override(str(payload.get("model_override") or ""))
    concept_key = str(payload.get("programme_concept_key") or existing_day.get("concept_key") or "").strip().lower()
    concept_label = str(payload.get("programme_concept_label") or existing_day.get("concept_label") or "").strip()
    programme_context = {
        "programme_name": str(payload.get("programme_name") or "").strip(),
        "programme_code": str(payload.get("programme_code") or "").strip(),
        "pillar_key": str(payload.get("pillar_key") or "").strip().lower(),
        "programme_concept_key": concept_key,
        "programme_concept_label": concept_label,
        "selected_day_index": day_index,
        "existing_day": _compact_education_day_for_llm(existing_day),
        "task_description": brief,
    }
    output_schema = {
        "day_index": day_index,
        "lesson_goal": "string",
        "default_title": "string",
        "default_summary": "string",
        "variants": [
            {
                "level": existing_level,
                "title": "string",
                "summary": "string",
                "script": "string",
                "action_prompt": "string",
                "poster_url": "",
                "avatar_character": "",
                "avatar_style": "",
                "avatar_voice": "",
                "takeaway_default": "string",
                "takeaway_if_low_score": "string",
                "takeaway_if_high_score": "string",
                "is_active": True,
                "quiz": {
                    "pass_score_pct": 66.67,
                    "questions": [
                        {
                            "question_order": 1,
                            "question_text": "string",
                            "answer_type": "single_choice",
                            "options_json": ["string", "string", "string", "string"],
                            "correct_answer_json": "one exact option string",
                            "explanation": "string",
                        }
                    ],
                },
            }
        ],
    }
    prompt = (
        "You are creating a HealthSense education programme day for the admin editor.\n"
        "Return a single valid JSON object only. Do not use markdown, code fences, comments, or prose outside JSON.\n\n"
        "Task:\n"
        "- Regenerate the selected day entirely from the task_description.\n"
        "- Use the existing day only for continuity with the programme; replace the lesson goal, title, summary, script, daily action, takeaways, and quiz.\n"
        "- Generate one active variant unless the task_description explicitly asks for multiple variants.\n"
        f"- Use the existing level '{existing_level}' unless the task_description explicitly asks for another level.\n"
        "- Include exactly 3 quiz questions for each variant.\n"
        "- Use answer_type='single_choice' unless the task_description clearly requires boolean or multi_choice.\n"
        "- For single_choice questions, options_json must be an array of 4 short answer options.\n"
        "- correct_answer_json must exactly match the correct option string for single_choice questions.\n"
        "- Leave video_url, avatar_status, avatar_job_id, avatar_error, avatar_generated_at, avatar_source, and avatar_summary_url absent or empty.\n"
        "- Use UK English, clear coaching language, and avoid diagnosis or medical claims.\n\n"
        "CONTEXT_JSON:\n"
        f"{json.dumps(programme_context, ensure_ascii=False, default=str)}\n\n"
        "OUTPUT_SCHEMA_JSON:\n"
        f"{json.dumps(output_schema, ensure_ascii=False)}\n"
    )

    try:
        from . import llm as shared_llm

        t0 = time.perf_counter()
        resolved_model = shared_llm.resolve_model_name_for_touchpoint(
            touchpoint=EDUCATION_DAY_LLM_TOUCHPOINT,
            model_override=model_override,
        )
        client = shared_llm.get_llm_client(
            touchpoint=EDUCATION_DAY_LLM_TOUCHPOINT,
            model_override=model_override,
        )
        response = client.invoke(prompt)
        duration_ms = int((time.perf_counter() - t0) * 1000)
        content = _coerce_llm_content(getattr(response, "content", None)).strip()
    except Exception as exc:
        raise HTTPException(500, f"LLM day generation failed: {exc}")

    try:
        raw_generated = _extract_llm_json_object(content)
        generated_day = _normalise_generated_education_day(
            raw_generated,
            day_index=day_index,
            concept_key=concept_key,
            concept_label=concept_label,
            existing_level=existing_level,
        )
    except Exception as exc:
        raise HTTPException(502, f"LLM response could not be used: {exc}")

    try:
        log_llm_prompt(
            user_id=None,
            touchpoint=EDUCATION_DAY_LLM_TOUCHPOINT,
            prompt_text=prompt,
            model=resolved_model,
            duration_ms=duration_ms,
            response_preview=content[:4000],
            context_meta={
                "programme_name": programme_context["programme_name"],
                "programme_code": programme_context["programme_code"],
                "pillar_key": programme_context["pillar_key"],
                "programme_concept_key": concept_key,
                "day_index": day_index,
                "model_override": model_override,
            },
            prompt_variant="admin_editor",
            task_label=brief[:160],
            prompt_blocks={
                "context": json.dumps(programme_context, ensure_ascii=False, default=str),
                "task": brief,
            },
            block_order=["context", "task"],
        )
    except Exception:
        pass

    return {"ok": True, "model": resolved_model, "day": generated_day}


@admin.get("/education-programmes/edit", response_class=HTMLResponse)
def edit_education_programme(id: int | None = None):
    ensure_education_plan_schema()
    row = None
    with SessionLocal() as s:
        if id is not None:
            row = s.get(EducationProgramme, id)
            if row is None:
                raise HTTPException(404, "Education programme not found")
        programme_payload = _education_programme_payload(s, row)
        concept_options = _education_editor_options(s)
    try:
        from . import llm as shared_llm
        default_day_llm_model = shared_llm.resolve_model_name_for_touchpoint(EDUCATION_DAY_LLM_TOUCHPOINT)
        default_programme_llm_model = shared_llm.resolve_model_name_for_touchpoint(EDUCATION_PROGRAMME_LLM_TOUCHPOINT)
    except Exception:
        default_day_llm_model = "default"
        default_programme_llm_model = "default"
    day_llm_model_options_html = _llm_model_options_html(default_day_llm_model)
    programme_llm_model_options_html = _llm_model_options_html(default_programme_llm_model)
    title = "Edit Education Programme" if row is not None else "Create Education Programme"
    title += f": {html.escape(str(getattr(row, 'name', '') or '').strip())}" if row is not None else ""
    current_pillar = str(programme_payload.get("pillar_key") or "").strip().lower()
    current_programme_concept = str(programme_payload.get("programme_concept_key") or "").strip().lower()
    current_programme_concept_value = (
        f"{current_pillar}::{current_programme_concept}"
        if current_pillar and current_programme_concept
        else current_programme_concept
    )
    structure_seed = {"days": programme_payload.get("days") or []}
    delete_form_html = ""
    avatar_bulk_html = ""
    if row is not None:
        programme_id = html.escape(str(programme_payload.get("id") or ""))
        avatar_bulk_html = (
            "<div class='programme-video-actions' style='margin-top:12px; padding-top:12px; border-top:1px solid var(--border);'>"
            "<h3 class='section-title'>Avatar videos</h3>"
            "<p class='help'>Generate and review lesson avatar videos from this programme header. Existing videos are skipped unless you choose regenerate.</p>"
            "<div class='stack'>"
            f"<form method='post' action='/admin/education-programmes/{programme_id}/avatar/generate' "
            "onsubmit=\"return confirm('Start missing avatar videos for every active lesson in this programme?');\">"
            "<button type='submit' class='secondary'>Generate missing videos</button>"
            "</form>"
            f"<form method='post' action='/admin/education-programmes/{programme_id}/avatar/refresh' "
            "onsubmit=\"return confirm('Refresh all pending avatar jobs for this programme?');\">"
            "<button type='submit' class='secondary'>Refresh pending videos</button>"
            "</form>"
            f"<form method='post' action='/admin/education-programmes/{programme_id}/avatar/generate' "
            "onsubmit=\"return confirm('Regenerate avatar videos for every active lesson in this programme? This will replace existing generated jobs when the new videos are ready.');\">"
            "<input type='hidden' name='regenerate' value='1' />"
            "<button type='submit' class='danger'>Regenerate all videos</button>"
            "</form>"
            "<button type='button' class='secondary' id='review-selected-day-video-button'>Review selected day video</button>"
            "</div>"
            "</div>"
        )
        delete_form_html = (
            "<form method='post' action='/admin/education-programmes/delete' class='card' style='margin-top:12px;' "
            "onsubmit=\"return confirm('Delete this education programme? This cannot be undone.');\">"
            "<h3 class='section-title'>Delete programme</h3>"
            "<p class='help'>Deletes this programme only if no user education plans are attached. If user plans exist, the programme is deactivated instead.</p>"
            f"<input type='hidden' name='id' value='{html.escape(str(programme_payload.get('id') or ''))}' />"
            f"<input type='hidden' name='expected_code' value='{html.escape(str(programme_payload.get('code') or ''))}' />"
            "<button type='submit' class='danger'>Delete Programme</button>"
            "</form>"
        )
    body = f"""
    <h2>{title}</h2>
    {_build_version_label()}
    <div class='card' style='margin-bottom:12px;'>
      <p class='help'>Use this editor to define a concept-based lesson module with levelled video variants, the 3-question quiz, and the takeaway text shown after quiz completion. The user is routed into a programme by concept, and the programme length is derived from the days you configure here.</p>
      {avatar_bulk_html}
    </div>
    <form method="post" action="/admin/education-programmes/save" id="education-programme-form">
      <input type="hidden" name="id" value="{html.escape(str(programme_payload.get('id') or ''))}" />
      <input type="hidden" name="structure_json" id="structure_json" value="" />
      <div class='card' style='margin-bottom:12px;'>
        <div class='grid-2'>
          <div class='field'>
            <label>Programme concept<br/>
              <select name="programme_concept_key" id="programme_concept_key" data-selected="{html.escape(current_programme_concept_value)}">
                <option value="">Select concept</option>
              </select>
            </label>
          </div>
          <div class='field'>
            <label>Pillar (derived)<br/>
              <input type="text" id="programme_pillar_display" value="{html.escape(current_pillar.title() if current_pillar else '')}" readonly />
            </label>
          </div>
          <div class='field'>
            <label>Programme code<br/>
              <input type="text" name="code" value="{html.escape(str(programme_payload.get('code') or ''))}" required />
            </label>
          </div>
          <div class='field'>
            <label>Programme name<br/>
              <input type="text" name="name" value="{html.escape(str(programme_payload.get('name') or ''))}" required />
            </label>
          </div>
          <div class='field'>
            <label>Programme concept label<br/>
              <input type="text" name="programme_concept_label" id="programme_concept_label" value="{html.escape(str(programme_payload.get('programme_concept_label') or ''))}" />
            </label>
          </div>
        </div>
        <div class='field'>
          <label><input type="checkbox" name="is_active" {"checked" if bool(programme_payload.get("is_active", True)) else ""} /> Active programme</label>
        </div>
      </div>

      <details class="programme-day-llm" id="programme-llm" style="margin-bottom:12px;">
        <summary>Regenerate concept programme with LLM</summary>
        <p class="help">Draft the full programme for the selected concept using the nominated model. This replaces the editor draft only; click Save Programme to persist it.</p>
        <div class="grid-2">
          <div class="field">
            <label>Model<br/>
              <select id="programme-llm-model">
                {programme_llm_model_options_html}
              </select>
            </label>
          </div>
          <div class="field">
            <label>Number of days<br/>
              <input type="number" id="programme-llm-days" min="1" max="31" value="{html.escape(str(programme_payload.get('duration_days') or len(programme_payload.get('days') or []) or 7))}" />
            </label>
          </div>
        </div>
        <div class="field">
          <label>Task description<br/>
            <textarea id="programme-llm-brief" rows="4" placeholder="Example: Regenerate a 7-day concept programme that builds practical understanding, one daily action, and a 3-question quiz each day."></textarea>
          </label>
        </div>
        <div class="stack">
          <button type="button" id="generate-programme-llm">Generate concept programme draft</button>
          <span class="subtle programme-day-llm-status" id="programme-llm-status"></span>
        </div>
      </details>

      <div class="programme-days-shell">
        <div class="card">
          <div class='stack' style='justify-content:space-between; margin-bottom:12px;'>
            <div>
              <h3 class='section-title'>Programme days</h3>
              <div class='subtle'>Review the programme as a day list. Select a day to open its edit card.</div>
            </div>
            <button type="button" class="secondary" id="add-day-button">Add day</button>
          </div>
          <div id="programme-days-summary" class="programme-day-list"></div>
        </div>
        <div class="card programme-day-detail-card" id="programme-day-detail-card">
          <div class="stack" style="justify-content:space-between;">
            <div>
              <h3 class="section-title" id="programme-day-detail-title">Selected day</h3>
              <div class="subtle" id="programme-day-detail-meta"></div>
            </div>
            <button type="button" class="secondary" id="programme-day-list-focus">Back to days</button>
          </div>
          <details class="programme-day-llm" id="programme-day-llm">
            <summary>Regenerate selected day with LLM</summary>
            <p class="help">Use a task description to draft the whole selected day again, including the lesson script, daily action, takeaways, and quiz questions. Review the draft in the editor, then save the programme.</p>
            <div class="grid-2">
              <div class="field">
                <label>Model<br/>
                  <select id="day-llm-model">
                    {day_llm_model_options_html}
                  </select>
                </label>
              </div>
            </div>
            <div class="field">
              <label>Task description<br/>
                <textarea id="day-llm-brief" rows="4" placeholder="Example: Regenerate this day around sleep pressure and a consistent wake time for a build-level recovery programme."></textarea>
              </label>
            </div>
            <div class="stack">
              <button type="button" id="generate-selected-day-llm">Generate day draft</button>
              <span class="subtle programme-day-llm-status" id="day-llm-status"></span>
            </div>
          </details>
          <div id="programme-days-root" class="programme-day-editor"></div>
        </div>
      </div>

      <div class='actions stack' style='margin-top:16px;'>
        <button type="submit">Save Programme</button>
        <a class='button-link' href="/admin/education-programmes">Back to list</a>
      </div>
    </form>

    {delete_form_html}

    <div id="avatar-review-modal" hidden style="position:fixed; inset:0; z-index:999; background:rgba(15,23,42,0.68); padding:20px;">
      <div style="max-width:900px; margin:40px auto; background:#fff; border-radius:8px; padding:16px; box-shadow:0 18px 48px rgba(15,23,42,0.25);">
        <div class="stack" style="justify-content:space-between; margin-bottom:12px;">
          <h3 id="avatar-review-title" class="section-title" style="margin:0;">Review avatar</h3>
          <button type="button" class="secondary" id="avatar-review-close">Close</button>
        </div>
        <video id="avatar-review-video" controls playsinline preload="metadata" style="width:100%; max-height:70vh; background:#000; border-radius:8px;"></video>
        <div class="stack" style="justify-content:space-between; margin-top:10px;">
          <a id="avatar-review-open-link" class="button-link" href="#" target="_blank" rel="noopener">Open video in new tab</a>
          <span id="avatar-review-status" class="subtle"></span>
        </div>
      </div>
    </div>

    <script id="education-programme-seed" type="application/json">{_json_script_content(structure_seed)}</script>
    <script id="education-concept-options" type="application/json">{_json_script_content(concept_options)}</script>
    <script>
      (function() {{
        const seed = JSON.parse(document.getElementById('education-programme-seed').textContent || '{{}}');
        const conceptOptions = JSON.parse(document.getElementById('education-concept-options').textContent || '[]');
        const root = document.getElementById('programme-days-root');
        const summaryRoot = document.getElementById('programme-days-summary');
        const dayDetailCard = document.getElementById('programme-day-detail-card');
        const dayDetailTitle = document.getElementById('programme-day-detail-title');
        const dayDetailMeta = document.getElementById('programme-day-detail-meta');
        const dayListFocusButton = document.getElementById('programme-day-list-focus');
        const dayLlmBrief = document.getElementById('day-llm-brief');
        const dayLlmModel = document.getElementById('day-llm-model');
        const dayLlmButton = document.getElementById('generate-selected-day-llm');
        const dayLlmStatus = document.getElementById('day-llm-status');
        const programmeLlmBrief = document.getElementById('programme-llm-brief');
        const programmeLlmModel = document.getElementById('programme-llm-model');
        const programmeLlmDays = document.getElementById('programme-llm-days');
        const programmeLlmButton = document.getElementById('generate-programme-llm');
        const programmeLlmStatus = document.getElementById('programme-llm-status');
        const form = document.getElementById('education-programme-form');
        const structureField = document.getElementById('structure_json');
        const programmeConceptInput = document.getElementById('programme_concept_key');
        const programmeConceptLabelInput = document.getElementById('programme_concept_label');
        const pillarDisplayInput = document.getElementById('programme_pillar_display');
        const reviewSelectedDayVideoButton = document.getElementById('review-selected-day-video-button');
        const avatarReviewModal = document.getElementById('avatar-review-modal');
        const avatarReviewVideo = document.getElementById('avatar-review-video');
        const avatarReviewTitle = document.getElementById('avatar-review-title');
        const avatarReviewStatus = document.getElementById('avatar-review-status');
        const avatarReviewOpenLink = document.getElementById('avatar-review-open-link');
        const avatarReviewClose = document.getElementById('avatar-review-close');
        let selectedDayPosition = 0;

        function escapeHtml(value) {{
          return String(value ?? '')
            .replaceAll('&', '&amp;')
            .replaceAll('<', '&lt;')
            .replaceAll('>', '&gt;')
            .replaceAll('"', '&quot;');
        }}

        function normaliseJsonText(value, fallback) {{
          if (value === undefined || value === null || value === '') return JSON.stringify(fallback);
          try {{
            return JSON.stringify(typeof value === 'string' ? JSON.parse(value) : value);
          }} catch (_err) {{
            return typeof value === 'string' ? value : JSON.stringify(fallback);
          }}
        }}

        function emptyQuestion(order) {{
          return {{
            id: null,
            question_order: order,
            question_text: '',
            answer_type: 'single_choice',
            options_json: [''],
            correct_answer_json: '',
            explanation: '',
          }};
        }}

        function emptyVariant() {{
          return {{
            id: null,
            level: 'build',
            title: '',
            summary: '',
            script: '',
            action_prompt: '',
            video_url: '',
            poster_url: '',
            avatar_character: '',
            avatar_style: '',
            avatar_voice: '',
            avatar_status: '',
            avatar_job_id: '',
            avatar_error: '',
            avatar_generated_at: '',
            avatar_source: '',
            avatar_summary_url: '',
            content_item_id: null,
            reset_avatar_media: false,
            takeaway_default: '',
            takeaway_if_low_score: '',
            takeaway_if_high_score: '',
            is_active: true,
            quiz: {{
              id: null,
              pass_score_pct: '',
              questions: [emptyQuestion(1), emptyQuestion(2), emptyQuestion(3)],
            }},
          }};
        }}

        function emptyDay(dayIndex) {{
          return {{
            id: null,
            day_index: dayIndex,
            concept_key: String(programmeConceptInput?.value || '').trim().toLowerCase(),
            concept_label: String(programmeConceptLabelInput?.value || '').trim(),
            lesson_goal: '',
            default_title: '',
            default_summary: '',
            variants: [emptyVariant()],
          }};
        }}

        function titleCasePillar(value) {{
          const token = String(value || '').trim().toLowerCase();
          return token ? token.charAt(0).toUpperCase() + token.slice(1) : '';
        }}

        function splitProgrammeConceptValue(value) {{
          const raw = String(value || '').trim().toLowerCase();
          if (!raw) return {{ pillarKey: '', conceptKey: '' }};
          const parts = raw.split('::', 2);
          if (parts.length === 2) {{
            return {{
              pillarKey: String(parts[0] || '').trim().toLowerCase(),
              conceptKey: String(parts[1] || '').trim().toLowerCase(),
            }};
          }}
          return {{ pillarKey: '', conceptKey: raw }};
        }}

        function selectedProgrammeConceptValue() {{
          return String(programmeConceptInput?.value || '').trim().toLowerCase();
        }}

        function selectedProgrammeConceptKey() {{
          return splitProgrammeConceptValue(selectedProgrammeConceptValue()).conceptKey;
        }}

        function selectedProgrammeConcept() {{
          const selection = splitProgrammeConceptValue(selectedProgrammeConceptValue());
          return conceptOptions.find((item) => {{
            const code = String(item.code || '').toLowerCase();
            const pillar = String(item.pillar_key || '').toLowerCase();
            if (!selection.conceptKey) return false;
            if (selection.pillarKey) return code === selection.conceptKey && pillar === selection.pillarKey;
            return code === selection.conceptKey;
          }}) || null;
        }}

        function selectedProgrammePillar() {{
          const selected = splitProgrammeConceptValue(selectedProgrammeConceptValue());
          return String(selectedProgrammeConcept()?.pillar_key || selected.pillarKey || '').trim().toLowerCase();
        }}

        function resolvedProgrammeConceptLabel() {{
          const typed = String(programmeConceptLabelInput?.value || '').trim();
          if (typed) return typed;
          return String(selectedProgrammeConcept()?.name || '').trim();
        }}

        function refreshProgrammeConceptChoices() {{
          if (!programmeConceptInput) return;
          const selected = String(programmeConceptInput.value || programmeConceptInput.dataset.selected || '').trim().toLowerCase();
          const options = conceptOptions;
          programmeConceptInput.innerHTML = "<option value=''>Select concept</option>" + options.map((item) => {{
            const value = `${{String(item.pillar_key || '').toLowerCase()}}::${{String(item.code || '').toLowerCase()}}`;
            const isSelected = value === selected ? 'selected' : '';
            const pillarLabel = titleCasePillar(item.pillar_key || '');
            return `<option value="${{escapeHtml(value)}}" ${{isSelected}}>${{escapeHtml(pillarLabel ? `${{pillarLabel}} · ${{item.name || item.code}}` : (item.name || item.code))}}</option>`;
          }}).join('');
          const stillValid = options.some((item) => `${{String(item.pillar_key || '').toLowerCase()}}::${{String(item.code || '').toLowerCase()}}` === selected);
          if (!stillValid) {{
            programmeConceptInput.value = '';
          }}
          programmeConceptInput.dataset.selected = String(programmeConceptInput.value || '').trim().toLowerCase();
          if (pillarDisplayInput) {{
            pillarDisplayInput.value = titleCasePillar(selectedProgrammePillar());
          }}
        }}

        function dayConceptLabel(day) {{
          return resolvedProgrammeConceptLabel() || String(day?.concept_label || '').trim();
        }}

        function currentDayElements() {{
          return Array.from(root.querySelectorAll(':scope > .js-day'));
        }}

        function collectAllDaysFromDom() {{
          return currentDayElements().map((dayEl) => collectDayData(dayEl));
        }}

        function selectedDayElement() {{
          return currentDayElements()[selectedDayPosition] || null;
        }}

        function dayVariantSummary(day) {{
          const variants = Array.isArray(day.variants) && day.variants.length ? day.variants : [];
          const activeVariants = variants.filter((variant) => variant.is_active !== false);
          const readyCount = variants.filter((variant) => String(variant.video_url || '').trim()).length;
          const pendingCount = variants.filter((variant) => {{
            const status = String(variant.avatar_status || '').trim().toLowerCase();
            const jobId = String(variant.avatar_job_id || '').trim();
            return jobId && !String(variant.video_url || '').trim() && !['failed', 'cancelled', 'canceled'].includes(status);
          }}).length;
          const failedCount = variants.filter((variant) => String(variant.avatar_status || '').trim().toLowerCase() === 'failed').length;
          if (failedCount) return {{ label: `${{failedCount}} failed`, tone: 'failed' }};
          if (pendingCount) return {{ label: `${{pendingCount}} pending`, tone: 'pending' }};
          if (readyCount) return {{ label: `${{readyCount}} video${{readyCount === 1 ? '' : 's'}} ready`, tone: 'ready' }};
          if (activeVariants.length) return {{ label: 'needs video', tone: 'needs-video' }};
          return {{ label: 'inactive', tone: 'needs-video' }};
        }}

        function renderDaySummaries() {{
          if (!summaryRoot) return;
          const dayEls = currentDayElements();
          if (!dayEls.length) {{
            selectedDayPosition = 0;
            summaryRoot.innerHTML = '<div class="programme-day-summary-empty">No days configured yet.</div>';
            if (dayDetailCard) dayDetailCard.hidden = true;
            return;
          }}
          if (dayDetailCard) dayDetailCard.hidden = false;
          selectedDayPosition = Math.min(Math.max(0, selectedDayPosition), dayEls.length - 1);
          const days = dayEls.map((dayEl) => collectDayData(dayEl));
          const selectedDay = days[selectedDayPosition] || days[0];
          if (dayDetailTitle && selectedDay) {{
            const title = String(selectedDay.default_title || selectedDay.variants?.[0]?.title || '').trim() || 'Untitled lesson';
            dayDetailTitle.textContent = `Day ${{selectedDay.day_index || selectedDayPosition + 1}} · ${{title}}`;
          }}
          if (dayDetailMeta && selectedDay) {{
            const variantCount = Array.isArray(selectedDay.variants) ? selectedDay.variants.length : 0;
            const concept = String(selectedDay.concept_label || resolvedProgrammeConceptLabel() || '').trim();
            dayDetailMeta.textContent = [concept, `${{variantCount}} variant${{variantCount === 1 ? '' : 's'}}`].filter(Boolean).join(' · ');
          }}
          summaryRoot.innerHTML = days.map((day, position) => {{
            const variants = Array.isArray(day.variants) ? day.variants : [];
            const levels = variants.map((variant) => String(variant.level || '').trim()).filter(Boolean).join(', ') || 'no variants';
            const title = String(day.default_title || variants[0]?.title || '').trim() || 'Untitled lesson';
            const quizCount = variants.reduce((total, variant) => {{
              const questions = Array.isArray(variant.quiz?.questions) ? variant.quiz.questions : [];
              return total + questions.length;
            }}, 0);
            const status = dayVariantSummary(day);
            return `
              <button type="button" class="programme-day-summary js-select-day ${{position === selectedDayPosition ? 'is-selected' : ''}}" data-day-position="${{position}}">
                <span class="programme-day-summary-index">Day ${{escapeHtml(day.day_index || position + 1)}}</span>
                <span>
                  <span class="programme-day-summary-title">${{escapeHtml(title)}}</span>
                  <span class="programme-day-summary-meta">${{escapeHtml(levels)}} · ${{quizCount}} quiz question${{quizCount === 1 ? '' : 's'}}</span>
                </span>
                <span class="programme-day-summary-status ${{escapeHtml(status.tone)}}">${{escapeHtml(status.label)}}</span>
              </button>
            `;
          }}).join('');
          dayEls.forEach((dayEl, position) => {{
            dayEl.hidden = position !== selectedDayPosition;
          }});
        }}

        function selectDay(position) {{
          const dayEls = currentDayElements();
          if (!dayEls.length) {{
            selectedDayPosition = 0;
            renderDaySummaries();
            return;
          }}
          selectedDayPosition = Math.min(Math.max(0, Number(position) || 0), dayEls.length - 1);
          renderDaySummaries();
          dayDetailCard?.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }}

        function renderQuestion(question) {{
          return `
            <div class="quiz-question js-question">
              <input type="hidden" class="js-question-id" value="${{escapeHtml(question.id || '')}}" />
              <div class="stack" style="justify-content:space-between;">
                <strong>Question</strong>
                <button type="button" class="danger js-remove-question">Remove</button>
              </div>
              <div class="grid-2" style="margin-top:10px;">
                <div class="field">
                  <label>Order<br/><input type="number" class="js-question-order" min="1" max="3" value="${{escapeHtml(question.question_order || 1)}}" /></label>
                </div>
                <div class="field">
                  <label>Answer type<br/>
                    <select class="js-question-answer-type">
                      <option value="single_choice" ${{String(question.answer_type || 'single_choice') === 'single_choice' ? 'selected' : ''}}>single_choice</option>
                      <option value="multi_choice" ${{String(question.answer_type || '') === 'multi_choice' ? 'selected' : ''}}>multi_choice</option>
                      <option value="boolean" ${{String(question.answer_type || '') === 'boolean' ? 'selected' : ''}}>boolean</option>
                    </select>
                  </label>
                </div>
              </div>
              <div class="field">
                <label>Question text<br/><textarea class="js-question-text" rows="2">${{escapeHtml(question.question_text || '')}}</textarea></label>
              </div>
              <div class="grid-2">
                <div class="field">
                  <label>Options JSON<br/><textarea class="js-question-options" rows="3">${{escapeHtml(normaliseJsonText(question.options_json, []))}}</textarea></label>
                </div>
                <div class="field">
                  <label>Correct answer JSON<br/><textarea class="js-question-correct" rows="3">${{escapeHtml(normaliseJsonText(question.correct_answer_json, ''))}}</textarea></label>
                </div>
              </div>
              <div class="field">
                <label>Explanation<br/><textarea class="js-question-explanation" rows="2">${{escapeHtml(question.explanation || '')}}</textarea></label>
              </div>
            </div>
          `;
        }}

        function renderVariant(day, variant) {{
          const quiz = variant.quiz || {{ id: null, pass_score_pct: '', questions: [] }};
          const questions = Array.isArray(quiz.questions) && quiz.questions.length
            ? quiz.questions
            : [emptyQuestion(1), emptyQuestion(2), emptyQuestion(3)];
          const variantId = String(variant.id || '').trim();
          const avatarStatus = String(variant.avatar_status || '').trim();
          return `
            <div class="lesson-variant js-variant">
              <input type="hidden" class="js-variant-id" value="${{escapeHtml(variant.id || '')}}" />
              <input type="hidden" class="js-variant-reset-avatar-media" value="${{variant.reset_avatar_media ? '1' : ''}}" />
              <div class="stack" style="justify-content:space-between;">
                <strong>Lesson Variant</strong>
                <div class="stack">
                  ${{variantId ? `<span class="subtle">Use the programme header to generate, refresh, or review videos.</span>` : `<span class="subtle">Save this variant before generating avatar video.</span>`}}
                  <button type="button" class="danger js-remove-variant">Remove variant</button>
                </div>
              </div>
              <div class="grid-3" style="margin-top:10px;">
                <div class="field">
                  <label>Level<br/>
                    <select class="js-variant-level">
                      <option value="support" ${{String(variant.level || '') === 'support' ? 'selected' : ''}}>support</option>
                      <option value="foundation" ${{String(variant.level || '') === 'foundation' ? 'selected' : ''}}>foundation</option>
                      <option value="build" ${{String(variant.level || 'build') === 'build' ? 'selected' : ''}}>build</option>
                      <option value="perform" ${{String(variant.level || '') === 'perform' ? 'selected' : ''}}>perform</option>
                    </select>
                  </label>
                </div>
                <div class="field">
                  <label><input type="checkbox" class="js-variant-active" ${{variant.is_active === false ? '' : 'checked'}} /> Active</label>
                </div>
                <div class="field">
                  <label>Avatar status<br/><input type="text" class="js-variant-avatar-status" value="${{escapeHtml(avatarStatus)}}" readonly /></label>
                </div>
              </div>

              <div class="card" style="margin-top:10px; padding:12px 14px;">
                <h4 class="section-title">Education lesson content</h4>
                <div class="grid-2">
                  <div class="field">
                    <label>Lesson title<br/><input type="text" class="js-variant-title" value="${{escapeHtml(variant.title || '')}}" /></label>
                  </div>
                  <div class="field">
                    <label>Lesson summary<br/><textarea class="js-variant-summary" rows="2">${{escapeHtml(variant.summary || '')}}</textarea></label>
                  </div>
                </div>
                <div class="field">
                  <label>Avatar/video script<br/><textarea class="js-variant-script" rows="8">${{escapeHtml(variant.script || '')}}</textarea></label>
                </div>
                <div class="field">
                  <label>Daily action prompt<br/><textarea class="js-variant-action-prompt" rows="2">${{escapeHtml(variant.action_prompt || '')}}</textarea></label>
                </div>
              </div>

              <div class="card" style="margin-top:10px; padding:12px 14px;">
                <h4 class="section-title">Avatar video</h4>
                <div class="grid-2">
                  <div class="field">
                    <label>Video URL<br/><input type="text" class="js-variant-video-url" value="${{escapeHtml(variant.video_url || '')}}" /></label>
                  </div>
                  <div class="field">
                    <label>Poster URL<br/><input type="text" class="js-variant-poster-url" value="${{escapeHtml(variant.poster_url || '')}}" /></label>
                  </div>
                </div>
                <div class="grid-3">
                  <div class="field">
                    <label>Character<br/><input type="text" class="js-variant-avatar-character" value="${{escapeHtml(variant.avatar_character || '')}}" placeholder="lisa" /></label>
                  </div>
                  <div class="field">
                    <label>Style<br/><input type="text" class="js-variant-avatar-style" value="${{escapeHtml(variant.avatar_style || '')}}" placeholder="graceful-sitting" /></label>
                  </div>
                  <div class="field">
                    <label>Voice<br/><input type="text" class="js-variant-avatar-voice" value="${{escapeHtml(variant.avatar_voice || '')}}" placeholder="en-GB-SoniaNeural" /></label>
                  </div>
                </div>
                <div class="grid-3">
                  <div class="field">
                    <label>Avatar job ID<br/><input type="text" class="js-variant-avatar-job-id" value="${{escapeHtml(variant.avatar_job_id || '')}}" readonly /></label>
                  </div>
                  <div class="field">
                    <label>Generated at<br/><input type="text" class="js-variant-avatar-generated-at" value="${{escapeHtml(variant.avatar_generated_at || '')}}" readonly /></label>
                  </div>
                  <div class="field">
                    <label>Source<br/><input type="text" class="js-variant-avatar-source" value="${{escapeHtml(variant.avatar_source || '')}}" readonly /></label>
                  </div>
                </div>
                <div class="grid-2">
                  <div class="field">
                    <label>Summary URL<br/><input type="text" class="js-variant-avatar-summary-url" value="${{escapeHtml(variant.avatar_summary_url || '')}}" readonly /></label>
                  </div>
                  <div class="field">
                    <label>Error<br/><textarea class="js-variant-avatar-error" rows="2" readonly>${{escapeHtml(variant.avatar_error || '')}}</textarea></label>
                  </div>
                </div>
              </div>

              <div class="grid-3">
                <div class="field">
                  <label>Takeaway default<br/><textarea class="js-variant-takeaway-default" rows="3">${{escapeHtml(variant.takeaway_default || '')}}</textarea></label>
                </div>
                <div class="field">
                  <label>Takeaway if low score<br/><textarea class="js-variant-takeaway-low" rows="3">${{escapeHtml(variant.takeaway_if_low_score || '')}}</textarea></label>
                </div>
                <div class="field">
                  <label>Takeaway if high score<br/><textarea class="js-variant-takeaway-high" rows="3">${{escapeHtml(variant.takeaway_if_high_score || '')}}</textarea></label>
                </div>
              </div>
              <div class="card" style="margin-top:10px; padding:12px 14px;">
                <input type="hidden" class="js-quiz-id" value="${{escapeHtml(quiz.id || '')}}" />
                <div class="stack" style="justify-content:space-between;">
                  <strong>Quiz</strong>
                  <button type="button" class="secondary js-add-question">Add question</button>
                </div>
                <div class="field" style="margin-top:10px;">
                  <label>Pass score %<br/><input type="number" class="js-quiz-pass-score" min="0" max="100" step="0.01" value="${{escapeHtml(quiz.pass_score_pct ?? '')}}" /></label>
                </div>
                <div class="js-questions-root">
                  ${{questions.map((question) => renderQuestion(question)).join('')}}
                </div>
              </div>
            </div>
          `;
        }}

        function renderDay(day) {{
          const variants = Array.isArray(day.variants) && day.variants.length ? day.variants : [emptyVariant()];
          const conceptLabel = dayConceptLabel(day);
          return `
            <div class="programme-day js-day">
              <input type="hidden" class="js-day-id" value="${{escapeHtml(day.id || '')}}" />
              <div class="stack" style="justify-content:space-between;">
                <strong>Programme Day</strong>
                <button type="button" class="danger js-remove-day">Remove day</button>
              </div>
              <div class="grid-3" style="margin-top:10px;">
                <div class="field">
                  <label>Day index<br/><input type="number" class="js-day-index" min="1" max="90" value="${{escapeHtml(day.day_index || '')}}" /></label>
                </div>
                <div class="field">
                  <label>Concept<br/><input type="text" value="${{escapeHtml(conceptLabel)}}" readonly /></label>
                </div>
              </div>
              <div class="field">
                <label>Lesson goal<br/><textarea class="js-day-lesson-goal" rows="2">${{escapeHtml(day.lesson_goal || '')}}</textarea></label>
              </div>
              <div class="grid-2">
                <div class="field">
                  <label>Default title<br/><input type="text" class="js-day-default-title" value="${{escapeHtml(day.default_title || '')}}" /></label>
                </div>
                <div class="field">
                  <label>Default summary<br/><textarea class="js-day-default-summary" rows="2">${{escapeHtml(day.default_summary || '')}}</textarea></label>
                </div>
              </div>
              <div class="stack" style="justify-content:space-between; margin-top:10px;">
                <strong>Variants</strong>
                <button type="button" class="secondary js-add-variant">Add variant</button>
              </div>
              <div class="js-variants-root">
                ${{variants.map((variant) => renderVariant(day, variant)).join('')}}
              </div>
            </div>
          `;
        }}

        function collectDayData(dayEl) {{
          const variantEls = Array.from(dayEl.querySelectorAll(':scope .js-variants-root > .js-variant'));
          const conceptKey = selectedProgrammeConceptKey();
          return {{
            id: dayEl.querySelector('.js-day-id')?.value ? Number(dayEl.querySelector('.js-day-id').value) : null,
            day_index: Number(dayEl.querySelector('.js-day-index')?.value || 0),
            concept_key: conceptKey,
            concept_label: resolvedProgrammeConceptLabel(),
            lesson_goal: String(dayEl.querySelector('.js-day-lesson-goal')?.value || '').trim(),
            default_title: String(dayEl.querySelector('.js-day-default-title')?.value || '').trim(),
            default_summary: String(dayEl.querySelector('.js-day-default-summary')?.value || '').trim(),
            variants: variantEls.map((variantEl) => {{
              const questionEls = Array.from(variantEl.querySelectorAll(':scope .js-questions-root > .js-question'));
              return {{
                id: variantEl.querySelector('.js-variant-id')?.value ? Number(variantEl.querySelector('.js-variant-id').value) : null,
                level: String(variantEl.querySelector('.js-variant-level')?.value || 'build').trim(),
                title: String(variantEl.querySelector('.js-variant-title')?.value || '').trim(),
                summary: String(variantEl.querySelector('.js-variant-summary')?.value || '').trim(),
                script: String(variantEl.querySelector('.js-variant-script')?.value || '').trim(),
                action_prompt: String(variantEl.querySelector('.js-variant-action-prompt')?.value || '').trim(),
                video_url: String(variantEl.querySelector('.js-variant-video-url')?.value || '').trim(),
                poster_url: String(variantEl.querySelector('.js-variant-poster-url')?.value || '').trim(),
                avatar_character: String(variantEl.querySelector('.js-variant-avatar-character')?.value || '').trim(),
                avatar_style: String(variantEl.querySelector('.js-variant-avatar-style')?.value || '').trim(),
                avatar_voice: String(variantEl.querySelector('.js-variant-avatar-voice')?.value || '').trim(),
                avatar_status: String(variantEl.querySelector('.js-variant-avatar-status')?.value || '').trim(),
                avatar_job_id: String(variantEl.querySelector('.js-variant-avatar-job-id')?.value || '').trim(),
                avatar_error: String(variantEl.querySelector('.js-variant-avatar-error')?.value || '').trim(),
                avatar_generated_at: String(variantEl.querySelector('.js-variant-avatar-generated-at')?.value || '').trim(),
                avatar_source: String(variantEl.querySelector('.js-variant-avatar-source')?.value || '').trim(),
                avatar_summary_url: String(variantEl.querySelector('.js-variant-avatar-summary-url')?.value || '').trim(),
                content_item_id: null,
                reset_avatar_media: String(variantEl.querySelector('.js-variant-reset-avatar-media')?.value || '').trim() === '1',
                takeaway_default: String(variantEl.querySelector('.js-variant-takeaway-default')?.value || '').trim(),
                takeaway_if_low_score: String(variantEl.querySelector('.js-variant-takeaway-low')?.value || '').trim(),
                takeaway_if_high_score: String(variantEl.querySelector('.js-variant-takeaway-high')?.value || '').trim(),
                is_active: Boolean(variantEl.querySelector('.js-variant-active')?.checked),
                quiz: {{
                  id: variantEl.querySelector('.js-quiz-id')?.value ? Number(variantEl.querySelector('.js-quiz-id').value) : null,
                  pass_score_pct: variantEl.querySelector('.js-quiz-pass-score')?.value !== '' ? Number(variantEl.querySelector('.js-quiz-pass-score').value) : null,
                  questions: questionEls.map((questionEl) => {{
                    return {{
                      id: questionEl.querySelector('.js-question-id')?.value ? Number(questionEl.querySelector('.js-question-id').value) : null,
                      question_order: Number(questionEl.querySelector('.js-question-order')?.value || 0),
                      question_text: String(questionEl.querySelector('.js-question-text')?.value || '').trim(),
                      answer_type: String(questionEl.querySelector('.js-question-answer-type')?.value || 'single_choice').trim(),
                      options_json: String(questionEl.querySelector('.js-question-options')?.value || '').trim(),
                      correct_answer_json: String(questionEl.querySelector('.js-question-correct')?.value || '').trim(),
                      explanation: String(questionEl.querySelector('.js-question-explanation')?.value || '').trim(),
                    }};
                  }}),
                }},
              }};
            }}),
          }};
        }}

        function serializeStructure() {{
          const dayEls = Array.from(root.querySelectorAll(':scope > .js-day'));
          const days = dayEls
            .map((dayEl) => collectDayData(dayEl))
            .filter((day) => day.day_index > 0 || day.default_title || day.lesson_goal || day.variants.some((variant) => variant.title || variant.script || variant.action_prompt || variant.video_url || variant.takeaway_default));
          return {{ days }};
        }}

        function updateVariantAvatarFields(variantEl, avatar) {{
          const data = avatar || {{}};
          const setValue = (selector, value) => {{
            const el = variantEl.querySelector(selector);
            if (!el) return;
            el.value = String(value || '');
          }};
          setValue('.js-variant-video-url', data.url);
          setValue('.js-variant-poster-url', data.poster_url);
          setValue('.js-variant-avatar-character', data.character);
          setValue('.js-variant-avatar-style', data.style);
          setValue('.js-variant-avatar-voice', data.voice);
          setValue('.js-variant-avatar-status', data.status);
          setValue('.js-variant-avatar-job-id', data.job_id);
          setValue('.js-variant-avatar-error', data.error);
          setValue('.js-variant-avatar-generated-at', data.generated_at);
          setValue('.js-variant-avatar-source', data.source);
          setValue('.js-variant-avatar-summary-url', data.summary_url);
          updateVariantAvatarReviewState(variantEl);
          renderDaySummaries();
        }}

        function variantAvatarVideoUrl(variantEl) {{
          return String(variantEl.querySelector('.js-variant-video-url')?.value || '').trim();
        }}

        function updateVariantAvatarReviewState(variantEl) {{
          const button = variantEl.querySelector('.js-review-avatar');
          if (!button) return;
          const hasVideo = Boolean(variantAvatarVideoUrl(variantEl));
          button.hidden = !hasVideo;
          button.disabled = !hasVideo;
        }}

        function updateAllVariantAvatarReviewStates() {{
          for (const variantEl of root.querySelectorAll('.js-variant')) {{
            updateVariantAvatarReviewState(variantEl);
          }}
        }}

        function closeAvatarReview() {{
          if (!avatarReviewModal || !avatarReviewVideo) return;
          avatarReviewVideo.pause();
          avatarReviewVideo.removeAttribute('src');
          avatarReviewVideo.removeAttribute('poster');
          avatarReviewVideo.load();
          avatarReviewModal.hidden = true;
        }}

        function openAvatarReview(variantEl) {{
          const videoUrl = variantAvatarVideoUrl(variantEl);
          if (!videoUrl) {{
            window.alert('No generated avatar video is available for this lesson yet.');
            return;
          }}
          const title = String(variantEl.querySelector('.js-variant-title')?.value || '').trim() || 'Review avatar';
          const status = String(variantEl.querySelector('.js-variant-avatar-status')?.value || '').trim();
          const generatedAt = String(variantEl.querySelector('.js-variant-avatar-generated-at')?.value || '').trim();
          const posterUrl = String(variantEl.querySelector('.js-variant-poster-url')?.value || '').trim();
          if (avatarReviewTitle) {{
            avatarReviewTitle.textContent = title;
          }}
          if (avatarReviewStatus) {{
            avatarReviewStatus.textContent = [status, generatedAt ? `generated ${{generatedAt}}` : ''].filter(Boolean).join(' · ');
          }}
          if (avatarReviewOpenLink) {{
            avatarReviewOpenLink.href = videoUrl;
          }}
          if (avatarReviewVideo) {{
            avatarReviewVideo.src = videoUrl;
            if (posterUrl) {{
              avatarReviewVideo.poster = posterUrl;
            }} else {{
              avatarReviewVideo.removeAttribute('poster');
            }}
            avatarReviewVideo.load();
          }}
          if (avatarReviewModal) {{
            avatarReviewModal.hidden = false;
          }}
        }}

        function openSelectedDayVideoReview() {{
          const dayEl = selectedDayElement();
          if (!dayEl) {{
            window.alert('Select a programme day first.');
            return;
          }}
          const variantWithVideo = Array.from(dayEl.querySelectorAll(':scope .js-variants-root > .js-variant'))
            .find((variantEl) => Boolean(variantAvatarVideoUrl(variantEl)));
          if (!variantWithVideo) {{
            window.alert('The selected day does not have a generated avatar video yet.');
            return;
          }}
          openAvatarReview(variantWithVideo);
        }}

        async function requestVariantAvatar(variantEl, mode) {{
          const variantId = String(variantEl.querySelector('.js-variant-id')?.value || '').trim();
          if (!variantId) {{
            window.alert('Save this programme before generating avatar video for this lesson.');
            return;
          }}
          const generateButton = variantEl.querySelector('.js-generate-avatar');
          const refreshButton = variantEl.querySelector('.js-refresh-avatar');
          const previousGenerateText = generateButton ? generateButton.textContent : '';
          const previousRefreshText = refreshButton ? refreshButton.textContent : '';
          if (generateButton) {{
            generateButton.disabled = true;
            generateButton.textContent = mode === 'generate' ? 'Generating...' : 'Generate avatar video';
          }}
          if (refreshButton) {{
            refreshButton.disabled = true;
            refreshButton.textContent = mode === 'refresh' ? 'Refreshing...' : 'Refresh avatar';
          }}
          try {{
            const payload = mode === 'generate' ? {{
              avatar_title: String(variantEl.querySelector('.js-variant-title')?.value || '').trim(),
              avatar_script: String(variantEl.querySelector('.js-variant-script')?.value || '').trim(),
              avatar_poster_url: String(variantEl.querySelector('.js-variant-poster-url')?.value || '').trim(),
              avatar_character: String(variantEl.querySelector('.js-variant-avatar-character')?.value || '').trim(),
              avatar_style: String(variantEl.querySelector('.js-variant-avatar-style')?.value || '').trim(),
              avatar_voice: String(variantEl.querySelector('.js-variant-avatar-voice')?.value || '').trim(),
            }} : {{}};
            const response = await fetch(`/admin/education-programmes/lesson-variants/${{encodeURIComponent(variantId)}}/avatar/${{mode}}`, {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(payload),
            }});
            const result = await response.json().catch(() => ({{}}));
            if (!response.ok || result.ok === false) {{
              const message = String(result.error || result.detail || `Avatar ${{mode}} failed.`);
              window.alert(message);
            }}
            if (result.avatar) {{
              updateVariantAvatarFields(variantEl, result.avatar);
            }}
          }} catch (err) {{
            window.alert(err instanceof Error ? err.message : String(err));
          }} finally {{
            if (generateButton) {{
              generateButton.disabled = false;
              generateButton.textContent = previousGenerateText || 'Generate avatar video';
            }}
            if (refreshButton) {{
              refreshButton.disabled = false;
              refreshButton.textContent = previousRefreshText || 'Refresh avatar';
            }}
          }}
        }}

        function normaliseGeneratedQuestions(generatedQuestions, existingQuestions) {{
          const questions = Array.isArray(generatedQuestions) ? generatedQuestions : [];
          const existing = Array.isArray(existingQuestions) ? existingQuestions : [];
          return questions.slice(0, 3).map((question, index) => {{
            const existingQuestion = existing[index] || {{}};
            let options = question?.options_json;
            if (options === undefined) options = question?.options;
            if (typeof options === 'string') {{
              try {{
                options = JSON.parse(options);
              }} catch (_err) {{
                options = options.split('\\n').map((item) => item.trim()).filter(Boolean);
              }}
            }}
            if (!Array.isArray(options)) {{
              options = [];
            }}
            let correct = question?.correct_answer_json;
            if (correct === undefined) correct = question?.correct_answer;
            if (correct === undefined) correct = question?.answer;
            return {{
              id: existingQuestion.id || null,
              question_order: Number(question?.question_order || index + 1),
              question_text: String(question?.question_text || question?.question || question?.text || '').trim(),
              answer_type: String(question?.answer_type || 'single_choice').trim() || 'single_choice',
              options_json: options,
              correct_answer_json: correct ?? '',
              explanation: String(question?.explanation || '').trim(),
            }};
          }}).filter((question) => question.question_text);
        }}

        function normaliseGeneratedVariant(generatedVariant, existingVariant) {{
          const generated = generatedVariant && typeof generatedVariant === 'object' ? generatedVariant : {{}};
          const existing = existingVariant && typeof existingVariant === 'object' ? existingVariant : {{}};
          const generatedQuiz = generated.quiz && typeof generated.quiz === 'object' ? generated.quiz : {{}};
          const existingQuiz = existing.quiz && typeof existing.quiz === 'object' ? existing.quiz : {{}};
          const existingQuestions = Array.isArray(existingQuiz.questions) ? existingQuiz.questions : [];
          const generatedQuestions = Array.isArray(generatedQuiz.questions) ? generatedQuiz.questions : [];
          const questions = normaliseGeneratedQuestions(generatedQuestions, existingQuestions);
          const level = String(generated.level || existing.level || 'build').trim().toLowerCase() || 'build';
          return {{
            id: existing.id || null,
            level,
            title: String(generated.title || generated.default_title || '').trim(),
            summary: String(generated.summary || generated.default_summary || '').trim(),
            script: String(generated.script || generated.body || '').trim(),
            action_prompt: String(generated.action_prompt || generated.daily_action || '').trim(),
            video_url: '',
            poster_url: '',
            avatar_character: String(generated.avatar_character || existing.avatar_character || '').trim(),
            avatar_style: String(generated.avatar_style || existing.avatar_style || '').trim(),
            avatar_voice: String(generated.avatar_voice || existing.avatar_voice || '').trim(),
            avatar_status: '',
            avatar_job_id: '',
            avatar_error: '',
            avatar_generated_at: '',
            avatar_source: '',
            avatar_summary_url: '',
            content_item_id: null,
            reset_avatar_media: true,
            takeaway_default: String(generated.takeaway_default || '').trim(),
            takeaway_if_low_score: String(generated.takeaway_if_low_score || '').trim(),
            takeaway_if_high_score: String(generated.takeaway_if_high_score || '').trim(),
            is_active: generated.is_active === false ? false : true,
            quiz: {{
              id: existingQuiz.id || null,
              pass_score_pct: generatedQuiz.pass_score_pct ?? existingQuiz.pass_score_pct ?? 66.67,
              questions: questions.length ? questions : [emptyQuestion(1), emptyQuestion(2), emptyQuestion(3)],
            }},
          }};
        }}

        function normaliseGeneratedDayForEditor(generatedDay, existingDay) {{
          const generated = generatedDay && typeof generatedDay === 'object' ? generatedDay : {{}};
          const existing = existingDay && typeof existingDay === 'object' ? existingDay : {{}};
          let generatedVariants = Array.isArray(generated.variants) ? generated.variants : [];
          if (!generatedVariants.length && (generated.title || generated.summary || generated.script || generated.action_prompt || generated.quiz)) {{
            generatedVariants = [generated];
          }}
          const existingVariants = Array.isArray(existing.variants) ? existing.variants : [];
          const variants = generatedVariants.length
            ? generatedVariants.map((variant, index) => normaliseGeneratedVariant(variant, existingVariants[index] || null))
            : [normaliseGeneratedVariant({{}}, existingVariants[0] || emptyVariant())];
          return {{
            id: existing.id || null,
            day_index: Number(generated.day_index || existing.day_index || selectedDayPosition + 1),
            concept_key: selectedProgrammeConceptKey(),
            concept_label: resolvedProgrammeConceptLabel(),
            lesson_goal: String(generated.lesson_goal || '').trim(),
            default_title: String(generated.default_title || variants[0]?.title || '').trim(),
            default_summary: String(generated.default_summary || variants[0]?.summary || '').trim(),
            variants,
          }};
        }}

        function replaceSelectedDayWithGenerated(generatedDay) {{
          const dayEl = selectedDayElement();
          if (!dayEl) {{
            window.alert('Select a programme day first.');
            return;
          }}
          const existingDay = collectDayData(dayEl);
          const replacement = normaliseGeneratedDayForEditor(generatedDay, existingDay);
          dayEl.outerHTML = renderDay(replacement);
          renderDaySummaries();
          updateAllVariantAvatarReviewStates();
          selectDay(selectedDayPosition);
        }}

        function normaliseGeneratedProgrammeForEditor(generatedProgramme) {{
          const generated = generatedProgramme && typeof generatedProgramme === 'object'
            ? (generatedProgramme.programme && typeof generatedProgramme.programme === 'object' ? generatedProgramme.programme : generatedProgramme)
            : {{}};
          const rawDays = Array.isArray(generated.days) ? generated.days : [];
          const existingDays = collectAllDaysFromDom();
          const existingByIndex = new Map(existingDays.map((day) => [Number(day.day_index || 0), day]));
          return rawDays.map((rawDay, index) => {{
            const generatedDay = rawDay && typeof rawDay === 'object' ? rawDay : {{}};
            const dayIndex = Number(generatedDay.day_index || index + 1);
            const existingDay = existingByIndex.get(dayIndex) || existingDays[index] || null;
            return normaliseGeneratedDayForEditor({{ ...generatedDay, day_index: dayIndex }}, existingDay);
          }}).filter((day) => day.default_title || day.lesson_goal || (Array.isArray(day.variants) && day.variants.length));
        }}

        function replaceProgrammeWithGenerated(generatedProgramme) {{
          const replacementDays = normaliseGeneratedProgrammeForEditor(generatedProgramme);
          if (!replacementDays.length) {{
            throw new Error('LLM response did not include usable programme days.');
          }}
          selectedDayPosition = 0;
          renderDays(replacementDays);
          selectDay(0);
        }}

        async function requestConceptProgrammeLlmGeneration() {{
          if (!selectedProgrammeConceptKey()) {{
            window.alert('Select a programme concept before generating a concept programme.');
            programmeConceptInput?.focus();
            return;
          }}
          const dayCount = Math.max(1, Math.min(31, Number(programmeLlmDays?.value || currentDayElements().length || 7)));
          const existingDays = collectAllDaysFromDom();
          const brief = String(programmeLlmBrief?.value || '').trim();
          if (!window.confirm(`Replace the current editor draft with a new ${{dayCount}}-day concept programme? You still need to save afterwards.`)) {{
            return;
          }}
          const payload = {{
            brief,
            model_override: String(programmeLlmModel?.value || '').trim(),
            duration_days: dayCount,
            programme_name: String(form.querySelector('input[name="name"]')?.value || '').trim(),
            programme_code: String(form.querySelector('input[name="code"]')?.value || '').trim(),
            pillar_key: selectedProgrammePillar(),
            programme_concept_key: selectedProgrammeConceptKey(),
            programme_concept_label: resolvedProgrammeConceptLabel(),
            existing_programme: {{
              programme_name: String(form.querySelector('input[name="name"]')?.value || '').trim(),
              programme_code: String(form.querySelector('input[name="code"]')?.value || '').trim(),
              pillar_key: selectedProgrammePillar(),
              programme_concept_key: selectedProgrammeConceptKey(),
              programme_concept_label: resolvedProgrammeConceptLabel(),
              duration_days: existingDays.length,
              days: existingDays,
            }},
          }};
          const previousText = programmeLlmButton ? programmeLlmButton.textContent : '';
          if (programmeLlmButton) {{
            programmeLlmButton.disabled = true;
            programmeLlmButton.textContent = 'Generating...';
          }}
          if (programmeLlmStatus) {{
            programmeLlmStatus.textContent = 'Generating concept programme draft...';
          }}
          try {{
            const response = await fetch('/admin/education-programmes/programme/llm-regenerate', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(payload),
            }});
            const result = await response.json().catch(() => ({{}}));
            if (!response.ok || result.ok === false) {{
              throw new Error(String(result.error || result.detail || 'LLM programme generation failed.'));
            }}
            if (!result.programme) {{
              throw new Error('LLM response did not include a programme draft.');
            }}
            replaceProgrammeWithGenerated(result.programme);
            if (programmeLlmStatus) {{
              programmeLlmStatus.textContent = `Generated with ${{result.model || 'selected model'}}. Review the full programme, then save.`;
            }}
          }} catch (err) {{
            const message = err instanceof Error ? err.message : String(err);
            if (programmeLlmStatus) {{
              programmeLlmStatus.textContent = message;
            }}
            window.alert(message);
          }} finally {{
            if (programmeLlmButton) {{
              programmeLlmButton.disabled = false;
              programmeLlmButton.textContent = previousText || 'Generate concept programme draft';
            }}
          }}
        }}

        async function requestSelectedDayLlmGeneration() {{
          const dayEl = selectedDayElement();
          if (!dayEl) {{
            window.alert('Select a programme day first.');
            return;
          }}
          const brief = String(dayLlmBrief?.value || '').trim();
          if (!brief) {{
            window.alert('Add a task description before generating a day draft.');
            dayLlmBrief?.focus();
            return;
          }}
          const existingDay = collectDayData(dayEl);
          const payload = {{
            brief,
            model_override: String(dayLlmModel?.value || '').trim(),
            programme_name: String(form.querySelector('input[name="name"]')?.value || '').trim(),
            programme_code: String(form.querySelector('input[name="code"]')?.value || '').trim(),
            pillar_key: selectedProgrammePillar(),
            programme_concept_key: selectedProgrammeConceptKey(),
            programme_concept_label: resolvedProgrammeConceptLabel(),
            day_index: existingDay.day_index || selectedDayPosition + 1,
            existing_day: existingDay,
          }};
          const previousText = dayLlmButton ? dayLlmButton.textContent : '';
          if (dayLlmButton) {{
            dayLlmButton.disabled = true;
            dayLlmButton.textContent = 'Generating...';
          }}
          if (dayLlmStatus) {{
            dayLlmStatus.textContent = 'Generating day draft...';
          }}
          try {{
            const response = await fetch('/admin/education-programmes/day/llm-generate', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify(payload),
            }});
            const result = await response.json().catch(() => ({{}}));
            if (!response.ok || result.ok === false) {{
              throw new Error(String(result.error || result.detail || 'LLM day generation failed.'));
            }}
            if (!result.day) {{
              throw new Error('LLM response did not include a day draft.');
            }}
            replaceSelectedDayWithGenerated(result.day);
            if (dayLlmStatus) {{
              dayLlmStatus.textContent = `Generated with ${{result.model || 'selected model'}}. Review the draft, then save.`;
            }}
          }} catch (err) {{
            const message = err instanceof Error ? err.message : String(err);
            if (dayLlmStatus) {{
              dayLlmStatus.textContent = message;
            }}
            window.alert(message);
          }} finally {{
            if (dayLlmButton) {{
              dayLlmButton.disabled = false;
              dayLlmButton.textContent = previousText || 'Generate day draft';
            }}
          }}
        }}

        function renderDays(days) {{
          const sortedDays = [...days]
            .sort((left, right) => Number(left.day_index || 0) - Number(right.day_index || 0));
          root.innerHTML = sortedDays.map((day) => renderDay(day)).join('');
          selectedDayPosition = Math.min(Math.max(0, selectedDayPosition), Math.max(0, sortedDays.length - 1));
          renderDaySummaries();
          updateAllVariantAvatarReviewStates();
        }}

        function renderInitial() {{
          const days = Array.isArray(seed.days) ? [...seed.days] : [];
          renderDays(days.length ? days : [emptyDay(1)]);
        }}

        document.getElementById('add-day-button').addEventListener('click', function() {{
          const dayEls = currentDayElements();
          const nextIndex = dayEls.reduce((maxValue, dayEl) => {{
            const value = Number(dayEl.querySelector('.js-day-index')?.value || 0);
            return Math.max(maxValue, value);
          }}, 0) + 1;
          const days = collectAllDaysFromDom();
          days.push(emptyDay(nextIndex));
          selectedDayPosition = days.length - 1;
          renderDays(days);
        }});

        summaryRoot?.addEventListener('click', function(event) {{
          const target = event.target;
          if (!(target instanceof HTMLElement)) return;
          const button = target.closest('.js-select-day');
          if (!(button instanceof HTMLElement)) return;
          selectDay(Number(button.dataset.dayPosition || 0));
        }});

        dayListFocusButton?.addEventListener('click', function() {{
          summaryRoot?.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
        }});

        root.addEventListener('click', function(event) {{
          const target = event.target;
          if (!(target instanceof HTMLElement)) return;
          if (target.classList.contains('js-remove-day')) {{
            const dayEl = target.closest('.js-day');
            const removedPosition = dayEl ? currentDayElements().indexOf(dayEl) : -1;
            dayEl?.remove();
            if (removedPosition >= 0 && selectedDayPosition > removedPosition) {{
              selectedDayPosition -= 1;
            }}
            renderDaySummaries();
            return;
          }}
          if (target.classList.contains('js-add-variant')) {{
            const dayEl = target.closest('.js-day');
            if (!dayEl) return;
            const variantsRoot = dayEl.querySelector('.js-variants-root');
            if (!variantsRoot) return;
            variantsRoot.insertAdjacentHTML('beforeend', renderVariant(collectDayData(dayEl), emptyVariant()));
            renderDaySummaries();
            updateAllVariantAvatarReviewStates();
            return;
          }}
          if (target.classList.contains('js-remove-variant')) {{
            target.closest('.js-variant')?.remove();
            renderDaySummaries();
            return;
          }}
          if (target.classList.contains('js-generate-avatar')) {{
            const variantEl = target.closest('.js-variant');
            if (variantEl) {{
              void requestVariantAvatar(variantEl, 'generate');
            }}
            return;
          }}
          if (target.classList.contains('js-refresh-avatar')) {{
            const variantEl = target.closest('.js-variant');
            if (variantEl) {{
              void requestVariantAvatar(variantEl, 'refresh');
            }}
            return;
          }}
          if (target.classList.contains('js-review-avatar')) {{
            const variantEl = target.closest('.js-variant');
            if (variantEl) {{
              openAvatarReview(variantEl);
            }}
            return;
          }}
          if (target.classList.contains('js-add-question')) {{
            const variantEl = target.closest('.js-variant');
            if (!variantEl) return;
            const questionsRoot = variantEl.querySelector('.js-questions-root');
            if (!questionsRoot) return;
            const existing = questionsRoot.querySelectorAll(':scope > .js-question').length;
            if (existing >= 3) {{
              window.alert('Use 3 quiz questions per lesson.');
              return;
            }}
            questionsRoot.insertAdjacentHTML('beforeend', renderQuestion(emptyQuestion(existing + 1)));
            renderDaySummaries();
            return;
          }}
          if (target.classList.contains('js-remove-question')) {{
            target.closest('.js-question')?.remove();
            renderDaySummaries();
          }}
        }});

        programmeConceptInput.addEventListener('change', function(event) {{
          const target = event.target;
          if (!(target instanceof HTMLSelectElement)) return;
          const previousLabel = String(programmeConceptLabelInput?.value || '').trim();
          const match = selectedProgrammeConcept();
          if (programmeConceptLabelInput && (!previousLabel || previousLabel === String(programmeConceptInput.dataset.previousLabel || ''))) {{
            programmeConceptLabelInput.value = String(match?.name || '').trim();
          }}
          programmeConceptInput.dataset.previousLabel = String(programmeConceptLabelInput?.value || '').trim();
          programmeConceptInput.dataset.selected = String(target.value || '').trim().toLowerCase();
          if (pillarDisplayInput) {{
            pillarDisplayInput.value = titleCasePillar(selectedProgrammePillar());
          }}
          const days = collectAllDaysFromDom();
          renderDays(days.length ? days : [emptyDay(1)]);
        }});

        programmeConceptLabelInput?.addEventListener('input', function() {{
          const days = collectAllDaysFromDom();
          renderDays(days.length ? days : [emptyDay(1)]);
        }});

        root.addEventListener('input', function(event) {{
          const target = event.target;
          if (!(target instanceof HTMLElement)) return;
          if (target.classList.contains('js-variant-video-url')) {{
            const variantEl = target.closest('.js-variant');
            if (variantEl) updateVariantAvatarReviewState(variantEl);
          }}
          renderDaySummaries();
        }});

        dayLlmButton?.addEventListener('click', function() {{
          void requestSelectedDayLlmGeneration();
        }});

        programmeLlmButton?.addEventListener('click', function() {{
          void requestConceptProgrammeLlmGeneration();
        }});

        reviewSelectedDayVideoButton?.addEventListener('click', openSelectedDayVideoReview);
        avatarReviewClose?.addEventListener('click', closeAvatarReview);
        avatarReviewModal?.addEventListener('click', function(event) {{
          if (event.target === avatarReviewModal) {{
            closeAvatarReview();
          }}
        }});
        document.addEventListener('keydown', function(event) {{
          if (event.key === 'Escape' && avatarReviewModal && !avatarReviewModal.hidden) {{
            closeAvatarReview();
          }}
        }});

        form.addEventListener('submit', function(event) {{
          try {{
            structureField.value = JSON.stringify(serializeStructure());
          }} catch (err) {{
            event.preventDefault();
            window.alert('Failed to prepare programme structure for saving.');
          }}
        }});

        refreshProgrammeConceptChoices();
        programmeConceptInput.dataset.previousLabel = String(programmeConceptLabelInput?.value || '').trim();
        renderInitial();
        updateAllVariantAvatarReviewStates();
      }})();
    </script>
    <p class='nav' style='margin-top:16px;'><a href="/admin/education-programmes">Back to list</a></p>
    """
    return _wrap_page(title, body)


@admin.post("/education-programmes/save")
async def save_education_programme(
    id: int | None = Form(default=None),
    pillar_key: str | None = Form(default=None),
    programme_concept_key: str | None = Form(default=None),
    programme_concept_label: str | None = Form(default=None),
    code: str = Form(...),
    name: str = Form(...),
    is_active: str | None = Form(default=None),
    structure_json: str | None = Form(default=None),
):
    ensure_education_plan_schema()
    pillar_token = str(pillar_key or "").strip().lower()
    raw_programme_concept_token = str(programme_concept_key or "").strip().lower()
    if "::" in raw_programme_concept_token:
        explicit_pillar, explicit_concept = raw_programme_concept_token.split("::", 1)
        pillar_token = str(explicit_pillar or "").strip().lower() or pillar_token
        programme_concept_token = str(explicit_concept or "").strip().lower()
    else:
        programme_concept_token = raw_programme_concept_token
    programme_concept_text = str(programme_concept_label or "").strip()
    code_token = str(code or "").strip()
    name_text = str(name or "").strip()
    if not programme_concept_token:
        raise HTTPException(400, "programme_concept_key is required")
    if not code_token:
        raise HTTPException(400, "code is required")
    if not name_text:
        raise HTTPException(400, "name is required")
    try:
        structure = json.loads(str(structure_json or "{}"))
    except Exception as exc:
        raise HTTPException(400, f"Invalid programme structure JSON: {exc}")
    days_payload = structure.get("days") if isinstance(structure, dict) else []
    if days_payload is None:
        days_payload = []
    if not isinstance(days_payload, list):
        raise HTTPException(400, "structure_json.days must be a list")

    seen_day_indexes: set[int] = set()
    normalised_days: list[dict[str, object]] = []
    for raw_day in days_payload:
        if not isinstance(raw_day, dict):
            continue
        try:
            day_index = int(raw_day.get("day_index") or 0)
        except Exception:
            day_index = 0
        if not day_index:
            continue
        if day_index in seen_day_indexes:
            raise HTTPException(400, f"Duplicate day_index: {day_index}")
        seen_day_indexes.add(day_index)
        variants = raw_day.get("variants") if isinstance(raw_day.get("variants"), list) else []
        normalised_days.append(
            {
                "id": int(raw_day.get("id")) if raw_day.get("id") else None,
                "day_index": day_index,
                "lesson_goal": str(raw_day.get("lesson_goal") or "").strip() or None,
                "default_title": str(raw_day.get("default_title") or "").strip() or None,
                "default_summary": str(raw_day.get("default_summary") or "").strip() or None,
                "variants": variants,
            }
        )
    resolved_duration = max(seen_day_indexes, default=0)

    with SessionLocal() as s:
        concept_candidates = (
            s.query(Concept)
            .filter(Concept.code == programme_concept_token)
            .order_by(Concept.pillar_key.asc(), Concept.id.asc())
            .all()
        )
        if pillar_token:
            concept_candidates = [
                item
                for item in concept_candidates
                if str(getattr(item, "pillar_key", "") or "").strip().lower() == pillar_token
            ]
        if not concept_candidates:
            raise HTTPException(400, "programme_concept_key is invalid")
        if len(concept_candidates) > 1:
            raise HTTPException(400, "programme_concept_key is ambiguous; provide a pillar-specific concept code")
        concept_row = concept_candidates[0]
        pillar_token = str(getattr(concept_row, "pillar_key", "") or "").strip().lower()
        if pillar_token not in {"nutrition", "training", "resilience", "recovery"}:
            raise HTTPException(400, "programme_concept_key must resolve to a supported pillar")
        if not programme_concept_text:
            programme_concept_text = str(getattr(concept_row, "name", "") or "").strip()
        row = s.get(EducationProgramme, id) if id else None
        if id and row is None:
            raise HTTPException(404, "Education programme not found")
        if row is None:
            row = EducationProgramme()
            row.pillar_key = pillar_token
            row.concept_key = programme_concept_token or None
            row.concept_label = programme_concept_text or None
            row.code = code_token
            row.name = name_text
            row.duration_days = resolved_duration
            row.is_active = is_active is not None
            s.add(row)
            s.flush()
        else:
            row.pillar_key = pillar_token
            row.concept_key = programme_concept_token or None
            row.concept_label = programme_concept_text or None
            row.code = code_token
            row.name = name_text
            row.duration_days = resolved_duration
            row.is_active = is_active is not None
        s.add(row)
        s.flush()

        existing_days = {
            int(item.id): item
            for item in s.query(EducationProgrammeDay)
            .filter(EducationProgrammeDay.programme_id == int(row.id))
            .all()
        }
        existing_days_by_index = {
            int(item.day_index): item
            for item in existing_days.values()
        }
        keep_day_ids: set[int] = set()

        for day_payload in sorted(normalised_days, key=lambda item: int(item.get("day_index") or 0)):
            day_row = None
            day_id = day_payload.get("id")
            if day_id and int(day_id) in existing_days:
                day_row = existing_days[int(day_id)]
            elif int(day_payload["day_index"]) in existing_days_by_index:
                day_row = existing_days_by_index[int(day_payload["day_index"])]
            else:
                day_row = EducationProgrammeDay(programme_id=int(row.id))
                s.add(day_row)
                s.flush()
            day_row.programme_id = int(row.id)
            day_row.day_index = int(day_payload["day_index"])
            day_row.concept_key = programme_concept_token
            day_row.concept_label = programme_concept_text or None
            day_row.lesson_goal = day_payload.get("lesson_goal")
            day_row.default_title = day_payload.get("default_title")
            day_row.default_summary = day_payload.get("default_summary")
            s.add(day_row)
            s.flush()
            keep_day_ids.add(int(day_row.id))

            existing_variants = {
                int(item.id): item
                for item in s.query(EducationLessonVariant)
                .filter(EducationLessonVariant.programme_day_id == int(day_row.id))
                .all()
            }
            existing_variants_by_level = {
                str(item.level or "").strip().lower(): item
                for item in existing_variants.values()
            }
            keep_variant_ids: set[int] = set()

            raw_variants = day_payload.get("variants") if isinstance(day_payload.get("variants"), list) else []
            for raw_variant in raw_variants:
                if not isinstance(raw_variant, dict):
                    continue
                level = str(raw_variant.get("level") or "").strip().lower() or "build"
                variant_row = None
                variant_id = raw_variant.get("id")
                if variant_id and int(variant_id) in existing_variants:
                    variant_row = existing_variants[int(variant_id)]
                elif level in existing_variants_by_level:
                    variant_row = existing_variants_by_level[level]
                else:
                    variant_row = EducationLessonVariant(programme_day_id=int(day_row.id))
                    s.add(variant_row)
                    s.flush()
                variant_row.programme_day_id = int(day_row.id)
                variant_row.level = level
                variant_row.title = str(raw_variant.get("title") or "").strip() or None
                variant_row.summary = str(raw_variant.get("summary") or "").strip() or None
                variant_row.script = str(raw_variant.get("script") or "").strip() or None
                variant_row.action_prompt = str(raw_variant.get("action_prompt") or "").strip() or None
                def _raw_variant_text(key: str) -> str:
                    return str(raw_variant.get(key) or "").strip()

                def _preserve_runtime_text(key: str, current: object) -> str | None:
                    value = _raw_variant_text(key)
                    if value:
                        return value
                    return str(current or "").strip() or None

                reset_avatar_media = _truthy_form_value(raw_variant.get("reset_avatar_media"))
                if reset_avatar_media:
                    variant_row.video_url = _raw_variant_text("video_url") or None
                else:
                    variant_row.video_url = _preserve_runtime_text("video_url", getattr(variant_row, "video_url", None))
                variant_row.poster_url = str(raw_variant.get("poster_url") or "").strip() or None
                variant_row.avatar_character = str(raw_variant.get("avatar_character") or "").strip() or None
                variant_row.avatar_style = str(raw_variant.get("avatar_style") or "").strip() or None
                variant_row.avatar_voice = str(raw_variant.get("avatar_voice") or "").strip() or None
                if reset_avatar_media:
                    variant_row.avatar_status = _raw_variant_text("avatar_status") or None
                    variant_row.avatar_job_id = _raw_variant_text("avatar_job_id") or None
                else:
                    variant_row.avatar_status = _preserve_runtime_text("avatar_status", getattr(variant_row, "avatar_status", None))
                    variant_row.avatar_job_id = _preserve_runtime_text("avatar_job_id", getattr(variant_row, "avatar_job_id", None))
                variant_row.avatar_error = str(raw_variant.get("avatar_error") or "").strip() or None
                if reset_avatar_media:
                    variant_row.avatar_source = _raw_variant_text("avatar_source") or None
                    variant_row.avatar_summary_url = _raw_variant_text("avatar_summary_url") or None
                else:
                    variant_row.avatar_source = _preserve_runtime_text("avatar_source", getattr(variant_row, "avatar_source", None))
                    variant_row.avatar_summary_url = _preserve_runtime_text("avatar_summary_url", getattr(variant_row, "avatar_summary_url", None))
                avatar_generated_at = _raw_variant_text("avatar_generated_at")
                if reset_avatar_media:
                    variant_row.avatar_generated_at = None
                elif avatar_generated_at:
                    try:
                        variant_row.avatar_generated_at = datetime.fromisoformat(avatar_generated_at)
                    except Exception:
                        pass
                elif getattr(variant_row, "avatar_generated_at", None) is None:
                    variant_row.avatar_generated_at = None
                variant_row.content_item_id = int(raw_variant.get("content_item_id")) if raw_variant.get("content_item_id") else None
                variant_row.takeaway_default = str(raw_variant.get("takeaway_default") or "").strip() or None
                variant_row.takeaway_if_low_score = str(raw_variant.get("takeaway_if_low_score") or "").strip() or None
                variant_row.takeaway_if_high_score = str(raw_variant.get("takeaway_if_high_score") or "").strip() or None
                variant_row.is_active = bool(raw_variant.get("is_active", True))
                s.add(variant_row)
                s.flush()
                keep_variant_ids.add(int(variant_row.id))

                quiz_payload = raw_variant.get("quiz") if isinstance(raw_variant.get("quiz"), dict) else {}
                raw_questions = quiz_payload.get("questions") if isinstance(quiz_payload.get("questions"), list) else []
                pass_score_pct = quiz_payload.get("pass_score_pct")
                try:
                    pass_score_val = float(pass_score_pct) if pass_score_pct not in (None, "") else None
                except Exception:
                    pass_score_val = None
                existing_quiz = (
                    s.query(EducationQuiz)
                    .filter(EducationQuiz.lesson_variant_id == int(variant_row.id))
                    .one_or_none()
                )
                normalised_questions = []
                for raw_question in raw_questions:
                    if not isinstance(raw_question, dict):
                        continue
                    question_text = str(raw_question.get("question_text") or "").strip()
                    if not question_text:
                        continue
                    try:
                        order = int(raw_question.get("question_order") or (len(normalised_questions) + 1))
                    except Exception:
                        order = len(normalised_questions) + 1
                    options_val = raw_question.get("options_json")
                    correct_val = raw_question.get("correct_answer_json")
                    if isinstance(options_val, str) and options_val.strip():
                        try:
                            options_val = json.loads(options_val)
                        except Exception as exc:
                            raise HTTPException(400, f"Day {day_row.day_index} variant {level} question {order}: invalid options JSON ({exc})")
                    if isinstance(correct_val, str) and correct_val.strip():
                        try:
                            correct_val = json.loads(correct_val)
                        except Exception:
                            correct_val = correct_val.strip()
                    elif correct_val == "":
                        correct_val = None
                    normalised_questions.append(
                        {
                            "id": int(raw_question.get("id")) if raw_question.get("id") else None,
                            "question_order": order,
                            "question_text": question_text,
                            "answer_type": str(raw_question.get("answer_type") or "single_choice").strip() or "single_choice",
                            "options_json": options_val,
                            "correct_answer_json": correct_val,
                            "explanation": str(raw_question.get("explanation") or "").strip() or None,
                        }
                    )

                if pass_score_val is not None or normalised_questions:
                    quiz_row = existing_quiz or EducationQuiz(lesson_variant_id=int(variant_row.id))
                    quiz_row.lesson_variant_id = int(variant_row.id)
                    quiz_row.pass_score_pct = pass_score_val
                    s.add(quiz_row)
                    s.flush()
                    existing_questions = {
                        int(item.id): item
                        for item in s.query(EducationQuizQuestion)
                        .filter(EducationQuizQuestion.quiz_id == int(quiz_row.id))
                        .all()
                    }
                    existing_questions_by_order = {
                        int(item.question_order): item
                        for item in existing_questions.values()
                    }
                    keep_question_ids: set[int] = set()
                    for question_payload in sorted(normalised_questions, key=lambda item: int(item.get("question_order") or 0)):
                        question_row = None
                        question_id = question_payload.get("id")
                        if question_id and int(question_id) in existing_questions:
                            question_row = existing_questions[int(question_id)]
                        elif int(question_payload["question_order"]) in existing_questions_by_order:
                            question_row = existing_questions_by_order[int(question_payload["question_order"])]
                        else:
                            question_row = EducationQuizQuestion(quiz_id=int(quiz_row.id))
                            s.add(question_row)
                            s.flush()
                        question_row.quiz_id = int(quiz_row.id)
                        question_row.question_order = int(question_payload["question_order"])
                        question_row.question_text = str(question_payload["question_text"] or "").strip()
                        question_row.answer_type = str(question_payload["answer_type"] or "single_choice").strip() or "single_choice"
                        question_row.options_json = question_payload.get("options_json")
                        question_row.correct_answer_json = question_payload.get("correct_answer_json")
                        question_row.explanation = question_payload.get("explanation")
                        s.add(question_row)
                        s.flush()
                        keep_question_ids.add(int(question_row.id))
                    for question_id, question_row in existing_questions.items():
                        if question_id not in keep_question_ids:
                            s.delete(question_row)
                elif existing_quiz is not None:
                    for question_row in (
                        s.query(EducationQuizQuestion)
                        .filter(EducationQuizQuestion.quiz_id == int(existing_quiz.id))
                        .all()
                    ):
                        s.delete(question_row)
                    s.delete(existing_quiz)

            for variant_id, variant_row in existing_variants.items():
                if variant_id not in keep_variant_ids:
                    s.delete(variant_row)

        for day_id, day_row in existing_days.items():
            if day_id not in keep_day_ids:
                s.delete(day_row)

        s.commit()
        redirect_id = int(row.id)
    return RedirectResponse(url=f"/admin/education-programmes/edit?id={redirect_id}", status_code=303)


@admin.get("/reports/prompt-audit", response_class=HTMLResponse)
def admin_prompt_audit(user_id: int, as_of_date: str, state: str = "live", logs: int = 3):
    """Generate a prompt audit report and return a link."""
    from .reporting import generate_prompt_audit_report, _report_link
    path = generate_prompt_audit_report(user_id=user_id, as_of_date=as_of_date, state=state, include_logs=True, logs_limit=logs)
    fname = os.path.basename(path)
    try:
        url = _report_link(user_id, fname)
        link_html = f"<a href='{html.escape(url)}' target='_blank' rel='noopener'>{html.escape(url)}</a>"
    except Exception:
        link_html = html.escape(path)
    body = f"<div class='card'><p>Prompt audit ready for user {user_id} @ {html.escape(as_of_date)} (state={html.escape(state)}).</p><p>{link_html}</p></div>"
    return _wrap_page("Prompt Audit", body)

@admin.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(run_id: int):
    with SessionLocal() as s:
        run = s.get(AssessmentRun, run_id)
        if not run:
            raise HTTPException(404, "Run not found")
        turns = s.query(AssessmentTurn).filter(AssessmentTurn.run_id == run_id).order_by(AssessmentTurn.idx.asc()).all()
        results = s.query(PillarResult).filter(PillarResult.run_id == run_id).all()

        turn_rows = []
        for t in turns:
            retr = t.retrieval or []
            retr_html = "<br>".join([f"<code>{x.get('id')}</code> <em>{x.get('type')}</em>: {x.get('text','')[:160]}…" for x in retr])
            deltas_html = "<pre style='white-space:pre-wrap'>" + (str(t.deltas) if t.deltas else "") + "</pre>"
            turn_rows.append(
                "<tr>"
                f"<td>{t.idx}</td>"
                f"<td>{t.pillar}</td>"
                f"<td>{t.concept_key or ''}</td>"
                f"<td>{'clarifier' if t.is_clarifier else ''}</td>"
                f"<td>{(t.assistant_q or '')[:200]}</td>"
                f"<td>{(t.user_a or '')[:200]}</td>"
                f"<td>{retr_html}</td>"
                f"<td><pre style='white-space:pre-wrap'>{(t.llm_raw or '')[:400]}</pre></td>"
                f"<td>{t.action or ''}</td>"
                f"<td>{deltas_html}</td>"
                f"<td>{'' if t.confidence is None else t.confidence}</td>"
                "</tr>"
            )

        res_rows = []
        for r in results:
            res_rows.append(
                "<tr>"
                f"<td>{r.pillar}</td>"
                f"<td>{r.level}</td>"
                f"<td>{r.confidence}</td>"
                f"<td><pre style='white-space:pre-wrap'>" + (str(r.coverage)[:400]) + "</pre></td>"
                f"<td><pre style='white-space:pre-wrap'>" + (r.summary_msg or "") + "</pre></td>"
                "</tr>"
            )

        html = (
            f"<h2>Run #{run.id} — user {run.user_id}</h2>"
            f"<p>Started: {run.started_at} | Completed: {run.is_completed} | Model: {run.model_name} | KB: {run.kb_version}</p>"
            "<h3>Turns</h3>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>#</th><th>Pillar</th><th>Concept</th><th>Clarifier?</th><th>Assistant Q</th><th>User A</th><th>Retrieval</th><th>LLM Raw</th><th>Action</th><th>Deltas</th><th>Conf</th></tr>"
            + "".join(turn_rows) + "</table>"
            "<h3>Pillar Results</h3>"
            "<table border='1' cellpadding='6' cellspacing='0'>"
            "<tr><th>Pillar</th><th>Level</th><th>Confidence</th><th>Coverage</th><th>Summary</th></tr>"
            + "".join(res_rows) + "</table>"
        )
        return HTMLResponse(html)
