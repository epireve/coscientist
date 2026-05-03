#!/bin/bash
# v0.218 — Stop hook.
# Runs lib.health and warns if stale spans accumulated this session.
# Silent on clean state; warns to stderr (visible in Claude transcript)
# only when something needs attention.
#
# Exit 0 always — never blocks Stop.

set +e

cd "$(dirname "$0")/../.." 2>/dev/null || exit 0

# Run health check; capture stale span count.
output=$(uv run python -m lib.health --json 2>/dev/null || echo '{}')
stale=$(echo "$output" | python3 -c \
  "import json,sys; d=json.load(sys.stdin); print(d.get('stale_spans',{}).get('count',0))" \
  2>/dev/null)

if [ -n "$stale" ] && [ "$stale" -gt 0 ] 2>/dev/null; then
  echo "[health] $stale stale span(s) accumulated. Run /run-audit on the affected run, or 'uv run python -m lib.trace_status --stale-only --mark-error' to close them." >&2
fi

exit 0
