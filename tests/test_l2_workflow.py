from __future__ import annotations

import json
import io
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import orchestrator  # noqa: E402
import prepare_context  # noqa: E402
import query_codegraph  # noqa: E402
from codegraph_post_edit import resolve_baseline  # noqa: E402
from l2_codegraph import query as query_module  # noqa: E402
from l2_codegraph import safety as safety_module  # noqa: E402
from l2_codegraph.safety import post_edit_impact  # noqa: E402


class L2WorkflowTests(unittest.TestCase):
    def test_concurrent_baseline_registration_publishes_one_complete_record(self) -> None:
        worker_source = """
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import prepare_context

preflight_path = Path(sys.argv[2])
revision = sys.argv[3]
ready = Path(sys.argv[4])
release = Path(sys.argv[5])
original_link = prepare_context.os.link

def synchronized_link(source, destination):
    ready.write_text("ready\\n", encoding="utf-8")
    deadline = time.monotonic() + 10.0
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {release}")
        time.sleep(0.01)
    return original_link(source, destination)

prepare_context.os.link = synchronized_link
prepare_context.preserve_l2_baseline(preflight_path, {
    "task_id": "task-l2",
    "status": "accepted",
    "graph_revision": revision,
})
print(json.dumps({"revision": revision}))
"""
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            artifact_root = project / ".adworkflow"
            preflight_path = artifact_root / "context_preflight.json"
            release = project / "release"
            processes: list[subprocess.Popen[str]] = []
            ready_files: list[Path] = []
            try:
                for index, revision in enumerate(("revision-a", "revision-b")):
                    ready = project / f"worker-{index}.ready"
                    ready_files.append(ready)
                    processes.append(subprocess.Popen(
                        [
                            sys.executable, "-c", worker_source, str(SCRIPT_DIR),
                            str(preflight_path), revision, str(ready), str(release),
                        ],
                        text=True,
                        encoding="utf-8",
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    ))

                deadline = time.monotonic() + 10.0
                for ready, process in zip(ready_files, processes):
                    while not ready.exists():
                        if process.poll() is not None:
                            stdout, stderr = process.communicate()
                            self.fail(
                                f"baseline worker exited before link barrier: "
                                f"stdout={stdout!r}, stderr={stderr!r}"
                            )
                        if time.monotonic() >= deadline:
                            self.fail(f"timed out waiting for {ready}")
                        time.sleep(0.01)

                release.write_text("release\n", encoding="utf-8")
                for process in processes:
                    stdout, stderr = process.communicate(timeout=10)
                    self.assertEqual(
                        0, process.returncode,
                        f"baseline worker failed: stdout={stdout!r}, stderr={stderr!r}",
                    )
            finally:
                for process in processes:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()

            baseline = safety_module.baseline_record_path(artifact_root, "task-l2")
            raw_record = baseline.read_text(encoding="utf-8")
            self.assertTrue(raw_record.endswith("\n"))
            record = json.loads(raw_record)
            expected_common = {
                "schema": "ADworkflo.codegraph.baseline.v1",
                "task_id": "task-l2",
                "source": str(preflight_path),
            }
            self.assertIn(record, [
                {**expected_common, "graph_revision": "revision-a"},
                {**expected_common, "graph_revision": "revision-b"},
            ])
            self.assertEqual(
                [], list(baseline.parent.glob(f"{baseline.name}.*.tmp")),
            )

            prepare_context.preserve_l2_baseline(preflight_path, {
                "task_id": "task-l2",
                "status": "accepted",
                "graph_revision": "revision-later",
            })
            self.assertEqual(raw_record, baseline.read_text(encoding="utf-8"))
            self.assertEqual(
                [], list(baseline.parent.glob(f"{baseline.name}.*.tmp")),
            )

    def test_baseline_registration_fsyncs_and_cleans_temp_after_link_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            preflight_path = Path(temp) / ".adworkflow" / "context_preflight.json"
            with patch.object(
                prepare_context.os, "fsync", wraps=prepare_context.os.fsync,
            ) as fsync, patch.object(
                prepare_context.os, "link", side_effect=OSError("link failed"),
            ), self.assertRaisesRegex(OSError, "link failed"):
                prepare_context.preserve_l2_baseline(preflight_path, {
                    "task_id": "task-l2",
                    "status": "accepted",
                    "graph_revision": "revision-a",
                })

            baseline = safety_module.baseline_record_path(
                preflight_path.parent, "task-l2",
            )
            self.assertEqual(1, fsync.call_count)
            self.assertFalse(baseline.exists())
            self.assertEqual(
                [], list(baseline.parent.glob(f"{baseline.name}.*.tmp")),
            )

    def test_baseline_registry_is_immutable_and_preferred_after_reprepare(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            artifact_root = project / ".adworkflow"
            preflight_path = artifact_root / "context_preflight.json"
            first = {
                "task_id": "task-l2", "status": "accepted",
                "graph_revision": "revision-before",
            }
            second = {
                "task_id": "task-l2", "status": "accepted",
                "graph_revision": "revision-after",
            }

            baseline_path = prepare_context.preserve_l2_baseline(
                preflight_path, first,
            )
            prepare_context.preserve_l2_baseline(preflight_path, second)
            prepare_context.write_json(preflight_path, second)

            assert baseline_path is not None
            baseline_record = json.loads(
                baseline_path.read_text(encoding="utf-8"),
            )
            self.assertEqual(
                "revision-before", baseline_record["graph_revision"],
            )
            self.assertEqual(
                project / ".codegraph" / "snapshots" / "revision-before.sqlite",
                resolve_baseline(project, artifact_root, "task-l2", None),
            )

    def test_invalid_immutable_baseline_does_not_fallback_to_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            artifact_root = project / ".adworkflow"
            artifact_root.mkdir()
            preflight = {
                "task_id": "task-l2", "status": "accepted",
                "graph_revision": "mutable-revision",
            }
            (artifact_root / "context_preflight.json").write_text(
                json.dumps(preflight), encoding="utf-8",
            )
            baseline = safety_module.baseline_record_path(
                artifact_root, "task-l2",
            )
            baseline.parent.mkdir()
            baseline.write_text(json.dumps({
                "schema": "ADworkflo.codegraph.baseline.v1",
                "task_id": "another-task",
                "graph_revision": "foreign-revision",
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "another task"):
                resolve_baseline(project, artifact_root, "task-l2", None)
            with self.assertRaisesRegex(ValueError, "another task"):
                orchestrator.resolve_task_baseline_revision(
                    artifact_root, "task-l2", preflight,
                )

    def test_prepare_and_cli_compound_reads_reuse_one_query_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            with patch.object(
                query_module, "connect", wraps=query_module.connect,
            ) as prepare_connect:
                _, _, _, preflight, _ = self.make_run(
                    project,
                    "def target():\n    return 1\n\ndef entry():\n    return target()\n",
                )
            self.assertEqual("accepted", preflight["status"])
            self.assertEqual(
                1,
                prepare_connect.call_count,
                "prepare slice, impact, and preflight must share one read session",
            )

            arguments = [
                "query_codegraph.py", "--project", str(project), "--level", "l2",
                "find-definition", "--symbol", "app.entry",
            ]
            with patch.object(sys, "argv", arguments), patch.object(
                query_module, "connect", wraps=query_module.connect,
            ) as cli_connect, patch.object(
                safety_module, "connect", wraps=safety_module.connect,
            ) as safety_connect, redirect_stdout(io.StringIO()):
                exit_code = query_codegraph.main()
            self.assertEqual(0, exit_code)
            self.assertEqual(1, cli_connect.call_count)
            self.assertEqual(
                0,
                safety_connect.call_count,
                "CLI freshness must consume the GraphQuery pinned connection",
            )

    def make_run(self, project: Path, source: str) -> tuple[Path, dict, dict, dict, dict]:
        (project / "app.py").write_text(source, encoding="utf-8")
        (project / "ARCH.md").write_text("architecture\n", encoding="utf-8")
        (project / "TODO.md").write_text("task\n", encoding="utf-8")
        task_dir = project / ".adworkflow" / "task_specs"
        task_dir.mkdir(parents=True)
        spec = {
            "schema": "ADworkflo.task_spec.v2", "configured": True, "task_id": "task-l2",
            "task_type": "code", "goal": "Change app.entry.", "non_goals": [],
            "acceptance_criteria": ["app.entry is verified."], "risk_level": "medium",
            "execution_mode": "solo_worker", "allowed_actions": ["read", "edit", "test"],
            "required_outputs": ["semantic_slice.json", "context_preflight.json", "impact_report.json"],
            "do_not_touch": [], "entrypoints": ["app.entry"], "context_sources": [],
            "notes": [], "codegraph_level": "l2",
        }
        (task_dir / "task-l2.json").write_text(json.dumps(spec), encoding="utf-8")
        plan = {
            "schema": "ADworkflo.execution_plan.v2", "configured": True, "mvp_id": "mvp-l2",
            "source_docs": ["ARCH.md", "TODO.md"],
            "worker_policy": {"max_parallel_workers": 1, "batching_rule": "dependencies-and-capacity", "handoff_outputs": ["worker_state.json"]},
            "batches": [{"batch_id": "batch-1", "parallel": False, "depends_on": [], "tasks": [{
                "task_id": "task-l2", "module": "protocol", "goal": "Change entry.", "depends_on": [],
                "task_spec_path": ".adworkflow/task_specs/task-l2.json", "expected_outputs": ["impact_report.json"],
            }]}],
            "integration_tasks": [], "open_questions": [],
        }
        plan_path = project / ".adworkflow" / "execution_plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        raw, manifest, semantic_slice, context_preflight = prepare_context.prepare_l2(project, spec)
        run_dir = orchestrator.start_run(project, "run-l2", plan_path)
        target = run_dir / "tasks" / "task-l2"
        for name, value in (
            ("context_raw.json", raw), ("context_manifest.json", manifest),
            ("semantic_slice.json", semantic_slice), ("context_preflight.json", context_preflight),
        ):
            (target / name).write_text(json.dumps(value), encoding="utf-8")
        return run_dir, spec, semantic_slice, context_preflight, manifest

    def test_accepted_context_and_passed_impact_allow_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir, spec, _, preflight, _ = self.make_run(
                project, "def target():\n    return 1\n\ndef entry():\n    return target()\n",
            )
            self.assertEqual("accepted", preflight["status"])
            orchestrator.update_task(run_dir, "task-l2", "in_progress", expected_revision=0)
            task_dir = run_dir / "tasks" / "task-l2"
            database = project / ".codegraph" / "l2.sqlite"
            baseline = project / ".codegraph" / "snapshots" / f"{preflight['graph_revision']}.sqlite"
            (project / "app.py").write_text(
                "def target():\n    return 2\n\ndef entry():\n    return target()\n",
                encoding="utf-8",
            )
            from l2_codegraph.database import build_database
            from l2_codegraph.python_provider import analyze_project
            build_database(project, database, [analyze_project(project)])
            impact = post_edit_impact("task-l2", baseline, database, ["app.py"], ["app.py"])
            (task_dir / "impact_report.json").write_text(json.dumps(impact), encoding="utf-8")
            worker_path = task_dir / "worker_state.json"
            worker = json.loads(worker_path.read_text(encoding="utf-8"))
            worker["changed_files"] = ["app.py"]
            worker_path.write_text(json.dumps(worker), encoding="utf-8")
            verification = {
                "schema": "ADworkflo.verification_result.v1", "task_id": "task-l2", "status": "passed",
                "source_revision": "revision-l2", "commands": [{"command": "unit", "status": "passed", "summary": "ok", "exit_code": 0}],
                "acceptance_criteria_coverage": [{"criterion": spec["acceptance_criteria"][0], "status": "passed", "evidence": ["unit"]}],
                "passed": ["unit"], "failed": [], "not_run_reason": None, "residual_risk": [],
            }
            review = {
                "schema": "ADworkflo.review_findings.v1", "task_id": "task-l2", "status": "approved",
                "reviewer": "reviewer-1", "source_revision": "revision-l2",
                "review_basis": ["task_spec", "patch", "verification_result", "context_preflight", "impact_report"],
                "blocking_findings": [], "non_blocking_findings": [], "suggested_tests": [], "risk_notes": [],
            }
            (task_dir / "verification_result.json").write_text(json.dumps(verification), encoding="utf-8")
            (task_dir / "review_findings.json").write_text(json.dumps(review), encoding="utf-8")
            state = orchestrator.update_task(run_dir, "task-l2", "verified", expected_revision=1)
            self.assertEqual("verified", state["task_statuses"]["task-l2"])

    def test_reprepare_keeps_orchestrator_bound_to_immutable_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir, spec, _, initial_preflight, _ = self.make_run(
                project, "def entry():\n    return 1\n",
            )
            self.assertEqual("accepted", initial_preflight["status"])
            task_dir = run_dir / "tasks" / "task-l2"
            preflight_path = task_dir / "context_preflight.json"
            prepare_context.preserve_l2_baseline(
                preflight_path, initial_preflight,
            )
            initial_revision = initial_preflight["graph_revision"]
            orchestrator.update_task(
                run_dir, "task-l2", "in_progress", expected_revision=0,
            )

            database = project / ".codegraph" / "l2.sqlite"
            (project / "app.py").write_text(
                "def entry():\n    return 2\n", encoding="utf-8",
            )
            from l2_codegraph.database import build_database
            from l2_codegraph.python_provider import analyze_project
            build_database(project, database, [analyze_project(project)])
            raw, manifest, semantic_slice, refreshed_preflight = (
                prepare_context.prepare_l2(project, spec, no_build_index=True)
            )
            self.assertEqual("accepted", refreshed_preflight["status"])
            self.assertNotEqual(
                initial_revision, refreshed_preflight["graph_revision"],
            )
            prepare_context.preserve_l2_baseline(
                preflight_path, refreshed_preflight,
            )
            for name, value in (
                ("context_raw.json", raw),
                ("context_manifest.json", manifest),
                ("semantic_slice.json", semantic_slice),
                ("context_preflight.json", refreshed_preflight),
            ):
                (task_dir / name).write_text(json.dumps(value), encoding="utf-8")
            self.assertEqual(
                initial_revision,
                orchestrator.resolve_task_baseline_revision(
                    task_dir, "task-l2", refreshed_preflight,
                ),
            )

            baseline = (
                project / ".codegraph" / "snapshots"
                / f"{initial_revision}.sqlite"
            )
            impact = post_edit_impact(
                "task-l2", baseline, database, ["app.py"],
                manifest.get("predicted_impact_files", []),
            )
            self.assertEqual("passed", impact["status"])
            self.assertEqual(initial_revision, impact["baseline_revision"])
            (task_dir / "impact_report.json").write_text(
                json.dumps(impact), encoding="utf-8",
            )
            worker_path = task_dir / "worker_state.json"
            worker = json.loads(worker_path.read_text(encoding="utf-8"))
            worker["changed_files"] = ["app.py"]
            worker_path.write_text(json.dumps(worker), encoding="utf-8")
            source_revision = f"l2-{impact['current_revision']}"
            verification = {
                "schema": "ADworkflo.verification_result.v1",
                "task_id": "task-l2",
                "status": "passed",
                "source_revision": source_revision,
                "commands": [{
                    "command": "unit", "status": "passed",
                    "summary": "ok", "exit_code": 0,
                }],
                "acceptance_criteria_coverage": [{
                    "criterion": spec["acceptance_criteria"][0],
                    "status": "passed", "evidence": ["unit"],
                }],
                "passed": ["unit"], "failed": [],
                "not_run_reason": None, "residual_risk": [],
            }
            review = {
                "schema": "ADworkflo.review_findings.v1",
                "task_id": "task-l2", "status": "approved",
                "reviewer": "reviewer-1",
                "source_revision": source_revision,
                "review_basis": ["context_preflight", "impact_report"],
                "blocking_findings": [], "non_blocking_findings": [],
                "suggested_tests": [], "risk_notes": [],
            }
            (task_dir / "verification_result.json").write_text(
                json.dumps(verification), encoding="utf-8",
            )
            (task_dir / "review_findings.json").write_text(
                json.dumps(review), encoding="utf-8",
            )

            state = orchestrator.update_task(
                run_dir, "task-l2", "verified", expected_revision=1,
            )
            self.assertEqual("verified", state["task_statuses"]["task-l2"])

    def test_needs_expansion_blocks_worker_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            run_dir, _, _, preflight, _ = self.make_run(Path(temp), "def entry(callback):\n    return callback()\n")
            self.assertEqual("needs_expansion", preflight["status"])
            with self.assertRaisesRegex(ValueError, "preflight must be accepted"):
                orchestrator.update_task(run_dir, "task-l2", "in_progress", expected_revision=0)

    def test_changed_active_graph_revision_blocks_dispatch_even_when_source_is_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir, _, _, preflight, _ = self.make_run(
                project, "def target():\n    return 1\n\ndef entry():\n    return target()\n",
            )
            database = project / ".codegraph" / "l2.sqlite"
            from l2_codegraph.database import build_database, connect, metadata
            from l2_codegraph.python_provider import analyze_project
            build_database(project, database, [analyze_project(project)], {"changed_provider_config": True})
            with connect(database, readonly=True) as connection:
                active_revision = metadata(connection)["revision"]
            self.assertNotEqual(preflight["graph_revision"], active_revision)
            with self.assertRaisesRegex(ValueError, "active L2 graph revision"):
                orchestrator.update_task(run_dir, "task-l2", "in_progress", expected_revision=0)


if __name__ == "__main__":
    unittest.main()
