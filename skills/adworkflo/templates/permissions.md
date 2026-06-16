# ADworkflo Permissions

This file defines the project-local operating boundary for AI-assisted engineering tasks.

## Default Allowed

- Read project files needed by `task_spec` and `context_manifest`.
- Edit files explicitly required by the current task.
- Run local build, lint, typecheck, unit test, and smoke test commands.
- Update ADworkflo artifacts under `.adworkflow/`.

## Require User Confirmation

- Installing or upgrading dependencies.
- Changing public API contracts, database schemas, auth, billing, permissions, deployment, or secrets handling.
- Deleting files, moving large directories, or applying broad formatting across unrelated files.
- Running commands that call external production services or mutate remote state.

## Forbidden By Default

- Reverting unrelated user changes.
- Using long chat history as task handoff material.
- Editing files outside the project root unless the user explicitly asks.
- Claiming completion without writing `verification_result.json`.
