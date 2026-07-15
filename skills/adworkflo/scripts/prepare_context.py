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
import sqlite3
import sys
import tempfile
from pathlib import Path

import build_codegraph as codegraph_builder


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


def preserve_l2_baseline(preflight_out: Path, context_preflight: dict) -> Path | None:
    from l2_codegraph.safety import baseline_record_path

    if context_preflight.get("status") != "accepted":
        return None
    task_id = str(context_preflight.get("task_id", "")).strip()
    revision = str(context_preflight.get("graph_revision", "")).strip()
    if not task_id or not revision:
        return None
    baseline = baseline_record_path(preflight_out.parent, task_id)
    baseline.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "ADworkflo.codegraph.baseline.v1",
        "task_id": task_id,
        "graph_revision": revision,
        "source": str(preflight_out),
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{baseline.name}.", suffix=".tmp", dir=baseline.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, baseline)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)
    return baseline


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


def artifact_reference(project: Path, path: Path) -> str:
    """Return a stable project-relative reference when the artifact is local."""
    try:
        return rel(project, path)
    except ValueError:
        return path.resolve().as_posix()


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


def validate_task(task: dict) -> None:
    if task.get("configured") is False:
        raise ValueError("Task spec is not configured.")
    if not task.get("task_id") or not task.get("goal"):
        raise ValueError("Task spec must include task_id and goal.")


def build_index(project: Path, index_path: Path) -> dict:
    index = codegraph_builder.build_index(project)
    codegraph_builder.write_index(index_path, index)
    return index


def context_level_for_index(index: dict) -> str:
    file_count = index.get("summary", {}).get("file_count", 0)
    if file_count <= 50:
        return "L0-rg-manual-context-manifest"
    if file_count > 300:
        return "L1-index-large-project"
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
        "schema": "ADworkflo.context_manifest.v1",
        "task_id": task.get("task_id", ""),
        "context_level": context_level_for_index(index),
        "read_first": read_first,
        "relevant_symbols": relevant_symbols,
        "entrypoints": task.get("entrypoints", []),
        "likely_tests": likely_tests,
        "do_not_touch": task.get("do_not_touch", []),
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
        ".adworkflow/PROJECT.md",
        ".adworkflow/architecture_manifest.json",
        ".adworkflow/design_alignment_report.json",
        ".adworkflow/layer_plan.json",
        ".adworkflow/interface_contracts.json",
        ".adworkflow/module_skills.md",
        ".adworkflow/permissions.md",
        ".adworkflow/verification_commands.md",
    ])

    raw = {
        "schema": "ADworkflo.context_raw.v1",
        "task_id": task.get("task_id", ""),
        "source": "architecture-docs",
        "matched_files": [{"path": path, "reason": "architecture-first"} for path in read_first],
        "matched_symbols": [],
        "likely_tests": [],
        "warnings": warnings,
    }

    manifest = {
        "schema": "ADworkflo.context_manifest.v1",
        "task_id": task.get("task_id", ""),
        "context_level": profile.get("context_strategy") or architecture.get("context_strategy") or "architecture-first",
        "read_first": read_first,
        "relevant_symbols": [],
        "entrypoints": task.get("entrypoints", []) or planned_modules,
        "likely_tests": [],
        "do_not_touch": task.get("do_not_touch", []),
        "open_questions": warnings,
    }
    return raw, manifest


DOCUMENT_TASK_TYPES = {"product", "architecture", "workflow", "docs", "review"}


def add_explicit_context_sources(project: Path, task: dict, raw: dict, manifest: dict) -> None:
    sources: list[str] = task.get("context_sources", [])
    read_first: list[str] = manifest["read_first"]
    matched_files: list[dict] = raw["matched_files"]
    for source in sources:
        normalized = source.replace("\\", "/")
        if (project / normalized).exists() and normalized not in read_first:
            read_first.append(normalized)
            matched_files.append({"path": normalized, "reason": "task_spec.context_sources"})


def prepare(project: Path, task: dict, no_build_index: bool = False) -> tuple[dict, dict]:
    project = project.resolve()
    validate_task(task)
    if task.get("task_type", "code") in DOCUMENT_TASK_TYPES:
        raw, manifest = make_architecture_context(project, task)
        add_explicit_context_sources(project, task, raw, manifest)
        return raw, manifest

    index_path = project / ".codegraph" / "index.json"
    source_files = list(iter_source_files(project))
    index = read_json(index_path) if index_path.exists() else {}
    stale = bool(index) and codegraph_builder.index_is_stale(project, index)
    rebuilt = False
    if source_files and (not index or stale) and not no_build_index:
        index = build_index(project, index_path)
        rebuilt = True

    if index.get("summary", {}).get("file_count", 0) > 0:
        raw, manifest = make_code_context(task, index)
        if stale and no_build_index:
            raw["warnings"].append("Codegraph index is stale and --no-build-index prevented refresh.")
            manifest["open_questions"].append("Refresh the stale codegraph before relying on impact analysis.")
        elif rebuilt and stale:
            raw["warnings"].append("Stale codegraph index was rebuilt before context preparation.")
    else:
        raw, manifest = make_architecture_context(project, task)
    add_explicit_context_sources(project, task, raw, manifest)
    return raw, manifest


def requested_level(project: Path, task: dict, explicit: str = "auto") -> str:
    if explicit in {"l1", "l2"}:
        return explicit
    configured = str(task.get("codegraph_level", "")).lower()
    if configured in {"l1", "l2"}:
        return configured
    config = read_json(project / ".codegraph" / "config.json", {})
    if config.get("level") in {"l1", "l2"}:
        return config["level"]
    return "l2" if str(config.get("context_strategy", "")).startswith("L2") else "l1"


def prepare_l2(
    project: Path,
    task: dict,
    no_build_index: bool = False,
    depth: int = 2,
    budget: int = 100,
    threshold: float = 0.80,
) -> tuple[dict, dict, dict, dict]:
    from build_codegraph_l2 import build as build_l2
    from l2_codegraph.query import GraphQuery
    from l2_codegraph.safety import freshness_report, preflight

    def invalid_database_context(reason: str) -> tuple[dict, dict, dict, dict]:
        semantic_slice = {
            "schema": "ADworkflo.semantic_slice.v1", "status": "invalid", "graph_revision": None,
            "entrypoints": task.get("entrypoints", []), "entrypoint_resolutions": [],
            "included_symbols": [], "included_files": [], "boundary_symbols": [], "excluded": [],
            "unresolved_edges": [{"file": None, "source_symbol_id": None, "kind": "database", "target": str(database),
                                  "line": 0, "reason": reason, "critical": True}],
            "likely_tests": [],
            "coverage": {"resolved_call_ratio": 0.0, "resolved_reference_ratio": 0.0,
                         "resolved_edge_ratio": 0.0, "resolved_entrypoint_ratio": 0.0},
            "confidence": 0.0, "truncated": False, "source_hashes": {}, "provenance": [],
            "parameters": {"depth": depth, "budget": budget, "include_callers": False, "additional_seeds": []},
            "expansion_history": [], "predicted_impact_files": [],
        }
        gate = {
            "schema": "ADworkflo.context_preflight.v1", "task_id": task["task_id"], "status": "invalid",
            "graph_revision": None, "slice_revision": None, "confidence": 0.0,
            "confidence_threshold": threshold, "freshness": {"fresh": False, "error": reason},
            "provider_capabilities": [], "missing_capabilities": {},
            "invalid_reasons": ["database-unreadable"], "expansion_reasons": [],
            "required_actions": ["Rebuild the L2 graph before editing."],
            "critical_unresolved_edges": semantic_slice["unresolved_edges"], "expansion_history": [],
        }
        raw = {
            "schema": "ADworkflo.context_raw.v1", "task_id": task["task_id"],
            "source": "semantic-codegraph-l2", "matched_files": [], "matched_symbols": [],
            "likely_tests": [], "warnings": [reason], "graph_revision": None, "confidence": 0.0,
            "unresolved_edges": semantic_slice["unresolved_edges"], "boundary_symbols": [],
            "predicted_impact_files": [],
        }
        manifest = {
            "schema": "ADworkflo.context_manifest.v1", "task_id": task["task_id"],
            "context_level": "L2-semantic-codegraph", "read_first": [], "relevant_symbols": [],
            "entrypoints": task.get("entrypoints", []), "likely_tests": [],
            "do_not_touch": task.get("do_not_touch", []), "open_questions": gate["required_actions"],
            "graph_revision": None, "context_confidence": 0.0, "preflight_status": "invalid",
            "semantic_slice": ".adworkflow/semantic_slice.json",
            "context_preflight": ".adworkflow/context_preflight.json", "predicted_impact_files": [],
        }
        add_explicit_context_sources(project, task, raw, manifest)
        return raw, manifest, semantic_slice, gate

    project = project.resolve()
    validate_task(task)
    database = project / ".codegraph" / "l2.sqlite"
    database_error: Exception | None = None
    try:
        stale = database.exists() and not freshness_report(project, database)["fresh"]
    except Exception as error:
        stale = database.exists()
        database_error = error
    if database_error and no_build_index:
        return invalid_database_context(f"L2 database is unreadable: {database_error}")
    rebuilt = False
    if (not database.exists() or stale) and not no_build_index:
        build_l2(project, database, include_typescript=True, require_typescript=False)
        rebuilt = True
    if not database.exists():
        return invalid_database_context("L2 database is missing and --no-build-index prevented creation")

    query = GraphQuery(database)
    with query.read_session():
        semantic_slice = query.slice(
            task.get("entrypoints", []), depth=depth, budget=budget,
        )
        predicted_impact_files: set[str] = set()
        for resolution in semantic_slice.get("entrypoint_resolutions", []):
            if resolution.get("status") == "resolved":
                impact = query.impact(
                    resolution["symbol"]["stable_id"],
                    depth=max(3, depth),
                    budget=max(200, budget),
                )
                predicted_impact_files.update(impact.get("predicted_files", []))
        semantic_slice["predicted_impact_files"] = sorted(predicted_impact_files)
        context_preflight = preflight(
            project,
            database,
            semantic_slice,
            task["task_id"],
            threshold,
            connection=query.connection,
        )
    warnings = [*context_preflight["invalid_reasons"], *context_preflight["expansion_reasons"]]
    if rebuilt:
        warnings.append("L2 graph was rebuilt before context preparation.")
    matched_symbols = [
        {
            "stable_id": item["stable_id"], "qualified_name": item["qualified_name"],
            "file": item["file"], "start_line": item["start_line"], "end_line": item["end_line"],
            "distance": item["distance"],
        }
        for item in semantic_slice.get("included_symbols", [])
    ]
    raw = {
        "schema": "ADworkflo.context_raw.v1",
        "task_id": task["task_id"],
        "source": "semantic-codegraph-l2",
        "matched_files": [
            {"path": path, "sha256": semantic_slice.get("source_hashes", {}).get(path), "reason": "semantic-slice"}
            for path in semantic_slice.get("included_files", [])
        ],
        "matched_symbols": matched_symbols,
        "likely_tests": semantic_slice.get("likely_tests", []),
        "warnings": warnings,
        "graph_revision": semantic_slice.get("graph_revision"),
        "confidence": semantic_slice.get("confidence", 0),
        "unresolved_edges": semantic_slice.get("unresolved_edges", []),
        "boundary_symbols": semantic_slice.get("boundary_symbols", []),
        "predicted_impact_files": sorted(predicted_impact_files),
    }
    manifest = {
        "schema": "ADworkflo.context_manifest.v1",
        "task_id": task["task_id"],
        "context_level": "L2-semantic-codegraph",
        "read_first": [*semantic_slice.get("included_files", []), *semantic_slice.get("likely_tests", [])],
        "relevant_symbols": [
            f"{item['qualified_name']} ({item['file']}:{item['start_line']})"
            for item in semantic_slice.get("included_symbols", [])
        ],
        "entrypoints": task.get("entrypoints", []),
        "likely_tests": semantic_slice.get("likely_tests", []),
        "do_not_touch": task.get("do_not_touch", []),
        "open_questions": context_preflight.get("required_actions", []),
        "graph_revision": semantic_slice.get("graph_revision"),
        "context_confidence": semantic_slice.get("confidence", 0),
        "preflight_status": context_preflight["status"],
        "semantic_slice": ".adworkflow/semantic_slice.json",
        "context_preflight": ".adworkflow/context_preflight.json",
        "predicted_impact_files": sorted(predicted_impact_files),
    }
    add_explicit_context_sources(project, task, raw, manifest)
    manifest["read_first"] = list(dict.fromkeys(manifest["read_first"]))
    return raw, manifest, semantic_slice, context_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare ADworkflo context artifacts.")
    parser.add_argument("--project", required=True, help="Project root path.")
    parser.add_argument("--task", default=None, help="Path to task_spec.json.")
    parser.add_argument("--raw-out", default=None, help="Output path for context_raw.json.")
    parser.add_argument("--manifest-out", default=None, help="Output path for context_manifest.json.")
    parser.add_argument("--no-build-index", action="store_true", help="Do not build .codegraph/index.json when missing.")
    parser.add_argument("--level", choices=["auto", "l1", "l2"], default="auto")
    parser.add_argument("--slice-out", default=None)
    parser.add_argument("--preflight-out", default=None)
    parser.add_argument("--slice-depth", type=int, default=2)
    parser.add_argument("--slice-budget", type=int, default=100)
    parser.add_argument("--confidence-threshold", type=float, default=0.80)
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.is_dir():
        raise SystemExit(f"Project path is not a directory: {project}")

    task_path = Path(args.task).resolve() if args.task else project / ".adworkflow" / "task_spec.json"
    raw_out = Path(args.raw_out).resolve() if args.raw_out else project / ".adworkflow" / "context_raw.json"
    manifest_out = Path(args.manifest_out).resolve() if args.manifest_out else project / ".adworkflow" / "context_manifest.json"
    slice_out = Path(args.slice_out).resolve() if args.slice_out else project / ".adworkflow" / "semantic_slice.json"
    preflight_out = Path(args.preflight_out).resolve() if args.preflight_out else project / ".adworkflow" / "context_preflight.json"

    task = read_json(task_path)
    try:
        level = requested_level(project, task, args.level)
        if level == "l2" and task.get("task_type", "code") not in DOCUMENT_TASK_TYPES:
            raw, manifest, semantic_slice, context_preflight = prepare_l2(
                project, task, args.no_build_index, args.slice_depth, args.slice_budget, args.confidence_threshold,
            )
            manifest["semantic_slice"] = artifact_reference(project, slice_out)
            manifest["context_preflight"] = artifact_reference(project, preflight_out)
            write_json(slice_out, semantic_slice)
            write_json(preflight_out, context_preflight)
            preserve_l2_baseline(preflight_out, context_preflight)
        else:
            raw, manifest = prepare(project, task, no_build_index=args.no_build_index)
    except (ValueError, RuntimeError, OSError, sqlite3.DatabaseError) as error:
        from l2_codegraph.database import graph_error_payload
        payload = graph_error_payload(error)
        if payload is not None:
            print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
            return 3 if payload["retryable"] else 2
        raise SystemExit(f"Invalid task spec {task_path}: {error}") from None

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
        "preflight_status": manifest.get("preflight_status"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
