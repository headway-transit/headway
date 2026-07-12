-- 0017: safety.events + safety.event_classifications — Safety & Security
-- module v0 (handoff 0010).
--
-- S&S events are NOT derivable from telemetry: the source is structured
-- manual entry with validation (POST /safety/events), plus future
-- CAD/incident-system connectors. Regulatory basis: 2026 S&S Policy Manual
-- pp. 3-19, verified 2026-07-12 (services/calc/REGULATORY_TRACKER.md,
-- "Verified — Safety & Security reporting").
--
-- Append-only correction discipline: a corrected event is never edited or
-- deleted — a NEW row is inserted and the original points at its replacement
-- via superseded_by (audit discipline; an unexplained gap becomes a finding
-- in an FTA triennial review). The trigger below makes the discipline
-- STRUCTURAL: DELETE is always rejected, and the ONLY permitted UPDATE is
-- setting superseded_by exactly once (NULL -> a real event), with every
-- other column byte-identical.

CREATE SCHEMA IF NOT EXISTS safety;

CREATE TABLE safety.events (
    event_id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at                  TIMESTAMPTZ NOT NULL,
    -- Agency-supplied mode (the Predominant Use Rule, manual p. 15: a
    -- multi-mode event is reported in ONE mode — rail wins over non-rail,
    -- otherwise by passenger volume; the CHOICE is the enterer's, documented
    -- here, never inferred by code).
    mode                         TEXT NOT NULL,
    type_of_service              TEXT,
    -- Event vocabulary per the manual (handoff 0010 design point 1); cyber
    -- events are enterable citing Scenario G (p. 19).
    event_category               TEXT NOT NULL CHECK (event_category IN
        ('collision', 'derailment', 'fire', 'evacuation', 'security',
         'assault', 'cyber', 'other')),
    narrative                    TEXT NOT NULL,
    location                     TEXT,
    -- Fatalities are confirmed-within-30-days counts and include suicides
    -- (Exhibit 5, p. 16). Injuries use the immediate-transport definition:
    -- "Immediate transport away from the scene for medical attention for
    -- one or more persons" (Exhibit 5, p. 16).
    fatalities                   INTEGER NOT NULL DEFAULT 0 CHECK (fatalities >= 0),
    injuries                     INTEGER NOT NULL DEFAULT 0 CHECK (injuries >= 0),
    -- NULLABLE by design: damage not (yet) assessed stays NULL — a missing
    -- figure is never coalesced to $0. The $25,000 threshold (Exhibit 5,
    -- p. 16) is evaluated by the classifier, never here.
    property_damage_usd          NUMERIC CHECK (property_damage_usd >= 0),
    -- Rail serious-injury criteria (Exhibit 5, p. 16): hospitalization >48h
    -- commencing within 7 days; any bone fracture (except simple fractures
    -- of fingers, toes, or nose); severe hemorrhages or nerve/muscle/tendon
    -- damage; internal organs; 2nd/3rd-degree burns or burns >5% of body
    -- surface. The entry form asks these as plain-language questions; this
    -- flag records the answer.
    serious_injury               BOOLEAN NOT NULL DEFAULT false,
    -- Rail substantial-damage criteria (Exhibit 5, p. 16): disrupts
    -- operations AND adversely affects structural strength/performance/
    -- operating characteristics such that towing, rescue, on-site
    -- maintenance, or immediate removal is required.
    substantial_damage           BOOLEAN NOT NULL DEFAULT false,
    -- Supporting fields for the thresholds above and the S&S-40 detail
    -- export (handoff 0010): towed supports the substantial-damage
    -- determination; the remaining flags support the p. 17
    -- collision/evacuation rules and the p. 14 scope questions.
    towed                        BOOLEAN NOT NULL DEFAULT false,
    evacuation_life_safety       BOOLEAN NOT NULL DEFAULT false,
    -- "Assaults on a transit worker do not require an injury to be
    -- reportable on the S&S-50." (p. 3)
    assault_on_worker            BOOLEAN NOT NULL DEFAULT false,
    involves_transit_vehicle     BOOLEAN NOT NULL DEFAULT false,
    involves_second_rail_vehicle BOOLEAN NOT NULL DEFAULT false,
    grade_crossing               BOOLEAN NOT NULL DEFAULT false,
    entered_by                   TEXT NOT NULL,
    entered_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Corrections are append-only: the original points at its replacement.
    superseded_by                UUID REFERENCES safety.events (event_id),
    CONSTRAINT events_no_self_supersede CHECK (superseded_by <> event_id)
);

CREATE INDEX events_occurred_at_idx ON safety.events (occurred_at);
CREATE INDEX events_mode_idx ON safety.events (mode);

-- Structural append-only guard: DELETE always rejected; UPDATE permitted
-- ONLY to set superseded_by once (NULL -> NOT NULL) with every other column
-- unchanged. Compared as jsonb minus the one mutable key so a new column
-- added later is covered automatically.
CREATE FUNCTION safety.enforce_events_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'safety.events is append-only: DELETE rejected. '
            'Corrections supersede (POST /safety/events/{id}/supersede); '
            'originals are never removed.';
    END IF;
    IF OLD.superseded_by IS NOT NULL THEN
        RAISE EXCEPTION 'safety.events is append-only: event % is already '
            'superseded and can never change again. Correct its '
            'replacement instead.', OLD.event_id;
    END IF;
    IF NEW.superseded_by IS NULL
       OR (to_jsonb(NEW) - 'superseded_by') IS DISTINCT FROM
          (to_jsonb(OLD) - 'superseded_by') THEN
        RAISE EXCEPTION 'safety.events is append-only: the only permitted '
            'UPDATE is setting superseded_by once, with every other column '
            'unchanged. Enter a correction as a new event instead.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER events_append_only
    BEFORE UPDATE OR DELETE ON safety.events
    FOR EACH ROW
    EXECUTE FUNCTION safety.enforce_events_append_only();

-- Classifications are written ONLY by the deterministic classifier
-- (headway_calc.sscls, sscls_v0 — the calc-discipline rule: no reported
-- classification originates outside the versioned calculation library).
-- Append-only history: re-classification (a new classifier version, or a
-- superseding correction) INSERTs a new row; rows are never updated or
-- deleted, so every past classification stays reproducible.
CREATE TABLE safety.event_classifications (
    classification_id  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_id           UUID NOT NULL REFERENCES safety.events (event_id),
    classification     TEXT NOT NULL CHECK (classification IN
        ('major', 'non_major', 'not_reportable')),
    -- The Exhibit 5 / p. 17 major-event thresholds the event met. An event
    -- meeting one or more thresholds is ONE major event report (p. 14) —
    -- structurally: classification is 'major' exactly when at least one
    -- threshold was met.
    thresholds_met     TEXT[] NOT NULL,
    classifier_version TEXT NOT NULL,
    classified_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT major_iff_thresholds_met CHECK (
        (classification = 'major') = (cardinality(thresholds_met) > 0)
    )
);

CREATE INDEX event_classifications_event_id_idx
    ON safety.event_classifications (event_id);

CREATE FUNCTION safety.reject_classification_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'safety.event_classifications is append-only: % '
        'rejected. Re-classification inserts a new row (new classifier '
        'version or superseding correction); history is never rewritten.',
        TG_OP;
END;
$$;

CREATE TRIGGER event_classifications_append_only
    BEFORE UPDATE OR DELETE ON safety.event_classifications
    FOR EACH STATEMENT
    EXECUTE FUNCTION safety.reject_classification_mutation();
