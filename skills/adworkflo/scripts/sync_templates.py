#!/usr/bin/env python3
"""Synchronize duplicated ADworkflo JSON templates from one canonical source."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


CANONICAL_NAMES = (
    "architecture_manifest.json",
    "artifact_registry.json",
    "context_manifest.json",
    "context_expansion_request.json",
    "context_preflight.json",
    "context_raw.json",
    "design_alignment_report.json",
    "execution_plan.json",
    "interface_contracts.json",
    "impact_report.json",
    "layer_plan.json",
    "orchestrator_state.json",
    "resume_manifest.json",
    "review_findings.json",
    "semantic_slice.json",
    "task_spec.json",
    "verification_result.json",
    "worker_state.json",
)


def canonical_dir(repo_root: Path) -> Path:
    return repo_root / "skills" / "adworkflo" / "templates"


def mirror_dirs(repo_root: Path) -> tuple[Path, ...]:
    import_root = next(
        path for path in repo_root.iterdir()
        if path.is_dir() and path.name.startswith("ADworkflo")
    )
    return (
        repo_root / "templates",
        repo_root / "skills" / "artifact-driven-development" / "templates",
        import_root / "copy-to-project" / ".adworkflow",
    )


def expected_pairs(repo_root: Path):
    source_dir = canonical_dir(repo_root)
    for name in CANONICAL_NAMES:
        source = source_dir / name
        for target_dir in mirror_dirs(repo_root):
            yield source, target_dir / name


def find_drift(repo_root: Path) -> list[str]:
    drift: list[str] = []
    for source, target in expected_pairs(repo_root):
        if not source.exists():
            drift.append(f"missing canonical template: {source.relative_to(repo_root)}")
        elif not target.exists():
            drift.append(f"missing mirror: {target.relative_to(repo_root)}")
        elif source.read_bytes() != target.read_bytes():
            drift.append(f"content drift: {target.relative_to(repo_root)}")
    return drift


def write_mirrors(repo_root: Path) -> None:
    for source, target in expected_pairs(repo_root):
        if not source.exists():
            raise FileNotFoundError(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--repo", default=None, help="Repository root; inferred by default.")
    args = parser.parse_args()

    repo_root = Path(args.repo).resolve() if args.repo else Path(__file__).resolve().parents[3]
    if args.write:
        write_mirrors(repo_root)

    drift = find_drift(repo_root)
    if drift:
        print("template drift detected:")
        for item in drift:
            print(f"- {item}")
        return 1
    print("templates in sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
