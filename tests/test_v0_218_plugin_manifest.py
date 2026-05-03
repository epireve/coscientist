"""v0.218 — Phase 4: canonical plugin manifest tests.

Validates the source layout at `coscientist-plugin-src/`:

  coscientist-plugin-src/
  ├── .claude-plugin/
  │   └── plugin.json          (per docs/plugins-reference)
  └── monitors/
      └── monitors.json

  plugin.json must:
    - have required field `name`
    - declare userConfig for sensitive secrets (zenodo, consensus, zotero)
    - reference monitors.json
    - reference the project's .claude/skills/ + .claude/agents/

  monitors.json must:
    - be a JSON array
    - have at least one monitor with name + command + description
"""
from __future__ import annotations

import json
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parent.parent
_PLUGIN_SRC = _REPO / "coscientist-plugin-src"
_MANIFEST = _PLUGIN_SRC / ".claude-plugin" / "plugin.json"
_MONITORS = _PLUGIN_SRC / "monitors" / "monitors.json"


class PluginManifestTests(TestCase):
    def test_plugin_src_dir_exists(self):
        self.assertTrue(
            _PLUGIN_SRC.is_dir(),
            f"missing {_PLUGIN_SRC}",
        )

    def test_manifest_is_valid_json(self):
        self.assertTrue(_MANIFEST.exists(), f"missing {_MANIFEST}")
        json.loads(_MANIFEST.read_text())

    def test_manifest_has_required_name(self):
        m = json.loads(_MANIFEST.read_text())
        self.assertEqual(m.get("name"), "coscientist")

    def test_manifest_has_version(self):
        m = json.loads(_MANIFEST.read_text())
        self.assertIn("version", m)

    def test_manifest_declares_user_config(self):
        m = json.loads(_MANIFEST.read_text())
        uc = m.get("userConfig", {})
        for required_key in (
            "consensus_authed", "zenodo_token", "zotero_api_host",
        ):
            self.assertIn(
                required_key, uc,
                f"plugin.json userConfig missing '{required_key}'",
            )

    def test_sensitive_keys_are_marked_sensitive(self):
        m = json.loads(_MANIFEST.read_text())
        uc = m.get("userConfig", {})
        for k in ("zenodo_token", "consensus_api_key"):
            if k in uc:
                self.assertTrue(
                    uc[k].get("sensitive") is True,
                    f"userConfig['{k}'] must have sensitive=true",
                )

    def test_manifest_references_monitors(self):
        m = json.loads(_MANIFEST.read_text())
        self.assertIn("monitors", m)


class PluginMonitorsTests(TestCase):
    def test_monitors_json_valid(self):
        self.assertTrue(_MONITORS.exists(), f"missing {_MONITORS}")
        data = json.loads(_MONITORS.read_text())
        self.assertIsInstance(data, list, "monitors.json must be JSON array")

    def test_monitors_have_required_fields(self):
        data = json.loads(_MONITORS.read_text())
        for m in data:
            for key in ("name", "command", "description"):
                self.assertIn(
                    key, m,
                    f"monitor entry missing '{key}': {m}",
                )

    def test_at_least_one_monitor(self):
        data = json.loads(_MONITORS.read_text())
        self.assertGreaterEqual(len(data), 1)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        PluginManifestTests, PluginMonitorsTests,
    ))
