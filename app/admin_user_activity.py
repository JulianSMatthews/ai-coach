"""Read-only, allowlisted user activity for the admin profile."""
from datetime import timezone
from sqlalchemy import select, desc
from .models import UsageEvent

ACTIVITY_LABELS = {
    'app_login_success': 'Signed in',
    'page_view': 'Viewed app page',
    'app_account_created': 'Created account',
    'pillar_tracker_update': 'Recorded check-in',
    'coach_home_habits_view': 'Opened daily plan',
    'coach_home_habits_update': 'Updated daily plan',
    'coach_home_insight_view': 'Opened coach insight',
    'education_plan_view': 'Opened lesson',
    'education_video_progress': 'Recorded lesson progress',
    'education_quiz_submit': 'Submitted quiz',
    'weekly_objectives_save': 'Saved objectives',
}


def activity_item(row):
    meta = row.meta if isinstance(row.meta, dict) else {}
    timestamp = row.created_at
    if timestamp is not None and timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    # Never return arbitrary event metadata, messages, credentials or answer text.
    return {
        'id': row.id,
        'recorded_at': timestamp.isoformat() if timestamp else None,
        'kind': row.unit_type,
        'label': ACTIVITY_LABELS[row.unit_type],
        'pillar_key': meta.get('pillar_key'),
        'for_date': meta.get('score_date') or meta.get('lesson_date'),
        'watch_pct': meta.get('watch_pct'),
        'quiz_score_pct': meta.get('quiz_score_pct'),
        'completion_status': meta.get('completion_status'),
    }


ACTIVITY_GROUPS = {
    'all': tuple(ACTIVITY_LABELS),
    'learn': ('education_plan_view', 'education_video_progress', 'education_quiz_submit'),
    'checkin': ('pillar_tracker_update',),
}


def load_user_activity(session, user_id, *, provider, product, tag, category='all'):
    kinds = ACTIVITY_GROUPS[category]
    rows = session.execute(
        select(UsageEvent).where(
            UsageEvent.user_id == user_id,
            UsageEvent.provider == provider,
            UsageEvent.product == product,
            UsageEvent.tag == tag,
            UsageEvent.unit_type.in_(kinds),
        ).order_by(desc(UsageEvent.created_at), desc(UsageEvent.id)).limit(100)
    ).scalars().all()
    return {'events': [activity_item(row) for row in rows], 'limit': 100}
