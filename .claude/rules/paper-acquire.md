---
paths:
  - ".claude/skills/paper-acquire/**"
  - ".claude/skills/institutional-access/**"
  - "lib/paper_artifact.py"
  - "lib/rate_limit.py"
---

# Paper acquisition guardrails

These rules load only when working on paper-acquire / institutional-access
code or paper artifact handling. Non-negotiable.

## Triage gate

`paper-acquire` MUST check `manifest.json["state"] == "triaged"` and
`manifest.json["triage"]["sufficient"] == false` before fetching any
PDF. No speculative downloads.

## Per-publisher rate limit

`institutional-access` MUST honor 10s delay per publisher domain. Use
`lib.rate_limit.wait(domain)` — never bypass.

## Sci-Hub tier

Sci-Hub tier is disabled unless `COSCIENTIST_ALLOW_SCIHUB=1`. Off by
default. Don't enable without explicit operator action.

## Playwright

Playwright runs headful with persistent context (NOT `--headless`) to
match a real profile and reuse Chrome cookie state. Don't pass
`--headless`.

## Audit log

Every PDF fetch (every tier — OA, institutional, Sci-Hub when enabled)
MUST append to `~/.cache/coscientist/audit.log` with DOI + timestamp +
tier. The `lib.audit.append` helper handles this — call it.
