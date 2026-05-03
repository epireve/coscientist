"""v0.228 — trace data mutation: stale-close + prune.

Split from lib/trace_status.py. All functions here MUTATE run-*.db
(or delete entire DB files). Re-exported by lib/trace_status.py.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from lib.trace_status_query import _open, find_stale_spans


def mark_stale_error(
    db_path: Path, *, max_age_minutes: int = 30,
    reason: str = "stale-span auto-close",
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """v0.98 — close stale running spans by setting status='error'."""
    from datetime import UTC, datetime
    stale = find_stale_spans(
        db_path, max_age_minutes=max_age_minutes, now_iso=now_iso,
    )
    if not stale:
        return []
    now = datetime.now(UTC).isoformat() if now_iso is None else now_iso
    con = _open(db_path)
    try:
        with con:
            for s in stale:
                con.execute(
                    "UPDATE spans SET status='error', "
                    "error_kind='stale', error_msg=?, ended_at=? "
                    "WHERE span_id=? AND status='running'",
                    (reason, now, s["span_id"]),
                )
                s["closed_at"] = now
    finally:
        con.close()
    return stale


def prune_old_traces(
    db_path: Path, *, max_age_days: int = 30,
    dry_run: bool = False, now_iso: str | None = None,
) -> dict[str, Any]:
    """v0.110 — delete trace data older than `max_age_days`."""
    from datetime import UTC, datetime, timedelta
    if now_iso is None:
        now = datetime.now(UTC)
    else:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    cutoff = (now - timedelta(days=max_age_days)).isoformat()
    if not db_path.exists():
        return {"n_traces": 0, "n_spans": 0, "n_events": 0,
                "dry_run": dry_run}
    con = _open(db_path)
    try:
        try:
            stale = list(con.execute(
                "SELECT trace_id FROM traces "
                "WHERE status != 'running' "
                "AND COALESCE(completed_at, started_at) < ?",
                (cutoff,),
            ))
        except sqlite3.OperationalError:
            return {"n_traces": 0, "n_spans": 0, "n_events": 0,
                    "dry_run": dry_run}
        trace_ids = [r["trace_id"] for r in stale]
        if not trace_ids:
            return {"n_traces": 0, "n_spans": 0, "n_events": 0,
                    "dry_run": dry_run}
        placeholders = ",".join("?" * len(trace_ids))
        n_spans = con.execute(
            f"SELECT COUNT(*) FROM spans "
            f"WHERE trace_id IN ({placeholders})",
            trace_ids,
        ).fetchone()[0]
        n_events = con.execute(
            f"SELECT COUNT(*) FROM span_events "
            f"WHERE span_id IN (SELECT span_id FROM spans "
            f"WHERE trace_id IN ({placeholders}))",
            trace_ids,
        ).fetchone()[0]
        if not dry_run:
            with con:
                con.execute(
                    f"DELETE FROM span_events "
                    f"WHERE span_id IN (SELECT span_id FROM spans "
                    f"WHERE trace_id IN ({placeholders}))",
                    trace_ids,
                )
                con.execute(
                    f"DELETE FROM spans "
                    f"WHERE trace_id IN ({placeholders})",
                    trace_ids,
                )
                con.execute(
                    f"DELETE FROM traces "
                    f"WHERE trace_id IN ({placeholders})",
                    trace_ids,
                )
        return {"n_traces": len(trace_ids), "n_spans": int(n_spans),
                "n_events": int(n_events), "dry_run": dry_run}
    finally:
        con.close()


def prune_empty_run_dbs(
    *, dry_run: bool = False,
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.111 — delete run-*.db files with zero traces AND zero phases."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    deleted: list[str] = []
    skipped: list[str] = []
    if not root.exists():
        return {"n_deleted": 0, "deleted": [], "skipped": [],
                "dry_run": dry_run}
    for db in sorted(root.glob("run-*.db")):
        try:
            con = _open(db)
            try:
                try:
                    n_traces = con.execute(
                        "SELECT COUNT(*) FROM traces",
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    n_traces = 0
                try:
                    n_phases = con.execute(
                        "SELECT COUNT(*) FROM phases",
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    n_phases = 0
            finally:
                con.close()
        except Exception:
            skipped.append(str(db))
            continue
        if n_traces == 0 and n_phases == 0:
            if not dry_run:
                try:
                    db.unlink()
                    for suffix in ("-wal", "-shm"):
                        sidecar = db.parent / (db.name + suffix)
                        if sidecar.exists():
                            sidecar.unlink()
                except OSError:
                    skipped.append(str(db))
                    continue
            deleted.append(str(db))
        else:
            skipped.append(str(db))
    return {
        "n_deleted": len(deleted),
        "deleted": deleted,
        "skipped": skipped,
        "dry_run": dry_run,
    }
