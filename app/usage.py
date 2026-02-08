from __future__ import annotations

from datetime import datetime, timedelta
import os
import math

from sqlalchemy import func, case, text as sa_text

from .db import SessionLocal, engine, _is_postgres, _table_exists
from .models import UsageEvent, UsageRollupDaily, UsageSettings


_USAGE_SCHEMA_READY = False


def _load_usage_settings() -> UsageSettings | None:
    try:
        ensure_usage_schema()
        with SessionLocal() as s:
            return s.query(UsageSettings).order_by(UsageSettings.id.desc()).first()
    except Exception:
        return None


def _tts_rate_gbp_per_1m_chars() -> tuple[float, str]:
    row = _load_usage_settings()
    if row and row.tts_gbp_per_1m_chars is not None:
        return float(row.tts_gbp_per_1m_chars), "db"
    raw = (
        os.getenv("USAGE_TTS_GBP_PER_1M_CHARS")
        or os.getenv("USAGE_TTS_COST_PER_1M_CHARS")
        or ""
    ).strip()
    if raw:
        try:
            return float(raw), "env"
        except Exception:
            return 12.0, "default"
    return 12.0, "default"


def _tts_chars_per_min() -> float:
    row = _load_usage_settings()
    if row and row.tts_chars_per_min is not None:
        return float(row.tts_chars_per_min)
    raw = (os.getenv("USAGE_TTS_CHARS_PER_MIN") or "").strip()
    if raw:
        try:
            return float(raw)
        except Exception:
            return 900.0
    return 900.0


def _llm_rate_gbp_per_1m_input_tokens() -> tuple[float, str]:
    row = _load_usage_settings()
    if row and row.llm_gbp_per_1m_input_tokens is not None:
        return float(row.llm_gbp_per_1m_input_tokens), "db"
    raw = (os.getenv("USAGE_LLM_GBP_PER_1M_INPUT_TOKENS") or "").strip()
    if raw:
        try:
            return float(raw), "env"
        except Exception:
            return 0.0, "default"
    return 0.0, "default"


def _llm_rate_gbp_per_1m_output_tokens() -> tuple[float, str]:
    row = _load_usage_settings()
    if row and row.llm_gbp_per_1m_output_tokens is not None:
        return float(row.llm_gbp_per_1m_output_tokens), "db"
    raw = (os.getenv("USAGE_LLM_GBP_PER_1M_OUTPUT_TOKENS") or "").strip()
    if raw:
        try:
            return float(raw), "env"
        except Exception:
            return 0.0, "default"
    return 0.0, "default"


def _wa_rate_gbp_per_message() -> tuple[float, str]:
    row = _load_usage_settings()
    if row and row.wa_gbp_per_message is not None:
        return float(row.wa_gbp_per_message), "db"
    raw = (os.getenv("USAGE_WA_GBP_PER_MESSAGE") or "").strip()
    if raw:
        try:
            return float(raw), "env"
        except Exception:
            return 0.0, "default"
    return 0.0, "default"


def _wa_rate_gbp_per_media_message() -> tuple[float, str]:
    row = _load_usage_settings()
    if row and row.wa_gbp_per_media_message is not None:
        return float(row.wa_gbp_per_media_message), "db"
    raw = (os.getenv("USAGE_WA_GBP_PER_MEDIA_MESSAGE") or "").strip()
    if raw:
        try:
            return float(raw), "env"
        except Exception:
            return 0.0, "default"
    return _wa_rate_gbp_per_message()


def _wa_rate_gbp_per_template_message() -> tuple[float, str]:
    row = _load_usage_settings()
    if row and row.wa_gbp_per_template_message is not None:
        return float(row.wa_gbp_per_template_message), "db"
    raw = (os.getenv("USAGE_WA_GBP_PER_TEMPLATE_MESSAGE") or "").strip()
    if raw:
        try:
            return float(raw), "env"
        except Exception:
            return 0.0, "default"
    return _wa_rate_gbp_per_message()


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, int(math.ceil(len(text) / 4)))


def estimate_llm_cost(tokens_in: int, tokens_out: int) -> tuple[float, float, float, str]:
    rate_in, src_in = _llm_rate_gbp_per_1m_input_tokens()
    rate_out, src_out = _llm_rate_gbp_per_1m_output_tokens()
    cost = (tokens_in / 1_000_000.0) * rate_in + (tokens_out / 1_000_000.0) * rate_out
    source = "env" if src_in == "env" or src_out == "env" else "default"
    return cost, rate_in, rate_out, source


def estimate_whatsapp_cost(unit_type: str, units: float = 1.0) -> tuple[float, float, str]:
    if unit_type == "message_media":
        rate, source = _wa_rate_gbp_per_media_message()
    elif unit_type == "message_template":
        rate, source = _wa_rate_gbp_per_template_message()
    else:
        rate, source = _wa_rate_gbp_per_message()
    return units * rate, rate, source


def ensure_usage_schema() -> None:
    global _USAGE_SCHEMA_READY
    if _USAGE_SCHEMA_READY:
        return
    try:
        UsageEvent.__table__.create(bind=engine, checkfirst=True)
        UsageRollupDaily.__table__.create(bind=engine, checkfirst=True)
        UsageSettings.__table__.create(bind=engine, checkfirst=True)
    except Exception:
        pass

    try:
        with engine.begin() as conn:
            if not _table_exists(conn, "usage_events"):
                _USAGE_SCHEMA_READY = True
                return
            is_pg = _is_postgres()
            alterations = [
                "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS cost_estimate double precision;",
                "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS currency varchar(8) DEFAULT 'GBP';",
                "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS request_id varchar(120);",
                "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS duration_ms integer;",
                "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS tag varchar(64);",
                (
                    "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS meta jsonb;"
                    if is_pg
                    else "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS meta text;"
                ),
            ]
            for stmt in alterations:
                try:
                    conn.execute(sa_text(stmt))
                except Exception:
                    pass
            if _table_exists(conn, "usage_settings"):
                try:
                    conn.execute(
                        sa_text(
                            "ALTER TABLE usage_settings ADD COLUMN IF NOT EXISTS meta jsonb;"
                            if is_pg
                            else "ALTER TABLE usage_settings ADD COLUMN IF NOT EXISTS meta text;"
                        )
                    )
                except Exception:
                    pass
    except Exception:
        pass

    _USAGE_SCHEMA_READY = True


def log_usage_event(
    *,
    user_id: int | None,
    provider: str,
    product: str,
    model: str | None,
    units: float,
    unit_type: str,
    cost_estimate: float | None = None,
    currency: str = "GBP",
    request_id: str | None = None,
    duration_ms: int | None = None,
    tag: str | None = None,
    meta: dict | None = None,
) -> None:
    try:
        ensure_usage_schema()
        with SessionLocal() as s:
            row = UsageEvent(
                user_id=user_id,
                provider=provider,
                product=product,
                model=model,
                units=units,
                unit_type=unit_type,
                cost_estimate=cost_estimate,
                currency=currency,
                request_id=request_id,
                duration_ms=duration_ms,
                tag=tag,
                meta=meta,
            )
            s.add(row)
            s.commit()
    except Exception as e:
        print(f"[usage] log failed: {e}")


def _estimate_tts_cost(chars: float) -> tuple[float, float, str]:
    rate, source = _tts_rate_gbp_per_1m_chars()
    cost = (chars / 1_000_000.0) * rate if chars else 0.0
    return cost, rate, source


def get_tts_usage_summary(
    *,
    start_utc: datetime,
    end_utc: datetime,
    tag: str | None = None,
    user_id: int | None = None,
) -> dict:
    ensure_usage_schema()
    with SessionLocal() as s:
        q = s.query(
            func.count(UsageEvent.id).label("events"),
            func.sum(
                case(
                    (UsageEvent.unit_type == "tts_chars", UsageEvent.units),
                    else_=0.0,
                )
            ).label("chars"),
            func.sum(
                case(
                    (UsageEvent.unit_type == "tts_chars", UsageEvent.cost_estimate),
                    else_=0.0,
                )
            ).label("cost_sum"),
        ).filter(
            UsageEvent.created_at >= start_utc,
            UsageEvent.created_at < end_utc,
            UsageEvent.product == "tts",
        )
        if tag:
            q = q.filter(UsageEvent.tag == tag)
        if user_id:
            q = q.filter(UsageEvent.user_id == user_id)
        row = q.one_or_none()

    events = int(row.events or 0) if row else 0
    chars = float(row.chars or 0.0) if row else 0.0
    cost_sum = float(row.cost_sum or 0.0) if row else 0.0
    chars_per_min = _tts_chars_per_min()
    minutes_est = chars / chars_per_min if chars_per_min else 0.0
    cost_est, rate, source = _estimate_tts_cost(chars)
    cost_final = cost_sum if cost_sum else cost_est
    return {
        "events": events,
        "chars": round(chars, 2),
        "minutes_est": round(minutes_est, 2),
        "cost_est_gbp": round(cost_final, 4),
        "rate_gbp_per_1m_chars": rate,
        "rate_source": source,
        "chars_per_min": chars_per_min,
        "tag": tag,
    }


def get_llm_usage_summary(
    *,
    start_utc: datetime,
    end_utc: datetime,
    tag: str | None = None,
    user_id: int | None = None,
) -> dict:
    ensure_usage_schema()
    with SessionLocal() as s:
        q = s.query(
            func.sum(case((UsageEvent.unit_type == "tokens_in", UsageEvent.units), else_=0.0)).label("tokens_in"),
            func.sum(case((UsageEvent.unit_type == "tokens_out", UsageEvent.units), else_=0.0)).label("tokens_out"),
            func.sum(UsageEvent.cost_estimate).label("cost_sum"),
        ).filter(
            UsageEvent.created_at >= start_utc,
            UsageEvent.created_at < end_utc,
            UsageEvent.product == "llm",
        )
        if tag:
            q = q.filter(UsageEvent.tag == tag)
        if user_id:
            q = q.filter(UsageEvent.user_id == user_id)
        row = q.one_or_none()

    tokens_in = int(row.tokens_in or 0) if row else 0
    tokens_out = int(row.tokens_out or 0) if row else 0
    cost_sum = float(row.cost_sum or 0.0) if row else 0.0
    cost_est, rate_in, rate_out, source = estimate_llm_cost(tokens_in, tokens_out)
    cost_final = cost_sum if cost_sum else cost_est
    return {
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_est_gbp": round(cost_final, 4),
        "rate_gbp_per_1m_input_tokens": rate_in,
        "rate_gbp_per_1m_output_tokens": rate_out,
        "rate_source": source,
        "tag": tag,
    }


def get_whatsapp_usage_summary(
    *,
    start_utc: datetime,
    end_utc: datetime,
    tag: str | None = None,
    user_id: int | None = None,
) -> dict:
    ensure_usage_schema()
    with SessionLocal() as s:
        q = s.query(
            func.sum(UsageEvent.units).label("messages"),
            func.sum(UsageEvent.cost_estimate).label("cost_sum"),
        ).filter(
            UsageEvent.created_at >= start_utc,
            UsageEvent.created_at < end_utc,
            UsageEvent.product == "whatsapp",
        )
        if tag:
            q = q.filter(UsageEvent.tag == tag)
        if user_id:
            q = q.filter(UsageEvent.user_id == user_id)
        row = q.one_or_none()

    messages = float(row.messages or 0.0) if row else 0.0
    cost_sum = float(row.cost_sum or 0.0) if row else 0.0
    cost_est, rate, source = estimate_whatsapp_cost("message_text", units=messages or 0.0)
    cost_final = cost_sum if cost_sum else cost_est
    return {
        "messages": int(messages),
        "cost_est_gbp": round(cost_final, 4),
        "rate_gbp_per_message": rate,
        "rate_source": source,
        "tag": tag,
    }


def get_usage_settings() -> dict:
    row = _load_usage_settings()
    if not row:
        return {
            "tts_gbp_per_1m_chars": None,
            "tts_chars_per_min": None,
            "llm_gbp_per_1m_input_tokens": None,
            "llm_gbp_per_1m_output_tokens": None,
            "wa_gbp_per_message": None,
            "wa_gbp_per_media_message": None,
            "wa_gbp_per_template_message": None,
            "meta": None,
        }
    return {
        "tts_gbp_per_1m_chars": row.tts_gbp_per_1m_chars,
        "tts_chars_per_min": row.tts_chars_per_min,
        "llm_gbp_per_1m_input_tokens": row.llm_gbp_per_1m_input_tokens,
        "llm_gbp_per_1m_output_tokens": row.llm_gbp_per_1m_output_tokens,
        "wa_gbp_per_message": row.wa_gbp_per_message,
        "wa_gbp_per_media_message": row.wa_gbp_per_media_message,
        "wa_gbp_per_template_message": row.wa_gbp_per_template_message,
        "meta": row.meta,
    }


def save_usage_settings(payload: dict) -> dict:
    ensure_usage_schema()
    with SessionLocal() as s:
        row = s.query(UsageSettings).order_by(UsageSettings.id.desc()).first()
        if not row:
            row = UsageSettings()

        def _num(key: str):
            val = payload.get(key)
            if val is None:
                return None
            try:
                if isinstance(val, str) and not val.strip():
                    return None
                return float(val)
            except Exception:
                return None

        row.tts_gbp_per_1m_chars = _num("tts_gbp_per_1m_chars")
        row.tts_chars_per_min = _num("tts_chars_per_min")
        row.llm_gbp_per_1m_input_tokens = _num("llm_gbp_per_1m_input_tokens")
        row.llm_gbp_per_1m_output_tokens = _num("llm_gbp_per_1m_output_tokens")
        row.wa_gbp_per_message = _num("wa_gbp_per_message")
        row.wa_gbp_per_media_message = _num("wa_gbp_per_media_message")
        row.wa_gbp_per_template_message = _num("wa_gbp_per_template_message")
        if payload.get("meta") is not None:
            row.meta = payload.get("meta")
        s.add(row)
        s.commit()
        s.refresh(row)
    return get_usage_settings()


def uk_week_bounds(now: datetime) -> tuple[datetime, datetime]:
    # Assumes `now` already in UTC (naive or aware), used for a simple 7-day window.
    start = now - timedelta(days=7)
    return start, now
