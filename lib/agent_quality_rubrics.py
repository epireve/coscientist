"""v0.227 — rubric model + per-persona rubrics.

Split from lib/agent_quality.py for testability + size. Behavior
unchanged. Public surface re-exported by lib/agent_quality.py.

Each `Rubric`:
  - agent_name + version + description
  - criteria: tuple of `Criterion`
  - loader: Path -> parsed artifact (passed to each criterion's `check`)

Pure stdlib. No DB writes.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


# ---------- rubric model ----------

@dataclass(frozen=True)
class Criterion:
    name: str
    weight: float
    check: Callable[[Any], float]
    description: str


@dataclass(frozen=True)
class Rubric:
    agent_name: str
    version: str
    description: str
    criteria: tuple[Criterion, ...]
    loader: Callable[[Path], Any]


# ---------- pure-stdlib check helpers ----------

def count_at_least(items: list, n: int) -> float:
    """1.0 if len(items) >= n; ramp from 0 to 1 across [0, n]."""
    if not items:
        return 0.0
    return min(1.0, len(items) / max(1, n))


def every_item_has_fields(items: list[dict], fields: list[str]) -> float:
    """Fraction of items where ALL `fields` present + truthy."""
    if not items:
        return 0.0
    ok = sum(
        1 for it in items
        if all(it.get(f) for f in fields)
    )
    return ok / len(items)


def fraction_with_field(items: list[dict], field: str) -> float:
    """Fraction of items where `field` present + truthy."""
    if not items:
        return 0.0
    return sum(1 for it in items if it.get(field)) / len(items)


def unique_kind_count(
    items: list[dict], key: str, min_unique: int = 3,
) -> float:
    """Reward distinct values of `key`. 1.0 at >= min_unique."""
    if not items:
        return 0.0
    return min(1.0, len({it.get(key) for it in items if it.get(key)})
               / max(1, min_unique))


def has_field(d: dict, field: str) -> float:
    """1.0 if d[field] is truthy."""
    return 1.0 if d.get(field) else 0.0


# ---------- artifact loaders ----------

def _load_json_path(p: Path) -> Any:
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


def _load_text_path(p: Path) -> str:
    if not p.exists():
        return ""
    return p.read_text()


def _items_from(payload: Any, list_field: str) -> list:
    """v0.105 — accept either raw list or dict with `list_field`."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        v = payload.get(list_field)
        if isinstance(v, list):
            return v
    return []


# ---------- per-persona rubrics ----------

RUBRICS: dict[str, Rubric] = {
    "scout": Rubric(
        agent_name="scout",
        version="0.2",
        description="Paper-discovery breadth + dedup",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_candidates",
                weight=2.0,
                check=lambda d: count_at_least(
                    _items_from(d, "shortlist"), 30,
                ),
                description=">=30 candidate papers",
            ),
            Criterion(
                name="canonical_id_present",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "shortlist"), "canonical_id",
                ),
                description="every paper has canonical_id",
            ),
            Criterion(
                name="title_present",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "shortlist"), "title",
                ),
                description="every paper has title",
            ),
            Criterion(
                name="source_diversity",
                weight=1.0,
                check=lambda d: unique_kind_count(
                    _items_from(d, "shortlist"), "source",
                    min_unique=3,
                ),
                description=">=3 distinct sources",
            ),
        ),
    ),
    "surveyor": Rubric(
        agent_name="surveyor",
        version="0.2",
        description="Gap identification specificity",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_gaps",
                weight=2.0,
                check=lambda d: count_at_least(
                    _items_from(d, "gaps"), 5,
                ),
                description=">=5 gaps",
            ),
            Criterion(
                name="why_present",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    _items_from(d, "gaps"), "why_matters",
                ),
                description="every gap has why-this-matters",
            ),
            Criterion(
                name="kind_present",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "gaps"), "kind",
                ),
                description="every gap has kind label",
            ),
        ),
    ),
    "architect": Rubric(
        agent_name="architect",
        version="0.2",
        description="Candidate-approach completeness",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_candidates",
                weight=2.0,
                check=lambda d: count_at_least(
                    _items_from(d, "hypotheses"), 1,
                ),
                description=">=1 hypothesis (max 3 per spec)",
            ),
            Criterion(
                name="all_have_falsifiers",
                weight=2.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "hypotheses"), "falsifiers",
                ),
                description="every hypothesis has falsifiers",
            ),
            Criterion(
                name="all_have_method_sketch",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    _items_from(d, "hypotheses"), "method_sketch",
                ),
                description="every hypothesis has method_sketch",
            ),
        ),
    ),
    "synthesist": Rubric(
        agent_name="synthesist",
        version="0.2",
        description="Cross-paper implications",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_implications",
                weight=2.0,
                check=lambda d: count_at_least(
                    _items_from(d, "implications"), 3,
                ),
                description=">=3 implications",
            ),
            Criterion(
                name="all_have_supporting_ids",
                weight=2.0,
                check=lambda d: every_item_has_fields(
                    _items_from(d, "implications"), ["supporting_ids"],
                ),
                description="every implication cites supporting papers",
            ),
        ),
    ),
    "weaver": Rubric(
        agent_name="weaver",
        version="0.2",
        description="Coherence map (dict JSON per v0.103 spec)",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="has_sharpened_question",
                weight=1.5,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("sharpened_question") or "").strip()
                                  else 0.0,
                description="non-empty sharpened_question",
            ),
            Criterion(
                name="enough_consensus_or_tensions",
                weight=2.0,
                check=lambda d: 1.0 if (
                    len(_items_from(d, "consensus")) +
                    len(_items_from(d, "tensions"))
                ) >= 3 else 0.0,
                description=">=3 consensus or tension entries",
            ),
            Criterion(
                name="consensus_have_supporting_ids",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    _items_from(d, "consensus"), "supporting_ids",
                ),
                description="every consensus entry cites papers",
            ),
        ),
    ),
    "cartographer": Rubric(
        agent_name="cartographer",
        version="0.1",
        description="Seminal-paper coverage",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="has_summary",
                weight=1.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("summary") or "").strip()
                                  else 0.0,
                description="non-empty summary",
            ),
            Criterion(
                name="enough_seminals",
                weight=2.0,
                check=lambda d: count_at_least(
                    (d or {}).get("seminals") or [], 3,
                ),
                description=">=3 seminal papers",
            ),
            Criterion(
                name="seminals_have_why",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    (d or {}).get("seminals") or [], "why_seminal",
                ),
                description="every seminal has why_seminal",
            ),
        ),
    ),
    "chronicler": Rubric(
        agent_name="chronicler",
        version="0.1",
        description="Timeline coverage + dead-end tracking",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="has_summary",
                weight=1.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("summary") or "").strip()
                                  else 0.0,
                description="non-empty summary",
            ),
            Criterion(
                name="enough_timeline",
                weight=2.0,
                check=lambda d: count_at_least(
                    (d or {}).get("timeline") or [], 3,
                ),
                description=">=3 timeline events",
            ),
            Criterion(
                name="timeline_event_present",
                weight=1.0,
                check=lambda d: fraction_with_field(
                    (d or {}).get("timeline") or [], "event",
                ),
                description="every timeline entry has event",
            ),
        ),
    ),
    "inquisitor": Rubric(
        agent_name="inquisitor",
        version="0.1",
        description="Per-hypothesis adversarial coverage",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_evaluations",
                weight=2.0,
                check=lambda d: count_at_least(
                    (d or {}).get("evaluations") or [], 1,
                ),
                description=">=1 evaluation per architect hypothesis",
            ),
            Criterion(
                name="all_have_steelman",
                weight=2.0,
                check=lambda d: fraction_with_field(
                    (d or {}).get("evaluations") or [], "steelman",
                ),
                description="every evaluation has steelman",
            ),
            Criterion(
                name="all_have_killer",
                weight=2.0,
                check=lambda d: fraction_with_field(
                    (d or {}).get("evaluations") or [],
                    "killer_experiment",
                ),
                description="every evaluation has killer_experiment",
            ),
            Criterion(
                name="all_have_survival",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    (d or {}).get("evaluations") or [], "survival",
                ),
                description="every evaluation has survival score",
            ),
        ),
    ),
    "visionary": Rubric(
        agent_name="visionary",
        version="0.1",
        description="New-direction depth",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="enough_directions",
                weight=2.0,
                check=lambda d: count_at_least(
                    (d or {}).get("directions") or [], 2,
                ),
                description=">=2 directions",
            ),
            Criterion(
                name="all_have_first_step",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    (d or {}).get("directions") or [], "first_step",
                ),
                description="every direction has first_step",
            ),
            Criterion(
                name="all_have_why_underexplored",
                weight=1.5,
                check=lambda d: fraction_with_field(
                    (d or {}).get("directions") or [],
                    "why_underexplored",
                ),
                description="every direction has why_underexplored",
            ),
        ),
    ),
    "steward": Rubric(
        agent_name="steward",
        version="0.1",
        description="Final-artifact integrity check",
        loader=_load_json_path,
        criteria=(
            Criterion(
                name="eval_passed",
                weight=2.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and d.get("eval_passed") is True
                                  else 0.0,
                description="research-eval passed",
            ),
            Criterion(
                name="zero_hedge_words",
                weight=1.5,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and d.get("hedge_word_hits", -1) == 0
                                  else 0.0,
                description="hedge_word_hits == 0",
            ),
            Criterion(
                name="claims_cited",
                weight=1.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("claims_cited") or 0) >= 5
                                  else 0.0,
                description=">=5 claims cited",
            ),
            Criterion(
                name="papers_cited",
                weight=1.0,
                check=lambda d: 1.0 if isinstance(d, dict)
                                  and (d.get("papers_cited") or 0) >= 10
                                  else 0.0,
                description=">=10 papers cited",
            ),
        ),
    ),
}
