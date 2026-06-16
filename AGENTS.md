# 项目 Agent 头文件

本文件只放所有任务都要遵守的最小纪律。复杂开发、多 Agent、review、验证、项目导入或流程改造任务，加载 `skills/artifact-driven-development/SKILL.md`。

## 最小纪律

1. 开始复杂任务前，先生成或确认 `task_spec`。
2. 不直接全仓库乱读，先用 codegraph、architecture docs 或定向搜索生成 `context_raw` 和 `context_manifest`。
3. 默认 `Solo Worker`；只有低耦合且可独立验证的任务才 `Fan-out`。
4. 所有修改必须留下或更新 `worker_state`。
5. 完成前必须有 `verification_result`。
6. Reviewer 默认只看 `patch.diff`、`task_spec` 和 `verification_result`。
7. 不把长聊天记录当交接材料，只交接结构化 artifact。

## 主窗口顺序

1. 把用户任务写入 `.adworkflow/task_spec.json`。
2. 用户要求 ARCHwork 时，读取 ARCH 并更新 module skill 路由。
3. 用户要求 TODOwork 时，读取 TODO 并生成 `.adworkflow/execution_plan.json`。
4. 按 execution_plan 生成 `.adworkflow/task_specs/<task_id>.json`。
5. 运行全局 `prepare_context.py` 或项目内 `prepare-context.ps1`。
6. 读取 `.adworkflow/context_manifest.json`。
7. 按 `.adworkflow/module_skills.md` 判断是否加载模块 skill。
8. 子 agent 实现、输出 diff/change summary + worker_state，并更新 artifacts。
