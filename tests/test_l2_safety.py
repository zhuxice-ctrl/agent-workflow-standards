from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from l2_codegraph.database import build_database  # noqa: E402
from l2_codegraph.python_provider import analyze_project  # noqa: E402
from l2_codegraph.query import GraphQuery  # noqa: E402
from l2_codegraph.safety import post_edit_impact, preflight  # noqa: E402


class L2SafetyTests(unittest.TestCase):
    def test_new_test_critical_edge_requires_review_without_blocking_production(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "def entry():\n    return 1\n", encoding="utf-8",
            )
            database = project / ".codegraph" / "l2.sqlite"
            first = build_database(
                project, database, [analyze_project(project)],
            )
            baseline = database.parent / "snapshots" / f"{first}.sqlite"
            tests_dir = project / "tests"
            tests_dir.mkdir()
            (tests_dir / "test_app.py").write_text(
                "def test_dynamic(callback):\n    return callback()\n",
                encoding="utf-8",
            )
            build_database(project, database, [analyze_project(project)])

            report = post_edit_impact(
                "test-critical", baseline, database,
                ["tests/test_app.py"], ["tests/test_app.py"],
            )

            self.assertEqual("passed", report["status"])
            self.assertEqual([], report["new_critical_unresolved_edges"])
            self.assertTrue(report["new_test_critical_unresolved_edges"])
            self.assertTrue(report["review_required"])

    def test_post_edit_does_not_treat_relocated_critical_edge_as_new(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text(
                "def entry(value):\n    return value.missing()\n",
                encoding="utf-8",
            )
            database = project / ".codegraph" / "l2.sqlite"
            first = build_database(
                project, database, [analyze_project(project)],
            )
            baseline = database.parent / "snapshots" / f"{first}.sqlite"
            source.write_text(
                "\ndef entry(value):\n    return value.missing()\n",
                encoding="utf-8",
            )
            build_database(project, database, [analyze_project(project)])

            report = post_edit_impact(
                "relocated-critical", baseline, database, ["app.py"], ["app.py"],
            )

            self.assertEqual([], report["new_critical_unresolved_edges"])
            self.assertEqual("passed", report["status"])

    def test_post_edit_rejects_reused_current_revision_as_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "def entry():\n    return 1\n", encoding="utf-8",
            )
            database = project / ".codegraph" / "l2.sqlite"
            build_database(project, database, [analyze_project(project)])

            report = post_edit_impact(
                "reused-baseline", database, database, ["app.py"], ["app.py"],
            )

            self.assertEqual("failed", report["status"])
            self.assertTrue(
                report["baseline_validation"]["reused_after_declared_edit"],
            )
            self.assertTrue(report["review_required"])

    def test_post_edit_rejects_same_revision_for_unindexed_new_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "def entry():\n    return 1\n", encoding="utf-8",
            )
            database = project / ".codegraph" / "l2.sqlite"
            build_database(project, database, [analyze_project(project)])
            (project / "new.py").write_text(
                "def added():\n    return 2\n", encoding="utf-8",
            )

            report = post_edit_impact(
                "unindexed-source", database, database, ["new.py"], ["new.py"],
            )

            self.assertEqual("failed", report["status"])
            self.assertEqual(
                ["new.py"],
                report["baseline_validation"]["declared_graph_files"],
            )
            self.assertTrue(
                report["baseline_validation"]["reused_after_declared_edit"],
            )
            self.assertTrue(report["review_required"])

    def test_preflight_accepts_fresh_complete_slice_and_invalidates_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text("def target():\n    return 1\n\ndef entry():\n    return target()\n", encoding="utf-8")
            database = project / ".codegraph" / "l2.sqlite"
            build_database(project, database, [analyze_project(project)])
            semantic_slice = GraphQuery(database).slice(["app.entry"])
            accepted = preflight(project, database, semantic_slice, "task-1")
            self.assertEqual("accepted", accepted["status"])
            source.write_text("def target():\n    return 2\n\ndef entry():\n    return target()\n", encoding="utf-8")
            invalid = preflight(project, database, semantic_slice, "task-1")
            self.assertEqual("invalid", invalid["status"])
            self.assertIn("source-drift", invalid["invalid_reasons"])

    def test_critical_unresolved_call_requires_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def entry(callback):\n    return callback()\n", encoding="utf-8")
            database = project / ".codegraph" / "l2.sqlite"
            build_database(project, database, [analyze_project(project)])
            semantic_slice = GraphQuery(database).slice(["app.entry"])
            result = preflight(project, database, semantic_slice, "task-1")
            self.assertEqual("needs_expansion", result["status"])
            self.assertIn("critical-unresolved-edges", result["expansion_reasons"])

    def test_post_edit_detects_unexpected_file_and_new_unresolved_edge(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            app = project / "app.py"
            extra = project / "extra.py"
            app.write_text("def entry():\n    return 1\n", encoding="utf-8")
            extra.write_text("def stable():\n    return 1\n", encoding="utf-8")
            database = project / ".codegraph" / "l2.sqlite"
            first = build_database(project, database, [analyze_project(project)])
            baseline = project / "baseline.sqlite"
            shutil.copyfile(project / ".codegraph" / "snapshots" / f"{first}.sqlite", baseline)
            extra.write_text("def stable(callback):\n    return callback()\n", encoding="utf-8")
            build_database(project, database, [analyze_project(project)])
            report = post_edit_impact("task-1", baseline, database, ["app.py"], ["app.py"])
            self.assertEqual("failed", report["status"])
            self.assertEqual(["extra.py"], report["unexpected_impact"])
            self.assertTrue(report["new_critical_unresolved_edges"])


if __name__ == "__main__":
    unittest.main()
