#!/usr/bin/env python3
"""Query a lightweight ADworkflo codegraph index."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def load_index(project: Path, index_path: str | None) -> dict:
    path = Path(index_path).resolve() if index_path else project / ".codegraph" / "index.json"
    if not path.exists():
        raise SystemExit(f"Codegraph index not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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


def cmd_summary(index: dict) -> None:
    print(json.dumps(index.get("summary", {}), ensure_ascii=False, indent=2))


def cmd_find_definition(index: dict, symbol: str) -> None:
    matches = [s for s in index.get("symbols", []) if s.get("name") == symbol]
    print(json.dumps(matches, ensure_ascii=False, indent=2))


def cmd_tests_for(index: dict, target: str) -> None:
    target_lower = target.lower()
    target_stem = Path(target).stem.lower()
    matches = []
    for test in index.get("tests", []):
        low = test.lower()
        if target_lower in low or target_stem in low:
            matches.append(test)
    if not matches:
        matches = index.get("tests", [])[:10]
    print(json.dumps(matches, ensure_ascii=False, indent=2))


def cmd_make_context(index: dict, task_path: Path, out_path: Path) -> None:
    task = json.loads(task_path.read_text(encoding="utf-8-sig"))
    text = " ".join([
        str(task.get("task_id", "")),
        str(task.get("goal", "")),
        " ".join(task.get("acceptance_criteria", [])),
    ])
    terms = words(text)

    scored_files = []
    for file_record in index.get("files", []):
        score = score_record(file_record, terms)
        if score:
            scored_files.append((score, file_record["path"]))

    scored_symbols = []
    for symbol in index.get("symbols", []):
        score = score_record(symbol, terms)
        if score:
            scored_symbols.append((score, symbol))

    scored_files.sort(reverse=True)
    scored_symbols.sort(key=lambda item: item[0], reverse=True)

    read_first = [p for _, p in scored_files[:8]]
    relevant_symbols = [
        f"{s.get('name')} ({s.get('file')}:{s.get('line')})"
        for _, s in scored_symbols[:12]
    ]
    for _, symbol in scored_symbols[:8]:
        file_path = symbol.get("file")
        if file_path and file_path not in read_first:
            read_first.append(file_path)
    read_first = read_first[:8]

    likely_tests = []
    read_tokens = {Path(p).stem.lower() for p in read_first}
    for test in index.get("tests", []):
        low = test.lower()
        if any(token and token in low for token in read_tokens):
            likely_tests.append(test)
    if not likely_tests:
        likely_tests = index.get("tests", [])[:8]

    context_level = "L1-index"
    file_count = index.get("summary", {}).get("file_count", 0)
    if file_count <= 50:
        context_level = "L0-rg-manual-context-manifest"
    elif file_count > 300:
        context_level = "L2-full-codegraph"

    manifest = {
        "task_id": task.get("task_id", ""),
        "context_level": context_level,
        "read_first": read_first,
        "relevant_symbols": relevant_symbols,
        "entrypoints": [],
        "likely_tests": likely_tests,
        "do_not_touch": task.get("non_goals", []),
        "open_questions": [] if read_first or relevant_symbols else [
            "No strong codegraph match found. Use rg and file tree to refine context_manifest."
        ],
    }
    write_json(out_path, manifest)
    print(f"Wrote context manifest: {out_path}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Query an ADworkflo codegraph index.")
    parser.add_argument("--project", required=True, help="Project root path.")
    parser.add_argument("--index", default=None, help="Index path. Defaults to .codegraph/index.json.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("summary")

    find_def = sub.add_parser("find-definition")
    find_def.add_argument("--symbol", required=True)

    tests_for = sub.add_parser("tests-for")
    tests_for.add_argument("--target", required=True)

    make_context = sub.add_parser("make-context")
    make_context.add_argument("--task", required=True, help="Path to task_spec.json.")
    make_context.add_argument("--out", default=None, help="Output manifest path.")

    args = parser.parse_args()
    project = Path(args.project).resolve()
    index = load_index(project, args.index)

    if args.command == "summary":
        cmd_summary(index)
    elif args.command == "find-definition":
        cmd_find_definition(index, args.symbol)
    elif args.command == "tests-for":
        cmd_tests_for(index, args.target)
    elif args.command == "make-context":
        out = Path(args.out).resolve() if args.out else project / ".adworkflow" / "context_manifest.json"
        cmd_make_context(index, Path(args.task).resolve(), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
