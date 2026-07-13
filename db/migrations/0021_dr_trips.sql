-- 0021: canonical.dr_trips — demand-response trips (handoff 0013, DR module
-- v0). One row per passenger trip (booking) from a dispatch/scheduling
-- platform, normalized from the demand_response_trip v0 wire contract
-- (contracts/demand-response-trip.v0.schema.json). Regulatory field
-- semantics are pointers to services/calc/REGULATORY_TRACKER.md, section
-- "Verified — Demand Response / on-demand reporting" (2026 NTD Full
-- Reporting Policy Manual pp. 33, 37–39, 129–139, 143–144) — never encoded
-- here from memory.
--
-- NO SEGMENTS TABLE (the handoff's "+ segments if needed"): TX
-- passenger-onboard-only accounting (p. 129) is derivable from the per-trip
-- onboard fields — onboard hours as the union of [pickup, dropoff] windows
-- per vehicle-day, onboard miles from onboard_miles / odometer pairs — so a
-- separate segments table would duplicate the trip rows without adding
-- information. Revisit only if a vendor exports sub-trip onboard segments.

CREATE TABLE canonical.dr_trips (
    -- Boarding time (for a no-show: arrival at the pickup point). The
    -- hypertable time dimension — event time from the dispatch platform,
    -- never ingest time.
    pickup_timestamp      TIMESTAMPTZ NOT NULL,
    service_date          DATE NOT NULL,
    dr_trip_id            TEXT NOT NULL,
    vehicle_id            TEXT NOT NULL,
    -- NTD type of service (manual pp. 37–39). TOS changes the revenue rule
    -- (TX onboard-only, p. 129; TX/TN no deadhead, p. 130), so it is NOT
    -- NULL: a trip without a TOS cannot be accounted and is quarantined by
    -- the transform, never guessed.
    tos                   TEXT NOT NULL CHECK (tos IN ('DO', 'PT', 'TX', 'TN')),
    request_timestamp     TIMESTAMPTZ,
    dispatch_timestamp    TIMESTAMPTZ,
    -- Alighting time (for a no-show: departure from the pickup point).
    -- dropoff >= pickup is enforced: a negative-duration trip is a
    -- contradiction the transform quarantines (fail loudly).
    dropoff_timestamp     TIMESTAMPTZ NOT NULL,
    CONSTRAINT dr_trips_dropoff_not_before_pickup
        CHECK (dropoff_timestamp >= pickup_timestamp),
    pickup_lat            DOUBLE PRECISION,
    pickup_lon            DOUBLE PRECISION,
    dropoff_lat           DOUBLE PRECISION,
    dropoff_lon           DOUBLE PRECISION,
    -- Measured passenger-onboard distance (statute miles). NUMERIC, never
    -- float (repo non-negotiable). NULL = UNMEASURED, preserved as NULL —
    -- never coalesced to 0: dr_vrm/dr_pmt flag the gap, a distance is never
    -- guessed.
    onboard_miles         NUMERIC CHECK (onboard_miles >= 0),
    distance_source       TEXT CHECK (distance_source IN ('odometer', 'gps')),
    -- Odometer readings at boarding/alighting (miles). Pairs make empty
    -- inter-passenger travel (revenue per Exhibit 36) and whole revenue
    -- spans exactly measurable; NULL preserved, never interpolated.
    pickup_odometer_miles  NUMERIC CHECK (pickup_odometer_miles >= 0),
    dropoff_odometer_miles NUMERIC CHECK (dropoff_odometer_miles >= 0),
    -- Boardings on this booking: riders plus NON-EMPLOYEE
    -- attendants/companions (pp. 143–144 — the employee rule is applied by
    -- the exporter per the wire contract). Both 0 on a no-show (revenue
    -- time yes, UPT no — enforced below).
    riders                INTEGER NOT NULL CHECK (riders >= 0),
    attendants_companions INTEGER NOT NULL CHECK (attendants_companions >= 0),
    ada_related           BOOLEAN NOT NULL,
    sponsored             BOOLEAN NOT NULL,
    -- Required exactly when sponsored (the transform quarantines the
    -- contradiction; the CHECK makes it structural).
    sponsor               TEXT,
    CONSTRAINT dr_trips_sponsor_iff_sponsored
        CHECK ((sponsored AND sponsor IS NOT NULL AND length(sponsor) > 0)
               OR (NOT sponsored AND sponsor IS NULL)),
    no_show               BOOLEAN NOT NULL,
    -- Exhibit 36: a no-show trip is revenue time but NEVER a boarding.
    CONSTRAINT dr_trips_no_show_has_no_boardings
        CHECK (NOT no_show OR (riders = 0 AND attendants_companions = 0)),
    -- Service interruption between this trip and the vehicle's next pickup:
    -- breaks the vehicle-day revenue span (p. 129 — garage/dispatching-point
    -- return, lunch, fueling/servicing).
    interruption_after    TEXT NOT NULL DEFAULT 'none' CHECK
        (interruption_after IN ('none', 'lunch', 'fuel', 'garage_return',
                                'dispatch_return')),
    -- References for the six p. 130 deadhead leg types (measurement needs a
    -- future shift-level feed; carried so that increment needs no contract
    -- break).
    driver_shift_id       TEXT,
    dispatching_point_id  TEXT,
    -- Envelope source: 'dr' for real dispatch feeds (or the vendor label
    -- bound to the pushing machine key), 'dr_simulated' for simulator
    -- output — simulated data is permanently distinguishable in provenance
    -- (handoff 0005 binding rule, applied to DR by handoff 0013).
    source                TEXT NOT NULL,
    source_record_id      TEXT NOT NULL REFERENCES raw.records (record_id)
);

SELECT create_hypertable('canonical.dr_trips', 'pickup_timestamp');

-- TimescaleDB requires unique indexes to include the partition column;
-- (dr_trip_id, pickup_timestamp, source_record_id) satisfies this and makes
-- at-least-once replays of the same content-addressed record no-ops via the
-- transform's ON CONFLICT DO NOTHING (the migration-0012 precedent).
CREATE UNIQUE INDEX dr_trips_trip_time_source_key
    ON canonical.dr_trips (dr_trip_id, pickup_timestamp, source_record_id);

-- Vehicle-day accounting (revenue spans, VOMS simultaneity) reads per
-- vehicle and service date.
CREATE INDEX dr_trips_vehicle_service_date_idx
    ON canonical.dr_trips (vehicle_id, service_date);
