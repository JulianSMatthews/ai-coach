import unittest
from datetime import date, datetime
from sqlalchemy import create_engine, MetaData, JSON
from sqlalchemy.orm import Session
from app.models import EducationProgramme, EducationProgrammeDay, UserEducationPlan, UserEducationDayProgress, EducationLessonVariant, UserEducationQuizAnswer
from app.admin_user_learning import load_user_learning


class AdminLearningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://')
        self.addCleanup(self.engine.dispose)
        metadata = MetaData()
        for source in EducationProgramme.metadata.tables.values():
            source.to_metadata(metadata)
        for model in (EducationProgramme, EducationProgrammeDay, UserEducationPlan, UserEducationDayProgress, EducationLessonVariant, UserEducationQuizAnswer):
            table = metadata.tables[model.__tablename__]
            for column in table.columns:
                if column.type.__class__.__name__ == 'JSONB':
                    column.type = JSON()
            # Production schema migrations manage indexes; this fixture tests data selection.
            table.indexes.clear()
            table.create(self.engine)
        self.session = self.enterContext(Session(self.engine))
        self.today = date(2026, 9, 28)
        self.session.add(EducationProgramme(id=1, pillar_key='recovery', code='recovery', name='Recovery'))
        self.session.add_all([
            EducationProgrammeDay(id=1, programme_id=1, day_index=1, concept_key='restoration', concept_label='Enjoyment / Restoration'),
            EducationProgrammeDay(id=2, programme_id=1, day_index=2, concept_key='sleep', concept_label='Sleep'),
            UserEducationPlan(id=1, user_id=4, programme_id=1, pillar_key='recovery', starts_on=self.today, status='completed', entry_concept_label='Wrong plan entry label'),
            UserEducationPlan(id=2, user_id=4, programme_id=1, pillar_key='recovery', starts_on=self.today, status='active'),
            UserEducationPlan(id=3, user_id=5, programme_id=1, pillar_key='recovery', starts_on=self.today, status='active'),
        ])
        self.session.flush()
        self.completed = UserEducationDayProgress(id=1, user_plan_id=1, programme_day_id=1, lesson_date=self.today, watch_pct=100, quiz_score_pct=80, video_completed_at=datetime(2026,9,28,8), quiz_completed_at=datetime(2026,9,28,8,5), completed_at=datetime(2026,9,28,8,5), completion_status='completed', updated_at=datetime(2026,9,28,8,5))
        self.pending = UserEducationDayProgress(id=2, user_plan_id=2, programme_day_id=2, lesson_date=self.today, completion_status='pending', updated_at=datetime(2026,9,28,9))
        other = UserEducationDayProgress(id=3, user_plan_id=3, programme_day_id=2, lesson_date=self.today, watch_pct=100, completion_status='completed', completed_at=datetime(2026,9,28,12), updated_at=datetime(2026,9,28,12))
        self.session.add_all([self.completed, self.pending, other])
        self.session.add(EducationLessonVariant(id=1, programme_day_id=1, level='build', title='Making time to restore'))
        self.completed.lesson_variant_id = 1
        self.session.add_all([
            UserEducationQuizAnswer(user_day_progress_id=1, question_id=1, answer_json=['a'], is_correct=True),
            UserEducationQuizAnswer(user_day_progress_id=1, question_id=2, answer_json=['b'], is_correct=True),
            UserEducationQuizAnswer(user_day_progress_id=1, question_id=3, answer_json=[], is_correct=False),
        ])
        self.session.commit()

    def test_completed_lesson_is_not_hidden_by_new_pending_lesson_or_completed_plan(self):
        result = load_user_learning(self.session, 4, self.today)
        self.assertEqual(result['plan_id'], 1)
        self.assertEqual(result['concept_label'], 'Enjoyment / Restoration')
        self.assertEqual(result['progress']['watch_pct'], 100)
        self.assertEqual(result['progress']['quiz_score_pct'], 80)
        self.assertIsNotNone(result['progress']['quiz_completed_at'])
        self.assertEqual(result['progress']['completion_status'], 'completed')
        self.assertFalse(self.session.dirty)

    def test_new_recorded_work_becomes_latest_without_inventing_completion(self):
        self.pending.watch_pct = 35
        self.session.commit()
        result = load_user_learning(self.session, 4, self.today)
        self.assertEqual(result['concept_label'], 'Sleep')
        self.assertEqual(result['progress']['watch_pct'], 35)
        self.assertIsNone(result['progress']['quiz_completed_at'])

    def test_quiz_submission_is_visible_even_when_older_playback_was_not_recorded(self):
        self.completed.watch_pct = None
        self.completed.video_completed_at = None
        self.session.commit()
        result = load_user_learning(self.session, 4, self.today)
        self.assertIsNotNone(result['progress']['quiz_completed_at'])
        self.assertIsNone(result['progress']['watch_pct'])
        self.assertEqual(result['progress']['completion_status'], 'completed')

    def test_missing_user_has_no_other_users_learning(self):
        self.assertIsNone(load_user_learning(self.session, 99, self.today))

    def test_programme_counts_and_saved_answer_breakdown(self):
        result = load_user_learning(self.session, 4, self.today)
        self.assertEqual(result['lesson_title'], 'Making time to restore')
        self.assertEqual(result['lesson_number'], 1)
        self.assertEqual(result['programme_lesson_count'], 2)
        self.assertEqual(result['programme_completed_count'], 1)
        self.assertEqual([item['completed'] for item in result['programme_lessons']], [True, False])
        self.assertEqual(result['progress']['quiz'], {
            'question_count': 3, 'answered_count': 2, 'correct_count': 2,
            'incorrect_count': 1, 'ungraded_count': 0,
        })

    def test_missing_answer_records_do_not_infer_counts_from_score(self):
        self.session.query(UserEducationQuizAnswer).delete()
        self.session.commit()
        result = load_user_learning(self.session, 4, self.today)
        self.assertEqual(result['progress']['quiz_score_pct'], 80)
        self.assertIsNone(result['progress']['quiz'])
