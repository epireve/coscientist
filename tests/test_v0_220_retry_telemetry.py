"""v0.220 — phases retry telemetry (migration v18 + db.py --retry).

Adds 3 columns to phases: error_count, last_error_at, retry_attempt.
Verifies migration applies, --error bumps counters, --retry resets
state and increments retry_attempt.
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


class V18MigrationTests(TestCase):
    def test_phases_columns_present_after_init(self):
        with isolated_cache() as cache:
            r = _run(["init", "--question", "Q?"], cache)
            self.assertEqual(r.returncode, 0, r.stderr)
            run_id = r.stdout.strip()
            db_path = cache / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db_path)
            try:
                cols = {row[1] for row in con.execute(
                    "PRAGMA table_info(phases)"
                )}
            finally:
                con.close()
            self.assertIn("error_count", cols)
            self.assertIn("last_error_at", cols)
            self.assertIn("retry_attempt", cols)

    def test_v18_recorded_in_schema_versions(self):
        with isolated_cache() as cache:
            r = _run(["init", "--question", "Q?"], cache)
            run_id = r.stdout.strip()
            db_path = cache / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db_path)
            try:
                versions = {row[0] for row in con.execute(
                    "SELECT version FROM schema_versions"
                )}
            finally:
                con.close()
            self.assertIn(18, versions)


class ErrorBumpsTelemetryTests(TestCase):
    def test_error_bumps_count_and_timestamp(self):
        with isolated_cache() as cache:
            run_id = _run(["init", "--question", "Q?"], cache).stdout.strip()
            r = _run([
                "record-phase", "--run-id", run_id,
                "--phase", "scout", "--error", "boom",
            ], cache)
            self.assertEqual(r.returncode, 0, r.stderr)
            db_path = cache / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db_path)
            try:
                row = con.execute(
                    "SELECT error, error_count, last_error_at, retry_attempt "
                    "FROM phases WHERE run_id=? AND name='scout'",
                    (run_id,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "boom")
            self.assertEqual(row[1], 1)
            self.assertIsNotNone(row[2])
            self.assertEqual(row[3], 0)

    def test_two_errors_increment_count(self):
        with isolated_cache() as cache:
            run_id = _run(["init", "--question", "Q?"], cache).stdout.strip()
            for msg in ("e1", "e2", "e3"):
                _run([
                    "record-phase", "--run-id", run_id,
                    "--phase", "scout", "--error", msg,
                ], cache)
            db_path = cache / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db_path)
            try:
                row = con.execute(
                    "SELECT error, error_count FROM phases "
                    "WHERE run_id=? AND name='scout'", (run_id,),
                ).fetchone()
            finally:
                con.close()
            self.assertEqual(row[0], "e3")
            self.assertEqual(row[1], 3)


class RetryFlagTests(TestCase):
    def test_retry_clears_error_and_bumps_attempt(self):
        with isolated_cache() as cache:
            run_id = _run(["init", "--question", "Q?"], cache).stdout.strip()
            _run([
                "record-phase", "--run-id", run_id,
                "--phase", "scout", "--error", "transient",
            ], cache)
            r = _run([
                "record-phase", "--run-id", run_id,
                "--phase", "scout", "--retry",
            ], cache)
            self.assertEqual(r.returncode, 0, r.stderr)
            db_path = cache / "runs" / f"run-{run_id}.db"
            con = sqlite3.connect(db_path)
            try:
                row = con.execute(
                    "SELECT error, completed_at, retry_attempt, error_count "
                    "FROM phases WHERE run_id=? AND name='scout'",
                    (run_id,),
                ).fetchone()
            finally:
                con.close()
            self.assertIsNone(row[0])         # error cleared
            self.assertIsNone(row[1])         # completed_at cleared
            self.assertEqual(row[2], 1)       # retry_attempt bumped
            self.assertEqual(row[3], 1)       # error_count preserved (audit)


class ResumeSurfacesTelemetryTests(TestCase):
    def test_resume_emits_retry_columns(self):
        with isolated_cache() as cache:
            run_id = _run(["init", "--question", "Q?"], cache).stdout.strip()
            _run([
                "record-phase", "--run-id", run_id,
                "--phase", "scout", "--error", "x",
            ], cache)
            r = _run(["resume", "--run-id", run_id], cache)
            self.assertEqual(r.returncode, 0, r.stderr)
            payload = json.loads(r.stdout)
            scout = next(p for p in payload["phases"] if p["name"] == "scout")
            self.assertEqual(scout["error_count"], 1)
            self.assertEqual(scout["retry_attempt"], 0)
            self.assertIsNotNone(scout["last_error_at"])


if __name__ == "__main__":
    raise SystemExit(run_tests(
        V18MigrationTests,
        ErrorBumpsTelemetryTests,
        RetryFlagTests,
        ResumeSurfacesTelemetryTests,
    ))
