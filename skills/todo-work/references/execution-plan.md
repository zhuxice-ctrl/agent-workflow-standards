# TODOwork Execution Plan

`execution_plan.json` is the validated task graph used by the main-window orchestrator.

## Shape

```json
{
  "schema": "ADworkflo.execution_plan.v2",
  "configured": true,
  "mvp_id": "mvp-login",
  "source_docs": ["ARCH.md", "TODO.md"],
  "worker_policy": {
    "max_parallel_workers": 3,
    "batching_rule": "dependencies-and-capacity",
    "handoff_outputs": ["worker_state.json", "verification_result.json"]
  },
  "batches": [
    {
      "batch_id": "batch-1-foundation",
      "parallel": true,
      "depends_on": [],
      "tasks": [
        {
          "task_id": "protocol-login",
          "module": "auth-protocol",
          "goal": "Implement the login protocol contract.",
          "depends_on": [],
          "task_spec_path": ".adworkflow/task_specs/protocol-login.json",
          "expected_outputs": ["worker_state.json", "verification_result.json"]
        }
      ]
    }
  ],
  "integration_tasks": [],
  "open_questions": []
}
```

## Validation And Scheduling

- Every task ID is unique.
- Every dependency references another task.
- The dependency graph must be acyclic.
- Logical module decomposition is not limited by runtime capacity.
- `max_parallel_workers` limits simultaneous in-progress tasks.
- Shared-file or shared-state tasks must be serialized even when their graph has no business dependency.

Use `validate_adworkflow.py` before starting a run. Use `orchestrator.py ready` to calculate dispatchable tasks.

## Task Boundary

Each task has one module, one goal, explicit dependencies, a configured task spec and task-scoped output artifacts under `.adworkflow/runs/<run_id>/tasks/<task_id>/`.
