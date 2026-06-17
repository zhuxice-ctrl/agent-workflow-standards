# ADworkflo Agent Workflow Standards

ADworkflo 是一套面向 AI-assisted development 的 artifact-driven workflow。它的目标不是替你写产品想法，而是把工程执行层从“聊天上下文乱跑”变成“按任务契约、上下文清单、验证证据推进”。

## 核心分层

### 1. 产品设计层

由人手动维护，通常放在项目根目录：

```text
PRD.md
ARCH.md
TODO.md
PROJECT.md
```

这一层负责讲清楚用户需求、功能边界、页面/业务流程、架构意图、验收标准。

### 2. 工程执行层

由 ADworkflo 自动化管理，通常放在项目内：

```text
.codex/AGENT_HEADER.md
.adworkflow/task_spec.json
.adworkflow/execution_plan.json
.adworkflow/context_raw.json
.adworkflow/context_manifest.json
.adworkflow/worker_state.json
.adworkflow/verification_result.json
.adworkflow/review_findings.json
.codegraph/index.json
```

这一层负责把自然语言任务转成可执行契约，让 Agent 先取上下文、再实现、再验证、再 review。

### 3. 全局工具层

仓库版全局 skill 放在：

```text
skills/adworkflo/
```

它保存通用方法、初始化脚本、产品文档分析脚本、codegraph 脚本、context prepare 脚本和模板。安装到本机后，通常位于：

```text
<CODEX_HOME>/skills/adworkflo/
```

当前本机示例路径是：

```text
F:\CodexHome\skills\adworkflo
```

## 推荐安装方式

在新设备上，先进入本仓库根目录，然后运行：

```powershell
.\install-adworkflow.ps1 -CodexHome F:\CodexHome -SetUserEnv
```

这会把下面这些 skills 安装到 `<CODEX_HOME>\skills\`：

```text
adworkflo
arch-work
todo-work
artifact-driven-development
```

如果目标目录已有旧版本，需要覆盖：

```powershell
.\install-adworkflow.ps1 -CodexHome F:\CodexHome -Force -SetUserEnv
```

安装后，在目标项目根目录写好产品设计文档，再运行：

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\init_adworkflow.py --project <工程根目录>
```

这会生成：

```text
.codex/
.adworkflow/
.codegraph/
```

## 新项目自然语言操作步骤

真实使用时，不需要开发者手动敲 `init_adworkflow.py`。这条命令是 ADworkflo 的底层动作，应该由 Codex 主窗口根据自然语言请求自动执行。

新项目推荐顺序：

```text
1. 新建项目目录。
2. 手动写好 PRD.md、ARCH.md、TODO.md、PROJECT.md。
3. 在 Codex 主窗口说：使用 ADworkflo 初始化当前项目第二层。
4. Codex 自动运行 init_adworkflow.py，只生成 .codex、.adworkflow、.codegraph，不改业务代码。
5. Codex 读取 PRD/ARCH/TODO/PROJECT，生成 architecture_manifest 和 ADWORKFLOW_PROFILE。
6. 你确认或补充 permissions、verification_commands、module_skills、review_checklist。
7. 在主窗口说：使用 ARCHwork 根据 ARCH 准备第二层执行。
8. 在主窗口说：使用 TODOwork 根据 TODO 编排子 agent 模块开发。
9. 在主窗口说：使用 ADworkflo 执行 MVP 第一批任务。
```

可直接复制的入口话术：

```text
使用 ADworkflo 初始化当前项目第二层。只补齐工作流文件，不改业务代码。初始化后读取 PRD、ARCH、TODO、PROJECT，生成 architecture_manifest 和 ADWORKFLOW_PROFILE。
```

初始化的意义不是让 Agent 开始写业务代码，而是把全局方法论落到当前项目的本地执行文件里：

```text
.codex/AGENT_HEADER.md
.adworkflow/permissions.md
.adworkflow/verification_commands.md
.adworkflow/module_skills.md
.adworkflow/task_spec.json
.adworkflow/context_manifest.json
.adworkflow/worker_state.json
.adworkflow/verification_result.json
.codegraph/config.json
```

没有这一步也能让 Codex 写代码，但那会退回普通聊天式开发：任务边界、上下文、验证记录和 worker 状态主要依赖临场对话。ADworkflo 要解决的正是这个问题，所以真实开发可以自然语言触发，但底层仍然需要初始化这些项目本地 artifacts。

## 手动导入方式

也可以直接复制：

```text
ADworkflo项目导入包/copy-to-project
```

到目标工程根目录。

复制后先补项目本地配置：

```text
.adworkflow/permissions.md
.adworkflow/verification_commands.md
.adworkflow/module_skills.md
```

然后运行：

```powershell
.\analyze-product-docs.ps1
```

导入包中的 PowerShell 脚本会按这个顺序寻找全局 `adworkflo`：

```text
1. ADWORKFLO_SKILL_ROOT
2. CODEX_HOME\skills\adworkflo
3. F:\CodexHome\skills\ADworkflo
```

所以换新设备时，推荐通过 `install-adworkflow.ps1 -SetUserEnv` 设置环境变量。

## 主窗口使用方式

真实开发时，第一层文档写完后，先用文档执行 skill：

```text
使用 ARCHwork skill 根据 ARCH 准备第二层执行。
使用 TODOwork skill 根据 TODO 编排子 agent 模块开发。
```

然后再在主窗口描述具体开发任务：

```text
使用 ADworkflo 执行这个任务：实现用户登录页验证码校验，并补充测试。
```

主窗口应执行：

```text
PRD/ARCH/TODO/PROJECT
-> ARCHwork 读取 ARCH 中声明的 Module Skill Plan
-> 更新 .adworkflow/module_skills.md
-> TODOwork 读取 TODO 模块审计清单
-> 生成 .adworkflow/execution_plan.json
-> 按 execution_plan 生成 .adworkflow/task_specs/<task_id>.json
-> 运行 prepare_context.py 或 .\prepare-context.ps1
-> 得到 .adworkflow/context_raw.json
-> 得到 .adworkflow/context_manifest.json
-> 按 module_skills.md 判断是否加载模块 skill
-> 子 agent 并发实现，数量由 TODO 模块和 ARCH 依赖决定
-> 子 agent 输出 diff/change summary + worker_state.json
-> 按 verification_commands.md 验证
-> 更新 verification_result.json
-> 中/高风险任务更新 review_findings.json
-> 需要保留时归档到 .adworkflow/artifacts/<task_id>/
```

全局命令：

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\prepare_context.py --project <工程根目录>
```

项目导入包命令：

```powershell
.\prepare-context.ps1
```

## 需要手动配置什么

产品设计层你手动写，ADworkflo 不替你决定产品方向。

工程执行层里，通常需要你手动维护这几类项目事实：

- `.adworkflow/permissions.md`：Agent 能做什么、什么必须先问你。
- `.adworkflow/verification_commands.md`：这个项目真正可用的测试、lint、typecheck、构建命令。
- `.adworkflow/module_skills.md`：哪些模块需要加载专门 skill。
- `.adworkflow/execution_plan.json`：TODOwork 生成的 MVP 子 agent 编排计划。
- `.adworkflow/review_checklist.md`：当前项目的 review 风险重点。

其余 JSON artifacts 由主窗口和脚本按任务生成或更新。

## 模块 skills 配置方案

不是每个模块都要做 skill。真实开发中，是否生成 module skill 由 `ARCH.md` 的 `Module Skill Plan` 显式声明，TODO 只负责把这些任务审计化呈现。第二层不靠打分自行新增 module skill。

推荐格式：

```text
module: agent-runtime
skill: skills/agent-runtime/SKILL.md
when: tool calling、memory、planner、worker handoff、权限边界变更
inputs: task_spec, context_manifest, ARCH.md
outputs: patch, worker_state, verification_result, review_findings if needed
verification: unit tests, integration smoke test, permission regression check
```

主窗口的判断逻辑是：先看 `task_spec` 属于哪个模块，再查 `.adworkflow/module_skills.md`，命中后加载对应 skill。

## ARCHwork / TODOwork

- `skills/arch-work/`：读取 `ARCH.md`，把 ARCH 中声明的 MVP 流程、模块边界、module skill plan 转成第二层执行输入。
- `skills/todo-work/`：读取 `TODO.md`，把模块审计清单转成 `.adworkflow/execution_plan.json` 和 per-module task specs。

一句话：

```text
ARCH decides MVP flow and declared module skills.
TODO audits modules.
TODOwork creates execution_plan.
execution_plan schedules subagents.
task_spec bounds each worker.
```

## adworkflo 与 artifact-driven-development 的区别

这两个不是重复关系。

`skills/adworkflo/` 是**全局执行引擎**：

```text
有脚本
有模板
能初始化项目
能分析 PRD/ARCH/TODO
能构建 lightweight codegraph
能根据 task_spec 生成 context_raw/context_manifest
```

它包含真正会被运行的 graphcode/codegraph 程序：

```text
scripts/init_adworkflow.py
scripts/analyze_project_plan.py
scripts/build_codegraph.py
scripts/query_codegraph.py
scripts/prepare_context.py
```

`skills/artifact-driven-development/` 是**执行协议说明 skill**：

```text
不负责安装项目
不包含 graphcode 主程序
主要规定 artifact-driven development 的执行纪律
说明 task_spec/context_manifest/worker_state/review/verification 怎么交接
```

简单说：

```text
adworkflo = engine + scripts + templates
artifact-driven-development = protocol + rules + handoff method
```

真实开发时，主窗口通常依赖 `adworkflo` 执行脚本；复杂任务需要解释执行纪律时，再加载 `artifact-driven-development`。

## 新设备与项目复制范围

新设备上必须保留并安装：

```text
skills/adworkflo/
skills/arch-work/
skills/todo-work/
skills/artifact-driven-development/
ADworkflo项目导入包/
README.md
install-adworkflow.ps1
```

建议在标准仓库中保留，但不需要复制进每个业务项目：

```text
schemas/
templates/
CODEGRAPH_RETRIEVAL_PROTOCOL.md
MODULE_SKILLS_GUIDE.md
MULTI_AGENT_ORCHESTRATION.md
REVIEW_AND_VERIFICATION_PROTOCOL.md
```

可选：

```text
examples/
```

`examples/` 只是演示项目。自己本地使用时可以删除；如果要上传 GitHub 给别人理解流程，建议保留一个最小示例。

每个具体业务项目只需要：

```text
PRD.md
ARCH.md
TODO.md
PROJECT.md
.codex/
.adworkflow/
.codegraph/
```

这些项目本地文件可以通过运行 `init_adworkflow.py` 生成，也可以直接复制 `ADworkflo项目导入包/copy-to-project`。

## 仓库目录

- `AGENTS.md`：项目常驻最小纪律。
- `AGENT_HEADER.md`：可复制到项目中的简短头文件。
- `ADworkflo项目导入包/`：可复制进具体工程的本地导入包。
- `skills/adworkflo/`：全局执行引擎，包含 graphcode/codegraph 脚本和初始化模板。
- `skills/artifact-driven-development/`：仓库版 artifact workflow skill。
- `skills/arch-work/`：ARCHwork 文档执行 skill。
- `skills/todo-work/`：TODOwork 子 agent 编排 skill。
- `templates/`：artifact 模板。
- `schemas/`：artifact JSON schemas。
- `examples/small-project-test/`：小项目样例。
- `MODULE_SKILLS_GUIDE.md`：模块级 skill 的封装标准。
- `CODEGRAPH_RETRIEVAL_PROTOCOL.md`：codegraph 查询规则。
- `MULTI_AGENT_ORCHESTRATION.md`：多 Agent 编排规则。
- `REVIEW_AND_VERIFICATION_PROTOCOL.md`：review 和验证规则。
- `install-adworkflow.ps1`：新设备安装脚本，把仓库 skills 安装到 Codex skills 目录。

## 工作流原则

- 不用长聊天记录做交接，只交接 artifacts。
- 先生成 `task_spec`，再找上下文。
- 先生成 `context_manifest`，再开始大范围读代码。
- 默认 Solo Worker；只有低耦合、可独立验证的任务才 fan-out。
- TODOwork 场景下 worker 数量不设固定上限，由 TODO 模块拆分和 ARCH 依赖决定。
- 子 agent 遇到 ARCH/TODO 细节不足时，上报主窗口并在 `worker_state` 留痕。
- 完成必须有 `verification_result`，中/高风险必须 review。
