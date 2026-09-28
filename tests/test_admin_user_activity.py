import ast
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch
from sqlalchemy import create_engine, JSON
from sqlalchemy.orm import Session
from fastapi import FastAPI, Depends, HTTPException, Header
from fastapi.testclient import TestClient
from app.admin_user_activity import load_user_activity
from app.models import UsageEvent


class ActivityDataTests(unittest.TestCase):
    def test_only_user_app_events_are_returned_without_private_metadata(self):
        engine = create_engine('sqlite://')
        self.addCleanup(engine.dispose)
        column = UsageEvent.__table__.c.meta
        self.enterContext(patch.object(column, 'type', column.type.with_variant(JSON(), 'sqlite')))
        UsageEvent.__table__.create(engine)
        with Session(engine) as session:
            for uid, provider, kind in [(1, 'app', 'pillar_tracker_update'), (2, 'app', 'education_quiz_submit'), (1, 'twilio', 'message'), (1, 'app', 'coaching_auto_enabled')]:
                session.add(UsageEvent(user_id=uid, provider=provider, product='engagement', tag='app', unit_type=kind, created_at=datetime(2026, 9, 28, 9), units=1, meta={'score_date': '2026-09-27', 'pillar_key': 'nutrition', 'secret': 'must-not-leak'}))
            session.commit()
            result = load_user_activity(session, 1, provider='app', product='engagement', tag='app')
            self.assertEqual(len(result['events']), 1)
            row = result['events'][0]
            self.assertEqual(row['for_date'], '2026-09-27')
            self.assertEqual(row['recorded_at'], '2026-09-28T09:00:00+00:00')
            self.assertEqual(row['label'], 'Recorded check-in')
            self.assertNotIn('secret', row)
            self.assertNotIn('must-not-leak', str(result))


class AdminUserRouteTests(unittest.TestCase):
    def setUp(self):
        api = FastAPI()
        def require_admin(x_test_admin: str | None = Header(None)):
            if x_test_admin != 'yes':
                raise HTTPException(401)
            return SimpleNamespace(id=99)
        self.session = MagicMock()
        self.session.get.return_value = SimpleNamespace(id=1)
        sessions = MagicMock()
        sessions.return_value.__enter__.return_value = self.session
        self.scope = Mock()
        self.summary = Mock(return_value={'week': {'start': '2026-09-21'}, 'pillars': []})
        namespace = {'__name__': 'app.api', '__package__': 'app', 'admin': api, 'User': object, 'Depends': Depends, '_require_admin': require_admin, 'HTTPException': HTTPException, 'SessionLocal': sessions, '_ensure_club_scope': self.scope, 'timedelta': timedelta, 'APP_ENGAGEMENT_PROVIDER': 'app', 'APP_ENGAGEMENT_PRODUCT': 'engagement', 'APP_ENGAGEMENT_TAG': 'app', 'get_pillar_tracker_summary': self.summary, 'parse_tracker_anchor': lambda value: date.fromisoformat(value) if value == '2026-09-14' else None}
        tree = ast.parse((Path(__file__).parents[1] / 'app/api.py').read_text())
        routes = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {'admin_user_activity', 'admin_user_performance'}], type_ignores=[])
        exec(compile(routes, 'app/api.py', 'exec'), namespace)
        self.enterContext(patch('app.pillar_tracker.tracker_today', return_value=date(2026, 9, 28)))
        self.activity = self.enterContext(patch('app.admin_user_activity.load_user_activity', return_value={'events': [], 'limit': 100}))
        self.client = self.enterContext(TestClient(api))

    def get(self, path, authenticated=True):
        return self.client.get('/users/1/' + path, headers={'X-Test-Admin': 'yes'} if authenticated else {})

    def test_routes_require_admin_and_club_scope(self):
        for route in ['activity', 'performance']:
            self.assertEqual(self.get(route, False).status_code, 401)
        self.scope.side_effect = HTTPException(403)
        for route in ['activity', 'performance']:
            self.assertEqual(self.get(route).status_code, 403)
        self.activity.assert_not_called()
        self.summary.assert_not_called()

    def test_history_uses_last_completed_week_without_generating_content(self):
        self.assertEqual(self.get('performance').status_code, 200)
        self.summary.assert_called_once_with(1, anchor=date(2026, 9, 27), skip_quote_generation=True)
        self.session.commit.assert_not_called()
        self.assertEqual(self.get('performance?week=2026-09-14').status_code, 200)
        self.assertEqual(self.summary.call_args.kwargs['anchor'], date(2026, 9, 14))
        self.assertEqual(self.get('performance?week=bad').status_code, 400)

    def test_missing_user_is_not_returned(self):
        self.session.get.return_value = None
        self.assertEqual(self.get('activity').status_code, 404)
        self.assertEqual(self.get('performance').status_code, 404)
        self.activity.assert_not_called()
