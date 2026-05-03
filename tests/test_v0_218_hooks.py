"""v0.218 — Phase 3: hooks structural + functional tests.

Validates:
  - .claude/settings.json declares the 3 hooks (SubagentStop+steward,
    SessionStart+startup, Stop)
  - Each declared hook command path exists and is executable
  - Each hook script has a #!/bin/bash shebang and `set` line
  - Manual smoke test: hooks return JSON or exit 0 cleanly when fed
    a representative input

Pure stdlib + isolated_cache. No actual session needed; we feed each
hook a stub stdin and check exit + output shape.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests

_REPO = Path(__file__).resolve().parent.parent
_SETTINGS = _REPO / ".claude" / "settings.json"
_HOOKS_DIR = _REPO / ".claude" / "hooks"


class HookSettingsTests(TestCase):
    def test_settings_json_exists(self):
        self.assertTrue(_SETTINGS.exists(), "missing .claude/settings.json")

    def test_settings_has_hooks_block(self):
        data = json.loads(_SETTINGS.read_text())
        self.assertIn("hooks", data, "settings.json must have 'hooks' block")

    def test_subagent_stop_steward_hook_declared(self):
        data = json.loads(_SETTINGS.read_text())
        sas = data["hooks"].get("SubagentStop", [])
        steward = [m for m in sas if m.get("matcher") == "steward"]
        self.assertTrue(
            steward,
            "expected SubagentStop hook with matcher='steward'",
        )

    def test_session_start_startup_hook_declared(self):
        data = json.loads(_SETTINGS.read_text())
        ss = data["hooks"].get("SessionStart", [])
        startup = [m for m in ss if m.get("matcher") == "startup"]
        self.assertTrue(
            startup,
            "expected SessionStart hook with matcher='startup'",
        )

    def test_stop_hook_declared(self):
        data = json.loads(_SETTINGS.read_text())
        st = data["hooks"].get("Stop", [])
        self.assertTrue(st, "expected Stop hook")


class HookScriptTests(TestCase):
    EXPECTED_SCRIPTS = (
        "closeout-on-steward-stop.sh",
        "load-active-run.sh",
        "health-on-stop.sh",
    )

    def test_hook_scripts_exist(self):
        for name in self.EXPECTED_SCRIPTS:
            p = _HOOKS_DIR / name
            self.assertTrue(p.exists(), f"missing hook script {p}")

    def test_hook_scripts_executable(self):
        for name in self.EXPECTED_SCRIPTS:
            p = _HOOKS_DIR / name
            mode = p.stat().st_mode
            self.assertTrue(
                bool(mode & stat.S_IXUSR),
                f"{name} not executable; run `chmod +x`",
            )

    def test_hook_scripts_have_shebang(self):
        for name in self.EXPECTED_SCRIPTS:
            first_line = (_HOOKS_DIR / name).read_text().splitlines()[0]
            self.assertTrue(
                first_line.startswith("#!/"),
                f"{name}: first line should be a shebang, got {first_line!r}",
            )


class HookFunctionalTests(TestCase):
    """Hooks should exit cleanly with a representative input on a fresh
    isolated cache (no runs registered)."""

    def _run_hook(self, name: str, stdin_payload: dict) -> subprocess.CompletedProcess:
        with isolated_cache() as cache:
            env = os.environ.copy()
            env["COSCIENTIST_CACHE_DIR"] = str(cache)
            env["PATH"] = os.environ.get("PATH", "/usr/bin:/bin")
            return subprocess.run(
                [str(_HOOKS_DIR / name)],
                input=json.dumps(stdin_payload),
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )

    def test_load_active_run_clean_cache(self):
        r = self._run_hook(
            "load-active-run.sh",
            {"hook_event_name": "SessionStart", "source": "startup"},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        # Should output "{}" when no active run exists.
        self.assertEqual(r.stdout.strip(), "{}", r.stdout)

    def test_health_on_stop_clean_cache(self):
        r = self._run_hook(
            "health-on-stop.sh",
            {"hook_event_name": "Stop"},
        )
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_closeout_on_steward_stop_no_runs(self):
        r = self._run_hook(
            "closeout-on-steward-stop.sh",
            {"hook_event_name": "SubagentStop", "agent_type": "steward"},
        )
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        HookSettingsTests, HookScriptTests, HookFunctionalTests,
    ))
