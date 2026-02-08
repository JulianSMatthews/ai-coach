from __future__ import annotations

from datetime import datetime, timezone
import os
import re
from typing import Any

import requests


def _usd_to_gbp() -> tuple[float, str]:
    raw = (os.getenv("USAGE_USD_TO_GBP") or os.getenv("USD_TO_GBP") or "").strip()
    if raw:
        try:
            return float(raw), "env"
        except Exception:
            return 0.8, "default"
    return 0.8, "default"


def _convert_usd_to_gbp(value_usd: float) -> float:
    fx, _ = _usd_to_gbp()
    return value_usd * fx


def _fetch_text(url: str, headers: dict | None = None, auth: tuple[str, str] | None = None) -> str | None:
    try:
        resp = requests.get(url, headers=headers, auth=auth, timeout=20)
        if not resp.ok:
            return None
        return resp.text or ""
    except Exception:
        return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "\n", text or "")


def fetch_openai_pricing(model_name: str | None = None) -> dict[str, Any]:
    """
    Best-effort fetch for OpenAI pricing from the public pricing page.
    Returns input/output USD per 1M tokens if found.
    """
    url = "https://platform.openai.com/pricing"
    raw = _fetch_text(url)
    if not raw:
        return {"ok": False, "error": "openai_pricing_fetch_failed"}
    text = _strip_html(raw)
    # Parse table rows like: gpt-4o-mini  | $0.15  | $0.075  | $0.60
    row_re = re.compile(r"^(gpt-[\\w\\.-]+)\\s*\\|\\s*\\$([0-9.]+)\\s*\\|\\s*\\$([0-9.]+)\\s*\\|\\s*\\$([0-9.]+)", re.M)
    rows = row_re.findall(text)
    price_map = {name: {"input": float(inp), "cached": float(cached), "output": float(out)} for name, inp, cached, out in rows}
    model = model_name or ""
    model = model.strip()
    match = price_map.get(model) if model else None
    if not match and model:
        # Try to fallback to base name (drop version suffixes)
        base = re.sub(r"-\\d{4}-\\d{2}-\\d{2}$", "", model)
        match = price_map.get(base)
    if not match and model and model.startswith("gpt-5.2"):
        fallback = "gpt-5.1"
        match = price_map.get(fallback)
        if match:
            return {
                "ok": True,
                "model": model,
                "fallback_model": fallback,
                "input_per_1m_usd": match["input"],
                "output_per_1m_usd": match["output"],
                "cached_per_1m_usd": match["cached"],
                "source": url,
            }
    if not match and not model:
        return {"ok": True, "prices": price_map, "model": None}
    if not match:
        return {"ok": False, "error": "model_not_found", "model": model, "prices": price_map}
    return {
        "ok": True,
        "model": model or None,
        "input_per_1m_usd": match["input"],
        "output_per_1m_usd": match["output"],
        "cached_per_1m_usd": match["cached"],
        "source": url,
    }


def fetch_openai_tts_rate() -> dict[str, Any]:
    """
    Best-effort fetch for OpenAI TTS estimated $/minute from pricing page.
    """
    url = "https://platform.openai.com/pricing"
    raw = _fetch_text(url)
    if not raw:
        return {"ok": False, "error": "openai_pricing_fetch_failed"}
    text = _strip_html(raw)
    # Find line like: gpt-4o-mini-tts  | $0.60  | -  | $0.015 / minute
    m = re.search(r"gpt-4o-mini-tts\\s*\\|\\s*\\$[0-9.]+\\s*\\|\\s*-\\s*\\|\\s*\\$([0-9.]+)\\s*/\\s*minute", text)
    if not m:
        return {"ok": False, "error": "tts_rate_not_found"}
    return {
        "ok": True,
        "model": "gpt-4o-mini-tts",
        "per_min_usd": float(m.group(1)),
        "source": url,
    }


def fetch_azure_tts_rate(region: str) -> dict[str, Any]:
    """
    Fetch Azure Speech TTS Neural price per 1M chars (USD) via Retail Prices API.
    """
    region = (region or "").strip().lower()
    if not region:
        return {"ok": False, "error": "missing_region"}
    url = (
        "https://prices.azure.com/api/retail/prices?"
        f"$filter=armRegionName%20eq%20'{region}'%20and%20serviceName%20eq%20'Cognitive%20Services'%20and%20contains(productName,'Text%20to%20Speech')"
    )
    best = None
    next_url = url
    while next_url:
        data = None
        try:
            resp = requests.get(next_url, timeout=20)
            if not resp.ok:
                break
            data = resp.json()
        except Exception:
            break
        items = data.get("Items") or []
        for item in items:
            name = f"{item.get('productName','')} {item.get('meterName','')}".lower()
            unit = (item.get("unitOfMeasure") or "").lower()
            if "text to speech" not in name:
                continue
            if "1m" not in unit and "1 m" not in unit:
                continue
            score = 0
            if "neural" in name:
                score += 2
            if "standard" in name:
                score += 1
            price = item.get("retailPrice")
            if price is None:
                continue
            candidate = {
                "price": float(price),
                "currency": item.get("currencyCode") or "USD",
                "name": name,
                "unit": unit,
                "score": score,
                "source": next_url,
            }
            if not best or candidate["score"] > best["score"]:
                best = candidate
        next_url = data.get("NextPageLink")
    if not best:
        return {"ok": False, "error": "azure_tts_rate_not_found"}
    return {"ok": True, **best}


def fetch_twilio_whatsapp_base_fee() -> dict[str, Any]:
    """
    Best-effort fetch of Twilio's base WhatsApp fee from the public pricing page.
    """
    url = "https://www.twilio.com/en-us/whatsapp/pricing"
    raw = _fetch_text(url)
    if not raw:
        return {"ok": False, "error": "twilio_pricing_fetch_failed"}
    text = _strip_html(raw)
    # Look for "$0.005" per message fee.
    m = re.search(r"Twilio(?:’|')?s per-message fee for WhatsApp is \\$([0-9.]+)", text, re.IGNORECASE)
    if not m:
        m = re.search(r"\\$([0-9.]+)\\s*/message Twilio Fee", text, re.IGNORECASE)
    if not m:
        return {"ok": False, "error": "twilio_whatsapp_fee_not_found"}
    return {
        "ok": True,
        "per_message_usd": float(m.group(1)),
        "source": url,
    }


def fetch_provider_rates() -> dict[str, Any]:
    fx, fx_source = _usd_to_gbp()
    fetched_at = datetime.now(timezone.utc).isoformat()
    results: dict[str, Any] = {
        "fetched_at": fetched_at,
        "fx_usd_to_gbp": fx,
        "fx_source": fx_source,
        "sources": {},
        "warnings": [],
    }

    # TTS
    tts_provider = "openai"
    if os.getenv("USE_AZURE_SPEECH", "0") == "1":
        tts_provider = "azure"
    if tts_provider == "azure":
        region = os.getenv("AZURE_SPEECH_REGION") or os.getenv("AZURE_TTS_REGION") or "uksouth"
        azure = fetch_azure_tts_rate(region)
        if azure.get("ok"):
            usd = float(azure["price"])
            gbp = _convert_usd_to_gbp(usd)
            results["tts_gbp_per_1m_chars"] = gbp
            results["sources"]["tts"] = {"provider": "azure", "detail": azure}
        else:
            results["warnings"].append("azure_tts_rate_unavailable")
    else:
        tts = fetch_openai_tts_rate()
        if tts.get("ok"):
            per_min_usd = float(tts["per_min_usd"])
            chars_per_min = float(os.getenv("USAGE_TTS_CHARS_PER_MIN") or 900)
            usd_per_1m = (per_min_usd / chars_per_min) * 1_000_000.0
            results["tts_gbp_per_1m_chars"] = _convert_usd_to_gbp(usd_per_1m)
            results["tts_chars_per_min"] = chars_per_min
            results["sources"]["tts"] = {"provider": "openai", "detail": tts}
        else:
            results["warnings"].append("openai_tts_rate_unavailable")

    # LLM
    model_name = os.getenv("LLM_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5.2"
    openai = fetch_openai_pricing(model_name)
    if openai.get("ok"):
        results["llm_gbp_per_1m_input_tokens"] = _convert_usd_to_gbp(float(openai["input_per_1m_usd"]))
        results["llm_gbp_per_1m_output_tokens"] = _convert_usd_to_gbp(float(openai["output_per_1m_usd"]))
        results["sources"]["llm"] = {"provider": "openai", "detail": openai}
    else:
        results["warnings"].append("openai_llm_rate_unavailable")

    # WhatsApp base fee (Twilio)
    twilio = fetch_twilio_whatsapp_base_fee()
    if twilio.get("ok"):
        gbp = _convert_usd_to_gbp(float(twilio["per_message_usd"]))
        results["wa_gbp_per_message"] = gbp
        results["wa_gbp_per_media_message"] = gbp
        results["wa_gbp_per_template_message"] = gbp
        results["sources"]["whatsapp"] = {"provider": "twilio", "detail": twilio}
    else:
        results["warnings"].append("twilio_whatsapp_rate_unavailable")

    return results
