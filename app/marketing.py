from __future__ import annotations

import threading

from sqlalchemy import text as sa_text

from .db import engine, _is_postgres, _table_exists

_MARKETING_SCHEMA_READY = False
_MARKETING_SCHEMA_LOCK = threading.Lock()


def ensure_marketing_schema() -> None:
    """
    Ensure marketing lead tracking schema exists (idempotent, non-destructive).
    Safe to run at startup on a live system.
    """
    global _MARKETING_SCHEMA_READY
    if _MARKETING_SCHEMA_READY:
        return
    with _MARKETING_SCHEMA_LOCK:
        if _MARKETING_SCHEMA_READY:
            return
        try:
            from .models import MarketingLead  # local import avoids cycles

            MarketingLead.__table__.create(bind=engine, checkfirst=True)
        except Exception as e:
            print(f"[marketing] ensure table failed: {e}")

        with engine.begin() as conn:
            if not _table_exists(conn, "marketing_leads"):
                _MARKETING_SCHEMA_READY = True
                return

            is_pg = _is_postgres()
            json_type = "jsonb" if is_pg else "text"
            bool_default = "false" if is_pg else "0"
            alterations = [
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS user_id integer;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS club_id integer;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS source varchar(64);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS campaign varchar(120);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS utm_source varchar(180);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS utm_medium varchar(180);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS utm_campaign varchar(180);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS utm_term varchar(180);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS utm_content varchar(180);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS fbclid varchar(255);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS gclid varchar(255);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS msclkid varchar(255);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS ttclid varchar(255);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS meta_campaign_id varchar(96);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS meta_adset_id varchar(96);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS meta_ad_id varchar(96);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS meta_creative_id varchar(96);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS placement varchar(120);",
                f"ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS lead_key_used boolean DEFAULT {bool_default};",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS landing_path text;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS referrer_url text;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS client_ip varchar(64);",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS user_agent text;",
                f"ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS raw_meta {json_type};",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS landing_viewed_at timestamp;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS assessment_started_at timestamp;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS identity_claimed_at timestamp;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS results_viewed_at timestamp;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS created_at timestamp;",
                "ALTER TABLE marketing_leads ADD COLUMN IF NOT EXISTS updated_at timestamp;",
            ]
            for stmt in alterations:
                try:
                    conn.execute(sa_text(stmt))
                except Exception:
                    pass

            index_stmts = [
                "CREATE INDEX IF NOT EXISTS ix_marketing_leads_user_id ON marketing_leads (user_id);",
                "CREATE INDEX IF NOT EXISTS ix_marketing_leads_club_id ON marketing_leads (club_id);",
                "CREATE INDEX IF NOT EXISTS ix_marketing_leads_created_at ON marketing_leads (created_at);",
                "CREATE INDEX IF NOT EXISTS ix_marketing_leads_source ON marketing_leads (source);",
                "CREATE INDEX IF NOT EXISTS ix_marketing_leads_campaign ON marketing_leads (campaign);",
                "CREATE INDEX IF NOT EXISTS ix_marketing_leads_source_campaign_created ON marketing_leads (source, campaign, created_at);",
                "CREATE INDEX IF NOT EXISTS ix_marketing_leads_meta_campaign ON marketing_leads (meta_campaign_id);",
            ]
            for stmt in index_stmts:
                try:
                    conn.execute(sa_text(stmt))
                except Exception:
                    pass

            backfill_stmts = [
                """
                UPDATE marketing_leads
                SET landing_viewed_at = created_at
                WHERE landing_viewed_at IS NULL
                  AND created_at IS NOT NULL;
                """,
                """
                UPDATE marketing_leads
                SET club_id = (
                    SELECT users.club_id
                    FROM users
                    WHERE users.id = marketing_leads.user_id
                )
                WHERE club_id IS NULL
                  AND user_id IS NOT NULL;
                """,
            ]
            for stmt in backfill_stmts:
                try:
                    conn.execute(sa_text(stmt))
                except Exception:
                    pass

        _MARKETING_SCHEMA_READY = True
