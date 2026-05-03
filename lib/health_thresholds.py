"""v0.222 — health threshold resolution + alert derivation.

Split from lib/health.py for testability + size. Behavior unchanged.

Three layers, in increasing precedence:
  DEFAULT_THRESHOLDS < global config < per-project config < kwargs

Public API (re-exported by lib/health.py for back-compat):
  - DEFAULT_THRESHOLDS
  - load_thresholds(...)
  - evaluate_alerts(...)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# v0.113 — alert thresholds. Tunable via env, kwargs, or v0.114
# config file at ~/.cache/coscientist/health_thresholds.json.
DEFAULT_THRESHOLDS = {
    "max_stale_spans": 0,           # any stale = alert
    "max_failed_spans": 5,          # >5 failed = alert
    "max_tool_error_rate": 0.20,    # >20% errors per tool = alert
    "min_quality_score": 0.50,      # mean < 0.5 per agent = alert
    "max_active_runs": 10,          # parallel runs >10 = alert
    "max_quality_decline": -0.10,   # v0.127: drift delta below this = alert
    "drift_window": 5,              # v0.127: window size for drift check
    "min_thinking_coverage": 0.50,  # v0.170: per-table thinking-log coverage
    "thinking_min_rows": 5,         # v0.170: only alert when n_total > this
    "mcp_degraded_rate": 0.50,      # v0.188: MCP error_rate > this = alert
    "mcp_degraded_min_calls": 5,    # v0.188: only alert when n_calls >= this
    "mcp_window_hours": 24,         # v0.188: rolling window for MCP rates
}


def _config_path() -> Path:
    """v0.114 — global config file path."""
    from lib.cache import cache_root
    return cache_root() / "health_thresholds.json"


def _project_config_path(project_id: str) -> Path:
    """v0.126 — per-project config file path."""
    from lib.cache import cache_root
    return (
        cache_root() / "projects" / project_id /
        "health_thresholds.json"
    )


def _apply_overrides(
    out: dict[str, Any], data: Any,
) -> None:
    """Mutate `out` with type-checked values from `data` dict."""
    if not isinstance(data, dict):
        return
    for k, v in data.items():
        if k not in DEFAULT_THRESHOLDS:
            continue
        expected_type = type(DEFAULT_THRESHOLDS[k])
        if isinstance(v, expected_type):
            out[k] = v
        elif expected_type is float and isinstance(v, int):
            out[k] = float(v)


def _read_config(path: Path) -> dict[str, Any]:
    """Read config file; silent fallback on errors."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load_thresholds(
    *,
    overrides: dict[str, Any] | None = None,
    config_path: Path | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Resolve thresholds with precedence:
    DEFAULT_THRESHOLDS < global_config < project_config < overrides.
    """
    out = dict(DEFAULT_THRESHOLDS)
    cfg = config_path if config_path is not None else _config_path()
    _apply_overrides(out, _read_config(cfg))
    if project_id:
        _apply_overrides(
            out, _read_config(_project_config_path(project_id)),
        )
    if overrides:
        _apply_overrides(out, overrides)
    return out


def evaluate_alerts(
    report: dict[str, Any],
    *,
    thresholds: dict[str, Any] | None = None,
    config_path: Path | None = None,
    project_id: str | None = None,
) -> list[dict[str, Any]]:
    """Derive named alerts from a health report.

    Each alert: {severity: 'warn'|'crit', code, message, value,
    threshold}.
    """
    t = load_thresholds(
        overrides=thresholds, config_path=config_path,
        project_id=project_id,
    )
    alerts: list[dict[str, Any]] = []

    n_stale = len(report.get("stale", []))
    if n_stale > t["max_stale_spans"]:
        alerts.append({
            "severity": "warn", "code": "stale_spans",
            "message": f"{n_stale} stale span(s) past threshold",
            "value": n_stale,
            "threshold": t["max_stale_spans"],
        })

    n_failed = report.get("failed_spans_total", 0) or 0
    if n_failed > t["max_failed_spans"]:
        alerts.append({
            "severity": "crit", "code": "failed_spans",
            "message": f"{n_failed} failed spans across runs",
            "value": n_failed,
            "threshold": t["max_failed_spans"],
        })

    n_active = len(report.get("active", []))
    if n_active > t["max_active_runs"]:
        alerts.append({
            "severity": "warn", "code": "too_many_active",
            "message": f"{n_active} active runs",
            "value": n_active,
            "threshold": t["max_active_runs"],
        })

    by_tool = report.get("tool_latency", {}).get("by_tool", {}) or {}
    for name, d in by_tool.items():
        if d.get("n", 0) >= 5 and d.get("n_errors", 0) > 0:
            rate = d["n_errors"] / max(1, d["n"])
            if rate > t["max_tool_error_rate"]:
                alerts.append({
                    "severity": "crit",
                    "code": "tool_error_rate",
                    "message": (
                        f"{name} error rate "
                        f"{rate:.0%} ({d['n_errors']}/{d['n']})"
                    ),
                    "value": round(rate, 3),
                    "threshold": t["max_tool_error_rate"],
                })

    by_agent = report.get("quality", {}).get("by_agent", {}) or {}
    for agent, d in by_agent.items():
        if d.get("n", 0) >= 3 and d.get("mean", 1.0) < t["min_quality_score"]:
            alerts.append({
                "severity": "warn",
                "code": "low_quality",
                "message": (
                    f"{agent} mean {d['mean']:.2f} below "
                    f"{t['min_quality_score']:.2f}"
                ),
                "value": round(d["mean"], 3),
                "threshold": t["min_quality_score"],
            })

    # v0.170: thinking-trace coverage alerts (per-table)
    thinking = report.get("thinking", {}) or {}
    for tbl, d in (thinking.get("by_table") or {}).items():
        n_total = d.get("n_total", 0) or 0
        if n_total <= t["thinking_min_rows"]:
            continue
        cov = d.get("coverage", 0.0) or 0.0
        if cov < t["min_thinking_coverage"]:
            alerts.append({
                "severity": "warn",
                "code": "thinking_coverage_low",
                "message": (
                    f"{tbl} thinking-log coverage "
                    f"{cov:.0%} ({d.get('n_with_trace', 0)}/"
                    f"{n_total})"
                ),
                "value": round(cov, 3),
                "threshold": t["min_thinking_coverage"],
            })

    # v0.188: degraded-MCP alerts
    mcp_health = report.get("mcp_health") or {}
    for name, d in mcp_health.items():
        n_calls = d.get("n_calls", 0) or 0
        rate = d.get("error_rate", 0.0) or 0.0
        if (n_calls >= t["mcp_degraded_min_calls"]
                and rate > t["mcp_degraded_rate"]):
            alerts.append({
                "severity": "warn",
                "code": "mcp_degraded",
                "message": (
                    f"{name} error rate {rate:.0%} "
                    f"({d.get('n_errors', 0)}/{n_calls})"
                ),
                "value": round(rate, 3),
                "threshold": t["mcp_degraded_rate"],
            })

    # v0.127: drift alerts
    drift = report.get("drift", {}) or {}
    for agent, d in (drift.get("by_agent") or {}).items():
        if d.get("direction") == "declining":
            delta = d.get("delta_mean", 0)
            if delta <= t["max_quality_decline"]:
                alerts.append({
                    "severity": "warn",
                    "code": "quality_decline",
                    "message": (
                        f"{agent} declined {delta:+.2f} "
                        f"(latest {d['latest_window']['mean']:.2f} "
                        f"vs prior {d['prior_window']['mean']:.2f})"
                    ),
                    "value": delta,
                    "threshold": t["max_quality_decline"],
                })

    return alerts
