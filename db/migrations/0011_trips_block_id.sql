-- 0011: canonical.trips.block_id — GTFS block identifier (handoff 0003,
-- block-aware VRH, calc vrh_v0 0.3.0, closes divergence D1). Append-only
-- extension; no existing column changes. Nullable by design: block_id is an
-- OPTIONAL trips.txt field per the GTFS Schedule Reference (gtfs.org) — "A
-- block consists of a single trip or many sequential trips made using the
-- same vehicle" — and feeds that omit it store NULL (calc v0.3 then falls
-- back to per-trip grouping and documents the undercount). Existing rows
-- backfill on the next static-feed replay via the transform upsert path.

ALTER TABLE canonical.trips ADD COLUMN block_id TEXT;
