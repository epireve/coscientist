#!/bin/bash
# v0.218 — SessionStart hook (matcher: startup).
# Surfaces the most recently-active deep-research run to Claude as
# additionalContext. Replaces the manual "where am I" question every
# session with automatic context injection.
#
# Hook output: stdout JSON with hookSpecificOutput.additionalContext.
# Silent if no active runs (returns empty context).

set -e

CACHE="${COSCIENTIST_CACHE_DIR:-$HOME/.cache/coscientist}"
RUNS_DIR="$CACHE/runs"

[ -d "$RUNS_DIR" ] || { echo '{}'; exit 0; }

# Find most-recent run with at least one phase incomplete (= active).
# If none active, fall back to most-recent finished run.
ctx=""
for db in $(ls -t "$RUNS_DIR"/run-*.db 2>/dev/null); do
  [ -f "$db" ] || continue
  rid=$(basename "$db" .db | sed 's/^run-//')
  question=$(sqlite3 "$db" "SELECT question FROM runs LIMIT 1" 2>/dev/null)
  [ -z "$question" ] && continue
  pending=$(sqlite3 "$db" \
    "SELECT name FROM phases WHERE completed_at IS NULL ORDER BY ordinal LIMIT 1" \
    2>/dev/null)
  if [ -n "$pending" ]; then
    ctx="Active deep-research run: $rid — paused at phase '$pending'. Question: $(printf '%s' "$question" | head -c 200)"
    break
  fi
done

if [ -z "$ctx" ]; then
  echo '{}'
  exit 0
fi

# Use jq if available; fallback to printf with manual escaping.
if command -v jq >/dev/null 2>&1; then
  jq -n --arg ctx "$ctx" \
    '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
else
  printf '{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"%s"}}\n' \
    "$(printf '%s' "$ctx" | sed 's/"/\\"/g')"
fi
