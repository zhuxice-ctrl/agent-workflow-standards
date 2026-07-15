# ADworkflo Project Instructions

This project uses ADworkflo. Treat `.adworkflow/` artifacts as the durable execution state.

## Required Order

1. For complex work, configure `.adworkflow/task_spec.json` before editing.
2. For PRD/ARCH work, require `.adworkflow/design_alignment_report.json` to pass before TODO execution.
3. When layered development is explicitly requested, configure `.adworkflow/layer_plan.json` and its three layer contracts.
4. Run `prepare_context.py`, then read `.adworkflow/context_manifest.json` before broad code reading.
5. Use `.adworkflow/runs/<run_id>/` for multi-task execution and resume from `resume_manifest.json` after context compression.
6. Update task-scoped `worker_state.json` and `verification_result.json` before claiming completion.
7. Medium/high-risk tasks require independent review evidence.
8. L2 tasks require an accepted `context_preflight` before work and a passed post-edit `impact_report` before verification.

Project profile: size={{PROJECT_SIZE}}, context={{CONTEXT_STRATEGY}}, execution={{EXECUTION_MODE}}.
