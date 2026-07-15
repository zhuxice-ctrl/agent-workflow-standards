from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from l2_codegraph.locking import GraphLockTimeout, graph_lock  # noqa: E402
from l2_codegraph.database import connect  # noqa: E402


def wait_for(path: Path, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {path}")
        time.sleep(0.01)


def signal(path: Path, value: str = "ready\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def sync_path(root: Path, iteration: int, event: str) -> Path:
    return root / f"{iteration:02d}.{event}"


def run_cli_build(project: Path, database: Path) -> int:
    command = [
        sys.executable,
        str(SCRIPT_DIR / "build_codegraph_l2.py"),
        "--project",
        str(project),
        "--out",
        str(database),
        "--no-typescript",
    ]
    completed = subprocess.run(command, text=True, encoding="utf-8", capture_output=True)
    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    return completed.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "hold-lock",
            "hold-reader",
            "try-lock",
            "build-marker",
            "build-pause-after-analysis",
            "cli-build",
            "build-continuous-churn",
            "query-loop",
            "rebuild-loop",
            "publish-candidate",
        ],
    )
    parser.add_argument("--database", required=True)
    parser.add_argument("--kind", choices=["build", "publish"], default="publish")
    parser.add_argument("--shared", action="store_true")
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--ready")
    parser.add_argument("--release")
    parser.add_argument("--project")
    parser.add_argument("--analysis-ready")
    parser.add_argument("--sync-dir")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--candidate")
    parser.add_argument("--revision")
    args = parser.parse_args()
    database = Path(args.database).resolve()

    if args.command == "publish-candidate":
        if not args.candidate or not args.revision or not args.ready or not args.release:
            raise ValueError(
                "publish-candidate requires --candidate, --revision, --ready, and --release"
            )
        from l2_codegraph.database import publish_candidate

        signal(Path(args.ready))
        wait_for(Path(args.release), 30.0)
        publish_candidate(
            Path(args.candidate).resolve(), database, args.revision,
        )
        print(json.dumps({"revision": args.revision}))
        return 0

    if args.command == "cli-build":
        if not args.project or not args.ready or not args.release:
            raise ValueError("cli-build requires --project, --ready, and --release")
        signal(Path(args.ready))
        wait_for(Path(args.release), 30.0)
        return run_cli_build(Path(args.project).resolve(), database)

    if args.command == "build-continuous-churn":
        if not args.project or not args.sync_dir:
            raise ValueError("build-continuous-churn requires --project and --sync-dir")
        import build_codegraph_l2

        project = Path(args.project).resolve()
        sync_dir = Path(args.sync_dir).resolve()
        original = build_codegraph_l2.analyze_python
        calls = 0

        def synchronized_analyze(root: Path, config: dict) -> dict:
            nonlocal calls
            result = original(root, config)
            calls += 1
            signal(sync_path(sync_dir, calls, "analysis-ready"))
            wait_for(sync_path(sync_dir, calls, "analysis-release"), 30.0)
            return result

        build_codegraph_l2.analyze_python = synchronized_analyze
        try:
            build_codegraph_l2.build(
                project,
                database,
                include_typescript=False,
                max_source_attempts=args.iterations,
            )
        except build_codegraph_l2.SourceChangedDuringBuild as error:
            print(json.dumps({**error.as_dict(), "analysis_calls": calls}), file=sys.stderr)
            return 4
        raise AssertionError("continuous source churn unexpectedly produced a successful build")

    if args.command == "query-loop":
        if not args.sync_dir:
            raise ValueError("query-loop requires --sync-dir")
        from l2_codegraph.query import GraphQuery

        sync_dir = Path(args.sync_dir).resolve()
        query = GraphQuery(database)
        records = []
        for iteration in range(args.iterations):
            original_resolve = query.resolve_symbol
            resolution: dict[str, object] = {}
            armed = True

            def synchronized_resolve(value: str) -> dict:
                nonlocal armed
                result = original_resolve(value)
                if armed:
                    armed = False
                    resolution["revision"] = query.graph_metadata()["revision"]
                    resolution["sha256"] = result.get("symbol", {}).get("sha256")
                    signal(
                        sync_path(sync_dir, iteration, "read-ready"),
                        json.dumps(resolution) + "\n",
                    )
                    wait_for(sync_path(sync_dir, iteration, "query-release"), 30.0)
                return result

            query.resolve_symbol = synchronized_resolve  # type: ignore[method-assign]
            operation = "slice" if iteration % 2 == 0 else "impact"
            if operation == "slice":
                result = query.slice(["app.entry"], depth=2, budget=50)
                records.append({
                    "operation": operation,
                    "pinned_revision": resolution["revision"],
                    "resolved_hash": resolution["sha256"],
                    "result_revision": result.get("graph_revision"),
                    "result_status": result.get("status"),
                    "source_hashes": result.get("source_hashes", {}),
                })
            else:
                result = query.impact("app.leaf", depth=2, budget=50)
                records.append({
                    "operation": operation,
                    "pinned_revision": resolution["revision"],
                    "resolved_hash": resolution["sha256"],
                    "result_revision": result.get("graph_revision"),
                    "result_status": result.get("status"),
                    "target": result.get("target"),
                    "predicted_files": result.get("predicted_files", []),
                })
            query.resolve_symbol = original_resolve  # type: ignore[method-assign]
            wait_for(sync_path(sync_dir, iteration, "published"), 30.0)
        print(json.dumps({"records": records}))
        return 0

    if args.command == "rebuild-loop":
        if not args.project or not args.sync_dir:
            raise ValueError("rebuild-loop requires --project and --sync-dir")
        import build_codegraph_l2

        project = Path(args.project).resolve()
        sync_dir = Path(args.sync_dir).resolve()
        original_publish = build_codegraph_l2.publish_candidate
        publishing_iteration = 0

        def synchronized_publish(candidate: Path, active: Path, revision: str, **kwargs: object) -> None:
            reader_blocked_publication = False
            try:
                with graph_lock(active, "publish", shared=False, timeout=0.2):
                    pass
            except GraphLockTimeout:
                reader_blocked_publication = True
            signal(
                sync_path(sync_dir, publishing_iteration, "publish-attempt"),
                json.dumps({
                    "revision": revision,
                    "reader_blocked_publication": reader_blocked_publication,
                }) + "\n",
            )
            if reader_blocked_publication:
                signal(sync_path(sync_dir, publishing_iteration, "query-release"))
                original_publish(candidate, active, revision, **kwargs)
            else:
                try:
                    original_publish(candidate, active, revision, **kwargs)
                finally:
                    signal(sync_path(sync_dir, publishing_iteration, "query-release"))

        build_codegraph_l2.publish_candidate = synchronized_publish
        revisions = []
        for iteration in range(args.iterations):
            publishing_iteration = iteration
            wait_for(sync_path(sync_dir, iteration, "read-ready"), 30.0)
            (project / "app.py").write_text(
                "def leaf():\n"
                f"    return {iteration + 1}\n\n"
                "def entry():\n"
                "    return leaf()\n",
                encoding="utf-8",
            )
            result = build_codegraph_l2.build(project, database, include_typescript=False)
            revisions.append(result["revision"])
            signal(sync_path(sync_dir, iteration, "published"), result["revision"] + "\n")
        print(json.dumps({"revisions": revisions}))
        return 0

    if args.command in {"build-marker", "build-pause-after-analysis"}:
        if not args.project or not args.ready:
            raise ValueError(f"{args.command} requires --project and --ready")
        import build_codegraph_l2

        project = Path(args.project).resolve()
        original = build_codegraph_l2.analyze_python
        calls = 0

        if args.command == "build-marker":
            if not args.analysis_ready:
                raise ValueError("build-marker requires --analysis-ready")
            original_graph_lock = build_codegraph_l2.graph_lock

            def marked_graph_lock(*lock_args: object, **lock_kwargs: object) -> object:
                signal(Path(args.ready))
                return original_graph_lock(*lock_args, **lock_kwargs)

            build_codegraph_l2.graph_lock = marked_graph_lock

        def marked_analyze(root: Path, config: dict) -> dict:
            nonlocal calls
            calls += 1
            if args.command == "build-marker":
                signal(Path(args.analysis_ready), "analysis-started\n")
                return original(root, config)
            result = original(root, config)
            if calls == 1:
                if not args.release:
                    raise ValueError("build-pause-after-analysis requires --release")
                signal(Path(args.ready), "analysis-complete\n")
                wait_for(Path(args.release), 30.0)
            return result

        build_codegraph_l2.analyze_python = marked_analyze
        result = build_codegraph_l2.build(project, database, include_typescript=False)
        print(json.dumps({**result, "analysis_calls": calls}))
        return 0

    if args.command == "hold-reader":
        if not args.ready or not args.release:
            raise ValueError("hold-reader requires --ready and --release")
        with connect(database, readonly=True) as connection:
            revision = connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0]
            Path(args.ready).write_text(revision + "\n", encoding="utf-8")
            wait_for(Path(args.release), 30.0)
        print(json.dumps({"status": "reader-released", "revision": revision}))
        return 0

    try:
        with graph_lock(database, args.kind, shared=args.shared, timeout=args.timeout) as lease:
            if args.command == "hold-lock":
                if not args.ready or not args.release:
                    raise ValueError("hold-lock requires --ready and --release")
                Path(args.ready).write_text("ready\n", encoding="utf-8")
                wait_for(Path(args.release), 30.0)
            print(json.dumps({
                "status": "acquired",
                "kind": lease.kind,
                "mode": lease.mode,
                "lock_path": str(lease.path),
            }))
            return 0
    except GraphLockTimeout as error:
        print(json.dumps(error.as_dict()), file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
