"""
Thursday educational boost: short podcast/text tied to active goals.
"""
from __future__ import annotations

from pathlib import Path
import os
from .db import SessionLocal
from .nudges import send_whatsapp, send_whatsapp_media
from .models import User
from .kickoff import COACH_NAME
from .prompts import primary_kr_payload, build_prompt, run_llm_prompt
from .podcast import generate_podcast_audio, generate_podcast_audio_for_voice
from .reporting import _reports_root_for_user
from .touchpoints import log_touchpoint


def send_thursday_boost(user: User, coach_name: str = COACH_NAME, week_no: int | None = None) -> None:
    with SessionLocal() as s:
        primary = primary_kr_payload(user.id, session=s, week_no=week_no)
    if not primary:
        send_whatsapp(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
        return
    touchpoint_week_no = week_no

    prompt_assembly = build_prompt(
        "podcast_thursday",
        user_id=user.id,
        coach_name=coach_name,
        user_name=user.first_name or "there",
        locale=getattr(user, "tz", "UK") or "UK",
        week_no=week_no,
    )
    transcript = run_llm_prompt(
        prompt_assembly.text,
        user_id=user.id,
        touchpoint="podcast_thursday",
        context_meta={"week_no": week_no},
        prompt_variant=prompt_assembly.variant,
        task_label=prompt_assembly.task_label,
        prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
        block_order=prompt_assembly.block_order,
        log=True,
    )

    if not transcript:
        tgt = primary["target"] if primary.get("target") is not None else ""
        transcript = (
            f"*Thursday* Hi { (user.first_name or 'there').strip().title() }, here’s a quick boost. "
            f"Focus on this goal: {primary['description']} (target {tgt}). "
            "Try one simple mini-challenge today and keep it light."
        )

    # Split transcript into educational (male voice) and motivational (female voice) parts
    edu_text = transcript
    mot_text = "Keep going—you’ve got this. I’m here if you need a tweak or idea."
    edu_lines, mot_lines = [], []
    current = None
    for line in [ln.strip() for ln in transcript.splitlines() if ln.strip()]:
        lower = line.lower()
        if lower.startswith("education:"):
            current = "edu"
            content = line.split(":", 1)[1].strip()
            if content:
                edu_lines.append(content)
            continue
        if lower.startswith("motivation:"):
            current = "mot"
            content = line.split(":", 1)[1].strip()
            if content:
                mot_lines.append(content)
            continue
        if current == "edu":
            edu_lines.append(line)
        elif current == "mot":
            mot_lines.append(line)
    if edu_lines or mot_lines:
        edu_text = " ".join(edu_lines).strip() or edu_text
        mot_text = " ".join(mot_lines).strip() or mot_text
    else:
        segments = [s.strip() for s in transcript.split(". ") if s.strip()]
        if len(segments) >= 2:
            edu_text = segments[0].rstrip(".") + "."
            mot_text = ". ".join(segments[1:]).rstrip(".") + "."

    fname_suffix = f"_week{touchpoint_week_no}" if touchpoint_week_no else ""
    edu_res = generate_podcast_audio_for_voice(
        edu_text,
        user.id,
        filename=f"thursday_edu{fname_suffix}.mp3",
        voice_role="male",
        return_bytes=True,
    )
    mot_res = generate_podcast_audio_for_voice(
        mot_text,
        user.id,
        filename=f"thursday_mot{fname_suffix}.mp3",
        voice_role="female",
        return_bytes=True,
    )

    combined_url = None
    try:
        edu_bytes = edu_res[1] if isinstance(edu_res, tuple) else None
        mot_bytes = mot_res[1] if isinstance(mot_res, tuple) else None
        if edu_bytes and mot_bytes:
            reports_root = _reports_root_for_user(user.id)
            Path(reports_root).mkdir(parents=True, exist_ok=True)
            out_path = os.path.join(reports_root, f"thursday{fname_suffix}.mp3")
            with open(out_path, "wb") as f:
                f.write(edu_bytes + mot_bytes)
            from .api import _public_report_url  # type: ignore
            combined_url = _public_report_url(user.id, f"thursday{fname_suffix}.mp3")
        elif isinstance(edu_res, tuple):
            combined_url = edu_res[0]
        elif isinstance(edu_res, str):
            combined_url = edu_res
        elif isinstance(mot_res, tuple):
            combined_url = mot_res[0]
        elif isinstance(mot_res, str):
            combined_url = mot_res
    except Exception:
        combined_url = None

    if combined_url:
        message = (
            f"*Thursday* Hi { (user.first_name or '').strip().title() or 'there' }, {coach_name} here. "
            f"Here’s your Thursday boost podcast—give it a quick listen."
        )
        try:
            send_whatsapp_media(to=user.phone, media_url=combined_url, caption=message)
        except Exception:
            send_whatsapp(to=user.phone, text=f"{message} {combined_url}")
    else:
        message = transcript if transcript.startswith("*Thursday*") else f"*Thursday* {transcript}"
        send_whatsapp(to=user.phone, text=message)
    log_touchpoint(
        user_id=user.id,
        tp_type="thursday",
        weekly_focus_id=None,
        week_no=touchpoint_week_no,
        kr_ids=[primary["id"]] if primary else [],
        meta={
            "source": "thursday",
            "week_no": touchpoint_week_no,
            "label": "thursday",
        },
        generated_text=message,
        audio_url=combined_url,
    )
