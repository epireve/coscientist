#!/bin/bash
# v0.218 — SubagentStop hook for steward.
# Fires when the deep-research steward persona finishes; auto-invokes
# closeout.py to score personas + close stale spans + write summary note.
#
# Eliminates the manual orchestrator burden from v0.214: closeout
# now happens automatically, no need for the operator to remember.
#
# Hook input arrives on stdin as JSON. We extract no fields — just
# detect the most recent run with steward complete + closeout not run,
# and fire closeout.py against it. Idempotent.

set -e

CACHE="${COSCIENTIST_CACHE_DIR:-$HOME/.cache/coscientist}"
RUNS_DIR="$CACHE/runs"

# Find runs where steward is done but closeout note not present.
# Skip silently if no matching run (e.g. steward fired in a different
# subagent type, or this is a non-coscientist session).
[ -d "$RUNS_DIR" ] || exit 0

for db in "$RUNS_DIR"/run-*.db; do
  [ -f "$db" ] || continue
  rid=$(basename "$db" .db | sed 's/^run-//')
  steward_done=$(sqlite3 "$db" \
    "SELECT 1 FROM phases WHERE name='steward' AND completed_at IS NOT NULL LIMIT 1" \
    2>/dev/null)
  if [ -z "$steward_done" ]; then continue; fi
  closeout_done=$(sqlite3 "$db" \
    "SELECT 1 FROM notes WHERE author='closeout' AND run_id='$rid' LIMIT 1" \
    2>/dev/null)
  if [ -n "$closeout_done" ]; then continue; fi
  # Fire closeout
  cd "$(dirname "$0")/../.." || exit 0
  uv run python .claude/skills/deep-research/scripts/closeout.py \
    --run-id "$rid" >/dev/null 2>&1 || true
done

exit 0
