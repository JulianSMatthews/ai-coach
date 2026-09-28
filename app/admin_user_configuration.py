"""Read-only current pillar choices and saved target record dates."""
from sqlalchemy import select, desc
from .models import UserPreference
from .pillar_config import HOME_PILLAR_PREF_KEYS, pillar_label
from .weekly_objectives import _primary_krs_by_concept


def load_user_configuration(session, user_id, objectives):
    rows = session.execute(select(UserPreference).where(
        UserPreference.user_id == user_id,
        UserPreference.key.in_([*HOME_PILLAR_PREF_KEYS.values(), 'app_setup_completed']),
    ).order_by(desc(UserPreference.updated_at), desc(UserPreference.id))).scalars().all()
    preferences = {}
    for row in rows:
        preferences.setdefault(row.key, row)
    def timestamp(value):
        return value.isoformat() if value else None
    selected = {pillar['pillar_key'] for pillar in (objectives or {}).get('pillars', [])}
    choices = []
    for key, pref_key in HOME_PILLAR_PREF_KEYS.items():
        pref = preferences.get(pref_key)
        choices.append({'key': key, 'label': pillar_label(key), 'selected': key in selected,
                        'source': 'saved' if pref else 'default',
                        'last_saved_at': timestamp(pref.updated_at) if pref else None})
    pillars = []
    for pillar in (objectives or {}).get('pillars', []):
        objective, targets, _ = _primary_krs_by_concept(session, user_id, pillar['pillar_key'])
        concepts = []
        for concept in pillar.get('concepts', []):
            target = targets.get(concept['concept_key'])
            concepts.append({**concept,
                'record_created_at': timestamp(target.created_at) if target else None,
                'record_updated_at': timestamp(target.updated_at) if target else None})
        pillars.append({**pillar, 'objective_created_at': timestamp(objective.created_at) if objective else None,
                        'concepts': concepts})
    setup = preferences.get('app_setup_completed')
    return {'pillars': choices, 'setup_last_saved_at': timestamp(setup.updated_at) if setup else None,
            'objectives': pillars, 'wellbeing': (objectives or {}).get('wellbeing')}
