-- 0045: app.reported_datasets — what this agency reports, who owns it, and
-- which system is the system of record.
--
-- From the partner agency's ITS manager, 2026-08-03, who wrote a whole NTD
-- certification framework and opened it with the right instinct: treat
-- certification like a financial audit rather than a data upload. His first
-- artifact was an ownership matrix — dataset, owner, system of record,
-- frequency, NTD form — and Headway had no concept of any of it.
--
-- WHY THIS IS THE FIRST BUILD FROM THAT FRAMEWORK. Everything else he
-- described (cross-source reconciliation, allowable variances, proactive
-- drift) needs the system to first know that two sources EXIST and who owns
-- each. You cannot reconcile APC against farebox until something says
-- "ridership comes from both, Planning owns it, and it should arrive daily".
--
-- WHAT MAKES IT MORE THAN A SPREADSHEET. `headway_sources` links a declared
-- dataset to the raw.records source labels Headway actually receives, and
-- GET /sources/status already derives observed freshness from those same
-- rows. Declared cadence beside observed arrival is the whole point: the gap
-- between "should arrive daily" and "last arrived nine days ago" is a finding
-- nobody has to remember to look for.
--
-- EMPTY BY DESIGN, AND IT STAYS EMPTY. Every row here is an agency fact —
-- their departments, their vendors, their forms. Seeding a plausible-looking
-- default would be Headway asserting an ownership structure it cannot know,
-- and an ownership matrix that is subtly wrong is worse than an absent one:
-- it sends someone to the wrong department during a filing.
--
-- A DATASET WITH NO SOURCE IS A VALID, USEFUL ROW. The ITS manager's own
-- matrix had an "Eventually:" section — fleet inventory, operating expenses,
-- employee counts — that no system feeds today. Recording those states the
-- gap deliberately, which is exactly the honesty this platform is for.

CREATE TABLE app.reported_datasets (
    -- Stable machine key ('ridership'), separate from the display name so a
    -- rename never orphans a reference.
    dataset_key       TEXT PRIMARY KEY,
    display_name      TEXT NOT NULL,

    -- The agency's OWN words. Free text on purpose: "Planning", "CAD/AVL",
    -- "Finance" are their org chart, not a vocabulary we get to define.
    owner             TEXT NOT NULL,
    system_of_record  TEXT NOT NULL,

    -- How often a complete update is expected. NULL means "no cadence
    -- declared" — different from zero, and never inferred from observed data
    -- (inferring cadence from arrivals would make a broken feed look correct
    -- by redefining normal around its own failure).
    expected_interval INTERVAL,

    -- NTD forms this dataset feeds ('S-10', 'A-30', 'F-10', 'R-20'). An array
    -- because one dataset can feed several.
    ntd_forms         TEXT[] NOT NULL DEFAULT '{}',

    -- raw.records.source labels Headway actually receives for this dataset.
    -- EMPTY IS MEANINGFUL: it says Headway holds nothing for a dataset the
    -- agency reports, which is a gap worth seeing rather than an error.
    headway_sources   TEXT[] NOT NULL DEFAULT '{}',

    notes             TEXT,
    updated_by        TEXT NOT NULL,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT reported_datasets_key_not_blank
        CHECK (btrim(dataset_key) <> ''),
    CONSTRAINT reported_datasets_name_not_blank
        CHECK (btrim(display_name) <> ''),
    -- A cadence must be forward. A zero or negative interval would make
    -- "overdue" arithmetic silently nonsense.
    CONSTRAINT reported_datasets_interval_forward
        CHECK (expected_interval IS NULL OR expected_interval > INTERVAL '0')
);

COMMENT ON TABLE app.reported_datasets IS
    'What this agency reports to the NTD, who owns each dataset, and which '
    'system is its system of record. Agency-authored; never seeded. '
    'headway_sources links a declared dataset to the raw.records source '
    'labels actually received, so declared cadence can be compared against '
    'observed arrival.';

CREATE INDEX reported_datasets_owner_idx ON app.reported_datasets (owner);
