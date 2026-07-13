-- 0020: sampling.plans + sampling.draws + sampling.measurements — NTD
-- ready-to-use sampling plan support v0 (handoff 0012).
--
-- Sampling records are the agency's FEDERAL EVIDENCE that its PMT estimate
-- followed an FTA-approved method (FTA NTD Sampling Manual, March 31, 2009;
-- named current by the 2026 NTD Policy Manual p. 150 — quotes in
-- services/calc/REGULATORY_TRACKER.md, "Verified — NTD Sampling Manual" +
-- "Sampling plan tables — implementation quotes"). The 2026 manual requires
-- sampling documentation be retained at least 3 years (p. 150); Headway
-- keeps these rows indefinitely and makes them structurally append-only:
-- corrections SUPERSEDE, history is never rewritten.
--
-- Required sample sizes are computed by the versioned calc selector
-- (headway_calc.sampling, sampling_v0 — verbatim Table 43.01–43.07 cells);
-- the API stores what the selector returned and records its version. No
-- regulatory number originates in the API or in this schema.

CREATE SCHEMA IF NOT EXISTS sampling;

CREATE TABLE sampling.plans (
    plan_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The NTD report year this plan samples for (§41.03 reuse rules are
    -- guidance strings in the API, never silent logic here).
    report_year         INTEGER NOT NULL CHECK (report_year BETWEEN 2000 AND 2100),
    -- NTD mode code the ready-to-use plans cover (§41.05 / Table 41.01):
    -- DR, VP (commuter vanpool), MB/TB (bus), CR, LR/HR/MR/AG (other rail).
    mode                TEXT NOT NULL CHECK (mode IN
        ('DR', 'VP', 'MB', 'TB', 'CR', 'LR', 'HR', 'MR', 'AG')),
    -- Sampling is per mode AND type of service (2026 Policy Manual p. 149:
    -- the 95%/±10% floor applies per mode and TOS).
    type_of_service     TEXT NOT NULL,
    -- Unit of sampling and measurement (Table 41.01; unit-per-mode validity
    -- is enforced by the calc selector at plan creation).
    unit                TEXT NOT NULL CHECK (unit IN
        ('vehicle_days', 'one_way_trips', 'round_trips',
         'one_way_car_trips', 'one_way_train_trips')),
    -- §41.07(c) efficiency options. v0 creates 'aptl' (without route
    -- grouping) and 'base' plans; the grouped-APTL option requires
    -- per-group sampling/estimation (§43.05(a)) and is deferred — the API
    -- refuses it in plain language, so no CHECK slot for it here.
    efficiency_option   TEXT NOT NULL CHECK (efficiency_option IN ('aptl', 'base')),
    -- §41.07(d): "quarterly, monthly, or weekly".
    frequency           TEXT NOT NULL CHECK (frequency IN
        ('quarterly', 'monthly', 'weekly')),
    -- BOTH required sizes are verbatim table cells returned by the calc
    -- selector (never derived from each other — Table 43.07 itself prints
    -- one weekly column where per-period x 52 <> annual, kept as printed).
    required_per_period INTEGER NOT NULL CHECK (required_per_period > 0),
    required_annual     INTEGER NOT NULL CHECK (required_annual > 0),
    -- The verbatim cell citation (table, column, both numbers, source pin)
    -- exactly as the selector produced it.
    table_citation      TEXT NOT NULL,
    -- e.g. 'sampling_v0 0.1.0' — which selector version produced the sizes.
    selector_version    TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'created' CHECK (status IN
        ('created', 'active')),
    created_by          TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX plans_report_year_idx ON sampling.plans (report_year);
CREATE INDEX plans_mode_idx ON sampling.plans (mode);

-- Structural append-only guard for plans: DELETE always rejected; the ONLY
-- permitted UPDATE is the one lifecycle transition created -> active (set
-- when the first sample is drawn), with every other column byte-identical.
CREATE FUNCTION sampling.enforce_plans_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'sampling.plans is append-only: DELETE rejected. '
            'Sampling documentation must be retained (2026 NTD Policy '
            'Manual p. 150: at least 3 years); Headway never removes it.';
    END IF;
    IF NOT (OLD.status = 'created' AND NEW.status = 'active')
       OR (to_jsonb(NEW) - 'status') IS DISTINCT FROM
          (to_jsonb(OLD) - 'status') THEN
        RAISE EXCEPTION 'sampling.plans is append-only: the only permitted '
            'UPDATE is the created -> active transition when the first '
            'sample is drawn, with every other column unchanged. Create a '
            'new plan instead of editing this one.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER plans_append_only
    BEFORE UPDATE OR DELETE ON sampling.plans
    FOR EACH ROW
    EXECUTE FUNCTION sampling.enforce_plans_append_only();

-- One row per random-selection act (§63.01/§63.07: the service-unit list is
-- per period at the plan's frequency; the draw selects that period's sample
-- from it). STRICTLY append-only: a draw is a historical act — it is never
-- edited, superseded, or deleted. The seed + frame reproduce the selection
-- bit-for-bit through the versioned drawer (headway_calc.sampling).
CREATE TABLE sampling.draws (
    draw_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id          UUID NOT NULL REFERENCES sampling.plans (plan_id),
    -- The period this draw covers, agency-labeled (e.g. '2026-Q1',
    -- '2026-01', '2026-W14'). One draw per plan period.
    period_label     TEXT NOT NULL CHECK (length(period_label) > 0),
    -- The §63.07 list of ALL service units expected to operate in the
    -- period (the sampling frame) — stored in full: seed + frame is the
    -- reproducibility evidence.
    service_units    TEXT[] NOT NULL,
    -- The selected units IN DRAW ORDER (the ride-checker worksheet).
    selected_units   TEXT[] NOT NULL,
    -- Random seed, generated by a CSPRNG in the API and RECORDED here for
    -- audit/reproducibility (§63.03(b): the method must be random and
    -- without replacement; the drawer's procedure is documented in
    -- headway_calc.sampling.DRAW_METHOD).
    seed             TEXT NOT NULL CHECK (length(seed) > 0),
    -- Units drawn BEYOND the required per-period size. Oversampling is
    -- permitted only when the extra units are randomly selected (2026 NTD
    -- Policy Manual p. 149); the drawer's prefix-consistent random order
    -- makes the extension random by construction, and this column flags it.
    oversample_units INTEGER NOT NULL DEFAULT 0 CHECK (oversample_units >= 0),
    -- e.g. 'sampling_v0 0.1.0' — which drawer version performed the draw.
    drawer_version   TEXT NOT NULL,
    drawn_by         TEXT NOT NULL,
    drawn_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT draws_one_per_plan_period UNIQUE (plan_id, period_label)
);

CREATE INDEX draws_plan_id_idx ON sampling.draws (plan_id);

CREATE FUNCTION sampling.reject_draw_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'sampling.draws is append-only: % rejected. A draw is '
        'a historical random-selection act; it is never edited or removed. '
        'If a draw was made in error, document it and draw the next period '
        'correctly — the record must show what actually happened.', TG_OP;
END;
$$;

CREATE TRIGGER draws_append_only
    BEFORE UPDATE OR DELETE ON sampling.draws
    FOR EACH STATEMENT
    EXECUTE FUNCTION sampling.reject_draw_mutation();

-- One manually entered ride-check observation per selected service unit:
-- the unit's observed UPT and PMT totals (§41.07(c)(2): the APTL option
-- samples average passenger trip length; the base option samples both).
-- Corrections are append-only via the supersede pattern (migration 0017
-- precedent): a corrected observation is a NEW row; the original points at
-- its replacement and never changes again.
CREATE TABLE sampling.measurements (
    measurement_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id          UUID NOT NULL REFERENCES sampling.plans (plan_id),
    -- Must be one of the plan's drawn selected_units (enforced by the API
    -- at entry — an array membership FK is not expressible here).
    unit_id          TEXT NOT NULL,
    observed_upt     INTEGER NOT NULL CHECK (observed_upt >= 0),
    -- NUMERIC, never float (repo non-negotiable). Whole-sample APTL is
    -- computed by the calc estimator as ratio of TOTALS (§83.05(a)); a
    -- per-unit ratio is never stored or computed anywhere (§83.05(b) ban).
    observed_pmt     NUMERIC NOT NULL CHECK (observed_pmt >= 0),
    -- Required only for by-type-of-service-day estimates (§83.01(b)).
    service_day_type TEXT CHECK (service_day_type IN
        ('Weekday', 'Saturday', 'Sunday')),
    -- The service date the ride check was performed (optional context).
    service_date     DATE,
    -- Where the observation came from. v0 is manual ride-check entry; the
    -- caveat travels with every estimate built on these rows.
    data_source      TEXT NOT NULL DEFAULT 'manual_ride_check',
    notes            TEXT,
    entered_by       TEXT NOT NULL,
    entered_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- DEFERRABLE: a correction must (1) mark the original superseded and
    -- (2) insert its replacement in ONE transaction, and the one-active-
    -- per-unit index below is checked per statement — so the link is
    -- written FIRST (pointing at the replacement's not-yet-inserted id,
    -- generated by the API) and the FK is validated at commit. Found by
    -- the live walkthrough 2026-07-12: insert-before-link trips the
    -- unique index.
    superseded_by    UUID REFERENCES sampling.measurements (measurement_id)
                     DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT measurements_no_self_supersede CHECK (superseded_by <> measurement_id)
);

CREATE INDEX measurements_plan_id_idx ON sampling.measurements (plan_id);

-- Exactly one ACTIVE (unsuperseded) observation per plan unit.
CREATE UNIQUE INDEX measurements_one_active_per_unit
    ON sampling.measurements (plan_id, unit_id)
    WHERE superseded_by IS NULL;

-- Structural append-only guard (the migration-0017 pattern): DELETE always
-- rejected; the ONLY permitted UPDATE is setting superseded_by exactly once
-- (NULL -> a real measurement), with every other column byte-identical.
CREATE FUNCTION sampling.enforce_measurements_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'sampling.measurements is append-only: DELETE '
            'rejected. Corrections supersede (POST /sampling/measurements/'
            '{id}/supersede); originals are never removed.';
    END IF;
    IF OLD.superseded_by IS NOT NULL THEN
        RAISE EXCEPTION 'sampling.measurements is append-only: measurement '
            '% is already superseded and can never change again. Correct '
            'its replacement instead.', OLD.measurement_id;
    END IF;
    IF NEW.superseded_by IS NULL
       OR (to_jsonb(NEW) - 'superseded_by') IS DISTINCT FROM
          (to_jsonb(OLD) - 'superseded_by') THEN
        RAISE EXCEPTION 'sampling.measurements is append-only: the only '
            'permitted UPDATE is setting superseded_by once, with every '
            'other column unchanged. Enter a correction as a new '
            'measurement instead.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER measurements_append_only
    BEFORE UPDATE OR DELETE ON sampling.measurements
    FOR EACH ROW
    EXECUTE FUNCTION sampling.enforce_measurements_append_only();
