#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from l2_codegraph.query import GraphQuery
from l2_codegraph.safety import preflight


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def apply_expansion(project: Path, task_root: Path, database: Path | None = None) -> dict[str, Any]:
    project = project.resolve()
    task_root = task_root.resolve()
    database = database.resolve() if database else project / ".codegraph" / "l2.sqlite"
    slice_path = task_root / "semantic_slice.json"
    request_path = task_root / "context_expansion_request.json"
    preflight_path = task_root / "context_preflight.json"
    worker_path = task_root / "worker_state.json"
    manifest_path = task_root / "context_manifest.json"
    request = read_json(request_path)
    if request.get("status") != "pending":
        raise ValueError("context expansion request status must be pending")
    semantic_slice = read_json(slice_path)
    if request.get("source_graph_revision") != semantic_slice.get("graph_revision"):
        raise ValueError("context expansion request revision does not match semantic slice")
    query = GraphQuery(database)
    expanded = query.expand(semantic_slice, request)
    task_id = request["task_id"]
    context_preflight = preflight(project, database, expanded, task_id)
    request["status"] = "applied"
    request["applied_slice_revision"] = expanded.get("graph_revision")
    worker = read_json(worker_path)
    history = worker.setdefault("context_expansion_history", [])
    history.append({
        "relation": request["relation"], "targets": request.get("targets", []),
        "depth": request["depth"], "budget": request["budget"], "reason": request.get("reason"),
        "requested_by": request.get("requested_by"), "graph_revision": expanded.get("graph_revision"),
        "preflight_status": context_preflight["status"],
    })
    worker["revision"] = int(worker.get("revision", 0)) + 1
    manifest = read_json(manifest_path) if manifest_path.exists() else None
    if manifest is not None:
        manifest["preflight_status"] = context_preflight["status"]
        manifest["context_confidence"] = expanded.get("confidence", 0)
        manifest["graph_revision"] = expanded.get("graph_revision")
        manifest["read_first"] = list(dict.fromkeys([
            *expanded.get("included_files", []), *expanded.get("likely_tests", []),
            *manifest.get("read_first", []),
        ]))
        manifest["relevant_symbols"] = [
            f"{item['qualified_name']} ({item['file']}:{item['start_line']})"
            for item in expanded.get("included_symbols", [])
        ]
        manifest["open_questions"] = context_preflight.get("required_actions", [])
        manifest["predicted_impact_files"] = expanded.get("predicted_impact_files", [])
    write_json(slice_path, expanded)
    write_json(preflight_path, context_preflight)
    write_json(request_path, request)
    write_json(worker_path, worker)
    if manifest is not None:
        write_json(manifest_path, manifest)
    return {"request": request, "preflight": context_preflight, "worker_revision": worker["revision"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply an L2 context expansion request and update task artifacts.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--task-root", default=None)
    parser.add_argument("--database", default=None)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    task_root = Path(args.task_root).resolve() if args.task_root else project / ".adworkflow"
    database = Path(args.database).resolve() if args.database else None
    result = apply_expansion(project, task_root, database)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["preflight"]["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
