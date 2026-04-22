from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from .config import DATABASE_URL


connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()


def init_db() -> None:
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _migrate_members_table()
    _migrate_survey_configs_table()
    _migrate_staff_users_table()
    _migrate_okrs_table()
    from .services import seed_default_okrs, sync_q2_2026_okrs

    with SessionLocal() as session:
        seed_default_okrs(session)
        sync_q2_2026_okrs(session)


def _migrate_members_table() -> None:
    if not DATABASE_URL.startswith("sqlite"):
        return
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(membersense_members)").fetchall()}
        if "external_member_id" not in columns:
            conn.exec_driver_sql("ALTER TABLE membersense_members ADD COLUMN external_member_id VARCHAR(64)")
        if "mobile_raw" not in columns:
            conn.exec_driver_sql("ALTER TABLE membersense_members ADD COLUMN mobile_raw VARCHAR(64)")
        if "expiry_date" not in columns:
            conn.exec_driver_sql("ALTER TABLE membersense_members ADD COLUMN expiry_date DATE")
            if "cancellation_date" in columns:
                conn.exec_driver_sql(
                    "UPDATE membersense_members SET expiry_date = cancellation_date "
                    "WHERE expiry_date IS NULL AND cancellation_date IS NOT NULL"
                )
        conversation_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(membersense_conversations)").fetchall()
        }
        if "app_link_token" not in conversation_columns:
            conn.exec_driver_sql("ALTER TABLE membersense_conversations ADD COLUMN app_link_token VARCHAR(96)")
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_membersense_members_external_member_id "
            "ON membersense_members (external_member_id)"
        )
        conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_membersense_members_mobile_raw ON membersense_members (mobile_raw)"
        )
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_membersense_conversations_app_link_token "
            "ON membersense_conversations (app_link_token)"
        )
        import_columns = {
            row[1] for row in conn.exec_driver_sql("PRAGMA table_info(membersense_import_batches)").fetchall()
        }
        if "rows_skipped" not in import_columns:
            conn.exec_driver_sql(
                "ALTER TABLE membersense_import_batches ADD COLUMN rows_skipped INTEGER NOT NULL DEFAULT 0"
            )
        conn.exec_driver_sql(
            "UPDATE membersense_members SET membership_status = 'current' "
            "WHERE lower(trim(membership_status)) IN ('not setup', 'not set up', 'active')"
        )


def _migrate_survey_configs_table() -> None:
    table_name = "membersense_survey_configs"
    dialect = engine.dialect.name
    avatar_columns = {
        "label": ("VARCHAR(180)", "VARCHAR(180)"),
        "intro": ("TEXT", "TEXT"),
        "completion": ("TEXT", "TEXT"),
        "questions": ("JSON", "JSONB"),
        "avatar_script": ("TEXT", "TEXT"),
        "avatar_video_url": ("TEXT", "TEXT"),
        "avatar_poster_url": ("TEXT", "TEXT"),
        "avatar_character": ("VARCHAR(80)", "VARCHAR(80)"),
        "avatar_style": ("VARCHAR(120)", "VARCHAR(120)"),
        "avatar_voice": ("VARCHAR(160)", "VARCHAR(160)"),
        "avatar_status": ("VARCHAR(32)", "VARCHAR(32)"),
        "avatar_job_id": ("VARCHAR(128)", "VARCHAR(128)"),
        "avatar_error": ("TEXT", "TEXT"),
        "avatar_summary_url": ("TEXT", "TEXT"),
        "avatar_source": ("VARCHAR(64)", "VARCHAR(64)"),
        "avatar_payload": ("JSON", "JSONB"),
        "avatar_generated_at": ("DATETIME", "TIMESTAMP"),
        "created_at": ("DATETIME", "TIMESTAMP"),
        "updated_at": ("DATETIME", "TIMESTAMP"),
    }
    with engine.begin() as conn:
        if dialect == "sqlite":
            columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()}
            if not columns:
                return
            for name, (sqlite_type, _) in avatar_columns.items():
                if name not in columns:
                    conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {name} {sqlite_type}")
            conn.exec_driver_sql(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_flow_key ON {table_name} (flow_key)"
            )
            return
        if dialect == "postgresql":
            for name, (_, postgres_type) in avatar_columns.items():
                conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {name} {postgres_type}")
            conn.exec_driver_sql(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_flow_key ON {table_name} (flow_key)"
            )


def _migrate_staff_users_table() -> None:
    table_name = "membersense_staff_users"
    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "sqlite":
            columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()}
            if not columns:
                return
            if "username" not in columns:
                conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN username VARCHAR(80)")
            if "mobile" not in columns:
                conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN mobile VARCHAR(64)")
            conn.exec_driver_sql(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_username ON {table_name} (username)"
            )
            return
        if dialect == "postgresql":
            conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS username VARCHAR(80)")
            conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS mobile VARCHAR(64)")
            conn.exec_driver_sql(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_username ON {table_name} (username)"
            )


def _migrate_okrs_table() -> None:
    dialect = engine.dialect.name
    tables = {
        "membersense_okr_objectives": {
            "champions": ("VARCHAR(240)", "VARCHAR(240)"),
            "objective_number": ("INTEGER", "INTEGER"),
        },
        "membersense_okr_key_results": {
            "key_result_number": ("INTEGER", "INTEGER"),
            "actual_updated_at": ("DATETIME", "TIMESTAMP"),
            "direction": ("VARCHAR(24)", "VARCHAR(24)"),
        },
    }
    with engine.begin() as conn:
        for table_name, columns_to_add in tables.items():
            if dialect == "sqlite":
                columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()}
                if not columns:
                    continue
                for name, (sqlite_type, _) in columns_to_add.items():
                    if name not in columns:
                        conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN {name} {sqlite_type}")
                        columns.add(name)
                if table_name == "membersense_okr_objectives" and "objective_number" in columns:
                    conn.exec_driver_sql(
                        "UPDATE membersense_okr_objectives "
                        "SET objective_number = CASE lower(trim(area)) "
                        "WHEN 'club growth' THEN 1 "
                        "WHEN 'onboarding' THEN 2 "
                        "WHEN 'experience' THEN 3 "
                        "WHEN 'team onboarding' THEN 4 "
                        "ELSE id END "
                        "WHERE objective_number IS NULL"
                    )
                    conn.exec_driver_sql(
                        "CREATE INDEX IF NOT EXISTS ix_membersense_okr_objectives_objective_number "
                        "ON membersense_okr_objectives (objective_number)"
                    )
                if table_name == "membersense_okr_key_results" and "direction" in columns:
                    conn.exec_driver_sql(
                        "UPDATE membersense_okr_key_results "
                        "SET direction = 'increase' "
                        "WHERE direction IS NULL OR trim(direction) = ''"
                    )
                continue
            if dialect == "postgresql":
                for name, (_, postgres_type) in columns_to_add.items():
                    conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {name} {postgres_type}")
                if table_name == "membersense_okr_objectives":
                    conn.exec_driver_sql(
                        "UPDATE membersense_okr_objectives "
                        "SET objective_number = CASE lower(trim(area)) "
                        "WHEN 'club growth' THEN 1 "
                        "WHEN 'onboarding' THEN 2 "
                        "WHEN 'experience' THEN 3 "
                        "WHEN 'team onboarding' THEN 4 "
                        "ELSE id END "
                        "WHERE objective_number IS NULL"
                    )
                    conn.exec_driver_sql(
                        "CREATE INDEX IF NOT EXISTS ix_membersense_okr_objectives_objective_number "
                        "ON membersense_okr_objectives (objective_number)"
                    )
                if table_name == "membersense_okr_key_results":
                    conn.exec_driver_sql(
                        "UPDATE membersense_okr_key_results "
                        "SET direction = 'increase' "
                        "WHERE direction IS NULL OR btrim(direction) = ''"
                    )
