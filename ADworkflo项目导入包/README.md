# ADworkflo 项目导入包

这个文件夹不是全局 skill。它是给具体工程项目复制使用的本地导入包。

## 三层位置

### 1. 全局 skill

位置：

```text
<CODEX_HOME>\skills\adworkflo
```

作用：

- 保存 ADworkflo 的通用方法。
- 保存初始化、产品文档分析、codegraph、context prepare 脚本。
- 保存全局模板，例如 `templates\AGENT_HEADER.md.tpl`。

### 2. GitHub 标准仓库

位置：

```text
F:\agent-workflow-standards
```

作用：

- 保存你要上传 GitHub 的 ADworkflo 标准说明。
- 保存可复制到项目根目录的 `ADworkflo项目导入包\copy-to-project`。
- 保存模块 skill 配置方案、artifact 模板、schema 和示例项目。

### 3. 具体工程项目

目标结构：

```text
<工程根目录>
  PRD.md
  ARCH.md
  TODO.md
  PROJECT.md
  .codex/
    AGENT_HEADER.md
  .adworkflow/
    ADWORKFLOW_PROFILE.json
    architecture_manifest.json
    execution_plan.json
    task_specs/
    task_spec.json
    context_raw.json
    context_manifest.json
    worker_state.json
    verification_result.json
    review_findings.json
    permissions.md
    verification_commands.md
    module_skills.md
    review_checklist.md
    final_summary.template.md
    artifacts/
  .codegraph/
    config.json
```

## 推荐用法

新项目最稳的方式是在工程根目录先写好：

```text
PRD.md
ARCH.md
TODO.md
PROJECT.md
```

然后运行：

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <工程根目录>
```

这样会自动生成 `.codex`、`.adworkflow`、`.codegraph`，并根据产品文档判断项目规模。

## 可复制用法

如果你想手动复制，把 `copy-to-project` 里的全部内容复制到工程根目录。

复制后，先按项目实际情况补：

```text
.adworkflow/permissions.md
.adworkflow/verification_commands.md
.adworkflow/module_skills.md
```

然后运行：

```powershell
.\analyze-product-docs.ps1
```

有代码后，主窗口可以直接运行：

```powershell
.\prepare-context.ps1
```

它会根据 `.adworkflow/task_spec.json` 生成 `context_raw.json` 和 `context_manifest.json`。如果需要，也会先构建 `.codegraph/index.json`。

## 真实开发入口

第一层文档写完后，建议按这个顺序在主窗口执行：

```text
使用 ARCHwork skill 根据 ARCH 准备第二层执行。
使用 TODOwork skill 根据 TODO 编排子 agent 模块开发。
```

ARCHwork 读取 `ARCH.md` 中声明的 MVP 流程和 Module Skill Plan。TODOwork 读取 `TODO.md` 的模块审计清单，并生成 `.adworkflow/execution_plan.json`。

## 判断逻辑

开发前不要用代码行数判断项目大小。项目刚开始时代码可能是 0 行。

ADworkflo 的判断顺序是：

```text
1. 先看 PRD / ARCH / TODO / PROJECT 里的预期复杂度。
2. 如果手动指定 --mode small|medium|large，以手动指定为准。
3. 只有没有产品文档时，才用源码文件数和行数兜底。
```
