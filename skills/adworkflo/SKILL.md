---
name: adworkflo
description: Use when starting or managing an AI-assisted software development task with Artifact-driven Workflow, product-doc alignment, layered development, project-local agent headers, task specs, context manifests, resumable orchestrator state, verification evidence, review findings, or codegraph retrieval.
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
- Deciding whether a project needs `rg`, the bundled L1 index, or the verified first-party L2 semantic graph.
- Coordinating worker/reviewer/finalizer agents.

Do not force the full workflow on tiny edits. For trivial changes, keep the process lightweight and still verify the result.

When the user explicitly asks for layered development on a complex product, load `references/layered-development.md`, generate `.adworkflow/layer_plan.json`, and require the three layer contracts plus cross-layer gates before module execution.

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
  design_alignment_report.json
  layer_plan.json
  interface_contracts.json
  execution_plan.json
  task_spec.json
  task_specs/
  context_raw.json
  context_manifest.json
  semantic_slice.json
  context_preflight.json
  context_expansion_request.json
  impact_report.json
  worker_state.json
  verification_result.json
  review_findings.json
  permissions.md
  verification_commands.md
  review_checklist.md
  module_skills.md
  final_summary.template.md
  artifacts/
  runs/
.codegraph/
  config.json
  l2.sqlite
  snapshots/
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
-> design_alignment.py creates the structural PRD-ARCH gate
-> independent semantic review approves or blocks the gate
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

By default, initialization analyzes only named first-layer docs such as `PRD.md`, `ARCH.md`, `TODO.md`, `PROJECT.md`, and Chinese equivalents. Pass explicit `--docs` paths for custom names; unrelated Markdown and README files are not implicit architecture inputs. If product docs exist, their expected architecture decides `small`, `medium`, or `large`.

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

## Build Codegraph

After implementation files exist, build a project-local index:

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\build_codegraph.py --project <PROJECT_PATH>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\build_codegraph.py --project <PROJECT_PATH> --level l2
```

This writes:

```text
<PROJECT_PATH>\.codegraph\index.json
<PROJECT_PATH>\.codegraph\l2.sqlite
```

V1 index contains:

- files
- languages
- line counts
- simple symbols
- simple imports
- likely test files

L1 is the portable file/symbol/import/test index. L2 uses the first-party Python `ast`/`symtable` provider and, when installed, the TypeScript Compiler API provider. Install the TS/JS runtime once per installed skill:

```powershell
npm install --prefix $env:ADWORKFLO_SKILL_ROOT\providers\typescript --ignore-scripts
```

Never claim L2 for a language whose provider does not pass the capability probe.

## Query Codegraph

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> summary
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> find-definition --symbol <SYMBOL>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> tests-for --target <FILE_OR_SYMBOL>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> callers --symbol <QUALIFIED_SYMBOL>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> impact --target <SYMBOL_OR_FILE>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT_PATH> slice --entrypoint <QUALIFIED_SYMBOL> --out <SLICE_PATH>
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
<PROJECT_PATH>\.adworkflow\semantic_slice.json
<PROJECT_PATH>\.adworkflow\context_preflight.json
```

Use it after the orchestrator has written `task_spec.json`.

Behavior:

- L0/L1 tasks build or refresh `.codegraph/index.json` and create bounded context as before.
- Configured L2 tasks build or refresh `.codegraph/l2.sqlite`, then create the slice and preflight artifacts.
- `needs_expansion` blocks dispatch until `apply_context_expansion.py` updates the slice, preflight, manifest, and worker history.
- `invalid` requires a graph rebuild or an unambiguous entrypoint; it cannot be waived by chat text.
- After edits, `codegraph_post_edit.py` rebuilds the graph and writes `impact_report.json`.
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
- `.adworkflow/runs/<run_id>/`: active multi-task control state and isolated task artifacts.

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

### Large Project: Verified L2 Semantic Graph

The bundled engine uses:

```text
Python ast/symtable + TypeScript Compiler API providers + revisioned SQLite graph
```

Use definition/reference/caller/callee/impact/slice queries only for languages listed by the capability probe. Unsupported languages remain L1 and must be recorded as a context boundary.

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
-> prepare_context creates context_raw/context_manifest and, for L2, semantic_slice/context_preflight
-> Worker implements scoped task
-> Build/update codegraph as code appears
-> Worker outputs patch + worker_state
-> Rebuild graph and generate post-edit impact_report
-> Verifier records verification_result and checks unexpected impact
-> Reviewer checks diff, context_preflight, and impact_report when risk requires it
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
task_spec + context_manifest + accepted context_preflight when L2 is active
```

Worker outputs:

```text
patch or change summary
worker_state
verification_result when it runs checks
```

Worker should read only the needed context first. It can request more context with a specific reason.

For L2, the worker writes a pending `context_expansion_request.json` instead of guessing across an unresolved or truncated boundary. Apply it with `apply_context_expansion.py`; the expansion is recorded in `semantic_slice.expansion_history` and `worker_state.context_expansion_history`.

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

For L2 tasks, reviewer input must also include `context_preflight.json` and the post-edit `impact_report.json`. Review is based on observed impact, not only the original slice.

## Codegraph Retrieval Rule

Use the lightest sufficient context strategy:

```text
small: rg + manual manifest
medium: symbol/import/test index
large: verified first-party L2 for Python/TS/JS, truthful L1 fallback for unsupported languages
```

For detailed codegraph design, read `references/codegraph-design.md`.

## Artifact Contracts

For artifact fields and examples, read `references/artifact-contracts.md`.
