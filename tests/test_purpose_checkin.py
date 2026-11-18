"""Purpose uses three choice questions while retaining four-question history."""
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import pillar_tracker as tracker


class PurposeCheckinTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.current = tracker.tracker_concepts_for_pillar('purpose')
        self.legacy = tracker._LEGACY_PURPOSE_TRACKER_CONFIG
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
                concept_key=concept.concept_key,
                value_num=concept.options[-1].value,
                meta={'question_set_version': version} if version is not None else None,
            )
            for concept in self.current
        }
        if retired:
            result['direction_vision'] = SimpleNamespace(
                concept_key='direction_vision', value_num=0, meta=None,
            )
        return result

    def targets(self, _user, pillar, concepts):
        return {concept.concept_key: tracker._default_resolved_target(pillar, concept)
                for concept in concepts}

    def evaluations(self, entries):
        concepts = tracker._week_evaluation_concepts(self.current, entries)
        return tracker._build_concept_week_evaluations(
            entries, self.current, self.targets(1, 'purpose', concepts), tracker._week_days(self.today)
        )

    def save_entries(self, entries, *, existing=None):
        session = MagicMock()
        existing = existing if existing is not None else self.rows(retired=True)
        session.execute.return_value.scalars.return_value.all.return_value = list(existing.values())
        factory = MagicMock()
        factory.return_value.__enter__.return_value = session
        with patch.object(tracker, 'SessionLocal', factory), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets), \
             patch.object(tracker, '_record_latest_tracker_focus'), \
             patch.object(tracker, '_sync_pillar_tracker_actuals_to_okrs'), \
             patch.object(tracker, 'get_pillar_tracker_detail', return_value={'saved': True}):
            result = tracker.save_pillar_tracker_day(1, 'purpose', score_date=self.today, entries=entries)
        self.assertEqual(result, {'saved': True})
        session.delete.assert_not_called()
        session.commit.assert_called_once()
        return existing

    def test_three_questions_keep_the_existing_rating_and_yes_no_formats(self):
        self.assertEqual([concept.concept_key for concept in self.current],
                         ['meaning_fulfilment', 'values_alignment', 'contribution_connection'])
        self.assertEqual([concept.label for concept in self.current],
                         ['Meaning & Direction', 'Values', 'Contribution'])
        self.assertEqual([concept.helper for concept in self.current], [
            'How connected did you feel to what matters most to you today?',
            'How closely did you live according to your values today?',
            "Did you positively contribute to someone else's day today?",
        ])
        self.assertEqual([concept.score_mode for concept in self.current], ['likert', 'likert', 'binary'])
        self.assertEqual([[option.label for option in concept.options] for concept in self.current], [
            ['Not at all', 'A little', 'Mostly', 'Completely'],
            ['Not at all', 'A little', 'Mostly', 'Completely'],
            ['No', 'Yes'],
        ])

    def test_three_current_answers_complete_but_three_unversioned_old_answers_do_not(self):
        self.assertTrue(tracker._day_complete(self.rows(version=2), self.current))
        self.assertFalse(tracker._day_complete(self.rows(), self.current))
        self.assertTrue(tracker._day_complete(self.rows(retired=True), self.current))
        incomplete = self.rows(version=2)
        incomplete.pop('contribution_connection')
        self.assertFalse(tracker._day_complete(incomplete, self.current))

    def test_mixed_week_preserves_old_direction_score_and_ignores_it_for_new_answers(self):
        yesterday = self.today - timedelta(days=1)
        entries = {
            yesterday: self.rows(retired=True),
            self.today: self.rows(version=2, retired=True),
        }
        evaluations = self.evaluations(entries)
        self.assertEqual(tracker._day_score(entries[yesterday], self.current, evaluations, yesterday), 75)
        self.assertEqual(tracker._day_score(entries[self.today], self.current, evaluations, self.today), 100)
        self.assertIsNone(evaluations['direction_vision'][self.today]['value'])
        self.assertEqual(tracker._week_score(entries, self.current, evaluations,
                                            tracker._week_days(self.today)), 88)

    def test_save_accepts_three_choice_answers_and_keeps_the_old_direction_row(self):
        entries = [{'concept_key': concept.concept_key, 'value': concept.options[-1].value}
                   for concept in self.current]
        existing = self.save_entries(entries)
        for concept in self.current:
            self.assertEqual(existing[concept.concept_key].meta['question_set_version'], 2)
        self.assertEqual(existing['direction_vision'].value_num, 0)
        self.assertIsNone(existing['direction_vision'].meta)

    def test_stale_four_question_form_retains_its_original_version_after_a_new_save(self):
        existing = self.rows(version=2, retired=True)
        entries = [{'concept_key': concept.concept_key, 'value': concept.options[-1].value}
                   for concept in self.legacy]
        existing = self.save_entries(entries, existing=existing)
        self.assertTrue(all(row.meta['question_set_version'] == 1 for row in existing.values()))
        self.assertEqual(tracker._recorded_day_concepts(existing, self.current), self.legacy)

    def test_historical_detail_keeps_four_original_questions_and_current_detail_uses_three(self):
        old_day = date(2026, 11, 10)
        entries = {old_day: self.rows(retired=True), self.today: self.rows(version=2)}
        def load(_user, _pillar, anchor):
            return {day: rows for day, rows in entries.items()
                    if tracker.start_of_week(day) == tracker.start_of_week(anchor)}
        with patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            historical = tracker.get_pillar_tracker_detail(1, 'purpose', old_day)
            current = tracker.get_pillar_tracker_detail(1, 'purpose', self.today)
        self.assertEqual([concept['concept_key'] for concept in historical['concepts']],
                         [concept.concept_key for concept in self.legacy])
        self.assertEqual(historical['concepts'][0]['helper'], 'How meaningful and worthwhile did today feel?')
        self.assertEqual(historical['pillar']['tracker_score'], 75)
        self.assertEqual(len(current['concepts']), 3)
        self.assertTrue(next(day['complete'] for day in current['days'] if day['is_today']))

    def test_mixed_historical_week_retains_the_old_direction_row_but_blanks_new_day(self):
        old_day = date(2026, 11, 10)
        new_day = old_day + timedelta(days=1)
        entries = {old_day: self.rows(retired=True), new_day: self.rows(version=2, retired=True)}
        def load(_user, _pillar, anchor):
            return entries if tracker.start_of_week(anchor) == tracker.start_of_week(old_day) else {}
        with patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            detail = tracker.get_pillar_tracker_detail(1, 'purpose', old_day)
        self.assertEqual(detail['pillar']['active_date'], new_day.isoformat())
        retired = next(concept for concept in detail['concepts'] if concept['concept_key'] == 'direction_vision')
        days = {day['date']: day for day in retired['week']}
        self.assertEqual(days[old_day.isoformat()]['value_label'], 'No')
        self.assertIsNone(days[new_day.isoformat()]['value_label'])
        self.assertIsNone(retired['value'])
        self.assertIsNone(retired['value_label'])
        self.assertEqual(detail['pillar']['tracker_score'], 88)

    def test_other_pillar_question_counts_are_unchanged(self):
        expected = {'reflection': 3, 'resilience': 4, 'nutrition': 4, 'training': 3, 'recovery': 3}
        self.assertEqual({key: len(tracker.tracker_concepts_for_pillar(key)) for key in expected}, expected)


if __name__ == '__main__':
    unittest.main()
