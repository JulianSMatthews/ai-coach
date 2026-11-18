"""Exact Purpose questions support written contribution and preserve old scores."""
import unittest
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import pillar_tracker as tracker


class PurposeCheckinTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.current = tracker.tracker_concepts_for_pillar('purpose')
        self.previous = tracker._PREVIOUS_PURPOSE_TRACKER_CONFIG
        self.legacy = tracker._LEGACY_PURPOSE_TRACKER_CONFIG
        self.enterContext(patch.object(tracker, 'tracker_today', return_value=self.today))
        self.enterContext(patch.object(tracker, 'ensure_pillar_tracker_schema'))
        self.enterContext(patch.object(tracker, '_latest_assessment_scores_for_user', return_value={}))
        self.enterContext(patch.object(tracker, '_daily_pillar_quote', return_value='Test quote'))
        self.enterContext(patch.object(tracker, '_daily_pillar_quote_is_generated', return_value=True))
        self.enterContext(patch.object(tracker, '_app_setup_completed_for_user', return_value=True))
        self.enterContext(patch.object(tracker, '_editable_tracker_dates_for_pillar',
                                     return_value=[self.today - timedelta(days=1), self.today]))

    def definitions(self, version):
        return {1: self.legacy, 2: self.previous, 3: self.current}[version]

    def rows(self, *, version=3, contribution='I helped a neighbour.', direction=0, unversioned=False):
        result = {}
        for concept in self.definitions(version):
            meta = {} if unversioned else {'question_set_version': version}
            value = concept.options[-1].value if concept.options else None
            if concept.concept_key == 'contribution_connection':
                if concept.score_mode == 'text':
                    meta['answer_text'] = contribution
                elif isinstance(contribution, (int, float)):
                    value = contribution
            elif concept.concept_key == 'direction_vision':
                value = direction
            result[concept.concept_key] = SimpleNamespace(
                concept_key=concept.concept_key, score_date=self.today,
                value_num=value, meta=meta,
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

    def entries(self, *, version=3, contribution='I helped a neighbour.'):
        result = []
        for concept in self.definitions(version):
            if concept.score_mode == 'text':
                result.append({'concept_key': concept.concept_key, 'text': contribution})
            else:
                result.append({'concept_key': concept.concept_key, 'value': concept.options[-1].value})
        return result

    def save_entries(self, entries, *, existing=None):
        session = MagicMock()
        existing = existing if existing is not None else self.rows(version=1, unversioned=True)
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

    def detail(self, entries, anchor):
        def load(_user, _pillar, requested):
            return {day: rows for day, rows in entries.items()
                    if tracker.start_of_week(day) == tracker.start_of_week(requested)}
        with patch.object(tracker, '_load_week_entries', side_effect=load), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            return tracker.get_pillar_tracker_detail(1, 'purpose', anchor)

    def test_three_exact_questions_keep_ratings_and_accept_written_contribution(self):
        self.assertEqual([concept.concept_key for concept in self.current],
                         ['meaning_fulfilment', 'values_alignment', 'contribution_connection'])
        self.assertEqual([concept.label for concept in self.current],
                         ['Meaning & Direction', 'Values', 'Contribution'])
        self.assertEqual([concept.helper for concept in self.current], [
            'How connected did you feel to what matters most to you today?',
            'How closely did you live according to your values today?',
            "How did you positively contribute to someone else's day?",
        ])
        self.assertEqual([concept.score_mode for concept in self.current], ['likert', 'likert', 'text'])
        self.assertEqual([[option.label for option in concept.options] for concept in self.current], [
            ['Not at all', 'A little', 'Mostly', 'Completely'],
            ['Not at all', 'A little', 'Mostly', 'Completely'],
            [],
        ])

    def test_written_answer_completes_without_becoming_a_contribution_score(self):
        rows = self.rows(contribution='Nothing specific today.')
        self.assertTrue(tracker._day_complete(rows, self.current))
        evaluations = self.evaluations({self.today: rows})
        contribution = evaluations['contribution_connection'][self.today]
        for key in ('score', 'target_met', 'target_reached', 'daily_status', 'daily_positive'):
            self.assertIsNone(contribution[key], key)
        self.assertEqual(tracker._day_score(rows, self.current, evaluations, self.today), 100)

    def test_blank_or_missing_written_answer_does_not_complete(self):
        for text in ('', ' \n\t '):
            with self.subTest(text=text):
                self.assertFalse(tracker._day_complete(self.rows(contribution=text), self.current))
        rows = self.rows()
        rows.pop('contribution_connection')
        self.assertFalse(tracker._day_complete(rows, self.current))

    def test_save_trims_and_persists_text_without_numeric_value_or_grade(self):
        written = '  Helped Sam\nwith <work> & listened.  '
        existing = self.save_entries(self.entries(contribution=written))
        for key in ('meaning_fulfilment', 'values_alignment', 'contribution_connection'):
            self.assertEqual(existing[key].meta['question_set_version'], 3)
        contribution = existing['contribution_connection']
        self.assertEqual(contribution.meta['answer_text'], written.strip())
        self.assertEqual(contribution.value_label, 'Recorded')
        self.assertIsNone(contribution.value_num)
        self.assertIsNone(contribution.score)
        self.assertIsNone(contribution.target_met)
        self.assertEqual(existing['direction_vision'].value_num, 0)
        self.assertNotIn('question_set_version', existing['direction_vision'].meta)

    def test_invalid_text_is_rejected_before_writing(self):
        for text in ('', ' \n\t ', 'a' * 2001, None, False, 0, [], {}):
            with self.subTest(text_type=type(text).__name__, length=len(text) if isinstance(text, str) else None):
                with self.assertRaises(ValueError):
                    self.save_entries(self.entries(contribution=text))

    def test_two_thousand_character_text_is_saved_without_truncation(self):
        written = 'x' * 2000
        existing = self.save_entries(self.entries(contribution=written))
        self.assertEqual(existing['contribution_connection'].meta['answer_text'], written)

    def test_current_detail_returns_text_input_and_recorded_written_response(self):
        written = 'I made time to listen.'
        detail = self.detail({self.today: self.rows(contribution=written)}, self.today)
        self.assertEqual(len(detail['concepts']), 3)
        contribution = detail['concepts'][2]
        self.assertEqual(contribution['input_type'], 'text')
        self.assertEqual(contribution['value_text'], written)
        self.assertEqual(contribution['options'], [])
        self.assertIsNone(contribution['value'])
        self.assertIsNone(contribution['score'])
        day = next(day for day in contribution['week'] if day['is_today'])
        self.assertEqual(day['value_text'], written)
        self.assertEqual(day['value_label'], 'Recorded')
        self.assertTrue(next(day['complete'] for day in detail['days'] if day['is_today']))

    def test_old_three_choice_form_keeps_version_two_and_removes_ghost_text(self):
        existing = self.rows(contribution='Written before an older form was submitted.')
        existing = self.save_entries(self.entries(version=2), existing=existing)
        for row in existing.values():
            self.assertEqual(row.meta['question_set_version'], 2)
            self.assertNotIn('answer_text', row.meta)
        self.assertEqual(existing['contribution_connection'].value_num, 1)
        self.assertEqual(tracker._recorded_day_concepts(existing, self.current), self.previous)

    def test_old_four_question_form_keeps_version_one_after_a_written_save(self):
        existing = self.rows()
        existing['direction_vision'] = self.rows(version=1)['direction_vision']
        existing = self.save_entries(self.entries(version=1), existing=existing)
        self.assertTrue(all(row.meta['question_set_version'] == 1 for row in existing.values()))
        self.assertTrue(all('answer_text' not in row.meta for row in existing.values()))
        self.assertEqual(tracker._recorded_day_concepts(existing, self.current), self.legacy)

    def test_mixed_versions_preserve_numeric_history_and_exclude_new_text_from_scores(self):
        old_day = self.today - timedelta(days=2)
        previous_day = self.today - timedelta(days=1)
        entries = {
            old_day: self.rows(version=1, unversioned=True),
            previous_day: self.rows(version=2, contribution=0),
            self.today: self.rows(contribution='Nothing specific today.'),
        }
        evaluations = self.evaluations(entries)
        self.assertEqual(tracker._day_score(entries[old_day], self.current, evaluations, old_day), 75)
        self.assertEqual(tracker._day_score(entries[previous_day], self.current, evaluations, previous_day), 67)
        self.assertEqual(tracker._day_score(entries[self.today], self.current, evaluations, self.today), 100)
        self.assertIsNone(evaluations['direction_vision'][self.today]['value'])
        self.assertIsNone(evaluations['contribution_connection'][self.today]['score'])
        self.assertEqual(tracker._week_score(entries, self.current, evaluations,
                                            tracker._week_days(self.today)), 81)

    def test_legacy_three_unversioned_answers_remain_incomplete(self):
        rows = self.rows(version=1, unversioned=True)
        rows.pop('direction_vision')
        self.assertFalse(tracker._day_complete(rows, self.current))
        self.assertTrue(tracker._day_complete(self.rows(version=1, unversioned=True), self.current))

    def test_historical_four_and_three_choice_views_keep_original_formats(self):
        for version, expected_count, question in (
            (1, 4, 'Did you positively contribute to or connect with someone today?'),
            (2, 3, "Did you positively contribute to someone else's day today?"),
        ):
            with self.subTest(version=version):
                old_day = date(2026, 11, 10)
                detail = self.detail({old_day: self.rows(version=version)}, old_day)
                self.assertEqual(len(detail['concepts']), expected_count)
                contribution = next(concept for concept in detail['concepts']
                                    if concept['concept_key'] == 'contribution_connection')
                self.assertEqual(contribution['helper'], question)
                self.assertEqual(contribution['input_type'], 'choice')
                self.assertIsNone(contribution.get('value_text'))
                self.assertEqual([option['label'] for option in contribution['options']], ['No', 'Yes'])

    def test_historical_mixed_week_keeps_written_answers_and_retired_direction(self):
        old_day = date(2026, 11, 10)
        new_day = old_day + timedelta(days=1)
        written = 'Helped a friend with their plans.'
        detail = self.detail({old_day: self.rows(version=1), new_day: self.rows(contribution=written)}, old_day)
        self.assertEqual(detail['pillar']['active_date'], new_day.isoformat())
        contribution = next(concept for concept in detail['concepts']
                            if concept['concept_key'] == 'contribution_connection')
        self.assertEqual(contribution['input_type'], 'text')
        self.assertEqual(contribution['value_text'], written)
        by_day = {day['date']: day for day in contribution['week']}
        self.assertIsNone(by_day[old_day.isoformat()].get('value_text'))
        self.assertEqual(by_day[new_day.isoformat()]['value_text'], written)
        retired = next(concept for concept in detail['concepts'] if concept['concept_key'] == 'direction_vision')
        retired_days = {day['date']: day for day in retired['week']}
        self.assertEqual(retired_days[old_day.isoformat()]['value_label'], 'No')
        self.assertIsNone(retired_days[new_day.isoformat()]['value_label'])
        self.assertEqual(detail['pillar']['tracker_score'], 88)

    def test_other_pillar_question_counts_are_unchanged(self):
        expected = {'reflection': 3, 'resilience': 4, 'nutrition': 4, 'training': 3, 'recovery': 3}
        self.assertEqual({key: len(tracker.tracker_concepts_for_pillar(key)) for key in expected}, expected)


if __name__ == '__main__':
    unittest.main()
