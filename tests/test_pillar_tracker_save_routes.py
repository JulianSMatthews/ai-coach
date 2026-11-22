"""Tracker reads and saves never generate or queue automatic coaching."""
import ast
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from fastapi import BackgroundTasks, Body, FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient


class PillarTrackerSaveRouteTests(unittest.TestCase):
    def setUp(self):
        api = FastAPI()
        self.access = Mock()
        self.save = Mock(side_effect=self.saved_result)
        self.summary = Mock(return_value={"pillars": []})
        self.detail = Mock(return_value={"pillar": {"pillar_key": "purpose"}})
        self.weekly_save = Mock(return_value={"sections": []})
        self.refresh = Mock(side_effect=AssertionError("Reads and saves must not queue AI generation"))
        self.engagement = Mock()
        namespace = {
            "api_v1": api, "Request": Request, "BackgroundTasks": BackgroundTasks,
            "Body": Body, "Header": Header, "HTTPException": HTTPException, "Any": Any,
            "_resolve_user_access": self.access, "ensure_pillar_tracker_schema": Mock(),
            "parse_tracker_anchor": self.parse_date, "save_pillar_tracker_day": self.save,
            "get_pillar_tracker_summary": self.summary, "get_pillar_tracker_detail": self.detail,
            "save_weekly_objectives_config": self.weekly_save,
            "_log_app_engagement_event": self.engagement,
            "queue_coach_home_tracker_refresh": self.refresh,
        }
        tree = ast.parse((Path(__file__).parents[1] / "app" / "api.py").read_text())
        route = ast.Module(body=[
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in {
                "api_user_pillar_tracker_save", "api_user_pillar_tracker_summary",
                "api_user_pillar_tracker_detail", "api_user_weekly_objectives_save",
            }
        ], type_ignores=[])
        exec(compile(route, "app/api.py", "exec"), namespace)
        self.client = self.enterContext(TestClient(api))
        self.entries = [{"concept_key": "values_alignment", "value": 3}]

    @staticmethod
    def parse_date(value):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def saved_result(_user_id, _pillar_key, **kwargs):
        if kwargs.get("skip_quote_generation") is not True:
            raise AssertionError("A tracker save must not request synchronous insight generation")
        return {
            "pillar": {"pillar_key": "purpose", "today": "2026-11-21"},
            "days": [{"date": "2026-11-21", "complete": True}],
        }

    def post(self, **overrides):
        return self.client.post("/users/42/pillar-tracker/purpose", json={
            "entries": self.entries, "score_date": "2026-11-21", **overrides,
        })

    def test_old_and_current_clients_save_without_waiting_for_generation(self):
        for flag in ({}, {"skip_quote_generation": False}, {"skip_quote_generation": True}):
            with self.subTest(flag=flag):
                self.save.reset_mock()
                self.refresh.reset_mock()
                response = self.post(**flag)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertTrue(response.json()["days"][0]["complete"])
                self.assertNotIn("coach_home_refresh", response.json())
                self.save.assert_called_once_with(
                    42, "purpose", score_date=date(2026, 11, 21),
                    entries=self.entries, skip_quote_generation=True,
                )
                self.refresh.assert_not_called()

    def test_home_and_detail_reads_ignore_legacy_generation_requests(self):
        for flag in ({}, {"skip_quote_generation": "false"}, {"skip_quote_generation": "true"}):
            with self.subTest(flag=flag):
                self.summary.reset_mock()
                self.detail.reset_mock()
                query = {"anchor_date": "2026-11-21", **flag}
                self.assertEqual(self.client.get("/users/42/pillar-tracker", params=query).status_code, 200)
                self.assertEqual(self.client.get("/users/42/pillar-tracker/purpose", params=query).status_code, 200)
                self.summary.assert_called_once_with(42, anchor=date(2026, 11, 21), skip_quote_generation=True)
                self.detail.assert_called_once_with(42, "purpose", anchor=date(2026, 11, 21), skip_quote_generation=True)
                self.refresh.assert_not_called()

    def test_objective_saves_do_not_queue_automatic_generation(self):
        response = self.client.post("/users/42/weekly-objectives", json={
            "section_key": "purpose", "concept_targets": {"values_alignment": 5},
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"sections": []})
        self.weekly_save.assert_called_once_with(
            42, pillar_key="purpose", concept_targets={"values_alignment": 5}, wellbeing_values={},
        )
        self.refresh.assert_not_called()

    def test_invalid_entries_and_save_validation_still_reject_without_refreshing(self):
        response = self.post(entries="invalid")
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(response.json()["detail"], "entries must be a list")
        self.save.assert_not_called()
        self.refresh.assert_not_called()
        self.engagement.assert_not_called()

        self.save.side_effect = ValueError("A complete pillar tracker requires all concept values for the day.")
        response = self.post(entries=[])
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("requires all concept values", response.json()["detail"])
        self.refresh.assert_not_called()
        self.engagement.assert_not_called()


if __name__ == "__main__":
    unittest.main()
