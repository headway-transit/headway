-- 0008: cert.certifications — the human attestation record. An insert must be
-- accompanied by an audit.events row (enforced by the API layer per the
-- handoff): certification is never silent.

CREATE TABLE cert.certifications (
    certification_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_value_ids UUID[] NOT NULL,
    certified_by     TEXT NOT NULL,
    certified_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    attestation      TEXT NOT NULL
);
