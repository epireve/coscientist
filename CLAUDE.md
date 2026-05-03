# Coscientist — project guide for Claude

Academic-research-agent toolkit built as atomic skills. Read this
file before working on anything in `.claude/`.

**Companion docs**:
- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — full layout,
  artifact contract, sub-agent phase listing, observability detail.
- [`RESEARCHER.md`](./RESEARCHER.md) — principles for sub-agents
  (Karpathy-style principle-as-antidote).
- [`ROADMAP.md`](./ROADMAP.md) — where this is going, what's parked.

## Three research modes (`lib/mode_selector.py`)

| Mode | When | Cost | Time |
|---|---|---|---|
| **Quick** | Single concrete one-shot, no per-item iteration | $0.05–0.30 | 30s–2m |
| **Deep** | Open-ended question — runs the 10-phase Expedition | $3–5 | 15–25 min |
| **Wide** | N items processed identically (10 ≤ N ≤ 250) | $5–30 (cap $50) | 5–20 min |

`select_mode(question, items=, explicit_mode=)` → `ModeRecommendation`
with confidence + warnings. Wide → Deep handoff via
`db.py init --seed-from-wide`.

## On-disk contract (one-line summary)

Every skill reads/writes a `<kind>` artifact under
`~/.cache/coscientist/<kind>s/<id>/`. Each kind has its own state
machine in `lib.artifact.STATES`. Two SQLite scopes (`runs/run-<rid>.db`,
`projects/<pid>/project.db`) share `lib/sqlite_schema.sql`.

Resume = replay `phases` where `completed_at IS NULL`. v0.220 added
`error_count` / `last_error_at` / `retry_attempt` for retry telemetry.
Never write directly to either DB — use `db.py` (runs),
`lib/project.py` (projects), `lib/graph.py` (graph edges).

Detail in `docs/ARCHITECTURE.md`.

## Observability stack (v0.89–v0.222)

Every coscientist DB has `traces` + `spans` + `span_events` +
`agent_quality` tables (migrations v11/v12/v18).

- **`spans` kinds**: `phase`, `sub-agent`, `tool-call`, `gate`,
  `persist`, `harvest`, `other`.
- **From Python**: `lib.trace.start_span` — context manager,
  auto-closes, captures exceptions as `status='error'`.
- **From MCPs**: `lib.trace.maybe_emit_tool_call(...)` reads
  `COSCIENTIST_TRACE_DB` + `COSCIENTIST_TRACE_ID` env vars set by
  orchestrator. Best-effort.
- **From gates**: `lib.gate_trace.emit_gate_span(...)`.
- **Inspect**: `uv run python -m lib.health` (one-shot, exit codes
  0/1/2 for clean/warn/crit). Also `lib.trace_render`,
  `lib.trace_status`, `lib.agent_quality`, `lib.persona_schema`.

### Recent landings (v0.51–v0.114)

- v0.51 Phase 1 parallel dispatch
- v0.52 search-strategy depth (PICO/SPIDER + critique)
- v0.53 Wide Research mode + Wide → Deep handoff
- v0.54–v0.56 brief richness + A5 trio + self-play debate
- v0.89–v0.92 observability foundation
- v0.93–v0.96 instrumentation hookup
- v0.97–v0.100 smoke-test infra
- v0.101–v0.105 persona schemas + rubrics
- v0.106–v0.110 `lib.health` + harvest/gate summaries
- v0.111–v0.114 alert thresholds + threshold config

### Invariants

1. **Best-effort.** Tracing failures NEVER break parent flow.
2. **Pure stdlib** in trace/health/agent_quality modules.
3. **WAL mode.** All DB writes via `lib.cache.connect_wal`.
4. **Schema-as-truth.** `lib/sqlite_schema.sql` mirrors every
   migration; `lib/migrations.py` applies forward.

See `docs/SMOKE-TEST-RUNBOOK.md` for operator walkthrough.
Full observability detail in `docs/ARCHITECTURE.md`.

## Skill composition rules

1. **Skills don't call other skills.** They read/write artifacts.
   The orchestrator (`deep-research`) is the only place that
   invokes a sequence.
2. **MCPs over custom code.** Prefer Consensus / paper-search-mcp /
   academic-mcp / Semantic Scholar over writing HTTP clients.
   Scripts are for local logic (extraction, browser automation, DB).
3. **Artifacts go in the cache, not the repo.** `~/.cache/coscientist/`
   is gitignored. Nothing in this repo should reference
   `/home/user/...`.
4. **Everything logs.** PDF fetches especially —
   `institutional-access` writes every download to
   `~/.cache/coscientist/audit.log`.

## Guardrails (non-negotiable)

- `paper-acquire` MUST check `manifest.json["state"] == "triaged"` and
  `manifest.json["triage"]["sufficient"] == false` before fetching
  any PDF. No speculative downloads.
- `institutional-access` MUST honor 10s delay per publisher domain.
  Use `lib.rate_limit.wait(domain)`.
- Sci-Hub tier disabled unless `COSCIENTIST_ALLOW_SCIHUB=1`.
- Playwright runs headful with persistent context (not `--headless`)
  to match a real profile.

## Sub-agents (one-line summary)

40+ personas in `.claude/agents/`. Each runs in its own context
window with a minimal `tools:` restriction. Eight phase groupings
(A–H): Expedition, Workshop, Tribunal, Laboratory, Tournament,
Archive, Wide Research, Self-play debate.

All sub-agents:
- Follow `RESEARCHER.md` principles
- Declare `tools:` restrictively in frontmatter (minimal-scope)
- Describe **what done looks like**, not procedural steps
- End with an **Exit test** clause
- Consume artifacts + DB state — never touch raw PDFs or publisher
  websites directly

Phase listing in `docs/ARCHITECTURE.md`.

## When adding a new skill

1. Create `.claude/skills/<name>/SKILL.md` with frontmatter
   (`name`, `description`, `when_to_use`).
2. Read from / write to the artifact contract only.
3. CLI scripts go in `.claude/skills/<name>/scripts/` with explicit
   `--paper-id` / `--run-id` args.
4. Update `SKILLS.md` (auto-regenerated by pre-commit).

## When adding a new publisher adapter

Add `.claude/skills/institutional-access/scripts/adapters/<publisher>.py`
implementing `fetch_pdf(doi, page, storage_state) -> Path`. Adapters
~20 lines. When a publisher changes HTML, fail-mode is fall-through
to Tier 2 (browser-use), not a broken skill.

## Working principles (for code in this repo)

Shaped after [karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills).
These govern how we *build* Coscientist. `RESEARCHER.md` governs
how sub-agents *do* research.

1. **Think Before Coding.** Name the assumption or ask. Multiple
   interpretations usually exist; pick explicitly.
2. **Simplicity First.** No speculative abstractions. Three similar
   adapters > premature `AdapterBase`. Indirection paid for in debug.
3. **Surgical Changes.** Fix X. Don't refactor adjacent code, rename
   unrelated vars, or tidy imports. Match existing style.
4. **Goal-Driven Execution.** Declarative success criteria over
   procedural steps. Sub-agents tell the agent *what done looks like*
   so it can loop until true.

## Git

Work on branch `main`. Commits: single-author (Firdaus), no
Claude/Anthropic attribution, no "follows X standards" framing.

## Test discipline

`uv run python tests/run_all.py` is the truth. Suite-green required
before commit. Auto-discovery via `pkgutil` — new `tests/test_*.py`
files register automatically.
