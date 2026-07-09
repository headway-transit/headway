-- 0003: canonical.routes, canonical.trips, canonical.vehicle_positions.

CREATE TABLE canonical.routes (
    route_id   TEXT PRIMARY KEY,
    short_name TEXT,
    long_name  TEXT,
    -- GTFS route_type mapped to a text mode; mapping cited to gtfs.org,
    -- verify against the current GTFS spec before extending.
    mode       TEXT NOT NULL
);

CREATE TABLE canonical.trips (
    trip_id      TEXT PRIMARY KEY,
    route_id     TEXT NOT NULL REFERENCES canonical.routes,
    service_id   TEXT NOT NULL,
    direction_id SMALLINT
);

CREATE TABLE canonical.vehicle_positions (
    "time"           TIMESTAMPTZ NOT NULL,  -- event time from the feed, not ingest time
    vehicle_id       TEXT NOT NULL,
    -- trip_id/route_id are nullable by design: an unassigned position stays
    -- unassigned (fail loudly downstream, never guess).
    trip_id          TEXT,
    route_id         TEXT,
    latitude         DOUBLE PRECISION NOT NULL,
    longitude        DOUBLE PRECISION NOT NULL,
    bearing          REAL,
    speed_mps        REAL,
    odometer_m       DOUBLE PRECISION,
    source_record_id TEXT NOT NULL REFERENCES raw.records (record_id)
);

SELECT create_hypertable('canonical.vehicle_positions', 'time');

-- TimescaleDB requires unique indexes to include the partition column;
-- (vehicle_id, time, source_record_id) satisfies this.
CREATE UNIQUE INDEX vehicle_positions_vehicle_time_source_key
    ON canonical.vehicle_positions (vehicle_id, "time", source_record_id);
