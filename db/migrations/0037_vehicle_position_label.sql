-- 0037: canonical.vehicle_positions.vehicle_label (handoff 0032).
--
-- WHY
-- ---
-- First-agency UAT: telemetry-gap warnings must name the vehicle the way
-- dispatch names it. Verified against the agency's LIVE feed (orchestrator,
-- 2026-07-29): all 54 of their GTFS-RT vehicles broadcast
-- VehicleDescriptor.label — fleet numbers ('5335', '5317'), the identifier
-- dispatch actually uses. The normalizer discarded it, because this column
-- did not exist: the data Tony wants was in his own feed, dropped at
-- ingestion. (MBTA labels its fleet too — verified 2026-07-30, 555 of 555
-- entities — so the fix is general, not agency-specific.)
--
-- The GTFS-Realtime reference (gtfs.org/documentation/realtime/reference,
-- VehicleDescriptor.label — verify against the current published spec)
-- defines label as "User visible label, i.e., something that must be shown
-- to the passenger to help identify the correct vehicle." OPTIONAL in the
-- spec, therefore NULLABLE here.
--
-- ADDITIVE, FORWARD-ONLY, NOTHING INVENTED
-- ----------------------------------------
-- NULL means the feed carried no label for that position — never that a
-- label was defaulted or derived. A feed without labels stores NULL forever
-- and every consumer must render the absence honestly (the shortened
-- vehicle_id fallback, handoff 0032). Rows written before this migration
-- keep NULL: no backfill in this wave. Raw GTFS-RT records are retained and
-- replayable, so a backfill via raw replay (tools/canonical-replace
-- precedent) is recorded as a handoff-0032 open question, not built here.
--
-- No index: nothing filters or joins on the label — it rides along with
-- rows already selected by the hypertable's time bounds, and an index
-- nothing reads would cost every insert (the migration-0036 discipline).

ALTER TABLE canonical.vehicle_positions
    ADD COLUMN vehicle_label TEXT;

COMMENT ON COLUMN canonical.vehicle_positions.vehicle_label IS
    'GTFS-Realtime VehicleDescriptor.label, verbatim as the feed stated it '
    '(handoff 0032): the user-visible vehicle identifier — typically the '
    'fleet number dispatch uses. OPTIONAL in the GTFS-RT spec and therefore '
    'NULLABLE: NULL means the feed carried no label (empty string is '
    'normalized to NULL), never that a label was guessed. Forward-only: '
    'rows written before migration 0037 keep NULL; backfill via raw replay '
    'is a recorded open question, not an assumption.';
