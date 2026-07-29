-- 0036: resolving a vendor's own trip identifiers against the agency's
-- schedule (handoff 0031).
--
-- WHY
-- ---
-- The first agency's APC export names a trip the way its schedulers do —
-- "route – pattern – start time" — while its GTFS trip_id is an opaque id.
-- The two never join, so passenger counts do not attach to operated trips
-- and every UPT figure over that data is blocked. Resolving one to the other
-- needs three things canonical did not have:
--
--   1. a way to know WHICH services run on a given day. canonical.trips
--      carries service_id and nothing could interpret it: calendar.txt and
--      calendar_dates.txt were parsed by nobody (noted in migration 0031's
--      header). Without them the join key loses its service component, and
--      that is not a rounding error — measured on the first agency's live
--      feed (2,704 trips, retrieved 2026-07-29), the key
--      (route short name, start time, direction) collides on 823 keys
--      covering 1,816 trips. With service it collides on 1 key covering 2.
--
--   2. a way to check a stop identifier that is NOT the stop_id. The
--      export identifies stops by the code printed on the sign; GTFS calls
--      that stop_code. In this agency's feed stop_id happens to equal
--      stop_code on all 851 stops — a coincidence that must never become an
--      assumption, so stop_code is stored as its own column.
--
--   3. somewhere to keep the vendor's identifier AFTER resolution. This is
--      the part that is not negotiable: the operational trip name is the
--      agency's own vocabulary and the audit path back into their system.
--      A resolved row replaces trip_id with the canonical trip — it must
--      NOT thereby erase what the vendor said.
--
-- ADDITIVE, AND NOTHING IS BACKFILLED
-- -----------------------------------
-- Every column and table here is new or nullable. Rows written before this
-- migration keep NULL in the new passenger-event columns and must read
-- exactly as they read yesterday. NULL in trip_resolution means "resolution
-- was not attempted for this row" — no configuration existed, or the
-- configuration is not yet confirmed — and that is the normal case, not an
-- error. Re-resolving rows ingested before a configuration existed is a
-- repair path this migration deliberately does not attempt (handoff 0031,
-- open question): resolution happens at normalization time and its outcome
-- is part of the row's lineage, so changing it later is a re-run, not an
-- UPDATE.

-- --- GTFS service calendar ---------------------------------------------
-- calendar.txt is CONDITIONALLY REQUIRED by the GTFS Schedule Reference
-- ("Required unless all dates of service are defined in calendar_dates.txt",
-- gtfs.org, verified 2026-07-29) — a feed may legitimately carry only
-- calendar_dates.txt, so neither table is treated as mandatory by the
-- normalizer.
--
-- Stored AS THE FEED STATES IT rather than expanded into one row per
-- service day: the expansion is derivable, the source rows are not, and a
-- feed spanning a year with many services expands into hundreds of
-- thousands of rows that say nothing new. The resolver applies the GTFS
-- rules (weekday flags within the inclusive start/end interval, then
-- exceptions) at read time.

CREATE TABLE canonical.service_calendars (
    service_id TEXT PRIMARY KEY,
    -- 1 = service is available on that weekday for every such day in the
    -- interval, 0 = not available (GTFS Schedule Reference, calendar.txt).
    monday     BOOLEAN NOT NULL,
    tuesday    BOOLEAN NOT NULL,
    wednesday  BOOLEAN NOT NULL,
    thursday   BOOLEAN NOT NULL,
    friday     BOOLEAN NOT NULL,
    saturday   BOOLEAN NOT NULL,
    sunday     BOOLEAN NOT NULL,
    -- Both bounds INCLUSIVE per the spec ("This service day is included in
    -- the interval").
    start_date DATE NOT NULL,
    end_date   DATE NOT NULL
);

COMMENT ON TABLE canonical.service_calendars IS
    'GTFS calendar.txt as the feed states it: which weekdays a service_id '
    'runs, within an inclusive date interval. Upserted by '
    'normalize_gtfs_static; provenance is the lineage.edges row per service, '
    'not a column here (a newer feed supersedes, and the edge history '
    'preserves every feed that produced the row).';

CREATE TABLE canonical.service_calendar_dates (
    service_id     TEXT NOT NULL,
    -- The service DAY the exception applies to (GTFS calendar_dates.date).
    service_date   DATE NOT NULL,
    -- 1 = service added for this date, 2 = service removed for this date
    -- (GTFS Schedule Reference, calendar_dates.txt, verified 2026-07-29).
    -- Stored as the feed's own integer, not a decoded boolean: an
    -- unrecognised value must be visible as itself and refused loudly, not
    -- silently folded into "removed".
    exception_type SMALLINT NOT NULL,
    PRIMARY KEY (service_id, service_date)
);

COMMENT ON TABLE canonical.service_calendar_dates IS
    'GTFS calendar_dates.txt: per-date exceptions to canonical.'
    'service_calendars (exception_type 1 = added, 2 = removed). A feed may '
    'define ALL of its service here and carry no calendar.txt at all.';

-- --- stop_code ----------------------------------------------------------

ALTER TABLE canonical.stops
    ADD COLUMN stop_code TEXT;

COMMENT ON COLUMN canonical.stops.stop_code IS
    'GTFS stops.txt stop_code: "Short text or a number that identifies the '
    'location for riders ... often used in phone-based transit information '
    'systems or printed on signage" (GTFS Schedule Reference, gtfs.org, '
    'verified 2026-07-29). OPTIONAL in GTFS and therefore NULLABLE here; '
    'NULL means the feed carried no code, never that the code equals the '
    'stop_id. Not unique by declaration — the spec does not require it.';

-- Vendor exports identify stops by the printed code, so the resolver looks
-- up by code. Not unique: a feed may repeat a code, and the resolver reports
-- that as ambiguity rather than picking a stop.
CREATE INDEX stops_stop_code_idx ON canonical.stops (stop_code)
    WHERE stop_code IS NOT NULL;

-- --- the resolution outcome, on the row ---------------------------------

ALTER TABLE canonical.passenger_events
    ADD COLUMN vendor_trip_ref TEXT,
    ADD COLUMN trip_resolution TEXT;

ALTER TABLE canonical.passenger_events
    ADD CONSTRAINT passenger_events_trip_resolution_check
    CHECK (trip_resolution IN ('resolved', 'ambiguous', 'unmatched'));

COMMENT ON COLUMN canonical.passenger_events.vendor_trip_ref IS
    'The trip identifier the VENDOR EXPORT stated, verbatim, preserved '
    'whenever trip resolution ran (handoff 0031). It is the agency''s own '
    'operational vocabulary and the audit path back into their system, so a '
    'resolved row keeps it alongside the canonical trip_id — resolution '
    'never overwrites what the source said. NULL when no resolution was '
    'attempted; trip_id then still carries the vendor''s value, exactly as '
    'before this migration.';

COMMENT ON COLUMN canonical.passenger_events.trip_resolution IS
    'Which of the three resolution outcomes this row got (handoff 0031): '
    '''resolved'' — exactly one scheduled trip matched and trip_id is that '
    'canonical trip; ''ambiguous'' — more than one matched, so trip_id was '
    'left as the vendor stated it and a DQ finding names the candidates; '
    '''unmatched'' — none matched, same, and the finding states what was '
    'parsed and searched. NULL means resolution was not attempted (no '
    'configuration, or a configuration whose direction convention the '
    'agency has not confirmed) — the normal case, not an error. The pipeline '
    'never picks a candidate: ambiguity is reported, not broken.';

-- Resolution quality per period is a queue-side question ("how much of this
-- month's APC data attached to a trip?"), answered by a scan over a period
-- that is already time-bounded by the hypertable. No index here: the column
-- is read alongside rows already selected by event_timestamp, and
-- canonical.passenger_events is large enough that an index nothing filters
-- on would cost every insert for no read. Add one with the query that needs
-- it, not before.
