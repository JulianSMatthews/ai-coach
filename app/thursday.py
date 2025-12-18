"""
Thursday educational boost: short podcast/text tied to active goals.
"""
from __future__ import annotations

from typing import Optional
from pathlib import Path
import os
from sqlalchemy.orm import Session

from .db import SessionLocal
from .nudges import send_whatsapp
from .models import WeeklyFocus, WeeklyFocusKR, OKRKeyResult, User
from .kickoff import COACH_NAME
from .prompts import thursday_prompt
from .podcast import generate_podcast_audio, generate_podcast_audio_for_voice
from .reporting import _reports_root_for_user
from . import llm as shared_llm
from .touchpoints import log_touchpoint


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def _pick_primary_kr(session: Session, wf_id: int) -> Optional[OKRKeyResult]:
    row = (
        session.query(WeeklyFocusKR, OKRKeyResult)
        .join(OKRKeyResult, WeeklyFocusKR.kr_id == OKRKeyResult.id)
        .filter(WeeklyFocusKR.weekly_focus_id == wf_id)
        .order_by(WeeklyFocusKR.priority_order.asc())
        .first()
    )
    return row[1] if row else None


def send_thursday_boost(user: User, coach_name: str = COACH_NAME, week_no: int | None = None) -> None:
    with SessionLocal() as s:
        wf = _latest_weekly_focus(s, user.id)
        if not wf:
            send_whatsapp(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
            return
        kr = _pick_primary_kr(s, wf.id)
        if not kr:
            send_whatsapp(to=user.phone, text="No key results found for this week. Say monday to set them up.")
            return

        client = getattr(shared_llm, "_llm", None)
        transcript = None
        if client:
            try:
                prompt = thursday_prompt(
                    coach_name=coach_name,
                    user_name=user.first_name or "there",
                    krs=[{"description": kr.description, "target": kr.target_num, "actual": kr.actual_num}],
                )
                resp = client.invoke(prompt)
                transcript = (getattr(resp, "content", None) or "").strip()
            except Exception:
                transcript = None

        if not transcript:
            tgt = kr.target_num if kr.target_num is not None else ""
            transcript = (
                f"*Thursday* Hi { (user.first_name or 'there').strip().title() }, here’s a quick boost. "
                f"Focus on this goal: {kr.description} (target {tgt}). "
                "Try one simple mini-challenge today and keep it light."
            )

        # Split transcript into educational (male voice) and motivational (female voice) parts
        edu_text = transcript
        mot_text = "Keep going—you’ve got this. I’m here if you need a tweak or idea."
        # Prefer explicit labeled sections from the prompt
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
            # Fallback: simple sentence split
            segments = [s.strip() for s in transcript.split(". ") if s.strip()]
            if len(segments) >= 2:
                edu_text = segments[0].rstrip(".") + "."
                mot_text = ". ".join(segments[1:]).rstrip(".") + "."

        fname_suffix = f"_week{week_no}" if week_no else ""
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

        print(
            f"[TTS-Thursday] male_voice_role=male female_voice_role=female "
            f"edu_res_type={type(edu_res)} mot_res_type={type(mot_res)}"
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
                f"Here’s your Thursday boost podcast—give it a quick listen: {combined_url}"
            )
        else:
            message = transcript if transcript.startswith("*Thursday*") else f"*Thursday* {transcript}"
        send_whatsapp(to=user.phone, text=message)
        log_touchpoint(
            user_id=user.id,
            tp_type="thursday",
            weekly_focus_id=wf.id,
            week_no=getattr(wf, "week_no", None),
            kr_ids=[kr.id] if kr else [],
            meta={"source": "thursday", "week_no": week_no, "label": "thursday"},
            generated_text=message,
            audio_url=combined_url,
        )
