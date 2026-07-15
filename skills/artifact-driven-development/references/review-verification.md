# Review 和验证协议

Review 必须基于证据且边界清晰。

验证与 review 必须绑定同一 `source_revision` 或 patch hash。Reviewer 必须记录身份；需要独立审计时，reviewer 不得与 implementation owner 相同。

Reviewer 不重新实现方案。Reviewer 检查 patch 是否满足任务契约，且没有引入不可接受的风险。

## 1. Review 级别

### Level 1: 确定性验证

始终优先使用确定性检查：

- 单元测试
- 集成测试
- e2e 测试
- lint
- typecheck
- build

### Level 2: 仅基于 Diff 的 LLM Review

默认 LLM review 模式。

输入：

```text
task_spec
patch.diff
verification_result
```

### Level 3: 感知上下文的 LLM Review

仅在风险升高时使用。

额外输入：

```text
已触及的文件切片
受影响的调用方/被调用方
测试覆盖切片
架构约束
context_preflight.json
修改后 impact_report.json
```

## 2. 风险升级触发条件

当 patch 触及以下内容时，升级到感知上下文的 review：

- authentication
- authorization
- billing
- payments
- migrations
- encryption
- concurrency
- cache invalidation
- global type system
- public API
- state machine
- deletion 或 irreversible actions

## 3. Review 输出

Reviewer 输出必须结构化：

```json
{
  "status": "approved",
  "blocking_findings": [],
  "non_blocking_findings": [],
  "suggested_tests": [],
  "risk_notes": []
}
```

Finding 形状：

```json
{
  "id": "R1",
  "severity": "blocking",
  "file": "src/auth/session.ts",
  "lines": "44-58",
  "issue": "refresh token 轮换后未持久化过期时间",
  "expected_fix": "refresh token 轮换后更新已持久化的 expiresAt",
  "evidence": "refresh token 轮换时 auth/session.test.ts 失败"
}
```

## 4. Fix Loop 规则

只有未解决的 findings 进入下一轮 worker。

不要包含：

- 已解决的 findings
- reviewer chain-of-thought
- 完整的先前对话
- 无关建议

Worker fix 输入：

```text
unresolved review_findings
latest patch.diff
latest verification_result
minimal local context
```

## 5. 完成标准

只有满足以下条件时，任务才能标记为完成：

1. 验收标准已满足。
2. 必需验证已通过，或已记录无法验证的原因。
3. 阻塞性 review findings 已解决。
4. 剩余风险已记录。
5. 已总结变更文件和行为变化。
6. 验证覆盖已逐条映射到 task acceptance criteria。
7. 分层开发还必须通过对应 layer audit 和跨层质量门禁。
8. L2 任务的 context preflight 已接受，post-edit impact 已通过，且 Reviewer 审查的是实际波及范围而非仅原始切片。

## 6. 最终证据包

最终输出应包括：

```json
{
  "status": "complete",
  "changed_files": [],
  "summary": [],
  "verification": [],
  "review": {
    "status": "approved",
    "remaining_findings": []
  },
  "risks": [],
  "follow_ups": []
}
```
