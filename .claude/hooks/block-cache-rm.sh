#!/bin/bash
# v0.219 — PreToolUse hook (matcher: Bash).
# Blocks destructive `rm -rf` against the coscientist cache.
# Codifies the permission hesitation we already had — explicit deny
# rather than relying on Claude to ask.
#
# Hook input: JSON on stdin with tool_input.command field.
# Hook output: emit hookSpecificOutput.permissionDecision='deny' on
# match; exit 0 silently otherwise (let normal permission flow run).

set -e

INPUT=$(cat)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)

[ -z "$COMMAND" ] && exit 0

# Patterns that target the cache destructively.
BLOCKED='rm[[:space:]]+-rf?[[:space:]]+.*(/\.cache/coscientist|~/\.cache/coscientist|\$HOME/\.cache/coscientist)'

if echo "$COMMAND" | grep -qE "$BLOCKED"; then
  jq -n --arg cmd "$COMMAND" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("Destructive rm against coscientist cache blocked by v0.219 guard. Use `lib.trace_status --prune-empty-dbs` or `--prune --prune-days N` for safe cleanup. Command attempted: " + $cmd)
    }
  }'
  exit 0
fi

exit 0
