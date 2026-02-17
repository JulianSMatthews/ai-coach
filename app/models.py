from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date, Boolean, Float, ForeignKey,
    UniqueConstraint, Index, PrimaryKeyConstraint, text
)
from sqlalchemy import text as sa_text
from sqlalchemy.dialects.postgresql import JSONB as JSONType
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()

# Shared admin role labels so CLI/API/seeds stay in sync
ADMIN_ROLE_MEMBER = "member"
ADMIN_ROLE_CLUB = "club_admin"
ADMIN_ROLE_GLOBAL = "global_admin"

# ──────────────────────────────────────────────────────────────────────────────
# Core
# ──────────────────────────────────────────────────────────────────────────────
class Club(Base):
    __tablename__ = "clubs"
    id         = Column(Integer, primary_key=True)
    name       = Column(String, nullable=False, unique=True)
    slug       = Column(String, nullable=False, unique=True)   # e.g. "anytime-eden"
    is_active  = Column(Boolean, nullable=False, server_default="true")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

class User(Base):
    __tablename__ = "users"
    id         = Column(Integer, primary_key=True)
    club_id    = Column(Integer, ForeignKey("clubs.id", ondelete="RESTRICT"), nullable=False, index=True)
    first_name = Column(String(120), nullable=True)
    surname    = Column(String(120), nullable=True)
    phone      = Column(String(64), unique=True, nullable=False, index=True)
    email      = Column(String(255), nullable=True, index=True)
    password_hash = Column(String(255), nullable=True)
    phone_verified_at = Column(DateTime, nullable=True)
    email_verified_at = Column(DateTime, nullable=True)
    two_factor_enabled = Column(Boolean, nullable=False, server_default=text("false"))
    created_on = Column(DateTime, nullable=True)
    updated_on = Column(DateTime, nullable=True)
    last_inbound_message_at = Column(DateTime, nullable=True, index=True)
    is_superuser = Column(Boolean, nullable=False, server_default=text("false"))
    admin_role  = Column(String(32), nullable=False, server_default=text("'member'"))
    consent_given = Column(Boolean, nullable=False, server_default=text("false"))
    consent_at = Column(DateTime, nullable=True)
    onboard_complete = Column(Boolean, nullable=False, server_default=text("false"))

    sessions   = relationship("AssessSession", back_populates="user", cascade="all, delete-orphan")
    club       =relationship("Club")


class AuthOtp(Base):
    __tablename__ = "auth_otps"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    channel    = Column(String(32), nullable=False)  # whatsapp|sms|email
    purpose    = Column(String(32), nullable=False)  # login_2fa|login
    code_hash  = Column(String(255), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    consumed_at = Column(DateTime, nullable=True)
    ip         = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(255), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    ip         = Column(String(64), nullable=True)
    user_agent = Column(String(255), nullable=True)

    user = relationship("User")

class AssessSession(Base):
    __tablename__ = "assess_sessions"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    domain     = Column(String(32), nullable=False, default="combined")
    is_active  = Column(Boolean, default=True, nullable=False)
    turn_count = Column(Integer, default=0, nullable=False)
    state      = Column(JSONType, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    user       = relationship("User", back_populates="sessions")

class MessageLog(Base):
    __tablename__ = "message_logs"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    user_name  = Column(String(160), nullable=True)   # optional display name captured at send 
    phone      = Column(String(64), nullable=True, index=True)
    direction  = Column(String(16), nullable=False)   # inbound | outbound
    channel    = Column(String(32), nullable=True)    # e.g. whatsapp
    text       = Column(Text, nullable=True)
    meta       = Column(JSONType, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class ScriptRun(Base):
    __tablename__ = "script_runs"
    id          = Column(Integer, primary_key=True)
    kind        = Column(String(32), nullable=False)  # assessment | coaching
    status      = Column(String(32), nullable=False, default="running")
    pid         = Column(Integer, nullable=True)
    command     = Column(Text, nullable=False)
    log_path    = Column(Text, nullable=True)
    exit_code   = Column(Integer, nullable=True)
    started_at  = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    created_by  = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)


# ──────────────────────────────────────────────────────────────────────────────
# LLM prompt logging
# ──────────────────────────────────────────────────────────────────────────────
class LLMPromptLog(Base):
    __tablename__ = "llm_prompt_logs"
    id               = Column(Integer, primary_key=True)
    user_id          = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    touchpoint       = Column(String(64), nullable=False, index=True)
    model            = Column(String(64), nullable=True)
    duration_ms      = Column(Integer, nullable=True)
    prompt_variant   = Column(String(160), nullable=True)  # e.g. named prompt set / variant
    task_label       = Column(String(160), nullable=True)  # short task summary
    # Prompt composition (stored per block for reviewer readability)
    system_block     = Column(Text, nullable=True)
    locale_block     = Column(Text, nullable=True)
    okr_block        = Column(Text, nullable=True)
    okr_scope        = Column(String(32), nullable=True)  # all | pillar | week | single
    scores_block     = Column(Text, nullable=True)
    habit_block      = Column(Text, nullable=True)
    task_block       = Column(Text, nullable=True)
    template_state   = Column(String(32), nullable=True)
    template_version = Column(Integer, nullable=True)
    user_block       = Column(Text, nullable=True)
    extra_blocks     = Column(JSONType, nullable=True)   # map of other labeled blocks
    block_order      = Column(JSONType, nullable=True)   # ordered list of labels used in assembly
    prompt_text      = Column(Text, nullable=False)      # final assembled prompt (legacy name)
    assembled_prompt = Column(Text, nullable=True)       # duplicate field for clarity / future rename
    response_preview = Column(Text, nullable=True)
    context_meta     = Column(JSONType, nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)

    user = relationship("User")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"
    id            = Column(Integer, primary_key=True)
    touchpoint    = Column(String(120), nullable=False, index=True)
    parent_id     = Column(Integer, nullable=True)  # optional linkage to source template when promoted
    version       = Column(Integer, nullable=False, server_default="1")
    state         = Column(String(32), nullable=False, server_default="develop")  # develop|beta|live
    note          = Column(Text, nullable=True)
    task_block    = Column(Text, nullable=True)
    block_order   = Column(JSONType, nullable=True)   # ordered list of labels
    include_blocks = Column(JSONType, nullable=True)  # list of labels to include
    okr_scope     = Column(String(32), nullable=True) # all|pillar|week|single
    programme_scope = Column(String(32), nullable=True) # full|pillar|none
    response_format = Column(String(32), nullable=True) # e.g., text|json
    model_override = Column(String(120), nullable=True) # optional runtime model override
    is_active     = Column(Boolean, nullable=False, server_default="true")
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("touchpoint", "state", "version", name="uq_prompt_templates_touchpoint_state_version"),
    )


class PromptSettings(Base):
    __tablename__ = "prompt_settings"
    id                = Column(Integer, primary_key=True)
    system_block      = Column(Text, nullable=True)
    developer_block   = Column(Text, nullable=True)
    locale_block      = Column(Text, nullable=True)
    policy_block      = Column(Text, nullable=True)
    tool_block        = Column(Text, nullable=True)
    default_block_order = Column(JSONType, nullable=True)
    worker_mode_override = Column(Boolean, nullable=True)
    podcast_worker_mode_override = Column(Boolean, nullable=True)
    monitoring_llm_p50_warn_ms = Column(Float, nullable=True)
    monitoring_llm_p50_critical_ms = Column(Float, nullable=True)
    monitoring_llm_p95_warn_ms = Column(Float, nullable=True)
    monitoring_llm_p95_critical_ms = Column(Float, nullable=True)
    monitoring_llm_interactive_p50_warn_ms = Column(Float, nullable=True)
    monitoring_llm_interactive_p50_critical_ms = Column(Float, nullable=True)
    monitoring_llm_interactive_p95_warn_ms = Column(Float, nullable=True)
    monitoring_llm_interactive_p95_critical_ms = Column(Float, nullable=True)
    monitoring_llm_worker_p50_warn_ms = Column(Float, nullable=True)
    monitoring_llm_worker_p50_critical_ms = Column(Float, nullable=True)
    monitoring_llm_worker_p95_warn_ms = Column(Float, nullable=True)
    monitoring_llm_worker_p95_critical_ms = Column(Float, nullable=True)
    updated_at        = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class PromptTemplateVersionLog(Base):
    __tablename__ = "prompt_template_versions"
    id            = Column(Integer, primary_key=True)
    version       = Column(Integer, nullable=False)
    from_state    = Column(String(32), nullable=False)
    to_state      = Column(String(32), nullable=False)
    note          = Column(Text, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)


class JobAudit(Base):
    __tablename__ = "job_audits"
    id         = Column(Integer, primary_key=True)
    job_name   = Column(String(120), nullable=True)
    status     = Column(String(32), nullable=True)    # started|ok|error
    payload    = Column(JSONType, nullable=True)
    error      = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

# ──────────────────────────────────────────────────────────────────────────────
# Pillars / Concepts + per-user concept state
# ──────────────────────────────────────────────────────────────────────────────

class Pillar(Base):
    __tablename__ = "pillars"
    id         = Column(Integer, primary_key=True)
    key        = Column(String(32), unique=True, nullable=False)  # nutrition/training/resilience/goals
    name       = Column(String(120), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Concept(Base):
    __tablename__ = "concepts"
    id          = Column(Integer, primary_key=True)
    pillar_key  = Column(String(32), nullable=False, index=True)
    code        = Column(String(64), nullable=False, index=True)
    name        = Column(String(160), nullable=False)
    description = Column(Text, nullable=True)
    # PATCH — 2025-09-11: quantity→score guidelines (simple bounds)
    # Quantity that maps to score 0, and quantity that maps to score 100 (cap at max+)
    zero_score = Column(Integer, nullable=True)
    max_score  = Column(Integer, nullable=True)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("pillar_key", "code", name="uq_concepts_pillar_code"),
    )


class ConceptQuestion(Base):
    __tablename__ = "concept_questions"
    id         = Column(Integer, primary_key=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    text       = Column(Text, nullable=False)                       # main/alternate question text
    is_primary = Column(Boolean, default=False, nullable=False)     # one primary per concept
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UserConceptState(Base):
    __tablename__ = "user_concept_state"
    id            = Column(Integer, primary_key=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    concept_id    = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    run_id        = Column(Integer, ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False, index=True)

    # Snapshot of the most recent scored interaction for this concept
    score         = Column(Float, nullable=True)  # 0..100 running avg

    # Denormalized helpers for fast grouping/reporting
    pillar_key    = Column(String(32), nullable=True, index=True)   # e.g. "nutrition"
    concept       = Column(String(160), nullable=True, index=True)  # e.g. "Fruit & Vegetables"

    # Latest Q/A captured for this concept
    question      = Column(Text, nullable=True)
    answer        = Column(Text, nullable=True)
    confidence    = Column(Float, nullable=True)
    notes         = Column(JSONType, nullable=True)  # raw LLM payload / parsed structures

    asked_count   = Column(Integer, nullable=True)
    last_asked_at = Column(DateTime, nullable=True)
    updated_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "run_id", "concept_id", name="uq_user_run_concept_state"),
    )


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key        = Column(String(64), nullable=False)
    value      = Column(Text, nullable=True)
    meta       = Column(JSONType, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_preferences_user_key"),
    )


class GlobalPromptSchedule(Base):
    __tablename__ = "global_prompt_schedule"

    id         = Column(Integer, primary_key=True)
    day_key    = Column(String(16), nullable=False, unique=True)  # monday..sunday
    time_local = Column(String(8), nullable=True)                # HH:MM (local)
    enabled    = Column(Boolean, nullable=False, server_default=text("true"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class TwilioTemplate(Base):
    __tablename__ = "twilio_templates"

    id            = Column(Integer, primary_key=True)
    provider      = Column(String(32), nullable=False, server_default="twilio")
    template_type = Column(String(64), nullable=False)  # quick-reply
    button_count  = Column(Integer, nullable=True)
    friendly_name = Column(String(120), nullable=True)
    sid           = Column(String(64), nullable=True, index=True)
    language      = Column(String(16), nullable=True, server_default="en")
    status        = Column(String(32), nullable=True)  # active|missing|error
    payload       = Column(JSONType, nullable=True)
    last_synced_at = Column(DateTime, nullable=True)
    created_at    = Column(DateTime, nullable=False, server_default=func.now())
    updated_at    = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("provider", "template_type", "button_count", name="uq_twilio_template_type_count"),
    )


class MessagingSettings(Base):
    __tablename__ = "messaging_settings"

    id                        = Column(Integer, primary_key=True)
    out_of_session_enabled    = Column(Boolean, nullable=False, server_default=text("false"))
    out_of_session_message    = Column(Text, nullable=True)
    updated_at                = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

# ──────────────────────────────────────────────────────────────────────────────
# Knowledge Base (retriever)
# ──────────────────────────────────────────────────────────────────────────────

class KbSnippet(Base):
    __tablename__ = "kb_snippets"
    id           = Column(Integer, primary_key=True)
    pillar_key   = Column(String(32), nullable=False, index=True)   # nutrition/training/resilience/goals
    concept_code = Column(String(64), nullable=True, index=True)    # e.g. 'protein_basics'
    title        = Column(String(200), nullable=True)
    text         = Column(Text, nullable=False)
    tags         = Column(JSONType, nullable=True)                  # ["portion", "grams"]
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_kb_snippets_pillar_concept", "pillar_key", "concept_code"),
    )


class KbVector(Base):
    __tablename__ = "kb_vectors"
    id         = Column(Integer, primary_key=True)
    snippet_id = Column(Integer, ForeignKey("kb_snippets.id", ondelete="CASCADE"), nullable=False, index=True)
    embedding  = Column(JSONType, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ──────────────────────────────────────────────────────────────────────────────
# Assessment runs + turns (logging / review)
# ──────────────────────────────────────────────────────────────────────────────

class AssessmentRun(Base):
    __tablename__ = "assessment_runs"
    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    domain     = Column(String(32), nullable=False, default="combined")
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at= Column(DateTime, nullable=True)
    combined_overall = Column(Integer, nullable=True)     # 0..100 combined score for this run
    report_path      = Column(String(255), nullable=True) # filesystem or URL path to generated PDF

    turns      = relationship("AssessmentTurn", back_populates="run", cascade="all, delete-orphan")
    narrative  = relationship("AssessmentNarrative", back_populates="run", uselist=False, cascade="all, delete-orphan")


class AssessmentNarrative(Base):
    __tablename__ = "assessment_narratives"
    id            = Column(Integer, primary_key=True)
    run_id        = Column(Integer, ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    score_html    = Column(Text, nullable=True)
    okr_html      = Column(Text, nullable=True)
    coaching_html = Column(Text, nullable=True)
    model         = Column(String(64), nullable=True)
    prompt_version = Column(String(64), nullable=True)
    meta          = Column(JSONType, nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    run = relationship("AssessmentRun", back_populates="narrative")


class AssessmentTurn(Base):
    __tablename__ = "assessment_turns"
    id                 = Column(Integer, primary_key=True)
    run_id             = Column(Integer, ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    idx                = Column(Integer, nullable=False)   # 0..N (order within run)

    pillar             = Column(String(24), nullable=False)      # nutrition/training/resilience/goals
    concept_key        = Column(String(64), nullable=True)       # e.g. 'protein_basics'

    is_clarifier       = Column(Boolean, default=False, nullable=False)

    assistant_q        = Column(Text, nullable=True)             # assistant’s question (main or clarifier)
    user_a             = Column(Text, nullable=True)             # user’s reply

    retrieval          = Column(JSONType, nullable=True)         # [{"id":..., "type":"kb", "score":...}, ...]
    llm_raw            = Column(Text, nullable=True)             # raw JSON returned by model
    action             = Column(String(24), nullable=True)       # 'ask' | 'finish_domain' | 'concept_complete' | 'concept_forced_advance'
    confidence         = Column(Float, nullable=True)            # pillar-level conf after this turn (if supplied)
    clarifier_count     = Column(Integer, nullable=True)

    # Per-concept summary payload (one per concept when it completes or is forced)
    is_concept_summary = Column(Boolean, default=False, nullable=False)
    concept_score      = Column(Float, nullable=True)            # final score (0..100) for concept at completion
    dialogue           = Column(JSONType, nullable=True)         # mini transcript (main + clarifiers + replies)
    kb_used            = Column(JSONType, nullable=True)         # de-duped KB snippets shown to LLM for this concept

    created_at         = Column(DateTime, default=datetime.utcnow, nullable=False)

    run                = relationship("AssessmentRun", back_populates="turns")

    __table_args__ = (
        UniqueConstraint("run_id", "idx", name="uq_assessment_turns_run_idx"),
        Index("ix_assessment_turns_pillar_concept", "pillar", "concept_key"),
    )

# ──────────────────────────────────────────────────────────────────────────────
# OKR TABLES (cycles → objectives → key results + lineage to assessment/pillar)
# ──────────────────────────────────────────────────────────────────────────────

class OKRCycle(Base):
    __tablename__ = "okr_cycles"

    id              = Column(Integer, primary_key=True)
    year            = Column(Integer, nullable=False, index=True)
    quarter         = Column(String(8), nullable=False, index=True)   # e.g., "Q1","Q2","Q3","Q4"
    title           = Column(String, nullable=True)
    # Use DateTime for consistency with other models; store date at 00:00:00 if needed
    starts_on       = Column(DateTime, nullable=False)
    ends_on         = Column(DateTime, nullable=False)

    # Optional pillar weights, e.g. {"nutrition":0.30,"training":0.40,"resilience":0.30}
    pillar_weights  = Column(JSONType, nullable=True)

    created_at      = Column(DateTime, nullable=False, server_default=func.now())

    # Relationships
    objectives      = relationship("OKRObjective", back_populates="cycle", cascade="all, delete-orphan")

    __table_args__  = (
        UniqueConstraint("year", "quarter", name="uq_okr_cycles_year_quarter"),
        Index("ix_okr_cycles_dates", "starts_on", "ends_on"),
    )


class OKRObjective(Base):
    __tablename__ = "okr_objectives"

    id                         = Column(Integer, primary_key=True)
    cycle_id                   = Column(Integer, ForeignKey("okr_cycles.id", ondelete="CASCADE"), nullable=False, index=True)
    pillar_key                 = Column(String(64), nullable=False, index=True)  # "nutrition","training","resilience","recovery"
    objective                  = Column(Text, nullable=False)
    # Raw prompt text used to prime the LLM for this objective (optional, can be large)
    llm_prompt                 = Column(Text, nullable=True)

    # Owner linkage – matches users.id INTEGER field definition used elsewhere
    owner_user_id              = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    # 🔗 Lineage back to the assessment run and specific pillar result
    source_assess_session_id   = Column(Integer, ForeignKey("assess_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    source_pillar_id           = Column(Integer, ForeignKey("pillar_results.id", ondelete="SET NULL"), nullable=True, index=True)

    # Weight for rollups (default 1.0)
    weight                     = Column(Float, nullable=False, server_default=text("1.0"))

    # Optional cache for the rolled-up score of this objective (0–100)
    overall_score              = Column(Float, nullable=True)

    created_at                 = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    cycle                      = relationship("OKRCycle", back_populates="objectives")
    key_results                = relationship("OKRKeyResult", back_populates="objective", cascade="all, delete-orphan")

    # Convenience upstream navigation (lazy joined for quick reads; safe to change)
    assess_session             = relationship("AssessSession", foreign_keys=[source_assess_session_id], lazy="joined")
    pillar_result              = relationship("PillarResult", foreign_keys=[source_pillar_id], lazy="joined")

    __table_args__ = (
        Index("ix_okr_objectives_cycle_pillar", "cycle_id", "pillar_key"),
    )

class OKRKeyResult(Base):
    __tablename__ = "okr_key_results"

    id               = Column(Integer, primary_key=True)
    objective_id     = Column(Integer, ForeignKey("okr_objectives.id", ondelete="CASCADE"), nullable=False, index=True)

    kr_key           = Column(String(32), nullable=True)     # e.g., "KR1","KR2"
    description      = Column(Text, nullable=False)

    metric_label     = Column(String, nullable=True)         # e.g., "Sessions per week"
    unit             = Column(String(32), nullable=True)     # e.g., "sessions/week","litres","watts"

    baseline_num     = Column(Float, nullable=True)
    target_num       = Column(Float, nullable=True)
    target_text      = Column(Text, nullable=True)           # non-numeric target fallback

    actual_num       = Column(Float, nullable=True)          # latest numeric actual (denormalized)
    score            = Column(Float, nullable=True)          # 0..100 (latest computed)

    weight           = Column(Float, nullable=False, server_default=text("1.0"))
    status           = Column(String(16), nullable=False, server_default=text("'active'"))
    notes            = Column(Text, nullable=True)

    created_at       = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at       = Column(DateTime, default=datetime.utcnow, nullable=False)

    objective        = relationship("OKRObjective", back_populates="key_results")
    entries          = relationship("OKRKrEntry", back_populates="key_result", cascade="all, delete-orphan")
    habit_steps      = relationship("OKRKrHabitStep", back_populates="key_result", cascade="all, delete-orphan")

    __table_args__   = (
        Index("ix_okr_krs_objective", "objective_id"),
        Index("ix_okr_krs_status", "status"),
    )

class OKRKrEntry(Base):
    __tablename__ = "okr_kr_entries"

    id               = Column(Integer, primary_key=True)
    key_result_id    = Column(Integer, ForeignKey("okr_key_results.id", ondelete="CASCADE"), nullable=False, index=True)
    # Optional lineage to a user-submitted check-in that triggered this update
    check_in_id      = Column(Integer, ForeignKey("check_ins.id", ondelete="SET NULL"), nullable=True, index=True)
    occurred_at      = Column(DateTime, nullable=False, server_default=func.now())
    actual_num       = Column(Float, nullable=True)
    note             = Column(Text, nullable=True)
    source           = Column(String(64), nullable=True)     # e.g., "manual","LLM","import:garmin"

    key_result       = relationship("OKRKeyResult", back_populates="entries")

    __table_args__   = (
        Index("ix_okr_kr_entries_kr_time", "key_result_id", "occurred_at"),
    )


class OKRKrHabitStep(Base):
    __tablename__ = "okr_kr_habit_steps"

    id              = Column(Integer, primary_key=True)
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kr_id           = Column(Integer, ForeignKey("okr_key_results.id", ondelete="CASCADE"), nullable=False, index=True)
    weekly_focus_id = Column(Integer, ForeignKey("weekly_focus.id", ondelete="SET NULL"), nullable=True, index=True)
    week_no         = Column(Integer, nullable=True, index=True)
    sort_order      = Column(Integer, nullable=False, server_default=text("0"))
    step_text       = Column(Text, nullable=False)
    status          = Column(String(16), nullable=False, server_default=text("'active'"))
    source          = Column(String(64), nullable=True)
    created_at      = Column(DateTime, nullable=False, server_default=func.now())
    updated_at      = Column(DateTime, nullable=False, server_default=func.now())

    key_result      = relationship("OKRKeyResult", back_populates="habit_steps")

    __table_args__ = (
        Index("ix_okr_kr_habit_steps_kr_week_order", "kr_id", "week_no", "sort_order"),
        Index("ix_okr_kr_habit_steps_user_kr", "user_id", "kr_id"),
    )


class PsychProfile(Base):
    """
    Stores a brief psychological/readiness profile captured post-assessment to tailor KR sizing and coaching.
    """
    __tablename__ = "psych_profiles"

    id                 = Column(Integer, primary_key=True)
    user_id            = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assessment_run_id  = Column(Integer, ForeignKey("assessment_runs.id", ondelete="SET NULL"), nullable=True, index=True)

    scores             = Column(JSONType, nullable=True)          # {"q1":3,...,"q6":4}
    section_averages   = Column(JSONType, nullable=True)          # {"readiness":3.5,...}
    flags              = Column(JSONType, nullable=True)          # {"stress_sensitive":true,...}
    parameters         = Column(JSONType, nullable=True)          # {"kr_scale_hint":0.8,"tone":"gentle",...}

    completed_at       = Column(DateTime, nullable=True)
    created_at         = Column(DateTime, default=datetime.utcnow, nullable=False)

    user               = relationship("User")
    assessment_run     = relationship("AssessmentRun")

class OKRObjectiveReview(Base):
    __tablename__ = "okr_objective_reviews"

    id                 = Column(Integer, primary_key=True)
    objective_id       = Column(Integer, ForeignKey("okr_objectives.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_user_id   = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    notes              = Column(Text, nullable=False)
    created_at         = Column(DateTime, nullable=False, server_default=func.now())

    # relationship back to objective
    objective          = relationship("OKRObjective", backref="reviews")


# ──────────────────────────────────────────────────────────────────────────────
# Reporting (used by summaries and PDF)
# ──────────────────────────────────────────────────────────────────────────────

class PillarResult(Base):
    __tablename__ = "pillar_results"
    id           = Column(Integer, primary_key=True)
    run_id       = Column(Integer, ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    pillar_key   = Column(String(32), nullable=False, index=True)

    overall      = Column(Integer, nullable=False)          # 0..100 rounded (primary display)
    overall_raw  = Column(Float, nullable=True)             # optional exact value before rounding
    concept_scores = Column(JSONType, nullable=False, default=dict)  # {"fruit_veg": 85, ...}

    rationale    = Column(Text, nullable=True)
    advice       = Column(JSONType, nullable=True)          # ["feedback", "next step 1", "next step 2"]
    level        = Column(String(16), nullable=True)        # Low | Moderate | High
    confidence   = Column(Float, nullable=True)             # 0.0..1.0
    clarifier_count = Column(Integer, nullable=True)        # total clarifiers asked in this pillar
    started_at   = Column(DateTime, nullable=True)
    finished_at  = Column(DateTime, nullable=True)
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "pillar_key", name="uq_pillar_results_run_pillar"),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Personalized comms + simulations (OKR-driven touchpoints)
# ──────────────────────────────────────────────────────────────────────────────

class CheckIn(Base):
    __tablename__ = "check_ins"

    # Captures a user's self-reported progress and context per touchpoint
    id               = Column(Integer, primary_key=True)
    user_id          = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    touchpoint_type  = Column(String(64), nullable=False)            # constrained set: kickoff|adjust|wrap|prime|ad_hoc
    progress_updates = Column(JSONType, nullable=True)               # [{kr_id, delta, note}]
    blockers         = Column(JSONType, nullable=True)               # user-declared impediments
    commitments      = Column(JSONType, nullable=True)               # user-committed actions with dates
    created_at       = Column(DateTime, nullable=False, server_default=func.now())


class Touchpoint(Base):
    __tablename__ = "touchpoints"

    # Scheduled or sent outbound interactions (text/audio/video) tied to OKR coaching
    id                  = Column(Integer, primary_key=True)
    user_id             = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    type                = Column(String(64), nullable=False)        # kickoff|adjust|wrap|prime|ad_hoc
    weekly_focus_id     = Column(Integer, ForeignKey("weekly_focus.id", ondelete="SET NULL"), nullable=True, index=True)
    week_no             = Column(Integer, nullable=True)            # explicit programme week index for this touchpoint
    scheduled_at        = Column(DateTime, nullable=True)
    channel             = Column(String(64), nullable=True)
    status              = Column(String(32), nullable=False, server_default=text("'planned'"))  # planned|sent|failed|expired
    source_check_in_id  = Column(Integer, ForeignKey("check_ins.id", ondelete="SET NULL"), nullable=True, index=True)
    generated_text      = Column(Text, nullable=True)
    audio_url           = Column(String(512), nullable=True)
    video_url           = Column(String(512), nullable=True)
    meta                = Column(JSONType, nullable=True)            # {length_hint, template_id, llm_model}
    created_at          = Column(DateTime, nullable=False, server_default=func.now())
    sent_at             = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_touchpoints_user_type", "user_id", "type"),
    )


class TouchpointKR(Base):
    __tablename__ = "touchpoint_krs"

    # Explicit linkage of a touchpoint to the KRs it is focusing on (ordered)
    id             = Column(Integer, primary_key=True)
    touchpoint_id  = Column(Integer, ForeignKey("touchpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    kr_id          = Column(Integer, ForeignKey("okr_key_results.id", ondelete="CASCADE"), nullable=False, index=True)
    priority_order = Column(Integer, nullable=True)                 # 0,1,2 for top-3 focus
    role           = Column(String(32), nullable=True)              # primary|secondary
    ask_text       = Column(Text, nullable=True)                    # cached ask/action for this KR in the touchpoint

    __table_args__ = (
        UniqueConstraint("touchpoint_id", "kr_id", name="uq_touchpoint_kr"),
        Index("ix_touchpoint_krs_touchpoint_order", "touchpoint_id", "priority_order"),
    )


class OKRFocusStack(Base):
    __tablename__ = "okr_focus_stack"

    # Snapshot of prioritized KRs for a user at a given touchpoint for transparency/debug
    id             = Column(Integer, primary_key=True)
    user_id        = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    touchpoint_id  = Column(Integer, ForeignKey("touchpoints.id", ondelete="CASCADE"), nullable=True, index=True)
    items          = Column(JSONType, nullable=False)                # [{kr_id, priority_score, rationale, recommended_actions}]
    computed_at    = Column(DateTime, nullable=False, server_default=func.now())


class ContentPromptGeneration(Base):
    __tablename__ = "content_prompt_generations"

    # Stored output for admin content generator based on prompt templates
    id                = Column(Integer, primary_key=True)
    user_id           = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    created_by        = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    template_id       = Column(Integer, ForeignKey("content_prompt_templates.id", ondelete="SET NULL"), nullable=True, index=True)
    touchpoint        = Column(String(64), nullable=False, index=True)
    prompt_state      = Column(String(32), nullable=True)
    provider          = Column(String(32), nullable=True)
    test_date         = Column(Date, nullable=True)
    model_override    = Column(String(120), nullable=True)
    run_llm           = Column(Boolean, nullable=False, server_default=text("false"))
    assembled_prompt  = Column(Text, nullable=True)
    blocks            = Column(JSONType, nullable=True)
    block_order       = Column(JSONType, nullable=True)
    meta              = Column(JSONType, nullable=True)
    llm_model         = Column(String(120), nullable=True)
    llm_duration_ms   = Column(Integer, nullable=True)
    llm_content       = Column(Text, nullable=True)
    llm_error         = Column(Text, nullable=True)
    podcast_url       = Column(Text, nullable=True)
    podcast_voice     = Column(String(120), nullable=True)
    podcast_error     = Column(Text, nullable=True)
    status            = Column(String(32), nullable=True)  # assembled|ok|error
    error             = Column(Text, nullable=True)
    created_at        = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_content_prompt_generations_touchpoint_state", "touchpoint", "prompt_state"),
    )


class ContentPromptTemplate(Base):
    __tablename__ = "content_prompt_templates"

    id             = Column(Integer, primary_key=True)
    template_key   = Column(String(120), nullable=False, index=True)
    label          = Column(String(160), nullable=True)
    pillar_key     = Column(String(64), nullable=True, index=True)
    concept_code   = Column(String(64), nullable=True, index=True)
    parent_id      = Column(Integer, nullable=True)
    version        = Column(Integer, nullable=False, server_default="1")
    state          = Column(String(32), nullable=False, server_default="draft")  # draft|published
    note           = Column(Text, nullable=True)
    task_block     = Column(Text, nullable=True)
    block_order    = Column(JSONType, nullable=True)
    include_blocks = Column(JSONType, nullable=True)
    response_format = Column(String(32), nullable=True)
    is_active      = Column(Boolean, nullable=False, server_default="true")
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ──────────────────────────────────────────────────────────────────────────────
# Usage tracking (cost analytics)
# ──────────────────────────────────────────────────────────────────────────────


class UsageEvent(Base):
    __tablename__ = "usage_events"

    id            = Column(Integer, primary_key=True)
    created_at    = Column(DateTime, nullable=False, server_default=func.now())
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    provider      = Column(String(32), nullable=False)
    product       = Column(String(32), nullable=False)  # tts|stt|llm|whatsapp|storage
    model         = Column(String(120), nullable=True)
    units         = Column(Float, nullable=False, default=0.0)
    unit_type     = Column(String(32), nullable=False)  # tts_chars|audio_seconds|tokens_in|tokens_out|message
    cost_estimate = Column(Float, nullable=True)
    currency      = Column(String(8), nullable=False, server_default=text("'GBP'"))
    request_id    = Column(String(120), nullable=True)
    duration_ms   = Column(Integer, nullable=True)
    tag           = Column(String(64), nullable=True)  # weekly_flow|assessment|content_generation|admin_test
    meta          = Column(JSONType, nullable=True)

    __table_args__ = (
        Index("ix_usage_events_created", "created_at"),
        Index("ix_usage_events_provider_product", "provider", "product"),
    )


class UsageRollupDaily(Base):
    __tablename__ = "usage_rollups_daily"

    day           = Column(Date, nullable=False)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    provider      = Column(String(32), nullable=False)
    product       = Column(String(32), nullable=False)
    unit_type     = Column(String(32), nullable=False)
    tag           = Column(String(64), nullable=True)
    units         = Column(Float, nullable=False, default=0.0)
    cost_estimate = Column(Float, nullable=True)
    currency      = Column(String(8), nullable=False, server_default=text("'GBP'"))

    __table_args__ = (
        PrimaryKeyConstraint("day", "user_id", "provider", "product", "unit_type", "tag", name="pk_usage_rollups_daily"),
    )


class UsageSettings(Base):
    __tablename__ = "usage_settings"

    id                           = Column(Integer, primary_key=True)
    tts_gbp_per_1m_chars         = Column(Float, nullable=True)
    tts_chars_per_min            = Column(Float, nullable=True)
    llm_gbp_per_1m_input_tokens  = Column(Float, nullable=True)
    llm_gbp_per_1m_output_tokens = Column(Float, nullable=True)
    wa_gbp_per_message           = Column(Float, nullable=True)
    wa_gbp_per_media_message     = Column(Float, nullable=True)
    wa_gbp_per_template_message  = Column(Float, nullable=True)
    meta                         = Column(JSONType, nullable=True)
    updated_at                   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ContentPromptSettings(Base):
    __tablename__ = "content_prompt_settings"
    id                 = Column(Integer, primary_key=True)
    system_block       = Column(Text, nullable=True)
    locale_block       = Column(Text, nullable=True)
    default_block_order = Column(JSONType, nullable=True)
    updated_at         = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ContentLibraryItem(Base):
    __tablename__ = "content_library_items"

    # Stored library content by pillar/concept
    id                     = Column(Integer, primary_key=True)
    pillar_key             = Column(String(64), nullable=False, index=True)
    concept_code           = Column(String(64), nullable=True, index=True)
    title                  = Column(String(200), nullable=False)
    body                   = Column(Text, nullable=False)
    status                 = Column(String(32), nullable=True)  # draft|published
    podcast_url            = Column(Text, nullable=True)
    podcast_voice          = Column(String(64), nullable=True)
    source_type            = Column(String(64), nullable=True)
    source_url             = Column(String(512), nullable=True)
    license                = Column(String(64), nullable=True)
    published_at           = Column(DateTime, nullable=True)
    level                  = Column(String(32), nullable=True)
    tags                   = Column(JSONType, nullable=True)
    source_generation_id   = Column(Integer, ForeignKey("content_prompt_generations.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by             = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at             = Column(DateTime, nullable=False, server_default=func.now())
    updated_at             = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_content_library_items_pillar_concept", "pillar_key", "concept_code"),
    )


class EngagementEvent(Base):
    __tablename__ = "engagement_events"

    # Logged engagement outcomes per touchpoint (opens/clicks/plays/feedback)
    id              = Column(Integer, primary_key=True)
    touchpoint_id   = Column(Integer, ForeignKey("touchpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    channel         = Column(String(64), nullable=True)
    opened          = Column(Boolean, nullable=True)
    clicked         = Column(Boolean, nullable=True)
    played          = Column(Boolean, nullable=True)
    watch_time_pct  = Column(Float, nullable=True)
    feedback        = Column(JSONType, nullable=True)               # {useful, too_long, free_text}
    result          = Column(String(32), nullable=True)             # delivered|no_reply|user_replied|failed
    created_at      = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_engagement_events_touchpoint_channel", "touchpoint_id", "channel"),
    )


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id         = Column(Integer, primary_key=True)
    kind       = Column(String(64), nullable=False, index=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status     = Column(String(32), nullable=False, server_default=text("'pending'"))  # pending|running|retry|done|error
    payload    = Column(JSONType, nullable=True)
    result     = Column(JSONType, nullable=True)
    error      = Column(Text, nullable=True)
    attempts   = Column(Integer, nullable=False, server_default=text("0"))
    locked_at  = Column(DateTime, nullable=True)
    locked_by  = Column(String(120), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_background_jobs_status_kind", "status", "kind"),
    )

class WeeklyFocus(Base):
    __tablename__ = "weekly_focus"

    # The KR shortlist selected during the planning call for a given period (typically a week)
    id            = Column(Integer, primary_key=True)
    user_id       = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    starts_on     = Column(DateTime, nullable=True)
    ends_on       = Column(DateTime, nullable=True)
    week_no       = Column(Integer, nullable=True)                  # explicit programme week index
    notes         = Column(Text, nullable=True)                     # optional summary/context from planning
    created_at    = Column(DateTime, nullable=False, server_default=func.now())


class WeeklyFocusKR(Base):
    __tablename__ = "weekly_focus_krs"

    # The specific KRs chosen for the weekly focus shortlist (ordered)
    id              = Column(Integer, primary_key=True)
    weekly_focus_id = Column(Integer, ForeignKey("weekly_focus.id", ondelete="CASCADE"), nullable=False, index=True)
    kr_id           = Column(Integer, ForeignKey("okr_key_results.id", ondelete="CASCADE"), nullable=False, index=True)
    priority_order  = Column(Integer, nullable=True)               # 0,1,2 for top-3 focus
    role            = Column(String(32), nullable=True)            # primary|secondary
    rationale       = Column(Text, nullable=True)                  # why this KR made the shortlist

    __table_args__ = (
        UniqueConstraint("weekly_focus_id", "kr_id", name="uq_weekly_focus_kr"),
        Index("ix_weekly_focus_krs_focus_order", "weekly_focus_id", "priority_order"),
    )


class PreferenceInferenceAudit(Base):
    __tablename__ = "preference_inference_audit"

    # Tracks inferred/updated user preferences from interactions to monitor LLM accuracy
    id                 = Column(Integer, primary_key=True)
    user_id            = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    source_touchpoint_id = Column(Integer, ForeignKey("touchpoints.id", ondelete="SET NULL"), nullable=True, index=True)
    key                = Column(String(128), nullable=False)        # e.g., "tone_pref","medium","time_window"
    old_value          = Column(Text, nullable=True)
    new_value          = Column(Text, nullable=True)
    confidence         = Column(Float, nullable=True)               # 0..1 confidence from model/human
    created_at         = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_pref_inference_user_key", "user_id", "key"),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Compatibility aliases for legacy imports (safe to keep)
# ──────────────────────────────────────────────────────────────────────────────

EMBEDDING_DIM = 256  # matches seed’s placeholder embedding dim
KBSnippet = KbSnippet
KBVector  = KbVector
