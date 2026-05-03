---
paths:
  - "lib/sqlite_schema.sql"
  - "lib/migrations.py"
  - ".claude/skills/deep-research/scripts/db.py"
  - "lib/cache.py"
  - "lib/trace.py"
---

# DB conventions (loads when editing schema / db.py / migrations / trace)

## Two SQLite scopes

- **Per-run**: `~/.cache/coscientist/runs/run-<rid>.db` — driven by
  `lib/sqlite_schema.sql`. One run = one DB.
- **Per-project**: `~/.cache/coscientist/projects/<pid>/project.db` —
  same schema layout; cross-run aggregations + manuscript tables.

Never write directly. Use `db.py`, `lib/project.py`, or `lib/graph.py`.

## WAL mode mandatory

All DB connections via `lib.cache.connect_wal`. Never plain
`sqlite3.connect()` — would lose concurrent-read safety.

## Schema-as-truth

`lib/sqlite_schema.sql` mirrors every migration. `lib/migrations.py`
applies forward. When adding a table:
1. Add `CREATE TABLE` to `sqlite_schema.sql`
2. Add forward migration in `migrations.py` with version bump
3. Test the migration is idempotent (apply twice → no error)

## Resume semantics

`db.py resume --run-id <id>` replays phases where `completed_at IS
NULL`. Don't break this contract — phase order matters.

## Tracing

Every `db.py record-phase --start` opens a span via `lib.trace`.
Always pair `--start` with `--complete` or `--error`. Stale spans
(status='running' past pipeline complete) are auto-closed by the
v0.214 closeout hook (now wired as v0.218 SubagentStop hook).
