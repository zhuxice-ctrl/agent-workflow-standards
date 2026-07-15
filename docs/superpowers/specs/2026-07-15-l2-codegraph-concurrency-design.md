# L2 Codegraph Cross-Process Concurrency Design

## Objective

Make L2 graph builds and reads safe when the main window, subagents, preflight, impact checks, resumed tasks, or separate CLI processes access the same project concurrently.

The implementation must guarantee:

- readers observe one complete graph revision per logical operation;
- builders cannot publish in reverse completion order;
- an open reader does not make Windows publication fail;
- an active revision always has a valid, correctly named snapshot;
- failed or terminated processes preserve the last-good active graph;
- contention and source churn produce bounded, actionable failures;
- the locking layer works on Windows, Linux, and macOS without a runtime dependency.

## Confirmed Failure Modes

The current implementation has deterministic reproductions for these failures:

1. A Windows process holding a readonly SQLite connection makes `os.replace(candidate, active)` fail with `WinError 5`.
2. Builder A can publish revision A, builder B can replace active with revision B, and builder A can then copy active into `snapshots/<revision-A>.sqlite`. The filename says A while metadata says B.
3. `GraphQuery.slice` can resolve its entrypoint from revision A, traverse revision B, and report revision B because the operation opens several independent connections.
4. If snapshot copying fails after active replacement, the caller sees a failed build even though active already changed and the required snapshot is absent or partial.
5. Provider analysis is outside any single-flight boundary, so an older analysis can publish after a newer build.
6. Preflight and CLI freshness checks can read metadata, source hashes, slices, and result provenance from different active revisions.

These failures can cause context drift even though each individual SQLite file passes integrity checks.

## Approaches Considered

### Two-Lock Protocol And Pinned Read Sessions

Use a build single-flight lock plus a short-lived reader/writer publication lock. Pin every logical query to one connection and one revision. This is the selected approach because it addresses build ordering, Windows file replacement, snapshot consistency, and mixed-revision query payloads without a service process.

### Publish-Only Mutex

Wrapping only `os.replace` is smaller, but it does not prevent stale build order, snapshot mislabelling, or multi-connection mixed-revision queries. This approach is rejected.

### Dedicated Build Daemon

A single daemon writer could centralize scheduling, but it adds IPC, lifecycle, recovery, and deployment requirements. It is out of scope until L2 becomes a remotely shared graph service.

## Locking Architecture

For an active database path `<graph>.sqlite`, derive two persistent lock files:

```text
<graph>.sqlite.build.lock
<graph>.sqlite.publish.lock
```

Lock files are never interpreted by existence. The operating system owns lock lifetime, so process exit or termination releases the held range even when the lock file remains.

### Build Lock

The build lock is cross-process exclusive and covers:

1. initial source/config capture;
2. provider discovery and analysis;
3. normalized candidate construction;
4. candidate integrity and revision validation;
5. final source/config stability validation;
6. publication.

This makes production builders single-flight. A second builder waits, then analyzes the latest source state rather than publishing a result calculated before the first builder completed.

Direct `build_database` callers use the same build lock. The higher-level builder may pass an internal already-held lease so it can include provider analysis without reacquiring the lock.

### Publish Lock

The publish lock is shared for readers and exclusive for the short commit phase. It covers only snapshot and active-path publication, not provider analysis or candidate construction.

Lock order is always:

```text
build lock -> publish lock
```

No code may acquire them in reverse order. Multi-database read operations acquire publish locks by sorted absolute path.

### Platform Adapter

- Windows: use `LockFileEx` and `UnlockFileEx` through `ctypes`, with shared and exclusive modes.
- Linux/macOS: use `fcntl.flock` with `LOCK_SH` and `LOCK_EX`.

Both implementations use nonblocking attempts plus bounded retry/backoff so timeout behavior is identical. Default timeout is 30 seconds and is configurable by API or `ADWORKFLO_GRAPH_LOCK_TIMEOUT_SECONDS`.

Timeout raises a structured `GraphLockTimeout` containing the database path, lock kind, requested mode, timeout, and retryable status. Lock acquisition failure never falls back to an unlocked read or write.

## Candidate And Publication Protocol

Each builder writes a unique candidate in the active database directory. Before publication it must pass:

- provider result validation;
- `PRAGMA integrity_check`;
- `PRAGMA foreign_key_check`;
- metadata revision equality with the content-addressed expected revision;
- current config equality;
- current handled-language file set equality;
- current source hash equality for every indexed file.

If source or config changes during provider analysis, discard the candidate and retry the complete analysis once while retaining the build lock. A second drift returns structured `SourceChangedDuringBuild`; active and snapshots remain unchanged.

Publication occurs while holding the exclusive publish lock:

1. Copy the verified candidate to a unique snapshot candidate.
2. Flush and validate the snapshot candidate, including `metadata.revision == snapshot filename revision`.
3. Atomically replace `snapshots/<revision>.sqlite` from the snapshot candidate, or verify an existing immutable snapshot with that name.
4. Copy the current active database to a short-lived rollback backup when one exists.
5. Atomically replace the active database from the original verified candidate.
6. Verify active durability and metadata revision, then delete the rollback backup. A post-replace failure restores the previous active path before releasing the publish lock.

The implementation must never create a snapshot by copying the active path.

Snapshot-first publication preserves the required invariant: every active revision already has a valid snapshot. A crash between snapshot and active publication can leave an unused valid snapshot, which is safe. A failure before active replacement leaves the last-good active graph untouched.

Temporary files are unique and removed in `finally` blocks. Old temporary files are never treated as candidates during recovery.

## Pinned Read Sessions

Every logical operation must read through one shared publish lease and one readonly SQLite connection:

- `resolve_symbol`, `find_references`, `callers`, `callees`;
- `impact`, `slice`, `expand`, `summarize_file`, capabilities;
- freshness and preflight evaluation;
- prepare-context slice plus predicted impact calculation;
- direct CLI freshness plus query execution;
- orchestrator evidence recomputation;
- post-edit baseline/current graph comparison.

`GraphQuery` exposes a nestable read-session context. Public query operations automatically create a session when none exists; nested calls reuse the same connection and pinned metadata rather than opening another connection.

The connection owns the shared lease until it closes. On Windows, a publisher therefore waits instead of failing with a sharing violation. On all platforms, query payload, source hashes, edge traversal, provenance, and reported revision come from the same database image.

Preflight may legitimately become invalid if source files change while its pinned graph is being evaluated. It must never combine freshness from a newer graph with a slice from an older graph.

The first accepted task preflight persists an immutable task-keyed baseline revision. Re-running context preparation may refresh current evidence but must not advance the post-edit baseline. A same-revision comparison with declared graph source changes is invalid rather than a successful empty impact report.

## Failure Semantics

Failures are explicit and retryable where appropriate:

- `graph-lock-timeout`: another reader or builder exceeded the configured wait;
- `source-changed-during-build`: source/config changed on both bounded attempts;
- `candidate-integrity-failed`: candidate or snapshot validation failed;
- `graph-publication-failed`: an OS publication operation failed while last-good active remained intact.

`--allow-stale` may allow a stale but internally valid graph query. It never bypasses lock acquisition, candidate integrity, or revision consistency.

Corrupt active recovery uses the same build and publish protocol. Multiple recovery callers serialize; all successful callers must return the same valid active revision when source remains stable.

## Test Design

### Deterministic Multiprocess Tests

Use real subprocesses, synchronization files/events, and bounded timeouts. Do not rely on probabilistic sleep-only races.

1. Hold a readonly graph session in one process, start a rebuild in another, confirm the writer waits, confirm the reader keeps seeing the old revision, release the reader, then confirm publication succeeds.
2. Start four builders against a missing or corrupt active database. Confirm all finish without traceback, active integrity passes, and successful results converge on one revision.
3. Interleave two different candidates at the publication boundary. Confirm every snapshot filename equals its internal metadata revision and every snapshot passes integrity checks.
4. Rebuild revisions repeatedly while readers execute `slice` and `impact`. Compare each result with its named revision snapshot and reject any mixed payload.
5. Inject failure before snapshot replacement, at snapshot replacement, and before active replacement. Confirm last-good active remains readable and no partial snapshot is accepted.
6. Hold a lock beyond a short test timeout and assert structured timeout evidence. Terminate a lock-holder process and confirm the next operation succeeds despite the persistent lock file.
7. Modify source during provider analysis. Confirm the old candidate never replaces a graph built from the newer source state.

Tests use small fixtures and short controlled delays so the concurrency suite remains suitable for normal CI.

### Lightweight Performance Fixture

Generate a deterministic temporary project with approximately:

- 400 Python modules;
- 4,000 symbols;
- 12,000-20,000 source lines;
- cross-module imports, calls, references, and representative tests.

Measure with `time.perf_counter`:

- first and second build duration;
- SQLite file size;
- semantic slice duration;
- preflight duration;
- repeated revision and canonical slice stability.

Default CI ceilings are deliberately broad:

```text
build:      30 seconds per build
slice:       3 seconds
preflight:   3 seconds
database:   64 MiB
```

Environment variables may tighten ceilings on dedicated benchmark hardware, but normal CI may not silently disable correctness assertions. The test prints measured metrics for trend collection.

## Acceptance Criteria

- Cross-process readers and builders coordinate on Windows, Linux, and macOS using only the standard library.
- A reader sees one immutable revision for a complete logical query.
- Concurrent builders cannot corrupt active or snapshots, publish reverse-order analyses, or mislabel snapshot revision.
- Publication failures preserve last-good active and never expose a partial snapshot.
- Corrupt recovery callers serialize and converge without raw SQLite or OS tracebacks.
- Lock timeout and source churn have structured, bounded failure semantics.
- The lightweight 400-module fixture satisfies the correctness, stability, time, and size ceilings.
- Existing L2 correctness, installation, preflight, impact, and distribution tests remain passing.

## Non-Goals

- A build daemon or remote graph service.
- Distributed locks for network filesystems or multiple machines.
- A full production monorepo benchmark.
- Changing the orchestrator-state JSON compare-and-swap protocol; its own cross-process lost-update risk requires a separate task.
- WAL-based in-place mutation of the active graph. L2 remains immutable-candidate plus atomic-publication based.
