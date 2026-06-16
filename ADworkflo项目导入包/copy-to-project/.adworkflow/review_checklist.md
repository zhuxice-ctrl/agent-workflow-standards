# ADworkflo Review Checklist

中/高风险任务，或者涉及共享接口、权限、数据、部署时，主窗口需要触发 review。

## Reviewer 输入

- `.adworkflow/task_spec.json`
- `.adworkflow/context_manifest.json`
- patch 或 changed files summary
- `.adworkflow/verification_result.json`

## 检查项

- 验收标准是否全部覆盖。
- non-goals 是否被遵守。
- 验证命令是否匹配风险级别。
- 公开 API、鉴权、权限、数据、缓存、状态、部署风险是否处理。
- 是否引入了无关重构、格式化噪音或隐藏行为变化。
