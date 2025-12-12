#!/usr/bin/env python3
"""
Quick Azure Speech TTS probe.
Loads .env, attempts synthesis with current env vars, and writes an mp3 for inspection.

Usage:
  python scripts/test_azure_tts.py --text "hello world" --out /tmp/azure_test.mp3
Env needed:
  AZURE_SPEECH_KEY, AZURE_SPEECH_REGION
Optional:
  AZURE_SPEECH_ENDPOINT, AZURE_SPEECH_VOICE (or *_MALE/_FEMALE via user pref; here we just use the env)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None  # type: ignore

# Load .env early
if load_dotenv is not None:
    load_dotenv(override=True)


def mask(s: str) -> str:
    if not s:
        return ""
    if len(s) <= 6:
        return "***"
    return s[:3] + "***" + s[-3:]


def synthesize(text: str, out_path: Path) -> bool:
    try:
        import azure.cognitiveservices.speech as speechsdk  # type: ignore
    except Exception as e:
        print(f"[fail] Azure SDK import failed: {e}")
        return False

    key = (os.getenv("AZURE_SPEECH_KEY") or "").strip()
    region = (os.getenv("AZURE_SPEECH_REGION") or "").strip()
    endpoint = (os.getenv("AZURE_SPEECH_ENDPOINT") or "").strip()
    voice = (
        os.getenv("AZURE_SPEECH_VOICE")
        or os.getenv("AZURE_SPEECH_VOICE_FEMALE")
        or "en-US-JennyNeural"
    )
    if not key or not region:
        print("[fail] Missing AZURE_SPEECH_KEY or AZURE_SPEECH_REGION.")
        return False

    print(f"[info] region={region} endpoint={'set' if endpoint else 'default'} voice={voice} key={mask(key)}")

    try:
        speech_config = (
            speechsdk.SpeechConfig(subscription=key, endpoint=endpoint)
            if endpoint
            else speechsdk.SpeechConfig(subscription=key, region=region)
        )
        speech_config.speech_synthesis_voice_name = voice
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio16Khz32KBitRateMonoMp3
        )
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        result = synthesizer.speak_text_async(text).get()
        if result.reason == speechsdk.ResultReason.SynthesizingAudioCompleted:
            audio = bytes(result.audio_data)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(audio)
            print(f"[ok] Azure TTS success. Wrote {len(audio)} bytes to {out_path}")
            return True
        if getattr(result, "reason", None) == speechsdk.ResultReason.Canceled:
            cd = getattr(result, "cancellation_details", None)
            err = getattr(cd, "error_details", None) if cd else None
            reason = getattr(cd, "reason", None)
            print(f"[fail] Azure canceled. reason={reason} error={err}")
        else:
            detail = getattr(result, "error_details", None)
            print(f"[fail] Azure failed. reason={getattr(result, 'reason', None)} error={detail}")
    except Exception as e:
        print(f"[fail] Azure synthesis error: {e}")
    return False


def main():
    ap = argparse.ArgumentParser(description="Test Azure Speech TTS with current env vars.")
    ap.add_argument("--text", default="Hello from Azure Speech TTS probe.", help="Text to synthesize.")
    ap.add_argument("--out", default="/tmp/azure_test.mp3", help="Output path for mp3.")
    args = ap.parse_args()

    success = synthesize(args.text, Path(args.out))
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
