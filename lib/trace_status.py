"""v0.95 — quick trace-status summary.

v0.228 — split into 3 modules (query, prune, render) for
testability + size. Facade re-exports public surface so
existing callers keep working unchanged.

Two surfaces:
  - `summarize_trace(db_path, trace_id)` → dict
  - `summarize_runs(roots=None)` → list[dict] across all run DBs

CLI:
    uv run python -m lib.trace_status                    # all runs
    uv run python -m lib.trace_status --run-id <rid>     # one run
    uv run python -m lib.trace_status --format md|json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lib.trace_status_prune import (
    mark_stale_error,
    prune_empty_run_dbs,
    prune_old_traces,
)
# Re-exports — preserve `from lib.trace_status import X` for callers.
from lib.trace_status_query import (
    _open,
    _runs_root,
    find_stale_spans,
    gate_summary,
    gate_summary_across_runs,
    harvest_summary,
    harvest_summary_across_runs,
    summarize_runs,
    summarize_trace,
    tool_call_latency,
    tool_call_latency_across_runs,
)
from lib.trace_status_render import render_md

__all__ = [
    "summarize_trace",
    "summarize_runs",
    "find_stale_spans",
    "gate_summary",
    "gate_summary_across_runs",
    "harvest_summary",
    "harvest_summary_across_runs",
    "tool_call_latency",
    "tool_call_latency_across_runs",
    "mark_stale_error",
    "prune_old_traces",
    "prune_empty_run_dbs",
    "render_md",
    "main",
]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="trace_status",
        description="Quick status across coscientist run traces.",
    )
    p.add_argument("--run-id", default=None,
                    help="Inspect one run; default scans all runs.")
    p.add_argument("--format", choices=("md", "json"), default="md")
    p.add_argument(
        "--stale-only", action="store_true",
        help="v0.97: list spans still running past --max-age minutes.",
    )
    p.add_argument("--max-age", type=int, default=30,
                    help="Stale threshold in minutes (default 30).")
    p.add_argument(
        "--mark-error", action="store_true",
        help="v0.98: mutate stale spans to status=error.",
    )
    p.add_argument(
        "--reason", default="stale-span auto-close",
        help="error_msg used when --mark-error fires.",
    )
    p.add_argument(
        "--tool-latency", action="store_true",
        help="v0.100: aggregate tool-call span durations by name.",
    )
    p.add_argument(
        "--prune", action="store_true",
        help="v0.110: delete trace data older than --prune-days.",
    )
    p.add_argument("--prune-days", type=int, default=30,
                    help="Age threshold for --prune (default 30).")
    p.add_argument("--dry-run", action="store_true",
                    help="With --prune or --prune-empty-dbs, "
                         "show counts without deleting.")
    p.add_argument(
        "--prune-empty-dbs", action="store_true",
        help="v0.111: delete run-*.db files with zero traces "
             "AND zero phases.",
    )
    args = p.parse_args(argv)
    if args.prune_empty_dbs:
        r = prune_empty_run_dbs(dry_run=args.dry_run)
        if args.format == "json":
            sys.stdout.write(
                json.dumps(r, indent=2, default=str) + "\n",
            )
        else:
            label = "Would delete" if args.dry_run else "Deleted"
            sys.stdout.write(
                f"# Prune empty run DBs\n\n"
                f"_{label} {r['n_deleted']} empty DB(s); "
                f"skipped {len(r['skipped'])} non-empty._\n",
            )
        return 0
    if args.prune:
        from lib.cache import run_db_path, runs_dir
        results: list[dict] = []
        if args.run_id:
            r = prune_old_traces(
                run_db_path(args.run_id),
                max_age_days=args.prune_days,
                dry_run=args.dry_run,
            )
            r["db_path"] = str(run_db_path(args.run_id))
            results.append(r)
        else:
            d = runs_dir()
            if d.exists():
                for db in sorted(d.glob("run-*.db")):
                    r = prune_old_traces(
                        db,
                        max_age_days=args.prune_days,
                        dry_run=args.dry_run,
                    )
                    r["db_path"] = str(db)
                    results.append(r)
        if args.format == "json":
            sys.stdout.write(
                json.dumps(results, indent=2, default=str) + "\n",
            )
        else:
            tot_t = sum(r["n_traces"] for r in results)
            tot_s = sum(r["n_spans"] for r in results)
            tot_e = sum(r["n_events"] for r in results)
            label = "Would delete" if args.dry_run else "Deleted"
            sys.stdout.write(
                f"# Prune ({args.prune_days} days)\n\n"
                f"_{label} {tot_t} trace(s), {tot_s} span(s), "
                f"{tot_e} event(s) across {len(results)} DB(s)._\n",
            )
        return 0
    if args.tool_latency:
        from lib.cache import run_db_path
        if args.run_id:
            out = tool_call_latency(
                run_db_path(args.run_id),
                trace_id=args.run_id,
            )
        else:
            out = tool_call_latency_across_runs()
        if args.format == "json":
            sys.stdout.write(json.dumps(out, indent=2,
                                         default=str) + "\n")
        else:
            lines = ["# Tool-call latency", "",
                     f"_{out['n_rows']} call(s)._", ""]
            for name, d in sorted(out["by_tool"].items(),
                                   key=lambda kv: -kv[1]["mean_ms"]):
                lines.append(
                    f"- `{name}` n={d['n']} "
                    f"errors={d['n_errors']} "
                    f"mean={d['mean_ms']:.0f}ms "
                    f"p50={d['p50_ms']}ms "
                    f"p95={d['p95_ms']}ms "
                    f"max={d['max_ms']}ms"
                )
            lines.append("")
            sys.stdout.write("\n".join(lines))
        return 0
    if args.stale_only:
        from lib.cache import run_db_path, runs_dir
        op = (
            (lambda db: mark_stale_error(
                db, max_age_minutes=args.max_age,
                reason=args.reason,
            ))
            if args.mark_error
            else (lambda db: find_stale_spans(
                db, max_age_minutes=args.max_age,
            ))
        )
        if args.run_id:
            stale = op(run_db_path(args.run_id))
        else:
            stale = []
            d = runs_dir()
            if d.exists():
                for db in sorted(d.glob("run-*.db")):
                    stale.extend(op(db))
        if args.format == "json":
            sys.stdout.write(json.dumps(stale, indent=2,
                                         default=str) + "\n")
        else:
            if not stale:
                sys.stdout.write("# Stale spans\n\n_None._\n")
            else:
                lines = ["# Stale spans (still running)", ""]
                for s in stale:
                    lines.append(
                        f"- ⏳ `{s['kind']}`/{s['name']} "
                        f"(span={s['span_id'][:16]}, "
                        f"trace={s['trace_id'][:16]}) "
                        f"age={s['age_minutes']}m"
                    )
                lines.append("")
                sys.stdout.write("\n".join(lines))
        return 0
    if args.run_id:
        from lib.cache import run_db_path
        s = summarize_trace(run_db_path(args.run_id), args.run_id)
        summaries = [s]
    else:
        summaries = summarize_runs()
    if args.format == "json":
        sys.stdout.write(json.dumps(summaries, indent=2,
                                     default=str) + "\n")
    else:
        sys.stdout.write(render_md(summaries))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
