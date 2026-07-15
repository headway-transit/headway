-- 0030: cert.certifications — the certifier's digital signature
-- (handoff 0019, design point B).
--
-- Certification was an audited consent flow; it becomes a visible,
-- tamper-evident digital signature. Three columns join the record:
--
--   canonical_document  the EXACT signed bytes, stored as TEXT (UTF-8 of
--                       the canonical JSON — services/api
--                       headway_api/signing.py documents the byte-precise
--                       canonicalization; TEXT, never JSONB: JSONB
--                       normalizes key order and whitespace, which would
--                       destroy the signed byte sequence);
--   signature           Ed25519 signature over exactly those bytes,
--                       standard base64;
--   key_fingerprint     'ed25519:' + SHA-256 hex of the 32-byte raw public
--                       key — identifies WHICH installation key signed.
--
-- The signing key is the INSTALLATION key: generated at install/first-use,
-- held in the environment/secret file (HEADWAY_SIGNING_KEY in
-- deploy/compose/.env, installer-generated) — NEVER in this database and
-- NEVER in the repository. Honest scope (stated on the certificate itself):
-- integrity + attribution within this system, NOT PKI non-repudiation;
-- per-certifier keys (WebAuthn) are the documented v1.
--
-- Existing certifications keep NULL in all three columns FOREVER — honest
-- history is never backfilled with signatures nobody made. The CHECK below
-- makes a partially signed row unrepresentable: all three or none.

ALTER TABLE cert.certifications
    ADD COLUMN canonical_document TEXT,
    ADD COLUMN signature          TEXT,
    ADD COLUMN key_fingerprint    TEXT;

ALTER TABLE cert.certifications
    ADD CONSTRAINT certifications_signature_all_or_none
    CHECK (
        (canonical_document IS NULL AND signature IS NULL
            AND key_fingerprint IS NULL)
        OR (canonical_document IS NOT NULL AND signature IS NOT NULL
            AND key_fingerprint IS NOT NULL)
    );

-- Structural append-only guard (the migration 0017/0029 house pattern,
-- strict form): a certification row NEVER changes and is NEVER deleted —
-- there is no legitimate in-band mutation at all. This is defense in depth
-- under the signature: an out-of-band mutation (superuser disabling the
-- trigger, direct file tampering) is exactly what the Ed25519 verification
-- endpoint exists to catch loudly (the handoff-0019 tamper test pins that).
CREATE FUNCTION cert.enforce_certifications_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'cert.certifications is append-only: % rejected. A '
        'certification is a signed legal attestation — it is never edited '
        'or deleted. A wrong certification is corrected by the record, '
        'never by rewriting it.', TG_OP;
    RETURN NULL;
END;
$$;

CREATE TRIGGER certifications_append_only
    BEFORE UPDATE OR DELETE ON cert.certifications
    FOR EACH ROW
    EXECUTE FUNCTION cert.enforce_certifications_append_only();
