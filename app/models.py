# app/models.py
from __future__ import annotations

import os
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Index, Float, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.dialects.postgresql import JSONB  # works on Postgres
from pgvector.sqlalchemy import Vector

Base = declarative_base()

# Fallback for non‑Postgres environments
try:
    JSONType = JSONB
except Exception:  # pragma: no cover
    from sqlalchemy import JSON as JSONType  # type: ignore

# ──────────────────────────────────────────────────────────────────────────────
# Existing app models
# ──────────────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id                = Column(Integer, primary_key=True)
    name              = Column(String(120), nullable=False)
    phone             = Column(String(32), nullable=False, unique=True, index=True)
    tz                = Column(String(64), nullable=False, default="Europe/London")

    # Pillar levels (LLM-assessed)
    nutrition_level   = Column(String(16), nullable=True)   # "Low" | "Moderate" | "High"
    training_level    = Column(String(16), nullable=True)
    resilience_level  = Column(String(16), nullable=True)    # renamed from psych_level

    # Goals snapshot
    goal_primary      = Column(Text, nullable=True)
    goal_timeframe    = Column(Text, nullable=True)
    goal_drivers      = Column(Text, nullable=True)
    goal_support      = Column(Text, nullable=True)
    goal_commitment   = Column(Text, nullable=True)
    goals_updated_at  = Column(DateTime, nullable=True)

    # Onboarding gate
    onboard_complete  = Column(Boolean, default=False, nullable=False)

    updated_on   = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_on   = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    assess_sessions   = relationship("AssessSession", back_populates="user", cascade="all, delete-orphan")
    job_audits        = relationship("JobAudit", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User id={self.id} phone={self.phone} tz={self.tz}>"


class AssessSession(Base):
    __tablename__ = "assess_sessions"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    domain     = Column(String(24), nullable=False)  # "nutrition" | "training" | "resilience" | "goals" | "combined"
    is_active  = Column(Boolean, default=True, nullable=False)
    turn_count = Column(Integer, default=0, nullable=False)
    state      = Column(JSONType, nullable=True)     # JSON blob for conversation state

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    user       = relationship("User", back_populates="assess_sessions")

    def __repr__(self) -> str:
        return f"<AssessSession id={self.id} user_id={self.user_id} domain={self.domain} active={self.is_active}>"


class JobAudit(Base):
    __tablename__ = "job_audits"

    id        = Column(Integer, primary_key=True)
    user_id   = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind      = Column(String(64), nullable=False)   # e.g. "daily_micro_nudge", "weekly_reflection"
    payload   = Column(JSONType, nullable=True)
    created_at= Column(DateTime, nullable=False, default=datetime.utcnow)

    user      = relationship("User", back_populates="job_audits")

    def __repr__(self) -> str:
        return f"<JobAudit id={self.id} user_id={self.user_id} kind={self.kind}>"


class MessageLog(Base):
    """
    Source of truth for chat events. Insert rows for messages that were actually
    received (inbound webhook) or successfully handed to Twilio (outbound).
    """
    __tablename__ = "message_logs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    phone = Column(String(32), nullable=False, index=True)  # bare E.164
    direction = Column(String(16), nullable=False)  # 'inbound' | 'outbound'
    category = Column(String(64), nullable=True)    # 'nutrition_assessment', 'combined', 'nudge', etc.
    text = Column(Text, nullable=False)
    twilio_sid = Column(String(64), nullable=True)  # set for successful outbound
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Optional denorm for admin display
    user_name = Column(String(120), nullable=True)


# Handy index for reviews
Index("ix_message_logs_user_created", MessageLog.user_id, MessageLog.created_at.desc())
Index("ix_assess_sessions_user_active", AssessSession.user_id, AssessSession.is_active)
Index("ix_job_audits_user_created", JobAudit.user_id, JobAudit.created_at)

# ──────────────────────────────────────────────────────────────────────────────
# Concept taxonomy & rubric
# ──────────────────────────────────────────────────────────────────────────────

class Pillar(Base):
    __tablename__ = "pillars"
    id         = Column(Integer, primary_key=True)
    key        = Column(String(32), unique=True, index=True)  # "nutrition" | "training" | "resilience"
    name       = Column(String(64), nullable=False)
    sort_order = Column(Integer, default=0, nullable=False)
    active     = Column(Boolean, default=True, nullable=False)

    concepts   = relationship("Concept", back_populates="pillar", cascade="all, delete-orphan")


class Concept(Base):
    __tablename__ = "concepts"
    id          = Column(Integer, primary_key=True)
    pillar_id   = Column(Integer, ForeignKey("pillars.id", ondelete="CASCADE"), nullable=False, index=True)
    key         = Column(String(64), nullable=False, index=True)         # e.g. "protein_basics"
    name        = Column(String(128), nullable=False)
    weight      = Column(Integer, default=1, nullable=False)
    description = Column(Text, default="")
    sort_order  = Column(Integer, default=0, nullable=False)
    active      = Column(Boolean, default=True, nullable=False)
    version     = Column(String(16), default="1.0.0")

    pillar      = relationship("Pillar", back_populates="concepts")
    rubrics     = relationship("ConceptRubric", back_populates="concept", cascade="all, delete-orphan")
    questions   = relationship("ConceptQuestion", back_populates="concept", cascade="all, delete-orphan")
    clarifiers  = relationship("ConceptClarifier", back_populates="concept", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("pillar_id", "key", name="uq_concept_pillar_key"),)


class ConceptRubric(Base):
    __tablename__ = "concept_rubrics"
    id         = Column(Integer, primary_key=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    level      = Column(String(16), nullable=False)   # "low" | "moderate" | "high"
    band_min   = Column(Float, default=0.0, nullable=False)
    band_max   = Column(Float, default=1.0, nullable=False)
    anchors    = Column(Text, default="")
    examples   = Column(Text, default="")

    concept    = relationship("Concept", back_populates="rubrics")


class ConceptQuestion(Base):
    __tablename__ = "concept_questions"
    id         = Column(Integer, primary_key=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    text       = Column(Text, nullable=False)
    active     = Column(Boolean, default=True, nullable=False)

    concept    = relationship("Concept", back_populates="questions")


class ConceptClarifier(Base):
    __tablename__ = "concept_clarifiers"
    id         = Column(Integer, primary_key=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    text       = Column(Text, nullable=False)
    active     = Column(Boolean, default=True, nullable=False)

    concept    = relationship("Concept", back_populates="clarifiers")


class UserConceptState(Base):
    __tablename__ = "user_concept_state"
    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    concept_id   = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False, index=True)
    score        = Column(Float, nullable=True)         # None = Unknown
    asked_count  = Column(Integer, default=0, nullable=False)
    last_asked_at= Column(DateTime, nullable=True)
    notes        = Column(Text, default="")
    updated_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "concept_id", name="uq_user_concept"),)

# ──────────────────────────────────────────────────────────────────────────────
# Knowledge base (text + vectors)
# ──────────────────────────────────────────────────────────────────────────────

EMBEDDING_DIM = int(os.getenv("KB_EMBED_DIM", "1536"))
try:
    from pgvector.sqlalchemy import Vector as PGVector
    VectorType = PGVector(EMBEDDING_DIM)  # cosine distance ops in Postgres
    HAS_PGVECTOR = True
except Exception:
    from sqlalchemy import JSON as VectorJSON  # fallback
    VectorType = VectorJSON
    HAS_PGVECTOR = False


class KBSnippet(Base):
    __tablename__ = "kb_snippets"
    id          = Column(String(64), primary_key=True)   # stable id from kb JSON
    pillar_key  = Column(String(32), index=True)
    concept_key = Column(String(64), index=True)
    type        = Column(String(32), default="definition")  # rubric/example_high/misconception/howto/metric
    text        = Column(Text, nullable=False)
    locale      = Column(String(16), default="en-GB")
    tags        = Column(String(256), default="")
    weight      = Column(Float, default=1.0)
    version     = Column(String(16), default="1.0.0")
    updated_at  = Column(DateTime, default=datetime.utcnow, nullable=False)


class KBVector(Base):
    __tablename__ = "kb_vectors"

    id          = Column(Text, primary_key=True)  # ← string IDs like "nut_protein_def_001"
    pillar_key  = Column(String(32), index=True, nullable=False)
    concept_key = Column(String(64), index=True, nullable=False)
    type        = Column(String(32), index=True, nullable=False)   # e.g., "guideline" | "example"
    locale      = Column(String(8),  index=True, nullable=False, default="en")
    # ✅ must be pgvector, not JSON
    embedding   = Column(Vector(1536), nullable=False)
    title       = Column(String(255), nullable=False)
    text        = Column(Text, nullable=False)
    version     = Column(String(16), nullable=True, default=1)
    created_at  = Column(DateTime, default=datetime.utcnow, nullable=False)

# ──────────────────────────────────────────────────────────────────────────────
# Assessment review / audit
# ──────────────────────────────────────────────────────────────────────────────

class AssessmentRun(Base):
    __tablename__ = "assessment_runs"
    id            = Column(Integer, primary_key=True)
    user_id       = Column(Integer, index=True, nullable=False)
    started_at    = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at   = Column(DateTime, nullable=True)
    pillars       = Column(JSONType, nullable=False)      # e.g. ["nutrition","training","resilience","goals"]
    model_name    = Column(String(64), default="gpt-5-thinking")
    model_hash    = Column(String(64), default="")
    kb_version    = Column(String(32), default="1.0.0")
    rubric_version= Column(String(32), default="1.0.0")
    is_completed  = Column(Boolean, default=False, nullable=False)

    turns         = relationship("AssessmentTurn", back_populates="run", cascade="all, delete-orphan")
    results       = relationship("PillarResult", back_populates="run", cascade="all, delete-orphan")


class AssessmentTurn(Base):
    __tablename__ = "assessment_turns"
    id           = Column(Integer, primary_key=True)
    run_id       = Column(Integer, ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    idx          = Column(Integer, nullable=False)   # 0..N
    pillar       = Column(String(24), nullable=False)  # nutrition/training/resilience/goals
    concept_key  = Column(String(64), nullable=True)
    is_clarifier = Column(Boolean, default=False, nullable=False)

    assistant_q  = Column(Text, nullable=True)
    user_a       = Column(Text, nullable=True)

    retrieval    = Column(JSONType, nullable=True)   # [{"id":"nut_protein_001","type":"rubric","score":0.41}, ...]
    llm_raw      = Column(Text, nullable=True)       # raw JSON returned by model
    action       = Column(String(24), nullable=True) # ask | finish_domain
    deltas       = Column(JSONType, nullable=True)   # {"protein_basics":{"delta":0.3,"note":"..."}}
    confidence   = Column(Float, nullable=True)      # pillar conf after this turn (if computed)

    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)

    run          = relationship("AssessmentRun", back_populates="turns")
    deltas_rows  = relationship("ConceptDelta", back_populates="turn", cascade="all, delete-orphan")


class ConceptDelta(Base):
    __tablename__ = "concept_deltas"
    id           = Column(Integer, primary_key=True)
    turn_id      = Column(Integer, ForeignKey("assessment_turns.id", ondelete="CASCADE"), nullable=False, index=True)
    pillar       = Column(String(24), nullable=False)
    concept_key  = Column(String(64), nullable=False)
    score_before = Column(Float, nullable=True)      # None allowed
    delta        = Column(Float, nullable=False)
    score_after  = Column(Float, nullable=True)
    note         = Column(Text, default="")

    turn         = relationship("AssessmentTurn", back_populates="deltas_rows")


class PillarResult(Base):
    __tablename__ = "pillar_results"
    id           = Column(Integer, primary_key=True)
    run_id       = Column(Integer, ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    pillar       = Column(String(24), nullable=False)
    level        = Column(String(16), nullable=False)     # Low/Moderate/High
    confidence   = Column(Float, nullable=False)          # 0..1
    coverage     = Column(JSONType, nullable=True)        # snapshot of concept scores at finish
    summary_msg  = Column(Text, nullable=True)

    run          = relationship("AssessmentRun", back_populates="results")


class ReviewFeedback(Base):
    __tablename__ = "review_feedback"
    id           = Column(Integer, primary_key=True)
    run_id       = Column(Integer, ForeignKey("assessment_runs.id", ondelete="CASCADE"), index=True)
    turn_id      = Column(Integer, ForeignKey("assessment_turns.id", ondelete="CASCADE"), index=True, nullable=True)
    reviewer     = Column(String(64), nullable=False)     # email or id
    rating_q     = Column(Integer, nullable=True)         # 1..5
    rating_rag   = Column(Integer, nullable=True)         # 1..5
    rating_score = Column(Integer, nullable=True)         # 1..5
    comment      = Column(Text, default="")
    suggested_snippet = Column(Text, default="")
    created_at   = Column(DateTime, default=datetime.utcnow, nullable=False)
