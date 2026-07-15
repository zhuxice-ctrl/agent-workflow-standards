# ADworkflo Artifact Contracts

The JSON schemas under `schemas/` are authoritative. `skills/adworkflo/templates/` is the canonical template source; run `sync_templates.py --write` after changing a shared template and `--check` in verification.

## Design Artifacts

- `architecture_manifest.json`: product-doc classification, explicit ARCH modules, heuristic suggestions, risks and source hashes.
- `design_alignment_report.json`: PRD requirement coverage, ARCH-only scope additions, independent semantic review and the gate status.
- `layer_plan.json`: explicitly triggered presentation/protocol/data four-question contracts, capability slices and cross-layer gates.
- `interface_contracts.json`: provider/consumer boundaries, inputs, outputs, errors, compatibility and verification.

`planned_modules` comes only from explicit ARCH module planning. Heuristic detections belong in `suggested_modules` and cannot silently become execution scope.

## Execution Artifacts

- `execution_plan.json`: configured v2 dependency graph plus `max_parallel_workers`.
- `task_spec.json`: configured v2 task contract with task type, semantic non-goals, concrete do-not-touch paths, entrypoints and context sources.
- `context_raw.json`: retrieval evidence and limitations.
- `context_manifest.json`: bounded read order for one task.
- `semantic_slice.json`: L2 included/boundary/excluded symbols, ranges, revision, hashes, confidence and provenance.
- `context_preflight.json`: L2 freshness/capability/confidence gate with accepted, needs-expansion or invalid state.
- `context_expansion_request.json`: targeted relation/depth/budget request tied to a graph revision.
- `impact_report.json`: baseline/current graph delta, predicted/observed files, unexpected impact and new critical unresolved edges.
- `worker_state.json`: task-scoped state with monotonic revision.
- `verification_result.json`: source revision, commands and acceptance-criteria coverage.
- `review_findings.json`: reviewer, source revision, review basis and structured findings.

An unconfigured template is valid scaffolding but is not executable. Scripts must reject `task_spec.configured=false` and `execution_plan.configured=false`.

## Main-Window Control Artifacts

Complex multi-task runs live under `.adworkflow/runs/<run_id>/`:

```text
orchestrator_state.json
resume_manifest.json
artifact_registry.json
execution_plan.json
tasks/<task_id>/
  task_spec.json
  context_raw.json
  context_manifest.json
  semantic_slice.json
  context_preflight.json
  context_expansion_request.json
  impact_report.json
  worker_state.json
  verification_result.json
  review_findings.json
```

`orchestrator_state` is the current control truth. `resume_manifest` defines deterministic rehydration after compression. `artifact_registry` binds paths to hashes and revisions. A stale expected revision must not overwrite newer state.

## Completion Gate

A task is complete only when its acceptance criteria are mapped to passing evidence, required review is approved for the same source revision, blocking findings are empty, and residual risks are recorded. L2 tasks additionally require an accepted preflight, a passed post-edit impact report, no unexpected impact, and no new critical unresolved edge. A product is complete only after layer/cross-layer gates and PRD requirements are satisfied.
