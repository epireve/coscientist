"""v0.217 — Phase 2: commands → skills migration tests.

Replaces v0.215's slash-command structural tests with the new convention:
operator commands live as `.claude/skills/<name>/SKILL.md` with
`disable-model-invocation: true` (per official docs/skills).

Locks in:
  - The 4 migrated /run-* + /db-* commands now exist as skills, NOT
    in `.claude/commands/`.
  - Each migrated skill has `disable-model-invocation: true`.
  - The legacy `/deep-research` command stays in `.claude/commands/`
    (it routes to a same-named skill — no migration needed).
  - Naming family conformance: every skill stem matches one of the
    `/deep-* /run-* /db-* /research-*` family prefixes (operator commands).

This supersedes v0.215; that test file is removed.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parent.parent
_CMD_DIR = _REPO / ".claude" / "commands"
_SKILLS_DIR = _REPO / ".claude" / "skills"

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)

_OPERATOR_FAMILIES = ("deep-", "run-", "db-", "research-")

# Migrated skills (Phase 2 of v0.217) — these moved from .claude/commands/
# to .claude/skills/<name>/SKILL.md.
MIGRATED_SKILLS = ("run-audit", "run-evolve", "run-to-manuscript", "db-describe")


def _frontmatter(p: Path) -> dict[str, str]:
    text = p.read_text()
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


class CommandSkillMigrationTests(TestCase):
    def test_migrated_skills_exist(self):
        for name in MIGRATED_SKILLS:
            self.assertTrue(
                (_SKILLS_DIR / name / "SKILL.md").exists(),
                f"{name}: expected at .claude/skills/{name}/SKILL.md",
            )

    def test_migrated_files_no_longer_in_commands_dir(self):
        for name in MIGRATED_SKILLS:
            self.assertFalse(
                (_CMD_DIR / f"{name}.md").exists(),
                f"{name}: legacy .claude/commands/{name}.md should have been "
                f"removed during migration",
            )

    def test_migrated_skills_have_disable_model_invocation(self):
        for name in MIGRATED_SKILLS:
            skill = _SKILLS_DIR / name / "SKILL.md"
            fm = _frontmatter(skill)
            self.assertEqual(
                fm.get("disable-model-invocation"), "true",
                f"{name}/SKILL.md must set 'disable-model-invocation: true' "
                f"(operator-invoked, no autonomous trigger)",
            )

    def test_migrated_skills_have_name_field(self):
        for name in MIGRATED_SKILLS:
            skill = _SKILLS_DIR / name / "SKILL.md"
            fm = _frontmatter(skill)
            self.assertEqual(
                fm.get("name"), name,
                f"{name}/SKILL.md must have 'name: {name}' frontmatter",
            )

    def test_migrated_skills_have_argument_hint(self):
        for name in MIGRATED_SKILLS:
            skill = _SKILLS_DIR / name / "SKILL.md"
            fm = _frontmatter(skill)
            self.assertIn(
                "argument-hint", fm,
                f"{name}/SKILL.md must have argument-hint",
            )

    def test_legacy_deep_research_command_preserved(self):
        """/deep-research keeps the .claude/commands/ wrapper that routes
        to the deep-research skill. Both can coexist per docs."""
        cmd = _CMD_DIR / "deep-research.md"
        self.assertTrue(
            cmd.exists(),
            "expected /deep-research wrapper at .claude/commands/deep-research.md",
        )
        skill = _SKILLS_DIR / "deep-research" / "SKILL.md"
        self.assertTrue(
            skill.exists(),
            "expected deep-research skill at .claude/skills/deep-research/SKILL.md",
        )

    def test_no_remaining_operator_commands_in_commands_dir(self):
        """Beyond /deep-research, .claude/commands/ should be empty after
        Phase 2 migration."""
        remaining = sorted(p.stem for p in _CMD_DIR.glob("*.md"))
        self.assertEqual(
            remaining, ["deep-research"],
            f"only deep-research wrapper should remain in .claude/commands/; "
            f"found: {remaining}",
        )

    def test_no_dogfood_phrasing_in_migrated_skills(self):
        for name in MIGRATED_SKILLS:
            body = (_SKILLS_DIR / name / "SKILL.md").read_text().lower()
            self.assertNotIn(
                "dogfood", body,
                f"{name}: drop 'dogfood' phrasing (deprecated)",
            )

    def test_migrated_skills_have_procedure_and_exit_test(self):
        for name in MIGRATED_SKILLS:
            body = (_SKILLS_DIR / name / "SKILL.md").read_text()
            self.assertIn(
                "## Procedure", body,
                f"{name}/SKILL.md missing '## Procedure' section",
            )
            self.assertIn(
                "## Exit test", body,
                f"{name}/SKILL.md missing '## Exit test' section",
            )

    def test_migrated_skill_names_match_family_prefixes(self):
        for name in MIGRATED_SKILLS:
            ok = any(name.startswith(p) for p in _OPERATOR_FAMILIES)
            self.assertTrue(
                ok,
                f"{name}: must start with one of {_OPERATOR_FAMILIES}",
            )


if __name__ == "__main__":
    raise SystemExit(run_tests(CommandSkillMigrationTests))
