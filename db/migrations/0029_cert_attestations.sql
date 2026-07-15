-- 0029: cert.attestations — statistician attestations for the p. 146
-- factor-up path (handoff 0019, design point A), plus the 'attested' DQ
-- resolution state.
--
-- Regulatory basis (2026 NTD Policy Manual, Full Reporting, p. 146 —
-- verified 2026-07-15, services/calc/REGULATORY_TRACKER.md "Verified —
-- statistician attestations"): "However, if the vehicle trips with missing
-- data exceed 2 percent of total trips, agencies must have a qualified
-- statistician approve the factoring method used to account for the missing
-- percentage." The approval is a HUMAN act: this table records it — WHO
-- (statistician + credentials summary), WHAT method, WHERE the approval
-- document lives (an external reference; the document itself is never
-- stored in v0), and the exact scope it covers (ONE metric, a
-- computed.metric_values scope pattern, a date range). upt_v0/pmt_v0 0.2.0
-- consume unrevoked in-scope rows via headway_calc.reader.load_attestations;
-- entry and revocation go ONLY through the audited API (POST /attestations,
-- POST /attestations/{id}/revoke — certifying_official).
--
-- Append-only correction discipline (the safety.events / migration 0017
-- house pattern): an attestation is never edited or deleted. The ONLY
-- permitted UPDATE is revocation — setting revoked_at/revoked_by/
-- revocation_reason exactly once, together, with every other column
-- byte-identical. Revocation never deletes: figures already factored under
-- the attestation keep their provenance forever; revocation only stops
-- FUTURE runs from factoring under it.

CREATE TABLE cert.attestations (
    attestation_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    statistician_name         TEXT NOT NULL,
    -- A summary of qualifications, not a credential document. The manual
    -- (p. 151) prescribes no specific qualifications: "transit agencies
    -- must ensure that statisticians are qualified" — the agency's
    -- accountability, recorded here.
    statistician_credentials  TEXT NOT NULL,
    -- The approved factoring method, in the statistician's terms.
    method_description        TEXT NOT NULL,
    -- External pointer to the approval document (file share path, document
    -- management system id, ...). v0 stores the REFERENCE, never the
    -- document (handoff 0019 open question: in-system encrypted doc
    -- storage later).
    document_reference        TEXT NOT NULL,
    -- The scope of the approval: exactly one metric the p. 146 rule
    -- applies to, a computed.metric_values.scope pattern (fnmatch:
    -- 'agency', 'mode:bus', 'mode:DR:tos:*', '*'), and a half-open
    -- [period_start, period_end) date range. A run is covered only when
    -- ALL three match (headway_calc.attestation.applicable_attestations).
    metric                    TEXT NOT NULL
        CONSTRAINT attestations_metric_vocabulary
        CHECK (metric IN ('upt', 'pmt')),
    scope_pattern             TEXT NOT NULL,
    period_start              DATE NOT NULL,
    period_end                DATE NOT NULL,
    entered_by                TEXT NOT NULL,
    entered_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Revocation trio: all NULL (live) or all set (revoked), exactly once.
    revoked_at                TIMESTAMPTZ,
    revoked_by                TEXT,
    revocation_reason         TEXT,
    CONSTRAINT attestations_period_nonempty
        CHECK (period_end > period_start),
    CONSTRAINT attestations_revocation_all_or_none
        CHECK (
            (revoked_at IS NULL AND revoked_by IS NULL
                AND revocation_reason IS NULL)
            OR (revoked_at IS NOT NULL AND revoked_by IS NOT NULL
                AND revocation_reason IS NOT NULL)
        )
);

CREATE INDEX attestations_metric_period_idx
    ON cert.attestations (metric, period_start, period_end);

-- Structural append-only guard (migration 0017 pattern): DELETE always
-- rejected; UPDATE permitted ONLY to set the revocation trio once (all
-- three NULL -> all three NOT NULL) with every other column unchanged.
-- Compared as jsonb minus the three mutable keys so a column added later
-- is covered automatically.
CREATE FUNCTION cert.enforce_attestations_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'cert.attestations is append-only: DELETE rejected. '
            'Revoke instead (POST /attestations/{id}/revoke) — an '
            'attestation figures were factored under is never removed.';
    END IF;
    IF OLD.revoked_at IS NOT NULL THEN
        RAISE EXCEPTION 'cert.attestations is append-only: attestation % is '
            'already revoked and can never change again. Enter a new '
            'attestation instead.', OLD.attestation_id;
    END IF;
    IF NEW.revoked_at IS NULL OR NEW.revoked_by IS NULL
       OR NEW.revocation_reason IS NULL
       OR (to_jsonb(NEW) - 'revoked_at' - 'revoked_by' - 'revocation_reason')
          IS DISTINCT FROM
          (to_jsonb(OLD) - 'revoked_at' - 'revoked_by' - 'revocation_reason')
    THEN
        RAISE EXCEPTION 'cert.attestations is append-only: the only '
            'permitted UPDATE is setting revoked_at, revoked_by and '
            'revocation_reason once, together, with every other column '
            'unchanged. Enter a correction as a new attestation instead.';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER attestations_append_only
    BEFORE UPDATE OR DELETE ON cert.attestations
    FOR EACH ROW
    EXECUTE FUNCTION cert.enforce_attestations_append_only();

-- The 'attested' DQ resolution state (handoff 0019, design point A.2): a
-- p. 146 refusal issue (apc_missing_trips_above_fta_threshold) does not
-- become a generic 'resolved' when a statistician attestation covers it —
-- it resolves to the EXPLICIT state 'attested' (POST /dq/issues/{id}/attest,
-- audited, referencing the attestation), so the trail says exactly WHY the
-- gap stopped blocking. Like every resolution, it is never deleted.
-- The certification blocking-issue gate treats 'attested' as closed
-- (services/api routers/certify.py counts open = status IN
-- ('open','owned'), category 'ntd').
ALTER TABLE dq.issues DROP CONSTRAINT issues_status_check;
ALTER TABLE dq.issues ADD CONSTRAINT issues_status_check
    CHECK (status IN ('open', 'owned', 'resolved', 'attested'));
