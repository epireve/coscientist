---
name: run-evolve
description: Run hypothesis-evolution round on a completed deep-research run. Mutator persona generates child hypotheses from top-Elo parents; children re-enter tournament. Closes Elo ties at the top of the leaderboard.
when_to_use: User says "evolve hypotheses", "tournament tied", "mutate top hypotheses", "break the Elo tie on run X". Operator-invoked only.
argument-hint: <run_id> [--top-k 3] [--children-per 2]
disable-model-invocation: true
---

# /run-evolve

Invokes the `mutator` persona over the top-Elo hypotheses of a run, persists children with `parent_hyp_id` lineage, runs a fresh pairwise tournament round.

## Inputs

The user has supplied: `$ARGUMENTS`

Required: `<run_id>`. Optional flags:
- `--top-k N` (default 3) — how many top-Elo parents to mutate
- `--children-per N` (default 2) — children to spawn per parent

## Pre-conditions

- Run has at least N hypotheses already in `hypotheses` table (Architect/Visionary fired)
- Tournament has run at least one round (`tournament_matches` non-empty)

Validate:
```bash
n_hyps=$(sqlite3 ~/.cache/coscientist/runs/run-${RID}.db \
  "SELECT COUNT(*) FROM hypotheses WHERE run_id='${RID}'")
[ "$n_hyps" -ge 2 ] || { echo "need >=2 hypotheses, found $n_hyps"; exit 2; }
```

## Procedure

1. **Fetch top-K parents**:
   ```bash
   uv run python .claude/skills/tournament/scripts/leaderboard.py \
     --run-id ${RID} --top ${TOP_K} --json > /tmp/parents.json
   ```

2. **Dispatch mutator** sub-agent (Task tool, `subagent_type=mutator`):
   - Pass parents JSON
   - Persona reads `RESEARCHER.md` + parents
   - Persona invokes `record_hypothesis.py` with `--parent-hyp-id <parent>` per child
   - Agent writes evolution-round summary to
     `~/.cache/coscientist/runs/run-${RID}/phases/mutator-output.json`

3. **Record evolution round**:
   ```bash
   sqlite3 ~/.cache/coscientist/runs/run-${RID}.db \
     "INSERT INTO evolution_rounds (run_id, parent_count, child_count, at)
      VALUES ('${RID}', ${TOP_K}, ${TOTAL_CHILDREN}, datetime('now'))"
   ```

4. **Run fresh tournament round** over enlarged set:
   ```bash
   uv run python .claude/skills/tournament/scripts/pairwise.py \
     --run-id ${RID} --strategy top-k-vs-rest --top-k 5 > /tmp/pairs.json
   ```
   Dispatch `ranker` sub-agents in parallel batches (max 3 concurrent).

5. **Re-emit leaderboard**:
   ```bash
   uv run python .claude/skills/tournament/scripts/leaderboard.py \
     --run-id ${RID} --top 10
   ```

## Exit test

Done when:
- Children persist in `hypotheses` table with `parent_hyp_id` set (verify
  `SELECT COUNT(*) FROM hypotheses WHERE run_id=? AND parent_hyp_id IS NOT NULL`).
- New `tournament_matches` rows exist (matches run after children added).
- One row in `evolution_rounds` for this round.
- Leaderboard shows Elo separation (no longer tied at top).
