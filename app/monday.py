"""
Monday kickoff touchpoint (podcast + support): proposal → support.
"""
from __future__ import annotations

import json
from typing import Optional
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .db import SessionLocal
from .nudges import send_whatsapp
from .models import User, UserPreference, WeeklyFocus, WeeklyFocusKR, OKRKeyResult, OKRObjective
from .focus import select_top_krs_for_user
from . import llm as shared_llm
from .kickoff import generate_kickoff_podcast_transcript, COACH_NAME
from .podcast import generate_podcast_audio
from .prompts import weekstart_actions_prompt, weekstart_support_prompt


def _current_focus_pillar(user: User) -> Optional[str]:
    """
    Infer the current pillar from the most recent WeeklyFocus and its top KR.
    """
    with SessionLocal() as s:
        wf = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id)
            .order_by(WeeklyFocus.starts_on.desc())
            .first()
        )
        if not wf:
            return None
        wfk = (
            s.query(WeeklyFocusKR)
            .filter(WeeklyFocusKR.weekly_focus_id == wf.id)
            .order_by(WeeklyFocusKR.priority_order.asc())
            .first()
        )
        if not wfk:
            return None
        kr = s.query(OKRKeyResult).get(getattr(wfk, "kr_id", None))
        if not kr:
            return None
        obj = s.query(OKRObjective).get(getattr(kr, "objective_id", None))
        if not obj:
            return None
        return (getattr(obj, "pillar_key", None) or "").lower() or None


def _send_weekly_briefing(user: User, week_no: int) -> tuple[Optional[str], Optional[str]]:
    """Generate and send a short audio briefing for the weekly kickoff. Returns (audio_url, transcript)."""
    transcript = None
    audio_url = None
    pillar_key = _current_focus_pillar(user)
    try:
        transcript = generate_kickoff_podcast_transcript(
            user.id,
            coach_name=COACH_NAME,
            mode="weekstart",
            focus_pillar=pillar_key,
            week_no=week_no,
        )
        audio_url = generate_podcast_audio(transcript, user.id, filename=f"monday_week{week_no}.mp3")
        if audio_url:
            send_whatsapp(
                to=user.phone,
                text=f"*Monday* Hi { (user.first_name or '').strip().title() or 'there' }. {COACH_NAME} here. Here’s your Week {week_no} podcast—please have a listen: {audio_url}",
            )
    except Exception:
        pass
    return audio_url, transcript


def _summarize_actions(transcript: Optional[str], krs: list[OKRKeyResult]) -> str:
    """Summarize 2-3 actions from the podcast transcript; fallback to KR-based tips."""
    transcript = (transcript or "").strip()
    client = getattr(shared_llm, "_llm", None)
    if client and transcript:
        prompt = weekstart_actions_prompt(transcript, [kr.description for kr in krs])
        try:
            resp = client.invoke(prompt)
            txt = (getattr(resp, "content", "") or "").strip()
            if txt:
                txt = txt.replace("(i)", "").replace("( i )", "").strip()
                if "as per the podcast" not in txt.lower():
                    txt = "As per the podcast, here are practical actions for this week:\n" + txt
                # Keep a single closing invite, no extra follow-up questions
                txt = txt.strip()
                if "ask any questions" not in txt.lower():
                    txt = txt.rstrip() + "\nLet me know if you want to adjust anything or need a quick tip."
                return txt
        except Exception:
            pass
    # fallback
    bullets = ["As per the podcast, here are practical actions for this week:"]
    for kr in krs[:3]:
        bullets.append(f"- {kr.description}: take one simple step toward the target this week.")
    bullets.append("Please ask any questions you have about the podcast or plan.")
    return "\n".join(bullets)


def _fmt_num(val) -> str:
    try:
        f = float(val)
        return str(int(f)) if f.is_integer() else str(f).rstrip("0").rstrip(".")
    except Exception:
        return str(val) if val is not None else ""


def _state_key() -> str:
    return "weekstart_state"


def _get_state(session: Session, user_id: int) -> Optional[dict]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == _state_key())
        .one_or_none()
    )
    if not pref or not pref.value:
        return None
    try:
        return json.loads(pref.value)
    except Exception:
        return None


def _set_state(session: Session, user_id: int, state: Optional[dict]):
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == _state_key())
        .one_or_none()
    )
    if state is None:
        if pref:
            session.delete(pref)
        return
    data = json.dumps(state)
    if pref:
        pref.value = data
    else:
        session.add(UserPreference(user_id=user_id, key=_state_key(), value=data))


def has_active_state(user_id: int) -> bool:
    with SessionLocal() as s:
        st = _get_state(s, user_id)
        return bool(st)


def _format_krs(krs: list[OKRKeyResult]) -> str:
    lines = []
    for idx, kr in enumerate(krs, 1):
        tgt = _fmt_num(kr.target_num)
        act = _fmt_num(kr.actual_num)
        bits = []
        if tgt:
            bits.append(f"target {tgt}")
        if act:
            bits.append(f"now {act}")
        suffix = f" ({'; '.join(bits)})" if bits else ""
        lines.append(f"{idx}) {kr.description}{suffix}")
    return "\n".join(lines)


def _support_prompt(krs: list[OKRKeyResult], history: list[dict], user_message: str | None, user: User) -> str:
    payload = [
        {"description": kr.description, "target": _fmt_num(kr.target_num), "actual": _fmt_num(kr.actual_num)}
        for kr in krs
    ]
    transcript = []
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role and content:
            transcript.append(f"{role.upper()}: {content}")
    if user_message:
        transcript.append(f"USER: {user_message}")
    return weekstart_support_prompt(payload, transcript, COACH_NAME, user_name=(user.first_name or ""))


def _support_conversation(
    krs: list[OKRKeyResult],
    history: list[dict],
    user_message: str | None,
    user: User,
    debug: bool = False,
) -> tuple[str, list[dict]]:
    """Generate the next support message and updated history."""
    client = getattr(shared_llm, "_llm", None)
    prompt = _support_prompt(krs, history, user_message, user)
    if debug:
        try:
            send_whatsapp(to=user.phone, text="(i Inst) " + prompt)
        except Exception:
            pass
    text = None
    if client:
        try:
            resp = client.invoke(prompt)
            candidate = (getattr(resp, "content", None) or "").strip()
            if candidate:
                text = "(i) " + candidate
        except Exception:
            text = None
    if text is None:
        if user_message:
            text = "(i) Thanks for the update. Want a quick idea for the next step on any goal? Tell me which one, and I’ll keep it simple."
        else:
            tips = [
                f"{kr.description}: quick plan or light scheduling idea for this week."
                for kr in krs
            ]
            text = "(i) Here are ideas to help this week: " + " ".join(tips)

    new_history = list(history)
    if user_message:
        new_history.append({"role": "user", "content": user_message})
    new_history.append({"role": "assistant", "content": text})
    return text, new_history


def _initial_message(user: User, wf: WeeklyFocus, krs: list[OKRKeyResult]) -> str:
    name = (getattr(user, "first_name", None) or "there").strip().title()
    start_str = ""
    if wf and wf.starts_on:
        day = wf.starts_on.day
        suffix = "th" if 11 <= day <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")
        start_str = f"{wf.starts_on.strftime('%A')} {day}{suffix} {wf.starts_on.strftime('%B')}"
    return (
        f"*Monday* Hi {name}, I’m {COACH_NAME}, your wellbeing coach—this sets your Nutrition key results for the week and offers ideas to make them doable.\n"
        f"For the week starting on {start_str or 'next week'}, I’ve reviewed your objectives and prioritised these KRs based on relative score and importance:\n"
        f"\n{_format_krs(krs)}\n\n"
        "Type **All ok** to continue, or tell me how you’d like support this week."
    )


def _summary_message(krs: list[OKRKeyResult]) -> str:
    return "Agreed KRs for this week:\n" + _format_krs(krs)


def start_kickoff(user: User, notes: str | None = None, debug: bool = False, set_state: bool = True, week_no: Optional[int] = None) -> None:
    """Create weekly focus, pick KRs, send monday message, and optionally set state."""
    with SessionLocal() as s:
        selected = select_top_krs_for_user(s, user.id, limit=None, week_no=week_no)
        kr_ids = [kr_id for kr_id, _ in selected]
        if not kr_ids:
            send_whatsapp(to=user.phone, text="No active KRs found to propose. Please set OKRs first.")
            return

        today = datetime.utcnow().date()
        days_ahead = 7 - today.weekday()
        start = today + timedelta(days=days_ahead)
        end = start + timedelta(days=6)
        wf = WeeklyFocus(user_id=user.id, starts_on=start, ends_on=end, notes=notes)
        s.add(wf); s.flush()
        for idx, kr_id in enumerate(kr_ids):
            s.add(WeeklyFocusKR(weekly_focus_id=wf.id, kr_id=kr_id, priority_order=idx, role="primary" if idx == 0 else "secondary"))
        s.commit()

        krs = s.query(OKRKeyResult).filter(OKRKeyResult.id.in_(kr_ids)).all()

        # Decide week number label
        label_week = week_no
        if label_week is None:
            try:
                label_week = max(1, int(((start - today).days // 7) + 1))
            except Exception:
                label_week = 1

        _send_weekly_briefing(user, week_no=label_week)
        summary = _summarize_actions("", krs)
        if summary and not summary.lower().startswith("*monday*"):
            summary = "*Monday* " + summary
        send_whatsapp(
            to=user.phone,
            text=summary,
        )

        if set_state:
            _set_state(s, user.id, {"mode": "support", "wf_id": wf.id, "kr_ids": kr_ids, "history": [], "debug": debug})
            s.commit()


def handle_message(user: User, text: str) -> None:
    msg = (text or "").strip()
    lower = msg.lower()
    with SessionLocal() as s:
        state = _get_state(s, user.id)

        if lower.startswith("mondaydebug"):
            _set_state(s, user.id, None); s.commit()
            start_kickoff(user, debug=True, set_state=True, week_no=None)
            return
        if lower.startswith("monday") or state is None:
            _set_state(s, user.id, None); s.commit()
            start_kickoff(user, debug=False, set_state=True, week_no=None)
            return

        if state is None:
            send_whatsapp(to=user.phone, text="Say monday to start your weekly focus.")
            return

        wf = s.query(WeeklyFocus).get(state.get("wf_id"))
        wkrs = (
            s.query(WeeklyFocusKR, OKRKeyResult)
             .join(OKRKeyResult, WeeklyFocusKR.kr_id == OKRKeyResult.id)
             .filter(WeeklyFocusKR.weekly_focus_id == wf.id)
             .order_by(WeeklyFocusKR.priority_order.asc())
             .all()
        )
        ordered_ids = state.get("kr_ids") or [kr.id for _, kr in wkrs]
        krs_lookup = {kr.id: kr for _, kr in wkrs}
        krs = [krs_lookup[kid] for kid in ordered_ids if kid in krs_lookup]
        kr_ids = [kr.id for kr in krs]

        mode = state.get("mode")
        debug = bool(state.get("debug"))

        if mode == "proposal":
            if lower.startswith("review"):
                send_whatsapp(to=user.phone, text="We’re keeping the Nutrition goals as-is for this week. Let’s focus on making them doable.")
            support_text, history = _support_conversation(krs, [], msg, user, debug)
            if support_text and not support_text.lower().startswith("*monday*"):
                support_text = "*Monday* " + support_text
            send_whatsapp(to=user.phone, text=support_text)
            _send_weekly_briefing(user)
            _set_state(s, user.id, {"mode": "support", "wf_id": wf.id, "kr_ids": kr_ids, "history": history, "debug": debug})
            s.commit()
            return

        if mode == "support":
            history = state.get("history") or []
            support_text, new_history = _support_conversation(krs, history, msg, user, debug)
            if support_text and not support_text.lower().startswith("*monday*"):
                support_text = "*Monday* " + support_text
            send_whatsapp(to=user.phone, text=support_text)
            _set_state(s, user.id, {"mode": "support", "wf_id": wf.id, "kr_ids": kr_ids, "history": new_history, "debug": debug})
            s.commit()
            return

        _set_state(s, user.id, None); s.commit()
        send_whatsapp(to=user.phone, text="Session reset. Say monday to start your weekly focus.")
