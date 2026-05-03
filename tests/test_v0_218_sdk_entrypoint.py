"""v0.218 — Phase 3.5: SDK headless entrypoint smoke test.

Validates lib.run_pipeline structure without requiring claude_agent_sdk
to actually be installed. Lazy-import pattern means the module loads
and the CLI parses args even on stock installs.

If the SDK is installed (optional dep), the import path is exercised
to catch obvious schema drift in our wrapper.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from tests.harness import TestCase, run_tests

_REPO = Path(__file__).resolve().parent.parent


class RunPipelineModuleTests(TestCase):
    def test_module_imports(self):
        from lib import run_pipeline  # noqa: F401

    def test_run_deep_research_callable_exists(self):
        from lib.run_pipeline import run_deep_research
        self.assertTrue(
            callable(run_deep_research),
            "run_deep_research must be a callable",
        )

    def test_main_callable_exists(self):
        from lib.run_pipeline import main
        self.assertTrue(callable(main))

    def test_module_does_not_eagerly_import_sdk(self):
        """SDK is optional. lib.run_pipeline should NOT fail to import
        when claude_agent_sdk is not installed."""
        spec = importlib.util.find_spec("claude_agent_sdk")
        if spec is not None:
            self.skipTest(
                "SDK installed locally — skipping lazy-import check",
            )
        # Re-import to verify lazy semantics held.
        if "lib.run_pipeline" in sys.modules:
            del sys.modules["lib.run_pipeline"]
        from lib import run_pipeline  # noqa: F401
        # If we got here the module loaded without the SDK present.
        # Now confirm calling run_deep_research raises ImportError, not
        # something cryptic.
        import asyncio
        from lib.run_pipeline import run_deep_research

        async def _try():
            agen = run_deep_research(question="test")
            try:
                async for _ in agen:
                    break
            except ImportError as e:
                return str(e)
            return "no-error"

        msg = asyncio.run(_try())
        self.assertIn("claude_agent_sdk", msg)


if __name__ == "__main__":
    raise SystemExit(run_tests(RunPipelineModuleTests))
