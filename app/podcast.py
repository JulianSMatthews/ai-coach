"""
Podcast helpers: TTS (ElevenLabs/OpenAI) for a given transcript.
Azure Speech is supported when USE_AZURE_SPEECH=1 with AZURE_SPEECH_KEY and AZURE_SPEECH_REGION.
"""
from __future__ import annotations

import os
import requests
import base64
from openai import OpenAI  # type: ignore
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from .reporting import _reports_root_for_user
from .usage import log_usage_event
from .db import SessionLocal
from .models import UserPreference


def _mask_secret(val: str | None) -> str:
    if not val:
        return ""
    v = val.strip()
    if len(v) <= 6:
        return "***"
    return f"{v[:3]}***{v[-3:]}"


def _voice_pref_for_user(user_id: int) -> Optional[str]:
    with SessionLocal() as s:
        pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user_id, UserPreference.key == "tts_voice_pref")
            .one_or_none()
        )
        return pref.value if pref and pref.value else None


def _select_voice_choices(user_id: int, role: Optional[str], voice_override: Optional[str]) -> Tuple[Optional[str], str, str]:
    """
    Choose provider-specific voices using a single role-aware selector.
    Returns (azure_voice, chatgpt_voice, elevenlabs_voice).
    role: None|\"male\"|\"female\"; overrides stored user pref when provided.
    voice_override: explicit voice name/id; applies to all providers when set.
    """
    # Resolve effective role (override > stored preference)
    pref = role or _voice_pref_for_user(user_id)

    # Azure voices
    azure_default = (
        os.getenv("AZURE_SPEECH_VOICE")
        or os.getenv("AZURE_SPEECH_VOICE_ID")
        or os.getenv("AZURE_TTS_VOICE")
        or "en-US-JennyNeural"
    )
    azure_male = os.getenv("AZURE_SPEECH_VOICE_MALE") or os.getenv("AZURE_TTS_VOICE_MALE")
    azure_female = os.getenv("AZURE_SPEECH_VOICE_FEMALE") or os.getenv("AZURE_TTS_VOICE_FEMALE")
    azure_voice = azure_default
    if pref == "male" and azure_male:
        azure_voice = azure_male
    elif pref == "female" and azure_female:
        azure_voice = azure_female

    # ChatGPT voices (OpenAI TTS): alloy (neutral), shimmer/coral (more feminine), echo/verse (more masculine)
    chatgpt_male = os.getenv("GPT_VOICE_MALE", "echo")
    chatgpt_female = os.getenv("GPT_VOICE_FEMALE", "shimmer")
    chatgpt_default = os.getenv("GPT_VOICE_DEFAULT", "alloy")
    chatgpt_voice = chatgpt_default
    if pref == "male":
        chatgpt_voice = chatgpt_male
    elif pref == "female":
        chatgpt_voice = chatgpt_female

    # ElevenLabs voices
    el_male = os.getenv("ELEVENLABS_VOICE_MALE") or os.getenv("elevenlabs_voice_male") or ""
    el_female = os.getenv("ELEVENLABS_VOICE_FEMALE") or os.getenv("elevenlabs_voice_female") or ""
    el_default = os.getenv("ELEVENLABS_VOICE_ID") or os.getenv("elevenlabs_voice_id") or "Rachel"
    el_voice = el_default
    if pref == "male" and el_male:
        el_voice = el_male
    elif pref == "female" and el_female:
        el_voice = el_female

    # voice_override applies to all providers when explicitly given
    if voice_override:
        azure_voice = voice_override
        if voice_override in _VALID_CHATGPT_VOICES:
            chatgpt_voice = voice_override
        el_voice = voice_override

    return azure_voice, chatgpt_voice, el_voice


def _tts_via_azure(transcript: str, voice_name: str | None) -> bytes | None:
    """
    Best-effort Azure Speech synthesis. Returns audio bytes (mp3) or None.
    Requires USE_AZURE_SPEECH=1, AZURE_SPEECH_KEY, AZURE_SPEECH_REGION.
    Optionally respects AZURE_SPEECH_ENDPOINT.
    """
    if os.getenv("USE_AZURE_SPEECH", "0") != "1":
        print("[TTS][azure] skipped (USE_AZURE_SPEECH!=1)")
        return None
    key = (os.getenv("AZURE_SPEECH_KEY") or os.getenv("AZURE_TTS_KEY") or "").strip()
    region = (os.getenv("AZURE_SPEECH_REGION") or os.getenv("AZURE_TTS_REGION") or "").strip()
    if not key or not region:
        print("[TTS][azure] missing key or region")
        return None
    try:
        import azure.cognitiveservices.speech as speechsdk  # type: ignore
    except Exception as e:
        try:
            import sys
            print(f"[TTS] Azure import failed: {e} (exe={sys.executable})")
            print(f"[TTS] sys.path sample: {sys.path[:5]}")
        except Exception:
            print(f"[TTS] Azure import failed: {e}")
        return None

    try:
        endpoint = (os.getenv("AZURE_SPEECH_ENDPOINT") or "").strip()
        if endpoint:
            speech_config = speechsdk.SpeechConfig(subscription=key, endpoint=endpoint)
        else:
            speech_config = speechsdk.SpeechConfig(subscription=key, region=region)
        voice = (
            voice_name
            or os.getenv("AZURE_SPEECH_VOICE")
            or os.getenv("AZURE_SPEECH_VOICE_ID")
            or "en-US-JennyNeural"
        )
        # Debug: Azure synthesis start
        # print(
        #     "[TTS][azure] synthesizing "
        #     f"(region={region}, endpoint={'set' if endpoint else 'default'}, voice={voice}, key={_mask_secret(key)})"
        # )
        speech_config.speech_synthesis_voice_name = voice
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        # Use None to avoid needing speaker activation; we only want in-memory bytes
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(transcript).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            # Debug: Azure synthesis success
            # print(f"[TTS][azure] success (bytes={len(result.audio_data) if result.audio_data else 0})")
            return bytes(result.audio_data)
        # Handle cancellations/errors without assuming error_details attribute exists
        if getattr(result, "reason", None) == speechsdk.ResultReason.Canceled:
            cd = getattr(result, "cancellation_details", None)
            err = getattr(cd, "error_details", None) if cd else None
            reason = getattr(cd, "reason", None)
            # Debug: Azure canceled
            # print(f"[TTS][azure] canceled (reason={reason}, error={err})")
        else:
            detail = getattr(result, "error_details", None)
            print(f"[TTS][azure] failed (reason={getattr(result, 'reason', None)}, error={detail})")
    except Exception as e:
        print(f"[TTS][azure] error: {e}")
        return None


# OpenAI ChatGPT TTS supported voices (as of 2025-09)
_VALID_CHATGPT_VOICES = {
    "alloy",
    "breeze",
    "echo",
    "verse",
    "shimmer",
    "onyx",
    "coral",
    "amber",
}


def _tts_generation_timeout_seconds() -> int | None:
    raw = (os.getenv("TTS_GENERATION_TIMEOUT_SECONDS") or "").strip()
    if not raw:
        return 180
    try:
        val = int(raw)
    except Exception:
        return 180
    return None if val <= 0 else val


def _generate_podcast_audio_for_voice_sync(
    transcript: str,
    user_id: int,
    filename: str = "kickoff.mp3",
    voice_override: Optional[str] = None,
    voice_role: Optional[str] = None,
    return_bytes: bool = False,
    usage_tag: Optional[str] = None,
    usage_meta: Optional[dict] = None,
) -> str | None | tuple[str | None, bytes | None]:
    """
    Generate audio for a given transcript, optionally forcing a specific voice.
    - Defaults to OpenAI TTS (ChatGPT). If USE_ELEVENLABS=1 and ELEVENLABS_API_KEY is set,
      will try ElevenLabs first, otherwise stays on OpenAI.
    - voice_role: None|\"male\"|\"female\" to bias selection toward gendered voices via env.
    Saves to public/reports/<user_id>/<filename> and returns the public URL or None.
    If return_bytes=True, also returns audio bytes as a tuple (url, bytes).
    """
    if not transcript or not str(transcript).strip():
        print(f"[TTS] skip empty transcript for user={user_id}, file={filename}")
        return None if not return_bytes else (None, None)

    audio_bytes = None
    used_provider = None
    azure_voice, chatgpt_voice, el_voice = _select_voice_choices(user_id, voice_role, voice_override)
    use_el = os.getenv("USE_ELEVENLABS", "0") == "1"

    # Try Azure Speech first when enabled
    audio_bytes = _tts_via_azure(transcript, azure_voice)
    if audio_bytes:
        used_provider = f"azure:{azure_voice}"
        print(f"[TTS] used Azure Speech (voice={azure_voice}, bytes={len(audio_bytes) if audio_bytes else 0})")

    # Always sanitize ChatGPT voice before calling OpenAI TTS.
    if chatgpt_voice not in _VALID_CHATGPT_VOICES:
        pref = _voice_pref_for_user(user_id)
        chatgpt_male = os.getenv("GPT_VOICE_MALE", "echo")
        chatgpt_female = os.getenv("GPT_VOICE_FEMALE", "shimmer")
        chatgpt_default = os.getenv("GPT_VOICE_DEFAULT", "alloy")
        if pref == "male":
            chatgpt_voice = chatgpt_male
        elif pref == "female":
            chatgpt_voice = chatgpt_female
        else:
            chatgpt_voice = chatgpt_default

    # Try ElevenLabs if explicitly enabled
    if audio_bytes is None and use_el:
        el_key = (os.getenv("ELEVENLABS_API_KEY") or "").strip()
        model_id = os.getenv("ELEVENLABS_MODEL_ID") or os.getenv("elevenlabs_model_id") or "eleven_turbo_v2"
        if el_key:
            try:
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{el_voice}"
                headers = {
                    "xi-api-key": el_key,
                    "Content-Type": "application/json",
                }
                payload = {
                    "text": transcript,
                    "model_id": model_id,
                    "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
                }
                resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
                resp.raise_for_status()
                audio_bytes = resp.content
            except Exception as e:
                print(f"[TTS] ElevenLabs failed: {e}")
                audio_bytes = None
            else:
                used_provider = f"elevenlabs:{el_voice}"
                print(f"[TTS] used ElevenLabs (voice={el_voice}, bytes={len(audio_bytes) if audio_bytes else 0})")

    # Default: OpenAI TTS
    if audio_bytes is None:
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not set")
            client = OpenAI(api_key=api_key)
            resp = client.audio.speech.create(
                model="gpt-4o-mini-tts",
                voice=chatgpt_voice,
                input=transcript,
            )
            audio_bytes = resp.read()
            used_provider = f"openai:{chatgpt_voice}"
            print(f"[TTS] used OpenAI TTS (voice={chatgpt_voice}, bytes={len(audio_bytes) if audio_bytes else 0})")
        except Exception as e:
            print(f"[TTS] OpenAI TTS failed: {e}")
            audio_bytes = None

    if not audio_bytes:
        print(f"[TTS] no audio produced (provider={used_provider}, user={user_id}, file={filename})")
        return None if not return_bytes else (None, None)

    try:
        provider_name = None
        model_name = None
        if used_provider:
            parts = used_provider.split(":", 1)
            provider_name = parts[0]
            model_name = parts[1] if len(parts) > 1 else None
        tag = usage_tag or _guess_usage_tag(filename)
        meta = {
            "filename": filename,
            "bytes": len(audio_bytes) if audio_bytes else 0,
            "voice": model_name,
        }
        if usage_meta:
            meta.update(usage_meta)
        log_usage_event(
            user_id=user_id,
            provider=provider_name or "unknown",
            product="tts",
            model=model_name,
            units=float(len(transcript)),
            unit_type="tts_chars",
            tag=tag,
            meta=meta,
        )
    except Exception as e:
        print(f"[usage] tts log failed: {e}")

    try:
        upload_url = (os.getenv("REPORTS_UPLOAD_URL") or "").strip()
        upload_token = (os.getenv("REPORTS_UPLOAD_TOKEN") or "").strip()
        if upload_url and upload_token:
            try:
                payload = {
                    "user_id": int(user_id),
                    "filename": filename,
                    "content_b64": base64.b64encode(audio_bytes).decode("ascii"),
                }
                resp = requests.post(
                    upload_url,
                    json=payload,
                    headers={"X-Reports-Token": upload_token},
                    timeout=60,
                )
                if resp.ok:
                    data = resp.json() if resp.content else {}
                    url = data.get("url")
                    if url:
                        if return_bytes:
                            return url, audio_bytes
                        return url
                else:
                    print(f"[TTS] upload failed: {resp.status_code} {resp.text[:200]}")
            except Exception as e:
                print(f"[TTS] upload error: {e}")

        reports_root = _reports_root_for_user(user_id)
        os.makedirs(reports_root, exist_ok=True)
        out_path = os.path.join(reports_root, filename)
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        # Lazy import to avoid circular dependency
        from .api import _public_report_url  # type: ignore
        url = _public_report_url(user_id, filename)
        if return_bytes:
            return url, audio_bytes
        return url
    except Exception as e:
        print(f"[TTS] failed to write audio file: {e}")
        return None if not return_bytes else (None, None)


def generate_podcast_audio_for_voice(
    transcript: str,
    user_id: int,
    filename: str = "kickoff.mp3",
    voice_override: Optional[str] = None,
    voice_role: Optional[str] = None,
    return_bytes: bool = False,
    usage_tag: Optional[str] = None,
    usage_meta: Optional[dict] = None,
) -> str | None | tuple[str | None, bytes | None]:
    """
    Generate audio for a given transcript, optionally forcing a specific voice.
    Uses a configurable timeout to avoid blocking long-running jobs.
    Set TTS_GENERATION_TIMEOUT_SECONDS=0 to disable the timeout.
    """
    timeout_s = _tts_generation_timeout_seconds()
    if timeout_s is None:
        return _generate_podcast_audio_for_voice_sync(
            transcript=transcript,
            user_id=user_id,
            filename=filename,
            voice_override=voice_override,
            voice_role=voice_role,
            return_bytes=return_bytes,
            usage_tag=usage_tag,
            usage_meta=usage_meta,
        )
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _generate_podcast_audio_for_voice_sync,
            transcript,
            user_id,
            filename,
            voice_override,
            voice_role,
            return_bytes,
            usage_tag,
            usage_meta,
        )
        try:
            return future.result(timeout=timeout_s)
        except FutureTimeout:
            print(f"[TTS] generation timed out after {timeout_s}s (user={user_id}, file={filename})")
            return None if not return_bytes else (None, None)


def generate_podcast_audio(
    transcript: str,
    user_id: int,
    filename: str = "kickoff.mp3",
    usage_tag: Optional[str] = None,
) -> str | None:
    """Backward-compatible wrapper using the user’s preferred voice."""
    return generate_podcast_audio_for_voice(
        transcript=transcript,
        user_id=user_id,
        filename=filename,
        voice_override=None,
        return_bytes=False,
        usage_tag=usage_tag,
    )


def _guess_usage_tag(filename: str | None) -> str | None:
    if not filename:
        return None
    low = filename.lower()
    if any(key in low for key in ["monday", "weekstart", "thursday", "friday", "kickoff"]):
        return "weekly_flow"
    if "assessment" in low:
        return "assessment"
    if "content-gen" in low:
        return "content_generation"
    if "prompt-test" in low:
        return "prompt_test"
    return "other"


__all__ = ["generate_podcast_audio"]
