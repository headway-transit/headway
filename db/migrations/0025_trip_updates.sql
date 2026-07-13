-- 0025: canonical.trip_updates — GTFS-Realtime TripUpdate stop-time events
-- (handoff 0014, design point 2; feature-gap report #8: the raw
-- raw.gtfs_rt.trip_updates records were never normalized).
--
-- PREDICTIONS, NOT OBSERVATIONS — the load-bearing honesty rule of this
-- table. Every timestamp here is what the agency's real-time system
-- PREDICTED at feed_timestamp, labeled as such (predicted_* columns), and
-- must never be treated as an observed arrival/departure or feed any
-- NTD figure. Observed passages are derived separately from
-- canonical.vehicle_positions (headway_calc.passages,
-- services/calc/OPS_DEFINITIONS.md).
--
-- Shape: one row per (TripUpdate entity, StopTimeUpdate) — the prediction
-- for one trip at one stop as of one feed snapshot — plus one TRIP-LEVEL
-- row (stop_id/stop_sequence NULL) for trips whose update carries no
-- stop-time events (e.g. schedule_relationship CANCELED): a cancellation
-- is data, not a defect. Field semantics are defined by the GTFS-Realtime
-- reference (gtfs.org/documentation/realtime/reference) — verify against
-- the current published spec; the schedule_relationship columns store the
-- spec's enum names verbatim (TEXT, no CHECK: the spec owns that
-- vocabulary and may extend it — an unknown value is data to surface, not
-- an insert failure).
--
-- Lineage: one lineage.edges row per canonical row (transform
-- normalize_gtfs_rt_trip_updates), anchored to the frame's
-- content-addressed raw record — same posture as vehicle_positions.
--
-- Replay idempotency (migration 0023 discipline): the natural key is
-- (trip_id, feed_timestamp, source_record_id, stop_sequence, stop_id);
-- stop_sequence/stop_id are NULL on trip-level rows and either may be
-- absent per the spec, so the unique index COALESCEs them (PostgreSQL
-- treats NULLs as distinct in a plain unique index, which would let
-- replays duplicate trip-level rows). The writer's ON CONFLICT targets the
-- same expressions.

CREATE TABLE canonical.trip_updates (
    -- When the prediction was made: the FeedMessage header timestamp
    -- (feed snapshot time). The hypertable time dimension. A frame without
    -- a header timestamp is quarantined by the transform — a prediction
    -- whose made-at time is unknown is unusable and a time is never
    -- guessed.
    feed_timestamp        TIMESTAMPTZ NOT NULL,
    trip_id               TEXT NOT NULL,
    route_id              TEXT,
    vehicle_id            TEXT,
    -- Stop identity: at least one of stop_id / stop_sequence per the
    -- GTFS-RT spec for stop-time rows; both NULL ONLY on a trip-level row
    -- (enforced below via trip_schedule_relationship).
    stop_id               TEXT,
    stop_sequence         INTEGER CHECK (stop_sequence >= 0),
    -- Predicted event times (POSIX from the feed's StopTimeEvent.time).
    -- NULLABLE: a StopTimeUpdate may carry only a delay, or NO_DATA/SKIPPED
    -- rows carry nothing. NULL is preserved, never derived from delay +
    -- schedule here — that inference belongs to a versioned calc, not the
    -- normalizer.
    predicted_arrival             TIMESTAMPTZ,
    arrival_delay_seconds         INTEGER,
    arrival_uncertainty_seconds   INTEGER,
    predicted_departure           TIMESTAMPTZ,
    departure_delay_seconds      INTEGER,
    departure_uncertainty_seconds INTEGER,
    -- TripDescriptor.schedule_relationship enum name, verbatim
    -- ('SCHEDULED', 'ADDED', 'CANCELED', ...).
    trip_schedule_relationship    TEXT NOT NULL,
    -- StopTimeUpdate.schedule_relationship enum name, verbatim
    -- ('SCHEDULED', 'SKIPPED', 'NO_DATA', ...); NULL on trip-level rows.
    stop_schedule_relationship    TEXT,
    source_record_id      TEXT NOT NULL REFERENCES raw.records (record_id),
    -- A row must identify a stop unless it is the trip-level form (which
    -- carries no stop-time prediction columns either).
    CONSTRAINT trip_updates_stop_identity CHECK (
        stop_id IS NOT NULL OR stop_sequence IS NOT NULL
        OR (
            stop_schedule_relationship IS NULL
            AND predicted_arrival IS NULL
            AND predicted_departure IS NULL
        )
    )
);

SELECT create_hypertable('canonical.trip_updates', 'feed_timestamp');

-- Natural key for replay dedupe (see header). TimescaleDB requires unique
-- indexes to include the partition column (feed_timestamp).
CREATE UNIQUE INDEX trip_updates_natural_key_uq
    ON canonical.trip_updates (
        trip_id,
        feed_timestamp,
        source_record_id,
        COALESCE(stop_sequence, -1),
        COALESCE(stop_id, '')
    );

-- Prediction-accuracy joins (trip_update predictions vs observed passages,
-- the handoff's natural v1) read per trip and stop.
CREATE INDEX trip_updates_trip_stop_idx
    ON canonical.trip_updates (trip_id, stop_id, feed_timestamp);
