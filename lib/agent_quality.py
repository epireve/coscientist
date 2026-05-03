"""v0.92 — agent quality scoring.

v0.227 — split into 3 modules (rubrics, scoring, aggregation) for
testability + size. lib/agent_quality.py kept as a facade
re-exporting the public surface so existing callers keep working
unchanged.

Three judging modes, all persist to `agent_quality`:
  - auto-rubric: pure-stdlib structural checks
  - llm-judge: emits a structured prompt the `quality-judge`
    sub-agent consumes; orchestrator dispatches and persists JSON
  - ranker: existing tournament/ranker (deferred to v0.93)

CLI:
    uv run python -m lib.agent_quality summary --db <path>
    uv run python -m lib.agent_quality leaderboard
    uv run python -m lib.agent_quality drift [--window N]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Re-exports — preserve `from lib.agent_quality import X` for callers.
from lib.agent_quality_aggregation import (
    leaderboard,
    list_for_run,
    quality_drift,
    summary,
)
from lib.agent_quality_rubrics import (
    RUBRICS,
    Criterion,
    Rubric,
    _items_from,
    _load_json_path,
    _load_text_path,
    count_at_least,
    every_item_has_fields,
    fraction_with_field,
    has_field,
    unique_kind_count,
)
from lib.agent_quality_scoring import (
    _normalize_total,
    _persist,
    emit_judge_prompt,
    persist_judge_result,
    score_auto,
)

__all__ = [
    "Criterion",
    "Rubric",
    "RUBRICS",
    "count_at_least",
    "every_item_has_fields",
    "fraction_with_field",
    "unique_kind_count",
    "has_field",
    "score_auto",
    "emit_judge_prompt",
    "persist_judge_result",
    "list_for_run",
    "summary",
    "leaderboard",
    "quality_drift",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    """CLI: `summary` | `leaderboard` | `drift`."""
    p = argparse.ArgumentParser(
        prog="agent_quality",
        description="Agent quality scoring (v0.92).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help="Per-agent quality summary")
    s.add_argument("--db", required=True)
    s.add_argument("--run-id", default=None)
    lb = sub.add_parser(
        "leaderboard",
        help="Cross-run leaderboard (scans all run DBs)",
    )
    lb.add_argument("--root", default=None,
                     help="Override runs root (default ~/.cache/coscientist/runs)")
    dr = sub.add_parser(
        "drift",
        help="v0.127: per-agent quality drift over time. "
             "Latest --window scores vs prior --window.",
    )
    dr.add_argument("--root", default=None)
    dr.add_argument("--window", type=int, default=10,
                     help="Window size (default 10)")
    dr.add_argument("--threshold", type=float, default=0.1,
                     help="Drift delta threshold (default 0.1)")
    dr.add_argument("--format", choices=("json", "text"),
                     default="json")
    args = p.parse_args(argv)
    if args.cmd == "summary":
        out = summary(Path(args.db), run_id=args.run_id)
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0
    if args.cmd == "leaderboard":
        roots = [Path(args.root)] if args.root else None
        out = leaderboard(roots=roots)
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0
    # drift
    roots = [Path(args.root)] if args.root else None
    out = quality_drift(
        window=args.window, roots=roots,
        threshold=args.threshold,
    )
    if args.format == "json":
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
    else:
        sys.stdout.write(_render_drift_text(out) + "\n")
    return 0


def _render_drift_text(report: dict) -> str:
    lines = [
        f"# Agent quality drift (window={report.get('window', 0)})",
        f"- DBs scanned: {report.get('n_dbs', 0)}",
        f"- Rows: {report.get('n_rows', 0)}",
        "",
    ]
    by_agent = report.get("by_agent") or {}
    if not by_agent:
        lines.append("_No quality data yet._")
        return "\n".join(lines)
    rows = sorted(by_agent.items(),
                   key=lambda kv: kv[1].get("delta_mean", 0))
    for agent, d in rows:
        direction = d.get("direction", "?")
        delta = d.get("delta_mean", 0)
        latest = d.get("latest_window", {})
        prior = d.get("prior_window", {})
        lines.append(
            f"- **{agent}** [{direction}] delta={delta:+.3f} "
            f"latest={latest.get('mean', 0):.3f} "
            f"(n={latest.get('n', 0)}) "
            f"prior={prior.get('mean', 0):.3f} "
            f"(n={prior.get('n', 0)})"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
