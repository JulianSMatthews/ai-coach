"""
User-configurable coaching preferences ("coach my coach").
Allows a user to set a brief note that can be used to tailor LLM behaviour.
Invoked via the command: coachmycoach <note text> or coachmycoach clear
"""
from __future__ import annotations

from typing import Optional

from .db import SessionLocal
from .models import User, UserPreference
from .nudges import send_whatsapp


def _note_key() -> str:
    return "coachmycoach_note"


def _voice_key() -> str:
    return "tts_voice_pref"

def _time_key(day: str) -> str:
    return f"coach_schedule_{day.lower()}"


def _get_note(session, user_id: int) -> str:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == _note_key())
        .one_or_none()
    )
    return pref.value if pref and pref.value else ""


def _set_note(session, user_id: int, note: Optional[str]):
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == _note_key())
        .one_or_none()
    )
    if not note:
        if pref:
            session.delete(pref)
        return
    if pref:
        pref.value = note
    else:
        session.add(UserPreference(user_id=user_id, key=_note_key(), value=note))


def _auto_prompt_status(session, user_id: int) -> str:
    """
    Return a human-friendly auto-prompt status for the user.
    Stored in UserPreference.coaching (primary) or legacy auto_daily_prompts: "1"=on, "0"=off, missing=not configured.
    """
    pref = (
        session.query(UserPreference)
        .filter(
            UserPreference.user_id == user_id,
            UserPreference.key.in_(("coaching", "auto_daily_prompts")),
        )
        .order_by(UserPreference.updated_at.desc())
        .first()
    )
    val = (pref.value or "").strip() if pref else ""
    if val == "1":
        return "on"
    if val == "0":
        return "off"
    return "not configured"


def handle(user: User, body: str) -> None:
    """
    Handle the coachmycoach command.
    - "coachmycoach" -> show current note/voice and instructions
    - "coachmycoach clear" -> remove note
    - "coachmycoach male|female" -> set podcast voice preference
    - "coachmycoach time <day> <HH:MM>" -> set daily prompt time for that day
    - "coachmycoach <note>" -> save note
    """
    parts = body.split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    with SessionLocal() as s:
        if arg.lower() == "clear":
            _set_note(s, user.id, None)
            s.commit()
            send_whatsapp(to=user.phone, text="Cleared your coaching preference note.")
            return

        if arg:
            low = arg.lower()
            if low in {"male", "female"}:
                # set voice preference
                pref = (
                    s.query(UserPreference)
                    .filter(UserPreference.user_id == user.id, UserPreference.key == _voice_key())
                    .one_or_none()
                )
                if pref:
                    pref.value = low
                else:
                    s.add(UserPreference(user_id=user.id, key=_voice_key(), value=low))
                s.commit()
                send_whatsapp(
                    to=user.phone,
                    text=f"Set your podcast voice preference to {low}.",
                )
                return
            if low.startswith("time "):
                # Format: coachmycoach time <day> <HH:MM>
                tokens = low.split()
                if len(tokens) != 3:
                    send_whatsapp(
                        to=user.phone,
                        text="Usage: coachmycoach time <day> <HH:MM> (e.g., coachmycoach time monday 08:00)",
                    )
                    return
                _, day, hhmm = tokens
                day = day.lower()
                valid_days = {"monday", "tuesday", "wednesday", "thursday", "friday", "sunday"}
                if day not in valid_days:
                    send_whatsapp(
                        to=user.phone,
                        text=f"Day must be one of: {', '.join(sorted(valid_days))}",
                    )
                    return
                try:
                    hh, mm = hhmm.split(":")
                    hh_int = int(hh); mm_int = int(mm)
                    if not (0 <= hh_int <= 23 and 0 <= mm_int <= 59):
                        raise ValueError()
                except Exception:
                    send_whatsapp(
                        to=user.phone,
                        text="Time must be HH:MM in 24h format (e.g., 08:00 or 19:00).",
                    )
                    return
                pref = (
                    s.query(UserPreference)
                    .filter(UserPreference.user_id == user.id, UserPreference.key == _time_key(day))
                    .one_or_none()
                )
                val = f"{hh_int:02d}:{mm_int:02d}"
                if pref:
                    pref.value = val
                else:
                    s.add(UserPreference(user_id=user.id, key=_time_key(day), value=val))
                s.commit()
                send_whatsapp(
                    to=user.phone,
                    text=f"Set your {day.title()} prompt time to {val} (24h).",
                )
                return
            _set_note(s, user.id, arg)
            s.commit()
            send_whatsapp(
                to=user.phone,
                text=(
                    "Saved your coaching note. I’ll use this to tailor support in future touchpoints.\n"
                    f"Note: {arg}"
                ),
            )
            return

        current = _get_note(s, user.id)
        voice_pref = (
            s.query(UserPreference)
            .filter(UserPreference.user_id == user.id, UserPreference.key == _voice_key())
            .one_or_none()
        )
        vp = voice_pref.value if voice_pref and voice_pref.value else "not set"
        reply = "You don't have a coaching note yet." if not current else f"Your current coaching note:\n{current}"
        reply += f"\n\nVoice preference: {vp}"
        auto_status = _auto_prompt_status(s, user.id)
        reply += f"\nCoaching: {auto_status}"
        # Show any custom prompt times
        times = {}
        for d in ("monday", "tuesday", "wednesday", "thursday", "friday", "sunday"):
            pref = (
                s.query(UserPreference)
                .filter(UserPreference.user_id == user.id, UserPreference.key == _time_key(d))
                .one_or_none()
            )
            if pref and pref.value:
                times[d] = pref.value
        if times:
            pretty = ", ".join(f"{d.title()}: {t}" for d, t in sorted(times.items()))
            reply += f"\n\nCustom prompt times: {pretty}"
        reply += (
            "\n\nSend 'coachmycoach <note>' to set a note, 'coachmycoach clear' to remove it, "
            "'coachmycoach male' / 'coachmycoach female' for voice, or "
            "'coachmycoach time <day> <HH:MM>' to set a daily prompt time. Auto prompts can be turned on/off by your coach."
        )
        send_whatsapp(to=user.phone, text=reply)
