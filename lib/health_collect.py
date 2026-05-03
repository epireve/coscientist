"""v0.222 — health data collection. Walks every run-*.db.

Split from lib/health.py for testability + size. Behavior unchanged.

Public API (re-exported by lib/health.py for back-compat):
  - collect(...)
  - mcp_error_rates(...)
  - trees_summary_across_runs(...)
  - thinking_coverage_across_runs(...)
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

# v0.188 — MCP server name prefixes mapped to canonical source names
# used by lib.source_selector. Tool-call span names look like
# "mcp__<server>__<tool>" (e.g. "mcp__semantic-scholar__search_papers")
# OR are emitted as bare server-prefixed names in some paths. We
# match by substring on the canonical key.
_MCP_SOURCE_KEYS = (
    "consensus",
    "openalex",
    "semantic-scholar",
    "paper-search",
)

# v0.170 — tables that carry a `thinking_log_json` column.
_THINKING_TABLES = (
    "hypotheses",
    "attack_findings",
    "novelty_assessments",
    "publishability_verdicts",
)


def _tree_summary_for_db(db: Path) -> dict[str, Any]:
    """v0.170 — per-DB tree-tournament summary.

    Returns: {n_trees, top_per_tree: [{tree_id, top_hyp_id, top_elo}],
              n_pruned}.
    """
    out: dict[str, Any] = {
        "n_trees": 0, "top_per_tree": [], "n_pruned": 0,
    }
    if not db.exists():
        return out
    try:
        con = sqlite3.connect(db)
        con.row_factory = sqlite3.Row
        try:
            tree_rows = list(con.execute(
                "SELECT tree_id, hyp_id, elo FROM hypotheses "
                "WHERE tree_id IS NOT NULL "
                "ORDER BY tree_id ASC, elo DESC, hyp_id ASC",
            ))
        except sqlite3.OperationalError:
            con.close()
            return out
        seen_trees: set[str] = set()
        for r in tree_rows:
            tid = r["tree_id"]
            if tid in seen_trees:
                continue
            seen_trees.add(tid)
            out["top_per_tree"].append({
                "tree_id": tid,
                "top_hyp_id": r["hyp_id"],
                "top_elo": float(r["elo"] or 0.0),
            })
        out["n_trees"] = len(seen_trees)
        try:
            pruned = con.execute(
                "SELECT COUNT(*) FROM ("
                "  SELECT hyp_a AS h FROM tournament_matches "
                "  UNION SELECT hyp_b FROM tournament_matches"
                ") WHERE h NOT IN (SELECT hyp_id FROM hypotheses)",
            ).fetchone()[0]
            out["n_pruned"] = int(pruned or 0)
        except sqlite3.OperationalError:
            pass
        con.close()
    except Exception:
        pass
    return out


def _thinking_coverage_for_db(db: Path) -> dict[str, Any]:
    """v0.170 — per-table thinking-log coverage for a single run DB."""
    by_table: dict[str, dict] = {}
    if not db.exists():
        return {"by_table": by_table}
    try:
        con = sqlite3.connect(db)
    except Exception:
        return {"by_table": by_table}
    try:
        for tbl in _THINKING_TABLES:
            try:
                total = con.execute(
                    f"SELECT COUNT(*) FROM {tbl}",
                ).fetchone()[0]
                covered = con.execute(
                    f"SELECT COUNT(*) FROM {tbl} "
                    f"WHERE thinking_log_json IS NOT NULL",
                ).fetchone()[0]
            except sqlite3.OperationalError:
                continue
            if total == 0 and covered == 0:
                if tbl not in by_table:
                    by_table[tbl] = {
                        "n_total": 0, "n_with_trace": 0,
                        "coverage": 0.0,
                    }
                continue
            d = by_table.setdefault(tbl, {
                "n_total": 0, "n_with_trace": 0, "coverage": 0.0,
            })
            d["n_total"] += int(total or 0)
            d["n_with_trace"] += int(covered or 0)
    finally:
        con.close()
    return {"by_table": by_table}


def trees_summary_across_runs(
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.170 — aggregate tree-tournament summary across run DBs."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    out: dict[str, Any] = {
        "n_trees_total": 0, "n_pruned_total": 0,
        "by_run": [],
    }
    if not root.exists():
        return out
    for db in sorted(root.glob("run-*.db")):
        s = _tree_summary_for_db(db)
        if s["n_trees"] == 0 and s["n_pruned"] == 0:
            continue
        out["n_trees_total"] += s["n_trees"]
        out["n_pruned_total"] += s["n_pruned"]
        out["by_run"].append({
            "db_path": str(db),
            "n_trees": s["n_trees"],
            "n_pruned": s["n_pruned"],
            "top_per_tree": s["top_per_tree"],
        })
    return out


def thinking_coverage_across_runs(
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.170 — aggregate thinking-log coverage per table across runs."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    by_table: dict[str, dict] = {
        t: {"n_total": 0, "n_with_trace": 0, "coverage": 0.0}
        for t in _THINKING_TABLES
    }
    if not root.exists():
        return {"by_table": by_table}
    for db in sorted(root.glob("run-*.db")):
        s = _thinking_coverage_for_db(db)
        for tbl, d in (s.get("by_table") or {}).items():
            agg = by_table.setdefault(tbl, {
                "n_total": 0, "n_with_trace": 0, "coverage": 0.0,
            })
            agg["n_total"] += d["n_total"]
            agg["n_with_trace"] += d["n_with_trace"]
    for tbl, d in by_table.items():
        d["coverage"] = (
            d["n_with_trace"] / d["n_total"]
            if d["n_total"] > 0 else 0.0
        )
        d["coverage"] = round(d["coverage"], 4)
    return {"by_table": by_table}


def mcp_error_rates(
    *,
    window_hours: int = 24,
    roots: list[Path] | None = None,
) -> dict[str, dict[str, Any]]:
    """v0.188 — aggregate tool-call error rates per MCP server."""
    from datetime import UTC, datetime, timedelta

    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    out: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return out
    cutoff = (
        datetime.now(UTC) - timedelta(hours=window_hours)
    ).isoformat()
    for db in sorted(root.glob("run-*.db")):
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
        except Exception:
            continue
        try:
            try:
                rows = list(con.execute(
                    "SELECT name, status, started_at FROM spans "
                    "WHERE kind='tool-call' AND started_at >= ?",
                    (cutoff,),
                ))
            except sqlite3.OperationalError:
                continue
            for r in rows:
                name = (r["name"] or "").lower()
                for key in _MCP_SOURCE_KEYS:
                    if key in name:
                        d = out.setdefault(key, {
                            "n_calls": 0, "n_errors": 0,
                            "error_rate": 0.0,
                        })
                        d["n_calls"] += 1
                        if r["status"] == "error":
                            d["n_errors"] += 1
                        break
        finally:
            con.close()
    for d in out.values():
        n = d["n_calls"]
        d["error_rate"] = (
            round(d["n_errors"] / n, 4) if n else 0.0
        )
    return out


def collect(*, max_age_minutes: int = 30) -> dict[str, Any]:
    """Walk every run-*.db and aggregate health signals."""
    from lib import agent_quality, trace_status
    from lib.cache import runs_dir

    root = runs_dir()
    if not root.exists():
        return {
            "n_runs": 0, "n_uninstrumented": 0,
            "uninstrumented_paths": [],
            "active": [], "stale": [],
            "tool_latency": {}, "quality": {},
            "failed_spans_total": 0,
        }

    active: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    failed_total = 0
    n_runs = 0
    n_uninstrumented = 0  # v0.184 — DBs lacking traces table (pre-v0.89)
    uninstrumented_paths: list[str] = []

    for db in sorted(root.glob("run-*.db")):
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            try:
                traces = list(con.execute(
                    "SELECT trace_id, run_id, status, started_at "
                    "FROM traces",
                ))
            except sqlite3.OperationalError:
                n_uninstrumented += 1
                uninstrumented_paths.append(str(db))
                con.close()
                continue
            n_runs += 1
            for t in traces:
                if t["status"] == "running":
                    active.append({
                        "trace_id": t["trace_id"],
                        "run_id": t["run_id"],
                        "started_at": t["started_at"],
                        "db_path": str(db),
                    })
                try:
                    nfail = con.execute(
                        "SELECT COUNT(*) FROM spans "
                        "WHERE trace_id=? AND status='error'",
                        (t["trace_id"],),
                    ).fetchone()[0]
                    failed_total += int(nfail)
                except sqlite3.OperationalError:
                    pass
            con.close()
        except Exception:
            continue
        try:
            stale.extend(trace_status.find_stale_spans(
                db, max_age_minutes=max_age_minutes,
            ))
        except Exception:
            pass

    try:
        tool_latency = trace_status.tool_call_latency_across_runs()
    except Exception:
        tool_latency = {"n_rows": 0, "by_tool": {}}
    try:
        quality = agent_quality.leaderboard()
    except Exception:
        quality = {"n_rows": 0, "by_agent": {}}
    try:
        harvests = trace_status.harvest_summary_across_runs()
    except Exception:
        harvests = {"n_harvests": 0, "by_persona": {},
                    "totals": {"raw": 0, "deduped": 0,
                                "kept": 0, "queries": 0}}
    try:
        gates = trace_status.gate_summary_across_runs()
    except Exception:
        gates = {"n_gates": 0, "by_gate": {}}
    try:
        drift = agent_quality.quality_drift()
    except Exception:
        drift = {"n_rows": 0, "by_agent": {}}
    try:
        trees = trees_summary_across_runs()
    except Exception:
        trees = {"n_trees_total": 0, "n_pruned_total": 0, "by_run": []}
    try:
        thinking = thinking_coverage_across_runs()
    except Exception:
        thinking = {"by_table": {}}
    try:
        mcp_health = mcp_error_rates()
    except Exception:
        mcp_health = {}

    return {
        "n_runs": n_runs,
        "n_uninstrumented": n_uninstrumented,
        "uninstrumented_paths": uninstrumented_paths,
        "active": active,
        "stale": stale,
        "tool_latency": tool_latency,
        "quality": quality,
        "harvests": harvests,
        "gates": gates,
        "drift": drift,
        "trees": trees,
        "thinking": thinking,
        "mcp_health": mcp_health,
        "failed_spans_total": failed_total,
    }
