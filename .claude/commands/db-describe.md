---
description: Introspect a Coscientist run DB schema. Lists tables, valid --phase / --kind enums, and row counts. Read-only.
argument-hint: [<run_id>] (optional — defaults to most recent run)
---

# /db-describe

One-stop schema introspection. Replaces the 6× `PRAGMA table_info` queries sub-agents tend to fire when they don't know column names.

## Inputs

The user has supplied: `$ARGUMENTS`

Optional: `<run_id>`. If omitted, picks the most recent run by mtime.

## Procedure

1. **Resolve target DB**:
   ```bash
   if [ -z "$RID" ]; then
     DB=$(ls -t ~/.cache/coscientist/runs/run-*.db 2>/dev/null | head -1)
   else
     DB=~/.cache/coscientist/runs/run-${RID}.db
   fi
   ```

2. **Schema dump** — all tables with row counts:
   ```bash
   sqlite3 "$DB" ".tables" | tr ' ' '\n' | grep -v '^$' | while read t; do
     n=$(sqlite3 "$DB" "SELECT COUNT(*) FROM $t" 2>/dev/null)
     printf "  %-32s %s\n" "$t" "$n"
   done
   ```

3. **Phase enum** — valid `--phase` values from `db.py`:
   ```bash
   uv run python -c "from .claude.skills.deep_research.scripts.db import VALID_PHASES; print(VALID_PHASES)"
   ```
   (or grep `db.py` for the constant if import fails)

4. **Claim kind enum** — surface what `--kind` strings exist in the run:
   ```bash
   sqlite3 "$DB" "SELECT DISTINCT kind FROM claims"
   ```

5. **Common-mistake warnings**:
   - If `agent_quality.run_id IS NULL` for any rows → score_auto called without run_id
   - If `spans.status='running'` for spans whose phase is complete → stale, run closeout
   - If `claims.kind='hypothesis'` exists but `hypotheses` table empty → manual register needed (v0.214 known gap)

## Output

Markdown report with:
- Table list with row counts
- Valid `--phase` strings
- Distinct `--kind` strings already used in this run
- Warnings section

## Exit test

Done when: schema printed; warnings section names every detected anomaly; user can author correct CLI calls without further introspection.
