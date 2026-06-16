# ADworkflo Architecture Analysis

Before code exists, project size must be inferred from product and architecture documents, not from current lines of code. Source file count and LOC are fallback signals for existing projects only.

Read first-layer docs such as:

- `PRD.md`
- `ARCH.md`
- `TODO.md`
- `PROJECT.md`
- `README.md`
- user-provided product, architecture, roadmap, or task documents

## Classification Signals

Small project:

- Single function or narrow workflow.
- No complex state.
- No serious permission or safety boundary.
- One app surface.
- Few modules.

Medium project:

- Complete MVP.
- Frontend + backend + database.
- Several business modules.
- API integration.
- Some testing and deployment needs.
- Optional login/permission layer.

Large project:

- Agent/RAG/tool calling/long-term memory.
- Complex state machine or multi-step orchestration.
- Multi-platform or multi-service architecture.
- High-risk actions such as payment, trading, deletion, external sending, credential access, or irreversible database writes.
- Required audit, monitoring, rollback, review, or strict verification.
- Multiple workers or reviewers are likely useful.

## Recommended Flow

```text
PRD / ARCH / TODO / PROJECT
-> init_adworkflow.py or analyze_project_plan.py
-> .adworkflow/architecture_manifest.json
-> task_spec
-> context_manifest from architecture first
-> worker implementation
-> build_codegraph as code appears
-> verification_result
-> review_findings when risk requires
```
