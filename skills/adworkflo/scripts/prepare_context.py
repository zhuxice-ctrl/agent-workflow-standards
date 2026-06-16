#!/usr/bin/env python3
"""Prepare ADworkflo context artifacts from a task spec.

This is the main-window bridge between a natural-language task and worker-ready
context. It writes both:
- .adworkflow/context_raw.json: retrieval evidence
- .adworkflow/context_manifest.json: bounded worker context
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent

SOURCE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".swift",
    ".cs",
    ".php",
    ".rb",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
}

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".turbo",
    "coverage",
    ".adworkflow",
    ".codegraph",
}


def read_json(path: Path, default: dict | None = None) -> dict:
    if not path.exists():
        return default or {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def iter_source_files(project: Path):
    for root, dirs, files in os.walk(project):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        root_path = Path(root)
        for name in files:
            path = root_path / name
            if path.suffix.lower() in SOURCE_EXTENSIONS:
                yield path


def rel(project: Path, path: Path) -> str:
    return path.resolve().relative_to(project.resolve()).as_posix()


def existing(project: Path, paths: list[str]) -> list[str]:
    return [p for p in paths if (project / p).exists()]


def words(text: str) -> list[str]:
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", text)
    stop = {
        "the", "and", "for", "with", "this", "that", "fix", "add", "update",
        "实现", "修复", "新增", "调整", "优化", "问题", "功能", "模块",
    }
    return [w for w in raw if w.lower() not in stop]


def score_record(record: dict, terms: list[str]) -> int:
    haystack = " ".join(str(v) for v in record.values()).lower()
    return sum(1 for term in terms if term.lower() in haystack)


def task_terms(task: dict) -> list[str]:
    text = " ".join([
        str(task.get("task_id", "")),
        str(task.get("goal", "")),
        " ".join(task.get("acceptance_criteria", [])),
    ])
    return words(text)


def build_index(project: Path, index_path: Path) -> None:
    script = SCRIPT_DIR / "build_codegraph.py"
    subprocess.run(
        [sys.executable, str(script), "--project", str(project), "--out", str(index_path)],
        check=True,
    )


def context_level_for_index(index: dict) -> str:
    file_count = index.get("summary", {}).get("file_count", 0)
    if file_count <= 50:
        return "L0-rg-manual-context-manifest"
    if file_count > 300:
        return "L2-full-codegraph"
    return "L1-index"


def make_code_context(task: dict, index: dict) -> tuple[dict, dict]:
    terms = task_terms(task)
    scored_files = []
    for record in index.get("files", []):
        score = score_record(record, terms)
        if score:
            scored_files.append((score, record))

    scored_symbols = []
    for symbol in index.get("symbols", []):
        score = score_record(symbol, terms)
        if score:
            scored_symbols.append((score, symbol))

    scored_files.sort(key=lambda item: item[0], reverse=True)
    scored_symbols.sort(key=lambda item: item[0], reverse=True)

    read_first = [record["path"] for _, record in scored_files[:8]]
    for _, symbol in scored_symbols[:8]:
        file_path = symbol.get("file")
        if file_path and file_path not in read_first:
            read_first.append(file_path)
    read_first = read_first[:8]

    relevant_symbols = [
        f"{symbol.get('name')} ({symbol.get('file')}:{symbol.get('line')})"
        for _, symbol in scored_symbols[:12]
    ]

    likely_tests = []
    read_tokens = {Path(path).stem.lower() for path in read_first}
    for test in index.get("tests", []):
        low = test.lower()
        if any(token and token in low for token in read_tokens):
            likely_tests.append(test)
    if not likely_tests:
        likely_tests = index.get("tests", [])[:8]

    warnings = []
    if not read_first and not relevant_symbols:
        warnings.append("No strong codegraph match found. Refine context with rg and file tree.")

    raw = {
        "schema": "ADworkflo.context_raw.v1",
        "task_id": task.get("task_id", ""),
        "source": "codegraph-index",
        "matched_files": [
            {"score": score, **record} for score, record in scored_files[:20]
        ],
        "matched_symbols": [
            {"score": score, **symbol} for score, symbol in scored_symbols[:20]
        ],
        "likely_tests": likely_tests,
        "warnings": warnings,
    }

    manifest = {
        "task_id": task.get("task_id", ""),
        "context_level": context_level_for_index(index),
        "read_first": read_first,
        "relevant_symbols": relevant_symbols,
        "entrypoints": [],
        "likely_tests": likely_tests,
        "do_not_touch": task.get("non_goals", []),
        "open_questions": warnings,
    }
    return raw, manifest


def make_architecture_context(project: Path, task: dict) -> tuple[dict, dict]:
    architecture = read_json(project / ".adworkflow" / "architecture_manifest.json", {})
    profile = read_json(project / ".adworkflow" / "ADWORKFLOW_PROFILE.json", {})
    planned_modules = architecture.get("planned_modules", [])
    warnings = []
    if not architecture.get("analysis_basis"):
        warnings.append("No product-doc architecture analysis found. Run analyze_project_plan.py after PRD/ARCH/TODO/PROJECT are written.")

    read_first = existing(project, [
        "PRD.md",
        "ARCH.md",
        "TODO.md",
        "PROJECT.md",
        ".adworkflow/architecture_manifest.json",
        ".adworkflow/module_skills.md",
        ".adworkflow/permissions.md",
        ".adworkflow/verification_commands.md",
    ])

    raw = {
        "schema": "ADworkflo.context_raw.v1",
        "task_id": task.get("task_id", ""),
        "source": "architecture-manifest",
        "matched_files": [{"path": path, "reason": "architecture-first"} for path in read_first],
        "matched_symbols": [],
        "likely_tests": [],
        "warnings": warnings,
    }

    manifest = {
        "task_id": task.get("task_id", ""),
        "context_level": profile.get("context_strategy") or architecture.get("context_strategy") or "architecture-first",
        "read_first": read_first,
        "relevant_symbols": [],
        "entrypoints": planned_modules,
        "likely_tests": [],
        "do_not_touch": task.get("non_goals", []),
        "open_questions": warnings,
    }
    return raw, manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare ADworkflo context artifacts.")
    parser.add_argument("--project", required=True, help="Project root path.")
    parser.add_argument("--task", default=None, help="Path to task_spec.json.")
    parser.add_argument("--raw-out", default=None, help="Output path for context_raw.json.")
    parser.add_argument("--manifest-out", default=None, help="Output path for context_manifest.json.")
    parser.add_argument("--no-build-index", action="store_true", help="Do not build .codegraph/index.json when missing.")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        raise SystemExit(f"Project path is not a directory: {project}")

    task_path = Path(args.task).resolve() if args.task else project / ".adworkflow" / "task_spec.json"
    raw_out = Path(args.raw_out).resolve() if args.raw_out else project / ".adworkflow" / "context_raw.json"
    manifest_out = Path(args.manifest_out).resolve() if args.manifest_out else project / ".adworkflow" / "context_manifest.json"
    index_path = project / ".codegraph" / "index.json"

    task = read_json(task_path)
    if not task.get("task_id") or not task.get("goal"):
        raise SystemExit(f"Task spec must include task_id and goal: {task_path}")

    source_files = list(iter_source_files(project))
    if source_files and not index_path.exists() and not args.no_build_index:
        build_index(project, index_path)

    if index_path.exists():
        index = read_json(index_path)
        if index.get("summary", {}).get("file_count", 0) > 0:
            raw, manifest = make_code_context(task, index)
        else:
            raw, manifest = make_architecture_context(project, task)
    else:
        raw, manifest = make_architecture_context(project, task)

    write_json(raw_out, raw)
    write_json(manifest_out, manifest)
    print(f"Wrote context raw: {raw_out}")
    print(f"Wrote context manifest: {manifest_out}")
    print(json.dumps({
        "task_id": manifest.get("task_id"),
        "source": raw.get("source"),
        "context_level": manifest.get("context_level"),
        "read_first_count": len(manifest.get("read_first", [])),
        "warning_count": len(raw.get("warnings", [])),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
