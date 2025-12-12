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


def handle(user: User, body: str) -> None:
    """
    Handle the coachmycoach command.
    - "coachmycoach" -> show current note/voice and instructions
    - "coachmycoach clear" -> remove note
    - "coachmycoach male|female" -> set podcast voice preference
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
        reply += "\n\nSend 'coachmycoach <note>' to set a note, 'coachmycoach clear' to remove it, or 'coachmycoach male' / 'coachmycoach female' to set the podcast voice."
        send_whatsapp(to=user.phone, text=reply)
