"""v0.227 — agent quality scoring (auto-rubric + llm-judge protocol).

Split from lib/agent_quality.py. Behavior unchanged. Public surface
re-exported by lib/agent_quality.py.

Three modes converge on the same `agent_quality` table row schema:
  - auto-rubric: pure-stdlib structural checks
  - llm-judge: emit_judge_prompt -> sub-agent -> persist_judge_result
  - ranker: deferred (v0.93)
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.agent_quality_rubrics import RUBRICS, Criterion


def _normalize_total(criteria: tuple[Criterion, ...],
                     scores: dict[str, float]) -> float:
    total_weight = sum(c.weight for c in criteria) or 1.0
    weighted = sum(c.weight * scores.get(c.name, 0.0) for c in criteria)
    return weighted / total_weight


def score_auto(
    db_path: Path,
    *,
    run_id: str | None,
    span_id: str | None,
    agent_name: str,
    artifact_path: Path,
    rubric_name: str | None = None,
) -> dict[str, Any]:
    """Auto-rubric scoring for a persona."""
    rubric = RUBRICS.get(rubric_name or agent_name)
    if rubric is None:
        return {
            "ok": False,
            "error": f"no rubric for agent {agent_name!r}",
        }
    artifact = rubric.loader(Path(artifact_path))
    per_criterion: dict[str, float] = {}
    for c in rubric.criteria:
        try:
            per_criterion[c.name] = float(c.check(artifact))
        except Exception:  # noqa: BLE001
            per_criterion[c.name] = 0.0
            per_criterion[f"{c.name}__error"] = -1.0
    score_total = _normalize_total(rubric.criteria, per_criterion)
    persisted = _persist(
        db_path=db_path,
        run_id=run_id, span_id=span_id, agent_name=agent_name,
        rubric_version=rubric.version,
        score_total=score_total,
        criteria_json=json.dumps(per_criterion, sort_keys=True),
        judge="auto-rubric",
        artifact_path=str(artifact_path),
        reasoning=None,
        notes=None,
    )
    return {
        "ok": True,
        "agent_name": agent_name,
        "rubric_version": rubric.version,
        "score_total": score_total,
        "criteria": per_criterion,
        "judge": "auto-rubric",
        "quality_id": persisted,
    }


def emit_judge_prompt(
    agent_name: str,
    artifact_path: Path,
    *,
    rubric_name: str | None = None,
) -> dict[str, Any]:
    """v0.92b — produce the structured prompt the `quality-judge`
    sub-agent consumes."""
    rubric = RUBRICS.get(rubric_name or agent_name)
    if rubric is None:
        return {"ok": False, "error": f"no rubric for {agent_name!r}"}
    artifact_text = ""
    p = Path(artifact_path)
    if p.exists():
        try:
            artifact_text = p.read_text()
        except OSError as e:
            artifact_text = f"<read error: {e}>"
    return {
        "ok": True,
        "agent_name": agent_name,
        "rubric_version": rubric.version,
        "rubric_description": rubric.description,
        "artifact_path": str(p),
        "artifact_text": artifact_text[:16000],
        "criteria": [
            {
                "name": c.name,
                "weight": c.weight,
                "description": c.description,
            }
            for c in rubric.criteria
        ],
        "instructions": (
            "Score each criterion on a 0.0–1.0 scale. Return a JSON "
            "object: {\"scores\": {<criterion>: float}, "
            "\"reasoning\": <one paragraph>}. Be honest — low "
            "scores when warranted are more useful than inflated "
            "praise."
        ),
    }


def persist_judge_result(
    db_path: Path,
    *,
    run_id: str | None,
    span_id: str | None,
    agent_name: str,
    artifact_path: Path,
    judge_json: dict,
    rubric_name: str | None = None,
) -> dict[str, Any]:
    """Validate + persist the `quality-judge` sub-agent's output."""
    rubric = RUBRICS.get(rubric_name or agent_name)
    if rubric is None:
        return {"ok": False, "error": f"no rubric for {agent_name!r}"}
    scores = (judge_json or {}).get("scores") or {}
    per_criterion = {
        c.name: float(scores.get(c.name, 0.0))
        for c in rubric.criteria
    }
    score_total = _normalize_total(rubric.criteria, per_criterion)
    qid = _persist(
        db_path=db_path,
        run_id=run_id, span_id=span_id, agent_name=agent_name,
        rubric_version=rubric.version,
        score_total=score_total,
        criteria_json=json.dumps(per_criterion, sort_keys=True),
        judge="llm-judge",
        artifact_path=str(artifact_path),
        reasoning=str(judge_json.get("reasoning") or "")[:8000],
        notes=None,
    )
    return {
        "ok": True,
        "agent_name": agent_name,
        "score_total": score_total,
        "criteria": per_criterion,
        "judge": "llm-judge",
        "quality_id": qid,
    }


def _persist(
    *,
    db_path: Path,
    run_id: str | None,
    span_id: str | None,
    agent_name: str,
    rubric_version: str,
    score_total: float,
    criteria_json: str,
    judge: str,
    artifact_path: str | None,
    reasoning: str | None,
    notes: str | None,
) -> int:
    from lib.cache import connect_wal
    from lib.migrations import ensure_current
    ensure_current(Path(db_path))
    con = connect_wal(Path(db_path))
    try:
        with con:
            cur = con.execute(
                "INSERT INTO agent_quality "
                "(run_id, span_id, agent_name, rubric_version, "
                "score_total, criteria_json, judge, artifact_path, "
                "reasoning, notes, at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, span_id, agent_name, rubric_version,
                 float(score_total), criteria_json, judge,
                 artifact_path, reasoning, notes,
                 datetime.now(UTC).isoformat()),
            )
            return int(cur.lastrowid or 0)
    finally:
        con.close()
