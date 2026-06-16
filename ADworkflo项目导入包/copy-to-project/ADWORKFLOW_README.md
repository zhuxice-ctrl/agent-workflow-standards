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
-> 按 module_skills.md 判断是否加载模块 skill
-> 子 agent 按 execution_plan 并发实现
-> 写 worker_state.json
-> 按 verification_commands.md 验证
-> 写 verification_result.json
-> 中/高风险任务写 review_findings.json
-> 必要时归档到 .adworkflow/artifacts/<task_id>/
```

## 本地脚本

```powershell
.\analyze-product-docs.ps1
```

根据 PRD/ARCH/TODO/PROJECT 生成 architecture manifest 和 profile。

```powershell
.\prepare-context.ps1
```

根据当前 `.adworkflow/task_spec.json` 生成 `context_raw.json` 和 `context_manifest.json`。如果项目已经有代码但还没有 `.codegraph/index.json`，会自动先构建轻量 codegraph。

```powershell
.\build-codegraph.ps1
```

手动重建 `.codegraph/index.json`。

```powershell
.\init-adworkflow.ps1 -Force
```

用全局模板重新生成本地工作流文件。谨慎使用，可能覆盖本地配置。

## 需要你手动维护的文件

- `.adworkflow/permissions.md`：Agent 权限边界。
- `.adworkflow/verification_commands.md`：当前项目的验证命令。
- `.adworkflow/module_skills.md`：模块级 skill 路由规则。
- `.adworkflow/review_checklist.md`：review 检查标准。
- `.adworkflow/execution_plan.json`：TODOwork 生成或更新的 MVP 子 agent 编排计划。

这些文件是“自动化能不能听话”的关键，不是装饰文档。

## 子 agent 不确定性处理

子 agent 遇到 ARCH/TODO 细节不足时，不自行扩展解释，先上报主窗口。主窗口复核 PRD/ARCH/TODO；仍不确定就问你。超时未反馈时，主窗口按最接近 PRD/ARCH 的解释给出 fallback，子 agent 继续执行并在 `worker_state.clarification_events`、`worker_state.timeout_fallbacks` 留痕。
