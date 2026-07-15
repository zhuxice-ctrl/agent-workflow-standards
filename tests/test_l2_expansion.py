from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from apply_context_expansion import apply_expansion  # noqa: E402
from l2_codegraph.database import build_database  # noqa: E402
from l2_codegraph.python_provider import analyze_project  # noqa: E402
from l2_codegraph.query import GraphQuery  # noqa: E402


class L2ExpansionTests(unittest.TestCase):
    def test_applies_request_to_slice_preflight_and_worker_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def target():\n    return 1\n\ndef entry():\n    return target()\n", encoding="utf-8")
            database = project / ".codegraph" / "l2.sqlite"
            build_database(project, database, [analyze_project(project)])
            task_root = project / ".adworkflow"
            task_root.mkdir()
            initial = GraphQuery(database).slice(["app.entry"], depth=0)
            request = {
                "schema": "ADworkflo.context_expansion_request.v1", "task_id": "task-1", "status": "pending",
                "relation": "callees", "targets": ["app.entry"], "depth": 2, "budget": 100,
                "reason": "Resolve depth boundary", "requested_by": "worker-1",
                "source_graph_revision": initial["graph_revision"], "applied_slice_revision": None,
            }
            worker = {
                "schema": "ADworkflo.worker_state.v1", "task_id": "task-1", "status": "in_progress", "revision": 0,
                "done": [], "changed_files": [], "current_problem": None, "next_action": None,
                "must_keep_context": [], "discarded_context": [], "remaining_risks": [],
                "clarification_events": [], "timeout_fallbacks": [], "context_expansion_history": [],
            }
            (task_root / "semantic_slice.json").write_text(json.dumps(initial), encoding="utf-8")
            (task_root / "context_expansion_request.json").write_text(json.dumps(request), encoding="utf-8")
            (task_root / "worker_state.json").write_text(json.dumps(worker), encoding="utf-8")
            result = apply_expansion(project, task_root, database)
            self.assertEqual("accepted", result["preflight"]["status"])
            updated_worker = json.loads((task_root / "worker_state.json").read_text(encoding="utf-8"))
            self.assertEqual(1, updated_worker["revision"])
            self.assertEqual("accepted", updated_worker["context_expansion_history"][0]["preflight_status"])
            updated_request = json.loads((task_root / "context_expansion_request.json").read_text(encoding="utf-8"))
            self.assertEqual("applied", updated_request["status"])


if __name__ == "__main__":
    unittest.main()
