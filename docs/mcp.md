# Ask your assistant about your transit data — with receipts

Headway ships an MCP server (`services/mcp/`): a small program that lets an
AI assistant — Claude Desktop, Claude Code, or a local open-weight model
with an MCP client — read this installation's computed figures, walk their
provenance, and verify claims about them. The Model Context Protocol (MCP)
is an open standard for connecting assistants to tools.

The one-sentence version: **your data, your box, your assistant — with
receipts.** Every figure the assistant sees carries its certification
status, its calculation name and version, its verbatim calculation detail
(including simulated-data flags), and a `metric_value_id` that walks all
the way down to raw source records. When there is no figure, the assistant
is told why — never handed an empty list to fill with a guess.

## How it connects

```
assistant  ⇄  headway-mcp (stdio, on your box)  ⇄  Headway HTTP API  ⇄  database
```

The MCP server is a **client of the Headway API and nothing else**. It
holds no database credentials. It authenticates with a machine API key
(`hwk_…`) carrying only the `read:metrics` permission, so the API remains
the authorization boundary and **every tool call lands in the audit trail**
under that key's identity (`key:<prefix>`) — the same discipline as every
other machine integration. Without a key, the server refuses to start.

## Setup

1. **Issue a machine key** (a Headway administrator, signed in as the
   certifying official):

   ```sh
   curl -s -X POST https://your-headway/machine/keys \
     -H "Authorization: Bearer <session token>" -H 'Content-Type: application/json' \
     -d '{"name": "mcp-server", "scopes": ["read:metrics"]}'
   ```

   The full key is shown once — store it now. Revoke it any time with
   `DELETE /machine/keys/{key_id}`; revocation takes effect immediately.

2. **Install** (same box as the API, or any machine that can reach it):

   ```sh
   pip install ./services/mcp        # installs the `headway-mcp` command
   ```

3. **Point your assistant at it.** Claude Desktop
   (`claude_desktop_config.json`) or any MCP-capable client:

   ```json
   {
     "mcpServers": {
       "headway": {
         "command": "headway-mcp",
         "env": {
           "HEADWAY_API_URL": "http://127.0.0.1:8000",
           "HEADWAY_MCP_API_KEY": "hwk_..."
         }
       }
     }
   }
   ```

   Claude Code:

   ```sh
   claude mcp add headway \
     --env HEADWAY_API_URL=http://127.0.0.1:8000 \
     --env HEADWAY_MCP_API_KEY=hwk_... \
     -- headway-mcp
   ```

## What it exposes

| Tool | What it answers |
| --- | --- |
| `metric_values` | Computed figures (VRM, VRH, UPT, PMT, VOMS, operations metrics), filterable by metric, period, and the ntd/ops honesty boundary. Every row is a receipt, not a bare number. |
| `explain_figure` | The "explain this number" walk: figure → transforms (name+version) → content-addressed raw records. |
| `verify_claim` | Given a `metric_value_id` and a claimed value (and optionally a claimed period): **match**, **mismatch**, or **no-such-figure**, byte-compared against the store. |
| `certified_figures` | The human-certified public record, with each figure's certification reference and signing-key fingerprint. |
| `verify_certification` | Re-verifies a certification's Ed25519 signature server-side and returns the verdict. |

All tools are **read-only**. There are no certify, resolve, ingest, or
user-management tools, and there is deliberately no plan to add
certification by assistant: certification is a human attestation, and
separation of duties says the surface that summarizes figures should not
also be able to sign them.

## What it deliberately does not expose

Per [the data classification](data-classification.md):

- **Paratransit trip coordinates** (rider home and destination addresses —
  the highest-sensitivity data in the platform) and anything
  ADA-eligibility adjacent. No tool serves them; the analyst-role
  column-withholding precedent applies here with no exceptions.
- **Operator-identified data** — vehicle-position histories joined to
  people, driver-identified telematics.
- **User accounts and the audit trail** — a security record and an
  employee record at once.
- The **data-quality queue, sources status, operations summaries, and
  calc-run status** are absent for a different reason: today those API
  endpoints require a signed-in human session, and the MCP server refuses
  to impersonate one. Exposing them behind new read scopes is a recorded
  open question in handoff 0034 — until then, refusal reasons live in the
  Headway UI.

Enforcement is not politeness: the machine key's scopes are checked by the
API on every request, deny-by-default. A key with `read:metrics` can read
computed figures and their lineage, and nothing else.

## The guarantee boundary, stated plainly

**Headway guarantees what the tools returned. It cannot guarantee what an
assistant says about it.** A language model writing prose about your
figures is outside Headway's deterministic pipeline — it can round,
paraphrase, or misremember. What Headway can do is make every claim one
call away from verification: `verify_claim` byte-compares any restated
number against the store and answers match, mismatch, or no-such-figure.
If a summary matters — a board packet, a press number — verify it, or read
it from `certified_figures`, which serves only what your certifying
official signed.

The same discipline the platform applies everywhere applies here: the MCP
server never computes, rounds, fills, or reconciles a number. Figures
originate only in the versioned calculation library; refusals (the
calculation declining to emit a figure over a data gap) pass through in
Headway's own words.

## Where your data goes

Nothing, anywhere, unless you connect it. The server speaks stdio to a
client on your machine and HTTP to your Headway API; it opens no listening
port and phones nothing home. Two honest notes:

- **Connecting a cloud assistant (like Claude Desktop) sends whatever the
  tools return to that vendor's service** as part of your conversation.
  That is your explicit act and your call to make — the same consent
  framing as every other outbound path in Headway. Don't connect a cloud
  assistant if your governance says figures can't leave the building.
- **The air-gapped story works today:** the server works identically with
  a local MCP client driving a local open-weight model (Ollama-class). No
  Headway feature here depends on any cloud service.

HTTP/SSE transport for networked assistants (with the compose profile and
TLS story that deserves) is recorded as a follow-up, not improvised.

## Verifying it yourself

`services/mcp/README.md` has the verification section: the unit suite
(`pytest`), the license gate, and a transcript harness
(`scripts/mcp_transcript.py`) that drives the server as a real MCP client
against your live API — initialize, list tools, call everything, including
a refusal and a deliberate mismatch.
