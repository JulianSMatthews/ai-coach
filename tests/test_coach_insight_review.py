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
        self.details = {}
        self.pillars = []
        self.enterContext(patch.object(insight, "tracker_today", return_value=self.today))
        self.enterContext(patch.object(insight, "_guidance_anchor_for_pillar", return_value=self.today, create=True))
        self.enterContext(patch.object(insight, "get_pillar_tracker_summary", side_effect=lambda *_a, **_k: {"pillars": self.pillars}))
        self.detail_calls = self.enterContext(patch.object(insight, "get_pillar_tracker_detail", side_effect=lambda _user, key, **_k: self.details[key]))
        self.library = self.enterContext(patch.object(insight, "_load_library_rows", return_value=[]))
        self.prefs = {}
        self.enterContext(patch.object(insight, "_get_json_pref", side_effect=lambda user, key: copy.deepcopy(self.prefs.get((user, key)))))
        self.enterContext(patch.object(insight, "_set_json_pref", side_effect=lambda user, key, payload: self.prefs.update({(user, key): copy.deepcopy(payload)})))

    def concept(self, key, *, score=40, target_met=False, neutral=False, logged=True, day=None):
        day = day or self.today
        row = {
            "date": day.isoformat(),
            "value_label": "A little" if logged else None,
            "score": score if logged else None,
            "target_met": target_met if logged else None,
            "not_applicable": neutral,
            "daily_positive": target_met if logged else None,
        }
        return {
            "concept_key": key,
            "label": key.replace("_", " ").title(),
            "helper": f"Make time for {key.replace('_', ' ')} today.",
            "score": score if logged else None,
            "target_met": target_met if logged else None,
            "target_label": "Your agreed target",
            "target_period": "day",
            "value_label": row["value_label"],
            "not_applicable": neutral,
            "week": [row],
        }

    def add_pillar(self, key, concepts, *, active_day=None):
        self.pillars.append({"pillar_key": key, "label": key.title(), "score": 70})
        self.details[key] = {
            "pillar": {"active_date": (active_day or self.today).isoformat()},
            "concepts": concepts,
        }

    def result(self, **kwargs):
        return insight.get_coach_insight(1, **kwargs)

    def test_only_off_track_concepts_receive_guidance_using_target_status_before_score(self):
        self.add_pillar("purpose", [
            self.concept("direction_vision", score=40, target_met=True),
            self.concept("values_alignment", score=100, target_met=False),
            self.concept("meaning_fulfilment", logged=False),
            self.concept("contribution_connection", neutral=True),
        ])
        result = self.result(anchor=self.today)
        self.assertEqual([item["concept_key"] for item in result["available_concepts"]], ["values_alignment"])
        item = result["available_concepts"][0]
        self.assertEqual(item["status"], "off_track")
        self.assertTrue(item["reason"])
        self.assertTrue(item["guidance"])
        self.assertEqual(item["target_label"], "Your agreed target")
        self.assertEqual(item["latest_value"], "A little")
        self.assertEqual(item["anchor_date"], self.today.isoformat())
        self.assertEqual(result["review"], {
            "status": "off_track", "reviewed_count": 4, "off_track_count": 1,
            "on_track_count": 1, "unlogged_count": 1, "not_applicable_count": 1,
        })

    def test_default_review_keeps_all_off_track_concepts_across_all_pillars(self):
        self.add_pillar("purpose", [self.concept(f"purpose_item_{i}") for i in range(6)])
        self.add_pillar("reflection", [self.concept(f"reflection_item_{i}") for i in range(6)])
        result = self.result()
        self.assertEqual(len(result["available_concepts"]), 12)
        self.assertEqual(result["review"]["reviewed_count"], 12)
        self.assertEqual(result["review"]["off_track_count"], 12)
        self.assertEqual({call.args[1] for call in self.detail_calls.call_args_list}, {"purpose", "reflection"})
        self.assertTrue(all(item["guidance"] for item in result["available_concepts"]))

    def test_all_on_track_has_no_guidance_or_library_lookup(self):
        self.add_pillar("purpose", [self.concept("direction_vision", score=100, target_met=True)])
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
        self.assertIsNone(result["content"])
        self.library.assert_not_called()

    def test_no_concepts_returns_insufficient_data(self):
        result = self.result()
        self.assertEqual(result["review"]["status"], "insufficient_data")
        self.assertEqual(result["review"]["reviewed_count"], 0)
        self.assertEqual(result["available_concepts"], [])
        self.assertIsNone(result["content"])

    def test_partial_on_track_review_does_not_claim_unlogged_concepts_are_on_track(self):
        self.add_pillar("purpose", [
            self.concept("direction_vision", score=100, target_met=True),
            self.concept("values_alignment", logged=False),
        ])
        result = self.result()
        self.assertEqual(result["review"]["status"], "insufficient_data")
        self.assertEqual(result["review"]["on_track_count"], 1)
        self.assertEqual(result["review"]["unlogged_count"], 1)
        self.assertEqual(result["available_concepts"], [])

    def test_preferred_on_track_concept_cannot_override_an_off_track_concept(self):
        self.add_pillar("purpose", [
            self.concept("direction_vision", score=100, target_met=True),
            self.concept("values_alignment"),
        ])
        result = self.result(concept_key="direction_vision")
        self.assertEqual(result["concept_key"], "values_alignment")
        self.assertEqual([item["concept_key"] for item in result["available_concepts"]], ["values_alignment"])

    def test_resolved_tracker_date_controls_evidence_and_ignores_old_miss_after_recovery(self):
        yesterday = self.today - timedelta(days=1)
        recovered = self.concept("direction_vision", score=100, target_met=True, day=yesterday)
        old_miss = self.concept("direction_vision", day=yesterday - timedelta(days=1))["week"][0]
        recovered["week"].insert(0, old_miss)
        self.add_pillar("purpose", [recovered], active_day=yesterday)
        result = self.result()
        self.assertEqual(result["review"]["status"], "on_track")
        self.assertEqual(result["available_concepts"], [])

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
