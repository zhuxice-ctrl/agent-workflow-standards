# L2 Codegraph Concurrency And Lightweight Scale Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make L2 graph reads, rebuilds, snapshots, preflight, and impact checks revision-consistent under multiple processes, then enforce a lightweight 400-module performance budget.

**Architecture:** A standard-library cross-platform lock adapter provides a whole-build exclusive lock and a shared-reader/exclusive-publisher lock. Builders construct and validate immutable candidates, publish the snapshot before active, and retry bounded source churn; readers pin an entire logical operation to one shared lease, one SQLite connection, and one revision. Deterministic subprocess tests exercise real races, while a generated large fixture records broad CI performance ceilings.

**Tech Stack:** Python 3 standard library (`ctypes`, `fcntl`, `sqlite3`, `subprocess`, `unittest`, `time`), TypeScript Compiler API, Windows `LockFileEx`, POSIX `flock`.

**Working-tree rule:** Do not create commits automatically. The current branch contains a large shared uncommitted ADworkflo implementation, and the user did not request commits.

---

## File Map

- Create `skills/adworkflo/scripts/l2_codegraph/locking.py`: cross-platform OS lock adapter, timeout errors, lock-path derivation, ordered multi-lock helpers.
- Modify `skills/adworkflo/scripts/l2_codegraph/database.py`: lock-owning readonly connections, candidate validation, snapshot-first atomic publication, direct-builder single-flight.
- Modify `skills/adworkflo/scripts/build_codegraph_l2.py`: whole provider analysis under build single-flight, bounded source-stability retry.
- Modify `skills/adworkflo/scripts/l2_codegraph/query.py`: nestable pinned read sessions and one-connection public queries.
- Modify `skills/adworkflo/scripts/l2_codegraph/safety.py`: connection-aware freshness/preflight and pinned baseline/current impact reads.
- Modify `skills/adworkflo/scripts/prepare_context.py`: one read session for slice, predicted impact, and preflight.
- Modify `skills/adworkflo/scripts/query_codegraph.py`: one read session for freshness plus CLI query.
- Modify `skills/adworkflo/scripts/orchestrator.py`: pinned evidence recomputation.
- Modify `skills/adworkflo/scripts/codegraph_post_edit.py`: preserve structured concurrency errors.
- Create `tests/l2_concurrency_worker.py`: deterministic subprocess actions used by concurrency tests.
- Create `tests/test_l2_concurrency.py`: cross-process read/build/publication/recovery tests.
- Create `tests/test_l2_performance.py`: generated 400-module fixture and broad CI budgets.
- Modify `skills/adworkflo/references/codegraph-design.md`: lock protocol and failure semantics.
- Update active `.adworkflow` task, context, worker, verification, impact, and review artifacts.

---

### Task 1: Establish the new artifact-driven task

**Files:**
- Archive: `.adworkflow/artifacts/fix-l2-codegraph-audit-findings/`
- Modify: `.adworkflow/task_spec.json`
- Regenerate: `.adworkflow/context_raw.json`
- Regenerate: `.adworkflow/context_manifest.json`
- Regenerate: `.adworkflow/semantic_slice.json`
- Regenerate: `.adworkflow/context_preflight.json`

- [x] **Step 1: Archive the completed fix artifacts without modifying the previous audit archives**

Archive `task_spec`, context artifacts, impact, worker state, verification, and review under the completed task ID.

- [x] **Step 2: Write the concurrency task contract**

Set `task_id` to `harden-l2-codegraph-concurrency` and include exact acceptance criteria for cross-platform locks, revision-pinned reads, snapshot-first publication, structured failures, corrupt recovery convergence, and the 400-module performance fixture.

- [x] **Step 3: Prepare initial L2 context**

Run:

```powershell
py -3 skills/adworkflo/scripts/prepare_context.py --project . --level l2 --slice-depth 6 --slice-budget 2500
```

Expected: preflight is `accepted`, confidence is at least `0.8`, and the database/query/build entrypoints are included.

---

### Task 2: Add the cross-platform lock adapter with failing unit tests

**Files:**
- Create: `skills/adworkflo/scripts/l2_codegraph/locking.py`
- Create: `tests/test_l2_concurrency.py`

- [x] **Step 1: Write failing timeout, shared/exclusive, and crash-release tests**

Tests must use separate processes, not threads, and assert:

```python
with graph_lock(database, "publish", shared=True, timeout=1.0):
    # A second shared process succeeds.
    # An exclusive process times out with GraphLockTimeout.
    pass
```

Terminate a child holding a lock, leave the lock file present, then assert the next process acquires it.

- [x] **Step 2: Run the focused tests and confirm failure**

```powershell
py -3 -m unittest tests.test_l2_concurrency.L2LockTests -v
```

Expected: import or missing lock API failures.

- [x] **Step 3: Implement the lock contract**

The public surface is:

```python
class GraphLockTimeout(TimeoutError):
    retryable = True

    def __init__(self, database: Path, kind: str, mode: str, timeout: float) -> None:
        self.database = database.resolve()
        self.kind = kind
        self.mode = mode
        self.timeout = timeout
        super().__init__(f"graph-lock-timeout: {kind} {mode} lock for {self.database} exceeded {timeout:.3f}s")

def lock_path(database: Path, kind: str) -> Path:
    if kind not in {"build", "publish"}:
        raise ValueError(f"unsupported graph lock kind: {kind}")
    resolved = database.resolve()
    return resolved.with_name(f"{resolved.name}.{kind}.lock")
```

Add `graph_lock(database, kind, shared=False, timeout=None)` as a context manager returning a `GraphLockLease`. Use `LockFileEx`/`UnlockFileEx` with a one-byte range on Windows and `fcntl.flock` on POSIX. Retry nonblocking acquisition with bounded exponential backoff. Read the default timeout from `ADWORKFLO_GRAPH_LOCK_TIMEOUT_SECONDS`, falling back to 30 seconds.

- [x] **Step 4: Run focused tests**

Expected: shared readers coexist, exclusive acquisition waits/times out, crash release succeeds, and a residual lock file is harmless.

---

### Task 3: Make readonly connections own publish leases

**Files:**
- Modify: `skills/adworkflo/scripts/l2_codegraph/database.py`
- Modify: `tests/test_l2_concurrency.py`

- [x] **Step 1: Write the Windows reader-versus-publisher regression**

Start a child that opens `connect(database, readonly=True)` and waits. Start a publisher child and assert it remains blocked rather than returning `WinError 5`. Release the reader and assert the publisher succeeds.

- [x] **Step 2: Add lock ownership to `ClosingConnection`**

Implement connection creation with this behavior:

```python
def connect(path: Path, readonly: bool = False, *, acquire_lease: bool = True) -> sqlite3.Connection:
    lease = graph_lock(path, "publish", shared=True) if readonly and acquire_lease else nullcontext()
    lease.__enter__()
    try:
        target = f"file:{path.resolve().as_posix()}?mode=ro" if readonly else str(path)
        connection = sqlite3.connect(target, uri=readonly, factory=ClosingConnection)
        connection.attach_graph_lease(lease)
        return connection
    except BaseException:
        lease.__exit__(*sys.exc_info())
        raise
```

`ClosingConnection.close()` closes SQLite before releasing the shared lease, is idempotent, and also releases on failed `__enter__` paths.

- [x] **Step 3: Verify existing database tests plus the reader regression**

```powershell
py -3 -m unittest tests.test_l2_database tests.test_l2_concurrency -v
```

Expected: existing atomicity behavior remains and the writer waits successfully.

---

### Task 4: Publish snapshots and active graph atomically in the safe order

**Files:**
- Modify: `skills/adworkflo/scripts/l2_codegraph/database.py`
- Modify: `tests/test_l2_database.py`
- Modify: `tests/test_l2_concurrency.py`

- [x] **Step 1: Add deterministic failure-injection and mislabelled-snapshot tests**

Patch the internal publication operations at three boundaries: snapshot copy, snapshot replace, and active replace. Each failure must leave the previous active revision readable. Also validate every snapshot with:

```python
with connect(snapshot, readonly=True) as connection:
    assert metadata(connection)["revision"] == snapshot.stem
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
```

- [x] **Step 2: Confirm the tests fail against active-first publication**

Expected: current tests reproduce changed-active-without-snapshot and revision filename mismatch.

- [x] **Step 3: Extract candidate validation and safe publication helpers**

Use these internal boundaries:

```python
def validate_database(path: Path, expected_revision: str) -> None:
    with connect(path, readonly=True, acquire_lease=False) as connection:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
        actual_revision = metadata(connection).get("revision")
    if integrity != "ok" or foreign_keys or actual_revision != expected_revision:
        raise CandidateIntegrityError(path, expected_revision, actual_revision, integrity, foreign_keys)

def publish_candidate(candidate: Path, active: Path, revision: str, *, timeout: float | None = None) -> None:
    with graph_lock(active, "publish", shared=False, timeout=timeout):
        snapshot = active.parent / "snapshots" / f"{revision}.sqlite"
        snapshot_candidate = unique_temp(snapshot.parent, snapshot.name)
        copy_flush_validate(candidate, snapshot_candidate, revision)
        atomic_publish_or_validate(snapshot_candidate, snapshot, revision)
        os.replace(candidate, active)
        validate_database(active, revision, acquire_lease=False)
```

Never copy from `active`. Flush candidate files with `os.fsync`; fsync the containing directory where supported. Snapshot publication happens before active publication.

- [x] **Step 4: Run database and publication tests**

Expected: injected failures preserve last-good active, snapshots are immutable and correctly named, and no partial temp is accepted.

---

### Task 5: Serialize whole builds and reject source churn

**Files:**
- Modify: `skills/adworkflo/scripts/build_codegraph_l2.py`
- Modify: `skills/adworkflo/scripts/l2_codegraph/database.py`
- Modify: `tests/l2_concurrency_worker.py`
- Modify: `tests/test_l2_concurrency.py`

- [x] **Step 1: Write concurrent builder and source-churn failures**

Start four real CLI builders against the same missing database. Add a controlled provider-delay hook used only by the subprocess worker, mutate a source file during the first attempt, and assert no candidate with old hashes becomes active.

- [x] **Step 2: Add structured build errors**

```python
class SourceChangedDuringBuild(RuntimeError):
    retryable = True

class GraphPublicationError(RuntimeError):
    retryable = True
```

Errors include stable reason codes in their messages/results. Raw `PermissionError` and `sqlite3.DatabaseError` must not escape normal concurrent prepare/build paths.

- [x] **Step 3: Put provider analysis under build single-flight**

```python
def build(project: Path, out: Path, include_typescript: bool = True,
          require_typescript: bool = False, max_source_attempts: int = 2) -> dict:
    with graph_lock(out, "build", shared=False):
        for attempt in range(max_source_attempts):
            config = load_graph_config(project)
            before = capture_source_state(project, config)
            results, ts_status = analyze_capable_providers(project, config, include_typescript, require_typescript)
            candidate, revision = build_candidate_database(project, out, results, config)
            after = capture_source_state(project, config, handled_languages(results))
            if before == after == provider_source_state(results):
                publish_candidate(candidate, out, revision)
                return make_build_result(out, revision, results, ts_status)
            candidate.unlink(missing_ok=True)
        raise SourceChangedDuringBuild(project, max_source_attempts)
```

Direct `build_database` acquires the build lock itself and performs final source validation before publishing.

- [x] **Step 4: Verify convergence and recovery**

Expected: four builders/recovery callers finish without corrupting active, successful outputs converge on one revision, and source churn either retries to the new revision or returns the structured bounded failure.

---

### Task 6: Pin every GraphQuery operation to one connection and revision

**Files:**
- Modify: `skills/adworkflo/scripts/l2_codegraph/query.py`
- Modify: `tests/test_l2_queries.py`
- Modify: `tests/test_l2_concurrency.py`

- [x] **Step 1: Add the mixed-revision slice reproduction**

Publish revision B after entrypoint resolution from A but before traversal. Assert the old implementation can return A hashes inside a result labelled B.

- [x] **Step 2: Add a nestable query read session**

```python
@contextmanager
def read_session(self) -> Iterator[GraphQuery]:
    if self._connection is not None:
        self._session_depth += 1
        try:
            yield self
        finally:
            self._session_depth -= 1
        return
    with connect(self.database, readonly=True) as connection:
        self._connection = connection
        self._pinned_metadata = metadata(connection)
        try:
            yield self
        finally:
            self._pinned_metadata = None
            self._connection = None
```

All public operations enter `read_session`; nested `resolve_symbol`, `impact`, `_result`, and `graph_metadata` reuse `_connection` and `_pinned_metadata`. Internal SQL helpers accept the pinned connection and never open a second one.

- [x] **Step 3: Run query and rebuild-loop tests**

Expected: every query result matches its revision snapshot, no payload contains mixed source hashes, and existing query behavior is unchanged.

---

### Task 7: Pin freshness, preflight, prepare, CLI, impact, and orchestrator evidence

**Files:**
- Modify: `skills/adworkflo/scripts/l2_codegraph/safety.py`
- Modify: `skills/adworkflo/scripts/prepare_context.py`
- Modify: `skills/adworkflo/scripts/query_codegraph.py`
- Modify: `skills/adworkflo/scripts/orchestrator.py`
- Modify: `skills/adworkflo/scripts/codegraph_post_edit.py`
- Modify: `tests/test_l2_workflow.py`
- Modify: `tests/test_l2_audit_regressions.py`
- Modify: `tests/test_l2_concurrency.py`

- [x] **Step 1: Write integration races**

Trigger publication between slice and preflight and between CLI freshness and query. Expected behavior is either one pinned accepted revision or an explicit invalid/source-drift result, never accepted mixed evidence.

- [x] **Step 2: Make safety functions connection-aware**

```python
with query.read_session():
    freshness = freshness_report(project, database, connection=query.connection)
    semantic_slice = query.slice(entrypoints, depth=depth, budget=budget)
    gate = preflight(
        project, database, semantic_slice, task_id, threshold,
        connection=query.connection,
    )
```

When a caller supplies a pinned connection, metadata and indexed hashes come from it. When absent, the function creates one read session for its complete operation.

- [x] **Step 3: Wrap compound workflows in read sessions**

- `prepare_l2`: one `GraphQuery.read_session()` for slice, entrypoint impact, and preflight.
- CLI: one read session for freshness and query execution.
- orchestrator dispatch/completion: one session per active or baseline graph evidence recomputation.
- post-edit: acquire baseline/current read leases in sorted absolute-path order and keep them through comparison.

- [x] **Step 4: Run workflow, safety, orchestrator, stale CLI, and concurrency tests**

Expected: no mixed accepted evidence and all previous forgery/freshness tests remain passing.

---

### Task 8: Add the lightweight 400-module performance fixture

**Files:**
- Create: `tests/test_l2_performance.py`

- [x] **Step 1: Generate a deterministic large temporary project**

Create 400 modules with ten functions per module, a module-level constant, a call to the next module, and representative test modules. Keep generation inside `TemporaryDirectory`; do not add fixture source files to the repository.

- [x] **Step 2: Measure build, slice, preflight, size, and stability**

```python
build_limit = float(os.getenv("ADWORKFLO_PERF_BUILD_MAX_SECONDS", "30"))
slice_limit = float(os.getenv("ADWORKFLO_PERF_SLICE_MAX_SECONDS", "3"))
preflight_limit = float(os.getenv("ADWORKFLO_PERF_PREFLIGHT_MAX_SECONDS", "3"))
size_limit = int(os.getenv("ADWORKFLO_PERF_DATABASE_MAX_MIB", "64")) * 1024 * 1024
```

Build twice, assert identical revisions, canonical slice payloads, accepted preflight, no truncation, and database size below the limit. Print a single JSON metrics line.

- [x] **Step 3: Run and calibrate only if the default ceiling is exceeded for a correctness-neutral machine reason**

```powershell
py -3 -m unittest tests.test_l2_performance -v
```

Expected: both builds are under 30 seconds, slice/preflight are each under 3 seconds, and SQLite is under 64 MiB. Do not weaken correctness assertions or silently skip the benchmark.

---

### Task 9: Document, review, and verify end to end

**Files:**
- Modify: `skills/adworkflo/references/codegraph-design.md`
- Modify: `.adworkflow/worker_state.json`
- Modify: `.adworkflow/verification_result.json`
- Modify: `.adworkflow/review_findings.json`
- Regenerate: `.adworkflow/context_raw.json`
- Regenerate: `.adworkflow/context_manifest.json`
- Regenerate: `.adworkflow/semantic_slice.json`
- Regenerate: `.adworkflow/context_preflight.json`
- Regenerate: `.adworkflow/impact_report.json`

- [x] **Step 1: Document lock files, lock ordering, timeout codes, source churn, and snapshot-first recovery**

Keep the operational documentation concise and link to the detailed design spec.

- [x] **Step 2: Run the focused concurrency and performance suites**

```powershell
py -3 -m unittest tests.test_l2_concurrency tests.test_l2_performance -v
```

- [x] **Step 3: Run the complete regression and static suite**

```powershell
py -3 -m unittest discover -s tests -v
py -3 skills/adworkflo/scripts/sync_templates.py --check
py -3 skills/adworkflo/scripts/validate_adworkflow.py --project . --templates
py -3 F:/CodexHome/skills/.system/skill-creator/scripts/quick_validate.py skills/adworkflo
git diff --check
```

Also compile every Python script, run `node --check` for the TypeScript analyzer, parse all repository JSON, and parse all PowerShell scripts.

- [x] **Step 4: Rebuild real L2 evidence and post-edit impact**

```powershell
py -3 skills/adworkflo/scripts/prepare_context.py --project . --level l2 --slice-depth 6 --slice-budget 2500
py -3 skills/adworkflo/scripts/codegraph_post_edit.py --project . --task-id harden-l2-codegraph-concurrency
```

Expected: accepted preflight, passed impact, no unexpected impact, no new critical edge, and no propagation truncation.

- [x] **Step 5: Perform a Level 3 review**

Review the final diff against the task spec, concurrency test evidence, performance metrics, real preflight, and impact report. Record any remaining risks, especially network filesystems, distributed builders, and orchestrator-state CAS.
