# ADworkflo Agent Header

This project uses ADworkflo for AI-assisted engineering execution.

## Project Profile

- Project size: {{PROJECT_SIZE}}
- Context strategy: {{CONTEXT_STRATEGY}}
- Classification source: {{CLASSIFICATION_SOURCE}}
- Execution mode: {{EXECUTION_MODE}}
- Expected complexity score: {{EXPECTED_COMPLEXITY_SCORE}}
- Source files scanned: {{SOURCE_FILE_COUNT}}
- Approx source lines: {{SOURCE_LINE_COUNT}}
- Languages detected: {{LANGUAGES}}

## Execution Rules

1. For non-trivial tasks, create or update `.adworkflow/task_spec.json` before implementation.
2. For new or pre-code projects, read `.adworkflow/architecture_manifest.json` before relying on codegraph.
3. For MVP/module execution, read or create `.adworkflow/execution_plan.json` from ARCH/TODO before fan-out.
4. Do not read the whole repository by default. Create or update `.adworkflow/context_manifest.json` first.
5. If the task comes from PRD/ARCH/TODO, derive context from architecture_manifest before code exists.
6. Use codegraph after enough implementation exists to make symbol/import/test lookup meaningful.
7. Use the lightest sufficient context strategy:
   - small: `rg + file tree + manual context_manifest`
   - medium: symbol/import/test index
   - large: verified first-party L2 for Python/TS/JS; truthful L1 fallback for unsupported languages
8. If `.codegraph/index.json` is missing and code already exists for the task, build it with ADworkflo before routing code context.
9. Default to one worker for a single task. For TODOwork batches, dispatch only ready tasks within `max_parallel_workers`.
10. After edits, update the active task's `worker_state.json` under the run namespace; use root artifacts only for a single non-run task.
11. Before claiming completion, update the matching task-scoped `verification_result.json`.
12. For medium/high risk tasks, use review based on task spec, diff/change summary, verification result, and minimal context.
13. Do not use long chat history as a handoff artifact. Use ADworkflo artifacts.

## Main Window Flow

When the user gives a development task in the main window:

1. If the user asks for ARCHwork, prepare module skill routing from ARCH.
2. If the user asks for TODOwork, convert TODO modules into `.adworkflow/execution_plan.json`.
3. Convert the active task into a configured task spec and start a run for multi-task execution.
4. Run:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\prepare_context.py --project .
```

5. Read `.adworkflow/context_manifest.json` before implementation.
6. If `.adworkflow/module_skills.md` names a relevant module skill, load that skill before editing.
7. Implement only the scoped task.
8. If ARCH/TODO detail is missing, report to the main window and record the decision or timeout fallback in `worker_state.json`.
9. Run commands from `.adworkflow/verification_commands.md` when applicable.
10. Update task-scoped `worker_state.json`, `verification_result.json`, and `review_findings.json` when risk requires review.

## Local Files

- `.adworkflow/PROJECT.md`: current project operating state.
- `.adworkflow/architecture_manifest.json`: product-doc-based size, module, risk, and execution strategy analysis.
- `.adworkflow/execution_plan.json`: TODO-driven MVP subagent orchestration plan.
- `.adworkflow/task_specs/`: per-module task specs for subagents.
- `.adworkflow/task_spec.json`: current task contract.
- `.adworkflow/context_raw.json`: raw retrieval evidence from codegraph or architecture docs.
- `.adworkflow/context_manifest.json`: scoped context for worker.
- `.adworkflow/worker_state.json`: compact worker state.
- `.adworkflow/verification_result.json`: verification evidence.
- `.adworkflow/review_findings.json`: structured review output.
- `.adworkflow/permissions.md`: project-local permission boundary.
- `.adworkflow/verification_commands.md`: preferred local verification commands.
- `.adworkflow/module_skills.md`: module-specific skill routing rules.
- `.adworkflow/review_checklist.md`: reviewer checklist.
- `.adworkflow/final_summary.template.md`: final summary template for archived tasks.
- `.adworkflow/artifacts/`: optional completed-task artifact archive.
- `.codegraph/config.json`: project codegraph configuration.
- `.codegraph/index.json`: generated lightweight codegraph index when available.
