from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_core_docs_describe_alignment_layers_and_resume(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")
        self.assertIn("Design Alignment Gate", readme)
        self.assertIn("产品表现层", readme)
        self.assertIn("resume_manifest.json", readme)
        self.assertIn("L2 Semantic Codegraph", readme)
        self.assertIn("context_preflight", readme)

    def test_docs_do_not_promise_unbounded_runtime_workers(self) -> None:
        paths = [
            ROOT / "README.md",
            ROOT / "MULTI_AGENT_ORCHESTRATION.md",
            ROOT / "skills" / "todo-work" / "SKILL.md",
            ROOT / "skills" / "todo-work" / "references" / "execution-plan.md",
            ROOT / "skills" / "artifact-driven-development" / "references" / "multi-agent-orchestration.md",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertNotIn("unbounded-by-design", path.read_text(encoding="utf-8-sig"))

    def test_real_example_exists(self) -> None:
        self.assertTrue((ROOT / "examples" / "small-project-test" / "README.md").exists())

    def test_import_pack_documents_new_commands(self) -> None:
        import_root = next(path for path in ROOT.iterdir() if path.is_dir() and path.name.startswith("ADworkflo"))
        readme = (import_root / "copy-to-project" / "ADWORKFLOW_README.md").read_text(encoding="utf-8-sig")
        self.assertIn("align-design.ps1", readme)
        self.assertIn("validate-adworkflow.ps1", readme)
        self.assertIn("orchestrator.ps1", readme)
        self.assertIn("setup-l2-provider.ps1", readme)
        self.assertIn("codegraph-post-edit.ps1", readme)

    def test_l2_docs_do_not_describe_first_party_l2_as_external_only(self) -> None:
        paths = [
            ROOT / "CODEGRAPH_RETRIEVAL_PROTOCOL.md",
            ROOT / "skills" / "adworkflo" / "SKILL.md",
            ROOT / "skills" / "adworkflo" / "references" / "codegraph-design.md",
        ]
        for path in paths:
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8-sig")
                self.assertNotIn("explicitly configured external L2", text)
                self.assertNotIn("另行接入并声明这些能力", text)


if __name__ == "__main__":
    unittest.main()
