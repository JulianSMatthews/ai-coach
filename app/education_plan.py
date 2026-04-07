from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, desc, inspect, select, text
from sqlalchemy.schema import CreateColumn

from .coach_insight import _library_avatar_payload
from .daily_habits import build_daily_tracker_generation_context_snapshot
from .db import SessionLocal, engine
from .models import (
    AssessmentRun,
    ContentLibraryItem,
    EducationLessonVariant,
    EducationProgramme,
    EducationProgrammeDay,
    EducationQuiz,
    EducationQuizQuestion,
    PillarResult,
    UserEducationConceptLevel,
    UserEducationDayProgress,
    UserEducationPlan,
    UserEducationQuizAnswer,
)
from .okr import _normalize_concept_key
from .pillar_tracker import tracker_today

_EDUCATION_PLAN_SCHEMA_READY = False
_DEFAULT_PROGRAMME_DURATION_DAYS = 21
_WATCH_COMPLETE_THRESHOLD_PCT = 80.0
_QUIZ_LOW_SCORE_PCT = 50.0
_QUIZ_HIGH_SCORE_PCT = 85.0
_LEVEL_PRIORITY = ("support", "foundation", "build", "perform")

_EDUCATION_SCHEMA_TABLES = (
    EducationProgramme.__table__,
    EducationProgrammeDay.__table__,
    EducationLessonVariant.__table__,
    EducationQuiz.__table__,
    EducationQuizQuestion.__table__,
    UserEducationPlan.__table__,
    UserEducationConceptLevel.__table__,
    UserEducationDayProgress.__table__,
    UserEducationQuizAnswer.__table__,
)

_EDUCATION_SCHEMA_INDEX_SQL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_education_programmes_code ON education_programmes(code);",
    "CREATE INDEX IF NOT EXISTS ix_education_programmes_pillar_active ON education_programmes(pillar_key, is_active);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_education_programme_days_programme_day ON education_programme_days(programme_id, day_index);",
    "CREATE INDEX IF NOT EXISTS ix_education_programme_days_programme_concept ON education_programme_days(programme_id, concept_key);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_education_lesson_variants_day_level ON education_lesson_variants(programme_day_id, level);",
    "CREATE INDEX IF NOT EXISTS ix_education_lesson_variants_day_active ON education_lesson_variants(programme_day_id, is_active);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_education_quiz_questions_quiz_order ON education_quiz_questions(quiz_id, question_order);",
    "CREATE INDEX IF NOT EXISTS ix_user_education_plans_user_status ON user_education_plans(user_id, status);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_education_concept_levels_user_concept ON user_education_concept_levels(user_id, pillar_key, concept_key);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_education_day_progress_plan_date ON user_education_day_progress(user_plan_id, lesson_date);",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_user_education_quiz_answers_progress_question ON user_education_quiz_answers(user_day_progress_id, question_id);",
)


def _ensure_table_columns(table) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(table.name):
        return
    existing_columns = {
        str(column.get("name") or "").strip().lower()
        for column in inspector.get_columns(table.name)
    }
    missing_columns = [
        column
        for column in table.columns
        if str(column.name or "").strip().lower() not in existing_columns
    ]
    if not missing_columns:
        return
    with engine.begin() as conn:
        dialect = str(getattr(conn.dialect, "name", "") or "").strip().lower()
        for column in missing_columns:
            column_sql = str(CreateColumn(column).compile(dialect=conn.dialect)).strip()
            if not column_sql:
                continue
            if dialect == "postgresql":
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN IF NOT EXISTS {column_sql};"))
            else:
                conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {column_sql};"))


def ensure_education_plan_schema() -> None:
    global _EDUCATION_PLAN_SCHEMA_READY
    if _EDUCATION_PLAN_SCHEMA_READY:
        return
    try:
        for table in _EDUCATION_SCHEMA_TABLES:
            table.create(bind=engine, checkfirst=True)
        for table in _EDUCATION_SCHEMA_TABLES:
            _ensure_table_columns(table)
        with engine.begin() as conn:
            for sql in _EDUCATION_SCHEMA_INDEX_SQL:
                conn.execute(text(sql))
        _EDUCATION_PLAN_SCHEMA_READY = True
    except Exception:
        _EDUCATION_PLAN_SCHEMA_READY = False
        raise


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(round(float(value)))
    except Exception:
        return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _now_utc() -> datetime:
    return datetime.utcnow().replace(microsecond=0)


def _pillar_label(pillar_key: str | None) -> str:
    token = str(pillar_key or "").strip().lower()
    lookup = {
        "nutrition": "Nutrition",
        "training": "Training",
        "resilience": "Resilience",
        "recovery": "Recovery",
    }
    return lookup.get(token, token.title() or "Education")


def _normalize_level(value: Any) -> str:
    token = str(value or "").strip().lower()
    if token in _LEVEL_PRIORITY:
        return token
    return "build"


def _latest_assessment_run(session, user_id: int) -> AssessmentRun | None:
    return (
        session.execute(
            select(AssessmentRun)
            .where(AssessmentRun.user_id == int(user_id))
            .order_by(desc(AssessmentRun.finished_at), desc(AssessmentRun.id))
        )
        .scalars()
        .first()
    )


def _assessment_snapshot(session, user_id: int) -> dict[str, Any]:
    run = _latest_assessment_run(session, int(user_id))
    pillar_results = (
        session.execute(
            select(PillarResult)
            .where(PillarResult.user_id == int(user_id))
            .order_by(desc(PillarResult.run_id), desc(PillarResult.id))
        )
        .scalars()
        .all()
    )
    latest_by_pillar: dict[str, PillarResult] = {}
    if run is not None:
        for row in pillar_results:
            if int(getattr(row, "run_id", 0) or 0) != int(run.id):
                continue
            pillar_key = str(getattr(row, "pillar_key", "") or "").strip().lower()
            if pillar_key and pillar_key not in latest_by_pillar:
                latest_by_pillar[pillar_key] = row
    return {
        "run": run,
        "pillars": latest_by_pillar,
    }


def _find_tracker_pillar(context: dict[str, Any], pillar_key: str) -> dict[str, Any] | None:
    token = str(pillar_key or "").strip().lower()
    for pillar in context.get("tracker_review") or []:
        if not isinstance(pillar, dict):
            continue
        if str(pillar.get("pillar_key") or "").strip().lower() == token:
            return pillar
    return None


def _find_tracker_concept(context: dict[str, Any], pillar_key: str, concept_key: str) -> dict[str, Any] | None:
    pillar = _find_tracker_pillar(context, pillar_key)
    token = _normalize_concept_key(concept_key) or ""
    for concept in (pillar or {}).get("concepts") or []:
        if not isinstance(concept, dict):
            continue
        if str(concept.get("concept_key") or "").strip().lower() == token:
            return concept
    return None


def _assessment_concept_score(snapshot: dict[str, Any], pillar_key: str, concept_key: str) -> float | None:
    pillar = (snapshot.get("pillars") or {}).get(str(pillar_key or "").strip().lower())
    if pillar is None:
        return None
    concept_scores = getattr(pillar, "concept_scores", None)
    if not isinstance(concept_scores, dict):
        return None
    token = _normalize_concept_key(concept_key) or str(concept_key or "").strip().lower()
    if token in concept_scores:
        return _safe_float(concept_scores.get(token))
    for raw_key, raw_value in concept_scores.items():
        if _normalize_concept_key(raw_key) == token:
            return _safe_float(raw_value)
    return None


def _assessment_pillar_score(snapshot: dict[str, Any], pillar_key: str) -> float | None:
    pillar = (snapshot.get("pillars") or {}).get(str(pillar_key or "").strip().lower())
    return _safe_float(getattr(pillar, "overall", None)) if pillar is not None else None


def _starting_level_for_score(score: float | None) -> str:
    if score is None:
        return "build"
    if score < 45:
        return "foundation"
    if score >= 80:
        return "perform"
    return "build"


def _current_level_for_context(
    *,
    pillar_key: str,
    pillar_state: str | None,
    concept_signal: str | None,
    assessment_score: float | None,
) -> str:
    state = str(pillar_state or "").strip().lower()
    signal = str(concept_signal or "").strip().lower()
    if signal in {"missed_today", "missed_yesterday"}:
        if str(pillar_key or "").strip().lower() in {"recovery", "resilience"}:
            return "support"
        if assessment_score is not None and assessment_score < 45:
            return "support"
        return "foundation"
    if state == "weak":
        return "foundation"
    if assessment_score is not None and assessment_score >= 80 and signal in {"on_track", ""}:
        return "perform"
    if assessment_score is not None and assessment_score < 45:
        return "foundation"
    return "build"


def _variant_level_candidates(level: str) -> list[str]:
    current = _normalize_level(level)
    ordered = [current]
    for candidate in ("build", "foundation", "perform", "support"):
        if candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _content_payload(item: ContentLibraryItem | None) -> dict[str, Any] | None:
    if item is None:
        return None
    avatar = _library_avatar_payload(item)
    return {
        "id": int(getattr(item, "id", 0) or 0),
        "pillar_key": str(getattr(item, "pillar_key", "") or "").strip() or None,
        "concept_code": str(getattr(item, "concept_code", "") or "").strip() or None,
        "title": str(getattr(item, "title", "") or "").strip() or None,
        "body": str(getattr(item, "body", "") or "").strip() or None,
        "video_url": str(getattr(item, "podcast_url", "") or "").strip() or None,
        "podcast_url": str(getattr(item, "podcast_url", "") or "").strip() or None,
        "avatar": avatar,
        "level": str(getattr(item, "level", "") or "").strip() or None,
        "created_at": getattr(item, "created_at", None).isoformat() if getattr(item, "created_at", None) else None,
    }


def _quiz_question_payload(row: EducationQuizQuestion) -> dict[str, Any]:
    return {
        "id": int(getattr(row, "id", 0) or 0),
        "order": int(getattr(row, "question_order", 0) or 0),
        "question_text": str(getattr(row, "question_text", "") or "").strip(),
        "answer_type": str(getattr(row, "answer_type", "") or "").strip(),
        "options": list(getattr(row, "options_json", None) or []),
        "explanation": str(getattr(row, "explanation", "") or "").strip() or None,
    }


def _normalize_answer_payload(value: Any) -> Any:
    if isinstance(value, list):
        return [_normalize_answer_payload(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_answer_payload(item) for item in value]
    if isinstance(value, dict):
        return {
            str(key): _normalize_answer_payload(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, str):
        return value.strip()
    return value


def _answers_equal(expected: Any, actual: Any) -> bool:
    left = _normalize_answer_payload(expected)
    right = _normalize_answer_payload(actual)
    if isinstance(left, list) and isinstance(right, list):
        return sorted(left, key=lambda item: str(item)) == sorted(right, key=lambda item: str(item))
    return left == right


def _calculate_streaks(session, user_plan_id: int) -> tuple[int, int]:
    rows = (
        session.execute(
            select(UserEducationDayProgress.lesson_date)
            .where(
                UserEducationDayProgress.user_plan_id == int(user_plan_id),
                UserEducationDayProgress.completed_at.isnot(None),
            )
            .order_by(UserEducationDayProgress.lesson_date.asc())
        )
        .scalars()
        .all()
    )
    dates = sorted({row for row in rows if isinstance(row, date)})
    if not dates:
        return 0, 0
    best = 0
    running = 0
    previous: date | None = None
    for current in dates:
        if previous is None or current == previous + timedelta(days=1):
            running += 1
        else:
            running = 1
        best = max(best, running)
        previous = current
    anchor = tracker_today()
    current = 0
    cursor = anchor
    date_set = set(dates)
    while cursor in date_set:
        current += 1
        cursor -= timedelta(days=1)
    if current == 0:
        cursor = anchor - timedelta(days=1)
        while cursor in date_set:
            current += 1
            cursor -= timedelta(days=1)
    return current, best


def _sync_plan_streaks(session, plan: UserEducationPlan) -> None:
    current, best = _calculate_streaks(session, int(plan.id))
    plan.current_streak_days = int(current)
    plan.best_streak_days = max(int(getattr(plan, "best_streak_days", 0) or 0), int(best))
    session.add(plan)


def _resolve_plan_date(anchor: date | None) -> date:
    return anchor if isinstance(anchor, date) else tracker_today()


def _select_programme(session, pillar_key: str | None) -> EducationProgramme | None:
    if pillar_key:
        row = (
            session.execute(
                select(EducationProgramme)
                .where(
                    EducationProgramme.is_active.is_(True),
                    EducationProgramme.pillar_key == str(pillar_key).strip().lower(),
                )
                .order_by(desc(EducationProgramme.updated_at), desc(EducationProgramme.id))
            )
            .scalars()
            .first()
        )
        if row is not None:
            return row
    return (
        session.execute(
            select(EducationProgramme)
            .where(EducationProgramme.is_active.is_(True))
            .order_by(desc(EducationProgramme.updated_at), desc(EducationProgramme.id))
        )
        .scalars()
        .first()
    )


def _resolve_programme_day(session, programme_id: int, day_index: int) -> EducationProgrammeDay | None:
    row = (
        session.execute(
            select(EducationProgrammeDay)
            .where(
                EducationProgrammeDay.programme_id == int(programme_id),
                EducationProgrammeDay.day_index == int(day_index),
            )
            .order_by(desc(EducationProgrammeDay.id))
        )
        .scalars()
        .first()
    )
    if row is not None:
        return row
    return (
        session.execute(
            select(EducationProgrammeDay)
            .where(
                EducationProgrammeDay.programme_id == int(programme_id),
                EducationProgrammeDay.day_index <= int(day_index),
            )
            .order_by(desc(EducationProgrammeDay.day_index), desc(EducationProgrammeDay.id))
        )
        .scalars()
        .first()
    )


def _resolve_lesson_variant(
    session,
    programme_day_id: int,
    resolved_level: str,
) -> EducationLessonVariant | None:
    rows = (
        session.execute(
            select(EducationLessonVariant)
            .where(
                EducationLessonVariant.programme_day_id == int(programme_day_id),
                EducationLessonVariant.is_active.is_(True),
            )
            .order_by(desc(EducationLessonVariant.updated_at), desc(EducationLessonVariant.id))
        )
        .scalars()
        .all()
    )
    if not rows:
        return None
    by_level = {
        _normalize_level(getattr(row, "level", None)): row
        for row in rows
    }
    for candidate in _variant_level_candidates(resolved_level):
        if candidate in by_level:
            return by_level[candidate]
    return rows[0]


def _get_or_create_concept_level(
    session,
    *,
    user_id: int,
    pillar_key: str,
    concept_key: str,
    assessment_score: float | None,
    tracker_state: dict[str, Any] | None,
) -> UserEducationConceptLevel:
    row = (
        session.execute(
            select(UserEducationConceptLevel)
            .where(
                UserEducationConceptLevel.user_id == int(user_id),
                UserEducationConceptLevel.pillar_key == str(pillar_key).strip().lower(),
                UserEducationConceptLevel.concept_key == str(concept_key).strip().lower(),
            )
            .order_by(desc(UserEducationConceptLevel.updated_at), desc(UserEducationConceptLevel.id))
        )
        .scalars()
        .first()
    )
    pillar_state = str((tracker_state or {}).get("pillar_state") or "").strip().lower()
    concept_signal = str((tracker_state or {}).get("signal") or "").strip().lower()
    starting_level = _starting_level_for_score(assessment_score)
    current_level = _current_level_for_context(
        pillar_key=pillar_key,
        pillar_state=pillar_state,
        concept_signal=concept_signal,
        assessment_score=assessment_score,
    )
    if row is None:
        row = UserEducationConceptLevel(
            user_id=int(user_id),
            pillar_key=str(pillar_key).strip().lower(),
            concept_key=str(concept_key).strip().lower(),
            starting_level=starting_level,
            current_level=current_level,
        )
    row.starting_level = str(getattr(row, "starting_level", None) or starting_level)
    row.current_level = current_level
    row.assessment_score_snapshot = assessment_score
    row.tracker_state_json = tracker_state or None
    row.last_recomputed_at = _now_utc()
    session.add(row)
    session.flush()
    return row


def _get_or_create_active_plan(
    session,
    *,
    user_id: int,
    plan_date: date,
    context: dict[str, Any],
    context_hash: str,
) -> tuple[UserEducationPlan | None, EducationProgramme | None]:
    existing = (
        session.execute(
            select(UserEducationPlan)
            .where(
                UserEducationPlan.user_id == int(user_id),
                UserEducationPlan.status == "active",
            )
            .order_by(desc(UserEducationPlan.updated_at), desc(UserEducationPlan.id))
        )
        .scalars()
        .first()
    )
    programme: EducationProgramme | None = None
    if existing is not None:
        programme = session.get(EducationProgramme, int(existing.programme_id))
        if programme is None or not bool(getattr(programme, "is_active", False)):
            existing.status = "paused"
            session.add(existing)
            session.flush()
            existing = None
            programme = None
    if existing is None:
        weakest = context.get("weakest_pillar") if isinstance(context.get("weakest_pillar"), dict) else {}
        preferred_pillar = str((weakest or {}).get("pillar_key") or "").strip().lower() or None
        programme = _select_programme(session, preferred_pillar)
        if programme is None:
            return None, None
        snapshot = _assessment_snapshot(session, int(user_id))
        run = snapshot.get("run")
        existing = UserEducationPlan(
            user_id=int(user_id),
            programme_id=int(programme.id),
            pillar_key=str(getattr(programme, "pillar_key", "") or "").strip().lower() or "nutrition",
            starts_on=plan_date,
            current_day_index=1,
            status="active",
            source_assessment_run_id=int(getattr(run, "id", 0) or 0) or None,
            initial_context_json={
                "created_from": "education_plan",
                "weakest_pillar": context.get("weakest_pillar"),
                "tracker_focus_source": context.get("tracker_focus_source"),
            },
            last_context_hash=context_hash or None,
            last_refreshed_at=_now_utc(),
        )
        session.add(existing)
        session.flush()
    duration_days = int(getattr(programme, "duration_days", 0) or 0) if programme is not None else 0
    duration_days = duration_days if duration_days > 0 else _DEFAULT_PROGRAMME_DURATION_DAYS
    elapsed = max(0, (plan_date - existing.starts_on).days)
    existing.current_day_index = min(duration_days, elapsed + 1)
    existing.last_context_hash = context_hash or None
    existing.last_refreshed_at = _now_utc()
    session.add(existing)
    session.flush()
    return existing, programme


def _get_or_create_day_progress(
    session,
    *,
    plan: UserEducationPlan,
    programme_day: EducationProgrammeDay,
    lesson_variant: EducationLessonVariant | None,
    lesson_date: date,
) -> UserEducationDayProgress:
    row = (
        session.execute(
            select(UserEducationDayProgress)
            .where(
                UserEducationDayProgress.user_plan_id == int(plan.id),
                UserEducationDayProgress.lesson_date == lesson_date,
            )
            .order_by(desc(UserEducationDayProgress.updated_at), desc(UserEducationDayProgress.id))
        )
        .scalars()
        .first()
    )
    if row is None:
        row = UserEducationDayProgress(
            user_plan_id=int(plan.id),
            programme_day_id=int(programme_day.id),
            lesson_variant_id=int(getattr(lesson_variant, "id", 0) or 0) or None,
            lesson_date=lesson_date,
            completion_status="pending",
        )
    row.programme_day_id = int(programme_day.id)
    row.lesson_variant_id = int(getattr(lesson_variant, "id", 0) or 0) or None
    session.add(row)
    session.flush()
    return row


def _select_takeaway(lesson_variant: EducationLessonVariant | None, score_pct: float | None) -> tuple[str | None, str | None]:
    if lesson_variant is None:
        return None, None
    score = _safe_float(score_pct)
    if score is not None and score >= _QUIZ_HIGH_SCORE_PCT:
        text = str(getattr(lesson_variant, "takeaway_if_high_score", "") or "").strip()
        if text:
            return text, "high_score"
    if score is not None and score < _QUIZ_LOW_SCORE_PCT:
        text = str(getattr(lesson_variant, "takeaway_if_low_score", "") or "").strip()
        if text:
            return text, "low_score"
    text = str(getattr(lesson_variant, "takeaway_default", "") or "").strip()
    return (text or None), ("default" if text else None)


def _sync_progress_completion(progress: UserEducationDayProgress) -> None:
    has_video = bool(getattr(progress, "video_completed_at", None))
    has_quiz = bool(getattr(progress, "quiz_completed_at", None))
    if has_video and has_quiz:
        progress.completion_status = "completed"
        if getattr(progress, "completed_at", None) is None:
            progress.completed_at = _now_utc()
    elif has_video:
        progress.completion_status = "video_done"
        progress.completed_at = None
    elif has_quiz:
        progress.completion_status = "quiz_done"
        progress.completed_at = None
    else:
        progress.completion_status = "pending"
        progress.completed_at = None


def _question_rows(session, quiz_id: int | None) -> list[EducationQuizQuestion]:
    if not quiz_id:
        return []
    return (
        session.execute(
            select(EducationQuizQuestion)
            .where(EducationQuizQuestion.quiz_id == int(quiz_id))
            .order_by(EducationQuizQuestion.question_order.asc(), EducationQuizQuestion.id.asc())
        )
        .scalars()
        .all()
    )


def _quiz_row(session, lesson_variant_id: int | None) -> EducationQuiz | None:
    if not lesson_variant_id:
        return None
    return (
        session.execute(
            select(EducationQuiz)
            .where(EducationQuiz.lesson_variant_id == int(lesson_variant_id))
            .order_by(desc(EducationQuiz.updated_at), desc(EducationQuiz.id))
        )
        .scalars()
        .first()
    )


def _lesson_state(
    session,
    *,
    user_id: int,
    anchor: date,
) -> dict[str, Any]:
    snapshot = build_daily_tracker_generation_context_snapshot(int(user_id))
    context = snapshot.get("context") if isinstance(snapshot.get("context"), dict) else {}
    context_hash = str(snapshot.get("context_hash") or "").strip()
    plan, programme = _get_or_create_active_plan(
        session,
        user_id=int(user_id),
        plan_date=anchor,
        context=context,
        context_hash=context_hash,
    )
    if plan is None or programme is None:
        return {
            "available": False,
            "user_id": int(user_id),
            "lesson_date": anchor.isoformat(),
            "reason": "No active education programme is configured.",
        }
    programme_day = _resolve_programme_day(session, int(programme.id), int(plan.current_day_index))
    if programme_day is None:
        return {
            "available": False,
            "user_id": int(user_id),
            "lesson_date": anchor.isoformat(),
            "plan_id": int(plan.id),
            "programme_id": int(programme.id),
            "reason": "No lesson is configured for today in the active programme.",
        }
    concept_key = str(getattr(programme_day, "concept_key", "") or "").strip().lower()
    pillar_key = str(getattr(plan, "pillar_key", "") or getattr(programme, "pillar_key", "") or "").strip().lower()
    tracker_pillar = _find_tracker_pillar(context, pillar_key) or {}
    tracker_concept = _find_tracker_concept(context, pillar_key, concept_key) or {}
    assessment = _assessment_snapshot(session, int(user_id))
    concept_score = _assessment_concept_score(assessment, pillar_key, concept_key)
    pillar_score = _assessment_pillar_score(assessment, pillar_key)
    concept_level = _get_or_create_concept_level(
        session,
        user_id=int(user_id),
        pillar_key=pillar_key,
        concept_key=concept_key,
        assessment_score=concept_score if concept_score is not None else pillar_score,
        tracker_state={
            "pillar_state": tracker_pillar.get("state"),
            "signal": tracker_concept.get("signal"),
            "latest_value": tracker_concept.get("latest_value"),
            "target_label": tracker_concept.get("target_label"),
            "active_label": tracker_pillar.get("active_label"),
        },
    )
    lesson_variant = _resolve_lesson_variant(session, int(programme_day.id), str(getattr(concept_level, "current_level", "") or "build"))
    quiz = _quiz_row(session, int(getattr(lesson_variant, "id", 0) or 0) or None)
    quiz_questions = _question_rows(session, int(getattr(quiz, "id", 0) or 0) or None)
    content_item = session.get(ContentLibraryItem, int(getattr(lesson_variant, "content_item_id", 0) or 0)) if lesson_variant is not None and getattr(lesson_variant, "content_item_id", None) else None
    progress = _get_or_create_day_progress(
        session,
        plan=plan,
        programme_day=programme_day,
        lesson_variant=lesson_variant,
        lesson_date=anchor,
    )
    _sync_plan_streaks(session, plan)
    session.flush()
    takeaway = str(getattr(progress, "takeaway_text_shown", "") or "").strip() or None
    return {
        "available": True,
        "user_id": int(user_id),
        "lesson_date": anchor.isoformat(),
        "plan_id": int(plan.id),
        "programme_id": int(programme.id),
        "programme": {
            "id": int(programme.id),
            "code": str(getattr(programme, "code", "") or "").strip() or None,
            "name": str(getattr(programme, "name", "") or "").strip() or None,
            "duration_days": int(getattr(programme, "duration_days", 0) or 0) or _DEFAULT_PROGRAMME_DURATION_DAYS,
        },
        "pillar_key": pillar_key or None,
        "pillar_label": _pillar_label(pillar_key),
        "day_index": int(getattr(plan, "current_day_index", 0) or 1),
        "streak_days": int(getattr(plan, "current_streak_days", 0) or 0),
        "best_streak_days": int(getattr(plan, "best_streak_days", 0) or 0),
        "concept_key": concept_key or None,
        "concept_label": str(getattr(programme_day, "concept_label", "") or "").strip() or str(getattr(programme_day, "concept_key", "") or "").strip() or None,
        "level": str(getattr(concept_level, "current_level", "") or "").strip() or "build",
        "assessment_score": concept_score if concept_score is not None else pillar_score,
        "tracker_signal": str(tracker_concept.get("signal") or "").strip() or None,
        "tracker_state": str(tracker_pillar.get("state") or "").strip() or None,
        "tracker_day_label": str(tracker_pillar.get("active_label") or "").strip() or None,
        "lesson": {
            "programme_day_id": int(programme_day.id),
            "lesson_variant_id": int(getattr(lesson_variant, "id", 0) or 0) or None,
            "title": (
                str((content_item.title if content_item is not None else None) or "").strip()
                or str(getattr(programme_day, "default_title", "") or "").strip()
                or str(getattr(programme_day, "concept_label", "") or getattr(programme_day, "concept_key", "") or "").strip()
                or "Today's lesson"
            ),
            "summary": (
                str(getattr(programme_day, "default_summary", "") or "").strip()
                or str((content_item.body if content_item is not None else "") or "").strip()[:280]
                or None
            ),
            "goal": str(getattr(programme_day, "lesson_goal", "") or "").strip() or None,
            "content": _content_payload(content_item),
        },
        "quiz": {
            "id": int(getattr(quiz, "id", 0) or 0) or None,
            "pass_score_pct": _safe_float(getattr(quiz, "pass_score_pct", None)),
            "questions": [_quiz_question_payload(item) for item in quiz_questions],
        },
        "progress": {
            "id": int(getattr(progress, "id", 0) or 0),
            "watch_pct": _safe_float(getattr(progress, "watch_pct", None)),
            "watched_seconds": _safe_int(getattr(progress, "watched_seconds", None)),
            "quiz_score_pct": _safe_float(getattr(progress, "quiz_score_pct", None)),
            "completion_status": str(getattr(progress, "completion_status", "") or "").strip() or "pending",
            "video_completed_at": getattr(progress, "video_completed_at", None).isoformat() if getattr(progress, "video_completed_at", None) else None,
            "quiz_completed_at": getattr(progress, "quiz_completed_at", None).isoformat() if getattr(progress, "quiz_completed_at", None) else None,
            "completed_at": getattr(progress, "completed_at", None).isoformat() if getattr(progress, "completed_at", None) else None,
        },
        "takeaway": takeaway,
    }


def get_today_education_plan(user_id: int, *, anchor: date | None = None) -> dict[str, Any]:
    ensure_education_plan_schema()
    resolved_anchor = _resolve_plan_date(anchor)
    with SessionLocal() as session:
        payload = _lesson_state(session, user_id=int(user_id), anchor=resolved_anchor)
        session.commit()
        return payload


def record_education_video_progress(
    user_id: int,
    *,
    watch_pct: float | int | None = None,
    watched_seconds: int | None = None,
    anchor: date | None = None,
) -> dict[str, Any]:
    ensure_education_plan_schema()
    resolved_anchor = _resolve_plan_date(anchor)
    with SessionLocal() as session:
        state = _lesson_state(session, user_id=int(user_id), anchor=resolved_anchor)
        if not state.get("available"):
            session.commit()
            return state
        progress_id = int(((state.get("progress") or {}).get("id") or 0) or 0)
        progress = session.get(UserEducationDayProgress, progress_id)
        if progress is None:
            session.commit()
            return state
        resolved_watch_pct = max(0.0, min(100.0, _safe_float(watch_pct) or 0.0))
        progress.watch_pct = max(_safe_float(getattr(progress, "watch_pct", None)) or 0.0, resolved_watch_pct)
        if watched_seconds is not None:
            try:
                progress.watched_seconds = max(int(getattr(progress, "watched_seconds", 0) or 0), int(watched_seconds))
            except Exception:
                pass
        if (progress.watch_pct or 0.0) >= _WATCH_COMPLETE_THRESHOLD_PCT and getattr(progress, "video_completed_at", None) is None:
            progress.video_completed_at = _now_utc()
        _sync_progress_completion(progress)
        session.add(progress)
        plan = session.get(UserEducationPlan, int(state.get("plan_id") or 0))
        if plan is not None:
            _sync_plan_streaks(session, plan)
        session.commit()
    return get_today_education_plan(int(user_id), anchor=resolved_anchor)


def submit_education_quiz(
    user_id: int,
    *,
    answers: list[dict[str, Any]] | None,
    anchor: date | None = None,
) -> dict[str, Any]:
    ensure_education_plan_schema()
    resolved_anchor = _resolve_plan_date(anchor)
    with SessionLocal() as session:
        state = _lesson_state(session, user_id=int(user_id), anchor=resolved_anchor)
        if not state.get("available"):
            session.commit()
            return state
        progress_id = int(((state.get("progress") or {}).get("id") or 0) or 0)
        lesson_variant_id = int((((state.get("lesson") or {}).get("lesson_variant_id")) or 0) or 0)
        quiz_id = int((((state.get("quiz") or {}).get("id")) or 0) or 0)
        progress = session.get(UserEducationDayProgress, progress_id)
        lesson_variant = session.get(EducationLessonVariant, lesson_variant_id) if lesson_variant_id else None
        if progress is None or not quiz_id:
            session.commit()
            return state
        question_rows = _question_rows(session, quiz_id)
        answers_by_question: dict[int, Any] = {}
        for row in answers or []:
            if not isinstance(row, dict):
                continue
            qid = _safe_int(row.get("question_id"))
            if not qid:
                continue
            answers_by_question[int(qid)] = row.get("answer")
        correct_count = 0
        total = len(question_rows)
        session.execute(
            delete(UserEducationQuizAnswer).where(UserEducationQuizAnswer.user_day_progress_id == int(progress.id))
        )
        for question in question_rows:
            submitted = answers_by_question.get(int(question.id))
            expected = getattr(question, "correct_answer_json", None)
            is_correct = _answers_equal(expected, submitted) if expected is not None else None
            if is_correct:
                correct_count += 1
            session.add(
                UserEducationQuizAnswer(
                    user_day_progress_id=int(progress.id),
                    question_id=int(question.id),
                    answer_json=submitted,
                    is_correct=is_correct,
                )
            )
        score_pct = round((correct_count / total) * 100.0, 2) if total > 0 else None
        progress.quiz_score_pct = score_pct
        progress.quiz_completed_at = _now_utc()
        takeaway_text, takeaway_variant = _select_takeaway(lesson_variant, score_pct)
        progress.takeaway_text_shown = takeaway_text
        progress.takeaway_variant = takeaway_variant
        _sync_progress_completion(progress)
        session.add(progress)
        plan = session.get(UserEducationPlan, int(state.get("plan_id") or 0))
        if plan is not None:
            _sync_plan_streaks(session, plan)
        session.commit()
    return get_today_education_plan(int(user_id), anchor=resolved_anchor)
