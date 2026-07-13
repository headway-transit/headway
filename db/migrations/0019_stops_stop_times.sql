-- 0019: canonical.stops + canonical.stop_times — GTFS static stop geometry
-- (handoff 0011, Passenger Miles Traveled slice). PMT's per-trip load
-- profiles need per-segment distances between consecutive stops; canonical
-- had no stop geometry before this migration (tracker "Verified — Passenger
-- Miles Traveled", distance-measurement note).
--
-- Lineage: like canonical.routes/trips, provenance is carried by one
-- lineage.edges row per normalized row (transform normalize_gtfs_static),
-- anchored to the static feed's content-addressed raw record — not by a
-- column here, because static-feed rows are upserted (a newer feed
-- supersedes) and the edge history preserves every feed that produced them.

CREATE TABLE canonical.stops (
    stop_id   TEXT PRIMARY KEY,
    name      TEXT,
    -- latitude/longitude are NULLABLE BY DESIGN: the GTFS Schedule Reference
    -- (stops.txt, gtfs.org) requires coordinates only for location_type
    -- 0/1/2 (stops/platforms, stations, entrances); generic nodes (3) and
    -- boarding areas (4) may legitimately omit them. NULL is preserved,
    -- NEVER fabricated — a distance calculation that needs a missing
    -- coordinate must fail loudly downstream (DQ finding), not receive a
    -- guessed point.
    latitude  DOUBLE PRECISION,
    longitude DOUBLE PRECISION
);

CREATE TABLE canonical.stop_times (
    trip_id       TEXT NOT NULL,
    stop_id       TEXT NOT NULL,
    stop_sequence INTEGER NOT NULL,
    -- GTFS times routinely exceed 24:00:00 (service past midnight on the
    -- service day), so TIMESTAMPTZ/TIME cannot hold them: stored as integer
    -- seconds after "noon minus 12 h" of the service day (the GTFS time
    -- convention), parsed from HH:MM:SS. NULLABLE — GTFS permits empty
    -- times on non-timepoint rows; NULL is preserved, never interpolated.
    arrival_seconds   INTEGER,
    departure_seconds INTEGER,
    -- shape_dist_traveled NULLABLE, PRESERVED AS-IS (handoff 0011, binding):
    -- a feed that omits the optional field (e.g. MBTA) stays NULL — the
    -- pmt_v0 distance-source precedence then falls back to stop-to-stop
    -- haversine and FLAGS the documented divergence on every figure it
    -- touches; a distance is NEVER fabricated here. Units are FEED-DEFINED
    -- per the GTFS spec (must only be consistent with shapes.txt), so no
    -- unit is assumed by the schema.
    shape_dist_traveled DOUBLE PRECISION,
    -- (trip_id, stop_sequence) is the GTFS-native row identity. No FK to
    -- canonical.trips/canonical.stops: a row referencing a quarantined or
    -- unknown trip/stop is still evidence and must land (its unusability
    -- surfaces as a calc DQ finding, never as a dropped row) — the same
    -- posture as canonical.vehicle_positions.trip_id.
    PRIMARY KEY (trip_id, stop_sequence)
);

-- Reads are per trip (ORDER BY trip_id, stop_sequence — the PK), plus
-- stop-centric lookups for geometry joins.
CREATE INDEX stop_times_stop_id_idx ON canonical.stop_times (stop_id);
