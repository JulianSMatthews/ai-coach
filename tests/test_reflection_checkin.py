"""Reflection consolidation preserves recorded question sets and their scores."""
import ast
import unittest
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import pillar_tracker as tracker


class ReflectionCheckinTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.current = tracker.tracker_concepts_for_pillar('reflection')
        self.legacy = tracker._LEGACY_REFLECTION_TRACKER_CONFIG
        self.enterContext(patch.object(tracker, 'tracker_today', return_value=self.today))
        self.enterContext(patch.object(tracker, 'ensure_pillar_tracker_schema'))
        self.enterContext(patch.object(tracker, '_latest_assessment_scores_for_user', return_value={}))
        self.enterContext(patch.object(tracker, '_daily_pillar_quote', return_value='Test quote'))
        self.enterContext(patch.object(tracker, '_daily_pillar_quote_is_generated', return_value=True))
        self.enterContext(patch.object(tracker, '_app_setup_completed_for_user', return_value=True))
        self.enterContext(patch.object(tracker, '_editable_tracker_dates_for_pillar',
                                     return_value=[self.today - timedelta(days=1), self.today]))

    def rows(self, *, version=None, retired=False):
        result = {
            concept.concept_key: SimpleNamespace(
                value_num=concept.options[-1].value,
                meta={'question_set_version': version} if version is not None else None,
            )
            for concept in self.current
        }
        if retired:
            result['self_awareness'] = SimpleNamespace(value_num=0, meta=None)
        return result

    def targets(self, _user, pillar, concepts):
        return {concept.concept_key: tracker._default_resolved_target(pillar, concept) for concept in concepts}

    def evaluations(self, entries):
        concepts = tracker._week_evaluation_concepts(self.current, entries)
        return tracker._build_concept_week_evaluations(
            entries, self.current, self.targets(1, 'reflection', concepts), tracker._week_days(self.today)
        )

    def test_new_three_answers_complete_but_old_partial_answers_do_not(self):
        self.assertFalse(tracker._day_complete(self.rows(), self.current))
        self.assertTrue(tracker._day_complete(self.rows(version=2), self.current))
        self.assertFalse(tracker._day_complete({}, self.current))
        for meta in (None, [], 'old metadata', {}):
            rows = self.rows()
            for row in rows.values():
                row.meta = meta
            self.assertFalse(tracker._day_complete(rows, self.current))

    def test_legacy_score_and_completion_keep_fourth_answer(self):
        rows = self.rows(retired=True)
        evaluations = self.evaluations({self.today: rows})
        self.assertTrue(tracker._day_complete(rows, self.current))
        self.assertEqual(tracker._day_score(rows, self.current, evaluations, self.today), 75)

    def test_new_answers_ignore_leftover_retired_row_and_use_three_scores(self):
        for version in (2, '2'):
            with self.subTest(version=version):
                rows = self.rows(version=version, retired=True)
                evaluations = self.evaluations({self.today: rows})
                self.assertTrue(tracker._day_complete(rows, self.legacy))
                self.assertEqual(tracker._day_score(rows, self.legacy, evaluations, self.today), 100)

    def test_mixed_week_scores_each_day_using_its_recorded_questions(self):
        yesterday = self.today - timedelta(days=1)
        entries = {
            yesterday: self.rows(retired=True),
            self.today: self.rows(version=2, retired=True),
        }
        evaluations = self.evaluations(entries)
        self.assertEqual(tracker._day_score(entries[yesterday], self.current, evaluations, yesterday), 75)
        self.assertEqual(tracker._day_score(entries[self.today], self.current, evaluations, self.today), 100)
        self.assertIsNone(evaluations['self_awareness'][self.today]['value'])
        self.assertEqual(tracker._week_score(entries, self.current, evaluations, tracker._week_days(self.today)), 88)

    def test_historical_detail_shows_old_questions_and_current_detail_shows_three(self):
        old_day = date(2026, 11, 10)
        entries = {old_day: self.rows(retired=True), self.today: self.rows(version=2)}
        def load(_user, _pillar, anchor):
            return {day: rows for day, rows in entries.items()
                    if tracker.start_of_week(day) == tracker.start_of_week(anchor)}
        with patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            historical = tracker.get_pillar_tracker_detail(1, 'reflection', old_day)
            current = tracker.get_pillar_tracker_detail(1, 'reflection', self.today)
        self.assertEqual([item['concept_key'] for item in historical['concepts']],
                         [item.concept_key for item in self.legacy])
        self.assertEqual(historical['concepts'][1]['helper'], 'How emotionally aware did you feel today?')
        self.assertEqual(historical['pillar']['tracker_score'], 75)
        self.assertEqual([item['label'] for item in current['concepts']],
                         ['Self & Emotional Awareness', 'Presence', 'Learning & Growth'])
        self.assertEqual(current['concepts'][0]['helper'],
                         'How aware were you of your thoughts, feelings and behaviours today?')
        self.assertTrue(next(day['complete'] for day in current['days'] if day['is_today']))

    def test_summary_resolves_retired_weekly_target_for_historical_scores(self):
        entries = {
            self.today - timedelta(days=1): self.rows(retired=True),
            self.today: self.rows(retired=True),
        }
        entries[self.today - timedelta(days=1)]['self_awareness'].value_num = 1
        def targets(user, pillar, concepts):
            result = self.targets(user, pillar, concepts)
            if 'self_awareness' in result:
                result['self_awareness'] = replace(result['self_awareness'], source='okr', target_value=7)
            return result
        with patch.object(tracker, 'active_pillar_keys', return_value=['reflection']), \
             patch.object(tracker, '_load_week_entries', return_value=entries), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=targets) as resolve:
            result = tracker.get_pillar_tracker_summary(1)['pillars'][0]
        self.assertIn('self_awareness', [item.concept_key for item in resolve.call_args.args[2]])
        expected = tracker._build_concept_week_evaluations(
            entries, self.legacy, targets(1, 'reflection', self.legacy), tracker._week_days(self.today)
        )
        self.assertEqual(result['tracker_score'],
                         tracker._week_score(entries, self.legacy, expected, tracker._week_days(self.today)))

    def test_mixed_historical_week_keeps_retired_answers_visible(self):
        old_day = date(2026, 11, 10)
        new_day = old_day + timedelta(days=1)
        entries = {old_day: self.rows(retired=True), new_day: self.rows(version=2, retired=True)}
        def load(_user, _pillar, anchor):
            return entries if tracker.start_of_week(anchor) == tracker.start_of_week(old_day) else {}
        with patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            detail = tracker.get_pillar_tracker_detail(1, 'reflection', old_day)
        self.assertEqual(detail['pillar']['active_date'], new_day.isoformat())
        retired = next(concept for concept in detail['concepts'] if concept['concept_key'] == 'self_awareness')
        days = {day['date']: day for day in retired['week']}
        self.assertEqual(days[old_day.isoformat()]['value_label'], 'No')
        self.assertIsNone(days[new_day.isoformat()]['value_label'])
        self.assertIsNone(retired['value'])
        self.assertIsNone(retired['value_label'])
        self.assertEqual(detail['pillar']['tracker_score'], 88)

    def test_monday_fallback_resolves_legacy_target_when_current_week_is_empty(self):
        monday = date(2026, 11, 23)
        entries = {self.today: self.rows(retired=True)}
        def load(_user, _pillar, anchor):
            return {day: rows for day, rows in entries.items()
                    if tracker.start_of_week(day) == tracker.start_of_week(anchor)}
        with patch.object(tracker, 'tracker_today', return_value=monday), \
             patch.object(tracker, 'active_pillar_keys', return_value=['reflection']), \
             patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets) as resolve:
            result = tracker.get_pillar_tracker_summary(1)['pillars'][0]
        self.assertEqual(result['tracker_score'], 75)
        self.assertFalse(result['today_complete'])
        self.assertEqual(resolve.call_count, 2)
        self.assertIn('self_awareness', [item.concept_key for item in resolve.call_args.args[2]])

    def test_admin_completion_uses_recorded_versions_for_all_three_days(self):
        tree = ast.parse((Path(__file__).parents[1] / 'app/api.py').read_text())
        route = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                     and node.name == 'admin_user_app_state')
        loop = next(node for node in ast.walk(route) if isinstance(node, ast.For)
                    and isinstance(node.target, ast.Name) and node.target.id == 'pillar')
        yesterday = self.today - timedelta(days=1)
        before = self.today - timedelta(days=2)
        namespace = {
            'tracker_pillars': [{'pillar_key': 'reflection', 'label': 'Reflection'}],
            'tracker_journey_pillars': [], 'tracker_concepts_for_pillar': tracker.tracker_concepts_for_pillar,
            '_day_complete': tracker._day_complete, 'user_id': 1, 'today': self.today,
            'yesterday': yesterday, 'day_before_yesterday': before,
            'tracker_day_rows': {
                self.today: {'reflection': self.rows(version=2)},
                yesterday: {'reflection': self.rows(retired=True)},
                before: {'reflection': self.rows()},
            },
        }
        exec(compile(ast.Module(body=[loop], type_ignores=[]), 'app/api.py', 'exec'), namespace)
        result = namespace['tracker_journey_pillars'][0]
        self.assertTrue(result['today_complete'])
        self.assertTrue(result['yesterday_complete'])
        self.assertFalse(result['day_before_yesterday_complete'])

    def save_entries(self, entries):
        session = MagicMock()
        existing = self.rows(retired=True)
        for key, row in existing.items():
            row.concept_key = key
        session.execute.return_value.scalars.return_value.all.return_value = list(existing.values())
        factory = MagicMock()
        factory.return_value.__enter__.return_value = session
        with patch.object(tracker, 'SessionLocal', factory), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets), \
             patch.object(tracker, '_record_latest_tracker_focus'), \
             patch.object(tracker, '_sync_pillar_tracker_actuals_to_okrs'), \
             patch.object(tracker, 'get_pillar_tracker_detail', return_value={'saved': True}):
            result = tracker.save_pillar_tracker_day(1, 'reflection', score_date=self.today, entries=entries)
        self.assertEqual(result, {'saved': True})
        session.delete.assert_not_called()
        session.commit.assert_called_once()
        return existing

    def test_save_requires_only_three_answers_versions_them_and_keeps_retired_row(self):
        entries = [{'concept_key': concept.concept_key, 'value': concept.options[-1].value}
                   for concept in self.current]
        existing = self.save_entries(entries)
        for concept in self.current:
            self.assertEqual(existing[concept.concept_key].meta['question_set_version'], 2)
        self.assertEqual(existing['self_awareness'].value_num, 0)
        self.assertIsNone(existing['self_awareness'].meta)

    def test_checkin_opened_before_deployment_can_save_its_original_four_answers(self):
        entries = [{'concept_key': concept.concept_key, 'value': concept.options[-1].value}
                   for concept in self.legacy]
        existing = self.save_entries(entries)
        for concept in self.legacy:
            self.assertEqual(existing[concept.concept_key].meta['question_set_version'], 1)
        self.assertTrue(tracker._day_complete(existing, self.current))

    def test_unversioned_pillar_completion_and_scores_are_unchanged(self):
        concepts = tracker.tracker_concepts_for_pillar('training')
        rows = {concept.concept_key: SimpleNamespace(value_num=concept.options[-1].value)
                for concept in concepts}
        targets = self.targets(1, 'training', concepts)
        evaluations = tracker._build_concept_week_evaluations(
            {self.today: rows}, concepts, targets, tracker._week_days(self.today)
        )
        self.assertTrue(tracker._day_complete(rows, concepts))
        self.assertEqual(tracker._day_score(rows, concepts, evaluations, self.today), 100)


if __name__ == '__main__':
    unittest.main()
