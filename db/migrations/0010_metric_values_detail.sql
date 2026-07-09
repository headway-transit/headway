-- 0010: computed.metric_values.detail — per-value calculation detail (handoff
-- 0002, calc 0.2.0 gap policy). Append-only extension; no existing column
-- changes. Written exclusively by the calc library: for 0.2.0 runs it carries
-- {coverage, total_groups, excluded_groups, clean_position_share,
-- gap_threshold_seconds, coverage_threshold} (ratios as JSON strings —
-- Decimal-safe, never binary float); '{}' (the default) for detail-less rows
-- such as 0.1.0 recomputes.

ALTER TABLE computed.metric_values ADD COLUMN detail JSONB NOT NULL DEFAULT '{}'::jsonb;
