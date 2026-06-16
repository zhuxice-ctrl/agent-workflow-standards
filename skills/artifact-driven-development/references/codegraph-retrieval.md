# Codegraph 检索协议

Codegraph 检索用于减少不必要的上下文。

Agent 在读取大面积代码前，应使用图来定位真正相关的内容。

## 1. 工具契约

推荐工具接口：

```text
find_definition(symbol)
find_references(symbol)
callers(function)
callees(function)
impacted_files(file)
tests_for(symbol_or_file)
get_slice(entrypoint, depth=2)
summarize_file(file, budget=800)
```

## 2. 检索顺序

除非任务给出更合适的路径，否则按以下顺序执行：

1. 识别入口符号、文件或面向用户的行为。
2. 查找定义。
3. 查找引用和调用方。
4. 查找受影响的测试。
5. 读取定向代码切片。
6. 仅在需要时扩展到被调用方或受影响文件。

## 3. Context Raw 与 Context Manifest

Locator 应在实现前先保留原始检索证据：

```json
{
  "schema": "ADworkflo.context_raw.v1",
  "task_id": "task-id",
  "source": "codegraph-index",
  "matched_files": [],
  "matched_symbols": [],
  "likely_tests": [],
  "warnings": []
}
```

再压缩成 worker-facing manifest：

```json
{
  "task_id": "task-id",
  "context_level": "L1-index",
  "read_first": [],
  "relevant_symbols": [],
  "entrypoints": [],
  "likely_tests": [],
  "do_not_touch": [],
  "open_questions": []
}
```

## 4. 预算规则

推荐限制：

```text
initial_manifest: 1000-2000 tokens
single_tool_response: 300-800 tokens
max_queries_per_round: 3-5
slice_depth_default: 1-2
```

如果结果超出预算：

- 降低深度
- 摘要化
- 对符号排序
- 按模块拆分
- 请求更窄的切片

## 5. 何时读取完整文件

在以下情况下允许读取完整文件：

- 文件较小
- 文件是配置文件
- 文件是直接实现目标
- 读取切片的成本高于读取整个文件

在以下情况下应避免读取完整文件：

- 文件较大
- 文件包含多个无关职责
- 只有一个符号相关
- 任务只需要调用方/被调用方上下文

## 6. 影响升级

当 patch 触及以下内容时，请求影响分析：

- public API
- auth 或 permissions
- payment 或 billing
- data migrations
- cache behavior
- concurrency
- global types
- state machines
- serialization/deserialization

## 7. 输出风格

Codegraph 响应应紧凑且结构化。

推荐：

```json
{
  "symbol": "SessionStore.save",
  "definition": "src/auth/session.ts:44",
  "callers": ["src/auth/refresh.ts:88"],
  "tests": ["test/auth/session.test.ts"],
  "notes": ["expiresAt 需要 epoch 毫秒"]
}
```

除非明确要求，否则避免冗长的叙事性解释。
