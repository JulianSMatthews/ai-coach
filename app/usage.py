from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
import math

from sqlalchemy import func, case, text as sa_text
from sqlalchemy.orm import Session

from .db import SessionLocal, engine, _is_postgres, _table_exists
from .models import UsageEvent, UsageRollupDaily, UsageSettings, LLMPromptLog


_USAGE_SCHEMA_READY = False


def _load_usage_settings() -> UsageSettings | None:
    try:
        ensure_usage_schema()
        with SessionLocal() as s:
            return s.query(UsageSettings).order_by(UsageSettings.id.desc()).first()
    except Exception:
        return None


def _meta_to_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str) and not value.strip():
            return None
        return float(value)
    except Exception:
        return None


def _normalize_model_name(value: str | None) -> str:
    return (value or "").strip().lower()


def _normalize_llm_model_rates(value) -> dict[str, dict[str, float]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, float]] = {}
    for raw_model, raw_rates in value.items():
        model_key = str(raw_model or "").strip()
        if not model_key:
            continue
        if not isinstance(raw_rates, dict):
            continue
        rate_in = _to_float(
            raw_rates.get("input")
            if raw_rates.get("input") is not None
            else raw_rates.get("rate_in")
            if raw_rates.get("rate_in") is not None
            else raw_rates.get("in")
        )
        rate_out = _to_float(
            raw_rates.get("output")
            if raw_rates.get("output") is not None
            else raw_rates.get("rate_out")
            if raw_rates.get("rate_out") is not None
            else raw_rates.get("out")
        )
        clean: dict[str, float] = {}
        if rate_in is not None:
            clean["input"] = rate_in
        if rate_out is not None:
            clean["output"] = rate_out
        if not clean:
            continue
        normalized[model_key] = clean
    return normalized


def _extract_llm_model_rates(meta) -> dict[str, dict[str, float]]:
    meta_obj = _meta_to_dict(meta)
    return _normalize_llm_model_rates(meta_obj.get("llm_model_rates"))


def _default_llm_rates_from_settings(settings: dict | None) -> tuple[float, str, float, str]:
    rate_in = _to_float((settings or {}).get("llm_gbp_per_1m_input_tokens"))
    if rate_in is not None:
        src_in = "db"
    else:
        env_in = _to_float((os.getenv("USAGE_LLM_GBP_PER_1M_INPUT_TOKENS") or "").strip())
        if env_in is not None:
            rate_in = env_in
            src_in = "env"
        else:
            rate_in = 0.0
            src_in = "default"

    rate_out = _to_float((settings or {}).get("llm_gbp_per_1m_output_tokens"))
    if rate_out is not None:
        src_out = "db"
    else:
        env_out = _to_float((os.getenv("USAGE_LLM_GBP_PER_1M_OUTPUT_TOKENS") or "").strip())
        if env_out is not None:
            rate_out = env_out
            src_out = "env"
        else:
            rate_out = 0.0
            src_out = "default"
    return float(rate_in), src_in, float(rate_out), src_out


def resolve_llm_rates(
    *,
    model: str | None = None,
    settings: dict | None = None,
) -> tuple[float, float, str, str | None]:
    resolved_settings = settings if isinstance(settings, dict) else get_usage_settings()
    default_in, src_in, default_out, src_out = _default_llm_rates_from_settings(resolved_settings)
    model_rates = _normalize_llm_model_rates((resolved_settings or {}).get("llm_model_rates"))
    if not model_rates:
        if "db" in (src_in, src_out):
            source = "db"
        elif "env" in (src_in, src_out):
            source = "env"
        else:
            source = "default"
        return default_in, default_out, source, None

    key_raw = (model or "").strip()
    key_norm = _normalize_model_name(model)
    matched_key = None
    if key_raw and key_raw in model_rates:
        matched_key = key_raw
    elif key_norm:
        for candidate in model_rates.keys():
            if _normalize_model_name(candidate) == key_norm:
                matched_key = candidate
                break
    if matched_key is None:
        if "db" in (src_in, src_out):
            source = "db"
        elif "env" in (src_in, src_out):
            source = "env"
        else:
            source = "default"
        return default_in, default_out, source, None

    matched = model_rates.get(matched_key) or {}
    model_in = _to_float(matched.get("input"))
    model_out = _to_float(matched.get("output"))
    rate_in = default_in if model_in is None else float(model_in)
    rate_out = default_out if model_out is None else float(model_out)
    if model_in is not None and model_out is not None:
        source = "model_db"
    else:
        fallback_src = src_in if model_in is None else src_out
        source = f"model_db+{fallback_src}"
    return rate_in, rate_out, source, matched_key


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
    rate_in, _, source, _ = resolve_llm_rates()
    return rate_in, source


def _llm_rate_gbp_per_1m_output_tokens() -> tuple[float, str]:
    _, rate_out, source, _ = resolve_llm_rates()
    return rate_out, source


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


def estimate_llm_cost(
    tokens_in: int,
    tokens_out: int,
    model: str | None = None,
    settings: dict | None = None,
) -> tuple[float, float, float, str]:
    rate_in, rate_out, source, _ = resolve_llm_rates(model=model, settings=settings)
    cost = (tokens_in / 1_000_000.0) * rate_in + (tokens_out / 1_000_000.0) * rate_out
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


def _log_usage_event_with_session(
    s: Session,
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
    resolved_user_id = user_id
    resolved_model = model
    resolved_request_id = request_id
    if product == "llm" and (resolved_user_id is None or resolved_model is None or resolved_request_id is None):
        raw = resolved_request_id
        meta_obj = meta
        if raw is None and isinstance(meta_obj, dict):
            raw = meta_obj.get("prompt_log_id")
        if raw is None and isinstance(meta_obj, str):
            try:
                parsed = json.loads(meta_obj)
                if isinstance(parsed, dict):
                    raw = parsed.get("prompt_log_id")
                    meta_obj = parsed
            except Exception:
                pass
        if raw is not None:
            try:
                prompt_id = int(str(raw).strip())
            except Exception:
                prompt_id = None
            if prompt_id:
                prompt = s.get(LLMPromptLog, prompt_id)
                if prompt:
                    if resolved_user_id is None and prompt.user_id is not None:
                        resolved_user_id = prompt.user_id
                    if resolved_model is None and prompt.model:
                        resolved_model = prompt.model
                    if resolved_request_id is None:
                        resolved_request_id = str(prompt_id)
    row = UsageEvent(
        user_id=resolved_user_id,
        provider=provider,
        product=product,
        model=resolved_model,
        units=units,
        unit_type=unit_type,
        cost_estimate=cost_estimate,
        currency=currency,
        request_id=resolved_request_id,
        duration_ms=duration_ms,
        tag=tag,
        meta=meta,
    )
    s.add(row)


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
    session: Session | None = None,
    commit: bool = True,
    ensure: bool = True,
) -> None:
    try:
        if ensure:
            ensure_usage_schema()
        if session is None:
            with SessionLocal() as s:
                _log_usage_event_with_session(
                    s,
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
                s.commit()
        else:
            _log_usage_event_with_session(
                session,
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
            if commit:
                session.commit()
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
        filters = [
            UsageEvent.created_at >= start_utc,
            UsageEvent.created_at < end_utc,
            UsageEvent.product == "llm",
        ]
        if tag:
            filters.append(UsageEvent.tag == tag)
        if user_id:
            filters.append(UsageEvent.user_id == user_id)

        q = s.query(
            func.sum(case((UsageEvent.unit_type == "tokens_in", UsageEvent.units), else_=0.0)).label("tokens_in"),
            func.sum(case((UsageEvent.unit_type == "tokens_out", UsageEvent.units), else_=0.0)).label("tokens_out"),
            func.sum(UsageEvent.cost_estimate).label("cost_sum"),
        ).filter(*filters)
        row = q.one_or_none()

        grouped = (
            s.query(
                UsageEvent.model.label("model"),
                func.sum(case((UsageEvent.unit_type == "tokens_in", UsageEvent.units), else_=0.0)).label("tokens_in"),
                func.sum(case((UsageEvent.unit_type == "tokens_out", UsageEvent.units), else_=0.0)).label("tokens_out"),
            )
            .filter(*filters)
        )
        grouped_rows = grouped.group_by(UsageEvent.model).all()

    tokens_in = int(row.tokens_in or 0) if row else 0
    tokens_out = int(row.tokens_out or 0) if row else 0
    cost_sum = float(row.cost_sum or 0.0) if row else 0.0
    rate_settings = get_usage_settings()
    non_empty_models = []
    fallback_cost = 0.0
    for group in grouped_rows:
        model_name = (group.model or "").strip() or None
        group_in = int(group.tokens_in or 0)
        group_out = int(group.tokens_out or 0)
        if group_in or group_out:
            non_empty_models.append(model_name or "")
        group_cost, _, _, _ = estimate_llm_cost(group_in, group_out, model=model_name, settings=rate_settings)
        fallback_cost += group_cost
    if len(set(non_empty_models)) == 1 and non_empty_models:
        _, rate_in, rate_out, source = estimate_llm_cost(
            0,
            0,
            model=non_empty_models[0] or None,
            settings=rate_settings,
        )
    elif len(set(non_empty_models)) > 1:
        rate_in, rate_out, source = None, None, "mixed_model"
    else:
        _, rate_in, rate_out, source = estimate_llm_cost(0, 0, settings=rate_settings)
    cost_est = fallback_cost
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
            "llm_model_rates": None,
            "wa_gbp_per_message": None,
            "wa_gbp_per_media_message": None,
            "wa_gbp_per_template_message": None,
            "meta": None,
        }
    model_rates = _extract_llm_model_rates(row.meta)
    return {
        "tts_gbp_per_1m_chars": row.tts_gbp_per_1m_chars,
        "tts_chars_per_min": row.tts_chars_per_min,
        "llm_gbp_per_1m_input_tokens": row.llm_gbp_per_1m_input_tokens,
        "llm_gbp_per_1m_output_tokens": row.llm_gbp_per_1m_output_tokens,
        "llm_model_rates": model_rates or None,
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
            return _to_float(payload.get(key))

        row.tts_gbp_per_1m_chars = _num("tts_gbp_per_1m_chars")
        row.tts_chars_per_min = _num("tts_chars_per_min")
        row.llm_gbp_per_1m_input_tokens = _num("llm_gbp_per_1m_input_tokens")
        row.llm_gbp_per_1m_output_tokens = _num("llm_gbp_per_1m_output_tokens")
        row.wa_gbp_per_message = _num("wa_gbp_per_message")
        row.wa_gbp_per_media_message = _num("wa_gbp_per_media_message")
        row.wa_gbp_per_template_message = _num("wa_gbp_per_template_message")

        existing_meta = _meta_to_dict(getattr(row, "meta", None))
        incoming_meta = payload.get("meta")
        if incoming_meta is not None:
            next_meta = _meta_to_dict(incoming_meta)
            if (
                "llm_model_rates" not in next_meta
                and existing_meta.get("llm_model_rates") is not None
            ):
                next_meta["llm_model_rates"] = existing_meta.get("llm_model_rates")
        else:
            next_meta = dict(existing_meta)

        if "llm_model_rates" in payload:
            model_rates = _normalize_llm_model_rates(payload.get("llm_model_rates"))
            if model_rates:
                next_meta["llm_model_rates"] = model_rates
            else:
                next_meta.pop("llm_model_rates", None)

        if incoming_meta is not None or "llm_model_rates" in payload:
            row.meta = next_meta or None
        s.add(row)
        s.commit()
        s.refresh(row)
    return get_usage_settings()


def uk_week_bounds(now: datetime) -> tuple[datetime, datetime]:
    # Assumes `now` already in UTC (naive or aware), used for a simple 7-day window.
    start = now - timedelta(days=7)
    return start, now
