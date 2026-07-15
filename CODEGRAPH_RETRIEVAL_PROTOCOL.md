# Codegraph 检索协议

ADworkflo 内置两套真实能力：便携式 `lightweight-l1`，以及面向 Python、TypeScript、JavaScript 的 revisioned L2 semantic graph。其他语言只有在 provider capability probe 通过后才能声明 L2。

## 检索顺序

1. 从 `task_spec.entrypoints` 解析唯一 stable ID 或 qualified symbol。
2. 查询 definition、references、callers、callees、imports 和 tests。
3. 生成带预算的 `semantic_slice.json` 与预测影响范围。
4. 运行 `context_preflight`。
5. `accepted` 才进入开发；`needs_expansion` 写定向扩展请求；`invalid` 重建图或修正入口。
6. 修改后重建图，生成 `impact_report.json`，Reviewer 审查实际波及范围。

## 查询命令

```powershell
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT> capabilities
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT> find-references --symbol <SYMBOL>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT> callers --symbol <SYMBOL>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT> callees --symbol <SYMBOL>
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT> impact --target <SYMBOL_OR_FILE> --depth 3 --budget 200
py -3 $env:ADWORKFLO_SKILL_ROOT\scripts\query_codegraph.py --project <PROJECT> slice --entrypoint <SYMBOL> --depth 2 --budget 100
```

短名有歧义时只返回 candidates，不猜定义。查询结果必须携带 graph revision、provider provenance、未解析边和截断边界。

## 防漂移门禁

`semantic_slice` 不是允许读取的白名单。Agent 发现以下任一情况必须扩展或回到源码定向检索：

- 关键动态调用或反射边未解析
- depth/item budget 截断
- 入口缺失或歧义
- 文件哈希或 graph revision 变化
- 当前语言没有通过 L2 capability probe
- 实际修改文件超出预测范围

`apply_context_expansion.py` 会同时更新 slice、preflight、manifest 和 worker history。`codegraph_post_edit.py` 会自动重建图，对比 symbols/calls/references/imports，并在 unexpected impact 或新增 critical unresolved edge 时失败。

## 预算与源码读取

默认 slice depth 为 2、item budget 为 100、confidence threshold 为 0.80。预算是防止上下文爆炸的边界，不是证明范围完整的依据。

切片只提供定位范围。直接目标文件较小、配置文件、序列化协议、全局类型或切片存在不确定边时，应读取完整源码并把扩展原因记录到 artifacts。
