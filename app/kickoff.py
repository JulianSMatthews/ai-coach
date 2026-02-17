"""
Kickoff touchpoint: create/reuse Week 1 focus and send a kickoff podcast.
"""
from __future__ import annotations

import json
import re
import os
from typing import Optional, List, Dict, Any
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from .db import SessionLocal
from .job_queue import enqueue_job, should_use_podcast_worker
from .nudges import send_whatsapp, send_whatsapp_media
from .debug_utils import debug_enabled
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
from .programme_timeline import programme_blocks, week_anchor_date
from .reporting import _reports_root_for_user
from .prompts import podcast_prompt, build_prompt, run_llm_prompt, okrs_by_pillar_payload
from .touchpoints import log_touchpoint
from . import general_support
from .podcast import generate_podcast_audio

COACH_NAME = os.getenv("COACH_NAME", "Gia")


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def _podcast_worker_enabled() -> bool:
    return should_use_podcast_worker() and not _in_worker_process()


def _kickoff_label() -> str:
    return "Kickoff." if not _in_worker_process() else "Kickoff"


def _kickoff_tag() -> str:
    return f"*{_kickoff_label()}*"


def _apply_kickoff_marker(text: str | None) -> str | None:
    if not text:
        return text
    if text.startswith("*Kickoff*"):
        return text.replace("*Kickoff*", _kickoff_tag(), 1)
    return text


def _send_kickoff(*, text: str, to: str | None = None, category: str | None = None, quick_replies: list[str] | None = None) -> str:
    return send_whatsapp(
        text=_apply_kickoff_marker(text) or text,
        to=to,
        category=category,
        quick_replies=quick_replies,
    )


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
    src_start = start.date() if start else datetime.utcnow().date()
    blocks = []
    for item in programme_blocks(src_start):
        blk_start = item.get("start")
        blk_end = item.get("end")
        if not isinstance(blk_start, date) or not isinstance(blk_end, date):
            continue
        blocks.append(
            {
                "pillar_key": str(item.get("pillar_key") or ""),
                "label": str(item.get("pillar_label") or ""),
                "window": str(item.get("label") or item.get("week_label") or ""),
                "dates": f"{blk_start.strftime('%d %b %Y')} – {blk_end.strftime('%d %b %Y')}",
            }
        )
    return blocks


def generate_kickoff_podcast_transcript(
    user_id: int,
    coach_name: str = COACH_NAME,
    mode: str = "kickoff",
    focus_pillar: str | None = None,
    week_no: int | None = None,
    locale: str | None = None,
) -> str:
    """
    Build a personalised kickoff transcript. Uses LLM when available; otherwise returns a concise fallback.
    """
    run, pillars = _latest_assessment(user_id)
    user: Optional[User] = None
    with SessionLocal() as s:
        user = s.query(User).get(user_id)
    name = (getattr(user, "first_name", "") or "").strip() or "there"
    # locale currently unused; kept for compatibility/future prompt tweaks
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
    programme = _programme_blocks(
        getattr(run, "finished_at", None)
        or getattr(run, "started_at", None)
        or getattr(run, "created_at", None)
    )
    first_block = programme[0] if programme else None
    current_block = None
    if programme:
        if week_no and week_no > 0:
            block_idx = min(len(programme) - 1, max(0, (week_no - 1) // 3))
            current_block = programme[block_idx]
        else:
            current_block = first_block
    okrs = _okr_by_pillar(user_id)
    okrs_for_prompt = (
        okrs_by_pillar_payload(user_id, week_no=week_no, max_krs=None)
        if mode == "weekstart"
        else {pillar: [kr.description for kr in krs] for pillar, krs in okrs.items()}
    )
    llm_client = getattr(shared_llm, "_llm", None)

    def _trim_to_max_words(text: str, max_words: int) -> str:
        words = (text or "").split()
        if not words or len(words) <= max_words:
            return text
        # Prefer trimming at sentence boundaries while respecting the word cap.
        sentences = re.split(r"(?<=[.!?])\\s+", text.strip())
        trimmed: list[str] = []
        count = 0
        for sentence in sentences:
            if not sentence:
                continue
            sentence_words = sentence.split()
            if count + len(sentence_words) > max_words:
                break
            trimmed.append(sentence.strip())
            count += len(sentence_words)
        if not trimmed:
            trimmed = [" ".join(words[:max_words]).strip()]
        return " ".join(trimmed).strip()

    if llm_client:
        if mode == "weekstart":
            prompt_assembly = build_prompt(
                "podcast_weekstart",
                user_id=user_id,
                coach_name=coach_name,
                user_name=name,
                scores=scores,
                psych_payload=psych_payload,
                programme=programme,
                first_block=first_block,
                week_no=week_no,
                focus_pillar=focus_pillar,
                locale=locale or "UK",
            )
            transcript = run_llm_prompt(
                prompt_assembly.text,
                user_id=user_id,
                touchpoint="podcast_weekstart",
                context_meta={"week_no": week_no, "focus_pillar": focus_pillar},
                prompt_variant=prompt_assembly.variant,
                task_label=prompt_assembly.task_label,
                prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
                block_order=prompt_assembly.block_order,
                log=True,
            )
            if transcript:
                max_words = int(os.getenv("WEEKSTART_PODCAST_MAX_WORDS", "420") or "420")
                return _trim_to_max_words(transcript, max_words)
        else:
            prompt_assembly = build_prompt(
                "podcast_kickoff",
                user_id=user_id,
                coach_name=coach_name,
                user_name=name,
                scores=scores,
                psych_payload=psych_payload,
                programme=programme,
                first_block=first_block,
                okrs_by_pillar={pillar: [kr.description for kr in krs] for pillar, krs in okrs.items()},
                locale=locale or "UK",
            )
            transcript = run_llm_prompt(
                prompt_assembly.text,
                user_id=user_id,
                touchpoint="podcast_kickoff",
                context_meta={"week_no": week_no},
                prompt_variant=prompt_assembly.variant,
                task_label=prompt_assembly.task_label,
                prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
                block_order=prompt_assembly.block_order,
                log=True,
            )
            if transcript:
                return transcript

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
        if okrs_for_prompt:
            pillar_key = (focus_pillar or (blk or {}).get("pillar_key") or "").lower()
            if pillar_key in okrs_for_prompt:
                pillar_krs = okrs_for_prompt[pillar_key]
                kr_list = "; ".join((kr.description if hasattr(kr, "description") else str(kr)) for kr in pillar_krs[:3])
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
    audio_url = generate_podcast_audio(
        transcript,
        user_id,
        filename="kickoff.mp3",
        usage_tag="weekly_flow",
    )
    return audio_url, transcript


def send_kickoff_podcast_message(
    user: User,
    audio_url: str | None,
    coach_name: str = COACH_NAME,
    week_no: int | None = None,
    weekly_focus_id: int | None = None,
    kr_ids: list[int] | None = None,
) -> None:
    """
    Send kickoff podcast link and log touchpoint (used by automated weekflow kickoff).
    """
    quick_replies = ["All good", "Need help"]
    cta = "Please always respond by tapping a button (this keeps our support going)."
    name = (user.first_name or "").strip().title() or "there"
    intro = f"{_kickoff_tag()} Hi {name}, {coach_name} here. This is your 12-week programme kickoff podcast—give it a listen."
    if audio_url:
        print(f"[kickoff] sending kickoff message for user={user.id} url={audio_url}")
        message = f"{intro}\n\n{cta}"
        media_sent = False
        try:
            # For audio media, clients may not reliably render captions.
            # Send companion text separately so the context is always visible.
            send_whatsapp_media(
                to=user.phone,
                media_url=audio_url,
                caption=None,
            )
            media_sent = True
        except Exception:
            media_sent = False
        if not media_sent:
            _send_kickoff(
                to=user.phone,
                text=f"{intro} {audio_url}",
            )
        try:
            _send_kickoff(
                to=user.phone,
                text=message,
                quick_replies=quick_replies,
            )
        except Exception:
            _send_kickoff(
                to=user.phone,
                text=message,
            )
    else:
        print(f"[kickoff] no audio_url for user={user.id}; sending fallback text")
        message = (
            f"{_kickoff_tag()} Hi {name}, {coach_name} here. "
            "This is your 12-week programme kickoff. "
            "I couldn’t generate your kickoff audio just now, but the plan is ready—let’s proceed.\n\n"
            f"{cta}"
        )
        _send_kickoff(to=user.phone, text=message, quick_replies=quick_replies)
    try:
        log_touchpoint(
            user_id=user.id,
            tp_type="kickoff",
            weekly_focus_id=weekly_focus_id,
            week_no=week_no,
            kr_ids=kr_ids,
            meta={"source": "kickoff_auto", "label": "kickoff", "week_no": week_no},
            generated_text=message,
            audio_url=audio_url,
        )
    except Exception:
        pass


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
    assembly = build_prompt(
        "kickoff_support",
        user_id=0,
        coach_name=COACH_NAME,
        user_name="User",
        locale="UK",
        krs_payload=payload,
        transcript_history=transcript_str,
        user_message=user_message,
    )
    return assembly.text


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
            _send_kickoff(to=user.phone, text="(i Inst) " + prompt)
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
    """
    Create (or reuse) Week 1 focus, generate kickoff podcast, and send it.
    """
    if _podcast_worker_enabled():
        job_id = enqueue_job(
            "kickoff_flow",
            {"user_id": user.id, "notes": notes, "debug": bool(debug)},
            user_id=user.id,
        )
        print(f"[kickoff] enqueued kickoff flow user_id={user.id} job={job_id}")
        return
    general_support.clear(user.id)
    week_no = 1
    with SessionLocal() as s:
        selected = select_top_krs_for_user(s, user.id, limit=None, week_no=week_no)
        kr_ids = [kr_id for kr_id, _ in selected]
        if not kr_ids:
            _send_kickoff(to=user.phone, text="No active KRs found to propose. Please set OKRs first.")
            return

        today = datetime.utcnow().date()
        earliest = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id)
            .order_by(WeeklyFocus.starts_on.asc())
            .first()
        )
        base_start = week_anchor_date(earliest.starts_on if earliest else today, default_today=today)
        start = base_start  # Week 1 anchor
        end = start + timedelta(days=6)

        wf = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id, WeeklyFocus.starts_on == start, WeeklyFocus.ends_on == end)
            .first()
        )
        if wf:
            existing_kr_ids = [
                row.kr_id
                for row in (
                    s.query(WeeklyFocusKR)
                    .filter(WeeklyFocusKR.weekly_focus_id == wf.id)
                    .order_by(WeeklyFocusKR.priority_order.asc())
                    .all()
                )
            ]
            if existing_kr_ids:
                kr_ids = existing_kr_ids
            else:
                for idx, kr_id in enumerate(kr_ids):
                    s.add(
                        WeeklyFocusKR(
                            weekly_focus_id=wf.id,
                            kr_id=kr_id,
                            priority_order=idx,
                            role="primary" if idx == 0 else "secondary",
                        )
                    )
                s.commit()
        else:
            wf = WeeklyFocus(user_id=user.id, starts_on=start, ends_on=end, notes=notes, week_no=week_no)
            s.add(wf); s.flush()
            for idx, kr_id in enumerate(kr_ids):
                s.add(
                    WeeklyFocusKR(
                        weekly_focus_id=wf.id,
                        kr_id=kr_id,
                        priority_order=idx,
                        role="primary" if idx == 0 else "secondary",
                    )
                )
            s.commit()
        wf_id = getattr(wf, "id", None)

    try:
        audio_url, _ = generate_kickoff_podcast_audio(user.id, week_no=week_no)
        send_kickoff_podcast_message(
            user,
            audio_url,
            coach_name=COACH_NAME,
            week_no=week_no,
            weekly_focus_id=wf_id,
            kr_ids=kr_ids,
        )
        general_support.activate(user.id, source="kickoff", week_no=week_no, send_intro=False)
    except Exception as e:
        try:
            print(f"[kickoff] start_kickoff error for user {user.id}: {e}")
        except Exception:
            pass
        _send_kickoff(
            to=user.phone,
            text="*Kickoff* Sorry—something went wrong sending your kickoff. Please try again shortly.",
        )


def handle_message(user: User, text: str) -> None:
    msg = (text or "").strip()
    lower = msg.lower()
    # kickoff keyword starts a new flow
    if lower.startswith("kickoff"):
        debug = lower.startswith("kickoffdebug") and debug_enabled()
        start_kickoff(user, debug=debug)
        return

    # No other stateful kickoff chat: politely prompt the user to use the keyword
    _send_kickoff(to=user.phone, text="Say kickoff to start your weekly focus.")
