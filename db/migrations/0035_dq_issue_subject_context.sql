-- 0035: dq.issues.subject_context — the finding's subject in the agency's
-- own vocabulary, resolved once and frozen (handoff 0029).
--
-- WHY
-- ---
-- First-agency UAT, on a real blocking finding: "staff/users will need an
-- easier way to know what exact block they are looking for that had the
-- issue." What Headway showed was a wall of opaque ids, because upt_v0
-- formatted the first 20 raw trip ids into its description string. A finding
-- is addressed to a person who has to go fix something; it must name the
-- thing in the vocabulary that person uses to find it. Internal ids stay —
-- they are the provenance — but they are the footnote, not the headline.
--
-- WHAT
-- ----
-- The calculation library stays PURE: it emits a structured subject (a kind
-- plus the ids), never a label, because it never queries a database. The
-- runner — which already holds a repository connection — resolves those ids
-- into blocks, routes and scheduled departure times at PERSISTENCE time
-- (headway_calc.subjects) and writes the result here.
--
-- FROZEN ON PURPOSE. The labels are written once, with the row, and never
-- recomputed: a finding must read the same in an FTA triennial review years
-- later, even after the agency renames a route or the feed drops a block.
-- The ids are stored inside the blob alongside the labels, so any reader can
-- re-derive.
--
-- NO LABEL IS EVER INVENTED. A trip with no block carries no block; a route
-- with no short name carries no short name; a trip that is not in the
-- schedule feed is reported as exactly that, in its own bucket. Absent data
-- renders as absent.
--
-- ADDITIVE, and that cuts both ways
-- ---------------------------------
-- NULLABLE with no default and no backfill. Every dq.issues row written
-- before this migration keeps a NULL here and must render exactly as it
-- rendered yesterday — no crash, no blank panel, no "unknown block"
-- placeholder. The API serves NULL as null, the UI degrades to the prose
-- description it always showed, and a test pins that. Symmetrically, the
-- calc-side writer probes for this column and falls back to the pre-0035
-- INSERT if a database has not been migrated yet: a display feature must
-- never be the reason a data-quality finding fails to land.
--
-- Shape (headway_calc.subjects.CONTEXT_VERSION = 1). `version` is the FIRST
-- key any reader checks: an unrecognised version must be rendered as if the
-- context were absent, which is why the graceful-degradation path above is
-- the same code path.
--
--   {
--     "version": 1,
--     "kind": "canonical.trips",
--     "total": 1111,                 -- affected rows, never truncated
--     "grouped_by": "block",
--     "group_count": 34,             -- true total; groups[] may be capped
--     "group_cap": 25,
--     "trip_id_cap": 20,
--     "groups": [
--       {"block_id": "M899_-1",      -- null when the feed carries no block
--        "trip_count": 18,
--        "routes": [{"route_id": "42", "short_name": "42",
--                    "long_name": "Dayton Transfer"}],
--        "route_count": 1,
--        "first_departure": "06:14", -- GTFS service-day clock; null if none
--        "last_departure": "14:22",
--        "trip_ids": ["..."]}        -- capped sample; trip_count is truth
--     ],
--     "unmatched": {"trip_count": 3, "trip_ids": ["..."]}   -- key absent
--                                    -- when every trip was in the feed
--   }
--
-- No index. Nothing filters or joins on this column: it is read only as part
-- of a row already selected by issue_id or status, and dq.issues is a large
-- table (97k live) where an unused GIN index would cost every insert for no
-- read. Add one with the query that needs it, not before.

ALTER TABLE dq.issues
    ADD COLUMN subject_context JSONB;

COMMENT ON COLUMN dq.issues.subject_context IS
    'What this finding is about, in the agency''s own vocabulary: affected '
    'canonical rows grouped by block with route and scheduled time span, '
    'resolved once at write time and frozen (handoff 0029). Raw ids are kept '
    'inside as the footnote/provenance. NULL for every finding raised before '
    'migration 0035 and for findings about the run as a whole rather than '
    'about identifiable rows — such a finding renders from its prose '
    'description exactly as it always has. No label here is ever inferred or '
    'invented: absent data is stored as absent.';
