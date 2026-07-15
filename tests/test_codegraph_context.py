from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import build_codegraph  # noqa: E402
import init_adworkflow  # noqa: E402
import prepare_context  # noqa: E402
import query_codegraph  # noqa: E402


class CodegraphContextTests(unittest.TestCase):
    def test_advertised_queries_are_implemented(self) -> None:
        for size in ("small", "medium", "large"):
            advertised = set(init_adworkflow.queries_for_size(size))
            self.assertLessEqual(advertised, query_codegraph.SUPPORTED_QUERIES)
        self.assertIn("callers", init_adworkflow.queries_for_size("large"))
        self.assertEqual("L2-semantic-codegraph", init_adworkflow.strategy_for_size("large"))

    def test_index_staleness_detects_added_changed_and_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "src" / "app.py"
            source.parent.mkdir(parents=True)
            source.write_text("def first():\n    return 1\n", encoding="utf-8")
            index = build_codegraph.build_index(project)
            self.assertFalse(build_codegraph.index_is_stale(project, index))

            source.write_text("def second():\n    return 2\n", encoding="utf-8")
            self.assertTrue(build_codegraph.index_is_stale(project, index))
            updated = build_codegraph.build_index(project)
            extra = project / "src" / "extra.py"
            extra.write_text("VALUE = 1\n", encoding="utf-8")
            self.assertTrue(build_codegraph.index_is_stale(project, updated))
            extra.unlink()
            source.unlink()
            self.assertTrue(build_codegraph.index_is_stale(project, updated))

    def test_prepare_rebuilds_stale_index_and_finds_new_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "src" / "app.py"
            source.parent.mkdir(parents=True)
            source.write_text("def first_symbol():\n    return 1\n", encoding="utf-8")
            index_path = project / ".codegraph" / "index.json"
            build_codegraph.write_index(index_path, build_codegraph.build_index(project))
            source.write_text("def fresh_symbol():\n    return 2\n", encoding="utf-8")
            task = self.task("fresh-symbol", "Implement fresh_symbol.")

            raw, manifest = prepare_context.prepare(project, task, no_build_index=False)
            names = [item["name"] for item in raw["matched_symbols"]]
            self.assertIn("fresh_symbol", names)
            self.assertIn("src/app.py", manifest["read_first"])

    def test_workflow_task_uses_document_context_even_when_code_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "src").mkdir()
            (project / "src" / "app.py").write_text("def app():\n    return 1\n", encoding="utf-8")
            (project / "PRD.md").write_text("FR-001 Workflow requirement.\n", encoding="utf-8")
            (project / "ARCH.md").write_text("FR-001 Workflow architecture.\n", encoding="utf-8")
            task = self.task("audit-workflow", "Audit the workflow.", task_type="workflow")

            raw, manifest = prepare_context.prepare(project, task, no_build_index=False)
            self.assertEqual("architecture-docs", raw["source"])
            self.assertIn("PRD.md", manifest["read_first"])
            self.assertIn("ARCH.md", manifest["read_first"])

    def test_unconfigured_task_is_rejected(self) -> None:
        task = self.task("unconfigured", "", configured=False)
        with self.assertRaisesRegex(ValueError, "configured"):
            prepare_context.validate_task(task)

    def test_tests_for_does_not_return_unrelated_fallback_tests(self) -> None:
        index = {"tests": ["tests/test_billing.py"]}
        self.assertEqual([], query_codegraph.tests_for(index, "src/auth.py"))

    @staticmethod
    def task(task_id: str, goal: str, task_type: str = "code", configured: bool = True) -> dict:
        return {
            "schema": "ADworkflo.task_spec.v2",
            "configured": configured,
            "task_id": task_id,
            "task_type": task_type,
            "goal": goal,
            "non_goals": [],
            "acceptance_criteria": ["Context identifies the target."] if configured else [],
            "risk_level": "low",
            "execution_mode": "solo_worker",
            "allowed_actions": ["read"],
            "required_outputs": ["context_raw.json", "context_manifest.json"],
            "do_not_touch": ["vendor/"],
            "entrypoints": ["fresh_symbol"] if task_type == "code" else [],
            "context_sources": [],
            "notes": [],
        }


if __name__ == "__main__":
    unittest.main()
