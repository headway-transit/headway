-- 0023: replay idempotency for lineage.edges and transform-emitted
-- dq.issues (2026-07-13 hardening pass, Batch B).
--
-- The transform consumer is at-least-once: Kafka redelivers, and
-- normalization is deterministic, so a replay re-derives byte-identical
-- lineage edges and DQ findings. canonical.* tables already dedupe replays
-- via unique natural keys + ON CONFLICT DO NOTHING, but lineage.edges and
-- dq.issues did not — the transform README's idempotency claim was not
-- true for them (confirmed live: 672,073 duplicate edge rows of 6,632,038
-- on 2026-07-13, all from normalize_gtfs_static / normalize_gtfs_rt_positions
-- replays).
--
-- lineage.edges: an edge is a pure derivation fact — a duplicate row
-- carries zero information, so existing duplicates are deleted (keeping
-- the lowest edge_id) and the FULL six-column tuple becomes the unique
-- natural key. The writer inserts with ON CONFLICT DO NOTHING against it.
--
-- dq.issues: findings must NOT be blanket-deduplicated — human-created
-- issues, AI anomaly flags, and calc-run exclusions may legitimately
-- repeat (each calc run re-emitting an exclusion is a distinct, owned
-- event). Dedupe is therefore scoped by a NULLABLE dedupe_key that ONLY
-- the transform writer populates ("transform:" + sha256 of the finding's
-- full identity; see headway_transform/model.py). Rows with a NULL
-- dedupe_key — everything human/AI/calc-created, and all existing rows —
-- are untouched and can never collide. No existing dq.issues rows are
-- deleted by this migration.

-- 1) Remove duplicate lineage edges, keeping the earliest row of each
--    natural-key group.
DELETE FROM lineage.edges
WHERE edge_id IN (
    SELECT edge_id
    FROM (
        SELECT edge_id,
               row_number() OVER (
                   PARTITION BY output_kind, output_id, transform_name,
                                transform_version, input_kind, input_id
                   ORDER BY edge_id
               ) AS rn
        FROM lineage.edges
    ) numbered
    WHERE rn > 1
);

-- 2) The natural key: one derivation fact, one row. The transform writer's
--    ON CONFLICT target.
CREATE UNIQUE INDEX edges_natural_key_uq
    ON lineage.edges (output_kind, output_id, transform_name,
                      transform_version, input_kind, input_id);

-- 3) Transform-scoped dedupe key for dq.issues. NULL for every row not
--    written by the transform writer (human, AI, calc) — those are never
--    deduplicated.
ALTER TABLE dq.issues ADD COLUMN dedupe_key TEXT;

CREATE UNIQUE INDEX issues_dedupe_key_uq
    ON dq.issues (dedupe_key)
    WHERE dedupe_key IS NOT NULL;
