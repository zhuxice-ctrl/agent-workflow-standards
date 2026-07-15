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

    def test_unified_skill_initialization_is_the_only_project_bootstrap(self) -> None:
        self.assertFalse((ROOT / "ADworkflo项目导入包").exists())
        readme = (ROOT / "README.md").read_text(encoding="utf-8-sig")
        self.assertIn("install-adworkflow.ps1", readme)
        self.assertIn("init_adworkflow.py", readme)
        bootstrap_docs = "\n".join(
            path.read_text(encoding="utf-8-sig")
            for path in (
                ROOT / "README.md",
                ROOT / "skills" / "artifact-driven-development" / "SKILL.md",
                ROOT / "docs" / "superpowers" / "plans" / "2026-07-15-l2-codegraph.md",
                ROOT / "docs" / "superpowers" / "specs" / "2026-07-15-l2-codegraph-design.md",
            )
        )
        for legacy_marker in (
            "copy-to-project",
            "Copy and fill templates",
            "import-pack wrappers",
            "installed/imported skill",
        ):
            self.assertNotIn(legacy_marker, bootstrap_docs)

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
