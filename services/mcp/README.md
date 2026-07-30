# headway-mcp — the Headway MCP server

Exposes Headway's read surface to AI assistants over the
[Model Context Protocol](https://modelcontextprotocol.io/) (official
Python SDK, MIT). Read-only, receipts structural, refusals pass through.
User-facing docs — setup, tool reference, the guarantee boundary, and what
is deliberately absent — live in [`docs/mcp.md`](../../docs/mcp.md);
design and evidence in handoff
[`docs/handoffs/0034-from-platform-to-ai-backend-mcp-server.md`](../../docs/handoffs/0034-from-platform-to-ai-backend-mcp-server.md).

## Architecture

```
assistant ⇄ headway-mcp (stdio) ⇄ Headway HTTP API ⇄ DB
```

**API client only.** This service holds no database credentials and
imports no database driver (test-pinned). It authenticates with a machine
key (`hwk_…`, scope `read:metrics`) from `HEADWAY_MCP_API_KEY` and refuses
to start without one, so the API stays the authorization + audit boundary:
every tool call is audited by the API under `key:<prefix>`.

| Module | Role |
| --- | --- |
| `headway_mcp/client.py` | httpx client over the machine-key-reachable surface (`/machine/metrics`, the lineage walk, the two public endpoints). API refusals carried verbatim as `ApiRefusal`. |
| `headway_mcp/tools.py` | The five tools. `_figure_payload` enforces the no-bare-number invariant (a row missing receipt fields is refused, never served stripped); empty results return refusal text, never `[]`. |
| `headway_mcp/server.py` | MCP registration (official SDK), server instructions stating the guarantee boundary, startup config refusal, stdio transport. |
| `scripts/mcp_transcript.py` | Live-verification harness: drives the server as a real MCP client (initialize → list → every tool). |

## Configuration

| Env var | Meaning |
| --- | --- |
| `HEADWAY_MCP_API_KEY` | **Required.** A Headway machine key (`hwk_…`) with the `read:metrics` permission, issued via `POST /machine/keys`. A session token is rejected — machine access is a separate, audited identity. |
| `HEADWAY_API_URL` | The Headway API base URL. Default `http://127.0.0.1:8000`. |

Run: `headway-mcp` (or `python -m headway_mcp`) — stdio transport, meant
to be spawned by an MCP client. See `docs/mcp.md` for Claude Desktop /
Claude Code config examples.

## Verification

```sh
# Unit + invariant suite (fakes only — no network, no live stack):
cd services/mcp && python -m pytest tests/ -q
# 24 passed  (schemas; startup refusal without a key / with a non-hwk credential;
#             refusal passthrough verbatim incl. scope denial; verify_claim
#             tri-state incl. rounded-value-is-a-mismatch; no-bare-number
#             invariant incl. refuse-on-stripped-row; empty-period refusal text;
#             no-DB-credential structural check)

# License gate (ADR-0001) — covers this package's dependency closure:
python scripts/license_gate.py --ecosystem python
# mcp 2.0.0 MIT PASS, mcp-types MIT PASS, httpx/httpx2 BSD PASS — gate PASS

# Live, against a running API with a real read-scoped key:
HEADWAY_MCP_API_KEY=hwk_... python scripts/mcp_transcript.py
# Full MCP session: initialize → tools/list → all five tools called live,
# including one live refusal (unknown id, API text verbatim), an
# empty-period refusal, and a verify_claim mismatch. The 2026-07-30 run
# transcript is in handoff 0034's evidence; audit.events verified to carry
# machine_read_metrics / machine_read_lineage rows under the key identity.
```

## Honest scope

- v0 wraps exactly the endpoints a `read:metrics` machine key (plus the
  unauthenticated public surface) can reach. The DQ queue, sources status,
  ops summaries, calc-run status, and metrics history/compare require a
  human session today — recorded as handoff 0034's scope-expansion open
  question, named as deliberately absent in the tool descriptions.
- No write tools, no prompt templates pretending to be policy, no
  streaming; stdio first, HTTP/SSE transport is a recorded follow-up.
