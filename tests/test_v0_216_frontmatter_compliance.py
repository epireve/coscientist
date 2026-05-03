"""v0.216 — frontmatter compliance tests.

Phase 1 of the official-spec-alignment refactor (plan: swift-orbiting-taco).
Locks in:

  Skills:
    - Manual-trigger skills (compositor, reviser, ...) have
      `disable-model-invocation: true`
    - Read-only analytics skills have `allowed-tools: ...`

  Agents:
    - Long-running personas have `memory: project`
    - Deep-research personas preload skills via `skills: [...]`
    - Heavy thinkers have `effort: high`; fast judges `effort: low`
    - Read-only roles have `disallowedTools: Write, Edit`
    - All have `color:` for visual triage

Source of truth: scripts/v0_216_frontmatter_patch.py classifications.
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parent.parent
_SKILLS = _REPO / ".claude" / "skills"
_AGENTS = _REPO / ".claude" / "agents"

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _frontmatter(path: Path) -> str:
    text = path.read_text()
    m = _FRONTMATTER_RE.match(text)
    return m.group(1) if m else ""


def _has(fm: str, key: str) -> bool:
    return bool(re.search(rf"^{re.escape(key)}\s*:", fm, re.MULTILINE))


# Mirror the patcher's classification.
MANUAL_SKILLS = {
    "audit-rotate", "dmp-generator", "ethics-irb", "experiment-reproduce",
    "grant-draft", "manuscript-bibtex-import", "manuscript-draft",
    "manuscript-format", "manuscript-revise", "manuscript-version",
    "registered-reports", "zenodo-deposit",
}

READ_ONLY_ANALYTICS_SKILLS = {
    "audit-query", "citation-decay", "claim-cluster", "coauthor-network",
    "cross-project-memory", "field-trends-analyzer", "funding-graph",
    "graph-query", "graph-viz", "health", "meta-research",
    "project-dashboard", "reading-pace-analytics", "replication-finder",
}

MEMORY_PROJECT_AGENTS = {
    "assumption-auditor", "diarist", "indexer", "librarian", "panel",
    "stylist", "verifier", "watchman",
}

HIGH_EFFORT_AGENTS = {
    "architect", "synthesist", "diviner", "weaver", "steward", "visionary",
    "inquisitor",
}

LOW_EFFORT_AGENTS = {
    "ranker", "debate-judge", "quality-judge", "wide-rank", "wide-screen",
    "wide-triage", "wide-survey", "scout", "watchman", "indexer",
}

READ_ONLY_AGENTS = {
    "scout", "cartographer", "chronicler", "surveyor", "inquisitor",
    "red-team", "peer-reviewer", "novelty-auditor", "publishability-judge",
    "watchman", "indexer", "wide-triage", "wide-screen", "wide-rank",
    "wide-survey", "wide-read", "wide-compare", "quality-judge",
    "debate-judge", "advocate", "panel", "verifier", "ranker",
    "assumption-auditor",
}

PRELOAD_AGENTS = {
    "cartographer", "chronicler", "surveyor", "synthesist", "architect",
    "inquisitor", "weaver", "visionary", "steward", "verifier", "panel",
    "diviner", "novelty-auditor", "publishability-judge", "red-team",
    "advocate", "peer-reviewer", "experimentalist", "curator", "ranker",
    "mutator", "librarian", "stylist", "drafter", "compositor", "reviser",
}


class SkillFrontmatterCompliance(TestCase):
    def test_manual_skills_have_disable_model_invocation(self):
        for name in MANUAL_SKILLS:
            skill = _SKILLS / name / "SKILL.md"
            if not skill.exists():
                continue  # skill may not exist in this branch
            fm = _frontmatter(skill)
            self.assertTrue(
                _has(fm, "disable-model-invocation"),
                f"{name}/SKILL.md missing 'disable-model-invocation: true' "
                f"(MANUAL_SKILLS class)",
            )

    def test_readonly_analytics_skills_have_allowed_tools(self):
        for name in READ_ONLY_ANALYTICS_SKILLS:
            skill = _SKILLS / name / "SKILL.md"
            if not skill.exists():
                continue
            fm = _frontmatter(skill)
            self.assertTrue(
                _has(fm, "allowed-tools"),
                f"{name}/SKILL.md missing 'allowed-tools' "
                f"(READ_ONLY_ANALYTICS_SKILLS class)",
            )


class AgentFrontmatterCompliance(TestCase):
    def test_memory_project_agents_have_memory(self):
        for name in MEMORY_PROJECT_AGENTS:
            agent = _AGENTS / f"{name}.md"
            if not agent.exists():
                continue
            fm = _frontmatter(agent)
            self.assertTrue(
                _has(fm, "memory"),
                f"agents/{name}.md missing 'memory: project'",
            )

    def test_high_effort_agents_have_effort_high(self):
        for name in HIGH_EFFORT_AGENTS:
            agent = _AGENTS / f"{name}.md"
            if not agent.exists():
                continue
            fm = _frontmatter(agent)
            self.assertTrue(
                _has(fm, "effort"),
                f"agents/{name}.md missing 'effort: high'",
            )

    def test_low_effort_agents_have_effort_low(self):
        for name in LOW_EFFORT_AGENTS:
            agent = _AGENTS / f"{name}.md"
            if not agent.exists():
                continue
            fm = _frontmatter(agent)
            self.assertTrue(
                _has(fm, "effort"),
                f"agents/{name}.md missing 'effort: low'",
            )

    def test_readonly_agents_have_disallowed_tools(self):
        for name in READ_ONLY_AGENTS:
            agent = _AGENTS / f"{name}.md"
            if not agent.exists():
                continue
            fm = _frontmatter(agent)
            self.assertTrue(
                _has(fm, "disallowedTools"),
                f"agents/{name}.md missing 'disallowedTools: Write, Edit' "
                f"(READ_ONLY_AGENTS class)",
            )

    def test_preload_agents_have_skills_field(self):
        for name in PRELOAD_AGENTS:
            agent = _AGENTS / f"{name}.md"
            if not agent.exists():
                continue
            fm = _frontmatter(agent)
            self.assertTrue(
                _has(fm, "skills"),
                f"agents/{name}.md missing 'skills: [...]' preload",
            )

    def test_every_agent_has_color(self):
        for agent in _AGENTS.glob("*.md"):
            fm = _frontmatter(agent)
            self.assertTrue(
                _has(fm, "color"),
                f"{agent.name}: missing 'color:' field for visual triage",
            )


if __name__ == "__main__":
    raise SystemExit(run_tests(
        SkillFrontmatterCompliance, AgentFrontmatterCompliance,
    ))
