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
- `headway_transform/gtfs_static.py` — `normalize_gtfs_static` v0.3.1
  (0.3.1: decompression budget + per-row parse quarantine, 2026-07-13):
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
  `raw.gtfs_static.feed` and `raw.tides.passenger_events` (the latter two
  fetch `object_ref` payloads through the injected object fetcher).
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

- **2026-07-13 (hardening pass, Batch B — intake robustness + replay
  idempotency):** `python3 -m pytest tests/ -q` → **83 passed in 0.23s**
  (was 66 before this batch; Python 3.12.3, venv `/home/daniel/venv`).
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
  Python 3.12.3, venv `/home/daniel/venv`). Covers: envelope contract
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
