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
key (`hwk_…`) from `HEADWAY_MCP_API_KEY` and refuses to start without one,
so the API stays the authorization + audit boundary: every tool call is
audited by the API under `key:<prefix>`. The key's SCOPES decide which tools
work — `read:metrics` for the metrics/certified tools, `read:dq` for the
data-quality tools, `read:ops` for the operations snapshot (handoff 0039).

| Module | Role |
| --- | --- |
| `headway_mcp/client.py` | httpx client over the machine-key-reachable surface (`/machine/metrics`, the lineage walk, `/machine/dq/*`, `/machine/ops/vehicles/latest`, the two public endpoints). API refusals carried verbatim as `ApiRefusal`. |
| `headway_mcp/tools.py` | The tools. `_figure_payload` enforces the no-bare-number invariant on figures (a row missing receipt fields is refused, never served stripped); `_issue_headline` leads a DQ finding with agency vocabulary, never a bare UUID; empty results return refusal text, never `[]`. |
| `headway_mcp/server.py` | MCP registration (official SDK), server instructions stating the guarantee boundary, startup config refusal, stdio transport. |
| `scripts/mcp_transcript.py` | Live-verification harness: drives the server as a real MCP client (initialize → list → every tool). |

### Tools

| Tool | Scope | What it returns |
| --- | --- | --- |
| `metric_values` | `read:metrics` | Computed figures, each with its receipt (value string, cert status, calc name+version, verbatim detail, `metric_value_id`). |
| `explain_figure` | `read:metrics` | The "explain this number" lineage walk for one figure, down to raw records. |
| `verify_claim` | `read:metrics` | Byte-checks a claimed value/period against the store — `match` / `mismatch` / `no_such_figure`. |
| `certified_figures` | *(public)* | The human-signed certified open-data list, with certification refs. |
| `verify_certification` | *(public)* | Ed25519 tamper-evidence check of one certification. |
| `dq_summary` | `read:dq` | The data-quality queue in agency vocabulary: whole-queue counts by severity/status + a page of findings led by title/description/subject_context (never a bare UUID). |
| `dq_issue` | `read:dq` | One finding in full: its own description, its frozen subject_context, and the complete untruncated `source_record_ids` provenance. |
| `dq_blocking_for_period` | `read:dq` | The open, blocking findings — what a calc run refuses over. An empty result is explicit that a clear blocking queue is not a certification green light. |
| `ops_snapshot` | `read:ops` | The live vehicle snapshot with last-seen staleness framing and count honesty (`truncated`) — operations data, never a reported figure, never interpolated. |

**Deliberately absent (handoff 0039):** every WRITE action — resolving or
acknowledging a DQ finding, and certification — carries human accountability
and is not a tool. Paratransit rider coordinates, operator-identified
telematics, user accounts, and the audit trail stay withheld: a machine key
is a VIEWER-class principal and sensitivity does not relax for it (a future
scope would be needed). Sources status, calc-run status, and metrics
history/compare remain session-only for now (recorded follow-up).

## Configuration

| Env var | Meaning |
| --- | --- |
| `HEADWAY_MCP_API_KEY` | **Required.** A Headway machine key (`hwk_…`), issued via `POST /machine/keys`. Grant the scopes for the tools you want: `read:metrics` (metrics/certified), `read:dq` (data-quality queue), `read:ops` (operations snapshot). A tool whose scope the key lacks returns Headway's plain-language 403 verbatim. A session token is rejected — machine access is a separate, audited identity. |
| `HEADWAY_API_URL` | The Headway API base URL. Default `http://127.0.0.1:8000`. |

Run: `headway-mcp` (or `python -m headway_mcp`) — stdio transport, meant
to be spawned by an MCP client. See `docs/mcp.md` for Claude Desktop /
Claude Code config examples.

## Verification

```sh
# Unit + invariant suite (fakes only — no network, no live stack):
cd services/mcp && python -m pytest tests/ -q
# 42 passed  (schemas; startup refusal without a key / with a non-hwk credential;
#             refusal passthrough verbatim incl. scope denial; verify_claim
#             tri-state incl. rounded-value-is-a-mismatch; no-bare-number
#             invariant incl. refuse-on-stripped-row; empty-period refusal text;
#             no-DB-credential structural check; the read:dq / read:ops tools —
#             agency-vocabulary headlines, blocking-for-period empty refusal,
#             ops staleness verbatim, truncated preserved)

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

- The toolset wraps exactly the endpoints a machine key can reach: the
  `read:metrics`, `read:dq` (handoff 0039), and `read:ops` (handoff 0039)
  scopes, plus the unauthenticated public surface. Sources status, calc-run
  status, and metrics history/compare still require a human session today —
  named as deliberately absent in the tool descriptions and instructions.
- No write tools — resolving/acknowledging a DQ finding and certification
  carry human accountability and are deliberately not tools (the
  separation-of-duties argument, handoff 0034/0039). No prompt templates
  pretending to be policy, no streaming; stdio first, HTTP/SSE transport is
  a recorded follow-up.
