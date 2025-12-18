from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey,
    UniqueConstraint, Index, text
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
    created_on = Column(DateTime, nullable=True)
    updated_on = Column(DateTime, nullable=True)
    is_superuser = Column(Boolean, nullable=False, server_default=text("false"))
    admin_role  = Column(String(32), nullable=False, server_default=text("'member'"))
    consent_given = Column(Boolean, nullable=False, server_default=text("false"))
    consent_at = Column(DateTime, nullable=True)
    onboard_complete = Column(Boolean, nullable=False, server_default=text("false"))

    sessions   = relationship("AssessSession", back_populates="user", cascade="all, delete-orphan")
    club       =relationship("Club")

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


# Educational content (news/updates/longer-form) kept separate from assessment KB
class EduContent(Base):
    __tablename__ = "edu_content"

    id            = Column(Integer, primary_key=True)
    pillar_key    = Column(String(32), nullable=False, index=True)   # nutrition/training/resilience/goals
    concept_code  = Column(String(64), nullable=True, index=True)    # e.g. 'sleep_quality'
    title         = Column(String(200), nullable=True)
    text          = Column(Text, nullable=False)                     # normalized summary/script body
    source_type   = Column(String(64), nullable=True)                # public_domain|journal|blog|manual
    source_url    = Column(String(512), nullable=True)
    license       = Column(String(64), nullable=True)                # e.g., cc0, cc-by, internal
    published_at  = Column(DateTime, nullable=True)
    level         = Column(String(32), nullable=True)                # intro|intermediate|advanced
    tags          = Column(JSONType, nullable=True)                  # ["sleep","cbt-i","chronotype"]
    beats         = Column(JSONType, nullable=True)                  # talking points for media generation
    is_active     = Column(Boolean, nullable=False, server_default=sa_text("true"))
    meta          = Column(JSONType, nullable=True)                  # {"source_confidence":0.9,"reviewed_at":...}
    created_at    = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_edu_content_pillar_concept_active", "pillar_key", "concept_code", "is_active"),
    )

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


class ContentTemplate(Base):
    __tablename__ = "content_templates"

    # Versioned templated bodies used to generate personalized touchpoint messages
    id              = Column(Integer, primary_key=True)
    name            = Column(String(160), nullable=False)
    touchpoint_type = Column(String(64), nullable=False)
    persona_tag     = Column(String(64), nullable=True)
    status_state    = Column(String(32), nullable=True)              # on_track|off_track|low_energy
    body            = Column(Text, nullable=False)                   # templated text with slots
    slots           = Column(JSONType, nullable=True)                # ["kr","metric","deadline"]
    version         = Column(Integer, nullable=False, server_default=text("1"))
    is_active       = Column(Boolean, nullable=False, server_default=text("true"))
    created_at      = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        Index("ix_content_templates_touchpoint_persona", "touchpoint_type", "persona_tag"),
    )


class GenerationRun(Base):
    __tablename__ = "generation_runs"

    # Audit log for LLM/auto-media generation per touchpoint
    id             = Column(Integer, primary_key=True)
    touchpoint_id  = Column(Integer, ForeignKey("touchpoints.id", ondelete="CASCADE"), nullable=False, index=True)
    template_id    = Column(Integer, ForeignKey("content_templates.id", ondelete="SET NULL"), nullable=True, index=True)
    llm_prompt     = Column(JSONType, nullable=True)
    llm_response   = Column(JSONType, nullable=True)
    tts_engine     = Column(String(120), nullable=True)
    video_engine   = Column(String(120), nullable=True)
    duration_ms    = Column(Integer, nullable=True)
    status         = Column(String(32), nullable=True)              # started|ok|error
    created_at     = Column(DateTime, nullable=False, server_default=func.now())


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
