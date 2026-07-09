-- 0009: auth.users — local accounts (ADR-0011). NOTE: auth.users is NOT part
-- of handoff 0001's schema contract; the Backend Engineer adds it here with an
-- explicit "## Response — backend-engineer" appended to that handoff (schema
-- handoffs require responses, never silent extension). The native OIDC relying
-- party is the next increment and produces the same claim set {sub, username,
-- role}, so this table only backs the local-account path.

CREATE SCHEMA IF NOT EXISTS auth;

CREATE TABLE auth.users (
    user_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username      TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,  -- bcrypt (Apache-2.0 library), never plaintext
    role          TEXT NOT NULL
        CHECK (role IN ('viewer', 'data_steward', 'report_preparer', 'certifying_official')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    disabled      BOOLEAN NOT NULL DEFAULT false
);
