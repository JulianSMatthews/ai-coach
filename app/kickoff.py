"""
Kickoff touchpoint flow (proposal → review → confirmation + support offers).
Self-contained: handles outbound message generation and inbound replies.
"""
from __future__ import annotations

import json
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from .db import SessionLocal
from .nudges import send_whatsapp
from .models import (
    User,
    UserPreference,
    WeeklyFocus,
    WeeklyFocusKR,
    OKRKeyResult,
    AssessmentRun,
    PillarResult,
    OKRObjective,
    PsychProfile,
)
from .focus import select_top_krs_for_user
from . import llm as shared_llm
from .reporting import _reports_root_for_user
from .prompts import (
    podcast_prompt,
    coach_block,
    user_block,
    context_block,
    okr_block,
    scores_block,
    habit_readiness_block,
    task_block,
    assemble_prompt,
)
import os
from .podcast import generate_podcast_audio

COACH_NAME = os.getenv("COACH_NAME", "Gia")


def _fmt_num(val) -> str:
    try:
        f = float(val)
        return str(int(f)) if f.is_integer() else str(f).rstrip("0").rstrip(".")
    except Exception:
        return str(val) if val is not None else ""


def _latest_assessment(user_id: int) -> tuple[Optional[AssessmentRun], List[PillarResult]]:
    with SessionLocal() as s:
        run = (
            s.query(AssessmentRun)
            .filter(AssessmentRun.user_id == user_id)
            .order_by(AssessmentRun.id.desc())
            .first()
        )
        if not run:
            return None, []
        pillars = (
            s.query(PillarResult)
            .filter(PillarResult.run_id == run.id)
            .order_by(PillarResult.id.asc())
            .all()
        )
        return run, pillars


def _latest_psych(user_id: int) -> Optional[PsychProfile]:
    with SessionLocal() as s:
        return (
            s.query(PsychProfile)
            .filter(PsychProfile.user_id == user_id)
            .order_by(PsychProfile.completed_at.desc().nullslast(), PsychProfile.id.desc())
            .first()
        )


def _okr_by_pillar(user_id: int) -> Dict[str, List[OKRKeyResult]]:
    with SessionLocal() as s:
        objs = (
            s.query(OKRObjective)
            .filter(OKRObjective.owner_user_id == user_id)
            .all()
        )
        by_pillar: Dict[str, List[OKRKeyResult]] = {}
        for obj in objs:
            krs = (
                s.query(OKRKeyResult)
                .filter(OKRKeyResult.objective_id == obj.id, OKRKeyResult.status == "active")
                .all()
            )
            if not krs:
                continue
            by_pillar.setdefault(obj.pillar_key, []).extend(krs)
        return by_pillar


def _programme_blocks(start: Optional[datetime]) -> List[Dict[str, str]]:
    pillars = [("nutrition", "Nutrition"), ("recovery", "Recovery"), ("training", "Training"), ("resilience", "Resilience")]
    base = start.date() if start else datetime.utcnow().date()
    blocks = []
    for idx, (key, label) in enumerate(pillars):
        blk_start = base + timedelta(days=idx * 21)
        blk_end = blk_start + timedelta(days=20)
        blocks.append({
            "pillar_key": key,
            "label": label,
            "window": f"Weeks {idx*3+1}–{idx*3+3}",
            "dates": f"{blk_start.strftime('%d %b %Y')} – {blk_end.strftime('%d %b %Y')}",
        })
    return blocks


def generate_kickoff_podcast_transcript(
    user_id: int,
    coach_name: str = COACH_NAME,
    mode: str = "kickoff",
    focus_pillar: str | None = None,
    week_no: int | None = None,
) -> str:
    """
    Build a personalised kickoff transcript. Uses LLM when available; otherwise returns a concise fallback.
    """
    run, pillars = _latest_assessment(user_id)
    user: Optional[User] = None
    with SessionLocal() as s:
        user = s.query(User).get(user_id)
    name = (getattr(user, "first_name", "") or "").strip() or "there"
    psych = _latest_psych(user_id)
    psych_payload: Dict[str, Any] = {}
    if psych:
        psych_payload = {
            "section_averages": getattr(psych, "section_averages", None),
            "flags": getattr(psych, "flags", None),
            "parameters": getattr(psych, "parameters", None),
        }
    scores = [
        {
            "pillar": getattr(p, "pillar_key", ""),
            "score": int(getattr(p, "overall", 0) or 0),
        }
        for p in pillars
    ]
    programme = _programme_blocks(getattr(run, "started_at", None) or getattr(run, "created_at", None))
    first_block = programme[0] if programme else None
    current_block = None
    if programme:
        if week_no and week_no > 0:
            block_idx = min(len(programme) - 1, max(0, (week_no - 1) // 3))
            current_block = programme[block_idx]
        else:
            current_block = first_block
    okrs = _okr_by_pillar(user_id)
    llm_client = getattr(shared_llm, "_llm", None)

    if llm_client:
        okr_payload = {pillar: [kr.description for kr in krs] for pillar, krs in okrs.items()}
        blocks = [
            coach_block(coach_name),
            user_block(name),
            context_block("weekstart" if mode == "weekstart" else "kickoff", "podcast intro", timeframe=str(first_block or programme)),
            okr_block(okr_payload),
            scores_block(scores),
            habit_readiness_block(psych_payload),
        ]
        if mode == "weekstart":
            pillar_label = (focus_pillar or (current_block or {}).get("label") or "current pillar").title()
            window = (current_block or {}).get("window") or ""
            within_block = None
            if week_no and week_no > 0:
                within_block = ((week_no - 1) % 3) + 1
            week_hint = f" (Week {week_no})" if week_no else ""
            descr = (
                f"Create a 1–2 minute weekly audio brief for the {pillar_label} block"
                f"{' ' + window if window else ''}{week_hint}; explain why each KR matters and give 2–3 practical suggestions for this specific week."
            )
            constraints = "No music/SFX; no section headers; natural flow; make tips feel fresh for this week, not a repeat of prior weeks."
            if within_block:
                constraints += f" Tailor guidance to week {within_block} of this 3-week block."
            blocks.append(task_block(descr, constraints=constraints))
        else:
            blocks.append(
                task_block(
                    "Create a 2–3 minute kickoff audio intro covering welcome, assessment summary, habit readiness summary, 12-week plan overview (3-week blocks), KR highlights, weekly expectations, and a motivational close.",
                    constraints="No music/SFX; no section headers; natural flow.",
                )
            )
        prompt = assemble_prompt(blocks)
        try:
            resp = llm_client.invoke(prompt)
            transcript = (getattr(resp, "content", None) or "").strip()
            if transcript:
                return transcript
        except Exception:
            pass

    # Fallback transcript
    parts = []
    parts.append(f"Hi {name}, I’m {coach_name}, your HealthSense coach.")
    if mode == "weekstart":
        blk = current_block or first_block
        if blk:
            label = blk.get("label")
            dates = blk.get("dates")
            parts.append(f"This week is part of your {label} block ({dates}).")
        within_block = None
        if week_no and week_no > 0:
            within_block = ((week_no - 1) % 3) + 1
        if okrs:
            pillar_key = (focus_pillar or (blk or {}).get("pillar_key") or "").lower()
            if pillar_key in okrs:
                kr_list = "; ".join(kr.description for kr in okrs[pillar_key][:3])
                parts.append(f"This block’s KRs: {kr_list}.")
        if within_block == 1:
            parts.append("Since this is the first week of the block, start light: swap one processed meal for whole foods, add one extra portion of fruit/veg, and plan one small session.")
        elif within_block == 2:
            parts.append("Mid-block: build on last week—lock in two consistent days for your key habits and add one prep step (shopping or meal prep) to stay on track.")
        elif within_block == 3:
            parts.append("Final week of this block: aim for consistency and a small stretch—keep the basics and choose one extra push (e.g., one more portion or an extra simple meal swap).")
        else:
            parts.append("Let’s keep it simple this week: pick one or two easy actions that move you toward these goals, and I’ll support you along the way.")
    else:
        if scores:
            score_bits = ", ".join(f"{s['pillar'].title()} {s['score']}/100" for s in scores)
            parts.append(f"Your assessment scores: {score_bits}.")
        if psych_payload:
            parts.append("Your habit readiness shows how we’ll tailor support so it matches your pace and preferences.")
        parts.append("Your 12-week plan: three weeks each on Nutrition, Recovery, Training, then Resilience, building step by step.")
        if okrs:
            for pillar, krs in okrs.items():
                kr_list = "; ".join(kr.description for kr in krs[:3])
                parts.append(f"For {pillar.title()}, we’ll focus on: {kr_list}.")
        parts.append("Each week we’ll keep it practical, check in on progress, and adjust together. You’ve got this, and I’m here to help.")
    return " ".join(parts)


def generate_kickoff_podcast_audio(
    user_id: int,
    model: str = "gpt-4o-mini-tts",
    voice: str = "alloy",
    coach_name: str = COACH_NAME,
    mode: str = "kickoff",
    focus_pillar: str | None = None,
    week_no: int | None = None,
) -> tuple[str | None, str]:
    """
    Generate transcript + TTS audio (mp3). Returns (audio_url, transcript).
    If TTS fails, audio_url will be None and transcript is still returned.
    """
    transcript = generate_kickoff_podcast_transcript(
        user_id, coach_name=coach_name, mode=mode, focus_pillar=focus_pillar, week_no=week_no
    )
    audio_url = generate_podcast_audio(transcript, user_id, filename="kickoff.mp3")
    return audio_url, transcript


def _state_key() -> str:
    return "kickoff_state"


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


def _support_prompt(krs: list[OKRKeyResult], history: list[dict], user_message: str | None) -> str:
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
    transcript_str = "\n".join(transcript)
    return (
        "You are a concise wellbeing coach in a kickoff support chat. "
        "Context: the user already completed an assessment; objectives and KRs exist. "
        "These KRs are the agreed focus for this week, and this kickoff is to help them plan and feel supported. "
        "Do NOT assume progress yet; stay focused on planning and making the week doable. "
        "Acknowledge what they just shared, build on it, and avoid repeating the same ask. "
        "Offer 2-3 practical ideas or next steps for this week and feel free to include a couple of follow-ups that logically advance the plan (e.g., which idea they want to try, and whether they need a resource/schedule). "
        "Do not suggest more sessions than the KR targets unless the user asked for it. "
        "Avoid praise, avoid commands, keep it conversational and forward-looking.\n"
        f"KRs: {payload}\n"
        f"Conversation so far:\n{transcript_str}"
    )


def _support_conversation(
    krs: list[OKRKeyResult],
    history: list[dict],
    user_message: str | None,
    user: User,
    debug: bool = False,
) -> tuple[str, list[dict]]:
    """Generate the next support message and updated history."""
    client = getattr(shared_llm, "_llm", None)
    prompt = _support_prompt(krs, history, user_message)
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
            text = "(i) Thanks for the update. Want a quick idea for the next step on any KR? Tell me which one, and I’ll keep it simple."
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
        f"Hi {name}, I’m your wellbeing coach—this kickoff sets your key results for the week and offers ideas to make them doable.\n"
        f"For the week starting on {start_str or 'next week'}, I’ve reviewed your objectives and prioritised these KRs based on relative score and importance:\n"
        f"\n{_format_krs(krs)}\n\n"
        "Type **All ok** to confirm or **review** to modify KRs proposed."
    )


def _summary_message(krs: list[OKRKeyResult]) -> str:
    return "Agreed KRs for this week:\n" + _format_krs(krs)


def start_kickoff(user: User, notes: str | None = None, debug: bool = False) -> None:
    """Create weekly focus, pick KRs, send kickoff message, and set state."""
    with SessionLocal() as s:
        # select KRs
        selected = select_top_krs_for_user(s, user.id, limit=None)
        kr_ids = [kr_id for kr_id, _ in selected]
        if not kr_ids:
            send_whatsapp(to=user.phone, text="No active KRs found to propose. Please set OKRs first.")
            return

        # create weekly focus
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

        # send kickoff
        send_whatsapp(to=user.phone, text=_initial_message(user, wf, krs))

        # set state
        _set_state(s, user.id, {"mode": "proposal", "wf_id": wf.id, "kr_ids": kr_ids, "debug": debug})
        s.commit()


def handle_message(user: User, text: str) -> None:
    msg = (text or "").strip()
    lower = msg.lower()
    with SessionLocal() as s:
        state = _get_state(s, user.id)

        # kickoff keyword starts a new flow
        if lower.startswith("kickoffdebug"):
            _set_state(s, user.id, None); s.commit()
            start_kickoff(user, debug=True)
            return
        if lower.startswith("kickoff") or state is None:
            # start new kickoff
            _set_state(s, user.id, None); s.commit()
            start_kickoff(user, debug=False)
            return

        # if no state after attempt, bail
        if state is None:
            send_whatsapp(to=user.phone, text="Say kickoff to start your weekly focus.")
            return

        # load wf and krs
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

        # proposal phase
        if mode == "proposal":
            if lower.replace(" ", "") in {"allok", "allokay", "allokey"} or lower.strip() == "all ok":
                support_text, history = _support_conversation(krs, [], None, user, debug)
                send_whatsapp(to=user.phone, text=support_text)
                _set_state(s, user.id, {"mode": "support", "wf_id": wf.id, "kr_ids": kr_ids, "history": history, "debug": debug})
                s.commit()
                return
            if lower.startswith("review"):
                _set_state(s, user.id, {"mode": "review", "wf_id": wf.id, "kr_ids": kr_ids, "idx": 0})
                s.commit()
                current = krs[0]
                send_whatsapp(to=user.phone, text=f"Reviewing KR 1/{len(kr_ids)}: {current.description} (target={_fmt_num(current.target_num)}). Reply keep or drop.")
                return
            # unknown input in proposal
            send_whatsapp(to=user.phone, text="Type All ok to confirm or review to modify KRs proposed.")
            return

        # review phase
        if mode == "review":
            idx = state.get("idx", 0)
            kr_id_list = state.get("kr_ids", [])
            if idx >= len(kr_id_list):
                _set_state(s, user.id, None); s.commit()
                send_whatsapp(to=user.phone, text=_summary_message(krs))
                send_whatsapp(to=user.phone, text=_support_offer(krs))
                return
            current_id = kr_id_list[idx]
            current = next((kr for kr in krs if kr.id == current_id), None)
            if not current:
                _set_state(s, user.id, None); s.commit()
                send_whatsapp(to=user.phone, text="No KRs to review. Say kickoff to start again.")
                return
            if "drop" in lower:
                kr_id_list = [kid for kid in kr_id_list if kid != current_id]
                state["kr_ids"] = kr_id_list
            elif "keep" in lower:
                pass
            else:
                send_whatsapp(to=user.phone, text=f"KR {idx+1}/{len(state['kr_ids'])}: {current.description} (target={_fmt_num(current.target_num)}). Reply keep or drop.")
                return
            idx += 1
            if idx >= len(kr_id_list):
                # finalize
                krs_final = [kr for kr in krs if kr.id in kr_id_list]
                support_text, history = _support_conversation(krs_final, [], None, user, debug)
                _set_state(s, user.id, {"mode": "support", "wf_id": wf.id, "kr_ids": kr_id_list, "history": history, "debug": debug}); s.commit()
                send_whatsapp(to=user.phone, text=_summary_message(krs_final))
                send_whatsapp(to=user.phone, text=support_text)
                return
            state["idx"] = idx
            _set_state(s, user.id, state); s.commit()
            nxt = next((kr for kr in krs if kr.id == kr_id_list[idx]), None)
            if nxt:
                send_whatsapp(to=user.phone, text=f"KR {idx+1}/{len(kr_id_list)}: {nxt.description} (target={_fmt_num(nxt.target_num)}). Reply keep or drop.")
            return

        # support phase
        if mode == "support":
            history = state.get("history") or []
            # allow user to end the session explicitly
            support_text, new_history = _support_conversation(krs, history, msg, user, debug)
            send_whatsapp(to=user.phone, text=support_text)
            _set_state(s, user.id, {"mode": "support", "wf_id": wf.id, "kr_ids": kr_ids, "history": new_history, "debug": debug})
            s.commit()
            return

        # fallback
        _set_state(s, user.id, None); s.commit()
        send_whatsapp(to=user.phone, text="Session reset. Say kickoff to start your weekly focus.")
