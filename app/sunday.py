"""
Sunday weekly review: capture progress for weekly focus KRs and ask wins/barriers.
Stateful flow: per-KR actuals → wins → blockers.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session

from .db import SessionLocal
from .nudges import send_whatsapp
from .models import WeeklyFocus, WeeklyFocusKR, OKRKeyResult, User, UserPreference, OKRKrEntry
from .kickoff import COACH_NAME
from .prompts import sunday_prompt
from . import llm as shared_llm

STATE_KEY = "sunday_state"


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


def _pick_krs(session: Session, wf_id: int) -> list[OKRKeyResult]:
    rows = (
        session.query(WeeklyFocusKR, OKRKeyResult)
        .join(OKRKeyResult, WeeklyFocusKR.kr_id == OKRKeyResult.id)
        .filter(WeeklyFocusKR.weekly_focus_id == wf_id)
        .order_by(WeeklyFocusKR.priority_order.asc())
        .all()
    )
    return [kr for _, kr in rows]


def _get_state(session: Session, user_id: int) -> Optional[dict]:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if pref and pref.value:
        try:
            import json
            return json.loads(pref.value)
        except Exception:
            return None
    return None


def _set_state(session: Session, user_id: int, state: Optional[dict]) -> None:
    pref = (
        session.query(UserPreference)
        .filter(UserPreference.user_id == user_id, UserPreference.key == STATE_KEY)
        .one_or_none()
    )
    if state is None:
        if pref:
            session.delete(pref)
        return
    import json
    if pref:
        pref.value = json.dumps(state)
    else:
        pref = UserPreference(user_id=user_id, key=STATE_KEY, value=json.dumps(state))
        session.add(pref)


def has_active_state(user_id: int) -> bool:
    with SessionLocal() as s:
        st = _get_state(s, user_id)
        return st is not None


def _ask_current_kr(user: User, kr: OKRKeyResult, idx: int, total: int) -> None:
    target = kr.target_num if kr.target_num is not None else kr.target_text or ""
    unit = f" {kr.unit}" if kr.unit else ""
    msg = (
        f"*Sunday* KR {idx}/{total}: {kr.description}\n"
        f"Target: {target}{unit if target else ''}\n"
        "What was your actual this week? Reply with a number."
    )
    send_whatsapp(to=user.phone, text=msg)


def send_sunday_review(user: User, coach_name: str = COACH_NAME) -> None:
    with SessionLocal() as s:
        wf = _latest_weekly_focus(s, user.id)
        if not wf:
            send_whatsapp(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
            return
        krs = _pick_krs(s, wf.id)
        if not krs:
            send_whatsapp(to=user.phone, text="No key results found for this week. Say monday to set them up.")
            return

        # initialise state
        kr_ids = [kr.id for kr in krs]
        _set_state(
            s,
            user.id,
            {"step": "kr", "idx": 0, "kr_ids": kr_ids, "wf_id": wf.id, "wins": None, "blocks": None},
        )
        s.commit()
    # Fetch fresh KR in a new session to avoid detached instances
    with SessionLocal() as s:
        first_kr = s.query(OKRKeyResult).filter(OKRKeyResult.id == kr_ids[0]).one_or_none()
        if not first_kr:
            send_whatsapp(to=user.phone, text="*Sunday* No key results available to review.")
            return
        _ask_current_kr(user, first_kr, 1, len(kr_ids))


def handle_message(user: User, body: str) -> None:
    text = (body or "").strip()
    if not text:
        return
    with SessionLocal() as s:
        state = _get_state(s, user.id)
        if not state:
            return
        step = state.get("step")
        kr_ids = state.get("kr_ids") or []
        idx = state.get("idx", 0)

        if step == "kr":
            # parse numeric
            try:
                val = float(text.replace(",", "."))
            except Exception:
                send_whatsapp(to=user.phone, text="Please reply with a number for this KR. (e.g., 2, 3.5)")
                return
            # update KR
            kr_id = kr_ids[idx] if idx < len(kr_ids) else None
            if kr_id:
                kr = s.query(OKRKeyResult).filter(OKRKeyResult.id == kr_id).one_or_none()
                if kr:
                    kr.actual_num = val
                    entry = OKRKrEntry(
                        key_result_id=kr.id,
                        occurred_at=datetime.utcnow(),
                        actual_num=val,
                        note="Sunday check-in",
                        source="sunday",
                    )
                    s.add(entry)
                    s.commit()
            idx += 1
            if idx < len(kr_ids):
                state["idx"] = idx
                _set_state(s, user.id, state)
                s.commit()
                nxt = s.query(OKRKeyResult).filter(OKRKeyResult.id == kr_ids[idx]).one()
                _ask_current_kr(user, nxt, idx + 1, len(kr_ids))
                return
            # move to wins
            state["step"] = "wins"
            _set_state(s, user.id, state)
            s.commit()
            send_whatsapp(to=user.phone, text="*Sunday* What worked well this week that helped you make progress?")
            return

        if step == "wins":
            state["wins"] = text
            state["step"] = "blocks"
            _set_state(s, user.id, state)
            s.commit()
            send_whatsapp(to=user.phone, text="*Sunday* What didn’t work well or made things harder than expected?")
            return

        if step == "blocks":
            state["blocks"] = text
            _set_state(s, user.id, None)
            s.commit()
            send_whatsapp(
                to=user.phone,
                text="*Sunday* Thanks, got your updates. I’ll summarise these and we’ll pick up with Monday’s kickoff.",
            )
            return

        # default: clear if unknown
        _set_state(s, user.id, None)
        s.commit()
