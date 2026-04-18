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
    _migrate_staff_users_table()


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
            conn.exec_driver_sql(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_username ON {table_name} (username)"
            )
            return
        if dialect == "postgresql":
            conn.exec_driver_sql(f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS username VARCHAR(80)")
            conn.exec_driver_sql(
                f"CREATE UNIQUE INDEX IF NOT EXISTS ix_{table_name}_username ON {table_name} (username)"
            )
