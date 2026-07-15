from __future__ import annotations

import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import layered_development  # noqa: E402
import validate_adworkflow  # noqa: E402


class LayerPlanTests(unittest.TestCase):
    def test_layered_plan_contains_three_distinct_four_question_contracts(self) -> None:
        plan = layered_development.new_layered_plan()
        self.assertEqual({"presentation", "protocol", "data"}, {item["layer_id"] for item in plan["layers"]})
        self.assertEqual([], validate_adworkflow.validate_layer_plan(plan))
        for layer in plan["layers"]:
            self.assertIn("final_goal", layer)
            self.assertIn("scope", layer)
            self.assertIn("non_completion_conditions", layer)
            self.assertIn("exploration_and_audit", layer)

    def test_layer_requires_independent_auditor_before_completion(self) -> None:
        plan = layered_development.new_layered_plan()
        layer = plan["layers"][0]
        layer["status"] = "complete"
        layer["implementation_owner"] = "worker-a"
        layer["exploration_and_audit"]["implementation_owner"] = "worker-a"
        layer["exploration_and_audit"]["independent_auditor"] = "worker-a"
        errors = validate_adworkflow.validate_layer_plan(plan)
        self.assertIn("independent auditor must differ from implementation owner", "\n".join(errors))

    def test_not_applicable_layer_requires_reason(self) -> None:
        plan = layered_development.new_layered_plan()
        plan["layers"][2]["status"] = "not_applicable"
        errors = validate_adworkflow.validate_layer_plan(plan)
        self.assertIn("not_applicable_reason", "\n".join(errors))

    def test_interface_contract_requires_compatibility_and_verification(self) -> None:
        schema = layered_development.load_schema(ROOT, "interface_contracts")
        invalid = {"schema": "ADworkflo.interface_contracts.v1", "configured": True, "contracts": [{"contract_id": "api-1"}]}
        errors = list(Draft202012Validator(schema).iter_errors(invalid))
        self.assertTrue(errors)


if __name__ == "__main__":
    unittest.main()
