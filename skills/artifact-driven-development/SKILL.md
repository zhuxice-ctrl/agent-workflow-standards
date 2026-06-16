---
name: artifact-driven-development
description: Artifact-driven development workflow for complex coding tasks, multi-agent orchestration, review, verification, project import packs, task_spec/context_manifest/worker_state/verification_result/review_findings artifacts. Use when a task needs structured planning, bounded context, codegraph retrieval, worker/reviewer handoff, or reproducible verification.
---

# Artifact-driven Development

## Overview

Use this skill to run complex development work with structured artifacts instead of long chat history. Keep the always-loaded project header short; load this skill when the task needs planning, context retrieval, verification, review, or multi-agent coordination.

## Decision Rule

Use the project `AGENTS.md` header alone for tiny edits, typo fixes, and obvious one-file changes.

Use this skill when any of these apply:

- the task has multiple steps, files, or acceptance criteria
- context discovery matters before editing
- verification evidence must be preserved
- reviewer or multi-agent handoff may be needed
- a reusable project import pack is being created or updated

Default to `Solo Worker`. Escalate to `Worker + Reviewer` for public API, auth, permissions, billing, data, concurrency, cache, migration, state-machine, or large changes. Use `Fan-out Workers` only when subtasks are low-coupling and independently verifiable.

## Core Workflow

1. Create or confirm `task_spec` before editing.
2. For ARCH/TODO-driven MVP work, create or confirm `execution_plan` before spawning module workers.
3. Build `context_raw` and `context_manifest` from codegraph, architecture docs, or targeted search before reading large surfaces.
4. Select execution mode, defaulting to `solo_worker` for one task or TODOwork batches for module execution.
5. Implement the change and maintain `worker_state`.
6. Run deterministic verification and record `verification_result`.
7. If review is required, provide `task_spec`, `patch.diff`, and `verification_result` first.
8. Finish with changed files, behavior summary, verification result, remaining risks, and follow-ups.

Do not use full conversation history as handoff material. Exchange artifacts: `execution_plan`, `task_spec`, `context_raw`, `context_manifest`, `worker_state`, `patch.diff`, `review_findings`, and `verification_result`.

## Main Window Automation

In a project using the global ADworkflo skill, the main window should:

1. Use ARCHwork when the user wants ARCH-derived module skill routing.
2. Use TODOwork when the user wants TODO-derived module execution and subagent orchestration.
3. Write the active concrete task into `.adworkflow/task_spec.json` or `.adworkflow/task_specs/<task_id>.json`.
4. Run `prepare_context.py --project <project>` or the local `prepare-context.ps1` wrapper.
5. Read `.adworkflow/context_manifest.json`.
6. Check `.adworkflow/module_skills.md` for module-specific skill routing.
7. Implement, verify, and update artifacts.

`context_raw.json` is retrieval evidence. `context_manifest.json` is the worker-facing bounded context.

## References

Load only the reference needed for the current step:

- `references/task-spec.md`: task contract, scope, risk, acceptance criteria
- `references/context-manifest.md`: bounded context discovery and manifest fields
- `references/codegraph-retrieval.md`: codegraph retrieval order and budget rules
- `references/multi-agent-orchestration.md`: mode selection, roles, handoff rules
- `references/review-verification.md`: review levels, fix loop, completion evidence

## Templates

Copy and fill templates from `templates/` when the target project does not already have artifact files:

- `task_spec.json`
- `execution_plan.json`
- `context_raw.json`
- `context_manifest.json`
- `worker_state.json`
- `verification_result.json`
- `review_findings.json`

Keep JSON keys and enum values unchanged. Translate or customize only human-readable string values.
