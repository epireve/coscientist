"""v0.222 — health markdown rendering.

Split from lib/health.py for testability + size. Behavior unchanged.

Public API (re-exported by lib/health.py for back-compat):
  - render_md(report, *, alerts=...)
"""
from __future__ import annotations

from typing import Any


def render_md(report: dict[str, Any],
              *, alerts: list[dict] | None = None) -> str:
    lines = ["# Coscientist health", ""]
    if alerts:
        lines.append("## Alerts")
        lines.append("")
        for a in alerts:
            emoji = "🚨" if a["severity"] == "crit" else "⚠️"
            lines.append(
                f"- {emoji} **{a['code']}** {a['message']} "
                f"(threshold={a['threshold']})"
            )
        lines.append("")
    lines.append(f"- **Runs scanned**: {report['n_runs']}")
    n_unin = report.get("n_uninstrumented", 0)
    if n_unin:
        lines.append(
            f"- **Uninstrumented (pre-v0.89, no traces table)**: {n_unin}"
        )
    lines.append(f"- **Active**: {len(report['active'])}")
    lines.append(f"- **Stale spans**: {len(report['stale'])}")
    lines.append(
        f"- **Failed spans (total)**: {report['failed_spans_total']}"
    )
    lines.append("")

    if report["active"]:
        lines.append("## Active runs")
        lines.append("")
        for a in report["active"]:
            lines.append(
                f"- 🔄 `{a['trace_id']}` started {a['started_at']}"
            )
        lines.append("")

    if report["stale"]:
        lines.append("## Stale spans (still running)")
        lines.append("")
        for s in report["stale"]:
            lines.append(
                f"- ⏳ `{s['kind']}`/{s['name']} "
                f"(trace={s['trace_id'][:16]}) "
                f"age={s['age_minutes']}m"
            )
        lines.append("")

    by_tool = report["tool_latency"].get("by_tool", {})
    if by_tool:
        lines.append("## Tool-call latency (slowest first)")
        lines.append("")
        sorted_tools = sorted(
            by_tool.items(), key=lambda kv: -kv[1]["mean_ms"],
        )[:10]
        for name, d in sorted_tools:
            lines.append(
                f"- `{name}` n={d['n']} "
                f"errors={d['n_errors']} "
                f"mean={d['mean_ms']:.0f}ms "
                f"p95={d['p95_ms']}ms"
            )
        lines.append("")

    gates = report.get("gates") or {}
    by_gate = gates.get("by_gate", {})
    if by_gate:
        lines.append("## Gate decisions")
        lines.append("")
        for name, d in sorted(
            by_gate.items(), key=lambda kv: -kv[1]["n_rejected"],
        ):
            lines.append(
                f"- **{name}** ok={d['n_ok']} "
                f"rejected={d['n_rejected']} "
                f"(total={d['n_total']})"
            )
            for err in d["recent_errors"][:2]:
                lines.append(f"  - ❌ {err[:100]}")
        lines.append("")

    harvests = report.get("harvests") or {}
    by_persona = harvests.get("by_persona", {})
    if by_persona:
        lines.append("## Harvest activity (per persona)")
        lines.append("")
        for persona, d in sorted(
            by_persona.items(), key=lambda kv: -kv[1]["kept"],
        ):
            lines.append(
                f"- **{persona}** harvests={d['n']} "
                f"raw={d['raw']} → deduped={d['deduped']} "
                f"→ kept={d['kept']} (queries={d['queries']})"
            )
        lines.append("")

    by_agent = report["quality"].get("by_agent", {})
    if by_agent:
        lines.append("## Agent quality (lowest mean first)")
        lines.append("")
        sorted_agents = sorted(
            by_agent.items(), key=lambda kv: kv[1]["mean"],
        )
        for agent, d in sorted_agents:
            lines.append(
                f"- **{agent}** mean={d['mean']:.2f} "
                f"latest={d.get('latest_score', 0):.2f} "
                f"(n={d['n']}, runs={d['n_runs']})"
            )
        lines.append("")

    trees = report.get("trees") or {}
    if trees.get("n_trees_total", 0) > 0 or trees.get("by_run"):
        lines.append("## Tree tournaments")
        lines.append("")
        lines.append(
            f"- Trees: {trees.get('n_trees_total', 0)}"
        )
        lines.append(
            f"- Pruned hyp ids: {trees.get('n_pruned_total', 0)}"
        )
        for r in trees.get("by_run", [])[:5]:
            for top in r.get("top_per_tree", [])[:3]:
                lines.append(
                    f"  - tree `{top['tree_id']}` top "
                    f"`{top['top_hyp_id']}` "
                    f"Elo {round(top['top_elo'])}"
                )
        lines.append("")

    thinking = report.get("thinking") or {}
    by_table = thinking.get("by_table") or {}
    if any(d.get("n_total", 0) for d in by_table.values()):
        lines.append("## Thinking-trace coverage")
        lines.append("")
        for tbl, d in sorted(by_table.items()):
            if not d.get("n_total"):
                continue
            lines.append(
                f"- **{tbl}** {d['n_with_trace']}/{d['n_total']} "
                f"({d['coverage']:.0%})"
            )
        lines.append("")

    mcp_health = report.get("mcp_health") or {}
    degraded = [
        (n, d) for n, d in mcp_health.items()
        if (d.get("n_calls", 0) >= 5
            and d.get("error_rate", 0.0) > 0.5)
    ]
    if degraded:
        lines.append("## MCP source health")
        lines.append("")
        for name, d in sorted(degraded, key=lambda kv: -kv[1]["error_rate"]):
            lines.append(
                f"- **{name}** error_rate={d['error_rate']:.0%} "
                f"({d['n_errors']}/{d['n_calls']})"
            )
        lines.append("")

    if not (report["active"] or report["stale"]
            or by_tool or by_agent):
        lines.append("_No data — instrumentation hasn't logged yet._")
        lines.append("")
    return "\n".join(lines)
