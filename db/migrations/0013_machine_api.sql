-- 0013: machine API — service-account keys + webhook subscriptions (handoff
-- 0006, design points 2 and 7). NOTE: like auth.users (0009), these tables are
-- NOT part of handoff 0001's schema contract; they are added under handoff
-- 0006's binding design, never by silent extension.

-- Service-account API keys. The key itself is `hwk_<32 bytes url-safe random>`
-- and is stored ONLY as its SHA-256 hex digest: the key is high-entropy random
-- (not a human password), so a fast hash is the correct at-rest protection —
-- brute-forcing 32 random bytes through SHA-256 is infeasible, and bcrypt-class
-- stretching would add per-request latency without adding security. The full
-- key is shown exactly once at issuance and is never retrievable again.
CREATE TABLE auth.api_keys (
    key_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,           -- human label, e.g. 'APC vendor X'
    key_hash     TEXT NOT NULL UNIQUE,    -- SHA-256 hex of the full key; NEVER the key
    key_prefix   TEXT NOT NULL,           -- first 12 chars ('hwk_' + 8), for UI/logs/audit
    scopes       TEXT[] NOT NULL,         -- v0: 'ingest:tides', 'read:metrics'; deny-by-default
    -- Bound envelope source for ingest keys: the ONLY `source` this key may
    -- write. A simulated-data key gets 'tides_simulated', a real vendor gets
    -- its own label — never interchangeable, never client-supplied.
    source_label TEXT,
    created_by   TEXT NOT NULL,           -- issuing admin (audit attribution)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Soft revoke: keys are never deleted, so the issuance/use/revocation
    -- history stays auditable forever.
    revoked_at   TIMESTAMPTZ
);

-- Outbound webhook subscriptions (v0 event: 'certification.created').
--
-- DOCUMENTED RISK (handoff 0006, design point 7): `secret` holds the HMAC
-- signing secret in PLAINTEXT. It cannot be hashed — the API must read it back
-- to sign each delivery. Application-level encryption of this column is the
-- secrets-management increment (Security role, tracked in handoff 0006's Open
-- Questions). COMPENSATING CONTROL until then: database-at-rest encryption
-- (the platform's encryption-at-rest default, Constraint 5) plus the fact that
-- this secret only authenticates outbound notifications — it grants no read or
-- write access to any Headway data.
CREATE TABLE auth.webhook_subscriptions (
    subscription_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url             TEXT NOT NULL,        -- delivery target (https expected)
    event_types     TEXT[] NOT NULL,      -- v0: 'certification.created'
    secret          TEXT NOT NULL,        -- HMAC-SHA256 signing secret (see risk note above)
    created_by      TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Soft revoke, same audit-history rationale as auth.api_keys.
    revoked_at      TIMESTAMPTZ
);
