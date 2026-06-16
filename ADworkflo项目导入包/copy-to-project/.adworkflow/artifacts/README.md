# ADworkflo Task Artifacts

这里归档已经完成的重要任务。

推荐结构：

```text
.adworkflow/artifacts/
  <task_id>/
    task_spec.json
    execution_plan.json
    context_raw.json
    context_manifest.json
    worker_state.json
    verification_result.json
    review_findings.json
    final_summary.md
```

`.adworkflow/` 根目录下的 JSON 是当前任务的工作副本；任务完成后再归档到这里。
