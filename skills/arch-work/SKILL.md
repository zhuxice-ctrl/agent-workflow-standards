---
name: arch-work
description: "Use ARCHwork after PRD/ARCH/PROJECT are written to convert first-layer architecture intent into ADworkflo execution inputs: architecture_manifest review, module skill plan, module boundaries, MVP flow, uncertainty handling rules, and TODO-ready module development direction. Trigger when the user says 使用 ARCHwork, ARCHwork skill, 根据 ARCH 准备第二层执行, or asks to prepare module skills from ARCH."
---

# ARCHwork

ARCHwork prepares second-layer execution from first-layer architecture docs. It does not invent product direction. It reads the developer-written `ARCH.md` as the source of truth for MVP flow, module boundaries, and declared module skills.

## Read First

Read, in order:

1. `PRD.md`
2. `ARCH.md`
3. `PROJECT.md`
4. `.adworkflow/architecture_manifest.json` when it exists
5. `.adworkflow/module_skills.md` when it exists

If `.adworkflow/` is missing, initialize ADworkflo before continuing.

## Workflow

1. Confirm `ARCH.md` contains an MVP flow, module boundaries, and a declared module skill plan.
2. Treat ARCH declarations as authority. Do not decide new module skills by complexity score.
3. Update or prepare `.adworkflow/module_skills.md` from the ARCH-declared module skill plan.
4. Confirm TODO can audit the ARCH modules. If TODO is missing module skill tasks, report the gap for TODOwork.
5. Preserve uncertain or underspecified areas as execution notes. Do not add extra business constraints in this window.

## Required ARCH Sections

Use `references/arch-structure.md` when ARCH needs normalization.

Minimum expected sections:

- MVP development flow
- module planning
- module dependencies
- module skill plan
- integration sequence
- verification direction
- unresolved product or implementation decisions

## Outputs

Write or update only ADworkflo/project planning artifacts:

- `.adworkflow/architecture_manifest.json`
- `.adworkflow/module_skills.md`
- `.adworkflow/worker_state.json` when this skill performs a document task

Do not generate code. Do not run worker implementation. Leave module execution to TODOwork and ADworkflo.

## Unclear ARCH Details

If ARCH lacks detail:

1. Record the missing detail in `worker_state.must_keep_context`.
2. Ask the main window to review PRD/ARCH/PROJECT.
3. If the main window still cannot decide, it asks the user.
4. If the user timeout policy applies, use the closest PRD/ARCH interpretation and record the fallback in `worker_state.timeout_fallbacks`.

Do not evaluate external business, legal, brand, or review concerns in ARCHwork. Those belong to review/final reporting workflows. ARCHwork only records what happened and keeps execution aligned to the first-layer docs.
