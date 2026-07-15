#!/usr/bin/env python3
"""Persistent control-plane state for ADworkflo main-window orchestration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from validate_adworkflow import validate_execution_plan


SCRIPT_DIR = Path(__file__).resolve().parent
TEMPLATE_DIR = SCRIPT_DIR.parent / "templates"
TASK_STATUSES = {"pending", "in_progress", "blocked", "implementation_complete", "verified", "failed"}
ALLOWED_TRANSITIONS = {
    "pending": {"in_progress", "blocked"},
    "in_progress": {"implementation_complete", "verified", "blocked", "failed"},
    "implementation_complete": {"in_progress", "verified", "blocked", "failed"},
    "blocked": {"pending", "in_progress"},
    "failed": {"pending", "in_progress"},
    "verified": set(),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_mismatches(stored: dict[str, Any], recomputed: dict[str, Any], fields: tuple[str, ...]) -> list[str]:
    return [field for field in fields if stored.get(field) != recomputed.get(field)]


def resolve_task_baseline_revision(
    task_dir: Path,
    task_id: str,
    preflight: dict[str, Any],
) -> str:
    from l2_codegraph.safety import resolve_baseline_revision

    return resolve_baseline_revision(
        task_dir, task_id, preflight.get("graph_revision"),
    )


def source_hashes(project: Path, source_docs: list[str]) -> dict[str, str]:
    result = {}
    for relative in source_docs:
        path = project / relative
        if path.exists() and path.is_file():
            result[relative.replace("\\", "/")] = sha256_file(path)
    return result


def flatten_tasks(plan: dict[str, Any]) -> list[dict[str, Any]]:
    return [task for batch in plan.get("batches", []) for task in batch.get("tasks", [])]


def customize_template(name: str, task_id: str) -> dict[str, Any]:
    data = read_json(TEMPLATE_DIR / name)
    if "task_id" in data:
        data["task_id"] = task_id
    return data


def initialize_task_artifacts(project: Path, run_dir: Path, task: dict[str, Any]) -> None:
    task_id = task["task_id"]
    task_dir = run_dir / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    source_spec = (project / task["task_spec_path"]).resolve()
    try:
        source_spec.relative_to(project.resolve())
    except ValueError as error:
        raise ValueError(f"Task spec path escapes project: {source_spec}") from error
    if not source_spec.exists():
        raise FileNotFoundError(f"Task spec missing for {task_id}: {source_spec}")
    shutil.copyfile(source_spec, task_dir / "task_spec.json")
    for name in (
        "context_raw.json", "context_manifest.json", "semantic_slice.json", "context_preflight.json",
        "context_expansion_request.json", "impact_report.json", "worker_state.json",
        "verification_result.json", "review_findings.json",
    ):
        write_json(task_dir / name, customize_template(name, task_id))
    (task_dir / "patch.diff").write_text("", encoding="utf-8")


def build_artifact_registry(run_dir: Path, run_id: str, revision: int) -> dict[str, Any]:
    artifacts = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name in {"artifact_registry.json", "resume_manifest.json"}:
            continue
        relative = path.relative_to(run_dir).as_posix()
        artifacts.append({
            "artifact_id": relative.replace("/", ":"),
            "path": relative,
            "kind": path.stem,
            "revision": revision,
            "sha256": sha256_file(path),
            "status": "current",
        })
    return {"schema": "ADworkflo.artifact_registry.v1", "run_id": run_id, "revision": revision, "artifacts": artifacts}


def start_run(project: Path, run_id: str, plan_path: Path) -> Path:
    project = project.resolve()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise ValueError("run_id must contain only letters, digits, dot, underscore, and hyphen")
    plan = read_json(plan_path)
    errors = validate_execution_plan(plan)
    if errors:
        raise ValueError("Invalid execution plan: " + "; ".join(errors))
    if not plan.get("configured"):
        raise ValueError("Execution plan is not configured")

    run_dir = project / ".adworkflow" / "runs" / run_id
    if run_dir.exists():
        raise FileExistsError(f"Run already exists: {run_dir}")
    run_dir.mkdir(parents=True)
    shutil.copyfile(plan_path, run_dir / "execution_plan.json")
    tasks = flatten_tasks(plan)
    for task in tasks:
        initialize_task_artifacts(project, run_dir, task)

    state = {
        "schema": "ADworkflo.orchestrator_state.v1",
        "run_id": run_id,
        "revision": 0,
        "status": "running",
        "current_phase": "execution",
        "active_tasks": [],
        "completed_tasks": [],
        "blocked_tasks": [],
        "pending_questions": [],
        "confirmed_decisions": [],
        "forbidden_assumptions": ["Do not infer decisions from compressed conversation history."],
        "source_hashes": source_hashes(project, plan.get("source_docs", [])),
        "artifact_pointers": {task["task_id"]: f"tasks/{task['task_id']}" for task in tasks},
        "task_statuses": {task["task_id"]: "pending" for task in tasks},
        "task_dependencies": {task["task_id"]: task.get("depends_on", []) for task in tasks},
        "max_parallel_workers": plan["worker_policy"]["max_parallel_workers"],
        "next_action": "Dispatch ready tasks returned by orchestrator.py ready.",
        "updated_at": now(),
    }
    write_json(run_dir / "orchestrator_state.json", state)
    write_json(run_dir / "artifact_registry.json", build_artifact_registry(run_dir, run_id, 0))
    write_json(run_dir / "resume_manifest.json", build_resume_manifest(run_dir))
    return run_dir


def ready_task_ids(run_dir: Path) -> list[str]:
    state = read_json(run_dir / "orchestrator_state.json")
    if source_drift(run_dir, state):
        return []
    statuses = state["task_statuses"]
    active_count = sum(status == "in_progress" for status in statuses.values())
    available = max(0, state["max_parallel_workers"] - active_count)
    ready = []
    for task_id, status in statuses.items():
        if status != "pending":
            continue
        dependencies = state["task_dependencies"].get(task_id, [])
        if all(statuses.get(dependency) == "verified" for dependency in dependencies):
            ready.append(task_id)
    return ready[:available]


def source_drift(run_dir: Path, state: dict[str, Any] | None = None) -> list[str]:
    state = state or read_json(run_dir / "orchestrator_state.json")
    project = run_dir.parents[2]
    changed = []
    for relative, expected_hash in state.get("source_hashes", {}).items():
        path = project / relative
        current_hash = sha256_file(path) if path.exists() else "missing"
        if current_hash != expected_hash:
            changed.append(relative)
    return sorted(changed)


def completion_errors(run_dir: Path, task_id: str) -> list[str]:
    task_dir = run_dir / "tasks" / task_id
    spec = read_json(task_dir / "task_spec.json")
    verification = read_json(task_dir / "verification_result.json")
    errors = []
    if verification.get("status") != "passed":
        errors.append("verification status must be passed")
    source_revision = verification.get("source_revision")
    if source_revision in {None, ""}:
        errors.append("verification must identify source_revision")
    covered = {
        item.get("criterion")
        for item in verification.get("acceptance_criteria_coverage", [])
        if item.get("status") == "passed" and item.get("evidence")
    }
    for criterion in spec.get("acceptance_criteria", []):
        if criterion not in covered:
            errors.append(f"acceptance criterion lacks passing evidence: {criterion}")
    if verification.get("failed"):
        errors.append("verification contains failed checks")

    manifest = read_json(task_dir / "context_manifest.json")
    uses_l2 = str(manifest.get("context_level", "")).startswith("L2")
    if uses_l2:
        errors.extend(l2_context_errors(run_dir, task_id, require_active_revision=False))
        impact = read_json(task_dir / "impact_report.json")
        preflight = read_json(task_dir / "context_preflight.json")
        project = run_dir.parents[2]
        database = project / ".codegraph" / "l2.sqlite"
        baseline_revision = None
        try:
            baseline_revision = resolve_task_baseline_revision(
                task_dir, task_id, preflight,
            )
        except Exception as error:
            errors.append(f"post-edit impact baseline resolution failed: {error}")
        if database.exists() and baseline_revision is not None:
            baseline = (
                project / ".codegraph" / "snapshots"
                / f"{baseline_revision}.sqlite"
            )
            if baseline.exists():
                try:
                    from l2_codegraph.safety import post_edit_impact
                    worker = read_json(task_dir / "worker_state.json")
                    recomputed_impact = post_edit_impact(
                        task_id,
                        baseline,
                        database,
                        worker.get("changed_files", []),
                        manifest.get("predicted_impact_files", []),
                    )
                    mismatch = evidence_mismatches(impact, recomputed_impact, (
                        "status", "baseline_revision", "current_revision", "changed_files",
                        "observed_impact_files", "unexpected_impact", "symbol_delta", "edge_delta",
                        "new_critical_unresolved_edges", "new_test_critical_unresolved_edges",
                        "propagation", "baseline_validation", "review_required",
                    ))
                    if mismatch:
                        errors.append("stored impact evidence differs from recomputed impact: " + ", ".join(mismatch))
                except Exception as error:
                    errors.append(f"post-edit impact recomputation failed: {error}")
            else:
                errors.append("post-edit impact baseline or active database is missing")
        elif baseline_revision is not None:
            errors.append("post-edit impact baseline or active database is missing")
        if impact.get("status") != "passed":
            errors.append("post-edit impact report must be passed")
        if impact.get("unexpected_impact"):
            errors.append("post-edit impact report contains unexpected impact")
        if impact.get("new_critical_unresolved_edges"):
            errors.append("post-edit impact introduced critical unresolved edges")
        if (
            baseline_revision is not None
            and impact.get("baseline_revision") != baseline_revision
        ):
            errors.append(
                "impact baseline revision must match resolved task baseline revision"
            )
        if database.exists():
            from l2_codegraph.database import connect, metadata
            with connect(database, readonly=True) as connection:
                active_revision = metadata(connection).get("revision")
            if impact.get("current_revision") != active_revision:
                errors.append("impact current revision must match the active L2 graph")

    requires_review = spec.get("risk_level") in {"medium", "high"} or spec.get("execution_mode") == "worker_plus_reviewer"
    if requires_review:
        review = read_json(task_dir / "review_findings.json")
        if review.get("status") != "approved" or not review.get("reviewer"):
            errors.append("independent review must be approved")
        if review.get("blocking_findings"):
            errors.append("review contains blocking findings")
        if review.get("source_revision") != source_revision:
            errors.append("review and verification source_revision must match")
        owner = spec.get("implementation_owner")
        if owner and review.get("reviewer") == owner:
            errors.append("reviewer must differ from implementation owner")
        if uses_l2:
            basis = set(review.get("review_basis", []))
            for required in ("context_preflight", "impact_report"):
                if required not in basis:
                    errors.append(f"L2 review_basis must include {required}")
    return errors


def l2_context_errors(run_dir: Path, task_id: str, require_active_revision: bool = True) -> list[str]:
    task_dir = run_dir / "tasks" / task_id
    manifest = read_json(task_dir / "context_manifest.json")
    if not str(manifest.get("context_level", "")).startswith("L2"):
        return []
    preflight = read_json(task_dir / "context_preflight.json")
    semantic_slice = read_json(task_dir / "semantic_slice.json")
    errors = []
    if preflight.get("status") != "accepted":
        errors.append("L2 context preflight must be accepted")
    if semantic_slice.get("graph_revision") != preflight.get("graph_revision"):
        errors.append("semantic slice and preflight graph revisions must match")
    project = run_dir.parents[2]
    database = project / ".codegraph" / "l2.sqlite"
    if not database.exists():
        errors.append("L2 database is missing")
        return errors
    try:
        from l2_codegraph.query import GraphQuery
        from l2_codegraph.safety import freshness_report, preflight as recompute_preflight
        evidence_database = database
        if not require_active_revision:
            evidence_database = project / ".codegraph" / "snapshots" / f"{preflight.get('graph_revision')}.sqlite"
            if not evidence_database.exists():
                raise FileNotFoundError(f"L2 baseline snapshot is missing: {evidence_database}")
        parameters = semantic_slice.get("parameters", {})
        query = GraphQuery(evidence_database)
        with query.read_session():
            freshness = (
                freshness_report(
                    project, evidence_database, connection=query.connection,
                )
                if require_active_revision else preflight.get("freshness", {})
            )
            active_revision = (
                query.graph_metadata().get("revision")
                if require_active_revision else None
            )
            recomputed_slice = query.slice(
                semantic_slice.get("entrypoints", []),
                depth=int(parameters.get("depth", 2)),
                budget=int(parameters.get("budget", 100)),
                include_callers=bool(parameters.get("include_callers", False)),
                expansion_history=semantic_slice.get("expansion_history", []),
                additional_seeds=parameters.get("additional_seeds", []),
            )
            recomputed_preflight = recompute_preflight(
                project,
                evidence_database,
                recomputed_slice,
                task_id,
                float(preflight.get("confidence_threshold", 0.80)),
                freshness_override=None if require_active_revision else freshness,
                connection=query.connection,
            )
    except Exception as error:
        errors.append(f"L2 freshness check failed: {error}")
    else:
        slice_mismatch = evidence_mismatches(semantic_slice, recomputed_slice, (
            "status", "graph_revision", "entrypoints", "entrypoint_resolutions", "included_symbols",
            "included_files", "boundary_symbols", "unresolved_edges", "likely_tests", "coverage",
            "confidence", "truncated", "source_hashes", "parameters", "expansion_history",
        ))
        if slice_mismatch:
            errors.append("stored semantic slice evidence differs from recomputed slice: " + ", ".join(slice_mismatch))
        preflight_mismatch = evidence_mismatches(preflight, recomputed_preflight, (
            "status", "graph_revision", "slice_revision", "confidence", "confidence_threshold",
            "freshness", "missing_capabilities", "invalid_reasons", "expansion_reasons",
            "required_actions", "critical_unresolved_edges", "expansion_history",
        ))
        if preflight_mismatch:
            errors.append("stored preflight evidence differs from recomputed preflight: " + ", ".join(preflight_mismatch))
        if require_active_revision and not freshness["fresh"]:
            errors.append("L2 context is stale against the source tree")
        if require_active_revision and active_revision != preflight.get("graph_revision"):
            errors.append("active L2 graph revision does not match context preflight")
    return errors


def refresh_state_lists(state: dict[str, Any]) -> None:
    statuses = state["task_statuses"]
    state["active_tasks"] = sorted(task_id for task_id, status in statuses.items() if status == "in_progress")
    state["completed_tasks"] = sorted(task_id for task_id, status in statuses.items() if status == "verified")
    state["blocked_tasks"] = sorted(task_id for task_id, status in statuses.items() if status in {"blocked", "failed"})
    if statuses and all(status == "verified" for status in statuses.values()):
        state["status"] = "complete"
        state["current_phase"] = "complete"
        state["next_action"] = None
    elif state["blocked_tasks"] and not state["active_tasks"]:
        state["status"] = "blocked"
        state["next_action"] = "Resolve blocked task evidence before continuing."
    else:
        state["status"] = "running"
        state["next_action"] = "Dispatch or update ready tasks."


def update_task(run_dir: Path, task_id: str, status: str, expected_revision: int) -> dict[str, Any]:
    if status not in TASK_STATUSES:
        raise ValueError(f"Unsupported task status: {status}")
    state_path = run_dir / "orchestrator_state.json"
    state = read_json(state_path)
    if state["revision"] != expected_revision:
        raise ValueError(f"revision mismatch: expected {expected_revision}, current {state['revision']}")
    if task_id not in state["task_statuses"]:
        raise KeyError(task_id)
    current_status = state["task_statuses"][task_id]
    if status not in ALLOWED_TRANSITIONS[current_status]:
        raise ValueError(f"invalid task transition: {current_status} -> {status}")
    if status in {"in_progress", "verified"} and source_drift(run_dir, state):
        raise ValueError("source documents changed; rebuild the execution plan before continuing")
    if status == "verified":
        errors = completion_errors(run_dir, task_id)
        if errors:
            raise ValueError("; ".join(errors))
    if status == "in_progress":
        context_errors = l2_context_errors(run_dir, task_id)
        if context_errors:
            raise ValueError("; ".join(context_errors))
        dependencies = state["task_dependencies"].get(task_id, [])
        if not all(state["task_statuses"].get(dependency) == "verified" for dependency in dependencies):
            raise ValueError(f"task {task_id} dependencies are not verified")
        active_count = sum(item == "in_progress" for item in state["task_statuses"].values())
        if active_count >= state["max_parallel_workers"]:
            raise ValueError("runtime worker capacity is exhausted")
    state["task_statuses"][task_id] = status
    state["revision"] += 1
    state["updated_at"] = now()
    refresh_state_lists(state)
    write_json(state_path, state)
    write_json(run_dir / "artifact_registry.json", build_artifact_registry(run_dir, state["run_id"], state["revision"]))
    write_json(run_dir / "resume_manifest.json", build_resume_manifest(run_dir))
    return state


def build_resume_manifest(run_dir: Path) -> dict[str, Any]:
    state = read_json(run_dir / "orchestrator_state.json")
    active_artifacts = []
    for task_id in state.get("active_tasks", []):
        for name in (
            "task_spec.json", "context_manifest.json", "semantic_slice.json", "context_preflight.json",
            "context_expansion_request.json", "impact_report.json", "worker_state.json",
            "verification_result.json", "review_findings.json",
        ):
            active_artifacts.append(f"tasks/{task_id}/{name}")
    return {
        "schema": "ADworkflo.resume_manifest.v1",
        "run_id": state["run_id"],
        "orchestrator_revision": state["revision"],
        "read_order": ["orchestrator_state.json", "execution_plan.json", "artifact_registry.json", *active_artifacts],
        "active_task_artifacts": active_artifacts,
        "source_hashes": state.get("source_hashes", {}),
        "source_drift": source_drift(run_dir, state),
        "generated_at": now(),
    }


def resolve_run(project: Path, run_id: str) -> Path:
    run_dir = project.resolve() / ".adworkflow" / "runs" / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(run_dir)
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--run-id", required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("--plan", default=None)
    sub.add_parser("status")
    sub.add_parser("ready")
    update = sub.add_parser("update-task")
    update.add_argument("--task-id", required=True)
    update.add_argument("--status", required=True, choices=sorted(TASK_STATUSES))
    update.add_argument("--expected-revision", required=True, type=int)
    sub.add_parser("resume")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if args.command == "start":
        plan = Path(args.plan).resolve() if args.plan else project / ".adworkflow" / "execution_plan.json"
        run_dir = start_run(project, args.run_id, plan)
        result: Any = {"run_dir": str(run_dir), "ready_tasks": ready_task_ids(run_dir)}
    else:
        run_dir = resolve_run(project, args.run_id)
        if args.command == "status":
            result = read_json(run_dir / "orchestrator_state.json")
        elif args.command == "ready":
            result = {"ready_tasks": ready_task_ids(run_dir)}
        elif args.command == "update-task":
            result = update_task(run_dir, args.task_id, args.status, args.expected_revision)
        else:
            result = build_resume_manifest(run_dir)
            write_json(run_dir / "resume_manifest.json", result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
