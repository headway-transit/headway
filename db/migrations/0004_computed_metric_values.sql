-- 0004: computed.metric_values — the ONLY place reported figures land,
-- written exclusively by the calc library (never by AI, never ad hoc).

CREATE TABLE computed.metric_values (
    metric_value_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric               TEXT NOT NULL,  -- v0: 'vrm', 'vrh'
    unit                 TEXT NOT NULL,  -- 'miles', 'hours'
    period_start         DATE NOT NULL,
    period_end           DATE NOT NULL,
    scope                TEXT NOT NULL DEFAULT 'agency',
    value                NUMERIC NOT NULL,  -- NUMERIC, never float: reported figures must be exact
    calc_name            TEXT NOT NULL,
    calc_version         TEXT NOT NULL,
    computed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    certification_status TEXT NOT NULL DEFAULT 'uncertified'
        CHECK (certification_status IN ('uncertified', 'certified'))
);
