"""
Prompt helpers for LLM interactions (structured, data-in/data-out; no DB calls).

Sections:
1) Structured prompt blocks (coach/user/context/OKR/scores/habit readiness/task)
2) Podcast prompts (kickoff/weekstart) built from blocks
3) Message prompts (weekstart support/actions, assessment/OKR/psych, assessor)

Index (helper → purpose → used by):
- podcast_prompt: kickoff, weekstart, Thursday, Friday podcast transcripts → kickoff.py, monday.py, thursday.py, friday.py
- coaching_prompt: unified coaching text prompts (weekstart_support, kickoff_support, weekstart_actions, midweek, tuesday, saturday, sunday)
- weekstart_support_prompt (legacy): weekstart support chat → monday.py
- kickoff_support_prompt (legacy): kickoff support chat → kickoff.py
- weekstart_actions_prompt (legacy): actions summary from podcast transcript → monday.py
- current_krs_context + helpers: fetch current focused KRs and derive payloads (list, primary, okrs_by_pillar) for all prompts
- coaching_approach_prompt: habit-readiness approach → reporting.py (_coaching_approach_text)
- assessment_scores_prompt: assessment score narrative → reporting.py (_score_narrative_from_llm)
- okr_narrative_prompt: OKR narrative → reporting.py (_okr_narrative_from_llm)
- assessment_narrative_prompt: assessment narrative → assessor.py
- assessor_system_prompt: assessor system message → assessor.py
- assessor_feedback_prompt: short feedback/next steps → assessor.py
- Blocks: context_block, okr_block, scores_block, habit_readiness_block, task_block, assemble_prompt

Callers should pass data only; keep LLM instructions here for reviewability.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import func, text, case

from .db import SessionLocal, engine, _is_postgres, _table_exists
from .debug_utils import debug_enabled
from .focus import select_top_krs_for_user
from .job_queue import enqueue_job, should_use_worker, ensure_prompt_settings_schema
from .models import OKRKeyResult, OKRObjective, OKRKrHabitStep, PromptTemplate, PromptSettings
from . import llm as shared_llm
from .models import LLMPromptLog, UsageEvent
from .usage import log_usage_event, estimate_tokens, estimate_llm_cost

PROMPT_STATE_ALIASES = {"production": "live", "stage": "beta"}
PROMPT_STATE_ORDER = ["live", "beta", "develop"]


def format_checkin_history(checkins: List[Dict[str, Any]]) -> str:
    """
    Render recent check-ins into a concise bullet list for prompt context.
    """
    if not checkins:
        return ""
    lines: List[str] = []
    for ci in checkins:
        ts = ci.get("created_at")
        ts_str = ts.isoformat(timespec="minutes") if ts else ""
        header = f"- {ci.get('touchpoint_type','check-in')}"
        if ts_str:
            header += f" @ {ts_str}"
        parts: List[str] = []
        for upd in ci.get("progress_updates") or []:
            desc = upd.get("note") or upd.get("actual") or upd
            if desc:
                parts.append(f"progress {desc}")
        for blk in ci.get("blockers") or []:
            desc = blk.get("note") if isinstance(blk, dict) else blk
            if desc:
                parts.append(f"blocker {desc}")
        for com in ci.get("commitments") or []:
            desc = com.get("note") if isinstance(com, dict) else com
            if desc:
                parts.append(f"commitment {desc}")
        if parts:
            header += " — " + "; ".join(str(p) for p in parts)
        lines.append(header)
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Structured prompt blocks (reusable building pieces)
# Each block is a simple text fragment; compose them with assemble_prompt.
# ---------------------------------------------------------------------------


LOCALE_GUIDANCE_UK = (
    "Use British English: UK spelling (favour, programme, behaviour), light British phrasing (have a think, check in, crack on), "
    "warm, calm, supportive tone; avoid Americanisms (vacation, sidewalk, awesome, mom); no US cultural refs."
)


@dataclass
class PromptAssembly:
    text: str
    blocks: Dict[str, str]
    variant: str
    task_label: str
    block_order: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


def common_prompt_header(coach_name: str, user_name: str, locale: str = "UK") -> str:
    """Shared tone/locale/persona guidance for all prompts (text and podcast)."""
    return (
        "Tone: supportive, conversational; speak directly to the user as their coach. "
        "Do not mention background music or sound effects. "
        "Do not read out section headers or labels; speak naturally as a flowing message. "
        "Do not read or say emoji names; ignore emoji. "
        f"Coach={coach_name}; User={user_name}; Locale={locale}."
    )


def context_block(
    interaction: str,
    purpose: str,
    timeframe: str = "",
    history: str = "",
    channel: str = "WhatsApp",
    extras: str = "",
) -> str:
    """Context of the interaction: type, purpose, channel, timeframe, history."""
    bits = [
        f"Interaction={interaction}",
        f"Purpose={purpose}",
        f"Channel={channel}",
    ]
    if timeframe:
        bits.append(f"Timeframe={timeframe}")
    if history:
        bits.append(f"History: {history}")
    if extras:
        bits.append(f"Extras: {extras}")
    return "Context: " + "; ".join(bits)


def okr_block(okrs_by_pillar: Dict[str, List[str]] | List[Dict[str, Any]], targets: Optional[Dict[str, Any]] = None) -> str:
    """OKR/KR snapshot: objectives/KRs and optional targets."""
    def _format_dict_entry(d: Dict[str, Any]) -> str:
        desc = d.get("description") or d.get("title") or ""
        tgt = d.get("target") or d.get("target_num") or d.get("target_text")
        actual = d.get("actual") or d.get("actual_num") or d.get("actual_text")
        bits = []
        if tgt is not None:
            bits.append(f"target {tgt}")
        if actual is not None:
            bits.append(f"now {actual}")
        steps = d.get("habit_steps") or []
        step_bits: List[str] = []
        if isinstance(steps, list):
            for step in steps:
                if isinstance(step, dict):
                    text_val = step.get("text") or step.get("step") or ""
                else:
                    text_val = str(step)
                text_val = text_val.strip()
                if text_val:
                    step_bits.append(text_val)
        if step_bits:
            bits.append("steps: " + "; ".join(step_bits))
        suffix = f" ({'; '.join(bits)})" if bits else ""
        return f"{desc}{suffix}".strip()

    formatted = ""
    if isinstance(okrs_by_pillar, dict):
        parts = []
        for pillar, items in okrs_by_pillar.items():
            if isinstance(items, list):
                rendered = []
                for item in items:
                    if isinstance(item, dict):
                        rendered.append(_format_dict_entry(item))
                    else:
                        rendered.append(str(item))
                parts.append(f"{pillar}: " + "; ".join(rendered))
            else:
                parts.append(f"{pillar}: {items}")
        formatted = " | ".join(parts)
    elif isinstance(okrs_by_pillar, list):
        rendered = []
        for item in okrs_by_pillar:
            if isinstance(item, dict):
                rendered.append(_format_dict_entry(item))
            else:
                rendered.append(str(item))
        formatted = "; ".join(rendered)
    else:
        formatted = str(okrs_by_pillar)

    tgt_txt = ""
    if targets:
        try:
            tgt_txt = f"; Targets: {targets}"
        except Exception:
            tgt_txt = ""
    return f"OKRs/KRs: {formatted}{tgt_txt}"


def okr_block_with_scope(scope: str, okrs: Any, targets: Optional[Dict[str, Any]] = None) -> tuple[str, Dict[str, Any]]:
    """
    Return (block_text, meta) where meta carries okr_scope for logging.
    scope: all | pillar | week | single
    """
    return okr_block(okrs, targets=targets), {"okr_scope": scope}


def programme_block_with_scope(scope: str, programme: Any, current_block: Any = None) -> str:
    """
    Render programme/current-block info according to scope.
    scope: full | pillar | none
    """
    scope = (scope or "").lower() or "none"
    if scope == "none":
        return ""
    if scope == "pillar":
        return f"Current block: {current_block}" if current_block else ""
    # full
    return f"Programme blocks: {programme}" if programme else ""


def scores_block(pillar_scores: List[Dict[str, Any]], combined: Optional[int] = None) -> str:
    """Assessment scores: per-pillar (and combined if provided)."""
    return f"Pillar scores: {pillar_scores}; Combined: {combined}" if combined is not None else f"Pillar scores: {pillar_scores}"


def habit_readiness_block(psych_payload: Dict[str, Any]) -> str:
    """Habit readiness / psych flags and parameters."""
    return f"Habit readiness: {psych_payload}"


def locale_block(locale: str) -> str:
    """Locale-specific instructions (e.g., spelling/tone)."""
    if locale.upper() == "UK":
        return LOCALE_GUIDANCE_UK
    return f"Locale: {locale}"


def task_block(instruction: str, length_hint: str = "", constraints: str = "") -> str:
    """Task directive: what to produce, optional length and constraints."""
    parts = [f"Task: {instruction}"]
    if length_hint:
        parts.append(f"Length: {length_hint}")
    if constraints:
        parts.append(f"Constraints: {constraints}")
    return " ".join(parts)


def assemble_prompt(blocks: List[str]) -> str:
    """Join non-empty blocks with newlines."""
    return "\n".join([b for b in blocks if b])


def history_block(label: str, entries: List[str]) -> str:
    """Render conversation or check-in history as a labeled block."""
    if not entries:
        return ""
    return context_block("history", label, extras="\n".join(entries))


# ---------------------------------------------------------------------------
# Prompt logging helpers
# ---------------------------------------------------------------------------

DEFAULT_PROMPT_BLOCK_ORDER = [
    "system",
    "locale",
    "context",
    "history",
    "programme",
    "okr",
    "scores",
    "habit",
    "assessor",
    "task",
    "user",
]

_BANNED_BLOCKS = {"developer", "policy", "tool"}

def _normalize_block_labels(labels: Any) -> list[str]:
    if not labels or not isinstance(labels, list):
        return []
    cleaned: list[str] = []
    for lbl in labels:
        if lbl is None:
            continue
        txt = str(lbl).strip()
        if not txt:
            continue
        # Tolerate legacy stringified list items like "['system'".
        txt = txt.replace("[", "").replace("]", "").replace('"', "").replace("'", "").strip()
        if txt:
            cleaned.append(txt)
    return cleaned

def _canonical_state(state: Optional[str]) -> Optional[str]:
    if not state:
        return None
    return PROMPT_STATE_ALIASES.get(state, state)


def _state_priority_expr():
    return case(
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


def _merge_template_meta(meta: Optional[Dict[str, Any]], template: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(meta or {})
    if template:
        state = _canonical_state(template.get("state"))
        if state:
            merged["template_state"] = state
        version = template.get("version")
        if version is not None:
            merged["template_version"] = version
    return merged


def _apply_prompt_template(parts: List[tuple[str, str]], template: Optional[Dict[str, Any]]) -> tuple[List[tuple[str, str]], Optional[List[str]]]:
    """
    Apply template overrides (system/locale/task), include list, and block order.
    Returns (parts, block_order_override).
    """
    if not template:
        return parts, None

    include_blocks = _normalize_block_labels(template.get("include_blocks")) or None
    if include_blocks:
        include_blocks = [b for b in include_blocks if b not in _BANNED_BLOCKS] or None
        # Always include foundational blocks if a template specifies an include list.
        if include_blocks:
            for required in ("system", "locale"):
                if required not in include_blocks:
                    include_blocks = [required, *include_blocks]
    order_override = _normalize_block_labels(template.get("block_order"))
    if order_override:
        order_override = [b for b in order_override if b not in _BANNED_BLOCKS]
        for required in ("system", "locale"):
            if required not in order_override:
                order_override = [required, *order_override]
    programme_scope = template.get("programme_scope")
    overrides: Dict[str, Optional[str]] = {
        "task": template.get("task_block"),
    }
    new_parts: List[tuple[str, str]] = []
    for label, txt in parts:
        if label in _BANNED_BLOCKS:
            continue
        val = overrides.get(label, txt)
        if include_blocks and label not in include_blocks:
            continue
        if val:
            new_parts.append((label, val))

    if order_override:
        order_index = {lbl: idx for idx, lbl in enumerate(order_override)}
        new_parts.sort(key=lambda p: order_index.get(p[0], len(order_index)))

    return new_parts, order_override if order_override else None


def _template_prompt_with_data(
    touchpoint: str,
    user_name: str,
    locale: str,
    context_label: str,
    data_payload: Any,
    default_task: str,
    persona: str = "Coach",
) -> PromptAssembly:
    """
    Build a simple prompt using global settings + template overrides with a JSON data block.
    Returns assembled prompt text.
    """
    settings = _load_prompt_settings()
    template = _load_prompt_template(touchpoint)
    sys_block = settings.get("system_block") or common_prompt_header(persona, user_name, locale)
    loc_block = settings.get("locale_block") or locale_block(locale)
    parts = [
        ("system", sys_block),
        ("locale", loc_block),
        ("context", f"Context: {context_label}"),
        ("data", f"Data (JSON): {json.dumps(data_payload, ensure_ascii=False)}" if data_payload is not None else ""),
        ("task", (template or {}).get("task_block") or default_task),
    ]
    parts, order_override = _apply_prompt_template(parts, template)
    meta = _merge_template_meta({}, template)
    assembly = _prompt_assembly(
        touchpoint,
        touchpoint,
        parts,
        meta=meta,
        block_order_override=order_override or settings.get("default_block_order"),
    )
    return assembly


def _load_prompt_template(touchpoint: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a prompt template row for this touchpoint (if any), preferring live > beta > develop.
    """
    try:
        PromptTemplate.__table__.create(bind=engine, checkfirst=True)
        try:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS programme_scope varchar(32);"))
                conn.execute(text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS response_format varchar(32);"))
                conn.execute(text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS state varchar(32) DEFAULT 'develop';"))
                conn.execute(text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS version integer DEFAULT 1;"))
                conn.execute(text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS note text;"))
                conn.execute(text("ALTER TABLE prompt_templates ADD COLUMN IF NOT EXISTS parent_id integer;"))
                # Relax legacy unique constraint on touchpoint to allow multi-state/version rows
                try:
                    conn.execute(text("ALTER TABLE prompt_templates DROP CONSTRAINT IF EXISTS prompt_templates_touchpoint_key;"))
                except Exception:
                    pass
                try:
                    conn.execute(text("DROP INDEX IF EXISTS prompt_templates_touchpoint_key;"))
                except Exception:
                    pass
                try:
                    conn.execute(text("DROP INDEX IF EXISTS uq_prompt_templates_touchpoint;"))
                except Exception:
                    pass
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_prompt_templates_touchpoint_state_version ON prompt_templates(touchpoint, state, version);"))
                # Map legacy state labels to new ones
                conn.execute(text("UPDATE prompt_templates SET state='beta' WHERE state='stage';"))
                conn.execute(text("UPDATE prompt_templates SET state='live' WHERE state='production';"))
                conn.execute(text("UPDATE prompt_templates SET version=1 WHERE version IS NULL;"))
                conn.commit()
        except Exception:
            pass
        with SessionLocal() as s:
            row = (
                s.query(PromptTemplate)
                .filter(PromptTemplate.touchpoint == touchpoint, PromptTemplate.is_active == True)
                .order_by(
                    _state_priority_expr(),
                    PromptTemplate.version.desc(),
                    PromptTemplate.id.desc(),
                )
                .first()
            )
            if not row:
                return None
            state_val = _canonical_state(getattr(row, "state", None))
            return {
                "task_block": getattr(row, "task_block", None),
                "block_order": getattr(row, "block_order", None),
                "include_blocks": getattr(row, "include_blocks", None),
                "okr_scope": getattr(row, "okr_scope", None),
                "programme_scope": getattr(row, "programme_scope", None),
                "response_format": getattr(row, "response_format", None),
                "state": state_val,
                "version": getattr(row, "version", None),
            }
    except Exception as e:
        print(f"[prompts] WARN: failed to load prompt template for {touchpoint}: {e}")
        return None


def _load_prompt_template_with_state(touchpoint: str, state: str) -> Optional[Dict[str, Any]]:
    """
    Fetch a prompt template row for this touchpoint with explicit state (if any).
    """
    target_state = _canonical_state(state)
    try:
        PromptTemplate.__table__.create(bind=engine, checkfirst=True)
        with SessionLocal() as s:
            row = (
                s.query(PromptTemplate)
                .filter(
                    PromptTemplate.touchpoint == touchpoint,
                    PromptTemplate.is_active == True,
                    PromptTemplate.state.in_(
                        [
                            target_state,
                            "stage" if target_state == "beta" else target_state,
                            "production" if target_state == "live" else target_state,
                        ]
                    ),
                )
                .order_by(PromptTemplate.version.desc(), PromptTemplate.id.desc())
                .first()
            )
            if not row:
                return _load_prompt_template(touchpoint)
            state_val = _canonical_state(getattr(row, "state", None))
            return {
                "task_block": getattr(row, "task_block", None),
                "block_order": getattr(row, "block_order", None),
                "include_blocks": getattr(row, "include_blocks", None),
                "okr_scope": getattr(row, "okr_scope", None),
                "programme_scope": getattr(row, "programme_scope", None),
                "response_format": getattr(row, "response_format", None),
                "state": state_val,
                "version": getattr(row, "version", None),
            }
    except Exception:
        return _load_prompt_template(touchpoint)


def _load_prompt_settings() -> Dict[str, Any]:
    """
    Load global prompt settings (singleton). Falls back to defaults if missing.
    """
    defaults = {
        "system_block": None,
        "locale_block": None,
        "default_block_order": DEFAULT_PROMPT_BLOCK_ORDER,
    }
    try:
        ensure_prompt_settings_schema()
    except Exception:
        return defaults
    try:
        with SessionLocal() as s:
            row = s.query(PromptSettings).order_by(PromptSettings.id.asc()).first()
            if not row:
                return defaults
            order = getattr(row, "default_block_order", None) or DEFAULT_PROMPT_BLOCK_ORDER
            order = [b for b in order if b not in _BANNED_BLOCKS]
            data = {
                "system_block": getattr(row, "system_block", None),
                "locale_block": getattr(row, "locale_block", None),
                "default_block_order": order or DEFAULT_PROMPT_BLOCK_ORDER,
            }
            return data
    except Exception as e:
        print(f"[prompts] WARN: failed to load prompt settings: {e}")
        return defaults


def _prompt_assembly(
    variant: str,
    task_label: Optional[str],
    parts: List[tuple[str, str]],
    meta: Optional[Dict[str, Any]] = None,
    block_order_override: Optional[List[str]] = None,
) -> PromptAssembly:
    """
    Build PromptAssembly from labeled parts while preserving order.
    parts: list of (label, text) pairs; empty/falsey texts are skipped.
    """
    filtered = [(lbl, txt) for lbl, txt in parts if txt]
    block_order = block_order_override or [lbl for lbl, _ in filtered]
    blocks = {lbl: txt for lbl, txt in filtered}
    return PromptAssembly(
        text=assemble_prompt([txt for _, txt in filtered]),
        blocks=blocks,
        variant=variant,
        task_label=task_label or variant,
        block_order=block_order,
        meta=meta or {},
    )


def _normalize_prompt_blocks(
    prompt_blocks: Optional[Dict[str, str]],
    preferred_order: Optional[List[str]] = None,
) -> tuple[Dict[str, str], Dict[str, str], List[str], str]:
    """
    Split prompt_blocks into known buckets + extras, capture the order, and assemble text.
    Returns (known_blocks, extra_blocks, order, assembled_text).
    """
    prompt_blocks = prompt_blocks or {}
    order_template = preferred_order or DEFAULT_PROMPT_BLOCK_ORDER

    ordered_labels: List[str] = []
    known_blocks: Dict[str, str] = {}
    extra_blocks: Dict[str, str] = {}

    for label in order_template:
        val = prompt_blocks.get(label)
        if val is not None:
            sval = str(val)
            ordered_labels.append(label)
            known_blocks[label] = sval

    for label, val in prompt_blocks.items():
        if val is None or label in ordered_labels:
            continue
        sval = str(val)
        ordered_labels.append(label)
        extra_blocks[label] = sval

    assembled = assemble_prompt([str(prompt_blocks[l]) for l in ordered_labels if prompt_blocks.get(l) is not None])
    return known_blocks, extra_blocks, ordered_labels, assembled


# Avoid running schema alterations on every prompt log.
_LLM_PROMPT_SCHEMA_READY = False
_LLM_PROMPT_SCHEMA_LOCK = threading.Lock()


def _ensure_llm_prompt_log_schema() -> None:
    """
    Idempotently add new prompt-block columns and a reviewer-friendly view.
    Keeps compatibility for existing deployments without migrations.
    """
    global _LLM_PROMPT_SCHEMA_READY
    if _LLM_PROMPT_SCHEMA_READY:
        return
    with _LLM_PROMPT_SCHEMA_LOCK:
        if _LLM_PROMPT_SCHEMA_READY:
            return
        try:
            LLMPromptLog.__table__.create(bind=engine, checkfirst=True)
        except Exception as e:
            print(f"[prompts] ensure llm_prompt_logs failed: {e}")

        with engine.begin() as conn:
            if not _table_exists(conn, "llm_prompt_logs"):
                _LLM_PROMPT_SCHEMA_READY = True
                return

            is_pg = _is_postgres()
            alterations = [
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS prompt_variant varchar(160);",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS task_label varchar(160);",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS system_block text;",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS locale_block text;",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS okr_block text;",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS okr_scope varchar(32);",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS scores_block text;",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS habit_block text;",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS task_block text;",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS user_block text;",
                (
                    "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS extra_blocks jsonb;"
                    if is_pg
                    else "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS extra_blocks text;"
                ),
                (
                    "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS block_order jsonb;"
                    if is_pg
                    else "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS block_order text;"
                ),
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS assembled_prompt text;",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS template_state varchar(32);",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS template_version integer;",
                "ALTER TABLE llm_prompt_logs ADD COLUMN IF NOT EXISTS duration_ms integer;",
            ]

            for stmt in alterations:
                try:
                    conn.execute(text(stmt))
                except Exception as e:
                    # Ignore duplicate-column or dialect errors; log for visibility.
                    print(f"[prompts] WARN: alter llm_prompt_logs skipped ({stmt}): {e}")

            # Attempt to drop deprecated columns (best-effort; ignore failures)
            for drop_col in ["developer_block", "policy_block", "tool_block"]:
                try:
                    conn.execute(text(f"ALTER TABLE llm_prompt_logs DROP COLUMN IF EXISTS {drop_col};"))
                except Exception as e:
                    print(f"[prompts] WARN: drop column skipped ({drop_col}): {e}")

            if is_pg:
                view_sql = """
                    CREATE OR REPLACE VIEW llm_prompt_logs_view AS
                    SELECT
                        l.id,
                        l.created_at,
                        l.touchpoint,
                        l.user_id,
                        l.model,
                        l.duration_ms,
                        l.prompt_variant,
                        l.task_label,
                        COALESCE(l.block_order, '["system","locale","context","history","programme","okr","scores","habit","assessor","task","user"]'::jsonb) AS block_order,
                        l.system_block,
                        l.locale_block,
                        l.okr_block,
                        l.okr_scope,
                        l.scores_block,
                        l.habit_block,
                        l.task_block,
                        l.template_state,
                        l.template_version,
                        l.user_block,
                        l.extra_blocks,
                        COALESCE(l.assembled_prompt, l.prompt_text) AS assembled_prompt,
                        l.response_preview,
                        l.context_meta
                    FROM llm_prompt_logs l
                    ORDER BY l.created_at DESC;
                """
            else:
                sqlite_view_sql = """
                    CREATE VIEW IF NOT EXISTS llm_prompt_logs_view AS
                    SELECT
                        l.id,
                        l.created_at,
                        l.touchpoint,
                        l.user_id,
                        l.model,
                        l.duration_ms,
                        l.prompt_variant,
                        l.task_label,
                        COALESCE(l.block_order, json('["system","locale","context","history","programme","okr","scores","habit","assessor","task","user"]')) AS block_order,
                        l.system_block,
                        l.locale_block,
                        l.okr_block,
                        l.okr_scope,
                        l.scores_block,
                        l.habit_block,
                        l.task_block,
                        l.template_state,
                        l.template_version,
                        l.user_block,
                        l.extra_blocks,
                        COALESCE(l.assembled_prompt, l.prompt_text) AS assembled_prompt,
                        l.response_preview,
                        l.context_meta
                    FROM llm_prompt_logs l
                    ORDER BY l.created_at DESC;
                """

            try:
                if is_pg:
                    conn.execute(text(view_sql))
                else:
                    conn.execute(text("DROP VIEW IF EXISTS llm_prompt_logs_view;"))
                    conn.execute(text(sqlite_view_sql))
            except Exception as e:
                print(f"[prompts] WARN: could not create llm_prompt_logs_view: {e}")

        _LLM_PROMPT_SCHEMA_READY = True


# ---------------------------------------------------------------------------
# KR context helper (shared across prompts)
# ---------------------------------------------------------------------------


def current_krs_context(
    user_id: int,
    week_no: Optional[int] = None,
    max_krs: Optional[int] = 3,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """
    Return the current focused KRs (active, current pillar) for prompt builders.
    Uses select_top_krs_for_user to pick 2–3 active KRs on the current pillar.
    Returns dict with: krs (ordered list), krs_by_pillar, primary_kr.
    """
    owns_session = session is None
    session = session or SessionLocal()
    try:
        selected = select_top_krs_for_user(session, user_id, limit=max_krs, week_no=week_no)
        kr_ids = [kr_id for kr_id, _ in selected]
        rows: list[Any] = []
        if kr_ids:
            rows = (
                session.query(OKRKeyResult, OKRObjective)
                .join(OKRObjective, OKRKeyResult.objective_id == OKRObjective.id)
                .filter(OKRKeyResult.id.in_(kr_ids))
                .all()
            )
        steps_by_kr: Dict[int, List[str]] = {}
        if kr_ids:
            step_rows = (
                session.query(OKRKrHabitStep)
                .filter(OKRKrHabitStep.user_id == user_id, OKRKrHabitStep.kr_id.in_(kr_ids))
                .filter(OKRKrHabitStep.status != "archived")
                .order_by(
                    OKRKrHabitStep.kr_id.asc(),
                    OKRKrHabitStep.week_no.asc().nullslast(),
                    OKRKrHabitStep.sort_order.asc(),
                    OKRKrHabitStep.id.asc(),
                )
                .all()
            )
            for step in step_rows:
                if not step.step_text:
                    continue
                steps_by_kr.setdefault(step.kr_id, []).append(step.step_text)

        order_map = {kr_id: idx for idx, kr_id in enumerate(kr_ids)}
        krs: List[Dict[str, Any]] = []
        for idx, row in enumerate(rows):
            kr, obj = row
            priority = order_map.get(kr.id, idx)
            pillar = (getattr(obj, "pillar_key", None) or "").lower()
            krs.append(
                {
                    "id": kr.id,
                    "description": kr.description,
                    "target": getattr(kr, "target_num", None),
                    "actual": getattr(kr, "actual_num", None),
                    "status": getattr(kr, "status", None),
                    "pillar": pillar,
                    "priority": priority,
                    "habit_steps": steps_by_kr.get(int(kr.id), []),
                }
            )
        krs.sort(key=lambda x: x["priority"])
        if max_krs is not None:
            krs = krs[:max_krs]
        krs_by_pillar: Dict[str, List[Dict[str, Any]]] = {}
        for kr in krs:
            krs_by_pillar.setdefault(kr["pillar"], []).append(
                {
                    "description": kr.get("description"),
                    "target": kr.get("target"),
                    "actual": kr.get("actual"),
                    "habit_steps": kr.get("habit_steps") or [],
                }
            )
        primary = krs[0] if krs else None
        return {
            "krs": krs,
            "krs_by_pillar": krs_by_pillar,
            "primary_kr": primary,
        }
    finally:
        if owns_session:
            session.close()


def kr_payload_list(
    user_id: int,
    week_no: Optional[int] = None,
    max_krs: Optional[int] = 3,
    session: Optional[Session] = None,
) -> List[Dict[str, Any]]:
    """Convenience wrapper: list of KR payload dicts for prompts."""
    ctx = current_krs_context(user_id, week_no=week_no, max_krs=max_krs, session=session)
    return ctx.get("krs", [])


def primary_kr_payload(
    user_id: int,
    week_no: Optional[int] = None,
    session: Optional[Session] = None,
) -> Dict[str, Any]:
    """Convenience wrapper: single primary KR payload dict (or empty dict)."""
    ctx = current_krs_context(user_id, week_no=week_no, max_krs=1, session=session)
    return ctx.get("primary_kr") or {}


def okrs_by_pillar_payload(
    user_id: int,
    week_no: Optional[int] = None,
    max_krs: Optional[int] = 3,
    session: Optional[Session] = None,
) -> Dict[str, List[str]]:
    """Convenience wrapper: pillar→KR descriptions mapping for podcast prompts."""
    ctx = current_krs_context(user_id, week_no=week_no, max_krs=max_krs, session=session)
    return ctx.get("krs_by_pillar", {})


def _krs_for_okr_scope(
    *,
    okr_scope: str,
    user_id: int,
    week_no: Optional[int] = None,
    primary: Optional[Dict[str, Any]] = None,
    max_krs: Optional[int] = None,
    fallback_krs: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if okr_scope == "week":
        return kr_payload_list(user_id, week_no=week_no, max_krs=None)
    if okr_scope == "pillar" and primary:
        pillar_key = (primary.get("pillar") or "").lower()
        if pillar_key:
            all_krs = kr_payload_list(user_id, week_no=week_no, max_krs=None)
            pillar_krs = [item for item in all_krs if (item.get("pillar") or "").lower() == pillar_key]
            if pillar_krs:
                return pillar_krs
    if fallback_krs is not None:
        return fallback_krs
    return kr_payload_list(user_id, week_no=week_no, max_krs=max_krs)


# ---------------------------------------------------------------------------
# Central dispatcher / LLM runner
# ---------------------------------------------------------------------------


def build_prompt(
    touchpoint: str,
    user_id: int,
    coach_name: str,
    user_name: str,
    locale: str = "UK",
    use_state: Optional[str] = None,
    **data,
) -> PromptAssembly:
    """
    Central prompt builder. touchpoint options:
    - podcast_weekstart
    - podcast_thursday
    - podcast_friday
    - weekstart_support
    - general_support
    - kickoff_support
    - weekstart_actions
    - sunday_actions
    - sunday_support
    - tuesday
    - midweek
    - saturday
    - sunday
    """
    tp = touchpoint.lower()
    settings = _load_prompt_settings()
    preferred_state = _canonical_state(use_state or "live")
    if preferred_state in {"live", None}:
        try:
            with SessionLocal() as s:
                pref = (
                    s.query(UserPreference)
                    .filter(UserPreference.user_id == user_id, UserPreference.key == "prompt_state_override")
                    .first()
                )
                if pref and (pref.value or "").strip().lower() in {"live", "beta", "develop"}:
                    preferred_state = (pref.value or "").strip().lower()
        except Exception:
            pass
    template = _load_prompt_template(tp) if not preferred_state else _load_prompt_template_with_state(tp, preferred_state)
    if tp == "podcast_weekstart":
        scores = data.get("scores", [])
        psych_payload = data.get("psych_payload", {})
        first_block = data.get("first_block")
        okrs_by_pillar = okrs_by_pillar_payload(user_id, week_no=data.get("week_no"), max_krs=None)
        history_text = data.get("history_text", "")
        okr_scope = (template or {}).get("okr_scope") or "pillar"
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, okrs_by_pillar)
        programme_scope = (template or {}).get("programme_scope") or "pillar"
        programme_txt = programme_block_with_scope(programme_scope, data.get("programme"), first_block)
        instruction = (
            "You are a warm, concise wellbeing coach creating a 2–3 minute weekly audio brief (around 300–450 words). "
            "Focus on the current 3-week block: explain why each KR matters, and give 2–3 simple suggestions to start this week. "
            "Include: welcome, quick assessment nod, habit readiness nod, this block’s dates and pillar, "
            "KR highlights for this block, practical Week 1 ideas, and a short motivational close. "
            "Keep it tight; do not exceed 450 words."
        )
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("podcast_weekstart", "weekly audio brief", timeframe=data.get("week_no") or "")),
            ("task", instruction),
            ("scores", f"Assessment scores: {scores}" if scores else ""),
            ("habit", f"Habit readiness: {psych_payload}" if psych_payload else ""),
            ("history", f"History: {history_text}" if history_text else ""),
            ("programme", programme_txt),
            ("okr", okr_txt),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "podcast_weekstart",
            "weekstart_podcast",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "podcast_kickoff":
        scores = data.get("scores", [])
        psych_payload = data.get("psych_payload", {})
        programme = data.get("programme", [])
        okrs_by_pillar = data.get("okrs_by_pillar", {})
        okr_scope = (template or {}).get("okr_scope") or "all"
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, okrs_by_pillar) if okrs_by_pillar else ("", {})
        programme_scope = (template or {}).get("programme_scope") or "full"
        programme_txt = programme_block_with_scope(programme_scope, programme, data.get("first_block"))
        instruction = (
            "You are a warm, concise wellbeing coach creating a 2–3 minute kickoff audio intro. "
            "Write a transcript with: 1) welcome & personal context; 2) assessment findings summary (per pillar); "
            "3) habit readiness summary (from psych profile); 4) 12-week plan overview (3-week blocks by pillar); "
            "5) how to use the plan this week; 6) closing encouragement."
        )
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("podcast_kickoff", "kickoff audio intro")),
            ("task", instruction),
            ("scores", f"Assessment scores: {scores}" if scores else ""),
            ("habit", f"Habit readiness: {psych_payload}" if psych_payload else ""),
            ("programme", programme_txt),
            ("okr", okr_txt),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "podcast_kickoff",
            "kickoff_podcast",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "podcast_thursday":
        kr = primary_kr_payload(user_id, week_no=data.get("week_no"))
        okr_scope = (template or {}).get("okr_scope") or "week"
        krs = _krs_for_okr_scope(
            okr_scope=okr_scope,
            user_id=user_id,
            week_no=data.get("week_no"),
            primary=kr or None,
            fallback_krs=[kr] if kr else [],
        )
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, krs)
        instruction = (
            "You are a warm, concise wellbeing coach creating a short Thursday check-in podcast (~45–60s). "
            "Write a script with: 1) quick check-in; 2) one focused goal recap (no OKR/KR jargon); "
            "3) one simple action to try before the weekend; 4) short encouragement. No medical advice."
        )
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("podcast_thursday", "thursday boost")),
            ("task", instruction),
            ("okr", okr_txt),
            ("history", f"History: {data.get('history_text','')}" if data.get("history_text") else ""),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "podcast_thursday",
            "thursday_podcast",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "podcast_friday":
        kr = primary_kr_payload(user_id, week_no=data.get("week_no"))
        okr_scope = (template or {}).get("okr_scope") or "week"
        krs = _krs_for_okr_scope(
            okr_scope=okr_scope,
            user_id=user_id,
            week_no=data.get("week_no"),
            primary=kr or None,
            fallback_krs=[kr] if kr else [],
        )
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, krs)
        instruction = (
            "You are a warm, concise wellbeing coach creating a short Friday boost podcast (~45–60s). "
            "Write a script that: 1) friendly check-in; 2) encourage ONE focus goal in plain language (no OKR/KR terms); "
            "3) give ONE simple, realistic action they can do over the weekend; 4) keep it brief, motivating, and specific; 5) no medical advice."
        )
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("podcast_friday", "friday boost")),
            ("task", instruction),
            ("okr", okr_txt),
            ("history", f"History: {data.get('history_text','')}" if data.get("history_text") else ""),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "podcast_friday",
            "friday_podcast",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "weekstart_support":
        history = "\n".join(data.get("history", []))
        payload = kr_payload_list(user_id, max_krs=3)
        scores_payload = data.get("scores") or []
        psych_payload = data.get("psych_payload") or {}
        okr_scope = (template or {}).get("okr_scope") or "week"
        primary = payload[0] if payload else None
        krs = _krs_for_okr_scope(
            okr_scope=okr_scope,
            user_id=user_id,
            week_no=data.get("week_no"),
            primary=primary,
            fallback_krs=payload,
        )
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, krs)
        parts: List[tuple[str, str]] = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("weekstart", "support chat")),
            ("okr", okr_txt),
            ("scores", scores_block(scores_payload) if scores_payload else ""),
            ("habit", habit_readiness_block(psych_payload) if psych_payload else ""),
            ("history", history_block("conversation", history.splitlines()) if history else ""),
            (
                "task",
                task_block(
                    "Reply with 2-3 practical ideas or next steps for this week. "
                    "If proposed habit steps are shown in the KR context, ask the user to confirm or suggest edits so you can set them.",
                    constraints="Do not assume progress; avoid praise/commands; do not suggest more sessions than KR targets; keep it conversational.",
                ),
            ),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "weekstart_support",
            "weekstart_support_reply",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "general_support":
        history = "\n".join(data.get("history", []))
        scores_payload = data.get("scores") or []
        psych_payload = data.get("psych_payload") or {}
        okr_scope = (template or {}).get("okr_scope") or "week"
        payload = kr_payload_list(user_id, max_krs=3)
        primary = payload[0] if payload else None
        krs = _krs_for_okr_scope(
            okr_scope=okr_scope,
            user_id=user_id,
            week_no=data.get("week_no"),
            primary=primary,
            fallback_krs=payload,
        )
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, krs)
        timeframe = data.get("timeframe", "")
        extras = data.get("extras", "")
        parts: List[tuple[str, str]] = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("general_support", "open coaching support", timeframe=timeframe, extras=extras)),
            ("okr", okr_txt),
            ("scores", scores_block(scores_payload) if scores_payload else ""),
            ("habit", habit_readiness_block(psych_payload) if psych_payload else ""),
            ("history", history_block("conversation", history.splitlines()) if history else ""),
            (
                "task",
                task_block(
                    "Reply with a brief acknowledgement, one practical next step tied to their current habits or goals, "
                    "and one short follow-up question.",
                    constraints="Keep it concise (2-4 short sentences), warm, calm, supportive. Avoid OKR/KR jargon; do not introduce new goals unless asked.",
                ),
            ),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "general_support",
            "general_support_reply",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "weekstart_actions":
        transcript = data.get("transcript", "")
        krs = data.get("krs", [])
        okr_scope = (template or {}).get("okr_scope") or "week"
        primary = krs[0] if krs else None
        okr_txt, okr_meta = okr_block_with_scope(
            okr_scope,
            _krs_for_okr_scope(
                okr_scope=okr_scope,
                user_id=user_id,
                week_no=data.get("week_no"),
                primary=primary,
                fallback_krs=krs,
            ),
        )
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("weekstart_actions", "actions summary")),
            ("okr", okr_txt),
            ("task",
                "You are a concise wellbeing coach. Using the podcast transcript and the KR context, "
                "write a short intro plus 3 habit step options per KR using this exact format:\n"
                "KR1: <short KR description>\n"
                "1A) <habit step option>\n"
                "1B) <habit step option>\n"
                "1C) <habit step option>\n"
                "KR2: ...\n"
                "2A) ...\n"
                "2B) ...\n"
                "2C) ...\n"
                "Intro should say: 'As per the podcast, here are practical actions for this week:' "
                "Keep options practical, low-pressure, and easy to start this week. "
                "Each option must be a concrete, observable habit (avoid meta-instructions like "
                "'pick the smallest version' or 'schedule one simple step'). "
                "Use British English spelling and phrasing; avoid Americanisms. "
                "Do not add any closing instruction lines."
            ),
            ("history", f"Transcript: {transcript}"),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "weekstart_actions",
            "weekstart_actions",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "sunday_actions":
        review_mode = (data.get("review_mode") or "kr").strip().lower()
        timeframe = data.get("timeframe", "Sunday")
        okr_scope = (template or {}).get("okr_scope") or "week"
        fallback_krs = data.get("krs")
        primary = None
        if isinstance(fallback_krs, list) and fallback_krs:
            primary = fallback_krs[0]
        okr_txt, okr_meta = okr_block_with_scope(
            okr_scope,
            _krs_for_okr_scope(
                okr_scope=okr_scope,
                user_id=user_id,
                week_no=data.get("week_no"),
                primary=primary,
                fallback_krs=fallback_krs,
            ),
        )
        habit_steps = data.get("habit_steps", "")
        if review_mode == "habit":
            task_text = (
                "Write a short Sunday check-in focused on habit steps for the week. "
                "Ask how the habit steps went in plain language (no KR/OKR jargon). "
                "Ask what helped and what got in the way, and invite them to tweak any steps."
            )
        else:
            task_text = (
                "Write a short Sunday check-in asking for numeric updates on each goal. "
                "Ask what worked well and what didn’t work well or made things harder. "
                "End by saying you’ll summarise and prep Monday’s kickoff."
            )
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("sunday", "weekly review", timeframe=timeframe)),
            ("okr", okr_txt),
        ]
        if habit_steps:
            parts.append(("history", f"Habit steps:\n{habit_steps}"))
        parts.append(("task", task_text))
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "sunday_actions",
            "sunday_actions",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "sunday_support":
        review_mode = (data.get("review_mode") or "kr").strip().lower()
        timeframe = data.get("timeframe", "Sunday")
        history = data.get("history", "")
        okr_scope = (template or {}).get("okr_scope") or "week"
        fallback_krs = data.get("krs")
        primary = None
        if isinstance(fallback_krs, list) and fallback_krs:
            primary = fallback_krs[0]
        okr_txt, okr_meta = okr_block_with_scope(
            okr_scope,
            _krs_for_okr_scope(
                okr_scope=okr_scope,
                user_id=user_id,
                week_no=data.get("week_no"),
                primary=primary,
                fallback_krs=fallback_krs,
            ),
        )
        if review_mode == "habit":
            task_text = (
                "Reply to the user’s habit-step check-in. "
                "Acknowledge what they shared, suggest one tweak if helpful, and ask one follow-up question. "
                "Keep it brief, warm, and plain language."
            )
        else:
            task_text = (
                "Reply to the user’s update on their goals. "
                "Acknowledge, ask one focused follow-up (blocker or next step), and keep it short and supportive."
            )
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("sunday", "weekly review follow-up", timeframe=timeframe)),
            ("okr", okr_txt),
            ("history", history_block("conversation", history.splitlines()) if history else ""),
            ("task", task_text),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "sunday_support",
            "sunday_support",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "tuesday":
        kr = primary_kr_payload(user_id)
        timeframe = data.get("timeframe", "Tuesday")
        history_text = data.get("history_text", "")
        scores_payload = data.get("scores") or []
        psych_payload = data.get("psych_payload") or {}
        okr_scope = (template or {}).get("okr_scope") or "week"
        krs = _krs_for_okr_scope(
            okr_scope=okr_scope,
            user_id=user_id,
            week_no=data.get("week_no"),
            primary=kr or None,
            fallback_krs=[kr] if kr else [],
        )
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, krs) if krs else ("", {})
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("tuesday", "micro-check", timeframe=timeframe)),
            ("history", history_block("recent check-ins", history_text.splitlines()) if history_text else ""),
            ("scores", scores_block(scores_payload, combined=data.get("combined_score")) if scores_payload else ""),
            ("habit", habit_readiness_block(psych_payload) if psych_payload else ""),
            ("okr", okr_txt),
            (
                "task",
                task_block(
                    "Write a very short check-in asking how they’re doing on this goal. "
                    "Ask for a simple yes/no or number. Offer one actionable nudge. "
                    "Keep it friendly, low-burden, WhatsApp length, plain language (no OKR/KR terms).",
                    constraints="Avoid medical advice; avoid jargon; focus on one goal; be concise.",
                ),
            ),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "tuesday",
            "tuesday_micro_check",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "midweek":
        kr = primary_kr_payload(user_id)
        timeframe = data.get("timeframe", "midweek check")
        history_text = data.get("history_text", "")
        scores_payload = data.get("scores") or []
        psych_payload = data.get("psych_payload") or {}
        okr_scope = (template or {}).get("okr_scope") or "week"
        krs_for_okr = _krs_for_okr_scope(
            okr_scope=okr_scope,
            user_id=user_id,
            week_no=data.get("week_no"),
            primary=kr or None,
            fallback_krs=[kr] if kr else [],
        )
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, krs_for_okr) if krs_for_okr else ("", {})
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("midweek", "single-KR check-in", timeframe=timeframe)),
            ("history", history_block("recent check-ins", history_text.splitlines()) if history_text else ""),
            ("scores", scores_block(scores_payload, combined=data.get("combined_score")) if scores_payload else ""),
            ("habit", habit_readiness_block(psych_payload) if psych_payload else ""),
            ("okr", okr_txt),
            (
                "task",
                task_block(
                    "Write one short midweek message that: 1) asks how they’re getting on; "
                    "2) asks ONE focused question on this KR; 3) asks about blockers; "
                    "4) suggests one micro-adjustment; 5) encourages consistency.",
                    constraints="Keep it concise and conversational. Do not ask about other KRs.",
                ),
            ),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "midweek",
            "midweek_checkin",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "saturday":
        kr = primary_kr_payload(user_id)
        timeframe = data.get("timeframe", "Saturday")
        history_text = data.get("history_text", "")
        scores_payload = data.get("scores") or []
        psych_payload = data.get("psych_payload") or {}
        okr_scope = (template or {}).get("okr_scope") or "week"
        krs = _krs_for_okr_scope(
            okr_scope=okr_scope,
            user_id=user_id,
            week_no=data.get("week_no"),
            primary=kr or None,
            fallback_krs=[kr] if kr else [],
        )
        okr_txt, okr_meta = okr_block_with_scope(okr_scope, krs) if krs else ("", {})
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("saturday", "keepalive check-in", timeframe=timeframe)),
            ("history", history_block("recent check-ins", history_text.splitlines()) if history_text else ""),
            ("scores", scores_block(scores_payload, combined=data.get("combined_score")) if scores_payload else ""),
            ("habit", habit_readiness_block(psych_payload) if psych_payload else ""),
            ("okr", okr_txt),
            (
                "task",
                task_block(
                    "Write a very short Saturday keepalive that feels light and optional. "
                    "Ask for a one-word or short reply to keep the chat open. "
                    "Offer help if anything feels unclear. Keep it 1–2 lines.",
                    constraints="No new actions or goals. Keep it warm and low-pressure.",
                ),
            ),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "saturday",
            "saturday_keepalive",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    if tp == "sunday":
        krs = kr_payload_list(user_id, max_krs=3)
        history_text = data.get("history_text", "")
        scores_payload = data.get("scores") or []
        psych_payload = data.get("psych_payload") or {}
        okr_scope = (template or {}).get("okr_scope") or "week"
        primary = krs[0] if krs else None
        okr_txt, okr_meta = okr_block_with_scope(
            okr_scope,
            _krs_for_okr_scope(
                okr_scope=okr_scope,
                user_id=user_id,
                week_no=data.get("week_no"),
                primary=primary,
                fallback_krs=krs,
            ),
        )
        parts = [
            ("system", settings.get("system_block") or common_prompt_header(coach_name, user_name, locale)),
            ("locale", settings.get("locale_block") or locale_block(locale)),
            ("context", context_block("sunday", "weekly review", timeframe=data.get("timeframe", "Sunday"))),
            ("okr", okr_txt),
            ("scores", scores_block(scores_payload, combined=data.get("combined_score")) if scores_payload else ""),
            ("habit", habit_readiness_block(psych_payload) if psych_payload else ""),
            ("history", history_block("recent check-ins", history_text.splitlines()) if history_text else ""),
            (
                "task",
                task_block(
                    "Write a short Sunday review message that: "
                    "1) asks for a 1–5 update on each KR; "
                    "2) asks what worked well this week; "
                    "3) asks what didn't work well or made things harder. "
                    "End by saying you'll summarise and prep Monday’s kickoff.",
                    constraints="Keep it concise, friendly, and plain language; no OKR/KR jargon to user; no medical advice.",
                ),
            ),
        ]
        parts, order_override = _apply_prompt_template(parts, template)
        return _prompt_assembly(
            "sunday",
            "sunday_review",
            parts,
            meta=_merge_template_meta(okr_meta, template),
            block_order_override=order_override or settings.get("default_block_order"),
        )
    raise ValueError(f"Unsupported touchpoint: {touchpoint}")


def run_llm_prompt(
    prompt: str,
    user_id: Optional[int] = None,
    touchpoint: Optional[str] = None,
    model: Optional[str] = None,
    context_meta: Optional[Dict[str, Any]] = None,
    prompt_variant: Optional[str] = None,
    task_label: Optional[str] = None,
    prompt_blocks: Optional[Dict[str, str]] = None,
    block_order: Optional[List[str]] = None,
    log: Optional[bool] = None,
) -> str:
    """
    Invoke the shared LLM client and optionally log the prompt/preview to DB.
    Logging is controlled via the `log` flag OR env LOG_LLM_PROMPTS=true.
    """
    limit_raw = (os.getenv("MAX_DAILY_LLM_TOKENS") or "").strip()
    limit_val = None
    if limit_raw:
        try:
            limit_val = int(float(limit_raw))
        except Exception:
            limit_val = None
    if limit_val and limit_val > 0:
        est_tokens = estimate_tokens(prompt)
        try:
            now = datetime.utcnow()
            day_start = datetime(now.year, now.month, now.day)
            day_end = day_start + timedelta(days=1)
            with SessionLocal() as s:
                q = s.query(func.coalesce(func.sum(UsageEvent.units), 0.0)).filter(
                    UsageEvent.product == "llm",
                    UsageEvent.unit_type.in_(["tokens_in", "tokens_out"]),
                    UsageEvent.created_at >= day_start,
                    UsageEvent.created_at < day_end,
                )
                if user_id is not None:
                    q = q.filter(UsageEvent.user_id == user_id)
                used_tokens = float(q.scalar() or 0.0)
        except Exception as e:
            used_tokens = None
            print(f"[prompts] daily token limit check failed: {e}")
        if used_tokens is not None and (used_tokens + est_tokens) > limit_val:
            scope = f"user_id={user_id}" if user_id is not None else "global"
            print(
                f"[prompts] daily token limit reached ({scope}): "
                f"used={int(used_tokens)} + est={est_tokens} > limit={limit_val}"
            )
            return ""
    client = getattr(shared_llm, "_llm", None)
    content = ""
    duration = None
    model_name = model
    if client and not model_name:
        model_name = getattr(client, "model", None) or getattr(client, "model_name", None)
    if client:
        try:
            import time
            t0 = time.perf_counter()
            resp = client.invoke(prompt)
            duration = time.perf_counter() - t0
            content = _coerce_llm_content(getattr(resp, "content", None)).strip()
        except Exception as e:
            print(f"[prompts] LLM invoke failed for touchpoint={touchpoint}: {e}")
            content = ""
    else:
        print(f"[prompts] LLM client missing; skipping invoke for touchpoint={touchpoint}")

    env_val = os.getenv("LOG_LLM_PROMPTS")
    env_flag = True if env_val is None else env_val.lower() in {"1", "true", "yes", "on"}
    should_log = env_flag if log is None else bool(log)
    if should_log and touchpoint:
        preview = content or None  # store full response for reviewer visibility
        log_llm_prompt(
            user_id=user_id,
            touchpoint=touchpoint,
            prompt_text=prompt,
            model=model_name,
            response_preview=preview,
            context_meta=context_meta,
            prompt_variant=prompt_variant or touchpoint,
            task_label=task_label,
            prompt_blocks=prompt_blocks,
            block_order=block_order,
            duration_ms=int(duration * 1000) if duration is not None else None,
        )
    elif should_log and not touchpoint:
        print(f"[prompts] logging skipped: touchpoint not provided for user_id={user_id}")
    return content


def _normalize_job_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return json.loads(json.dumps(payload, default=str))
    except Exception:
        return {"payload_text": str(payload)}


def _coerce_llm_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: List[str] = []
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
                    parts.append(json.dumps(item, ensure_ascii=False))
                continue
            parts.append(str(item))
        joined = "\n".join(p for p in parts if p)
        return joined or json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        for key in ("text", "content"):
            v = value.get(key)
            if isinstance(v, str):
                return v
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def enqueue_llm_prompt(
    *,
    prompt: str,
    user_id: Optional[int] = None,
    touchpoint: Optional[str] = None,
    model: Optional[str] = None,
    context_meta: Optional[Dict[str, Any]] = None,
    prompt_variant: Optional[str] = None,
    task_label: Optional[str] = None,
    prompt_blocks: Optional[Dict[str, str]] = None,
    block_order: Optional[List[str]] = None,
    log: Optional[bool] = None,
) -> int:
    payload = _normalize_job_payload(
        {
            "prompt": prompt,
            "user_id": user_id,
            "touchpoint": touchpoint,
            "model": model,
            "context_meta": context_meta,
            "prompt_variant": prompt_variant,
            "task_label": task_label,
            "prompt_blocks": prompt_blocks,
            "block_order": block_order,
            "log": log,
        }
    )
    job_id = enqueue_job("llm_prompt", payload, user_id=user_id)
    print(f"[prompts] queued LLM prompt touchpoint={touchpoint} user_id={user_id} job={job_id}")
    return job_id


def run_llm_prompt_or_enqueue(
    prompt: str,
    user_id: Optional[int] = None,
    touchpoint: Optional[str] = None,
    model: Optional[str] = None,
    context_meta: Optional[Dict[str, Any]] = None,
    prompt_variant: Optional[str] = None,
    task_label: Optional[str] = None,
    prompt_blocks: Optional[Dict[str, str]] = None,
    block_order: Optional[List[str]] = None,
    log: Optional[bool] = None,
    *,
    queue_if_worker: bool = True,
) -> tuple[str, Optional[int]]:
    if queue_if_worker and should_use_worker() and not _in_worker_process():
        job_id = enqueue_llm_prompt(
            prompt=prompt,
            user_id=user_id,
            touchpoint=touchpoint,
            model=model,
            context_meta=context_meta,
            prompt_variant=prompt_variant,
            task_label=task_label,
            prompt_blocks=prompt_blocks,
            block_order=block_order,
            log=log,
        )
        return "", job_id
    return (
        run_llm_prompt(
            prompt,
            user_id=user_id,
            touchpoint=touchpoint,
            model=model,
            context_meta=context_meta,
            prompt_variant=prompt_variant,
            task_label=task_label,
            prompt_blocks=prompt_blocks,
            block_order=block_order,
            log=log,
        ),
        None,
    )


def log_llm_prompt(
    user_id: Optional[int],
    touchpoint: str,
    prompt_text: str,
    model: Optional[str] = None,
    duration_ms: Optional[int] = None,
    response_preview: Optional[str] = None,
    context_meta: Optional[Dict[str, Any]] = None,
    prompt_variant: Optional[str] = None,
    task_label: Optional[str] = None,
    prompt_blocks: Optional[Dict[str, str]] = None,
    block_order: Optional[List[str]] = None,
) -> None:
    """
    Persist the prompt sent to the LLM (optional response preview) with structured blocks.
    Enable by calling explicitly where needed; kept separate from run_llm_prompt for control.
    """
    debug = debug_enabled()
    if model is None:
        client = getattr(shared_llm, "_llm", None)
        model = getattr(client, "model", None) or getattr(client, "model_name", None) if client else None
    print(f"[prompts] logging LLM prompt touchpoint={touchpoint} user_id={user_id}")
    try:
        _ensure_llm_prompt_log_schema()
        if response_preview is not None and not isinstance(response_preview, str):
            response_preview = _coerce_llm_content(response_preview)
        known_blocks, extra_blocks, resolved_order, assembled_from_blocks = _normalize_prompt_blocks(
            prompt_blocks, preferred_order=block_order
        )
        template_state = extra_blocks.pop("template_state", None)
        template_version = extra_blocks.pop("template_version", None)
        if context_meta:
            template_state = template_state or context_meta.get("template_state")
            template_version = template_version or context_meta.get("template_version")
        try:
            template_version_int = int(template_version) if template_version not in {None, ""} else None
        except Exception:
            template_version_int = None
        final_prompt = prompt_text or assembled_from_blocks
        # Keep legacy prompt_text column populated for back-compat.
        prompt_text_value = final_prompt or ""
        block_order_value = block_order or resolved_order or DEFAULT_PROMPT_BLOCK_ORDER

        prompt_log_id = None
        with SessionLocal() as s:
            row = LLMPromptLog(
                    user_id=user_id,
                    touchpoint=touchpoint,
                    model=model,
                    duration_ms=duration_ms,
                    prompt_variant=prompt_variant,
                    task_label=task_label,
                    system_block=known_blocks.get("system"),
                    locale_block=known_blocks.get("locale"),
                    okr_block=known_blocks.get("okr"),
                    okr_scope=extra_blocks.pop("okr_scope", None),
                    scores_block=known_blocks.get("scores"),
                    habit_block=known_blocks.get("habit"),
                    task_block=known_blocks.get("task"),
                    template_state=template_state,
                    template_version=template_version_int,
                    user_block=known_blocks.get("user"),
                    extra_blocks=extra_blocks or None,
                    block_order=block_order_value or None,
                    prompt_text=prompt_text_value,
                    assembled_prompt=final_prompt,
                    response_preview=response_preview,
                    context_meta=context_meta,
                )
            s.add(row)
            s.flush()
            prompt_log_id = row.id
            s.commit()
            if debug:
                try:
                    total = s.query(func.count(LLMPromptLog.id)).scalar()
                    print(f"[prompts] logged LLM prompt touchpoint={touchpoint} user_id={user_id} (count={total})")
                except Exception as e:
                    print(f"[prompts] logged but count check failed: {e}")
            else:
                print(f"[prompts] logged LLM prompt touchpoint={touchpoint} user_id={user_id}")

        try:
            tag = _usage_tag_for_touchpoint(touchpoint)
            tokens_in = estimate_tokens(final_prompt)
            tokens_out = estimate_tokens(response_preview or "")
            _, rate_in, rate_out, rate_source = estimate_llm_cost(tokens_in, tokens_out)
            request_id = str(prompt_log_id) if prompt_log_id else None
            meta = {
                "prompt_log_id": prompt_log_id,
                "touchpoint": touchpoint,
                "prompt_variant": prompt_variant,
                "rate_source": rate_source,
                "rate_in": rate_in,
                "rate_out": rate_out,
            }
            if tokens_in:
                log_usage_event(
                    user_id=user_id,
                    provider=(os.getenv("LLM_PROVIDER") or "openai").strip() or "openai",
                    product="llm",
                    model=model,
                    units=float(tokens_in),
                    unit_type="tokens_in",
                    cost_estimate=(tokens_in / 1_000_000.0) * rate_in if rate_in else None,
                    request_id=request_id,
                    tag=tag,
                    meta=meta,
                )
            if tokens_out:
                log_usage_event(
                    user_id=user_id,
                    provider=(os.getenv("LLM_PROVIDER") or "openai").strip() or "openai",
                    product="llm",
                    model=model,
                    units=float(tokens_out),
                    unit_type="tokens_out",
                    cost_estimate=(tokens_out / 1_000_000.0) * rate_out if rate_out else None,
                    request_id=request_id,
                    tag=tag,
                    meta=meta,
                )
        except Exception as e:
            print(f"[usage] llm log failed: {e}")
    except Exception as e:
        # Best-effort: surface failures for missing tables or permissions
        print(f"[prompts] failed to log LLM prompt ({touchpoint}): {e}")


def _usage_tag_for_touchpoint(touchpoint: str | None) -> str | None:
    if not touchpoint:
        return None
    key = touchpoint.strip().lower()
    weekly = {
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "weekstart",
        "weekstart_actions",
        "podcast_weekstart",
        "podcast_thursday",
        "podcast_friday",
        "podcast_kickoff",
        "kickoff",
        "week",
    }
    if key in weekly:
        return "weekly_flow"
    if key.startswith("assessment") or key in {"assessment_scores", "assessment_okr", "assessment_approach"}:
        return "assessment"
    if key.startswith("content"):
        return "content_generation"
    return None


# ---------------------------------------------------------------------------
# Podcast prompts (kickoff/weekstart) built from blocks
# ---------------------------------------------------------------------------


def podcast_prompt(
    mode: str,
    coach_name: str,
    user_name: str,
    history_text: str = "",
    scores: Optional[List[Dict[str, Any]]] = None,
    psych_payload: Optional[Dict[str, Any]] = None,
    programme: Optional[List[Dict[str, Any]]] = None,
    first_block: Optional[Dict[str, Any]] = None,
    okrs_by_pillar: Optional[Dict[str, List[str]]] = None,
    focus_pillar: Optional[str] = None,
    week_no: Optional[int] = None,
    krs: Optional[List[Dict[str, Any]]] = None,
    timeframe: str = "",
    locale: str = "UK",
) -> str:
    """
    Build podcast transcript prompts for all podcast flows.
    mode: kickoff | weekstart | thursday | friday
    okrs_by_pillar: {pillar_key: [kr_desc, ...]} (kickoff/weekstart)
    krs: list of KR dicts (thursday/friday)
    """
    scores = scores or []
    psych_payload = psych_payload or {}
    programme = programme or []
    okrs_by_pillar = okrs_by_pillar or {}
    locale_txt = LOCALE_GUIDANCE_UK if locale.upper() == "UK" else ""
    history_block_txt = f"\nHistory: {history_text}" if history_text else ""

    common_header = (
        common_prompt_header(coach_name, user_name, locale)
        + f"\nAssessment scores: {scores}\nHabit readiness: {psych_payload}{history_block_txt}\n"
    )
    okr_str = f"Key Results: {okrs_by_pillar}"

    if mode == "weekstart":
        return (
            "You are a warm, concise wellbeing coach creating a 1–2 minute weekly audio brief. "
            "Focus on the current 3-week block: explain why each KR matters, and give 2–3 simple suggestions to start this week. "
            "Include: welcome, quick assessment nod, habit readiness nod, this block’s dates and pillar, "
            "KR highlights for this block, practical Week 1 ideas, and a short motivational close. "
            + common_header
            + f"Current block: {first_block}\n"
            + okr_str
        )

    if mode == "kickoff":
        return (
            "You are a warm, concise wellbeing coach creating a 2–3 minute kickoff audio intro. "
            "Write a transcript with:\n"
            "1) Welcome & personal context\n"
            "2) Assessment findings summary (per pillar)\n"
            "3) Habit readiness summary (from psych profile)\n"
            "4) 12-week plan overview (3-week blocks by pillar)\n"
            "5) Key Results highlights\n"
            "6) Weekly expectations and how you’ll support\n"
            "7) Motivational closing\n"
            + common_header
            + f"Programme blocks: {programme}\n"
            + okr_str
        )

    if mode == "thursday":
        krs = krs or []
        return (
            "You are a warm, concise wellbeing coach creating a ~60s Thursday podcast-style script. "
            "Output exactly two labeled sections (labels for routing only; do NOT speak the labels):\n"
            "Education: short welcome, why the goal matters, and one practical mini-challenge.\n"
            "Motivation: brief encouragement/next step.\n"
            "Keep educational content in Education and encouragement in Motivation. Plain habit language (no OKR/KR terms). "
            "No medical advice; avoid jargon; concise and actionable.\n"
            + common_header +
            f"KRs: {krs}"
        )

    if mode == "friday":
        krs = krs or []
        return (
            "You are a warm, concise wellbeing coach creating a short Friday boost podcast (~45–60s). "
            "Write a script that: 1) friendly check-in; 2) encourage ONE focus goal in plain language (no OKR/KR terms); "
            "3) give ONE simple, realistic action they can do over the weekend; 4) keep it brief, motivating, and specific; 5) no medical advice. "
            + common_header +
            f"KRs: {krs}"
        )

    raise ValueError(f"Unsupported podcast mode: {mode}")


# ---------------------------------------------------------------------------
# Coaching text prompts (dispatcher + mode-specific builder)
# ---------------------------------------------------------------------------


def coaching_prompt(
    mode: str,
    coach_name: str,
    user_name: str,
    locale: str = "UK",
    **data,
) -> str:
    """
    Central builder for interactive coaching text prompts.
    Modes: weekstart_support | kickoff_support | weekstart_actions | midweek | tuesday | sunday
    """
    m = mode.lower()
    header = common_prompt_header(coach_name, user_name, locale)
    scores_payload = data.get("scores") or []
    psych_payload = data.get("psych_payload") or {}
    extra_blocks: List[str] = []
    if scores_payload:
        extra_blocks.append(scores_block(scores_payload, combined=data.get("combined_score")))
    if psych_payload:
        extra_blocks.append(habit_readiness_block(psych_payload))

    if m == "weekstart_support":
        history = "\n".join(data.get("history", []))
        krs_payload = data.get("krs_payload", [])
        blocks = [
            header,
            context_block("weekstart", "support chat"),
            okr_block(krs_payload),
            *extra_blocks,
            task_block(
                "Reply with 2-3 practical ideas or next steps for this week; include a couple of follow-ups that advance the plan.",
                constraints="Do not assume progress; avoid praise/commands; do not suggest more sessions than KR targets; keep it conversational.",
            ),
            f"Conversation so far:\n{history}",
        ]
        return assemble_prompt(blocks)

    if m == "kickoff_support":
        krs_payload = data.get("krs_payload", [])
        transcript_history = data.get("transcript_history", "")
        user_message = data.get("user_message", "")
        blocks = [
            header,
            *extra_blocks,
            (
                "You are a concise wellbeing coach in a kickoff support chat. "
                "Context: the user already completed an assessment; objectives and KRs exist. "
                "These KRs are the agreed focus for this week, and this kickoff is to help them plan and feel supported. "
                "Do NOT assume progress yet; stay focused on planning and making the week doable. "
                "Acknowledge what they just shared, build on it, and avoid repeating the same ask. "
                "Offer 2-3 practical ideas or next steps for this week and feel free to include a couple of follow-ups that logically advance the plan "
                "(e.g., which idea they want to try, and whether they need a resource/schedule). "
                "Do not suggest more sessions than the KR targets unless the user asked for it. "
                "Avoid praise, avoid commands, keep it conversational and forward-looking."
            ),
            f"KRs: {krs_payload}",
            f"Conversation so far:\n{transcript_history}",
            f"Latest user note: {user_message or ''}",
        ]
        return assemble_prompt(blocks)

    if m == "weekstart_actions":
        transcript = data.get("transcript", "")
        krs = data.get("krs", [])
        return (
            f"{header}\n"
            "You are a concise wellbeing coach. Using the podcast transcript and the KR context, "
            "write a short intro plus 1–2 habit step options per KR using this exact format:\n"
            "KR1: <short KR description>\n"
            "1A) <habit step option>\n"
            "1B) <habit step option>\n"
            "KR2: ...\n"
            "2A) ...\n"
            "2B) ...\n"
            "Intro should say: 'As per the podcast, here are practical actions for this week:' "
            "Keep options practical, low-pressure, and easy to start this week. "
            "Use British English spelling and phrasing; avoid Americanisms. "
            "End with a single line instructing: 'Reply with 1A, 2B, etc. or All ok to accept the first option for each KR.'\n"
            f"Transcript: {transcript}\n"
            f"KRs: {krs}"
        )

    if m == "midweek":
        kr = data.get("kr", {})
        timeframe = data.get("timeframe", "")
        history_text = data.get("history_text", "")
        blocks = [
            header,
            context_block("midweek", "single-KR check-in", timeframe=timeframe),
        ]
        if history_text:
            blocks.append(history_block("recent check-ins", history_text.splitlines()))
        blocks.extend(extra_blocks)
        blocks.extend(
            [
                okr_block([kr]),
                task_block(
                    "Write one short midweek message that: 1) asks how they’re getting on; "
                    "2) asks ONE focused question on this KR; 3) asks about blockers; "
                    "4) suggests one micro-adjustment; 5) encourages consistency.",
                    constraints="Keep it concise and conversational. Do not ask about other KRs.",
                ),
            ]
        )
        return assemble_prompt(blocks)

    if m == "tuesday":
        kr = data.get("kr", {})
        timeframe = data.get("timeframe", "Tuesday")
        history_text = data.get("history_text", "")
        blocks = [
            header,
            context_block("tuesday", "micro-check", timeframe=timeframe),
        ]
        if history_text:
            blocks.append(history_block("recent check-ins", history_text.splitlines()))
        blocks.extend(extra_blocks)
        blocks.extend(
            [
                okr_block([kr]),
                task_block(
                    "Write a very short check-in asking how they’re doing on this goal. "
                    "Ask for a simple yes/no or number. Offer one actionable nudge. "
                    "Keep it friendly, low-burden, WhatsApp length, plain language (no OKR/KR terms).",
                    constraints="Avoid medical advice; avoid jargon; focus on one goal; be concise.",
                ),
            ]
        )
        return assemble_prompt(blocks)

    if m == "sunday":
        krs = data.get("krs", [])
        timeframe = data.get("timeframe", "Sunday")
        blocks = [
            header,
            context_block("sunday", "weekly review", timeframe=timeframe),
            okr_block(krs),
            *extra_blocks,
            task_block(
                "Write a short Sunday review message that: "
                "1) asks for a 1–5 update on each KR; "
                "2) asks what worked well this week; "
                "3) asks what didn't work well or made things harder. "
                "End by saying you'll summarise and prep Monday’s kickoff.",
                constraints="Keep it concise, friendly, and plain language; no OKR/KR jargon to user; no medical advice.",
            ),
        ]
        return assemble_prompt(blocks)

    raise ValueError(f"Unsupported coaching prompt mode: {mode}")


# Legacy convenience wrappers (used by callers expecting specific helpers)
def weekstart_support_prompt(
    krs_payload: List[Dict[str, Any]],
    transcript_history: List[str],
    coach_name: str,
    user_name: str,
    locale: str = "UK",
) -> str:
    return coaching_prompt(
        "weekstart_support",
        coach_name=coach_name,
        user_name=user_name,
        locale=locale,
        krs_payload=krs_payload,
        history=transcript_history,
    )


def weekstart_actions_prompt(transcript: str, krs: List[str], coach_name: str = "Coach", user_name: str = "User", locale: str = "UK") -> str:
    return coaching_prompt(
        "weekstart_actions",
        coach_name=coach_name,
        user_name=user_name,
        locale=locale,
        transcript=transcript,
        krs=krs,
    )


def coaching_approach_prompt(
    user_name: str,
    section_averages: Dict[str, Any],
    flags: Dict[str, Any],
    parameters: Dict[str, Any],
    locale: str = "UK",
) -> PromptAssembly:
    """Habit-readiness coaching approach (2–3 sentences) — template-driven."""
    data_payload = {
        "section_averages": section_averages,
        "flags": flags,
        "parameters": parameters,
    }
    default_task = (
        "You are a concise wellbeing coach writing directly to the user. "
        "In 2–3 sentences, explain how you'll tailor support based on their habit readiness profile. "
        "Use 'you', keep it plain text, no bullets."
    )
    settings = _load_prompt_settings()
    template = _load_prompt_template("assessment_approach") or _load_prompt_template("coaching_approach")
    sys_block = settings.get("system_block") or common_prompt_header("Coach", user_name, locale)
    loc_block = settings.get("locale_block") or locale_block(locale)
    parts = [
        ("system", sys_block),
        ("locale", loc_block),
        ("context", "Context: habit readiness approach"),
        ("habit", f"Habit readiness: {json.dumps(data_payload, ensure_ascii=False)}"),
        ("task", (template or {}).get("task_block") or default_task),
    ]
    parts, order_override = _apply_prompt_template(parts, template)
    assembly = _prompt_assembly(
        "assessment_approach",
        "assessment_approach",
        parts,
        meta=_merge_template_meta({}, template),
        block_order_override=order_override or settings.get("default_block_order"),
    )
    return assembly


def assessment_scores_prompt(
    user_name: str,
    combined: int,
    payload: list[dict],
    locale: str = "UK",
) -> PromptAssembly:
    """Assessment score narrative (2 short paragraphs) — now template-driven."""
    data_payload = {"combined": combined, "scores": payload}
    default_task = (
        "You are a supportive wellbeing coach writing a concise summary of assessment scores. "
        "Write two short paragraphs (under 140 words total) that explain what the combined score and per-pillar scores suggest, "
        "reference notable answers when helpful, treat Resilience gently, and encourage small next steps. "
        "Use second-person voice ('you'). Return plain text."
    )
    settings = _load_prompt_settings()
    template = _load_prompt_template("assessment_scores")
    sys_block = settings.get("system_block") or common_prompt_header("Coach", user_name, locale)
    loc_block = settings.get("locale_block") or locale_block(locale)
    parts = [
        ("system", sys_block),
        ("locale", loc_block),
        ("context", "Context: assessment scores summary"),
        ("scores", f"Assessment scores: {json.dumps(data_payload, ensure_ascii=False)}"),
        ("task", (template or {}).get("task_block") or default_task),
    ]
    parts, order_override = _apply_prompt_template(parts, template)
    assembly = _prompt_assembly(
        "assessment_scores",
        "assessment_scores",
        parts,
        meta=_merge_template_meta({}, template),
        block_order_override=order_override or settings.get("default_block_order"),
    )
    return assembly


def okr_narrative_prompt(
    user_name: str,
    payload: list[dict],
    locale: str = "UK",
) -> PromptAssembly:
    """OKR narrative prompt tying objectives to scores."""
    default_task = (
        "You are a wellbeing performance coach. Explain why each Objective and Key Result matters for the user’s wellbeing. "
        "Write two short paragraphs that tie the objectives to the scores, highlight where focus is needed, "
        "keep the tone gentle but action-oriented, and use second-person voice. Reference 'focus_note' when present."
    )
    settings = _load_prompt_settings()
    template = _load_prompt_template("assessment_okr") or _load_prompt_template("okr_narrative")
    sys_block = settings.get("system_block") or common_prompt_header("Coach", user_name, locale)
    loc_block = settings.get("locale_block") or locale_block(locale)
    parts = [
        ("system", sys_block),
        ("locale", loc_block),
        ("context", "Context: okr narrative"),
        ("okr", f"OKRs: {json.dumps(payload, ensure_ascii=False)}"),
        ("task", (template or {}).get("task_block") or default_task),
    ]
    parts, order_override = _apply_prompt_template(parts, template)
    assembly = _prompt_assembly(
        "assessment_okr",
        "assessment_okr",
        parts,
        meta=_merge_template_meta({}, template),
        block_order_override=order_override or settings.get("default_block_order"),
    )
    return assembly


def assessment_narrative_prompt(user_name: str, combined: int, payload: List[Dict[str, Any]], locale: str = "UK") -> PromptAssembly:
    # Deprecated: assessment_narrative touchpoint removed
    raise RuntimeError("assessment_narrative prompt is deprecated; use assessment_scores instead.")


def assessor_system_prompt(pillar: str, concept: str) -> str:
    """Render the assessor system prompt for a pillar/concept."""
    data_payload = {"pillar": pillar, "concept": concept}
    default_task = (
        "You are a concise WhatsApp assessor. Ask a main question (<=300 chars) or a clarifier (<=320 chars) when the user's answer is vague. "
        "If the reply contains a NUMBER or strongly implies a count/timeframe, you may treat it as sufficient and finish with a score. "
        "Only finish once you can assign a 0–100 score. Return JSON only with fields: "
        "{action:ask|finish, question, level:Low|Moderate|High, confidence:float, rationale, scores:{}, status:scorable|needs_clarifier|insufficient, why, missing:[], parsed_value:{value,unit,timeframe_ok}}. "
        "Use polarity inference and bounds when provided; map habitual phrases to counts; prefer clarifiers if uncertain."
    )
    settings = _load_prompt_settings()
    template = _load_prompt_template("assessor_system")
    sys_block = settings.get("system_block") or common_prompt_header("Assessor", "User", "UK")
    loc_block = settings.get("locale_block") or locale_block("UK")
    parts = [
        ("system", sys_block),
        ("locale", loc_block),
        ("context", f"Context: assessment system prompt for pillar={pillar}, concept={concept}"),
        ("assessor", json.dumps(data_payload, ensure_ascii=False)),
        ("task", (template or {}).get("task_block") or default_task),
    ]
    parts, order_override = _apply_prompt_template(parts, template)
    assembly = _prompt_assembly(
        "assessor_system",
        "assessor_system",
        parts,
        meta=_merge_template_meta({}, template),
        block_order_override=order_override or settings.get("default_block_order"),
    )
    return assembly.text


def assessor_feedback_prompt() -> str:
    return (
        f"{common_prompt_header('Assessor', 'User', 'UK')}\n"
        "Write one short feedback line and two short next steps based on pillar dialog.\n"
        "Format:\n"
        "- 1 short feedback line (what they do well + gap)\n"
        '- \"Next steps:\" + 2 bullets (<= 12 words), practical, non-judgmental.'
    )


__all__ = [
    "podcast_prompt",
    "weekstart_support_prompt",
    "weekstart_actions_prompt",
    "coaching_prompt",
    "coaching_approach_prompt",
    "assessment_scores_prompt",
    "okr_narrative_prompt",
    "assessor_system_prompt",
    "assessor_feedback_prompt",
    "context_block",
    "okr_block",
    "scores_block",
    "habit_readiness_block",
    "task_block",
    "assemble_prompt",
    "podcast_prompt",
]
