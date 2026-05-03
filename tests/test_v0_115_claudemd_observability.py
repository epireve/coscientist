"""v0.115 — observability stack documentation tests.

v0.223 — CLAUDE.md compressed; verbose detail moved to
docs/ARCHITECTURE.md. Tests now check the union of both files so
the doc parity invariant holds wherever the content lives.
"""
from __future__ import annotations

from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parents[1]
_CLAUDE_MD = _REPO / "CLAUDE.md"
_ARCH_MD = _REPO / "docs" / "ARCHITECTURE.md"


def _docs_text() -> str:
    """Union of CLAUDE.md + docs/ARCHITECTURE.md."""
    parts = []
    if _CLAUDE_MD.exists():
        parts.append(_CLAUDE_MD.read_text())
    if _ARCH_MD.exists():
        parts.append(_ARCH_MD.read_text())
    return "\n".join(parts)


class ObservabilityDocsTests(TestCase):
    def test_claude_md_exists(self):
        self.assertTrue(_CLAUDE_MD.exists())

    def test_recent_landings_includes_v0_93_through_v0_114(self):
        text = _docs_text()
        for marker in ("v0.89", "v0.93", "v0.97",
                        "v0.106", "v0.110", "v0.114"):
            self.assertIn(marker, text,
                           f"recent-landings missing {marker}")

    def test_observability_section_exists(self):
        text = _docs_text()
        # Either full heading or compressed reference acceptable.
        self.assertTrue(
            "## Observability stack" in text
            or "Observability one-liner" in text,
            "no Observability section in CLAUDE.md or ARCHITECTURE.md",
        )

    def test_observability_lists_three_tables(self):
        text = _docs_text()
        for table in ("traces", "spans", "span_events",
                       "agent_quality"):
            self.assertIn(f"`{table}`", text)

    def test_observability_lists_span_kinds(self):
        text = _docs_text()
        for kind in ("phase", "sub-agent", "tool-call", "gate",
                     "persist", "harvest", "other"):
            self.assertIn(f"`{kind}`", text)

    def test_observability_mentions_key_modules(self):
        text = _docs_text()
        for mod_short in ("health", "trace_render",
                           "trace_status", "agent_quality",
                           "persona_schema", "gate_trace"):
            self.assertTrue(
                f"lib.{mod_short}" in text
                or f"lib/{mod_short}.py" in text
                or f"lib/{mod_short}`" in text,
                f"missing reference to lib/{mod_short}",
            )

    def test_observability_mentions_env_vars(self):
        text = _docs_text()
        self.assertIn("COSCIENTIST_TRACE_DB", text)
        self.assertIn("COSCIENTIST_TRACE_ID", text)

    def test_invariants_listed(self):
        text = _docs_text()
        self.assertIn("Best-effort", text)
        self.assertIn("stdlib", text)
        self.assertIn("WAL mode", text)

    def test_runbook_referenced(self):
        text = _docs_text()
        self.assertIn("SMOKE-TEST-RUNBOOK", text)


if __name__ == "__main__":
    raise SystemExit(run_tests(ObservabilityDocsTests))
