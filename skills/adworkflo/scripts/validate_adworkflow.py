#!/usr/bin/env python3
"""Validate ADworkflo artifacts, templates, and execution-plan dependencies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

import sync_templates


def validate_execution_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    tasks: dict[str, dict[str, Any]] = {}
    for batch in plan.get("batches", []):
        for task in batch.get("tasks", []):
            task_id = task.get("task_id", "")
            if not task_id:
                errors.append("task without task_id")
            elif task_id in tasks:
                errors.append(f"duplicate task_id {task_id}")
            else:
                tasks[task_id] = task

    graph: dict[str, list[str]] = {}
    for task_id, task in tasks.items():
        dependencies = task.get("depends_on", [])
        graph[task_id] = dependencies
        for dependency in dependencies:
            if dependency not in tasks:
                errors.append(f"task {task_id} has unknown dependency {dependency}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            errors.append(f"dependency cycle includes {task_id}")
            return
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph.get(task_id, []):
            if dependency in graph:
                visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)

    capacity = plan.get("worker_policy", {}).get("max_parallel_workers", 0)
    if not isinstance(capacity, int) or capacity < 1:
        errors.append("worker_policy.max_parallel_workers must be a positive integer")
    return sorted(set(errors))


def validate_layer_plan(plan: dict[str, Any]) -> list[str]:
    if not plan.get("configured") or plan.get("mode") != "layered":
        return []
    errors: list[str] = []
    layers = {item.get("layer_id"): item for item in plan.get("layers", [])}
    required = {"presentation", "protocol", "data"}
    if set(layers) != required:
        errors.append("layered mode requires exactly presentation, protocol, and data layers")
    for layer_id, layer in layers.items():
        status = layer.get("status")
        if status == "not_applicable":
            if not layer.get("not_applicable_reason"):
                errors.append(f"layer {layer_id} requires not_applicable_reason")
            continue
        if not layer.get("final_goal"):
            errors.append(f"layer {layer_id} requires final_goal")
        if not layer.get("non_completion_conditions"):
            errors.append(f"layer {layer_id} requires non_completion_conditions")
        audit = layer.get("exploration_and_audit", {})
        if not audit.get("read_first") or not audit.get("questions_to_resolve"):
            errors.append(f"layer {layer_id} requires an exploration plan")
        if not audit.get("required_audit_evidence"):
            errors.append(f"layer {layer_id} requires audit evidence")
        if status == "complete":
            owner = audit.get("implementation_owner")
            auditor = audit.get("independent_auditor")
            if not owner or not auditor:
                errors.append(f"complete layer {layer_id} requires implementation owner and independent auditor")
            elif owner == auditor:
                errors.append(f"layer {layer_id} independent auditor must differ from implementation owner")
    return sorted(set(errors))


def validate_json(path: Path, schema_path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    schema = json.loads(schema_path.read_text(encoding="utf-8-sig"))
    validator = Draft202012Validator(schema)
    errors = []
    for error in validator.iter_errors(data):
        location = ".".join(map(str, error.path)) or "<root>"
        errors.append(f"{path}: {location}: {error.message}")
    if path.name == "execution_plan.json" and data.get("configured"):
        errors.extend(f"{path}: {item}" for item in validate_execution_plan(data))
    if path.name == "layer_plan.json" and data.get("configured"):
        errors.extend(f"{path}: {item}" for item in validate_layer_plan(data))
    return errors


def known_schema_path(repo_root: Path, artifact: Path) -> Path | None:
    aliases = {
        "ADWORKFLOW_PROFILE": "adworkflow_profile",
        "index": "codegraph",
    }
    schema_name = aliases.get(artifact.stem, artifact.stem)
    schema_root = repo_root / "schemas"
    if not schema_root.exists():
        schema_root = Path(__file__).resolve().parents[1] / "schemas"
    candidate = schema_root / f"{schema_name}.schema.json"
    return candidate if candidate.exists() else None


def validate_project(repo_root: Path, project: Path) -> list[str]:
    errors: list[str] = []
    artifact_root = project / ".adworkflow"
    artifacts = list(artifact_root.glob("*.json"))
    runs_root = artifact_root / "runs"
    if runs_root.exists():
        artifacts.extend(runs_root.rglob("*.json"))
    for artifact in sorted(artifacts):
        schema = known_schema_path(repo_root, artifact)
        if schema:
            errors.extend(validate_json(artifact, schema))
    codegraph = project / ".codegraph" / "index.json"
    if codegraph.exists():
        schema = known_schema_path(repo_root, codegraph)
        if schema:
            errors.extend(validate_json(codegraph, schema))
    l2_database = project / ".codegraph" / "l2.sqlite"
    if l2_database.exists():
        try:
            from l2_codegraph.database import connect, metadata
            from l2_codegraph.model import REQUIRED_L2_CAPABILITIES
            with connect(l2_database, readonly=True) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                foreign_keys = list(connection.execute("PRAGMA foreign_key_check"))
                graph = metadata(connection)
            if integrity != "ok" or foreign_keys:
                errors.append(f"{l2_database}: SQLite integrity validation failed")
            if not graph.get("revision"):
                errors.append(f"{l2_database}: missing graph revision")
            for provider in graph.get("providers", []):
                missing = REQUIRED_L2_CAPABILITIES - set(provider.get("capabilities", []))
                if missing:
                    errors.append(f"{l2_database}: provider {provider.get('provider')} missing {sorted(missing)}")
        except Exception as error:
            errors.append(f"{l2_database}: L2 validation failed: {error}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--templates", action="store_true")
    parser.add_argument("--repo", default=None)
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parents[3]
    project = Path(args.project).resolve()
    errors = validate_project(repo_root, project)
    if args.templates:
        errors.extend(sync_templates.find_drift(repo_root))
        for template in sorted(sync_templates.canonical_dir(repo_root).glob("*.json")):
            schema = known_schema_path(repo_root, template)
            if schema:
                errors.extend(validate_json(template, schema))

    if errors:
        print("validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("ADworkflo validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
