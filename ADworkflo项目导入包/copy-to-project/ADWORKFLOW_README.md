# ADworkflo 本地项目文件

这个目录可以直接复制进工程根目录，用来把 ADworkflo 的第二层工程执行自动化接入项目。

第一层产品设计文档仍然由你手动写：`PRD.md`、`ARCH.md`、`TODO.md`、`PROJECT.md`。第二层从 `task_spec` 开始自动化：生成上下文、约束 worker、记录验证和 review。

## 推荐方式

新工程优先使用全局初始化脚本：

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <工程根目录>
```

它会从全局 skill 生成 `.codex`、`.adworkflow`、`.codegraph`，并根据产品文档判断项目规模。

## 手动复制方式

把 `copy-to-project` 里的全部内容复制到工程根目录，然后补全：

```text
PRD.md
ARCH.md
TODO.md
PROJECT.md
.adworkflow/permissions.md
.adworkflow/verification_commands.md
.adworkflow/module_skills.md
```

产品文档写好后运行：

```powershell
.\analyze-product-docs.ps1
```

它会更新：

```text
.adworkflow/architecture_manifest.json
.adworkflow/ADWORKFLOW_PROFILE.json
```

## 主窗口执行流程

第一层文档写完后，先在主窗口执行：

```text
使用 ARCHwork skill 根据 ARCH 准备第二层执行。
使用 TODOwork skill 根据 TODO 编排子 agent 模块开发。
```

然后再说清楚具体任务，例如：

```text
使用 ADworkflo 执行这个任务：给登录页增加验证码校验，并补充测试。
```

主窗口应该按这个顺序做：

```text
用户需求
-> ARCHwork 更新 module skill 路由
-> TODOwork 生成 .adworkflow/execution_plan.json
-> 写入 .adworkflow/task_spec.json 或 .adworkflow/task_specs/<task_id>.json
-> 运行 .\prepare-context.ps1
-> 得到 .adworkflow/context_raw.json
-> 得到 .adworkflow/context_manifest.json
-> L2 任务得到 semantic_slice.json 和 context_preflight.json
-> preflight accepted 后才进入实现
-> 按 module_skills.md 判断是否加载模块 skill
-> 子 agent 按 execution_plan 并发实现
-> 写 worker_state.json
-> 按 verification_commands.md 验证
-> 运行 codegraph-post-edit.ps1 生成实际 impact_report.json
-> 写 verification_result.json
-> 中/高风险任务写 review_findings.json
-> 必要时归档到 .adworkflow/artifacts/<task_id>/
```

## 本地脚本

```powershell
.\align-design.ps1
```

生成 PRD-ARCH 结构覆盖报告。结构覆盖完成后，使用独立 Reviewer 名称批准语义审计：

```powershell
.\align-design.ps1 -Reviewer independent-design-reviewer
```

```powershell
.\layered-development.ps1
```

仅在用户明确要求分层开发时，生成产品表现层、后端协议层、数据支撑层的四问契约。

```powershell
.\validate-adworkflow.ps1
```

校验当前 artifacts 和 execution plan。

```powershell
.\orchestrator.ps1 -RunId mvp-1 -Command start
.\orchestrator.ps1 -RunId mvp-1 -Command ready
.\orchestrator.ps1 -RunId mvp-1 -Command resume
```

创建 run-scoped 主窗口状态、查询 ready tasks，并在上下文压缩后恢复。

```powershell
.\analyze-product-docs.ps1
```

根据 PRD/ARCH/TODO/PROJECT 生成 architecture manifest 和 profile。

```powershell
.\prepare-context.ps1
```

根据当前 `.adworkflow/task_spec.json` 生成上下文。L0/L1 写 `context_raw.json` 和 `context_manifest.json`；L2 还会写 `semantic_slice.json` 与 `context_preflight.json`。

```powershell
.\build-codegraph.ps1 -Level l2
```

手动重建 `.codegraph/index.json` 或 `.codegraph/l2.sqlite`。

```powershell
.\setup-l2-provider.ps1
```

安装 TypeScript/JavaScript L2 provider runtime。Python L2 无额外依赖。

```powershell
.\apply-context-expansion.ps1
```

应用 pending `context_expansion_request.json`，同步更新 semantic slice、preflight、context manifest 和 worker expansion history。

```powershell
.\codegraph-post-edit.ps1 -TaskId <task_id>
```

按 preflight revision 读取基线，从 `worker_state.changed_files` 和 manifest 读取声明/预测范围，自动重建当前图并生成 `impact_report.json`。

```powershell
.\init-adworkflow.ps1 -Force
```

更新机器生成的本地工作流文件，但保留 permissions、verification commands、module skills 和 review checklist。只有显式传入 `-ForceUserConfig` 才覆盖这些用户维护文件。

## 需要你手动维护的文件

- `.adworkflow/permissions.md`：Agent 权限边界。
- `.adworkflow/verification_commands.md`：当前项目的验证命令。
- `.adworkflow/module_skills.md`：模块级 skill 路由规则。
- `.adworkflow/review_checklist.md`：review 检查标准。
- `.adworkflow/execution_plan.json`：TODOwork 生成或更新的 MVP 子 agent 编排计划。

这些文件是“自动化能不能听话”的关键，不是装饰文档。

## 子 agent 不确定性处理

子 agent 遇到 ARCH/TODO 细节不足时，不自行扩展解释，先上报主窗口。主窗口复核 PRD/ARCH/TODO；仍不确定就问你。超时未反馈时，主窗口按最接近 PRD/ARCH 的解释给出 fallback，子 agent 继续执行并在 `worker_state.clarification_events`、`worker_state.timeout_fallbacks` 留痕。
