from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
import math
import re

from sqlalchemy import func, case, text as sa_text
from sqlalchemy.orm import Session

from .db import SessionLocal, engine, _is_postgres, _table_exists
from .models import (
    EducationLessonVariant,
    EducationProgramme,
    EducationProgrammeDay,
    UsageEvent,
    UsageRollupDaily,
    UsageSettings,
    LLMPromptLog,
)


_USAGE_SCHEMA_READY = False
PRIMARY_LLM_RATE_MODELS = ("gpt-5-mini", "gpt-5.1")


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


def _primary_llm_model_rates(value) -> dict[str, dict[str, float]]:
    normalized = _normalize_llm_model_rates(value)
    if not normalized:
        return {}
    selected: dict[str, dict[str, float]] = {}
    for allowed in PRIMARY_LLM_RATE_MODELS:
        allowed_norm = _normalize_model_name(allowed)
        for model_name, rates in normalized.items():
            if _normalize_model_name(model_name) != allowed_norm:
                continue
            selected[allowed] = dict(rates)
            break
    return selected


def _extract_llm_model_rates(meta) -> dict[str, dict[str, float]]:
    meta_obj = _meta_to_dict(meta)
    return _primary_llm_model_rates(meta_obj.get("llm_model_rates"))


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
    model_rates = _primary_llm_model_rates((resolved_settings or {}).get("llm_model_rates"))
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


def _avatar_rate_gbp_per_minute() -> tuple[float, str]:
    row = _load_usage_settings()
    if row:
        meta = _meta_to_dict(getattr(row, "meta", None))
        rate = _to_float(meta.get("avatar_gbp_per_minute"))
        if rate is not None:
            return float(rate), "db_meta"
    raw = (
        os.getenv("USAGE_AVATAR_GBP_PER_MINUTE")
        or os.getenv("AZURE_AVATAR_GBP_PER_MINUTE")
        or ""
    ).strip()
    if raw:
        try:
            return float(raw), "env"
        except Exception:
            return 0.0, "default"
    return 0.0, "default"


def _avatar_chars_per_min() -> float:
    row = _load_usage_settings()
    if row:
        meta = _meta_to_dict(getattr(row, "meta", None))
        chars_per_min = _to_float(meta.get("avatar_chars_per_min"))
        if chars_per_min is not None and chars_per_min > 0:
            return float(chars_per_min)
    raw = (
        os.getenv("USAGE_AVATAR_CHARS_PER_MIN")
        or os.getenv("AZURE_AVATAR_CHARS_PER_MIN")
        or ""
    ).strip()
    if raw:
        try:
            parsed = float(raw)
            if parsed > 0:
                return parsed
        except Exception:
            pass
    return _tts_chars_per_min()


def estimate_avatar_cost_from_text(text: str | None) -> tuple[float, float, float, float, str]:
    chars = float(len(str(text or "")))
    chars_per_min = _avatar_chars_per_min()
    minutes_est = chars / chars_per_min if chars_per_min else 0.0
    seconds_est = minutes_est * 60.0
    rate, source = _avatar_rate_gbp_per_minute()
    cost_est = minutes_est * rate if minutes_est and rate else 0.0
    return cost_est, seconds_est, rate, chars_per_min, source


def estimate_avatar_cost_from_seconds(seconds: float | int | None) -> tuple[float, float, str]:
    seconds_val = max(0.0, float(seconds or 0.0))
    rate, source = _avatar_rate_gbp_per_minute()
    cost_est = (seconds_val / 60.0) * rate if seconds_val and rate else 0.0
    return cost_est, rate, source


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


def _parse_azure_datetime(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(microsecond=0)
    return parsed.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def _azure_batch_avatar_usage_payload(
    payload: dict,
    *,
    fallback_tag: str | None = None,
    extra_meta: dict | None = None,
) -> dict | None:
    if not isinstance(payload, dict):
        return None
    job_id = str(payload.get("id") or "").strip()
    if not job_id:
        return None
    props = payload.get("properties") if isinstance(payload.get("properties"), dict) else {}
    billing = props.get("billingDetails") if isinstance(props.get("billingDetails"), dict) else {}
    seconds = _to_float(
        billing.get("talkingAvatarDurationSeconds")
        or billing.get("durationSeconds")
        or props.get("durationSeconds")
    )
    if seconds is None or seconds <= 0:
        return None
    cost_estimate, rate_per_minute, rate_source = estimate_avatar_cost_from_seconds(seconds)
    created_at = (
        _parse_azure_datetime(str(payload.get("createdDateTime") or ""))
        or _parse_azure_datetime(str(payload.get("lastActionDateTime") or ""))
    )
    display_name = str(payload.get("displayName") or payload.get("description") or "").strip() or None
    meta = {
        "mode": "azure_batch",
        "azure_status": str(payload.get("status") or "").strip() or None,
        "display_name": display_name,
        "text_chars": _to_float(billing.get("neuralCharacters")),
        "rate_gbp_per_minute": rate_per_minute,
        "rate_source": rate_source,
        "billing_details": billing or None,
    }
    if extra_meta:
        meta.update(extra_meta)
    return {
        "created_at": created_at,
        "request_id": job_id,
        "model": "batch_avatar",
        "units": float(seconds),
        "unit_type": "avatar_seconds",
        "cost_estimate": cost_estimate,
        "duration_ms": int(float(seconds) * 1000),
        "tag": fallback_tag or "azure_batch",
        "meta": meta,
    }


def _avatar_lesson_variant_id_from_usage(row: UsageEvent, meta: dict) -> int | None:
    raw = meta.get("lesson_variant_id")
    if raw is not None:
        try:
            value = int(str(raw).strip())
            if value > 0:
                return value
        except Exception:
            pass
    request_id = str(getattr(row, "request_id", "") or "").strip()
    match = re.match(r"^edu-avatar-(\d+)-", request_id)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def _education_avatar_context_for_usage_rows(session: Session, rows: list[UsageEvent]) -> dict[int, dict[str, object]]:
    variant_ids = {
        int(variant_id)
        for row in rows
        for variant_id in [_avatar_lesson_variant_id_from_usage(row, _meta_to_dict(getattr(row, "meta", None)))]
        if variant_id
    }
    if not variant_ids:
        return {}
    result: dict[int, dict[str, object]] = {}
    joined_rows = (
        session.query(EducationLessonVariant, EducationProgrammeDay, EducationProgramme)
        .join(EducationProgrammeDay, EducationLessonVariant.programme_day_id == EducationProgrammeDay.id)
        .join(EducationProgramme, EducationProgrammeDay.programme_id == EducationProgramme.id)
        .filter(EducationLessonVariant.id.in_(sorted(variant_ids)))
        .all()
    )
    for variant, day, programme in joined_rows:
        variant_id = int(getattr(variant, "id", 0) or 0)
        result[variant_id] = {
            "lesson_variant_id": variant_id,
            "programme_id": int(getattr(programme, "id", 0) or 0) or None,
            "programme_code": str(getattr(programme, "code", "") or "").strip() or None,
            "programme_name": str(getattr(programme, "name", "") or "").strip() or None,
            "programme_day_id": int(getattr(day, "id", 0) or 0) or None,
            "day_index": int(getattr(day, "day_index", 0) or 0) or None,
            "level": str(getattr(variant, "level", "") or "").strip() or None,
            "lesson_title": (
                str(getattr(variant, "title", "") or "").strip()
                or str(getattr(day, "default_title", "") or "").strip()
                or None
            ),
        }
    return result


def log_azure_batch_avatar_usage_once(
    payload: dict,
    *,
    session: Session,
    user_id: int | None = None,
    tag: str | None = None,
    model: str | None = None,
    extra_meta: dict | None = None,
    commit: bool = False,
) -> bool:
    try:
        usage = _azure_batch_avatar_usage_payload(payload, fallback_tag=tag, extra_meta=extra_meta)
        if not usage:
            return False
        existing = (
            session.query(UsageEvent.id)
            .filter(
                UsageEvent.product == "avatar",
                UsageEvent.request_id == usage["request_id"],
            )
            .first()
        )
        if existing:
            return False
        row = UsageEvent(
            created_at=usage.get("created_at") or datetime.utcnow().replace(microsecond=0),
            user_id=user_id,
            provider="azure",
            product="avatar",
            model=model or usage.get("model"),
            units=float(usage.get("units") or 0.0),
            unit_type=str(usage.get("unit_type") or "avatar_seconds"),
            cost_estimate=float(usage.get("cost_estimate") or 0.0),
            currency="GBP",
            request_id=str(usage.get("request_id") or "").strip(),
            duration_ms=usage.get("duration_ms"),
            tag=str(usage.get("tag") or tag or "azure_batch"),
            meta=usage.get("meta") if isinstance(usage.get("meta"), dict) else None,
        )
        session.add(row)
        if commit:
            session.commit()
        return True
    except Exception as e:
        print(f"[usage] azure batch avatar log failed: {e}")
        return False


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


def get_avatar_usage_summary(
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
                    (UsageEvent.unit_type == "avatar_seconds", UsageEvent.units),
                    else_=0.0,
                )
            ).label("seconds_sum"),
            func.sum(
                case(
                    (UsageEvent.unit_type == "avatar_seconds", UsageEvent.cost_estimate),
                    else_=0.0,
                )
            ).label("cost_sum"),
        ).filter(
            UsageEvent.created_at >= start_utc,
            UsageEvent.created_at < end_utc,
            UsageEvent.product == "avatar",
        )
        if tag:
            q = q.filter(UsageEvent.tag == tag)
        if user_id:
            q = q.filter(UsageEvent.user_id == user_id)
        row = q.one_or_none()

    events = int(row.events or 0) if row else 0
    seconds_sum = float(row.seconds_sum or 0.0) if row else 0.0
    minutes_est = seconds_sum / 60.0 if seconds_sum else 0.0
    cost_sum = float(row.cost_sum or 0.0) if row else 0.0
    rate, source = _avatar_rate_gbp_per_minute()
    chars_per_min = _avatar_chars_per_min()
    cost_est = minutes_est * rate if minutes_est and rate else 0.0
    cost_final = cost_sum if cost_sum else cost_est
    return {
        "events": events,
        "seconds_est": round(seconds_sum, 2),
        "minutes_est": round(minutes_est, 2),
        "cost_est_gbp": round(cost_final, 4),
        "rate_gbp_per_minute": rate,
        "rate_source": source,
        "chars_per_min": chars_per_min,
        "tag": tag,
    }


def get_avatar_usage_rows(
    *,
    start_utc: datetime,
    end_utc: datetime,
    tag: str | None = None,
    user_id: int | None = None,
    limit: int = 50,
) -> tuple[list[dict], dict]:
    ensure_usage_schema()
    limit_val = max(1, min(int(limit or 50), 200))
    default_rate, default_source = _avatar_rate_gbp_per_minute()
    with SessionLocal() as s:
        base_q = (
            s.query(UsageEvent)
            .filter(
                UsageEvent.created_at >= start_utc,
                UsageEvent.created_at < end_utc,
                UsageEvent.product == "avatar",
                UsageEvent.unit_type == "avatar_seconds",
            )
        )
        if tag:
            base_q = base_q.filter(UsageEvent.tag == tag)
        if user_id:
            base_q = base_q.filter(UsageEvent.user_id == user_id)
        all_rows = base_q.order_by(UsageEvent.created_at.desc(), UsageEvent.id.desc()).all()
        rows = all_rows[:limit_val]
        education_context = _education_avatar_context_for_usage_rows(s, rows)

    out: list[dict] = []
    window_total_cost = 0.0
    window_total_seconds = 0.0
    window_daily_totals: dict[str, dict[str, float | int | str]] = {}
    for row in all_rows:
        created_at_value = getattr(row, "created_at", None)
        day_key = created_at_value.date().isoformat() if created_at_value else "unknown"
        seconds_est = float(getattr(row, "units", 0.0) or 0.0)
        minutes_est = seconds_est / 60.0 if seconds_est else 0.0
        cost_est = float(getattr(row, "cost_estimate", 0.0) or 0.0)
        day_total = window_daily_totals.setdefault(
            day_key,
            {"date": day_key, "events": 0, "seconds_est": 0.0, "minutes_est": 0.0, "cost_est_gbp": 0.0},
        )
        day_total["events"] = int(day_total.get("events") or 0) + 1
        day_total["seconds_est"] = float(day_total.get("seconds_est") or 0.0) + seconds_est
        day_total["minutes_est"] = float(day_total.get("minutes_est") or 0.0) + minutes_est
        day_total["cost_est_gbp"] = float(day_total.get("cost_est_gbp") or 0.0) + cost_est
        window_total_cost += cost_est
        window_total_seconds += seconds_est

    def _avatar_usage_row_payload(row: UsageEvent) -> dict:
        meta = _meta_to_dict(getattr(row, "meta", None))
        variant_id = _avatar_lesson_variant_id_from_usage(row, meta)
        education = education_context.get(int(variant_id or 0), {}) if variant_id else {}
        seconds_est = float(getattr(row, "units", 0.0) or 0.0)
        minutes_est = seconds_est / 60.0 if seconds_est else 0.0
        cost_est = float(getattr(row, "cost_estimate", 0.0) or 0.0)
        rate = _to_float(meta.get("rate_gbp_per_minute"))
        if rate is None:
            rate = default_rate
        rate_source = str(meta.get("rate_source") or default_source or "").strip() or None
        working = None
        if rate is not None:
            working = f"({minutes_est:.2f} min * £{float(rate):.4f}/min) = £{(minutes_est * float(rate)):.4f}"
        created_at_value = getattr(row, "created_at", None)
        created_at_iso = created_at_value.isoformat() if created_at_value else None
        day_key = created_at_value.date().isoformat() if created_at_value else "unknown"
        programme_name = education.get("programme_name") or meta.get("programme_name")
        programme_code = education.get("programme_code") or meta.get("programme_code")
        programme_id = education.get("programme_id") or meta.get("programme_id")
        programme_label = (
            str(programme_name or "").strip()
            or str(programme_code or "").strip()
            or (f"Programme {programme_id}" if programme_id else None)
        )
        lesson_title = education.get("lesson_title") or meta.get("lesson_title") or meta.get("title")
        return {
            "event_id": int(getattr(row, "id", 0) or 0),
            "created_at": created_at_iso,
            "date": day_key,
            "user_id": getattr(row, "user_id", None),
            "model": getattr(row, "model", None),
            "request_id": getattr(row, "request_id", None),
            "mode": meta.get("mode"),
            "title": meta.get("title") or meta.get("display_name"),
            "programme_id": programme_id,
            "programme_code": programme_code,
            "programme_name": programme_name,
            "programme_label": programme_label,
            "programme_day_id": education.get("programme_day_id") or meta.get("programme_day_id"),
            "day_index": education.get("day_index") or meta.get("day_index"),
            "lesson_variant_id": education.get("lesson_variant_id") or meta.get("lesson_variant_id") or variant_id,
            "lesson_level": education.get("level") or meta.get("level"),
            "lesson_title": lesson_title,
            "transaction_label": " · ".join(
                part
                for part in (
                    str(programme_label or "").strip(),
                    f"Lesson {education.get('day_index') or meta.get('day_index')}" if (education.get("day_index") or meta.get("day_index")) else "",
                    str(lesson_title or "").strip(),
                )
                if part
            )
            or meta.get("title")
            or meta.get("display_name"),
            "azure_status": meta.get("azure_status"),
            "run_id": meta.get("run_id"),
            "character": meta.get("character"),
            "style": meta.get("style"),
            "voice": meta.get("voice"),
            "text_chars": meta.get("text_chars"),
            "seconds_est": round(seconds_est, 2),
            "minutes_est": round(minutes_est, 2),
            "duration_ms": getattr(row, "duration_ms", None),
            "rate_gbp_per_minute": float(rate) if rate is not None else None,
            "rate_source": rate_source,
            "cost_est_gbp": round(cost_est, 6),
            "working": working,
        }

    out = [_avatar_usage_row_payload(row) for row in rows]

    daily_totals_out = [
        {
            "date": str(item.get("date") or ""),
            "events": int(item.get("events") or 0),
            "seconds_est": round(float(item.get("seconds_est") or 0.0), 2),
            "minutes_est": round(float(item.get("minutes_est") or 0.0), 2),
            "cost_est_gbp": round(float(item.get("cost_est_gbp") or 0.0), 6),
        }
        for _date, item in sorted(window_daily_totals.items(), reverse=True)
    ]
    transactions_by_date = []
    for daily in daily_totals_out:
        date_key = str(daily.get("date") or "")
        date_rows = [row for row in out if row.get("date") == date_key]
        transactions_by_date.append({**daily, "rows": date_rows})
    return out, {
        "events": len(all_rows),
        "returned_events": len(out),
        "seconds_est": round(window_total_seconds, 2),
        "minutes_est": round(window_total_seconds / 60.0, 2) if window_total_seconds else 0.0,
        "cost_est_gbp": round(window_total_cost, 6),
        "daily_totals": daily_totals_out,
        "transactions_by_date": transactions_by_date,
    }


def get_usage_settings() -> dict:
    row = _load_usage_settings()
    meta = _meta_to_dict(getattr(row, "meta", None)) if row else {}
    if not row:
        return {
            "tts_gbp_per_1m_chars": None,
            "tts_chars_per_min": None,
            "avatar_gbp_per_minute": None,
            "avatar_chars_per_min": None,
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
        "avatar_gbp_per_minute": _to_float(meta.get("avatar_gbp_per_minute")),
        "avatar_chars_per_min": _to_float(meta.get("avatar_chars_per_min")),
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
            for preserved_key in ("avatar_gbp_per_minute", "avatar_chars_per_min"):
                if preserved_key not in next_meta and preserved_key in existing_meta:
                    next_meta[preserved_key] = existing_meta.get(preserved_key)
        else:
            next_meta = dict(existing_meta)

        if "llm_model_rates" in payload:
            model_rates = _primary_llm_model_rates(payload.get("llm_model_rates"))
            if model_rates:
                next_meta["llm_model_rates"] = model_rates
            else:
                next_meta.pop("llm_model_rates", None)

        for meta_key in ("avatar_gbp_per_minute", "avatar_chars_per_min"):
            if meta_key not in payload:
                continue
            meta_value = _to_float(payload.get(meta_key))
            if meta_value is None:
                next_meta.pop(meta_key, None)
            else:
                next_meta[meta_key] = float(meta_value)

        if incoming_meta is not None or "llm_model_rates" in payload or "avatar_gbp_per_minute" in payload or "avatar_chars_per_min" in payload:
            row.meta = next_meta or None
        s.add(row)
        s.commit()
        s.refresh(row)
    return get_usage_settings()


def uk_week_bounds(now: datetime) -> tuple[datetime, datetime]:
    # Assumes `now` already in UTC (naive or aware), used for a simple 7-day window.
    start = now - timedelta(days=7)
    return start, now
