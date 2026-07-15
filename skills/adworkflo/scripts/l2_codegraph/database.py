from __future__ import annotations

import errno
import json
import os
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .model import (
    LANGUAGE_EXTENSIONS, file_in_graph_scope, graph_revision, read_source,
    load_graph_config, sha256_text, validate_provider_result,
)
from .locking import (
    GraphLockLease, GraphLockTimeout, acquire_graph_lock, graph_lock, graph_locks,
)


SCHEMA_VERSION = "ADworkflo.codegraph.sqlite.v1"


class CandidateIntegrityError(ValueError):
    code = "candidate-integrity-failed"
    retryable = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
        }


class GraphPublicationError(OSError):
    code = "graph-publication-failed"
    retryable = True

    def __init__(self, active: Path, revision: str, stage: str, cause: BaseException) -> None:
        self.active = active.resolve()
        self.revision = revision
        self.stage = stage
        self.cause = cause
        super().__init__(
            f"graph-publication-failed: stage={stage} active={self.active} revision={revision}: {cause}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "active": str(self.active),
            "revision": self.revision,
            "stage": self.stage,
            "retryable": self.retryable,
        }


class SourceChangedDuringBuild(RuntimeError):
    code = "source-changed-during-build"
    retryable = True

    def __init__(self, project: Path, attempts: int) -> None:
        self.project = project.resolve()
        self.attempts = attempts
        super().__init__(
            f"{self.code}: source or codegraph config changed during {attempts} "
            f"build attempts for {self.project}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": str(self),
            "project": str(self.project),
            "attempts": self.attempts,
            "retryable": self.retryable,
        }


def graph_error_payload(error: BaseException) -> dict[str, Any] | None:
    if isinstance(error, CandidateIntegrityError):
        return CandidateIntegrityError.as_dict(error)
    if isinstance(error, GraphLockTimeout):
        return GraphLockTimeout.as_dict(error)
    if isinstance(error, GraphPublicationError):
        return GraphPublicationError.as_dict(error)
    if isinstance(error, SourceChangedDuringBuild):
        return SourceChangedDuringBuild.as_dict(error)
    return None


DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE revisions (
  revision TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  providers_json TEXT NOT NULL,
  complete INTEGER NOT NULL CHECK (complete IN (0, 1))
);
CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL UNIQUE,
  language TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  mtime_ns INTEGER NOT NULL,
  is_test INTEGER NOT NULL CHECK (is_test IN (0, 1)),
  module TEXT,
  provider TEXT NOT NULL
);
CREATE TABLE modules (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  language TEXT NOT NULL,
  UNIQUE(name, file_id)
);
CREATE TABLE symbols (
  id INTEGER PRIMARY KEY,
  stable_id TEXT NOT NULL UNIQUE,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  module TEXT NOT NULL,
  name TEXT NOT NULL,
  qualified_name TEXT NOT NULL,
  local_qualified_name TEXT,
  kind TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  start_column INTEGER NOT NULL DEFAULT 0,
  end_line INTEGER NOT NULL,
  end_column INTEGER NOT NULL DEFAULT 0,
  scope_symbol_id TEXT,
  exported INTEGER NOT NULL DEFAULT 0,
  signature TEXT
  ,symbol_group_id TEXT
  ,declaration_index INTEGER NOT NULL DEFAULT 0
  ,runtime_effective INTEGER NOT NULL DEFAULT 1 CHECK (runtime_effective IN (0, 1))
);
CREATE TABLE symbol_references (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  source_symbol_id TEXT,
  symbol_id TEXT,
  name TEXT NOT NULL,
  line INTEGER NOT NULL,
  column_no INTEGER NOT NULL DEFAULT 0,
  context TEXT NOT NULL,
  resolution TEXT NOT NULL
);
CREATE TABLE calls (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  caller_symbol_id TEXT,
  callee_symbol_id TEXT,
  callee_name TEXT NOT NULL,
  line INTEGER NOT NULL,
  column_no INTEGER NOT NULL DEFAULT 0,
  resolution TEXT NOT NULL,
  confidence REAL NOT NULL
);
CREATE TABLE imports (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  target_file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
  module_specifier TEXT NOT NULL,
  imported_name TEXT,
  local_name TEXT,
  line INTEGER NOT NULL,
  column_no INTEGER NOT NULL DEFAULT 0,
  resolution TEXT NOT NULL
);
CREATE TABLE tests (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE
);
CREATE TABLE unresolved_edges (
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  source_symbol_id TEXT,
  kind TEXT NOT NULL,
  target TEXT NOT NULL,
  line INTEGER NOT NULL,
  column_no INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL,
  critical INTEGER NOT NULL CHECK (critical IN (0, 1))
);
CREATE TABLE diagnostics (
  id INTEGER PRIMARY KEY,
  file_id INTEGER REFERENCES files(id) ON DELETE CASCADE,
  severity TEXT NOT NULL,
  kind TEXT NOT NULL,
  line INTEGER NOT NULL,
  message TEXT NOT NULL
);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_qualified ON symbols(qualified_name);
CREATE INDEX idx_refs_symbol ON symbol_references(symbol_id);
CREATE INDEX idx_refs_source ON symbol_references(source_symbol_id);
CREATE INDEX idx_calls_caller ON calls(caller_symbol_id);
CREATE INDEX idx_calls_callee ON calls(callee_symbol_id);
CREATE INDEX idx_imports_target ON imports(target_file_id);
CREATE INDEX idx_unresolved_source ON unresolved_edges(source_symbol_id);
"""


class ClosingConnection(sqlite3.Connection):
    _graph_lease: GraphLockLease | None = None

    def attach_graph_lease(self, lease: GraphLockLease) -> None:
        self._graph_lease = lease

    def close(self) -> None:
        lease = self._graph_lease
        self._graph_lease = None
        try:
            super().close()
        finally:
            if lease is not None:
                lease.release()

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def connect(
    path: Path,
    readonly: bool = False,
    *,
    acquire_lease: bool = True,
    lock_timeout: float | None = None,
) -> sqlite3.Connection:
    path = path.resolve()
    lease = (
        acquire_graph_lock(
            path, "publish", shared=True, timeout=lock_timeout,
        )
        if readonly and acquire_lease else None
    )
    connection: ClosingConnection | None = None
    try:
        if readonly:
            connection = sqlite3.connect(
                f"file:{path.as_posix()}?mode=ro", uri=True, factory=ClosingConnection,
            )
        else:
            connection = sqlite3.connect(path, factory=ClosingConnection)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        try:
            if connection is not None:
                connection.close()
        finally:
            if lease is not None:
                GraphLockLease.release(lease)
        raise
    if lease is not None:
        connection.attach_graph_lease(lease)
    return connection


def _merge_files(results: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for result in results:
        for record in result["files"]:
            existing = merged.get(record["path"])
            if existing and existing["sha256"] != record["sha256"]:
                raise ValueError(f"providers disagree on source hash for {record['path']}")
            merged[record["path"]] = record
    return [merged[key] for key in sorted(merged)]


_SOURCE_EXCLUDE_DIRS = {
    ".git", ".adworkflow", ".codegraph", "node_modules", ".venv", "venv",
    "dist", "build", "coverage", ".next", ".turbo", "__pycache__",
}


def _provider_source_state(
    project: Path,
    provider_results: list[dict[str, Any]],
    config: dict[str, Any],
) -> tuple[dict[str, str], dict[str, str]]:
    expected = {
        record["path"]: record["sha256"]
        for result in provider_results
        for record in result["files"]
    }
    handled_languages = {
        language
        for result in provider_results
        for language in (
            result.get("languages")
            or {record["language"] for record in result.get("files", [])}
        )
    }
    extension_languages = {
        extension: language
        for language, extensions in LANGUAGE_EXTENSIONS.items()
        for extension in extensions
    }
    current: dict[str, str] = {}
    for root, dirs, files in os.walk(project.resolve()):
        dirs[:] = [item for item in dirs if item not in _SOURCE_EXCLUDE_DIRS]
        for name in files:
            path = Path(root) / name
            language = extension_languages.get(path.suffix.lower())
            if language not in handled_languages:
                continue
            relative = path.resolve().relative_to(project.resolve()).as_posix()
            if file_in_graph_scope(relative, language, config):
                current[relative] = sha256_text(read_source(path))
    return expected, current


def validate_provider_source_state(
    project: Path,
    provider_results: list[dict[str, Any]],
    config: dict[str, Any],
) -> None:
    try:
        expected, current = _provider_source_state(
            project, provider_results, config,
        )
    except OSError as error:
        raise SourceChangedDuringBuild(project, 1) from error
    if expected != current:
        raise SourceChangedDuringBuild(project, 1)


def _insert_records(connection: sqlite3.Connection, results: list[dict[str, Any]], revision: str, config: dict[str, Any]) -> None:
    files = _merge_files(results)
    providers = [{
        "provider": result["provider"],
        "version": result.get("version", "unknown"),
        "implementation_identity": result.get("implementation_identity", "unknown"),
        "languages": result.get("languages", []),
        "capabilities": result.get("capabilities", []),
    } for result in results]
    source_hash = graph_revision(files, [], {})
    now = datetime.now(timezone.utc).isoformat()
    metadata = {
        "schema": SCHEMA_VERSION,
        "revision": revision,
        "created_at": now,
        "providers": json.dumps(providers, sort_keys=True),
        "config": json.dumps(config, sort_keys=True),
    }
    connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items())
    connection.execute(
        "INSERT INTO revisions(revision, created_at, source_hash, providers_json, complete) VALUES (?, ?, ?, ?, 1)",
        (revision, now, source_hash, json.dumps(providers, sort_keys=True)),
    )
    connection.executemany(
        "INSERT INTO files(path, language, sha256, mtime_ns, is_test, module, provider) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(item["path"], item["language"], item["sha256"], item.get("mtime_ns", 0), int(item.get("is_test", False)), item.get("module"), item["provider"]) for item in files],
    )
    file_ids = {row["path"]: row["id"] for row in connection.execute("SELECT id, path FROM files")}

    for result in results:
        connection.executemany(
            "INSERT OR IGNORE INTO modules(name, file_id, language) VALUES (?, ?, ?)",
            [(item["name"], file_ids[item["file"]], item["language"]) for item in result["modules"]],
        )
        connection.executemany(
            """INSERT INTO symbols(stable_id, file_id, module, name, qualified_name, local_qualified_name, kind,
               start_line, start_column, end_line, end_column, scope_symbol_id, exported, signature,
               symbol_group_id, declaration_index, runtime_effective)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(
                item["stable_id"], file_ids[item["file"]], item["module"], item["name"], item["qualified_name"],
                item.get("local_qualified_name"), item["kind"], item["start_line"], item.get("start_column", 0),
                item["end_line"], item.get("end_column", 0), item.get("scope_symbol_id"), int(item.get("exported", False)),
                item.get("signature"), item.get("symbol_group_id", item["stable_id"]),
                int(item.get("declaration_index", 0)), int(item.get("runtime_effective", True)),
            ) for item in result["symbols"]],
        )
        connection.executemany(
            """INSERT INTO symbol_references(file_id, source_symbol_id, symbol_id, name, line, column_no, context, resolution)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_ids[item["file"]], item.get("source_symbol_id"), item.get("symbol_id"), item["name"], item["line"], item.get("column", 0), item["context"], item["resolution"]) for item in result["references"]],
        )
        connection.executemany(
            """INSERT INTO calls(file_id, caller_symbol_id, callee_symbol_id, callee_name, line, column_no, resolution, confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_ids[item["file"]], item.get("caller_symbol_id"), item.get("callee_symbol_id"), item["callee_name"], item["line"], item.get("column", 0), item["resolution"], item["confidence"]) for item in result["calls"]],
        )
        connection.executemany(
            """INSERT INTO imports(file_id, target_file_id, module_specifier, imported_name, local_name, line, column_no, resolution)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_ids[item["file"]], file_ids.get(item.get("target_file")), item["module_specifier"], item.get("imported_name"), item.get("local_name"), item["line"], item.get("column", 0), item["resolution"]) for item in result["imports"]],
        )
        connection.executemany(
            """INSERT INTO unresolved_edges(file_id, source_symbol_id, kind, target, line, column_no, reason, critical)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(file_ids[item["file"]], item.get("source_symbol_id"), item["kind"], item["target"], item["line"], item.get("column", 0), item["reason"], int(item.get("critical", False))) for item in result["unresolved_edges"]],
        )
        connection.executemany(
            "INSERT INTO diagnostics(file_id, severity, kind, line, message) VALUES (?, ?, ?, ?, ?)",
            [(file_ids.get(item.get("file")), item["severity"], item["kind"], item.get("line", 1), item["message"]) for item in result["diagnostics"]],
        )
    connection.execute("INSERT INTO tests(file_id) SELECT id FROM files WHERE is_test = 1")


def validate_database(path: Path, expected_revision: str, *, acquire_lease: bool = False) -> None:
    try:
        with connect(path, readonly=True, acquire_lease=acquire_lease) as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
            actual_revision = metadata(connection).get("revision")
    except (OSError, sqlite3.DatabaseError, json.JSONDecodeError) as error:
        raise CandidateIntegrityError(f"candidate-integrity-failed: {path}: {error}") from error
    if integrity != "ok" or foreign_keys or actual_revision != expected_revision:
        raise CandidateIntegrityError(
            f"candidate-integrity-failed: {path}: expected_revision={expected_revision}, "
            f"actual_revision={actual_revision}, integrity={integrity}, foreign_keys={foreign_keys}"
        )


def _flush_file(path: Path) -> None:
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    unsupported = {
        errno.EBADF,
        errno.EINVAL,
        getattr(errno, "ENOTSUP", errno.EINVAL),
        getattr(errno, "EOPNOTSUPP", errno.EINVAL),
    }
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError as error:
        if error.errno in unsupported:
            return
        raise
    try:
        try:
            os.fsync(descriptor)
        except OSError as error:
            if error.errno not in unsupported:
                raise
    finally:
        os.close(descriptor)


def _temporary_path(parent: Path, prefix: str, suffix: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=prefix, suffix=suffix, dir=parent)
    os.close(descriptor)
    return Path(name)


def build_candidate_database(
    project: Path,
    out: Path,
    provider_results: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> tuple[Path, str]:
    del project
    if not provider_results:
        raise ValueError("at least one capable L2 provider is required")
    for result in provider_results:
        errors = validate_provider_result(result)
        if errors:
            raise ValueError("; ".join(errors))
    config = config or {}
    files = _merge_files(provider_results)
    providers = [{
        "provider": item["provider"], "version": item.get("version", "unknown"),
        "implementation_identity": item.get("implementation_identity", "unknown"),
        "capabilities": item.get("capabilities", []),
    } for item in provider_results]
    semantic_keys = ("modules", "symbols", "references", "calls", "imports", "unresolved_edges")
    semantics = {
        key: [record for result in provider_results for record in result.get(key, [])]
        for key in semantic_keys
    }
    revision = graph_revision(files, providers, config, semantics)
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_path(out.parent, f"{out.name}.", ".candidate.tmp")
    try:
        with closing(connect(temp_path)) as connection:
            connection.executescript(DDL)
            _insert_records(connection, provider_results, revision, config)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
            if integrity != "ok" or foreign_keys:
                raise ValueError(f"invalid graph database: integrity={integrity}, foreign_keys={foreign_keys}")
            connection.commit()
        _flush_file(temp_path)
        validate_database(temp_path, revision, acquire_lease=False)
    except BaseException:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return temp_path, revision


def _restore_active(active: Path, backup: Path | None) -> None:
    if backup is None:
        active.unlink(missing_ok=True)
    else:
        os.replace(backup, active)
    _fsync_directory(active.parent)


def _discard_temporary(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def publish_candidate(
    candidate: Path,
    active: Path,
    revision: str,
    *,
    lock_timeout: float | None = None,
) -> None:
    candidate = candidate.resolve()
    active = active.resolve()
    snapshot = active.parent / "snapshots" / f"{revision}.sqlite"
    snapshot_candidate: Path | None = None
    active_backup: Path | None = None
    stage = "snapshot-copy"
    try:
        with graph_locks([active, snapshot], "publish", shared=False, timeout=lock_timeout):
            snapshot_candidate = _temporary_path(snapshot.parent, f"{snapshot.name}.", ".candidate.tmp")
            shutil.copyfile(candidate, snapshot_candidate)
            _flush_file(snapshot_candidate)
            validate_database(snapshot_candidate, revision, acquire_lease=False)
            stage = "snapshot-replace"
            if snapshot.exists():
                try:
                    validate_database(snapshot, revision, acquire_lease=False)
                except CandidateIntegrityError:
                    os.replace(snapshot_candidate, snapshot)
                else:
                    snapshot_candidate.unlink()
            else:
                os.replace(snapshot_candidate, snapshot)
            snapshot_candidate = None
            _fsync_directory(snapshot.parent)
            stage = "active-backup"
            if active.exists():
                active_backup = _temporary_path(
                    active.parent, f"{active.name}.", ".active-backup.tmp",
                )
                shutil.copyfile(active, active_backup)
                _flush_file(active_backup)
            stage = "active-replace"
            os.replace(candidate, active)
            try:
                stage = "active-sync"
                _fsync_directory(active.parent)
                stage = "active-validate"
                validate_database(active, revision, acquire_lease=False)
            except (CandidateIntegrityError, OSError, sqlite3.DatabaseError) as error:
                failed_stage = stage
                try:
                    _restore_active(active, active_backup)
                    active_backup = None
                except (OSError, sqlite3.DatabaseError) as rollback_error:
                    raise GraphPublicationError(
                        active, revision, "active-rollback", rollback_error,
                    ) from error
                stage = failed_stage
                raise
            if active_backup is not None:
                _discard_temporary(active_backup)
                active_backup = None
    except CandidateIntegrityError:
        raise
    except (OSError, sqlite3.DatabaseError) as error:
        raise GraphPublicationError(active, revision, stage, error) from error
    finally:
        _discard_temporary(snapshot_candidate)
        _discard_temporary(active_backup)


def build_database(
    project: Path,
    out: Path,
    provider_results: list[dict[str, Any]],
    config: dict[str, Any] | None = None,
) -> str:
    out = out.resolve()
    with graph_lock(out, "build", shared=False):
        normalized_config = (
            load_graph_config(project) if config is None else config
        )
        validate_provider_source_state(project, provider_results, normalized_config)
        candidate: Path | None = None
        try:
            candidate, revision = build_candidate_database(
                project, out, provider_results, normalized_config,
            )
            validate_provider_source_state(
                project, provider_results, normalized_config,
            )
            publish_candidate(candidate, out, revision)
            candidate = None
        finally:
            _discard_temporary(candidate)
        return revision


def metadata(connection: sqlite3.Connection) -> dict[str, Any]:
    raw = {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
    for key in ("providers", "config"):
        if key in raw:
            raw[key] = json.loads(raw[key])
    return raw


def export_snapshot(connection: sqlite3.Connection) -> dict[str, Any]:
    def rows(sql: str) -> list[dict[str, Any]]:
        return [dict(row) for row in connection.execute(sql)]

    return {
        "metadata": metadata(connection),
        "files": rows("SELECT path, language, sha256, is_test, module, provider FROM files ORDER BY path"),
        "symbols": rows("SELECT stable_id, symbol_group_id, declaration_index, runtime_effective, qualified_name, kind, start_line, end_line FROM symbols ORDER BY stable_id"),
        "references": rows("SELECT source_symbol_id, symbol_id, name, resolution FROM symbol_references ORDER BY file_id, line, column_no"),
        "calls": rows("SELECT caller_symbol_id, callee_symbol_id, callee_name, resolution FROM calls ORDER BY file_id, line, column_no"),
        "imports": rows("SELECT f.path AS file, tf.path AS target_file, i.module_specifier, i.imported_name, i.resolution FROM imports i JOIN files f ON f.id=i.file_id LEFT JOIN files tf ON tf.id=i.target_file_id ORDER BY f.path, i.line"),
        "unresolved_edges": rows("SELECT source_symbol_id, kind, target, reason, critical FROM unresolved_edges ORDER BY file_id, line"),
    }
