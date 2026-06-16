# ADworkflo Artifact Contracts

This file defines the minimum artifact contracts used by ADworkflo.

## architecture_manifest.json

Purpose: convert first-layer product docs into engineering execution strategy before code exists.

Required fields:

```json
{
  "schema": "ADworkflo.architecture_manifest.v1",
  "project_size": "small|medium|large",
  "classification_source": "product_docs|product_docs_empty|source_scan_fallback|manual",
  "expected_complexity_score": 0,
  "context_strategy": "architecture-first-l0-rg-manual-context|architecture-first-l1-symbol-import-test-index|architecture-first-l2-codegraph-after-code-exists",
  "execution_mode": "solo|solo-with-risk-review|orchestrator-with-workers-and-reviewers",
  "analysis_basis": [{"path": "PRD.md", "chars": 1200}],
  "planned_modules": ["frontend", "backend"],
  "data_stores": ["postgres"],
  "agent_features": ["tool_calling", "rag"],
  "risk_areas": ["permission boundary"],
  "recommended_artifacts": ["task_spec.json", "context_manifest.json"],
  "recommended_next_actions": []
}
```

Use this artifact before codegraph on new projects. Codegraph becomes useful after implementation files exist.

## task_spec.json

Purpose: define the task contract before implementation.

Required fields:

```json
{
  "task_id": "short-kebab-case-id",
  "goal": "What this task must accomplish.",
  "non_goals": ["What must not be changed."],
  "acceptance_criteria": ["Observable completion criteria."],
  "risk_level": "low|medium|high",
  "execution_mode": "solo_worker|worker_plus_reviewer|fanout_workers",
  "allowed_actions": ["read", "edit", "test"],
  "required_outputs": [
    "context_raw.json",
    "context_manifest.json",
    "worker_state.json",
    "verification_result.json"
  ]
}
```

## execution_plan.json

Purpose: convert TODO module checklists into main-window subagent orchestration.

Required fields:

```json
{
  "schema": "ADworkflo.execution_plan.v1",
  "mvp_id": "short-mvp-id",
  "source_docs": ["ARCH.md", "TODO.md"],
  "worker_policy": {
    "worker_limit": "unbounded-by-design",
    "batching_rule": "driven-by-todo-modules-and-arch-dependencies",
    "handoff_outputs": ["diff", "worker_state.json"]
  },
  "batches": [],
  "integration_tasks": [],
  "open_questions": []
}
```

TODO decides modules. `execution_plan` decides subagent batches. `task_spec` decides each worker boundary.

## context_raw.json

Purpose: keep graphcode/codegraph retrieval evidence separate from the worker-facing context.

Required fields:

```json
{
  "schema": "ADworkflo.context_raw.v1",
  "task_id": "same-as-task-spec",
  "source": "codegraph-index|architecture-manifest",
  "matched_files": [],
  "matched_symbols": [],
  "likely_tests": [],
  "warnings": []
}
```

## context_manifest.json

Purpose: tell the worker where to look first.

`context_manifest.json` is the worker-facing summary. If retrieval was automated, preserve the retrieval evidence in `context_raw.json`.

Required fields:

```json
{
  "task_id": "same-as-task-spec",
  "context_level": "L0-rg|L1-index|L2-codegraph",
  "read_first": ["path/to/file"],
  "relevant_symbols": ["SymbolName"],
  "entrypoints": ["route/command/function"],
  "likely_tests": ["path/to/test"],
  "do_not_touch": ["path/or/module"],
  "open_questions": []
}
```

## worker_state.json

Purpose: replace long chat history with compact execution state.

Required fields:

```json
{
  "task_id": "same-as-task-spec",
  "status": "not_started|in_progress|blocked|implementation_complete|verified",
  "done": [],
  "changed_files": [],
  "current_problem": "",
  "next_action": "",
  "must_keep_context": [],
  "remaining_risks": [],
  "clarification_events": [],
  "timeout_fallbacks": []
}
```

## verification_result.json

Purpose: record evidence, not confidence.

Required fields:

```json
{
  "task_id": "same-as-task-spec",
  "commands": [],
  "passed": [],
  "failed": [],
  "not_run": [],
  "summary": "",
  "residual_risk": ""
}
```

## review_findings.json

Purpose: provide structured review output.

Required fields:

```json
{
  "task_id": "same-as-task-spec",
  "status": "approved|changes_requested",
  "blocking_findings": [],
  "non_blocking_findings": [],
  "review_basis": ["task_spec", "diff", "verification_result"]
}
```
