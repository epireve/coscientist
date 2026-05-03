"""v0.228 — read-only trace status queries.

Split from lib/trace_status.py. All functions here are pure reads
against run-*.db. No mutations. Re-exported by lib/trace_status.py.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _runs_root() -> Path:
    """Default: ~/.cache/coscientist/runs/."""
    from lib.cache import runs_dir
    return runs_dir()


def _open(db: Path) -> sqlite3.Connection:
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    return con


def summarize_trace(db_path: Path, trace_id: str) -> dict[str, Any]:
    """Return concise status for one trace."""
    if not db_path.exists():
        return {"found": False, "trace_id": trace_id,
                "error": f"db not found: {db_path}"}
    con = _open(db_path)
    try:
        try:
            t = con.execute(
                "SELECT * FROM traces WHERE trace_id=?",
                (trace_id,),
            ).fetchone()
        except sqlite3.OperationalError:
            return {"found": False, "trace_id": trace_id,
                    "error": "no traces table (pre-v11 db)"}
        if t is None:
            return {"found": False, "trace_id": trace_id}
        spans = list(con.execute(
            "SELECT span_id, name, kind, status, error_kind, "
            "error_msg, started_at FROM spans "
            "WHERE trace_id=? ORDER BY started_at",
            (trace_id,),
        ))
        by_kind: dict[str, int] = {}
        n_failed = n_running = n_ok = 0
        latest_phase = None
        latest_error = None
        for s in spans:
            k = s["kind"]
            by_kind[k] = by_kind.get(k, 0) + 1
            if s["status"] == "error":
                n_failed += 1
                latest_error = {
                    "span_id": s["span_id"],
                    "name": s["name"],
                    "kind": k,
                    "msg": s["error_msg"],
                }
            elif s["status"] == "running":
                n_running += 1
            elif s["status"] == "ok":
                n_ok += 1
            if k == "phase":
                latest_phase = s["name"]
        return {
            "found": True,
            "trace_id": t["trace_id"],
            "run_id": t["run_id"],
            "status": t["status"],
            "started_at": t["started_at"],
            "completed_at": t["completed_at"],
            "n_spans": len(spans),
            "n_failed": n_failed,
            "n_running": n_running,
            "n_ok": n_ok,
            "by_kind": by_kind,
            "latest_phase": latest_phase,
            "latest_error": latest_error,
        }
    finally:
        con.close()


def summarize_runs(roots: list[Path] | None = None) -> list[dict[str, Any]]:
    """Walk all run DBs and summarize each trace they contain."""
    out: list[dict[str, Any]] = []
    root = roots[0] if roots else _runs_root()
    if not root.exists():
        return out
    for db in sorted(root.glob("run-*.db")):
        try:
            con = _open(db)
            try:
                traces = list(con.execute("SELECT trace_id FROM traces"))
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
            for r in traces:
                tid = r["trace_id"]
                summary = summarize_trace(db, tid)
                summary["db_path"] = str(db)
                out.append(summary)
        except Exception as e:
            out.append({"db_path": str(db), "error": str(e),
                        "found": False})
    return out


def find_stale_spans(
    db_path: Path, *, max_age_minutes: int = 30,
    now_iso: str | None = None,
) -> list[dict[str, Any]]:
    """v0.97 — return spans still status='running' past `max_age_minutes`."""
    from datetime import UTC, datetime, timedelta
    if now_iso is None:
        now = datetime.now(UTC)
    else:
        now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    cutoff = now - timedelta(minutes=max_age_minutes)
    if not db_path.exists():
        return []
    con = _open(db_path)
    try:
        try:
            rows = list(con.execute(
                "SELECT span_id, trace_id, kind, name, started_at "
                "FROM spans WHERE status='running' "
                "ORDER BY started_at",
            ))
        except sqlite3.OperationalError:
            return []
    finally:
        con.close()
    out: list[dict[str, Any]] = []
    for r in rows:
        try:
            started = datetime.fromisoformat(
                r["started_at"].replace("Z", "+00:00"),
            )
        except (ValueError, AttributeError):
            continue
        if started < cutoff:
            age = int((now - started).total_seconds() / 60)
            out.append({
                "span_id": r["span_id"],
                "trace_id": r["trace_id"],
                "kind": r["kind"],
                "name": r["name"],
                "started_at": r["started_at"],
                "age_minutes": age,
            })
    return out


def gate_summary(
    db_path: Path, *, trace_id: str | None = None,
) -> dict[str, Any]:
    """v0.109 — aggregate gate-kind span outcomes by gate name."""
    if not db_path.exists():
        return {"n_gates": 0, "by_gate": {}}
    con = _open(db_path)
    try:
        try:
            if trace_id:
                rows = list(con.execute(
                    "SELECT name, status, attrs_json, error_msg "
                    "FROM spans WHERE trace_id=? AND kind='gate' "
                    "ORDER BY started_at DESC",
                    (trace_id,),
                ))
            else:
                rows = list(con.execute(
                    "SELECT name, status, attrs_json, error_msg "
                    "FROM spans WHERE kind='gate' "
                    "ORDER BY started_at DESC",
                ))
        except sqlite3.OperationalError:
            return {"n_gates": 0, "by_gate": {}}
    finally:
        con.close()
    by_gate: dict[str, dict] = {}
    for r in rows:
        name = r["name"] or "?"
        d = by_gate.setdefault(
            name,
            {"n_total": 0, "n_ok": 0, "n_rejected": 0,
             "recent_errors": []},
        )
        d["n_total"] += 1
        verdict = None
        if r["attrs_json"]:
            try:
                attrs = json.loads(r["attrs_json"])
                verdict = attrs.get("verdict")
            except json.JSONDecodeError:
                pass
        if verdict == "ok":
            d["n_ok"] += 1
        elif verdict == "rejected":
            d["n_rejected"] += 1
        elif r["status"] == "error":
            d["n_rejected"] += 1
        elif r["status"] == "ok":
            d["n_ok"] += 1
        if (r["status"] == "error" and r["error_msg"]
                and len(d["recent_errors"]) < 3):
            d["recent_errors"].append(r["error_msg"][:120])
    return {"n_gates": len(rows), "by_gate": by_gate}


def gate_summary_across_runs(
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.109 — gate summary aggregated across every run DB."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    by_gate: dict[str, dict] = {}
    n_gates = 0
    n_dbs = 0
    if not root.exists():
        return {"n_gates": 0, "n_dbs": 0, "by_gate": {}}
    for db in sorted(root.glob("run-*.db")):
        try:
            s = gate_summary(db)
        except Exception:
            continue
        if s["n_gates"] == 0:
            try:
                con = _open(db)
                try:
                    con.execute("SELECT 1 FROM traces LIMIT 1")
                    n_dbs += 1
                except sqlite3.OperationalError:
                    pass
                con.close()
            except Exception:
                pass
            continue
        n_dbs += 1
        n_gates += s["n_gates"]
        for name, d in s["by_gate"].items():
            agg = by_gate.setdefault(
                name,
                {"n_total": 0, "n_ok": 0, "n_rejected": 0,
                 "recent_errors": []},
            )
            for k in ("n_total", "n_ok", "n_rejected"):
                agg[k] += d[k]
            for e in d["recent_errors"]:
                if len(agg["recent_errors"]) < 5:
                    agg["recent_errors"].append(e)
    return {"n_gates": n_gates, "n_dbs": n_dbs,
             "by_gate": by_gate}


def harvest_summary(
    db_path: Path, *, trace_id: str | None = None,
) -> dict[str, Any]:
    """v0.108 — aggregate harvest_write events across spans."""
    if not db_path.exists():
        return {"n_harvests": 0, "by_persona": {},
                "totals": {"raw": 0, "deduped": 0,
                           "kept": 0, "queries": 0}}
    con = _open(db_path)
    try:
        try:
            if trace_id:
                rows = list(con.execute(
                    "SELECT s.name, e.payload_json FROM spans s "
                    "JOIN span_events e ON s.span_id = e.span_id "
                    "WHERE s.trace_id=? AND s.kind='harvest' "
                    "AND e.name='harvest_write'",
                    (trace_id,),
                ))
            else:
                rows = list(con.execute(
                    "SELECT s.name, e.payload_json FROM spans s "
                    "JOIN span_events e ON s.span_id = e.span_id "
                    "WHERE s.kind='harvest' "
                    "AND e.name='harvest_write'",
                ))
        except sqlite3.OperationalError:
            return {"n_harvests": 0, "by_persona": {},
                    "totals": {"raw": 0, "deduped": 0,
                               "kept": 0, "queries": 0}}
    finally:
        con.close()
    by_persona: dict[str, dict] = {}
    tot = {"raw": 0, "deduped": 0, "kept": 0, "queries": 0}
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except json.JSONDecodeError:
            continue
        persona = (r["name"] or "").split("/", 1)[0] or "?"
        d = by_persona.setdefault(
            persona,
            {"n": 0, "raw": 0, "deduped": 0,
             "kept": 0, "queries": 0},
        )
        d["n"] += 1
        for src, dst in (("raw_count", "raw"),
                          ("deduped_count", "deduped"),
                          ("kept_count", "kept"),
                          ("queries_sent", "queries")):
            v = payload.get(src) or 0
            try:
                v = int(v)
            except (TypeError, ValueError):
                v = 0
            d[dst] += v
            tot[dst] += v
    return {
        "n_harvests": len(rows),
        "by_persona": by_persona,
        "totals": tot,
    }


def harvest_summary_across_runs(
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.108 — harvest summary aggregated across every run DB."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    by_persona: dict[str, dict] = {}
    tot = {"raw": 0, "deduped": 0, "kept": 0, "queries": 0}
    n_harvests = 0
    n_dbs = 0
    if not root.exists():
        return {"n_harvests": 0, "n_dbs": 0,
                "by_persona": {}, "totals": tot}
    for db in sorted(root.glob("run-*.db")):
        try:
            s = harvest_summary(db)
        except Exception:
            continue
        if s["n_harvests"] == 0 and not s["by_persona"]:
            try:
                con = _open(db)
                try:
                    con.execute("SELECT 1 FROM traces LIMIT 1")
                    n_dbs += 1
                except sqlite3.OperationalError:
                    pass
                con.close()
            except Exception:
                pass
            continue
        n_dbs += 1
        n_harvests += s["n_harvests"]
        for persona, d in s["by_persona"].items():
            agg = by_persona.setdefault(
                persona,
                {"n": 0, "raw": 0, "deduped": 0,
                 "kept": 0, "queries": 0},
            )
            for k in ("n", "raw", "deduped", "kept", "queries"):
                agg[k] += d[k]
        for k in tot:
            tot[k] += s["totals"][k]
    return {
        "n_harvests": n_harvests,
        "n_dbs": n_dbs,
        "by_persona": by_persona,
        "totals": tot,
    }


def tool_call_latency(
    db_path: Path, *, trace_id: str | None = None,
) -> dict[str, Any]:
    """v0.100 — aggregate tool-call span durations by tool name."""
    if not db_path.exists():
        return {"n_rows": 0, "by_tool": {}}
    con = _open(db_path)
    try:
        try:
            if trace_id:
                rows = list(con.execute(
                    "SELECT name, duration_ms, status FROM spans "
                    "WHERE trace_id=? AND kind='tool-call' "
                    "AND duration_ms IS NOT NULL",
                    (trace_id,),
                ))
            else:
                rows = list(con.execute(
                    "SELECT name, duration_ms, status FROM spans "
                    "WHERE kind='tool-call' "
                    "AND duration_ms IS NOT NULL",
                ))
        except sqlite3.OperationalError:
            return {"n_rows": 0, "by_tool": {}}
    finally:
        con.close()
    by_tool: dict[str, dict] = {}
    for r in rows:
        d = by_tool.setdefault(
            r["name"],
            {"n": 0, "n_errors": 0, "durations": []},
        )
        d["n"] += 1
        if r["status"] == "error":
            d["n_errors"] += 1
        d["durations"].append(int(r["duration_ms"]))
    for name, d in by_tool.items():
        durs = sorted(d.pop("durations"))
        n = len(durs)
        d["mean_ms"] = sum(durs) / n if n else 0.0
        d["p50_ms"] = durs[n // 2] if n else 0
        d["p95_ms"] = durs[min(n - 1, int(n * 0.95))] if n else 0
        d["max_ms"] = durs[-1] if n else 0
    return {"n_rows": len(rows), "by_tool": by_tool}


def tool_call_latency_across_runs(
    roots: list[Path] | None = None,
) -> dict[str, Any]:
    """v0.100 — tool-call latency aggregated across every run DB."""
    from lib.cache import runs_dir
    root = roots[0] if roots else runs_dir()
    by_tool: dict[str, dict] = {}
    n_dbs = 0
    n_rows = 0
    if not root.exists():
        return {"n_rows": 0, "n_dbs": 0, "by_tool": {}}
    for db in sorted(root.glob("run-*.db")):
        try:
            con = _open(db)
            try:
                rows = list(con.execute(
                    "SELECT name, duration_ms, status FROM spans "
                    "WHERE kind='tool-call' "
                    "AND duration_ms IS NOT NULL",
                ))
            except sqlite3.OperationalError:
                con.close()
                continue
            con.close()
            n_dbs += 1
            n_rows += len(rows)
            for r in rows:
                d = by_tool.setdefault(
                    r["name"],
                    {"n": 0, "n_errors": 0, "durations": []},
                )
                d["n"] += 1
                if r["status"] == "error":
                    d["n_errors"] += 1
                d["durations"].append(int(r["duration_ms"]))
        except Exception:
            continue
    for name, d in by_tool.items():
        durs = sorted(d.pop("durations"))
        n = len(durs)
        d["mean_ms"] = sum(durs) / n if n else 0.0
        d["p50_ms"] = durs[n // 2] if n else 0
        d["p95_ms"] = durs[min(n - 1, int(n * 0.95))] if n else 0
        d["max_ms"] = durs[-1] if n else 0
    return {"n_rows": n_rows, "n_dbs": n_dbs, "by_tool": by_tool}
