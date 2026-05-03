"""v0.232 — every CLI-flavored user-invocable skill declares argument-hint.

Locks the arg-hint coverage so future skills with `<run_id>` /
`--run-id` / `<paper_id>` patterns in their body must declare an
`argument-hint:` in YAML frontmatter.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_SKILLS = _REPO / ".claude" / "skills"

# Patterns that signal "this skill takes structured CLI args".
_CLI_PATTERN = re.compile(
    r"\$ARGUMENTS|--run-id <|--paper-id <|<run_id>|<paper_id>|"
    r"--manuscript-id <|<manuscript_id>|<query>|<command>",
)

# Skills genuinely arg-less (analytics, batch, dashboards) — exempt.
_EXEMPT = {
    "audit-rotate",
    "calibration",
    "citation-decay",
    "citation-format-converter",
    "claim-cluster",
    "coauthor-network",
    "credit-tracker",
    "cross-project-memory",
    "field-trends-analyzer",
    "funding-graph",
    "graph-query",
    "graph-viz",
    "health",
    "meta-research",
    "preprint-alerts",
    "project-dashboard",
    "project-manager",
    "reading-pace-analytics",
    "replication-finder",
    "research-journal",
    "retraction-watch",
    "citation-alerts",
    "venue-match",
    "writing-style",
}


def _frontmatter(path: Path) -> str:
    text = path.read_text()
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    return text[4:end] if end > 0 else ""


def _body(path: Path) -> str:
    text = path.read_text()
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    return text[end + 5:] if end > 0 else text


class SkillArgHintTests(TestCase):
    def test_cli_skills_declare_argument_hint(self):
        missing: list[str] = []
        for skill in sorted(_SKILLS.glob("*/SKILL.md")):
            name = skill.parent.name
            if name in _EXEMPT:
                continue
            body = _body(skill)
            fm = _frontmatter(skill)
            if not _CLI_PATTERN.search(body):
                continue
            if "argument-hint:" not in fm:
                missing.append(name)
        self.assertEqual(
            missing, [],
            f"CLI-flavored skills missing argument-hint: {missing}",
        )


if __name__ == "__main__":
    raise SystemExit(run_tests(SkillArgHintTests))
