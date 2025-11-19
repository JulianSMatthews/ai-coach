from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Boolean, Float, ForeignKey,
    UniqueConstraint, Index, text
)
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
    metadata   = Column(JSONType, nullable=True)
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

    occurred_at      = Column(DateTime, nullable=False, server_default=func.now())
    actual_num       = Column(Float, nullable=True)
    note             = Column(Text, nullable=True)
    source           = Column(String(64), nullable=True)     # e.g., "manual","LLM","import:garmin"

    key_result       = relationship("OKRKeyResult", back_populates="entries")

    __table_args__   = (
        Index("ix_okr_kr_entries_kr_time", "key_result_id", "occurred_at"),
    )

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
# Compatibility aliases for legacy imports (safe to keep)
# ──────────────────────────────────────────────────────────────────────────────

EMBEDDING_DIM = 256  # matches seed’s placeholder embedding dim
KBSnippet = KbSnippet
KBVector  = KbVector
