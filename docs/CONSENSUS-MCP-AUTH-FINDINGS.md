# Handover reply: Consensus MCP Pro tier in Claude Code CLI

**Status:** Investigation complete. Auth mechanism identified, root cause identified, two workarounds available, no static-token path exists for Pro tier.

---

## TL;DR

Consensus Pro tier authenticates via **OAuth only**. There is no self-serve static API key on Pro — bearer-token auth is gated behind their enterprise sales channel. The reason Claude Code is stuck on the 3-result anonymous tier is a known systemic bug in Claude Code's HTTP-MCP OAuth handshake (canonical tracking issue [anthropics/claude-code#11585](https://github.com/anthropics/claude-code/issues/11585), open since Nov 2025). Two viable fixes below — try Path A first, fall through to Path B if it fails.

---

## 1. Auth mechanism Consensus Pro exposes

From [Consensus's official MCP docs](https://docs.consensus.app/docs/mcp):

| Tier | Papers/search | Auth |
|---|---|---|
| No Account | 3 | none (anonymous) |
| Free | 10 | OAuth |
| **Pro** | **20** | **OAuth** |
| Enterprise | unlimited | Bearer token (`Authorization: Bearer <key>`) |

Confirmed against the [Consensus pricing page](https://consensus.app/pricing/) and the [Pro features doc](https://help.consensus.app/en/articles/11408820-what-do-you-get-with-pro). The Pro plan ($15/mo or $120/yr) does **not** ship with a self-serve API key. The only header-injection path documented is the enterprise tier, which requires contacting Consensus sales at `consensus.app/home/api`.

So the workaround in your investigation step 4 (`claude mcp add ... --header "Authorization: Bearer ..."`) is unavailable to a Pro user — there is no token to put after `Bearer`.

## 2. Headers claude.ai uses

I could not capture the live request from claude.ai (would require your logged-in browser's DevTools — see below for how to do it yourself if needed). But the architecture is documented: claude.ai uses Anthropic's hosted MCP-proxy (`mcp-proxy.anthropic.com` per multiple bug reports including [#11585 comment thread](https://github.com/anthropics/claude-code/issues/11585)). When you connect Consensus on claude.ai, Anthropic's proxy completes OAuth on your behalf, stores the token server-side, and forwards `Authorization: Bearer <consensus_oauth_token>` on every MCP request. Your Anthropic session cookie is what authenticates **you to the proxy** — it is not forwarded to Consensus directly.

Claude Code CLI is supposed to do its own OAuth handshake locally (no proxy involved) — the bug is that this handshake silently fails to trigger for many HTTP MCPs.

If you want the actual headers anyway: open claude.ai in Chrome, F12 → Network → trigger a Consensus search → filter by `mcp.consensus.app` (or `mcp-proxy.anthropic.com` since claude.ai routes through the proxy). The Bearer token will be visible on the outgoing request.

## 3. Why Consensus is stuck on anonymous tier in Claude Code

The signal that confirmed your hypothesis: `~/.claude/mcp-needs-auth-cache.json` has no Consensus entry. That cache is populated when Claude Code receives a `WWW-Authenticate: Bearer` response from an MCP server. Consensus is configured to **allow anonymous access** (the 3-result no-account tier), so it returns 200 OK without ever signaling 401. Claude Code therefore never marks Consensus as needing auth and never offers to start the OAuth flow on its own.

Consensus's docs say you can manually trigger OAuth via the `/mcp` command inside Claude Code. In practice this is exactly the surface Issue #11585 says is broken for HTTP MCPs — the authorization URL gets generated but `Redirection handling is disabled, skipping redirect` aborts the flow before the browser opens (see comment by `ctngln` on Feb 21, 2026 in [#11585](https://github.com/anthropics/claude-code/issues/11585) for the smoking-gun debug log).

## 4. Working invocation — two paths

### Path A: Native OAuth via `/mcp` command (try first)

Per Consensus's own Claude Code instructions, this should work. Worth trying once on the latest CLI:

```bash
# Make sure you're on a recent Claude Code (≥ 2.1.79 has OAuth fixes)
claude --version

# Clean slate
claude mcp remove consensus -s project
claude mcp remove consensus -s user 2>/dev/null

# Re-add at user scope (so OAuth tokens persist across projects)
claude mcp add --transport http --scope user consensus https://mcp.consensus.app/mcp

# Start Claude Code, then inside the CLI:
#   /mcp
#   → select "consensus"
#   → choose "Authenticate" (or "Clear authentication" then "Authenticate")
# Browser should open to Consensus OAuth login
# Sign in with your Pro account
# Fully quit Claude Code (NOT /reload — fully quit)
# Restart and verify result count
```

If `/mcp` does not surface an `Authenticate` action for Consensus, or browser never opens — that's #11585. Skip to Path B.

### Path B: `mcp-remote` stdio wrapper (proven workaround)

[`mcp-remote`](https://github.com/geelen/mcp-remote) is the standard escape hatch for clients that don't yet handle remote-MCP OAuth correctly. It wraps the HTTP server in a local stdio process, runs the OAuth dance itself, and persists tokens to `~/.mcp-auth/`. This is what Cursor uses for Consensus — see the official [Consensus docs](https://docs.consensus.app/docs/mcp) Cursor section. It works in Claude Code CLI too:

```bash
claude mcp remove consensus -s project
claude mcp remove consensus -s user 2>/dev/null
claude mcp add --scope user consensus npx -- -y mcp-remote@latest https://mcp.consensus.app/mcp
```

Or by editing `.mcp.json` directly:

```json
"consensus": {
  "type": "stdio",
  "command": "npx",
  "args": ["-y", "mcp-remote@latest", "https://mcp.consensus.app/mcp"]
}
```

First run: a browser tab will open for Consensus OAuth login. Sign in with the Pro account. Token is cached at `~/.mcp-auth/<hash>.json` and reused on subsequent runs. Restart Claude Code once after first auth.

### Verification after either path

Run a Consensus search inside Claude Code and check the response payload — you should see 20 papers per search instead of 3, and each paper object should include the `study_type` and `takeaway` fields (Pro-only fields per the Consensus tool schema). If you only see 10, you're on the Free tier (logged in but Pro entitlement not picked up — re-auth or check Consensus account status).

After verification, set `COSCIENTIST_CONSENSUS_AUTHED=1` in your shell rc so `lib/source_selector.py:_consensus_authed_default()` flips to the 10-result budget.

## 5. GitHub issue link

No new feature request filed. The canonical tracking issue is **[anthropics/claude-code#11585](https://github.com/anthropics/claude-code/issues/11585)** — "MCP servers requiring OAuth authentication don't expose tools — no browser auth flow triggered." Open since Nov 2025, multiple duplicates closed against it (#36307, #36374, #21355, #44223, etc.). It already references the Consensus-class symptom (see comments by `pkccgh` Feb 7 on claude.ai-proxy connectors, and `ctngln` Feb 21 with the `Redirection handling is disabled` debug log — that's the literal log line in your situation if you enable debug).

Recommended action: 👍 the issue and add a comment with your specific Consensus repro (`mcp-needs-auth-cache.json` empty + 3-result anonymous tier despite Pro account). That signal — "MCP server allows anonymous, so no 401 → CC never triggers OAuth even though Pro account exists" — is a useful variant the issue thread doesn't cleanly cover yet.

If Path B works (and it should), you're unblocked regardless. The CLI fix is on Anthropic's side and will land when it lands.

---

## What I did *not* do

- Did not run `claude mcp add` myself — that is on your machine and reversible/idempotent on your side, no value in me doing it remotely.
- Did not inspect claude.ai dispatch headers — that requires your authenticated browser session. Architecture is well-documented enough that the answer is high-confidence without it; if you want to capture the headers yourself for completeness, the DevTools recipe is in section 2.
- Did not file a new GitHub issue — duplicate of #11585. Comment + 👍 on the existing one is the right move.
