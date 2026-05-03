#!/usr/bin/env python3
"""v0.216 — Phase 1 frontmatter compliance patcher.

Walks every .claude/skills/<name>/SKILL.md and .claude/agents/<name>.md and
adds the missing official-spec frontmatter fields:

  Skills:
    - disable-model-invocation: true (manual-trigger skills)
    - allowed-tools: ... (read-only analytics skills)

  Agents:
    - memory: project (long-running personas)
    - skills: [...] (preload for deep-research personas)
    - effort: low|high
    - disallowedTools: Write, Edit (read-only roles)
    - color: ... (visual triage)

Idempotent: skips files that already have the field. Run multiple times safe.

Usage:
    uv run python scripts/v0_216_frontmatter_patch.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SKILLS = _REPO / ".claude" / "skills"
_AGENTS = _REPO / ".claude" / "agents"

# ---------------------------------------------------------------------------
# Classification maps
# ---------------------------------------------------------------------------

# Skills users invoke manually (no autonomous Claude trigger).
# Side-effects: writes to disk, sends data to external services, mutates state.
MANUAL_SKILLS = frozenset({
    "audit-rotate",
    "compositor",  # legacy mapping -> manuscript-format
    "dmp-generator",
    "ethics-irb",
    "experiment-reproduce",
    "funder",  # legacy mapping -> grant-draft
    "grant-draft",
    "manuscript-bibtex-import",
    "manuscript-draft",
    "manuscript-format",
    "manuscript-revise",
    "manuscript-version",
    "registered-reports",
    "reviser",  # legacy
    "zenodo-deposit",
    # NB: deep-research stays auto-invocable so Claude can dispatch from
    # natural-language prompts. Its phases each have their own internal
    # break-points.
})

# Read-only analytics skills — pre-approve sqlite + uv run + Read/Bash so
# Claude doesn't get permission prompts mid-session.
READ_ONLY_ANALYTICS_SKILLS = frozenset({
    "audit-query",
    "citation-decay",
    "claim-cluster",
    "coauthor-network",
    "cross-project-memory",
    "field-trends-analyzer",
    "funding-graph",
    "graph-query",
    "graph-viz",
    "health",
    "meta-research",
    "project-dashboard",
    "reading-pace-analytics",
    "replication-finder",
})

ANALYTICS_ALLOWED_TOOLS = "Read Bash(sqlite3 *) Bash(uv run python *) Glob Grep"

# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

# Agents that benefit from cross-session memory accumulation.
MEMORY_PROJECT_AGENTS = frozenset({
    "assumption-auditor",
    "diarist",
    "indexer",
    "librarian",
    "panel",
    "stylist",
    "verifier",
    "watchman",
})

# Agents that should explicitly preload skills they invoke.
# Maps agent → list of skill names to preload as system-prompt context.
AGENT_SKILL_PRELOAD: dict[str, list[str]] = {
    "cartographer": ["graph-query", "citation-decay"],
    "chronicler": ["graph-query", "citation-decay"],
    "surveyor": ["gap-analyzer", "statistics"],
    "synthesist": ["claim-cluster", "graph-query"],
    "architect": ["tournament", "idea-attacker"],
    "inquisitor": ["attack-vectors", "idea-attacker"],
    "weaver": ["claim-cluster"],
    "visionary": ["tournament"],
    "steward": ["research-eval"],
    "verifier": ["research-eval", "novelty-check"],
    "panel": ["attack-vectors", "novelty-check", "publishability-check"],
    "diviner": ["claim-cluster", "graph-query"],
    "novelty-auditor": ["novelty-check"],
    "publishability-judge": ["publishability-check", "calibration"],
    "red-team": ["attack-vectors"],
    "advocate": ["attack-vectors"],
    "peer-reviewer": ["attack-vectors", "novelty-check"],
    "experimentalist": ["experiment-design", "statistics"],
    "curator": ["dataset-agent"],
    "ranker": ["tournament"],
    "mutator": ["tournament"],
    "librarian": ["reference-agent", "resolve-citation"],
    "stylist": ["writing-style"],
    "drafter": ["manuscript-draft", "writing-style"],
    "compositor": ["manuscript-format"],
    "reviser": ["manuscript-revise"],
}

# Effort tiers.
HIGH_EFFORT_AGENTS = frozenset({
    "architect",
    "synthesist",
    "diviner",
    "weaver",
    "steward",
    "visionary",
    "inquisitor",
})

LOW_EFFORT_AGENTS = frozenset({
    "ranker",
    "debate-judge",
    "quality-judge",
    "wide-rank",
    "wide-screen",
    "wide-triage",
    "wide-survey",
    "scout",
    "watchman",
    "indexer",
})

# Read-only personas — should never Write/Edit.
READ_ONLY_AGENTS = frozenset({
    "scout",
    "cartographer",
    "chronicler",
    "surveyor",
    "inquisitor",
    "red-team",
    "peer-reviewer",
    "novelty-auditor",
    "publishability-judge",
    "watchman",
    "indexer",
    "wide-triage",
    "wide-screen",
    "wide-rank",
    "wide-survey",
    "wide-read",
    "wide-compare",
    "quality-judge",
    "debate-judge",
    "advocate",
    "panel",
    "verifier",
    "ranker",
    "assumption-auditor",
})

# Color assignments — narrative phase grouping.
AGENT_COLOR: dict[str, str] = {
    # Phase A — Expedition (deep-research): blue family
    "scout": "cyan",
    "cartographer": "blue",
    "chronicler": "blue",
    "surveyor": "blue",
    "synthesist": "purple",
    "architect": "purple",
    "inquisitor": "red",
    "weaver": "purple",
    "visionary": "purple",
    "steward": "blue",
    # Phase B — Workshop (manuscript): green
    "verifier": "green",
    "panel": "green",
    "diviner": "green",
    "drafter": "green",
    "compositor": "green",
    "reviser": "green",
    # Phase C — Tribunal (judgment): red/orange
    "novelty-auditor": "orange",
    "publishability-judge": "orange",
    "red-team": "red",
    "advocate": "orange",
    "peer-reviewer": "orange",
    # Phase D — Laboratory: yellow
    "experimentalist": "yellow",
    "curator": "yellow",
    "funder": "yellow",
    # Phase E — Tournament: pink
    "ranker": "pink",
    "mutator": "pink",
    # Phase F — Archive: cyan
    "librarian": "cyan",
    "stylist": "cyan",
    "diarist": "cyan",
    "watchman": "cyan",
    "indexer": "cyan",
    # Phase G — Wide research: yellow
    "wide-triage": "yellow",
    "wide-read": "yellow",
    "wide-rank": "yellow",
    "wide-compare": "yellow",
    "wide-survey": "yellow",
    "wide-screen": "yellow",
    # Phase H — Debate: pink
    "debate-pro": "pink",
    "debate-con": "pink",
    "debate-judge": "pink",
    # Phase I — Quality: green
    "quality-judge": "green",
    # Phase J — Idea-tree: purple
    "idea-tree-generator": "purple",
    # Phase K — Assumption: red
    "assumption-auditor": "red",
}


# ---------------------------------------------------------------------------
# Patching helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)


def _split_frontmatter(text: str) -> tuple[str, str] | None:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    body_start = m.end()
    return m.group(1), text[body_start:]


def _has_field(fm: str, key: str) -> bool:
    pattern = re.compile(rf"^{re.escape(key)}\s*:", re.MULTILINE)
    return bool(pattern.search(fm))


def _add_field(fm: str, key: str, value: str) -> str:
    """Append `key: value` line just before the closing `---`."""
    if _has_field(fm, key):
        return fm
    return f"{fm.rstrip()}\n{key}: {value}"


def _apply_skill_patches(name: str, fm: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    if name in MANUAL_SKILLS and not _has_field(fm, "disable-model-invocation"):
        fm = _add_field(fm, "disable-model-invocation", "true")
        changes.append("disable-model-invocation: true")
    if name in READ_ONLY_ANALYTICS_SKILLS and not _has_field(fm, "allowed-tools"):
        fm = _add_field(fm, "allowed-tools", ANALYTICS_ALLOWED_TOOLS)
        changes.append(f"allowed-tools: {ANALYTICS_ALLOWED_TOOLS}")
    return fm, changes


def _apply_agent_patches(name: str, fm: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    if name in MEMORY_PROJECT_AGENTS and not _has_field(fm, "memory"):
        fm = _add_field(fm, "memory", "project")
        changes.append("memory: project")
    if name in AGENT_SKILL_PRELOAD and not _has_field(fm, "skills"):
        skills_yaml = "[" + ", ".join(AGENT_SKILL_PRELOAD[name]) + "]"
        fm = _add_field(fm, "skills", skills_yaml)
        changes.append(f"skills: {skills_yaml}")
    if name in HIGH_EFFORT_AGENTS and not _has_field(fm, "effort"):
        fm = _add_field(fm, "effort", "high")
        changes.append("effort: high")
    elif name in LOW_EFFORT_AGENTS and not _has_field(fm, "effort"):
        fm = _add_field(fm, "effort", "low")
        changes.append("effort: low")
    if name in READ_ONLY_AGENTS and not _has_field(fm, "disallowedTools"):
        fm = _add_field(fm, "disallowedTools", "Write, Edit")
        changes.append("disallowedTools: Write, Edit")
    if name in AGENT_COLOR and not _has_field(fm, "color"):
        fm = _add_field(fm, "color", AGENT_COLOR[name])
        changes.append(f"color: {AGENT_COLOR[name]}")
    return fm, changes


def patch_skill(skill_dir: Path, dry_run: bool) -> tuple[str, list[str]]:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return skill_dir.name, ["[skip: no SKILL.md]"]
    text = skill_md.read_text()
    parts = _split_frontmatter(text)
    if parts is None:
        return skill_dir.name, ["[skip: no frontmatter]"]
    fm, body = parts
    new_fm, changes = _apply_skill_patches(skill_dir.name, fm)
    if changes and not dry_run:
        skill_md.write_text(f"---\n{new_fm}\n---\n{body}")
    return skill_dir.name, changes


def patch_agent(agent_md: Path, dry_run: bool) -> tuple[str, list[str]]:
    name = agent_md.stem
    text = agent_md.read_text()
    parts = _split_frontmatter(text)
    if parts is None:
        return name, ["[skip: no frontmatter]"]
    fm, body = parts
    new_fm, changes = _apply_agent_patches(name, fm)
    if changes and not dry_run:
        agent_md.write_text(f"---\n{new_fm}\n---\n{body}")
    return name, changes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    skill_changes = 0
    agent_changes = 0

    print("=== Skills ===")
    for d in sorted(_SKILLS.iterdir()):
        if not d.is_dir():
            continue
        name, changes = patch_skill(d, args.dry_run)
        if changes:
            skill_changes += 1
            print(f"  {name}:")
            for c in changes:
                print(f"    + {c}")

    print()
    print("=== Agents ===")
    for f in sorted(_AGENTS.glob("*.md")):
        name, changes = patch_agent(f, args.dry_run)
        if changes:
            agent_changes += 1
            print(f"  {name}:")
            for c in changes:
                print(f"    + {c}")

    print()
    print(f"Summary: {skill_changes} skills patched, {agent_changes} agents patched")
    if args.dry_run:
        print("(dry-run — no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
