-- 0028: headway_readonly — the analyst's read-only SQL role (handoff 0018,
-- design point 2).
--
-- WHY: planning/data teams evaluate platforms by how well they feed the
-- tools they already use. This role lets an analyst point psql, DBeaver, or
-- pandas.read_sql at the agency database and explore — and the honesty
-- story holds structurally: explore and compute freely; nothing computed
-- outside the calc library can become a reported figure, because only the
-- calc library writes computed.metric_values and the category walls are
-- database CHECKs (migration 0024), not privileges this role could bypass.
-- SELECT-only means the role cannot write anything anywhere.
--
-- LEAST PRIVILEGE (the design's binding rule):
--
--   GRANTED — SELECT on all tables in exactly four schemas:
--     canonical.*  the normalized open data model
--     computed.*   the calc library's persisted figures (with provenance)
--     lineage.*    the edges that let any figure prove itself
--     dq.*         the owned gaps/conflicts workflow (fail-loudly, visible)
--   plus raw.records METADATA COLUMNS ONLY (column-level grant below).
--
--   EXCLUDED ENTIRELY — no USAGE, no SELECT:
--     auth.*      password hashes, machine-key hashes, webhook secrets
--     audit.*     the audit trail (operator surface, actor attribution)
--     cert.*      certification records (certifier identity)
--     app.*       settings (operator surface; audited writes)
--     safety.*    S&S event narratives — free-text about casualties;
--                 PII-adjacent, excluded on any doubt
--     sampling.*  measurement rows carry surveyor notes / free-text;
--                 PII-adjacent, excluded on any doubt
--
--   raw.records COLUMN-LEVEL: payload bytes are NOT inline (they live in
--   the object store / Kafka; this table is the index — migration 0002),
--   so the metadata columns are safe and useful for lineage walks that
--   bottom out at raw record_ids. Two columns are still withheld:
--     payload_ref  object-store keys — useless without object-store
--                  credentials the analyst must not have; least privilege
--     parse_error  populated from parser output that can quote fragments
--                  of a malformed payload verbatim (see the transform's
--                  "CSV parse error:" findings) — content, not metadata
--
-- CLUSTER vs DATABASE: a PostgreSQL role is cluster-wide; GRANTs are
-- per-database. Under one-database-per-agency (ADR-0004) this migration
-- runs in every agency database, so the guarded CREATE ROLE makes the
-- second and later runs (and re-runs anywhere) idempotent.
--
-- NOLOGIN by design: this role is a bundle of privileges, never a
-- credential. An administrator creates a per-person LOGIN user and grants
-- the role (commands in docs/analyst-access.md) — so access is per-person,
-- revocable, and attributable, and no shared analyst password ever exists.
--
-- FUTURE TABLES: ALTER DEFAULT PRIVILEGES below covers tables that future
-- migrations create in the four granted schemas, because migrations run as
-- the same database owner this migration runs as. A future PII-bearing
-- table in these schemas must therefore be weighed against this role in
-- its own migration (REVOKE there if needed) — stated here so the default
-- is a conscious choice, not an accident.

DO $$
BEGIN
    CREATE ROLE headway_readonly NOLOGIN;
EXCEPTION
    WHEN duplicate_object THEN
        RAISE NOTICE 'role headway_readonly already exists (cluster-wide), reusing it';
END
$$;

-- Belt and braces: if the role pre-existed with wider rights (it should
-- never — but least privilege is re-asserted, not assumed), strip every
-- grant in this database before re-granting exactly the intended set.
REVOKE ALL ON ALL TABLES IN SCHEMA raw, canonical, computed, lineage, dq
    FROM headway_readonly;
REVOKE ALL ON SCHEMA raw, canonical, computed, lineage, dq
    FROM headway_readonly;

GRANT USAGE ON SCHEMA canonical, computed, lineage, dq TO headway_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA canonical, computed, lineage, dq
    TO headway_readonly;
ALTER DEFAULT PRIVILEGES IN SCHEMA canonical, computed, lineage, dq
    GRANT SELECT ON TABLES TO headway_readonly;

-- raw.records: metadata columns only (see the header for what is withheld
-- and why). A column-level grant means SELECT * fails for this role —
-- analysts name the columns, and the two withheld ones stay unreadable.
GRANT USAGE ON SCHEMA raw TO headway_readonly;
GRANT SELECT (record_id, source, connector, connector_version, content_type,
              payload_encoding, fetched_at, landed_at, parse_status)
    ON raw.records TO headway_readonly;

-- canonical.dr_trips: rider-privacy withholding (Security review, handoff
-- 0018 evidence). Precise pickup/dropoff coordinates of demand-response
-- trips are effectively rider home addresses. The analyst role gets every
-- operational column (times, distances, counts, TOS, flags) but NOT
-- pickup_lat/pickup_lon/dropoff_lat/dropoff_lon — location-level analysis
-- goes through the application's authorized roles, not the bulk SQL path.
REVOKE SELECT ON canonical.dr_trips FROM headway_readonly;
GRANT SELECT (pickup_timestamp, service_date, dr_trip_id, vehicle_id, tos,
              request_timestamp, dispatch_timestamp, dropoff_timestamp,
              onboard_miles, distance_source, pickup_odometer_miles,
              dropoff_odometer_miles, riders, attendants_companions,
              ada_related, sponsored, sponsor, no_show, interruption_after,
              driver_shift_id, dispatching_point_id, source, source_record_id)
    ON canonical.dr_trips TO headway_readonly;
