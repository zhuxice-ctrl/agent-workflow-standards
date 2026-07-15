from __future__ import annotations

import sqlite3
import threading
from collections import deque
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterator

from .database import connect, metadata


def row_dict(row: Any) -> dict[str, Any]:
    return dict(row) if row is not None else {}


class GraphQuery:
    def __init__(self, database: Path) -> None:
        self.database = database.resolve()
        self._connection: sqlite3.Connection | None = None
        self._pinned_metadata: dict[str, Any] | None = None
        self._session_depth = 0
        self._session_lock = threading.RLock()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("GraphQuery connection is only available inside a read session")
        return self._connection

    @contextmanager
    def read_session(self) -> Iterator[GraphQuery]:
        with self._session_lock:
            if self._connection is not None:
                self._session_depth += 1
                try:
                    yield self
                finally:
                    self._session_depth -= 1
                return

            with connect(self.database, readonly=True) as connection:
                self._connection = connection
                self._session_depth = 1
                try:
                    self._pinned_metadata = metadata(connection)
                    yield self
                finally:
                    self._pinned_metadata = None
                    self._connection = None
                    self._session_depth = 0

    @contextmanager
    def _connection_scope(self) -> Iterator[sqlite3.Connection]:
        with self.read_session():
            yield self.connection

    def graph_metadata(self) -> dict[str, Any]:
        with self.read_session():
            return self._graph_metadata()

    def _graph_metadata(self) -> dict[str, Any]:
        if self._pinned_metadata is None:
            raise RuntimeError("GraphQuery metadata is only available inside a read session")
        return deepcopy(self._pinned_metadata)

    def capabilities(self) -> dict[str, Any]:
        with self.read_session():
            return self._capabilities()

    def _capabilities(self) -> dict[str, Any]:
        graph = self.graph_metadata()
        providers = graph.get("providers", [])
        intersection = None
        for provider in providers:
            values = set(provider.get("capabilities", []))
            intersection = values if intersection is None else intersection & values
        return {
            "schema": "ADworkflo.codegraph.capabilities.v1",
            "revision": graph.get("revision"),
            "providers": providers,
            "capabilities": sorted(intersection or []),
        }

    @staticmethod
    def _symbol_record(row: Any) -> dict[str, Any]:
        record = dict(row)
        record["location"] = f"{record['file']}:{record['start_line']}"
        return record

    def resolve_symbol(self, value: str) -> dict[str, Any]:
        with self.read_session():
            return self._resolve_symbol(value)

    def _resolve_symbol(self, value: str) -> dict[str, Any]:
        with self._connection_scope() as connection:
            rows = list(connection.execute(
                """SELECT s.stable_id, s.symbol_group_id, s.declaration_index, s.runtime_effective,
                          s.name, s.qualified_name, s.kind, s.start_line, s.end_line,
                          f.path AS file, f.sha256
                   FROM symbols s JOIN files f ON f.id=s.file_id
                   WHERE s.stable_id=? OR s.qualified_name=? OR s.name=?
                   ORDER BY CASE WHEN s.stable_id=? THEN 0 WHEN s.qualified_name=? AND s.runtime_effective=1 THEN 1
                                 WHEN s.qualified_name=? THEN 2 ELSE 3 END,
                            s.qualified_name, s.declaration_index DESC""",
                (value, value, value, value, value, value),
            ))
        exact_stable = [row for row in rows if row["stable_id"] == value]
        exact_qualified = [row for row in rows if row["qualified_name"] == value and row["runtime_effective"]]
        selected = exact_stable or exact_qualified or rows
        candidates = [self._symbol_record(row) for row in selected]
        if not candidates:
            return {"status": "not_found", "query": value, "candidates": []}
        if len(candidates) > 1:
            return {"status": "ambiguous", "query": value, "candidates": candidates}
        return {"status": "resolved", "query": value, "symbol": candidates[0], "candidates": candidates}

    def find_references(self, value: str) -> dict[str, Any]:
        with self.read_session():
            return self._find_references(value)

    def _find_references(self, value: str) -> dict[str, Any]:
        resolved = self.resolve_symbol(value)
        if resolved["status"] != "resolved":
            return resolved
        symbol = resolved["symbol"]
        with self._connection_scope() as connection:
            records = [dict(row) for row in connection.execute(
                """SELECT f.path AS file, r.line, r.column_no AS column, r.name, r.context, r.resolution,
                          r.source_symbol_id, source.qualified_name AS source_symbol
                   FROM symbol_references r JOIN files f ON f.id=r.file_id
                   LEFT JOIN symbols source ON source.stable_id=r.source_symbol_id
                   WHERE r.symbol_id=? ORDER BY f.path, r.line, r.column_no""",
                (symbol["stable_id"],),
            )]
        return self._result("find-references", {"symbol": symbol, "references": records})

    def callers(self, value: str) -> dict[str, Any]:
        with self.read_session():
            return self._call_query(value, callers=True)

    def callees(self, value: str) -> dict[str, Any]:
        with self.read_session():
            return self._call_query(value, callers=False)

    def _call_query(self, value: str, callers: bool) -> dict[str, Any]:
        resolved = self.resolve_symbol(value)
        if resolved["status"] != "resolved":
            return resolved
        symbol = resolved["symbol"]
        if callers:
            where, target = "c.callee_symbol_id=?", "c.caller_symbol_id"
            name = "callers"
        else:
            where, target = "c.caller_symbol_id=?", "c.callee_symbol_id"
            name = "callees"
        with self._connection_scope() as connection:
            records = [dict(row) for row in connection.execute(
                f"""SELECT f.path AS file, c.line, c.column_no AS column, c.callee_name, c.resolution,
                           c.confidence, target.stable_id, target.qualified_name, target.kind,
                           tf.path AS target_file, target.start_line
                    FROM calls c JOIN files f ON f.id=c.file_id
                    LEFT JOIN symbols target ON target.stable_id={target}
                    LEFT JOIN files tf ON tf.id=target.file_id
                    WHERE {where} ORDER BY f.path, c.line""",
                (symbol["stable_id"],),
            )]
        return self._result(name, {"symbol": symbol, name: records})

    def find_importers(self, file_path: str) -> dict[str, Any]:
        with self.read_session():
            return self._find_importers(file_path)

    def _find_importers(self, file_path: str) -> dict[str, Any]:
        normalized = file_path.replace("\\", "/")
        with self._connection_scope() as connection:
            target = connection.execute("SELECT id, path FROM files WHERE path=?", (normalized,)).fetchone()
            if not target:
                return {"status": "not_found", "query": normalized, "candidates": []}
            records = [dict(row) for row in connection.execute(
                """SELECT f.path AS file, i.module_specifier, i.imported_name, i.local_name,
                          i.line, i.resolution
                   FROM imports i JOIN files f ON f.id=i.file_id
                   WHERE i.target_file_id=? ORDER BY f.path, i.line""",
                (target["id"],),
            )]
        return self._result("find-importers", {"file": normalized, "importers": records})

    def tests_for(self, value: str) -> dict[str, Any]:
        with self.read_session():
            return self._tests_for(value)

    def _tests_for(self, value: str) -> dict[str, Any]:
        resolved = self.resolve_symbol(value)
        symbol_id = resolved.get("symbol", {}).get("stable_id") if resolved["status"] == "resolved" else None
        normalized = value.replace("\\", "/")
        with self._connection_scope() as connection:
            file_row = connection.execute("SELECT id, path FROM files WHERE path=?", (normalized,)).fetchone()
            records: dict[str, set[str]] = {}
            if symbol_id:
                for row in connection.execute(
                    """SELECT DISTINCT f.path, 'symbol-call-or-reference' AS reason
                       FROM files f
                       LEFT JOIN calls c ON c.file_id=f.id AND c.callee_symbol_id=?
                       LEFT JOIN symbol_references r ON r.file_id=f.id AND r.symbol_id=?
                       WHERE f.is_test=1 AND (c.id IS NOT NULL OR r.id IS NOT NULL)""",
                    (symbol_id, symbol_id),
                ):
                    records.setdefault(row["path"], set()).add(row["reason"])
            if file_row:
                for row in connection.execute(
                    """SELECT DISTINCT f.path, 'imports-target-file' AS reason
                       FROM imports i JOIN files f ON f.id=i.file_id
                       WHERE f.is_test=1 AND i.target_file_id=?""",
                    (file_row["id"],),
                ):
                    records.setdefault(row["path"], set()).add(row["reason"])
        return self._result("tests-for", {
            "query": value,
            "tests": [{"file": key, "reasons": sorted(values)} for key, values in sorted(records.items())],
        })

    def impact(self, value: str, depth: int = 3, budget: int = 200) -> dict[str, Any]:
        with self.read_session():
            return self._impact(value, depth, budget)

    def _impact(self, value: str, depth: int = 3, budget: int = 200) -> dict[str, Any]:
        if depth < 0 or budget < 1:
            raise ValueError("depth must be non-negative and budget must be positive")
        resolved = self.resolve_symbol(value)
        with self._connection_scope() as connection:
            file_row = connection.execute("SELECT id, path FROM files WHERE path=?", (value.replace("\\", "/"),)).fetchone()
            if resolved["status"] == "resolved":
                seeds = [resolved["symbol"]["stable_id"]]
                seed_files = {resolved["symbol"]["file"]}
                target = {"type": "symbol", "value": resolved["symbol"]}
            elif file_row:
                seeds = [row["stable_id"] for row in connection.execute("SELECT stable_id FROM symbols WHERE file_id=?", (file_row["id"],))]
                seed_files = {file_row["path"]}
                target = {"type": "file", "value": file_row["path"]}
            else:
                return resolved if resolved["status"] != "ambiguous" else resolved

            queue = deque((symbol_id, 0, [f"seed:{value}"]) for symbol_id in seeds)
            seen_symbols = set(seeds)
            affected: dict[str, dict[str, Any]] = {
                item: {"file": item, "distance": 0, "reason_path": [f"seed:{value}"]} for item in seed_files
            }
            boundary: list[dict[str, Any]] = []
            visited = 0
            while queue and visited < budget:
                symbol_id, distance, path_reason = queue.popleft()
                visited += 1
                if distance >= depth:
                    boundary.append({"symbol_id": symbol_id, "reason": "depth-limit", "distance": distance})
                    continue
                reverse_edges = list(connection.execute(
                    """SELECT DISTINCT source.stable_id, source.qualified_name, f.path AS file, 'caller' AS relation
                       FROM calls edge JOIN symbols source ON source.stable_id=edge.caller_symbol_id
                       JOIN files f ON f.id=source.file_id WHERE edge.callee_symbol_id=?
                       UNION
                       SELECT DISTINCT source.stable_id, source.qualified_name, f.path AS file, 'reference' AS relation
                       FROM symbol_references edge JOIN symbols source ON source.stable_id=edge.source_symbol_id
                       JOIN files f ON f.id=source.file_id WHERE edge.symbol_id=?""",
                    (symbol_id, symbol_id),
                ))
                for edge in reverse_edges:
                    next_reason = [*path_reason, f"{edge['relation']}:{edge['qualified_name']}"]
                    existing = affected.get(edge["file"])
                    if not existing or distance + 1 < existing["distance"]:
                        affected[edge["file"]] = {"file": edge["file"], "distance": distance + 1, "reason_path": next_reason}
                    if edge["stable_id"] not in seen_symbols:
                        seen_symbols.add(edge["stable_id"])
                        queue.append((edge["stable_id"], distance + 1, next_reason))

            file_queue = deque((record["file"], record["distance"], record["reason_path"]) for record in affected.values())
            seen_files = set(affected)
            while file_queue and visited < budget:
                target_file, distance, path_reason = file_queue.popleft()
                visited += 1
                if distance >= depth:
                    continue
                for edge in connection.execute(
                    """SELECT source.path AS file FROM imports i
                       JOIN files source ON source.id=i.file_id JOIN files target ON target.id=i.target_file_id
                       WHERE target.path=?""",
                    (target_file,),
                ):
                    if edge["file"] in seen_files:
                        continue
                    seen_files.add(edge["file"])
                    reason = [*path_reason, f"importer:{edge['file']}"]
                    affected[edge["file"]] = {"file": edge["file"], "distance": distance + 1, "reason_path": reason}
                    file_queue.append((edge["file"], distance + 1, reason))

            truncated = bool(queue or file_queue)
            if truncated:
                boundary.append({"reason": "item-budget", "remaining_frontier": len(queue) + len(file_queue)})
            records = sorted(affected.values(), key=lambda item: (item["distance"], item["file"]))
            tests = [item for item in records if self._is_test_file(connection, item["file"])]
            direct = [item for item in records if item["distance"] <= 1 and item not in tests]
            transitive = [item for item in records if item["distance"] > 1 and item not in tests]
            placeholders = ",".join("?" for _ in affected) or "NULL"
            unresolved = [dict(row) for row in connection.execute(
                f"""SELECT f.path AS file, u.source_symbol_id, u.kind, u.target, u.line, u.reason, u.critical
                    FROM unresolved_edges u JOIN files f ON f.id=u.file_id WHERE f.path IN ({placeholders})""",
                tuple(affected),
            )]
        return self._result("impact", {
            "target": target,
            "depth": depth,
            "budget": budget,
            "direct": direct,
            "transitive": transitive,
            "tests": tests,
            "boundary": boundary,
            "unresolved": unresolved,
            "truncated": truncated,
            "predicted_files": [item["file"] for item in records],
        })

    @staticmethod
    def _is_test_file(connection: Any, file_path: str) -> bool:
        row = connection.execute("SELECT is_test FROM files WHERE path=?", (file_path,)).fetchone()
        return bool(row and row["is_test"])

    def slice(
        self,
        entrypoints: list[str],
        depth: int = 2,
        budget: int = 100,
        include_callers: bool = False,
        expansion_history: list[dict[str, Any]] | None = None,
        additional_seeds: list[str] | None = None,
    ) -> dict[str, Any]:
        with self.read_session():
            return self._slice(
                entrypoints,
                depth,
                budget,
                include_callers,
                expansion_history,
                additional_seeds,
            )

    def _slice(
        self,
        entrypoints: list[str],
        depth: int = 2,
        budget: int = 100,
        include_callers: bool = False,
        expansion_history: list[dict[str, Any]] | None = None,
        additional_seeds: list[str] | None = None,
    ) -> dict[str, Any]:
        resolutions = [self.resolve_symbol(item) for item in entrypoints]
        resolution_errors = [item for item in resolutions if item["status"] != "resolved"]
        graph = self.graph_metadata()
        if resolution_errors:
            return {
                "schema": "ADworkflo.semantic_slice.v1", "status": "invalid",
                "graph_revision": graph.get("revision"), "entrypoints": entrypoints,
                "entrypoint_resolutions": resolutions, "included_symbols": [], "included_files": [],
                "boundary_symbols": [], "excluded": [], "unresolved_edges": [], "likely_tests": [],
                "coverage": {"resolved_call_ratio": 0.0, "resolved_entrypoint_ratio": (len(resolutions) - len(resolution_errors)) / max(1, len(resolutions))},
                "confidence": 0.0, "truncated": False, "source_hashes": {},
                "provenance": graph.get("providers", []), "expansion_history": expansion_history or [],
            }
        seed_ids = list(dict.fromkeys([
            *[item["symbol"]["stable_id"] for item in resolutions],
            *(additional_seeds or []),
        ]))
        with self._connection_scope() as connection:
            queue = deque((item, 0) for item in seed_ids)
            included = set(seed_ids)
            distances = {item: 0 for item in seed_ids}
            boundary: list[dict[str, Any]] = []
            visited = 0
            while queue and visited < budget:
                symbol_id, distance = queue.popleft()
                visited += 1
                rows = list(connection.execute("SELECT callee_symbol_id AS target, 'callee' AS relation FROM calls WHERE caller_symbol_id=? AND callee_symbol_id IS NOT NULL", (symbol_id,)))
                rows.extend(connection.execute(
                    "SELECT symbol_id AS target, 'reference' AS relation FROM symbol_references WHERE source_symbol_id=? AND symbol_id IS NOT NULL",
                    (symbol_id,),
                ))
                if include_callers:
                    rows.extend(connection.execute("SELECT caller_symbol_id AS target, 'caller' AS relation FROM calls WHERE callee_symbol_id=? AND caller_symbol_id IS NOT NULL", (symbol_id,)))
                for edge in rows:
                    target = edge["target"]
                    if target in included:
                        continue
                    if distance >= depth:
                        boundary.append({"symbol_id": target, "relation": edge["relation"], "reason": "depth-limit", "from": symbol_id})
                        continue
                    included.add(target)
                    distances[target] = distance + 1
                    queue.append((target, distance + 1))
            truncated = bool(queue or boundary)
            if truncated:
                boundary.append({"reason": "item-budget", "remaining_frontier": len(queue)})

            placeholders = ",".join("?" for _ in included)
            symbols = [dict(row) for row in connection.execute(
                f"""SELECT s.stable_id, s.name, s.qualified_name, s.kind, f.path AS file,
                           s.start_line, s.end_line, f.sha256
                    FROM symbols s JOIN files f ON f.id=s.file_id
                    WHERE s.stable_id IN ({placeholders}) ORDER BY f.path, s.start_line""",
                tuple(sorted(included)),
            )]
            for item in symbols:
                item["distance"] = distances[item["stable_id"]]
            included_files = sorted({item["file"] for item in symbols})
            source_hashes = {item["file"]: item["sha256"] for item in symbols}
            unresolved = [dict(row) for row in connection.execute(
                f"""SELECT f.path AS file, u.source_symbol_id, u.kind, u.target, u.line, u.reason, u.critical
                    FROM unresolved_edges u JOIN files f ON f.id=u.file_id
                    WHERE u.source_symbol_id IN ({placeholders}) ORDER BY f.path, u.line""",
                tuple(sorted(included)),
            )]
            call_counts = connection.execute(
                f"""SELECT COUNT(*) AS total,
                           SUM(CASE WHEN callee_symbol_id IS NOT NULL OR resolution IN
                             ('builtin', 'external', 'external-import', 'external-import-attribute')
                             OR resolution IN ('external-typed-attribute', 'external-inherited-attribute')
                           THEN 1.0 WHEN resolution = 'opaque-library-method' THEN 0.75 ELSE 0 END) AS resolved
                    FROM calls WHERE caller_symbol_id IN ({placeholders})""",
                tuple(sorted(included)),
            ).fetchone()
            total_calls = call_counts["total"] or 0
            resolved_calls = call_counts["resolved"] or 0
            resolved_ratio = resolved_calls / total_calls if total_calls else 1.0
            reference_counts = connection.execute(
                f"""SELECT COUNT(*) AS total,
                           SUM(CASE WHEN symbol_id IS NOT NULL OR resolution IN
                             ('builtin', 'external', 'external-import', 'external-import-attribute',
                              'external-typed-attribute', 'external-inherited-attribute', 'local-value')
                           THEN 1.0 ELSE 0 END) AS resolved
                    FROM symbol_references WHERE source_symbol_id IN ({placeholders})""",
                tuple(sorted(included)),
            ).fetchone()
            total_references = reference_counts["total"] or 0
            resolved_references = reference_counts["resolved"] or 0
            resolved_reference_ratio = resolved_references / total_references if total_references else 1.0
            likely_tests = self._slice_tests(connection, included, included_files)
            all_files = {row["path"] for row in connection.execute("SELECT path FROM files")}
            excluded = sorted(all_files - set(included_files) - set(likely_tests))
        critical_count = sum(bool(item["critical"]) for item in unresolved)
        total_edges = total_calls + total_references
        resolved_edge_ratio = (
            (resolved_calls + resolved_references) / total_edges if total_edges else 1.0
        )
        confidence = resolved_edge_ratio
        confidence -= min(0.40, critical_count * 0.15)
        confidence -= 0.20 if truncated else 0.0
        confidence = round(max(0.0, min(1.0, confidence)), 3)
        return {
            "schema": "ADworkflo.semantic_slice.v1",
            "status": "ready",
            "graph_revision": graph.get("revision"),
            "entrypoints": entrypoints,
            "entrypoint_resolutions": resolutions,
            "included_symbols": symbols,
            "included_files": included_files,
            "boundary_symbols": boundary,
            "excluded": excluded,
            "unresolved_edges": unresolved,
            "likely_tests": likely_tests,
            "coverage": {
                "resolved_call_ratio": round(resolved_ratio, 3),
                "resolved_reference_ratio": round(resolved_reference_ratio, 3),
                "resolved_edge_ratio": round(resolved_edge_ratio, 3),
                "resolved_entrypoint_ratio": 1.0,
            },
            "confidence": confidence,
            "truncated": truncated,
            "source_hashes": source_hashes,
            "provenance": graph.get("providers", []),
            "parameters": {
                "depth": depth,
                "budget": budget,
                "include_callers": include_callers,
                "additional_seeds": additional_seeds or [],
            },
            "expansion_history": expansion_history or [],
        }

    @staticmethod
    def _slice_tests(connection: Any, symbols: set[str], files: list[str]) -> list[str]:
        tests: set[str] = set()
        symbol_placeholders = ",".join("?" for _ in symbols)
        file_placeholders = ",".join("?" for _ in files)
        if symbols:
            for row in connection.execute(
                f"""SELECT DISTINCT f.path FROM files f
                    LEFT JOIN calls c ON c.file_id=f.id AND c.callee_symbol_id IN ({symbol_placeholders})
                    LEFT JOIN symbol_references r ON r.file_id=f.id AND r.symbol_id IN ({symbol_placeholders})
                    WHERE f.is_test=1 AND (c.id IS NOT NULL OR r.id IS NOT NULL)""",
                (*sorted(symbols), *sorted(symbols)),
            ):
                tests.add(row["path"])
        if files:
            for row in connection.execute(
                f"""SELECT DISTINCT source.path FROM imports i JOIN files source ON source.id=i.file_id
                    JOIN files target ON target.id=i.target_file_id
                    WHERE source.is_test=1 AND target.path IN ({file_placeholders})""",
                tuple(files),
            ):
                tests.add(row["path"])
        return sorted(tests)

    def expand(self, semantic_slice: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        with self.read_session():
            return self._expand(semantic_slice, request)

    def _expand(self, semantic_slice: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        if semantic_slice.get("graph_revision") != self.graph_metadata().get("revision"):
            raise ValueError("semantic slice graph revision is stale")
        relation = request.get("relation", "callees")
        if relation not in {"callees", "callers", "both"}:
            raise ValueError("expansion relation must be callees, callers, or both")
        previous = semantic_slice.get("parameters", {})
        target_ids: list[str] = []
        target_resolutions: list[dict[str, Any]] = []
        with self._connection_scope() as connection:
            for raw_target in request.get("targets", []):
                target = str(raw_target).replace("\\", "/")
                file_row = connection.execute("SELECT id, path FROM files WHERE path=?", (target,)).fetchone()
                if file_row:
                    rows = list(connection.execute(
                        "SELECT stable_id, qualified_name FROM symbols WHERE file_id=? AND runtime_effective=1 ORDER BY start_line",
                        (file_row["id"],),
                    ))
                    if not rows:
                        raise ValueError(f"expansion target file has no symbols: {target}")
                    ids = [row["stable_id"] for row in rows]
                    target_ids.extend(ids)
                    target_resolutions.append({"target": raw_target, "status": "resolved_file", "symbol_ids": ids})
                    continue
                resolved = self.resolve_symbol(str(raw_target))
                if resolved["status"] != "resolved":
                    raise ValueError(f"expansion target {raw_target!r} is {resolved['status']}")
                symbol_id = resolved["symbol"]["stable_id"]
                target_ids.append(symbol_id)
                target_resolutions.append({"target": raw_target, "status": "resolved_symbol", "symbol_ids": [symbol_id]})
        target_ids = list(dict.fromkeys([*previous.get("additional_seeds", []), *target_ids]))
        applied_request = {**request, "target_resolutions": target_resolutions, "applied": True}
        history = [*semantic_slice.get("expansion_history", []), applied_request]
        expanded = self.slice(
            semantic_slice.get("entrypoints", []),
            depth=max(int(previous.get("depth", 2)), int(request.get("depth", 2))),
            budget=max(int(previous.get("budget", 100)), int(request.get("budget", 100))),
            include_callers=bool(previous.get("include_callers")) or relation in {"callers", "both"},
            expansion_history=history,
            additional_seeds=target_ids,
        )
        included_ids = {item["stable_id"] for item in expanded.get("included_symbols", [])}
        missing_targets = sorted(set(target_ids) - included_ids)
        if missing_targets:
            raise ValueError(f"expansion targets were not included: {', '.join(missing_targets)}")
        expanded["expansion_targets"] = target_resolutions
        predicted: set[str] = set()
        for resolution in expanded.get("entrypoint_resolutions", []):
            if resolution.get("status") == "resolved":
                result = self.impact(
                    resolution["symbol"]["stable_id"],
                    depth=max(3, int(request.get("depth", 2))),
                    budget=max(200, int(request.get("budget", 100))),
                )
                predicted.update(result.get("predicted_files", []))
        expanded["predicted_impact_files"] = sorted(predicted)
        return expanded

    def summarize_file(self, file_path: str) -> dict[str, Any]:
        with self.read_session():
            return self._summarize_file(file_path)

    def _summarize_file(self, file_path: str) -> dict[str, Any]:
        normalized = file_path.replace("\\", "/")
        with self._connection_scope() as connection:
            file_row = connection.execute("SELECT * FROM files WHERE path=?", (normalized,)).fetchone()
            if not file_row:
                return {"status": "not_found", "path": normalized}
            symbols = [dict(row) for row in connection.execute(
                "SELECT stable_id, qualified_name, kind, start_line, end_line FROM symbols WHERE file_id=? ORDER BY start_line",
                (file_row["id"],),
            )]
            imports = [dict(row) for row in connection.execute(
                "SELECT module_specifier, imported_name, local_name, resolution FROM imports WHERE file_id=? ORDER BY line",
                (file_row["id"],),
            )]
            unresolved = [dict(row) for row in connection.execute(
                "SELECT kind, target, line, reason, critical FROM unresolved_edges WHERE file_id=? ORDER BY line",
                (file_row["id"],),
            )]
        return self._result("summarize-file", {"file": dict(file_row), "symbols": symbols, "imports": imports, "unresolved": unresolved})

    def _result(self, query: str, payload: dict[str, Any]) -> dict[str, Any]:
        graph = self.graph_metadata()
        return {
            "schema": "ADworkflo.codegraph.query_result.v1",
            "status": "ok",
            "query": query,
            "graph_revision": graph.get("revision"),
            "provenance": graph.get("providers", []),
            **payload,
        }
