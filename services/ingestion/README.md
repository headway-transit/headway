# Headway Ingestion Service (walking skeleton)

First-party ingestion connectors for the ADR-0009 walking skeleton. Each
connector fetches raw source bytes, wraps the **exact bytes as received** in
the raw-record envelope (`contracts/raw-record-envelope.v0.schema.json`,
ADR-0006), and produces to Kafka on the topics in `contracts/topics.v0.md`,
keyed by `record_id` (lowercase hex SHA-256 of the payload bytes — the
content-addressed identity of ADR-0007).

Invariants (Ingestion Engineer guardrails):

- **Payload bytes are never mutated.** Source parsers run only to classify
  `parse_status`; the raw bytes are what is enveloped, landed, and produced.
- **Malformed input is never dropped.** An unparseable frame or broken zip is
  still landed/produced with `parse_status: "malformed"` and a `parse_error`,
  and logged loudly as a DQ hook (Guardrail 7).
- **Re-ingest is idempotent by construction** — same bytes → same `record_id`.
  The GTFS-RT poller also skips identical *consecutive* frames (same
  `record_id` as the previous poll) and logs the skip.
- **A partially-copied file is never ingested** (2026-07-13 hardening pass) —
  see "File-drop robustness" below.
- **Bounded reads everywhere** — file-drop reads and the GTFS static fetch
  are capped (default 256 MiB; configurable). Oversize input is a loud
  refusal (file moved to `rejected/` / fetch error), never a truncated
  record and never a silent skip.
- **The file-drop source label is enforced, not conventional** — no
  default; simulator-marked content under a real label is hard-refused
  (Shared Constraint 2). See "File-drop robustness" below.

## File-drop robustness (TIDES + DR + vendor-file connectors, 2026-07-13 hardening pass)

**Partial-copy stability guard.** The reviewers confirmed that a file still
being copied into the drop directory could be ingested mid-copy — silent
truncation of a real export. The scanners now rescan the drop directory
every `POLL_INTERVAL` and ingest a file only after it is **stable**: seen
with an identical size *and* mtime on two consecutive scans, i.e. unchanged
for one full scan interval. A growing file is skipped with an INFO log
("file not yet stable") each scan until it settles, then ingested exactly
once (content addressing dedupes any re-produce).

**Rename-into-place convention (recommended to agencies).** The settle
check is a safety net, not an invitation to copy slowly. Export processes
SHOULD write the file under a name the scanner ignores (e.g.
`passenger_events_2026-07-13.csv.tmp` or a dotfile) and `rename(2)`/`mv` it
to its final `passenger_events*.csv` / `demand_response_trips*.csv` name
only when complete. Rename is atomic on the same filesystem, so the scanner
only ever sees complete files — the stability guard then merely costs one
scan interval of latency.

**Source label is required and enforced.** `TIDES_SOURCE` / `DR_SOURCE`
have **no default**: a connector with a drop dir configured and no source
label refuses to start with a plain-language error (fail closed). Labels
ending `_simulated` declare simulated data (handoff 0005 binding rule).
Enforcement is also structural: the Headway simulators mark every row's id
with the `sim:` prefix, and a scanner configured with a *non*-simulated
label hard-refuses any file carrying that marker — moved to `rejected/`,
logged as an ERROR naming the fix, never landed (Shared Constraint 2: full
provenance; simulated data must never be able to masquerade as real).

**Size caps and `rejected/`.** Dropped files over `DROP_MAX_FILE_BYTES`
(default 256 MiB) are refused before being read into memory. Every refused
file (oversize or provenance) is *moved* to `<drop dir>/rejected/` and
loudly logged — preserved for human inspection, never deleted, never
silently skipped, and out of the scanner's rescan path so the refusal does
not repeat forever.

## Layout

| Path | What |
| --- | --- |
| `internal/envelope/` | Raw-record envelope v0 builder + schema-shaped validation |
| `internal/producer/` | `Producer` interface; Kafka impl (franz-go) + in-memory fake |
| `connectors/gtfsrt/` | GTFS-Realtime poller (vehicle_positions / trip_updates / alerts → `raw.gtfs_rt.*`, base64 payload) |
| `connectors/gtfsstatic/` | GTFS static zip fetcher (→ `raw.gtfs_static.feed`, `object_ref` payload; bytes landed at `raw/gtfs_static/<record_id>.zip` via an `ObjectStore` interface: MinIO impl + fake) |
| `connectors/tides/` | TIDES passenger_events file-drop scanner (periodic scan of `TIDES_DROP_DIR` every `POLL_INTERVAL` for `passenger_events*.csv` → `raw.tides.passenger_events`, `object_ref` payload; bytes landed at `raw/tides/<record_id>.csv`; partial-copy stability guard + size cap + simulated-source enforcement per "File-drop robustness" above; processed files moved to `processed/`, refused files to `rejected/`; header sanity check against the required TIDES columns sets `parse_status` only) |
| `connectors/dr/` | Demand-response trips file-drop scanner (handoff 0013; periodic scan of `DR_DROP_DIR` every `POLL_INTERVAL` for `demand_response_trips*.csv` → `raw.dr.trips`, `object_ref` payload; bytes landed at `raw/dr/<record_id>.csv`; same robustness guards as the TIDES scanner; processed files moved to `processed/`, refused files to `rejected/`; header sanity check against the required `demand_response_trip` v0 columns — `contracts/demand-response-trip.v0.schema.json` — sets `parse_status` only) |
| `connectors/vendorfile/` | Generic vendor-export file-drop scanner for the adapter framework (handoff 0015; periodic scan of `VENDOR_DROP_DIR` every `POLL_INTERVAL` for `*.csv` → `raw.vendor.files`, `object_ref` payload; ORIGINAL vendor bytes landed content-addressed at `raw/vendor/<record_id>.csv`; same robustness guards as the TIDES/DR scanners; deliberately NO header/content check — `parse_status` is always `ok`, because only the registered mapping spec (`adapters/<vendor>/<product>/mapping.v0.yaml`) knows the vendor format; all interpretation, per-row quarantine and the fail-closed unregistered-label refusal happen in the transform adapter runtime) |
| `connectors/samsara/` | Samsara fleet-telematics poller (handoff 0028; polls `GET /fleet/vehicles/stats/history` one DECLARED service day per window → `raw.telematics.vehicle_stats`, `object_ref` payload; **data minimization at the connector boundary** — fleet telematics is EMPLOYEE-MONITORING data, so every response is reduced to an allow-list (vehicle `id`/`name`; `time`/`value` per reading) BEFORE anything is hashed, landed or produced, and driver-identified or unrequested fields — `externalIds`/payroll ids, `nfcCardScans`, `decorations`, any driver object — are dropped before the first write, never landed "just in case"; the minimized bytes are landed at `raw/telematics/<record_id>.json`; bearer token from `SAMSARA_API_TOKEN`, never logged; fail-closed on token / source label / service-day timezone; cursor pagination, documented `Retry-After` rate-limit backoff and 5xx exponential backoff; a page that is not the documented response shape is landed with `parse_status: malformed` and pagination stops. **Every API detail derived from the vendor's published OpenAPI document, version 2025-10-23, retrieved 2026-07-29 — and NO live Samsara account has ever been contacted; see `connectors/samsara/README.md`.** Telematics distance is NOT revenue miles and engine time is NOT revenue hours: this connector computes nothing) |
| `connectors/sqlsource/` | Generic SQL-source poller (handoff 0033; SQL Server first via `github.com/microsoft/go-mssqldb`, BSD-3-Clause). Keyset-polls a **view or query the agency supplies in configuration** — vendor table/column names never enter this repository; the agency's DBA creates the view (e.g. `dbo.vw_headway_apc`) and a read-only login, and **the view is the contract**. Each poll reads `WHERE cursor > high-water ORDER BY cursor` up to `SQLSOURCE_BATCH_MAX_ROWS`, renders the batch to the registered adapter's declared **positional-CSV shape** (`SQLSOURCE_COLUMNS` must be exactly the adapter's `source_format.csv.columns`, in order), and lands it EXACTLY like a dropped vendor file: content-addressed at `raw/vendor/<record_id>.csv`, `object_ref` envelope to `raw.vendor.files` — the transform adapter runtime and (0031) trip resolution take over untouched. **One pipeline, two intakes.** The result set's columns must match the configured list exactly or the batch is refused whole (the wrong_width precedent, enforced at both ends); `SELECT *` is refused in config validation (ADR-0013 minimization — only the columns the adapter declares are ever read); datetime/float/binary columns are refused with instructions to CAST to varchar **inside the view** (Headway renders bytes, it never invents a format); NULL or non-integer cursors and cursor ties at a full-batch boundary are loud refusals, never silent skips. The high-water mark persists as an atomic JSON file under `SQLSOURCE_STATE_DIR`; it advances only after land + produce (at-least-once), and deleting it deliberately just re-reads history idempotently (content-addressed batches + the adapter engine's deterministic natural keys). Read-only by construction: the connector can only emit one generated `SELECT` over validated bracket-quoted identifiers, under a client-side statement timeout; the agency-side enforcement is the read-only login. The DSN is never held by the poller, never logged, and withheld from parse errors. Same fail-closed label rule as the file intake, including the structural `sim:`-marker refusal |
| `cmd/headway-ingest/` | The service binary: env config, connector startup, SIGINT/SIGTERM clean shutdown, `log/slog` JSON logging |

GTFS / GTFS-Realtime payload *semantics* are defined by the specs at
gtfs.org and are the Data Engineer's concern; this service captures bytes and
transport only. GTFS-RT parse classification uses the pinned MobilityData
bindings (`gtfs-realtime-bindings/golang/gtfs v1.0.0`). TIDES
passenger_events semantics are defined by the TIDES spec
(TIDES-transit/TIDES on GitHub, `spec/passenger_events.schema.json`); the
connector's header check was verified against commit
`d887d42ce081f3fb6155664a3c486101d62ec52b` (2026-07-10) — re-verify against
the current spec before extending. Simulated drops (from
`tools/tides-simulator`) MUST run with `TIDES_SOURCE=tides_simulated` so
provenance permanently distinguishes them (handoff 0005 binding rule). Fleet
telematics payload semantics are the VENDOR's: the raw record is the vendor
API's own response bytes, and the canonical record derived from them is
defined by `contracts/fleet-telematics.v0.schema.json` (handoff 0028). Every
Samsara endpoint path, parameter, field name and limit is derived from the
vendor's published OpenAPI document with the version and retrieval date
recorded in `connectors/samsara/README.md` — never from memory. Simulated
telematics runs MUST use `SAMSARA_SOURCE=samsara_simulated`, never
`samsara` (the same handoff-0005 binding rule).

## Configuration (environment)

| Variable | Meaning |
| --- | --- |
| `KAFKA_BROKERS` | Comma-separated broker list (required) |
| `GTFS_RT_VEHICLE_POSITIONS_URL` | Poll this vehicle-positions feed (optional) |
| `GTFS_RT_TRIP_UPDATES_URL` | Poll this trip-updates feed (optional) |
| `GTFS_RT_ALERTS_URL` | Poll this alerts feed (optional) |
| `GTFS_STATIC_URL` | Fetch this GTFS static zip once at startup (optional) |
| `GTFS_STATIC_MAX_BYTES` | Cap on the fetched zip, plain bytes; default 268435456 (256 MiB). Oversize responses are refused, never truncated |
| `TIDES_DROP_DIR` | Scan this directory every `POLL_INTERVAL` for TIDES `passenger_events*.csv` drops (optional) |
| `TIDES_SOURCE` | Envelope `source` for TIDES drops — **REQUIRED with `TIDES_DROP_DIR`, no default** (fail closed); simulator drops MUST use `tides_simulated` |
| `DR_DROP_DIR` | Scan this directory every `POLL_INTERVAL` for `demand_response_trips*.csv` drops (optional, handoff 0013) |
| `DR_SOURCE` | Envelope `source` for DR drops — **REQUIRED with `DR_DROP_DIR`, no default** (fail closed); simulator drops MUST use `dr_simulated` |
| `VENDOR_DROP_DIR` | Scan this directory every `POLL_INTERVAL` for vendor-export `*.csv` drops (optional, handoff 0015) |
| `VENDOR_SOURCE` | Envelope `source` for vendor drops — **REQUIRED with `VENDOR_DROP_DIR`, no default** (fail closed). Must be the REGISTERED adapter mapping-spec label `<vendor>_<product>` (see `adapters/README.md`), or `<vendor>_<product>_simulated` for synthetic data; the transform runtime refuses unregistered labels with a blocking DQ issue |
| `DROP_MAX_FILE_BYTES` | Cap on a dropped file, plain bytes; default 268435456 (256 MiB). Oversize files are moved to `rejected/` and logged |
| `SAMSARA_ENABLED` | `true` starts the Samsara telematics poller (handoff 0028). The TOKEN is deliberately NOT the on-switch: a missing token must be a loud refusal, not a silently skipped connector |
| `SAMSARA_API_TOKEN` | Bearer API token — **REQUIRED with `SAMSARA_ENABLED`**, from the secret store, **never logged** and never written into a record. Needs only the read-only "Read Vehicle Statistics" scope (Vehicles category) |
| `SAMSARA_SOURCE` | Envelope `source` for telematics records — **REQUIRED with `SAMSARA_ENABLED`, no default** (fail closed). Must be a REGISTERED label from `contracts/fleet-telematics.v0.schema.json`: `samsara` for a real account, `samsara_simulated` for anything synthetic |
| `SAMSARA_SERVICE_DAY_TZ` | Agency IANA service-day timezone — **REQUIRED with `SAMSARA_ENABLED`**, never guessed. The transform must be given the SAME zone (`HEADWAY_TELEMATICS_SERVICE_DAY_TZ`) |
| `SAMSARA_BASE_URL` | API root, default `https://api.samsara.com` (the vendor spec also lists `https://api.eu.samsara.com` and `https://api.ca.samsara.com`) |
| `SAMSARA_VEHICLE_IDS` / `SAMSARA_TAG_IDS` / `SAMSARA_PARENT_TAG_IDS` | Optional comma-separated vendor-side filters. A tag-scoped token plus a tag filter is the least-privilege way to poll only the vanpool |
| `SAMSARA_ENGINE_TIME` | `false` skips the engine-runtime request (default on). Engine RUNTIME is not duty hours and not revenue hours |
| `SAMSARA_LAG_DAYS` / `SAMSARA_BACKFILL_DAYS` | Newest polled service day = today − lag (default 1); consecutive days re-polled per cycle (default 3). Headway operational defaults, not vendor limits |
| `SAMSARA_POLL_INTERVAL` | Go duration between poll cycles, default `6h`. Deliberately separate from `POLL_INTERVAL`: a daily-window API is not a 30-second feed |
| `SAMSARA_MAX_PAGE_BYTES` | Cap on one API response page, plain bytes; default 67108864 (64 MiB). Oversize pages are refused, never truncated |
| `SQLSOURCE_ENABLED` | `true` starts the generic SQL-source connector (handoff 0033). The DSN is deliberately NOT the on-switch: a missing DSN must be a loud refusal, not a silently skipped connector |
| `SQLSOURCE_DSN` | Read-only connection string — **REQUIRED with `SQLSOURCE_ENABLED`**, from the secret store, **never logged** (withheld even from its own parse error). Shape: `sqlserver://headway_ro:pass@host:1433?database=WAREHOUSE&encrypt=true` |
| `SQLSOURCE_DRIVER` | Optional, default `sqlserver` — the only driver v0 supports; anything else is refused (Postgres/Oracle are future increments on the same config shape) |
| `SQLSOURCE_VIEW` | The view the agency's DBA created for Headway (e.g. `dbo.vw_headway_apc`) — **REQUIRED**. One to three dot-separated plain identifiers; free-form SQL is refused (query logic belongs INSIDE the view) |
| `SQLSOURCE_COLUMNS` | Comma-separated ordered column list — **REQUIRED**. Must be EXACTLY the registered adapter's declared positional columns in the adapter's order (`source_format.csv.columns` in `adapters/<vendor>/<product>/mapping.v0.yaml`); `*` is refused (ADR-0013) |
| `SQLSOURCE_CURSOR_COLUMN` | The monotonic INTEGER keyset column (a unique warehouse key, e.g. `VehicleLocationAPCKey`) — **REQUIRED**, must be one of `SQLSOURCE_COLUMNS` so every landed batch carries its own cursor evidence |
| `SQLSOURCE_ADAPTER_LABEL` | Envelope `source` — **REQUIRED, no default** (fail closed). Must be the REGISTERED adapter mapping-spec label `<vendor>_<product>` (or `..._simulated` for synthetic data); the transform runtime refuses unregistered labels with a blocking DQ issue |
| `SQLSOURCE_STATE_DIR` | Writable directory persisting the high-water mark — **REQUIRED** (the Compose file mounts `deploy/compose/sqlsource-state`) |
| `SQLSOURCE_POLL_INTERVAL` | Go duration between poll cycles, default `5m` — "more frequent than nightly" is the point; a keyset SELECT on an indexed key is trivial warehouse load |
| `SQLSOURCE_BATCH_MAX_ROWS` | Cap on one rendered batch (one raw record), default 5000 |
| `SQLSOURCE_QUERY_TIMEOUT` | Client-side statement timeout per query, default `60s` |
| `POLL_INTERVAL` | Go duration for GTFS-RT polling AND drop-dir rescans, default `30s`; also the file-drop partial-copy settle time |
| `AGENCY_ID` | Optional envelope `agency_id` (multi-feed disambiguation only) |
| `S3_ENDPOINT` | MinIO/S3 endpoint `host:port` (required with `GTFS_STATIC_URL`, `TIDES_DROP_DIR`, `DR_DROP_DIR`, `VENDOR_DROP_DIR` or `SAMSARA_ENABLED`) |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Object-store credentials (inject from the secret store; never logged) |
| `S3_BUCKET` | Raw bucket, default `headway-raw` |
| `S3_USE_SSL` | `true` for TLS; default `false` (on-prem MinIO) |

At least one connector must be configured (a `GTFS_*` URL, a `*_DROP_DIR`,
or `SAMSARA_ENABLED=true`); otherwise the service refuses to start.

**Topic prerequisite (handoff 0028).** `raw.telematics.vehicle_stats` is
registered in `contracts/topics.v0.md`, but the Compose stack's
`bootstrap-kafka` topic list (`deploy/compose/compose.yaml`) still needs it
added — a one-line DevOps change outside the handoff-0028 scope. Until then
the Samsara connector fails loudly at produce time with
`UNKNOWN_TOPIC_OR_PARTITION` (observed 2026-07-29, and correct behaviour:
nothing is silently dropped, and the page is retried next cycle).

## Dependency licenses (verified in the module cache at build)

| Dependency | Version | License |
| --- | --- | --- |
| `github.com/twmb/franz-go` (+ `pkg/kmsg`) | v1.21.5 / v1.13.1 | **BSD-3-Clause** (not Apache-2.0 as the scope assumed — verified against the LICENSE file; OSI-permissive, compliant with Guardrail 3) |
| `github.com/minio/minio-go/v7` | v7.2.1 | Apache-2.0 |
| `github.com/MobilityData/gtfs-realtime-bindings/golang/gtfs` | v1.0.0 | Apache-2.0 |
| `google.golang.org/protobuf` | v1.36.11 | BSD-3-Clause |
| `github.com/microsoft/go-mssqldb` | v1.10.0 | **BSD-3-Clause** (verified against the LICENSE file in the module cache AND by `scripts/license_gate.py --ecosystem go`, 2026-07-30: 32/32 deps PASS; the handoff-0033 assumption held. Its Azure-AD auth subpackages are NOT imported, so no Azure SDK code links into the build) |
| `github.com/golang-sql/civil` | v0.0.0-20220223132316 | Apache-2.0 (transitive of go-mssqldb) |
| `github.com/golang-sql/sqlexp` | v0.1.0 | BSD-3-Clause (transitive of go-mssqldb) |
| `github.com/shopspring/decimal` | v1.4.0 | MIT (transitive of go-mssqldb) |

## Verification status

**2026-07-30 (generic SQL-source connector, handoff 0033).**
`go build ./... && go vet ./... && go test ./... -count=1` → all packages
**ok**, **108 tests** (was 73; 30 new in `connectors/sqlsource/`, counting
the refusal-matrix subtests). Toolchain auto-selected go1.25.12 from host
go1.22.2 (`go.mod` `go` directive moved 1.25.0 → 1.25.7 by the go-mssqldb
requirement). ADR-0001 license gate run for real: `scripts/license_gate.py
--ecosystem go` → **PASS, 32/32 dependencies** (go-mssqldb BSD-3-Clause as
the handoff assumed).

**NO AGENCY DATABASE SERVER HAS EVER BEEN CONTACTED.** The agency-side
prerequisites (read-only `headway_ro` login, `vw_headway_apc` view,
firewall path) are with the agency's DBA; every test ran against fakes or
a DISPOSABLE local container. Integration evidence (2026-07-30): a
throwaway `mcr.microsoft.com/mssql/server:2022-latest` container
(`docker run --name headway-0033-mssql`, localhost-only port, removed
afterwards; the live Compose project untouched) ran
`TestIntegrationKeysetPollAgainstRealSQLServer` — **PASS** in 0.11s: 5
seeded rows through a 2-row cap produced 3 batches (2+2+1) with the exact
positional 18-column rendering asserted byte-for-byte; an idle poll landed
nothing; 2 late rows were picked up by keyset resume without re-reading
history; a RESTARTED poller resumed from the persisted high-water file; a
deliberately wrong view exposing a raw `datetime2` was refused naming the
column and the CAST-in-the-view fix. Real-driver type handling verified:
`bigint identity` → int64 cursor, `bit` → 1/0, `nvarchar` verbatim, NULL
`int` → empty cell. What still needs re-verification **when the agency's
ticket clears**, against their real server: TLS/`encrypt=true` behaviour
through their firewall path, the real view's column list and cursor
declaration, login read-only enforcement, warehouse collation/encoding of
`nvarchar` values, and poll-interval load review with their DBA.

**2026-07-29 (Samsara fleet-telematics connector, handoff 0028).**
`go build ./... && go vet ./... && go test ./... -count=1` → all packages
**ok**, **73 tests** (was 47; 26 new in `connectors/samsara/`). Go toolchain
auto-selected by the go.mod directive from host go1.22.2.

```
$ go test ./... -count=1
?   .../cmd/headway-ingest    [no test files]
ok  .../connectors/dr         0.029s
ok  .../connectors/gtfsrt     0.007s
ok  .../connectors/gtfsstatic 0.007s
ok  .../connectors/samsara    0.016s
ok  .../connectors/tides      0.019s
ok  .../connectors/vendorfile 0.023s
ok  .../internal/envelope     0.002s
?   .../internal/producer     [no test files]
```

**NO LIVE SAMSARA ACCOUNT HAS EVER BEEN CONTACTED** — the vendor's API
surface was derived entirely from its published OpenAPI document
(`https://developers.samsara.com/openapi/samsara-api.json`, `info.version`
2025-10-23, retrieved 2026-07-29, sha256
`2ed9a10c…994730e`), and every fixture is synthetic. The full
verification statement and the checklist of what must be re-verified when an
agency token arrives is in
[`connectors/samsara/README.md`](connectors/samsara/README.md).

**Live-verified 2026-07-29** against the running Compose stack, using a
local SYNTHETIC vendor-shaped server (source label `samsara_simulated`,
never `samsara`): startup refused with the plain-language message when the
token / source label / timezone were absent, and again for an unregistered
source label; a documented `429` + `Retry-After: 0.40235` was honoured
(waited 402.35 ms) and the poll then succeeded; cursor pagination followed
`endCursor` across two distance pages plus a separate engine-time request;
3 pages landed in MinIO and produced to `raw.telematics.vehicle_stats`; the
API token appeared **zero** times in the connector's logs. Full evidence,
including the transform side and the replay-idempotency run, is in handoff
0028.

Unit tests, build, and vet **pass** (2026-07-13, toolchain auto-selected by
the go.mod directive; host go1.22+ with `GOTOOLCHAIN=auto`; 37 tests):

```
$ go build ./... && go vet ./... && go test ./... -count=1
?   .../cmd/headway-ingest    [no test files]
ok  .../connectors/dr         0.016s
ok  .../connectors/gtfsrt     0.004s
ok  .../connectors/gtfsstatic 0.004s
ok  .../connectors/tides      0.015s
ok  .../internal/envelope     0.001s
?   .../internal/producer     [no test files]
```

Covered by fakes/httptest: envelope determinism + SHA-256 known vector +
required-field completeness; GTFS-RT happy path / malformed-never-dropped /
consecutive-duplicate skip; GTFS static envelope + content-addressed object
key + broken-zip-still-landed + land-before-produce ordering + oversize
response refused with the limit named; TIDES and DR drop envelopes +
missing-required-column-still-landed-and-produced-as-malformed + source
carried verbatim (`tides_simulated` / `dr_simulated`) + processed-move
idempotent re-scan + land-before-produce ordering; and per the 2026-07-13
hardening pass, on both file-drop scanners: growing-file-never-ingested-
until-stable (the reviewers' partial-copy regression, ingest exactly once
with the complete bytes), empty-source refusal naming the env var,
simulator-marked-content-under-real-label hard refusal (and its
counterpart ingesting under a `*_simulated` label), oversize file moved to
`rejected/` with the limit named, and the periodic `Run` loop ingesting
then stopping cleanly on cancel.

**Live-verified 2026-07-13** against the running Compose stack (evidence:
`docs/reviews/2026-07-13-hardening-pass.md`, Batch B): the mid-copy
scenario — a simulator CSV slow-written into `DR_DROP_DIR` at ~512 B/s
while the connector scanned every 3 s — was skipped on four consecutive
scans ("file not yet stable", 1024→2560→4096→5130 bytes) and ingested
exactly once when stable, with `record_id` equal to the complete file's
sha256; startup without `DR_SOURCE` refused fatally with the
plain-language error; the same simulator file dropped under
`DR_SOURCE=dr` was refused ("16 row(s) carry the simulator marker") and
preserved in `rejected/`.

**PENDING (not verified — no Docker in the authoring environment):**

- Live Kafka produce path (`internal/producer/kafka.go`) — exercised only
  through the `Producer` interface with the fake; needs the Compose stack
  (Kafka KRaft, ADR-0002).
- Live MinIO landing (`connectors/gtfsstatic/objectstore.go` MinIO impl).
- Docker image build (`Dockerfile` is written but untested).
- Apicurio schema registration, replay-from-raw-store proof, and
  backpressure/at-least-once demonstration under a slow consumer.

## Deliberately out of scope (next increments)

Walking skeleton only: no connector-runtime base image, no checkpointing, no
backpressure tuning, no DQ-issue rows (malformed records are landed and
logged; the `dq.issues` emission hook comes with the Data Engineer's rule
engine), no source-schema descriptor registry, GTFS static is a one-shot
fetch (no re-poll/If-Modified-Since), GTFS-RT dedupe cursor is in-memory
(restart re-produces the current frame; safe because `record_id` makes
re-ingest idempotent). The file-drop scanners rescan every `POLL_INTERVAL`
(2026-07-13 hardening pass — required by the partial-copy stability guard);
there is still no inotify-style watcher, and the pending-file state is
in-memory (a restart just re-observes candidates for one extra interval —
the `processed/` move plus content-addressed `record_id` keep re-scans
idempotent).
