"""v0.219 — three more hooks: PreToolUse cache-rm, PostToolUse lint, PreCompact externalize.

Extends v0.218 hook coverage with high-leverage events from the
official-spec-alignment plan E section.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parent.parent
_HOOKS_DIR = _REPO / ".claude" / "hooks"
_SETTINGS = _REPO / ".claude" / "settings.json"


def _run_hook(name: str, payload: dict, cache: Path | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if cache is not None:
        env["COSCIENTIST_CACHE_DIR"] = str(cache)
    env["PATH"] = os.environ.get("PATH", "/usr/bin:/bin")
    return subprocess.run(
        [str(_HOOKS_DIR / name)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


class NewHooksRegisteredTests(TestCase):
    def test_pretooluse_bash_hook_declared(self):
        d = json.loads(_SETTINGS.read_text())
        h = d["hooks"].get("PreToolUse", [])
        bash = [m for m in h if m.get("matcher") == "Bash"]
        self.assertTrue(bash, "expected PreToolUse matcher='Bash' hook")

    def test_posttooluse_write_edit_hook_declared(self):
        d = json.loads(_SETTINGS.read_text())
        h = d["hooks"].get("PostToolUse", [])
        we = [m for m in h if m.get("matcher") == "Write|Edit"]
        self.assertTrue(we, "expected PostToolUse matcher='Write|Edit' hook")

    def test_precompact_hook_declared(self):
        d = json.loads(_SETTINGS.read_text())
        self.assertIn("PreCompact", d["hooks"])

    def test_new_hook_scripts_executable(self):
        for name in (
            "block-cache-rm.sh",
            "lint-touched.sh",
            "externalize-active-state.sh",
        ):
            p = _HOOKS_DIR / name
            self.assertTrue(p.exists(), f"missing {p}")
            self.assertTrue(
                bool(p.stat().st_mode & stat.S_IXUSR),
                f"{name} not executable",
            )


class BlockCacheRmTests(TestCase):
    def test_blocks_rm_rf_against_cache(self):
        r = _run_hook("block-cache-rm.sh", {
            "tool_input": {"command": "rm -rf ~/.cache/coscientist/runs/*"},
        })
        self.assertEqual(r.returncode, 0)
        out = json.loads(r.stdout)
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_blocks_with_dollar_home(self):
        r = _run_hook("block-cache-rm.sh", {
            "tool_input": {"command": "rm -rf $HOME/.cache/coscientist"},
        })
        out = json.loads(r.stdout)
        self.assertEqual(
            out["hookSpecificOutput"]["permissionDecision"], "deny",
        )

    def test_silent_on_safe_command(self):
        r = _run_hook("block-cache-rm.sh", {
            "tool_input": {"command": "ls -la"},
        })
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_silent_on_rm_outside_cache(self):
        r = _run_hook("block-cache-rm.sh", {
            "tool_input": {"command": "rm -rf /tmp/scratch"},
        })
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), "")

    def test_handles_empty_input(self):
        r = _run_hook("block-cache-rm.sh", {"tool_input": {}})
        self.assertEqual(r.returncode, 0)


class LintTouchedTests(TestCase):
    def test_silent_on_valid_python(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tf:
            tf.write(b"x = 1\n")
            path = tf.name
        try:
            r = _run_hook("lint-touched.sh", {
                "tool_input": {"file_path": path},
            })
            self.assertEqual(r.returncode, 0)
            self.assertEqual(r.stderr.strip(), "")
        finally:
            os.unlink(path)

    def test_warns_on_python_syntax_error(self):
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tf:
            tf.write(b"def broken(:\n")
            path = tf.name
        try:
            r = _run_hook("lint-touched.sh", {
                "tool_input": {"file_path": path},
            })
            # Exit 0 (don't block); stderr has warning.
            self.assertEqual(r.returncode, 0)
            self.assertIn("syntax error", r.stderr.lower())
        finally:
            os.unlink(path)

    def test_warns_on_invalid_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tf.write(b"{not valid")
            path = tf.name
        try:
            r = _run_hook("lint-touched.sh", {
                "tool_input": {"file_path": path},
            })
            self.assertEqual(r.returncode, 0)
            self.assertIn("invalid json", r.stderr.lower())
        finally:
            os.unlink(path)

    def test_silent_on_missing_file(self):
        r = _run_hook("lint-touched.sh", {
            "tool_input": {"file_path": "/nonexistent/path.py"},
        })
        self.assertEqual(r.returncode, 0)


class PreCompactExternalizeTests(TestCase):
    def test_writes_state_file_when_active_run_exists(self):
        with isolated_cache() as cache:
            # Plant a minimal run DB with one pending phase.
            import sqlite3
            runs_dir = cache / "runs"
            runs_dir.mkdir(parents=True)
            db_path = runs_dir / "run-test01.db"
            schema_sql = (_REPO / "lib" / "sqlite_schema.sql").read_text()
            con = sqlite3.connect(db_path)
            with con:
                con.executescript(schema_sql)
                con.execute(
                    "INSERT INTO runs (run_id, question, started_at) "
                    "VALUES (?, ?, ?)",
                    ("test01", "test question", "2026-01-01T00:00:00+00:00"),
                )
                # All 10 phases pending.
                phases = ["scout", "cartographer", "chronicler", "surveyor",
                          "synthesist", "architect", "inquisitor", "weaver",
                          "visionary", "steward"]
                for i, name in enumerate(phases):
                    con.execute(
                        "INSERT INTO phases (run_id, name, ordinal) "
                        "VALUES (?, ?, ?)",
                        ("test01", name, i),
                    )
            con.close()

            r = _run_hook(
                "externalize-active-state.sh",
                {"hook_event_name": "PreCompact"},
                cache=cache,
            )
            self.assertEqual(r.returncode, 0, r.stderr)

            out_file = runs_dir / "run-test01" / "precompact-state.json"
            self.assertTrue(
                out_file.exists(),
                f"precompact-state.json not written at {out_file}",
            )
            data = json.loads(out_file.read_text())
            self.assertEqual(data["run_id"], "test01")
            self.assertIn("scout", data["pending_phases"])
            self.assertIn("restore_hint", data)

    def test_silent_on_empty_cache(self):
        with isolated_cache() as cache:
            r = _run_hook(
                "externalize-active-state.sh",
                {"hook_event_name": "PreCompact"},
                cache=cache,
            )
            self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        NewHooksRegisteredTests,
        BlockCacheRmTests,
        LintTouchedTests,
        PreCompactExternalizeTests,
    ))
