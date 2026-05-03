"""v0.106 — single-shot health dump across the coscientist stack.

v0.222 — split into 3 modules (thresholds, collect, render) for
testability + size. lib/health.py kept as a facade re-exporting
the public surface so existing callers (`from lib.health import
collect`, etc) keep working unchanged.

Combines:
  - active runs (in-progress traces)
  - stale spans (status=running past threshold)
  - tool-call latency leaderboard
  - per-agent quality leaderboard
  - failed spans across all runs

One command, one report. Designed for "is anything stuck or
slow?" check during smoke test or daily review.

CLI:
    uv run python -m lib.health [--format md|json] [--max-age 30]
"""
from __future__ import annotations

import argparse
import json
import sys

# Re-exports — preserve `from lib.health import X` for callers.
from lib.health_collect import (
    _MCP_SOURCE_KEYS,
    _THINKING_TABLES,
    _thinking_coverage_for_db,
    _tree_summary_for_db,
    collect,
    mcp_error_rates,
    thinking_coverage_across_runs,
    trees_summary_across_runs,
)
from lib.health_render import render_md
from lib.health_thresholds import (
    DEFAULT_THRESHOLDS,
    _apply_overrides,
    _config_path,
    _project_config_path,
    _read_config,
    evaluate_alerts,
    load_thresholds,
)

__all__ = [
    "DEFAULT_THRESHOLDS",
    "load_thresholds",
    "evaluate_alerts",
    "collect",
    "mcp_error_rates",
    "trees_summary_across_runs",
    "thinking_coverage_across_runs",
    "render_md",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="health",
        description="Coscientist health dump (v0.106).",
    )
    p.add_argument("--format", choices=("md", "json"), default="md")
    p.add_argument("--max-age", type=int, default=30,
                    help="Stale-span threshold in minutes.")
    p.add_argument(
        "--no-alerts", action="store_true",
        help="v0.113: suppress alert banner (raw report only).",
    )
    p.add_argument(
        "--show-thresholds", action="store_true",
        help="v0.114: print resolved thresholds + config path "
             "as JSON, then exit.",
    )
    p.add_argument(
        "--project-id", default=None,
        help="v0.126: apply per-project threshold overlay "
             "from <cache>/projects/<pid>/health_thresholds.json.",
    )
    args = p.parse_args(argv)
    if args.show_thresholds:
        out = {
            "global_config_path": str(_config_path()),
            "global_config_exists": _config_path().exists(),
            "project_id": args.project_id,
            "project_config_path": (
                str(_project_config_path(args.project_id))
                if args.project_id else None
            ),
            "project_config_exists": (
                _project_config_path(args.project_id).exists()
                if args.project_id else False
            ),
            "thresholds": load_thresholds(
                project_id=args.project_id,
            ),
        }
        sys.stdout.write(json.dumps(out, indent=2) + "\n")
        return 0
    report = collect(max_age_minutes=args.max_age)
    alerts = (
        [] if args.no_alerts
        else evaluate_alerts(report, project_id=args.project_id)
    )
    if args.format == "json":
        out = dict(report)
        out["alerts"] = alerts
        sys.stdout.write(
            json.dumps(out, indent=2, default=str) + "\n"
        )
    else:
        sys.stdout.write(render_md(report, alerts=alerts))
    if any(a["severity"] == "crit" for a in alerts):
        return 2
    if alerts:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
