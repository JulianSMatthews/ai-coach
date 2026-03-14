from __future__ import annotations

import os
import re
import time
import uuid
from html import escape
from typing import Any
from urllib.parse import urlparse

import requests


def _is_truthy_env(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def azure_avatar_enabled() -> bool:
    configured = os.getenv("USE_AZURE_AVATAR")
    if configured is None:
        configured = os.getenv("USE_AZURE_SPEECH")
    return _is_truthy_env(configured)


def azure_avatar_defaults() -> dict[str, Any]:
    return {
        "character": str(os.getenv("AZURE_AVATAR_CHARACTER") or "lisa").strip() or "lisa",
        "style": str(os.getenv("AZURE_AVATAR_STYLE") or "graceful-sitting").strip() or "graceful-sitting",
        "voice": (
            str(
                os.getenv("AZURE_AVATAR_VOICE")
                or os.getenv("AZURE_SPEECH_VOICE")
                or os.getenv("AZURE_SPEECH_VOICE_ID")
                or "en-GB-SoniaNeural"
            ).strip()
            or "en-GB-SoniaNeural"
        ),
        "video_format": str(os.getenv("AZURE_AVATAR_VIDEO_FORMAT") or "Mp4").strip() or "Mp4",
        "video_codec": str(os.getenv("AZURE_AVATAR_VIDEO_CODEC") or "h264").strip() or "h264",
        "subtitle_type": str(os.getenv("AZURE_AVATAR_SUBTITLE_TYPE") or "none").strip() or "none",
        "background_color": str(os.getenv("AZURE_AVATAR_BACKGROUND_COLOR") or "#FFF8F1FF").strip() or "#FFF8F1FF",
        "bitrate_kbps": _safe_int(os.getenv("AZURE_AVATAR_BITRATE_KBPS"), 2000),
        "time_to_live_hours": max(1, min(_safe_int(os.getenv("AZURE_AVATAR_TTL_HOURS"), 48), 744)),
        "timeout_seconds": max(10, _safe_int(os.getenv("AZURE_AVATAR_TIMEOUT_SECONDS"), 180)),
        "poll_seconds": max(2, _safe_int(os.getenv("AZURE_AVATAR_POLL_SECONDS"), 5)),
        "locale": str(os.getenv("AZURE_AVATAR_LOCALE") or "en-GB").strip() or "en-GB",
    }


def _safe_int(value: str | None, default: int) -> int:
    try:
        parsed = int(str(value or "").strip())
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _speech_resource_key() -> str:
    key = str(os.getenv("AZURE_SPEECH_KEY") or os.getenv("AZURE_TTS_KEY") or "").strip()
    if not key:
        raise RuntimeError("AZURE_SPEECH_KEY is not set")
    return key


def _speech_api_base() -> str:
    endpoint = str(os.getenv("AZURE_AVATAR_ENDPOINT") or os.getenv("AZURE_SPEECH_ENDPOINT") or "").strip()
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    region = str(os.getenv("AZURE_SPEECH_REGION") or os.getenv("AZURE_TTS_REGION") or "").strip()
    if not region:
        raise RuntimeError("AZURE_SPEECH_REGION is not set")
    return f"https://{region}.api.cognitive.microsoft.com"


def _azure_headers(*, include_content_type: bool = False) -> dict[str, str]:
    headers = {"Ocp-Apim-Subscription-Key": _speech_resource_key()}
    if include_content_type:
        headers["Content-Type"] = "application/json"
    return headers


def _sanitize_job_id(value: str) -> str:
    compact = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-_")
    compact = compact[:48]
    if len(compact) < 3:
        compact = f"intro-avatar-{uuid.uuid4().hex[:10]}"
    if not compact[0].isalnum():
        compact = f"a{compact}"
    if not compact[-1].isalnum():
        compact = f"{compact}a"
    return compact[:64]


def build_avatar_ssml(script: str, voice: str, locale: str = "en-GB") -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", str(script or "").strip()) if part.strip()]
    if not paragraphs:
        raise RuntimeError("Avatar script is empty")
    content_parts: list[str] = []
    for index, paragraph in enumerate(paragraphs):
        escaped = escape(paragraph).replace("\n", " ")
        content_parts.append(escaped)
        if index < len(paragraphs) - 1:
            content_parts.append("<break time='400ms'/>")
    content = " ".join(content_parts)
    return (
        f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='{escape(locale)}'>"
        f"<voice name='{escape(voice)}'><prosody rate='0.96'>{content}</prosody></voice></speak>"
    )


def create_batch_avatar(
    *,
    script: str,
    title: str,
    character: str,
    style: str,
    voice: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    defaults = azure_avatar_defaults()
    batch_id = _sanitize_job_id(job_id or f"{title or 'intro-avatar'}-{uuid.uuid4().hex[:12]}")
    payload: dict[str, Any] = {
        "displayName": title or "Intro avatar",
        "description": "HealthSense assessment intro avatar",
        "inputKind": "SSML",
        "inputs": [{"content": build_avatar_ssml(script, voice, defaults["locale"])}],
        "avatarConfig": {
            "talkingAvatarCharacter": character or defaults["character"],
            "talkingAvatarStyle": style or defaults["style"],
            "videoFormat": defaults["video_format"],
            "videoCodec": defaults["video_codec"],
            "subtitleType": defaults["subtitle_type"],
            "backgroundColor": defaults["background_color"],
            "bitrateKbps": defaults["bitrate_kbps"],
        },
        "properties": {
            "timeToLiveInHours": defaults["time_to_live_hours"],
        },
    }
    response = requests.put(
        f"{_speech_api_base()}/avatar/batchsyntheses/{batch_id}?api-version=2024-08-01",
        json=payload,
        headers=_azure_headers(include_content_type=True),
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Azure avatar create returned invalid response")
    return data


def get_batch_avatar(job_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{_speech_api_base()}/avatar/batchsyntheses/{job_id}?api-version=2024-08-01",
        headers=_azure_headers(),
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise RuntimeError("Azure avatar status returned invalid response")
    return data


def wait_for_batch_avatar(job_id: str, *, timeout_seconds: int | None = None, poll_seconds: int | None = None) -> dict[str, Any]:
    defaults = azure_avatar_defaults()
    timeout = timeout_seconds or defaults["timeout_seconds"]
    poll = poll_seconds or defaults["poll_seconds"]
    deadline = time.time() + timeout
    latest = get_batch_avatar(job_id)
    while time.time() < deadline:
        status = str(latest.get("status") or "").strip()
        if status in {"Succeeded", "Failed"}:
            return latest
        time.sleep(poll)
        latest = get_batch_avatar(job_id)
    latest["status"] = str(latest.get("status") or "Running").strip() or "Running"
    latest["_timed_out"] = True
    return latest


def download_batch_avatar_output(output_url: str) -> bytes:
    response = requests.get(output_url, headers=_azure_headers(), timeout=120)
    response.raise_for_status()
    return bytes(response.content or b"")


def generate_batch_avatar_video(
    *,
    script: str,
    title: str,
    character: str | None = None,
    style: str | None = None,
    voice: str | None = None,
) -> dict[str, Any]:
    defaults = azure_avatar_defaults()
    create_payload = create_batch_avatar(
        script=script,
        title=title,
        character=character or defaults["character"],
        style=style or defaults["style"],
        voice=voice or defaults["voice"],
    )
    job_id = str(create_payload.get("id") or "").strip()
    if not job_id:
        raise RuntimeError("Azure avatar generation did not return a job id")
    latest = wait_for_batch_avatar(job_id)
    status = str(latest.get("status") or "").strip()
    outputs = latest.get("outputs") if isinstance(latest.get("outputs"), dict) else {}
    result_url = str((outputs or {}).get("result") or "").strip() or None
    summary_url = str((outputs or {}).get("summary") or "").strip() or None
    video_bytes = download_batch_avatar_output(result_url) if status == "Succeeded" and result_url else None
    return {
        "job_id": job_id,
        "status": status,
        "timed_out": bool(latest.get("_timed_out")),
        "result_url": result_url,
        "summary_url": summary_url,
        "video_bytes": video_bytes,
        "response": latest,
    }


__all__ = [
    "azure_avatar_defaults",
    "azure_avatar_enabled",
    "build_avatar_ssml",
    "create_batch_avatar",
    "download_batch_avatar_output",
    "generate_batch_avatar_video",
    "get_batch_avatar",
    "wait_for_batch_avatar",
]
