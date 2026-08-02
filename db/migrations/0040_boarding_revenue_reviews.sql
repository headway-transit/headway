-- 0040: dq.boarding_revenue_reviews — the human-in-the-loop review queue for
-- no-run boardings, and the justification note that makes the correction
-- defensible (handoff 0040, design point 4; the review sub-wave).
--
-- WHY
-- ---
-- Migration 0039 + upt_v0 0.3.0 taught Headway to separate real ridership
-- from prep-time noise: a boarding the vehicle fired while NOT logged into a
-- run is not in revenue service (2026 NTD Policy Manual p. 128), so it is not
-- an unlinked passenger trip. The clear cases auto-classify. The genuinely
-- ambiguous ones — a no-run boarding INSIDE the day's revenue window, which
-- could be non-revenue prep OR a real catch-up bus dispatch that ran without
-- a formal trip assignment — are HELD OUT of the reported figure pending a
-- human decision (the exclude-until-classified default).
--
-- Until this table existed there was nowhere for that human decision to land.
-- Held boardings were held FOREVER and the figure could never be completed.
-- That is the dead end this table closes: one row per no-run boarding the
-- calculation could not decide, carrying the context an analyst needs and the
-- slot their verdict + justification goes into.
--
-- WHAT A ROW IS
-- -------------
-- One row = one passenger event (one boarding) the calculation HELD PENDING.
-- Rows are written by the calc runner at persist time, from the calculation's
-- own review items — the calc is the only component that decides what is
-- pending, exactly as it is the only component that produces a figure.
-- Re-running the calculation UPSERTs the context (a later run may see the
-- same boarding again) and NEVER touches a human verdict already recorded.
--
-- THE JUSTIFICATION NOTE IS REQUIRED, BY THE SCHEMA
-- -------------------------------------------------
-- The whole point of this wave is that the correction is DEFENSIBLE, not
-- asserted: "explain this number" must be able to say who classified this
-- boarding, when, and why. So the note is not a nice-to-have the API happens
-- to validate — the database refuses a verdict without one. The four human
-- columns move together (all NULL = pending; all present = classified) and a
-- blank or whitespace-only note is rejected by CHECK. There is no path,
-- through any client, that records a verdict with no reason.
--
-- WHY NOT JUST dq.issues
-- ----------------------
-- The finding stays in dq.issues where it belongs — every pending boarding
-- already raises a 'boarding_pending_revenue_review' warning citing its raw
-- record, and classifying a boarding CLOSES that issue through the ordinary
-- resolution workflow (owner, status, notes; handoffs 0029/0030), audited the
-- same way. What dq.issues cannot do is carry the structured boarding facts a
-- reviewer decides on (vehicle, timestamp, count, the calculation's own
-- reason) in a form that pages at scale and that the calculation can read
-- BACK on its next run. That is this table: the workflow is the DQ workflow;
-- this is the decision record the calculation consumes.
--
-- NOTHING HERE MUTATES A PERSISTED FIGURE
-- ---------------------------------------
-- Classifying a boarding changes NO computed.metric_values row. The verdict
-- takes effect only when the calculation is re-run over a period containing
-- the boarding — the figure is recomputed from its inputs, never patched in
-- place. A certified figure is never rewritten: the API refuses to classify a
-- boarding whose service date falls inside an already-certified period and
-- says exactly why (the certification would no longer describe the number it
-- attests to).

CREATE TABLE dq.boarding_revenue_reviews (
    -- The canonical.passenger_events row under review. TEXT (not UUID) to
    -- match canonical.passenger_events.passenger_event_id exactly; one row
    -- per boarding, so re-running the calculation cannot duplicate the queue.
    passenger_event_id TEXT PRIMARY KEY,

    -- Provenance: the raw record this boarding was normalized from. Kept so
    -- the review row can walk back to the bytes, and so classifying can find
    -- the dq.issues finding raised over the same record.
    source_record_id   TEXT NOT NULL,

    -- Frozen context, as the calculation saw it (never re-derived later — a
    -- review must read the same in an FTA triennial review years from now,
    -- even after a feed is re-ingested or a vehicle is renumbered).
    service_date       DATE NOT NULL,
    event_timestamp    TIMESTAMPTZ NOT NULL,
    -- The feed's own vehicle identifier (TIDES vehicle_id — for the exports
    -- that produce these rows this is the fleet number a dispatcher says out
    -- loud). Nullable because the contract allows a boarding with no vehicle;
    -- absent renders as absent, never as a placeholder.
    vehicle_id         TEXT,
    -- Boardings on this event. NOT NULL: a NULL-count boarding carries no
    -- number to classify and is warned by its own 'apc_null_count' finding
    -- instead of landing here.
    event_count        INTEGER NOT NULL,

    -- WHY the calculation could not decide, in its own words, frozen. The
    -- suggestion is deliberately NOT a verdict in disguise: 'pending_review'
    -- means Headway declined to guess. An analyst is told what was checked
    -- and what was ambiguous — never nudged toward an answer the data does
    -- not support.
    suggested_verdict  TEXT NOT NULL
        CHECK (suggested_verdict IN ('pending_review')),
    suggested_reason   TEXT NOT NULL,

    -- Which calculation raised it, and over which period. Provenance for the
    -- decision: a reviewer can always get back to the run that flagged this.
    calc_name          TEXT NOT NULL,
    calc_version       TEXT NOT NULL,
    period_start       DATE NOT NULL,
    period_end         DATE NOT NULL,
    first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- --- the human decision -------------------------------------------------
    -- All four NULL = pending. All four present = classified. Enforced below,
    -- so "classified with no reason" is not a state this schema can hold.
    verdict            TEXT
        CHECK (verdict IN ('revenue', 'non_revenue')),
    justification      TEXT,
    classified_by      TEXT,
    classified_at      TIMESTAMPTZ,

    -- The dq.issues finding this classification closed, when one was open.
    -- Nullable: the finding may already have been resolved by hand, or the
    -- database may hold a review row whose finding predates it. Null means
    -- "no open finding was found to close", which is recorded honestly rather
    -- than papered over.
    dq_issue_id        UUID REFERENCES dq.issues (issue_id),

    -- A verdict REQUIRES a justification, a person, and a time — together or
    -- not at all. This is the schema-level form of the wave's rule: the
    -- correction is defensible, not asserted.
    CONSTRAINT boarding_review_decision_complete CHECK (
        (verdict IS NULL AND justification IS NULL
             AND classified_by IS NULL AND classified_at IS NULL)
        OR (verdict IS NOT NULL AND justification IS NOT NULL
             AND classified_by IS NOT NULL AND classified_at IS NOT NULL)
    ),
    -- ...and the justification must actually say something. A blank note is
    -- the same as no note, and no note is not a resolution path.
    CONSTRAINT boarding_review_justification_not_blank CHECK (
        justification IS NULL OR length(btrim(justification)) > 0
    )
);

-- The queue read: pending rows, oldest boarding first, keyset-paged on
-- (event_timestamp, passenger_event_id) — the same total ordering discipline
-- as the DQ queue (handoff 0030), so a page can neither skip a row nor serve
-- one twice while a calc run writes behind the reader. Partial, because the
-- queue only ever reads the undecided rows and the classified ones are
-- history.
CREATE INDEX boarding_revenue_reviews_pending_idx
    ON dq.boarding_revenue_reviews (event_timestamp, passenger_event_id)
    WHERE verdict IS NULL;

-- The receipt read: every human classification whose boarding falls in a
-- reporting period, so "explain this number" can list the judgment calls that
-- shaped the figure without scanning the pending backlog.
CREATE INDEX boarding_revenue_reviews_classified_idx
    ON dq.boarding_revenue_reviews (service_date, passenger_event_id)
    WHERE verdict IS NOT NULL;

COMMENT ON TABLE dq.boarding_revenue_reviews IS
    'Human-in-the-loop revenue review of no-run boardings (handoff 0040). '
    'One row per boarding the calculation held PENDING because it could not '
    'be decided from the schedule alone — a no-run boarding inside the day''s '
    'revenue-service window is either non-revenue prep or a real catch-up bus '
    'dispatched without a formal trip assignment, and only a human who knows '
    'the day''s dispatch decisions can tell them apart. Rows are written by '
    'the calc runner (the calculation is the only component that decides what '
    'is pending) and re-run UPSERTs never overwrite a human verdict. A '
    'verdict is inseparable from its justification note, its author and its '
    'timestamp: that trio is what makes the exclusion defensible in an FTA '
    'triennial review, and the CHECK constraints make a verdict without a '
    'reason unrepresentable. Classifying changes no persisted figure — the '
    'verdict takes effect on the next calculation run.';

COMMENT ON COLUMN dq.boarding_revenue_reviews.suggested_verdict IS
    'What the calculation concluded on its own: always ''pending_review'' — '
    'it declined to guess. Auto-excluded prep boardings never reach this '
    'table (they are decided, excluded, and cited by their own '
    '''boarding_excluded_non_revenue'' finding), and assigned boardings count '
    'as ordinary revenue ridership. The column exists so a future reviewer '
    'reads the calculation''s own position rather than inferring it.';

COMMENT ON COLUMN dq.boarding_revenue_reviews.justification IS
    'WHY this boarding was classified the way it was, in the analyst''s own '
    'words — e.g. "unit''s counter double-fired during layover, confirmed '
    'with dispatch" or "extra bus sent to recover the route at 15:10, these '
    'are real riders". REQUIRED with any verdict and never blank (CHECK). '
    'This note becomes part of the figure''s receipt: "explain this number" '
    'shows who decided, when, and why, so the correction can be defended '
    'rather than merely asserted.';
