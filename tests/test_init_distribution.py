from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "skills" / "adworkflo" / "scripts" / "init_adworkflow.py"
VALIDATE = ROOT / "skills" / "adworkflo" / "scripts" / "validate_adworkflow.py"


class InitDistributionTests(unittest.TestCase):
    def run_init(self, project: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["py", "-3", str(INIT), "--project", str(project), *args],
            check=True,
            text=True,
            encoding="utf-8",
            capture_output=True,
        )

    def test_init_creates_root_agents_only_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.run_init(project, "--skip-doc-analysis")
            agents = project / "AGENTS.md"
            self.assertTrue(agents.exists())
            agents.write_text("USER OWNED\n", encoding="utf-8")
            self.run_init(project, "--skip-doc-analysis", "--force")
            self.assertEqual("USER OWNED\n", agents.read_text(encoding="utf-8"))

    def test_force_preserves_user_config_unless_explicitly_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.run_init(project, "--skip-doc-analysis")
            permissions = project / ".adworkflow" / "permissions.md"
            permissions.write_text("CUSTOM PERMISSIONS\n", encoding="utf-8")
            self.run_init(project, "--skip-doc-analysis", "--force")
            self.assertEqual("CUSTOM PERMISSIONS\n", permissions.read_text(encoding="utf-8"))
            self.run_init(project, "--skip-doc-analysis", "--force-user-config")
            self.assertIn("ADworkflo Permissions", permissions.read_text(encoding="utf-8"))

    def test_init_creates_new_control_and_layer_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.run_init(project, "--skip-doc-analysis")
            expected = {
                "design_alignment_report.json",
                "layer_plan.json",
                "interface_contracts.json",
                "orchestrator_state.json",
                "resume_manifest.json",
                "artifact_registry.json",
                "semantic_slice.json",
                "context_preflight.json",
                "context_expansion_request.json",
                "impact_report.json",
            }
            actual = {path.name for path in (project / ".adworkflow").glob("*.json")}
            self.assertLessEqual(expected, actual)
            result = subprocess.run(
                ["py", "-3", str(VALIDATE), "--project", str(project), "--repo", str(ROOT)],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_installed_skill_contains_schemas_and_validates_without_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            codex_home = base / "codex-home"
            project = base / "project"
            project.mkdir()
            install = subprocess.run(
                ["powershell", "-NoProfile", "-File", str(ROOT / "install-adworkflow.ps1"), "-CodexHome", str(codex_home)],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(0, install.returncode, install.stdout + install.stderr)
            installed = codex_home / "skills" / "adworkflo"
            self.assertTrue((installed / "schemas" / "task_spec.schema.json").exists())
            self.assertTrue((installed / "providers" / "typescript" / "package.json").exists())
            self.assertTrue((installed / "providers" / "typescript" / "package-lock.json").exists())
            self.assertFalse((installed / "providers" / "typescript" / "node_modules").exists())
            subprocess.run(
                ["py", "-3", str(installed / "scripts" / "init_adworkflow.py"), "--project", str(project), "--skip-doc-analysis"],
                check=True,
                capture_output=True,
            )
            validate = subprocess.run(
                ["py", "-3", str(installed / "scripts" / "validate_adworkflow.py"), "--project", str(project)],
                text=True,
                encoding="utf-8",
                capture_output=True,
            )
            self.assertEqual(0, validate.returncode, validate.stdout + validate.stderr)


if __name__ == "__main__":
    unittest.main()
