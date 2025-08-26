# app/db.py
from __future__ import annotations
import os
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ──────────────────────────────────────────────────────────────────────────────
# DATABASE URL
# ──────────────────────────────────────────────────────────────────────────────

# Prefer env var; fall back to config.py if present; else default local PG.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    try:
        from .config import settings  # optional fallback
        DATABASE_URL = getattr(settings, "DATABASE_URL", None)
    except Exception:
        DATABASE_URL = None
if not DATABASE_URL:
    # final fallback: local Postgres without credentials (override via .env)
    DATABASE_URL = "postgresql+psycopg2://localhost/aicoach"

# ──────────────────────────────────────────────────────────────────────────────
# SQLAlchemy engine/session
# ──────────────────────────────────────────────────────────────────────────────
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _is_postgres() -> bool:
    try:
        return engine.url.get_backend_name().startswith("postgres")
    except Exception:
        return False

def _table_exists(conn, table_name: str) -> bool:
    """
    Works on Postgres and SQLite. Uses information_schema for PG and sqlite_master for SQLite.
    """
    try:
        if _is_postgres():
            res = conn.execute(text("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = :t
                )
            """), {"t": table_name}).scalar()
            return bool(res)
        else:
            res = conn.execute(text("""
                SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t
            """), {"t": table_name}).first()
            return bool(res)
    except Exception:
        return False

def ensure_pgvector_and_indexes() -> None:
    """
    Create pgvector extension and KB indexes (idempotent). No‑op on non‑Postgres.
    Safe to call on every startup.
    """
    if not _is_postgres():
        return

    with engine.begin() as conn:
        # 1) Ensure pgvector extension
        try:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        except Exception as e:
            print(f"[db] WARN: failed to CREATE EXTENSION vector: {e}")

        # If kb_vectors isn't created yet, indexes will be attempted later.
        if not _table_exists(conn, "kb_vectors"):
            return

        # 2) ivfflat index on kb_vectors.embedding (optional, faster ANN)
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes WHERE indexname = 'kb_vec_idx'
                    ) THEN
                        CREATE INDEX kb_vec_idx
                          ON kb_vectors USING ivfflat (embedding vector_cosine_ops)
                          WITH (lists = 100);
                    END IF;
                END$$;
            """))
        except Exception as e:
            # Can fail if extension missing or permissions—log and continue
            print(f"[db] WARN: could not create kb_vec_idx: {e}")

        # 3) metadata index for fast filters
        try:
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_indexes WHERE indexname = 'kb_meta_idx'
                    ) THEN
                        CREATE INDEX kb_meta_idx
                          ON kb_vectors (pillar_key, concept_key, type, locale);
                    END IF;
                END$$;
            """))
        except Exception as e:
            print(f"[db] WARN: could not create kb_meta_idx: {e}")

def maybe_seed_concepts_and_kb() -> None:
    """
    Auto‑seed concepts & KB only if tables exist and appear empty.
    Uses app.seed.seed_concepts_and_kb_if_empty().
    """
    if os.getenv("AI_COACH_DISABLE_AUTO_SEED", "0") == "1":
        print("[auto-seed] Skipped by env (AI_COACH_DISABLE_AUTO_SEED=1).")
        return

    try:
        from app.seed import seed_concepts_and_kb_if_empty
    except Exception as e:
        print(f"[auto-seed] Could not import seeder from app.seed: {e}")
        return

    with engine.begin() as conn:
        have_concepts = _table_exists(conn, "concepts")
        have_kb = _table_exists(conn, "kb_vectors")

    # If tables aren’t there yet, init_db() will call this again after create_all.
    if not (have_concepts and have_kb):
        return

    # Delegate to seeder (handles idempotency)
    try:
        seed_concepts_and_kb_if_empty()
    except Exception as e:
        print(f"[auto-seed] Failed while seeding: {e}")

def init_db() -> None:
    """
    One‑shot initializer to call at app startup:
      1) create tables,
      2) ensure pgvector + indexes,
      3) auto‑seed concepts & KB if empty.
    """
    # Import here to avoid circular import at module import time
    from .models import Base

    # 1) Create all tables
    Base.metadata.create_all(bind=engine)

    # 2) pgvector + indexes (Postgres only)
    ensure_pgvector_and_indexes()

    # 3) Concepts / KB auto‑seed if empty
    maybe_seed_concepts_and_kb()