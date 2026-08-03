-- 0044: service_day_timezone — the agency's local timezone, as a SETTING.
--
-- ADR-0015: configuration an operator must change after installation lives in
-- app.settings, not in a dotfile reachable only over SSH. This is the worked
-- example that prompted the ADR.
--
-- WHAT WENT WRONG WITHOUT IT (2026-08-03, partner agency): the transform
-- service requires a declared timezone before it will normalize fleet
-- telematics, because a service date is a LOCAL WALL DATE and must never be
-- derived from a guessed zone. It refuses loudly rather than guess — correct.
-- But the variable it reads was documented in a service README and plumbed
-- nowhere, so every telematics page was refused for three days and the only
-- evidence was one WARNING line in a container log. The agency's ITS manager
-- is an expert in his data and not a systems administrator; there was no path
-- he could have taken.
--
-- WHY EMPTY IS THE DEFAULT, AND STAYS THE DEFAULT. An unset zone must keep
-- refusing. Seeding a plausible-looking default (UTC, or the server's zone)
-- would silently date a federal figure to the wrong day — the failure mode
-- the refusal exists to prevent. An installation that has not declared its
-- zone is not misconfigured; it is undeclared, and Headway says so.
--
-- WHY THIS IS NOT MERELY A PREFERENCE. The service-day timezone helps define
-- what a DAY is, and therefore what every reported figure covers. Changing it
-- means yesterday's figures spanned a different twenty-four hours than
-- tomorrow's. app.settings records updated_by and updated_at, so the change is
-- attributable — which a .env edit over SSH never was. Making already-computed
-- figures carry the zone they were computed under is the remaining half, and
-- is deliberately NOT in this migration: canonical.vehicle_telematics_days
-- already stores window_start/window_end as instants for exactly that reason,
-- and extending it to computed.metric_values is its own change with its own
-- backfill question.
--
-- Additive only. No existing column or row is touched.

INSERT INTO app.settings (setting_key, setting_value, value_type, description, updated_by)
VALUES (
    'service_day_timezone',
    '',
    'text',
    'Your agency''s local timezone, as an IANA name — for example '
    || 'America/Los_Angeles, America/Denver, America/Chicago or '
    || 'America/New_York. A service date is a local wall date, so Headway '
    || 'needs to know which local day a vehicle''s activity belongs to. '
    || 'Leave it blank and vehicle-telematics data is refused rather than '
    || 'dated to a guessed day — that refusal is deliberate, not a fault. '
    || 'CHANGING THIS CHANGES WHAT A DAY MEANS: figures computed before the '
    || 'change covered a different twenty-four hours than figures computed '
    || 'after it. Set it once, when the installation is set up, and change it '
    || 'only if the agency genuinely moves timezone.',
    'migration-0044'
)
ON CONFLICT (setting_key) DO NOTHING;
