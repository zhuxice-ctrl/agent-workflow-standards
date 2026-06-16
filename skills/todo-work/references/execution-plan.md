# TODOwork Execution Plan

`execution_plan.json` is the main-window orchestration artifact for MVP module execution.

## Shape

```json
{
  "schema": "ADworkflo.execution_plan.v1",
  "mvp_id": "",
  "source_docs": ["ARCH.md", "TODO.md"],
  "worker_policy": {
    "worker_limit": "unbounded-by-design",
    "batching_rule": "driven-by-todo-modules-and-arch-dependencies",
    "handoff_outputs": ["diff", "worker_state.json"]
  },
  "batches": [
    {
      "batch_id": "batch-1-foundation",
      "parallel": true,
      "depends_on": [],
      "tasks": [
        {
          "task_id": "frontend-ui-home",
          "todo_id": "T001",
          "module": "frontend-ui",
          "goal": "",
          "module_skill": "skills/frontend-ui/SKILL.md",
          "task_spec_path": ".adworkflow/task_specs/frontend-ui-home.json",
          "expected_outputs": ["diff", "worker_state.json"]
        }
      ]
    }
  ],
  "integration_tasks": [],
  "open_questions": []
}
```

## Batching

Create a new batch when ARCH/TODO says a task depends on another task. Mark `parallel: true` when tasks can be assigned to separate workers in the same batch.

Do not use a fixed max worker count. The number of workers follows the number of module tasks in the active batch.

## Subagent Boundary

Each task must have:

- one module
- one goal
- non-goals
- expected outputs
- module skill path when ARCH declared one
- clear handoff: `diff` plus `worker_state`
