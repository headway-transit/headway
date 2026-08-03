-- 0038: canonical.block_labels — the agency's own name for a block
-- (handoff 0038).
--
-- WHY
-- ---
-- Handoff 0032 put vehicles and routes into findings in agency vocabulary;
-- blocks were the missing third. The first agency's GTFS export carries an
-- opaque UUID in trips.block_id, while the word on their run board is an
-- operational name like '225-4' — so no display change alone can name the
-- block a finding is about (headway_calc/subjects.py recorded exactly this
-- gap). The agency has now supplied the source to close it: a trip->block
-- export in their own vocabulary, joined to GTFS trips through the
-- handoff-0031 trip-name parse (route short name + first scheduled
-- departure), which lands feed block_id -> operational block name.
--
-- This table is AGENCY-LOCAL REFERENCE DATA, not feed data: one row per
-- feed block_id, loaded by tools/block-labels/derive.py from an
-- agency-supplied mapping file. The mapping file itself never enters the
-- repo (gitignored agency data); what lands here is the derived pairs plus
-- enough provenance to say where every label came from.
--
-- An agency whose feed already carries operational names in block_id (MBTA:
-- 'B800-53') simply has no rows here — the empty table IS the correct
-- mapping for them, and every consumer falls back to the feed id exactly as
-- before this migration.
--
-- ADDITIVE, AND NO LABEL IS EVER INVENTED
-- ---------------------------------------
-- Nothing existing is altered and nothing is backfilled. Consumers
-- (headway_calc.subjects) attach the label at persistence time, frozen on
-- the dq.issues row; a block_id with no row here renders exactly as it
-- renders today, and findings persisted before this migration are history
-- and are not rewritten. A pre-0038 database is probed for and tolerated by
-- the calc (the migration-0035 discipline: a display feature must never be
-- the reason a finding fails to land).

CREATE TABLE canonical.block_labels (
    -- The feed's block identifier, verbatim as canonical.trips.block_id
    -- carries it (for the first agency: an opaque UUID).
    block_id    TEXT PRIMARY KEY,
    -- The operational name the agency's dispatchers use for that block
    -- ('225-4'). NOT NULL: a row with no label would be an invented
    -- absence — an unmapped block is represented by NO row, never by an
    -- empty or placeholder label.
    block_label TEXT NOT NULL,
    -- Provenance: where the mapping came from (source file name + sha256),
    -- how each pair was derived (tool, resolution-config content hash,
    -- match rule), when, and by what. A label shown to an auditor must be
    -- traceable to the agency artifact that stated it.
    source      TEXT NOT NULL,
    derivation  TEXT NOT NULL,
    loaded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    loaded_by   TEXT NOT NULL,
    CONSTRAINT block_labels_label_nonempty CHECK (block_label <> '')
);

COMMENT ON TABLE canonical.block_labels IS
    'Agency-local mapping from the schedule feed''s block_id to the '
    'operational block name dispatch uses (handoff 0038): reference data '
    'loaded by tools/block-labels/derive.py from an agency-supplied '
    'trip->block export, joined to GTFS trips via the handoff-0031 '
    'trip-name parse. One row per feed block_id; a block with no row is '
    'UNMAPPED and every consumer shows the feed id, exactly as before this '
    'table existed. Consumers freeze the label at persistence time '
    '(dq.issues.subject_context), so reloading this table never rewrites '
    'an existing finding.';

COMMENT ON COLUMN canonical.block_labels.block_label IS
    'The operational block name in the agency''s own vocabulary (''225-4'') '
    '— exactly what their mapping export stated, never derived or guessed. '
    'Ambiguous or conflicting derivations are refused by the loader and '
    'reported, not stored.';

COMMENT ON COLUMN canonical.block_labels.source IS
    'The agency artifact this label came from: mapping file name plus its '
    'sha256, as stated by the loader.';

COMMENT ON COLUMN canonical.block_labels.derivation IS
    'How block_id was joined to the label: the deriving tool, the '
    'resolution-config content hash whose parse rules were reused (handoff '
    '0031), and the match key. Plain text, read by a human explaining a '
    'finding years later.';

-- No index beyond the primary key: the calc's label query joins on
-- block_id (the PK) and nothing filters on the label — an index nothing
-- reads would cost every insert (the migration-0036/0037 discipline).
