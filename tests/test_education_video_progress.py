import unittest
from contextlib import ExitStack
from datetime import date
from types import SimpleNamespace as Row
from unittest.mock import MagicMock, patch
from app import education_plan as education


class VideoProgressTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.progress = Row(id=41, lesson_date=date(2026, 9, 28), watch_pct=None, watched_seconds=None,
                            video_completed_at=None, quiz_completed_at=None, completed_at=None,
                            completion_status='pending', lesson_variant_id=17)
        self.variant = Row(id=17, programme_day_id=12)
        self.day = Row(id=12, programme_id=5)
        self.plan = Row(id=3, pillar_key='recovery')
        self.session = MagicMock()
        self.session.get.side_effect = lambda model, key: {
            education.EducationLessonVariant: self.variant if key == 17 else None,
            education.EducationProgrammeDay: self.day,
            education.EducationProgramme: Row(id=5),
        }.get(model)
        self.session.execute.return_value.scalars.return_value.one.return_value = self.progress
        sessions = stack.enter_context(patch.object(education, 'SessionLocal'))
        sessions.return_value.__enter__.return_value = self.session
        for name, result in {
            'ensure_education_plan_schema': None,
            '_programme_is_available_in_app': True,
            'build_daily_tracker_generation_context_snapshot': {'context': {}, 'context_hash': 'test'},
            '_assessment_snapshot': {},
            '_get_or_create_programme_plan': self.plan,
            '_get_or_create_day_progress': self.progress,
            '_quiz_row': Row(id=9),
            '_lesson_variant_has_playable_media': True,
            '_sync_plan_streaks': None,
            '_clear_education_explore_catalog_cache': None,
        }.items():
            setattr(self, name, stack.enter_context(patch.object(education, name, return_value=result)))
        self.default_lesson = stack.enter_context(patch.object(education, '_lesson_state'))

    def record(self, pct, seconds=60, variant=17):
        return education.record_education_video_progress(7, watch_pct=pct, watched_seconds=seconds,
                                                         lesson_variant_id=variant, anchor=date(2026, 9, 28))

    def test_watching_selected_lesson_records_video_without_completing_quiz(self):
        result = self.record(100)
        self.assertTrue(result['video_progress_applied'])
        self.assertEqual(result['lesson_variant_id'], 17)
        self.assertEqual(self.progress.watch_pct, 100)
        self.assertIsNotNone(self.progress.video_completed_at)
        self.assertIsNone(self.progress.quiz_completed_at)
        self.assertEqual(self.progress.completion_status, 'video_done')
        self.assertIsNone(self.progress.completed_at)
        self.default_lesson.assert_not_called()
        self.assertEqual(self._get_or_create_programme_plan.call_args.kwargs['user_id'], 7)
        self.assertIs(self._get_or_create_day_progress.call_args.kwargs['lesson_variant'], self.variant)
        self.session.commit.assert_called_once()

    def test_partial_replay_cannot_reduce_progress_or_clear_completed_quiz(self):
        self.record(95)
        self.progress.quiz_completed_at = education._now_utc()
        self.record(20, 10)
        self.assertEqual(self.progress.watch_pct, 95)
        self.assertEqual(self.progress.watched_seconds, 60)
        self.assertEqual(self.progress.completion_status, 'completed')

    def test_unknown_lesson_cannot_record_against_default_lesson(self):
        result = self.record(100, variant=999)
        self.assertFalse(result['video_progress_applied'])
        self._get_or_create_day_progress.assert_not_called()
        self.default_lesson.assert_not_called()
        self.assertIsNone(self.progress.watch_pct)

    def test_partial_watch_stays_pending(self):
        self.record(20)
        self.assertEqual(self.progress.completion_status, 'pending')
        self.assertIsNone(self.progress.video_completed_at)
