"""Saved insight history stays isolated, chronological and free of generation."""
import ast
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import JSON, create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import pillar_tracker as tracker
from app.models import PillarCueQuote


class PillarInsightHistoryTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 17)
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)
        column = PillarCueQuote.__table__.c.meta
        self.enterContext(patch.object(column, "type", column.type.with_variant(JSON(), "sqlite")))
        PillarCueQuote.__table__.create(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.enterContext(patch.object(tracker, "SessionLocal", self.sessions))
        self.schema = self.enterContext(patch.object(tracker, "ensure_pillar_tracker_schema"))
        self.enterContext(patch.object(tracker, "tracker_today", return_value=self.today))
        self.generators = [
            self.enterContext(patch.object(tracker, name, side_effect=AssertionError("History must not generate")))
            for name in ("_daily_pillar_quote", "_save_latest_daily_pillar_quote", "run_llm_prompt")
        ]
        self.statements = []
        event.listen(self.engine, "before_cursor_execute", lambda _conn, _cursor, statement, *_args: self.statements.append(statement))

        # Load the actual route without starting the monolithic API's services.
        api = FastAPI()
        self.access = Mock()
        namespace = {
            "api_v1": api, "Request": Request, "Header": Header, "HTTPException": HTTPException,
            "_resolve_user_access": self.access, "parse_tracker_anchor": tracker.parse_tracker_anchor,
            "get_pillar_insight_history": tracker.get_pillar_insight_history,
        }
        tree = ast.parse((Path(__file__).parents[1] / "app" / "api.py").read_text())
        route = ast.Module(body=[
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "api_user_pillar_insight_history"
        ], type_ignores=[])
        exec(compile(route, "app/api.py", "exec"), namespace)
        self.client = self.enterContext(TestClient(api))

    def save(self, day, quote, *, user_id=1, pillar_key="nutrition", source="home_pillar_quote_bank"):
        with self.sessions() as session:
            row = PillarCueQuote(
                user_id=user_id, pillar_key=pillar_key, quote_date=day, quote=quote,
                source_cache_key=source, generated_at=datetime(2026, 11, 17, 10),
            )
            session.add(row)
            session.commit()
            return row.id

    def history(self, **kwargs):
        return tracker.get_pillar_insight_history(1, "nutrition", **kwargs)

    def get(self, query="", *, pillar="nutrition", headers=None):
        return self.client.get(f"/users/1/pillar-tracker/{pillar}/insights{query}", headers=headers or {})

    def test_only_requested_user_and_pillar_and_actual_dates_are_returned(self):
        self.save(self.today - timedelta(days=8), "An older insight")
        self.save(self.today, '"A quote"\nA reflection.\nAn author')
        self.save(self.today, "Other account", user_id=2)
        self.save(self.today, "Other pillar", pillar_key="training")
        self.save(self.today + timedelta(days=1), "Future insight")
        result = self.history()
        self.assertEqual([item["quote_date"] for item in result["insights"]], ["2026-11-17", "2026-11-09"])
        self.assertEqual(result["insights"][0]["quote"], '"A quote"\nA reflection.\nAn author')
        self.assertEqual(result["insights"][0]["generated_at"], "2026-11-17T10:00:00")
        self.assertFalse(result["has_more"])
        self.assertIsNone(result["next_before"])

    def test_empty_days_do_not_carry_previous_insight_forward(self):
        self.save(self.today - timedelta(days=14), "A saved insight")
        result = self.history()
        self.assertEqual(len(result["insights"]), 1)
        self.assertEqual(result["insights"][0]["quote_date"], "2026-11-03")
        self.assertEqual(self.get(pillar="training").json()["insights"], [])

    def test_all_saved_sources_and_repeated_text_are_retained(self):
        sources = [None, "home_pillar_daily_quote", "education_concept_insight", "home_pillar_quote_bank"]
        for offset, source in enumerate(sources):
            self.save(self.today - timedelta(days=offset), "The same saved insight", source=source)
        self.assertEqual(len(self.history()["insights"]), 4)

    def test_pagination_skips_many_blank_and_fallback_rows_without_losing_valid_dates(self):
        self.save(self.today, "Newest insight")
        for offset in range(1, 36):
            quote = "  \n " if offset % 2 else tracker._HOME_PILLAR_QUOTE_FALLBACKS["nutrition"]
            self.save(self.today - timedelta(days=offset), quote)
        self.save(self.today - timedelta(days=36), "Middle insight")
        self.save(self.today - timedelta(days=39), "Oldest insight")
        first = self.history(limit=1)
        self.assertTrue(first["has_more"])
        self.assertEqual(first["next_before"], "2026-11-17")
        second = self.history(limit=1, before=date.fromisoformat(first["next_before"]))
        self.assertEqual(second["insights"][0]["quote"], "Middle insight")
        self.assertTrue(second["has_more"])
        third = self.history(limit=1, before=date.fromisoformat(second["next_before"]))
        self.assertEqual(third["insights"][0]["quote"], "Oldest insight")
        self.assertFalse(third["has_more"])
        self.assertIsNone(third["next_before"])
        self.assertEqual(self.history(before=date(2026, 1, 1))["insights"], [])

    def test_default_limit_and_exact_page_boundary(self):
        for offset in range(10):
            self.save(self.today - timedelta(days=offset), f"Insight {offset}")
        result = self.history()
        self.assertEqual(len(result["insights"]), 10)
        self.assertFalse(result["has_more"])
        self.save(self.today - timedelta(days=10), "One more insight")
        result = self.history()
        self.assertEqual(len(result["insights"]), 10)
        self.assertTrue(result["has_more"])

    def test_reads_do_not_change_saved_content_or_generate_new_content(self):
        row_id = self.save(self.today - timedelta(days=2), "Original saved insight")
        self.statements.clear()
        self.history()
        self.get()
        self.assertTrue(self.statements)
        self.assertTrue(all(statement.lstrip().upper().startswith("SELECT") for statement in self.statements))
        for generator in self.generators:
            generator.assert_not_called()
        with self.sessions() as session:
            rows = session.execute(select(PillarCueQuote)).scalars().all()
            self.assertEqual([(row.id, row.quote) for row in rows], [(row_id, "Original saved insight")])

    def test_validation_rejects_unknown_pillars_bad_dates_and_unbounded_limits(self):
        for query, pillar in [
            ("", "unknown"), ("?before=invalid", "nutrition"), ("?before=20261110", "nutrition"),
            ("?before=2026-02-30", "nutrition"), ("?before=", "nutrition"),
            ("?limit=0", "nutrition"), ("?limit=31", "nutrition"),
        ]:
            with self.subTest(query=query, pillar=pillar):
                self.assertEqual(self.get(query, pillar=pillar).status_code, 400)
        self.assertEqual(self.get("?limit=abc").status_code, 422)
        self.schema.assert_not_called()
        for limit in (True, "10", 1.5):
            with self.assertRaises(ValueError):
                self.history(limit=limit)

    def test_route_forwards_exclusive_date_limit_and_admin_access_headers(self):
        self.save(self.today, "Today")
        self.save(self.today - timedelta(days=1), "Yesterday")
        response = self.get("?before=2026-11-17&limit=1", headers={"X-Admin-Token": "token", "X-Admin-User-Id": "99"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["insights"][0]["quote"], "Yesterday")
        self.assertEqual(self.access.call_args.kwargs["user_id"], 1)
        self.assertEqual(self.access.call_args.kwargs["x_admin_token"], "token")
        self.assertEqual(self.access.call_args.kwargs["x_admin_user_id"], "99")

    def test_access_denial_precedes_any_history_read(self):
        for status in (401, 403, 404):
            self.access.side_effect = HTTPException(status_code=status, detail="Access denied")
            self.assertEqual(self.get().status_code, status)
        self.schema.assert_not_called()
        self.assertEqual(self.statements, [])


if __name__ == "__main__":
    unittest.main()
