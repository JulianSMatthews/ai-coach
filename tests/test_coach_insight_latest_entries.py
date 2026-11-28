"""Insight assistance uses real tracker scores for the week through its cutoff."""
import unittest
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy import JSON, create_engine, select
from sqlalchemy.orm import sessionmaker

from app import coach_insight as insight
from app import pillar_progress as progress
from app import pillar_tracker as tracker
from app.models import DailyPillarTrackerEntry


class WeeklyInsightEntriesTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.active = ["reflection"]
        self.target_override = {}
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        column = DailyPillarTrackerEntry.__table__.c.meta
        self.enterContext(patch.object(column, "type", column.type.with_variant(JSON(), "sqlite")))
        DailyPillarTrackerEntry.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        for module in (insight, tracker):
            self.enterContext(patch.object(module, "tracker_today", side_effect=lambda: self.today))
        self.enterContext(patch.object(tracker, "ensure_pillar_tracker_schema"))
        self.enterContext(patch.object(progress, "active_pillar_keys", side_effect=lambda _user: self.active))
        self.enterContext(patch.object(tracker, "_load_week_entries", side_effect=self.load_entries))
        self.enterContext(patch.object(tracker, "tracker_concepts_for_pillar", side_effect=lambda pillar, **_kwargs: tracker.PILLAR_TRACKER_CONFIG[pillar]))
        self.enterContext(patch.object(tracker, "_resolve_pillar_targets_for_user", side_effect=self.targets))
        self.enterContext(patch.object(insight, "_load_library_rows", side_effect=AssertionError("Selection must not read library advice")))
        self.enterContext(patch.object(progress, "run_llm_prompt", side_effect=AssertionError("Selection must precede AI generation")))

    def targets(self, _user, pillar, concepts):
        return {item.concept_key: replace(tracker._default_resolved_target(pillar, item),
                                         **self.target_override.get(item.concept_key, {})) for item in concepts}

    def load_entries(self, user_id, pillar, anchor):
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

    def save(self, concept, day, value, *, user_id=1, pillar="reflection", version=2):
        meta = {"question_set_version": version}
        if version == 3:
            meta["answer_text"] = "Private written contribution"
        with self.sessions() as session:
            session.add(DailyPillarTrackerEntry(
                user_id=user_id, pillar_key=pillar, concept_key=concept,
                score_date=day, value_num=value, meta=meta,
            ))
            session.commit()

    def test_latest_success_still_needs_help_when_week_to_date_score_is_low(self):
        monday = tracker.start_of_week(self.today)
        self.save("emotional_awareness", monday, 0)
        self.save("emotional_awareness", monday + timedelta(days=1), 3)
        result = insight.get_coach_insight(1)
        self.assertEqual(result["review"]["off_track_count"], 1)
        item = result["available_concepts"][0]
        self.assertEqual(item["concept_key"], "emotional_awareness")
        self.assertEqual(item["score"], 50)
        self.assertEqual(item["anchor_date"], self.today.isoformat())
        self.assertNotIn("reason", item)
        self.assertNotIn("latest_value", item)
        self.assertNotIn("guidance", item)
        self.assertNotIn("reflection", item)
        self.assertEqual(result["review"]["evidence_start_date"], monday.isoformat())
        self.assertEqual(result["review"]["evidence_end_date"], (monday + timedelta(days=1)).isoformat())

    def test_latest_miss_does_not_need_help_when_week_to_date_score_is_on_track(self):
        self.today = date(2026, 11, 20)
        monday = tracker.start_of_week(self.today)
        for index, value in enumerate([3, 3, 3, 3, 0]):
            self.save("emotional_awareness", monday + timedelta(days=index), value)
        result = insight.get_coach_insight(1)
        self.assertEqual(result["review"]["on_track_count"], 1)
        self.assertEqual(result["review"]["off_track_count"], 0)
        self.assertEqual(result["available_concepts"], [])

    def test_monday_has_no_carryover_from_previous_week(self):
        self.today = date(2026, 11, 23)
        for concept in tracker.PILLAR_TRACKER_CONFIG["reflection"]:
            self.save(concept.concept_key, self.today - timedelta(days=1), 0)
        result = insight.get_coach_insight(1)
        self.assertEqual(result["review"]["week_start_date"], "2026-11-23")
        self.assertEqual(result["review"]["through_date"], "2026-11-23")
        self.assertEqual(result["review"]["unlogged_count"], 3)
        self.assertEqual(result["review"]["off_track_count"], 0)
        self.assertIsNone(result["review"]["evidence_start_date"])
        self.assertEqual(result["available_concepts"], [])

    def test_other_members_inactive_pillars_blank_and_future_entries_do_not_affect_review(self):
        self.save("emotional_awareness", self.today, 3)
        self.save("mindfulness_presence", self.today, None)
        self.save("emotional_awareness", self.today + timedelta(days=1), 0)
        self.save("mindfulness_presence", self.today, 0, user_id=2)
        self.save("values_alignment", self.today, 0, pillar="purpose")
        result = insight.get_coach_insight(1, anchor=self.today + timedelta(days=20))
        self.assertEqual(result["review"]["on_track_count"], 1)
        self.assertEqual(result["review"]["unlogged_count"], 2)
        self.assertEqual(result["review"]["reviewed_count"], 3)
        self.assertEqual(result["review"]["off_track_count"], 0)
        self.assertEqual(result["review"]["through_date"], self.today.isoformat())

    def test_historical_anchor_reviews_its_week_only_through_that_day(self):
        monday = date(2026, 11, 9)
        self.save("emotional_awareness", monday, 0)
        self.save("emotional_awareness", monday + timedelta(days=1), 3)
        self.save("emotional_awareness", self.today, 3)
        historical = insight.get_coach_insight(1, anchor=monday)
        self.assertEqual(historical["review"]["week_start_date"], monday.isoformat())
        self.assertEqual(historical["review"]["through_date"], monday.isoformat())
        self.assertEqual(historical["available_concepts"][0]["score"], 0)
        current = insight.get_coach_insight(1)
        self.assertEqual(current["review"]["on_track_count"], 1)
        self.assertEqual(current["available_concepts"], [])

    def test_neutral_answers_are_excluded_without_erasing_scored_answers_from_the_week(self):
        self.active = ["resilience"]
        monday = tracker.start_of_week(self.today)
        self.save("emotional_regulation", monday, 1, pillar="resilience")
        self.save("emotional_regulation", self.today, 1, pillar="resilience")
        self.save("adaptability", monday, 0, pillar="resilience")
        self.save("adaptability", self.today, -1, pillar="resilience")
        result = insight.get_coach_insight(1)
        self.assertEqual(result["review"]["off_track_count"], 1)
        self.assertEqual(result["available_concepts"][0]["concept_key"], "adaptability")
        self.assertEqual(result["available_concepts"][0]["score"], 0)
        self.assertEqual(result["review"]["not_applicable_count"], 0)

    def test_all_neutral_and_private_written_answers_do_not_receive_assistance(self):
        self.active = ["resilience", "purpose"]
        self.save("emotional_regulation", self.today, 1, pillar="resilience")
        self.save("adaptability", self.today, -1, pillar="resilience")
        self.save("contribution_connection", self.today, 1, pillar="purpose", version=3)
        result = insight.get_coach_insight(1)
        self.assertEqual(result["review"]["off_track_count"], 0)
        self.assertEqual(result["review"]["not_applicable_count"], 2)
        self.assertEqual(result["available_concepts"], [])
        self.assertNotIn("Private written contribution", str(result))

    def test_weekly_target_uses_the_same_pace_score_as_pillar_progress(self):
        self.active = ["purpose"]
        self.target_override["contribution_connection"] = {
            "source": "okr", "target_value": 5, "target_period": "week",
            "target_unit": "days/week", "target_label": "5 days per week",
        }
        monday = tracker.start_of_week(self.today)
        for index, value in enumerate([1, 0, 1]):
            self.save("contribution_connection", monday + timedelta(days=index), value, pillar="purpose")
        result = insight.get_coach_insight(1)
        item = result["available_concepts"][0]
        self.assertEqual(item["concept_key"], "contribution_connection")
        self.assertEqual(item["score"], 72)
        self.assertEqual(item["target_label"], "5 days per week")
        weekly = progress.get_pillar_progress(1)
        concept = next(row for row in weekly["pillars"][0]["concepts"] if row["concept_key"] == item["concept_key"])
        self.assertEqual(item["score"], concept["score"])


if __name__ == "__main__":
    unittest.main()
