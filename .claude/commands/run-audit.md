---
description: Audit a completed deep-research run for bugs, quality issues, stale spans, missing close-out steps. Read-only diagnostics — no DB writes.
argument-hint: <run_id>
---

# /run-audit

Diagnostic sweep over a single deep-research run. Emits a punch list of fixable issues. Does **not** mutate the run DB.

## Inputs

The user has supplied: `$ARGUMENTS`

Expected: a single `run_id` (e.g. `88888895`).

## Procedure

1. **Validate run exists**:
   ```bash
   ls ~/.cache/coscientist/runs/run-${RID}.db 2>/dev/null \
     || { echo "no run DB at run-${RID}.db"; exit 2; }
   ```

2. **Phase status table** — surface incomplete phases:
   ```bash
   sqlite3 ~/.cache/coscientist/runs/run-${RID}.db \
     "SELECT ordinal, name,
       CASE WHEN completed_at IS NOT NULL THEN 'done'
            WHEN started_at IS NOT NULL THEN 'started'
            ELSE 'pending' END
      FROM phases ORDER BY ordinal"
   ```

3. **Stale-span check**:
   ```bash
   uv run python -m lib.trace_status --run-id ${RID} --stale-only
   ```

4. **Closeout-ran check**:
   ```bash
   sqlite3 ~/.cache/coscientist/runs/run-${RID}.db \
     "SELECT COUNT(*) FROM notes WHERE run_id='${RID}' AND author='closeout'"
   ```
   If 0, recommend `/run-audit --fix` (or invoke `closeout.py` directly).

5. **Quality leaderboard** — if any agents scored poorly:
   ```bash
   uv run python -m lib.agent_quality summary \
     --db ~/.cache/coscientist/runs/run-${RID}.db \
     --run-id ${RID}
   ```

6. **Empty-table audit** — surface unused run-scoped tables:
   ```bash
   for t in claims hypotheses tournament_matches attack_findings agent_quality artifacts; do
     cnt=$(sqlite3 ~/.cache/coscientist/runs/run-${RID}.db "SELECT COUNT(*) FROM $t WHERE run_id='${RID}'" 2>/dev/null || echo 0)
     printf "  %-25s %s\n" "$t" "$cnt"
   done
   ```

7. **Tournament tie detection** — Elo ties at top suggest `/run-evolve` should fire:
   ```bash
   uv run python .claude/skills/tournament/scripts/leaderboard.py \
     --run-id ${RID} --top 5 --json
   ```

## Output

Single markdown report:

```
# Run audit: <run_id>

## Phase status
[table]

## Issues found
- [N] stale spans (status='running' but phase complete)
- closeout: [ran|NOT RAN — recommend invocation]
- [N] phases with no output
- [N] agents below quality 0.5

## Recommendations
1. Run closeout: `uv run python .claude/skills/deep-research/scripts/closeout.py --run-id <rid>`
2. Run evolve: `/run-evolve <rid>`  (if Elo tie at top)
3. ...
```

## Exit test

Done when: report printed; user has clear punch-list of next actions; no DB mutations occurred.
