"""Read-only learning diagnostics; run in the API service's Render shell.

    python scripts/diagnose_user_learning.py --user-id 1 --user-id 4

Outputs record IDs, dates and progress only, never credentials or quiz answers.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, func, text
from app.db import SessionLocal
from app.models import (
    User, UserEducationPlan, UserEducationDayProgress, EducationProgrammeDay,
    UserEducationQuizAnswer, UsageEvent,
)


def diagnose(session, user_id):
    exists = session.scalar(select(User.id).where(User.id == user_id)) is not None
    progress = session.execute(
        select(
            UserEducationDayProgress.id,
            UserEducationPlan.id.label('plan_id'),
            UserEducationPlan.status.label('plan_status'),
            UserEducationDayProgress.programme_day_id,
            EducationProgrammeDay.concept_label,
            UserEducationDayProgress.lesson_date,
            UserEducationDayProgress.watch_pct,
            UserEducationDayProgress.video_completed_at,
            UserEducationDayProgress.quiz_score_pct,
            UserEducationDayProgress.quiz_completed_at,
            UserEducationDayProgress.completion_status,
            UserEducationDayProgress.completed_at,
            UserEducationDayProgress.updated_at,
        )
        .join(UserEducationPlan, UserEducationDayProgress.user_plan_id == UserEducationPlan.id)
        .outerjoin(EducationProgrammeDay, UserEducationDayProgress.programme_day_id == EducationProgrammeDay.id)
        .where(UserEducationPlan.user_id == user_id)
        .order_by(UserEducationDayProgress.updated_at.desc(), UserEducationDayProgress.id.desc())
        .limit(20)
    ).mappings().all()
    completed_quizzes = session.scalar(
        select(func.count(UserEducationDayProgress.id))
        .join(UserEducationPlan, UserEducationDayProgress.user_plan_id == UserEducationPlan.id)
        .where(UserEducationPlan.user_id == user_id, UserEducationDayProgress.quiz_completed_at.isnot(None))
    )
    answer_count = session.scalar(
        select(func.count(UserEducationQuizAnswer.id))
        .join(UserEducationDayProgress, UserEducationQuizAnswer.user_day_progress_id == UserEducationDayProgress.id)
        .join(UserEducationPlan, UserEducationDayProgress.user_plan_id == UserEducationPlan.id)
        .where(UserEducationPlan.user_id == user_id)
    )
    rows = session.execute(
        select(UsageEvent.created_at, UsageEvent.unit_type, UsageEvent.meta)
        .where(UsageEvent.user_id == user_id, UsageEvent.tag == 'app_engagement',
               UsageEvent.unit_type.in_(['education_quiz_submit', 'education_video_progress']))
        .order_by(UsageEvent.created_at.desc(), UsageEvent.id.desc()).limit(20)
    ).all()
    events = []
    for timestamp, kind, metadata in rows:
        metadata = metadata if isinstance(metadata, dict) else {}
        events.append({'recorded_at': timestamp, 'kind': kind, **{
            key: metadata.get(key) for key in (
                'lesson_date', 'concept_key', 'pillar_key', 'quiz_score_pct', 'watch_pct', 'completion_status'
            )
        }})
    return {'user_id': user_id, 'user_exists': exists, 'completed_quiz_records': completed_quizzes,
            'saved_quiz_answer_count': answer_count, 'recent_progress': [dict(row) for row in progress],
            'recent_submission_events': events}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=int, action='append', required=True)
    args = parser.parse_args()
    if any(user_id <= 0 for user_id in args.user_id):
        parser.error('user IDs must be positive')
    with SessionLocal() as session:
        if session.bind.dialect.name == 'postgresql':
            session.execute(text('SET TRANSACTION READ ONLY'))
        result = [diagnose(session, user_id) for user_id in args.user_id]
        session.rollback()
    print(json.dumps(result, indent=2, default=str))


if __name__ == '__main__':
    main()
