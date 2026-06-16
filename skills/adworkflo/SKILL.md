---
name: adworkflo
description: Use when starting or managing an AI-assisted software development task with Artifact-driven Workflow, product-doc-based architecture analysis, project-local agent headers, task specs, context manifests, worker state, verification evidence, review findings, or codegraph retrieval. Also use when the user asks to initialize ADworkflo in a project, automate the engineering execution layer after PRD/ARCH/TODO, classify project size, or decide whether to use rg, symbol index, or full codegraph.
---

# ADworkflo

ADworkflo is a lightweight automation layer for AI-assisted development. It turns chat-driven coding into artifact-driven execution.

Core principle:

> Product design can stay human-led. Engineering execution should be driven by task contracts, scoped context, worker state, verification evidence, and review findings.

## When To Use

Use this skill when the task involves:

- Initializing an AI development workflow in a repo.
- Turning product requirements into engineering execution.
- Creating `task_spec`, `context_manifest`, `worker_state`, `verification_result`, or `review_findings`.
- Deciding whether a project needs `rg`, a symbol/import/test index, or a full codegraph.
- Coordinating worker/reviewer/finalizer agents.

Do not force the full workflow on tiny edits. For trivial changes, keep the process lightweight and still verify the result.

## Two-Layer Model

### 1. Global Skill

This skill stores the reusable method:

- Workflow rules.
- Project size classification.
- Artifact contracts.
- Codegraph levels.
- Initialization script and templates.

### 2. Project-Local Files

Each project gets only local facts and minimum execution discipline:

```text
.codex/
  AGENT_HEADER.md
.adworkflow/
  ADWORKFLOW_PROFILE.json
  PROJECT.md
  architecture_manifest.json
  execution_plan.json
  task_spec.json
  task_specs/
  context_raw.json
  context_manifest.json
  worker_state.json
  verification_result.json
  review_findings.json
  permissions.md
  verification_commands.md
  review_checklist.md
  module_skills.md
  final_summary.template.md
  artifacts/
.codegraph/
  config.json
```

Global skill is the method. Project-local files are the current project's operating context.

## Initialize A Project

Run:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <PROJECT_PATH>
```

Recommended order for new projects:

```text
User writes PRD / ARCH / TODO / PROJECT
-> init_adworkflow.py auto-analyzes first-layer docs
-> .adworkflow/architecture_manifest.json
-> .adworkflow/ADWORKFLOW_PROFILE.json
-> task_spec + context_manifest
-> worker implementation
-> build codegraph after code exists
```

Optional:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <PROJECT_PATH> --mode small
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <PROJECT_PATH> --mode medium
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <PROJECT_PATH> --mode large
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <PROJECT_PATH> --skip-doc-analysis
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <PROJECT_PATH> --force
```

The script does not overwrite existing files unless `--force` is used.

By default, initialization analyzes first-layer Markdown docs such as `PRD.md`, `ARCH.md`, `TODO.md`, `PROJECT.md`, Chinese equivalents, and shallow project docs. If product docs exist, their expected architecture decides `small`, `medium`, or `large`. Source file count and LOC are only a fallback for existing projects or projects without product docs.

## Analyze Product Docs

Run this when first-layer docs changed after initialization:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\analyze_project_plan.py --project <PROJECT_PATH> --update-profile
```

Use explicit docs when the project contains many unrelated Markdown notes:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\analyze_project_plan.py --project <PROJECT_PATH> --docs <PROJECT_PATH>\PRD.md <PROJECT_PATH>\ARCH.md --update-profile
```

This writes:

```text
<PROJECT_PATH>\.adworkflow\architecture_manifest.json
```

Use `architecture_manifest.json` to generate the first `task_spec` and `context_manifest` before implementation files exist.

## Build Lightweight Codegraph

After implementation files exist, build a project-local index:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\build_codegraph.py --project <PROJECT_PATH>
```

This writes:

```text
<PROJECT_PATH>\.codegraph\index.json
```

V1 index contains:

- files
- languages
- line counts
- simple symbols
- simple imports
- likely test files

It is enough for small/medium project context routing. Large projects may still need a stronger language-server or tree-sitter based codegraph later.

## Query Codegraph

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> summary
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> find-definition --symbol <SYMBOL>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> tests-for --target <FILE_OR_SYMBOL>
```

Generate an initial context manifest from a task spec:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> make-context --task <PROJECT_PATH>\.adworkflow\task_spec.json
```

## Prepare Context From Main Window

For normal local use, prefer the main-window bridge command:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\prepare_context.py --project <PROJECT_PATH>
```

Default inputs:

```text
<PROJECT_PATH>\.adworkflow\task_spec.json
```

Default outputs:

```text
<PROJECT_PATH>\.adworkflow\context_raw.json
<PROJECT_PATH>\.adworkflow\context_manifest.json
```

Use it after the orchestrator has written `task_spec.json`.

Behavior:

- If source files exist and `.codegraph/index.json` is missing, it builds the lightweight codegraph first.
- If codegraph has usable source data, it derives `context_raw.json` and `context_manifest.json` from code matches.
- If code does not exist yet, it falls back to `architecture_manifest.json`, `PRD.md`, `ARCH.md`, `TODO.md`, `PROJECT.md`, and project-local config files.

This is the recommended answer to "task_spec has been generated; how does graphcode get called?"

## Project-Local Manual Configs

The user still owns product design docs. The automation layer owns engineering execution. Keep these project-local files current:

- `.adworkflow/permissions.md`: what the agent may do, what requires confirmation, and what is forbidden.
- `.adworkflow/verification_commands.md`: project-native commands the verifier should run.
- `.adworkflow/module_skills.md`: module/domain-specific skills to load for focused work.
- `.adworkflow/execution_plan.json`: TODO-driven MVP orchestration plan for subagents.
- `.adworkflow/task_specs/<task_id>.json`: per-module task specs generated from execution_plan.
- `.adworkflow/review_checklist.md`: reviewer inputs and risk checks.
- `.adworkflow/final_summary.template.md`: final output shape for important tasks.
- `.adworkflow/artifacts/<task_id>/`: optional archive for completed task artifacts.

Do not turn every module into a skill. Create module skills only when a module has repeatable rules, special domain constraints, strict UI/design conventions, non-obvious verification, or a recurring implementation pattern.

## Project Size Classification

ADworkflo uses three levels.

Classification priority:

```text
1. Product docs: expected modules, data, agent behavior, risk, platforms, deployment.
2. Manual override: --mode small|medium|large.
3. Source scan fallback: source file count and LOC for existing projects.
```

Do not classify a new project only by current LOC. A pre-development repo can be empty while the planned system is medium or large.

### Small Project: L0 Context

Use:

```text
rg + file tree + manual context_manifest
```

Typical signs:

- Up to about 50 source files or 5k source lines.
- Simple module boundaries.
- One worker can understand the task context quickly.
- Call chains are shallow.

Goal: move fast. Do not introduce a graph system heavier than the project.

### Medium Project: L1 Index

Use:

```text
symbol index + import index + test index
```

Typical signs:

- 50-300 source files or up to about 50k source lines.
- Several modules, services, screens, routes, or tests.
- `rg` still works, but definition/import/test lookup is repeatedly needed.

Goal: stop workers from rediscovering definitions, imports, and relevant tests from scratch.

### Large Project: L2 Codegraph

Use:

```text
definition/reference/caller/callee/tests_for/impacted_files/get_slice
```

Typical signs:

- 300+ source files or 50k+ source lines.
- Deep call chains, multiple services, shared state, complex runtime flows, or many agents.
- A change can affect multiple entrypoints or test surfaces.

Goal: control impact analysis and reduce wrong edits.

## Default Execution Flow

```text
Product docs prepared by user
-> analyze_project_plan creates architecture_manifest
-> ARCHwork reads ARCH-declared module skill plan
-> TODOwork creates execution_plan from TODO module checklist
-> Orchestrator creates task_specs from execution_plan
-> prepare_context creates context_raw and context_manifest
-> Worker implements scoped task
-> Build/update codegraph as code appears
-> Worker outputs patch + worker_state
-> Verifier records verification_result
-> Reviewer checks diff when risk requires it
-> Finalizer summarizes completed work and residual risk
```

## Orchestrator Rules

The orchestrator owns the workflow, not the implementation details.

It should:

- Convert user/product intent into `task_spec`.
- Convert ARCH/TODO module plans into `execution_plan`.
- Fan out subagents from `execution_plan` without a hard worker limit.
- Decide `solo`, `review`, or `fanout`.
- Create or update `context_manifest`.
- Assign worker scope.
- Require `worker_state` and `verification_result`.
- Escalate to reviewer when risk is medium/high.
- Keep final summaries tied to evidence.

It should not:

- Dump long chat history into workers.
- Fan out shared-state tasks by default.
- Treat "agent says done" as completion without verification.

## Worker Rules

Worker receives:

```text
task_spec + context_manifest
```

Worker outputs:

```text
patch or change summary
worker_state
verification_result when it runs checks
```

Worker should read only the needed context first. It can request more context with a specific reason.

When ARCH/TODO details are missing, the worker should stop expanding, report the question to the main window, wait for a PRD/ARCH/TODO-backed decision or configured timeout fallback, then record the event in `worker_state.clarification_events` and `worker_state.timeout_fallbacks`. The worker records facts and decisions; review judgments belong to reviewer/final reporting artifacts.

## Reviewer Rules

Reviewer default input:

```text
task_spec + patch.diff/change summary + verification_result + minimal context
```

Reviewer checks:

- Acceptance criteria.
- Regressions.
- Missing tests.
- Security, permission, data consistency risks.
- Caller/consumer impact when relevant.

Reviewer should not become a second developer unless explicitly asked.

## Codegraph Retrieval Rule

Use the lightest sufficient context strategy:

```text
small: rg + manual manifest
medium: symbol/import/test index
large: full codegraph
```

For detailed codegraph design, read `references/codegraph-design.md`.

## Artifact Contracts

For artifact fields and examples, read `references/artifact-contracts.md`.
