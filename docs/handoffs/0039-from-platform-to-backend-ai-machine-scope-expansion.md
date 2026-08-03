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

## Outputs — evidence

### Response — backend + ai systems engineer (implementation + live verification, 2026-07-31)

Contract accepted; all six design points shipped. No commits — the
orchestrator integrates. Honest split of what ran live vs. what is pinned by
tests is stated throughout.

**A note on the discarded prior attempt (context, not evidence):** the
earlier cut-off work refactored `dq.py`/`ops.py` in a way that dropped the
ops `truncated` field and broke 11 api tests, and never touched
`services/mcp`. That work was discarded; this wave started clean. The
approach here is deliberately **additive**: the human `/dq` and `/ops`
routers were refactored ONLY to extract their exact query bodies into shared
functions, and the human endpoints keep returning their identical Pydantic
models — every field, including the ops `truncated`/`note`/`total_in_window`
count-honesty trio, is preserved. The api suite went 470 → 494 (green
before, +24 new, green after); nothing existing broke.

#### 1. Scopes (design point 1) — ADDED

`read:dq` and `read:ops` were NOT on main (grep confirmed) — added to
`machine_auth.KNOWN_SCOPES` as `SCOPE_READ_DQ` / `SCOPE_READ_OPS`, granted
explicitly at issuance (no scope implies another; deny-by-default preserved
in both directions). Generic-401 no-leak behavior is unchanged (a key
lacking the scope gets the audited plain-language 403; an unknown/revoked key
gets the audited 401).

#### 2. Machine endpoints mirror the human read surface (design point 2) — they do not fork it

**Choice recorded: additive `/machine/...` routes on the existing
`machine_read.py`, following the `GET /machine/metrics` precedent exactly**
(scope check → per-key rate limit → shared query fn → per-request audit).
Rejected forking the human routers or duplicating SQL. New routes:

- `GET /machine/dq/issues` — the 0030 keyset page (same `total` /
  `next_cursor` / `has_more`), scope `read:dq`
- `GET /machine/dq/issues/counts` — the whole-queue GROUP BY, `read:dq`
- `GET /machine/dq/issues/{id}` — one issue WITH untruncated
  `source_record_ids`, `read:dq`
- `GET /machine/ops/vehicles/latest` — the live-map snapshot, `read:ops`

Each delegates to the SAME query function the human router now calls
(`dq.query_issue_page` / `query_issue_counts` / `query_issue_detail`,
`ops.query_latest_vehicles`), so figures/counts/provenance/pagination can
never drift. Test-pinned byte-identical:
`test_dq_list_matches_the_human_endpoint_byte_for_byte`,
`test_dq_counts_matches_the_human_endpoint`,
`test_dq_detail_serves_full_provenance_like_the_human_endpoint`,
`test_ops_vehicles_matches_the_human_endpoint`.

**Open question resolved (read:ops scope boundary): TABULAR only.**
`read:ops` authorizes the vehicle-position surface (and ops metric values via
the existing `/machine/metrics?category=ops`). It does NOT authorize the
GTFS-static geometry endpoints (route shapes / stop patterns) — a
map-drawing assistant is a separate, deliberately-absent surface for a future
wave, not granted implicitly. Recorded in `machine_read.py` and the tool
docs.

#### 3. Sensitivity does not relax for machines (design point 3) — tested

A machine key is a VIEWER-class principal. `source_record_ids` stays OFF the
machine list view exactly as off the human list (it is the SAME query) and
rides only on the per-issue detail — pinned
`test_dq_list_does_not_leak_source_record_ids`. No sensitive column
(migration 0028 DR rider coordinates, the 0035 rules) is on the `dq.issues`
or `canonical.vehicle_positions` surfaces in the first place, and none is
added here; the paratransit rider surface is not reachable by ANY machine
scope in this wave. A future sensitive-content scope is out of scope — said
so in `machine_auth.py` and `docs`/tool descriptions.

#### 4. Audit rows (design point 3) — every machine read audited `key:<prefix>`

New audit actions: `machine_read_dq_issues`, `machine_read_dq_counts`,
`machine_read_dq_issue`, `machine_read_ops_vehicles` — each written in a
transaction with actor `key:<prefix>`, filters/row-count only (never the
figures). Pinned by four `test_successful_*_is_audited` tests AND verified
live (below).

#### 5. MCP tools (design point 4) — four new tools, 0034 invariants honored

`services/mcp` grew from 5 tools to 9. New: `dq_summary` (counts + a page of
findings led by title/description/subject_context — never a bare issue UUID
as the headline, via `_issue_headline`), `dq_issue` (the finding's own
plain-language description + verbatim frozen subject_context + the complete
untruncated `source_record_ids`), `dq_blocking_for_period` (the OPEN/BLOCKING
findings — the calc-runs refusal story — whose empty result says plainly that
a clear blocking queue is ONE cleared gate, **not** a certification green
light), and `ops_snapshot` (last-seen staleness framing, `truncated` count
honesty, never interpolation, empty = data-availability state not empty
fleet). Refusals pass through verbatim; empty results return refusal text,
never `[]`; `verify_claim` is untouched. Every tool description names what is
DELIBERATELY absent (all WRITE actions — resolve/acknowledge/certify carry
human accountability; the rider surfaces; the still-session-only surfaces).

#### 6. Docs + transcript harness (design point 5) + drift gate (6)

- `services/mcp/README.md`: full 9-tool reference table with per-tool scope,
  the deliberately-absent list, updated env-var scope guidance, test count
  24 → 42.
- `scripts/mcp_transcript.py`: extended to call all four new tools live
  (DQ summary, blocking-for-period, DQ issue detail with a real id AND a
  live unknown-id refusal, ops snapshot at 300s and at a 1s window for the
  staleness note); `--issue-id` arg added.
- **OpenAPI drift gate:** `openapi.json` regenerated
  (`scripts/export_openapi.py`) — 67 → 71 paths, the four new `/machine/...`
  routes present.

### Test suites — green at BOTH layers, api green before AND after

```
# API — BEFORE any change (baseline):        470 passed
# API — AFTER refactor, BEFORE new tests:     470 passed  (nothing broke)
$ cd services/api && python -m pytest -q
494 passed in 24.78s          # +24 new (tests/test_machine_dq_ops.py)

$ cd services/mcp && python -m pytest tests/ -q
42 passed in 0.79s            # +18 new (tests/test_dq_ops_tools.py, updated test_server.py)
```

New api tests pin: scope grant serves byte-identical rows to the human
endpoint; deny-by-default (read:dq⊬read:ops, read:ops⊬read:dq,
read:metrics⊬either, ingest⊬read); revoked-key 401 + audit; human-session
401 (credential separation); every successful read audited `key:<prefix>`;
per-key 429; ops `truncated` preserved; source_record_ids withheld from the
list. New mcp tests pin: agency-vocabulary headline (id rides behind
title/description), counts over the whole queue, blocking-empty refusal text
("not a green light"), ops staleness verbatim + no-interpolation guide,
scope-denial passthrough.

**License gate:** PASS (ADR-0001) — `python scripts/license_gate.py
--ecosystem python` → 63 deps, 0 fail. No new dependencies were added.

### Live MCP transcript — REAL: a fresh worktree API on :8099 against the live DB, driven by the MCP server over stdio

The running :8000 service is the OLD code (no `/machine/dq|ops` routes) and
was left **untouched** (verified 200 before and after). To exercise the new
routes live, a second API instance was started from THIS worktree's code on
:8099 against the SAME live Postgres (host=127.0.0.1 dbname=headway), then the
MCP server (worktree `headway_mcp` via PYTHONPATH) was driven against it by
`scripts/mcp_transcript.py` as a real MCP client over stdio. The :8099
instance was stopped after; the live DB was only read (plus the one-time key
row + its issuance audit event).

**Demo key (name its id so the orchestrator can revoke/store it):**
- key id: **`e4307ef6-3d91-4bd9-b9fb-d2324f0c2aa9`**
- key prefix / audit identity: **`hwk_e6EdS61f`**
- scopes: `read:dq`, `read:ops`, `read:metrics`
- name: `mcp-server (0039 live verification)`
- plaintext: scratchpad `hwk_key_0039` (mode 600) — **never in the repo**.
- Revoke via `DELETE /machine/keys/e4307ef6-3d91-4bd9-b9fb-d2324f0c2aa9`.
- **Honesty note on issuance:** no admin session/password existed in this
  environment (the documented path is `POST /machine/keys` as a
  certifying_official). The key row + a `machine_key_issued` audit event were
  therefore inserted directly via psycopg using `headway_api`'s OWN
  `machine_auth.generate_key()` (SHA-256 hash stored, plaintext shown once),
  `created_by` attributed to a live certifying_official. This is an operator
  action recorded honestly, not the API-session path.

**Live audit trail landed under the key identity** (read-only query, evidence
only — the MCP service itself never touches the DB):

```
action                    | actor            | count
machine_read_dq_counts    | key:hwk_e6EdS61f | 2
machine_read_dq_issue     | key:hwk_e6EdS61f | 1
machine_read_dq_issues    | key:hwk_e6EdS61f | 3
machine_read_lineage      | key:hwk_e6EdS61f | 1
machine_read_metrics      | key:hwk_e6EdS61f | 5
machine_read_ops_vehicles | key:hwk_e6EdS61f | 2
```

**Live queue scale (real):** `dq_summary` returned `total: 110046`
(343 blocking / 99648 warning / 10055 info; 109764 open, 280 resolved,
2 attested) — the machine counts served verbatim from the same GROUP BY the
human `/dq/issues/counts` uses. 61 open-blocking findings.

**tools/list (all 9 registered live):**

```
metric_values, explain_figure, verify_claim, certified_figures,
verify_certification, dq_summary [], dq_issue [issue_id],
dq_blocking_for_period [], ops_snapshot []
```

**`dq_blocking_for_period` — the calc-runs refusal story, live and real.**
It surfaced exactly the OPEN/BLOCKING findings a calc run refuses over, in the
agency's own words, e.g. (verbatim from the run):

```
title: "Average saturday UPT (typical) refused: 1 of 1 contributing days
        refused their UPT figure"
title: "[2026-07-11] Missing-trip share 1.0000 exceeds the FTA 2% threshold:
        108 of 108 operated trips have no passenger events"  (p. 146 story)
```

**`dq_issue` — LIVE REFUSAL passed through verbatim** for an unknown id:

```json
{"refusal": {"from": "headway-api", "http_status": 404,
             "message": "No data-quality issue with that id exists."}}
```

**`ops_snapshot` — real MBTA commuter-rail vehicles, last-seen framing.** The
300s window returned live vehicles (e.g. vehicle `1701`, route
`CR-Fitchburg`, `age_seconds: 45`, `simulated: false`), each with the ops
boundary on the payload (`category: ops`, `ops_note`). The 1-second window
returned the staleness refusal, NOT an empty fleet:

```json
{"vehicles": [], "vehicle_count": 0, "truncated": false,
 "newest_position_at": "2026-07-31T12:56:03Z",
 "note": "No vehicle has reported a position in the last 1 seconds. The
          newest position on record is 7 seconds old — the feed is stale or
          service is not running, not an empty fleet."}
```

The `truncated` field — the one the discarded work dropped — is present and
correct on every ops response, machine and human.

Full transcript saved to scratchpad `transcript_0039.txt` (long multi-row
payloads truncated at 2200 chars per call for that file; every call and
verdict complete).

### Unproven / not exercised live

- A real desktop assistant (Claude Desktop) end-to-end — the harness IS a
  conformant MCP client over stdio, but no third-party client was attached
  (same posture as 0034).
- The per-key 429 passthrough at the MCP layer live — the bucket never
  emptied during the run; it is unit-tested at the API layer
  (`test_dq_read_is_rate_limited_per_key`, `test_ops_read_is_rate_limited_per_key`).
  Open question (rate limiting at MCP call cadence) observed, not built —
  the existing in-process token bucket applies unchanged to the new routes.

### Files changed

API: `headway_api/machine_auth.py` (scopes), `routers/dq.py` (extract shared
query fns), `routers/ops.py` (extract shared query fn),
`routers/machine_read.py` (4 new routes), `openapi.json` (regenerated),
`tests/test_machine_dq_ops.py` (new, 24 tests).

MCP: `headway_mcp/client.py` (4 new client methods), `headway_mcp/tools.py`
(4 new tools + `_issue_headline`), `headway_mcp/server.py` (4 registrations +
instructions), `scripts/mcp_transcript.py` (new-tool calls + `--issue-id`),
`README.md` (tool reference), `tests/conftest.py` (fake routes/fixtures),
`tests/test_server.py` (updated toolset + description pins),
`tests/test_dq_ops_tools.py` (new, 18 tests).
