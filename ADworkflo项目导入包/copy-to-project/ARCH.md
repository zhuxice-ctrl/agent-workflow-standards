# ARCH

## 架构目标

- 产品形态：
- 技术栈：
- 部署方式：

## 模块规划

| 模块 | 责任 | 输入 | 输出 | 依赖 | 是否需要 module skill | skill path |
|---|---|---|---|---|---|---|
| frontend |  |  |  |  | yes/no | skills/frontend/SKILL.md |
| backend |  |  |  |  | yes/no | skills/backend/SKILL.md |
| database |  |  |  |  | yes/no | skills/database/SKILL.md |

## Module Skill Plan

只在这里声明需要生成的项目级 module skills。第二层不根据打分自行新增 module skill。

### <module-name>

- skill path:
- 使用场景：
- 固定开发模板：
- 输入 artifacts：
- 输出 artifacts：
- 子 agent 遇到不确定时的上报方式：

## 核心流程

```text
入口
-> 
-> 
-> 输出
```

## 数据设计

| 数据对象 | 字段 | 说明 |
|---|---|---|
|  |  |  |

## 第三方服务

| 服务 | 用途 | 失败处理 |
|---|---|---|
|  |  |  |

## 权限与安全

- 认证：
- 权限：
- 敏感数据：
- 高风险操作：

## 测试与验收

- 单元测试：
- 集成测试：
- E2E：
- 手工验收：

## 第二层执行约定

- ARCH 是 MVP 开发流程的主依据。
- TODO 只作为模块化审计清单。
- TODOwork 根据 TODO 生成 `.adworkflow/execution_plan.json`。
- 子 agent 数量不设固定上限，由 TODO 模块拆分和 ARCH 依赖决定。
- 子 agent 遇到 ARCH 细节不足时，上报主窗口；主窗口复核 PRD/ARCH/TODO，仍不确定时问用户。
- 用户超时未反馈时，主窗口按最接近 PRD/ARCH 的解释给出 fallback，并要求子 agent 写入 `worker_state`。
