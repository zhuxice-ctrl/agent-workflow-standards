# ADworkflo Codegraph Design

Codegraph is a project-local evidence index, not a prompt dump and not source truth.

## Levels

- L0: `rg`, file tree, manual manifest.
- L1: portable JSON file/symbol/import/test index.
- L2: verified semantic providers, revisioned SQLite graph, bounded queries, context safety, and post-edit impact.

Use the lightest sufficient level. Large size alone does not make an unsupported language semantic.

## First-Party L2 Providers

Python uses standard-library `ast` and `symtable`. TypeScript/JavaScript uses the TypeScript Compiler API and `TypeChecker` from `providers/typescript`. Run:

```powershell
npm install --prefix $env:ADWORKFLO_SKILL_ROOT\providers\typescript --ignore-scripts
```

Both providers must report definitions, references, calls, imports, source ranges, and unresolved edges. A provider missing any capability is not L2.

Dynamic dispatch, reflection, wildcard imports, runtime injection, syntax failures, and external calls are not guessed. They remain explicit unresolved boundaries.

## Storage And Revisions

L2 writes `.codegraph/l2.sqlite` atomically and preserves `.codegraph/snapshots/<revision>.sqlite`. Tables cover files, modules, symbols, references, calls, imports, tests, unresolved edges, diagnostics, providers, and revisions.

Revision identity is derived from source hashes, provider versions/capabilities, and build configuration. Every query returns its graph revision and provenance.

### Cross-Process Concurrency

Each active database has two persistent advisory lock files:

```text
<database>.build.lock
<database>.publish.lock
```

The build lock is exclusive and covers provider analysis, candidate construction, source/config revalidation, and publication. The publish lock is shared by readers and exclusive during publication. Lock files may remain on disk; only the OS lock state is authoritative. Windows uses `LockFileEx`; Linux and macOS use `flock`.

Lock order is always `build -> publish`. Operations that read more than one database acquire publish locks in sorted absolute-path order. Never acquire these locks in reverse order.

Publication validates a standalone candidate, atomically publishes and validates `snapshots/<revision>.sqlite`, then atomically replaces the active database. A short-lived active backup is retained until post-replace durability and revision validation pass, so a reported late publication failure can restore the previous active graph. A snapshot is never copied from the active path. Source or config drift discards the candidate and retries the complete analysis once; repeated drift leaves the last-good graph unchanged.

Every logical query and compound workflow pins one shared publish lease, one readonly SQLite connection, and one metadata revision. This includes slice, impact, freshness, preflight, context preparation, CLI queries, orchestrator evidence recomputation, and post-edit baseline/current comparison.

Concurrency failures are structured and bounded:

- `graph-lock-timeout`: retryable lock contention.
- `source-changed-during-build`: retryable source/config churn after bounded attempts.
- `candidate-integrity-failed`: non-retryable invalid candidate or snapshot evidence.
- `graph-publication-failed`: retryable atomic publication failure.

`--allow-stale` may query an internally valid stale graph, but it never bypasses locks, integrity checks, or revision pinning. The detailed protocol and recovery rationale are in [L2 Codegraph Cross-Process Concurrency Design](../../../docs/superpowers/specs/2026-07-15-l2-codegraph-concurrency-design.md).

## Queries

```text
capabilities
find-definition
find-references
find-importers
callers
callees
tests-for
impact
slice
expand
summarize-file
```

Lookup accepts stable ID, qualified name, or a unique short name. Ambiguous short names return candidates and never guess.

Impact traverses reverse call, reference, and import edges. Slice traverses entrypoint definitions and call relations under explicit depth and item budgets. Both expose reason paths, boundaries, unresolved edges, truncation, revision, and provenance.

## Context Safety Loop

```text
task_spec entrypoints
-> semantic_slice.json
-> context_preflight.json
-> accepted: dispatch
-> needs_expansion: context_expansion_request.json
-> apply_context_expansion.py
-> accepted: dispatch
-> worker edits and records changed_files
-> codegraph_post_edit.py rebuilds graph
-> impact_report.json
-> verifier/reviewer completion gate
```

`invalid` means stale source, graph revision mismatch, missing provider capability, corrupt graph, or unresolved/ambiguous entrypoint. `needs_expansion` means the slice is usable but has a critical unresolved edge, insufficient confidence, or a traversal boundary. Neither state may be silently treated as accepted.

Default confidence threshold is `0.80`. Increasing it is allowed. Lowering it requires an explicit project policy and must not conceal critical unresolved edges.

## Formal Project Commands

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\build_codegraph.py --project <PROJECT> --level l2
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\prepare_context.py --project <PROJECT> --level l2
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\apply_context_expansion.py --project <PROJECT>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\codegraph_post_edit.py --project <PROJECT> --task-id <TASK_ID>
```

The post-edit command finds the baseline from the immutable task baseline record, falling back to `context_preflight.graph_revision` for older tasks. It reads declared changes from `worker_state.changed_files`, reads predicted impact from `context_manifest.predicted_impact_files`, rebuilds the active graph, and emits the comparison report.

The first accepted context also writes an immutable task-keyed record under `.adworkflow/baselines/`. Later context preparation never advances this record, and post-edit prefers it over a mutable preflight file. If baseline and current revisions are equal while declared files belong to the graph, impact fails as a reused-baseline error instead of passing an empty comparison. New critical edges in production code remain blocking; test-only critical edges are reported separately and require reviewer attention without invalidating the production semantic slice.

## Fallback

If a provider is unavailable, keep supported languages on L2 and expose unsupported languages as a boundary, or deliberately route the task to L1/manual context. Record the limitation in `context_manifest`, `worker_state`, and verification residual risk. Never synthesize missing semantic edges with regex and label them L2.
