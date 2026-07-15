#!/usr/bin/env python3
"""Query a lightweight ADworkflo codegraph index."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


SUPPORTED_QUERIES = {
    "capabilities",
    "callees",
    "callers",
    "expand",
    "find_references",
    "summary",
    "find_definition",
    "find_importers",
    "tests_for",
    "summarize_file",
    "make_context",
    "impact",
    "slice",
}


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


def find_importers(index: dict, target: str) -> list[dict]:
    normalized = target.replace("\\", "/").removesuffix(".py").removesuffix(".js").removesuffix(".ts")
    stem = Path(normalized).name
    matches = []
    for record in index.get("imports", []):
        imported = str(record.get("imports", "")).replace(".", "/")
        if imported == normalized or imported.endswith(f"/{stem}") or imported == stem:
            matches.append(record)
    return matches


def cmd_find_importers(index: dict, target: str) -> None:
    print(json.dumps(find_importers(index, target), ensure_ascii=False, indent=2))


def summarize_file(index: dict, file_path: str) -> dict:
    normalized = file_path.replace("\\", "/")
    file_record = next((item for item in index.get("files", []) if item.get("path") == normalized), None)
    if not file_record:
        return {"path": normalized, "found": False}
    return {
        "path": normalized,
        "found": True,
        "language": file_record.get("language"),
        "loc": file_record.get("loc"),
        "sha256": file_record.get("sha256"),
        "is_test": file_record.get("is_test", False),
        "symbols": [item for item in index.get("symbols", []) if item.get("file") == normalized],
        "imports": [item.get("imports") for item in index.get("imports", []) if item.get("file") == normalized],
    }


def cmd_summarize_file(index: dict, file_path: str) -> None:
    print(json.dumps(summarize_file(index, file_path), ensure_ascii=False, indent=2))


def tests_for(index: dict, target: str) -> list[str]:
    target_lower = target.lower()
    target_stem = Path(target).stem.lower()
    return [test for test in index.get("tests", [])
        if target_lower in test.lower() or target_stem in test.lower()]


def cmd_tests_for(index: dict, target: str) -> None:
    matches = tests_for(index, target)
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
    context_level = "L1-index"
    file_count = index.get("summary", {}).get("file_count", 0)
    if file_count <= 50:
        context_level = "L0-rg-manual-context-manifest"
    elif file_count > 300:
        context_level = "L1-index-large-project"

    manifest = {
        "schema": "ADworkflo.context_manifest.v1",
        "task_id": task.get("task_id", ""),
        "context_level": context_level,
        "read_first": read_first,
        "relevant_symbols": relevant_symbols,
        "entrypoints": task.get("entrypoints", []),
        "likely_tests": likely_tests,
        "do_not_touch": task.get("do_not_touch", []),
        "open_questions": [] if read_first or relevant_symbols else [
            "No strong codegraph match found. Use rg and file tree to refine context_manifest."
        ],
    }
    write_json(out_path, manifest)
    print(f"Wrote context manifest: {out_path}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description="Query an ADworkflo L1 index or L2 semantic graph.")
    parser.add_argument("--project", required=True, help="Project root path.")
    parser.add_argument("--index", default=None, help="Index path. Defaults to .codegraph/index.json.")
    parser.add_argument("--database", default=None, help="L2 database path. Defaults to .codegraph/l2.sqlite.")
    parser.add_argument("--level", choices=["auto", "l1", "l2"], default="auto")
    parser.add_argument("--allow-stale", action="store_true", help="Allow L2 queries against stale source data and mark the result.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("summary")

    find_def = sub.add_parser("find-definition")
    find_def.add_argument("--symbol", required=True)

    find_import = sub.add_parser("find-importers")
    find_import.add_argument("--target", required=True)

    tests_for = sub.add_parser("tests-for")
    tests_for.add_argument("--target", required=True)

    summarize = sub.add_parser("summarize-file")
    summarize.add_argument("--file", required=True)

    make_context = sub.add_parser("make-context")
    make_context.add_argument("--task", required=True, help="Path to task_spec.json.")
    make_context.add_argument("--out", default=None, help="Output manifest path.")

    sub.add_parser("capabilities")
    find_refs = sub.add_parser("find-references")
    find_refs.add_argument("--symbol", required=True)
    find_refs.add_argument("--out", default=None)
    callers = sub.add_parser("callers")
    callers.add_argument("--symbol", required=True)
    callers.add_argument("--out", default=None)
    callees = sub.add_parser("callees")
    callees.add_argument("--symbol", required=True)
    callees.add_argument("--out", default=None)
    impact = sub.add_parser("impact")
    impact.add_argument("--target", required=True)
    impact.add_argument("--depth", type=int, default=3)
    impact.add_argument("--budget", type=int, default=200)
    impact.add_argument("--out", default=None)
    slice_parser = sub.add_parser("slice")
    slice_parser.add_argument("--entrypoint", action="append", required=True)
    slice_parser.add_argument("--depth", type=int, default=2)
    slice_parser.add_argument("--budget", type=int, default=100)
    slice_parser.add_argument("--include-callers", action="store_true")
    slice_parser.add_argument("--out", default=None)
    expand = sub.add_parser("expand")
    expand.add_argument("--slice", required=True)
    expand.add_argument("--request", required=True)
    expand.add_argument("--out", default=None)

    args = parser.parse_args()
    project = Path(args.project).resolve()
    l2_commands = {"capabilities", "find-references", "callers", "callees", "impact", "slice", "expand"}
    database_path = Path(args.database).resolve() if args.database else project / ".codegraph" / "l2.sqlite"
    use_l2 = args.level == "l2" or args.command in l2_commands or (args.level == "auto" and database_path.exists() and args.command != "make-context")
    if use_l2:
        if not database_path.exists():
            raise SystemExit(f"L2 codegraph database not found: {database_path}. Build it with build_codegraph.py --level l2.")
        from l2_codegraph.query import GraphQuery
        from l2_codegraph.safety import freshness_report
        query = GraphQuery(database_path)
        try:
            with query.read_session():
                freshness = freshness_report(
                    project, database_path, connection=query.connection,
                )
                if not freshness["fresh"] and not args.allow_stale and args.command != "capabilities":
                    raise SystemExit("L2 codegraph is stale: " + json.dumps(freshness, sort_keys=True))
                if args.command == "capabilities":
                    result = query.capabilities()
                elif args.command == "find-definition":
                    result = query.resolve_symbol(args.symbol)
                elif args.command == "find-references":
                    result = query.find_references(args.symbol)
                elif args.command == "find-importers":
                    result = query.find_importers(args.target)
                elif args.command == "callers":
                    result = query.callers(args.symbol)
                elif args.command == "callees":
                    result = query.callees(args.symbol)
                elif args.command == "tests-for":
                    result = query.tests_for(args.target)
                elif args.command == "summarize-file":
                    result = query.summarize_file(args.file)
                elif args.command == "impact":
                    result = query.impact(args.target, args.depth, args.budget)
                elif args.command == "slice":
                    result = query.slice(args.entrypoint, args.depth, args.budget, args.include_callers)
                elif args.command == "expand":
                    semantic_slice = json.loads(Path(args.slice).read_text(encoding="utf-8-sig"))
                    request = json.loads(Path(args.request).read_text(encoding="utf-8-sig"))
                    result = query.expand(semantic_slice, request)
                    if args.out:
                        write_json(Path(args.out).resolve(), result)
                else:
                    result = query.graph_metadata()
        except Exception as error:
            from l2_codegraph.database import graph_error_payload
            payload = graph_error_payload(error)
            if payload is not None:
                print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
                return 3 if payload["retryable"] else 2
            raise SystemExit(f"L2 codegraph freshness check failed: {error}") from None
        if args.allow_stale or args.command == "capabilities":
            result = {**result, "freshness": freshness, "stale": not freshness["fresh"]}
        output_path = getattr(args, "out", None)
        if output_path:
            resolved_output = Path(output_path).resolve()
            write_json(resolved_output, result)
            counts = {
                key: len(result.get(key, []))
                for key in ("references", "callers", "callees", "direct", "transitive", "tests", "included_symbols", "boundary_symbols", "unresolved_edges")
                if key in result
            }
            result = {
                "status": result.get("status"),
                "graph_revision": result.get("graph_revision"),
                "written": str(resolved_output),
                "counts": counts,
                "confidence": result.get("confidence"),
                "truncated": result.get("truncated"),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    index = load_index(project, args.index)

    if args.command == "summary":
        cmd_summary(index)
    elif args.command == "find-definition":
        cmd_find_definition(index, args.symbol)
    elif args.command == "find-importers":
        cmd_find_importers(index, args.target)
    elif args.command == "tests-for":
        cmd_tests_for(index, args.target)
    elif args.command == "summarize-file":
        cmd_summarize_file(index, args.file)
    elif args.command == "make-context":
        out = Path(args.out).resolve() if args.out else project / ".adworkflow" / "context_manifest.json"
        cmd_make_context(index, Path(args.task).resolve(), out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
