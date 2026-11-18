"""Retired written answers stay private when Purpose returns to Yes/No."""
import json
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import pillar_tracker as tracker


class PurposePrivateHistoryTests(unittest.TestCase):
    private_answer = 'PRIVATE HISTORICAL ANSWER: I helped a neighbour.'

    def setUp(self):
        self.today = date(2026, 11, 18)
        self.current = tracker.tracker_concepts_for_pillar('purpose')
        self.enterContext(patch.object(tracker, 'tracker_today', return_value=self.today))
        self.enterContext(patch.object(tracker, 'ensure_pillar_tracker_schema'))
        self.enterContext(patch.object(tracker, '_latest_assessment_scores_for_user', return_value={}))
        self.enterContext(patch.object(tracker, '_daily_pillar_quote', return_value='Test quote'))
        self.enterContext(patch.object(tracker, '_daily_pillar_quote_is_generated', return_value=True))
        self.enterContext(patch.object(tracker, '_editable_tracker_dates_for_pillar',
                                     return_value=[self.today - timedelta(days=1), self.today]))

    def rows(self):
        rows = {
            concept.concept_key: SimpleNamespace(
                concept_key=concept.concept_key,
                value_num=concept.options[-1].value,
                meta={'question_set_version': 3},
            )
            for concept in self.current
        }
        rows['values_alignment'].value_num = 0
        # Even a stale numeric value must not reinterpret an old written answer.
        rows['contribution_connection'].meta['answer_text'] = self.private_answer
        return rows

    def targets(self, _user, pillar, concepts):
        return {concept.concept_key: tracker._default_resolved_target(pillar, concept)
                for concept in concepts}

    def detail(self, rows, day):
        def load(_user, _pillar, anchor):
            return {day: rows} if tracker.start_of_week(day) == tracker.start_of_week(anchor) else {}
        with patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            return tracker.get_pillar_tracker_detail(1, 'purpose', day)

    def test_written_version_three_day_completes_without_inventing_contribution_score(self):
        rows = self.rows()
        evaluations = tracker._build_concept_week_evaluations(
            {self.today: rows}, self.current, self.targets(1, 'purpose', self.current),
            tracker._week_days(self.today),
        )
        self.assertTrue(tracker._day_complete(rows, self.current))
        self.assertEqual(tracker._day_score(rows, self.current, evaluations, self.today), 50)
        contribution = evaluations['contribution_connection'][self.today]
        self.assertTrue(contribution['not_applicable'])
        for key in ('row', 'value', 'value_label', 'score', 'target_met', 'daily_status'):
            self.assertIsNone(contribution[key], key)

    def test_public_history_never_returns_private_text_or_text_input_fields(self):
        day = self.today - timedelta(days=8)
        detail = self.detail(self.rows(), day)
        serialized = json.dumps(detail)
        self.assertNotIn(self.private_answer, serialized)
        for field in ('answer_text', 'value_text', 'input_type'):
            self.assertNotIn(field, serialized)
        self.assertEqual(len(detail['concepts']), 3)
        contribution = next(item for item in detail['concepts']
                            if item['concept_key'] == 'contribution_connection')
        self.assertEqual([option['label'] for option in contribution['options']], ['No', 'Yes'])
        self.assertIsNone(contribution['value'])
        self.assertIsNone(contribution['value_label'])
        self.assertEqual(detail['pillar']['tracker_score'], 50)

    def test_numeric_resave_preserves_private_metadata_and_scores_yes_no_normally(self):
        for value, label, score in ((0, 'No', 0), (1, 'Yes', 100)):
            with self.subTest(value=value):
                rows = self.rows()
                session = MagicMock()
                session.execute.return_value.scalars.return_value.all.return_value = list(rows.values())
                factory = MagicMock()
                factory.return_value.__enter__.return_value = session
                entries = [{'concept_key': key, 'value': row.value_num}
                           for key, row in rows.items()]
                entries[-1]['value'] = value
                with patch.object(tracker, 'SessionLocal', factory), \
                     patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets), \
                     patch.object(tracker, '_record_latest_tracker_focus'), \
                     patch.object(tracker, '_sync_pillar_tracker_actuals_to_okrs'), \
                     patch.object(tracker, 'get_pillar_tracker_detail', return_value={'saved': True}):
                    tracker.save_pillar_tracker_day(1, 'purpose', score_date=self.today, entries=entries)
                answer = rows['contribution_connection']
                self.assertEqual(answer.meta['answer_text'], self.private_answer)
                self.assertEqual(answer.meta['question_set_version'], 2)
                self.assertEqual(answer.value_num, value)
                self.assertEqual(answer.value_label, label)
                self.assertEqual(answer.score, score)
                self.assertFalse(tracker._is_historical_written_contribution(answer))
                self.assertNotIn(self.private_answer, json.dumps(self.detail(rows, self.today)))
                session.delete.assert_not_called()
                session.commit.assert_called_once()

    def test_text_only_submission_is_rejected_before_database_writes(self):
        entries = [{'concept_key': concept.concept_key, 'value': concept.options[-1].value}
                   for concept in self.current]
        entries[-1] = {'concept_key': 'contribution_connection', 'text': self.private_answer}
        with patch.object(tracker, 'SessionLocal') as sessions, \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            with self.assertRaisesRegex(ValueError, 'Invalid value for contribution_connection'):
                tracker.save_pillar_tracker_day(1, 'purpose', score_date=self.today, entries=entries)
        sessions.assert_not_called()


if __name__ == '__main__':
    unittest.main()
