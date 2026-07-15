from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import analyze_project_plan  # noqa: E402
import design_alignment  # noqa: E402


class ProductDocumentTests(unittest.TestCase):
    def test_large_product_plan_selects_l2_and_recommends_safety_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "PRD.md").write_text(
                "# PRD\nFR-001 frontend backend API database auth agent workflow webhook payment android docker e2e with 40 modules.\n",
                encoding="utf-8",
            )
            manifest = analyze_project_plan.build_architecture_manifest(project)
            self.assertEqual("large", manifest["project_size"])
            self.assertIn("l2-semantic-codegraph", manifest["context_strategy"])
            self.assertIn("context_preflight.json", manifest["recommended_artifacts"])

    def test_ascii_signal_matching_uses_token_boundaries(self) -> None:
        text = "storage mapping decision"
        self.assertEqual([], analyze_project_plan.find_patterns(text, ["rag", "app", "ci"]))

    def test_arch_module_planning_is_the_source_of_planned_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "PRD.md").write_text("# PRD\n\nFR-001 Export a report.\n", encoding="utf-8")
            (project / "ARCH.md").write_text(
                "# ARCH\n\n## Module Planning\n\n- mapping\n- storage\n\n## Decision\n\nUse a decision table.\n",
                encoding="utf-8",
            )
            manifest = analyze_project_plan.build_architecture_manifest(project)

        self.assertEqual(["mapping", "storage"], manifest["planned_modules"])
        self.assertFalse(manifest["detected_signals"]["agent_rag_tools"]["detected"])
        self.assertFalse(manifest["detected_signals"]["multi_platform"]["detected"])
        self.assertFalse(manifest["detected_signals"]["deployment_observability"]["detected"])

    def test_unrelated_root_markdown_is_not_analyzed_implicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "PRD.md").write_text("FR-001 Export.\n", encoding="utf-8")
            (project / "ARCH.md").write_text("FR-001 Export architecture.\n", encoding="utf-8")
            (project / "MEETING_NOTES.md").write_text("app rag ci payment deletion\n", encoding="utf-8")
            manifest = analyze_project_plan.build_architecture_manifest(project)
            analyzed = {item["path"] for item in manifest["analysis_basis"]}
            self.assertNotIn("MEETING_NOTES.md", analyzed)

    def test_alignment_gate_blocks_missing_requirement_and_semantic_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "PRD.md").write_text(
                "# PRD\n\n## FR-001 Export\nExport reports.\n\n## NFR-001 Retention\nKeep data for 30 days.\n",
                encoding="utf-8",
            )
            (project / "ARCH.md").write_text(
                "# ARCH\n\n## Requirement Mapping\n\n- FR-001: export service\n",
                encoding="utf-8",
            )
            report = design_alignment.build_report(project)
            missing = [item["requirement_id"] for item in report["requirements"] if item["status"] == "missing"]
            self.assertEqual(["NFR-001"], missing)
            self.assertEqual("blocked", report["gate_status"])

            (project / "ARCH.md").write_text(
                "# ARCH\n\n## Requirement Mapping\n\n- FR-001: export service\n- NFR-001: retention policy\n",
                encoding="utf-8",
            )
            report = design_alignment.build_report(project)
            self.assertEqual("blocked", report["gate_status"])
            self.assertIn("semantic review is pending", report["blocking_reasons"])

            approved = design_alignment.approve_report(report, "independent-design-reviewer", ["PRD and ARCH agree."])
            self.assertEqual("passed", approved["gate_status"])
            self.assertEqual("approved", approved["semantic_review"]["status"])

    def test_alignment_cli_writes_schema_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "PRD.md").write_text("FR-001 Export reports.\n", encoding="utf-8")
            (project / "ARCH.md").write_text("FR-001 is implemented by export service.\n", encoding="utf-8")
            report = design_alignment.build_report(project)
            output = project / ".adworkflow" / "design_alignment_report.json"
            design_alignment.write_json(output, report)
            loaded = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("ADworkflo.design_alignment_report.v1", loaded["schema"])

    def test_semantic_approval_rejects_changed_source_documents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "PRD.md").write_text("FR-001 Export reports.\n", encoding="utf-8")
            (project / "ARCH.md").write_text("FR-001 uses export service.\n", encoding="utf-8")
            report = design_alignment.build_report(project)
            (project / "ARCH.md").write_text("FR-001 uses a changed service.\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source documents changed"):
                design_alignment.assert_report_fresh(project, report)

    def test_alignment_requires_stable_prd_requirement_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "PRD.md").write_text("Users can export reports.\n", encoding="utf-8")
            (project / "ARCH.md").write_text("The export service handles reports.\n", encoding="utf-8")
            report = design_alignment.build_report(project)
            self.assertIn("PRD contains no stable requirement IDs", report["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
