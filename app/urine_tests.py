from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from .db import _is_postgres, engine


SIEMENS_MULTISTIX_PROVIDER = "siemens_multistix"
URINE_TEST_MAX_IMAGE_DATA_URL_BYTES = 12 * 1024 * 1024
URINE_TEST_DEFAULT_MIN_ANALYSIS_CONFIDENCE = 0.45

URINE_MARKER_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "concentration",
        "label": "Hydration",
        "source_analytes": ["specific_gravity"],
        "status_options": ["well", "ok", "low"],
    },
    {
        "key": "uti",
        "label": "UTI Signs",
        "source_analytes": ["leukocytes", "nitrite"],
        "status_options": ["clear", "watch", "flagged"],
    },
    {
        "key": "protein",
        "label": "Protein",
        "source_analytes": ["protein"],
        "status_options": ["clear", "trace", "flagged"],
    },
    {
        "key": "blood",
        "label": "Blood",
        "source_analytes": ["blood"],
        "status_options": ["clear", "trace", "flagged"],
    },
    {
        "key": "glucose",
        "label": "Glucose",
        "source_analytes": ["glucose"],
        "status_options": ["clear", "raised"],
    },
    {
        "key": "ketones",
        "label": "Ketones",
        "source_analytes": ["ketones"],
        "status_options": ["clear", "trace", "raised"],
    },
)

URINE_ANALYTE_REFERENCE: dict[str, dict[str, Any]] = {
    "specific_gravity": {
        "marker_key": "concentration",
        "healthsense_status_map": {
            "1.000-1.005": "well",
            "1.010-1.025": "ok",
            "1.030+": "low",
        },
        "visual_reference": "low values trend blue/blue-green; mid values trend green/yellow-green; high values trend yellow/orange.",
    },
    "leukocytes": {
        "marker_key": "uti",
        "healthsense_status_map": {
            "negative": "clear",
            "trace/small": "watch",
            "moderate/large": "flagged",
        },
        "visual_reference": "negative is beige/off-white; positive shifts toward lavender/purple.",
    },
    "nitrite": {
        "marker_key": "uti",
        "healthsense_status_map": {
            "negative": "clear",
            "positive": "flagged",
        },
        "visual_reference": "negative is white/tan; positive shifts pink.",
    },
    "protein": {
        "marker_key": "protein",
        "healthsense_status_map": {
            "negative": "clear",
            "trace": "trace",
            "1+ or higher": "flagged",
        },
        "visual_reference": "negative is yellow; positive shifts green to blue-green.",
    },
    "blood": {
        "marker_key": "blood",
        "healthsense_status_map": {
            "negative": "clear",
            "trace/non-hemolyzed": "trace",
            "small or higher": "flagged",
        },
        "visual_reference": "negative is yellow/orange; positive appears green spots or green/blue-green.",
    },
    "glucose": {
        "marker_key": "glucose",
        "healthsense_status_map": {
            "negative": "clear",
            "trace or higher": "raised",
        },
        "visual_reference": "negative trends blue/green; positive shifts green/brown.",
    },
    "ketones": {
        "marker_key": "ketones",
        "healthsense_status_map": {
            "negative": "clear",
            "trace/small": "trace",
            "moderate/large": "raised",
        },
        "visual_reference": "negative is beige/tan; positive shifts pink, purple, or maroon.",
    },
}

_URINE_TEST_SCHEMA_READY = False


_STATUS_OPTIONS_BY_MARKER = {
    str(marker["key"]): set(marker.get("status_options") or [])
    for marker in URINE_MARKER_DEFINITIONS
}

_STATUS_SYNONYMS = {
    "normal": "clear",
    "negative": "clear",
    "neg": "clear",
    "none": "clear",
    "ok": "clear",
    "positive": "flagged",
    "pos": "flagged",
    "high": "raised",
    "elevated": "raised",
    "moderate": "flagged",
    "large": "flagged",
    "small": "trace",
    "low": "trace",
    "uncertain": "review",
    "unknown": "review",
}


def ensure_urine_test_schema() -> None:
    global _URINE_TEST_SCHEMA_READY
    if _URINE_TEST_SCHEMA_READY:
        return
    with engine.begin() as conn:
        if _is_postgres():
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS urine_tests (
                        id BIGSERIAL PRIMARY KEY,
                        user_id integer NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        provider varchar(64) NOT NULL DEFAULT 'siemens_multistix',
                        sample_date date NOT NULL,
                        captured_at timestamp NULL,
                        status varchar(32) NOT NULL DEFAULT 'queued',
                        result_payload jsonb NULL,
                        image_metadata jsonb NULL,
                        created_at timestamp NOT NULL DEFAULT now(),
                        updated_at timestamp NOT NULL DEFAULT now()
                    );
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_urine_tests_user_sample_date
                    ON urine_tests(user_id, sample_date DESC);
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS ix_urine_tests_user_status
                    ON urine_tests(user_id, status);
                    """
                )
            )
        else:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS urine_tests (
                        id integer PRIMARY KEY AUTOINCREMENT,
                        user_id integer NOT NULL,
                        provider varchar(64) NOT NULL DEFAULT 'siemens_multistix',
                        sample_date date NOT NULL,
                        captured_at timestamp NULL,
                        status varchar(32) NOT NULL DEFAULT 'queued',
                        result_payload text NULL,
                        image_metadata text NULL,
                        created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    """
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_urine_tests_user_sample_date "
                    "ON urine_tests(user_id, sample_date DESC);"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_urine_tests_user_status "
                    "ON urine_tests(user_id, status);"
                )
            )
    _URINE_TEST_SCHEMA_READY = True


def _parse_json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)) or value is None:
        return value
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            return json.loads(token)
        except Exception:
            return None
    return value


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    token = str(value or "").strip()
    if token:
        try:
            parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
            return parsed.replace(tzinfo=None)
        except Exception:
            pass
    return datetime.utcnow()


def _analysis_enabled() -> bool:
    raw = str(os.getenv("URINE_TEST_ANALYSIS_ENABLED") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _analysis_model_name() -> str:
    return (
        str(os.getenv("URINE_TEST_VISION_MODEL") or "").strip()
        or str(os.getenv("VISION_MODEL") or "").strip()
        or str(os.getenv("LLM_MODEL") or "").strip()
        or "gpt-5.1"
    )


def _analysis_min_confidence() -> float:
    raw = str(os.getenv("URINE_TEST_MIN_ANALYSIS_CONFIDENCE") or "").strip()
    if raw:
        try:
            value = float(raw)
            if value == value:
                return max(0.0, min(1.0, value))
        except Exception:
            pass
    return URINE_TEST_DEFAULT_MIN_ANALYSIS_CONFIDENCE


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text_value = str(raw or "").strip()
    if not text_value:
        return None
    try:
        parsed = json.loads(text_value)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text_value, flags=re.S | re.I)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass
    start = text_value.find("{")
    end = text_value.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(text_value[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        resolved = float(value)
        if resolved != resolved:
            return default
        return max(0.0, min(1.0, resolved))
    except Exception:
        return default


def _normalize_status(marker_key: str, raw_status: Any) -> str:
    key = str(marker_key or "").strip().lower()
    status = re.sub(r"[^a-z0-9+]+", "_", str(raw_status or "").strip().lower()).strip("_")
    if status in {"review", "needs_review", "uncertain", "unknown", "cannot_read", "not_visible"}:
        return "review"
    if key == "concentration":
        if status in {"well", "dilute", "very_dilute", "very_low", "overhydrated", "well_hydrated"}:
            return "well"
        if status in {"ok", "balanced", "normal", "clear", "hydrated", "in_range"}:
            return "ok"
        if status in {"low", "concentrated", "high", "very_high", "dehydrated", "underhydrated"}:
            return "low"
    if key == "uti":
        if status in {"clear", "negative", "neg", "none", "normal", "ok"}:
            return "clear"
        if status in {"watch", "trace", "small", "trace_small"}:
            return "watch"
        if status in {"flagged", "positive", "pos", "moderate", "large", "moderate_large", "raised", "high"}:
            return "flagged"
    if key in {"protein", "blood"}:
        if status in {"clear", "negative", "neg", "none", "normal", "ok"}:
            return "clear"
        if status in {"trace", "small", "trace_small", "non_hemolyzed", "non_haemolyzed"}:
            return "trace"
        if status in {"flagged", "positive", "pos", "moderate", "large", "moderate_large", "raised", "high", "1+", "2+", "3+"}:
            return "flagged"
    if key == "glucose":
        if status in {"clear", "negative", "neg", "none", "normal", "ok"}:
            return "clear"
        if status in {"raised", "positive", "pos", "trace", "small", "moderate", "large", "high", "1+", "2+", "3+"}:
            return "raised"
    if key == "ketones":
        if status in {"clear", "negative", "neg", "none", "normal", "ok"}:
            return "clear"
        if status in {"trace", "small", "trace_small"}:
            return "trace"
        if status in {"raised", "positive", "pos", "moderate", "large", "moderate_large", "high", "1+", "2+", "3+"}:
            return "raised"
    status = _STATUS_SYNONYMS.get(status, status)
    options = _STATUS_OPTIONS_BY_MARKER.get(key) or set()
    if status in options:
        return status
    if status == "review":
        return "review"
    if key == "concentration" and status in {"clear", "normal", "balanced"}:
        return "ok"
    if key in {"glucose", "ketones"} and status == "flagged":
        return "raised"
    if key in {"protein", "blood"} and status == "raised":
        return "flagged"
    if key == "uti" and status == "raised":
        return "flagged"
    return "review"


def _analyte_token(raw_value: Any) -> str:
    return re.sub(r"[^a-z0-9.+]+", "_", str(raw_value or "").strip().lower()).strip("_")


def _is_negative_analyte(raw_value: Any) -> bool:
    return _analyte_token(raw_value) in {"neg", "negative", "none", "normal", "clear", "0", "0.0"}


def _derive_marker_status_from_analytes(marker_key: str, raw_analytes: dict[str, Any]) -> str | None:
    key = str(marker_key or "").strip().lower()
    if key == "concentration":
        token = _analyte_token(raw_analytes.get("specific_gravity"))
        try:
            value = float(re.sub(r"[^0-9.]+", "", token))
            if value <= 1.005:
                return "well"
            if value <= 1.025:
                return "ok"
            return "low"
        except Exception:
            return _normalize_status("concentration", token) if token else None
    if key == "uti":
        leukocytes = _analyte_token(raw_analytes.get("leukocytes"))
        nitrite = _analyte_token(raw_analytes.get("nitrite"))
        if nitrite in {"positive", "pos", "trace", "small", "moderate", "large"}:
            return "flagged"
        if leukocytes in {"moderate", "large", "positive", "pos"}:
            return "flagged"
        if leukocytes in {"trace", "small", "trace_small"}:
            return "watch"
        if leukocytes and nitrite and _is_negative_analyte(leukocytes) and _is_negative_analyte(nitrite):
            return "clear"
        return None
    if key in {"protein", "blood", "glucose", "ketones"}:
        analyte_key = "ketones" if key == "ketones" else key
        raw_value = raw_analytes.get(analyte_key)
        if not _analyte_token(raw_value):
            return None
        if _is_negative_analyte(raw_value):
            return "clear"
        return _normalize_status(key, raw_value)
    return None


def _marker_tone(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {"clear", "ok", "well"}:
        return "success"
    if normalized in {"flagged", "raised"}:
        return "danger"
    if normalized in {"watch", "trace", "low", "queued", "review"}:
        return "warning"
    return "neutral"


def _review_markers(reason: str) -> list[dict[str, Any]]:
    return [
        {
            "key": str(marker["key"]),
            "label": str(marker["label"]),
            "source_analytes": list(marker.get("source_analytes") or []),
            "status": "review",
            "status_label": "review",
            "tone": "warning",
            "status_options": list(marker.get("status_options") or []),
            "note": reason,
        }
        for marker in URINE_MARKER_DEFINITIONS
    ]


def _validate_analysis_payload(parsed: dict[str, Any], *, model: str, duration_ms: int) -> dict[str, Any]:
    interpretation_status = str(parsed.get("interpretation_status") or "").strip().lower()
    if interpretation_status in {"analyzed", "analysed", "analysis_complete", "complete", "ok"}:
        interpretation_status = "analysed"
    elif interpretation_status in {"needs review", "needs_review", "review"}:
        interpretation_status = "needs_review"
    confidence = _coerce_float(parsed.get("confidence"), 0.0)
    min_confidence = _analysis_min_confidence()
    notes = parsed.get("notes") if isinstance(parsed.get("notes"), list) else []
    clean_notes = [str(note).strip() for note in notes if str(note).strip()]
    raw_markers = parsed.get("markers") if isinstance(parsed.get("markers"), list) else []
    raw_analytes = parsed.get("raw_analytes") if isinstance(parsed.get("raw_analytes"), dict) else {}
    raw_marker_map: dict[str, dict[str, Any]] = {}
    for item in raw_markers:
        if not isinstance(item, dict):
            continue
        marker_key = str(item.get("key") or "").strip().lower()
        if marker_key:
            raw_marker_map[marker_key] = item

    markers: list[dict[str, Any]] = []
    resolved_marker_count = 0
    review_marker_count = 0
    for definition in URINE_MARKER_DEFINITIONS:
        marker_key = str(definition["key"])
        item = raw_marker_map.get(marker_key) or {}
        status = _normalize_status(marker_key, item.get("status"))
        if status == "review":
            status = _derive_marker_status_from_analytes(marker_key, raw_analytes) or status
        if status == "review":
            review_marker_count += 1
        else:
            resolved_marker_count += 1
        markers.append(
            {
                "key": marker_key,
                "label": str(definition["label"]),
                "source_analytes": list(definition.get("source_analytes") or []),
                "status": status,
                "status_label": status,
                "tone": _marker_tone(status),
                "status_options": list(definition.get("status_options") or []),
                "confidence": _coerce_float(item.get("confidence"), confidence),
                "note": str(item.get("note") or "").strip() or None,
            }
        )

    whole_photo_uncertain = interpretation_status != "analysed" or confidence < min_confidence
    if whole_photo_uncertain and resolved_marker_count == 0:
        reason = "review"
        return {
            "provider": SIEMENS_MULTISTIX_PROVIDER,
            "test_name": "Siemens Multistix",
            "interpretation_status": "needs_review",
            "confidence": confidence,
            "markers": _review_markers(reason),
            "notes": clean_notes or ["Photo quality, timing, or strip visibility was not strong enough for interpretation."],
            "raw_analytes": raw_analytes,
            "analysis": {
                "model": model,
                "duration_ms": duration_ms,
                "minimum_confidence": min_confidence,
                "source": "vision_llm",
            },
            "screening_note": (
                "This urine strip photo could not be interpreted with enough confidence. "
                "Retake on a plain white background in good light at the 60-second capture point."
            ),
        }

    if whole_photo_uncertain:
        if confidence < min_confidence:
            clean_notes.append("Overall photo confidence was low; resolved markers are shown, but uncertain markers should be retaken.")
        elif interpretation_status != "analysed":
            clean_notes.append("The analyser requested review for part of the photo; resolved markers are shown where available.")
    interpretation_status = "needs_review" if whole_photo_uncertain or review_marker_count else "analysed"
    return {
        "provider": SIEMENS_MULTISTIX_PROVIDER,
        "test_name": "Siemens Multistix",
        "interpretation_status": interpretation_status,
        "confidence": confidence,
        "markers": markers,
        "notes": clean_notes,
        "raw_analytes": raw_analytes,
        "analysis": {
            "model": model,
            "duration_ms": duration_ms,
            "minimum_confidence": min_confidence,
            "source": "vision_llm",
        },
        "screening_note": (
            "Urine strip photo results are screening information only and are not a diagnosis. "
            "Repeat or seek clinical advice for symptoms or flagged results."
        ),
    }


def analyse_urine_test_photo(image_data_url: str) -> dict[str, Any]:
    if not _analysis_enabled():
        return {
            **_default_result_payload(),
            "interpretation_status": "queued",
            "notes": ["Urine test analysis is disabled."],
        }
    image_payload = str(image_data_url or "").strip()
    if not image_payload:
        return {
            **_default_result_payload(),
            "interpretation_status": "queued",
            "notes": ["No image payload was received."],
        }
    if not image_payload.startswith("data:image/"):
        return {
            "provider": SIEMENS_MULTISTIX_PROVIDER,
            "test_name": "Siemens Multistix",
            "interpretation_status": "needs_review",
            "confidence": 0.0,
            "markers": _review_markers("review"),
            "notes": ["Image format was not recognised."],
            "raw_analytes": {},
            "screening_note": "Retake the urine strip photo in the app camera flow.",
        }

    model = _analysis_model_name()
    reference_json = json.dumps(URINE_ANALYTE_REFERENCE, ensure_ascii=False, sort_keys=True)
    system_prompt = (
        "You analyse photos of Siemens Multistix urine reagent strips for a wellness screening app. "
        "Return only JSON. Do not diagnose disease. Use the embedded colour/status reference; do not "
        "require an external colour chart to be visible. If a strip and most reagent pads are visible, "
        "return interpretation_status analysed and provide the best marker statuses you can. Only set the "
        "whole test to needs_review when the strip cannot be interpreted at all. "
        "Use only the allowed marker status words."
    )
    user_text = (
        "Inspect the image for a Siemens Multistix urine strip photographed at about 60 seconds after dipping. "
        "No external colour chart is required; use this embedded HealthSense reference map:\n"
        f"{reference_json}\n\n"
        "Use this HealthSense output mapping only:\n"
        "- hydration from specific gravity: well, ok, low\n"
        "- uti from leukocytes + nitrite: clear, watch, flagged\n"
        "- protein: clear, trace, flagged\n"
        "- blood: clear, trace, flagged\n"
        "- glucose: clear, raised\n"
        "- ketones: clear, trace, raised\n\n"
        "Return one JSON object with these keys only: "
        "interpretation_status, confidence, markers, raw_analytes, notes. "
        'interpretation_status must be "analysed" or "needs_review". '
        "confidence must be a number from 0 to 1 based on the overall image. "
        "markers must contain exactly six objects in this order: concentration, uti, protein, blood, glucose, ketones. "
        "Each marker object must include key, status, confidence, and note. "
        "Use review for an individual marker only when that pad cannot be judged. "
        "raw_analytes must include specific_gravity, leukocytes, nitrite, protein, blood, glucose, and ketones. "
        "Do not wrap the JSON in markdown."
    )
    try:
        from . import llm as shared_llm

        client = shared_llm.get_llm_client(
            touchpoint="urine_test_analysis",
            model_override=model,
        )
        started_at = time.perf_counter()
        response = client.invoke(
            [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_text},
                        {"type": "image_url", "image_url": {"url": image_payload}},
                    ],
                },
            ]
        )
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        raw_text = str(getattr(response, "content", "") or "").strip()
        parsed = _extract_json_object(raw_text)
        if not parsed:
            return {
                "provider": SIEMENS_MULTISTIX_PROVIDER,
                "test_name": "Siemens Multistix",
                "interpretation_status": "needs_review",
                "confidence": 0.0,
                "markers": _review_markers("review"),
                "notes": ["The analyser did not return valid structured results."],
                "raw_analytes": {},
                "analysis": {
                    "model": model,
                    "duration_ms": duration_ms,
                    "source": "vision_llm",
                    "raw_preview": raw_text[:500],
                },
                "screening_note": "Retake on a plain white background in good light at the 60-second capture point.",
            }
        result = _validate_analysis_payload(parsed, model=model, duration_ms=duration_ms)
        result.setdefault("analysis", {})["raw_preview"] = raw_text[:500]
        return result
    except Exception as exc:
        return {
            "provider": SIEMENS_MULTISTIX_PROVIDER,
            "test_name": "Siemens Multistix",
            "interpretation_status": "needs_review",
            "confidence": 0.0,
            "markers": _review_markers("review"),
            "notes": [f"Analysis failed: {exc}"],
            "raw_analytes": {},
            "analysis": {
                "model": model,
                "source": "vision_llm",
                "error": str(exc),
            },
            "screening_note": "Retake the photo or try again later.",
        }


def _serialize_row(row: Any | None) -> dict[str, Any]:
    if not row:
        return {
            "available": False,
            "provider": SIEMENS_MULTISTIX_PROVIDER,
            "markers": _ready_markers(),
        }
    mapping = row._mapping if hasattr(row, "_mapping") else row
    result_payload = _parse_json_value(mapping.get("result_payload"))
    image_metadata = _parse_json_value(mapping.get("image_metadata"))
    sample_date = mapping.get("sample_date")
    captured_at = mapping.get("captured_at")
    created_at = mapping.get("created_at")
    updated_at = mapping.get("updated_at")
    payload = result_payload if isinstance(result_payload, dict) else {}
    return {
        "available": True,
        "id": int(mapping.get("id")),
        "provider": str(mapping.get("provider") or SIEMENS_MULTISTIX_PROVIDER),
        "sample_date": sample_date.isoformat() if isinstance(sample_date, date) else str(sample_date or ""),
        "captured_at": captured_at.isoformat() if isinstance(captured_at, datetime) else str(captured_at or ""),
        "status": str(mapping.get("status") or "queued"),
        "markers": payload.get("markers") if isinstance(payload.get("markers"), list) else _queued_markers(),
        "result_payload": payload,
        "image_metadata": image_metadata if isinstance(image_metadata, dict) else {},
        "created_at": created_at.isoformat() if isinstance(created_at, datetime) else str(created_at or ""),
        "updated_at": updated_at.isoformat() if isinstance(updated_at, datetime) else str(updated_at or ""),
    }


def _queued_markers() -> list[dict[str, Any]]:
    return [
        {
            "key": str(marker["key"]),
            "label": str(marker["label"]),
            "source_analytes": list(marker.get("source_analytes") or []),
            "status": "queued",
            "status_label": "queued",
            "tone": "warning",
            "status_options": list(marker.get("status_options") or []),
        }
        for marker in URINE_MARKER_DEFINITIONS
    ]


def _ready_markers() -> list[dict[str, Any]]:
    return [
        {
            "key": str(marker["key"]),
            "label": str(marker["label"]),
            "source_analytes": list(marker.get("source_analytes") or []),
            "status": "ready",
            "status_label": "ready",
            "tone": "neutral",
            "status_options": list(marker.get("status_options") or []),
        }
        for marker in URINE_MARKER_DEFINITIONS
    ]


def _default_result_payload() -> dict[str, Any]:
    return {
        "provider": SIEMENS_MULTISTIX_PROVIDER,
        "test_name": "Siemens Multistix",
        "interpretation_status": "queued",
        "markers": _queued_markers(),
        "screening_note": (
            "Photo captured. Interpretation is queued; urine strip results are screening information "
            "and are not a diagnosis."
        ),
    }


def get_latest_urine_test_result(session, *, user_id: int) -> dict[str, Any]:
    ensure_urine_test_schema()
    row = (
        session.execute(
            text(
                """
                SELECT id, user_id, provider, sample_date, captured_at, status,
                       result_payload, image_metadata, created_at, updated_at
                FROM urine_tests
                WHERE user_id = :user_id
                ORDER BY captured_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"user_id": int(user_id)},
        )
        .mappings()
        .first()
    )
    return _serialize_row(row)


def record_urine_test_capture(session, *, user_id: int, payload: dict[str, Any] | None) -> dict[str, Any]:
    ensure_urine_test_schema()
    body = payload if isinstance(payload, dict) else {}
    captured_at = _parse_datetime(body.get("captured_at"))
    image_data_url = str(body.get("image_data_url") or "").strip()
    if image_data_url and len(image_data_url.encode("utf-8")) > URINE_TEST_MAX_IMAGE_DATA_URL_BYTES:
        raise ValueError("Urine test image is too large. Please retake with a smaller image.")
    image_metadata = {
        "file_name": str(body.get("file_name") or "").strip() or None,
        "mime_type": str(body.get("mime_type") or "").strip() or None,
        "size_bytes": int(body.get("size_bytes") or 0) if str(body.get("size_bytes") or "").isdigit() else None,
        "capture_stage": str(body.get("capture_stage") or "single").strip() or "single",
        "has_image_payload": bool(image_data_url),
        "image_payload_bytes": len(image_data_url.encode("utf-8")) if image_data_url else 0,
        "image_storage": "not_persisted",
    }
    result_payload = analyse_urine_test_photo(image_data_url) if image_data_url else _default_result_payload()
    result_payload["capture_stage"] = image_metadata["capture_stage"]
    interpretation_status = str(result_payload.get("interpretation_status") or "queued").strip().lower()
    row_status = (
        "analysed"
        if interpretation_status == "analysed"
        else "needs_review"
        if interpretation_status == "needs_review"
        else "queued"
    )
    params = {
        "user_id": int(user_id),
        "provider": SIEMENS_MULTISTIX_PROVIDER,
        "sample_date": captured_at.date(),
        "captured_at": captured_at,
        "status": row_status,
        "result_payload": json.dumps(result_payload),
        "image_metadata": json.dumps(image_metadata),
    }
    if _is_postgres():
        insert_sql = text(
            """
            INSERT INTO urine_tests (
                user_id, provider, sample_date, captured_at, status,
                result_payload, image_metadata, created_at, updated_at
            )
            VALUES (
                :user_id, :provider, :sample_date, :captured_at, :status,
                CAST(:result_payload AS jsonb), CAST(:image_metadata AS jsonb), now(), now()
            )
            RETURNING id, user_id, provider, sample_date, captured_at, status,
                      result_payload, image_metadata, created_at, updated_at
            """
        )
    else:
        insert_sql = text(
            """
            INSERT INTO urine_tests (
                user_id, provider, sample_date, captured_at, status,
                result_payload, image_metadata, created_at, updated_at
            )
            VALUES (
                :user_id, :provider, :sample_date, :captured_at, :status,
                :result_payload, :image_metadata, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            RETURNING id, user_id, provider, sample_date, captured_at, status,
                      result_payload, image_metadata, created_at, updated_at
            """
        )
    row = session.execute(insert_sql, params).mappings().first()
    return _serialize_row(row)
