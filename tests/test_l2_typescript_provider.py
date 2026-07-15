from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from l2_codegraph.model import validate_provider_result  # noqa: E402
from l2_codegraph.typescript_provider import analyze_project, capability_status  # noqa: E402


TS_STATUS = capability_status()


@unittest.skipUnless(TS_STATUS["available"], TS_STATUS.get("reason", "provider unavailable"))
class TypeScriptProviderTests(unittest.TestCase):
    def test_typechecker_resolves_aliases_calls_and_dynamic_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "service.ts").write_text(
                "export function helper(value: number): number { return value + 1; }\n"
                "export class Service { run(value: number): number { return helper(value); } }\n",
                encoding="utf-8",
            )
            (project / "app.ts").write_text(
                "import { helper as importedHelper } from './service';\n"
                "export function entry(value: number, callback: (n: number) => number): number {\n"
                "  return callback(importedHelper(value));\n}\n",
                encoding="utf-8",
            )
            result, status = analyze_project(project)
            self.assertTrue(status["available"], status)
            assert result is not None
            self.assertEqual([], validate_provider_result(result))
            helper = next(item for item in result["symbols"] if item["qualified_name"] == "service.helper")
            entry = next(item for item in result["symbols"] if item["qualified_name"] == "app.entry")
            entry_calls = [item for item in result["calls"] if item["caller_symbol_id"] == entry["stable_id"]]
            self.assertTrue(any(item["callee_symbol_id"] == helper["stable_id"] for item in entry_calls))
            self.assertTrue(any(item["callee_name"] == "callback" and not item["callee_symbol_id"] for item in entry_calls))
            self.assertTrue(any(item["target"] == "callback" for item in result["unresolved_edges"]))
            self.assertTrue(any(item["target_file"] == "service.ts" for item in result["imports"]))


if __name__ == "__main__":
    unittest.main()
