"""Written Contribution answers are kept out of performance targets and nudges."""
import json
import unittest
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import coach_insight, daily_habits, pillar_tracker, weekly_objectives


class PurposeTextConsumersTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.pillar = {'pillar_key': 'purpose', 'label': 'Purpose', 'score': 50}
        configured = pillar_tracker.tracker_concepts_for_pillar('purpose')
        self.definitions = (
            configured[0], configured[1],
            replace(configured[2], score_mode='text', options=()),
        )

    def text_concept(self, recorded):
        return {
            'concept_key': 'contribution_connection', 'label': 'Contribution',
            'input_type': 'text', 'value_text': 'I listened to a friend.' if recorded else None,
            'score': None, 'target_period': None,
            'week': [{
                'date': self.today.isoformat(),
                'value_text': 'I listened to a friend.' if recorded else None,
                'value_label': 'Recorded' if recorded else None,
                'score': None, 'target_met': None,
            }],
        }

    def rating_concept(self):
        return {
            'concept_key': 'values_alignment', 'label': 'Values', 'input_type': 'choice',
            'score': 0, 'target_period': 'week',
            'week': [{'date': self.today.isoformat(), 'value_label': 'Not at all',
                      'score': 0, 'target_met': False, 'daily_positive': False}],
        }

    def test_recent_daily_focus_skips_absent_and_recorded_text(self):
        for recorded in (False, True):
            with self.subTest(recorded=recorded):
                result = daily_habits._recent_concept_focuses(
                    {'concepts': [self.text_concept(recorded), self.rating_concept()]}, self.today,
                    pillar_key='purpose', pillar_label='Purpose',
                )
                self.assertEqual([item['concept_key'] for item in result], ['values_alignment'])
                self.assertEqual(result[0]['signal'], 'missed_today')

    def test_anchored_daily_focus_skips_absent_and_recorded_text(self):
        for recorded in (False, True):
            with self.subTest(recorded=recorded), \
                 patch.object(daily_habits, 'tracker_today', return_value=self.today):
                result = daily_habits._anchored_concept_focuses(
                    {'concepts': [self.text_concept(recorded), self.rating_concept()]}, self.today,
                    pillar_key='purpose', pillar_label='Purpose',
                )
                self.assertEqual([item['concept_key'] for item in result], ['values_alignment'])
                self.assertEqual(result[0]['signal'], 'missed_today')

    def test_text_is_not_a_missing_or_poor_score_candidate_even_with_old_low_scores(self):
        for recorded in (False, True):
            with self.subTest(recorded=recorded):
                text = self.text_concept(recorded)
                text['score'] = 0
                text['week'].append({'date': (self.today - timedelta(days=1)).isoformat(),
                                     'score': 0, 'target_met': False})
                result = coach_insight._concept_candidate(self.pillar, text, anchor=self.today)
                self.assertFalse(result['has_signal'])
                self.assertIsNone(result['current_score'])
                self.assertIsNone(result['recent_average'])
                self.assertEqual(result['recent_misses'], 0)
                self.assertEqual(result['recent_missing'], 0)

    def test_preferred_text_does_not_override_a_real_insight_issue(self):
        with patch.object(coach_insight, 'get_pillar_tracker_summary', return_value={'pillars': [self.pillar]}), \
             patch.object(coach_insight, 'get_pillar_tracker_detail', return_value={
                 'concepts': [self.text_concept(True), self.rating_concept()],
             }):
            available, selected, _ = coach_insight._select_focus_concepts(
                1, self.today, preferred_concept_key='contribution_connection',
            )
        self.assertEqual([item['concept_key'] for item in available], ['values_alignment'])
        self.assertEqual(selected['concept_key'], 'values_alignment')

    def test_actual_text_day_is_unscored_even_when_history_uses_a_legacy_choice_definition(self):
        concept = self.text_concept(True)
        concept['input_type'] = 'choice'
        concept['score'] = 0
        concept['week'][0]['input_type'] = 'text'
        detail = {'concepts': [concept]}
        recent = daily_habits._recent_concept_focuses(
            detail, self.today, pillar_key='purpose', pillar_label='Purpose',
        )
        with patch.object(daily_habits, 'tracker_today', return_value=self.today):
            anchored = daily_habits._anchored_concept_focuses(
                detail, self.today, pillar_key='purpose', pillar_label='Purpose',
            )
        candidate = coach_insight._concept_candidate(self.pillar, concept, anchor=self.today)
        self.assertEqual(recent, [])
        self.assertEqual(anchored, [])
        self.assertFalse(candidate['has_signal'])
        self.assertEqual(candidate['recent_missing'], 0)

    def test_previous_text_day_does_not_count_as_missing_for_a_legacy_choice_day(self):
        concept = {
            'concept_key': 'contribution_connection', 'label': 'Contribution',
            'input_type': 'choice', 'score': 100, 'target_period': 'week',
            'week': [
                {'date': self.today.isoformat(), 'input_type': 'choice',
                 'value_label': 'Yes', 'score': 100, 'target_met': True},
                {'date': (self.today - timedelta(days=1)).isoformat(), 'input_type': 'text',
                 'value_label': 'Recorded', 'value_text': 'I listened to a friend.',
                 'score': None, 'target_met': None},
            ],
        }
        recent = daily_habits._recent_concept_focuses(
            {'concepts': [concept]}, self.today, pillar_key='purpose', pillar_label='Purpose',
        )[0]
        candidate = coach_insight._concept_candidate(self.pillar, concept, anchor=self.today)
        self.assertEqual(recent['missing'], 0)
        self.assertEqual(recent['signal'], 'on_track')
        self.assertEqual(recent['latest_value'], 'Yes')
        self.assertEqual(candidate['recent_missing'], 0)
        self.assertEqual(candidate['recent_average'], 100)

    def test_preferred_text_does_not_become_a_daily_habit_recommendation(self):
        with patch.object(daily_habits, 'get_pillar_tracker_detail', return_value={
            'concepts': [self.text_concept(False), self.rating_concept()],
        }):
            available, selected = daily_habits._select_focus_concepts(
                1, {'pillars': [self.pillar]}, today=self.today,
                preferred_concept_key='contribution_connection',
            )
        self.assertEqual([item['concept_key'] for item in available], ['values_alignment'])
        self.assertEqual(selected['concept_key'], 'values_alignment')

    def test_text_has_no_numeric_target_options_while_ratings_keep_day_counts(self):
        with patch.object(weekly_objectives, 'tracker_concepts_for_pillar', return_value=self.definitions):
            self.assertEqual(weekly_objectives._concept_target_options(1, 'purpose', 'contribution_connection'), [])
            self.assertEqual(
                [item['value'] for item in weekly_objectives._concept_target_options(1, 'purpose', 'values_alignment')],
                list(range(8)),
            )

    def test_setup_lists_only_two_numeric_targets_without_changing_old_krs(self):
        session = MagicMock()
        factory = MagicMock()
        factory.return_value.__enter__.return_value = session
        contribution = SimpleNamespace(target_num=5, actual_num=3, status='active')
        def targets(_user, pillar, definitions):
            return {item.concept_key: pillar_tracker._default_resolved_target(pillar, item) for item in definitions}
        with patch.object(weekly_objectives, 'SessionLocal', factory), \
             patch.object(weekly_objectives, 'tracker_concepts_for_pillar', return_value=self.definitions), \
             patch.object(weekly_objectives, '_resolve_pillar_targets_for_user', side_effect=targets), \
             patch.object(weekly_objectives, '_primary_krs_by_concept', return_value=(
                 SimpleNamespace(objective='Purpose'), {'contribution_connection': contribution}, [],
             )):
            result = weekly_objectives._objective_concepts_payload(1, 'purpose')
        self.assertEqual(result['concept_count'], 2)
        self.assertEqual([item['concept_key'] for item in result['concepts']],
                         ['meaning_fulfilment', 'values_alignment'])
        self.assertEqual(vars(contribution), {'target_num': 5, 'actual_num': 3, 'status': 'active'})
        session.add.assert_not_called()
        session.commit.assert_not_called()

    def test_saving_numeric_targets_preserves_text_concept_primary_and_duplicate_krs(self):
        session = MagicMock()
        factory = MagicMock()
        factory.return_value.__enter__.return_value = session
        objective = SimpleNamespace(id=11, cycle_id=1, objective='Purpose')
        primary = {
            item.concept_key: SimpleNamespace(
                id=index + 1, target_num=4, actual_num=2, status='active',
                notes=json.dumps({'concept_key': 'purpose.' + item.concept_key}),
            )
            for index, item in enumerate(self.definitions)
        }
        duplicate = SimpleNamespace(
            id=90, status='active', target_num=3,
            notes=json.dumps({'concept_key': 'purpose.contribution_connection'}),
        )
        old_primary = dict(vars(primary['contribution_connection']))
        old_duplicate = dict(vars(duplicate))
        with patch.object(weekly_objectives, 'SessionLocal', factory), \
             patch.object(weekly_objectives, 'active_pillar_keys', return_value=['purpose']), \
             patch.object(weekly_objectives, 'tracker_concepts_for_pillar', return_value=self.definitions), \
             patch.object(weekly_objectives, 'ensure_cycle', return_value=SimpleNamespace(id=3)), \
             patch.object(weekly_objectives, '_primary_krs_by_concept', return_value=(objective, primary, [duplicate])), \
             patch.object(weekly_objectives, 'get_weekly_objectives_config', return_value={'saved': True}):
            result = weekly_objectives.save_weekly_objectives_config(
                1, pillar_key='purpose', concept_targets={
                    'meaning_fulfilment': 6, 'values_alignment': 5,
                    'contribution_connection': {'unscored': 'ignore this obsolete target'},
                },
            )
        self.assertEqual(result, {'saved': True})
        self.assertEqual(primary['meaning_fulfilment'].target_num, 6)
        self.assertEqual(primary['values_alignment'].target_num, 5)
        self.assertEqual(vars(primary['contribution_connection']), old_primary)
        self.assertEqual(vars(duplicate), old_duplicate)
        self.assertNotIn(primary['contribution_connection'], [call.args[0] for call in session.add.call_args_list])
        self.assertNotIn(duplicate, [call.args[0] for call in session.add.call_args_list])
        session.delete.assert_not_called()
        session.commit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
