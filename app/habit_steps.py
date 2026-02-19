from __future__ import annotations

import os
import re
from typing import Optional

from sqlalchemy.orm import Session

from . import llm as shared_llm
from .kickoff import COACH_NAME
from .models import OKRKeyResult, OKRKrHabitStep, User
from .prompts import build_prompt, run_llm_prompt


def normalize_text(text: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in text or "").split())


def match_kr_for_label(label: str, krs: list[OKRKeyResult]) -> Optional[OKRKeyResult]:
    label_norm = normalize_text(label)
    if not label_norm:
        return None
    for kr in krs:
        desc_norm = normalize_text(kr.description or "")
        if not desc_norm:
            continue
        if label_norm in desc_norm:
            return kr
    return None


def parse_action_options(text: str, krs: list[OKRKeyResult]) -> dict[int, list[str]]:
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
            or lowered.startswith("here are practical habit step options for next week")
            or lowered.startswith("here are practical habit-step options for next week")
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
                label = header_match.group(2).strip()
                matched = match_kr_for_label(label, krs)
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


def fallback_options_for_kr(kr: OKRKeyResult) -> list[str]:
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


def build_actions_message(krs: list[OKRKeyResult], options_by_kr: dict[int, list[str]]) -> str:
    lines = ["Here are practical habit-step options for next week:"]
    for idx, kr in enumerate(krs, 1):
        lines.append(f"KR{idx}: {kr.description}")
        options = options_by_kr.get(kr.id) or []
        for opt_idx, opt in enumerate(options):
            letter = chr(ord("A") + opt_idx)
            lines.append(f"{idx}{letter}) {opt}")
    lines.append("Tap a button under each KR to choose your habit step.")
    return "\n".join(lines)


def build_actions_for_kr(idx: int, kr: OKRKeyResult, options: list[str]) -> str:
    lines = [f"KR{idx}: {kr.description}"]
    for opt_idx, opt in enumerate(options):
        letter = chr(ord("A") + opt_idx)
        lines.append(f"{letter}) {opt}")
    return "\n".join(lines)


def kr_quick_replies(idx: int, options: list[str]) -> list[str]:
    replies = []
    for opt_idx, _opt in enumerate(options):
        letter = chr(ord("A") + opt_idx)
        replies.append(f"Option {letter}||KR{idx} {letter}")
    return replies


def is_fallback_option_set(options: list[str]) -> bool:
    if len(options) < 3:
        return False
    joined = " ".join(opt.lower() for opt in options if opt)
    return (
        "do one simple step toward this kr" in joined
        and "anchor this kr to one routine" in joined
        and "set one tiny prep step" in joined
    )


def refresh_options_from_actions_message(
    actions_message: str,
    krs: list[OKRKeyResult],
    options_by_index: list[list[str]],
) -> list[list[str]]:
    if not actions_message or not krs:
        return options_by_index
    parsed = parse_action_options(actions_message, krs)
    if not parsed:
        return options_by_index
    refreshed: list[list[str]] = []
    for idx, kr in enumerate(krs):
        current = options_by_index[idx] if idx < len(options_by_index) else []
        parsed_opts = parsed.get(kr.id) or []
        if parsed_opts and (not current or is_fallback_option_set(current)):
            refreshed.append(parsed_opts)
        else:
            refreshed.append(current)
    return refreshed


def any_fallback_options(options_by_index: list[list[str]]) -> bool:
    return any(is_fallback_option_set(opts) for opts in options_by_index if opts)


def _require_week_no(week_no: int | None) -> int:
    try:
        week_i = int(week_no) if week_no is not None else 0
    except Exception as exc:
        raise ValueError("week_no is required for habit_steps_generator") from exc
    if week_i <= 0:
        raise ValueError("week_no is required for habit_steps_generator")
    return week_i


def build_sunday_habit_actions(
    transcript: Optional[str],
    krs: list[OKRKeyResult],
    user: User,
    *,
    week_no: int | None,
) -> tuple[str, list[list[str]]]:
    transcript = (transcript or "").strip()
    week_i = _require_week_no(week_no)
    client = getattr(shared_llm, "_llm", None)
    options_by_kr: dict[int, list[str]] = {kr.id: [] for kr in krs}
    llm_text = None
    allow_fallback = os.getenv("WEEKSTART_ALLOW_FALLBACK", "0").strip().lower() in {"1", "true", "yes"}
    if client:
        try:
            prompt_krs = [
                {
                    "id": int(kr.id),
                    "description": (kr.description or "").strip(),
                    "pillar": (getattr(getattr(kr, "objective", None), "pillar_key", None) or "").strip().lower(),
                }
                for kr in krs
                if getattr(kr, "id", None)
            ]
            prompt_assembly = build_prompt(
                "habit_steps_generator",
                user_id=user.id,
                coach_name=COACH_NAME,
                user_name=(user.first_name or ""),
                locale=getattr(user, "tz", "UK") or "UK",
                transcript=transcript,
                week_no=week_i,
                krs=prompt_krs or [kr.description for kr in krs],
            )
            txt = run_llm_prompt(
                prompt_assembly.text,
                user_id=user.id,
                touchpoint="habit_steps_generator",
                prompt_variant=prompt_assembly.variant,
                task_label=prompt_assembly.task_label,
                prompt_blocks={**prompt_assembly.blocks, **(prompt_assembly.meta or {})},
                block_order=prompt_assembly.block_order,
                log=True,
            )
            txt = (txt or "").strip()
            if txt:
                llm_text = txt
                parsed = parse_action_options(txt, krs)
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
            options = fallback_options_for_kr(kr)
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
    message = llm_text or (build_actions_message(krs, options_by_kr) if allow_fallback else "")
    options_by_index = [options_by_kr.get(kr.id, []) for kr in krs]
    return message, options_by_index


def build_weekstart_actions(
    transcript: Optional[str],
    krs: list[OKRKeyResult],
    user: User,
    *,
    week_no: int | None,
) -> tuple[str, list[list[str]]]:
    # Backward-compatible alias used by existing callers/tests.
    return build_sunday_habit_actions(transcript, krs, user, week_no=week_no)


def extract_action_lines(summary: str) -> list[str]:
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


def parse_option_selections(message: str, options_by_index: list[list[str]]) -> dict[int, int]:
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


def normalize_state_selections(
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


def normalize_state_edits(edits: dict | None) -> dict[int, list[str]]:
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


def selected_kr_ids(
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


def resolve_chosen_steps(
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


def confirmation_message(krs: list[OKRKeyResult], chosen_steps: dict[int, str]) -> str:
    lines = ["Agreed habit steps for this week:"]
    for idx, kr in enumerate(krs, 1):
        step = chosen_steps.get(kr.id)
        if step:
            lines.append(f"{idx}) {step}")
    return "\n".join(lines)


def extract_step_edits(message: str, krs: list[OKRKeyResult]) -> dict[int, list[str]]:
    edits: dict[int, list[str]] = {}
    lines = extract_action_lines(message or "")
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
            kr = match_kr_for_label(label, krs)
            text_val = action or text_val
        if kr is None and len(krs) == 1:
            kr = krs[0]
        if kr and text_val:
            edits.setdefault(kr.id, []).append(text_val)
    return edits


def apply_habit_step_edits(
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


def activate_habit_steps(
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


def is_confirm_message(text: str, *, allow_all_good: bool = False) -> bool:
    cleaned = normalize_text(text)
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
