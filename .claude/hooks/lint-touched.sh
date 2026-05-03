#!/bin/bash
# v0.219 — PostToolUse hook (matcher: Write|Edit).
# Auto-runs cheap quality checks on touched files. Silent on clean;
# warns to stderr (visible in Claude transcript) on issues.
#
# Hook input: JSON on stdin with tool_input.file_path.
# Hook output: silent (exit 0). Don't block — just surface signal.
#
# Checks (cheap; <1s total):
#  - Python syntax via `python3 -m py_compile` for *.py
#  - JSON syntax via `jq empty` for *.json
#  - Markdown frontmatter validity for SKILL.md / agent .md

set +e

INPUT=$(cat)
FILE=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

[ -z "$FILE" ] && exit 0
[ -f "$FILE" ] || exit 0

case "$FILE" in
  *.py)
    err=$(python3 -m py_compile "$FILE" 2>&1)
    if [ -n "$err" ]; then
      echo "[lint] $FILE: Python syntax error: $err" >&2
    fi
    ;;
  *.json)
    if ! jq empty "$FILE" >/dev/null 2>&1; then
      echo "[lint] $FILE: invalid JSON" >&2
    fi
    ;;
  */SKILL.md|*/agents/*.md)
    # Verify YAML frontmatter exists.
    head -1 "$FILE" | grep -q '^---$' || \
      echo "[lint] $FILE: missing YAML frontmatter (expected '---' on line 1)" >&2
    ;;
esac

exit 0
