-- 0034: canonical.vehicle_telematics_days — fleet telematics vehicle-day
-- measurement series (handoff 0028). One row per
-- (vehicle, service date, measure, basis, source record), normalized from
-- raw.telematics.vehicle_stats against the vendor-neutral wire contract
-- contracts/fleet-telematics.v0.schema.json (+ .md).
--
-- ============================ THE HONESTY WALL ============================
-- TELEMATICS DISTANCE IS NOT REVENUE MILES. ENGINE/DUTY TIME IS NOT REVENUE
-- HOURS. An odometer delta includes deadhead, personal use, maintenance
-- travel and everything else the vehicle did; an engine-hour meter counts
-- idling in a car park. NOTHING in services/calc/ reads this table, and no
-- NTD figure (VRM, VRH, VP-mode) is derived from it in this wave. The path
-- from these measurements to a reportable vanpool figure requires the FTA
-- vanpool rules quoted verbatim into services/calc/REGULATORY_TRACKER.md by
-- the NTD Compliance role, plus an agency-declared statement of which
-- vehicle-days were revenue service — a separate, compliance-gated wave
-- (handoff 0028, Open Questions). This table holds MEASURED VEHICLE
-- MOVEMENT, not a reportable figure.
-- =========================================================================
--
-- WHY ONE ROW PER (measure, basis) INSTEAD OF ONE ROW PER VEHICLE-DAY:
-- measurement bases must be kept DISTINCT and never silently substituted
-- for one another. A van with both an ECU odometer and a GPS distance
-- counter produces TWO rows for the same day, so "fill the missing ECU
-- figure with the GPS one" is not expressible — it would be writing a
-- different row's basis, which the unique key forbids. Disagreement between
-- bases stays visible instead of being averaged away (Shared Constraint 7).

CREATE TABLE canonical.vehicle_telematics_days (
    -- Service-day boundaries in the operator's DECLARED timezone, carried
    -- as instants so the local day is auditable after the fact. The
    -- hypertable time dimension. Day length is whatever the declared zone
    -- says (23 or 25 hours across a DST transition) — never assumed 24.
    window_start           TIMESTAMPTZ NOT NULL,
    window_end             TIMESTAMPTZ NOT NULL,
    CONSTRAINT vtd_window_is_forward CHECK (window_end > window_start),
    -- The local wall date the window represents. Derived from the DECLARED
    -- timezone only; a deployment with no declared zone writes zero rows
    -- (the transform fails closed rather than guessing a zone).
    service_date           DATE NOT NULL,

    -- The telematics system's own vehicle identifier, verbatim. Headway
    -- never re-keys a vendor id; matching it to the agency fleet roster is
    -- a separate, human-confirmed step.
    vehicle_id             TEXT NOT NULL,
    vehicle_label          TEXT,

    -- WHAT was measured. 'distance' = all vehicle movement (revenue,
    -- deadhead, personal, maintenance). 'engine_time' = engine runtime.
    measure                TEXT NOT NULL
        CHECK (measure IN ('distance', 'engine_time')),
    -- HOW it was measured. Kept distinct, never substituted.
    --   ecu_odometer          the vehicle's own odometer, off the diagnostic bus
    --   gps_odometer          odometer maintained from GPS, seeded by a human reading
    --   gps_distance          distance accumulated by the GATEWAY since installation
    --   ecu_engine_time       engine runtime off the diagnostic bus
    --   estimated_engine_time gateway-estimated runtime — an estimate, labelled as one
    --   duty_status_time      driver ELD/HOS duty time (a DRIVER's status, not the
    --                         vehicle's revenue time). Reserved: nothing writes it
    --                         today (handoff 0028 leaves HOS unimplemented).
    basis                  TEXT NOT NULL
        CHECK (basis IN ('ecu_odometer', 'gps_odometer', 'gps_distance',
                         'ecu_engine_time', 'estimated_engine_time',
                         'duty_status_time')),
    -- A distance basis can never appear on an engine-time row, or vice
    -- versa: the substitution the honesty wall forbids is made structurally
    -- impossible rather than merely discouraged.
    CONSTRAINT vtd_basis_matches_measure CHECK (
        (measure = 'distance'
         AND basis IN ('ecu_odometer', 'gps_odometer', 'gps_distance'))
        OR
        (measure = 'engine_time'
         AND basis IN ('ecu_engine_time', 'estimated_engine_time',
                       'duty_status_time'))
    ),
    -- SI on the wire, always. Miles/hours are an exact-decimal conversion
    -- downstream, never stored here and never in binary float.
    unit                   TEXT NOT NULL CHECK (unit IN ('meters', 'seconds')),
    CONSTRAINT vtd_unit_matches_measure CHECK (
        (measure = 'distance' AND unit = 'meters')
        OR (measure = 'engine_time' AND unit = 'seconds')
    ),
    -- How the source expresses the quantity: a running total whose
    -- endpoints are both recorded, or an amount the source already
    -- attributed to the period. Neither is converted into the other.
    reading_kind           TEXT NOT NULL
        CHECK (reading_kind IN ('cumulative_counter', 'period_total')),

    -- The measured amount over the window, in `unit`. NUMERIC, never float
    -- (repo non-negotiable). NULL = UNMEASURED, preserved as NULL — never
    -- coalesced to 0, never interpolated, never extrapolated to the window
    -- boundaries. NULL legitimately occurs when the day holds fewer than
    -- two readings, or when a cumulative counter went backwards (a reset or
    -- a replaced gateway): the endpoints are still recorded and a dq.issues
    -- row is raised, but no number is invented.
    value                  NUMERIC CHECK (value >= 0),

    -- The two readings the value was measured between, with their times.
    -- These are NOT the start and end of the day: movement before the first
    -- reading or after the last is not included and is not estimated.
    first_reading_at       TIMESTAMPTZ,
    first_reading_value    NUMERIC CHECK (first_reading_value >= 0),
    last_reading_at        TIMESTAMPTZ,
    last_reading_value     NUMERIC CHECK (last_reading_value >= 0),
    CONSTRAINT vtd_first_reading_is_paired CHECK (
        (first_reading_at IS NULL) = (first_reading_value IS NULL)),
    CONSTRAINT vtd_last_reading_is_paired CHECK (
        (last_reading_at IS NULL) = (last_reading_value IS NULL)),
    CONSTRAINT vtd_readings_in_order CHECK (
        first_reading_at IS NULL OR last_reading_at IS NULL
        OR last_reading_at >= first_reading_at),
    -- Readings belong to the window they are filed under.
    CONSTRAINT vtd_first_reading_inside_window CHECK (
        first_reading_at IS NULL
        OR (first_reading_at >= window_start AND first_reading_at < window_end)),
    CONSTRAINT vtd_last_reading_inside_window CHECK (
        last_reading_at IS NULL
        OR (last_reading_at >= window_start AND last_reading_at < window_end)),
    -- A period_total has no endpoints to record; carrying some would imply a
    -- subtraction that never happened.
    CONSTRAINT vtd_period_total_has_no_endpoints CHECK (
        reading_kind <> 'period_total'
        OR (first_reading_at IS NULL AND last_reading_at IS NULL)),
    -- THE ANTI-FABRICATION CONSTRAINT: for a cumulative counter, a stored
    -- value must be EXACTLY the difference of the two stored readings. The
    -- database itself refuses a number that is not the arithmetic of two
    -- recorded measurements — there is nowhere for an estimate, an
    -- interpolation or a model output to hide.
    CONSTRAINT vtd_value_is_the_recorded_difference CHECK (
        reading_kind <> 'cumulative_counter'
        OR value IS NULL
        OR (first_reading_value IS NOT NULL
            AND last_reading_value IS NOT NULL
            AND value = last_reading_value - first_reading_value)),

    -- How many readings of this basis landed in the window. 0 or 1 still
    -- produces a row: the absence is stated, not inferred from a missing row.
    sample_count           INTEGER NOT NULL CHECK (sample_count >= 0),
    -- The honesty field: the largest interval between consecutive readings,
    -- i.e. how blind the measurement is between its endpoints. NULL when
    -- fewer than two samples exist. Headway never interpolates across it.
    max_sample_gap_seconds INTEGER CHECK (max_sample_gap_seconds >= 0),
    CONSTRAINT vtd_gap_needs_two_samples CHECK (
        sample_count >= 2 OR max_sample_gap_seconds IS NULL),

    -- The envelope's fetched_at: when this page was pulled from the vendor.
    -- A service day re-polled later (late-arriving samples) lands a NEW row
    -- from a NEW content-addressed record; polled_at makes "which reading of
    -- this day is the most recent" deterministic instead of a guess.
    polled_at              TIMESTAMPTZ NOT NULL,

    -- Envelope source: the REGISTERED telematics label ('samsara' for a real
    -- account, 'samsara_simulated' for synthetic data). Carried verbatim so
    -- simulated data stays permanently distinguishable in provenance
    -- (handoff 0005 binding rule; unregistered labels are refused
    -- fail-closed by the transform, handoff 0015 rule).
    source                 TEXT NOT NULL,
    source_record_id       TEXT NOT NULL REFERENCES raw.records (record_id)
);

SELECT create_hypertable('canonical.vehicle_telematics_days', 'window_start');

-- TimescaleDB requires unique indexes to include the partition column.
-- Including source_record_id follows the migration-0012/0021 precedent: an
-- at-least-once replay of the SAME content-addressed record is a no-op via
-- the transform's ON CONFLICT DO NOTHING, while a genuinely different
-- record (a re-poll that picked up late samples) lands as a visible
-- restatement rather than silently overwriting history.
CREATE UNIQUE INDEX vehicle_telematics_days_key
    ON canonical.vehicle_telematics_days
       (vehicle_id, window_start, measure, basis, source_record_id);

-- Vehicle-day lookups ("show me this van's July") and per-day sweeps.
CREATE INDEX vehicle_telematics_days_vehicle_service_date_idx
    ON canonical.vehicle_telematics_days (vehicle_id, service_date);
CREATE INDEX vehicle_telematics_days_service_date_basis_idx
    ON canonical.vehicle_telematics_days (service_date, measure, basis);
