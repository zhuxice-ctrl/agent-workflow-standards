from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from build_codegraph_l2 import build  # noqa: E402
from l2_codegraph.query import GraphQuery  # noqa: E402
from l2_codegraph.safety import preflight  # noqa: E402


MODULE_COUNT = 400
FUNCTIONS_PER_MODULE = 10
TEST_MODULE_COUNT = 4
ENTRY_MODULE = 390
SLICE_DEPTH = ((MODULE_COUNT - ENTRY_MODULE) * FUNCTIONS_PER_MODULE) - 1
SLICE_BUDGET = (MODULE_COUNT - ENTRY_MODULE) * FUNCTIONS_PER_MODULE + 20


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def generate_large_fixture(project: Path) -> None:
    for module_index in range(MODULE_COUNT):
        lines = [f"MODULE_INDEX = {module_index}", ""]
        if module_index + 1 < MODULE_COUNT:
            lines.extend([
                f"from module_{module_index + 1:04d} import function_0 as next_module_function",
                "",
            ])
        for function_index in range(FUNCTIONS_PER_MODULE):
            lines.append(f"def function_{function_index}(value):")
            if function_index + 1 < FUNCTIONS_PER_MODULE:
                lines.append(f"    return function_{function_index + 1}(value)")
            elif module_index + 1 < MODULE_COUNT:
                lines.append("    return next_module_function(value)")
            else:
                lines.append("    return value")
            lines.append("")
        (project / f"module_{module_index:04d}.py").write_text(
            "\n".join(lines), encoding="utf-8",
        )

    tests_dir = project / "tests"
    tests_dir.mkdir()
    for test_index in range(TEST_MODULE_COUNT):
        (tests_dir / f"test_large_fixture_{test_index:02d}.py").write_text(
            f"from module_{ENTRY_MODULE:04d} import function_0\n\n"
            f"def test_entry_{test_index:02d}():\n"
            f"    assert function_0({test_index}) == {test_index}\n",
            encoding="utf-8",
        )


class L2PerformanceTests(unittest.TestCase):
    def test_large_python_graph_stays_stable_and_within_budget(self) -> None:
        build_limit = float(os.getenv("ADWORKFLO_PERF_BUILD_MAX_SECONDS", "30"))
        slice_limit = float(os.getenv("ADWORKFLO_PERF_SLICE_MAX_SECONDS", "3"))
        preflight_limit = float(os.getenv("ADWORKFLO_PERF_PREFLIGHT_MAX_SECONDS", "3"))
        size_limit = int(os.getenv("ADWORKFLO_PERF_DATABASE_MAX_MIB", "64")) * 1024 * 1024

        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            generate_large_fixture(project)
            database = project / ".codegraph" / "l2.sqlite"
            entrypoint = f"module_{ENTRY_MODULE:04d}.function_0"

            started = time.perf_counter()
            first_build = build(project, database, include_typescript=False)
            first_build_seconds = time.perf_counter() - started

            started = time.perf_counter()
            first_slice = GraphQuery(database).slice(
                [entrypoint], depth=SLICE_DEPTH, budget=SLICE_BUDGET,
            )
            first_slice_seconds = time.perf_counter() - started

            started = time.perf_counter()
            second_build = build(project, database, include_typescript=False)
            second_build_seconds = time.perf_counter() - started

            started = time.perf_counter()
            second_slice = GraphQuery(database).slice(
                [entrypoint], depth=SLICE_DEPTH, budget=SLICE_BUDGET,
            )
            second_slice_seconds = time.perf_counter() - started

            started = time.perf_counter()
            gate = preflight(project, database, second_slice, "l2-performance")
            preflight_seconds = time.perf_counter() - started
            database_bytes = database.stat().st_size

            metrics = {
                "build_first_seconds": round(first_build_seconds, 6),
                "build_second_seconds": round(second_build_seconds, 6),
                "database_bytes": database_bytes,
                "database_mib": round(database_bytes / (1024 * 1024), 3),
                "file_count": second_build["file_count"],
                "module_count": MODULE_COUNT,
                "preflight_seconds": round(preflight_seconds, 6),
                "revision": second_build["revision"],
                "slice_first_seconds": round(first_slice_seconds, 6),
                "slice_second_seconds": round(second_slice_seconds, 6),
                "slice_symbol_count": len(second_slice["included_symbols"]),
                "symbol_count": second_build["symbol_count"],
            }
            print(json.dumps(metrics, sort_keys=True, separators=(",", ":")), flush=True)

            self.assertGreaterEqual(second_build["file_count"], MODULE_COUNT)
            self.assertGreaterEqual(
                second_build["symbol_count"], MODULE_COUNT * FUNCTIONS_PER_MODULE,
            )
            self.assertEqual(first_build["revision"], second_build["revision"])
            self.assertEqual(canonical_json(first_slice), canonical_json(second_slice))
            self.assertEqual("ready", second_slice["status"])
            self.assertFalse(second_slice["truncated"])
            self.assertEqual(
                (MODULE_COUNT - ENTRY_MODULE) * FUNCTIONS_PER_MODULE,
                len(second_slice["included_symbols"]),
            )
            self.assertEqual("accepted", gate["status"], gate)
            self.assertLess(first_build_seconds, build_limit, metrics)
            self.assertLess(second_build_seconds, build_limit, metrics)
            self.assertLess(first_slice_seconds, slice_limit, metrics)
            self.assertLess(second_slice_seconds, slice_limit, metrics)
            self.assertLess(preflight_seconds, preflight_limit, metrics)
            self.assertLess(database_bytes, size_limit, metrics)


if __name__ == "__main__":
    unittest.main()
