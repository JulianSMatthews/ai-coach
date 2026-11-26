"""Insights review every concept and coach only evidenced off-track concepts."""
import ast
import copy
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

from app import coach_insight as insight


class CoachInsightReviewTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 18)
        self.pillars = []
        self.clock = self.enterContext(patch.object(insight, "tracker_today", return_value=self.today))
        self.progress = self.enterContext(patch.object(insight, "get_pillar_progress", side_effect=self.progress_payload))
        self.library = self.enterContext(patch.object(insight, "_load_library_rows", return_value=[]))
        self.prefs = {}
        self.enterContext(patch.object(insight, "_get_json_pref", side_effect=lambda user, key: copy.deepcopy(self.prefs.get((user, key)))))
        self.enterContext(patch.object(insight, "_set_json_pref", side_effect=lambda user, key, payload: self.prefs.update({(user, key): copy.deepcopy(payload)})))

    @staticmethod
    def week_start(day):
        return day - timedelta(days=day.weekday())

    def progress_payload(self, _user, *, anchor=None):
        through = anchor or self.today
        return {"week": {"start": self.week_start(through).isoformat(), "through": through.isoformat()}, "pillars": self.pillars}

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

    def test_only_week_to_date_scores_below_80_receive_guidance(self):
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
        self.assertEqual(item["reason"], "")
        self.assertIsNone(item["latest_value"])
        self.assertTrue(item["guidance"])
        self.assertTrue(item["reflection"])
        self.assertEqual(item["target_label"], "Your agreed target")
        self.assertEqual(item["anchor_date"], self.today.isoformat())
        self.assertEqual(result["review"], {
            "status": "off_track", "week_start_date": "2026-11-16", "through_date": "2026-11-18",
            "reviewed_count": 4, "off_track_count": 1, "on_track_count": 1,
            "unlogged_count": 1, "not_applicable_count": 1,
            "evidence_start_date": self.today.isoformat(), "evidence_end_date": self.today.isoformat(),
        })
        self.progress.assert_called_once_with(1, anchor=self.today)

    def test_default_review_keeps_all_off_track_concepts_across_all_pillars(self):
        self.add_pillar("purpose", [self.concept(f"purpose_item_{i}") for i in range(6)])
        self.add_pillar("reflection", [self.concept(f"reflection_item_{i}") for i in range(6)])
        result = self.result()
        self.assertEqual(len(result["available_concepts"]), 12)
        self.assertEqual(result["review"]["reviewed_count"], 12)
        self.assertEqual(result["review"]["off_track_count"], 12)
        self.assertTrue(all(item["guidance"] for item in result["available_concepts"]))

    def test_all_on_track_has_no_guidance_or_library_lookup(self):
        self.add_pillar("purpose", [self.concept("direction_vision", score=100)])
        result = self.result()
        self.assertEqual(result["review"]["status"], "on_track")
        self.assertEqual(result["available_concepts"], [])
        self.assertIsNone(result["concept_key"])
        self.assertIsNone(result["content"])
        self.library.assert_not_called()

    def test_unlogged_and_neutral_concepts_do_not_become_off_track_guidance(self):
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
        self.library.assert_not_called()

    def test_no_concepts_returns_insufficient_data_with_week_window(self):
        result = self.result()
        self.assertEqual(result["review"]["status"], "insufficient_data")
        self.assertEqual(result["review"]["reviewed_count"], 0)
        self.assertEqual(result["review"]["week_start_date"], "2026-11-16")
        self.assertEqual(result["review"]["through_date"], "2026-11-18")
        self.assertEqual(result["available_concepts"], [])
        self.assertIsNone(result["content"])

    def test_partial_on_track_review_does_not_claim_unlogged_concepts_are_on_track(self):
        self.add_pillar("purpose", [self.concept("direction_vision", score=100), self.concept("values_alignment", logged=False)])
        result = self.result()
        self.assertEqual(result["review"]["status"], "insufficient_data")
        self.assertEqual(result["review"]["on_track_count"], 1)
        self.assertEqual(result["review"]["unlogged_count"], 1)
        self.assertEqual(result["available_concepts"], [])

    def test_preferred_on_track_concept_cannot_override_an_off_track_concept(self):
        self.add_pillar("purpose", [self.concept("direction_vision", score=100), self.concept("values_alignment")])
        result = self.result(concept_key="direction_vision")
        self.assertEqual(result["concept_key"], "values_alignment")

    def test_retired_concepts_do_not_receive_assistance_or_count_as_current(self):
        self.add_pillar("purpose", [self.concept("retired", score=0, historical=True), self.concept("values_alignment", score=100)])
        result = self.result()
        self.assertEqual(result["review"]["reviewed_count"], 1)
        self.assertEqual(result["review"]["status"], "on_track")
        self.assertEqual(result["available_concepts"], [])
        self.library.assert_not_called()

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

    def test_unrelated_concept_library_content_is_never_returned_as_fallback(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        self.library.return_value = [SimpleNamespace(
            id=17, pillar_key="purpose", concept_code="direction_vision", title="Unrelated lesson",
            body="UNRELATED DIRECTION ADVICE", podcast_url=None, podcast_voice=None,
            tags={}, created_at=None,
        )]
        result = self.result()
        self.assertIsNone(result["content"])
        self.assertIsNone(result["available_concepts"][0]["content"])
        self.assertNotIn("UNRELATED DIRECTION ADVICE", result["available_concepts"][0]["guidance"])

    def test_exact_concept_library_content_is_attached_to_its_own_guidance(self):
        self.add_pillar("purpose", [self.concept("values_alignment"), self.concept("meaning_fulfilment")])
        self.library.return_value = [SimpleNamespace(
            id=18, pillar_key="purpose", concept_code="values_alignment", title="Values lesson",
            body="Choose one action aligned with your values.", podcast_url=None, podcast_voice=None,
            tags={}, created_at=None,
        )]
        result = self.result()
        items = {item["concept_key"]: item for item in result["available_concepts"]}
        self.assertEqual(items["values_alignment"]["content"]["id"], 18)
        self.assertIsNone(items["meaning_fulfilment"]["content"])
        for key, item in items.items():
            self.assertIn(item["label"].lower(), item["reflection"])
            self.assertTrue(item["reflection"].endswith("?"))
            self.assertIn("existing", item["reflection"])
        self.assertNotEqual(items["values_alignment"]["reflection"], items["meaning_fulfilment"]["reflection"])

    def library_item(self, key, body):
        return SimpleNamespace(
            id=19, pillar_key="purpose", concept_code=key, title="Concept advice",
            body=body, podcast_url=None, podcast_voice=None, tags={}, created_at=None,
        )

    def test_short_guidance_and_exactly_100_combined_words_remain_unchanged(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        reflection = self.result()["available_concepts"][0]["reflection"]
        budget = 100 - len(reflection.split())
        for count in (8, budget):
            with self.subTest(words=count):
                body = " ".join(f"word{i}" for i in range(count))
                self.library.return_value = [self.library_item("values_alignment", body)]
                item = self.result()["available_concepts"][0]
                self.assertEqual(item["reflection"], reflection)
                self.assertEqual(item["guidance"], body)
                self.assertEqual(len(item["reflection"].split()) + len(item["guidance"].split()), len(reflection.split()) + count)

    def test_long_single_sentence_guidance_stops_at_word_boundary_without_changing_library_content(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        body = " ".join(f"word{i}" for i in range(150)) + "."
        row = self.library_item("values_alignment", body)
        self.library.return_value = [row]
        item = self.result()["available_concepts"][0]
        self.assertEqual(len(item["reflection"].split()) + len(item["guidance"].split()), 100)
        self.assertTrue(item["guidance"].endswith("…"))
        self.assertFalse(item["guidance"].endswith(" …"))
        self.assertTrue(body.startswith(item["guidance"][:-1]))
        self.assertEqual(item["content"]["body"], body)
        self.assertEqual(row.body, body)

    def test_long_guidance_prefers_the_last_complete_sentence_that_fits(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        sentence = " ".join(f"step{i}" for i in range(35)) + "."
        complete = f"{sentence} {sentence}"
        body = f"{complete} " + " ".join("continue" for _ in range(100)) + "."
        self.library.return_value = [self.library_item("values_alignment", body)]
        item = self.result()["available_concepts"][0]
        self.assertEqual(item["guidance"], complete)
        self.assertLessEqual(len(item["reflection"].split()) + len(item["guidance"].split()), 100)

    def test_each_concept_has_its_own_100_word_budget(self):
        self.add_pillar("purpose", [self.concept("values_alignment"), self.concept("meaning_fulfilment")])
        self.library.return_value = [
            self.library_item("values_alignment", " ".join("values" for _ in range(150))),
            self.library_item("meaning_fulfilment", " ".join("meaning" for _ in range(150))),
        ]
        items = self.result()["available_concepts"]
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(len(item["reflection"].split()) + len(item["guidance"].split()), 100)
            self.assertEqual(len(item["content"]["body"].split()), 150)

    def test_fallback_keeps_word_limit_and_target_without_recorded_answer_narrative(self):
        concept = self.concept("values_alignment")
        target = " ".join("target" for _ in range(180))
        value = " ".join("recorded" for _ in range(180))
        concept["target_label"] = target
        concept["days"][0]["value_label"] = value
        self.add_pillar("purpose", [concept])
        item = self.result()["available_concepts"][0]
        self.assertEqual(item["reason"], "")
        self.assertTrue(item["guidance"])
        self.assertLessEqual(len(item["reflection"].split()) + len(item["guidance"].split()), 100)
        self.assertLessEqual(len(item["reflection"].split()), 25)
        self.assertIsNone(item["latest_value"])
        self.assertEqual(item["target_label"], target)
        self.assertIsNone(item["content"])

    def test_reflection_keeps_optional_behaviours_tied_to_the_existing_target(self):
        self.add_pillar("nutrition", [self.concept("fasting"), self.concept("alcohol")])
        for item in self.result()["available_concepts"]:
            self.assertIn(item["label"].lower(), item["reflection"])
            self.assertIn("existing", item["reflection"])
            self.assertIn("target", item["reflection"])
            self.assertTrue(item["reflection"].endswith("?"))
            self.assertNotIn("increase", item["reflection"].lower())
            self.assertNotIn("start", item["reflection"].lower())

    def test_previous_cached_review_without_reflection_is_regenerated(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        insight.get_or_generate_cached_coach_insight(1)
        pref = self.prefs[(1, insight._INSIGHT_CACHE_KEY)]
        pref["review_version"] = insight._INSIGHT_REVIEW_VERSION - 1
        pref["result"]["available_concepts"][0].pop("reflection")
        item = insight.get_or_generate_cached_coach_insight(1)["available_concepts"][0]
        self.assertTrue(item["reflection"])
        self.assertTrue(item["guidance"])
        self.assertLessEqual(len(item["guidance"].split()) + len(item["reflection"].split()), 100)

    def test_cached_review_updates_when_a_concept_beyond_the_old_limit_changes(self):
        concepts = [self.concept(f"purpose_item_{i}") for i in range(10)]
        self.add_pillar("purpose", concepts)
        first = insight.get_or_generate_cached_coach_insight(1)
        self.assertEqual(first["review"]["off_track_count"], 10)
        concepts[9].update(self.concept("purpose_item_9", score=100, target_met=True))
        updated = insight.get_or_generate_cached_coach_insight(1)
        self.assertEqual(updated["review"]["off_track_count"], 9)
        self.assertNotIn("purpose_item_9", [item["concept_key"] for item in updated["available_concepts"]])

    def test_legacy_cache_cannot_reintroduce_guidance_from_the_old_selector(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        insight.get_or_generate_cached_coach_insight(1)
        pref = self.prefs[(1, insight._INSIGHT_CACHE_KEY)]
        pref.pop("review_version", None)
        pref["result"] = {"legacy": True, "concept_key": "direction_vision"}
        result = insight.get_or_generate_cached_coach_insight(1)
        self.assertNotIn("legacy", result)
        self.assertEqual(result["concept_key"], "values_alignment")

    def test_cache_from_before_word_limit_is_regenerated(self):
        self.add_pillar("purpose", [self.concept("values_alignment")])
        insight.get_or_generate_cached_coach_insight(1)
        pref = self.prefs[(1, insight._INSIGHT_CACHE_KEY)]
        pref["review_version"] = insight._INSIGHT_REVIEW_VERSION - 1
        pref["result"]["available_concepts"][0]["guidance"] = " ".join("outdated" for _ in range(150))
        result = insight.get_or_generate_cached_coach_insight(1)
        item = result["available_concepts"][0]
        self.assertLessEqual(len(item["reflection"].split()) + len(item["guidance"].split()), 100)
        self.assertNotIn("outdated", item["guidance"])


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
