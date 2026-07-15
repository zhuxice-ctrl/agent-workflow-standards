from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))
WORKER = ROOT / "tests" / "l2_concurrency_worker.py"
BUILD_SCRIPT = ROOT / "skills" / "adworkflo" / "scripts" / "build_codegraph_l2.py"
QUERY_SCRIPT = ROOT / "skills" / "adworkflo" / "scripts" / "query_codegraph.py"
PYTHON = sys.executable


class L2SubprocessHelpers:
    def wait_for_file(self, path: Path, process: subprocess.Popen[str], timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while not path.exists():
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                self.fail(f"lock holder exited early ({process.returncode}): stdout={stdout!r} stderr={stderr!r}")
            if time.monotonic() >= deadline:
                process.terminate()
                stdout, stderr = process.communicate(timeout=5)
                self.fail(f"timed out waiting for {path}: stdout={stdout!r} stderr={stderr!r}")
            time.sleep(0.01)

    def start_holder(
        self, root: Path, *, shared: bool, kind: str = "publish",
    ) -> tuple[subprocess.Popen[str], Path, Path, Path]:
        database = root / "l2.sqlite"
        ready = root / ("shared.ready" if shared else "exclusive.ready")
        release = root / ("shared.release" if shared else "exclusive.release")
        command = [
            PYTHON, str(WORKER), "hold-lock", "--database", str(database),
            "--kind", kind, "--timeout", "2", "--ready", str(ready), "--release", str(release),
        ]
        if shared:
            command.append("--shared")
        process = subprocess.Popen(command, text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.wait_for_file(ready, process)
        return process, database, ready, release

    def run_try(self, database: Path, *, shared: bool, timeout: float = 0.25) -> subprocess.CompletedProcess[str]:
        command = [
            PYTHON, str(WORKER), "try-lock", "--database", str(database),
            "--timeout", str(timeout),
        ]
        if shared:
            command.append("--shared")
        return subprocess.run(command, text=True, encoding="utf-8", capture_output=True, timeout=5)

    def assert_no_traceback(self, stdout: str, stderr: str) -> None:
        combined = stdout + stderr
        self.assertNotIn("Traceback (most recent call last)", combined)
        self.assertNotIn("sqlite3.DatabaseError", combined)
        self.assertNotIn("PermissionError", combined)

    @staticmethod
    def terminate_processes(processes: list[subprocess.Popen[str]]) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        for process in processes:
            if process.poll() is None:
                process.communicate(timeout=5)

    def run_cli_build(self, project: Path, database: Path) -> dict:
        completed = subprocess.run([
            PYTHON, str(BUILD_SCRIPT), "--project", str(project), "--out", str(database), "--no-typescript",
        ], text=True, encoding="utf-8", capture_output=True, timeout=30)
        self.assert_no_traceback(completed.stdout, completed.stderr)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertEqual("", completed.stderr)
        return json.loads(completed.stdout)

    @staticmethod
    def database_revision(database: Path) -> str:
        with closing(sqlite3.connect(database)) as connection:
            return connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0]


class L2LockTests(L2SubprocessHelpers, unittest.TestCase):

    def test_lock_timeout_rejects_negative_and_non_finite_values(self) -> None:
        from l2_codegraph.locking import lock_timeout

        for value in (-1.0, float("nan"), float("inf")):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "finite non-negative"):
                    lock_timeout(value)

    def test_shared_publish_leases_can_coexist(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            holder, database, _, release = self.start_holder(root, shared=True)
            try:
                contender = self.run_try(database, shared=True)
                self.assertEqual(0, contender.returncode, contender.stderr)
                self.assertEqual("shared", json.loads(contender.stdout)["mode"])
            finally:
                release.write_text("release\n", encoding="utf-8")
                stdout, stderr = holder.communicate(timeout=5)
                self.assertEqual(0, holder.returncode, stderr or stdout)

    def test_shared_reader_blocks_exclusive_publisher_with_structured_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            holder, database, _, release = self.start_holder(root, shared=True)
            try:
                contender = self.run_try(database, shared=False)
                self.assertEqual(3, contender.returncode, contender.stdout + contender.stderr)
                error = json.loads(contender.stderr)
                self.assertEqual("graph-lock-timeout", error["code"])
                self.assertEqual("publish", error["kind"])
                self.assertEqual("exclusive", error["mode"])
                self.assertTrue(error["retryable"])
            finally:
                release.write_text("release\n", encoding="utf-8")
                holder.communicate(timeout=5)

    def test_terminated_holder_releases_os_lock_even_when_lock_file_remains(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            holder, database, _, _ = self.start_holder(root, shared=False)
            holder.terminate()
            holder.communicate(timeout=5)
            contender = self.run_try(database, shared=False, timeout=1.0)
            self.assertEqual(0, contender.returncode, contender.stderr)
            result = json.loads(contender.stdout)
            self.assertEqual("exclusive", result["mode"])
            self.assertTrue(Path(result["lock_path"]).exists())


class L2ConnectionLeaseTests(L2SubprocessHelpers, unittest.TestCase):

    @staticmethod
    def create_database(database: Path, revision: str = "revision-a") -> None:
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            connection.execute("INSERT INTO metadata(key, value) VALUES ('revision', ?)", (revision,))
            connection.commit()

    def test_readonly_connection_holds_shared_publish_lease_until_close(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / "l2.sqlite"
            self.create_database(database)
            ready = root / "reader.ready"
            release = root / "reader.release"
            reader = subprocess.Popen([
                PYTHON, str(WORKER), "hold-reader", "--database", str(database),
                "--ready", str(ready), "--release", str(release),
            ], text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.wait_for_file(ready, reader)
            try:
                blocked = self.run_try(database, shared=False, timeout=0.2)
                self.assertEqual(3, blocked.returncode, blocked.stdout + blocked.stderr)
            finally:
                release.write_text("release\n", encoding="utf-8")
                stdout, stderr = reader.communicate(timeout=5)
                self.assertEqual(0, reader.returncode, stderr or stdout)
            acquired = self.run_try(database, shared=False, timeout=1.0)
            self.assertEqual(0, acquired.returncode, acquired.stderr)


class L2BuildCoordinationTests(L2SubprocessHelpers, unittest.TestCase):
    @staticmethod
    def create_project(root: Path, value: int = 1) -> Path:
        project = root / "project"
        project.mkdir()
        (project / "app.py").write_text(f"def entry():\n    return {value}\n", encoding="utf-8")
        return project

    def test_build_lock_is_acquired_before_provider_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            holder, database, _, release = self.start_holder(root, shared=False, kind="build")
            project = self.create_project(root)
            lock_attempted = root / "build.attempted"
            analysis_started = root / "analysis.started"
            builder = subprocess.Popen([
                PYTHON, str(WORKER), "build-marker", "--database", str(database),
                "--project", str(project), "--ready", str(lock_attempted),
                "--analysis-ready", str(analysis_started),
            ], text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.wait_for_file(lock_attempted, builder)
                self.assertFalse(analysis_started.exists(), "provider analysis ran outside the build lock")
            finally:
                release.write_text("release\n", encoding="utf-8")
                holder.communicate(timeout=5)
            stdout, stderr = builder.communicate(timeout=10)
            self.assertEqual(0, builder.returncode, stderr or stdout)
            self.assertTrue(analysis_started.exists())

    def test_build_cli_reports_lock_timeout_as_structured_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            holder, database, _, release = self.start_holder(
                root, shared=False, kind="build",
            )
            project = self.create_project(root)
            environment = os.environ.copy()
            environment["ADWORKFLO_GRAPH_LOCK_TIMEOUT_SECONDS"] = "0.1"
            try:
                completed = subprocess.run([
                    PYTHON,
                    str(BUILD_SCRIPT),
                    "--project",
                    str(project),
                    "--out",
                    str(database),
                    "--no-typescript",
                ], text=True, encoding="utf-8", capture_output=True, timeout=5,
                    env=environment)
            finally:
                release.write_text("release\n", encoding="utf-8")
                holder.communicate(timeout=5)

            self.assertEqual(3, completed.returncode, completed.stdout + completed.stderr)
            self.assert_no_traceback(completed.stdout, completed.stderr)
            payload = json.loads(completed.stderr)
            self.assertEqual("graph-lock-timeout", payload["code"])
            self.assertEqual("build", payload["kind"])
            self.assertTrue(payload["retryable"])

    def test_query_cli_reports_lock_timeout_as_structured_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.create_project(root)
            database = root / "l2.sqlite"
            self.run_cli_build(project, database)
            holder, _, _, release = self.start_holder(
                root, shared=False, kind="publish",
            )
            environment = os.environ.copy()
            environment["ADWORKFLO_GRAPH_LOCK_TIMEOUT_SECONDS"] = "0.1"
            try:
                completed = subprocess.run([
                    PYTHON,
                    str(QUERY_SCRIPT),
                    "--project",
                    str(project),
                    "--level",
                    "l2",
                    "--database",
                    str(database),
                    "find-definition",
                    "--symbol",
                    "app.entry",
                ], text=True, encoding="utf-8", capture_output=True, timeout=5,
                    env=environment)
            finally:
                release.write_text("release\n", encoding="utf-8")
                holder.communicate(timeout=5)

            self.assertEqual(3, completed.returncode, completed.stdout + completed.stderr)
            self.assert_no_traceback(completed.stdout, completed.stderr)
            payload = json.loads(completed.stderr)
            self.assertEqual("graph-lock-timeout", payload["code"])
            self.assertEqual("publish", payload["kind"])
            self.assertEqual("shared", payload["mode"])
            self.assertTrue(payload["retryable"])

    def test_source_change_after_analysis_retries_before_publish(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.create_project(root, value=1)
            database = root / "l2.sqlite"
            analysis_complete = root / "analysis.complete"
            release = root / "analysis.release"
            builder = subprocess.Popen([
                PYTHON, str(WORKER), "build-pause-after-analysis", "--database", str(database),
                "--project", str(project), "--ready", str(analysis_complete), "--release", str(release),
            ], text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.wait_for_file(analysis_complete, builder)
            (project / "app.py").write_text("def entry():\n    return 2\n", encoding="utf-8")
            release.write_text("release\n", encoding="utf-8")
            stdout, stderr = builder.communicate(timeout=15)
            self.assertEqual(0, builder.returncode, stderr or stdout)
            result = json.loads(stdout)
            self.assertEqual(2, result["analysis_calls"])
            with closing(sqlite3.connect(database)) as connection:
                indexed_hash = connection.execute("SELECT sha256 FROM files WHERE path='app.py'").fetchone()[0]
            current_text = (project / "app.py").read_text(encoding="utf-8")
            self.assertEqual(hashlib.sha256(current_text.encode("utf-8")).hexdigest(), indexed_hash)


class L2ConcurrentBuildAndQueryTests(L2SubprocessHelpers, unittest.TestCase):
    @staticmethod
    def write_query_project(root: Path, value: int = 0) -> Path:
        project = root / "project"
        project.mkdir(exist_ok=True)
        (project / "app.py").write_text(
            "def leaf():\n"
            f"    return {value}\n\n"
            "def entry():\n"
            "    return leaf()\n",
            encoding="utf-8",
        )
        return project

    def test_four_cli_builders_converge_from_missing_and_corrupt_active_graphs(self) -> None:
        for initial_state in ("missing", "corrupt"):
            with self.subTest(initial_state=initial_state), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                project = self.write_query_project(root)
                database = root / "graph" / "l2.sqlite"
                database.parent.mkdir()
                if initial_state == "corrupt":
                    database.write_bytes(b"not-a-sqlite-database")

                release = root / "builders.release"
                processes: list[subprocess.Popen[str]] = []
                ready_files: list[Path] = []
                try:
                    for index in range(4):
                        ready = root / f"builder-{index}.ready"
                        ready_files.append(ready)
                        processes.append(subprocess.Popen([
                            PYTHON, str(WORKER), "cli-build", "--database", str(database),
                            "--project", str(project), "--ready", str(ready), "--release", str(release),
                        ], text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE))
                    for ready, process in zip(ready_files, processes):
                        self.wait_for_file(ready, process)
                    release.write_text("release\n", encoding="utf-8")
                    outputs = [process.communicate(timeout=45) for process in processes]
                finally:
                    self.terminate_processes(processes)

                revisions = set()
                for process, (stdout, stderr) in zip(processes, outputs):
                    self.assert_no_traceback(stdout, stderr)
                    self.assertEqual(0, process.returncode, stdout + stderr)
                    self.assertEqual("", stderr)
                    revisions.add(json.loads(stdout)["revision"])
                self.assertEqual(1, len(revisions))

                revision = revisions.pop()
                with closing(sqlite3.connect(database)) as connection:
                    self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
                    self.assertEqual(
                        revision,
                        connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0],
                    )
                snapshot = database.parent / "snapshots" / f"{revision}.sqlite"
                with closing(sqlite3.connect(snapshot)) as connection:
                    self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
                    self.assertEqual(
                        revision,
                        connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0],
                    )
                self.assertEqual([], list(database.parent.glob("*.candidate.tmp")))

    def test_concurrent_publishers_keep_snapshot_revisions_consistent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.write_query_project(root, value=10)
            database = root / "graph" / "l2.sqlite"
            from l2_codegraph.database import build_candidate_database
            from l2_codegraph.python_provider import analyze_project

            candidate_a, revision_a = build_candidate_database(
                project, database, [analyze_project(project)],
            )
            self.write_query_project(root, value=20)
            candidate_b, revision_b = build_candidate_database(
                project, database, [analyze_project(project)],
            )
            self.assertNotEqual(revision_a, revision_b)
            release = root / "publishers.release"
            publishers: list[subprocess.Popen[str]] = []
            try:
                for index, (candidate, revision) in enumerate((
                    (candidate_a, revision_a), (candidate_b, revision_b),
                )):
                    ready = root / f"publisher-{index}.ready"
                    process = subprocess.Popen([
                        PYTHON,
                        str(WORKER),
                        "publish-candidate",
                        "--database",
                        str(database),
                        "--candidate",
                        str(candidate),
                        "--revision",
                        revision,
                        "--ready",
                        str(ready),
                        "--release",
                        str(release),
                    ], text=True, encoding="utf-8", stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE)
                    publishers.append(process)
                    self.wait_for_file(ready, process)
                release.write_text("release\n", encoding="utf-8")
                outputs = [process.communicate(timeout=15) for process in publishers]
            finally:
                self.terminate_processes(publishers)

            for process, (stdout, stderr) in zip(publishers, outputs):
                self.assert_no_traceback(stdout, stderr)
                self.assertEqual(0, process.returncode, stdout + stderr)
            for revision in (revision_a, revision_b):
                snapshot = database.parent / "snapshots" / f"{revision}.sqlite"
                with closing(sqlite3.connect(snapshot)) as connection:
                    self.assertEqual(
                        "ok", connection.execute("PRAGMA integrity_check").fetchone()[0],
                    )
                    self.assertEqual(
                        revision,
                        connection.execute(
                            "SELECT value FROM metadata WHERE key='revision'",
                        ).fetchone()[0],
                    )
            self.assertIn(
                self.database_revision(database), {revision_a, revision_b},
            )

    def test_continuous_source_churn_returns_structured_failure_and_preserves_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.write_query_project(root, value=0)
            database = root / "graph" / "l2.sqlite"
            baseline = self.run_cli_build(project, database)
            baseline_revision = baseline["revision"]
            with closing(sqlite3.connect(database)) as connection:
                baseline_hash = connection.execute("SELECT sha256 FROM files WHERE path='app.py'").fetchone()[0]

            self.write_query_project(root, value=1)
            sync_dir = root / "churn-sync"
            builder = subprocess.Popen([
                PYTHON, str(WORKER), "build-continuous-churn", "--database", str(database),
                "--project", str(project), "--sync-dir", str(sync_dir), "--iterations", "2",
            ], text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                for attempt, value in ((1, 2), (2, 3)):
                    ready = sync_dir / f"{attempt:02d}.analysis-ready"
                    self.wait_for_file(ready, builder, timeout=15)
                    self.write_query_project(root, value=value)
                    (sync_dir / f"{attempt:02d}.analysis-release").write_text("release\n", encoding="utf-8")
                stdout, stderr = builder.communicate(timeout=30)
            finally:
                self.terminate_processes([builder])

            self.assert_no_traceback(stdout, stderr)
            self.assertEqual(4, builder.returncode, stdout + stderr)
            self.assertEqual("", stdout)
            error = json.loads(stderr)
            self.assertEqual("source-changed-during-build", error["code"])
            self.assertEqual(2, error["attempts"])
            self.assertEqual(2, error["analysis_calls"])
            self.assertTrue(error["retryable"])
            self.assertEqual(baseline_revision, self.database_revision(database))
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
                self.assertEqual(
                    baseline_hash,
                    connection.execute("SELECT sha256 FROM files WHERE path='app.py'").fetchone()[0],
                )
            current_hash = hashlib.sha256((project / "app.py").read_bytes()).hexdigest()
            self.assertNotEqual(current_hash, baseline_hash)
            self.assertEqual(
                [f"{baseline_revision}.sqlite"],
                sorted(path.name for path in (database.parent / "snapshots").glob("*.sqlite")),
            )
            self.assertEqual([], list(database.parent.glob("*.candidate.tmp")))

    def test_query_loop_and_rebuild_loop_never_mix_revisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.write_query_project(root, value=0)
            database = root / "graph" / "l2.sqlite"
            baseline_revision = self.run_cli_build(project, database)["revision"]
            sync_dir = root / "query-rebuild-sync"
            iterations = 4
            reader = subprocess.Popen([
                PYTHON, str(WORKER), "query-loop", "--database", str(database),
                "--sync-dir", str(sync_dir), "--iterations", str(iterations),
            ], text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            writer = subprocess.Popen([
                PYTHON, str(WORKER), "rebuild-loop", "--database", str(database),
                "--project", str(project), "--sync-dir", str(sync_dir), "--iterations", str(iterations),
            ], text=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                reader_stdout, reader_stderr = reader.communicate(timeout=60)
                writer_stdout, writer_stderr = writer.communicate(timeout=15)
            finally:
                self.terminate_processes([reader, writer])

            for process, stdout, stderr in (
                (reader, reader_stdout, reader_stderr),
                (writer, writer_stdout, writer_stderr),
            ):
                self.assert_no_traceback(stdout, stderr)
                self.assertEqual(0, process.returncode, stdout + stderr)
                self.assertEqual("", stderr)

            records = json.loads(reader_stdout)["records"]
            writer_revisions = json.loads(writer_stdout)["revisions"]
            self.assertEqual(iterations, len(records))
            self.assertEqual(iterations, len(writer_revisions))
            self.assertEqual(iterations, len(set(writer_revisions)))
            self.assertEqual(
                [baseline_revision, *writer_revisions[:-1]],
                [record["pinned_revision"] for record in records],
            )

            for iteration, record in enumerate(records):
                revision = record["pinned_revision"]
                snapshot = database.parent / "snapshots" / f"{revision}.sqlite"
                with closing(sqlite3.connect(snapshot)) as connection:
                    self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
                    self.assertEqual(
                        revision,
                        connection.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0],
                    )
                    expected_hash = connection.execute(
                        "SELECT sha256 FROM files WHERE path='app.py'",
                    ).fetchone()[0]
                self.assertEqual(expected_hash, record["resolved_hash"])
                self.assertEqual(revision, record["result_revision"])
                publish_attempt = json.loads(
                    (sync_dir / f"{iteration:02d}.publish-attempt").read_text(encoding="utf-8"),
                )
                self.assertTrue(
                    publish_attempt["reader_blocked_publication"],
                    f"{record['operation']} released its graph lease before completing",
                )
                if record["operation"] == "slice":
                    self.assertEqual("ready", record["result_status"])
                    self.assertEqual({"app.py": expected_hash}, record["source_hashes"])
                else:
                    self.assertEqual("impact", record["operation"])
                    self.assertEqual("ok", record["result_status"])
                    self.assertEqual(expected_hash, record["target"]["value"]["sha256"])
                    self.assertEqual(["app.py"], record["predicted_files"])

            self.assertEqual(writer_revisions[-1], self.database_revision(database))
            self.assertEqual(
                iterations + 1,
                len(list((database.parent / "snapshots").glob("*.sqlite"))),
            )
            self.assertEqual([], list(database.parent.glob("*.candidate.tmp")))


if __name__ == "__main__":
    unittest.main()
