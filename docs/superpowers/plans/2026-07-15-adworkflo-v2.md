# ADworkflo v2 Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build verifiable ADworkflo contracts, design alignment, truthful context retrieval, layered development contracts, and resumable run-scoped orchestration.

**Architecture:** Keep `skills/adworkflo` as the executable engine and canonical template source. Add small focused Python CLIs for contract sync/validation, design alignment, and orchestration; strengthen existing analyzer/index/context scripts; generate all duplicated project templates from the canonical source.

**Tech Stack:** Python 3.11 standard library, jsonschema 4.x for contract validation, PowerShell installer, JSON Schema 2020-12, unittest.

---

### Task 1: Contract Test Harness And Canonical Templates

**Files:**
- Create: `requirements-dev.txt`
- Create: `tests/test_contracts.py`
- Create: `skills/adworkflo/scripts/sync_templates.py`
- Create: `skills/adworkflo/scripts/validate_adworkflow.py`
- Modify: `schemas/*.schema.json`
- Modify: `skills/adworkflo/templates/*.json`

- [x] Write tests that load every canonical template, validate it with `Draft202012Validator`, and compare all mirrored JSON templates byte-for-byte.
- [x] Run `py -3 -m unittest tests.test_contracts -v`; expect failures for verification schema drift and missing schemas.
- [x] Add versioned schemas for task spec, worker state, architecture manifest, profile, codegraph, design alignment, layer plan, orchestrator state, resume manifest, artifact registry and interface contracts.
- [x] Make canonical templates schema-valid with explicit `configured` or draft states.
- [x] Implement `sync_templates.py --check|--write` using a fixed mapping from canonical files to mirrors.
- [x] Implement `validate_adworkflow.py` to validate known artifact filenames and execution-plan dependency graphs.
- [x] Run `py -3 -m unittest tests.test_contracts -v`; expect all tests to pass.

### Task 2: Product Document Analysis And Alignment Gate

**Files:**
- Create: `tests/test_product_docs.py`
- Create: `skills/adworkflo/scripts/design_alignment.py`
- Create: `skills/adworkflo/templates/design_alignment_report.json`
- Modify: `skills/adworkflo/scripts/analyze_project_plan.py`
- Modify: `skills/arch-work/SKILL.md`

- [x] Add a regression fixture containing `storage`, `mapping`, and `decision`; assert these do not trigger rag, app, or ci signals.
- [x] Add tests that extract explicit modules from ARCH Module Planning and PRD requirement IDs such as `FR-001` and `NFR-001`.
- [x] Replace ASCII substring matching with token-boundary matching and count structured declarations instead of raw word frequency.
- [x] Keep `planned_modules` limited to explicitly parsed ARCH modules; place heuristic results in `suggested_modules`.
- [x] Implement `design_alignment.py` with `analyze` and `approve-semantic-review` commands. Structural missing requirements set `gate_status=blocked`; semantic approval records reviewer and timestamp.
- [x] Update ARCHwork so TODOwork cannot proceed while the alignment gate is blocked.
- [x] Run `py -3 -m unittest tests.test_product_docs -v`; expect all tests to pass.

### Task 3: Truthful Codegraph And Fresh Context

**Files:**
- Create: `tests/test_codegraph_context.py`
- Modify: `skills/adworkflo/scripts/build_codegraph.py`
- Modify: `skills/adworkflo/scripts/query_codegraph.py`
- Modify: `skills/adworkflo/scripts/prepare_context.py`
- Modify: `skills/adworkflo/scripts/init_adworkflow.py`

- [x] Test that every configured query has a CLI command and that unsupported L2 queries are not advertised.
- [x] Test that changing, adding, or deleting a source file marks the index stale and causes default prepare to rebuild it.
- [x] Add `sha256` and `mtime_ns` to file records and implement deterministic `index_is_stale()`.
- [x] Implement `find-importers` and `summarize-file`; label large projects `L1-large-project` until a real L2 provider exists.
- [x] Route `product`, `architecture`, `workflow`, and `docs` task types to document context; combine explicit `context_sources` with code context for code tasks.
- [x] Populate `entrypoints` and `do_not_touch` from dedicated task fields rather than inferred non-goals.
- [x] Run `py -3 -m unittest tests.test_codegraph_context -v`; expect all tests to pass.

### Task 4: Layered Development Contracts

**Files:**
- Create: `tests/test_layer_plan.py`
- Create: `skills/adworkflo/templates/layer_plan.json`
- Create: `skills/adworkflo/templates/interface_contracts.json`
- Create: `skills/adworkflo/references/layered-development.md`
- Modify: `skills/adworkflo/SKILL.md`
- Modify: `skills/todo-work/SKILL.md`

- [x] Add schema tests requiring presentation, protocol and data layer contracts to answer goal, scope, non-completion, exploration and independent audit.
- [x] Add cross-layer gates for security, privacy, performance, observability, deployment and end-to-end verification.
- [x] Add interface contract records with provider, consumers, inputs, outputs, errors, compatibility and verification.
- [x] Document explicit trigger semantics: layered mode activates only when the user asks for layered development; layers may be marked not-applicable only with a reason.
- [x] Make TODOwork map product capability slices to layer tasks without imposing a fixed three-stage order.
- [x] Run `py -3 -m unittest tests.test_layer_plan -v`; expect all tests to pass.

### Task 5: Resumable Main-Window Orchestration

**Files:**
- Create: `tests/test_orchestrator.py`
- Create: `skills/adworkflo/scripts/orchestrator.py`
- Create: `skills/adworkflo/templates/orchestrator_state.json`
- Create: `skills/adworkflo/templates/resume_manifest.json`
- Create: `skills/adworkflo/templates/artifact_registry.json`
- Modify: `schemas/execution_plan.schema.json`
- Modify: `skills/todo-work/references/execution-plan.md`
- Modify: `skills/artifact-driven-development/references/multi-agent-orchestration.md`

- [x] Test missing dependencies, dependency cycles, max-parallel capacity, ready-task calculation and state revision increments.
- [x] Implement `orchestrator.py start`, `status`, `ready`, `update-task` and `resume` commands.
- [x] Create run-scoped task directories and copy each task spec into its own namespace.
- [x] Record source document hashes, user decisions, artifact pointers, next action and forbidden assumptions.
- [x] Generate resume read order from current active tasks rather than conversation history.
- [x] Run `py -3 -m unittest tests.test_orchestrator -v`; expect all tests to pass.

### Task 6: Safe Initialization And Distribution Sync

**Files:**
- Create: `tests/test_init_distribution.py`
- Modify: `skills/adworkflo/scripts/init_adworkflow.py`
- Modify: `install-adworkflow.ps1`
- Modify: `skills/adworkflo/templates/AGENT_HEADER.md.tpl`

- [x] Test that initialization creates root `AGENTS.md` only when absent and never overwrites an existing one.
- [x] Test that `--force` preserves user-owned configuration and `--force-user-config` explicitly replaces it.
- [x] Initialize alignment, layer, interface and control artifacts without claiming they are configured.
- [x] Run template sync and verify root/protocol mirrors match canonical JSON contracts.
- [x] Verify the installed global Skill contains schemas and providers and can initialize and validate a project without the source repository.
- [x] Run `py -3 -m unittest tests.test_init_distribution -v`; expect all tests to pass.

### Task 7: Documentation And End-To-End Verification

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `AGENT_HEADER.md`
- Modify: `MODULE_SKILLS_GUIDE.md`
- Modify: `CODEGRAPH_RETRIEVAL_PROTOCOL.md`
- Modify: `MULTI_AGENT_ORCHESTRATION.md`
- Modify: `REVIEW_AND_VERIFICATION_PROTOCOL.md`
- Create: `examples/small-project-test/README.md`

- [x] Update all capability statements so they match executable commands and schemas.
- [x] Document PRD-ARCH gate, layered development trigger, run namespaces and compression recovery order.
- [x] Add a real minimal example instead of referencing a missing directory.
- [x] Run `py -3 skills/adworkflo/scripts/sync_templates.py --check`; expect `templates in sync`.
- [x] Run `py -3 skills/adworkflo/scripts/validate_adworkflow.py --project . --templates`; expect success.
- [x] Run `py -3 -m unittest discover -s tests -v`; expect all tests to pass.
- [x] Run PowerShell, JSON, YAML and Python syntax checks plus `git diff --check`; expect no errors.
