"""Current-week score decomposition and strictly selected-concept AI coaching."""
import ast
import json
import unittest
from datetime import date, timedelta
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from fastapi import Body, FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

from app import pillar_progress as progress
from app import pillar_tracker as tracker


class PillarProgressTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)  # Wednesday
        self.monday = self.today - timedelta(days=2)
        self.rows = {}
        self.active = ['purpose']
        self.target_override = {}
        self.enterContext(patch.object(tracker, 'tracker_today', return_value=self.today))
        self.enterContext(patch.object(tracker, 'ensure_pillar_tracker_schema'))
        self.enterContext(patch.object(progress, 'active_pillar_keys', side_effect=lambda _user: self.active))
        self.enterContext(patch.object(tracker, '_load_week_entries', side_effect=lambda _user, pillar, _day: self.rows.get(pillar, {})))
        self.enterContext(patch.object(tracker, 'tracker_concepts_for_pillar', side_effect=lambda pillar, **_kw: tracker.PILLAR_TRACKER_CONFIG[pillar]))
        self.enterContext(patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets))
        self.generate = self.enterContext(patch.object(progress, 'run_llm_prompt', return_value=json.dumps({
            'insight': 'You recorded a moment of connection.',
            'action': 'Choose one small way to help someone today.',
            'reflection': 'What made that moment possible?',
        })))
        self.cache = {}
        self.enterContext(patch.object(progress, '_read_cache', side_effect=lambda user, key: self.cache.get((user, key), {})))
        self.enterContext(patch.object(progress, '_write_cache', side_effect=lambda user, key, payload: self.cache.update({(user, key): payload})))

    def targets(self, _user, pillar, concepts):
        return {item.concept_key: replace(tracker._default_resolved_target(pillar, item), **self.target_override) for item in concepts}

    def day(self, pillar='purpose', *, version=2, values=None):
        values = values or {}
        return {item.concept_key: SimpleNamespace(
            value_num=values.get(item.concept_key, max(option.value for option in item.options)),
            meta={'question_set_version': version},
        ) for item in tracker.PILLAR_TRACKER_CONFIG[pillar]}

    def result(self):
        return progress.get_pillar_progress(1)

    def test_week_to_date_is_elapsed_only_and_has_no_monday_carry_forward(self):
        self.rows['purpose'] = {
            self.monday - timedelta(days=1): self.day(),
            self.today + timedelta(days=1): self.day(),
        }
        result = self.result()
        self.assertEqual(result['week'], {'start': '2026-11-16', 'end': '2026-11-22', 'through': '2026-11-18', 'elapsed_days': 3})
        self.assertIsNone(result['overall_score'])
        pillar = result['pillars'][0]
        self.assertIsNone(pillar['score'])
        self.assertEqual(pillar['status'], 'grey')
        self.assertEqual(pillar['scored_days_count'], 0)
        self.assertEqual([day['date'] for day in pillar['concepts'][0]['days']], ['2026-11-16', '2026-11-17', '2026-11-18'])
        self.generate.assert_not_called()

    def test_active_pillars_only_and_empty_optional_pillars_are_not_scored(self):
        self.active = ['reflection', 'purpose']
        self.rows['training'] = {self.today: self.day('training')}
        self.rows['purpose'] = {self.today: self.day()}
        result = self.result()
        self.assertEqual([item['pillar_key'] for item in result['pillars']], self.active)
        self.assertEqual(result['overall_score'], 100)
        self.assertIsNone(result['pillars'][0]['score'])

    def test_contributions_reconcile_mean_of_daily_means_and_rounding(self):
        # Monday has two scored questions; Tuesday has three. A simple mean of
        # the three concept means does not reproduce the parent score.
        first = self.day(values={'meaning_fulfilment': 3, 'values_alignment': 0})
        del first['contribution_connection']
        second = self.day(values={'meaning_fulfilment': 0, 'values_alignment': 3, 'contribution_connection': 1})
        self.rows['purpose'] = {self.monday: first, self.monday + timedelta(days=1): second}
        pillar = self.result()['pillars'][0]
        self.assertEqual(pillar['score'], 58)  # mean(50, rounded(200/3))
        self.assertEqual(pillar['completed_days_count'], 1)
        self.assertEqual(pillar['scored_days_count'], 2)
        self.assertEqual(pillar['concepts'][0]['answered_days_count'], 2)
        self.assertEqual(pillar['concepts'][0]['elapsed_days'], 3)
        self.assertAlmostEqual(sum(item['contribution_points'] for item in pillar['concepts']) + pillar['rounding_adjustment'], pillar['score'])
        self.assertAlmostEqual(sum(item['weight_percent'] for item in pillar['concepts']), 100, places=1)
        self.assertEqual([item['status'] for item in pillar['concepts']], ['amber', 'amber', 'green'])

    def test_neutral_adaptability_does_not_reduce_score_or_become_missing_no(self):
        self.active = ['resilience']
        self.rows['resilience'] = {self.today: self.day('resilience', values={'adaptability': -1})}
        pillar = self.result()['pillars'][0]
        concept = next(item for item in pillar['concepts'] if item['concept_key'] == 'adaptability')
        self.assertEqual(pillar['score'], 100)
        self.assertEqual(concept['status'], 'grey')
        self.assertIsNone(concept['score'])
        self.assertEqual(concept['answered_days_count'], 1)
        self.assertEqual(concept['not_applicable_days_count'], 1)
        self.assertIsNone(concept['contribution_points'])
        self.assertTrue(concept['days'][-1]['not_applicable'])
        self.assertIsNone(concept['days'][0]['value_label'])

    def test_active_weekly_target_preserves_tracker_pace_scores_and_original_answers(self):
        self.rows['purpose'] = {
            self.monday + timedelta(days=index): self.day(values={'contribution_connection': answer})
            for index, answer in enumerate([1, 0, 1])
        }
        def targets(user, pillar, concepts):
            result = self.targets(user, pillar, concepts)
            result['contribution_connection'] = replace(result['contribution_connection'],
                source='okr', target_value=5, target_period='week', target_unit='days/week')
            return result
        with patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=targets):
            pillar = self.result()['pillars'][0]
        concept = pillar['concepts'][-1]
        self.assertEqual([day['value_label'] for day in concept['days']], ['Yes', 'No', 'Yes'])
        self.assertEqual([day['score'] for day in concept['days']], [100, 50, 67])
        self.assertEqual(concept['score'], 72)
        self.assertEqual(concept['status'], 'amber')
        self.assertEqual(pillar['score'], 91)
        self.assertAlmostEqual(sum(item['contribution_points'] for item in pillar['concepts']) + pillar['rounding_adjustment'], 91)

    def test_historical_question_contribution_is_visible_and_retired_leftovers_ignored(self):
        self.active = ['reflection']
        old = self.day('reflection', version=1)
        old['self_awareness'] = SimpleNamespace(value_num=0, meta=None)
        new = self.day('reflection')
        new['self_awareness'] = SimpleNamespace(value_num=0, meta=None)
        self.rows['reflection'] = {self.monday: old, self.today: new}
        pillar = self.result()['pillars'][0]
        self.assertEqual(pillar['score'], 88)
        retired = next(item for item in pillar['concepts'] if item['concept_key'] == 'self_awareness')
        self.assertTrue(retired['is_historical'])
        self.assertEqual(retired['answered_days_count'], 1)
        self.assertIsNone(retired['days'][-1]['score'])
        self.assertAlmostEqual(sum(item['contribution_points'] for item in pillar['concepts']) + pillar['rounding_adjustment'], 88)

    def test_private_written_contribution_never_exposes_text_or_fake_numeric_score(self):
        rows = self.day(version=3)
        rows['contribution_connection'] = SimpleNamespace(value_num=1, meta={'question_set_version': 3, 'answer_text': 'PRIVATE NARRATIVE'})
        self.rows['purpose'] = {self.today: rows}
        result = self.result()
        self.assertNotIn('PRIVATE NARRATIVE', json.dumps(result))
        concept = result['pillars'][0]['concepts'][-1]
        self.assertIsNone(concept['score'])
        self.assertIsNone(concept['latest_value_label'])
        with self.assertRaises(ValueError):
            progress.get_concept_coaching(1, 'purpose', 'contribution_connection')
        self.generate.assert_not_called()

    def test_current_option_definitions_are_used_without_extra_optional_questions(self):
        self.active = ['nutrition']
        result = self.result()
        self.assertEqual([item['concept_key'] for item in result['pillars'][0]['concepts']],
                         [item.concept_key for item in tracker.PILLAR_TRACKER_CONFIG['nutrition']])

    def test_tap_coaches_only_selected_concept_and_cache_is_user_and_evidence_scoped(self):
        self.rows['purpose'] = {self.today: self.day(values={'meaning_fulfilment': 1})}
        first = progress.get_concept_coaching(1, 'purpose', 'contribution_connection')
        prompt = self.generate.call_args.args[0]
        self.assertIn('contribution_connection', prompt)
        self.assertNotIn('meaning_fulfilment', prompt)
        self.assertNotIn('values_alignment', prompt)
        self.assertEqual(first['source'], 'ai')
        self.assertFalse(first['cached'])
        self.assertTrue(progress.get_concept_coaching(1, 'purpose', 'contribution_connection')['cached'])
        self.assertEqual(self.generate.call_count, 1)
        # Changing an unrelated question must not regenerate selected guidance.
        self.rows['purpose'][self.today]['meaning_fulfilment'].value_num = 3
        self.assertTrue(progress.get_concept_coaching(1, 'purpose', 'contribution_connection')['cached'])
        self.rows['purpose'][self.today]['contribution_connection'].value_num = 0
        self.assertFalse(progress.get_concept_coaching(1, 'purpose', 'contribution_connection')['cached'])
        self.assertEqual(self.generate.call_count, 2)
        self.assertFalse(progress.get_concept_coaching(2, 'purpose', 'contribution_connection')['cached'])
        self.assertEqual(self.generate.call_count, 3)

    def test_target_and_prompt_version_changes_invalidate_guidance(self):
        self.rows['purpose'] = {self.today: self.day()}
        progress.get_concept_coaching(1, 'purpose', 'contribution_connection')
        self.target_override = {'success_value': 0.5}
        self.assertFalse(progress.get_concept_coaching(1, 'purpose', 'contribution_connection')['cached'])
        with patch.object(progress, '_PROMPT_VERSION', 2):
            self.assertFalse(progress.get_concept_coaching(1, 'purpose', 'contribution_connection')['cached'])
        self.assertEqual(self.generate.call_count, 3)

    def test_missing_and_all_neutral_answers_do_not_generate_coaching(self):
        with self.assertRaisesRegex(ValueError, 'applicable check-in'):
            progress.get_concept_coaching(1, 'purpose', 'contribution_connection')
        self.active = ['resilience']
        self.rows['resilience'] = {self.today: self.day('resilience', values={'adaptability': -1})}
        with self.assertRaisesRegex(ValueError, 'applicable check-in'):
            progress.get_concept_coaching(1, 'resilience', 'adaptability')
        self.generate.assert_not_called()

    def test_unknown_or_inactive_concept_never_falls_back_or_calls_ai(self):
        for pillar, concept in [('purpose', 'nonexistent'), ('training', 'cardio_frequency'), ('', '')]:
            with self.subTest(pillar=pillar, concept=concept), self.assertRaises(ValueError):
                progress.get_concept_coaching(1, pillar, concept)
        self.generate.assert_not_called()

    def test_empty_or_malformed_ai_response_is_an_error_and_is_not_cached(self):
        self.rows['purpose'] = {self.today: self.day()}
        for raw in ['', 'not json', '{}', '[]', '{"insight":"a","action":"b","reflection":null}']:
            with self.subTest(raw=raw), self.assertRaises(progress.CoachingUnavailableError):
                self.generate.return_value = raw
                progress.get_concept_coaching(1, 'purpose', 'contribution_connection')
        self.assertEqual(self.cache, {})

    def test_cache_storage_failure_returns_coaching_unavailable(self):
        self.rows['purpose'] = {self.today: self.day()}
        with patch.object(progress, '_read_cache', side_effect=RuntimeError('Database unavailable')):
            with self.assertRaises(progress.CoachingUnavailableError):
                progress.get_concept_coaching(1, 'purpose', 'contribution_connection')
        self.generate.assert_not_called()
        with patch.object(progress, '_write_cache', side_effect=RuntimeError('Database unavailable')):
            with self.assertRaises(progress.CoachingUnavailableError):
                progress.get_concept_coaching(1, 'purpose', 'contribution_connection')


class PillarProgressRouteTests(unittest.TestCase):
    def setUp(self):
        self.api = FastAPI()
        self.access = Mock()
        self.readonly = Mock(return_value=False)
        self.get = Mock(return_value={'pillars': []})
        self.coach = Mock(return_value={'source': 'ai'})
        namespace = {'api_v1': self.api, 'Request': Request, 'Header': Header, 'HTTPException': HTTPException,
                     'Body': Body, 'Any': Any, '_resolve_user_access': self.access,
                     '_is_readonly_admin_preview_request': self.readonly, 'get_pillar_progress': self.get,
                     'get_concept_coaching': self.coach, 'CoachingUnavailableError': progress.CoachingUnavailableError}
        tree = ast.parse((Path(__file__).parents[1] / 'app' / 'api.py').read_text())
        routes = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                                  and node.name in {'api_user_pillar_progress', 'api_user_pillar_progress_coaching'}], type_ignores=[])
        exec(compile(routes, 'app/api.py', 'exec'), namespace)
        self.client = self.enterContext(TestClient(self.api))

    def post(self):
        return self.client.post('/users/8/pillar-progress/coaching', json={'pillar_key': 'purpose', 'concept_key': 'contribution_connection'})

    def test_routes_forward_requested_user_and_selected_question_after_access_check(self):
        self.assertEqual(self.client.get('/users/8/pillar-progress').status_code, 200)
        self.get.assert_called_once_with(8)
        self.assertEqual(self.post().status_code, 200)
        self.coach.assert_called_once_with(8, 'purpose', 'contribution_connection')
        self.assertEqual(self.access.call_count, 2)

    def test_denied_access_prevents_both_data_and_generation(self):
        self.access.side_effect = HTTPException(status_code=403, detail='Access denied')
        self.assertEqual(self.client.get('/users/8/pillar-progress').status_code, 403)
        self.assertEqual(self.post().status_code, 403)
        self.get.assert_not_called()
        self.coach.assert_not_called()

    def test_readonly_admin_preview_cannot_generate(self):
        self.readonly.return_value = True
        self.assertEqual(self.post().status_code, 403)
        self.coach.assert_not_called()

    def test_invalid_selected_question_and_ai_failure_have_explicit_errors(self):
        self.coach.side_effect = ValueError('Unknown question')
        self.assertEqual(self.post().status_code, 400)
        self.coach.side_effect = progress.CoachingUnavailableError('Try again shortly')
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail'], 'Try again shortly')


if __name__ == '__main__':
    unittest.main()
