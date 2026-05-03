"""v0.215 — slash command sanity tests.

Validates `.claude/commands/*.md` files conform to the family naming
standard and have required frontmatter.

Naming families:
  /deep-*       — high-level pipelines
  /run-*        — run-scoped post-processing
  /db-*         — DB introspection / ops
  /research-*   — multi-pipeline orchestration

Required frontmatter keys: description, argument-hint.
Body must contain: ## Procedure, ## Exit test.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parent.parent
_CMD_DIR = _REPO / ".claude" / "commands"

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

_VALID_FAMILIES = ("deep-", "run-", "db-", "research-")


def _parse_frontmatter(text: str) -> dict[str, str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip()
    return out


class SlashCommandStructureTests(TestCase):
    def test_commands_dir_exists(self):
        self.assertTrue(_CMD_DIR.is_dir(),
                        f"missing slash command dir at {_CMD_DIR}")

    def test_at_least_four_commands_registered(self):
        cmds = list(_CMD_DIR.glob("*.md"))
        self.assertGreaterEqual(
            len(cmds), 4,
            f"expected ≥4 commands; found {len(cmds)}: {[c.name for c in cmds]}",
        )

    def test_every_command_has_frontmatter(self):
        for p in _CMD_DIR.glob("*.md"):
            fm = _parse_frontmatter(p.read_text())
            self.assertTrue(fm, f"{p.name}: no frontmatter")
            self.assertIn("description", fm,
                          f"{p.name}: missing description")
            self.assertIn("argument-hint", fm,
                          f"{p.name}: missing argument-hint")

    def test_command_name_matches_family_pattern(self):
        for p in _CMD_DIR.glob("*.md"):
            stem = p.stem
            ok = any(stem.startswith(prefix) for prefix in _VALID_FAMILIES)
            self.assertTrue(
                ok,
                f"{stem!r} doesn't match family prefix "
                f"{_VALID_FAMILIES} — rename or add a family",
            )

    def test_body_has_procedure_and_exit_test(self):
        for p in _CMD_DIR.glob("*.md"):
            body = p.read_text()
            self.assertIn(
                "## Procedure", body,
                f"{p.name}: missing '## Procedure' section",
            )
            self.assertIn(
                "## Exit test", body,
                f"{p.name}: missing '## Exit test' section",
            )

    def test_no_dogfood_phrasing(self):
        """v0.215 — 'dogfood' deprecated for forward-facing surfaces."""
        for p in _CMD_DIR.glob("*.md"):
            body = p.read_text().lower()
            self.assertNotIn(
                "dogfood", body,
                f"{p.name}: drop 'dogfood' (deprecated; use 'field-test' "
                f"or 'validation run')",
            )

    def test_known_commands_present(self):
        expected = {
            "deep-research",
            "run-audit",
            "run-evolve",
            "run-to-manuscript",
            "db-describe",
        }
        found = {p.stem for p in _CMD_DIR.glob("*.md")}
        missing = expected - found
        self.assertFalse(
            missing,
            f"missing expected commands: {missing}",
        )

    def test_argument_hint_uses_angle_brackets_or_flags(self):
        """argument-hint should look like '<x>' or '--flag' — not prose."""
        for p in _CMD_DIR.glob("*.md"):
            fm = _parse_frontmatter(p.read_text())
            hint = fm.get("argument-hint", "").strip().strip('"\'')
            if not hint:
                self.fail(f"{p.name}: empty argument-hint")
            has_angle = "<" in hint and ">" in hint
            has_flag = "--" in hint
            self.assertTrue(
                has_angle or has_flag,
                f"{p.name}: argument-hint {hint!r} should include "
                f"'<arg>' or '--flag'",
            )


if __name__ == "__main__":
    raise SystemExit(run_tests(SlashCommandStructureTests))
