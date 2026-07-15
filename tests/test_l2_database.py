from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "adworkflo" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from l2_codegraph.database import (  # noqa: E402
    CandidateIntegrityError, GraphPublicationError, SourceChangedDuringBuild,
    build_candidate_database, build_database, connect, export_snapshot, metadata,
    publish_candidate,
)
from l2_codegraph.python_provider import analyze_project  # noqa: E402


class L2DatabaseTests(unittest.TestCase):
    def test_direct_build_rejects_stale_provider_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text("def target():\n    return 1\n", encoding="utf-8")
            out = project / ".codegraph" / "l2.sqlite"
            last_good = build_database(project, out, [analyze_project(project)])
            stale_result = analyze_project(project)
            source.write_text("def target():\n    return 2\n", encoding="utf-8")

            with self.assertRaisesRegex(
                SourceChangedDuringBuild, "source-changed-during-build",
            ):
                build_database(project, out, [stale_result])

            with connect(out, readonly=True) as connection:
                self.assertEqual(last_good, metadata(connection)["revision"])

    def test_direct_build_rejects_files_added_after_provider_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "def target():\n    return 1\n", encoding="utf-8",
            )
            out = project / ".codegraph" / "l2.sqlite"
            last_good = build_database(project, out, [analyze_project(project)])
            stale_result = analyze_project(project)
            (project / "added.py").write_text(
                "def added():\n    return 2\n", encoding="utf-8",
            )

            with self.assertRaises(SourceChangedDuringBuild):
                build_database(project, out, [stale_result])

            with connect(out, readonly=True) as connection:
                self.assertEqual(last_good, metadata(connection)["revision"])

    def test_direct_build_uses_project_config_when_not_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "src").mkdir()
            (project / "vendor").mkdir()
            (project / "src" / "app.py").write_text(
                "def entry():\n    return 1\n", encoding="utf-8",
            )
            (project / "vendor" / "ignored.py").write_text(
                "def ignored():\n    return 2\n", encoding="utf-8",
            )
            graph_dir = project / ".codegraph"
            graph_dir.mkdir()
            (graph_dir / "config.json").write_text(json.dumps({
                "include": ["src"],
                "exclude": ["vendor"],
                "languages": ["python"],
            }), encoding="utf-8")
            out = graph_dir / "l2.sqlite"

            revision = build_database(
                project, out, [analyze_project(project)],
            )

            with connect(out, readonly=True) as connection:
                self.assertEqual(revision, metadata(connection)["revision"])
                self.assertEqual(
                    ["src/app.py"],
                    [
                        row["path"]
                        for row in connection.execute(
                            "SELECT path FROM files ORDER BY path",
                        )
                    ],
                )
                self.assertEqual(
                    ["src"], metadata(connection)["config"]["include"],
                )

    def test_build_is_revisioned_stable_and_queryable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def target():\n    return 1\n\ndef entry():\n    return target()\n", encoding="utf-8")
            out = project / ".codegraph" / "l2.sqlite"
            result = analyze_project(project)
            first = build_database(project, out, [result])
            second = build_database(project, out, [analyze_project(project)])
            self.assertEqual(first, second)
            with connect(out, readonly=True) as connection:
                self.assertEqual(first, metadata(connection)["revision"])
                snapshot = export_snapshot(connection)
                self.assertEqual(2, len(snapshot["symbols"]))
                self.assertEqual(1, sum(item["callee_symbol_id"] is not None for item in snapshot["calls"]))

    def test_failed_build_preserves_last_good_database(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text("def target():\n    return 1\n", encoding="utf-8")
            out = project / ".codegraph" / "l2.sqlite"
            revision = build_database(project, out, [analyze_project(project)])
            invalid = analyze_project(project)
            invalid["capabilities"] = []
            with self.assertRaisesRegex(ValueError, "missing L2 capabilities"):
                build_database(project, out, [invalid])
            with connect(out, readonly=True) as connection:
                self.assertEqual(revision, metadata(connection)["revision"])

    def test_snapshot_failure_does_not_publish_candidate_as_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text("def target():\n    return 1\n", encoding="utf-8")
            out = project / ".codegraph" / "l2.sqlite"
            last_good = build_database(project, out, [analyze_project(project)])
            source.write_text("def target():\n    return 200\n", encoding="utf-8")
            with patch("l2_codegraph.database.shutil.copyfile", side_effect=OSError("snapshot write failed")):
                with self.assertRaisesRegex(OSError, "snapshot write failed"):
                    build_database(project, out, [analyze_project(project)])
            with connect(out, readonly=True) as connection:
                self.assertEqual(last_good, metadata(connection)["revision"])

    def test_active_replace_failure_keeps_last_good_and_valid_new_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text("def target():\n    return 1\n", encoding="utf-8")
            out = project / ".codegraph" / "l2.sqlite"
            last_good = build_database(project, out, [analyze_project(project)])
            source.write_text("def target():\n    return 300\n", encoding="utf-8")
            candidate, revision = build_candidate_database(project, out, [analyze_project(project)])
            real_replace = os.replace

            def fail_active_replace(source_path: str | Path, target_path: str | Path) -> None:
                if Path(target_path).resolve() == out.resolve():
                    raise OSError("active replace failed")
                real_replace(source_path, target_path)

            try:
                with patch("l2_codegraph.database.os.replace", side_effect=fail_active_replace):
                    with self.assertRaisesRegex(GraphPublicationError, "active replace failed"):
                        publish_candidate(candidate, out, revision)
                with connect(out, readonly=True) as connection:
                    self.assertEqual(last_good, metadata(connection)["revision"])
                snapshot = out.parent / "snapshots" / f"{revision}.sqlite"
                with connect(snapshot, readonly=True) as connection:
                    self.assertEqual(revision, metadata(connection)["revision"])
                    self.assertEqual("ok", connection.execute("PRAGMA integrity_check").fetchone()[0])
            finally:
                candidate.unlink(missing_ok=True)

    def test_snapshot_replace_failure_keeps_last_good_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text("def target():\n    return 1\n", encoding="utf-8")
            out = project / ".codegraph" / "l2.sqlite"
            last_good = build_database(project, out, [analyze_project(project)])
            source.write_text("def target():\n    return 400\n", encoding="utf-8")
            candidate, revision = build_candidate_database(
                project, out, [analyze_project(project)],
            )
            snapshot = out.parent / "snapshots" / f"{revision}.sqlite"
            real_replace = os.replace

            def fail_snapshot_replace(
                source_path: str | Path, target_path: str | Path,
            ) -> None:
                if Path(target_path).resolve() == snapshot.resolve():
                    raise OSError("snapshot replace failed")
                real_replace(source_path, target_path)

            try:
                with patch(
                    "l2_codegraph.database.os.replace",
                    side_effect=fail_snapshot_replace,
                ):
                    with self.assertRaisesRegex(
                        GraphPublicationError, "snapshot replace failed",
                    ) as raised:
                        publish_candidate(candidate, out, revision)
                self.assertEqual("snapshot-replace", raised.exception.stage)
                with connect(out, readonly=True) as connection:
                    self.assertEqual(last_good, metadata(connection)["revision"])
                self.assertFalse(snapshot.exists())
            finally:
                candidate.unlink(missing_ok=True)

    def test_invalid_snapshot_metadata_is_replaced_on_rebuild(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "app.py").write_text(
                "def target():\n    return 1\n", encoding="utf-8",
            )
            out = project / ".codegraph" / "l2.sqlite"
            revision = build_database(project, out, [analyze_project(project)])
            snapshot = out.parent / "snapshots" / f"{revision}.sqlite"
            with closing(sqlite3.connect(snapshot)) as connection:
                connection.execute(
                    "UPDATE metadata SET value='{' WHERE key='providers'",
                )
                connection.commit()

            rebuilt = build_database(
                project, out, [analyze_project(project)],
            )

            self.assertEqual(revision, rebuilt)
            with connect(snapshot, readonly=True) as connection:
                self.assertEqual(revision, metadata(connection)["revision"])
                self.assertEqual(
                    "ok", connection.execute("PRAGMA integrity_check").fetchone()[0],
                )

    def test_active_validation_failure_rolls_back_last_good_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            source = project / "app.py"
            source.write_text("def target():\n    return 1\n", encoding="utf-8")
            out = project / ".codegraph" / "l2.sqlite"
            last_good = build_database(project, out, [analyze_project(project)])
            source.write_text("def target():\n    return 500\n", encoding="utf-8")
            candidate, revision = build_candidate_database(
                project, out, [analyze_project(project)],
            )

            from l2_codegraph import database as database_module
            real_validate = database_module.validate_database

            def fail_new_active_validation(
                path: Path, expected_revision: str, *, acquire_lease: bool = False,
            ) -> None:
                if path.resolve() == out.resolve() and expected_revision == revision:
                    raise CandidateIntegrityError("injected active validation failure")
                real_validate(
                    path, expected_revision, acquire_lease=acquire_lease,
                )

            try:
                with patch.object(
                    database_module,
                    "validate_database",
                    side_effect=fail_new_active_validation,
                ):
                    with self.assertRaisesRegex(
                        CandidateIntegrityError, "injected active validation failure",
                    ):
                        publish_candidate(candidate, out, revision)
                with connect(out, readonly=True) as connection:
                    self.assertEqual(last_good, metadata(connection)["revision"])
                    self.assertEqual(
                        "ok", connection.execute("PRAGMA integrity_check").fetchone()[0],
                    )
                snapshot = out.parent / "snapshots" / f"{revision}.sqlite"
                with connect(snapshot, readonly=True) as connection:
                    self.assertEqual(revision, metadata(connection)["revision"])
                self.assertEqual(
                    [], list(out.parent.glob("*.active-backup.tmp")),
                )
            finally:
                candidate.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
