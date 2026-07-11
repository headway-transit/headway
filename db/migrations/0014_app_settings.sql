-- 0014: per-agency settings — the ONE audited place an agency sets calc
-- policy. NOTE: like auth.users (0009) and the machine tables (0013), this
-- table is NOT part of handoff 0001's schema contract; it is added under the
-- per-agency-configuration follow-up named in handoff 0002's Open Questions
-- ("ultimately per-agency configuration … then Backend for config surface")
-- and REGULATORY_TRACKER.md's open items, never by silent extension.
--
-- Keys are SEEDED here, never client-creatable: the settings surface exposes
-- exactly the policy knobs the calc library defines, so an unknown key is a
-- 404 at the API, not a new row. Values are TEXT and validated against
-- value_type at write time (decimal values are parsed with Decimal — floating
-- point never touches a policy number, the same rule as reported figures).
--
-- IMPORTANT (documented limitation, handoff 0002 Response): the calc runner
-- does NOT yet read this table — its explicit CLI flags still govern every
-- run. Wiring runner-reads-settings is the follow-up increment; this table
-- exists now so agencies have one audited place to set policy.

CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.settings (
    setting_key   TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    value_type    TEXT NOT NULL CHECK (value_type IN ('decimal', 'integer', 'text')),
    description   TEXT NOT NULL,   -- plain language + the basis of the default
    updated_by    TEXT NOT NULL,   -- who last set it (audit attribution)
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The four calc policy knobs (defaults exactly matching the calc library's
-- documented defaults; each basis cited from REGULATORY_TRACKER.md — no
-- regulatory number enters from memory).

INSERT INTO app.settings (setting_key, setting_value, value_type, description, updated_by) VALUES
('coverage_threshold', '0.95', 'decimal', 'The share of clean telemetry groups a calculation run must reach before its figure can be persisted; below this the run refuses with one blocking coverage_below_threshold finding. The 0.95 default is an ENGINEERING PLACEHOLDER chosen for calc 0.2.0''s certifiability line, NOT an FTA number (REGULATORY_TRACKER.md); FTA completeness/sampling expectations must be verified against the current NTD Policy Manual before it is treated as more than a placeholder. For reference, the measured MBTA trip-level structural coverage is ~0.914 - hence this per-agency setting.', 'migration-0014'),
('gap_threshold_seconds', '300', 'integer', 'Maximum seconds between consecutive telemetry positions inside one trip before the gap excludes that trip from the figure (calc gap policy, handoff 0002). Engineering default; per-agency configurable.', 'migration-0014'),
('layover_max_seconds', '1800', 'integer', 'Maximum seconds of between-trip time within one vehicle block counted as layover in Vehicle Revenue Hours. Data-informed (measured MBTA inter-trip distribution, p50=30s/p99=7124s) and aligned with 2026 NTD Policy Manual Exhibit 35, which excludes out-of-service parking from revenue hours (REGULATORY_TRACKER.md). Per-agency configurable.', 'migration-0014'),
('missing_trip_threshold', '0.02', 'decimal', 'Maximum share of operated trips without passenger-count data before UPT refuses. At or under this share the figure is factored up as the FTA prescribes; above it a qualified statistician must approve the method. This 0.02 is a REAL FTA threshold: 2026 NTD Policy Manual p. 146 (quoted in REGULATORY_TRACKER.md).', 'migration-0014');
