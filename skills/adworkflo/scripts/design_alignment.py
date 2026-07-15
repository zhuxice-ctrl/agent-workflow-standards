#!/usr/bin/env python3
"""Build and approve the structural PRD-to-ARCH alignment gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIREMENT_RE = re.compile(r"\b(?:FR|NFR|UX|SEC|DATA|API)-\d+\b", re.IGNORECASE)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def requirement_statements(text: str) -> dict[str, str]:
    statements: dict[str, str] = {}
    lines = text.splitlines()
    for index, line in enumerate(lines):
        for match in REQUIREMENT_RE.findall(line):
            requirement_id = match.upper()
            statement = re.sub(REQUIREMENT_RE, "", line).strip(" #-:：|`")
            if not statement and index + 1 < len(lines):
                statement = lines[index + 1].strip()
            statements.setdefault(requirement_id, statement)
    return statements


def build_report(project: Path, prd_path: Path | None = None, arch_path: Path | None = None) -> dict[str, Any]:
    prd = prd_path or project / "PRD.md"
    arch = arch_path or project / "ARCH.md"
    if not prd.exists() or not arch.exists():
        missing = [str(path) for path in (prd, arch) if not path.exists()]
        raise FileNotFoundError(f"Required design documents missing: {', '.join(missing)}")

    prd_text = read(prd)
    arch_text = read(arch)
    prd_requirements = requirement_statements(prd_text)
    arch_requirements = set(requirement_statements(arch_text))
    requirements = [
        {
            "requirement_id": requirement_id,
            "prd_statement": statement,
            "architecture_refs": [requirement_id] if requirement_id in arch_requirements else [],
            "status": "covered" if requirement_id in arch_requirements else "missing",
            "evidence": [f"ARCH.md references {requirement_id}"] if requirement_id in arch_requirements else [],
        }
        for requirement_id, statement in sorted(prd_requirements.items())
    ]
    additions = sorted(arch_requirements - set(prd_requirements))
    blocking = [
        f"missing architecture coverage for {item['requirement_id']}"
        for item in requirements if item["status"] == "missing"
    ]
    if not prd_requirements:
        blocking.append("PRD contains no stable requirement IDs")
    if additions:
        blocking.append("architecture contains requirement IDs absent from PRD")
    blocking.append("semantic review is pending")
    return {
        "schema": "ADworkflo.design_alignment_report.v1",
        "configured": True,
        "created_at": now(),
        "source_hashes": {
            prd.name: sha256_text(prd_text),
            arch.name: sha256_text(arch_text),
        },
        "requirements": requirements,
        "architecture_scope_additions": additions,
        "semantic_review": {
            "required": True,
            "status": "pending",
            "reviewer": None,
            "reviewed_at": None,
            "notes": [],
        },
        "gate_status": "blocked",
        "blocking_reasons": blocking,
    }


def assert_report_fresh(project: Path, report: dict[str, Any]) -> None:
    expected = report.get("source_hashes", {})
    current = {}
    for name in expected:
        path = project / name
        current[name] = sha256_text(read(path)) if path.exists() else "missing"
    if current != expected:
        changed = sorted(name for name in set(expected) | set(current) if expected.get(name) != current.get(name))
        raise ValueError(f"source documents changed after alignment analysis: {', '.join(changed)}")


def approve_report(report: dict[str, Any], reviewer: str, notes: list[str]) -> dict[str, Any]:
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    report = json.loads(json.dumps(report))
    report["semantic_review"] = {
        "required": True,
        "status": "approved",
        "reviewer": reviewer,
        "reviewed_at": now(),
        "notes": notes,
    }
    structural = [
        reason for reason in report.get("blocking_reasons", [])
        if reason != "semantic review is pending"
    ]
    report["blocking_reasons"] = structural
    report["gate_status"] = "blocked" if structural else "passed"
    return report


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--prd", default=None)
    analyze.add_argument("--arch", default=None)
    approve = sub.add_parser("approve-semantic-review")
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--note", action="append", default=[])
    args = parser.parse_args()

    project = Path(args.project).resolve()
    output = project / ".adworkflow" / "design_alignment_report.json"
    if args.command == "analyze":
        report = build_report(
            project,
            Path(args.prd).resolve() if args.prd else None,
            Path(args.arch).resolve() if args.arch else None,
        )
    else:
        report = json.loads(output.read_text(encoding="utf-8-sig"))
        assert_report_fresh(project, report)
        report = approve_report(report, args.reviewer, args.note)
    write_json(output, report)
    print(json.dumps({"output": str(output), "gate_status": report["gate_status"], "blocking_reasons": report["blocking_reasons"]}, ensure_ascii=False, indent=2))
    return 0 if report["gate_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
