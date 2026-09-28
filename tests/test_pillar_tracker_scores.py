"""Reporting-week and alcohol colour regressions, without database access."""
import unittest
from contextlib import ExitStack
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from app import pillar_tracker as tracker


class TrackerScoreTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        for name, value in {
            'ensure_pillar_tracker_schema': None,
            '_latest_assessment_scores_for_user': {},
            '_app_setup_completed_for_user': True,
            '_daily_pillar_quote': 'Test quote',
            '_daily_pillar_quote_is_generated': True,
            '_week_has_completed_tracker_days': False,
        }.items():
            stack.enter_context(patch.object(tracker, name, return_value=value))
        stack.enter_context(patch.object(tracker, '_wellbeing_tracking_settings', return_value=('off', 'on')))
        stack.enter_context(patch.object(tracker, '_wellbeing_weekly_targets', return_value=('off', 'on', 0, 0)))
        self.concept = tracker._optional_nutrition_tracker_concepts(1)[0]
        self.target = tracker._default_resolved_target_for_user(1, 'nutrition', self.concept)

    def test_zero_alcohol_is_green_and_scores_100(self):
        day = date(2026, 9, 27)
        rows = {day: {'alcohol_units': SimpleNamespace(value_num=0)}}
        result = tracker._build_concept_week_evaluations(rows, (self.concept,), {'alcohol_units': self.target}, tracker._week_days(day))['alcohol_units'][day]
        self.assertEqual(result['daily_status'], 'success')
        self.assertTrue(result['daily_positive'])
        self.assertTrue(result['target_reached'])
        self.assertEqual(result['score'], 100)

    def test_alcohol_above_zero_is_not_green_and_missing_is_unrated(self):
        day = date(2026, 9, 21)
        rows = {day: {'alcohol_units': SimpleNamespace(value_num=1)}}
        result = tracker._build_concept_week_evaluations(rows, (self.concept,), {'alcohol_units': self.target}, tracker._week_days(day))['alcohol_units']
        self.assertNotEqual(result[day]['daily_status'], 'success')
        self.assertFalse(result[day]['target_reached'])
        self.assertEqual(result[day]['score'], 0)
        self.assertIsNone(result[day + timedelta(days=1)]['daily_status'])
        self.assertIsNone(result[day + timedelta(days=1)]['score'])

    def summary(self, today, rows, anchor=None):
        def load(_user, _pillar, day):
            return {d: row for d, row in rows.items() if tracker.start_of_week(d) == tracker.start_of_week(day)}
        with patch.object(tracker, 'tracker_today', return_value=today), \
             patch.object(tracker, 'active_pillar_keys', return_value=['nutrition']), \
             patch.object(tracker, 'tracker_concepts_for_pillar', return_value=(self.concept,)), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', return_value={'alcohol_units': self.target}), \
             patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_editable_tracker_dates_for_pillar', return_value=[today - timedelta(days=1), today]):
            return tracker.get_pillar_tracker_summary(1, anchor=anchor)

    def test_monday_scores_sunday_but_tracks_monday_completion_separately(self):
        monday = date(2026, 9, 28)
        rows = {monday: {'alcohol_units': SimpleNamespace(value_num=6)}, monday - timedelta(days=1): {'alcohol_units': SimpleNamespace(value_num=0)}}
        result = self.summary(monday, rows)
        self.assertEqual(result['week']['start'], '2026-09-21')
        self.assertEqual(result['overall_score'], 100)
        self.assertTrue(result['today_complete'])
        self.assertTrue(all(option['complete'] for option in result['pillars'][0]['checkin_options']))
        tuesday = self.summary(monday + timedelta(days=1), rows)
        self.assertEqual(tuesday['week']['start'], '2026-09-28')
        self.assertEqual(tuesday['overall_score'], 0)
        self.assertFalse(tuesday['today_complete'])

    def test_empty_week_stays_unrated_and_explicit_history_is_respected(self):
        result = self.summary(date(2026, 9, 28), {})
        self.assertIsNone(result['overall_score'])
        self.assertIsNone(result['pillars'][0]['score'])
        historical = self.summary(date(2026, 9, 28), {}, anchor=date(2026, 9, 14))
        self.assertEqual(historical['week']['start'], '2026-09-14')


if __name__ == '__main__':
    unittest.main()
