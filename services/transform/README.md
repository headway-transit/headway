# headway-transform

Data Engineer normalization scope of the ADR-0009 walking skeleton: consumes
raw-record envelopes from Kafka, normalizes them into `canonical.*` rows with
an explicit lineage edge per row, and quarantines every failure as a
`dq.issues` row. Schema contract:
`docs/handoffs/0001-from-platform-architect-to-all-canonical-schema-v0.md`.
Wire contract: `contracts/raw-record-envelope.v0.schema.json` +
`contracts/topics.v0.md` (the schema file is loaded from disk at import — the
code cannot drift from the checked-in contract without failing loudly).

## Layout

- `headway_transform/envelope.py` — envelope parse + jsonschema validation
  against the actual contract file; invalid → typed `EnvelopeValidationError`
  (quarantined by the consumer, never dropped).
- `headway_transform/gtfs_rt_positions.py` — `normalize_gtfs_rt_positions`
  v0.1.0: base64 GTFS-Realtime FeedMessage → `CanonicalVehiclePosition` rows
  + one `lineage.edges` row per canonical row
  (`output_id = '<vehicle_id>|<time RFC3339>|<record_id>'`) + `DQFinding`s
  for undecodable payloads / malformed entities. Event-time policy: entity
  timestamp, else header timestamp (noted as an info DQ finding), else the
  entity is a DQ finding — a time is never guessed.
- `headway_transform/trip_updates.py` — `normalize_gtfs_rt_trip_updates`
  v0.1.0 (handoff 0014, migration 0025): base64 GTFS-Realtime FeedMessage →
  `CanonicalTripUpdate` rows — one per (TripUpdate, StopTimeUpdate), plus a
  trip-level row for updates with no stop events (e.g. CANCELED) — + one
  lineage edge per row. PREDICTIONS ARE PREDICTIONS: every time column is
  `predicted_*`, anchored to the frame's header timestamp
  (`feed_timestamp`); a frame without a header timestamp is quarantined
  whole (a prediction's made-at time is never guessed), a delay-only
  StopTimeEvent keeps its delay with a NULL predicted time (never derived
  from delay + schedule here), and in-frame duplicate trip/stop keys are
  kept-first + warned (the writer's ON CONFLICT would otherwise absorb
  them silently).
- `headway_transform/gtfs_static.py` — `normalize_gtfs_static` v0.4.0
  (0.4.0: parses `agency.txt` → `CanonicalAgency`/`canonical.agencies`,
  handoff 0014/migration 0026 — the feed-declared `agency_timezone` that
  anchors otp_v0's schedule comparison; a row without a usable timezone is
  quarantined, never guessed. 0.3.1: decompression budget + per-row parse
  quarantine, 2026-07-13):
  GTFS zip `routes.txt`/`trips.txt` → `CanonicalRoute`/`CanonicalTrip` +
  edges. `route_type` → mode map cited to gtfs.org; unmapped values → mode
  `'unknown'` + DQ finding, never a guess. v0.2.0 (handoff 0003) parses
  `trips.txt` `block_id` — OPTIONAL per the GTFS Schedule Reference
  (gtfs.org, cited in-code), so an absent column or empty value is NULL with
  **no** DQ finding; existing rows backfill on the next static-feed replay
  via the upsert path.
- `headway_transform/tides_passenger_events.py` —
  `normalize_tides_passenger_events` v0.1.1 (handoff 0005, slice 2 UPT;
  0.1.1: per-row parse quarantine, 2026-07-13):
  TIDES `passenger_events` CSV → `CanonicalPassengerEvent` rows (migration
  0012, column-for-column; `trip_id` from TIDES `trip_id_performed`) + one
  lineage edge per row
  (`output_id = '<passenger_event_id>|<event_timestamp RFC3339>|<record_id>'`).
  Required fields, the 16-value `event_type` enum and the missing-value
  tokens (`NA`, `NaN`, empty string) verified against TIDES-transit/TIDES
  `spec/passenger_events.schema.json` (main branch, 2026-07-10, cited
  in-code). `event_count` NULL is **preserved as NULL** — never coalesced
  (not to 0, not to the TIDES documented default of 1). `event_timestamp`
  must carry a UTC offset (TIDES declares Frictionless `datetime`; the
  default format is ISO 8601 in UTC per specs.frictionlessdata.io); a naive
  timestamp is a DQ finding, never a guessed zone. Every malformed row →
  `malformed_passenger_event` finding citing record_id + row number (row
  skipped from canonical, never silently); empty file → single
  info-severity finding. The envelope `source` (`tides` |
  `tides_simulated`) is carried verbatim onto every row — simulated data
  stays permanently distinguishable in provenance (handoff 0005 binding
  rule).
- `headway_transform/dr_trips.py` — `normalize_dr_trips` v0.1.1 (handoff
  0013, Demand Response module; 0.1.1: per-row parse quarantine,
  2026-07-13): `demand_response_trips` CSV (wire
  contract: `contracts/demand-response-trip.v0.schema.json`) →
  `CanonicalDrTrip` rows (migration 0021, column-for-column) + one lineage
  edge per row
  (`output_id = '<dr_trip_id>|<pickup_timestamp RFC3339>|<record_id>'`).
  Contradictions are QUARANTINED, never repaired: dropoff before pickup, a
  decreasing odometer pair, sponsored without a sponsor label (or a stray
  sponsor label), and a no-show carrying boardings (Exhibit 36 as quoted in
  the tracker: revenue time yes, boarding no) are all
  `malformed_dr_trip` findings citing record_id + row number. Missing
  optional distances stay NULL — an unmeasured distance is a flagged gap
  downstream, never a fabricated 0. The envelope `source` (`dr` |
  `dr_simulated` | a vendor label bound to the pushing machine key) is
  carried verbatim onto every row.
- `headway_transform/adapters/` — the vendor adapter framework runtime v0
  (handoff 0015). PLACEMENT DECISION (design point 2 said "Go or
  transform-side Python — implementer chooses"): transform-side Python,
  because both v0 target contracts land in the Python normalizers here — the
  adapter engine REUSES `tides_passenger_events`/`dr_trips` (the verified
  contract validation, canonical row construction, and idempotent writer
  paths) instead of duplicating contract semantics in Go. Modules:
  `spec.py` (mapping.v0.yaml loading, machine-validated against
  `contracts/adapter-mapping.v0.schema.json` + semantic checks: resolvable
  IANA timezone, `<vendor>_<product>` label rules with the mandatory
  `_simulated` suffix for synthetic provenance; 2026-07-16 extensions —
  headerless positional columns must be unique and cover every read column,
  `emit` emission names unique with per-emission merged-field contract
  completeness), `registry.py` (fail-closed
  label registry — registration REQUIRES sample fixtures; duplicate/broken
  specs refuse the whole registry at startup), `engine.py` (dialect-aware
  parsing via `row_guard` — header'd or headerless positional (`header:
  false` + declared `columns`; row-width mismatches quarantine), filters
  with reasons, coercions/constants/derived
  fields/exact-Decimal unit conversions, declared-timezone handling that
  quarantines DST-ambiguous/nonexistent wall times, `emit` fan-out (one
  source row → zero or more contract records; per-emission reasoned
  suppression predicates surface as aggregated `adapter_emissions_filtered`
  info findings; rows are atomic — any failing non-suppressed emission
  quarantines the whole row), the target contract's
  validation — JSON Schema for DR plus the contract normalizers per-row —
  and one adapter lineage edge per canonical row carrying
  `adapter:<source_label>` + the spec's content hash), `harness.py` (the
  core of `adapters/validate`: full row accounting, pinned expected counts
  incl. `emitted` for fan-out specs, deterministic round-trip). The consumer routes `raw.vendor.files` through
  the registry: an UNREGISTERED envelope source label is refused with a
  blocking `unregistered_adapter_source` dq.issues row (raw record retained,
  zero canonical writes — fail closed, never guessed). Reference adapter +
  contributor docs: `adapters/` at the repo root.
- `headway_transform/row_guard.py` — per-row CSV parse guards shared by the
  CSV/GTFS normalizers (2026-07-13 hardening pass): mid-iteration
  `csv.Error` capture (oversized field), NUL-byte rejection at field level
  BEFORE anything reaches Postgres, and stray/unterminated-quote absorption
  detection with the absorbed span counted in the finding. One hostile row
  is ONE quarantine finding; the rest of the file still lands.
- `headway_transform/writer.py` — injectable DB-API writer; SQL matches the
  handoff-0001 schema exactly, plus `canonical.trips.block_id` (migration
  0011, handoff 0003) in the trip upsert and `canonical.passenger_events`
  inserts (migration 0012, handoff 0005; `ON CONFLICT (passenger_event_id,
  event_timestamp, source_record_id) DO NOTHING`) (`raw.records`,
  `canonical.*`, `lineage.edges`, `dq.issues`; vehicle positions
  `ON CONFLICT (vehicle_id, "time", source_record_id) DO NOTHING`).
  Replay idempotency now covers lineage and DQ too (migration 0023,
  2026-07-13 hardening pass): `lineage.edges` inserts conflict-DO-NOTHING
  on the full six-column natural key, and transform-emitted `dq.issues`
  rows carry a `dedupe_key` (`transform:` + sha256 of the finding's full
  identity; UNIQUE WHERE NOT NULL) so a redelivered message writes zero
  duplicate edges/findings — while human-/AI-/calc-created issues keep
  `dedupe_key` NULL and are never deduplicated. No `tenant_id` anywhere
  (ADR-0004).
- `headway_transform/consumer.py` — loop skeleton behind a tiny
  `MessageSource` interface (`poll() -> (topic, key, value) | None`) so the
  Kafka client is swappable and unit-testable with a fake. Per-message
  failures are logged AND written as `dq.issues` rows (rollback + quarantine
  commit); the loop continues — a poison message never kills it and is never
  dropped without a trace. Routes `raw.gtfs_rt.vehicle_positions`,
  `raw.gtfs_rt.trip_updates`, `raw.gtfs_static.feed`,
  `raw.tides.passenger_events`, `raw.dr.trips` and `raw.vendor.files`
  (file-carrying topics fetch `object_ref` payloads through the injected
  object fetcher; vendor files resolve their envelope source label against
  the injected adapter registry, fail closed).
- `headway_transform/kafka_source.py` — the real source over
  **kafka-python-ng** (lazy import; `kafka` extra), manual offset commit
  after the DB commit → at-least-once, idempotent via content-addressed
  record_ids + ON CONFLICT DO NOTHING on `raw.records`, every
  `canonical.*` unique key, the `lineage.edges` natural key, and the
  transform `dq.issues` dedupe_key (migration 0023 — before 2026-07-13
  this claim was NOT true for lineage/DQ; a replay duplicated edges and
  findings. Live-verified fixed: see Verification status).

## Running tests

```
cd services/transform && python3 -m pytest tests/ -q
```

## Verification status

- **2026-07-16 (first REAL vendor adapter — TripSpark Streets APC, handoff
  0015 follow-up):** `python3 -m pytest tests/ -q` → **144 passed** (was
  131). New in `tests/test_adapters.py` (13 tests): headerless positional
  columns (undeclared/duplicate column refusals, `columns` without
  `header: false` schema-invalid, per-row width-mismatch quarantine), `emit`
  fan-out (unique emission names, per-emission merged-field contract
  completeness, one row → two distinct records via concat `suffix`, atomic
  row quarantine, suppression findings), the registered `tripspark_streets`
  flow to canonical (the label the 0015 live refusal used — now the first
  real adapter), and harness `emitted` pinning (green/missing-key
  red/drift red). Harness: `python3 adapters/validate` → ALL CHECKS PASSED
  over 4 registered adapters. Live end-to-end + redelivery idempotence
  evidence: handoff 0015, "Outputs — first real adapter (2026-07-16)".
  Operational reminder relearned live: stop side consumers with
  SIGTERM/SIGINT and never let a shell pipeline (`| head`) kill one
  mid-transaction — the orphaned idle-in-transaction backend blocks every
  later replay of the same content-addressed record until terminated, and
  when clearing stray backends, terminate ONLY pids whose client process is
  confirmed dead (one live-container backend was clipped collaterally this
  run; it quarantine-logged, restarted, and resumed idempotently).
- **2026-07-13 (vendor adapter framework v0, handoff 0015):**
  `python3 -m pytest tests/ -q` → **131 passed** (was 102). New:
  `tests/test_adapters.py` (29 tests — spec machine-validation refusals
  incl. unresolvable timezone / synthetic-without-`_simulated` /
  label≠vendor_product / vendor-manual-shaped provenance; registry
  fail-closed rules (no fixture, duplicate label, broken spec); the full
  reference-adapter fixtures with reason-level assertions (DST
  nonexistent/ambiguous quarantines, enum/boolean/integer/decimal coercion
  refusals, JSON-Schema and normalizer cross-field contract rejections,
  row_guard absorption); dual normalizer+adapter lineage edges; determinism;
  consumer fail-closed refusals for unregistered labels and missing
  registry; registered-label flow to canonical for BOTH target contracts;
  harness green-on-reference / red-on-drift). Harness:
  `python3 adapters/validate` → ALL CHECKS PASSED over both registered
  reference adapters. **Live end-to-end run against the running compose
  stack** (evidence in handoff 0015 "Outputs — framework evidence"):
  reference fixtures dropped → `headway-vendor-file` connector →
  `raw.vendor.files` → this consumer (`KAFKA_TOPICS=raw.vendor.files`,
  side group) → psql-verified from a separate connection: 2 raw vendor
  records, 2 `canonical.passenger_events` + 3 `canonical.dr_trips` rows, 5
  normalizer + 5 adapter lineage edges, 14 reasoned quarantine findings + 2
  filter findings; byte-identical redelivery of both files re-produced and
  re-consumed → ZERO new rows in every table; a live unregistered label
  (`tripspark_streets`) was refused with a blocking
  `unregistered_adapter_source` dq.issues row, raw record retained, zero
  canonical writes. Operational finding from the live run: a SIGKILLed
  consumer can leave its in-flight transaction as an orphaned backend
  holding the content-addressed `raw.records` insert, blocking replays
  until the server notices — stop the consumer with SIGTERM/SIGINT
  (`__main__` shuts down cleanly), and terminate stray
  idle-in-transaction backends before re-running.
- **2026-07-13 (ops analytics wave, handoff 0014 — trip_updates +
  agencies):** `python3 -m pytest tests/ -q` → **102 passed** (was 83).
  New: `tests/test_trip_updates.py` (12 tests — stop-time events with one
  edge per row; delay-only events never derive a time; CANCELED →
  trip-level row; SKIPPED recorded; missing header timestamp quarantines
  the frame whole; no-trip-id/no-stop-identity quarantines; in-frame
  duplicate kept-first + warned; undecodable/malformed paths; replay
  dedupe keys), agency.txt coverage in `tests/test_gtfs_static.py`
  (normalize now returns agencies; missing agency.txt blocking; missing
  timezone quarantined; omitted agency_id stored '' with the name as the
  lineage output_id), writer SQL tests for `canonical.trip_updates`
  (natural-key ON CONFLICT exactly matching migration 0025) and
  `canonical.agencies`, and consumer routing for
  `raw.gtfs_rt.trip_updates`. LIVE: real MBTA trip_updates ingested and
  replayed into canonical.trip_updates, canonical.agencies populated from
  the live MBTA static feed, and a two-frame double-delivery demonstrated
  writing zero new rows — counts and psql evidence in handoff 0014,
  "Outputs — backend evidence".
- **2026-07-13 (hardening pass, Batch B — intake robustness + replay
  idempotency):** `python3 -m pytest tests/ -q` → **83 passed in 0.23s**
  (was 66 before this batch; Python 3.12.3, venv `~/venv`).
  New coverage (`tests/test_hardening.py` + writer/model additions): the
  reviewers' three reproduced hostile-CSV inputs — oversized field
  (mid-iteration `csv.Error` captured per row), NUL cell (rejected at
  field level before Postgres), stray/unterminated quote (absorption
  detected and counted) — each against the DR, TIDES and GTFS-static
  normalizers, with remaining good rows still landing; GTFS zip
  decompression budget (per-member and whole-archive, small limits
  injected, blocking `transform_failure` finding naming the limit, feed
  aborted with zero rows); capped object fetch (`read_capped` +
  `ObjectTooLargeError` → `transform_failure` finding naming the limit);
  `run_loop`'s quarantine finding now carrying the actual exception
  message; lineage/dq ON CONFLICT SQL and the transform-scoped
  `dedupe_key` (stable, `transform:`-prefixed, None without a
  source-record anchor). Transform versions bumped: `normalize_dr_trips` /
  `normalize_tides_passenger_events` 0.1.1, `normalize_gtfs_static` 0.3.1.
  **Live-verified the same day** (evidence with output in
  `docs/reviews/2026-07-13-hardening-pass.md`, Batch B): migration 0023
  applied to the live TimescaleDB (672,073 duplicate lineage-edge rows
  measured pre-migration, 0 after; unique indexes psql-verified from a
  separate connection), then a REAL `raw.dr.trips` message (produced by
  the live connector from a simulator drop) delivered twice through
  `process_message` + `DbWriter` into the live database: first delivery
  13 canonical rows / 13 edges / 3 findings / 1 raw record, second
  delivery **zero new rows in all four tables**.

- **2026-07-12 (handoff 0011 — GTFS stop geometry):** `python3 -m pytest
  tests/ -q` → **58 passed** (49 pre-0011 green with the widened
  `normalize` signature, plus 9 new: stops/stop_times normalization with
  one edge per row at transform version 0.3.0; nullable node coordinates
  with NO finding vs missing REQUIRED coordinates → warning + NULL, never a
  guess; GTFS >24:00:00 times parsed, empty times NULL with no finding,
  malformed times/negative shape_dist warned; absent `shape_dist_traveled`
  → NULL preserved, present values parsed; row-by-row quarantine of
  malformed stop_times identities; writer upsert SQL/params incl. NULL
  binds; consumer wiring). **Live-verified the same day** against the
  already-ingested MBTA static feed (record `48dc4271…`, fetched from
  MinIO, replayed through `normalize` + `DbWriter` with the consumer's
  one-commit boundary): **403 routes / 112,578 trips / 10,309 stops /
  3,077,103 stop_times normalized, 3,200,393 lineage edges at 0.3.0, 0 DQ
  findings**; counts and spot-checked rows (GTFS `10:40:00` → 38400 s; 691
  coordinate-less generic nodes stored NULL; zero fabricated shape_dist
  values on a feed that omits the column) verified from a separate psql
  connection — evidence in handoff 0011, "Outputs — evidence".

- `python3 -m pytest tests/ -q` → **49 passed in 0.22s** (2026-07-10,
  Python 3.12.3, venv `~/venv`). Covers: envelope contract
  validation (valid/invalid/extra-property/bad-version); real FeedMessage
  round trip (built with gtfs-realtime-bindings in-test) with one lineage
  edge per row; header-timestamp fallback noted; no-timestamp →
  DQ finding not a guessed row; undecodable protobuf → `undecodable_payload`
  finding, zero rows, no swallowed exception; in-test GTFS zip →
  routes/trips + edges; unknown `route_type` → `'unknown'` + finding;
  `block_id` parsed when the column is present (empty → NULL) and NULL with
  no DQ finding when the column is absent — the optional-field case stays
  green (handoff 0003); fake-connection writer SQL/params including the
  five-column trip upsert with `block_id = EXCLUDED.block_id`; consumer
  poison-message quarantine and loop survival. TIDES passenger events
  (handoff 0005, in-test CSV bytes): happy path with one edge per row and
  source carried; `tides_simulated` carried verbatim; malformed rows (missing
  `vehicle_id`, unparseable timestamp, unparseable count) → one
  `malformed_passenger_event` finding each with row number while good rows
  still land; unknown `event_type` (wrong case) → finding, not a guess;
  NULL/absent `event_count` preserved as `None`, never 0; naive timestamp →
  finding, row skipped; empty file (zero bytes and header-only) → single
  info finding; writer passenger-events SQL/params with `None` binds;
  consumer routing of `raw.tides.passenger_events` through the object
  fetcher and blocking `object_ref_unavailable` without one.
- `cd db && python3 -m pytest test_migrations_static.py -q` → **10 passed in
  0.11s** (2026-07-10), including the new migration-0012 checks (hypertable
  on `event_timestamp`, unique `(passenger_event_id, event_timestamp,
  source_record_id)`, `source TEXT NOT NULL`, FK to `raw.records`, nullable
  no-default `event_count`).
- **PENDING — live verification.** Docker/Kafka/Postgres are unavailable in
  this environment. Not yet verified: consumption from a real Kafka broker
  (`kafka_source.py` is untested against a live cluster), inserts against a
  real TimescaleDB (SQL is written to the handoff-0001 migrations in
  `db/migrations/` but has not been executed), object-store fetch for
  `object_ref` GTFS static payloads (interface injected, no real client).
  The first environment with Docker must run the compose stack, replay a
  golden fixture, and attach the evidence before this is declared Done
  (Shared Constraint 8).
- **PENDING — live block_id backfill (orchestrator's job, handoff 0003).**
  Migration `0011_trips_block_id.sql` and a static-feed replay (the upsert
  backfills `block_id` onto existing `canonical.trips` rows — MBTA carries
  it for bus/subway, confirm at replay) run against the live database by the
  orchestrator, followed by the calc v0.2-vs-v0.3 VRH comparison.
- **PENDING — migration 0012 live apply (orchestrator's job, handoff 0005).**
  `0012_passenger_events.sql` has passed the static checks only; the
  orchestrator applies it to the live database. End-to-end TIDES flow
  (headway-tides connector → MinIO object_ref → topic
  `raw.tides.passenger_events` → this normalizer → live TimescaleDB) awaits
  the ingestion deliverables of handoff 0005.

## Dependency licenses (all permissive / OSI-approved)

| Package | License | Role |
| --- | --- | --- |
| jsonschema | MIT | envelope contract validation |
| gtfs-realtime-bindings 2.1.0 | Apache-2.0 | GTFS-RT protobuf bindings |
| protobuf (transitive) | BSD-3-Clause | protobuf runtime |
| kafka-python-ng (optional `kafka` extra) | Apache-2.0 | Kafka client |
| python-snappy (optional `kafka` extra) | BSD | snappy codec — required in practice: the Go ingestion's franz-go producer snappy-compresses by default, and kafka-python-ng cannot decode those batches without it (2026-07-09 live-run finding, handoff 0001) |
| psycopg (optional `db` extra) | LGPL-3.0 with exception | DB driver only; core logic takes any DB-API connection |
| pytest (test only) | MIT | test runner |

## Guardrails held

No `tenant_id`; no silent drops (`grep -rE 'except.*pass'` clean — every
failure path emits a `DQFinding` or re-raises); every canonical row has
exactly one lineage edge stamped with transform name + version; raw records
are never mutated; unassigned positions stay unassigned.
