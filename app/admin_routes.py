# app/admin_routes.py
from __future__ import annotations

import html
import os

import json
from types import SimpleNamespace

from fastapi import APIRouter, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, text as sa_text, case, false

from .db import SessionLocal, engine
from .models import (
    AssessmentRun,
    AssessmentTurn,
    ContentLibraryItem,
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
)
from .job_queue import ensure_prompt_settings_schema
from .prompts import _ensure_llm_prompt_log_schema, _canonical_state
from .prompts import build_prompt
from . import prompts as prompts_module
from .models import User
from .education_plan import ensure_education_plan_schema
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
    --accent: #1459ff;
  }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 0; background: var(--bg); color: var(--text); font-family: 'Inter', system-ui, -apple-system, sans-serif; }
  h1, h2, h3, h4 { font-family: 'Outfit', 'Inter', system-ui, sans-serif; margin: 0 0 12px; }
  a { color: var(--accent); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .page { max-width: 1100px; margin: 32px auto; padding: 0 20px 40px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 16px 18px; box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04); }
  .meta { color: var(--muted); font-size: 0.95rem; }
  .admin-menu { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-bottom: 16px; padding: 10px 12px; background: #eef4ff; border: 1px solid #cfe0ff; border-radius: 12px; }
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
  button:hover { background: #0f47cc; }
  .nav { margin-bottom: 12px; }
  .help { color: var(--muted); font-size: 0.9rem; margin: 4px 0 10px; }
  select { width: 100%; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-family: 'Inter', system-ui, sans-serif; font-size: 14px; background: #fff; }
  .grid-2 { display: grid; gap: 12px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .grid-3 { display: grid; gap: 12px; grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .stack { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
  .section-title { margin: 0 0 6px; font-size: 1.05rem; }
  .subtle { color: var(--muted); font-size: 0.86rem; }
  .programme-day { border: 1px solid var(--border); border-radius: 12px; padding: 14px; background: #fcfdff; margin-bottom: 12px; }
  .lesson-variant { border: 1px solid #d7dfe8; border-radius: 10px; padding: 12px; background: #fff; margin-top: 10px; }
  .quiz-question { border: 1px dashed #c6d1dc; border-radius: 10px; padding: 12px; background: #fbfcfe; margin-top: 10px; }
  .danger { background: #9f1239; }
  .danger:hover { background: #881337; }
  .secondary { background: #e2e8f0; color: #0f172a; }
  .secondary:hover { background: #cbd5e1; }
  @media (max-width: 860px) {
    .grid-2, .grid-3 { grid-template-columns: 1fr; }
  }
</style>
<style>
  .button-link {
    display: inline-block;
    background: #e2e8f0;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 8px 12px;
    text-decoration: none;
    font-weight: 600;
  }
  .button-link:hover {
    background: #cbd5e1;
  }
</style>
"""


def _admin_menu_html() -> str:
    return (
        "<nav class='admin-menu'>"
        "<a href='/admin/runs'>Assessment Runs</a>"
        "<a href='/admin/prompt-templates'>Prompt Templates</a>"
        "<a href='/admin/education-programmes'>Education Programmes</a>"
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
            "pillar_key": "nutrition",
            "code": "",
            "name": "",
            "duration_days": 21,
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
    return {
        "id": int(row.id),
        "pillar_key": str(row.pillar_key or ""),
        "code": str(row.code or ""),
        "name": str(row.name or ""),
        "duration_days": int(row.duration_days or 21),
        "is_active": bool(row.is_active),
        "days": payload_days,
    }


def _education_editor_options(session) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    concept_rows = (
        session.query(Concept)
        .order_by(Concept.pillar_key.asc(), Concept.code.asc())
        .all()
    )
    content_rows = (
        session.query(ContentLibraryItem)
        .order_by(ContentLibraryItem.pillar_key.asc(), ContentLibraryItem.concept_code.asc(), ContentLibraryItem.title.asc(), ContentLibraryItem.id.asc())
        .limit(2000)
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
    contents = [
        {
            "id": int(row.id),
            "pillar_key": str(row.pillar_key or "").strip().lower(),
            "concept_code": str(row.concept_code or "").strip().lower() or None,
            "title": str(row.title or "").strip() or f"Content #{row.id}",
            "level": str(row.level or "").strip().lower() or None,
            "status": str(row.status or "").strip().lower() or None,
        }
        for row in content_rows
    ]
    return concepts, contents


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
    items = []
    for row in rows:
        items.append(
            "<tr>"
            f"<td>{int(row.id)}</td>"
            f"<td>{html.escape(str(row.pillar_key or ''))}</td>"
            f"<td>{html.escape(str(row.code or ''))}</td>"
            f"<td>{html.escape(str(row.name or ''))}</td>"
            f"<td>{int(row.duration_days or 21)}</td>"
            f"<td>{'✓' if bool(row.is_active) else '✕'}</td>"
            f"<td>{html.escape(str(row.updated_at or ''))}</td>"
            f"<td><a href='/admin/education-programmes/edit?id={int(row.id)}'>Edit</a></td>"
            "</tr>"
        )
    body = (
        "<h2>Education Programmes</h2>"
        f"{_build_version_label()}"
        "<div class='nav'><a href='/admin/education-programmes/edit'>Create new programme</a></div>"
        "<div class='card'>"
        "<table>"
        "<tr><th>ID</th><th>Pillar</th><th>Code</th><th>Name</th><th>Days</th><th>Active</th><th>Updated</th><th>Action</th></tr>"
        + ("".join(items) if items else "<tr><td colspan='8'><em>No education programmes configured yet.</em></td></tr>")
        + "</table>"
        "</div>"
    )
    return _wrap_page("Education Programmes", body)


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
        concept_options, content_options = _education_editor_options(s)
    title = "Edit Education Programme" if row is not None else "Create Education Programme"
    title += f": {html.escape(str(getattr(row, 'name', '') or '').strip())}" if row is not None else ""
    pillar_options = [
        ("nutrition", "Nutrition"),
        ("training", "Training"),
        ("resilience", "Resilience"),
        ("recovery", "Recovery"),
    ]
    current_pillar = str(programme_payload.get("pillar_key") or "nutrition").strip().lower() or "nutrition"
    structure_seed = {"days": programme_payload.get("days") or []}
    body = f"""
    <h2>{title}</h2>
    {_build_version_label()}
    <div class='card' style='margin-bottom:12px;'>
      <p class='help'>Use this editor to define the 21-day lesson spine, levelled video variants, the 3-question quiz, and the takeaway text shown after quiz completion. Saving rewrites the programme structure for this template, so edit active programmes carefully.</p>
    </div>
    <form method="post" action="/admin/education-programmes/save" id="education-programme-form">
      <input type="hidden" name="id" value="{html.escape(str(programme_payload.get('id') or ''))}" />
      <input type="hidden" name="structure_json" id="structure_json" value="" />
      <div class='card' style='margin-bottom:12px;'>
        <div class='grid-2'>
          <div class='field'>
            <label>Pillar<br/>
              <select name="pillar_key" id="pillar_key">
                {"".join(
                    f"<option value='{value}' {'selected' if current_pillar == value else ''}>{label}</option>"
                    for value, label in pillar_options
                )}
              </select>
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
            <label>Duration days<br/>
              <input type="number" min="1" max="90" name="duration_days" id="duration_days" value="{html.escape(str(programme_payload.get('duration_days') or 21))}" />
            </label>
          </div>
        </div>
        <div class='field'>
          <label><input type="checkbox" name="is_active" {"checked" if bool(programme_payload.get("is_active", True)) else ""} /> Active programme</label>
        </div>
      </div>

      <div class='card' style='margin-bottom:12px;'>
        <div class='stack' style='justify-content:space-between;'>
          <div>
            <h3 class='section-title'>Programme Days</h3>
            <div class='subtle'>Each day can carry levelled video variants. Each variant can have one quiz with up to 3 questions.</div>
          </div>
          <div class='stack'>
            <button type="button" class="secondary" id="seed-days-button">Seed From Duration</button>
            <button type="button" class="secondary" id="add-day-button">Add Day</button>
          </div>
        </div>
      </div>

      <div id="programme-days-root"></div>

      <div class='actions stack' style='margin-top:16px;'>
        <button type="submit">Save Programme</button>
        <a class='button-link' href="/admin/education-programmes">Back to list</a>
      </div>
    </form>

    <script id="education-programme-seed" type="application/json">{html.escape(json.dumps(structure_seed))}</script>
    <script id="education-concept-options" type="application/json">{html.escape(json.dumps(concept_options))}</script>
    <script id="education-content-options" type="application/json">{html.escape(json.dumps(content_options))}</script>
    <script>
      (function() {{
        const seed = JSON.parse(document.getElementById('education-programme-seed').textContent || '{{}}');
        const conceptOptions = JSON.parse(document.getElementById('education-concept-options').textContent || '[]');
        const contentOptions = JSON.parse(document.getElementById('education-content-options').textContent || '[]');
        const root = document.getElementById('programme-days-root');
        const form = document.getElementById('education-programme-form');
        const structureField = document.getElementById('structure_json');
        const pillarInput = document.getElementById('pillar_key');
        const durationInput = document.getElementById('duration_days');

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
            content_item_id: null,
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
            concept_key: '',
            concept_label: '',
            lesson_goal: '',
            default_title: '',
            default_summary: '',
            variants: [emptyVariant()],
          }};
        }}

        function selectedPillar() {{
          return String(pillarInput.value || '').trim().toLowerCase();
        }}

        function conceptChoices(pillarKey) {{
          const token = String(pillarKey || '').trim().toLowerCase();
          return conceptOptions.filter((item) => String(item.pillar_key || '').toLowerCase() === token);
        }}

        function contentChoices(pillarKey, conceptKey, selectedId) {{
          const pillarToken = String(pillarKey || '').trim().toLowerCase();
          const conceptToken = String(conceptKey || '').trim().toLowerCase();
          const selectedToken = selectedId ? Number(selectedId) : null;
          const matched = [];
          const fallback = [];
          for (const item of contentOptions) {{
            const samePillar = String(item.pillar_key || '').toLowerCase() === pillarToken;
            const sameConcept = conceptToken && String(item.concept_code || '').toLowerCase() === conceptToken;
            if (samePillar && (sameConcept || selectedToken === Number(item.id))) {{
              matched.push(item);
            }} else if (samePillar) {{
              fallback.push(item);
            }}
          }}
          const combined = [...matched];
          for (const item of fallback) {{
            if (!combined.some((candidate) => Number(candidate.id) === Number(item.id))) {{
              combined.push(item);
            }}
          }}
          return combined;
        }}

        function renderConceptSelect(day) {{
          const options = conceptChoices(selectedPillar());
          const current = String(day.concept_key || '').trim().toLowerCase();
          const empty = "<option value=''>Select concept</option>";
          const items = options.map((item) => {{
            const selected = current === String(item.code || '').toLowerCase() ? 'selected' : '';
            return `<option value="${{escapeHtml(item.code)}}" ${{selected}}>${{escapeHtml(item.name || item.code)}}</option>`;
          }}).join('');
          return `<select class="js-day-concept">${{empty}}${{items}}</select>`;
        }}

        function renderContentSelect(day, variant) {{
          const current = variant.content_item_id ? Number(variant.content_item_id) : null;
          const options = contentChoices(selectedPillar(), day.concept_key, current);
          const empty = "<option value=''>Select video content</option>";
          const items = options.map((item) => {{
            const selected = current === Number(item.id) ? 'selected' : '';
            const label = `#${{item.id}} · ${{item.title}}${{item.level ? ` · ${{item.level}}` : ''}}${{item.status ? ` · ${{item.status}}` : ''}}`;
            return `<option value="${{Number(item.id)}}" ${{selected}}>${{escapeHtml(label)}}</option>`;
          }}).join('');
          return `<select class="js-variant-content-item">${{empty}}${{items}}</select>`;
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
          return `
            <div class="lesson-variant js-variant">
              <input type="hidden" class="js-variant-id" value="${{escapeHtml(variant.id || '')}}" />
              <div class="stack" style="justify-content:space-between;">
                <strong>Lesson Variant</strong>
                <button type="button" class="danger js-remove-variant">Remove variant</button>
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
                  <label>Video content<br/>${{renderContentSelect(day, variant)}}</label>
                </div>
                <div class="field">
                  <label><input type="checkbox" class="js-variant-active" ${{variant.is_active === false ? '' : 'checked'}} /> Active</label>
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
                  <label>Concept<br/>${{renderConceptSelect(day)}}</label>
                </div>
                <div class="field">
                  <label>Concept label<br/><input type="text" class="js-day-concept-label" value="${{escapeHtml(day.concept_label || '')}}" /></label>
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
          const conceptKey = String(dayEl.querySelector('.js-day-concept')?.value || '').trim();
          return {{
            id: dayEl.querySelector('.js-day-id')?.value ? Number(dayEl.querySelector('.js-day-id').value) : null,
            day_index: Number(dayEl.querySelector('.js-day-index')?.value || 0),
            concept_key: conceptKey,
            concept_label: String(dayEl.querySelector('.js-day-concept-label')?.value || '').trim(),
            lesson_goal: String(dayEl.querySelector('.js-day-lesson-goal')?.value || '').trim(),
            default_title: String(dayEl.querySelector('.js-day-default-title')?.value || '').trim(),
            default_summary: String(dayEl.querySelector('.js-day-default-summary')?.value || '').trim(),
            variants: variantEls.map((variantEl) => {{
              const questionEls = Array.from(variantEl.querySelectorAll(':scope .js-questions-root > .js-question'));
              return {{
                id: variantEl.querySelector('.js-variant-id')?.value ? Number(variantEl.querySelector('.js-variant-id').value) : null,
                level: String(variantEl.querySelector('.js-variant-level')?.value || 'build').trim(),
                content_item_id: variantEl.querySelector('.js-variant-content-item')?.value ? Number(variantEl.querySelector('.js-variant-content-item').value) : null,
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
            .filter((day) => day.day_index > 0 || day.concept_key || day.default_title || day.variants.some((variant) => variant.content_item_id || variant.takeaway_default));
          return {{ days }};
        }}

        function refreshContentSelectsWithinDay(dayEl) {{
          const day = collectDayData(dayEl);
          for (const variantEl of dayEl.querySelectorAll(':scope .js-variants-root > .js-variant')) {{
            const select = variantEl.querySelector('.js-variant-content-item');
            if (!select) continue;
            const variant = {{
              content_item_id: select.value ? Number(select.value) : null,
            }};
            select.outerHTML = renderContentSelect(day, variant);
          }}
        }}

        function seedDays() {{
          const duration = Math.max(1, Math.min(90, Number(durationInput.value || 21)));
          root.innerHTML = '';
          for (let index = 1; index <= duration; index += 1) {{
            root.insertAdjacentHTML('beforeend', renderDay(emptyDay(index)));
          }}
        }}

        function renderInitial() {{
          const days = Array.isArray(seed.days) ? [...seed.days] : [];
          if (!days.length) {{
            seedDays();
            return;
          }}
          root.innerHTML = days
            .sort((left, right) => Number(left.day_index || 0) - Number(right.day_index || 0))
            .map((day) => renderDay(day))
            .join('');
        }}

        document.getElementById('seed-days-button').addEventListener('click', seedDays);
        document.getElementById('add-day-button').addEventListener('click', function() {{
          const nextIndex = root.querySelectorAll(':scope > .js-day').length + 1;
          root.insertAdjacentHTML('beforeend', renderDay(emptyDay(nextIndex)));
        }});

        root.addEventListener('click', function(event) {{
          const target = event.target;
          if (!(target instanceof HTMLElement)) return;
          if (target.classList.contains('js-remove-day')) {{
            target.closest('.js-day')?.remove();
            return;
          }}
          if (target.classList.contains('js-add-variant')) {{
            const dayEl = target.closest('.js-day');
            if (!dayEl) return;
            const variantsRoot = dayEl.querySelector('.js-variants-root');
            if (!variantsRoot) return;
            variantsRoot.insertAdjacentHTML('beforeend', renderVariant(collectDayData(dayEl), emptyVariant()));
            return;
          }}
          if (target.classList.contains('js-remove-variant')) {{
            target.closest('.js-variant')?.remove();
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
            return;
          }}
          if (target.classList.contains('js-remove-question')) {{
            target.closest('.js-question')?.remove();
          }}
        }});

        root.addEventListener('change', function(event) {{
          const target = event.target;
          if (!(target instanceof HTMLElement)) return;
          if (target.classList.contains('js-day-concept')) {{
            const dayEl = target.closest('.js-day');
            if (!dayEl) return;
            const select = target;
            const match = conceptOptions.find((item) => String(item.code || '').toLowerCase() === String(select.value || '').toLowerCase());
            const labelInput = dayEl.querySelector('.js-day-concept-label');
            if (labelInput && !String(labelInput.value || '').trim() && match) {{
              labelInput.value = String(match.name || '').trim();
            }}
            refreshContentSelectsWithinDay(dayEl);
          }}
        }});

        pillarInput.addEventListener('change', function() {{
          const days = Array.from(root.querySelectorAll(':scope > .js-day')).map((dayEl) => collectDayData(dayEl));
          root.innerHTML = days.map((day) => renderDay(day)).join('');
        }});

        form.addEventListener('submit', function(event) {{
          try {{
            structureField.value = JSON.stringify(serializeStructure());
          }} catch (err) {{
            event.preventDefault();
            window.alert('Failed to prepare programme structure for saving.');
          }}
        }});

        renderInitial();
      }})();
    </script>
    <p class='nav' style='margin-top:16px;'><a href="/admin/education-programmes">Back to list</a></p>
    """
    return _wrap_page(title, body)


@admin.post("/education-programmes/save")
async def save_education_programme(
    id: int | None = Form(default=None),
    pillar_key: str = Form(...),
    code: str = Form(...),
    name: str = Form(...),
    duration_days: int = Form(default=21),
    is_active: str | None = Form(default=None),
    structure_json: str | None = Form(default=None),
):
    ensure_education_plan_schema()
    pillar_token = str(pillar_key or "").strip().lower()
    code_token = str(code or "").strip()
    name_text = str(name or "").strip()
    if pillar_token not in {"nutrition", "training", "resilience", "recovery"}:
        raise HTTPException(400, "pillar_key must be one of nutrition|training|resilience|recovery")
    if not code_token:
        raise HTTPException(400, "code is required")
    if not name_text:
        raise HTTPException(400, "name is required")
    resolved_duration = max(1, min(90, int(duration_days or 21)))
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
        concept_key = str(raw_day.get("concept_key") or "").strip().lower()
        if not day_index:
            continue
        if day_index in seen_day_indexes:
            raise HTTPException(400, f"Duplicate day_index: {day_index}")
        seen_day_indexes.add(day_index)
        if not concept_key:
            raise HTTPException(400, f"Day {day_index} requires concept_key")
        variants = raw_day.get("variants") if isinstance(raw_day.get("variants"), list) else []
        normalised_days.append(
            {
                "id": int(raw_day.get("id")) if raw_day.get("id") else None,
                "day_index": day_index,
                "concept_key": concept_key,
                "concept_label": str(raw_day.get("concept_label") or "").strip() or None,
                "lesson_goal": str(raw_day.get("lesson_goal") or "").strip() or None,
                "default_title": str(raw_day.get("default_title") or "").strip() or None,
                "default_summary": str(raw_day.get("default_summary") or "").strip() or None,
                "variants": variants,
            }
        )

    with SessionLocal() as s:
        row = s.get(EducationProgramme, id) if id else None
        if id and row is None:
            raise HTTPException(404, "Education programme not found")
        if row is None:
            row = EducationProgramme()
            s.add(row)
            s.flush()
        row.pillar_key = pillar_token
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
            day_row.concept_key = str(day_payload["concept_key"] or "").strip().lower()
            day_row.concept_label = day_payload.get("concept_label")
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
