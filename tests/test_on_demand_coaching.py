"""Automatic app refreshes cannot generate coaching; static cue cards still work."""
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app import coach_home_refresh as refresh
from app import pillar_tracker as tracker


class RetiredAutomaticRefreshTests(unittest.TestCase):
    def test_already_queued_jobs_finish_without_generating_or_loading_context(self):
        with patch.object(refresh, "_update_refresh_state") as state, \
             patch.object(refresh, "SessionLocal", side_effect=AssertionError("No generation context should be loaded")):
            for trigger in ("pillar_tracker_update", "weekly_objectives_update", "tracker_update"):
                with self.subTest(trigger=trigger):
                    result = refresh.run_coach_home_tracker_refresh(
                        42, trigger=trigger, pillar_key="Purpose", score_date="2026-11-21", job_id=7,
                    )
                    self.assertTrue(result["ok"])
                    self.assertTrue(result["skipped"])
                    self.assertEqual(result["reason"], "on_demand_coaching_only")
                    self.assertEqual(result["pillar_key"], "purpose")
                    self.assertEqual(state.call_args.kwargs["status"], "succeeded")
                    self.assertEqual(state.call_args.kwargs["job_id"], 7)
                    self.assertEqual(state.call_args.kwargs["result"], result)

    def test_legacy_queue_call_does_not_schedule_or_access_database(self):
        background = MagicMock()
        with patch.object(refresh, "SessionLocal", side_effect=AssertionError("No queue database access expected")):
            result = refresh.queue_coach_home_tracker_refresh(
                42, trigger="pillar_tracker_update", pillar_key="purpose", background_tasks=background,
            )
        self.assertFalse(result["queued"])
        self.assertFalse(result["created"])
        self.assertIsNone(result["job_id"])
        background.add_task.assert_not_called()


class StaticCueReadTests(unittest.TestCase):
    def setUp(self):
        self.session = MagicMock()
        factory = MagicMock()
        factory.return_value.__enter__.return_value = self.session
        self.enterContext(patch.object(tracker, "SessionLocal", factory))
        self.cached = self.enterContext(patch.object(tracker, "_latest_generated_daily_pillar_quote", return_value=""))
        self.ai = self.enterContext(patch.object(tracker, "run_llm_prompt", side_effect=AssertionError("Cue reads must not call AI")))
        self.persist = self.enterContext(patch.object(tracker, "_save_latest_daily_pillar_quote", side_effect=AssertionError("Cue reads must not persist new content")))
        self.session.execute.return_value.scalars.return_value.all.return_value = []
        self.today = date(2026, 11, 21)

    def quote(self, pillar="purpose"):
        return tracker._daily_pillar_quote(42, pillar, pillar.title(), 80, self.today, skip_generation=True)

    def test_builtin_static_cues_display_for_every_pillar_without_ai_or_writes(self):
        for pillar in tracker._QUOTE_LED_PILLARS:
            with self.subTest(pillar=pillar):
                text = self.quote(pillar)
                bank = tracker._QUOTE_LED_CUE_BANK[pillar]
                self.assertTrue(any(item["quote"] in text and item["author"] in text for item in bank))
                self.assertGreaterEqual(len(text.splitlines()), 3)
        self.ai.assert_not_called()
        self.persist.assert_not_called()
        self.session.commit.assert_not_called()
        self.session.add.assert_not_called()

    def test_existing_database_cue_is_selected_without_ai_or_writes(self):
        self.session.execute.return_value.scalars.return_value.all.return_value = [SimpleNamespace(
            quote="An existing quotation", reflection="An existing reflection.", author="An author",
        )]
        self.assertEqual(self.quote(), '"An existing quotation"\nAn existing reflection.\nAn author')
        self.ai.assert_not_called()
        self.persist.assert_not_called()
        self.session.commit.assert_not_called()

    def test_saved_static_cue_remains_available_without_reading_the_bank(self):
        self.cached.return_value = '"A saved quotation"\nA saved reflection.\nAn author'
        self.assertEqual(self.quote(), self.cached.return_value)
        self.session.execute.assert_not_called()
        self.ai.assert_not_called()
        self.persist.assert_not_called()


if __name__ == "__main__":
    unittest.main()
