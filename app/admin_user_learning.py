"""Read-only learning snapshot based on recorded lesson activity."""
from sqlalchemy import select, desc, case, or_, func
from .models import EducationProgramme, EducationProgrammeDay, UserEducationPlan, UserEducationDayProgress


def load_user_learning(session, user_id, today):
    progress_model = UserEducationDayProgress
    has_activity = or_(
        progress_model.watch_pct > 0,
        progress_model.watched_seconds > 0,
        progress_model.video_completed_at.isnot(None),
        progress_model.quiz_completed_at.isnot(None),
        progress_model.completed_at.isnot(None),
    )
    row = session.execute(
        select(UserEducationPlan, EducationProgramme, progress_model, EducationProgrammeDay)
        .join(EducationProgramme, UserEducationPlan.programme_id == EducationProgramme.id)
        .join(progress_model, progress_model.user_plan_id == UserEducationPlan.id)
        .join(EducationProgrammeDay, progress_model.programme_day_id == EducationProgrammeDay.id)
        .where(UserEducationPlan.user_id == int(user_id))
        .order_by(
            # Merely preparing/opening the next lesson must not hide recorded work.
            case((has_activity, 1), else_=0).desc(),
            func.coalesce(progress_model.updated_at, progress_model.created_at).desc(),
            progress_model.id.desc(),
        )
        .limit(1)
    ).first()
    if row:
        plan, programme, progress, day = row
    else:
        plan_row = session.execute(
            select(UserEducationPlan, EducationProgramme)
            .join(EducationProgramme, UserEducationPlan.programme_id == EducationProgramme.id)
            .where(UserEducationPlan.user_id == int(user_id), UserEducationPlan.status == 'active')
            .order_by(desc(UserEducationPlan.updated_at), desc(UserEducationPlan.id)).limit(1)
        ).first()
        if not plan_row:
            return None
        plan, programme = plan_row
        progress = day = None

    def iso(value):
        return value.isoformat() if value is not None else None

    return {
        'available': True,
        'plan_id': int(plan.id),
        'programme_id': int(programme.id),
        'programme_name': programme.name,
        'pillar_key': plan.pillar_key,
        'concept_key': day.concept_key if day else plan.entry_concept_key,
        'concept_label': (day.concept_label or day.concept_key) if day else plan.entry_concept_label,
        'starts_on': iso(plan.starts_on),
        'current_day_index': day.day_index if day else plan.current_day_index,
        'current_streak_days': plan.current_streak_days,
        'best_streak_days': plan.best_streak_days,
        'progress': {
            'id': int(progress.id),
            'is_today': progress.lesson_date == today,
            'lesson_date': iso(progress.lesson_date),
            'completion_status': progress.completion_status,
            'watch_pct': progress.watch_pct,
            'quiz_score_pct': progress.quiz_score_pct,
            'video_completed_at': iso(progress.video_completed_at),
            'quiz_completed_at': iso(progress.quiz_completed_at),
            'completed_at': iso(progress.completed_at),
        } if progress else None,
    }
