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
- `headway_transform/gtfs_static.py` — `normalize_gtfs_static` v0.1.0:
  GTFS zip `routes.txt`/`trips.txt` → `CanonicalRoute`/`CanonicalTrip` +
  edges. `route_type` → mode map cited to gtfs.org; unmapped values → mode
  `'unknown'` + DQ finding, never a guess.
- `headway_transform/writer.py` — injectable DB-API writer; SQL matches the
  handoff-0001 schema exactly (`raw.records`, `canonical.*`,
  `lineage.edges`, `dq.issues`; vehicle positions `ON CONFLICT (vehicle_id,
  "time", source_record_id) DO NOTHING`). No `tenant_id` anywhere (ADR-0004).
- `headway_transform/consumer.py` — loop skeleton behind a tiny
  `MessageSource` interface (`poll() -> (topic, key, value) | None`) so the
  Kafka client is swappable and unit-testable with a fake. Per-message
  failures are logged AND written as `dq.issues` rows (rollback + quarantine
  commit); the loop continues — a poison message never kills it and is never
  dropped without a trace.
- `headway_transform/kafka_source.py` — the real source over
  **kafka-python-ng** (lazy import; `kafka` extra), manual offset commit
  after the DB commit → at-least-once, idempotent via content-addressed
  record_ids + ON CONFLICT DO NOTHING.

## Running tests

```
cd services/transform && python3 -m pytest tests/ -q
```

## Verification status

- `python3 -m pytest tests/ -q` → **36 passed in 0.16s** (2026-07-08,
  Python 3.12, venv `/home/daniel/venv`). Covers: envelope contract
  validation (valid/invalid/extra-property/bad-version); real FeedMessage
  round trip (built with gtfs-realtime-bindings in-test) with one lineage
  edge per row; header-timestamp fallback noted; no-timestamp →
  DQ finding not a guessed row; undecodable protobuf → `undecodable_payload`
  finding, zero rows, no swallowed exception; in-test GTFS zip →
  routes/trips + edges; unknown `route_type` → `'unknown'` + finding;
  fake-connection writer SQL/params; consumer poison-message quarantine and
  loop survival.
- **PENDING — live verification.** Docker/Kafka/Postgres are unavailable in
  this environment. Not yet verified: consumption from a real Kafka broker
  (`kafka_source.py` is untested against a live cluster), inserts against a
  real TimescaleDB (SQL is written to the handoff-0001 migrations in
  `db/migrations/` but has not been executed), object-store fetch for
  `object_ref` GTFS static payloads (interface injected, no real client).
  The first environment with Docker must run the compose stack, replay a
  golden fixture, and attach the evidence before this is declared Done
  (Shared Constraint 8).

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
