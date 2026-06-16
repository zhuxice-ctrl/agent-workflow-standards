# ADworkflo Module Skills

Use this file to list project-specific module skills that should be loaded for focused work.

Only add module skills explicitly declared by `ARCH.md` Module Skill Plan. TODO audits these declarations; TODOwork binds them into `execution_plan.json`.

## Format

```text
module: <module-or-domain-name>
skill: <skill-name-or-path>
when: <when the main window should use it>
inputs: <task_spec/context_manifest/files needed>
outputs: <expected artifact or implementation output>
verification: <preferred checks>
```

## Default Modules

Add module skills only when a module has repeatable rules that are not obvious from normal code reading.

Examples:

```text
module: frontend
skill: skills/frontend-ui/SKILL.md
when: UI layout, interaction, accessibility, or visual consistency changes
inputs: task_spec, context_manifest, design notes
outputs: patch, worker_state, verification_result
verification: lint, component tests, browser smoke test
```
