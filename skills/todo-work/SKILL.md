---
name: todo-work
description: "Use TODOwork after ARCH/TODO are written to turn first-layer module checklists into capacity-aware ADworkflo execution plans, per-module task boundaries, module skill routing, clarification handoff, timeout fallback records, and worker artifact expectations. Trigger when the user says 使用 TODOwork, TODOwork skill, 根据 TODO 编排子 agent, or asks to execute ARCH/TODO module development."
---

# TODOwork

TODOwork converts the developer-written `TODO.md` into a second-layer execution plan. TODO is an audit checklist. ARCH is the source of MVP direction. TODOwork must not invent product design.

## Read First

Read, in order:

1. `ARCH.md`
2. `TODO.md`
3. `PRD.md`
4. `.adworkflow/module_skills.md`
5. `.adworkflow/architecture_manifest.json`
6. `.adworkflow/permissions.md`
7. `.adworkflow/verification_commands.md`
8. `.adworkflow/design_alignment_report.json`
9. `.adworkflow/layer_plan.json` when layered development is active

If `.adworkflow/execution_plan.json` exists, update it instead of starting from scratch.

## Workflow

1. Parse TODO into module tasks and audit IDs.
2. Map each TODO item back to ARCH module boundaries and MVP flow.
3. Stop when `design_alignment_report.gate_status` is not `passed`.
4. In layered mode, map product capability slices to presentation/protocol/data tasks without imposing a fixed layer order.
5. Generate or update `.adworkflow/execution_plan.json`.
6. Create task boundaries for each module task: goal, non-goals, dependencies, expected outputs, and assigned module skill.
7. Batch tasks for subagent execution using the configured runtime capacity and dependencies.
8. Require each subagent to output `diff` or changed-file summary plus `worker_state`.
9. Record uncertain details as clarification events in `worker_state`; do not make review judgments inside worker execution.

## Concurrency Rule

Use `references/execution-plan.md` for the execution plan shape.

Principle:

```text
TODO decides modules.
execution_plan decides batches and parallelism.
task_spec decides each subagent boundary.
```

Keep logical task decomposition independent from runtime capacity. Configure `worker_policy.max_parallel_workers` for the current platform, and dispatch only the ready tasks returned by dependency and capacity checks.

## Clarification And Timeout

Use `references/clarification-flow.md`.

When a subagent finds ARCH/TODO detail missing:

1. Stop expanding the task.
2. Report the missing detail to the main window.
3. Main window reviews PRD/ARCH/TODO.
4. If still unclear, main window asks the user and starts the configured timeout.
5. If no user reply arrives, main window gives the closest PRD/ARCH-based fallback instruction.
6. Subagent continues and records the event in `worker_state.clarification_events` and `worker_state.timeout_fallbacks`.

The worker window does not add external business constraints. It only executes, records, and reports.

## Outputs

Primary output:

- `.adworkflow/execution_plan.json`

Secondary outputs when needed:

- `.adworkflow/task_specs/<task_id>.json`
- `.adworkflow/module_skills.md`
- `.adworkflow/worker_state.json`

TODOwork does not directly claim MVP completion. MVP completion requires downstream implementation, verification, and final summary artifacts.
