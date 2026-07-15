from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import l2_codegraph.database as graph_database  # noqa: E402
from l2_codegraph.database import build_database, connect  # noqa: E402
from l2_codegraph.python_provider import analyze_project  # noqa: E402
from l2_codegraph.query import GraphQuery  # noqa: E402


class L2QueryTests(unittest.TestCase):
    def build_fixture(self, project: Path) -> GraphQuery:
        (project / "pkg").mkdir()
        (project / "tests").mkdir()
        (project / "pkg" / "__init__.py").write_text("", encoding="utf-8")
        (project / "pkg" / "repo.py").write_text("def save(value):\n    return value\n", encoding="utf-8")
        (project / "pkg" / "service.py").write_text(
            "from pkg.repo import save\n\ndef process(value):\n    return save(value)\n",
            encoding="utf-8",
        )
        (project / "app.py").write_text(
            "from pkg.service import process\n\ndef entry(value):\n    return process(value)\n",
            encoding="utf-8",
        )
        (project / "tests" / "test_app.py").write_text(
            "from app import entry\n\ndef test_entry():\n    assert entry(1) == 1\n",
            encoding="utf-8",
        )
        out = project / ".codegraph" / "l2.sqlite"
        build_database(project, out, [analyze_project(project)])
        return GraphQuery(out)

    def test_references_callers_callees_and_tests_are_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            query = self.build_fixture(Path(temp))
            callers = query.callers("pkg.repo.save")
            self.assertEqual("pkg.service.process", callers["callers"][0]["qualified_name"])
            callees = query.callees("app.entry")
            self.assertEqual("pkg.service.process", callees["callees"][0]["qualified_name"])
            references = query.find_references("pkg.service.process")
            self.assertTrue(any(item["source_symbol"] == "app.entry" for item in references["references"]))
            tests = query.tests_for("app.entry")
            self.assertEqual(["tests/test_app.py"], [item["file"] for item in tests["tests"]])

    def test_impact_and_slice_expose_paths_boundaries_and_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            query = self.build_fixture(Path(temp))
            impact = query.impact("pkg.repo.save", depth=4, budget=100)
            self.assertIn("app.py", impact["predicted_files"])
            self.assertIn("tests/test_app.py", impact["predicted_files"])
            app_reason = next(item for item in impact["direct"] + impact["transitive"] if item["file"] == "app.py")
            self.assertTrue(any(part.startswith("caller:") for part in app_reason["reason_path"]))

            semantic_slice = query.slice(["app.entry"], depth=2, budget=100)
            included = {item["qualified_name"] for item in semantic_slice["included_symbols"]}
            self.assertEqual({"app.entry", "pkg.service.process", "pkg.repo.save"}, included)
            self.assertEqual(1.0, semantic_slice["confidence"])
            self.assertTrue(semantic_slice["graph_revision"])
            self.assertEqual(["tests/test_app.py"], semantic_slice["likely_tests"])

    def test_ambiguous_short_name_and_budget_truncation_do_not_guess(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "a.py").write_text("def run():\n    return 1\n", encoding="utf-8")
            (project / "b.py").write_text("def run():\n    return 2\n", encoding="utf-8")
            out = project / ".codegraph" / "l2.sqlite"
            build_database(project, out, [analyze_project(project)])
            query = GraphQuery(out)
            self.assertEqual("ambiguous", query.resolve_symbol("run")["status"])
            self.assertEqual("invalid", query.slice(["run"])["status"])

    def test_expansion_adds_history_and_clears_depth_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            query = self.build_fixture(Path(temp))
            initial = query.slice(["app.entry"], depth=0, budget=100)
            self.assertTrue(initial["truncated"])
            expanded = query.expand(initial, {"relation": "callees", "depth": 3, "budget": 100, "reason": "follow call chain"})
            self.assertFalse(expanded["truncated"])
            self.assertEqual(1, len(expanded["expansion_history"]))
            self.assertIn("pkg.repo.save", {item["qualified_name"] for item in expanded["included_symbols"]})

    def test_read_session_is_nestable_and_reuses_one_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            query = self.build_fixture(Path(temp))
            with mock.patch("l2_codegraph.query.connect", wraps=connect) as patched_connect:
                with query.read_session():
                    pinned_connection = query.connection
                    with query.read_session():
                        self.assertIs(pinned_connection, query.connection)
                        self.assertTrue(query.graph_metadata()["revision"])
                    self.assertEqual("resolved", query.resolve_symbol("app.entry")["status"])
                    self.assertEqual("ready", query.slice(["app.entry"])["status"])
                    self.assertEqual("ok", query.impact("app.entry")["status"])
                    self.assertIs(pinned_connection, query.connection)
                self.assertEqual(1, patched_connect.call_count)
            with self.assertRaisesRegex(RuntimeError, "read session"):
                _ = query.connection

    def test_slice_blocks_publication_and_stays_on_one_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text(
                "def target_a():\n    return 1\n\ndef entry():\n    return target_a()\n",
                encoding="utf-8",
            )
            database = project / ".codegraph" / "l2.sqlite"
            revision_a = build_database(project, database, [analyze_project(project)])
            query = GraphQuery(database)

            source.write_text(
                "def target_b():\n    return 2\n\ndef entry():\n    return target_b()\n",
                encoding="utf-8",
            )
            result_b = analyze_project(project)
            publisher_at_boundary = threading.Event()
            publisher: threading.Thread | None = None
            published_revisions: list[str] = []
            publisher_errors: list[BaseException] = []
            original_publish = graph_database.publish_candidate
            original_resolve = query.resolve_symbol

            def marked_publish(*args, **kwargs) -> None:
                publisher_at_boundary.set()
                original_publish(*args, **kwargs)

            def publish_revision_b() -> None:
                try:
                    published_revisions.append(build_database(project, database, [result_b]))
                except BaseException as error:
                    publisher_errors.append(error)

            def staged_resolution(value: str) -> dict:
                nonlocal publisher
                resolved = original_resolve(value)
                publisher = threading.Thread(target=publish_revision_b, daemon=True)
                publisher.start()
                if not publisher_at_boundary.wait(5):
                    self.fail("publisher did not reach the publication boundary")
                return resolved

            with mock.patch.object(graph_database, "publish_candidate", side_effect=marked_publish):
                with mock.patch.object(query, "resolve_symbol", side_effect=staged_resolution):
                    semantic_slice = query.slice(["app.entry"])

            assert publisher is not None
            publisher.join(10)
            self.assertFalse(publisher.is_alive(), "publisher remained blocked after the query session closed")
            self.assertEqual([], publisher_errors)
            self.assertEqual(1, len(published_revisions))
            self.assertNotEqual(revision_a, published_revisions[0])
            self.assertEqual(revision_a, semantic_slice["graph_revision"])
            self.assertEqual(
                semantic_slice["entrypoint_resolutions"][0]["symbol"]["sha256"],
                semantic_slice["source_hashes"]["app.py"],
            )
            included = {item["qualified_name"] for item in semantic_slice["included_symbols"]}
            self.assertIn("app.target_a", included)
            self.assertNotIn("app.target_b", included)
            self.assertEqual(published_revisions[0], GraphQuery(database).graph_metadata()["revision"])

    def test_cli_out_writes_full_evidence_and_prints_compact_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.build_fixture(project)
            out = project / "callers.json"
            process = subprocess.run(
                [
                    "py", "-3", str(SCRIPT_DIR / "query_codegraph.py"), "--project", str(project),
                    "--level", "l2", "callers", "--symbol", "pkg.repo.save", "--out", str(out),
                ],
                text=True, encoding="utf-8", capture_output=True,
            )
            self.assertEqual(0, process.returncode, process.stderr)
            summary = json.loads(process.stdout)
            full = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(1, summary["counts"]["callers"])
            self.assertEqual("pkg.service.process", full["callers"][0]["qualified_name"])


if __name__ == "__main__":
    unittest.main()
