"""v0.227 — agent quality aggregation: list/summary/leaderboard/drift.

Split from lib/agent_quality.py. Behavior unchanged. Public surface
re-exported by lib/agent_quality.py.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path


def list_for_run(db_path: Path, run_id: str) -> list[dict]:
    """Return every quality row for `run_id`, newest first."""
    from lib.cache import connect_wal
    con = connect_wal(Path(db_path))
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM agent_quality WHERE run_id=? "
            "ORDER BY at DESC",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


def summary(db_path: Path, *, run_id: str | None = None) -> dict:
    """Per-agent summary across runs (or one run if `run_id` set)."""
    from lib.cache import connect_wal
    con = connect_wal(Path(db_path))
    try:
        con.row_factory = sqlite3.Row
        if run_id:
            rows = con.execute(
                "SELECT agent_name, score_total, at FROM agent_quality "
                "WHERE run_id=?", (run_id,),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT agent_name, score_total, at FROM agent_quality"
            ).fetchall()
        by_agent: dict[str, dict] = {}
        for r in rows:
            d = by_agent.setdefault(
                r["agent_name"],
                {"n": 0, "scores": [], "latest_at": None,
                 "latest_score": None},
            )
            d["n"] += 1
            d["scores"].append(float(r["score_total"]))
            if d["latest_at"] is None or r["at"] > d["latest_at"]:
                d["latest_at"] = r["at"]
                d["latest_score"] = float(r["score_total"])
        for agent_name, d in by_agent.items():
            scores = d.pop("scores")
            d["mean"] = sum(scores) / len(scores) if scores else 0.0
            d["min"] = min(scores) if scores else 0.0
            d["max"] = max(scores) if scores else 0.0
        return {"n_rows": len(rows), "by_agent": by_agent}
    finally:
        con.close()


def leaderboard(roots: list[Path] | None = None) -> dict:
    """v0.96 — per-agent quality summary across every run DB."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    by_agent: dict[str, dict] = {}
    n_dbs = 0
    if not root.exists():
        return {"n_rows": 0, "n_dbs": 0, "by_agent": {}}
    for db in sorted(root.glob("run-*.db")):
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT agent_name, score_total, at, run_id "
                    "FROM agent_quality"
                ).fetchall()
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
            n_dbs += 1
            for r in rows:
                d = by_agent.setdefault(
                    r["agent_name"],
                    {"n": 0, "scores": [], "run_ids": set(),
                     "latest_at": None, "latest_score": None},
                )
                d["n"] += 1
                d["scores"].append(float(r["score_total"]))
                if r["run_id"]:
                    d["run_ids"].add(r["run_id"])
                if d["latest_at"] is None or r["at"] > d["latest_at"]:
                    d["latest_at"] = r["at"]
                    d["latest_score"] = float(r["score_total"])
        except Exception:
            continue
    n_rows = 0
    for agent_name, d in by_agent.items():
        scores = d.pop("scores")
        run_ids = d.pop("run_ids")
        d["n_runs"] = len(run_ids)
        d["mean"] = sum(scores) / len(scores) if scores else 0.0
        d["min"] = min(scores) if scores else 0.0
        d["max"] = max(scores) if scores else 0.0
        n_rows += d["n"]
    return {"n_rows": n_rows, "n_dbs": n_dbs, "by_agent": by_agent}


def quality_drift(
    *,
    window: int = 5,
    roots: list[Path] | None = None,
    threshold: float = 0.05,
) -> dict:
    """v0.127 — per-agent score drift over time."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    if window < 1:
        window = 1
    series: dict[str, list[tuple[str, float]]] = {}
    n_dbs = 0
    if not root.exists():
        return {"n_rows": 0, "n_dbs": 0,
                "window": window, "by_agent": {}}
    for db in sorted(root.glob("run-*.db")):
        try:
            con = sqlite3.connect(db)
            con.row_factory = sqlite3.Row
            try:
                rows = con.execute(
                    "SELECT agent_name, score_total, at "
                    "FROM agent_quality"
                ).fetchall()
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
            n_dbs += 1
            for r in rows:
                series.setdefault(r["agent_name"], []).append(
                    (r["at"], float(r["score_total"])),
                )
        except Exception:
            continue

    by_agent: dict[str, dict] = {}
    n_rows = 0
    for agent, points in series.items():
        points.sort(key=lambda p: p[0])
        n_total = len(points)
        n_rows += n_total
        latest = points[-window:]
        prior = points[-(2 * window):-window] if n_total >= 2 else []
        latest_scores = [p[1] for p in latest]
        prior_scores = [p[1] for p in prior]
        latest_mean = (
            sum(latest_scores) / len(latest_scores)
            if latest_scores else 0.0
        )
        prior_mean = (
            sum(prior_scores) / len(prior_scores)
            if prior_scores else 0.0
        )
        delta = latest_mean - prior_mean if prior_scores else 0.0
        if (len(latest_scores) < window
                or len(prior_scores) < window):
            direction = "insufficient"
        elif delta > threshold:
            direction = "improving"
        elif delta < -threshold:
            direction = "declining"
        else:
            direction = "stable"
        by_agent[agent] = {
            "n_total": n_total,
            "latest_window": {
                "n": len(latest_scores),
                "mean": round(latest_mean, 3),
                "scores": [round(s, 3) for s in latest_scores],
            },
            "prior_window": {
                "n": len(prior_scores),
                "mean": round(prior_mean, 3),
                "scores": [round(s, 3) for s in prior_scores],
            },
            "delta_mean": round(delta, 3),
            "direction": direction,
        }
    return {
        "n_rows": n_rows, "n_dbs": n_dbs,
        "window": window, "by_agent": by_agent,
    }
