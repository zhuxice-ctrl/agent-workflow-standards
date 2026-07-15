from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import orchestrator  # noqa: E402
import validate_adworkflow  # noqa: E402


class OrchestratorTests(unittest.TestCase):
    def test_start_creates_run_and_per_task_namespaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            plan_path = self.write_plan(project, capacity=2)
            run_dir = orchestrator.start_run(project, "run-1", plan_path)
            state = orchestrator.read_json(run_dir / "orchestrator_state.json")
            self.assertEqual(0, state["revision"])
            self.assertEqual("running", state["status"])
            self.assertTrue((run_dir / "tasks" / "task-a" / "task_spec.json").exists())
            self.assertTrue((run_dir / "tasks" / "task-b" / "task_spec.json").exists())
            self.assertEqual([], validate_adworkflow.validate_project(ROOT, project))

    def test_ready_tasks_respect_dependencies_and_capacity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir = orchestrator.start_run(project, "run-1", self.write_plan(project, capacity=1))
            self.assertEqual(["task-a"], orchestrator.ready_task_ids(run_dir))
            orchestrator.update_task(run_dir, "task-a", "in_progress", expected_revision=0)
            self.assertEqual([], orchestrator.ready_task_ids(run_dir))
            self.write_passing_evidence(run_dir, "task-a")
            orchestrator.update_task(run_dir, "task-a", "verified", expected_revision=1)
            self.assertEqual(["task-b"], orchestrator.ready_task_ids(run_dir))

    def test_revision_guard_rejects_stale_main_window(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir = orchestrator.start_run(project, "run-1", self.write_plan(project))
            orchestrator.update_task(run_dir, "task-a", "in_progress", expected_revision=0)
            with self.assertRaisesRegex(ValueError, "revision mismatch"):
                orchestrator.update_task(run_dir, "task-a", "verified", expected_revision=0)

    def test_update_rejects_dependency_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir = orchestrator.start_run(project, "run-1", self.write_plan(project))
            with self.assertRaisesRegex(ValueError, "dependencies are not verified"):
                orchestrator.update_task(run_dir, "task-b", "in_progress", expected_revision=0)

    def test_verified_transition_requires_acceptance_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir = orchestrator.start_run(project, "run-1", self.write_plan(project))
            orchestrator.update_task(run_dir, "task-a", "in_progress", expected_revision=0)
            with self.assertRaisesRegex(ValueError, "verification status must be passed"):
                orchestrator.update_task(run_dir, "task-a", "verified", expected_revision=1)

    def test_medium_risk_verified_transition_requires_independent_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir = orchestrator.start_run(project, "run-1", self.write_plan(project))
            spec_path = run_dir / "tasks" / "task-a" / "task_spec.json"
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            spec["risk_level"] = "medium"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")
            orchestrator.update_task(run_dir, "task-a", "in_progress", expected_revision=0)
            self.write_passing_evidence(run_dir, "task-a")
            with self.assertRaisesRegex(ValueError, "independent review must be approved"):
                orchestrator.update_task(run_dir, "task-a", "verified", expected_revision=1)
            self.write_passing_evidence(run_dir, "task-a", review=True)
            state = orchestrator.update_task(run_dir, "task-a", "verified", expected_revision=1)
            self.assertIn("task-a", state["completed_tasks"])

    def test_changed_source_documents_pause_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir = orchestrator.start_run(project, "run-1", self.write_plan(project))
            (project / "ARCH.md").write_text("changed architecture\n", encoding="utf-8")
            self.assertEqual([], orchestrator.ready_task_ids(run_dir))
            resume = orchestrator.build_resume_manifest(run_dir)
            self.assertIn("ARCH.md", resume["source_drift"])

    def test_run_id_cannot_escape_project(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            plan = self.write_plan(project)
            with self.assertRaisesRegex(ValueError, "run_id"):
                orchestrator.start_run(project, "../escape", plan)

    def test_resume_manifest_starts_with_control_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            run_dir = orchestrator.start_run(project, "run-1", self.write_plan(project))
            orchestrator.update_task(run_dir, "task-a", "in_progress", expected_revision=0)
            resume = orchestrator.build_resume_manifest(run_dir)
            self.assertEqual("orchestrator_state.json", resume["read_order"][0])
            self.assertIn("tasks/task-a/task_spec.json", resume["active_task_artifacts"])
            self.assertEqual(1, resume["orchestrator_revision"])

    def write_plan(self, project: Path, capacity: int = 2) -> Path:
        (project / "ARCH.md").write_text("architecture\n", encoding="utf-8")
        (project / "TODO.md").write_text("tasks\n", encoding="utf-8")
        task_specs = project / ".adworkflow" / "task_specs"
        task_specs.mkdir(parents=True)
        for task_id in ("task-a", "task-b"):
            spec = {
                "schema": "ADworkflo.task_spec.v2", "configured": True, "task_id": task_id,
                "task_type": "code", "goal": f"Implement {task_id}.", "non_goals": [],
                "acceptance_criteria": [f"{task_id} is verified."], "risk_level": "low",
                "execution_mode": "solo_worker", "allowed_actions": ["read", "edit", "test"],
                "required_outputs": ["worker_state.json", "verification_result.json"],
                "do_not_touch": [], "entrypoints": [], "context_sources": [], "notes": [],
            }
            (task_specs / f"{task_id}.json").write_text(json.dumps(spec), encoding="utf-8")
        plan = {
            "schema": "ADworkflo.execution_plan.v2", "configured": True, "mvp_id": "mvp-1",
            "source_docs": ["ARCH.md", "TODO.md"],
            "worker_policy": {"max_parallel_workers": capacity, "batching_rule": "dependencies-and-capacity", "handoff_outputs": ["worker_state.json"]},
            "batches": [{"batch_id": "batch-1", "parallel": True, "depends_on": [], "tasks": [
                {"task_id": "task-a", "module": "presentation", "goal": "Implement A.", "depends_on": [], "task_spec_path": ".adworkflow/task_specs/task-a.json", "expected_outputs": ["worker_state.json"]},
                {"task_id": "task-b", "module": "protocol", "goal": "Implement B.", "depends_on": ["task-a"], "task_spec_path": ".adworkflow/task_specs/task-b.json", "expected_outputs": ["worker_state.json"]}
            ]}],
            "integration_tasks": [], "open_questions": [],
        }
        path = project / ".adworkflow" / "execution_plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    @staticmethod
    def write_passing_evidence(run_dir: Path, task_id: str, review: bool = False) -> None:
        task_dir = run_dir / "tasks" / task_id
        spec = json.loads((task_dir / "task_spec.json").read_text(encoding="utf-8"))
        verification = {
            "schema": "ADworkflo.verification_result.v1", "task_id": task_id, "status": "passed",
            "source_revision": "patch-1", "commands": [{"command": "unit-test", "status": "passed", "summary": "passed", "exit_code": 0}],
            "acceptance_criteria_coverage": [{"criterion": item, "status": "passed", "evidence": ["unit-test"]} for item in spec["acceptance_criteria"]],
            "passed": ["unit-test"], "failed": [], "not_run_reason": None, "residual_risk": [],
        }
        (task_dir / "verification_result.json").write_text(json.dumps(verification), encoding="utf-8")
        if review:
            findings = {
                "schema": "ADworkflo.review_findings.v1", "task_id": task_id, "status": "approved",
                "reviewer": "independent-reviewer", "source_revision": "patch-1",
                "review_basis": ["task_spec", "patch", "verification_result"],
                "blocking_findings": [], "non_blocking_findings": [], "suggested_tests": [], "risk_notes": [],
            }
            (task_dir / "review_findings.json").write_text(json.dumps(findings), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
