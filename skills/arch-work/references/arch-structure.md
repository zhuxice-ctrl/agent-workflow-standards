# ARCHwork ARCH Structure

Use this structure when normalizing or checking `ARCH.md`.

## MVP Development Flow

Write the complete MVP flow as an ordered pipeline:

```text
entry
-> module-a
-> module-b
-> integration
-> verification
```

## Module Planning

```markdown
| module | responsibility | inputs | outputs | dependencies | owner skill |
|---|---|---|---|---|---|
| frontend-ui |  |  |  |  | skills/frontend-ui/SKILL.md |
```

## Module Skill Plan

Only list module skills explicitly chosen by the developer.

```markdown
### frontend-ui

skill path: skills/frontend-ui/SKILL.md
reason: 固定 UI 开发模板、视觉约定、验证方式
scope:
- pages
- components
- styles
handoff:
- diff
- worker_state
- verification_result when applicable
```

## Unresolved Decisions

Keep unresolved items visible:

```markdown
| id | module | question | current fallback source |
|---|---|---|---|
| Q001 | frontend-ui | 美术方向只写了“类似 4399”，未细化 | PRD/ARCH closest interpretation |
```
