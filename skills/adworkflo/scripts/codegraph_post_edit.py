#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from build_codegraph_l2 import build as build_l2
from l2_codegraph.safety import post_edit_impact, resolve_baseline_revision


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}


def resolve_baseline(
    project: Path,
    artifact_root: Path,
    task_id: str,
    explicit: str | None,
) -> Path:
    if explicit:
        return Path(explicit).resolve()
    preflight = read_json(artifact_root / "context_preflight.json")
    revision = resolve_baseline_revision(
        artifact_root, task_id, preflight.get("graph_revision"),
    )
    return project / ".codegraph" / "snapshots" / f"{revision}.sqlite"


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare baseline and post-edit L2 graphs.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--baseline", default=None)
    parser.add_argument("--current", default=None)
    parser.add_argument("--declared-file", action="append", default=[])
    parser.add_argument("--predicted-file", action="append", default=[])
    parser.add_argument("--out", default=None)
    parser.add_argument("--no-rebuild", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    current = Path(args.current).resolve() if args.current else project / ".codegraph" / "l2.sqlite"
    out = Path(args.out).resolve() if args.out else project / ".adworkflow" / "impact_report.json"
    artifact_root = out.parent
    baseline = resolve_baseline(
        project, artifact_root, args.task_id, args.baseline,
    )
    if not baseline.exists():
        raise SystemExit(f"Baseline L2 snapshot not found: {baseline}")
    try:
        if not args.no_rebuild:
            build_l2(
                project, current, include_typescript=True, require_typescript=False,
            )
        worker = read_json(artifact_root / "worker_state.json")
        manifest = read_json(artifact_root / "context_manifest.json")
        declared_files = args.declared_file or worker.get("changed_files", [])
        predicted_files = args.predicted_file or manifest.get("predicted_impact_files", [])
        result = post_edit_impact(
            args.task_id, baseline, current, declared_files, predicted_files,
        )
    except (ValueError, RuntimeError, OSError, sqlite3.DatabaseError) as error:
        from l2_codegraph.database import graph_error_payload
        payload = graph_error_payload(error)
        if payload is not None:
            print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
            return 3 if payload["retryable"] else 2
        raise SystemExit(f"L2 post-edit impact failed: {error}") from None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
