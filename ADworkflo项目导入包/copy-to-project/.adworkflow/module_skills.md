# ADworkflo Module Skills

这里记录项目内“模块级 skill”的使用规则。不是每个模块都要封装，只有当某个模块在 `ARCH.md` 的 `Module Skill Plan` 中被明确声明时才写入。

TODO 只负责把这些声明审计化呈现；TODOwork 负责把它们绑定到 `execution_plan.json`。

## 格式

```text
module: <模块或业务域>
skill: <skill 名称或路径>
when: <什么任务需要加载>
inputs: <需要读取的 artifact 或文件>
outputs: <期望产物>
verification: <优先验证方式>
```

## 示例

```text
module: frontend
skill: skills/frontend-ui/SKILL.md
when: 页面布局、交互、可访问性、视觉一致性变更
inputs: task_spec, context_manifest, design notes
outputs: patch, worker_state, verification_result
verification: lint, component tests, browser smoke test
```

```text
module: agent-runtime
skill: skills/agent-runtime/SKILL.md
when: tool calling、memory、planner、worker handoff、权限边界变更
inputs: task_spec, context_manifest, ARCH.md
outputs: patch, worker_state, verification_result, review_findings if needed
verification: unit tests, integration smoke test, permission regression check
```
