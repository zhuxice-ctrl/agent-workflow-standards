#!/usr/bin/env python3
"""Initialize ADworkflo files inside a project.

This script is intentionally conservative:
- It only writes ADworkflo metadata/header/template files.
- It analyzes first-layer product docs when present, then falls back to source counts.
- It does not modify source code.
- It does not overwrite existing files unless --force is passed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Iterable

from analyze_project_plan import build_architecture_manifest


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = SKILL_ROOT / "templates"

SOURCE_EXTENSIONS = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".cs": "csharp",
    ".php": "php",
    ".rb": "ruby",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".hpp": "cpp",
}

EXCLUDE_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".turbo",
    "coverage",
    ".codegraph",
    ".adworkflow",
}


def iter_source_files(project: Path) -> Iterable[Path]:
    for root, dirs, files in os.walk(project):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for name in files:
            path = root_path / name
            if path.suffix.lower() in SOURCE_EXTENSIONS:
                yield path


def count_lines(path: Path) -> int:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def detect_include_dirs(project: Path) -> list[str]:
    candidates = [
        "src",
        "app",
        "apps",
        "backend",
        "frontend",
        "server",
        "client",
        "lib",
        "packages",
        "tests",
        "__tests__",
    ]
    found = [name for name in candidates if (project / name).is_dir()]
    return found or ["."]


def strategy_for_size(size: str) -> str:
    if size == "small":
        return "L0-rg-manual-context-manifest"
    if size == "medium":
        return "L1-symbol-import-test-index"
    return "L2-full-codegraph"


def queries_for_size(size: str) -> list[str]:
    if size == "small":
        return ["rg_search", "file_tree", "manual_context_manifest"]
    if size == "medium":
        return ["find_definition", "find_importers", "tests_for", "summarize_file"]
    return [
        "find_definition",
        "find_references",
        "callers",
        "callees",
        "impacted_files",
        "tests_for",
        "get_slice",
        "summarize_file",
    ]


def classify_project(source_count: int, loc: int, forced: str) -> tuple[str, str, list[str]]:
    if forced != "auto":
        size = forced
    elif source_count <= 50 and loc <= 5_000:
        size = "small"
    elif source_count <= 300 and loc <= 50_000:
        size = "medium"
    else:
        size = "large"

    return size, strategy_for_size(size), queries_for_size(size)


def read_template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8")


def render_template(name: str, values: dict[str, str]) -> str:
    text = read_template(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", value)
    return text


def write_file(path: Path, content: str, force: bool) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def copy_template(name: str, dest: Path, force: bool) -> bool:
    return write_file(dest, read_template(name), force)


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize ADworkflo in a project.")
    parser.add_argument("--project", required=True, help="Project root path.")
    parser.add_argument(
        "--mode",
        choices=["auto", "small", "medium", "large"],
        default="auto",
        help="Force project size classification or use auto.",
    )
    parser.add_argument(
        "--skip-doc-analysis",
        action="store_true",
        help="Skip first-layer PRD/ARCH/TODO/PROJECT analysis and use source scan classification only.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing ADworkflo files.")
    args = parser.parse_args()

    project = Path(args.project).resolve()
    if not project.exists() or not project.is_dir():
        raise SystemExit(f"Project path is not a directory: {project}")

    source_files = list(iter_source_files(project))
    source_count = len(source_files)
    loc = sum(count_lines(p) for p in source_files)
    languages = sorted({SOURCE_EXTENSIONS[p.suffix.lower()] for p in source_files})
    include_dirs = detect_include_dirs(project)
    size, strategy, queries = classify_project(source_count, loc, args.mode)
    classification_source = "manual" if args.mode != "auto" else "source_scan_fallback"
    execution_mode = "solo"
    expected_complexity_score: int | None = None
    architecture_manifest = None

    if not args.skip_doc_analysis:
        architecture_manifest = build_architecture_manifest(project)
        if architecture_manifest.get("analysis_basis"):
            expected_complexity_score = architecture_manifest["expected_complexity_score"]
            execution_mode = architecture_manifest["execution_mode"]
            classification_source = "manual_override_with_product_docs" if args.mode != "auto" else "product_docs"
            if args.mode == "auto":
                size = architecture_manifest["project_size"]
                strategy = architecture_manifest["context_strategy"]
                queries = queries_for_size(size)

    values = {
        "PROJECT_SIZE": size,
        "CONTEXT_STRATEGY": strategy,
        "SOURCE_FILE_COUNT": str(source_count),
        "SOURCE_LINE_COUNT": str(loc),
        "LANGUAGES": ", ".join(languages) if languages else "unknown",
        "CLASSIFICATION_SOURCE": classification_source,
        "EXECUTION_MODE": execution_mode,
        "EXPECTED_COMPLEXITY_SCORE": str(expected_complexity_score) if expected_complexity_score is not None else "n/a",
        "LANGUAGES_JSON": json.dumps(languages, ensure_ascii=False, indent=2),
        "INCLUDE_DIRS_JSON": json.dumps(include_dirs, ensure_ascii=False, indent=2),
        "SUPPORTED_QUERIES_JSON": json.dumps(queries, ensure_ascii=False, indent=2),
    }

    outputs: list[tuple[str, bool]] = []
    outputs.append((
        ".codex/AGENT_HEADER.md",
        write_file(project / ".codex" / "AGENT_HEADER.md", render_template("AGENT_HEADER.md.tpl", values), args.force),
    ))
    outputs.append((
        ".adworkflow/PROJECT.md",
        write_file(project / ".adworkflow" / "PROJECT.md", render_template("PROJECT.md.tpl", values), args.force),
    ))
    outputs.append((
        ".codegraph/config.json",
        write_file(project / ".codegraph" / "config.json", render_template("codegraph_config.json.tpl", values), args.force),
    ))

    profile = {
        "project_size": size,
        "context_strategy": strategy,
        "source_file_count": source_count,
        "source_line_count": loc,
        "languages": languages,
        "include_dirs": include_dirs,
        "supported_queries": queries,
        "classification_source": classification_source,
        "execution_mode": execution_mode,
        "expected_complexity_score": expected_complexity_score,
    }
    if architecture_manifest and architecture_manifest.get("analysis_basis"):
        profile.update({
            "planned_modules": architecture_manifest["planned_modules"],
            "risk_areas": architecture_manifest["risk_areas"],
            "agent_features": architecture_manifest["agent_features"],
        })
    outputs.append((
        ".adworkflow/ADWORKFLOW_PROFILE.json",
        write_file(
            project / ".adworkflow" / "ADWORKFLOW_PROFILE.json",
            json.dumps(profile, ensure_ascii=False, indent=2) + "\n",
            args.force,
        ),
    ))

    if architecture_manifest and architecture_manifest.get("analysis_basis"):
        outputs.append((
            ".adworkflow/architecture_manifest.json",
            write_file(
                project / ".adworkflow" / "architecture_manifest.json",
                json.dumps(architecture_manifest, ensure_ascii=False, indent=2) + "\n",
                args.force,
            ),
        ))
    else:
        outputs.append((
            ".adworkflow/architecture_manifest.json",
            copy_template("architecture_manifest.json", project / ".adworkflow" / "architecture_manifest.json", args.force),
        ))

    for name in [
        "execution_plan.json",
        "task_spec.json",
        "context_raw.json",
        "context_manifest.json",
        "worker_state.json",
        "verification_result.json",
        "review_findings.json",
    ]:
        outputs.append((
            f".adworkflow/{name}",
            copy_template(name, project / ".adworkflow" / name, args.force),
        ))

    for template_name, target_name in [
        ("permissions.md", "permissions.md"),
        ("verification_commands.md", "verification_commands.md"),
        ("review_checklist.md", "review_checklist.md"),
        ("module_skills.md", "module_skills.md"),
        ("final_summary.template.md", "final_summary.template.md"),
        ("artifacts_README.md", "artifacts/README.md"),
        ("task_specs_README.md", "task_specs/README.md"),
    ]:
        outputs.append((
            f".adworkflow/{target_name}",
            copy_template(template_name, project / ".adworkflow" / target_name, args.force),
        ))

    print("ADworkflo initialized")
    print(f"Project: {project}")
    print(f"Size: {size}")
    print(f"Context strategy: {strategy}")
    print(f"Classification source: {classification_source}")
    print(f"Execution mode: {execution_mode}")
    if expected_complexity_score is not None:
        print(f"Expected complexity score: {expected_complexity_score}")
    if architecture_manifest and architecture_manifest.get("analysis_basis"):
        docs = ", ".join(item["path"] for item in architecture_manifest["analysis_basis"])
        print(f"Product docs analyzed: {docs}")
    print(f"Source files: {source_count}")
    print(f"Source lines: {loc}")
    print(f"Languages: {', '.join(languages) if languages else 'unknown'}")
    print("Files:")
    for rel, written in outputs:
        status = "written" if written else "exists-skipped"
        print(f"  {status}: {rel}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
