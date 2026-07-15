# Codegraph 检索协议

使用最轻的充分策略：小项目 L0、中项目 L1、大项目或深调用链任务使用经过 capability probe 的 L2。未支持语言保持 L1，不能用正则结果冒充语义图。

## L2 顺序

1. 在 `task_spec.entrypoints` 使用 stable ID 或唯一 qualified symbol。
2. 生成 `.codegraph/l2.sqlite` 和 revision snapshot。
3. 查询 definitions、references、callers、callees、imports、tests 与 impact。
4. 生成 `semantic_slice.json` 和 `context_preflight.json`。
5. 仅在 preflight 为 `accepted` 时 dispatch worker。
6. `needs_expansion` 时填写 `context_expansion_request.json` 并运行 `apply_context_expansion.py`。
7. 修改后运行 `codegraph_post_edit.py`，Reviewer 检查 `impact_report.json` 的实际波及范围。

## 必须暴露的信息

- graph revision 与 provider provenance
- included、boundary、excluded symbols/files
- unresolved edges 与 criticality
- coverage、confidence、truncated
- source hashes 与 freshness
- prediction reasons 和 post-edit edge delta

切片是 locator，不是源码真相或读取白名单。入口歧义、源漂移、provider 能力不足为 `invalid`；关键未解析边、低置信度、预算截断为 `needs_expansion`。不得通过聊天文字把这两种状态改写成已接受。

## 预算

默认 depth 2、item budget 100、confidence threshold 0.80。超预算时缩小入口或按关系扩展，不删除 boundary/unresolved evidence。
