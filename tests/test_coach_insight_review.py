"""Insight selects current struggling concepts before any AI coaching is requested."""
import ast
import copy
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

from app import coach_insight as insight


class CoachInsightReviewTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.pillars = []
        self.enterContext(patch.object(insight, "tracker_today", side_effect=lambda: self.today))
        self.progress = self.enterContext(patch.object(insight, "get_pillar_progress", side_effect=self.progress_payload))
        self.library = self.enterContext(patch.object(insight, "_load_library_rows", side_effect=AssertionError("Selection must not read library advice")))
        self.ai = self.enterContext(patch("app.pillar_progress.run_llm_prompt", side_effect=AssertionError("Selection must finish before AI generation")))
        self.coaching = self.enterContext(patch("app.pillar_progress.get_concept_coaching", side_effect=AssertionError("Selection must not request coaching")))
        self.prefs = {}
        self.enterContext(patch.object(insight, "_get_json_pref", side_effect=lambda user, key: copy.deepcopy(self.prefs.get((user, key)))))
        self.enterContext(patch.object(insight, "_set_json_pref", side_effect=lambda user, key, payload: self.prefs.update({(user, key): copy.deepcopy(payload)})))

    def progress_payload(self, _user, *, anchor=None):
        through = anchor or self.today
        week_start = through - timedelta(days=through.weekday())
        return {"week": {"start": week_start.isoformat(), "through": through.isoformat()}, "pillars": self.pillars}

    def concept(self, key, *, score=40, target_met=False, neutral=False, logged=True, day=None, historical=False):
        day = day or self.today
        return {
            "concept_key": key,
            "label": key.replace("_", " ").title(),
            "score": score if logged and not neutral else None,
            "target_met": target_met,
            "target_label": "Your agreed target",
            "not_applicable_days_count": int(neutral),
            "is_historical": historical,
            "days": [{"date": day.isoformat(), "value_label": "A little" if logged else None,
                      "not_applicable": neutral}],
        }

    def add_pillar(self, key, concepts):
        self.pillars.append({"pillar_key": key, "label": key.title(), "score": 70, "concepts": concepts})

    def result(self, **kwargs):
        return insight.get_coach_insight(1, **kwargs)

    def test_only_week_to_date_scores_below_80_are_selected(self):
        self.add_pillar("purpose", [
            self.concept("direction_vision", score=79, target_met=True),
            self.concept("values_alignment", score=80, target_met=False),
            self.concept("meaning_fulfilment", logged=False),
            self.concept("contribution_connection", neutral=True),
        ])
        result = self.result(anchor=self.today)
        self.assertEqual([item["concept_key"] for item in result["available_concepts"]], ["direction_vision"])
        item = result["available_concepts"][0]
        self.assertEqual(item["status"], "off_track")
        self.assertEqual(item["score"], 79)
        self.assertEqual(item["target_label"], "Your agreed target")
        self.assertEqual(item["anchor_date"], self.today.isoformat())
        self.assertEqual(result["review"], {
            "status": "off_track", "week_start_date": "2026-11-16", "through_date": "2026-11-18",
            "reviewed_count": 4, "off_track_count": 1, "focus_count": 1, "on_track_count": 1,
            "unlogged_count": 1, "not_applicable_count": 1,
            "evidence_start_date": self.today.isoformat(), "evidence_end_date": self.today.isoformat(),
        })
        self.progress.assert_called_once_with(1, anchor=self.today)

    def test_six_globally_lowest_scores_can_all_come_from_one_pillar(self):
        self.add_pillar("reflection", [self.concept("reflection_low", score=60)])
        self.add_pillar("purpose", [self.concept(f"purpose_item_{i}", score=i * 5) for i in reversed(range(8))])
        result = self.result()
        selected = result["available_concepts"]
        self.assertEqual([item["concept_key"] for item in selected], [f"purpose_item_{i}" for i in range(6)])
        self.assertEqual([item["score"] for item in selected], [0, 5, 10, 15, 20, 25])
        self.assertEqual(result["review"]["reviewed_count"], 9)
        self.assertEqual(result["review"]["off_track_count"], 9)
        self.assertEqual(result["review"]["focus_count"], 6)
        self.assertEqual(result["concept_key"], "purpose_item_0")
        self.library.assert_not_called()
        self.coaching.assert_not_called()
        self.ai.assert_not_called()

    def test_fewer_than_six_struggling_concepts_are_all_selected_in_score_order(self):
        self.add_pillar("purpose", [
            self.concept("values_alignment", score=35), self.concept("meaning_fulfilment", score=20),
            self.concept("contribution_connection", score=90), self.concept("retired", score=0, historical=True),
        ])
        self.add_pillar("reflection", [self.concept("emotional_awareness", score=10), self.concept("mindfulness_presence", score=60)])
        self.add_pillar("resilience", [self.concept("adaptability", neutral=True), self.concept("emotional_regulation", logged=False)])
        result = self.result()
        self.assertEqual([(item["pillar_key"], item["concept_key"], item["score"]) for item in result["available_concepts"]], [
            ("reflection", "emotional_awareness", 10), ("purpose", "meaning_fulfilment", 20),
            ("purpose", "values_alignment", 35), ("reflection", "mindfulness_presence", 60),
        ])
        self.assertEqual(result["review"]["reviewed_count"], 7)
        self.assertEqual(result["review"]["off_track_count"], 4)
        self.assertEqual(result["review"]["focus_count"], 4)
        self.assertEqual(result["review"]["on_track_count"], 1)
        self.assertEqual(result["review"]["not_applicable_count"], 1)
        self.assertEqual(result["review"]["unlogged_count"], 1)

    def test_equal_scores_use_stable_pillar_label_then_key_order_at_sixth_place(self):
        tied = [self.concept(f"tie_{letter}", score=20) for letter in "gfedcba"]
        for concept in tied:
            concept["label"] = "Same label"
        for concepts in (tied, list(reversed(tied))):
            with self.subTest(order=[item["concept_key"] for item in concepts]):
                self.pillars.clear()
                self.add_pillar("purpose", concepts)
                self.add_pillar("reflection", [self.concept("reflection_tie", score=20)])
                result = self.result()
                expected = sorted(
                    [("purpose", "Same label", item["concept_key"]) for item in tied]
                    + [("reflection", "Reflection Tie", "reflection_tie")],
                    key=lambda item: (insight._PILLAR_ORDER.index(item[0]), item[1], item[2]),
                )[:6]
                self.assertEqual([item["concept_key"] for item in result["available_concepts"]], [item[2] for item in expected])

    def test_preference_can_only_mark_a_concept_already_among_the_lowest_six(self):
        self.add_pillar("purpose", [self.concept(f"purpose_item_{i}", score=i * 10) for i in range(8)])
        for preferred, expected in (("purpose_item_4", "purpose_item_4"), ("purpose_item_6", "purpose_item_0")):
            with self.subTest(preferred=preferred):
                result = self.result(concept_key=preferred)
                self.assertEqual([item["concept_key"] for item in result["available_concepts"]], [f"purpose_item_{i}" for i in range(6)])
                self.assertEqual(result["concept_key"], expected)
                self.assertEqual(sum(item["is_selected"] for item in result["available_concepts"]), 1)
                available, selected, _ = insight._select_focus_concepts(1, self.today, preferred_concept_key=preferred)
                self.assertEqual([item["concept_key"] for item in available], [f"purpose_item_{i}" for i in range(6)])
                self.assertEqual(selected["concept_key"], expected)

    def test_unlogged_neutral_retired_or_on_track_preference_cannot_replace_a_focus(self):
        self.add_pillar("resilience", [
            self.concept("emotional_regulation", score=10), self.concept("support_connection", logged=False),
            self.concept("adaptability", neutral=True), self.concept("retired", score=0, historical=True),
            self.concept("on_track", score=80),
        ])
        for preferred in ("support_connection", "adaptability", "retired", "on_track", "unknown"):
            with self.subTest(preferred=preferred):
                result = self.result(concept_key=preferred)
                self.assertEqual([item["concept_key"] for item in result["available_concepts"]], ["emotional_regulation"])
                self.assertEqual(result["review"]["focus_count"], 1)

    def test_selection_payload_has_no_library_advice_or_generated_guidance(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        result = self.result()
        self.assertEqual(set(result["available_concepts"][0]), {
            "pillar_key", "pillar_label", "concept_key", "label", "is_selected", "status",
            "signal", "anchor_date", "score", "target_label",
        })
        for field in ("content", "matched_by", "guidance", "reflection", "reason", "latest_value"):
            self.assertNotIn(field, result)
        self.library.assert_not_called()
        self.coaching.assert_not_called()
        self.ai.assert_not_called()

    def test_all_on_track_has_no_selected_concepts(self):
        self.add_pillar("purpose", [self.concept("direction_vision", score=100)])
        result = self.result()
        self.assertEqual(result["review"]["status"], "on_track")
        self.assertEqual(result["available_concepts"], [])
        self.assertIsNone(result["concept_key"])

    def test_unlogged_and_neutral_concepts_do_not_become_off_track(self):
        self.add_pillar("resilience", [
            self.concept("emotional_regulation", logged=False),
            self.concept("adaptability", neutral=True, score=0),
        ])
        result = self.result()
        self.assertEqual(result["review"]["status"], "insufficient_data")
        self.assertEqual(result["review"]["off_track_count"], 0)
        self.assertEqual(result["review"]["unlogged_count"], 1)
        self.assertEqual(result["review"]["not_applicable_count"], 1)
        self.assertEqual(result["available_concepts"], [])

    def test_no_concepts_returns_insufficient_data_with_week_window(self):
        result = self.result()
        self.assertEqual(result["review"]["status"], "insufficient_data")
        self.assertEqual(result["review"]["reviewed_count"], 0)
        self.assertEqual(result["review"]["week_start_date"], "2026-11-16")
        self.assertEqual(result["review"]["through_date"], "2026-11-18")
        self.assertEqual(result["available_concepts"], [])

    def test_partial_on_track_review_does_not_claim_unlogged_concepts_are_on_track(self):
        self.add_pillar("purpose", [self.concept("direction_vision", score=100), self.concept("values_alignment", logged=False)])
        result = self.result()
        self.assertEqual(result["review"]["status"], "insufficient_data")
        self.assertEqual(result["review"]["on_track_count"], 1)
        self.assertEqual(result["review"]["unlogged_count"], 1)
        self.assertEqual(result["available_concepts"], [])

    def test_retired_concepts_do_not_count_as_current(self):
        self.add_pillar("purpose", [self.concept("retired", score=0, historical=True), self.concept("values_alignment", score=100)])
        result = self.result()
        self.assertEqual(result["review"]["reviewed_count"], 1)
        self.assertEqual(result["review"]["status"], "on_track")
        self.assertEqual(result["available_concepts"], [])

    def test_future_anchor_is_capped_at_today_and_historical_anchor_is_forwarded(self):
        self.result(anchor=self.today + timedelta(days=10))
        self.progress.assert_called_once_with(1, anchor=self.today)
        self.progress.reset_mock()
        past = self.today - timedelta(days=8)
        result = self.result(anchor=past)
        self.progress.assert_called_once_with(1, anchor=past)
        self.assertEqual(result["insight_date"], past.isoformat())
        self.assertEqual(result["review"]["week_start_date"], "2026-11-09")
        self.assertEqual(result["review"]["through_date"], past.isoformat())

    def test_score_changes_invalidate_cached_weekly_review(self):
        concept = self.concept("values_alignment", score=70)
        self.add_pillar("purpose", [concept])
        previous = insight.get_or_generate_cached_coach_insight(1)
        self.assertEqual(previous["review"]["off_track_count"], 1)
        concept["score"] = 80
        current = insight.get_or_generate_cached_coach_insight(1)
        self.assertEqual(current["review"]["status"], "on_track")
        self.assertEqual(current["available_concepts"], [])

    def test_cached_review_updates_when_a_concept_beyond_six_becomes_lowest(self):
        concepts = [self.concept(f"purpose_item_{i}", score=10 + i * 5) for i in range(10)]
        self.add_pillar("purpose", concepts)
        first = insight.get_or_generate_cached_coach_insight(1)
        self.assertEqual([item["concept_key"] for item in first["available_concepts"]], [f"purpose_item_{i}" for i in range(6)])
        concepts[9]["score"] = 0
        updated = insight.get_or_generate_cached_coach_insight(1)
        self.assertEqual([item["concept_key"] for item in updated["available_concepts"]], ["purpose_item_9"] + [f"purpose_item_{i}" for i in range(5)])
        self.assertEqual(updated["review"]["off_track_count"], 10)

    def test_old_cache_with_one_per_pillar_and_generic_guidance_is_discarded(self):
        self.add_pillar("purpose", [self.concept(f"purpose_item_{i}", score=i * 10) for i in range(8)])
        insight.get_or_generate_cached_coach_insight(1)
        cached = self.prefs[(1, insight._INSIGHT_CACHE_KEY)]
        cached["review_version"] = insight._INSIGHT_REVIEW_VERSION - 1
        cached["result"]["available_concepts"] = [{"concept_key": "purpose_item_0", "guidance": "Old generic guidance", "reflection": "Old generic reflection"}]
        updated = insight.get_or_generate_cached_coach_insight(1)
        self.assertEqual(len(updated["available_concepts"]), 6)
        for item in updated["available_concepts"]:
            self.assertNotIn("guidance", item)
            self.assertNotIn("reflection", item)
        self.assertEqual(self.prefs[(1, insight._INSIGHT_CACHE_KEY)]["review_version"], insight._INSIGHT_REVIEW_VERSION)

    def test_unchanged_context_reuses_selection_cache_without_coaching_or_library_reads(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        first = insight.get_or_generate_cached_coach_insight(1)
        with patch.object(insight, "_build_insight_result", side_effect=AssertionError("Expected cached selection")):
            self.assertEqual(insight.get_or_generate_cached_coach_insight(1), first)
        self.ai.assert_not_called()
        self.coaching.assert_not_called()
        self.library.assert_not_called()

    def test_legacy_cache_without_version_cannot_reintroduce_guidance(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        insight.get_or_generate_cached_coach_insight(1)
        cached = self.prefs[(1, insight._INSIGHT_CACHE_KEY)]
        cached.pop("review_version")
        cached["result"] = {"legacy": True, "guidance": "Legacy advice"}
        updated = insight.get_or_generate_cached_coach_insight(1)
        self.assertNotIn("legacy", updated)
        self.assertNotIn("guidance", updated)
        self.assertEqual(updated["concept_key"], "values_alignment")


class CoachInsightRouteTests(unittest.TestCase):
    def setUp(self):
        api = FastAPI()
        self.access = Mock()
        self.generate = Mock()
        self.log_event = Mock()

        def normalize(value):
            if value and value.startswith("/reports/"):
                return f"https://coach.test{value}"
            return value

        namespace = {
            "api_v1": api, "Request": Request, "Header": Header,
            "HTTPException": HTTPException, "_resolve_user_access": self.access,
            "ensure_pillar_tracker_schema": Mock(),
            "parse_tracker_anchor": date.fromisoformat,
            "get_or_generate_cached_coach_insight": self.generate,
            "_normalize_reports_url": normalize,
            "_log_app_engagement_event": self.log_event,
        }
        tree = ast.parse((Path(__file__).parents[1] / "app" / "api.py").read_text())
        route = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "api_user_coach_insight"], type_ignores=[])
        exec(compile(route, "app/api.py", "exec"), namespace)
        self.client = self.enterContext(TestClient(api))

    def test_nested_concept_media_is_normalized_with_selected_content(self):
        def media(prefix):
            return {
                "podcast_url": f"/reports/{prefix}.mp3",
                "avatar": {
                    "url": f"/reports/{prefix}.mp4",
                    "poster_url": f"/reports/{prefix}.png",
                    "summary_url": f"/reports/{prefix}.json",
                },
            }

        self.generate.return_value = {
            "content": media("selected"),
            "available_concepts": [{"content": media("concept")}, {"content": None}],
        }
        response = self.client.get("/users/1/coach-insight")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        for content in (result["content"], result["available_concepts"][0]["content"]):
            self.assertTrue(content["podcast_url"].startswith("https://coach.test/reports/"))
            self.assertTrue(all(url.startswith("https://coach.test/reports/") for url in content["avatar"].values()))
        self.access.assert_called_once()

    def test_unauthorized_review_does_not_read_concepts_or_log_an_insight(self):
        self.access.side_effect = HTTPException(status_code=403, detail="Forbidden")
        response = self.client.get("/users/2/coach-insight")
        self.assertEqual(response.status_code, 403)
        self.generate.assert_not_called()
        self.log_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
