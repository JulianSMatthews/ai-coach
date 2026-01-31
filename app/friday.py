"""
Friday boost: short podcast/message focusing on one KR with a simple action.
"""
from __future__ import annotations

from .db import SessionLocal
from .nudges import send_whatsapp, send_whatsapp_media, append_button_cta
from .models import User
from .kickoff import COACH_NAME
from .prompts import primary_kr_payload, build_prompt, run_llm_prompt
from .podcast import generate_podcast_audio
from .touchpoints import log_touchpoint
from .debug_utils import debug_log
from . import general_support


def send_boost(user: User, coach_name: str = COACH_NAME, week_no: int | None = None) -> None:
    general_support.clear(user.id)
    with SessionLocal() as s:
        primary = primary_kr_payload(user.id, session=s, week_no=week_no)
    if not primary:
        debug_log("friday skipped: no primary KR payload", {"user_id": user.id, "week_no": week_no}, tag="friday")
        send_whatsapp(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
        return
    touchpoint_week_no = week_no

    prompt_assembly = build_prompt(
        "podcast_friday",
        user_id=user.id,
        coach_name=coach_name,
        user_name=user.first_name or "there",
        locale=getattr(user, "tz", "UK") or "UK",
        week_no=week_no,
    )
    transcript = run_llm_prompt(
        prompt_assembly.text,
        user_id=user.id,
        touchpoint="podcast_friday",
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
            f"*Friday* Hi { (user.first_name or 'there').strip().title() }, here’s a quick boost. "
            f"Focus on this goal: {primary['description']} (target {tgt}). "
            "Try one simple step over the next couple of days to stay consistent."
        )

    fname = f"friday_week{touchpoint_week_no}.mp3" if touchpoint_week_no else "friday.mp3"
    audio_url = generate_podcast_audio(transcript, user.id, filename=fname)
    if audio_url:
        print(f"[friday] sending podcast media for user={user.id} url={audio_url}")
        message = (
            f"*Friday* Hi { (user.first_name or '').strip().title() or 'there' }, {coach_name} here. "
            "Here’s your boost podcast—give it a quick listen."
        )
        try:
            send_whatsapp_media(
                to=user.phone,
                media_url=audio_url,
                caption=message,
            )
        except Exception:
            send_whatsapp(
                to=user.phone,
                text=f"{message} {audio_url}",
            )
        checkin = "*Friday* Quick check-in: how does this boost feel for today?"
        send_whatsapp(
            to=user.phone,
            text=append_button_cta(checkin),
            quick_replies=["All good", "Need help"],
        )
    else:
        print(f"[friday] no audio_url for user={user.id}; sending text fallback")
        message = transcript if transcript.startswith("*Friday*") else f"*Friday* {transcript}"
        send_whatsapp(
            to=user.phone,
            text=append_button_cta(message),
            quick_replies=["All good", "Need help"],
        )
    log_touchpoint(
        user_id=user.id,
        tp_type="friday",
        weekly_focus_id=None,
        week_no=touchpoint_week_no,
        kr_ids=[primary["id"]] if primary else [],
        meta={"source": "friday", "week_no": touchpoint_week_no, "label": "friday"},
        generated_text=message,
        audio_url=audio_url,
    )
    general_support.activate(user.id, source="friday", week_no=touchpoint_week_no, send_intro=False)
