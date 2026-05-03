"""v0.231 — bin/coscientist dispatcher smoke tests.

Verifies the dispatcher exists, is executable, and routes a few
common subcommands without errors. Each test runs the script in
a subprocess with isolated cache.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parents[1]
_BIN = _REPO / "bin" / "coscientist"


def _run(args: list[str], cache: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["COSCIENTIST_CACHE_DIR"] = str(cache)
    env["PYTHONPATH"] = str(_REPO)
    env["PATH"] = os.environ.get("PATH", "/usr/bin:/bin")
    return subprocess.run(
        [str(_BIN), *args],
        capture_output=True, text=True, env=env, timeout=60,
        cwd=str(_REPO),
    )


class DispatcherShapeTests(TestCase):
    def test_exists_and_executable(self):
        self.assertTrue(_BIN.exists(), f"missing {_BIN}")
        mode = _BIN.stat().st_mode
        self.assertTrue(
            bool(mode & stat.S_IXUSR),
            f"{_BIN} not executable",
        )

    def test_help_prints_command_list(self):
        with isolated_cache() as cache:
            r = _run(["help"], cache)
        self.assertEqual(r.returncode, 0, r.stderr)
        for cmd in ("health", "status", "trace", "quality",
                     "run-audit", "db", "plugin-checksums",
                     "version", "help"):
            self.assertIn(cmd, r.stdout)

    def test_no_args_prints_help(self):
        with isolated_cache() as cache:
            r = _run([], cache)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Usage", r.stdout)

    def test_unknown_command_exits_nonzero(self):
        with isolated_cache() as cache:
            r = _run(["definitely-not-real"], cache)
        self.assertTrue(
            r.returncode != 0,
            f"unknown command should exit nonzero, got {r.returncode}",
        )
        self.assertIn("unknown command", r.stderr)


class DispatcherRoutingTests(TestCase):
    def test_version_prints_v0_dot(self):
        with isolated_cache() as cache:
            r = _run(["version"], cache)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(
            r.stdout.strip().startswith("v0."),
            f"unexpected version output: {r.stdout!r}",
        )

    def test_health_runs_clean_on_empty_cache(self):
        # health surfaces zero alerts on a fresh cache; exit 0.
        with isolated_cache() as cache:
            r = _run(["health", "--format", "json"], cache)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("n_runs", r.stdout)

    def test_status_runs_clean_on_empty_cache(self):
        with isolated_cache() as cache:
            r = _run(["status", "--format", "json"], cache)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_db_subcommand_passthrough(self):
        # db.py should accept `init` and emit a run_id.
        with isolated_cache() as cache:
            r = _run(["db", "init", "--question", "Q?"], cache)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(
            r.stdout.strip(), "expected run_id from db init",
        )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        DispatcherShapeTests,
        DispatcherRoutingTests,
    ))
