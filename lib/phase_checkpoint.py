"""v0.225 — within-phase checkpointing for resume.

Personas process work in discrete units (papers triaged, hypotheses
scored, queries issued, ...). Crashing mid-phase used to mean
restarting the phase from unit 0. This module persists per-unit
state so resume skips done work.

Usage from a persona script:

    from lib.phase_checkpoint import is_done, record

    for paper_id in candidates:
        if is_done(run_id, "scout", "paper", paper_id):
            continue
        try:
            process(paper_id)
            record(run_id, "scout", "paper", paper_id, "done")
        except Exception as e:
            record(run_id, "scout", "paper", paper_id,
                   "failed", payload={"error": str(e)})

`db.py record-phase --retry` clears matching rows so a fresh
attempt starts from unit 0.

Pure stdlib. Best-effort: errors silenced so a checkpoint failure
never aborts the parent persona.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from lib.cache import connect_wal, run_db_path

VALID_STATES = ("done", "failed", "skipped")


def record(
    run_id: str,
    phase: str,
    unit_kind: str,
    unit_id: str,
    state: str,
    *,
    payload: Any | None = None,
) -> None:
    """Persist (run_id, phase, unit_kind, unit_id, state).

    Idempotent: re-recording the same (run, phase, kind, id)
    overwrites state + payload + at.
    """
    if state not in VALID_STATES:
        raise ValueError(
            f"state must be one of {VALID_STATES}, got {state!r}"
        )
    db = run_db_path(run_id)
    if not db.exists():
        return
    now = datetime.now(UTC).isoformat()
    payload_json = json.dumps(payload) if payload is not None else None
    try:
        con = connect_wal(db)
        with con:
            con.execute(
                "INSERT INTO phase_checkpoints "
                "(run_id, phase, unit_kind, unit_id, state, "
                " payload_json, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id, phase, unit_kind, unit_id) "
                "DO UPDATE SET state=excluded.state, "
                "payload_json=excluded.payload_json, "
                "at=excluded.at",
                (run_id, phase, unit_kind, unit_id,
                 state, payload_json, now),
            )
        con.close()
    except Exception:
        # Best-effort. Never let checkpointing break the persona.
        pass


def is_done(
    run_id: str, phase: str, unit_kind: str, unit_id: str,
) -> bool:
    """True iff (run, phase, kind, id) row exists with state='done'."""
    db = run_db_path(run_id)
    if not db.exists():
        return False
    try:
        con = connect_wal(db)
        try:
            row = con.execute(
                "SELECT state FROM phase_checkpoints "
                "WHERE run_id=? AND phase=? AND unit_kind=? "
                "AND unit_id=?",
                (run_id, phase, unit_kind, unit_id),
            ).fetchone()
        finally:
            con.close()
    except Exception:
        return False
    return bool(row) and row[0] == "done"


def done_units(
    run_id: str, phase: str, unit_kind: str | None = None,
) -> list[str]:
    """List unit_id values with state='done' for (run, phase[, kind])."""
    db = run_db_path(run_id)
    if not db.exists():
        return []
    sql = (
        "SELECT unit_id FROM phase_checkpoints "
        "WHERE run_id=? AND phase=? AND state='done'"
    )
    args: list[Any] = [run_id, phase]
    if unit_kind is not None:
        sql += " AND unit_kind=?"
        args.append(unit_kind)
    sql += " ORDER BY at ASC"
    try:
        con = connect_wal(db)
        try:
            return [r[0] for r in con.execute(sql, args).fetchall()]
        finally:
            con.close()
    except Exception:
        return []


def list_checkpoints(
    run_id: str, phase: str | None = None,
) -> list[dict[str, Any]]:
    """List all checkpoint rows for diagnostics. Newest first."""
    db = run_db_path(run_id)
    if not db.exists():
        return []
    sql = (
        "SELECT phase, unit_kind, unit_id, state, "
        "payload_json, at FROM phase_checkpoints "
        "WHERE run_id=?"
    )
    args: list[Any] = [run_id]
    if phase is not None:
        sql += " AND phase=?"
        args.append(phase)
    sql += " ORDER BY at DESC"
    try:
        con = connect_wal(db)
        try:
            rows = con.execute(sql, args).fetchall()
        finally:
            con.close()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({
            "phase": r[0],
            "unit_kind": r[1],
            "unit_id": r[2],
            "state": r[3],
            "payload": json.loads(r[4]) if r[4] else None,
            "at": r[5],
        })
    return out


def clear_phase(run_id: str, phase: str) -> int:
    """Delete every checkpoint for (run_id, phase). Returns count.

    Called by `db.py record-phase --retry` so the next attempt
    starts from unit 0.
    """
    db = run_db_path(run_id)
    if not db.exists():
        return 0
    try:
        con = connect_wal(db)
        with con:
            cur = con.execute(
                "DELETE FROM phase_checkpoints "
                "WHERE run_id=? AND phase=?",
                (run_id, phase),
            )
            n = cur.rowcount or 0
        con.close()
        return n
    except Exception:
        return 0


def progress(run_id: str, phase: str) -> dict[str, int]:
    """Counts per state for (run_id, phase). Useful for resume display."""
    db = run_db_path(run_id)
    out = {"done": 0, "failed": 0, "skipped": 0, "total": 0}
    if not db.exists():
        return out
    try:
        con = connect_wal(db)
        try:
            rows = con.execute(
                "SELECT state, COUNT(*) FROM phase_checkpoints "
                "WHERE run_id=? AND phase=? GROUP BY state",
                (run_id, phase),
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return out
    for state, n in rows:
        if state in out:
            out[state] = int(n or 0)
    out["total"] = sum(
        out[k] for k in ("done", "failed", "skipped")
    )
    return out
