---
description: Convert a completed deep-research run into a manuscript draft. Promotes the top-Elo hypothesis (or user-named hyp) into a structured manuscript via the manuscript-draft skill, harvests cite-keys from the run's papers_in_run.
argument-hint: <run_id> [--hyp <hyp_id>] [--venue IMRaD|NeurIPS|ACL|Nature|thesis]
---

# /run-to-manuscript

Bridge from /deep-research output → manuscript subsystem. Closes the longstanding gap where briefs sit unread and never become drafts.

## Inputs

The user has supplied: `$ARGUMENTS`

Required: `<run_id>`. Optional flags:
- `--hyp <hyp_id>` (default: top-Elo from leaderboard)
- `--venue <template>` (default: IMRaD)

## Pre-conditions

- Run has `brief.md` and `understanding_map.md` (Steward fired)
- At least 1 hypothesis registered

## Procedure

1. **Pick hypothesis**:
   ```bash
   if [ -z "$HYP" ]; then
     HYP=$(uv run python .claude/skills/tournament/scripts/leaderboard.py \
       --run-id ${RID} --top 1 --json | jq -r '.top[0].hyp_id')
   fi
   ```

2. **Pull hypothesis statement + supporting papers**:
   ```bash
   sqlite3 ~/.cache/coscientist/runs/run-${RID}.db <<EOF
   SELECT statement, predicted_observables, falsifiers, supporting_ids
   FROM hypotheses WHERE hyp_id='${HYP}' AND run_id='${RID}'
   EOF
   ```

3. **Init manuscript**:
   ```bash
   uv run python .claude/skills/manuscript-draft/scripts/init.py \
     --title "<derived from hypothesis>" \
     --venue ${VENUE} \
     --abstract-seed "<hypothesis statement>" \
     --source-run-id ${RID}
   # → returns mid (manuscript_id)
   ```

4. **Harvest cite-keys** from `papers_in_run` → seed manuscript outline.json
   `cite_keys` field. Use `supporting_ids` from hypothesis as primary, then
   add Inquisitor's attack-supporting papers, then breadth from
   `papers_in_run`.

5. **Auto-fill outline sections** from brief.md headings:
   - Abstract: hypothesis statement + falsifier
   - Introduction: pull "Field consensus" + "Sharpened question" from brief
   - Methods: hypothesis `method_sketch` field
   - Results: placeholder (no data yet)
   - Discussion: pull tensions + attacks from inquisitor-output.json

6. **Dispatch drafter sub-agent** (Task tool, `subagent_type=drafter`):
   - Pass mid + outline.json
   - Drafter fills each section to target word count
   - Tracks cite-keys against project paper artifacts

7. **Verify state machine**:
   ```bash
   sqlite3 ~/.cache/coscientist/projects/<pid>/project.db \
     "SELECT state FROM artifact_index WHERE artifact_id='${MID}'"
   # expected: 'drafted'
   ```

## Output

- New manuscript artifact at `~/.cache/coscientist/manuscripts/<mid>/`
- `source.md` populated with placeholder-free draft
- `outline.json` with cite-keys harvested from run
- Link recorded: `manuscripts/<mid>/manifest.json` references `source_run_id`

## Exit test

Done when:
- manuscript artifact exists with state='drafted'
- source.md word count > 1500 (non-placeholder)
- ≥5 cite-keys harvested from run papers
- manifest.json links back to run_id
