# ADworkflo L2 Codegraph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement a truthful, revisioned L2 semantic graph and its complete context-safety loop for formal Agent development.

**Architecture:** Language providers emit normalized semantic records into an atomically rebuilt SQLite graph. A shared query/safety layer creates impact and slice evidence, while `prepare_context` and Orchestrator enforce freshness, confidence, expansion, post-edit impact, verification, and review gates.

**Tech Stack:** Python 3 standard library (`ast`, `symtable`, `sqlite3`), TypeScript Compiler API on Node.js, JSON Schema, `unittest`, PowerShell installer.

---

### Task 1: Formalize L2 artifacts and provider contracts

**Files:**
- Create: `skills/adworkflo/scripts/l2_codegraph/__init__.py`
- Create: `skills/adworkflo/scripts/l2_codegraph/model.py`
- Create: `schemas/semantic_slice.schema.json`
- Create: `schemas/context_preflight.schema.json`
- Create: `schemas/context_expansion_request.schema.json`
- Create: `schemas/impact_report.schema.json`
- Create/Modify: canonical and mirrored JSON templates
- Test: `tests/test_l2_contracts.py`

- [x] Write failing schema and capability-contract tests.
- [x] Define normalized provider records and required L2 capability constants.
- [x] Add canonical artifact templates and register them in template synchronization.
- [x] Run `py -3 -m unittest tests.test_l2_contracts -v` and make it pass.

### Task 2: Implement the Python semantic provider

**Files:**
- Create: `skills/adworkflo/scripts/l2_codegraph/python_provider.py`
- Test: `tests/test_l2_python_provider.py`
- Fixtures: generated in test temporary directories

- [x] Write failing tests for modules, qualified symbols, lexical references, imported aliases, same-file/cross-file calls, methods, and dynamic unresolved calls.
- [x] Implement two-pass `ast`/`symtable` extraction with deterministic stable IDs.
- [x] Resolve only defensible edges and emit diagnostics/unresolved records for the rest.
- [x] Run `py -3 -m unittest tests.test_l2_python_provider -v` and make it pass.

### Task 3: Implement SQLite graph builds and revisions

**Files:**
- Create: `skills/adworkflo/scripts/l2_codegraph/database.py`
- Create: `skills/adworkflo/scripts/build_codegraph_l2.py`
- Modify: `skills/adworkflo/scripts/build_codegraph.py`
- Test: `tests/test_l2_database.py`

- [x] Write failing tests for schema integrity, atomic builds, stable revision IDs, source drift, and provider failures.
- [x] Create normalized tables, indexes, foreign keys, metadata, and revision records.
- [x] Build a temporary database, validate it, and atomically publish `.codegraph/l2.sqlite`.
- [x] Preserve the existing L1 builder and add explicit `--level l1|l2|auto` routing.
- [x] Run `py -3 -m unittest tests.test_l2_database -v` and make it pass.

### Task 4: Implement the TypeScript/JavaScript provider

**Files:**
- Create: `skills/adworkflo/providers/typescript/package.json`
- Create: `skills/adworkflo/providers/typescript/package-lock.json`
- Create: `skills/adworkflo/providers/typescript/analyze.mjs`
- Create: `skills/adworkflo/scripts/l2_codegraph/typescript_provider.py`
- Test: `tests/test_l2_typescript_provider.py`

- [x] Add provider-local TypeScript dependency metadata and install it for verification without distributing `node_modules`.
- [x] Write failing TS/JS fixture tests for definitions, aliases, references, imports, calls, and unresolved dynamic calls.
- [x] Implement `Program`/`TypeChecker` analysis and the Python subprocess adapter.
- [x] Add a capability probe with actionable unavailable diagnostics.
- [x] Run `py -3 -m unittest tests.test_l2_typescript_provider -v` and make it pass.

### Task 5: Implement graph queries, impact, slices, and expansion

**Files:**
- Create: `skills/adworkflo/scripts/l2_codegraph/query.py`
- Modify: `skills/adworkflo/scripts/query_codegraph.py`
- Test: `tests/test_l2_queries.py`

- [x] Write failing tests for unique/ambiguous lookup, references, callers, callees, importers, related tests, and provenance.
- [x] Implement deterministic bounded traversals and reason paths.
- [x] Implement weighted cross-module impact with direct/transitive/test/boundary/unresolved groups.
- [x] Implement entrypoint slices with ranges, coverage, confidence, truncation, hashes, revision, and provenance.
- [x] Implement additive relation/depth/budget expansion history.
- [x] Run `py -3 -m unittest tests.test_l2_queries -v` and make it pass.

### Task 6: Implement context safety and post-edit impact

**Files:**
- Create: `skills/adworkflo/scripts/l2_codegraph/safety.py`
- Create: `skills/adworkflo/scripts/codegraph_preflight.py`
- Create: `skills/adworkflo/scripts/codegraph_post_edit.py`
- Test: `tests/test_l2_safety.py`

- [x] Write failing tests for accepted, needs-expansion, invalid, stale, missing capability, ambiguity, and critical unresolved states.
- [x] Calculate evidence-based confidence and required expansion actions.
- [x] Validate graph revision and slice file hashes against disk.
- [x] Compare baseline/current graphs and emit edge deltas, observed impact, unexpected impact, and pass/fail status.
- [x] Run `py -3 -m unittest tests.test_l2_safety -v` and make it pass.

### Task 7: Integrate prepare-context and Orchestrator gates

**Files:**
- Modify: `skills/adworkflo/scripts/prepare_context.py`
- Modify: `skills/adworkflo/scripts/orchestrator.py`
- Modify: `skills/adworkflo/scripts/validate_adworkflow.py`
- Modify: `schemas/context_manifest.schema.json`
- Modify: `schemas/worker_state.schema.json`
- Modify: `schemas/review_findings.schema.json`
- Test: `tests/test_l2_workflow.py`
- Test: `tests/test_orchestrator.py`

- [x] Write failing integration tests for L2 selection, artifact output, dispatch blocking, expansion history, completion, and review basis.
- [x] Make `prepare_context` prefer a fresh capable L2 graph only when configured/requested and preserve L0/L1 fallback.
- [x] Initialize task-scoped L2 artifacts and add dispatch/completion validation.
- [x] Require accepted fresh preflight plus passed post-edit impact for L2 verification.
- [x] Run the integration tests and existing context/orchestrator tests.

### Task 8: Package, document, and verify end to end

**Files:**
- Modify: `skills/adworkflo/SKILL.md`
- Modify: `skills/adworkflo/references/codegraph-design.md`
- Modify: `skills/artifact-driven-development/references/codegraph-retrieval.md`
- Modify: `CODEGRAPH_RETRIEVAL_PROTOCOL.md`
- Modify: `README.md`
- Modify: installed Skill initialization and installation entrypoints
- Modify: `.adworkflow/worker_state.json`
- Modify: `.adworkflow/verification_result.json`
- Modify: `.adworkflow/review_findings.json`

- [x] Update project-size routing and supported-query advertising to reflect verified first-party L2 availability.
- [x] Document provider setup, query examples, slice recovery, expansion, drift, and post-edit verification.
- [x] Run the full unit suite and TypeScript smoke fixture.
- [x] Run template sync, artifact/schema validation, Python compile, JSON/PowerShell parse, and `git diff --check`.
- [x] Record exact evidence and residual risks in the active ADworkflo artifacts.
