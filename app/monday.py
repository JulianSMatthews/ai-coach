"""
Monday weekstart touchpoint: podcast confirmation and handoff to general support.
"""
from __future__ import annotations

import json
import os
from typing import Optional
from datetime import datetime, timedelta

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
    OKRObjective,
    AssessmentRun,
)
from .kickoff import generate_kickoff_podcast_transcript, COACH_NAME
from .podcast import generate_podcast_audio
from .prompts import kr_payload_list
from .touchpoints import log_touchpoint
from . import general_support
from .virtual_clock import get_effective_today


def _in_worker_process() -> bool:
    return (os.getenv("PROMPT_WORKER_PROCESS") or "").strip().lower() in {"1", "true", "yes"}


def _podcast_worker_enabled() -> bool:
    return should_use_podcast_worker() and not _in_worker_process()


def _monday_label() -> str:
    return "Monday." if not _in_worker_process() else "Monday"


def _monday_tag() -> str:
    return f"*{_monday_label()}*"


def _apply_monday_marker(text: str | None) -> str | None:
    if not text:
        return text
    if text.startswith("*Monday*"):
        return text.replace("*Monday*", _monday_tag(), 1)
    return text


def _send_monday(*, text: str, to: str | None = None, category: str | None = None, quick_replies: list[str] | None = None) -> str:
    return send_whatsapp(
        text=_apply_monday_marker(text) or text,
        to=to,
        category=category,
        quick_replies=quick_replies,
    )


def _current_focus_pillar(user: User) -> Optional[str]:
    """
    Infer the current pillar from the most recent WeeklyFocus and its top KR.
    """
    with SessionLocal() as s:
        wf = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id)
            .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
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
    """Generate and send a short audio briefing for the weekly weekstart. Returns (audio_url, transcript)."""
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
            locale="UK",
        )
        audio_url = generate_podcast_audio(
            transcript,
            user.id,
            filename=f"monday_week{week_no}.mp3",
            usage_tag="weekly_flow",
        )
        if audio_url:
            try:
                print(f"[monday] podcast url: {audio_url}")
                if audio_url.startswith("http://localhost") or audio_url.startswith("http://127.0.0.1"):
                    print("[monday] WARNING: podcast url is localhost; Twilio cannot fetch media from localhost.")
            except Exception:
                pass
            caption = (
                f"{_monday_tag()} Hi { (user.first_name or '').strip().title() or 'there' }. "
                f"{COACH_NAME} here. Here’s your Week {week_no} podcast—give it a listen."
            )
            try:
                send_whatsapp_media(
                    to=user.phone,
                    media_url=audio_url,
                    caption=caption,
                )
            except Exception:
                _send_monday(
                    to=user.phone,
                    text=f"{caption} {audio_url}",
                )
        else:
            # Fallback: send transcript if audio generation failed
            if transcript:
                _send_monday(
                    to=user.phone,
                    text=f"*Monday* Podcast unavailable right now—here’s the briefing:\n\n{transcript}",
                )
            print(f"[monday] podcast generation returned no URL (user={user.id}, week={week_no})")
    except Exception as e:
        print(f"[monday] podcast generation error for user {user.id}: {e}")
    return audio_url, transcript


def _build_podcast_confirm_message(user: User, coach_name: str = COACH_NAME) -> str:
    name = (getattr(user, "first_name", "") or "").strip().title() or "there"
    return (
        f"*Monday* Hi {name}, {coach_name} here. "
        "This is your weekstart podcast — please confirm once you’ve listened."
    )


def _fmt_num(val) -> str:
    """Render numeric values as clean strings (ints without .0)."""
    try:
        f = float(val)
        return str(int(f)) if f.is_integer() else str(f).rstrip("0").rstrip(".")
    except Exception:
        return str(val) if val is not None else ""


def _state_key() -> str:
    """Preference key used to store the monday session state."""
    return "weekstart_state"


def _get_state(session: Session, user_id: int) -> Optional[dict]:
    """Load the monday session state from UserPreference, if present."""
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
    """Persist or clear the monday session state in UserPreference."""
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
    """Check if a monday session state is stored for this user."""
    with SessionLocal() as s:
        st = _get_state(s, user_id)
        return bool(st)


def _format_krs(krs: list[OKRKeyResult]) -> str:
    """Human-readable multi-line string for the current KRs."""
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


def _summary_message(krs: list[OKRKeyResult]) -> str:
    """Short confirmation of the agreed KRs."""
    return "Agreed KRs for this week:\n" + _format_krs(krs)


def _is_podcast_confirm_message(text: str) -> bool:
    cleaned = " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text or "").split())
    if not cleaned:
        return False
    confirmations = {
        "listened",
        "listen",
        "all ok",
        "all okay",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "yes",
        "y",
        "all good",
        "looks good",
        "looks great",
    }
    return cleaned in confirmations or cleaned.startswith("all ok") or cleaned.startswith("all okay") or cleaned.startswith("all good")


def start_weekstart(user: User, notes: str | None = None, debug: bool = False, set_state: bool = True, week_no: Optional[int] = None) -> None:
    """Create weekly focus, pick KRs, send monday weekstart message, and optionally set state."""
    if _podcast_worker_enabled():
        job_id = enqueue_job(
            "weekstart_flow",
            {
                "user_id": user.id,
                "notes": notes,
                "debug": bool(debug),
                "set_state": bool(set_state),
                "week_no": week_no,
            },
            user_id=user.id,
        )
        print(f"[monday] enqueued weekstart flow user_id={user.id} job={job_id}")
        return
    general_support.clear(user.id)
    with SessionLocal() as s:
        today = get_effective_today(s, user.id, default_today=datetime.utcnow().date())
        base_start = None
        run = (
            s.query(AssessmentRun)
            .filter(AssessmentRun.user_id == user.id)
            .order_by(AssessmentRun.id.desc())
            .first()
        )
        if run:
            base_dt = getattr(run, "started_at", None) or getattr(run, "created_at", None)
            if isinstance(base_dt, datetime):
                base_start = base_dt.date() - timedelta(days=base_dt.date().weekday())
        if base_start is None:
            earliest = (
                s.query(WeeklyFocus)
                .filter(WeeklyFocus.user_id == user.id)
                .order_by(WeeklyFocus.starts_on.asc())
                .first()
            )
            if earliest and getattr(earliest, "starts_on", None):
                try:
                    base_start = earliest.starts_on.date()
                except Exception:
                    base_start = None
        if base_start is None:
            base_start = today - timedelta(days=today.weekday())

        label_week = week_no
        if label_week is None:
            current_week_start = today - timedelta(days=today.weekday())
            try:
                label_week = max(1, int(((current_week_start - base_start).days // 7) + 1))
            except Exception:
                label_week = 1

        start = base_start + timedelta(days=7 * (label_week - 1))
        end = start + timedelta(days=6)

        wf = (
            s.query(WeeklyFocus)
            .filter(WeeklyFocus.user_id == user.id, WeeklyFocus.week_no == label_week)
            .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
            .first()
        )
        kr_ids: list[int] = []
        if wf:
            rows = (
                s.query(WeeklyFocusKR)
                .filter(WeeklyFocusKR.weekly_focus_id == wf.id)
                .order_by(WeeklyFocusKR.priority_order.asc())
                .all()
            )
            kr_ids = [row.kr_id for row in rows if row.kr_id]

        if not kr_ids:
            kr_ids = [kr["id"] for kr in kr_payload_list(user.id, session=s, week_no=label_week, max_krs=3)]
            if not kr_ids:
                _send_monday(to=user.phone, text="No active KRs found to propose. Please set OKRs first.")
                return

        if not wf:
            wf = WeeklyFocus(user_id=user.id, starts_on=start, ends_on=end, notes=notes, week_no=label_week)
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
        else:
            try:
                if wf.week_no != label_week:
                    wf.week_no = label_week
                if notes:
                    wf.notes = notes
                s.add(wf)
                s.commit()
            except Exception:
                pass

        kr_rows = s.query(OKRKeyResult).filter(OKRKeyResult.id.in_(kr_ids)).all()
        kr_lookup = {kr.id: kr for kr in kr_rows if kr}
        krs = [kr_lookup[kid] for kid in kr_ids if kid in kr_lookup]

        audio_url, _transcript = _send_weekly_briefing(user, week_no=label_week)
        confirm_msg = _build_podcast_confirm_message(user, COACH_NAME)
        _send_monday(
            to=user.phone,
            text=confirm_msg,
            quick_replies=["Listened", "Later"],
        )

        # Log weekstart touchpoint
        log_touchpoint(
            user_id=user.id,
            tp_type="monday",
            weekly_focus_id=wf.id,
            week_no=label_week,
            kr_ids=kr_ids,
            meta={"notes": notes, "week_no": label_week, "source": "weekstart", "label": "monday"},
            generated_text=confirm_msg,
            audio_url=audio_url,
        )

        if set_state:
            _set_state(
                s,
                user.id,
                {
                    "mode": "awaiting_podcast",
                    "wf_id": wf.id,
                    "kr_ids": kr_ids,
                    "history": [],
                    "debug": debug,
                    "week_no": label_week,
                },
            )
            s.commit()


def handle_message(user: User, text: str) -> None:
    """Entry point for inbound monday/Weekstart chat messages."""
    msg = (text or "").strip()
    lower = msg.lower()
    with SessionLocal() as s:
        state = _get_state(s, user.id)

        if lower.startswith("mondaydebug") and debug_enabled():
            _set_state(s, user.id, None); s.commit()
            start_weekstart(user, debug=True, set_state=True, week_no=None)
            return
        if lower.startswith("monday") or state is None:
            _set_state(s, user.id, None); s.commit()
            start_weekstart(user, debug=False, set_state=True, week_no=None)
            return

        if state is None:
            _send_monday(to=user.phone, text="Say monday to start your weekly focus.")
            return

        debug = bool(state.get("debug"))
        wf_id = state.get("wf_id")
        wf = s.query(WeeklyFocus).get(wf_id) if wf_id else None
        if not wf:
            _set_state(s, user.id, None)
            s.commit()
            start_weekstart(user, debug=debug, set_state=True, week_no=None)
            return

        mode = state.get("mode")
        week_no = getattr(wf, "week_no", None)

        if mode == "awaiting_podcast":
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
            if not krs and wkrs:
                krs = [kr for _, kr in wkrs if kr]

            listened = "listened" in lower or lower == "listen" or _is_podcast_confirm_message(msg)
            if listened:
                summary = _summary_message(krs) if krs else "Weekstart confirmed."
                msg_txt = (
                    f"*Monday* Thanks for listening.\n\n{summary}\n\n"
                    "We’ll set your habit steps on Sunday for the next week."
                )
                _send_monday(to=user.phone, text=msg_txt)
                _set_state(s, user.id, None)
                s.commit()
                general_support.activate(user.id, source="monday", week_no=week_no, send_intro=True)
                return
            _send_monday(
                to=user.phone,
                text="*Monday* No rush — reply “Listened” when you’re ready.",
                quick_replies=["Listened", "Later"],
            )
            return

        if mode in {"proposal", "support"}:
            _send_monday(
                to=user.phone,
                text=(
                    "*Monday* Habit-step setting now runs on Sunday. "
                    "For today, your weekstart is confirmed after the podcast."
                ),
            )
            _set_state(s, user.id, None)
            s.commit()
            general_support.activate(user.id, source="monday", week_no=week_no, send_intro=True)
            return

        _set_state(s, user.id, None); s.commit()
        _send_monday(to=user.phone, text="Session reset. Say monday to start your weekly focus.")
