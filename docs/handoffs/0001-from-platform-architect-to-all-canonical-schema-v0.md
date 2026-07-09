# Handoff: platform-architect → all roles — Canonical Schema v0 (walking skeleton)

## Context
ADR-0009's walking skeleton needs one shared schema contract so Ingestion (Go), Transform, Calc, API (Python), and Web can build in parallel. This document IS that contract for v0. It implements the TIDES-compatible hybrid model (ADR-0003) at minimum viable scope: enough to carry GTFS static + GTFS-RT vehicle positions through normalization to a VRM/VRH computation with a full lineage graph (ADR-0007). It is deliberately thin; extending it requires a follow-up handoff, not an in-place edit.

## Inputs (what receiving roles are given)
- Wire contract: `contracts/raw-record-envelope.v0.schema.json` + `contracts/topics.v0.md` (ADR-0006).
- Target database: PostgreSQL 16 + TimescaleDB, one database per agency, **no tenant_id anywhere** (ADR-0004).
- The schema contract below. Migrations live in `db/migrations/` (plain SQL, ordered `NNNN_description.sql`, applied by a simple runner).

### Schema contract v0 (PostgreSQL schemas and tables)

**`raw.records`** — registry of immutable raw records (bytes live in the object store / Kafka; this is the index).
- `record_id TEXT PRIMARY KEY` — lowercase hex SHA-256 of raw payload bytes (matches envelope).
- `source TEXT NOT NULL`, `connector TEXT NOT NULL`, `connector_version TEXT NOT NULL`
- `content_type TEXT NOT NULL`, `payload_encoding TEXT NOT NULL`, `payload_ref TEXT` (object key when object_ref)
- `fetched_at TIMESTAMPTZ NOT NULL`, `landed_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `parse_status TEXT NOT NULL CHECK (parse_status IN ('ok','malformed'))`, `parse_error TEXT`
- Immutability: a trigger rejects UPDATE and DELETE.

**`canonical.routes`** — `route_id TEXT PRIMARY KEY`, `short_name TEXT`, `long_name TEXT`, `mode TEXT NOT NULL` (GTFS route_type mapped to a text mode; mapping cited to gtfs.org, verify current spec).

**`canonical.trips`** — `trip_id TEXT PRIMARY KEY`, `route_id TEXT NOT NULL REFERENCES canonical.routes`, `service_id TEXT NOT NULL`, `direction_id SMALLINT`.

**`canonical.vehicle_positions`** — TimescaleDB hypertable, partitioned on `time`.
- `time TIMESTAMPTZ NOT NULL` (vehicle timestamp from the feed; event time, not ingest time)
- `vehicle_id TEXT NOT NULL`, `trip_id TEXT`, `route_id TEXT`
- `latitude DOUBLE PRECISION NOT NULL`, `longitude DOUBLE PRECISION NOT NULL`
- `bearing REAL`, `speed_mps REAL`, `odometer_m DOUBLE PRECISION`
- `source_record_id TEXT NOT NULL REFERENCES raw.records(record_id)`
- Unique on `(vehicle_id, time, source_record_id)`; no NOT NULL trip coercion — an unassigned position stays unassigned (fail loudly downstream, never guess).

**`computed.metric_values`** — the ONLY place reported figures land (written exclusively by the calc library).
- `metric_value_id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
- `metric TEXT NOT NULL` (v0: `'vrm'`, `'vrh'`), `unit TEXT NOT NULL` (`'miles'`, `'hours'`)
- `period_start DATE NOT NULL`, `period_end DATE NOT NULL`, `scope TEXT NOT NULL DEFAULT 'agency'`
- `value NUMERIC NOT NULL` — NUMERIC, never float
- `calc_name TEXT NOT NULL`, `calc_version TEXT NOT NULL`, `computed_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `certification_status TEXT NOT NULL DEFAULT 'uncertified' CHECK (certification_status IN ('uncertified','certified'))`

**`lineage.edges`** — the explicit lineage graph (ADR-0007). One row per derivation edge.
- `edge_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
- `output_kind TEXT NOT NULL` (`'canonical.vehicle_positions'`, `'computed.metric_values'`, …)
- `output_id TEXT NOT NULL` (the output row's natural/primary key rendered as text)
- `transform_name TEXT NOT NULL`, `transform_version TEXT NOT NULL`
- `input_kind TEXT NOT NULL` (`'raw.records'`, `'canonical.vehicle_positions'`, …)
- `input_id TEXT NOT NULL`
- Index on `(output_kind, output_id)` and `(input_kind, input_id)`. "Explain this number" = recursive traversal from a `computed.metric_values` row to `raw.records` rows.

**`dq.issues`** — `issue_id UUID PK DEFAULT gen_random_uuid()`, `issue_type TEXT NOT NULL`, `severity TEXT NOT NULL CHECK (severity IN ('info','warning','blocking'))`, `status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','owned','resolved'))`, `owner TEXT`, `title TEXT NOT NULL`, `description TEXT NOT NULL`, `source_record_ids TEXT[]`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `resolved_at TIMESTAMPTZ`, `resolution TEXT`.

**`audit.events`** — append-only (trigger rejects UPDATE/DELETE): `event_id BIGINT IDENTITY PK`, `at TIMESTAMPTZ NOT NULL DEFAULT now()`, `actor TEXT NOT NULL`, `action TEXT NOT NULL`, `subject_kind TEXT`, `subject_id TEXT`, `detail JSONB NOT NULL DEFAULT '{}'`.

**`cert.certifications`** — `certification_id UUID PK DEFAULT gen_random_uuid()`, `metric_value_ids UUID[] NOT NULL`, `certified_by TEXT NOT NULL`, `certified_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `attestation TEXT NOT NULL`. Insert must be accompanied by an `audit.events` row; certification is never silent.

## Outputs (what each receiving role must produce)
- **Data Engineer scope:** `db/migrations/` implementing exactly this contract + a minimal migration runner; deviations require a response section here, not silent edits.
- **Ingestion scope:** Go connectors producing envelope-conformant messages to the v0 topics; `raw.records` rows landed by the consumer side of the pipeline.
- **Calc scope:** VRM/VRH v0 as pure versioned functions reading `canonical.*`, writing `computed.metric_values` + `lineage.edges`.
- **API scope:** read endpoints for computed values with lineage traversal; local-account auth (ADR-0011); certification endpoint writing `cert.certifications` + `audit.events`.

## Open Questions
- VRM/VRH v0 semantics are a walking-skeleton approximation (position-derived distance/duration in revenue service). The FTA NTD definitions (revenue-service inclusion, deadhead exclusion) MUST be verified against the current FTA NTD Reporting Manuals before any figure is treated as reportable; calc v0 is versioned `0.x` and marked pre-verification in the regulatory-change tracker. Owner: NTD & Compliance Engineer.
- Trip-distance authority (shape-based vs position-derived) deferred to slice 2. Proposed default: position-derived haversine for v0, flagged in calc docs.

## Verification Evidence
- Wire contract + topic registry exist at `contracts/` (this repo, this commit).
- Schema contract reviewed against ADR-0003/0004/0006/0007 by the Platform Architect (author of this handoff).
- Live-stack verification (migrations applied to a real TimescaleDB) is pending — Docker is unavailable in the authoring environment; the migration runner and SQL must be validated by the first environment with Docker, and this handoff must be updated with that evidence before the schema is declared Done.

## Response — backend-engineer

**Schema addition: `auth.users` (migration `db/migrations/0009_auth_users.sql`).** The API scope in this handoff requires local-account auth (ADR-0011), but the schema contract above defines no users table. Rather than extend the contract silently, this response records the addition:

- `auth.users` — `user_id UUID PK DEFAULT gen_random_uuid()`, `username TEXT NOT NULL UNIQUE`, `password_hash TEXT NOT NULL` (bcrypt; Apache-2.0 library per ADR-0001), `role TEXT NOT NULL CHECK (role IN ('viewer','data_steward','report_preparer','certifying_official'))`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `disabled BOOLEAN NOT NULL DEFAULT false`. The migration also creates the `auth` schema (0001 predates it).
- Scope note: this table backs the **local-account** path only. The native OIDC relying party (ADR-0011, next increment) produces the same normalized claim set `{sub, username, role}` and needs no change here.
- The API deliverables named in "API scope" above are implemented at `services/api/` against this contract's table/column names exactly; the certification endpoint writes `cert.certifications` + `audit.events` in one transaction and refuses (409) while any blocking `dq.issues` row is unresolved (v0 global check; lineage-scoped blocking is a follow-up).
- Verification: `services/api` test suite green against a fake connection; live-database verification remains PENDING alongside this handoff's own pending TimescaleDB evidence (no Docker in the authoring environment).
