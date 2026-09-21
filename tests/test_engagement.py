import unittest
from datetime import datetime

from app.engagement import build_engagement_summary


def instant(value):
    return datetime.fromisoformat(value)


class EngagementSummaryTests(unittest.TestCase):
    def summary(self, *values, now="2026-09-17T12:00:00+00:00"):
        return build_engagement_summary([instant(value) for value in values], now=instant(now))

    def test_scattered_dates_are_not_a_streak_or_invented_activity(self):
        result = self.summary("2026-09-01T12:00:00", "2026-09-05T12:00:00", "2026-09-17T10:00:00")
        self.assertEqual(result["interaction_days_count"], 3)
        self.assertEqual(result["current_streak_days"], 1)
        self.assertEqual(result["active_dates"], ["2026-09-01", "2026-09-05", "2026-09-17"])

    def test_yesterday_keeps_streak_without_highlighting_today(self):
        result = self.summary("2026-09-15T12:00:00", "2026-09-16T12:00:00")
        self.assertEqual(result["current_streak_days"], 2)
        self.assertFalse(result["active_today"])
        self.assertNotIn(result["today"], result["active_dates"])

    def test_missed_day_breaks_current_but_preserves_best(self):
        result = self.summary("2026-09-14T12:00:00", "2026-09-15T12:00:00")
        self.assertEqual(result["current_streak_days"], 0)
        self.assertEqual(result["best_streak_days"], 2)

    def test_multiple_events_count_once_and_latest_is_chronological(self):
        result = self.summary("2026-09-17T11:00:00", "2026-09-16T12:00:00", "2026-09-17T10:00:00")
        self.assertEqual(result["current_streak_days"], 2)
        self.assertEqual(result["interaction_days_count"], 2)
        self.assertEqual(result["latest_interaction_at"], "2026-09-17T12:00:00+01:00")

    def test_london_midnight_and_naive_utc(self):
        result = self.summary("2026-09-16T23:15:00", now="2026-09-16T23:30:00+00:00")
        self.assertEqual(result["today"], "2026-09-17")
        self.assertEqual(result["active_dates"], ["2026-09-17"])
        self.assertTrue(result["active_today"])

    def test_dst_change_uses_calendar_days(self):
        result = self.summary("2026-03-28T12:00:00+00:00", "2026-03-29T12:00:00+00:00", "2026-03-29T23:15:00+00:00", now="2026-03-30T12:00:00+00:00")
        self.assertEqual(result["current_streak_days"], 3)
        result = self.summary("2026-10-25T00:30:00+00:00", "2026-10-25T01:30:00+00:00", now="2026-10-25T12:00:00+00:00")
        self.assertEqual(result["interaction_days_count"], 1)

    def test_empty_missing_and_future_events(self):
        result = build_engagement_summary([None, instant("2026-09-18T12:00:00+00:00")], now=instant("2026-09-17T12:00:00+00:00"))
        self.assertEqual(result["active_dates"], [])
        self.assertEqual(result["current_streak_days"], 0)
        self.assertEqual(result["best_streak_days"], 0)
        self.assertIsNone(result["latest_interaction_at"])


if __name__ == "__main__":
    unittest.main()
