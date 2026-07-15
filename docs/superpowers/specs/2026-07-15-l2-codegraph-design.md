# ADworkflo L2 Codegraph Design

## 1. Goal

Build a project-local semantic evidence system that reduces Agent discovery cost without hiding uncertainty. The system must answer definitions, references, callers, callees, cross-module impact, and entrypoint slices, then prove that the context remains valid through implementation and review.

L2 is a locator and evidence layer. Source code, compiler/type checker results, project tests, and review remain authoritative.

## 2. Supported Scope

First-party reliable providers:

- Python: standard-library `ast` and `symtable`, with deterministic qualified symbols and explicit unresolved edges.
- TypeScript/JavaScript: TypeScript Compiler API and `TypeChecker`, installed as a provider-local development dependency.

Other languages remain L1 unless a provider implements the same output contract and passes a capability probe. File or regex extraction never qualifies as L2.

## 3. Runtime Architecture

```text
source tree
  -> provider capability probe
  -> language semantic records
  -> normalized graph builder
  -> atomic SQLite revision
  -> query engine
  -> semantic_slice / context_preflight
  -> worker implementation
  -> rebuilt graph / impact_report
  -> verifier and reviewer gates
```

The existing `.codegraph/index.json` remains the portable L1 index. L2 uses `.codegraph/l2.sqlite`; both may coexist. `prepare_context` prefers a fresh, capable L2 graph when the project configuration requests L2, and otherwise retains the current L0/L1 behavior.

## 4. Provider Contract

Each provider returns:

- provider name and version
- languages and verified capabilities
- file records and source hashes
- modules
- symbol definitions with stable IDs, qualified names, kind, scope, ranges, export visibility, and signatures when available
- references with resolved symbol ID or an explicit unresolved resolution
- calls with caller, resolved callee or unresolved target, source location, and confidence
- imports with resolved target file when known
- unresolved edges with kind, target text, reason, location, and criticality
- diagnostics

A provider qualifies for L2 only when its probe confirms `definitions`, `references`, `calls`, `imports`, `source_ranges`, and `unresolved_edges`. Missing required capabilities cause a truthful fallback or an invalid preflight, never silent partial L2.

### Python resolution

The Python provider performs a repository-wide two-pass analysis. Pass one records modules, classes, functions, methods, and nested functions. Pass two resolves lexical names, local/global definitions, imported names, module-qualified attribute calls, and same-module calls. Instance dispatch, decorators that replace callables, reflection, `eval`, wildcard imports, and runtime injection are recorded as unresolved boundaries when static resolution is unsafe.

### TypeScript/JavaScript resolution

The Node provider builds a TypeScript `Program`, loads `tsconfig.json` when present, and uses `TypeChecker` symbols and aliased symbols. It records declarations, identifiers, imports, and call expressions. Calls with no source declaration or ambiguous/dynamic targets become unresolved edges. Dependency installation is explicit and `node_modules` is never distributed.

## 5. SQLite Graph

`.codegraph/l2.sqlite` contains normalized tables for:

- revisions and metadata
- files and modules
- symbols
- references
- calls
- imports
- tests
- unresolved edges

Every build writes a temporary database, validates referential integrity and provider capabilities, then atomically replaces the active database. The revision ID is derived from sorted source hashes plus provider versions and build configuration. Query output always includes this revision and provenance.

## 6. Query Semantics

The CLI supports:

- `capabilities`
- `find-definition`
- `find-references`
- `find-importers`
- `callers`
- `callees`
- `tests-for`
- `impact`
- `slice`
- `expand`
- `summarize-file`

Symbol lookup accepts stable ID, qualified name, or unique short name. Ambiguous names return candidates and do not guess.

`impact` traverses reverse calls, references, and imports with relation-specific weights. Results are grouped as direct, transitive, tests, boundary, and unresolved, with a reason path for every included item. Depth and item budgets are mandatory and truncation is explicit.

`slice` starts from one or more entrypoints and traverses definitions, callees, selected callers, references, imports, and related tests. It returns symbol source ranges rather than synthesized code. Included, boundary, excluded, and unresolved sets are separate.

## 7. Confidence And Preflight

Slice confidence is evidence-based:

- provider capability completeness
- resolved edge ratio
- entrypoint resolution
- traversal truncation
- source freshness
- critical unresolved edges

The preflight state is:

- `accepted`: fresh graph, resolved entrypoints, no critical unresolved boundary, confidence at or above threshold, not critically truncated
- `needs_expansion`: usable slice but an explicit relation/depth/file expansion is needed
- `invalid`: stale graph, missing required provider capability, ambiguous/missing entrypoint, or corrupt revision

The default acceptance threshold is `0.80`. A task may raise but not silently lower it. The preflight artifact includes required actions and may never report `accepted` for a stale graph.

## 8. Expansion And Drift

A worker may request context expansion by relation, symbol/file target, depth, item budget, and reason. The query engine appends expansion history and emits a new slice tied to the same graph revision. Expansion cannot erase earlier unresolved evidence.

Before editing, file hashes in the slice are checked against disk. After editing, the graph is rebuilt and an `impact_report` compares:

- baseline and current graph revisions
- declared files/symbols and actually changed files/symbols
- predicted and observed impacted files/tests
- added/removed call, reference, and import edges
- unexpected impact and unresolved regressions

An old slice becomes invalid when its source hashes or graph revision no longer match the active source tree.

## 9. Workflow Integration

`prepare_context` writes `semantic_slice.json` and `context_preflight.json` for L2 tasks and exposes the slice paths in `context_manifest`. A `needs_expansion` result prevents worker dispatch until the requested expansion is resolved or the main window deliberately switches to a wider manual context. `invalid` always blocks dispatch.

Run-scoped task directories include:

- `semantic_slice.json`
- `context_preflight.json`
- `context_expansion_request.json`
- `impact_report.json`

Orchestrator completion rejects `verified` when preflight is not accepted, the slice is stale, `impact_report` is not passed, or unexpected impact remains. Medium/high-risk review must list `context_preflight` and `impact_report` in `review_basis`.

## 10. Failure Behavior

- Syntax errors generate provider diagnostics and an unresolved file boundary; no fabricated edges.
- Missing TypeScript runtime leaves TS/JS at unavailable capability and explains the setup command.
- Ambiguous symbols return candidates and require a stable ID or qualified name.
- Budgets stop traversal deterministically and mark the remaining frontier as boundary.
- Database corruption or revision mismatch invalidates the preflight.
- Provider crashes do not destroy the last good graph because builds replace atomically.

## 11. Verification

Tests use small multi-module Python and TS/JS fixtures with known definitions, imports, references, calls, unresolved dynamic calls, tests, and graph changes. Assertions cover query paths, stable revisions, ambiguity, truncation, expansion, freshness, post-edit edge deltas, Orchestrator gates, schema validation, initialization, and installed-skill smoke behavior.

The final acceptance run includes all Python unit tests, TypeScript provider smoke analysis, template synchronization, artifact/schema validation, Python compilation, JSON/PowerShell parsing, and `git diff --check`.

## 12. Non-Completion Conditions

The feature is not complete if any of the following is true:

- query names exist but providers cannot prove their capabilities
- unresolved or truncated edges are silently omitted
- slices lack graph revision, hashes, confidence, or provenance
- worker dispatch accepts stale or invalid context
- verification checks only the original slice and not post-edit impact
- the installed Skill lacks the provider runtime files, schemas, initialization scripts, or setup instructions
