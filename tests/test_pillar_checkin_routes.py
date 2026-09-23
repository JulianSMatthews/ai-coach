"""Run the actual route functions without the monolithic API's startup services."""
import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient


class CheckinRouteTests(unittest.TestCase):
    def setUp(self):
        api = FastAPI()
        self.access = Mock(return_value=types.SimpleNamespace(id=1, first_assessment_completed=None))
        self.preview = Mock(return_value=False)
        self.handle = Mock(return_value=({"phase": "collecting", "messages": []}, False))
        self.token = Mock(return_value=("test-token", 540))
        self.legacy_ready = Mock(return_value=False)
        names = {"api_user_pillar_checkin_voice_session", "api_user_pillar_checkin_message"}
        tree = ast.parse((Path(__file__).parents[1] / "app" / "api.py").read_text())
        routes = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names], type_ignores=[])
        namespace = {
            "__name__": "app.api", "__package__": "app", "api_v1": api,
            "Request": Request, "BackgroundTasks": BackgroundTasks, "Body": Body,
            "Any": object, "HTTPException": HTTPException, "JSONResponse": JSONResponse,
            "_resolve_user_access": self.access, "_is_readonly_admin_preview_request": self.preview,
            "_general_support_ready_for_user": self.legacy_ready,
            "_log_app_engagement_event": Mock(), "queue_coach_home_tracker_refresh": Mock(),
        }
        exec(compile(routes, "app/api.py", "exec"), namespace)
        self.modules = patch.dict(sys.modules, {
            "app.avatar": types.SimpleNamespace(issue_avatar_speech_token=self.token, _avatar_region=lambda: "uksouth", azure_avatar_defaults=lambda: {"voice": "test-voice", "locale": "en-GB"}),
            "app.pillar_checkin": types.SimpleNamespace(handle_message=self.handle),
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.client = TestClient(api)
        self.addCleanup(self.client.close)

    def post(self, voice=False):
        path = "/users/1/pillar-checkin" + ("/voice-session" if voice else "")
        return self.client.post(path, json={"text": "start", "request_id": "test-request-1"})

    def test_account_without_assessment_can_start_conversation(self):
        response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.handle.assert_called_once_with(1, "start", "test-request-1")
        self.access.assert_called_once()
        self.legacy_ready.assert_not_called()

    def test_account_without_assessment_can_start_voice(self):
        response = self.post(voice=True)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["token"], "test-token")
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.access.assert_called_once()
        self.legacy_ready.assert_not_called()

    def test_unauthenticated_and_other_account_access_still_rejected(self):
        for status in (401, 403):
            for voice in (False, True):
                with self.subTest(status=status, voice=voice):
                    self.access.side_effect = HTTPException(status_code=status, detail="Access denied")
                    self.assertEqual(self.post(voice).status_code, status)
        self.handle.assert_not_called()
        self.token.assert_not_called()

    def test_readonly_preview_cannot_start_either_flow(self):
        self.preview.return_value = True
        for voice in (False, True):
            self.assertEqual(self.post(voice).status_code, 403)
        self.handle.assert_not_called()
        self.token.assert_not_called()


if __name__ == "__main__":
    unittest.main()
