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
- **2026-07-09 — live-verified against the Compose stack** (Docker available for the first time):
  - Full stack booted healthy: apache/kafka:3.9.1 (KRaft), timescale/timescaledb:latest-pg16, apicurio-registry:3.0.6, MinIO, Prometheus, Grafana — 6/6 healthchecks green.
  - `db/migrate.py` applied all 9 migrations to real TimescaleDB; re-run reported "up to date: 9 migration(s) already applied" (idempotent).
  - `canonical.vehicle_positions` confirmed a real hypertable via `timescaledb_information.hypertables`.
  - Immutability proven by attack: `UPDATE`/`DELETE` on `raw.records` → `ERROR: raw.records is immutable`; `UPDATE` on `audit.events` → `ERROR: audit.events is append-only`; the inserted record survived intact.
  - Defect found in verification: a `DATABASE_URL` built from a password containing `@`/special characters breaks URL parsing — credentials must be percent-encoded (fixed in the session by encoding; `db/README.md` and the compose placeholder need the note; migrate.py accepting libpq `PG*` env vars is the robust follow-up).
- **2026-07-09 — end-to-end run against live MBTA feeds (public GTFS + GTFS-RT, zero onboarding per ADR-0009):**
  - Go ingestion container (first Docker build of the image) produced GTFS-RT frames every 30s and landed the 24 MB GTFS static zip in MinIO; the zip's content-addressed `record_id` was identical across a container restart (content addressing proven on real data).
  - Transform consumed both topics from Kafka (host listener 127.0.0.1:29092) → real TimescaleDB: 114 raw.records, 403 canonical.routes, 112,578 canonical.trips, 59,317 canonical.vehicle_positions, 172,298 lineage.edges, **0 dq.issues from normalization**.
  - Calc runner over the day's period: loaded 59,317 positions, found 122 real telemetry gaps per metric (collection cold-start artifacts + genuine GPS dropouts, e.g. subway tunnels), **refused to persist both VRM and VRH** (`value: null`) and routed **244 blocking dq.issues** — the fail-loudly guardrail exercised end-to-end on real data.
  - API served the DQ queue live (local-account login → bearer token → `GET /dq/issues`): 244 open issues, plain-language descriptions naming vehicle/trip/timestamps and citing content-addressed source record ids.
  - Provisioning gaps found & fixed in-session (compose bootstrap follow-up): Kafka topics needed explicit creation; MinIO bucket needed creation; kafka-python-ng needed `python-snappy` to read franz-go's snappy-compressed batches (transform `kafka` extra must declare it).
  - Product learning: vrm_v0/vrh_v0's all-or-nothing gap refusal means any realistic full-fleet window refuses; the per-group exclusion + coverage-reporting policy (an NTD & Compliance decision, verified against FTA guidance) is the necessary next calc increment before a live metric can persist and the lineage-traversal endpoint can be demonstrated on real data (it is proven in tests).

## Response — backend-engineer

**Schema addition: `auth.users` (migration `db/migrations/0009_auth_users.sql`).** The API scope in this handoff requires local-account auth (ADR-0011), but the schema contract above defines no users table. Rather than extend the contract silently, this response records the addition:

- `auth.users` — `user_id UUID PK DEFAULT gen_random_uuid()`, `username TEXT NOT NULL UNIQUE`, `password_hash TEXT NOT NULL` (bcrypt; Apache-2.0 library per ADR-0001), `role TEXT NOT NULL CHECK (role IN ('viewer','data_steward','report_preparer','certifying_official'))`, `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `disabled BOOLEAN NOT NULL DEFAULT false`. The migration also creates the `auth` schema (0001 predates it).
- Scope note: this table backs the **local-account** path only. The native OIDC relying party (ADR-0011, next increment) produces the same normalized claim set `{sub, username, role}` and needs no change here.
- The API deliverables named in "API scope" above are implemented at `services/api/` against this contract's table/column names exactly; the certification endpoint writes `cert.certifications` + `audit.events` in one transaction and refuses (409) while any blocking `dq.issues` row is unresolved (v0 global check; lineage-scoped blocking is a follow-up).
- Verification: `services/api` test suite green against a fake connection; live-database verification remains PENDING alongside this handoff's own pending TimescaleDB evidence (no Docker in the authoring environment).

## Response — backend+frontend (wave 8)

**Additive contract extension: `GET /metrics/values` now serves the `detail` column.** Migration 0010 added `computed.metric_values.detail JSONB NOT NULL DEFAULT '{}'` (per-value calculation detail: coverage details for vrm/vrh, `UptDetail` for upt — see `services/calc/headway_calc/types.py` `to_dict` shapes) after the API's read endpoint was written, so the API silently omitted it. Wave 8 extends the SELECT and the `MetricValue` response model with `detail` (JSON object, `{}` for detail-less rows, optional-with-default in the schema so existing clients are unaffected). Ratios/factors inside `detail` are JSON **strings**, exactly as persisted — the same Decimal-safety rule as `value`. Read-only and additive; no existing field changed. `services/api/openapi.json` regenerated via `scripts/export_openapi.py`; round-trip covered by `services/api/tests/test_metrics.py` (canned UPT detail incl. `source_mix` served verbatim; detail-less row serves `{}`). Consumed by the web UI (wave-8 frontend track) for the per-figure detail panel, the SIMULATED DATA badge (`detail.source_mix` containing any source named like `*simulated*`), and the Monthly Ridership preview report.
