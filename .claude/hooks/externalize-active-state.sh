#!/bin/bash
# v0.219 — PreCompact hook.
# Externalizes the most-recent active run's state to disk before
# context compaction. Closes the steward 3h43m runaway class:
# if compaction loses mid-pipeline orchestrator context, the next
# session can read this file and recover.
#
# Hook input: JSON on stdin with hook_event_name=PreCompact.
# Hook output: silent (exit 0). Side effect: writes
# `~/.cache/coscientist/runs/run-<rid>/precompact-state.json` for
# the most-recent active run.

set -e

CACHE="${COSCIENTIST_CACHE_DIR:-$HOME/.cache/coscientist}"
RUNS_DIR="$CACHE/runs"

[ -d "$RUNS_DIR" ] || exit 0

# Find most-recent run with at least one phase incomplete (= active).
for db in $(ls -t "$RUNS_DIR"/run-*.db 2>/dev/null); do
  [ -f "$db" ] || continue
  rid=$(basename "$db" .db | sed 's/^run-//')
  pending=$(sqlite3 "$db" \
    "SELECT name FROM phases WHERE completed_at IS NULL ORDER BY ordinal LIMIT 1" \
    2>/dev/null)
  [ -z "$pending" ] && continue

  # Active run found — externalize.
  out_dir="$CACHE/runs/run-$rid"
  mkdir -p "$out_dir"
  out="$out_dir/precompact-state.json"

  question=$(sqlite3 "$db" "SELECT question FROM runs LIMIT 1" 2>/dev/null)
  done_phases=$(sqlite3 "$db" \
    "SELECT GROUP_CONCAT(name, ',') FROM phases WHERE completed_at IS NOT NULL" \
    2>/dev/null)
  pending_phases=$(sqlite3 "$db" \
    "SELECT GROUP_CONCAT(name, ',') FROM phases WHERE completed_at IS NULL" \
    2>/dev/null)
  paper_count=$(sqlite3 "$db" \
    "SELECT COUNT(*) FROM papers_in_run" 2>/dev/null)
  hyp_count=$(sqlite3 "$db" \
    "SELECT COUNT(*) FROM hypotheses" 2>/dev/null)

  jq -n \
    --arg rid "$rid" \
    --arg q "$question" \
    --arg done "$done_phases" \
    --arg pending "$pending_phases" \
    --arg pc "$paper_count" \
    --arg hc "$hyp_count" \
    --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{
      run_id: $rid,
      question: $q,
      completed_phases: $done,
      pending_phases: $pending,
      paper_count: ($pc | tonumber),
      hypothesis_count: ($hc | tonumber),
      externalized_at: $ts,
      hook: "PreCompact v0.219",
      restore_hint: ("uv run python .claude/skills/deep-research/scripts/db.py resume --run-id " + $rid)
    }' > "$out" 2>/dev/null || true

  # Only externalize the most-recent active run; break.
  break
done

exit 0
