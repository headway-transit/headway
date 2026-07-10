-- 0012: canonical.passenger_events — TIDES passenger events (handoff 0005,
-- slice 2 UPT). Column vocabulary adopted from the TIDES passenger_events
-- table per ADR-0003 (TIDES-transit/TIDES spec/passenger_events.schema.json,
-- main branch, verified 2026-07-10); trip_id carries TIDES trip_id_performed.

CREATE TABLE canonical.passenger_events (
    event_timestamp    TIMESTAMPTZ NOT NULL,  -- event time from the feed (hypertable time), never ingest time
    service_date       DATE NOT NULL,
    passenger_event_id TEXT NOT NULL,
    vehicle_id         TEXT NOT NULL,
    -- trip_id is nullable by design (TIDES trip_id_performed is optional):
    -- an unassigned event stays unassigned (fail loudly downstream, never guess).
    trip_id            TEXT,
    trip_stop_sequence INTEGER,
    -- One of the 16 TIDES event_type enum values (verified 2026-07-10),
    -- e.g. 'Passenger boarded' / 'Passenger alighted'.
    event_type         TEXT NOT NULL,
    -- NULL preserved as NULL — never coalesced (not to 0, not to the TIDES
    -- documented default of 1). A missing count must surface loudly in the
    -- UPT calc's DQ trail, not silently fabricate or erase boardings.
    event_count        INTEGER,
    -- Envelope source: 'tides' for real feeds, 'tides_simulated' for
    -- simulator output — simulated data is permanently distinguishable
    -- in provenance (handoff 0005 binding rule).
    source             TEXT NOT NULL,
    source_record_id   TEXT NOT NULL REFERENCES raw.records (record_id)
);

SELECT create_hypertable('canonical.passenger_events', 'event_timestamp');

-- TimescaleDB requires unique indexes to include the partition column;
-- (passenger_event_id, event_timestamp, source_record_id) satisfies this and
-- makes at-least-once replays of the same content-addressed record no-ops
-- via the transform's ON CONFLICT DO NOTHING.
CREATE UNIQUE INDEX passenger_events_event_time_source_key
    ON canonical.passenger_events (passenger_event_id, event_timestamp, source_record_id);
