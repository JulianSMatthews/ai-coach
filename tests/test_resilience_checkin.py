"""Resilience revisions preserve legacy answers and keep neutral days unscored."""
import unittest
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import pillar_tracker as tracker


class ResilienceCheckinTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.current = tracker.tracker_concepts_for_pillar('resilience')
        self.legacy = tracker._LEGACY_RESILIENCE_TRACKER_CONFIG
        self.enterContext(patch.object(tracker, 'tracker_today', return_value=self.today))
        self.enterContext(patch.object(tracker, 'ensure_pillar_tracker_schema'))
        self.enterContext(patch.object(tracker, '_latest_assessment_scores_for_user', return_value={}))
        self.enterContext(patch.object(tracker, '_daily_pillar_quote', return_value='Test quote'))
        self.enterContext(patch.object(tracker, '_daily_pillar_quote_is_generated', return_value=True))
        self.enterContext(patch.object(tracker, '_app_setup_completed_for_user', return_value=True))
        self.enterContext(patch.object(tracker, '_editable_tracker_dates_for_pillar',
                                     return_value=[self.today - timedelta(days=1), self.today]))

    def rows(self, *, legacy=False, retired=False, adaptation=1, score_date=None):
        definitions = self.legacy if legacy else self.current
        rows = {
            concept.concept_key: SimpleNamespace(
                concept_key=concept.concept_key,
                value_num=max(option.value for option in concept.options),
                score_date=score_date or self.today,
                meta=None if legacy else {'question_set_version': 2},
            )
            for concept in definitions
        }
        if legacy:
            for key in ('stress_recovery', 'optimism_perspective', 'support_openness'):
                rows[key].value_num = 0
        else:
            rows['adaptability'].value_num = adaptation
            if retired:
                rows.update({key: row for key, row in self.rows(legacy=True).items() if key not in rows})
        return rows

    def targets(self, _user, pillar, concepts):
        return {concept.concept_key: tracker._default_resolved_target(pillar, concept) for concept in concepts}

    def evaluations(self, entries):
        concepts = tracker._week_evaluation_concepts(self.current, entries)
        return tracker._build_concept_week_evaluations(
            entries, self.current, self.targets(1, 'resilience', concepts), tracker._week_days(self.today)
        )

    def load(self, entries, anchor):
        return {day: rows for day, rows in entries.items()
                if tracker.start_of_week(day) == tracker.start_of_week(anchor)}

    def test_current_four_answers_complete_without_retired_questions(self):
        self.assertEqual({concept.concept_key for concept in self.current},
                         {'emotional_regulation', 'positive_connection', 'adaptability', 'support_connection'})
        current = self.rows()
        self.assertTrue(tracker._day_complete(current, self.current))
        del current['support_connection']
        self.assertFalse(tracker._day_complete(current, self.current))
        old_partial = self.rows(legacy=True)
        del old_partial['stress_recovery']
        self.assertFalse(tracker._day_complete(old_partial, self.current))

    def test_neutral_adaptability_completes_but_does_not_lower_score_or_targets(self):
        rows = self.rows(adaptation=-1)
        evaluations = self.evaluations({self.today: rows})
        neutral = evaluations['adaptability'][self.today]
        self.assertTrue(tracker._day_complete(rows, self.current))
        self.assertTrue(neutral['not_applicable'])
        self.assertEqual(neutral['value'], -1)
        self.assertTrue(neutral['value_label'])
        for key in ('score', 'target_met', 'target_reached', 'daily_status', 'daily_positive'):
            self.assertIsNone(neutral[key], key)
        self.assertEqual(tracker._day_score(rows, self.current, evaluations, self.today), 100)
        self.assertEqual(tracker._week_score({self.today: rows}, self.current, evaluations,
                                            tracker._week_days(self.today)), 100)

    def test_neutral_adaptability_remains_selectable_and_neutral_in_detail(self):
        entries = {self.today: self.rows(adaptation=-1)}
        with patch.object(tracker, '_load_week_entries', side_effect=lambda _u, _p, day: self.load(entries, day)), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            detail = tracker.get_pillar_tracker_detail(1, 'resilience', self.today)
        adaptation = next(concept for concept in detail['concepts'] if concept['concept_key'] == 'adaptability')
        self.assertEqual(adaptation['value'], -1)
        self.assertTrue(adaptation['not_applicable'])
        self.assertIsNone(adaptation['score'])
        self.assertIsNone(adaptation['daily_status'])
        today = next(day for day in adaptation['week'] if day['is_today'])
        self.assertTrue(today['not_applicable'])
        self.assertEqual(today['value_label'], adaptation['value_label'])
        self.assertTrue(next(day['complete'] for day in detail['days'] if day['is_today']))

    def test_neutral_days_do_not_reduce_weekly_actuals_or_add_logged_days(self):
        yesterday = self.today - timedelta(days=1)
        entries = {yesterday: self.rows(adaptation=1), self.today: self.rows(adaptation=-1)}
        evaluations = self.evaluations(entries)['adaptability']
        definition = next(concept for concept in self.current if concept.concept_key == 'adaptability')
        target = replace(tracker._default_resolved_target('resilience', definition),
                         source='okr', target_value=7, target_period='week', target_unit='days/week')
        actual = tracker._concept_okr_actual_achieved(evaluations, target, self.today,
                                                     tracker._week_days(self.today))
        self.assertEqual(actual['actual_value'], 1)
        self.assertEqual(actual['logged_days'], 1)
        self.assertTrue(actual['on_track'])

    def test_raw_tracker_sync_excludes_neutral_values(self):
        yesterday = self.today - timedelta(days=1)
        rows = [*self.rows(adaptation=1, score_date=yesterday).values(),
                *self.rows(adaptation=-1).values()]
        definition = next(concept for concept in self.current if concept.concept_key == 'adaptability')
        target = replace(tracker._default_resolved_target('resilience', definition),
                         source='okr', target_value=7, target_period='week', target_unit='days/week')
        kr = SimpleNamespace(id=12, actual_num=None)
        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = rows
        session.execute.return_value.scalars.return_value.first.return_value = None
        with patch.object(tracker, '_resolve_pillar_targets_for_user_with_session',
                          return_value=({'adaptability': target}, {'adaptability': kr})):
            tracker._sync_pillar_tracker_actuals_to_okrs(
                session, user_id=1, pillar_key='resilience', anchor_date=self.today,
                required_concepts=self.current,
            )
        self.assertEqual(kr.actual_num, 1)

    def test_new_weekly_targets_use_day_counts_without_neutral_answer_option(self):
        from app.weekly_objectives import _concept_target_options
        for concept_key in ('adaptability', 'support_connection'):
            with self.subTest(concept_key=concept_key):
                options = _concept_target_options(1, 'resilience', concept_key)
                self.assertEqual([option['value'] for option in options], list(range(8)))

    def test_neutral_does_not_increment_or_break_success_streaks(self):
        yesterday = self.today - timedelta(days=1)
        evaluations = {
            self.today: {'not_applicable': True, 'target_met': None, 'daily_positive': None},
            yesterday: {'not_applicable': False, 'target_met': True, 'daily_positive': True},
        }
        self.assertEqual(tracker._concept_target_streak_days(evaluations, self.today), 1)
        self.assertEqual(tracker._concept_positive_streak_days(evaluations, self.today), 1)
        del evaluations[yesterday]
        self.assertEqual(tracker._concept_target_streak_days(evaluations, self.today), 0)
        self.assertEqual(tracker._concept_positive_streak_days(evaluations, self.today), 0)

    def test_neutral_answer_cannot_be_selected_as_coaching_focus(self):
        with patch.object(tracker, '_set_user_pref_json') as save:
            tracker._record_latest_tracker_focus(
                object(), user_id=1, pillar_key='resilience', score_date=self.today,
                session_day=self.today,
                normalized_rows={'adaptability': {'value_num': -1, 'score': None, 'target_met': None}},
            )
        self.assertIsNone(save.call_args.args[3]['concept_key'])

    def test_legacy_answers_keep_original_five_question_score_and_formats(self):
        entries = {self.today: self.rows(legacy=True)}
        evaluations = self.evaluations(entries)
        self.assertTrue(tracker._day_complete(entries[self.today], self.current))
        self.assertEqual(tracker._day_score(entries[self.today], self.current, evaluations, self.today), 40)
        support = next(concept for concept in self.legacy if concept.concept_key == 'support_openness')
        self.assertEqual([option.label for option in support.options], ['No', 'Yes'])

    def test_legacy_history_uses_original_labels_and_response_formats(self):
        old_day = date(2026, 11, 10)
        entries = {old_day: self.rows(legacy=True)}
        with patch.object(tracker, '_load_week_entries', side_effect=lambda _u, _p, day: self.load(entries, day)), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            detail = tracker.get_pillar_tracker_detail(1, 'resilience', old_day)
        self.assertEqual([concept['concept_key'] for concept in detail['concepts']],
                         [concept.concept_key for concept in self.legacy])
        self.assertEqual(detail['concepts'][0]['label'], 'Calm & Control')
        self.assertEqual(detail['pillar']['tracker_score'], 40)

    def test_mixed_history_retains_old_rows_and_blanks_them_on_new_days(self):
        old_day = date(2026, 11, 10)
        new_day = old_day + timedelta(days=1)
        entries = {old_day: self.rows(legacy=True), new_day: self.rows(retired=True)}
        with patch.object(tracker, '_load_week_entries', side_effect=lambda _u, _p, day: self.load(entries, day)), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets):
            detail = tracker.get_pillar_tracker_detail(1, 'resilience', old_day)
        self.assertEqual(detail['pillar']['active_date'], new_day.isoformat())
        self.assertEqual(detail['pillar']['tracker_score'], 70)
        keys = {concept['concept_key'] for concept in detail['concepts']}
        self.assertTrue({'adaptability', 'support_connection', 'stress_recovery',
                         'optimism_perspective', 'support_openness'}.issubset(keys))
        retired = next(concept for concept in detail['concepts'] if concept['concept_key'] == 'support_openness')
        days = {day['date']: day for day in retired['week']}
        self.assertEqual(days[old_day.isoformat()]['value_label'], 'No')
        self.assertIsNone(days[new_day.isoformat()]['value_label'])
        self.assertIsNone(retired['value'])
        self.assertIsNone(retired['value_label'])

    def test_summary_resolves_retired_custom_targets_for_legacy_days(self):
        entries = {self.today: self.rows(legacy=True)}
        def targets(user, pillar, concepts):
            result = self.targets(user, pillar, concepts)
            if 'stress_recovery' in result:
                result['stress_recovery'] = replace(result['stress_recovery'], source='okr', target_value=7)
            return result
        with patch.object(tracker, 'active_pillar_keys', return_value=['resilience']), \
             patch.object(tracker, '_load_week_entries', return_value=entries), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=targets) as resolve:
            result = tracker.get_pillar_tracker_summary(1)['pillars'][0]
        self.assertIn('stress_recovery', [concept.concept_key for concept in resolve.call_args.args[2]])
        expected = tracker._build_concept_week_evaluations(
            entries, self.legacy, targets(1, 'resilience', self.legacy), tracker._week_days(self.today)
        )
        self.assertEqual(result['tracker_score'],
                         tracker._week_score(entries, self.legacy, expected, tracker._week_days(self.today)))

    def save_entries(self, entries, *, existing=None):
        session = MagicMock()
        existing = self.rows(retired=True) if existing is None else existing
        session.execute.return_value.scalars.return_value.all.return_value = list(existing.values())
        factory = MagicMock()
        factory.return_value.__enter__.return_value = session
        with patch.object(tracker, 'SessionLocal', factory), \
             patch.object(tracker, '_resolve_pillar_targets_for_user', side_effect=self.targets), \
             patch.object(tracker, '_record_latest_tracker_focus'), \
             patch.object(tracker, '_sync_pillar_tracker_actuals_to_okrs'), \
             patch.object(tracker, 'get_pillar_tracker_detail', return_value={'saved': True}):
            result = tracker.save_pillar_tracker_day(1, 'resilience', score_date=self.today, entries=entries)
        self.assertEqual(result, {'saved': True})
        session.delete.assert_not_called()
        session.commit.assert_called_once()
        return existing

    def test_save_four_answers_versions_them_and_persists_neutral_without_score(self):
        entries = [{'concept_key': key, 'value': row.value_num}
                   for key, row in self.rows(adaptation=-1).items()]
        existing = self.save_entries(entries)
        for concept in self.current:
            self.assertEqual(existing[concept.concept_key].meta['question_set_version'], 2)
        self.assertEqual(existing['adaptability'].value_num, -1)
        self.assertIsNone(existing['adaptability'].score)
        self.assertIsNone(existing['adaptability'].target_met)
        self.assertIsNone(existing['stress_recovery'].meta)

    def test_stale_five_answer_form_stays_legacy_after_day_was_saved_in_new_format(self):
        # The leftover new-only rows must not override the newer shared-row version.
        entries = [{'concept_key': key, 'value': row.value_num}
                   for key, row in self.rows(legacy=True).items()]
        existing = self.save_entries(entries, existing=self.rows(retired=True))
        for concept in self.legacy:
            self.assertEqual(existing[concept.concept_key].meta['question_set_version'], 1)
        self.assertEqual(existing['adaptability'].meta['question_set_version'], 2)
        definitions = tracker._recorded_day_concepts(existing, self.current)
        self.assertEqual([concept.concept_key for concept in definitions],
                         [concept.concept_key for concept in self.legacy])
        evaluations = self.evaluations({self.today: existing})
        self.assertEqual(tracker._day_score(existing, self.current, evaluations, self.today), 40)

    def test_raw_tracker_sync_ignores_new_only_rows_left_after_legacy_resave(self):
        entries = [{'concept_key': key, 'value': row.value_num}
                   for key, row in self.rows(legacy=True).items()]
        previous = self.save_entries(entries, existing=self.rows(retired=True))
        for row in previous.values():
            row.score_date = self.today - timedelta(days=1)
        # These valid-looking old v2 rows remain stored after a later v1 save.
        self.assertEqual(previous['adaptability'].meta['question_set_version'], 2)
        self.assertEqual(previous['support_connection'].meta['question_set_version'], 2)
        rows = [*previous.values(), *self.rows().values()]
        targets = self.targets(1, 'resilience', self.current)
        keys = ('adaptability', 'support_connection')
        resolved = {key: replace(targets[key], source='okr', target_value=7,
                                 target_period='week', target_unit='days/week') for key in keys}
        krs = {key: SimpleNamespace(id=index + 20, actual_num=None) for index, key in enumerate(keys)}
        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = rows
        session.execute.return_value.scalars.return_value.first.return_value = None
        with patch.object(tracker, '_resolve_pillar_targets_for_user_with_session', return_value=(resolved, krs)):
            tracker._sync_pillar_tracker_actuals_to_okrs(
                session, user_id=1, pillar_key='resilience', anchor_date=self.today,
                required_concepts=self.current,
            )
        for key in keys:
            with self.subTest(concept_key=key):
                self.assertEqual(krs[key].actual_num, 1)


if __name__ == '__main__':
    unittest.main()
