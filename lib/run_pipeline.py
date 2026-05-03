"""v0.218 — SDK headless entrypoint for the deep-research pipeline.

Wraps `claude_agent_sdk.query()` so the deep-research pipeline can run
non-interactively (CI/CD, scheduled cron, batch fan-out, programmatic
integration tests).

Lazy import: `claude_agent_sdk` is an optional dep. This module imports
it only at call time, so users who don't need SDK use don't pay the
install cost.

Usage:
    import asyncio
    from lib.run_pipeline import run_deep_research

    asyncio.run(run_deep_research(
        question="How does X work?",
        max_turns=200,
    ))

Or from CLI:
    uv run python -m lib.run_pipeline --question "..." [--overnight]

Reference: https://code.claude.com/docs/en/agent-sdk/overview
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any, AsyncIterator

_REPO = Path(__file__).resolve().parent.parent


async def run_deep_research(
    question: str,
    *,
    cwd: str | Path = _REPO,
    max_turns: int = 200,
    plugin_path: str | Path | None = None,
    extra_options: dict[str, Any] | None = None,
) -> AsyncIterator[Any]:
    """Run /deep-research via the Claude Agent SDK.

    Yields each message from the SDK stream so callers can react in
    real time (log to disk, push to Slack, etc).

    Raises ImportError if `claude_agent_sdk` is not installed.
    Install via: ``uv add claude-agent-sdk``.
    """
    try:
        from claude_agent_sdk import query, ClaudeAgentOptions
    except ImportError as e:
        raise ImportError(
            "claude_agent_sdk required for SDK headless mode. "
            "Install via: uv add claude-agent-sdk"
        ) from e

    setting_sources = ["user", "project"]
    allowed_tools = ["Skill", "Read", "Write", "Bash", "Agent", "TodoWrite"]
    plugins: list[dict[str, str]] = []
    if plugin_path is not None:
        plugins.append({"type": "local", "path": str(plugin_path)})

    options_kwargs: dict[str, Any] = {
        "cwd": str(cwd),
        "setting_sources": setting_sources,
        "allowed_tools": allowed_tools,
        "system_prompt": {"type": "preset", "preset": "claude_code"},
        "max_turns": max_turns,
    }
    if plugins:
        options_kwargs["plugins"] = plugins
    if extra_options:
        options_kwargs.update(extra_options)

    options = ClaudeAgentOptions(**options_kwargs)
    prompt = f'/deep-research "{question}"'
    async for message in query(prompt=prompt, options=options):
        yield message


async def _main_async(args: argparse.Namespace) -> int:
    print(f"[run_pipeline] starting /deep-research: {args.question!r}")
    print(f"[run_pipeline] cwd={args.cwd} max_turns={args.max_turns}")
    n_msgs = 0
    n_assistant = 0
    try:
        async for msg in run_deep_research(
            question=args.question,
            cwd=args.cwd,
            max_turns=args.max_turns,
            plugin_path=args.plugin,
        ):
            n_msgs += 1
            mtype = getattr(msg, "type", None)
            if mtype == "system" and getattr(msg, "subtype", None) == "init":
                slash = msg.data.get("slash_commands", []) if hasattr(msg, "data") else []
                plugins = msg.data.get("plugins", []) if hasattr(msg, "data") else []
                print(f"[init] {len(slash)} slash commands, {len(plugins)} plugins")
            if mtype == "assistant":
                n_assistant += 1
            if args.verbose:
                print(msg)
    except ImportError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 2
    print(f"[run_pipeline] done. messages={n_msgs} assistant_turns={n_assistant}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Headless deep-research pipeline runner via Claude Agent SDK",
    )
    parser.add_argument("--question", required=True, help="Research question")
    parser.add_argument("--cwd", default=str(_REPO), help="Working directory")
    parser.add_argument("--max-turns", type=int, default=200)
    parser.add_argument(
        "--plugin", default=None,
        help="Optional plugin directory path (for testing canonical plugin)",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
