-- 0018: safety.events — runaway-train and evacuation-to-ROW capture
-- (handoff 0010 correction round; REGULATORY_TRACKER.md "S&S addendum —
-- verbatim rules for sscls", verified 2026-07-12 second pass).
--
-- Two rules on the manual's printed p. 17 need capture fields the 0017
-- schema lacked (smallest honest schema change — two booleans):
--
-- * runaway_train — "movement of a rail transit vehicle on the mainline,
--   yard, or shop that is uncommanded, uncontrolled, or unmanned due to an
--   incapacitated, sleeping, or absent operator, or the failure of a rail
--   transit vehicle's electrical, mechanical, or software system or
--   subsystem." (rail only, revenue vehicles). The classifier (sscls_v0
--   0.1.1) treats this as a major-event threshold on rail modes.
--
-- * evacuation_to_rail_row — rail evacuations include "Evacuations to
--   controlled rail right-of-way (excludes evacuation to a platform,
--   except for life safety)", covering "Both transit-directed evacuations
--   and self-evacuations." Distinct from evacuation_life_safety (any
--   mode): an evacuation to the controlled ROW is reportable on rail even
--   without a life-safety reason.
--
-- NOT NULL DEFAULT false: the entry form asks each as an explicit yes/no
-- question (API validation); the default makes the backfill honest — no
-- pre-0018 event was a runaway or a ROW evacuation record, those fields
-- simply did not exist and read as "not recorded as such".
--
-- The 0017 append-only trigger compares rows as to_jsonb(...) minus
-- 'superseded_by', so these new columns are covered by it automatically —
-- no trigger change needed.

ALTER TABLE safety.events
    ADD COLUMN runaway_train BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE safety.events
    ADD COLUMN evacuation_to_rail_row BOOLEAN NOT NULL DEFAULT false;
