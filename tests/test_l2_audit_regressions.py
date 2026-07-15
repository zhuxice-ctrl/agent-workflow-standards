from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import orchestrator  # noqa: E402
import prepare_context  # noqa: E402
from build_codegraph_l2 import build as build_l2  # noqa: E402
from l2_codegraph.database import build_database, connect  # noqa: E402
from l2_codegraph.model import validate_provider_result  # noqa: E402
from l2_codegraph.python_provider import analyze_project as analyze_python  # noqa: E402
from l2_codegraph.query import GraphQuery  # noqa: E402
from l2_codegraph.safety import post_edit_impact, preflight  # noqa: E402
from l2_codegraph.typescript_provider import analyze_project as analyze_typescript, capability_status  # noqa: E402
from tests.test_l2_workflow import L2WorkflowTests  # noqa: E402


class L2AuditRegressionTests(unittest.TestCase):
    def build_python(self, project: Path) -> tuple[Path, GraphQuery]:
        database = project / ".codegraph" / "l2.sqlite"
        build_database(project, database, [analyze_python(project)])
        return database, GraphQuery(database)

    def test_slice_includes_resolved_forward_references(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("CONFIG = 7\n\ndef entry():\n    return CONFIG\n", encoding="utf-8")
            database, query = self.build_python(project)
            semantic_slice = query.slice(["app.entry"])
            self.assertIn("app.CONFIG", {item["qualified_name"] for item in semantic_slice["included_symbols"]})
            self.assertEqual("accepted", preflight(project, database, semantic_slice, "forward-ref")["status"])

    def test_unresolved_noncall_reference_requires_expansion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def entry():\n    return MISSING_GLOBAL\n", encoding="utf-8")
            database, query = self.build_python(project)
            semantic_slice = query.slice(["app.entry"])
            self.assertTrue(any(item["kind"] == "reference" and item["critical"] for item in semantic_slice["unresolved_edges"]))
            self.assertEqual("needs_expansion", preflight(project, database, semantic_slice, "missing-ref")["status"])

    def test_graph_revision_changes_when_semantic_edges_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def target():\n    return 1\n\ndef entry():\n    return target()\n", encoding="utf-8")
            first = analyze_python(project)
            second = copy.deepcopy(first)
            second["calls"] = []
            revision1 = build_database(project, project / "first.sqlite", [first])
            revision2 = build_database(project, project / "second.sqlite", [second])
            self.assertNotEqual(revision1, revision2)

    def test_post_edit_propagates_changed_file_to_existing_consumers(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "lib.py").write_text("def target():\n    return 1\n", encoding="utf-8")
            (project / "app.py").write_text("from lib import target\n\ndef entry():\n    return target()\n", encoding="utf-8")
            (project / "other.py").write_text("from lib import target\n\ndef other():\n    return target()\n", encoding="utf-8")
            database, query = self.build_python(project)
            revision = query.graph_metadata()["revision"]
            baseline = project / ".codegraph" / "snapshots" / f"{revision}.sqlite"
            predicted = query.impact("app.entry", depth=4, budget=100)["predicted_files"]
            (project / "lib.py").write_text("def target():\n    return 200\n", encoding="utf-8")
            build_database(project, database, [analyze_python(project)])
            report = post_edit_impact("impact", baseline, database, ["lib.py"], predicted)
            self.assertIn("other.py", report["observed_impact_files"])
            self.assertIn("other.py", report["unexpected_impact"])
            self.assertEqual("failed", report["status"])

    def test_orchestrator_recomputes_forged_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir, _, _, gate, _ = L2WorkflowTests().make_run(project, "def entry(callback):\n    return callback()\n")
            self.assertEqual("needs_expansion", gate["status"])
            task_dir = run_dir / "tasks" / "task-l2"
            forged = json.loads((task_dir / "context_preflight.json").read_text(encoding="utf-8"))
            forged["status"] = "accepted"
            (task_dir / "context_preflight.json").write_text(json.dumps(forged), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "recomputed|evidence|preflight"):
                orchestrator.update_task(run_dir, "task-l2", "in_progress", expected_revision=0)

    def test_orchestrator_recomputes_post_edit_impact_before_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir, spec, _, gate, _ = L2WorkflowTests().make_run(project, "def entry():\n    return 1\n")
            orchestrator.update_task(run_dir, "task-l2", "in_progress", expected_revision=0)
            task_dir = run_dir / "tasks" / "task-l2"
            database = project / ".codegraph" / "l2.sqlite"
            baseline = project / ".codegraph" / "snapshots" / f"{gate['graph_revision']}.sqlite"
            (project / "app.py").write_text("def entry():\n    return 2\n", encoding="utf-8")
            build_database(project, database, [analyze_python(project)])
            manifest = json.loads((task_dir / "context_manifest.json").read_text(encoding="utf-8"))
            real_impact = post_edit_impact(
                "task-l2", baseline, database, ["app.py"], manifest.get("predicted_impact_files", []),
            )
            self.assertEqual("passed", real_impact["status"])
            forged = copy.deepcopy(real_impact)
            forged["observed_impact_files"] = []
            (task_dir / "impact_report.json").write_text(json.dumps(forged), encoding="utf-8")
            worker = json.loads((task_dir / "worker_state.json").read_text(encoding="utf-8"))
            worker["changed_files"] = ["app.py"]
            (task_dir / "worker_state.json").write_text(json.dumps(worker), encoding="utf-8")
            verification = {
                "schema": "ADworkflo.verification_result.v1", "task_id": "task-l2", "status": "passed",
                "source_revision": "revision-edited", "commands": [],
                "acceptance_criteria_coverage": [{"criterion": spec["acceptance_criteria"][0], "status": "passed", "evidence": ["unit"]}],
                "passed": ["unit"], "failed": [], "not_run_reason": None, "residual_risk": [],
            }
            review = {
                "schema": "ADworkflo.review_findings.v1", "task_id": "task-l2", "status": "approved",
                "reviewer": "reviewer-1", "source_revision": "revision-edited",
                "review_basis": ["context_preflight", "impact_report"], "blocking_findings": [],
                "non_blocking_findings": [], "suggested_tests": [], "risk_notes": [],
            }
            (task_dir / "verification_result.json").write_text(json.dumps(verification), encoding="utf-8")
            (task_dir / "review_findings.json").write_text(json.dumps(review), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "recomputed impact"):
                orchestrator.update_task(run_dir, "task-l2", "verified", expected_revision=1)
            (task_dir / "impact_report.json").write_text(json.dumps(real_impact), encoding="utf-8")
            state = orchestrator.update_task(run_dir, "task-l2", "verified", expected_revision=1)
            self.assertEqual("verified", state["task_statuses"]["task-l2"])

    @unittest.skipUnless(capability_status()["available"], capability_status().get("reason", "provider unavailable"))
    def test_typescript_variable_initializer_call_belongs_to_function(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "service.ts").write_text("export function helper(): number { return 1; }\n", encoding="utf-8")
            (project / "app.ts").write_text(
                "import * as service from './service';\n"
                "export function entry(): number { const first = service.helper(); return first; }\n",
                encoding="utf-8",
            )
            result, _ = analyze_typescript(project)
            assert result is not None
            names = {item["stable_id"]: item["qualified_name"] for item in result["symbols"]}
            helper_call = next(item for item in result["calls"] if item["callee_name"] == "service.helper")
            self.assertEqual("app.entry", names[helper_call["caller_symbol_id"]])

    @unittest.skipUnless(capability_status()["available"], capability_status().get("reason", "provider unavailable"))
    def test_typescript_callback_parameter_is_critical_dynamic_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.ts").write_text(
                "export function entry(callback: () => number): number { return callback(); }\n",
                encoding="utf-8",
            )
            result, _ = analyze_typescript(project)
            assert result is not None
            edge = next(item for item in result["unresolved_edges"] if item["target"] == "callback")
            call = next(item for item in result["calls"] if item["callee_name"] == "callback")
            self.assertEqual("dynamic-dispatch", call["resolution"])
            self.assertTrue(edge["critical"])

    def test_unknown_python_method_remains_critical(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "def entry(service):\n    size = len([])\n    return service.execute() + size\n",
                encoding="utf-8",
            )
            database, query = self.build_python(project)
            semantic_slice = query.slice(["app.entry"])
            edge = next(item for item in semantic_slice["unresolved_edges"] if item["target"] == "service.execute")
            self.assertTrue(edge["critical"])
            self.assertEqual("needs_expansion", preflight(project, database, semantic_slice, "opaque")["status"])

    def test_expansion_includes_explicit_symbol_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def extra():\n    return 2\n\ndef entry():\n    return 1\n", encoding="utf-8")
            _, query = self.build_python(project)
            semantic_slice = query.slice(["app.entry"])
            expanded = query.expand(semantic_slice, {
                "relation": "callees", "targets": ["app.extra"], "depth": 2, "budget": 100, "reason": "explicit",
            })
            self.assertIn("app.extra", {item["qualified_name"] for item in expanded["included_symbols"]})

    def test_stale_l2_cli_fails_without_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text("def entry():\n    return 1\n", encoding="utf-8")
            self.build_python(project)
            source.write_text("def replacement():\n    return 2\n", encoding="utf-8")
            process = subprocess.run([
                "py", "-3", str(SCRIPT_DIR / "query_codegraph.py"), "--project", str(project),
                "--level", "l2", "find-definition", "--symbol", "app.entry",
            ], text=True, encoding="utf-8", capture_output=True)
            self.assertNotEqual(0, process.returncode)
            self.assertIn("stale", (process.stdout + process.stderr).lower())

    def test_l2_honors_project_include_exclude_and_languages(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "src").mkdir()
            (project / "vendor").mkdir()
            (project / "src" / "app.py").write_text("def entry():\n    return 1\n", encoding="utf-8")
            (project / "vendor" / "hidden.py").write_text("def hidden():\n    return 2\n", encoding="utf-8")
            (project / ".codegraph").mkdir()
            (project / ".codegraph" / "config.json").write_text(json.dumps({
                "level": "l2", "include": ["src"], "exclude": ["vendor"], "languages": ["python"],
            }), encoding="utf-8")
            database = project / ".codegraph" / "l2.sqlite"
            build_l2(project, database, include_typescript=True)
            with connect(database, readonly=True) as connection:
                indexed = [row["path"] for row in connection.execute("SELECT path FROM files ORDER BY path")]
            self.assertEqual(["src/app.py"], indexed)

    def test_prepare_l2_recovers_corrupt_database_or_returns_invalid_without_build(self) -> None:
        task = {
            "schema": "ADworkflo.task_spec.v2", "configured": True, "task_id": "corrupt",
            "task_type": "code", "goal": "Recover graph.", "acceptance_criteria": ["context"],
            "entrypoints": ["app.entry"], "do_not_touch": [], "context_sources": [],
        }
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def entry():\n    return 1\n", encoding="utf-8")
            (project / ".codegraph").mkdir()
            database = project / ".codegraph" / "l2.sqlite"
            database.write_bytes(b"not-sqlite")
            _, _, _, invalid = prepare_context.prepare_l2(project, task, no_build_index=True)
            self.assertEqual("invalid", invalid["status"])
            _, _, _, rebuilt = prepare_context.prepare_l2(project, task, no_build_index=False)
            self.assertEqual("accepted", rebuilt["status"])

    def test_python_redefinition_uses_unique_declarations_and_effective_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "def parse(value):\n    return 1\n\ndef parse(value):\n    return 2\n\ndef entry(value):\n    return parse(value)\n",
                encoding="utf-8",
            )
            provider = analyze_python(project)
            self.assertEqual([], validate_provider_result(provider))
            declarations = [item for item in provider["symbols"] if item["qualified_name"] == "app.parse"]
            self.assertEqual(2, len({item["stable_id"] for item in declarations}))
            effective = [item for item in declarations if item.get("runtime_effective")]
            self.assertEqual(1, len(effective))
            database = project / ".codegraph" / "l2.sqlite"
            build_database(project, database, [provider])
            resolved = GraphQuery(database).resolve_symbol("app.parse")
            self.assertEqual("resolved", resolved["status"])
            self.assertEqual(effective[0]["stable_id"], resolved["symbol"]["stable_id"])


if __name__ == "__main__":
    unittest.main()
