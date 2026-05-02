"""v0.214 — deep-research close-out hook.

Verifies the closeout script:
  1. Closes stale spans (status='running' → 'ok').
  2. Records a notes row with author='closeout'.
  3. Skips persona scoring when no rubric output file exists
     (does not crash on missing artifacts).

Uses isolated_cache so we don't touch the real run DB.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parent.parent
_CLOSEOUT = _REPO / ".claude" / "skills" / "deep-research" / "scripts" / "closeout.py"
_INIT_SCHEMA = _REPO / "lib" / "sqlite_schema.sql"


class CloseoutTests(TestCase):
    def _make_run_db(self, cache: Path, run_id: str = "test001") -> Path:
        """Spin up a minimal run DB matching real schema, plant fixtures."""
        runs_dir = cache / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        db_path = runs_dir / f"run-{run_id}.db"
        con = sqlite3.connect(db_path)
        with con:
            con.executescript(_INIT_SCHEMA.read_text())
            # Seed run + trace + 2 stale spans + 1 closed span
            con.execute(
                "INSERT INTO runs (run_id, question, started_at) "
                "VALUES (?, ?, ?)",
                (run_id, "test question", "2026-01-01T00:00:00+00:00"),
            )
            con.execute(
                "INSERT INTO traces (trace_id, run_id, started_at, status) "
                "VALUES (?, ?, ?, ?)",
                (f"t-{run_id}", run_id, "2026-01-01T00:00:00+00:00", "ok"),
            )
            for i, status in enumerate(["running", "running", "ok"]):
                con.execute(
                    "INSERT INTO spans "
                    "(span_id, trace_id, kind, name, started_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        f"span-{i}",
                        f"t-{run_id}",
                        "phase",
                        f"phase-{i}",
                        "2026-01-01T00:00:00+00:00",
                        status,
                    ),
                )
        con.close()
        return db_path

    def _run(self, cache: Path, run_id: str, *extra_args: str) -> dict:
        result = subprocess.run(
            [
                sys.executable,
                str(_CLOSEOUT),
                "--run-id",
                run_id,
                *extra_args,
            ],
            capture_output=True,
            text=True,
            env={"COSCIENTIST_CACHE_DIR": str(cache), "PATH": "/usr/bin:/bin"},
        )
        return {
            "rc": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    def test_dry_run_reports_stale_spans_without_writing(self):
        with isolated_cache() as cache:
            run_id = "dry01"
            db = self._make_run_db(cache, run_id)
            r = self._run(cache, run_id, "--dry-run")
            self.assertEqual(r["rc"], 0, r["stderr"])
            payload = json.loads(r["stdout"])
            self.assertEqual(payload["dry_run"], True)
            self.assertEqual(payload["stale_spans"], 2)
            # Confirm no writes
            con = sqlite3.connect(db)
            still_running = con.execute(
                "SELECT COUNT(*) FROM spans WHERE status='running'"
            ).fetchone()[0]
            con.close()
            self.assertEqual(still_running, 2)

    def test_live_closes_spans_and_writes_note(self):
        with isolated_cache() as cache:
            run_id = "live01"
            db = self._make_run_db(cache, run_id)
            r = self._run(cache, run_id)
            self.assertEqual(r["rc"], 0, r["stderr"])
            payload = json.loads(r["stdout"])
            self.assertEqual(payload["spans_closed"], 2)

            con = sqlite3.connect(db)
            stale = con.execute(
                "SELECT COUNT(*) FROM spans WHERE status='running'"
            ).fetchone()[0]
            self.assertEqual(stale, 0)

            note_row = con.execute(
                "SELECT author, text FROM notes WHERE run_id=?",
                (run_id,),
            ).fetchone()
            con.close()
            self.assertIsNotNone(note_row)
            self.assertEqual(note_row[0], "closeout")
            note_body = json.loads(note_row[1])
            self.assertEqual(note_body["kind"], "closeout")
            self.assertEqual(note_body["spans_closed"], 2)

    def test_idempotent_second_call_is_safe(self):
        with isolated_cache() as cache:
            run_id = "idem01"
            self._make_run_db(cache, run_id)
            r1 = self._run(cache, run_id)
            self.assertEqual(r1["rc"], 0)
            r2 = self._run(cache, run_id)
            self.assertEqual(r2["rc"], 0)
            payload2 = json.loads(r2["stdout"])
            # Second run finds zero stale (first call closed them all)
            self.assertEqual(payload2["spans_closed"], 0)


if __name__ == "__main__":
    raise SystemExit(run_tests(CloseoutTests))
