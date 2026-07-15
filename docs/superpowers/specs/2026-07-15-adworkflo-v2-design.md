# ADworkflo v2 Reliability Design

## Goal

将 ADworkflo 从依赖 Agent 自觉遵守的协议脚手架，升级为具有机器可校验契约、设计追踪、可信检索、任务隔离和可恢复主窗口状态的工程工作流。

## Product Development Model

当用户明确提出“使用分层开发”时，产品工作采用三个架构维度：

- `presentation`：产品表现层。
- `protocol`：后端协议层。
- `data`：数据支撑层。

每层必须建立四问契约：最终目标、范围与边界、非完成条件、探索与独立审计。三层用于责任划分，不硬编码为瀑布顺序；execution plan 仍按真实依赖组织纵向产品能力切片。

安全、权限、隐私、性能、可观测性、部署和端到端验证属于跨层质量门禁。

## Canonical Contracts

`skills/adworkflo/templates/` 是 JSON 模板的唯一来源。`sync_templates.py` 将共享模板同步到根 `templates/`、协议 skill 模板和项目导入包。`--check` 在 CI 或本地验证副本没有漂移。

所有运行 artifact 拥有 schema 标识和可验证初始状态。尚未填写的 task template 使用 `configured: false`，`prepare_context` 必须拒绝执行，避免把占位内容当成真实任务。

## Design Alignment Gate

`design_alignment.py` 从 PRD 提取 requirement IDs，从 ARCH 提取显式 requirement 引用和模块声明，生成 `.adworkflow/design_alignment_report.json`。

结构覆盖缺失会直接阻塞。语义冲突、范围扩大和实现合理性必须由独立 Design Reviewer 填写，脚本不得伪装成语义理解器。只有结构覆盖完成且语义审计批准后，gate 才能通过。

## Context And Codegraph

轻量索引只声明实际支持的 L0/L1 能力。大项目在没有真实 L2 provider 时标记为 `L1-large-project` 并写入 limitation。

索引记录每个文件的 SHA-256；prepare 前比较当前源码集合和哈希。索引过期时默认重建，`--no-build-index` 时降级并写 warning。

task spec 增加 `task_type`、`do_not_touch`、`entrypoints` 和 `context_sources`。产品、架构、workflow、文档任务优先读取文档；代码任务使用代码索引并补充显式文档来源。

## Orchestrator State

每次复杂执行使用：

```text
.adworkflow/runs/<run_id>/
  orchestrator_state.json
  resume_manifest.json
  artifact_registry.json
  execution_plan.json
  tasks/<task_id>/...
```

控制 CLI 负责启动 run、校验依赖图、创建 task namespace、计算 ready tasks、记录任务状态和生成恢复顺序。它不直接调用平台的 Agent API，主窗口根据 ready tasks 使用当前平台能力分派。

状态更新使用递增 revision。恢复时先读 resume manifest，再读 orchestrator state 和当前任务 artifacts；聊天摘要不作为事实来源。

## Initialization Safety

普通 `--force` 只更新机器生成文件。permissions、verification commands、module skills 和 review checklist 属于用户维护文件，只有显式 `--force-user-config` 才覆盖。

初始化在根 `AGENTS.md` 不存在时创建最小 ADworkflo 头文件；已存在时不覆盖并打印检查提示。

## Verification

使用 Python `unittest` 构造临时项目，覆盖 schema/template 同步、文档误判、PRD-ARCH 覆盖、索引过期、声明查询、上下文路由、DAG 校验、run 恢复和初始化保护。所有文档声明必须与可执行测试保持一致。
