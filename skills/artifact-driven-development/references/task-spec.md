# Task Spec

`task_spec` 是任务契约，必须在复杂任务编辑前创建或确认。

## 必填内容

- `task_id`：短标识，便于关联后续 artifacts。
- `goal`：具体可交付结果。
- `non_goals`：明确不做什么，防止范围漂移。
- `acceptance_criteria`：可观察、可验证的成功标准。
- `risk_level`：`low`、`medium` 或 `high`。
- `execution_mode`：默认 `solo_worker`，必要时升级。
- `allowed_actions`：本轮允许的动作，例如 `read`、`edit`、`test`、`shell`、`network`。
- `required_outputs`：本任务需要产出的 artifact 文件，例如 `context_raw.json`、`context_manifest.json`、`worker_state.json`、`verification_result.json`。

## 编写规则

保持任务规格短而具体。不要把长背景、完整聊天记录或推理过程放进 `task_spec`。如果需求不完整，先补齐目标、非目标、验收标准和验证计划，再编辑文件。

使用 `templates/task_spec.json` 作为起点。JSON 键名和枚举值必须保持不变。
