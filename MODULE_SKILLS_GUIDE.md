# Module Skills Guide

产品表现层、后端协议层和数据支撑层是产品架构维度，不自动等同于三个 module skills。只有 ARCH 明确声明了可重复的模块规则时才生成 module skill；layer contract 负责四问和独立审计，module skill 负责具体模块实现约束。

模块 skill 是项目内的局部开发规则，不是全局方法论。它用于把某个模块里反复出现、容易出错、需要稳定执行的知识封装起来。

真实开发中，是否生成 module skill 由开发者在 `ARCH.md` 的 `Module Skill Plan` 中显式声明。第二层 ADworkflo 不靠复杂度打分自行决定；TODO 只负责把这些声明审计化呈现，TODOwork 负责执行生成和编排。

## 什么时候在 ARCH 中声明模块 skill

适合在 ARCH 中声明：

- 模块有固定开发流程，例如 agent runtime、tool calling、RAG pipeline、权限流。
- 模块有强业务约束，例如 HR 审计、财务计算、审批状态机。
- 模块有固定验证方式，例如必须跑某组集成测试或回归脚本。
- 模块有稳定 UI/交互规范，例如设计系统组件、复杂表单、可视化图表。
- 模块经常被不同 worker 修改，需要统一边界和 handoff。

不适合声明：

- 一次性页面。
- 简单工具函数。
- Agent 读代码就能直接理解的普通模块。
- 还没有稳定规则的早期探索代码。

## 推荐目录

项目内可以这样放：

```text
skills/
  frontend-ui/
    SKILL.md
  agent-runtime/
    SKILL.md
  domain-audit/
    SKILL.md
```

然后在 ARCH 中写 `Module Skill Plan`，并在：

```text
.adworkflow/module_skills.md
```

写清楚主窗口什么时候加载它。TODO 中只需要把“生成 skill / 绑定 execution_plan / 审计状态”列成清单。

## module_skills.md 格式

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
module: agent-runtime
skill: skills/agent-runtime/SKILL.md
when: tool calling、planner、worker handoff、memory、权限边界变更
inputs: task_spec, context_manifest, ARCH.md
outputs: patch, worker_state, verification_result, review_findings if needed
verification: unit tests, integration smoke test, permission regression check
```

```text
module: frontend-ui
skill: skills/frontend-ui/SKILL.md
when: 页面布局、交互、可访问性、视觉一致性变更
inputs: task_spec, context_manifest, design notes
outputs: patch, worker_state, verification_result
verification: lint, component tests, browser smoke test
```

## SKILL.md 最小结构

```markdown
---
name: agent-runtime
description: Use when working on agent runtime, tool calling, planner, worker handoff, memory, permissions, or agent execution verification in this project.
---

# Agent Runtime

## Use When

- tool calling changes
- planner or worker handoff changes
- memory behavior changes
- permission boundary changes

## Read First

- ARCH.md
- .adworkflow/task_spec.json
- .adworkflow/context_manifest.json
- src/agent-runtime/

## Rules

- Keep permission checks explicit.
- Do not silently broaden tool access.
- Preserve worker_state and verification_result.

## Verification

- Run the agent runtime unit tests.
- Run one integration smoke test for tool calling.
- Record skipped checks in verification_result.json.
```

## 主窗口加载逻辑

```text
ARCH declares module skills
-> TODO audits module skill tasks
-> TODOwork creates execution_plan
-> task_spec.goal / acceptance_criteria
-> 判断模块
-> 查 .adworkflow/module_skills.md
-> 命中则加载对应 SKILL.md
-> 再进入 worker 实现
```

模块 skill 的价值是减少重复解释，而不是把所有知识都写成厚文档。能靠 `context_manifest` 精准定位解决的，不需要封装 skill。
