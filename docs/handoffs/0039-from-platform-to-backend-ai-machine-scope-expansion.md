# Handoff: platform → backend+ai — Machine-key scopes read:dq and read:ops (and the MCP toolset that grows with them)

## Context

Handoff 0034 shipped the MCP server against the machine-key-reachable surface and
recorded the deviation honestly: v0 could only see what `read:metrics` (and lineage)
expose, so an assistant can explain a figure but cannot answer "what's blocking my
July figures?" or "which vehicles went quiet this morning?" — the two questions the
DQ queue and the ops surfaces answer for humans. The queued expansion is now due:
two new machine scopes, the read-only machine endpoints they authorize, and the MCP
tools that consume them.

## Design (binding)

1. **Two new scopes in the v0 registry** (`headway_api/machine_auth.py`):
   `read:dq`, `read:ops`. Existing keys are untouched; scope grant stays explicit at
   key creation (no scope is implied by another). Generic-401 no-leak behavior is
   preserved everywhere: a key lacking the scope learns nothing about what exists.
2. **Machine endpoints mirror the human read surface — they do not fork it.** The
   DQ queue reads (list with the 0030 keyset pagination + counts + single-issue
   detail with provenance) and the ops reads (latest vehicle positions, ops metric
   values) get machine-key-authorized paths (either new `/machine/...` routes or
   scope-aware auth on the existing routers — study how `/machine/metrics` did it
   and follow that precedent; record the choice). Figures/counts serve VERBATIM
   from the same queries the human UI uses; no new SQL shapes without need.
3. **Sensitivity does not relax for machines.** Column-level withholdings (DR
   rider coordinates, migration 0028) and the 0035 sensitivity rules apply to
   machine reads exactly as to signed-in viewers-without-role: a machine key is a
   VIEWER-class principal for sensitive content unless a future scope says
   otherwise (that future scope is out of this wave — say so in docs). Audit every
   machine read as the existing machine surface audits (`key:<prefix>`).
4. **MCP tools** (`services/mcp`): grow the toolset with, at minimum: DQ queue
   summary/counts (agency vocabulary: routes, vehicles, blocks — never bare issue
   UUIDs as the headline), DQ issue detail (the finding's own plain-language
   description + linked evidence refs), blocking-for-period ("what stands between
   this period and certifiable figures" — the calc-runs refusal story), and an ops
   snapshot (staleness/last-seen framing, never interpolation). Every tool honors
   the 0034 invariants: no bare numbers (figures only travel with their receipt
   fields), refusal text over empty arrays, tri-state verify_claim untouched or
   extended compatibly. Tool descriptions state what is DELIBERATELY absent.
5. **Docs + transcript**: README tool reference updated; the live transcript
   harness (`scripts/mcp_transcript.py`) extended to call the new tools against
   the live API with a real hwk_ key carrying the new scopes (create a fresh demo
   key for the run; leave it in scratchpad and NAME its key id in evidence so the
   orchestrator can revoke/store it — the 0034 precedent).
6. **Tests**: api suite (scope grant/deny per endpoint, generic 401, audit rows,
   withheld columns stay withheld to machine keys), mcp suite (new tools, no-bare-
   number enforcement, refusal texts). OpenAPI drift gate: regenerate if routes
   were added.

## Outputs

Code + tests green (api, mcp), openapi.json in sync, README/docs updated, live MCP
transcript with the new tools, evidence appended here (house style: what was run,
what was observed, deviations, open items). No commits — the orchestrator
integrates.

## Open Questions

- Whether `read:ops` should include the geometry endpoints (a map-drawing
  assistant) or stay tabular — decide and record.
- Scoped WRITE (e.g. acknowledging a DQ issue via assistant) is explicitly out:
  resolution carries human accountability. Note it in the tool descriptions'
  "deliberately absent" list.
- Rate limiting for machine reads at MCP call cadence — observe and record, don't
  build yet.
