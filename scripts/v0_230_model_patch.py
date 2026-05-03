"""v0.230 — add `model:` to agent frontmatter where missing.

Tiered policy:
  - haiku: cheap judges + read-only aggregators
  - opus:  heavy thinkers + critical-judgment personas
  - sonnet: everything else (default)

Idempotent: skips files that already declare `model:`. Inserts the
new line right after the `description:` line in YAML frontmatter
to keep the block readable.

Usage:
    uv run python scripts/v0_230_model_patch.py [--dry-run]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_AGENTS = _REPO / ".claude" / "agents"

# Cheap: pairwise judges, fast aggregators, single-purpose readers.
HAIKU = {
    "ranker",
    "debate-judge",
    "quality-judge",
    "wide-rank",
    "wide-screen",
    "wide-triage",
    "indexer",
    "watchman",
    "librarian",
    "diarist",
    "stylist",
}

# Heavy: architecture, synthesis, adversarial critique, judgments
# that benefit from extended thinking.
OPUS = {
    "architect",
    "synthesist",
    "diviner",
    "weaver",
    "visionary",
    "steward",
    "inquisitor",
    "novelty-auditor",
    "publishability-judge",
    "red-team",
    "advocate",
    "panel",
    "peer-reviewer",
    "mutator",
    "idea-tree-generator",
    "verifier",
    "reviser",
    "drafter",
    "compositor",
    "funder",
    "experimentalist",
    "scout",
    "cartographer",
    "chronicler",
    "surveyor",
}


def _model_for(name: str) -> str:
    if name in HAIKU:
        return "haiku"
    if name in OPUS:
        return "opus"
    return "sonnet"


def _patch_one(path: Path, *, dry_run: bool = False) -> tuple[bool, str]:
    """Return (mutated, message). False mutated = nothing to do."""
    text = path.read_text()
    if not text.startswith("---\n"):
        return False, f"no frontmatter — skipped"
    end = text.find("\n---\n", 4)
    if end < 0:
        return False, "malformed frontmatter — skipped"
    fm = text[4:end]
    rest = text[end + 5:]
    if "\nmodel:" in fm or fm.startswith("model:"):
        return False, "already declares model:"
    name = path.stem
    model = _model_for(name)
    # Insert after `description:` if present, else append.
    lines = fm.splitlines()
    out_lines: list[str] = []
    inserted = False
    for line in lines:
        out_lines.append(line)
        if not inserted and line.startswith("description:"):
            # Continue past wrapped description (lines starting with
            # whitespace-only continuation).
            continue
        if not inserted and out_lines[-1].startswith("description:"):
            out_lines.append(f"model: {model}")
            inserted = True
    if not inserted:
        # Insert near top: after `name:` if present, else first line.
        new_lines = []
        for line in lines:
            new_lines.append(line)
            if not inserted and line.startswith("name:"):
                new_lines.append(f"model: {model}")
                inserted = True
        out_lines = new_lines
        if not inserted:
            out_lines.append(f"model: {model}")
    new_fm = "\n".join(out_lines)
    new_text = f"---\n{new_fm}\n---\n{rest}"
    if dry_run:
        return True, f"would set model: {model}"
    path.write_text(new_text)
    return True, f"set model: {model}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)

    n_patched = n_skip = 0
    for agent in sorted(_AGENTS.glob("*.md")):
        mutated, msg = _patch_one(agent, dry_run=args.dry_run)
        if mutated:
            n_patched += 1
            print(f"[{agent.stem}] {msg}")
        else:
            n_skip += 1
    print(
        f"\n{'would patch' if args.dry_run else 'patched'} "
        f"{n_patched}, skipped {n_skip}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
