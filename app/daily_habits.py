from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select

from .db import SessionLocal, engine
from .models import DailyCoachHabitPlan, OKRKeyResult, OKRKrHabitStep, OKRObjective, User
from .pillar_tracker import get_pillar_tracker_detail, get_pillar_tracker_summary, tracker_today
from .prompts import build_prompt, ensure_builtin_prompt_templates, run_llm_prompt

_DAILY_HABITS_SCHEMA_READY = False
_PILLAR_ORDER = ("nutrition", "training", "resilience", "recovery")


def ensure_daily_habit_plan_schema() -> None:
    global _DAILY_HABITS_SCHEMA_READY
    if _DAILY_HABITS_SCHEMA_READY:
        return
    try:
        DailyCoachHabitPlan.__table__.create(bind=engine, checkfirst=True)
        _DAILY_HABITS_SCHEMA_READY = True
    except Exception:
        _DAILY_HABITS_SCHEMA_READY = False
        raise


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _pillar_rank(pillar_key: str) -> int:
    token = str(pillar_key or "").strip().lower()
    try:
        return _PILLAR_ORDER.index(token)
    except Exception:
        return len(_PILLAR_ORDER) + 1


def _today_iso() -> str:
    return tracker_today().isoformat()


def _load_user_name(user_id: int) -> str:
    with SessionLocal() as s:
        user = s.get(User, int(user_id))
        first_name = str(getattr(user, "first_name", "") or "").strip() if user else ""
    return first_name or "User"


def _load_pillar_okr_context(user_id: int, pillar_key: str) -> dict[str, Any]:
    with SessionLocal() as s:
        objective = (
            s.execute(
                select(OKRObjective)
                .where(
                    OKRObjective.owner_user_id == int(user_id),
                    OKRObjective.pillar_key == str(pillar_key or "").strip().lower(),
                )
                .order_by(desc(OKRObjective.created_at), desc(OKRObjective.id))
            )
            .scalars()
            .first()
        )
        if objective is None:
            return {"objective": None, "krs": [], "habit_steps": []}
        krs = (
            s.execute(
                select(OKRKeyResult)
                .where(OKRKeyResult.objective_id == int(objective.id))
                .order_by(desc(OKRKeyResult.updated_at), desc(OKRKeyResult.id))
            )
            .scalars()
            .all()
        )
        kr_ids = [int(getattr(row, "id", 0) or 0) for row in krs if getattr(row, "id", None)]
        habit_rows = []
        if kr_ids:
            habit_rows = (
                s.execute(
                    select(OKRKrHabitStep)
                    .where(
                        OKRKrHabitStep.user_id == int(user_id),
                        OKRKrHabitStep.kr_id.in_(kr_ids),
                        OKRKrHabitStep.status != "archived",
                    )
                    .order_by(
                        OKRKrHabitStep.week_no.desc().nullslast(),
                        OKRKrHabitStep.sort_order.asc(),
                        OKRKrHabitStep.id.asc(),
                    )
                )
                .scalars()
                .all()
            )
    return {
        "objective": str(getattr(objective, "objective", "") or "").strip() if objective else None,
        "krs": [
            {
                "id": int(getattr(row, "id", 0) or 0),
                "description": str(getattr(row, "description", "") or "").strip(),
                "metric_label": str(getattr(row, "metric_label", "") or "").strip() or None,
                "target_num": getattr(row, "target_num", None),
                "unit": str(getattr(row, "unit", "") or "").strip() or None,
                "status": str(getattr(row, "status", "") or "").strip() or None,
            }
            for row in krs[:4]
            if str(getattr(row, "description", "") or "").strip()
        ],
        "habit_steps": [
            str(getattr(row, "step_text", "") or "").strip()
            for row in habit_rows[:5]
            if str(getattr(row, "step_text", "") or "").strip()
        ],
    }


def _select_weakest_pillar(summary: dict[str, Any]) -> dict[str, Any]:
    pillars = list(summary.get("pillars") or [])
    if not pillars:
        return {"pillar_key": "nutrition", "label": "Nutrition", "score": None}

    def _sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
        score = _safe_int(row.get("score"))
        return (
            score if score is not None else 999,
            _pillar_rank(str(row.get("pillar_key") or "")),
            0,
        )

    return sorted(pillars, key=_sort_key)[0]


def _recent_concept_focuses(detail: dict[str, Any], today: date) -> list[dict[str, Any]]:
    today_iso = today.isoformat()
    yesterday_iso = (today - timedelta(days=1)).isoformat()
    focus_rows: list[dict[str, Any]] = []
    for concept in detail.get("concepts") or []:
        week_rows = {
            str((row or {}).get("date") or "").strip(): row
            for row in (concept.get("week") or [])
            if isinstance(row, dict)
        }
        today_row = week_rows.get(today_iso) or {}
        yesterday_row = week_rows.get(yesterday_iso) or {}
        misses = sum(
            1
            for row in (today_row, yesterday_row)
            if isinstance(row, dict) and row.get("target_met") is False
        )
        missing = sum(
            1
            for row in (today_row, yesterday_row)
            if not isinstance(row, dict) or row.get("target_met") is None
        )
        latest_value = str(
            (today_row if today_row.get("value_label") else yesterday_row).get("value_label") or ""
        ).strip() or None
        signal = "on_track"
        if today_row.get("target_met") is False:
            signal = "missed_today"
        elif yesterday_row.get("target_met") is False:
            signal = "missed_yesterday"
        elif today_row.get("target_met") is None:
            signal = "not_logged_today"
        focus_rows.append(
            {
                "concept_key": str(concept.get("concept_key") or "").strip(),
                "label": str(concept.get("label") or "").strip(),
                "helper": str(concept.get("helper") or "").strip(),
                "target_label": str(concept.get("target_label") or "").strip() or None,
                "signal": signal,
                "misses": misses,
                "missing": missing,
                "latest_value": latest_value,
            }
        )
    focus_rows.sort(
        key=lambda item: (
            -int(item.get("misses") or 0),
            -int(item.get("missing") or 0),
            str(item.get("label") or ""),
        )
    )
    return focus_rows[:3]


def _build_generation_context(user_id: int) -> dict[str, Any]:
    today = tracker_today()
    summary = get_pillar_tracker_summary(user_id, anchor=today)
    weakest = _select_weakest_pillar(summary)
    pillar_key = str(weakest.get("pillar_key") or "nutrition").strip().lower()
    detail = get_pillar_tracker_detail(user_id, pillar_key, anchor=today)
    okr_context = _load_pillar_okr_context(user_id, pillar_key)
    pillars_payload = [
        {
            "pillar_key": str(item.get("pillar_key") or "").strip(),
            "label": str(item.get("label") or "").strip(),
            "score": _safe_int(item.get("score")),
            "tracker_score": _safe_int(item.get("tracker_score")),
            "baseline_score": _safe_int(item.get("baseline_score")),
        }
        for item in (summary.get("pillars") or [])
    ]
    return {
        "user_name": _load_user_name(user_id),
        "plan_date": today.isoformat(),
        "weakest_pillar": {
            "pillar_key": pillar_key,
            "label": str(weakest.get("label") or "").strip() or pillar_key.title(),
            "score": _safe_int(weakest.get("score")),
            "tracker_score": _safe_int(weakest.get("tracker_score")),
            "baseline_score": _safe_int(weakest.get("baseline_score")),
        },
        "pillar_scores": pillars_payload,
        "focus_concepts": _recent_concept_focuses(detail, today),
        "okr_context": okr_context,
    }


def _context_hash(context: dict[str, Any]) -> str:
    payload = json.dumps(context, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _normalize_habit_item(raw: Any) -> dict[str, str] | None:
    if isinstance(raw, str):
        title = raw.strip()
        if not title:
            return None
        return {"title": title[:90], "detail": ""}
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or raw.get("habit") or "").strip()
    detail = str(raw.get("detail") or raw.get("why") or raw.get("note") or "").strip()
    if not title and detail:
        title, detail = detail[:90], ""
    if not title:
        return None
    return {"title": title[:90], "detail": detail[:180]}


def _fallback_habit_for_concept(concept: dict[str, Any], pillar_key: str) -> dict[str, str]:
    target_label = str(concept.get("target_label") or "").strip()
    concept_key = str(concept.get("concept_key") or "").strip().lower()
    label = str(concept.get("label") or "").strip() or "Habit"
    fallback_map = {
        "protein_intake": ("Add protein to your next meal", target_label or "Aim for a stronger protein spread through the day."),
        "fruit_veg": ("Add colour to two meals today", target_label or "Build in at least one extra fruit or veg portion."),
        "hydration": ("Finish one full bottle early", target_label or "Keep water visible and top it up twice today."),
        "processed_food": ("Swap one processed snack today", target_label or "Make one whole-food swap before the day ends."),
        "cardio_frequency": ("Fit in one cardio block today", target_label or "A brisk 20-minute walk counts."),
        "strength_training": ("Complete a short strength session", target_label or "Even one focused block moves this forward."),
        "flexibility_mobility": ("Do 10 minutes of mobility", target_label or "Use it as a reset before bed or after work."),
        "emotional_regulation": ("Take one reset pause today", "Use breathing or a short walk before your busiest moment."),
        "positive_connection": ("Create one positive connection", "Check in with someone or take 10 minutes for yourself."),
        "stress_recovery": ("Use one recovery tool today", "Schedule a short reset before stress spikes."),
        "optimism_perspective": ("Reframe one difficult moment", "Write one constructive response before the day ends."),
        "support_openness": ("Ask for one bit of support", "Be clear about one thing you need today."),
        "sleep_duration": ("Protect 7+ hours tonight", target_label or "Set your stop time early enough for full sleep."),
        "sleep_quality": ("Build a calmer wind-down tonight", "Keep the final 30 minutes low-stimulation."),
        "bedtime_consistency": ("Set a bedtime alarm tonight", "Start winding down at the same time as yesterday."),
    }
    title, detail = fallback_map.get(
        concept_key,
        (
            f"Take one {label.lower()} step today",
            target_label or f"Choose one action that supports your {pillar_key} score today.",
        ),
    )
    return {"title": title, "detail": detail}


def _fallback_plan(context: dict[str, Any]) -> dict[str, Any]:
    weakest = context.get("weakest_pillar") or {}
    pillar_key = str(weakest.get("pillar_key") or "nutrition").strip().lower()
    pillar_label = str(weakest.get("label") or "").strip() or pillar_key.title()
    habits: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for step in (context.get("okr_context") or {}).get("habit_steps") or []:
        text = str(step or "").strip()
        if not text:
            continue
        title = text[:90]
        key = title.lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        habits.append({"title": title, "detail": "Keep this practical and doable today."})
        if len(habits) >= 2:
            break
    for concept in context.get("focus_concepts") or []:
        item = _fallback_habit_for_concept(concept, pillar_key)
        key = str(item.get("title") or "").strip().lower()
        if not key or key in seen_titles:
            continue
        seen_titles.add(key)
        habits.append(item)
        if len(habits) >= 5:
            break
    if not habits:
        habits = [
            {
                "title": f"Take one {pillar_label.lower()} step today",
                "detail": "Choose a small action you can complete before the day ends.",
            }
        ]
    return {
        "title": f"Today's {pillar_label} habits",
        "summary": f"These steps focus on your lowest-scoring pillar right now: {pillar_label}.",
        "habits": habits[:5],
        "source": "fallback",
    }


def _generate_plan_from_llm(user_id: int, context: dict[str, Any]) -> dict[str, Any] | None:
    weakest = context.get("weakest_pillar") or {}
    user_name = str(context.get("user_name") or "User").strip() or "User"
    ensure_builtin_prompt_templates(["daily_habit_plan"])
    assembly = build_prompt(
        "daily_habit_plan",
        user_id=user_id,
        coach_name="HealthSense",
        user_name=user_name,
        locale="UK",
        timeframe="today",
        plan_date=context.get("plan_date"),
        scores=context.get("pillar_scores") or [],
        weakest_pillar=context.get("weakest_pillar") or {},
        focus_concepts=context.get("focus_concepts") or [],
        okr_context=context.get("okr_context") or {},
    )
    prompt = assembly.text
    raw = run_llm_prompt(
        prompt,
        user_id=user_id,
        touchpoint="daily_habit_plan",
        prompt_variant=assembly.variant,
        task_label=assembly.task_label,
        context_meta={
            "page": "coach_home",
            "pillar_key": str(weakest.get("pillar_key") or "").strip().lower(),
            "plan_date": _today_iso(),
        },
        prompt_blocks=assembly.blocks,
        block_order=assembly.block_order,
    )
    parsed = _extract_json_object(raw)
    if not parsed:
        return None
    habits = [
        item
        for item in (_normalize_habit_item(row) for row in (parsed.get("habits") or []))
        if item
    ][:5]
    if len(habits) < 3:
        return None
    title = str(parsed.get("title") or "").strip() or f"Today's {str(weakest.get('label') or 'habit').strip()} habits"
    summary = str(parsed.get("summary") or "").strip() or f"Today's focus is {str(weakest.get('label') or 'your lowest pillar').strip()}."
    return {
        "title": title[:200],
        "summary": summary[:500],
        "habits": habits,
        "source": "llm",
    }


def _serialize_plan(row: DailyCoachHabitPlan) -> dict[str, Any]:
    return {
        "user_id": int(getattr(row, "user_id", 0) or 0),
        "plan_date": getattr(row, "plan_date", None).isoformat() if getattr(row, "plan_date", None) else None,
        "pillar_key": str(getattr(row, "pillar_key", "") or "").strip() or None,
        "pillar_label": str(getattr(row, "pillar_label", "") or "").strip() or None,
        "title": str(getattr(row, "title", "") or "").strip() or None,
        "summary": str(getattr(row, "summary", "") or "").strip() or None,
        "habits": list(getattr(row, "habits", None) or []),
        "source": str(getattr(row, "source", "") or "").strip() or None,
        "generated_at": getattr(row, "generated_at", None).isoformat() if getattr(row, "generated_at", None) else None,
    }


def get_or_generate_daily_habit_plan(user_id: int, *, force: bool = False) -> dict[str, Any]:
    ensure_daily_habit_plan_schema()
    today = tracker_today()
    context = _build_generation_context(user_id)
    hash_value = _context_hash(context)
    with SessionLocal() as s:
        existing = (
            s.execute(
                select(DailyCoachHabitPlan)
                .where(
                    DailyCoachHabitPlan.user_id == int(user_id),
                    DailyCoachHabitPlan.plan_date == today,
                )
                .order_by(desc(DailyCoachHabitPlan.id))
            )
            .scalars()
            .first()
        )
        if existing and not force and str(getattr(existing, "context_hash", "") or "") == hash_value:
            return _serialize_plan(existing)

        generated = _generate_plan_from_llm(user_id, context) or _fallback_plan(context)
        row = existing or DailyCoachHabitPlan(user_id=int(user_id), plan_date=today)
        row.pillar_key = str((context.get("weakest_pillar") or {}).get("pillar_key") or "").strip() or None
        row.pillar_label = str((context.get("weakest_pillar") or {}).get("label") or "").strip() or None
        row.title = str(generated.get("title") or "").strip() or None
        row.summary = str(generated.get("summary") or "").strip() or None
        row.habits = list(generated.get("habits") or [])
        row.source = str(generated.get("source") or "fallback").strip() or "fallback"
        row.context_hash = hash_value
        row.context_payload = context
        row.generated_at = datetime.utcnow().replace(microsecond=0)
        s.add(row)
        s.commit()
        s.refresh(row)
        return _serialize_plan(row)
