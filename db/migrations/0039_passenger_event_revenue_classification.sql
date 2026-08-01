-- 0039: revenue classification of boardings — the no-run assignment status on
-- the passenger event (handoff 0040, backend foundation).
--
-- WHY
-- ---
-- A live diagnostic (2026-07-31) over a real full-day APC export found ~3.3%
-- of boardings on rows carrying NO run assignment at all — trip, route, stop,
-- direction and stop-sequence all NULL. The ITS manager identified them as
-- drivers/staff boarding during prep, pull-out and pull-in while the vehicle
-- is moving with the APC on but not logged into a run. A vehicle not logged
-- into a run is NOT in revenue service (2026 NTD Policy Manual p. 128), so
-- those boardings are NOT unlinked passenger trips.
--
-- Until now the adapter QUARANTINED (or filtered) these rows — a loud but
-- lossy ~3.3% drop. This wave stops dropping them and instead lands them as
-- passenger events marked with an explicit ASSIGNMENT/REVENUE status, so the
-- calc can exclude the non-revenue ones from UPT with the receipts to prove
-- it, and a later human-in-the-loop wave can reclassify the genuinely
-- ambiguous mid-service ones.
--
-- ADDITIVE, AND NOTHING IS BACKFILLED (the migration-0036 precedent)
-- -----------------------------------------------------------------
-- The column is new and nullable. Rows written before this migration keep
-- NULL and must read exactly as they read yesterday. NULL means "assignment
-- status was not recorded for this row" — a first-party TIDES feed states its
-- own trip_id_performed and nothing classifies it, exactly as before — and
-- the calc treats a NULL-classification row by its existing trip-assignment
-- proxy (trip_id present = counted, trip_id NULL = excluded), byte-for-byte
-- as upt_v0 0.1.0/0.2.0. Re-classifying rows ingested before this existed is
-- a re-run, not an UPDATE (classification happens at normalization time and
-- is part of the row's lineage).
--
-- STATUS ONLY, NEVER THE REVENUE VERDICT
-- --------------------------------------
-- This column carries the TRANSFORM's assignment status — 'assigned' or
-- 'unassigned' — a mechanical fact about whether the row resolved to a run.
-- It is deliberately NOT the revenue verdict (revenue / non-revenue /
-- pending-review): a reported number is never produced by the transform. The
-- deterministic calc library derives the revenue verdict from this status
-- plus the schedule-derived revenue window and the detour flag (Shared
-- Constraint 1 — the calc is the only place a reportable figure originates).

ALTER TABLE canonical.passenger_events
    ADD COLUMN revenue_classification TEXT;

ALTER TABLE canonical.passenger_events
    ADD CONSTRAINT passenger_events_revenue_classification_check
    CHECK (revenue_classification IN ('assigned', 'unassigned'));

COMMENT ON COLUMN canonical.passenger_events.revenue_classification IS
    'The TRANSFORM''s assignment status for this boarding/alighting row '
    '(handoff 0040): ''assigned'' — the row resolved to a run (a trip, and '
    'in this export a stop and stop-sequence); ''unassigned'' — the row '
    'carried NO run assignment at all (trip, route, stop, direction and '
    'stop-sequence all absent), the "ghost" boarding a vehicle fired while '
    'moving with the APC on but not logged into a run (prep / pull-out / '
    'pull-in, or — rarely — a catch-up bus dispatch ran without a formal '
    'trip assignment). NULL means no assignment status was recorded — a '
    'first-party TIDES feed states trip_id_performed itself and nothing '
    'classifies it (the normal, pre-handoff-0040 case, not an error). This '
    'is an ASSIGNMENT STATUS, never the revenue verdict: whether an '
    'unassigned boarding is non-revenue prep (excluded from UPT) or a real '
    'catch-up rider (counted) is decided by the deterministic calc library '
    'from this status + the schedule-derived revenue window + the detour '
    'flag, and — for the genuinely ambiguous mid-service case — a human in '
    'the review queue. A reported number never originates in the transform.';

-- No index: the column is read alongside rows already selected by
-- event_timestamp (the hypertable time dimension), the same reasoning as
-- migration 0036's trip_resolution. Add one with the query that needs it,
-- not before.
