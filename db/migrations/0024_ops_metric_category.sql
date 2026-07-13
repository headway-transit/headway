-- 0024: the OPERATIONS / NTD honesty boundary (handoff 0014, design point 1).
--
-- Headway now computes OPERATIONS analytics (on-time performance, headway
-- adherence — services/calc/OPS_DEFINITIONS.md) alongside the NTD regulatory
-- figures. Operations metrics are NOT regulatory figures: they must never
-- appear in the certification cockpit, the MR-20/S&S preview packages, or
-- the public certified-figures endpoint. This migration makes that boundary
-- STRUCTURAL, not procedural:
--
-- 1) computed.metric_values.category — 'ntd' (default; every pre-existing
--    row is an NTD-pipeline figure) or 'ops'. The calc library derives the
--    category from the calc registry (headway_calc.persist), never from a
--    caller argument, so an ops calc cannot be persisted mislabeled.
--
-- 2) metric_values_ops_never_certified — a CHECK making the state
--    "category='ops' AND certification_status='certified'" IMPOSSIBLE to
--    represent. Certification is the gate to the public certified endpoint
--    and the legally-attested record; an operations figure can therefore
--    never reach them, no matter what code path tries. (The API's certify
--    route additionally refuses ops ids with a plain-language 409, and the
--    certified/MR-20 read paths carry hard "category='ntd'" WHERE clauses —
--    defense in depth on top of this constraint, not instead of it.)
--
-- 3) dq.issues.category — ops calc findings (e.g. an OTP cadence refusal)
--    are real findings with owners, but they are NOT gaps in any certified
--    figure: the certification blocking-issue gate counts ONLY
--    category='ntd' issues. Without this, an operations-metric refusal
--    would freeze federal certification — ops contaminating the regulatory
--    workflow in the opposite direction. Default 'ntd' keeps every existing
--    row and every existing writer (transform, AI, humans, NTD calcs)
--    exactly as strict as before.
--
-- 4) The two ops policy knobs (the configurable on-time window) join
--    app.settings with the same audited-surface rules as the calc knobs
--    (migration 0014: seeded here, never client-creatable). Their basis is
--    quoted in services/calc/OPS_DEFINITIONS.md — the ops analogue of
--    REGULATORY_TRACKER.md — not in the FTA tracker, because they are not
--    regulatory numbers.

ALTER TABLE computed.metric_values
    ADD COLUMN category TEXT NOT NULL DEFAULT 'ntd'
        CONSTRAINT metric_values_category_vocabulary
        CHECK (category IN ('ntd', 'ops'));

ALTER TABLE computed.metric_values
    ADD CONSTRAINT metric_values_ops_never_certified
    CHECK (NOT (category = 'ops' AND certification_status = 'certified'));

ALTER TABLE dq.issues
    ADD COLUMN category TEXT NOT NULL DEFAULT 'ntd'
        CONSTRAINT issues_category_vocabulary
        CHECK (category IN ('ntd', 'ops'));

-- The configurable OTP window (handoff 0014, design point 4). Basis:
-- TCQSM 3rd Edition (TCRP Report 165), on-time definition quoted and
-- page-cited in services/calc/OPS_DEFINITIONS.md ("Verified — on-time
-- performance"); verify against the current published TCQSM before treating
-- the default as more than the industry-typical window.
INSERT INTO app.settings (setting_key, setting_value, value_type, description, updated_by) VALUES
('otp_early_tolerance_seconds', '60', 'integer', 'OPERATIONS metric knob (never used by any NTD figure): how many seconds BEFORE the scheduled time a stop passage may occur and still count as on time in otp_v0. The 60 s default is the TCQSM 3rd Edition typical fixed-route window ("no more than 1 minute early"), quoted with page citation in services/calc/OPS_DEFINITIONS.md; per-agency configurable — many agencies define their own window.', 'migration-0024'),
('otp_late_tolerance_seconds', '300', 'integer', 'OPERATIONS metric knob (never used by any NTD figure): how many seconds AFTER the scheduled time a stop passage may occur and still count as on time in otp_v0. The 300 s default is the TCQSM 3rd Edition typical fixed-route window ("no more than 5 minutes late"), quoted with page citation in services/calc/OPS_DEFINITIONS.md; per-agency configurable.', 'migration-0024');
