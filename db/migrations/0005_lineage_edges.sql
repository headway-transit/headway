-- 0005: lineage.edges — explicit lineage graph (ADR-0007), one row per
-- derivation edge. "Explain this number" = recursive traversal from a
-- computed.metric_values row back to raw.records rows.

CREATE TABLE lineage.edges (
    edge_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    output_kind       TEXT NOT NULL,  -- 'canonical.vehicle_positions', 'computed.metric_values', ...
    output_id         TEXT NOT NULL,  -- the output row's natural/primary key rendered as text
    transform_name    TEXT NOT NULL,
    transform_version TEXT NOT NULL,
    input_kind        TEXT NOT NULL,  -- 'raw.records', 'canonical.vehicle_positions', ...
    input_id          TEXT NOT NULL
);

CREATE INDEX edges_output_idx ON lineage.edges (output_kind, output_id);
CREATE INDEX edges_input_idx  ON lineage.edges (input_kind, input_id);
