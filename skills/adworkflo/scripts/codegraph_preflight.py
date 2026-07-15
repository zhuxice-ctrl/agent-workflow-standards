#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from l2_codegraph.safety import preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate an L2 semantic slice before Agent implementation.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--slice", default=None)
    parser.add_argument("--database", default=None)
    parser.add_argument("--out", default=None)
    parser.add_argument("--threshold", type=float, default=0.80)
    args = parser.parse_args()
    project = Path(args.project).resolve()
    slice_path = Path(args.slice).resolve() if args.slice else project / ".adworkflow" / "semantic_slice.json"
    database = Path(args.database).resolve() if args.database else project / ".codegraph" / "l2.sqlite"
    out = Path(args.out).resolve() if args.out else project / ".adworkflow" / "context_preflight.json"
    semantic_slice = json.loads(slice_path.read_text(encoding="utf-8-sig"))
    result = preflight(project, database, semantic_slice, args.task_id, args.threshold)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "accepted" else 2


if __name__ == "__main__":
    raise SystemExit(main())
