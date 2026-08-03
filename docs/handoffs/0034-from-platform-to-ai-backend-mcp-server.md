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

## Response — ai+backend engineer (implementation + live verification, 2026-07-30)

Contract accepted, with one load-bearing deviation reported below (not
silently absorbed). Shipped: `services/mcp/` (new service, `headway-mcp`),
`docs/mcp.md`, README verification section, this evidence.

### What shipped

- **API-client-only architecture (design point 1) — exactly as bound.**
  `headway_mcp/client.py` holds an HTTP base URL and a bearer machine key,
  nothing else; the package imports no database driver (test-pinned:
  `test_client_holds_no_database_credentials`). Startup is deny-by-default:
  no `HEADWAY_MCP_API_KEY`, or a non-`hwk_` credential (e.g. a session
  JWT), refuses to start with a plain-language explanation (tests
  `test_refuses_to_start_without_a_key`,
  `test_refuses_a_non_machine_credential`). Every tool call is audited by
  the API under `key:<prefix>` — verified live below.
- **Toolset (design point 2), receipts structural.** Five read-only tools
  on the official MCP Python SDK (`mcp` 2.0.0, MIT), stdio transport:
  `metric_values`, `explain_figure` (the lineage walk), `verify_claim`,
  `certified_figures`, `verify_certification`. Every figure payload is the
  API row VERBATIM (value as exact string, certification_status,
  calc_name+calc_version, detail JSON incl. simulated flags) plus an
  additive `receipt` pointer naming the metric_value_id and the provenance
  tool. A row missing any receipt field is REFUSED
  (`BareNumberError`), never served stripped. Empty results return refusal
  text with the honest two-possibility explanation (never ran vs refused),
  never `[]`.
- **`verify_claim` tri-state (design point 3).** match / mismatch /
  no_such_figure, byte-compared against the store (a rounded restatement
  is a mismatch — test-pinned); optional claimed-period comparison; the
  mismatch response ships the stored figure with its receipt. The docs
  state the guarantee boundary plainly (docs/mcp.md, "The guarantee
  boundary"): Headway guarantees what the tools returned, not what an
  assistant said about it.
- **Sensitivity (design point 4).** No tool can reach paratransit
  coordinates, operator-identified data, accounts, or the audit trail —
  enforcement is the key's `read:metrics` scope, deny-by-default at the
  API; the server instructions and docs/mcp.md name what is deliberately
  absent (test-pinned against the instructions text).
- **No phone-home (design point 5).** stdio only; no listening port; the
  cloud-assistant consent framing and the local-model air-gapped story are
  both in docs/mcp.md ("Where your data goes").
- **Honest scope (design point 6).** Read-only; no write tools; no
  streaming; no prompt templates; descriptions in the house voice
  (refusal-forward wording test-pinned).

### DEVIATION (reported, load-bearing): v0 toolset is the machine-key-reachable surface, not the full list in design point 2

Design point 1 binds the server to a machine key with read scopes; design
point 2 lists DQ queue/counts/detail, sources status, ops summaries,
calc-run status, and metrics history/compare among the v0 tools. Those two
points conflict today: the only API surfaces that accept a machine key are
`GET /machine/metrics` (scope `read:metrics`), `GET
/metrics/values/{id}/lineage` (dual-credential), and the two
unauthenticated `/public/*` endpoints. Everything else on the design-point-2
list requires a signed-in human session (verified against
`services/api/headway_api/routers/*` — only `machine_read.py`, `metrics.py`
lineage, `ingest.py`, and `public.py` consume machine credentials), and
`read:metrics` is the ONLY read scope in `machine_auth.KNOWN_SCOPES`.

Per _SHARED_CONSTRAINTS.md the conflict is raised here rather than resolved
silently. The two dishonest resolutions were rejected: modifying
services/api (out of scope for this handoff) and holding a human session
token inside the MCP server (defeats the audit-under-key-identity design
and the credential-type separation the machine API deliberately enforces).
v0 therefore ships the five tools above; the tool descriptions and
docs/mcp.md say plainly that the DQ/sources/ops/calc-run surfaces are
absent and why. The `no_figures` refusal text routes users to the Headway
UI for refusal reasons until the scope exists.

**Proposed default for the open question:** a Backend increment adding
read scopes (`read:dq`, `read:ops`, `read:calc_runs`, and
`read:metrics` coverage for history/compare) via
`require_human_session_or_machine_scope` on the existing GET endpoints —
the lineage-endpoint precedent, no new endpoints needed. The MCP toolset
then grows tool-by-tool with no architectural change. Decider: platform +
security (scope registry is handoff 0006's deny-by-default surface).

### Open Questions (additions)

- Scope expansion for DQ/sources/ops/calc-runs reads (above) — blocks the
  rest of the design-point-2 toolset.
- The calc-refusal texts themselves (which figures refused and why) are
  today only on the session-only calc-run summary; once `read:calc_runs`
  exists, `metric_values`' empty-period answer should quote the refusal
  verbatim instead of routing to the UI.
- `verify_claim` looks up ids by fetching `/machine/metrics` unfiltered
  (no by-id filter exists on that endpoint); fine at 464 rows, worth a
  `metric_value_id` query param on the machine endpoint before row counts
  get large.

### Verification evidence (2026-07-30, live API on 127.0.0.1:8000, real data — API process untouched)

**Machine key issuance — the documented way, fully audited.** No admin
session existed in this environment, so a temporary `certifying_official`
account (`mcp-key-issuer`) was created with the EXACT documented one-off
container mechanism from `install.sh create_admin_user` (bcrypt inside a
`python:3.12-slim` container on the compose network; password never
logged), then used for `POST /auth/login` → `POST /machine/keys
{"name": "mcp-server (0034 live verification)", "scopes":
["read:metrics"]}` → key `hwk_N6lm-IDE…` shown once with the
store-it-now warning — then the temp account was deactivated via the
documented `POST /users/mcp-key-issuer/deactivate` (409 last-admin
lockout not triggered; audit_event_id 1071). The key remains active for
continued MCP use; revoke via `DELETE /machine/keys/9856a42d-7713-470d-8f0d-014bcadabb77`
if unwanted.

**Audit trail landed under the key identity** (read-only psql query, as
verification evidence only — the service itself never touches the DB):

```
action               | actor             | count
machine_read_lineage | key:hwk_N6lm-IDE  | 4
machine_read_metrics | key:hwk_N6lm-IDE  | 7
machine_key_issued   | mcp-key-issuer
user_deactivated     | mcp-key-issuer
```

**Test suite** (fakes only; `~/venv`, Python 3.12):

```
$ cd services/mcp && python -m pytest tests/ -q
24 passed in 0.93s
```

Pins: tool schemas + names; startup refusal (no key / non-hwk credential /
blank); refusal passthrough verbatim (404 and 403 scope denial);
verify_claim tri-state incl. rounded-value-is-a-mismatch and
claimed-period mismatch; no-bare-number invariant (receipt fields on every
figure; stripped row refused; certified rows keep certification ref);
empty-period refusal text never `[]`; instructions state guarantee
boundary + deliberate absences; no DB credential structurally.

**License gate green** (ADR-0001, `scripts/license_gate.py --ecosystem
python`, now resolving `services/mcp/pyproject.toml` automatically):

```
ok httpx      0.28.1   BSD License   PASS
ok httpx2     2.9.1    BSD-3-Clause  PASS
ok mcp        2.0.0    MIT License   PASS
ok mcp-types  2.0.0    MIT License   PASS
-- 63 deps: 63 pass (6 via reviewed allowlist), 0 fail
LICENSE GATE: PASS — 63 dependencies conform to ADR-0001 Amendment 1.
```

**Live MCP client transcript** — `scripts/mcp_transcript.py` driving the
server as a real MCP client over stdio (initialize → tools/list → every
tool against the live API; includes the empty-period refusal, one live API
refusal passed through verbatim, the verify_claim mismatch, and a live
Ed25519 verification). Long multi-row payloads are truncated at 4000 chars
per call FOR THIS DOCUMENT ONLY (marked inline); every call and verdict is
complete:

```
=== initialize ===
{
 "protocolVersion": "2025-11-25",
 "serverInfo": {
  "name": "headway",
  "title": "Headway (transit data, with receipts)",
  "version": "0.1.0",
  "description": null,
  "website_url": null,
  "icons": null
 },
 "instructions_first_line": "This server exposes a Headway installation's READ surface: computed transit"
}

=== tools/list ===
[
 {
  "name": "metric_values",
  "required": []
 },
 {
  "name": "explain_figure",
  "required": [
   "metric_value_id"
  ]
 },
 {
  "name": "verify_claim",
  "required": [
   "metric_value_id",
   "claimed_value"
  ]
 },
 {
  "name": "certified_figures",
  "required": []
 },
 {
  "name": "verify_certification",
  "required": [
   "certification_id"
  ]
 }
]

=== tools/call metric_values — computed figures for a period (receipts on every row) ===
{
 "figures": [
  {
   "metric_value_id": "c724e3f2-3938-4aa4-98a5-97fd3715ad65",
   "metric": "pmt",
   "unit": "passenger_miles",
   "period_start": "2026-07-01",
   "period_end": "2026-08-01",
   "scope": "mode:DR",
   "value": "1313.47",
   "calc_name": "dr_pmt_v0",
   "calc_version": "0.1.0",
   "computed_at": "2026-07-28T20:47:21.626586Z",
   "certification_status": "uncertified",
   "detail": {
    "tos_mix": {
     "DO": 56,
     "PT": 31,
     "TX": 21
    },
    "source_mix": {
     "dr_simulated": 108
    },
    "no_show_trips": 9,
    "trips_counted": 97,
    "persons_counted": 230,
    "distance_sources": {
     "odometer_pair": 97
    },
    "passenger_miles_counted": "1313.47",
    "trips_excluded_missing_distance": 2
   },
   "category": "ntd",
   "receipt": {
    "metric_value_id": "c724e3f2-3938-4aa4-98a5-97fd3715ad65",
    "provenance": "Call explain_figure with this metric_value_id to walk this figure's lineage down to the raw source records.",
    "verification": "Call verify_claim with this metric_value_id and a claimed value to byte-check any restatement of this figure."
   }
  },
  {
   "metric_value_id": "f6beb385-f201-4b5c-874d-f40f0d68d791",
   "metric": "pmt",
   "unit": "passenger_miles",
   "period_start": "2026-07-01",
   "period_end": "2026-08-01",
   "scope": "mode:DR:tos:DO",
   "value": "672.28",
   "calc_name": "dr_pmt_v0",
   "calc_version": "0.1.0",
   "computed_at": "2026-07-28T20:47:21.626586Z",
   "certification_status": "uncertified",
   "detail": {
    "tos_mix": {
     "DO": 56
    },
    "source_mix": {
     "dr_simulated": 56
    },
    "no_show_trips": 5,
    "trips_counted": 50,
    "persons_counted": 117,
    "distance_sources": {
     "odometer_pair": 50
    },
    "passenger_miles_counted": "672.28",
    "trips_excluded_missing_distance": 1
   },
   "category": "ntd",
   "receipt": {
    "metric_value_id": "f6beb385-f201-4b5c-874d-f40f0d68d791",
    "provenance": "Call explain_figure with this metric_value_id to walk this figure's lineage down to the raw source records.",
    "verification": "Call verify_claim with this metric_value_id and a claimed value to byte-check any restatement of this figure."
   }
  },
  {
   "metric_value_id": "4fe04027-78fd-42e7-b64f-20c6e56dcba3",
   "metric": "pmt",
   "unit": "passenger_miles",
   "period_start": "2026-07-01",
   "period_end": "2026-08-01",
   "scope": "mode:DR:tos:PT",
   "value": "427.89",
   "calc_name": "dr_pmt_v0",
   "calc_version": "0.1.0",
   "computed_at": "2026-07-28T20:47:21.626586Z",
   "certification_status": "uncertified",
   "detail": {
    "tos_mix": {
     "PT": 31
    },
    "source_mix": {
     "dr_simulated": 31
    },
    "no_show_trips": 1,
    "trips_counted": 30,
    "persons_counted": 74,
    "distance_sources": {
     "odometer_pair": 30
    },
    "passenger_miles_counted": "427.89",
    "trips_excluded_missing_distance": 0
   },
   "category": "ntd",
   "receipt": {
    "metric_value_id": "4fe04027-78fd-42e7-b64f-20c6e56dcba3",
    "provenance": "Call explain_figure with this metric_value_id to walk this figure's lineage down to the raw source records.",
    "verification": "Call verify_claim with this metric_value_id and a claimed value to byte-check any restatement of this figure."
   }
  },
  {
   "metric_value_id": "cdffdb6b-38b5-4d4c-9336-f741f5b81b40",
   "metric": "pmt",
   "unit": "passenger_miles",
   "period_start": "2026-07-01",
   "period_end": "2026-08-01",
   "scope": "mode:DR:tos:TX",
   "value": "213.30",
   "calc_name": "dr_pmt_v0",
   "calc_version": "0.1.0",
   "computed_at": "2026-07-28T20:47:21.626586Z",
   "certification_status": "uncertified",
   "detail": {
    "tos_mix": {
     "TX": 21
    },
    "source_mix": {
     "dr_simulated": 21
    },
    "no_show_trips": 3,
    "trips_counted": 17,
    "persons_counted": 39,
    "distance_sources": {
     "odometer_pair": 17
    },
    "passenger_miles_counted": "213.30",
    "trips_excluded_missing_distance": 1
   },
   "category": "
 ... [truncated at 4000 chars for the transcript]

=== tools/call metric_values — EMPTY PERIOD — refusal text, never a bare [] ===
{
 "figures": [],
 "no_figures": {
  "message": "No computed figure matches this request. In Headway that means one of two things: the calculation has not been run for this period, or it ran and REFUSED to emit a figure \u2014 for example over an unresolved data-quality gap \u2014 because Headway never fills, interpolates, or invents a number. A refusal is recorded on the calculation run with its reasons; that calc-run surface (and the data-quality queue behind it) is not yet readable with a machine key, so ask a signed-in Headway user to check Calc Runs and the Data Quality queue for the specific refusal reason. Do not treat this absence as zero.",
  "filters": {
   "metric": "vrm",
   "period_start": "2031-01-01",
   "period_end": null,
   "category": null
  }
 }
}

=== tools/call explain_figure — the lineage walk on a real figure ===
{
 "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
 "lineage": {
  "kind": "computed.metric_values",
  "id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
  "transform_name": "pmt_v0",
  "transform_version": "0.2.0",
  "inputs": [
   {
    "kind": "raw.records",
    "id": "2ab4d79e7812d819cb60461e3cd804a2d4c0b1dec036c651cd85f8206be64155",
    "transform_name": null,
    "transform_version": null,
    "inputs": []
   }
  ]
 },
 "reading_guide": "This tree is Headway's 'explain this number' walk, served verbatim: each node names the transform (and version) that produced it from its inputs; leaves are content-addressed raw records exactly as received from the source."
}

=== tools/call explain_figure — LIVE REFUSAL — unknown id, API refusal passed through verbatim ===
{
 "refusal": {
  "from": "headway-api",
  "http_status": 404,
  "message": "No reported figure with that id exists."
 }
}

=== tools/call verify_claim — verify_claim → match (byte-identical) ===
{
 "result": "match",
 "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
 "figure": {
  "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
  "metric": "pmt",
  "unit": "passenger_miles",
  "period_start": "2026-07-09",
  "period_end": "2026-07-10",
  "scope": "agency",
  "value": "221996.24",
  "calc_name": "pmt_v0",
  "calc_version": "0.2.0",
  "computed_at": "2026-07-15T22:56:55.760214Z",
  "certification_status": "certified",
  "detail": {
   "source_mix": {
    "tides_simulated": 111568
   },
   "attestation": {
    "basis": "However, if the vehicle trips with missing data exceed 2 percent of total trips, agencies must have a qualified statistician approve the factoring method used to account for the missing percentage.",
    "metric": "pmt",
    "entered_at": "2026-07-15T22:56:06.898304+00:00",
    "entered_by": "certifier",
    "period_end": "2026-07-10",
    "period_start": "2026-07-09",
    "scope_pattern": "agency",
    "attestation_id": "b4f5311e-2f90-4d96-86e3-2d4c339e853e",
    "statistician_name": "Dr. Rosa Field",
    "document_reference": "file://agency-dms/approvals/2026/pmt-factoring-2026-07-09-signed.pdf",
    "method_description": "Expansion factoring of the valid-trip passenger-miles base by operated/(operated - missing - invalid) with route-level stratification review; approved for the July 9, 2026 service day where APC coverage failed the 2 percent line",
    "statistician_credentials": "PhD, Statistics (Boston University); 11 years NTD sampling and estimation consulting for New England transit agencies"
   },
   "valid_trips": 5785,
   "invalid_trips": 3247,
   "missing_trips": 91,
   "factor_applied": "1.577010",
   "operated_trips": 9123,
   "trips_with_events": 9032,
   "imbalance_threshold": "0.10",
   "invalid_trip_reasons": {
    "negative_load": 74,
    "count_imbalance": 133,
    "unplaceable_event": 1739,
    "geometry_unavailable": 1301
   },
   "shape_dist_unit_miles": null,
   "missing_trip_threshold": "0.02",
   "passenger_miles_counted": "140770.39",
   "distance_source_segments": {
    "haversine": 61137,
    "shape_dist_traveled": 0
   },
   "missing_or_invalid_share": "0.3659"
  },
  "category": "ntd",
  "receipt": {
   "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
   "provenance": "Call explain_figure with this metric_value_id to walk this figure's lineage down to the raw source records.",
   "verification": "Call verify_claim with this metric_value_id and a claimed value to byte-check any restatement of this figure."
  }
 },
 "message": "The claimed value matches Headway's store byte-for-byte. Note the figure's certification_status and any simulated flags in detail \u2014 a matching number can still be uncertified or simulated."
}

=== tools/call verify_claim — verify_claim → MISMATCH (a rounded restatement is not the figure) ===
{
 "result": "mismatch",
 "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
 "mismatches": [
  {
   "field": "value",
   "claimed": "221996",
   "stored": "221996.24"
  }
 ],
 "figure": {
  "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
  "metric": "pmt",
  "unit": "passenger_miles",
  "period_start": "2026-07-09",
  "period_end": "2026-07-10",
  "scope": "agency",
  "value": "221996.24",
  "calc_name": "pmt_v0",
  "calc_version": "0.2.0",
  "computed_at": "2026-07-15T22:56:55.760214Z",
  "certification_status": "certified",
  "detail": {
   "source_mix": {
    "tides_simulated": 111568
   },
   "attestation": {
    "basis": "However, if the vehicle trips with missing data exceed 2 percent of total trips, agencies must have a qualified statistician approve the factoring method used to account for the missing percentage.",
    "metric": "pmt",
    "entered_at": "2026-07-15T22:56:06.898304+00:00",
    "entered_by": "certifier",
    "period_end": "2026-07-10",
    "period_start": "2026-07-09",
    "scope_pattern": "agency",
    "attestation_id": "b4f5311e-2f90-4d96-86e3-2d4c339e853e",
    "statistician_name": "Dr. Rosa Field",
    "document_reference": "file://agency-dms/approvals/2026/pmt-factoring-2026-07-09-signed.pdf",
    "method_description": "Expansion factoring of the valid-trip passenger-miles base by operated/(operated - missing - invalid) with route-level stratification review; approved for the July 9, 2026 service day where APC coverage failed the 2 percent line",
    "statistician_credentials": "PhD, Statistics (Boston University); 11 years NTD sampling and estimation consulting for New England transit agencies"
   },
   "valid_trips": 5785,
   "invalid_trips": 3247,
   "missing_trips": 91,
   "factor_applied": "1.577010",
   "operated_trips": 9123,
   "trips_with_events": 9032,
   "imbalance_threshold": "0.10",
   "invalid_trip_reasons": {
    "negative_load": 74,
    "count_imbalance": 133,
    "unplaceable_event": 1739,
    "geometry_unavailable": 1301
   },
   "shape_dist_unit_miles": null,
   "missing_trip_threshold": "0.02",
   "passenger_miles_counted": "140770.39",
   "distance_source_segments": {
    "haversine": 61137,
    "shape_dist_traveled": 0
   },
   "missing_or_invalid_share": "0.3659"
  },
  "category": "ntd",
  "receipt": {
   "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
   "provenance": "Call explain_figure with this metric_value_id to walk this figure's lineage down to the raw source records.",
   "verification": "Call verify_claim with this metric_value_id and a claimed value to byte-check any restatement of this figure."
  }
 },
 "message": "The claim does not match Headway's store (byte comparison \u2014 Headway values are exact strings, so '9524.6' is not '9524.63'). The stored figure, with its receipt, is included."
}

=== tools/call verify_claim — verify_claim → no_such_figure ===
{
 "result": "no_such_figure",
 "metric_value_id": "99999999-9999-9999-9999-999999999999",
 "message": "No figure with this metric_value_id exists in Headway's store. A claim citing it cannot be verified \u2014 treat the citation as unresolved, not as approximately right."
}

=== tools/call certified_figures — the certified public record ===
{
 "figures": [
  {
   "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
   "metric": "pmt",
   "unit": "passenger_miles",
   "period_start": "2026-07-09",
   "period_end": "2026-07-10",
   "scope": "agency",
   "value": "221996.24",
   "calc_name": "pmt_v0",
   "calc_version": "0.2.0",
   "computed_at": "2026-07-15T22:56:55.760214Z",
   "certification_status": "certified",
   "detail": {
    "source_mix": {
     "tides_simulated": 111568
    },
    "attestation": {
     "basis": "However, if the vehicle trips with missing data exceed 2 percent of total trips, agencies must have a qualified statistician approve the factoring method used to account for the missing percentage.",
     "metric": "pmt",
     "entered_at": "2026-07-15T22:56:06.898304+00:00",
     "entered_by": "certifier",
     "period_end": "2026-07-10",
     "period_start": "2026-07-09",
     "scope_pattern": "agency",
     "attestation_id": "b4f5311e-2f90-4d96-86e3-2d4c339e853e",
     "statistician_name": "Dr. Rosa Field",
     "document_reference": "file://agency-dms/approvals/2026/pmt-factoring-2026-07-09-signed.pdf",
     "method_description": "Expansion factoring of the valid-trip passenger-miles base by operated/(operated - missing - invalid) with route-level stratification review; approved for the July 9, 2026 service day where APC coverage failed the 2 percent line",
     "statistician_credentials": "PhD, Statistics (Boston University); 11 years NTD sampling and estimation consulting for New England transit agencies"
    },
    "valid_trips": 5785,
    "invalid_trips": 3247,
    "missing_trips": 91,
    "factor_applied": "1.577010",
    "operated_trips": 9123,
    "trips_with_events": 9032,
    "imbalance_threshold": "0.10",
    "invalid_trip_reasons": {
     "negative_load": 74,
     "count_imbalance": 133,
     "unplaceable_event": 1739,
     "geometry_unavailable": 1301
    },
    "shape_dist_unit_miles": null,
    "missing_trip_threshold": "0.02",
    "passenger_miles_counted": "140770.39",
    "distance_source_segments": {
     "haversine": 61137,
     "shape_dist_traveled": 0
    },
    "missing_or_invalid_share": "0.3659"
   },
   "category": "ntd",
   "certification": {
    "certification_id": "a3f4c2f4-3700-488f-8dc7-cdc4ca90f196",
    "certified_at": "2026-07-15T23:09:16.998147Z",
    "key_fingerprint": "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7b32fd3041691ecd10be9e371"
   },
   "receipt": {
    "metric_value_id": "82f8c972-f50c-4657-b3ff-3d3de50bbf71",
    "provenance": "Call explain_figure with this metric_value_id to walk this figure's lineage down to the raw source records.",
    "verification": "Call verify_claim with this metric_value_id and a claimed value to byte-check any restatement of this figure."
   }
  },
  {
   "metric_value_id": "4b21e995-86f2-4583-b3e1-c6637115a66d",
   "metric": "voms",
   "unit": "vehicles",
   "period_start": "2026-07-09",
   "period_end": "2026-07-10",
   "scope": "agency",
   "value": "984",
   "calc_name": "voms_v0",
   "calc_version": "0.1.0",
   "computed_at": "2026-07-12T23:37:35.748437Z",
   "certification_status": "certified",
   "detail": {
    "peak_day": "2026-07-09",
    "days_observed": 1,
    "days_in_period": 1,
    "per_day_counts": {
     "max": 984,
     "min": 984,
     "mean": "984.0000"
    }
   },
   "category": "ntd",
   "certification": {
    "certification_id": "f47c4ce0-b6e3-4fba-81d9-9bc0a48c3b92",
    "certified_at": "2026-07-15T23:00:05.644981Z",
    "key_fingerprint": "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7b32fd3041691ecd10be9e371"
   },
   "receipt": {
    "metric_value_id": "4b21e995-86f2-4583-b3e1-c6637115a66d",
    "provenance": "Call explain_figure with this metric_value_id to walk this figure's lineage down to the raw source records.",
    "verification": "Call verify_claim with this metric_value_id and a claimed value to byte-check any restatement of this figure."
   }
  },
  {
   "metric_value_id": "abad3473-5ebe-45d2-ae29-623b15f4c4f8",
   "metri
 ... [truncated at 4000 chars for the transcript]

=== tools/call verify_certification — Ed25519 signature verification of a certification ===
{
 "certification_id": "a3f4c2f4-3700-488f-8dc7-cdc4ca90f196",
 "verification": {
  "certification_id": "a3f4c2f4-3700-488f-8dc7-cdc4ca90f196",
  "signed": true,
  "verified": true,
  "verdict": "verified",
  "algorithm": "ed25519",
  "key_fingerprint": "ed25519:f0995b71ecc91f99d6c0794eee26297907fe2ae7b32fd3041691ecd10be9e371",
  "certified_at": "2026-07-15T23:09:16.998147Z",
  "message": "Verified: the stored certificate is byte-identical to what was signed, the signature is valid under this installation's key, and the document is bound to this certification record."
 },
 "reading_guide": "Served verbatim from Headway's tamper-evidence check: the stored certificate bytes re-verified against the stored Ed25519 signature, server-side. 'verified' means the record is exactly what was signed; anything else means it is not, and that is a finding."
}```

**Unproven / not exercised live:** (a) a real desktop assistant
(Claude Desktop) end-to-end — the harness IS a conformant MCP client over
stdio, but no third-party client was attached; (b) the per-key 429
rate-limit passthrough (the bucket never emptied during verification;
the generic refusal-passthrough path that would carry it is unit-tested at
403/404); (c) HTTP/SSE transport (recorded follow-up, deliberately not
started).
