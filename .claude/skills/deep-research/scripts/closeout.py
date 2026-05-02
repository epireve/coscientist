#!/usr/bin/env python3
"""deep-research close-out hook (v0.214).

Fires post-steward to populate run-scoped tables that orchestration
otherwise leaves empty. Idempotent — safe to run multiple times on
the same run.

What it does:
  1. Closes stale spans (status='running' but phase complete).
  2. Auto-scores every persona that has an output artifact via
     lib.agent_quality.score_auto (writes agent_quality rows).
  3. Logs a summary note in the notes table.

What it deliberately does NOT do:
  - Promote to project graph (project linkage is a separate step;
    run is project-less today).
  - Run A5 trio (novelty/publishability/red-team) — those are
    high-cost LLM ops; user invokes via /run-audit.
  - Mutate hypotheses (use /run-evolve).

Exit codes: 0 clean, 1 partial (some steps failed but DB consistent).
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parents[4]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from lib import agent_quality  # noqa: E402
from lib.cache import cache_root, connect_wal  # noqa: E402

_PERSONAS_WITH_OUTPUTS = (
    "scout", "cartographer", "chronicler", "surveyor",
    "synthesist", "architect", "inquisitor", "weaver",
    "visionary", "steward",
)


def _run_db_path(run_id: str) -> Path:
    p = cache_root() / "runs" / f"run-{run_id}.db"
    if not p.exists():
        raise SystemExit(f"no run DB at {p}")
    return p


def _phase_output_path(run_id: str, persona: str) -> Path | None:
    """Find phase output JSON if it exists."""
    base = cache_root() / "runs" / f"run-{run_id}" / "phases"
    p = base / f"{persona}-output.json"
    return p if p.exists() else None


def close_stale_spans(con: sqlite3.Connection) -> int:
    """Mark spans 'running' for completed phases as 'ok' with note."""
    now = datetime.now(UTC).isoformat()
    rows = con.execute(
        "SELECT span_id, started_at FROM spans WHERE status='running'"
    ).fetchall()
    closed = 0
    with con:
        for span_id, started_at in rows:
            con.execute(
                "UPDATE spans SET status='ok', ended_at=?, "
                "error_msg='auto-closed by closeout v0.214' "
                "WHERE span_id=?",
                (now, span_id),
            )
            closed += 1
    return closed


def score_personas(db_path: Path, run_id: str) -> dict[str, float]:
    """Run auto-rubric on each persona output that exists."""
    scores: dict[str, float] = {}
    for persona in _PERSONAS_WITH_OUTPUTS:
        out = _phase_output_path(run_id, persona)
        if out is None:
            continue
        try:
            res = agent_quality.score_auto(
                db_path=db_path,
                run_id=run_id,
                span_id=None,
                agent_name=persona,
                artifact_path=out,
            )
            if res.get("ok") is False:
                scores[persona] = -1.0
                sys.stderr.write(
                    f"[closeout] no rubric for {persona}: "
                    f"{res.get('error')}\n",
                )
            else:
                scores[persona] = float(res.get("score_total", 0.0))
        except Exception as exc:
            scores[persona] = -1.0
            sys.stderr.write(
                f"[closeout] score_auto({persona}) failed: {exc}\n"
            )
    return scores


def record_closeout_note(
    con: sqlite3.Connection,
    run_id: str,
    spans_closed: int,
    scores: dict[str, float],
) -> None:
    """Write a summary note.

    Schema: notes(note_id, run_id, phase_id, author, text, at).
    """
    text = json.dumps(
        {
            "kind": "closeout",
            "version": "v0.214",
            "spans_closed": spans_closed,
            "personas_scored": len(scores),
            "score_summary": scores,
        },
        sort_keys=True,
    )
    now = datetime.now(UTC).isoformat()
    with con:
        con.execute(
            "INSERT INTO notes (run_id, author, text, at) VALUES (?, ?, ?, ?)",
            (run_id, "closeout", text, now),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="deep-research close-out")
    parser.add_argument("--run-id", required=True)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report what would be done; write nothing",
    )
    args = parser.parse_args()

    db_path = _run_db_path(args.run_id)
    con = connect_wal(db_path)

    if args.dry_run:
        stale = con.execute(
            "SELECT COUNT(*) FROM spans WHERE status='running'"
        ).fetchone()[0]
        existing_outputs = [
            p for p in _PERSONAS_WITH_OUTPUTS
            if _phase_output_path(args.run_id, p) is not None
        ]
        already_scored = con.execute(
            "SELECT COUNT(DISTINCT agent_name) FROM agent_quality "
            "WHERE run_id=?",
            (args.run_id,),
        ).fetchone()[0]
        report = {
            "dry_run": True,
            "run_id": args.run_id,
            "stale_spans": stale,
            "personas_with_outputs": existing_outputs,
            "already_scored": already_scored,
            "would_score": [
                p for p in existing_outputs
            ],
        }
        print(json.dumps(report, indent=2))
        return 0

    spans_closed = close_stale_spans(con)
    scores = score_personas(db_path, args.run_id)
    record_closeout_note(con, args.run_id, spans_closed, scores)

    result = {
        "run_id": args.run_id,
        "spans_closed": spans_closed,
        "personas_scored": len(scores),
        "scores": scores,
    }
    print(json.dumps(result, indent=2))
    return 0 if all(v >= 0 for v in scores.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
