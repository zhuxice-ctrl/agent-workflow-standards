from __future__ import annotations

import json
import os
from collections import Counter
import hashlib
from pathlib import Path
from typing import Any

from .database import connect, metadata
from .locking import graph_locks
from .model import (
    LANGUAGE_EXTENSIONS, REQUIRED_L2_CAPABILITIES, file_in_graph_scope, load_graph_config,
    normalize_graph_config, read_source, sha256_text,
)


SOURCE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".mts", ".cts"}
EXCLUDE_DIRS = {".git", ".adworkflow", ".codegraph", "node_modules", ".venv", "venv", "dist", "build", "coverage", ".next", ".turbo", "__pycache__"}


def baseline_record_path(artifact_root: Path, task_id: str) -> Path:
    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
    return artifact_root / "baselines" / f"{digest}.json"


def resolve_baseline_revision(
    artifact_root: Path,
    task_id: str,
    fallback_revision: str | None = None,
) -> str:
    """Resolve a task baseline, failing closed when its immutable record is bad."""
    record_path = baseline_record_path(artifact_root, task_id)
    if record_path.exists():
        try:
            record = json.loads(record_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid task baseline record: {record_path}: {error}") from error
        if not isinstance(record, dict):
            raise ValueError(f"invalid task baseline record: {record_path}")
        if record.get("schema") != "ADworkflo.codegraph.baseline.v1":
            raise ValueError(f"invalid task baseline schema: {record_path}")
        if record.get("task_id") != task_id:
            raise ValueError(f"task baseline record belongs to another task: {record_path}")
        revision = record.get("graph_revision")
        if not isinstance(revision, str) or not revision.strip():
            raise ValueError(f"task baseline record has no graph revision: {record_path}")
        return revision.strip()
    if isinstance(fallback_revision, str) and fallback_revision.strip():
        return fallback_revision.strip()
    raise ValueError("task baseline has no graph revision")


def sha256_file(path: Path) -> str:
    return sha256_text(read_source(path))


def current_source_paths(project: Path, config: dict[str, Any] | None = None) -> set[str]:
    config = load_graph_config(project) if config is None else config
    extension_languages = {extension: language for language, extensions in LANGUAGE_EXTENSIONS.items() for extension in extensions}
    paths: set[str] = set()
    for root, dirs, files in os.walk(project):
        dirs[:] = [item for item in dirs if item not in EXCLUDE_DIRS]
        for name in files:
            path = Path(root) / name
            language = extension_languages.get(path.suffix.lower())
            relative_path = path.resolve().relative_to(project.resolve()).as_posix()
            if language and file_in_graph_scope(relative_path, language, config):
                paths.add(relative_path)
    return paths


def freshness_report(
    project: Path,
    database: Path,
    *,
    connection: Any | None = None,
) -> dict[str, Any]:
    project = project.resolve()
    if connection is None:
        with connect(database, readonly=True) as owned_connection:
            return freshness_report(
                project, database, connection=owned_connection,
            )
    indexed = {
        row["path"]: row["sha256"]
        for row in connection.execute("SELECT path, sha256 FROM files")
    }
    graph = metadata(connection)
    config = load_graph_config(project)
    changed = []
    missing = []
    for relative, expected in indexed.items():
        path = project / relative
        if not path.exists():
            missing.append(relative)
        elif sha256_file(path) != expected:
            changed.append(relative)
    added = sorted(current_source_paths(project, config) - set(indexed))
    config_changed = normalize_graph_config(graph.get("config", {})) != normalize_graph_config(config)
    return {
        "fresh": not (changed or missing or added or config_changed),
        "changed": sorted(changed),
        "missing": sorted(missing),
        "added": added,
        "config_changed": config_changed,
    }


def preflight(
    project: Path,
    database: Path,
    semantic_slice: dict[str, Any],
    task_id: str,
    threshold: float = 0.80,
    freshness_override: dict[str, Any] | None = None,
    *,
    connection: Any | None = None,
) -> dict[str, Any]:
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("confidence threshold must be between 0 and 1")
    if connection is None:
        with connect(database, readonly=True) as owned_connection:
            return preflight(
                project,
                database,
                semantic_slice,
                task_id,
                threshold,
                freshness_override,
                connection=owned_connection,
            )
    graph = metadata(connection)
    freshness = (
        freshness_override
        if freshness_override is not None
        else freshness_report(project, database, connection=connection)
    )
    providers = graph.get("providers", [])
    missing_capabilities = {
        item.get("provider", "unknown"): sorted(REQUIRED_L2_CAPABILITIES - set(item.get("capabilities", [])))
        for item in providers
        if REQUIRED_L2_CAPABILITIES - set(item.get("capabilities", []))
    }
    invalid_reasons = []
    expansion_reasons = []
    required_actions = []
    if semantic_slice.get("status") != "ready":
        invalid_reasons.append("entrypoint-resolution-failed")
        required_actions.append("Select an unambiguous stable_id or qualified entrypoint and regenerate the slice.")
    if semantic_slice.get("graph_revision") != graph.get("revision"):
        invalid_reasons.append("graph-revision-mismatch")
        required_actions.append("Regenerate the semantic slice from the active graph revision.")
    if not freshness["fresh"]:
        invalid_reasons.append("source-drift")
        required_actions.append("Rebuild the L2 graph and regenerate context before editing.")
    if missing_capabilities:
        invalid_reasons.append("provider-capability-incomplete")
        required_actions.append("Install or select a provider that passes the full L2 capability probe.")
    confidence = float(semantic_slice.get("confidence", 0.0))
    critical = [item for item in semantic_slice.get("unresolved_edges", []) if item.get("critical")]
    if confidence < threshold:
        expansion_reasons.append("confidence-below-threshold")
        required_actions.append("Expand the slice by the unresolved relation or widen the manual context.")
    if critical:
        expansion_reasons.append("critical-unresolved-edges")
        required_actions.append("Inspect each critical unresolved edge and request targeted context expansion.")
    if semantic_slice.get("truncated"):
        expansion_reasons.append("slice-truncated")
        required_actions.append("Increase depth or item budget for the remaining frontier.")
    if invalid_reasons:
        status = "invalid"
    elif expansion_reasons:
        status = "needs_expansion"
    else:
        status = "accepted"
    return {
        "schema": "ADworkflo.context_preflight.v1",
        "task_id": task_id,
        "status": status,
        "graph_revision": graph.get("revision"),
        "slice_revision": semantic_slice.get("graph_revision"),
        "confidence": confidence,
        "confidence_threshold": threshold,
        "freshness": freshness,
        "provider_capabilities": providers,
        "missing_capabilities": missing_capabilities,
        "invalid_reasons": invalid_reasons,
        "expansion_reasons": expansion_reasons,
        "required_actions": list(dict.fromkeys(required_actions)),
        "critical_unresolved_edges": critical,
        "expansion_history": semantic_slice.get("expansion_history", []),
    }


def _graph_state(database: Path, *, connection: Any | None = None) -> dict[str, Any]:
    if connection is None:
        with connect(database, readonly=True) as owned_connection:
            return _graph_state(database, connection=owned_connection)
    graph = metadata(connection)
    files = {row["path"]: row["sha256"] for row in connection.execute("SELECT path, sha256 FROM files")}
    symbols = {row["stable_id"]: row["file"] for row in connection.execute("SELECT s.stable_id, f.path AS file FROM symbols s JOIN files f ON f.id=s.file_id")}
    calls = {
        (row["file"], row["caller_symbol_id"], row["callee_symbol_id"], row["callee_name"], row["line"])
        for row in connection.execute("SELECT f.path AS file, c.caller_symbol_id, c.callee_symbol_id, c.callee_name, c.line FROM calls c JOIN files f ON f.id=c.file_id")
    }
    references = {
        (row["file"], row["source_symbol_id"], row["symbol_id"], row["name"], row["line"])
        for row in connection.execute("SELECT f.path AS file, r.source_symbol_id, r.symbol_id, r.name, r.line FROM symbol_references r JOIN files f ON f.id=r.file_id")
    }
    imports = {
        (row["file"], row["target_file"], row["module_specifier"], row["imported_name"])
        for row in connection.execute("SELECT f.path AS file, tf.path AS target_file, i.module_specifier, i.imported_name FROM imports i JOIN files f ON f.id=i.file_id LEFT JOIN files tf ON tf.id=i.target_file_id")
    }
    critical_rows = list(connection.execute(
        "SELECT f.path AS file, f.is_test, u.source_symbol_id, u.kind, "
        "u.target, u.reason, u.line FROM unresolved_edges u "
        "JOIN files f ON f.id=u.file_id WHERE u.critical=1"
    ))
    critical = {
        (row["file"], row["source_symbol_id"], row["kind"], row["target"], row["reason"], row["line"])
        for row in critical_rows if not row["is_test"]
    }
    test_critical = {
        (row["file"], row["source_symbol_id"], row["kind"], row["target"], row["reason"], row["line"])
        for row in critical_rows if row["is_test"]
    }
    return {
        "metadata": graph,
        "files": files,
        "symbols": symbols,
        "calls": calls,
        "references": references,
        "imports": imports,
        "critical": critical,
        "test_critical": test_critical,
    }


def _edge_delta(before: set[tuple], after: set[tuple]) -> dict[str, list[list[Any]]]:
    return {
        "added": [list(item) for item in sorted(after - before, key=repr)],
        "removed": [list(item) for item in sorted(before - after, key=repr)],
    }


def _new_critical_edges(before: set[tuple], after: set[tuple]) -> list[list[Any]]:
    before_counts = Counter(item[:-1] for item in before)
    after_by_identity: dict[tuple, list[tuple]] = {}
    for item in after:
        after_by_identity.setdefault(item[:-1], []).append(item)
    added: list[list[Any]] = []
    for identity, records in sorted(after_by_identity.items(), key=repr):
        count = max(0, len(records) - before_counts[identity])
        added.extend(
            [list(item) for item in sorted(records, key=repr)[:count]]
        )
    return added


def _declared_graph_files(
    declared_files: list[str],
    before: dict[str, Any],
    after: dict[str, Any],
) -> list[str]:
    """Return declared paths that belong to the configured graph scope.

    A newly created source file is absent from both graph snapshots until the
    next rebuild.  Scope must therefore be inferred from the stored graph
    configuration, rather than only by intersecting declarations with the
    files currently present in SQLite.
    """
    extension_languages = {
        extension: language
        for language, extensions in LANGUAGE_EXTENSIONS.items()
        for extension in extensions
    }
    configs = [
        before.get("metadata", {}).get("config", {}),
        after.get("metadata", {}).get("config", {}),
    ]
    graph_files = set(before.get("files", {})) | set(after.get("files", {}))
    result: set[str] = set()
    for item in declared_files:
        normalized = item.replace("\\", "/")
        language = extension_languages.get(Path(normalized).suffix.lower())
        if normalized in graph_files or (
            language and any(
                file_in_graph_scope(normalized, language, config)
                for config in configs
            )
        ):
            result.add(normalized)
    return sorted(result)


def _reverse_impact(
    state: dict[str, Any],
    seed_files: set[str],
    depth: int = 12,
    budget: int = 10000,
) -> tuple[set[str], list[dict[str, Any]], bool]:
    symbols_by_file: dict[str, set[str]] = {}
    for symbol_id, file_path in state["symbols"].items():
        symbols_by_file.setdefault(file_path, set()).add(symbol_id)
    symbol_queue = [(symbol_id, 0) for file_path in seed_files for symbol_id in symbols_by_file.get(file_path, set())]
    file_queue = [(file_path, 0) for file_path in seed_files]
    visited_symbols: set[str] = set()
    visited_files: set[str] = set(seed_files)
    boundary: list[dict[str, Any]] = []
    steps = 0

    def add_file(file_path: str | None, distance: int) -> None:
        if not file_path or file_path in visited_files:
            return
        visited_files.add(file_path)
        file_queue.append((file_path, distance))
        for symbol_id in symbols_by_file.get(file_path, set()):
            if symbol_id not in visited_symbols:
                symbol_queue.append((symbol_id, distance))

    while (symbol_queue or file_queue) and steps < budget:
        while symbol_queue and steps < budget:
            symbol_id, distance = symbol_queue.pop(0)
            if symbol_id in visited_symbols:
                continue
            visited_symbols.add(symbol_id)
            steps += 1
            if distance >= depth:
                boundary.append({"kind": "symbol", "target": symbol_id, "reason": "depth-limit"})
                continue
            for file_path, caller, callee, _, _ in state["calls"]:
                if callee == symbol_id:
                    add_file(file_path, distance + 1)
                    if caller and caller not in visited_symbols:
                        symbol_queue.append((caller, distance + 1))
            for file_path, source, target, _, _ in state["references"]:
                if target == symbol_id:
                    add_file(file_path, distance + 1)
                    if source and source not in visited_symbols:
                        symbol_queue.append((source, distance + 1))
        if file_queue and steps < budget:
            target_file, distance = file_queue.pop(0)
            steps += 1
            if distance >= depth:
                boundary.append({"kind": "file", "target": target_file, "reason": "depth-limit"})
                continue
            for source_file, imported_file, _, _ in state["imports"]:
                if imported_file == target_file:
                    add_file(source_file, distance + 1)

    truncated = bool(symbol_queue or file_queue or boundary)
    if symbol_queue or file_queue:
        boundary.append({
            "kind": "frontier",
            "reason": "item-budget",
            "remaining": len(symbol_queue) + len(file_queue),
        })
    return visited_files, boundary, truncated


def post_edit_impact(
    task_id: str,
    baseline_database: Path,
    current_database: Path,
    declared_files: list[str],
    predicted_files: list[str],
) -> dict[str, Any]:
    with graph_locks(
        [baseline_database, current_database], "publish", shared=True,
    ):
        with connect(
            baseline_database, readonly=True, acquire_lease=False,
        ) as baseline_connection, connect(
            current_database, readonly=True, acquire_lease=False,
        ) as current_connection:
            before = _graph_state(
                baseline_database, connection=baseline_connection,
            )
            after = _graph_state(
                current_database, connection=current_connection,
            )
    all_files = set(before["files"]) | set(after["files"])
    changed_files = sorted(path for path in all_files if before["files"].get(path) != after["files"].get(path))
    declared_graph_files = _declared_graph_files(declared_files, before, after)
    same_revision = before["metadata"].get("revision") == after["metadata"].get("revision")
    baseline_reused_after_edit = same_revision and bool(declared_graph_files)
    added_symbols = sorted(set(after["symbols"]) - set(before["symbols"]))
    removed_symbols = sorted(set(before["symbols"]) - set(after["symbols"]))
    calls = _edge_delta(before["calls"], after["calls"])
    references = _edge_delta(before["references"], after["references"])
    imports = _edge_delta(before["imports"], after["imports"])
    new_critical = _new_critical_edges(before["critical"], after["critical"])
    new_test_critical = _new_critical_edges(
        before["test_critical"], after["test_critical"],
    )
    observed_files = set(changed_files)
    before_impact, before_boundary, before_truncated = _reverse_impact(before, set(changed_files))
    after_impact, after_boundary, after_truncated = _reverse_impact(after, set(changed_files))
    observed_files.update(before_impact)
    observed_files.update(after_impact)
    for delta in (calls, references, imports):
        for item in [*delta["added"], *delta["removed"]]:
            if item and item[0]:
                observed_files.add(item[0])
    expected = {item.replace("\\", "/") for item in [*declared_files, *predicted_files]}
    unexpected = sorted(observed_files - expected)
    propagation_truncated = before_truncated or after_truncated
    status = (
        "passed"
        if not unexpected
        and not new_critical
        and not propagation_truncated
        and not baseline_reused_after_edit
        else "failed"
    )
    return {
        "schema": "ADworkflo.impact_report.v1",
        "task_id": task_id,
        "status": status,
        "baseline_revision": before["metadata"].get("revision"),
        "current_revision": after["metadata"].get("revision"),
        "declared_files": sorted(set(declared_files)),
        "predicted_files": sorted(set(predicted_files)),
        "changed_files": changed_files,
        "observed_impact_files": sorted(observed_files),
        "unexpected_impact": unexpected,
        "symbol_delta": {"added": added_symbols, "removed": removed_symbols},
        "edge_delta": {"calls": calls, "references": references, "imports": imports},
        "new_critical_unresolved_edges": new_critical,
        "new_test_critical_unresolved_edges": new_test_critical,
        "propagation": {
            "truncated": propagation_truncated,
            "baseline_boundary": before_boundary,
            "current_boundary": after_boundary,
        },
        "baseline_validation": {
            "same_revision": same_revision,
            "declared_graph_files": declared_graph_files,
            "reused_after_declared_edit": baseline_reused_after_edit,
        },
        "review_required": bool(
            unexpected
            or new_critical
            or new_test_critical
            or propagation_truncated
            or baseline_reused_after_edit
        ),
    }
