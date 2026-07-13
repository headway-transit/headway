-- 0026: canonical.agencies — GTFS agency.txt (handoff 0014, design point 4).
--
-- WHY: otp_v0 must anchor GTFS schedule times (integer seconds after "noon
-- minus 12 h" of the service day, LOCAL to the agency) against observed UTC
-- passage times. The agency's timezone is therefore load-bearing — and it
-- is FEED-DECLARED: agency.txt/agency_timezone is required by the GTFS
-- Schedule Reference (gtfs.org — verify against the current published
-- spec), and the spec requires every agency in one feed to share the same
-- timezone. Reading it from the feed keeps provenance intact; a timezone
-- knob guessed in configuration would not be provenance. otp_v0 REFUSES
-- (blocking finding) when this table is empty or holds conflicting
-- timezones — a schedule anchor is never guessed.
--
-- Lineage: like canonical.routes/trips/stops, one lineage.edges row per
-- normalized row (transform normalize_gtfs_static), anchored to the static
-- feed's content-addressed raw record; rows are upserted (a newer feed
-- supersedes) and the edge history preserves every feed that produced them.
--
-- agency_id is OPTIONAL in GTFS for single-agency feeds: an omitted
-- agency_id is stored as '' (the feed's own representation — an id is never
-- fabricated), documented here and in the normalizer.

CREATE TABLE canonical.agencies (
    agency_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    -- IANA timezone name (e.g. 'America/New_York'), verbatim from
    -- agency_timezone. NOT NULL: a row without a timezone is quarantined by
    -- the transform (never guessed), because the timezone is the column
    -- this table exists for.
    timezone  TEXT NOT NULL
);
