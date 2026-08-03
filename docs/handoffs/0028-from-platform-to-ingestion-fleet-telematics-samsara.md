# Handoff: platform → ingestion — Fleet telematics contract + Samsara connector (vanpool)

## Context
The first partner agency runs four modes on four vendor systems: fixed route (TripSpark
Streets — live), paratransit (procurement in flight), on-demand (Via), and **vanpool on
Samsara fleet telematics**. No vendor's own reporting can produce that agency's NTD
submission; combining the modes is why this platform exists (ROADMAP, "the mode
dimension is the whole job"). Vanpool is the newest *shape* of source: not a transit
system's export but a telematics API — odometer readings, GPS distance, duty hours.
Vanpool NTD figures are typically assembled by hand from odometer sheets, so this is
also the most visibly automatable win.

**No agency credentials exist yet.** This wave builds everything that does not need
them and stops honestly at the line where they are required.

## Design (binding)

1. **The contract comes first, and it is vendor-neutral** (ADR-0006 wire-contract
   discipline; the `demand_response_trip` contract is the precedent). Author
   `contracts/fleet-telematics.v0.*` describing a **vehicle-day telematics record**:
   vehicle identity, service date, distance for the period (with its measurement basis
   — ECU odometer delta / GPS distance / GPS odometer, kept DISTINCT and never silently
   substituted), engine/duty time where available, sample timestamps, and the source
   system. Samsara is the first adapter onto it, not its definition — Geotab and
   Verizon Connect must fit the same contract without a rewrite. Ratify per the
   Platform Architect's topic registry (`raw.telematics.*` or nearest existing
   convention — read `contracts/topics.v0.md` and follow it).
2. **THE HONESTY WALL (binding, non-negotiable).** Telematics distance is **not**
   revenue miles, and duty hours are **not** revenue hours. An odometer delta includes
   deadhead, personal use, maintenance trips, and anything else the vehicle did.
   Therefore:
   - This wave lands raw + canonical telematics records ONLY. **No calc, no VRM, no
     VRH, no VP-mode figures.**
   - The canonical rows must carry their measurement basis and their gaps; nothing is
     interpolated across missing samples (the vehicle-positions precedent).
   - The path from telematics to reportable VP figures requires the FTA manual's
     vanpool rules quoted verbatim into `services/calc/REGULATORY_TRACKER.md` by the
     NTD Compliance role (2025/2026 manuals are on file in `docs/reference/`) — a
     SEPARATE wave, recorded in Open Questions. Say so plainly in the README: what we
     ingest today is measured vehicle movement, not a reportable figure.
3. **The Samsara connector** (`services/ingestion/connectors/samsara/`, Go, following
   the existing poller connectors' shape):
   - Pin the vendor's published API surface: fetch and record the OpenAPI spec
     (`https://developers.samsara.com/docs/openapi-spec`, index at
     `https://developers.samsara.com/llms.txt`) and derive endpoint paths and field
     names FROM IT — never from memory or a blog. Record the spec version/date consulted
     in the connector's README.
   - Endpoint of record for distance: `GET /fleet/vehicles/stats/history` with
     `types=obdOdometerMeters,gpsOdometerMeters,gpsDistanceMeters` over an explicit
     `startTime`/`endTime` window; honor documented time-range limits, pagination and
     rate limits with backoff. Duty/hours-of-service via the documented HOS endpoints
     where the account exposes them — treat as OPTIONAL and absent-by-default.
   - Auth: bearer token from env (`SAMSARA_API_TOKEN`), **never logged, never in an
     error message**; connector refuses to start with a drop-dir-style fail-closed
     message when unset. Read-only scopes only — document exactly which permissions the
     agency's token needs, and ask for no more.
   - Store-before-produce, content-addressed raw records, fail-closed source label
     (`samsara` for real accounts; `samsara_simulated` for anything synthetic —
     unregistered labels refused, handoff 0015 rule).
   - Idempotent re-polls: identical bytes → identical record id, no double-count.
4. **Canonical landing**: migration 0034, `canonical.vehicle_telematics` (or the name
   the schema conventions imply), with lineage edges to the raw records and DQ findings
   for the honest failure modes the vendor documents: missing ECU odometer (no
   coverage), implausible jumps (gateway reconfiguration), gaps between samples.
   Transform-side normalizer following the existing normalizers' shape.
5. **Verification without credentials — and the line you stop at.** Build fixtures from
   the published spec's own schemas/examples, clearly labeled synthetic; unit tests,
   contract-conformance tests, a fake-HTTP-server integration test covering pagination,
   rate-limit backoff, partial windows, and the missing-odometer case. **Do not invent
   response shapes**: anything the spec does not pin, leave unimplemented and record it.
   State in the README, in the house voice, that no live Samsara account has ever been
   contacted and exactly what will need re-verification when a token arrives.

## Outputs
Ratified contract + topic entry; Go connector with tests (`go test ./...`, `go vet`
green); migration 0034 applied to the live DB; transform normalizer + tests; DQ findings
wired; adapters/validate or equivalent harness updated if applicable; docs:
`docs/connecting-your-data.md` gains a telematics section (what it is, what it is NOT,
the token and read-only scopes an agency must create), connector README with the honest
verification status; evidence appended here. No commits — the orchestrator integrates.

## Open Questions
- **VP-mode reportability wave**: FTA vanpool rules quoted verbatim, revenue-vs-total
  distinction, how an agency declares which vehicle-days were revenue service (roster,
  driver attestation, or schedule) — NTD Compliance owns it; nothing computes until then.
- Geotab / Verizon Connect adapters onto the same contract (the reuse proof).
- Whether HOS duty hours are available in a typical agency's Samsara tier at all.
- Samsara's partner sandbox as a live-verification path before an agency token exists.

## Outputs — evidence

*Appended by the ingestion engineer (with platform-architect authority over the
new contract), 2026-07-29.*

### 0. The one-line summary

Contract ratified, connector built, migration applied, normalizer landing rows
in the live database — and **not one figure computed**. Per the 2026-07-29
governance addition, the connector also collects the **minimum** the purpose
needs: vehicle-level distance and time only, with driver-identified and
unrequested fields dropped by an allow-list **before the first write**. Telematics distance is
recorded as measured vehicle movement with its measurement basis and its gaps,
and the honesty wall is enforced by the database itself, not by a comment.

### 1. The ratified contract

**`contracts/fleet-telematics.v0.md` + `fleet-telematics.v0.schema.json`.**
The record is `fleet_telematics_vehicle_day`: **one measurement series** —
one vehicle, one service date, one `measure` (`distance` | `engine_time`), on
one `basis`.

The central design decision, and the reason it is shaped this way: **one row
per (measure, basis) makes silent substitution structurally impossible.** A
van with both an ECU odometer and a GPS distance counter produces two rows,
not one reconciled number. "Fill the missing ECU figure with the GPS one" is
not expressible, because it would mean writing a different row's `basis`,
which the unique key and a CHECK constraint both forbid. Disagreement between
bases stays visible instead of being averaged away.

Fields: `vehicle_id`/`vehicle_label`, `service_date` + explicit
offset-bearing `window_start`/`window_end`, `measure`, `basis` (six values:
`ecu_odometer`, `gps_odometer`, `gps_distance`, `ecu_engine_time`,
`estimated_engine_time`, `duty_status_time`), `unit` (`meters`|`seconds`, SI
on the wire always), `reading_kind` (`cumulative_counter`|`period_total`),
`value` (absent = UNMEASURED, never 0), the two endpoint readings with their
times, `sample_count`, `max_sample_gap_seconds`, `source_system` (registered
enum). JSON-Schema `if/then` blocks bind `unit` and the `basis` sub-vocabulary
to `measure`, and forbid endpoint fields on a `period_total`.

**Topic registered:** `raw.telematics.vehicle_stats` in
`contracts/topics.v0.md` (`raw.<source>.<subtype>`, `object_ref` payload,
registered source labels `samsara` / `samsara_simulated`, unregistered labels
refused fail-closed). `contracts/README.md` updated.

**Vendor-neutrality (the reuse proof).** The contract contains no Samsara
vocabulary. A second adapter answers four enum questions: which series is
distance vs engine time; is it read from the diagnostic bus / derived from
GPS with a human seed / accumulated by the gateway (→ `basis`); running total
or per-period amount (→ `reading_kind`); what is its registered label. A
vendor that reports per-period distance lands as `period_total` with no
endpoints — same table, same lineage, same DQ vocabulary. Geotab and Verizon
Connect field names are **deliberately not guessed** anywhere in this wave;
each must be derived from that vendor's own published spec.

### 2. Where the Samsara API surface came from (and its date)

Nothing was recalled from memory. Every endpoint path, parameter, field name,
type, limit and error behaviour was read out of the vendor's published
OpenAPI document, discovered through the index this handoff named:

| | |
| --- | --- |
| Index | `https://developers.samsara.com/llms.txt` (fetched 2026-07-29, sha256 `a03f3250bd8c4cbf12be6cc457aeb5094e7bfda568cc03dc301b2012032c7027`) |
| → guide | `https://developers.samsara.com/docs/openapi-spec.md` (`updatedAt: 2025-10-27`), which links the spec |
| Spec document | `https://developers.samsara.com/openapi/samsara-api.json` |
| **Spec version** | **`info.version` = 2025-10-23**, OpenAPI 3.0.1, `x-original-swagger-version: 2.0` |
| **Retrieved** | **2026-07-29**, `Last-Modified: 2026-07-29T13:08:10.048Z` |
| **sha256** | `2ed9a10c736189354662585f50ea6a756b73d5fecb6663b2ee122fdca994730e` (3,898,468 bytes, 255 paths) |

Supporting guides fetched the same day: `/docs/telematics.md` (updated
2025-10-23), `/docs/telematics-history.md` (2025-10-22),
`/docs/rate-limits.md` (2025-10-22), `/docs/authentication.md` (2025-10-22),
`/docs/response-codes.md` (2025-10-22).

Facts taken from it, each traceable to a quotable line:

- `GET /fleet/vehicles/stats/history`, `operationId: getVehicleStatsHistory`;
  servers `api.samsara.com`, `api.eu.samsara.com`, `api.ca.samsara.com`.
- `startTime`, `endTime` **and `types` are all `required: true`**.
- **`types` is capped at three per request** — *"You may list ***up to 3***
  types"*. `obdOdometerMeters,gpsOdometerMeters,gpsDistanceMeters` is exactly
  three, so **engine-time types cannot ride along**; they are a second
  request. This is a spec constraint that changed the connector's shape, not
  a design preference.
- Auth: global `AccessTokenHeader`, `type: http`, `scheme: bearer` — a
  header, never a query parameter (which is why request URLs are safe to log
  and to record as `feed_url`).
- Response `VehicleStatsListResponse`: `data[]` (per-vehicle `id`, `name`,
  one array per requested stat type of `{time, value, decorations?}`) plus
  `pagination` (`endCursor`, `hasNextPage`, both required).
- Value types: `obdOdometerMeters`/`gpsOdometerMeters` `int64`,
  `gpsDistanceMeters` **`double`**, `obdEngineSeconds` `int64`. (The double is
  why the normalizer parses JSON with `parse_float=Decimal` — exact end to
  end, never binary float.)
- Scope: *"select **Read Vehicle Statistics** under the Vehicles category"*.
- Rate limits: `GET fleet/vehicles/stats/history` listed at **50 reqs/s**;
  `429` carries `Retry-After` *"in seconds. Example: `0.40235`"*; 5xx →
  *"use exponential backoff"*.
- The vendor's own documented failure modes, quoted into the contract and
  turned into DQ findings: `obdOdometerMeters` *"will be omitted"* without
  diagnostic coverage; `gpsOdometerMeters` needs a **manually entered**
  starting reading; `gpsDistanceMeters` counts *"since the gateway was
  installed"*.

**No live Samsara account was ever contacted.** Only public documentation
servers were reached. Every fixture is synthetic and labelled; synthetic runs
used `samsara_simulated`, never `samsara`.

### 3. The connector's shape

`services/ingestion/connectors/samsara/` — `samsara.go`, `objectstore.go`,
`samsara_test.go`, `README.md`. Connector identity `headway-samsara` v0.1.0.

- **Poller, one declared service day per window.** `PollWindow(day)` builds
  `[local midnight, next local midnight)` in the declared IANA zone — day
  length is whatever the zone says (23 or 25 hours across DST), never assumed
  to be 24 — then issues the distance request and (by default) a second
  engine-time request, paginating each on `endCursor` while `hasNextPage`.
  `PollOnce` covers `BackfillDays` days ending `LagDays` back (defaults 3 and
  1). `Run` cycles every `SAMSARA_POLL_INTERVAL` (default 6h).
- **Fail closed.** `Check()` refuses to start, with a plain-language message
  naming the fix, when the token, the source label, or the service-day
  timezone is missing — and when the source label is not one of the
  **registered** contract labels. A test asserts the Go label list is
  byte-identical to the checked-in schema's `source_system` enum, so the two
  cannot drift.
- **Secrets never logged.** The token is written only into an
  `Authorization` header. Tests assert it appears in no log line, no error
  string, no query string, no `feed_url` and no produced envelope; the live
  run confirmed zero occurrences in the connector's logs.
- **Minimize, then store, then produce, content-addressed.** The
  data-minimization allow-list runs first (§3b); the minimized page bytes land
  at `raw/telematics/<sha256>.json` *before* the envelope is produced;
  `record_id` is the SHA-256 of exactly those landed bytes.
- **Idempotent re-polls.** Identical bytes → identical `record_id`; within a
  process an identical page is not even re-produced (bounded in-memory set).
- **Fail loudly.** A page that is not the documented response shape is still
  landed and produced with `parse_status: "malformed"` + `parse_error`, and
  pagination then **stops** rather than following a cursor Headway could not
  read. Empty 200 body, oversize page (capped, never truncated), stuck
  cursor, and page-count runaway are all loud errors.
- **Rate limits.** `429` honours the documented fractional `Retry-After`
  (capped); 5xx uses exponential backoff; other 4xx are not retried; 401/403
  names the required scope without echoing the token.

Wired into `cmd/headway-ingest` behind `SAMSARA_ENABLED=true`. The **token is
deliberately not the on-switch**: a missing token must be a loud refusal, not
a connector that quietly never runs.

### 3b. Data minimization — the 2026-07-29 governance addition

The project lead's binding addition mid-wave: **fleet telematics is
EMPLOYEE-MONITORING data**, and the first partner agency has no records
officer (oversight is HR + external counsel; a data-classification program is
only now being stood up). It narrows what is collected; it does not touch the
honesty wall or the contract.

**Conflict raised, not resolved silently.** Instruction 2 ("drop
driver-identified fields at the connector boundary before anything is
stored") is in tension with the Ingestion Engineer's Definition of Done
item 9, "a landed raw record is byte-identical to source input". Both are
binding. It was resolved in favour of minimization, and the exception is
stated loudly everywhere it matters (package doc, connector README, ingestion
README, this handoff) rather than quietly weakened: **the raw record is the
exact bytes of the MINIMIZED response.** Everything downstream is unchanged —
content-addressed, immutable, the anchor of every lineage walk — because
minimization runs *before* the hash. Flagging it here for the architect of
record; if the preference is instead to REFUSE a page carrying
driver-identified fields (landing nothing), that is a one-function change.

What was implemented:

1. **Nothing driver-identified is requested, and there is nothing to switch
   on.** Headway requests exactly five vehicle-statistics series
   (three distance, two engine-runtime). It never requests GPS positions,
   `decorations`, `nfcCardScans`, fault codes, driver records, HOS/ELD logs,
   safety scores, harsh-event records or dashcam references. HOS was already
   unimplemented on spec/scope grounds; the governance addition makes that
   the *primary* reason and it is recorded in Open Questions below. **No
   opt-in setting was added**, because adding a switch for an unimplemented
   capability is dead code — the requirement is recorded instead: any future
   driver-identified ingestion must be gated behind an explicit, documented
   opt-in with the plain-language employee-data warning.
2. **An allow-list runs before the first write** (`minimizePage`). Top level
   keeps `data` + `pagination`; per vehicle `id`, `name` and the requested
   stat series; per reading `time` and `value`. Everything else is dropped
   **before** hashing, landing or producing — including `externalIds`, whose
   own spec example is a **`payrollId`**. It is an allow-list, not a
   blocklist, so a driver-identified field added in a future API version is
   dropped automatically. Dropped key NAMES are logged; dropped VALUES never
   are. Minimization is deterministic (numeric literals preserved verbatim
   via `json.Number`, canonical key order), so identical responses still
   produce identical `record_id`s and re-polls stay idempotent — proven by
   test and live.
3. **A one-page table for an HR/legal reviewer** — requested / kept / never
   requested / never requested-driver-identified / dropped-before-landing /
   scope requested — is in `services/ingestion/connectors/samsara/README.md`
   and, in plain language, in `docs/connecting-your-data.md` §4. The scope
   asked for is **Read Vehicle Statistics** and nothing else; no write scope,
   no ELD/compliance scope, no driver-behavior scope.
4. **The re-identification note is stated honestly**, in both READMEs and the
   user guide: even with no driver id, daily distance and engine hours per
   vehicle combined with vehicle assignments or run sheets can locate an
   identifiable operator over time. That is a characteristic of the data
   class; these records must be treated as employee records.

A page whose structure does not permit minimization is still landed as
`malformed` — evidence of a failure is never destroyed, and such a page
cannot carry vendor-defined driver records anyway, because the requested
token scope does not grant them. That trade-off is documented in the
connector README.

**Live proof (2026-07-29).** The synthetic fixture was padded with exactly
the fields the governance addition targets — `externalIds`
(`payrollId: SIM-PAYROLL-4471`), `nfcCardScans` (`badgeId:
SIM-BADGE-EMP-99`), a `driver` object (`SIM-DRIVER-99` / "Simulated
Operator"), and per-sample GPS `decorations` — and re-polled:

```
WARN dropped unrequested response fields at the connector boundary before landing
     (data minimization; fleet telematics is employee-monitoring data)
     dropped_keys=data[].driver,data[].engineStates,data[].externalIds,
                  data[].nfcCardScans,data[].obdOdometerMeters[].decorations
```

All three landed MinIO objects were then read back and searched: **zero**
occurrences of `payrollId`, `SIM-PAYROLL-4471`, `maintenanceId`,
`nfcCardScans`, `badgeId`, `SIM-BADGE-EMP-99`, `driver`, `SIM-DRIVER-99`,
"Simulated Operator", `decorations`, `latitude` or `42.3601`. The
measurements survived verbatim (`14010293`, `81029.591434899`), and the
minimized records normalized to the **same six canonical rows** as the
pre-minimization run. Dropped values appeared **zero** times in the logs.

### 4. Canonical landing + transform

**Migration `db/migrations/0034_vehicle_telematics_days.sql`** —
`canonical.vehicle_telematics_days`, hypertable on `window_start`, unique
`(vehicle_id, window_start, measure, basis, source_record_id)` (the
0012/0021 replay-idempotency precedent), FK to `raw.records`, `polled_at` so
a restated service day is orderable.

The honesty wall is **structural**, not advisory:

| Constraint | What it makes impossible |
| --- | --- |
| `vtd_value_is_the_recorded_difference` | For a cumulative counter, a stored `value` must be **exactly** `last_reading_value - first_reading_value`. There is nowhere for an estimate, an interpolation or a model output to hide. |
| `vtd_basis_matches_measure` / `vtd_unit_matches_measure` | A distance basis can never appear on an engine-time row. Substitution is unrepresentable. |
| `vtd_first_reading_inside_window` / `..._last_...` | A reading cannot be filed under a day it does not fall in. |
| `vtd_period_total_has_no_endpoints` | A per-period amount cannot carry endpoints that imply a subtraction that never happened. |
| `vtd_gap_needs_two_samples` | A gap cannot exist without two readings to gap between. |
| `value NUMERIC` nullable, no default | Unmeasured stays NULL. Never 0, never coalesced, never float. |

**Normalizer** `services/transform/headway_transform/telematics_vehicle_days.py`
(`normalize_telematics_vehicle_days` v0.1.0). Loads the contract schema from
disk at import (the `envelope.py` pattern) so the registered labels and the
measure/basis vocabulary cannot drift. Two fail-closed refusals write **zero**
canonical rows and a blocking issue: an unregistered source label, and an
undeclared/unresolvable service-day timezone
(`HEADWAY_TELEMATICS_SERVICE_DAY_TZ`) — a service date is a local wall date
and is never derived from a guessed zone. Samples bucket by **local** date;
a date whose local midnight does not exist in the zone is quarantined rather
than moved.

DQ findings (all anchored to the record, all replay-deduped):
`telematics_ecu_odometer_absent` (the vendor's documented no-coverage case —
and the finding text states outright that GPS is not substituted),
`telematics_counter_regression` (gateway reset: `value` NULL, both endpoints
kept, "surfaced, never repaired"), `telematics_sample_gap`,
`telematics_implausible_distance` (whose text says in plain words that the
threshold is a Headway review prompt, **not** a vendor or regulatory limit),
`telematics_insufficient_samples`, `telematics_unmapped_series`,
`malformed_telematics_sample`, `empty_telematics_page`. Writer + consumer
routing + `__main__` env wiring added.

### 5. Test evidence

```
$ cd services/ingestion && go build ./... && go vet ./... && go test ./... -count=1
?   .../cmd/headway-ingest    [no test files]
ok  .../connectors/dr         0.029s
ok  .../connectors/gtfsrt     0.007s
ok  .../connectors/gtfsstatic 0.007s
ok  .../connectors/samsara    0.018s
ok  .../connectors/tides      0.019s
ok  .../connectors/vendorfile 0.023s
ok  .../internal/envelope     0.002s
?   .../internal/producer     [no test files]
```
**Go: 78 tests, all pass** (was 47; **31 new** in `connectors/samsara/`, of
which 5 cover data minimization).
`go vet` clean, `gofmt` clean on the new package.

```
$ cd services/transform && python3 -m pytest -q
182 passed in 1.20s
$ cd db && python3 -m pytest test_migrations_static.py -q
30 passed in 0.30s
```
**Python: 182 transform tests** (was 144; **38 new** in
`tests/test_telematics_vehicle_days.py`) **+ 30 migration static tests** (was
29; 1 new, asserting migration 0034's structural honesty wall).

Contract-conformance is enforced in the test suite: every emitted canonical
row is validated against the checked-in
`contracts/fleet-telematics.v0.schema.json` with `jsonschema`, and a
parametrized test asserts every contract `basis` is either mapped by the
Samsara adapter or deliberately reserved (`duty_status_time`).

### 6. Live verification — Compose stack, 2026-07-29, no live Samsara account

Migration applied to the live TimescaleDB via the standard runner:

```
$ PGHOST=127.0.0.1 … python3 db/migrate.py
applying 0034_vehicle_telematics_days.sql ... ok
applied 1 migration(s)

headway=# select filename, applied_at from public.schema_migrations order by filename desc limit 1;
 0034_vehicle_telematics_days.sql | 2026-07-29 16:11:16.532452+00
```

A local **synthetic** vendor-shaped server (built from the spec's own
schemas; every vehicle id prefixed `SIM-`) was polled by the **real
`headway-ingest` binary** with `SAMSARA_SOURCE=samsara_simulated`.

**Fail-closed refusals, live.** With `SAMSARA_ENABLED=true` and nothing else
set, the service exited non-zero naming all three missing settings
(`SAMSARA_API_TOKEN` … `SAMSARA_SOURCE` … `SAMSARA_SERVICE_DAY_TZ`). With
`SAMSARA_SOURCE=samsara_prod` it refused: *"is not a REGISTERED telematics
source label. Registered labels are samsara, samsara_simulated …"*.

**Rate limit, live.** The fixture returned one `429` with
`Retry-After: 0.40235`:

```
WARN samsara rate limited; honouring Retry-After  retry_after_header=0.40235 wait=402.35ms
INFO telematics page landed and produced  record_id=1499849e… bytes=803
INFO telematics page landed and produced  record_id=739ea30a… bytes=272   (after=SIMCURSOR2)
INFO telematics page landed and produced  record_id=ac1c201c… bytes=395   (types=obdEngineSeconds,syntheticEngineSeconds)
INFO samsara poll cycle complete  records_produced=3
```
Cursor pagination followed across two distance pages, engine time issued as a
separate request (the three-type limit), and `grep -c` for the token in the
log: **0**.

**Transform, live.** The real path (`KafkaMessageSource` → `run_loop` →
`process_message` → `DbWriter` → live TimescaleDB) processed the 3 messages.
Verified from a separate psql connection:

```
 vehicle_id |   measure   |         basis         |    value     |     first_v     |  last_v  | n | max_gap
------------+-------------+-----------------------+--------------+-----------------+----------+---+---------
 SIM-VAN-1  | distance    | ecu_odometer          |        82000 |        14010293 | 14092293 | 3 |   28800
 SIM-VAN-1  | distance    | gps_distance          | 82.808565101 | 81029.591434899 |  81112.4 | 3 |   28800
 SIM-VAN-1  | engine_time | ecu_engine_time       |        39000 |         9723103 |  9762103 | 2 |   39600
 SIM-VAN-1  | engine_time | estimated_engine_time |        41000 |         9800000 |  9841000 | 2 |   39600
 SIM-VAN-2  | distance    | gps_distance          |      36250.5 |          5000.0 |  41250.5 | 2 |   28800
 SIM-VAN-3  | distance    | gps_distance          |              |        903120.0 |    120.0 | 2 |   28800
(6 rows)

raw_records (source='samsara_simulated') = 3
lineage_edges (output_kind='canonical.vehicle_telematics_days') = 6
dq.issues: telematics_counter_regression 1 | telematics_ecu_odometer_absent 2
           | telematics_sample_gap 2 | telematics_unmapped_series 1
```

Read that table as the wave's thesis: SIM-VAN-1's two distance bases sit side
by side, unreconciled (82,000 m of ECU odometer, 82.808565101 m of GPS
distance — deliberately divergent fixture data, preserved as measured, with
the double staying exact); SIM-VAN-2 has **no ECU row at all** and a warning
saying so rather than a GPS number promoted into that column; SIM-VAN-3's
gateway reset leaves `value` **blank** with both readings retained.

**Replay idempotency, live.** A fresh connector process re-polled the same
window and produced the **same three `record_id`s**. A second consumer group
replayed all six messages on the topic:

```
BEFORE rows=6 edges=6 raw=3 dq=6
processed=6
AFTER  rows=6 edges=6 raw=3 dq=6
```
**Zero new rows in every table.**

**The database's own guards, exercised live** (each in a rolled-back
transaction):

```
ERROR: … violates check constraint "vtd_value_is_the_recorded_difference"   -- fabricated value refused
ERROR: … violates check constraint "vtd_basis_matches_measure"              -- gps basis on an engine_time row refused
ERROR: … violates check constraint "vtd_first_reading_inside_window"        -- reading filed outside its day refused
```

Left in the live database: **6 canonical rows, 3 raw records, 6 DQ issues,
all carrying `source = 'samsara_simulated'`** — permanently distinguishable
from real data, by design.

### 7. Deliberately left unimplemented (and why)

- **Hours-of-service / ELD endpoints** (`/fleet/hos/logs`,
  `/fleet/hos/daily-logs`). The spec requires the *"Read ELD Compliance
  Settings (US)"* scope — far broader than vehicle statistics — and these are
  **driver** records: personally identifiable, CJIS-adjacent, and a driver's
  regulated duty status is not a vehicle's revenue time anyway. Attributing
  it to a vehicle-day would additionally need driver-vehicle assignment data,
  another endpoint and another scope. The contract reserves a
  `duty_status_time` basis so a future, separately justified wave lands it
  without a contract break; **nothing populates it**, and a test asserts
  that.
- **`/fleet/vehicles/stats/feed`.** The vendor's guide calls the feed
  endpoint *"better than the `/history` endpoint for synchronizing data"* and
  it is the right long-term ingest mode — but its cursor is account state
  that cannot be exercised or reasoned about without a token. A checkpointed
  cursor loop that has never seen a real cursor would be guesswork.
- **A maximum query window.** The spec and guides pin **none**, so none was
  invented. One service day per request window is a Headway operational
  choice, stated as such in the connector README.
- **A vehicle-roster join.** Samsara vehicle ids are stored verbatim; nothing
  maps them onto the agency's fleet inventory. That mapping is a human,
  agency-confirmed step.
- **Geotab / Verizon Connect adapters.** Their field names are not guessed
  anywhere; each needs its own published-spec derivation.
- **Any calculation.** No VRM, no VRH, no VP figure, nothing in
  `services/calc/` reads these rows.

### 8. What must be re-verified when an agency token arrives

The full checklist lives in
`services/ingestion/connectors/samsara/README.md` ("What must be re-verified
the day an agency token arrives"). In brief: (1) a "Read Vehicle Statistics"-only
token actually works; (2) a live page matches `VehicleStatsListResponse`
field-for-field, including `externalIds`/`decorations` and any unexpected
keys; (3) pagination at real fleet/day volume and real page sizes; (4) real
`429` behaviour and the account's actual rate tier; (5) **whether a maximum
query window exists** — split the window if a full day is rejected; (6) which
vehicles actually return `obdOdometerMeters`; (7) whether
`gpsOdometerMeters` has ever been seeded with a manual reading (unseeded, it
is not a usable basis); (8) the real distribution of `max_sample_gap_seconds`,
which decides whether the 6-hour warning default is useful or noisy; (9) how
often gateway resets appear; (10) whether `obdEngineSeconds` returns anything
or only the vendor's `syntheticEngineSeconds` estimate; (11) that timestamps
arrive in the documented RFC 3339 UTC form and the declared service-day zone
is the one the agency actually uses for vanpool accounting; (12) how Samsara
vehicle ids map onto the agency's fleet roster.

Until all of that is done, this connector is **built and unit-verified, not
field-verified**, and the READMEs say exactly that.

### 9. Follow-ups for the orchestrator

1. **`deploy/compose/compose.yaml` needs `raw.telematics.vehicle_stats`
   added to the `bootstrap-kafka` topic list** — a one-line DevOps change
   outside this wave's scope. The contracts change it requires (the
   `topics.v0.md` registration) is done. The topic was created by hand on the
   live broker for verification; without the compose change a fresh stack
   makes the connector fail loudly at produce time with
   `UNKNOWN_TOPIC_OR_PARTITION` (observed — correct behaviour, nothing
   dropped, retried next cycle).
2. **`db/test_migrations_static.py`** was extended with the 0034 check. It is
   outside the literal scope line (`db/migrations/0034_*.sql`) but is the
   test for that migration; flagging it rather than leaving it unsaid.
3. **No commits made**; `git status` shows only the scoped paths.

## Open Questions — additions from the implementing wave

- **Restatement selection.** A service day re-polled later with different
  bytes lands a NEW row from a NEW content-addressed record (the 0012/0021
  precedent), with `polled_at` making "which reading of this day is most
  recent" deterministic. Nothing consumes these rows yet, so no double-count
  is possible today — but the compliance-gated wave must decide the
  selection rule explicitly (latest `polled_at`? human-confirmed
  restatement?) before any figure reads them.
- **Vehicle identity.** Nothing maps a telematics vehicle id to the agency's
  fleet roster. Whoever builds the VP-mode wave needs that mapping, and it is
  a human, agency-confirmed step — not something to infer from names.
- **HOS / driver-identified data is deliberately absent, and why (governance
  addition, 2026-07-29).** Hours-of-service duty records are **not needed for
  VP distance and time**, they require a far broader token scope ("Read ELD
  Compliance Settings (US)"), and they are employee-monitoring records whose
  collection may engage collective-bargaining agreements, state
  employee-privacy law and the agency's own (nascent) data-classification
  program. They are therefore not implemented at all — not implemented and
  switched off, but **absent**. The contract reserves a `duty_status_time`
  basis so a future wave needs no contract break; a test asserts nothing
  populates it. **Any future driver-identified ingestion must be gated behind
  an explicit, documented opt-in setting carrying a plain-language warning**
  that this is employee data. No such setting exists today, because nothing
  needs one — deliberately, rather than by omission.
- **Raw-record fidelity vs data minimization (conflict for the architect of
  record).** The raw record is now the exact bytes of the MINIMIZED response,
  not of the wire response — a deliberate exception to Ingestion DoD item 9,
  taken on the project lead's binding instruction and documented everywhere it
  matters. If the preferred resolution is instead to REFUSE (land nothing) a
  page carrying driver-identified fields, say so: it is a one-function change
  in `minimizePage`'s caller.
- **Retention and access control for employee-monitoring data.** These rows
  are employee records in substance. Retention policy, who may query
  `canonical.vehicle_telematics_days`, and how it appears (or does not) in
  the analyst read-only role are not settled by this wave and belong with the
  agency's data-classification program.
- **Threshold ownership.** `telematics_implausible_distance` (default ≈1,609,344 m/day)
  and `telematics_sample_gap` (default 6 h) are Headway review prompts with
  no published basis, labelled as such in the finding text. Real fleet data
  should replace the guesses; until then they must never be described as
  vendor or regulatory limits.
