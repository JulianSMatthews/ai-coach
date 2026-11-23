"""The insight review uses each member's latest genuine saved concept answer."""
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import JSON, create_engine, select
from sqlalchemy.orm import sessionmaker

from app import coach_insight as insight
from app import pillar_tracker as tracker
from app.models import DailyPillarTrackerEntry


class LatestInsightEntriesTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 23)
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        column = DailyPillarTrackerEntry.__table__.c.meta
        self.enterContext(patch.object(column, "type", column.type.with_variant(JSON(), "sqlite")))
        DailyPillarTrackerEntry.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.enterContext(patch.object(insight, "SessionLocal", self.sessions))

    def save(self, concept, day, value, *, user_id=1, pillar="reflection"):
        with self.sessions() as session:
            session.add(DailyPillarTrackerEntry(
                user_id=user_id, pillar_key=pillar, concept_key=concept,
                score_date=day, value_num=value, meta={"question_set_version": 2},
            ))
            session.commit()

    def test_latest_answers_exclude_other_members_future_dates_and_blank_rows(self):
        yesterday = self.today - timedelta(days=1)
        self.save("emotional_awareness", yesterday - timedelta(days=7), 2)
        self.save("emotional_awareness", yesterday, 4)
        self.save("emotional_awareness", self.today, None)
        self.save("emotional_awareness", self.today + timedelta(days=1), 5)
        self.save("emotional_awareness", self.today, 5, user_id=2)
        self.save("emotional_awareness", self.today, 5, pillar="training")
        self.save("mindfulness_presence", self.today, 0)
        self.save("adaptability", self.today, -1, pillar="resilience")
        self.save("pattern_recognition", self.today, None)

        result = insight._latest_recorded_concept_dates(1, ["reflection", "resilience"], as_of=self.today)

        self.assertEqual(result, {
            ("reflection", "emotional_awareness"): yesterday,
            ("reflection", "mindfulness_presence"): self.today,
            ("resilience", "adaptability"): self.today,
        })

    def test_latest_saved_answer_survives_week_boundaries_and_historical_cutoffs(self):
        old_day = date(2026, 10, 4)
        yesterday = self.today - timedelta(days=1)
        self.save("emotional_awareness", old_day, 3)
        self.save("emotional_awareness", yesterday, 4)
        self.save("pattern_recognition", old_day, 4)

        current = insight._latest_recorded_concept_dates(1, ["reflection"], as_of=self.today)
        historical = insight._latest_recorded_concept_dates(1, ["reflection"], as_of=old_day)

        self.assertEqual(current[("reflection", "emotional_awareness")], yesterday)
        self.assertEqual(current[("reflection", "pattern_recognition")], old_day)
        self.assertEqual(historical[("reflection", "emotional_awareness")], old_day)

    def test_real_tracker_review_counts_all_yesterdays_answers_on_monday(self):
        yesterday = self.today - timedelta(days=1)
        pillars = ["reflection", "purpose", "resilience", "recovery"]
        concept_count = 0
        for pillar in pillars:
            for concept in tracker.PILLAR_TRACKER_CONFIG[pillar]:
                self.save(concept.concept_key, yesterday, max(option.value for option in concept.options), pillar=pillar)
                concept_count += 1

        def load_entries(user_id, pillar, anchor):
            week_start = tracker.start_of_week(anchor)
            with self.sessions() as session:
                rows = session.execute(select(DailyPillarTrackerEntry).where(
                    DailyPillarTrackerEntry.user_id == user_id,
                    DailyPillarTrackerEntry.pillar_key == pillar,
                    DailyPillarTrackerEntry.score_date >= week_start,
                    DailyPillarTrackerEntry.score_date < week_start + timedelta(days=7),
                )).scalars().all()
            result = {}
            for row in rows:
                result.setdefault(row.score_date, {})[row.concept_key] = row
            return result

        for module, name, value in (
            (insight, "tracker_today", self.today),
            (tracker, "tracker_today", self.today),
            (tracker, "ensure_pillar_tracker_schema", None),
            (tracker, "_latest_assessment_scores_for_user", {}),
            (tracker, "_app_setup_completed_for_user", True),
            (tracker, "_daily_pillar_quote", ""),
            (tracker, "active_pillar_keys", pillars),
            (insight, "_load_library_rows", []),
        ):
            self.enterContext(patch.object(module, name, return_value=value))
        self.enterContext(patch.object(tracker, "_load_week_entries", side_effect=load_entries))
        self.enterContext(patch.object(tracker, "tracker_concepts_for_pillar", side_effect=lambda pillar, **_kwargs: tracker.PILLAR_TRACKER_CONFIG[pillar]))
        self.enterContext(patch.object(tracker, "_resolve_pillar_targets_for_user", side_effect=lambda _user, pillar, concepts: {
            item.concept_key: tracker._default_resolved_target(pillar, item) for item in concepts
        }))

        result = insight.get_coach_insight(1)

        self.assertEqual(result["review"]["reviewed_count"], concept_count)
        self.assertEqual(result["review"]["unlogged_count"], 0)
        self.assertEqual(result["review"]["on_track_count"], concept_count)
        self.assertEqual(result["review"]["evidence_start_date"], yesterday.isoformat())
        self.assertEqual(result["review"]["evidence_end_date"], yesterday.isoformat())


if __name__ == "__main__":
    unittest.main()
