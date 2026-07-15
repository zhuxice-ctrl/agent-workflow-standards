from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from l2_codegraph.model import validate_provider_result  # noqa: E402
from l2_codegraph.python_provider import analyze_project  # noqa: E402


class PythonProviderTests(unittest.TestCase):
    def test_resolves_cross_module_calls_references_and_dynamic_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "pkg").mkdir()
            (project / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (project / "pkg" / "service.py").write_text(
                "def helper(value):\n    return value + 1\n\n"
                "class Service:\n    def run(self, value):\n        return helper(value)\n",
                encoding="utf-8",
            )
            (project / "app.py").write_text(
                "from pkg.service import helper as imported_helper\n"
                "import pkg.service as service\n\n"
                "def entry(value, callback):\n"
                "    first = imported_helper(value)\n"
                "    second = service.helper(first)\n"
                "    return callback(second)\n",
                encoding="utf-8",
            )

            result = analyze_project(project)

            self.assertEqual([], validate_provider_result(result))
            by_qualified = {item["qualified_name"]: item for item in result["symbols"]}
            helper_id = by_qualified["pkg.service.helper"]["stable_id"]
            run_id = by_qualified["pkg.service.Service.run"]["stable_id"]
            entry_id = by_qualified["app.entry"]["stable_id"]
            entry_calls = [item for item in result["calls"] if item["caller_symbol_id"] == entry_id]
            self.assertEqual(2, sum(item["callee_symbol_id"] == helper_id for item in entry_calls))
            self.assertTrue(any(item["callee_name"] == "callback" and not item["callee_symbol_id"] for item in entry_calls))
            self.assertTrue(any(item["caller_symbol_id"] == run_id and item["callee_symbol_id"] == helper_id for item in result["calls"]))
            self.assertTrue(any(item["kind"] == "call" and item["target"] == "callback" for item in result["unresolved_edges"]))
            self.assertTrue(any(item["symbol_id"] == helper_id for item in result["references"]))

    def test_syntax_error_is_an_explicit_critical_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "broken.py").write_text("def broken(:\n", encoding="utf-8")
            result = analyze_project(project)
            self.assertEqual(1, len(result["diagnostics"]))
            self.assertTrue(result["unresolved_edges"][0]["critical"])

    def test_builtin_and_external_import_calls_are_noncritical_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "from pathlib import Path\n\ndef entry(values):\n    return Path(str(len(values)))\n",
                encoding="utf-8",
            )
            result = analyze_project(project)
            calls = [item for item in result["calls"] if item["caller_symbol_id"]]
            self.assertTrue(calls)
            self.assertTrue(all(item["resolution"] in {"builtin", "external-import"} for item in calls))
            self.assertFalse(any(item["critical"] for item in result["unresolved_edges"]))

    def test_imported_project_class_instance_method_is_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "pkg").mkdir()
            (project / "pkg" / "__init__.py").write_text("", encoding="utf-8")
            (project / "pkg" / "repo.py").write_text(
                "class Repo:\n    def save(self, value):\n        return value\n",
                encoding="utf-8",
            )
            (project / "app.py").write_text(
                "from pkg.repo import Repo\n\ndef entry(value):\n    repo = Repo()\n    return repo.save(value)\n",
                encoding="utf-8",
            )
            result = analyze_project(project)
            save = next(item for item in result["symbols"] if item["qualified_name"] == "pkg.repo.Repo.save")
            entry = next(item for item in result["symbols"] if item["qualified_name"] == "app.entry")
            self.assertTrue(any(
                item["caller_symbol_id"] == entry["stable_id"] and item["callee_symbol_id"] == save["stable_id"]
                for item in result["calls"]
            ))

    def test_untyped_method_name_does_not_bypass_dynamic_dispatch_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def entry(value):\n    return value.lower()\n", encoding="utf-8")
            result = analyze_project(project)
            call = next(item for item in result["calls"] if item["callee_name"] == "value.lower")
            self.assertEqual("dynamic-dispatch", call["resolution"])
            edge = next(item for item in result["unresolved_edges"] if item["target"] == "value.lower")
            self.assertTrue(edge["critical"])

    def test_external_inherited_method_is_noncritical_and_project_inheritance_resolves(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "import ast\n\n"
                "class Base:\n    def run(self):\n        return 1\n\n"
                "class Child(Base):\n    def execute(self):\n        return self.run()\n\n"
                "class Visitor(ast.NodeVisitor):\n    def execute(self, tree):\n        return self.visit(tree)\n",
                encoding="utf-8",
            )
            result = analyze_project(project)
            base_run = next(item for item in result["symbols"] if item["qualified_name"] == "app.Base.run")
            child_execute = next(item for item in result["symbols"] if item["qualified_name"] == "app.Child.execute")
            self.assertTrue(any(
                item["caller_symbol_id"] == child_execute["stable_id"] and item["callee_symbol_id"] == base_run["stable_id"]
                for item in result["calls"]
            ))
            visit_edge = next(item for item in result["unresolved_edges"] if item["target"] == "self.visit")
            self.assertEqual("external-inherited-attribute", visit_edge["reason"])
            self.assertFalse(visit_edge["critical"])


if __name__ == "__main__":
    unittest.main()
