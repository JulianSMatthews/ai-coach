import copy
import json
import sys
import types
import unittest
from datetime import date
from unittest.mock import Mock, patch

from app.pillar_checkin import advance, handle_message, validated_answers, _reflect


CONCEPTS = [
    {"concept_key": "sleep_duration", "label": "7h+ Sleep", "helper": "last night", "options": [{"value": 0, "label": "No"}, {"value": 1, "label": "Yes"}]},
    {"concept_key": "sleep_quality", "label": "Rested", "helper": "How rested did you feel?", "options": [{"value": 0, "label": "Not at all"}, {"value": 1, "label": "Completely"}]},
]
DETAIL = {"concepts": CONCEPTS}


def answer(key, value, evidence):
    return {"concept_key": key, "value": value, "evidence": evidence}


class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.extract = Mock(return_value={"answers": []})
        self.save = Mock(return_value=DETAIL)
        self.reflect = Mock(return_value="What made recovery easier?")

    def turn(self, state=None, text="start", today="2026-09-23", detail=None):
        return advance(state, text=text, today=today, detail=detail or DETAIL,
                       extract=self.extract, save=self.save, reflect=self.reflect)

    def complete_answers(self):
        state = self.turn()
        self.extract.return_value = {"answers": [answer("sleep_duration", 1, "eight hours"), answer("sleep_quality", 1, "refreshed")]}
        return self.turn(state, "I slept eight hours and feel refreshed")

    def test_multiple_answers_require_confirmation_before_save(self):
        state = self.complete_answers()
        self.assertEqual(state["phase"], "confirming")
        self.save.assert_not_called()
        state = self.turn(state, "save")
        self.save.assert_called_once_with({"sleep_duration": 1, "sleep_quality": 1}, "2026-09-23")
        self.assertEqual(state["phase"], "completed")
        self.assertIn("is saved", state["messages"][-1]["text"])

    def test_yes_during_collection_is_an_answer_not_save(self):
        state = self.turn()
        self.extract.return_value = {"answers": [answer("sleep_duration", 1, "yes")]}
        state = self.turn(state, "yes")
        self.assertEqual(state["phase"], "collecting")
        self.assertIn("How rested", state["messages"][-1]["text"])
        self.save.assert_not_called()

    def test_correction_replaces_answer_and_requires_new_confirmation(self):
        state = self.complete_answers()
        self.extract.return_value = {"answers": [answer("sleep_duration", 0, "six hours")]}
        corrected = self.turn(state, "Actually six hours")
        self.assertEqual(corrected["answers"]["sleep_duration"], 0)
        self.assertEqual(state["answers"]["sleep_duration"], 1)
        self.assertIn("7h+ Sleep: No", corrected["messages"][-1]["text"])
        self.save.assert_not_called()

    def test_invalid_model_output_cannot_change_or_save_answers(self):
        state = self.turn()
        for output in ({"answers": [answer("unknown", 1, "yes")]}, {"answers": [answer("sleep_duration", 6, "yes")]}, {"answers": [answer("sleep_duration", 1, "invented")]}, [], {"answers": [answer("sleep_duration", True, "yes")]}):
            with self.subTest(output=output):
                self.extract.return_value = output
                with self.assertLogs("app.pillar_checkin", level="WARNING"):
                    result = self.turn(state, "yes")
                self.assertEqual(result["answers"], {})
        self.save.assert_not_called()

    def test_model_failure_leaves_draft_intact(self):
        state = self.complete_answers()
        self.extract.side_effect = RuntimeError("unavailable")
        with self.assertLogs("app.pillar_checkin", level="WARNING"):
            result = self.turn(state, "Actually no")
        self.assertEqual(state["answers"], result["answers"])

    def test_save_failure_does_not_claim_success(self):
        state = self.complete_answers()
        self.save.side_effect = ValueError("Date no longer editable")
        with self.assertRaises(ValueError):
            self.turn(state, "save")
        self.assertEqual(state["phase"], "confirming")
        self.reflect.assert_not_called()

    def test_new_day_does_not_save_yesterdays_draft(self):
        state = self.complete_answers()
        result = self.turn(state, "save", today="2026-09-24")
        self.assertEqual(result["answers"], {})
        self.assertEqual(result["score_date"], "2026-09-24")
        self.save.assert_not_called()

    def test_configuration_change_invalidates_confirmation(self):
        state = self.complete_answers()
        changed = copy.deepcopy(DETAIL)
        changed["concepts"][0]["label"] = "8h+ Sleep"
        result = self.turn(state, "save", detail=changed)
        self.assertEqual(result["phase"], "collecting")
        self.save.assert_not_called()

    def test_pause_resume_and_reflection_do_not_resave(self):
        state = self.complete_answers()
        state = self.turn(state, "pause")
        resumed = self.turn(state, "resume")
        self.assertEqual(resumed["answers"], state["answers"])
        self.assertIn("Shall I save", resumed["messages"][-1]["text"])
        completed = self.turn(resumed, "save")
        reflected = self.turn(completed, "I had a calmer evening")
        self.assertEqual(reflected["phase"], "completed")
        self.save.assert_called_once()
        edited = self.turn(reflected, "edit")
        self.assertEqual(edited["phase"], "confirming")

    def test_ambiguous_response_does_not_fill_missing_fields(self):
        state = self.turn()
        self.extract.return_value = {"answers": [], "clarification": "Was that last night?"}
        state = self.turn(state, "Maybe seven hours on Monday")
        self.assertEqual(state["answers"], {})
        self.assertIn("Was that last night?", state["messages"][-1]["text"])

    def test_duplicate_extracted_concepts_rejected(self):
        with self.assertRaises(ValueError):
            validated_answers({"answers": [answer("sleep_duration", 1, "yes")] * 2}, CONCEPTS, "yes")

    def test_reflection_outage_has_fallback(self):
        fake_prompts = types.SimpleNamespace(run_llm_prompt=Mock(side_effect=RuntimeError("offline")))
        with patch.dict(sys.modules, {"app.prompts": fake_prompts}), self.assertLogs("app.pillar_checkin", level="WARNING"):
            self.assertIn("What stands out", _reflect(1, {"answers": {}, "messages": []}, DETAIL, None))


class PersistenceTests(unittest.TestCase):
    """Exercise the adapter against an isolated database, without live services."""
    def setUp(self):
        from sqlalchemy import Column, Integer, String, Text, UniqueConstraint, create_engine
        from sqlalchemy.orm import declarative_base, sessionmaker

        base = declarative_base()

        class User(base):
            __tablename__ = "users"
            id = Column(Integer, primary_key=True)

        class UserPreference(base):
            __tablename__ = "user_preferences"
            id = Column(Integer, primary_key=True)
            user_id = Column(Integer)
            key = Column(String)
            value = Column(Text)
            __table_args__ = (UniqueConstraint("user_id", "key"),)

        engine = create_engine("sqlite://")
        base.metadata.create_all(engine)
        sessions = sessionmaker(bind=engine)
        with sessions() as session:
            session.add_all([User(id=1), User(id=2)])
            session.commit()
        self.writer = Mock(return_value=DETAIL)
        self.modules = patch.dict(sys.modules, {
            "app.db": types.SimpleNamespace(SessionLocal=sessions),
            "app.models": types.SimpleNamespace(User=User, UserPreference=UserPreference),
            "app.pillar_tracker": types.SimpleNamespace(get_pillar_tracker_detail=Mock(return_value=DETAIL), save_pillar_tracker_day=self.writer, tracker_today=lambda: date(2026, 9, 23)),
        })
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.addCleanup(engine.dispose)

    def test_resume_retries_and_user_isolation(self):
        from app.pillar_checkin import get_state

        handle_message(1, "start", "request-start")
        extraction = {"answers": [answer("sleep_duration", 1, "yes"), answer("sleep_quality", 1, "yes")]}
        with patch("app.pillar_checkin._extract", return_value=extraction):
            first, _ = handle_message(1, "yes to both", "request-answer")
            retry, saved = handle_message(1, "yes to both", "request-answer")
        self.assertEqual(first, retry)
        self.assertFalse(saved)
        self.assertEqual(get_state(2), {})
        self.assertEqual(get_state(1)["phase"], "confirming")
        with patch("app.pillar_checkin._reflect", return_value="How did that feel?"):
            completed, saved = handle_message(1, "save", "request-save")
            repeated, saved_again = handle_message(1, "save", "request-save")
        self.assertTrue(saved)
        self.assertFalse(saved_again)
        self.assertEqual(completed, repeated)
        self.writer.assert_called_once()

    def test_failed_save_preserves_confirmation_for_retry(self):
        handle_message(1, "start", "request-start")
        with patch("app.pillar_checkin._extract", return_value={"answers": [answer("sleep_duration", 1, "yes"), answer("sleep_quality", 1, "yes")]}):
            handle_message(1, "yes to both", "request-answer")
        self.writer.side_effect = RuntimeError("database unavailable")
        with self.assertRaises(RuntimeError):
            handle_message(1, "save", "request-save")
        self.writer.side_effect = None
        with patch("app.pillar_checkin._reflect", return_value="Thanks"):
            result, saved = handle_message(1, "save", "request-save")
        self.assertTrue(saved)
        self.assertEqual(result["phase"], "completed")


if __name__ == "__main__":
    unittest.main()
