from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import sync_templates  # noqa: E402
import validate_adworkflow  # noqa: E402


class ContractTests(unittest.TestCase):
    def test_every_canonical_json_template_has_a_schema_and_validates(self) -> None:
        template_dir = ROOT / "skills" / "adworkflo" / "templates"
        contract_names = {
            "architecture_manifest",
            "artifact_registry",
            "context_manifest",
            "context_expansion_request",
            "context_preflight",
            "context_raw",
            "design_alignment_report",
            "execution_plan",
            "interface_contracts",
            "impact_report",
            "layer_plan",
            "orchestrator_state",
            "resume_manifest",
            "review_findings",
            "semantic_slice",
            "task_spec",
            "verification_result",
            "worker_state",
        }

        for name in sorted(contract_names):
            with self.subTest(name=name):
                template = json.loads((template_dir / f"{name}.json").read_text(encoding="utf-8-sig"))
                schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8-sig"))
                Draft202012Validator(schema).validate(template)

    def test_mirrored_templates_match_canonical_source(self) -> None:
        self.assertEqual([], sync_templates.find_drift(ROOT))

    def test_execution_plan_rejects_missing_dependency(self) -> None:
        plan = self.valid_plan()
        plan["batches"][0]["tasks"][0]["depends_on"] = ["missing-task"]
        errors = validate_adworkflow.validate_execution_plan(plan)
        self.assertIn("unknown dependency missing-task", "\n".join(errors))

    def test_execution_plan_rejects_dependency_cycle(self) -> None:
        plan = self.valid_plan()
        plan["batches"][0]["tasks"].append(
            {
                "task_id": "task-b",
                "module": "protocol",
                "goal": "Build protocol contract.",
                "depends_on": ["task-a"],
                "task_spec_path": ".adworkflow/task_specs/task-b.json",
                "expected_outputs": ["worker_state.json", "verification_result.json"],
            }
        )
        plan["batches"][0]["tasks"][0]["depends_on"] = ["task-b"]
        errors = validate_adworkflow.validate_execution_plan(plan)
        self.assertIn("dependency cycle", "\n".join(errors))

    @staticmethod
    def valid_plan() -> dict:
        return {
            "schema": "ADworkflo.execution_plan.v2",
            "configured": True,
            "mvp_id": "mvp-1",
            "source_docs": ["ARCH.md", "TODO.md"],
            "worker_policy": {
                "max_parallel_workers": 2,
                "batching_rule": "dependencies-and-capacity",
                "handoff_outputs": ["worker_state.json", "verification_result.json"],
            },
            "batches": [
                {
                    "batch_id": "batch-1",
                    "parallel": True,
                    "depends_on": [],
                    "tasks": [
                        {
                            "task_id": "task-a",
                            "module": "presentation",
                            "goal": "Build presentation contract.",
                            "depends_on": [],
                            "task_spec_path": ".adworkflow/task_specs/task-a.json",
                            "expected_outputs": ["worker_state.json", "verification_result.json"],
                        }
                    ],
                }
            ],
            "integration_tasks": [],
            "open_questions": [],
        }


if __name__ == "__main__":
    unittest.main()
