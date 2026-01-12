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
from .checkins import record_checkin
from .models import WeeklyFocus, OKRKeyResult, User, UserPreference, OKRKrEntry
from .kickoff import COACH_NAME
from . import llm as shared_llm
from .touchpoints import log_touchpoint
from .prompts import kr_payload_list, build_prompt, run_llm_prompt

STATE_KEY = "sunday_state"


def _latest_weekly_focus(session: Session, user_id: int) -> Optional[WeeklyFocus]:
    return (
        session.query(WeeklyFocus)
        .filter(WeeklyFocus.user_id == user_id)
        .order_by(WeeklyFocus.starts_on.desc(), WeeklyFocus.id.desc())
        .first()
    )


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
    wf_id: int | None = None
    kr_ids: list[int] = []
    with SessionLocal() as s:
        wf = _latest_weekly_focus(s, user.id)
        if not wf:
            send_whatsapp(to=user.phone, text="No weekly plan found. Say monday to plan your week first.")
            return
        wf_id = wf.id
        kr_ids = [kr["id"] for kr in kr_payload_list(user.id, session=s, max_krs=3)]
        if not kr_ids:
            send_whatsapp(to=user.phone, text="No key results found for this week. Say monday to set them up.")
            return

        # initialise state (store ids only to avoid detached instances)
        _set_state(
            s,
            user.id,
            {"step": "kr", "idx": 0, "kr_ids": kr_ids, "wf_id": wf_id, "wins": None, "blocks": None},
        )
        s.commit()
    # Fetch fresh KR in a new session to avoid detached instances
    if not kr_ids or wf_id is None:
        send_whatsapp(to=user.phone, text="*Sunday* No key results available to review.")
        return
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
            # Record check-in with latest KR actuals and blockers/wins
            wf = s.query(WeeklyFocus).get(state.get("wf_id"))
            krs = []
            if wf:
                krs = s.query(OKRKeyResult).filter(OKRKeyResult.id.in_(kr_ids)).all()
            progress_updates = []
            for kr in krs:
                progress_updates.append({"kr_id": kr.id, "actual": kr.actual_num, "target": kr.target_num})
            blockers = [{"note": text}] if text else []
            wins = state.get("wins")
            commitments = [{"note": wins}] if wins else []
            check_in_id = None
            try:
                check_in_id = record_checkin(
                    user_id=user.id,
                    touchpoint_type="sunday",
                    progress_updates=progress_updates,
                    blockers=blockers,
                    commitments=commitments,
                    weekly_focus_id=wf.id if wf else None,
                    week_no=getattr(wf, "week_no", None) if wf else None,
                )
            except Exception:
                check_in_id = None

            # LLM closing summary (logged)
            prompt_assembly = build_prompt(
                "sunday",
                user_id=user.id,
                coach_name=COACH_NAME,
                user_name=user.first_name or "there",
                locale=getattr(user, "tz", "UK") or "UK",
                timeframe="Sunday",
            )
            closing = run_llm_prompt(
                prompt_assembly.text,
                user_id=user.id,
                touchpoint="sunday",
                context_meta={"wf_id": wf.id if wf else None},
                prompt_variant=prompt_assembly.variant,
                task_label=prompt_assembly.task_label,
                prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
                block_order=prompt_assembly.block_order,
                log=True,
            )
            if closing:
                send_whatsapp(to=user.phone, text=closing if closing.startswith("*Sunday*") else f"*Sunday* {closing}")
            else:
                send_whatsapp(
                    to=user.phone,
                    text="*Sunday* Thanks, got your updates. I’ll summarise these and we’ll pick up with Monday’s kickoff.",
                )
            try:
                log_touchpoint(
                    user_id=user.id,
                    tp_type="sunday",
                    weekly_focus_id=wf.id if wf else None,
                    week_no=getattr(wf, "week_no", None) if wf else None,
                    kr_ids=[kr.id for _, kr in krs] if krs else [],
                    meta={"source": "sunday", "label": "sunday"},
                    source_check_in_id=check_in_id,
                )
            except Exception:
                pass
            return

        # default: clear if unknown
        _set_state(s, user.id, None)
        s.commit()
