# ADworkflo Agent Header

This project uses ADworkflo for AI-assisted engineering execution.

## Read Order

1. Read `PRD.md`, `ARCH.md`, `TODO.md`, and `PROJECT.md` when they exist.
2. Read `.adworkflow/architecture_manifest.json`.
3. Read `.adworkflow/permissions.md`, `.adworkflow/verification_commands.md`, and `.adworkflow/module_skills.md`.
4. Require `.adworkflow/design_alignment_report.json` to pass before ARCH/TODO execution.
5. Read `.adworkflow/layer_plan.json` when layered development is active.
6. Read `.adworkflow/execution_plan.json` when executing MVP/module work.
7. Read `.adworkflow/task_spec.json` or the run-scoped task spec.
8. Run or refresh context through `prepare_context.py`.
9. Resume complex runs from `.adworkflow/runs/<run_id>/resume_manifest.json`.

## Main Window Flow

When the user gives a development task in the main window:

1. If the user asks for ARCHwork, prepare module skill routing from ARCH.
2. If the user asks for TODOwork, convert TODO modules into `.adworkflow/execution_plan.json`.
3. Convert the active task into `.adworkflow/task_spec.json` or `.adworkflow/task_specs/<task_id>.json`.
4. Run:

```powershell
.\prepare-context.ps1
```

5. Read `.adworkflow/context_manifest.json`.
6. If `.adworkflow/module_skills.md` names a relevant module skill, load it before editing.
7. Implement only the scoped task.
8. If ARCH/TODO detail is missing, report to the main window and record the decision or timeout fallback in `worker_state.json`.
9. Run commands from `.adworkflow/verification_commands.md` when applicable.
10. Update `.adworkflow/worker_state.json`.
11. Update `.adworkflow/verification_result.json` before claiming completion.
12. For medium/high risk tasks, update `.adworkflow/review_findings.json`.

## Execution Rules

1. Product design is human-led. Engineering execution is artifact-driven.
2. For new projects, classify complexity from PRD/ARCH/TODO/PROJECT, not current LOC.
3. Before implementation, create or update `.adworkflow/task_spec.json`.
4. For TODOwork module execution, create or update `.adworkflow/execution_plan.json` before spawning subagents.
5. Before broad code reading, create or update `.adworkflow/context_manifest.json`.
6. Default to one worker for a single task. For TODOwork batches, dispatch only ready tasks within `max_parallel_workers`.
7. After edits, update `.adworkflow/worker_state.json`.
8. Before claiming completion, update `.adworkflow/verification_result.json`.
9. For medium/high risk tasks, use `.adworkflow/review_findings.json`.
10. Do not use long chat history as a handoff artifact. Use ADworkflo artifacts.

## Commands

Analyze product docs:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\analyze_project_plan.py --project . --update-profile
```

Prepare context from current task:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\prepare_context.py --project .
```

Build codegraph after code exists:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\build_codegraph.py --project .
```
