"""Read-only learning snapshot based on recorded lesson activity."""
from sqlalchemy import select, desc, case, or_, func
from .models import EducationProgramme, EducationProgrammeDay, UserEducationPlan, UserEducationDayProgress, EducationLessonVariant, UserEducationQuizAnswer


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

    days = session.execute(select(EducationProgrammeDay).where(
        EducationProgrammeDay.programme_id == programme.id
    ).order_by(EducationProgrammeDay.day_index, EducationProgrammeDay.id)).scalars().all()
    records = session.execute(select(progress_model).where(
        progress_model.user_plan_id == plan.id
    ).order_by(progress_model.updated_at.desc(), progress_model.id.desc())).scalars().all()
    by_day = {}
    for record in records:
        by_day.setdefault(record.programme_day_id, record)
    variants = {variant.id: variant for variant in session.execute(
        select(EducationLessonVariant).where(EducationLessonVariant.id.in_(
            [record.lesson_variant_id for record in records if record.lesson_variant_id]
        ))
    ).scalars().all()}
    answers_by_progress = {}
    for answer in session.execute(select(UserEducationQuizAnswer).where(
        UserEducationQuizAnswer.user_day_progress_id.in_([record.id for record in records])
    )).scalars().all():
        answers_by_progress.setdefault(answer.user_day_progress_id, []).append(answer)

    def quiz_details(record):
        answers = answers_by_progress.get(record.id, []) if record else []
        # These are saved submission answers, not reconstructed from the percentage
        # or today's question bank (which may have changed since submission).
        if not record or not record.quiz_completed_at or not answers:
            return None
        return {'question_count': len(answers),
                'answered_count': sum(answer.answer_json not in (None, '', [], {}) for answer in answers),
                'correct_count': sum(answer.is_correct is True for answer in answers),
                'incorrect_count': sum(answer.is_correct is False for answer in answers),
                'ungraded_count': sum(answer.is_correct is None for answer in answers)}

    lessons = []
    for position, programme_day in enumerate(days, 1):
        record = by_day.get(programme_day.id)
        variant = variants.get(record.lesson_variant_id) if record else None
        lessons.append({
            'programme_day_id': programme_day.id,
            'number': position,
            'title': (variant.title if variant else None) or programme_day.default_title or programme_day.concept_label or programme_day.concept_key,
            'completed': bool(record and (record.completed_at or record.completion_status == 'completed')),
            'completed_at': iso(record.completed_at) if record else None,
            'lesson_date': iso(record.lesson_date) if record else None,
            'quiz_completed_at': iso(record.quiz_completed_at) if record else None,
            'quiz': quiz_details(record),
        })
    selected_lesson = next((item for item in lessons if day and item['programme_day_id'] == day.id), None)

    return {
        'available': True,
        'plan_id': int(plan.id),
        'programme_id': int(programme.id),
        'programme_name': programme.name,
        'lesson_title': selected_lesson['title'] if selected_lesson else None,
        'lesson_number': selected_lesson['number'] if selected_lesson else None,
        'programme_lesson_count': len(lessons),
        'programme_completed_count': sum(item['completed'] for item in lessons),
        'programme_lessons': lessons,
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
            'quiz': quiz_details(progress),
            'video_completed_at': iso(progress.video_completed_at),
            'quiz_completed_at': iso(progress.quiz_completed_at),
            'completed_at': iso(progress.completed_at),
        } if progress else None,
    }
