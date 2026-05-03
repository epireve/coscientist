"""v0.225 — within-phase checkpointing for partial-phase resume.

Verifies migration v19 lands the table, the lib.phase_checkpoint
helpers work, and `db.py record-phase --retry` clears matching
checkpoints so the retry starts from unit 0.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parent.parent
_DB_PY = _REPO / ".claude" / "skills" / "deep-research" / "scripts" / "db.py"


def _run(args: list[str], cache: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["COSCIENTIST_CACHE_DIR"] = str(cache)
    env["PYTHONPATH"] = str(_REPO)
    return subprocess.run(
        [sys.executable, str(_DB_PY), *args],
        capture_output=True, text=True, env=env, timeout=30,
    )


class V19MigrationTests(TestCase):
    def test_phase_checkpoints_table_present(self):
        with isolated_cache() as cache:
            r = _run(["init", "--question", "Q?"], cache)
            run_id = r.stdout.strip()
            db = cache / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db)
            try:
                row = con.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='phase_checkpoints'"
                ).fetchone()
            finally:
                con.close()
            self.assertIsNotNone(row)

    def test_v19_recorded_in_schema_versions(self):
        with isolated_cache() as cache:
            r = _run(["init", "--question", "Q?"], cache)
            run_id = r.stdout.strip()
            db = cache / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db)
            try:
                versions = {row[0] for row in con.execute(
                    "SELECT version FROM schema_versions"
                )}
            finally:
                con.close()
            self.assertIn(19, versions)


class CheckpointHelperTests(TestCase):
    def _new_run(self, cache: Path) -> str:
        return _run(["init", "--question", "Q?"], cache).stdout.strip()

    def test_record_and_is_done(self):
        from lib.phase_checkpoint import is_done, record
        with isolated_cache() as cache:
            run_id = self._new_run(cache)
            self.assertFalse(
                is_done(run_id, "scout", "paper", "p1"),
            )
            record(run_id, "scout", "paper", "p1", "done")
            self.assertTrue(
                is_done(run_id, "scout", "paper", "p1"),
            )

    def test_idempotent_overwrite(self):
        from lib.phase_checkpoint import is_done, record
        with isolated_cache() as cache:
            run_id = self._new_run(cache)
            record(run_id, "scout", "paper", "p1", "failed")
            self.assertFalse(is_done(run_id, "scout", "paper", "p1"))
            # Re-record as done — should overwrite.
            record(run_id, "scout", "paper", "p1", "done")
            self.assertTrue(is_done(run_id, "scout", "paper", "p1"))

    def test_done_units_filters_by_state(self):
        from lib.phase_checkpoint import done_units, record
        with isolated_cache() as cache:
            run_id = self._new_run(cache)
            record(run_id, "scout", "paper", "p1", "done")
            record(run_id, "scout", "paper", "p2", "failed")
            record(run_id, "scout", "paper", "p3", "done")
            self.assertEqual(
                set(done_units(run_id, "scout", "paper")),
                {"p1", "p3"},
            )

    def test_done_units_filters_by_kind(self):
        from lib.phase_checkpoint import done_units, record
        with isolated_cache() as cache:
            run_id = self._new_run(cache)
            record(run_id, "scout", "paper", "p1", "done")
            record(run_id, "scout", "query", "q1", "done")
            self.assertEqual(
                done_units(run_id, "scout", "paper"), ["p1"],
            )
            self.assertEqual(
                done_units(run_id, "scout", "query"), ["q1"],
            )

    def test_progress_counts(self):
        from lib.phase_checkpoint import progress, record
        with isolated_cache() as cache:
            run_id = self._new_run(cache)
            record(run_id, "scout", "paper", "p1", "done")
            record(run_id, "scout", "paper", "p2", "done")
            record(run_id, "scout", "paper", "p3", "failed")
            record(run_id, "scout", "paper", "p4", "skipped")
            p = progress(run_id, "scout")
            self.assertEqual(p["done"], 2)
            self.assertEqual(p["failed"], 1)
            self.assertEqual(p["skipped"], 1)
            self.assertEqual(p["total"], 4)

    def test_clear_phase(self):
        from lib.phase_checkpoint import (
            clear_phase, is_done, record,
        )
        with isolated_cache() as cache:
            run_id = self._new_run(cache)
            record(run_id, "scout", "paper", "p1", "done")
            record(run_id, "cartographer", "paper", "p2", "done")
            n = clear_phase(run_id, "scout")
            self.assertEqual(n, 1)
            self.assertFalse(
                is_done(run_id, "scout", "paper", "p1"),
            )
            # cartographer untouched.
            self.assertTrue(
                is_done(run_id, "cartographer", "paper", "p2"),
            )

    def test_payload_round_trip(self):
        from lib.phase_checkpoint import list_checkpoints, record
        with isolated_cache() as cache:
            run_id = self._new_run(cache)
            record(
                run_id, "scout", "paper", "p1", "failed",
                payload={"http_status": 503, "attempt": 3},
            )
            rows = list_checkpoints(run_id, "scout")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["payload"]["http_status"], 503)


class RetryClearsCheckpointsTests(TestCase):
    def test_retry_clears_phase_checkpoints(self):
        from lib.phase_checkpoint import done_units, record
        with isolated_cache() as cache:
            r = _run(["init", "--question", "Q?"], cache)
            run_id = r.stdout.strip()
            record(run_id, "scout", "paper", "p1", "done")
            record(run_id, "scout", "paper", "p2", "done")
            self.assertEqual(
                set(done_units(run_id, "scout", "paper")),
                {"p1", "p2"},
            )
            r = _run([
                "record-phase", "--run-id", run_id,
                "--phase", "scout", "--retry",
            ], cache)
            self.assertEqual(r.returncode, 0, r.stderr)
            # Checkpoints gone.
            self.assertEqual(done_units(run_id, "scout", "paper"), [])


class ResumeSurfacesProgressTests(TestCase):
    def test_resume_includes_checkpoint_progress(self):
        from lib.phase_checkpoint import record
        with isolated_cache() as cache:
            r = _run(["init", "--question", "Q?"], cache)
            run_id = r.stdout.strip()
            record(run_id, "scout", "paper", "p1", "done")
            record(run_id, "scout", "paper", "p2", "failed")
            r = _run(["resume", "--run-id", run_id], cache)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            cp = payload["checkpoint_progress"]
            self.assertEqual(cp["done"], 1)
            self.assertEqual(cp["failed"], 1)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        V19MigrationTests,
        CheckpointHelperTests,
        RetryClearsCheckpointsTests,
        ResumeSurfacesProgressTests,
    ))
