# Context Manifest

`context_manifest` 记录 worker 真正应该先读什么，避免读取整个仓库或传递冗长摘要。

`context_raw` 记录 graphcode/codegraph 的原始检索证据。两者不要混在一起：

- `context_raw.json`：检索来源、命中文件、命中符号、可能测试、告警。
- `context_manifest.json`：worker 的最小阅读顺序和任务边界。

## 检索顺序

1. 从 `task_spec` 提取目标、验收标准、non-goals。
2. 如果已有代码，使用 codegraph 或定向搜索生成 `context_raw`。
3. 如果还没有代码，使用 `architecture_manifest`、PRD、ARCH、TODO、PROJECT 生成 architecture-first context。
4. 把 `context_raw` 压缩成 worker 可执行的 `context_manifest`。
5. 只有在风险或不确定性要求时，才扩展影响分析。

## context_manifest 字段

- `task_id`：与 task spec 一致。
- `context_level`：L0/L1/L2 或 architecture-first。
- `read_first`：worker 应优先阅读的文件。
- `relevant_symbols`：相关符号。
- `entrypoints`：入口点、命令、页面、API 或业务流程。
- `likely_tests`：可能需要运行或补充的测试。
- `do_not_touch`：不应修改的范围，通常来自 non-goals。
- `open_questions`：本地上下文无法确认的问题。

## 使用规则

Manifest 是定位结果，不是仓库摘要。优先记录文件、符号、测试和边界；避免长自然语言解释。使用 `templates/context_manifest.json` 作为起点。
