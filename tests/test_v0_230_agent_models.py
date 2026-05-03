"""v0.230 — every agent declares `model:` in YAML frontmatter.

Locks in the model-declaration coverage from v0.230's patcher so
new agents don't slip through without a tier assignment.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_AGENTS = _REPO / ".claude" / "agents"

_VALID_TIERS = {"haiku", "sonnet", "opus"}
_MODEL_RE = re.compile(r"^model:\s*(\S+)\s*$", re.MULTILINE)


def _frontmatter(path: Path) -> str:
    text = path.read_text()
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    return text[4:end] if end > 0 else ""


class AgentModelDeclarationTests(TestCase):
    def test_every_agent_declares_model(self):
        missing: list[str] = []
        for agent in sorted(_AGENTS.glob("*.md")):
            fm = _frontmatter(agent)
            if "\nmodel:" not in fm and not fm.startswith("model:"):
                missing.append(agent.name)
        self.assertEqual(
            missing, [],
            f"agents missing model: declaration: {missing}",
        )

    def test_models_use_known_tiers_or_explicit_id(self):
        bad: list[tuple[str, str]] = []
        for agent in sorted(_AGENTS.glob("*.md")):
            fm = _frontmatter(agent)
            m = _MODEL_RE.search(fm)
            if not m:
                continue
            value = m.group(1).strip().strip('"').strip("'")
            # Accept short tiers OR explicit model IDs (which start
            # with `claude-` and follow the official naming convention).
            if value in _VALID_TIERS:
                continue
            if value.startswith("claude-"):
                continue
            bad.append((agent.name, value))
        self.assertEqual(
            bad, [],
            f"agents with unknown model value: {bad}",
        )


if __name__ == "__main__":
    raise SystemExit(run_tests(AgentModelDeclarationTests))
