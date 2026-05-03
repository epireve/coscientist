"""v0.228 — markdown render for trace summaries.

Split from lib/trace_status.py. Re-exported by lib/trace_status.py.
"""
from __future__ import annotations

from typing import Any


def render_md(summaries: list[dict[str, Any]]) -> str:
    if not summaries:
        return "# Trace status\n\n_No traces found._\n"
    lines = ["# Trace status", "",
             f"_{len(summaries)} trace(s)._", ""]
    for s in summaries:
        if not s.get("found"):
            err = s.get("error", "not found")
            lines.append(f"- ❓ `{s.get('trace_id', '?')}` — {err}")
            continue
        emoji = {"running": "🔄", "ok": "✅",
                 "error": "❌"}.get(s["status"], "·")
        kind_str = ", ".join(
            f"{k}={n}" for k, n in sorted(s["by_kind"].items())
        ) or "(none)"
        lines.append(
            f"- {emoji} `{s['trace_id']}` "
            f"run=`{s.get('run_id') or '-'}` "
            f"status={s['status']} "
            f"spans={s['n_spans']} "
            f"(ok={s['n_ok']}, run={s['n_running']}, "
            f"err={s['n_failed']}) "
            f"latest_phase=`{s.get('latest_phase') or '-'}`"
        )
        lines.append(f"  - kinds: {kind_str}")
        if s.get("latest_error"):
            e = s["latest_error"]
            lines.append(
                f"  - ❌ `{e['name']}` ({e['kind']}): "
                f"{(e['msg'] or '')[:100]}"
            )
    lines.append("")
    return "\n".join(lines)
