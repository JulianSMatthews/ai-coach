"""
Monday weekstart touchpoint (podcast + support): proposal → support.
"""
from __future__ import annotations

import json
import re
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
    OKRKrHabitStep,
    AssessmentRun,
    LLMPromptLog,
    Touchpoint,
)
from .focus import select_top_krs_for_user
from . import llm as shared_llm
from .kickoff import generate_kickoff_podcast_transcript, COACH_NAME
from .podcast import generate_podcast_audio
from .prompts import coaching_prompt, kr_payload_list, build_prompt, run_llm_prompt
from .touchpoints import log_touchpoint
from . import general_support


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
        audio_url = generate_podcast_audio(transcript, user.id, filename=f"monday_week{week_no}.mp3")
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


def _parse_action_options(text: str, krs: list[OKRKeyResult]) -> dict[int, list[str]]:
    options_by_kr: dict[int, list[str]] = {kr.id: [] for kr in krs}
    if not text:
        return options_by_kr
    current_idx: Optional[int] = None
    current_kr_id: Optional[int] = None
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = line.replace("(i)", "").replace("( i )", "").strip()
        lowered = line.lower().replace("’", "'")
        if (
            lowered.startswith("as per the podcast")
            or lowered.startswith("reply with")
            or lowered.startswith("in your next message")
            or lowered.startswith("in the next message")
            or lowered.startswith("in the next step")
            or "you'll be asked" in lowered
            or "you will be asked" in lowered
        ):
            continue
        line = line.lstrip("-•*–—·").strip()

        header_match = re.match(r"^kr\s*(\d+)\s*[:\-]\s*(.+)$", line, flags=re.IGNORECASE)
        if header_match:
            idx = int(header_match.group(1)) - 1
            if 0 <= idx < len(krs):
                current_idx = idx
                current_kr_id = krs[idx].id
            else:
                # Attempt to map by description if index is off
                label = header_match.group(2).strip()
                matched = _match_kr_for_label(label, krs)
                current_idx = None
                current_kr_id = matched.id if matched else None
            continue

        match = re.match(r"^(?:kr\s*)?(\d+)\s*([a-c])\s*[)\].:\-–—]\s*(.+)$", line, flags=re.IGNORECASE)
        if match:
            idx = int(match.group(1)) - 1
            text_val = match.group(3).strip()
            if not text_val or idx < 0 or idx >= len(krs):
                continue
            kr = krs[idx]
            existing = options_by_kr.get(kr.id) or []
            if text_val not in existing:
                options_by_kr[kr.id] = [*existing, text_val]
            continue

        match = re.match(r"^([a-c])\s*[)\].:\-–—]\s*(.+)$", line, flags=re.IGNORECASE)
        if match and current_kr_id:
            text_val = match.group(2).strip()
            if not text_val:
                continue
            existing = options_by_kr.get(current_kr_id) or []
            if text_val not in existing:
                options_by_kr[current_kr_id] = [*existing, text_val]
            continue

        match = re.match(r"^(?:kr\s*)?(\d+)\s*[)\].:\-–—]\s*(.+)$", line, flags=re.IGNORECASE)
        if match:
            idx = int(match.group(1)) - 1
            text_val = match.group(2).strip()
            if not text_val or idx < 0 or idx >= len(krs):
                continue
            kr = krs[idx]
            existing = options_by_kr.get(kr.id) or []
            if text_val not in existing:
                options_by_kr[kr.id] = [*existing, text_val]
            continue

        if current_kr_id:
            text_val = line.strip()
            if text_val:
                existing = options_by_kr.get(current_kr_id) or []
                if text_val not in existing:
                    options_by_kr[current_kr_id] = [*existing, text_val]
    return options_by_kr


def _fallback_options_for_kr(kr: OKRKeyResult) -> list[str]:
    desc = (kr.description or "").strip()
    if not desc:
        return [
            "Do one simple step toward this KR on two days this week.",
            "Anchor this KR to one routine you already do (e.g., breakfast or dinner).",
            "Set one tiny prep step that makes this KR easier this week.",
        ]
    return [
        f"Do one simple step toward this KR on two days this week: {desc}.",
        f"Anchor this KR to one routine you already do (e.g., breakfast or dinner): {desc}.",
        f"Set one tiny prep step that makes this KR easier this week: {desc}.",
    ]


def _build_actions_message(krs: list[OKRKeyResult], options_by_kr: dict[int, list[str]]) -> str:
    lines = ["As per the podcast, here are practical actions for this week:"]
    for idx, kr in enumerate(krs, 1):
        lines.append(f"KR{idx}: {kr.description}")
        options = options_by_kr.get(kr.id) or []
        for opt_idx, opt in enumerate(options):
            letter = chr(ord("A") + opt_idx)
            lines.append(f"{idx}{letter}) {opt}")
    lines.append("Tap a button under each KR to choose your habit step.")
    return "\n".join(lines)


def _build_actions_intro() -> str:
    return "As per the podcast, here are practical actions for this week. Tap a button to choose your habit step. I’ll send the next KR after you choose."


def _build_podcast_confirm_message(user: User, coach_name: str = COACH_NAME) -> str:
    name = (getattr(user, "first_name", "") or "").strip().title() or "there"
    return (
        f"*Monday* Hi {name}, {coach_name} here. "
        "This is your weekstart podcast — please confirm once you’ve listened."
    )


def _extract_intro_from_actions_message(message: str) -> Optional[str]:
    if not message:
        return None
    lines = []
    for raw in message.splitlines():
        line = raw.strip().lstrip("*").strip()
        if not line:
            continue
        if re.match(r"^kr\s*\d+\s*[:\-]", line, flags=re.IGNORECASE):
            break
        lines.append(line)
    if not lines:
        return None
    return " ".join(lines).strip() or None


def _build_actions_for_kr(idx: int, kr: OKRKeyResult, options: list[str]) -> str:
    lines = [f"KR{idx}: {kr.description}"]
    for opt_idx, opt in enumerate(options):
        letter = chr(ord("A") + opt_idx)
        lines.append(f"{letter}) {opt}")
    return "\n".join(lines)


def _is_fallback_option_set(options: list[str]) -> bool:
    if len(options) < 3:
        return False
    joined = " ".join(opt.lower() for opt in options if opt)
    return (
        "do one simple step toward this kr" in joined
        and "anchor this kr to one routine" in joined
        and "set one tiny prep step" in joined
    )


def _refresh_options_from_actions_message(
    actions_message: str,
    krs: list[OKRKeyResult],
    options_by_index: list[list[str]],
) -> list[list[str]]:
    if not actions_message or not krs:
        return options_by_index
    parsed = _parse_action_options(actions_message, krs)
    if not parsed:
        return options_by_index
    refreshed: list[list[str]] = []
    for idx, kr in enumerate(krs):
        current = options_by_index[idx] if idx < len(options_by_index) else []
        parsed_opts = parsed.get(kr.id) or []
        if parsed_opts and (not current or _is_fallback_option_set(current)):
            refreshed.append(parsed_opts)
        else:
            refreshed.append(current)
    return refreshed


def _any_fallback_options(options_by_index: list[list[str]]) -> bool:
    return any(_is_fallback_option_set(opts) for opts in options_by_index if opts)


def _latest_actions_text_from_touchpoints(
    session: Session,
    user_id: int,
    weekly_focus_id: Optional[int],
    week_no: Optional[int],
) -> Optional[str]:
    query = session.query(Touchpoint).filter(Touchpoint.user_id == user_id, Touchpoint.type == "monday")
    if weekly_focus_id:
        query = query.filter(Touchpoint.weekly_focus_id == weekly_focus_id)
    if week_no is not None:
        query = query.filter(Touchpoint.week_no == week_no)
    row = query.order_by(Touchpoint.created_at.desc(), Touchpoint.id.desc()).first()
    text = (row.generated_text or "").strip() if row else ""
    return text or None


def _latest_actions_text_from_llm_logs(session: Session, user_id: int) -> Optional[str]:
    row = (
        session.query(LLMPromptLog)
        .filter(LLMPromptLog.user_id == user_id, LLMPromptLog.touchpoint == "weekstart_actions")
        .order_by(LLMPromptLog.created_at.desc(), LLMPromptLog.id.desc())
        .first()
    )
    text = (row.response_preview or "").strip() if row else ""
    return text or None


def _kr_quick_replies(idx: int, options: list[str]) -> list[str]:
    replies = []
    for opt_idx, _opt in enumerate(options):
        letter = chr(ord("A") + opt_idx)
        replies.append(f"Option {letter}||KR{idx} {letter}")
    return replies


def _build_weekstart_actions(transcript: Optional[str], krs: list[OKRKeyResult], user: User) -> tuple[str, list[list[str]]]:
    transcript = (transcript or "").strip()
    client = getattr(shared_llm, "_llm", None)
    options_by_kr: dict[int, list[str]] = {kr.id: [] for kr in krs}
    llm_text = None
    allow_fallback = os.getenv("WEEKSTART_ALLOW_FALLBACK", "0").strip().lower() in {"1", "true", "yes"}
    if client:
        prompt_assembly = build_prompt(
            "weekstart_actions",
            user_id=user.id,
            coach_name=COACH_NAME,
            user_name=(user.first_name or ""),
            locale=getattr(user, "tz", "UK") or "UK",
            transcript=transcript,
            krs=[kr.description for kr in krs],
        )
        try:
            txt = run_llm_prompt(
                prompt_assembly.text,
                user_id=user.id,
                touchpoint="weekstart_actions",
                prompt_variant=prompt_assembly.variant,
                task_label=prompt_assembly.task_label,
                prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
                block_order=prompt_assembly.block_order,
                log=True,
            )
            txt = (txt or "").strip()
            if txt:
                llm_text = txt
                parsed = _parse_action_options(txt, krs)
                options_by_kr.update(parsed)
        except Exception:
            pass
    for kr in krs:
        options = options_by_kr.get(kr.id) or []
        options = [
            opt.strip()
            for opt in options
            if opt and opt.strip() and "smallest version" not in opt.lower()
            and "schedule one simple step" not in opt.lower()
        ]
        if not options and allow_fallback:
            options = _fallback_options_for_kr(kr)
        if len(options) < 3 and allow_fallback:
            desc = (kr.description or "").strip()
            filler = (
                f"Pick one tiny action that nudges this KR forward this week: {desc}."
                if desc else
                "Pick one tiny action that nudges this KR forward this week."
            )
            options.append(filler)
        if len(options) > 3:
            options = options[:3]
        options_by_kr[kr.id] = options
    message = llm_text or (_build_actions_message(krs, options_by_kr) if allow_fallback else "")
    options_by_index = [options_by_kr.get(kr.id, []) for kr in krs]
    return message, options_by_index


def _normalize_text(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text or "").split())


def _match_kr_for_label(label: str, krs: list[OKRKeyResult]) -> Optional[OKRKeyResult]:
    label_norm = _normalize_text(label)
    if not label_norm:
        return None
    for kr in krs:
        desc_norm = _normalize_text(kr.description or "")
        if not desc_norm:
            continue
        if label_norm in desc_norm:
            return kr
    return None


def _extract_action_lines(summary: str) -> list[str]:
    lines = []
    for raw in (summary or "").splitlines():
        line = raw.strip().lstrip("*").strip()
        if not line:
            continue
        lowered = line.lower()
        if "as per the podcast" in lowered:
            continue
        if lowered.startswith("let me know") or lowered.startswith("please ask"):
            continue
        if line[0] in {"-", "•", "*"}:
            line = line[1:].strip()
        else:
            if len(line) > 2 and line[:2].isdigit() and line[2:3] in {")", "."}:
                line = line[3:].strip()
        if line:
            lines.append(line)
    return lines


def _save_habit_steps_from_options(
    session: Session,
    user_id: int,
    weekly_focus_id: int,
    week_no: int,
    krs: list[OKRKeyResult],
    options_by_index: list[list[str]],
) -> None:
    if not krs:
        return
    kr_ids = [kr.id for kr in krs if kr.id]
    session.query(OKRKrHabitStep).filter(
        OKRKrHabitStep.user_id == user_id,
        OKRKrHabitStep.kr_id.in_(kr_ids),
        OKRKrHabitStep.week_no == week_no,
    ).delete(synchronize_session=False)

    for idx, kr in enumerate(krs):
        options = options_by_index[idx] if idx < len(options_by_index) else []
        if not options:
            continue
        step_text = options[0].strip()
        if not step_text:
            continue
        session.add(
            OKRKrHabitStep(
                user_id=user_id,
                kr_id=kr.id,
                weekly_focus_id=weekly_focus_id,
                week_no=week_no,
                sort_order=0,
                step_text=step_text,
                status="proposed",
                source="weekstart_llm",
            )
            )


def _parse_option_selections(message: str, options_by_index: list[list[str]]) -> dict[int, int]:
    selections: dict[int, int] = {}
    if not message or not options_by_index:
        return selections
    for match in re.finditer(r"(?:kr\s*)?(\d+)\s*([a-z])", message.lower()):
        idx = int(match.group(1)) - 1
        opt_idx = ord(match.group(2)) - ord("a")
        if idx < 0 or idx >= len(options_by_index):
            continue
        if opt_idx < 0 or opt_idx >= len(options_by_index[idx]):
            continue
        selections[idx] = opt_idx
    return selections


def _normalize_state_selections(
    selections: dict | None,
    krs: list[OKRKeyResult],
    options_by_index: list[list[str]],
) -> dict[int, int]:
    if not selections:
        return {}
    normalized: dict[int, int] = {}
    for raw_idx, raw_opt in selections.items():
        try:
            idx = int(raw_idx)
            opt_idx = int(raw_opt)
        except Exception:
            continue
        if idx < 0 or idx >= len(krs):
            continue
        opts = options_by_index[idx] if idx < len(options_by_index) else []
        if opt_idx < 0 or opt_idx >= len(opts):
            continue
        normalized[idx] = opt_idx
    return normalized


def _normalize_state_edits(edits: dict | None) -> dict[int, list[str]]:
    if not edits:
        return {}
    normalized: dict[int, list[str]] = {}
    for raw_key, raw_val in edits.items():
        try:
            kr_id = int(raw_key)
        except Exception:
            continue
        if isinstance(raw_val, list):
            vals = [v for v in raw_val if isinstance(v, str) and v.strip()]
        elif isinstance(raw_val, str) and raw_val.strip():
            vals = [raw_val.strip()]
        else:
            vals = []
        if vals:
            normalized[kr_id] = vals
    return normalized


def _selected_kr_ids(
    krs: list[OKRKeyResult],
    selections: dict[int, int],
    edits: dict[int, list[str]],
) -> set[int]:
    selected: set[int] = set()
    for idx in selections.keys():
        if 0 <= idx < len(krs):
            selected.add(krs[idx].id)
    for kr_id in edits.keys():
        selected.add(kr_id)
    return selected


def _resolve_chosen_steps(
    krs: list[OKRKeyResult],
    options_by_index: list[list[str]],
    selections: dict[int, int],
    edits: dict[int, list[str]],
) -> dict[int, str]:
    chosen: dict[int, str] = {}
    for idx, kr in enumerate(krs):
        if edits and kr.id in edits and edits[kr.id]:
            chosen[kr.id] = edits[kr.id][0]
            continue
        if selections and idx in selections:
            opts = options_by_index[idx] if idx < len(options_by_index) else []
            opt_idx = selections[idx]
            if opts and 0 <= opt_idx < len(opts):
                chosen[kr.id] = opts[opt_idx]
                continue
        opts = options_by_index[idx] if idx < len(options_by_index) else []
        if opts:
            chosen[kr.id] = opts[0]
    return chosen


def _confirmation_message(krs: list[OKRKeyResult], chosen_steps: dict[int, str]) -> str:
    lines = ["Agreed habit steps for this week:"]
    for idx, kr in enumerate(krs, 1):
        step = chosen_steps.get(kr.id)
        if step:
            lines.append(f"{idx}) {step}")
    return "\n".join(lines)


def _extract_step_edits(message: str, krs: list[OKRKeyResult]) -> dict[int, list[str]]:
    edits: dict[int, list[str]] = {}
    lines = _extract_action_lines(message or "")
    for line in lines:
        kr = None
        text_val = line.strip()
        match = re.match(r"^(?:kr\s*)?(\d+)[\).:\-]\s*(.+)$", text_val, flags=re.IGNORECASE)
        if match:
            idx = int(match.group(1)) - 1
            text_val = match.group(2).strip()
            if 0 <= idx < len(krs):
                kr = krs[idx]
        if kr is None and ":" in text_val:
            label, action = text_val.split(":", 1)
            label = label.strip()
            action = action.strip()
            kr = _match_kr_for_label(label, krs)
            text_val = action or text_val
        if kr is None and len(krs) == 1:
            kr = krs[0]
        if kr and text_val:
            edits.setdefault(kr.id, []).append(text_val)
    return edits


def _apply_habit_step_edits(
    session: Session,
    user_id: int,
    weekly_focus_id: int | None,
    week_no: int | None,
    edits: dict[int, list[str]],
) -> None:
    if not edits:
        return
    kr_ids = list(edits.keys())
    if not kr_ids:
        return
    delete_query = session.query(OKRKrHabitStep).filter(
        OKRKrHabitStep.user_id == user_id,
        OKRKrHabitStep.kr_id.in_(kr_ids),
    )
    if week_no is not None:
        delete_query = delete_query.filter(OKRKrHabitStep.week_no == week_no)
    delete_query.delete(synchronize_session=False)

    for kr_id, steps in edits.items():
        for idx, step_text in enumerate(steps):
            session.add(
                OKRKrHabitStep(
                    user_id=user_id,
                    kr_id=kr_id,
                    weekly_focus_id=weekly_focus_id,
                    week_no=week_no,
                    sort_order=idx,
                    step_text=step_text.strip(),
                    status="active",
                    source="user",
                )
            )


def _activate_habit_steps(
    session: Session,
    user_id: int,
    week_no: int | None,
    kr_ids: list[int],
) -> None:
    if not kr_ids:
        return
    q = session.query(OKRKrHabitStep).filter(
        OKRKrHabitStep.user_id == user_id,
        OKRKrHabitStep.kr_id.in_(kr_ids),
    )
    if week_no is not None:
        q = q.filter(OKRKrHabitStep.week_no == week_no)
    q.update({"status": "active"}, synchronize_session=False)


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


def _support_prompt(user: User, history: list[dict], user_message: str | None):
    """Build the LLM prompt for weekstart support chat."""
    transcript = []
    for turn in history:
        role = turn.get("role", "")
        content = turn.get("content", "")
        if role and content:
            transcript.append(f"{role.upper()}: {content}")
    if user_message:
        transcript.append(f"USER: {user_message}")
    return build_prompt(
        "weekstart_support",
        user_id=user.id,
        coach_name=COACH_NAME,
        user_name=(user.first_name or ""),
        locale=getattr(user, "tz", "UK") or "UK",
        history=transcript,
    )


def _support_conversation(
    history: list[dict],
    user_message: str | None,
    user: User,
    debug: bool = False,
) -> tuple[str, list[dict]]:
    """Generate the next support message and updated history."""
    prompt_assembly = _support_prompt(user, history, user_message)
    prompt = prompt_assembly.text
    if debug:
        try:
            _send_monday(to=user.phone, text="(i Inst) " + prompt)
        except Exception:
            pass
    candidate = run_llm_prompt(
        prompt,
        user_id=user.id,
        touchpoint="weekstart_support",
        context_meta={"debug": debug},
        prompt_variant=prompt_assembly.variant,
        task_label=prompt_assembly.task_label,
        prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
        block_order=prompt_assembly.block_order,
        log=True,
    )
    text = "(i) " + candidate if candidate else None
    if text is None:
        if user_message:
            text = "(i) Thanks for the update. Want a quick idea for the next step on any goal? Tell me which one, and I’ll keep it simple."
        else:
            tips = [
                f"{kr['description']}: quick plan or light scheduling idea for this week."
                for kr in kr_payload_list(user.id, max_krs=3)
            ]
            if tips:
                text = "(i) Here are ideas to help this week: " + " ".join(tips)
            else:
                text = "(i) Here are ideas to help this week: pick any goal you want to start with and I’ll suggest one easy action."

    new_history = list(history)
    if user_message:
        new_history.append({"role": "user", "content": user_message})
    new_history.append({"role": "assistant", "content": text})
    return text, new_history


def _initial_message(user: User, wf: WeeklyFocus, krs: list[OKRKeyResult]) -> str:
    """First monday message proposing the weekly KR set."""
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
    """Short confirmation of the agreed KRs."""
    return "Agreed KRs for this week:\n" + _format_krs(krs)


def _is_confirm_message(text: str, *, allow_all_good: bool = False) -> bool:
    cleaned = _normalize_text(text)
    if not cleaned:
        return False
    confirmations = {
        "all ok",
        "all okay",
        "ok",
        "okay",
        "confirm",
        "confirmed",
        "yes",
        "y",
        "looks good",
        "fine",
        "sounds good",
    }
    if allow_all_good:
        confirmations.update({"all good", "looks great"})
    if cleaned in confirmations:
        return True
    if cleaned.startswith("all ok") or cleaned.startswith("all okay"):
        return True
    if allow_all_good and cleaned.startswith("all good"):
        return True
    return False


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
        today = datetime.utcnow().date()
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

        audio_url, transcript = _send_weekly_briefing(user, week_no=label_week)
        actions_message, options_by_index = _build_weekstart_actions(transcript, krs, user)
        if actions_message:
            options_by_index = _refresh_options_from_actions_message(actions_message, krs, options_by_index)
        confirm_msg = _build_podcast_confirm_message(user, COACH_NAME)
        _send_monday(
            to=user.phone,
            text=confirm_msg,
            quick_replies=["Listened", "Later"],
        )

        _save_habit_steps_from_options(
            s,
            user_id=user.id,
            weekly_focus_id=wf.id,
            week_no=label_week,
            krs=krs,
            options_by_index=options_by_index,
        )
        s.commit()

        # Log weekstart touchpoint
        log_touchpoint(
            user_id=user.id,
            tp_type="monday",
            weekly_focus_id=wf.id,
            week_no=label_week,
            kr_ids=kr_ids,
            meta={"notes": notes, "week_no": label_week, "source": "weekstart", "label": "monday"},
            generated_text=actions_message,
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
                    "options": options_by_index,
                    "actions_message": actions_message,
                    "current_idx": 0,
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

        wf_id = state.get("wf_id")
        wf = s.query(WeeklyFocus).get(wf_id) if wf_id else None
        if not wf:
            _set_state(s, user.id, None)
            s.commit()
            start_weekstart(user, debug=debug, set_state=True, week_no=None)
            return
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
        kr_ids = [kr.id for kr in krs]

        mode = state.get("mode")
        debug = bool(state.get("debug"))
        options_by_index = state.get("options") or []
        actions_message = state.get("actions_message") or ""
        needs_refresh = not actions_message or not options_by_index or _any_fallback_options(options_by_index)
        refreshed_options = False
        if needs_refresh:
            if not actions_message or _any_fallback_options(options_by_index):
                fallback_text = _latest_actions_text_from_llm_logs(s, user.id)
                if not fallback_text:
                    fallback_text = _latest_actions_text_from_touchpoints(
                        s,
                        user.id,
                        getattr(wf, "id", None),
                        getattr(wf, "week_no", None),
                    )
                if fallback_text:
                    actions_message = fallback_text
                    state["actions_message"] = actions_message
            if actions_message:
                refreshed = _refresh_options_from_actions_message(actions_message, krs, options_by_index)
                if refreshed != options_by_index:
                    options_by_index = refreshed
                    state["options"] = options_by_index
                    refreshed_options = True
            if (not actions_message or _any_fallback_options(options_by_index)) and krs:
                regen_message, regen_options = _build_weekstart_actions("", krs, user)
                if regen_message:
                    actions_message = regen_message
                    state["actions_message"] = actions_message
                if regen_options:
                    options_by_index = regen_options
                    state["options"] = options_by_index
                    refreshed_options = True
            _set_state(s, user.id, state)
            s.commit()

        if mode == "awaiting_podcast":
            listened = "listened" in lower or "listen" == lower or _is_confirm_message(msg, allow_all_good=True)
            if listened:
                actions_message = state.get("actions_message") or ""
                intro_msg = _extract_intro_from_actions_message(actions_message) or _build_actions_intro()
                if intro_msg and not intro_msg.lower().startswith("*monday*"):
                    intro_msg = "*Monday* " + intro_msg
                _send_monday(to=user.phone, text=intro_msg)
                if krs:
                    if actions_message:
                        parsed = _parse_action_options(actions_message, krs)
                        if parsed:
                            options_by_index = [parsed.get(kr.id, []) for kr in krs]
                        else:
                            options_by_index = _refresh_options_from_actions_message(actions_message, krs, options_by_index)
                    if not options_by_index or _any_fallback_options(options_by_index):
                        _, options_by_index = _build_weekstart_actions("", krs, user)
                    if not options_by_index or not options_by_index[0]:
                        _send_monday(
                            to=user.phone,
                            text="*Monday* Sorry — I couldn’t retrieve the habit options from the prompt. Please try again later.",
                        )
                        return
                    options = options_by_index[0] if options_by_index else []
                    kr_msg = _build_actions_for_kr(1, krs[0], options)
                    if kr_msg and not kr_msg.lower().startswith("*monday*"):
                        kr_msg = "*Monday* " + kr_msg
                    _send_monday(
                        to=user.phone,
                        text=kr_msg,
                        quick_replies=_kr_quick_replies(1, options),
                    )
                _set_state(
                    s,
                    user.id,
                    {
                        "mode": "proposal",
                        "wf_id": wf.id,
                        "kr_ids": kr_ids,
                        "history": state.get("history") or [],
                        "debug": debug,
                        "options": options_by_index,
                        "actions_message": actions_message,
                        "current_idx": 0,
                    },
                )
                s.commit()
                return
            _send_monday(
                to=user.phone,
                text="*Monday* No rush — reply “Listened” when you’re ready.",
                quick_replies=["Listened", "Later"],
            )
            return

        if mode == "proposal":
            if lower.startswith("review"):
                _send_monday(to=user.phone, text="We’re keeping the Nutrition goals as-is for this week. Let’s focus on making them doable.")
            options_by_index = state.get("options") or []
            current_idx = int(state.get("current_idx") or 0)
            stored_selections = _normalize_state_selections(state.get("selections"), krs, options_by_index)
            stored_edits = _normalize_state_edits(state.get("edits"))
            selections = _parse_option_selections(msg, options_by_index)
            if "listened" in lower or lower == "listen":
                if 0 <= current_idx < len(krs):
                    options = options_by_index[current_idx] if current_idx < len(options_by_index) else []
                    kr_msg = _build_actions_for_kr(current_idx + 1, krs[current_idx], options)
                    if kr_msg and not kr_msg.lower().startswith("*monday*"):
                        kr_msg = "*Monday* " + kr_msg
                    _send_monday(
                        to=user.phone,
                        text=kr_msg,
                        quick_replies=_kr_quick_replies(current_idx + 1, options),
                    )
                    return
            if refreshed_options and not selections and not _is_confirm_message(msg):
                if 0 <= current_idx < len(krs):
                    options = options_by_index[current_idx] if current_idx < len(options_by_index) else []
                    kr_msg = _build_actions_for_kr(current_idx + 1, krs[current_idx], options)
                    if kr_msg and not kr_msg.lower().startswith("*monday*"):
                        kr_msg = "*Monday* " + kr_msg
                    _send_monday(
                        to=user.phone,
                        text=kr_msg,
                        quick_replies=_kr_quick_replies(current_idx + 1, options),
                    )
                    return
            if _is_confirm_message(msg):
                # Accept first option for each KR
                all_selected = {idx: 0 for idx in range(len(krs))}
                chosen = _resolve_chosen_steps(krs, options_by_index, all_selected, {})
                edits_to_apply = {kr_id: [step] for kr_id, step in chosen.items()}
                _apply_habit_step_edits(s, user.id, getattr(wf, "id", None), getattr(wf, "week_no", None), edits_to_apply)
                _activate_habit_steps(s, user.id, getattr(wf, "week_no", None), kr_ids)
                s.commit()
                confirm_msg = _confirmation_message(krs, chosen)
                if confirm_msg and not confirm_msg.lower().startswith("*monday*"):
                    confirm_msg = "*Monday* " + confirm_msg
                _send_monday(to=user.phone, text=confirm_msg)
                _set_state(s, user.id, None)
                s.commit()
                general_support.activate(user.id, source="monday", week_no=getattr(wf, "week_no", None), send_intro=True)
                return
            edits = _extract_step_edits(msg, krs)
            if selections or edits:
                # Merge selections and edits into state
                merged_selections = {**stored_selections, **selections}
                merged_edits = {**stored_edits, **edits}

                edits_to_apply: dict[int, list[str]] = {}
                for idx, opt_idx in merged_selections.items():
                    opts = options_by_index[idx] if idx < len(options_by_index) else []
                    if opts and 0 <= opt_idx < len(opts):
                        edits_to_apply[krs[idx].id] = [opts[opt_idx]]
                for kr_id, steps in merged_edits.items():
                    edits_to_apply[kr_id] = steps

                if edits_to_apply:
                    _apply_habit_step_edits(s, user.id, getattr(wf, "id", None), getattr(wf, "week_no", None), edits_to_apply)
                    _activate_habit_steps(s, user.id, getattr(wf, "week_no", None), list(edits_to_apply.keys()))
                    s.commit()

                selected_ids = _selected_kr_ids(krs, merged_selections, merged_edits)
                if selected_ids and len(selected_ids) == len(krs):
                    chosen = _resolve_chosen_steps(krs, options_by_index, merged_selections, merged_edits)
                    confirm_msg = _confirmation_message(krs, chosen)
                    if confirm_msg and not confirm_msg.lower().startswith("*monday*"):
                        confirm_msg = "*Monday* " + confirm_msg
                    _send_monday(to=user.phone, text=confirm_msg)
                    _set_state(s, user.id, None)
                    s.commit()
                    general_support.activate(user.id, source="monday", week_no=getattr(wf, "week_no", None), send_intro=True)
                    return

                if 0 <= current_idx < len(krs):
                    current_kr = krs[current_idx]
                    if current_kr.id in selected_ids:
                        next_idx = current_idx + 1
                        if next_idx < len(krs):
                            options = options_by_index[next_idx] if next_idx < len(options_by_index) else []
                            kr_msg = _build_actions_for_kr(next_idx + 1, krs[next_idx], options)
                            if kr_msg and not kr_msg.lower().startswith("*monday*"):
                                kr_msg = "*Monday* " + kr_msg
                            _send_monday(
                                to=user.phone,
                                text=kr_msg,
                                quick_replies=_kr_quick_replies(next_idx + 1, options),
                            )
                        current_idx = next_idx

                _set_state(
                    s,
                    user.id,
                    {
                        "mode": "proposal",
                        "wf_id": wf.id,
                        "kr_ids": kr_ids,
                        "history": state.get("history") or [],
                        "debug": debug,
                        "options": options_by_index,
                        "selections": merged_selections,
                        "edits": merged_edits,
                        "current_idx": current_idx,
                        "actions_message": state.get("actions_message"),
                    },
                )
                s.commit()
                return
            history = state.get("history") or []
            support_text, history = _support_conversation(history, msg, user, debug)
            if support_text and not support_text.lower().startswith("*monday*"):
                support_text = "*Monday* " + support_text
            _send_monday(to=user.phone, text=support_text)
            _set_state(
                s,
                user.id,
                {
                    "mode": "proposal",
                    "wf_id": wf.id,
                    "kr_ids": kr_ids,
                    "history": history,
                    "debug": debug,
                    "options": options_by_index,
                    "actions_message": state.get("actions_message"),
                    "current_idx": current_idx,
                },
            )
            s.commit()
            return

        if mode == "support":
            history = state.get("history") or []
            edits = _extract_step_edits(msg, krs)
            if edits:
                _apply_habit_step_edits(s, user.id, getattr(wf, "id", None), getattr(wf, "week_no", None), edits)
                s.commit()
            elif _is_confirm_message(msg):
                _activate_habit_steps(s, user.id, getattr(wf, "week_no", None), kr_ids)
                s.commit()
            support_text, new_history = _support_conversation(history, msg, user, debug)
            if support_text and not support_text.lower().startswith("*monday*"):
                support_text = "*Monday* " + support_text
            _send_monday(to=user.phone, text=support_text)
            _set_state(s, user.id, {"mode": "support", "wf_id": wf.id, "kr_ids": kr_ids, "history": new_history, "debug": debug})
            s.commit()
            return

        _set_state(s, user.id, None); s.commit()
        _send_monday(to=user.phone, text="Session reset. Say monday to start your weekly focus.")
