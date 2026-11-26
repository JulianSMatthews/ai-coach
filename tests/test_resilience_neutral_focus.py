"""A neutral Adaptability answer must not become a missing-answer or support nudge."""
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from app import coach_insight, daily_habits


class NeutralFocusTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.yesterday = self.today - timedelta(days=1)
        self.pillar = {'pillar_key': 'resilience', 'label': 'Resilience', 'score': 67}

    def day(self, day, *, neutral=False, score=0, target_met=False):
        return {
            'date': day.isoformat(),
            'value_label': 'No challenges or unexpected situations today' if neutral else 'A little',
            'not_applicable': neutral,
            'score': None if neutral else score,
            'target_met': None if neutral else target_met,
            'daily_positive': None if neutral else target_met,
            'target_reached': None if neutral else target_met,
        }

    def concept(self, key='adaptability', *, rows=None, score=None, neutral=False):
        return {
            'concept_key': key, 'label': key.replace('_', ' ').title(),
            'score': score, 'not_applicable': neutral, 'target_period': 'week',
            'week': rows or [],
        }

    def recent(self, concepts):
        return daily_habits._recent_concept_focuses(
            {'concepts': concepts}, self.today, pillar_key='resilience', pillar_label='Resilience'
        )

    def test_neutral_current_answer_is_excluded_from_daily_focus_even_after_a_miss(self):
        neutral = self.concept(neutral=True, rows=[self.day(self.yesterday), self.day(self.today, neutral=True)])
        actual_issue = self.concept('support_connection', rows=[self.day(self.today)], score=0)
        rows = self.recent([neutral, actual_issue])
        self.assertEqual([row['concept_key'] for row in rows], ['support_connection'])
        self.assertEqual(rows[0]['signal'], 'missed_today')

    def test_yesterdays_neutral_answer_counts_as_neither_missing_nor_negative(self):
        concept = self.concept(rows=[
            self.day(self.yesterday, neutral=True),
            self.day(self.today, score=100, target_met=True),
        ], score=100)
        row = self.recent([concept])[0]
        self.assertEqual(row['misses'], 0)
        self.assertEqual(row['missing'], 0)
        self.assertEqual(row['signal'], 'on_track')

    def test_neutral_yesterday_does_not_hide_a_genuinely_missing_today(self):
        concept = self.concept(rows=[self.day(self.yesterday, neutral=True)])
        row = self.recent([concept])[0]
        self.assertEqual(row['missing'], 1)
        self.assertEqual(row['misses'], 0)
        self.assertEqual(row['signal'], 'not_logged_today')
        self.assertIsNone(row['latest_value'])

    def test_anchored_review_does_not_treat_neutral_as_support_needed(self):
        neutral = self.concept(neutral=True, rows=[self.day(self.today, neutral=True)], score=0)
        actual_issue = self.concept('emotional_regulation', rows=[self.day(self.today)], score=0)
        with patch.object(daily_habits, 'tracker_today', return_value=self.today):
            rows = daily_habits._anchored_concept_focuses(
                {'concepts': [neutral, actual_issue]}, self.today,
                pillar_key='resilience', pillar_label='Resilience',
            )
        self.assertEqual([row['concept_key'] for row in rows], ['emotional_regulation'])
        self.assertEqual(rows[0]['signal'], 'missed_today')

    def test_neutral_today_does_not_erase_a_low_week_to_date_insight_score(self):
        concept = {
            'concept_key': 'adaptability', 'label': 'Adaptability', 'score': 0,
            'not_applicable_days_count': 1,
            'days': [self.day(self.yesterday), self.day(self.today, neutral=True)],
        }
        candidate = coach_insight._concept_candidate(self.pillar, concept, anchor=self.today)
        self.assertFalse(candidate['not_applicable'])
        self.assertEqual(candidate['current_score'], 0)
        self.assertEqual(candidate['status'], 'off_track')

    def test_all_neutral_days_are_not_missing_or_off_track_in_insight(self):
        concept = {
            'concept_key': 'adaptability', 'label': 'Adaptability', 'score': None,
            'not_applicable_days_count': 2,
            'days': [self.day(self.yesterday, neutral=True), self.day(self.today, neutral=True)],
        }
        candidate = coach_insight._concept_candidate(self.pillar, concept, anchor=self.today)
        self.assertTrue(candidate['not_applicable'])
        self.assertIsNone(candidate['current_score'])
        self.assertEqual(candidate['status'], 'not_applicable')

    def test_preferred_neutral_concept_cannot_override_a_real_insight_issue(self):
        neutral = {'concept_key': 'adaptability', 'label': 'Adaptability', 'score': None,
                   'not_applicable_days_count': 1, 'days': [self.day(self.today, neutral=True)]}
        issue = {'concept_key': 'support_connection', 'label': 'Support Connection', 'score': 0,
                 'not_applicable_days_count': 0, 'days': [self.day(self.today)]}
        pillar = {**self.pillar, 'concepts': [neutral, issue]}
        with patch.object(coach_insight, 'get_pillar_progress', return_value={'pillars': [pillar]}), \
             patch.object(coach_insight, 'tracker_today', return_value=self.today):
            available, selected, _ = coach_insight._select_focus_concepts(
                1, self.today, preferred_concept_key='adaptability'
            )
        self.assertEqual([row['concept_key'] for row in available], ['support_connection'])
        self.assertEqual(selected['concept_key'], 'support_connection')


if __name__ == '__main__':
    unittest.main()
