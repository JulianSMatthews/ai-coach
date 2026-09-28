"""Reporting-week and alcohol colour regressions, without database access."""
import unittest
from contextlib import ExitStack
from datetime import date, timedelta
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
from app import pillar_tracker as tracker


class TrackerScoreTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        for name, value in {
            'ensure_pillar_tracker_schema': None,
            'tracker_today': date(2026, 9, 28),
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

    def summary(self, today, rows, anchor=None, pillar_rows=None, detail_pillar=None):
        def load(_user, _pillar, day):
            source = pillar_rows[_pillar] if pillar_rows is not None else rows
            return {d: row for d, row in source.items() if tracker.start_of_week(d) == tracker.start_of_week(day)}
        with patch.object(tracker, 'tracker_today', return_value=today), \
             patch.object(tracker, 'active_pillar_keys', return_value=list(pillar_rows) if pillar_rows is not None else ['nutrition']), \
             patch.object(tracker, 'tracker_concepts_for_pillar', return_value=(self.concept,)), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', return_value={'alcohol_units': self.target}), \
             patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_editable_tracker_dates_for_pillar', return_value=[today - timedelta(days=1), today]):
            if detail_pillar:
                return tracker.get_pillar_tracker_detail(1, detail_pillar, anchor=anchor)
            return tracker.get_pillar_tracker_summary(1, anchor=anchor)

    def test_monday_switches_only_after_todays_completed_checkin(self):
        monday = date(2026, 9, 28)
        rows = {monday - timedelta(days=1): {'alcohol_units': SimpleNamespace(value_num=0)}}
        result = self.summary(monday, rows)
        self.assertEqual(result['week']['start'], '2026-09-28')
        self.assertEqual(result['overall_score'], 100)
        self.assertFalse(result['today_complete'])
        rows[monday] = {'alcohol_units': SimpleNamespace(value_num=6)}
        result = self.summary(monday, rows)
        self.assertEqual(result['overall_score'], 0)
        self.assertTrue(result['today_complete'])
        tuesday = self.summary(monday + timedelta(days=1), rows)
        self.assertEqual(tuesday['week']['start'], '2026-09-28')
        self.assertEqual(tuesday['overall_score'], 0)
        self.assertFalse(tuesday['today_complete'])

    def test_monday_pillars_switch_independently(self):
        monday = date(2026, 9, 28)
        sunday = monday - timedelta(days=1)
        previous = {sunday: {'alcohol_units': SimpleNamespace(value_num=0)}}
        completed = {**previous, monday: {'alcohol_units': SimpleNamespace(value_num=6)}}
        result = self.summary(monday, {}, pillar_rows={'nutrition': completed, 'recovery': previous})
        self.assertEqual([p['tracker_score'] for p in result['pillars']], [0, 100])
        self.assertEqual([p['today_complete'] for p in result['pillars']], [True, False])
        self.assertEqual(result['today_completed_pillars_count'], 1)
        self.assertEqual(result['overall_score'], 50)

    def test_fallback_does_not_change_other_summary_fields_or_explicit_week(self):
        monday = date(2026, 9, 28)
        rows = {monday - timedelta(days=1): {'alcohol_units': SimpleNamespace(value_num=0)}}
        default = self.summary(monday, rows)
        explicit = self.summary(monday, rows, anchor=monday)
        self.assertIsNone(explicit['overall_score'])
        self.assertEqual(default['week'], explicit['week'])
        for key in default['pillars'][0]:
            if key not in {'score', 'tracker_score', 'source'}:
                self.assertEqual(default['pillars'][0][key], explicit['pillars'][0][key], key)
        self.assertIsNone(self.summary(monday + timedelta(days=1), rows)['overall_score'])

    def test_past_answers_still_score_when_target_start_is_newer(self):
        monday = date(2026, 9, 28)
        self.target = replace(self.target, start_date=monday)
        # No Sunday entry: previously every historical score was excluded.
        rows = {date(2026, 9, 25): {'alcohol_units': SimpleNamespace(value_num=0)}}
        result = self.summary(monday, rows)
        self.assertEqual(result['pillars'][0]['tracker_score'], 100)
        self.assertEqual(result['overall_score'], 100)
        detail = self.summary(monday, rows, anchor=date(2026, 9, 21), detail_pillar='nutrition')
        self.assertEqual(detail['pillar']['tracker_score'], 100)
        self.assertEqual(detail['overall_score'], 100)
        self.assertFalse(detail['pillar']['is_current_week'])

    def test_last_week_overall_excludes_this_weeks_scores(self):
        monday = date(2026, 9, 28)
        friday = date(2026, 9, 25)
        data = {
            'nutrition': {friday: {'alcohol_units': SimpleNamespace(value_num=0)}, monday: {'alcohol_units': SimpleNamespace(value_num=6)}},
            'recovery': {friday: {'alcohol_units': SimpleNamespace(value_num=6)}, monday: {'alcohol_units': SimpleNamespace(value_num=0)}},
        }
        detail = self.summary(monday, {}, anchor=date(2026, 9, 21), pillar_rows=data, detail_pillar='nutrition')
        self.assertEqual(detail['pillar']['tracker_score'], 100)
        self.assertEqual(detail['overall_score'], 50)

    def test_current_week_target_window_is_unchanged(self):
        monday = date(2026, 9, 28)
        self.target = replace(self.target, start_date=monday + timedelta(days=3))
        rows = {monday: {'alcohol_units': SimpleNamespace(value_num=0)}}
        result = self.summary(monday + timedelta(days=4), rows)
        self.assertIsNone(result['overall_score'])

    def test_empty_week_stays_unrated_and_explicit_history_is_respected(self):
        result = self.summary(date(2026, 9, 28), {})
        self.assertIsNone(result['overall_score'])
        self.assertIsNone(result['pillars'][0]['score'])
        historical = self.summary(date(2026, 9, 28), {}, anchor=date(2026, 9, 14))
        self.assertEqual(historical['week']['start'], '2026-09-14')


if __name__ == '__main__':
    unittest.main()
