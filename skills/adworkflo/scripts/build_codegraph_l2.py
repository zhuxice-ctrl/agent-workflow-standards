#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from l2_codegraph.database import (
    CandidateIntegrityError, GraphPublicationError, SourceChangedDuringBuild,
    build_candidate_database, graph_error_payload, publish_candidate,
)
from l2_codegraph.locking import GraphLockTimeout, graph_lock
from l2_codegraph.model import LANGUAGE_EXTENSIONS, load_graph_config, normalize_graph_config
from l2_codegraph.python_provider import analyze_project as analyze_python
from l2_codegraph.safety import current_source_paths, sha256_file


def source_state(project: Path, config: dict, languages: set[str]) -> dict[str, str]:
    extension_languages = {
        extension: language
        for language, extensions in LANGUAGE_EXTENSIONS.items()
        for extension in extensions
    }
    try:
        return {
            relative: sha256_file(project / relative)
            for relative in current_source_paths(project, config)
            if extension_languages.get(Path(relative).suffix.lower()) in languages
        }
    except OSError:
        return {"<unstable-source-state>": "<retry>"}


def provider_source_state(results: list[dict]) -> dict[str, str]:
    return {
        record["path"]: record["sha256"]
        for result in results
        for record in result["files"]
    }


def path_matches_languages(path: str, languages: set[str]) -> bool:
    lowered = path.lower()
    return any(
        lowered.endswith(extension)
        for language in languages
        for extension in LANGUAGE_EXTENSIONS[language]
    )


def build(
    project: Path,
    out: Path,
    include_typescript: bool = True,
    require_typescript: bool = False,
    max_source_attempts: int = 2,
) -> dict:
    project = project.resolve()
    out = out.resolve()
    if max_source_attempts < 1:
        raise ValueError("max_source_attempts must be positive")
    with graph_lock(out, "build", shared=False):
        for _attempt in range(max_source_attempts):
            config = load_graph_config(project)
            before_all = source_state(project, config, {"python", "typescript", "javascript"})
            results = []
            ts_status = {"available": False, "reason": "not requested"}
            try:
                python_result = analyze_python(project, config)
                if python_result["files"]:
                    results.append(python_result)
                if include_typescript:
                    from l2_codegraph.typescript_provider import analyze_project as analyze_typescript
                    ts_result, ts_status = analyze_typescript(project, config)
                    if ts_result and ts_result["files"]:
                        results.append(ts_result)
                    elif require_typescript:
                        raise RuntimeError(ts_status["reason"])
            except OSError:
                continue
            if not results:
                detail = ts_status.get("reason", "no provider accepted the project sources")
                raise RuntimeError(f"No source files were handled by a capable L2 provider: {detail}")

            handled_languages = {
                language for result in results for language in result["languages"]
            }
            expected = provider_source_state(results)
            before = {
                path: digest for path, digest in before_all.items()
                if path_matches_languages(path, handled_languages)
            }
            candidate, revision = build_candidate_database(project, out, results, config)
            try:
                try:
                    final_config = load_graph_config(project)
                except ValueError:
                    continue
                after = source_state(project, final_config, handled_languages)
                stable = (
                    normalize_graph_config(config) == normalize_graph_config(final_config)
                    and before == expected == after
                )
                if stable:
                    publish_candidate(candidate, out, revision)
                    candidate = None
                    return {
                        "schema": "ADworkflo.codegraph.build_result.v1",
                        "database": str(out),
                        "revision": revision,
                        "providers": [item["provider"] for item in results],
                        "typescript": ts_status,
                        "file_count": sum(len(item["files"]) for item in results),
                        "symbol_count": sum(len(item["symbols"]) for item in results),
                    }
            finally:
                if candidate is not None:
                    try:
                        candidate.unlink(missing_ok=True)
                    except OSError:
                        pass
        raise SourceChangedDuringBuild(project, max_source_attempts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the ADworkflo L2 semantic SQLite graph.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--no-typescript", action="store_true")
    parser.add_argument("--require-typescript", action="store_true")
    args = parser.parse_args()
    project = Path(args.project).resolve()
    out = Path(args.out).resolve() if args.out else project / ".codegraph" / "l2.sqlite"
    try:
        result = build(
            project, out, not args.no_typescript, args.require_typescript,
        )
    except (
        CandidateIntegrityError,
        GraphLockTimeout,
        GraphPublicationError,
        SourceChangedDuringBuild,
    ) as error:
        payload = graph_error_payload(error)
        assert payload is not None
        print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)
        return 3 if payload["retryable"] else 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
