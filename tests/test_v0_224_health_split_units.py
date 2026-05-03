"""v0.224 — unit tests for the 3 new health modules from v0.222.

Locks the split: any future regression in
`health_thresholds.py` / `health_collect.py` / `health_render.py`
should fail here, not in the broader integration tests.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tests.harness import TestCase, isolated_cache, run_tests


# ---------------------------------------------------------------- thresholds


class LoadThresholdsTests(TestCase):
    def test_defaults_returned_when_no_config(self):
        from lib.health_thresholds import (
            DEFAULT_THRESHOLDS,
            load_thresholds,
        )
        with isolated_cache():
            t = load_thresholds()
        self.assertEqual(t["max_stale_spans"],
                         DEFAULT_THRESHOLDS["max_stale_spans"])
        self.assertEqual(t["min_quality_score"],
                         DEFAULT_THRESHOLDS["min_quality_score"])

    def test_global_config_overrides_defaults(self):
        from lib.health_thresholds import load_thresholds
        with isolated_cache() as cache:
            cfg = cache / "health_thresholds.json"
            cfg.write_text(json.dumps({
                "max_stale_spans": 5,
                "min_quality_score": 0.75,
            }))
            t = load_thresholds(config_path=cfg)
        self.assertEqual(t["max_stale_spans"], 5)
        self.assertEqual(t["min_quality_score"], 0.75)

    def test_kwargs_override_global(self):
        from lib.health_thresholds import load_thresholds
        with isolated_cache() as cache:
            cfg = cache / "health_thresholds.json"
            cfg.write_text(json.dumps({"max_stale_spans": 5}))
            t = load_thresholds(
                config_path=cfg,
                overrides={"max_stale_spans": 10},
            )
        self.assertEqual(t["max_stale_spans"], 10)

    def test_unknown_keys_ignored(self):
        from lib.health_thresholds import load_thresholds
        with isolated_cache():
            t = load_thresholds(overrides={"made_up_key": 99})
        self.assertNotIn("made_up_key", t)

    def test_wrong_type_ignored(self):
        from lib.health_thresholds import load_thresholds
        with isolated_cache():
            # max_stale_spans is int — string should be ignored.
            t = load_thresholds(
                overrides={"max_stale_spans": "not-int"},
            )
        self.assertEqual(t["max_stale_spans"], 0)

    def test_int_promotes_to_float(self):
        from lib.health_thresholds import load_thresholds
        with isolated_cache():
            t = load_thresholds(
                overrides={"min_quality_score": 1},
            )
        self.assertEqual(t["min_quality_score"], 1.0)
        self.assertIsInstance(t["min_quality_score"], float)


class EvaluateAlertsTests(TestCase):
    def test_no_alerts_on_clean_report(self):
        from lib.health_thresholds import evaluate_alerts
        with isolated_cache():
            alerts = evaluate_alerts({
                "stale": [], "active": [],
                "tool_latency": {"by_tool": {}},
                "quality": {"by_agent": {}},
                "failed_spans_total": 0,
            })
        self.assertEqual(alerts, [])

    def test_stale_spans_warns(self):
        from lib.health_thresholds import evaluate_alerts
        with isolated_cache():
            alerts = evaluate_alerts({
                "stale": [{"id": "x"}],
                "active": [],
                "tool_latency": {"by_tool": {}},
                "quality": {"by_agent": {}},
                "failed_spans_total": 0,
            })
        codes = [a["code"] for a in alerts]
        self.assertIn("stale_spans", codes)

    def test_failed_spans_crit(self):
        from lib.health_thresholds import evaluate_alerts
        with isolated_cache():
            alerts = evaluate_alerts({
                "stale": [], "active": [],
                "tool_latency": {"by_tool": {}},
                "quality": {"by_agent": {}},
                "failed_spans_total": 100,
            })
        crit = [a for a in alerts if a["severity"] == "crit"]
        self.assertTrue(crit)
        self.assertEqual(crit[0]["code"], "failed_spans")

    def test_tool_error_rate_alerts(self):
        from lib.health_thresholds import evaluate_alerts
        with isolated_cache():
            alerts = evaluate_alerts({
                "stale": [], "active": [],
                "tool_latency": {"by_tool": {
                    "mcp__bad__call": {
                        "n": 10, "n_errors": 5, "mean_ms": 200,
                    },
                }},
                "quality": {"by_agent": {}},
                "failed_spans_total": 0,
            })
        codes = [a["code"] for a in alerts]
        self.assertIn("tool_error_rate", codes)


# ---------------------------------------------------------------- collect


def _empty_run_db(path: Path) -> Path:
    """Minimal DB with traces/spans tables, no rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE traces (
            trace_id TEXT PRIMARY KEY, run_id TEXT,
            status TEXT, started_at TEXT
        );
        CREATE TABLE spans (
            span_id INTEGER PRIMARY KEY,
            trace_id TEXT, kind TEXT, name TEXT,
            status TEXT, started_at TEXT, ended_at TEXT
        );
    """)
    con.close()
    return path


class CollectEmptyCacheTests(TestCase):
    def test_empty_cache_returns_zeroed_report(self):
        from lib.health_collect import collect
        with isolated_cache():
            r = collect()
        self.assertEqual(r["n_runs"], 0)
        self.assertEqual(r["active"], [])
        self.assertEqual(r["stale"], [])
        self.assertEqual(r["failed_spans_total"], 0)

    def test_uninstrumented_db_counted_separately(self):
        from lib.health_collect import collect
        with isolated_cache() as cache:
            runs = cache / "runs"
            runs.mkdir(parents=True)
            # No traces table → uninstrumented.
            db = runs / "run-foo.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE bogus (x INTEGER)")
            con.close()
            r = collect()
        self.assertEqual(r["n_runs"], 0)
        self.assertEqual(r["n_uninstrumented"], 1)


class McpErrorRatesTests(TestCase):
    def test_empty_runs_dir(self):
        from lib.health_collect import mcp_error_rates
        with isolated_cache():
            self.assertEqual(mcp_error_rates(), {})

    def test_aggregates_by_source_key(self):
        from datetime import UTC, datetime
        from lib.health_collect import mcp_error_rates
        with isolated_cache() as cache:
            runs = cache / "runs"
            runs.mkdir(parents=True)
            db = _empty_run_db(runs / "run-x.db")
            con = sqlite3.connect(db)
            ts = datetime.now(UTC).isoformat()
            with con:
                con.executemany(
                    "INSERT INTO spans (trace_id, kind, name, "
                    "status, started_at) VALUES (?, ?, ?, ?, ?)",
                    [
                        ("t1", "tool-call",
                         "mcp__semantic-scholar__search", "ok", ts),
                        ("t1", "tool-call",
                         "mcp__semantic-scholar__search", "error", ts),
                        ("t1", "tool-call",
                         "mcp__openalex__works", "ok", ts),
                    ],
                )
            con.close()
            rates = mcp_error_rates()
        self.assertEqual(rates["semantic-scholar"]["n_calls"], 2)
        self.assertEqual(rates["semantic-scholar"]["n_errors"], 1)
        self.assertEqual(rates["openalex"]["n_calls"], 1)


# ---------------------------------------------------------------- render


class RenderMdTests(TestCase):
    def _empty_report(self) -> dict:
        return {
            "n_runs": 0, "n_uninstrumented": 0,
            "uninstrumented_paths": [],
            "active": [], "stale": [],
            "tool_latency": {"by_tool": {}},
            "quality": {"by_agent": {}},
            "failed_spans_total": 0,
        }

    def test_empty_report_renders_no_data_marker(self):
        from lib.health_render import render_md
        out = render_md(self._empty_report())
        self.assertIn("Coscientist health", out)
        self.assertIn("No data", out)

    def test_alerts_banner_rendered_first(self):
        from lib.health_render import render_md
        out = render_md(self._empty_report(), alerts=[
            {"severity": "crit", "code": "x",
             "message": "boom", "value": 1, "threshold": 0},
        ])
        self.assertIn("## Alerts", out)
        self.assertIn("🚨", out)
        self.assertIn("**x**", out)

    def test_active_runs_section(self):
        from lib.health_render import render_md
        r = self._empty_report()
        r["active"] = [{
            "trace_id": "t1", "run_id": "r1",
            "started_at": "2026-01-01T00:00:00Z",
            "db_path": "/x",
        }]
        out = render_md(r)
        self.assertIn("Active runs", out)
        self.assertIn("`t1`", out)


if __name__ == "__main__":
    raise SystemExit(run_tests(
        LoadThresholdsTests,
        EvaluateAlertsTests,
        CollectEmptyCacheTests,
        McpErrorRatesTests,
        RenderMdTests,
    ))
