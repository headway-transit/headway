# Handoff: platform → ai+backend — The Headway MCP server (read-only, receipts-first)

## Context
Project-lead direction (2026-07-29/30): expose Headway to AI assistants via the Model
Context Protocol — an analyst or GM asks a question in their assistant of choice and
every figure that comes back carries its receipt, or the answer is a refusal that
explains itself. The boundary was set when the idea was raised: **the MCP server exposes
Headway's read surface; it never ingests vendor data** (deterministic connectors own
ingestion — a language model in a compliance ingestion path is nondeterminism in the
wrong place). This is the platform's first user-facing AI surface; the role-mandated
ordering is satisfied (the grounding harness shipped first, services/ai).

The adoption sentence this serves: *your data, your box, your assistant — with receipts.*

## Design (binding)

1. **The server is an API client, never a database client.** Architecture:
   `assistant ⇄ MCP server ⇄ Headway HTTP API ⇄ DB`. The API is the authz + audit
   boundary; the MCP server authenticates to it with a **machine key (`hwk_`, read
   scopes only)** from env, refuses to start without one, and holds no DB credentials.
   Every tool call therefore lands in the existing audit trail under that key's
   identity. New service `services/mcp/` (Python per ADR-0008; official MCP SDK — MIT,
   license-gate it), stdio transport first (Claude Desktop / local clients), HTTP
   transport recorded as follow-up.
2. **Read-only toolset, receipts structural.** v0 tools wrap existing endpoints only:
   metrics values / history / compare, the lineage walk ("explain this number"), DQ
   queue page + counts + issue detail, certifications + signature verification, sources
   status, ops summaries, calc-run status, the public certified list. **No tool returns
   a bare number**: every figure payload carries, verbatim from the API, its
   certification status, simulated flags, calc name+version, and receipt/lineage
   pointers. Refusals and empty periods return the refusal text — never `[]` where the
   truth is "the calculation refused, and here is why."
3. **`verify_claim` — the tool that makes AI summaries checkable.** Given a metric-value
   id and a claimed value/period, it answers match / mismatch / no-such-figure from the
   store, byte-compared. Headway cannot gate what a downstream model writes in prose;
   it CAN make every claim one call away from verification, and the docs state that
   boundary plainly: Headway guarantees what the tools returned, not what an external
   assistant said about it.
4. **Sensitivity follows the classification doc.** No tool exposes paratransit
   coordinates or any operator-identified data (docs/data-classification.md; the
   analyst-role column-withholding precedent). Scopes on the machine key are the
   enforcement; the tool descriptions say what is deliberately absent.
5. **No phone-home, agency's assistant choice.** The server binds locally; connecting
   it to a cloud assistant is the agency's explicit act, documented with the same
   consent framing as every other outbound path — and it works identically with a local
   Ollama-class model, which is the air-gapped story.
6. **Honest scope:** read-only (no certify/resolve/user actions — recorded as an open
   question with the separation-of-duties argument for why maybe never); no streaming;
   no prompt templates pretending to be policy; tool descriptions written in the house
   voice (plain, verbatim-quote-preserving, refusal-forward).

## Outputs
`services/mcp/` with tests (tool schemas, auth refusal, refusal passthrough,
verify_claim tri-state, no-bare-number invariant pinned); license gate green; live
verification against the running API with a real read-scoped `hwk_` key from an MCP
client harness (initialize → list tools → call every tool → transcript in evidence),
including at least one live refusal and one verify_claim mismatch; a Claude
Desktop/CLI config example + `docs/mcp.md` (what it exposes, what it deliberately does
not, the guarantee boundary); README verification section; evidence appended here. No
commits — the orchestrator integrates.

## Open Questions
- HTTP/SSE transport + compose profile for networked assistants.
- Write actions (calc-run trigger first?) — separation-of-duties argument pending.
- A grounded summarize-my-month tool using services/ai's harness server-side, so at
  least one AI-written surface IS inside the grounding guarantee.

## Outputs — evidence
(appended by the implementing agent)
