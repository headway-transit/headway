-- 0043: the native OIDC relying party (ADR-0011, handoff 0046).
--
-- ADR-0011 decided this two months ago: Headway is its OWN relying party
-- (authorization code + PKCE) and speaks to Entra ID, Google or Okta
-- directly, rather than putting a second JVM beside Kafka on a small
-- agency's single box. Keycloak stays an optional profile for SAML-only
-- IdPs; when it is used it is simply the configured OIDC provider and none
-- of the code below changes.
--
-- LOCAL ACCOUNTS SURVIVE, PERMANENTLY. Nothing here removes, disables or
-- weakens auth.users as it exists. An installation that never configures
-- OIDC is byte-for-byte as capable as before this migration. Three reasons,
-- all load-bearing:
--
--   * ON-PREM PARITY — an agency with no internet, or an IdP having a bad
--     morning, must still be able to operate Headway.
--   * BREAK-GLASS — the FIRST OIDC configuration attempt will be wrong.
--     There must be a way in that does not depend on the thing being
--     configured. (The API also honours HEADWAY_OIDC_DISABLED=1 as a
--     server-side kill switch that needs no database access at all.)
--   * `install.sh --reset-admin-password` keeps working — it writes a
--     bcrypt hash into auth.users.password_hash, which is still there.
--
-- ---------------------------------------------------------------------------
-- 1. auth.users learns where an account came from
-- ---------------------------------------------------------------------------
--
-- password_hash becomes NULLABLE, because a federated account has no
-- password and storing a dummy hash would be a lie that a future reader
-- could mistake for a credential. The CHECK below makes the two account
-- shapes mutually exclusive and makes a half-federated row unrepresentable:
--
--   auth_source='local' -> password_hash present, idp columns NULL
--   auth_source='oidc'  -> password_hash NULL,    idp columns present
--
-- The login surface (auth.py) refuses a password login against an account
-- with no password_hash using the SAME generic message as a wrong password,
-- so account shape is never an enumeration oracle.
--
-- idp_issuer + idp_subject are the IdP's OWN stable identifiers. They are
-- recorded because of the certification guardrail: under SSO the audit trail
-- must still record WHO SIGNED with at least today's fidelity. "An SSO user"
-- is not a signer. A signature whose signer cannot be resolved years later —
-- after the person has left, after the username has been reused, after the
-- tenant has been migrated — is not a signature. `sub` from the IdP is the
-- one identifier a provider promises not to reuse; the username is what a
-- human recognises. Headway keeps both, forever, on the account and inside
-- the signed certification document.

ALTER TABLE auth.users ALTER COLUMN password_hash DROP NOT NULL;

ALTER TABLE auth.users
    ADD COLUMN auth_source TEXT NOT NULL DEFAULT 'local'
        CHECK (auth_source IN ('local', 'oidc')),
    ADD COLUMN idp_issuer  TEXT,
    ADD COLUMN idp_subject TEXT,
    ADD COLUMN last_login_at TIMESTAMPTZ;

ALTER TABLE auth.users
    ADD CONSTRAINT users_auth_source_shape CHECK (
        (auth_source = 'local'
            AND password_hash IS NOT NULL
            AND idp_issuer IS NULL AND idp_subject IS NULL)
        OR
        (auth_source = 'oidc'
            AND password_hash IS NULL
            AND idp_issuer IS NOT NULL AND idp_subject IS NOT NULL)
    );

-- One Headway account per (issuer, subject). Two accounts claiming the same
-- IdP identity would make "who signed" ambiguous, which is the one thing the
-- certification trail may never be.
CREATE UNIQUE INDEX users_idp_identity_uniq
    ON auth.users (idp_issuer, idp_subject)
    WHERE idp_subject IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 2. The provider configuration — one row, secret encrypted at rest
-- ---------------------------------------------------------------------------
--
-- SINGLE ROW by construction (the `singleton` primary key can only ever be
-- true). One Headway installation serves one agency (ADR-0004: one database
-- per agency), so one identity provider. A second provider row would be a
-- silent ambiguity about which one issued a session.
--
-- client_secret_encrypted holds AES-256-GCM ciphertext produced by
-- services/api/headway_api/secrets_at_rest.py. The KEY lives in the
-- environment or a 0600 secret file (HEADWAY_SECRET_ENCRYPTION_KEY /
-- _KEY_FILE) — the same shape as the Ed25519 signing key (migration 0030),
-- and for the same reason: a key stored beside the ciphertext it protects is
-- not encryption, it is filing. Without the key the API REFUSES to store a
-- client secret rather than storing it in the clear.
--
-- The secret is SHOW-ONCE: it is written by the admin, encrypted, and never
-- served back by any endpoint. GET returns only whether one is set and when
-- it changed. Audit records `client_secret_changed: true` — never the value.
--
-- ca_bundle_path is the TLS-inspecting-proxy story, and it is not a nicety.
-- Agencies routinely terminate and re-sign TLS at the perimeter, so the
-- discovery document and JWKS arrive signed by a corporate CA that the
-- container's trust store has never heard of. Without somewhere to name that
-- CA the integration fails with a certificate error that reads like a bug,
-- and the field workaround is to turn verification off. So: a path to a PEM
-- bundle, verified to exist and be readable when it is set, and NO option
-- anywhere to disable verification.

CREATE TABLE auth.oidc_provider (
    singleton               BOOLEAN PRIMARY KEY DEFAULT true
                            CHECK (singleton),
    -- The provider's discovery document (…/.well-known/openid-configuration).
    -- HTTPS is required by the API; http:// is refused except for loopback,
    -- which exists so a developer can point at a local Keycloak.
    discovery_url           TEXT NOT NULL,
    client_id               TEXT NOT NULL,
    client_secret_encrypted TEXT,
    -- Where the provider sends the browser back. Must match what is
    -- registered at the provider exactly, including scheme and path.
    redirect_uri            TEXT NOT NULL,
    -- The claim carrying the user's groups/roles. Entra ID and Keycloak
    -- commonly use 'groups'; Okta often 'groups'; Google Workspace has no
    -- group claim by default, which is why this is configured and never
    -- guessed.
    groups_claim            TEXT NOT NULL DEFAULT 'groups',
    -- The claim carrying the human-readable username. Entra ID: 'preferred_
    -- username' or 'upn'; Keycloak: 'preferred_username'. Configured, not
    -- assumed.
    username_claim          TEXT NOT NULL DEFAULT 'preferred_username',
    -- Stated clock-skew tolerance for exp/iat/nbf, in seconds. A real value
    -- with a real default rather than a library default nobody can name.
    clock_skew_seconds      INTEGER NOT NULL DEFAULT 120
                            CHECK (clock_skew_seconds BETWEEN 0 AND 600),
    -- PEM bundle for an agency behind a TLS-inspecting proxy. NULL = the
    -- system trust store. There is deliberately no "skip verification".
    ca_bundle_path          TEXT,
    -- What the sign-in button says. Agencies call it different things
    -- ("Sign in with County SSO"), and a wrong label is a support call.
    button_label            TEXT NOT NULL DEFAULT 'Sign in with single sign-on',
    -- OIDC is OFF until an admin turns it on, and turning it off is always
    -- available. Local accounts are unaffected either way.
    is_enabled              BOOLEAN NOT NULL DEFAULT false,
    updated_by              TEXT NOT NULL,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE auth.oidc_provider IS
    'The single OIDC provider configuration (ADR-0011). The client secret is '
    'AES-256-GCM ciphertext; the key lives in the environment or a 0600 file, '
    'never in this database. Never served back by any endpoint.';

-- ---------------------------------------------------------------------------
-- 3. The claim -> role mapping — EXPLICIT, audited, and deny-by-default
-- ---------------------------------------------------------------------------
--
-- A row here says: "a user whose group claim contains this exact value gets
-- this Headway role". Nothing else grants anything.
--
--   * An UNMAPPED claim grants NOTHING — not viewer, not read-only, nothing.
--     A user whose groups match no row is refused sign-in and no account is
--     created. Deny-by-default is the whole design: guessing that a claim
--     called "Transit-Viewers" probably means `viewer` is how an IdP group
--     nobody audited turns into access nobody granted.
--   * Matching is EXACT and case-sensitive on the claim value. No prefixes,
--     no globs, no regular expressions — a pattern language here is a place
--     for a mistake to hide, and Entra ID emits opaque group object GUIDs
--     anyway, which are exact by nature.
--   * If a user's claims match SEVERAL rows, the API takes the LEAST
--     privileged of them (services/api/headway_api/routers/oidc.py). Union
--     of privilege would let adding someone to one more directory group
--     silently escalate them.
--
-- THE IdP MAY NOT GRANT certifying_official. This is the wave's central
-- security decision and it is enforced in three independent places: this
-- CHECK constraint, the mapping API's validation, and the login path itself
-- (which re-checks rather than trusting the row it read).
--
-- Why: certification is a legal attestation that figures submitted to the
-- federal government are correct, signed with the installation's Ed25519 key
-- and defensible in a triennial review. Making it reachable through a group
-- membership means the set of people who can sign a federal submission is
-- edited in a directory Headway does not control, by administrators Headway
-- cannot see, with no record in Headway's audit trail of the change. An
-- agency IT admin adding a colleague to a group would grant the power to
-- certify without anyone in the transit department knowing. So the ability
-- to certify is granted only inside Headway, by an existing certifying
-- official, through POST /users/{username}/role, audited with who/when/
-- from-what-to-what.
--
-- The consequence is stated honestly and is small: a federated certifying
-- official signs in with the IdP (so MFA, offboarding and password policy
-- still live in the directory) and has their certifying role granted once,
-- locally. Authentication is federated; authorization for the highest-
-- consequence action is not.
--
-- The mirror rule lives in the login path: the IdP can neither GRANT nor
-- REVOKE certifying_official. A mapping resolving to `viewer` for someone who
-- holds certifying_official locally does NOT demote them — otherwise removing
-- a group membership in the directory would revoke the ability to certify,
-- which is the same control by the other hand, and could strand an agency
-- with nobody able to certify (the migration-0032 lockout fail-safe).

CREATE TABLE auth.oidc_role_mappings (
    mapping_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- The exact value expected inside the configured groups claim.
    claim_value  TEXT NOT NULL UNIQUE,
    headway_role TEXT NOT NULL
        CHECK (headway_role IN ('viewer', 'data_steward', 'report_preparer',
                                'auditor')),
    -- Free-text so an admin can write "Finance team — read only" beside an
    -- Entra ID group GUID that means nothing to a human.
    note         TEXT,
    created_by   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE auth.oidc_role_mappings IS
    'Explicit IdP-claim -> Headway-role grants. An unmapped claim grants '
    'nothing. certifying_official is absent from the CHECK on purpose: it is '
    'granted only locally inside Headway (handoff 0046).';

-- ---------------------------------------------------------------------------
-- 4. In-flight authorization requests — state, nonce, PKCE verifier
-- ---------------------------------------------------------------------------
--
-- One row per started sign-in, deleted or consumed when it finishes. This is
-- the server side of four separate defences:
--
--   * CSRF / login-fixation — `state` is 32 bytes of CSPRNG randomness that
--     the API generated and remembers. A callback carrying a state the API
--     never issued is refused.
--   * REPLAY — SINGLE USE, enforced by
--     `UPDATE ... WHERE consumed_at IS NULL RETURNING`, so two concurrent
--     callbacks with the same state cannot both win. The second gets the same
--     generic refusal as a forged one.
--   * ID-TOKEN REPLAY — `nonce` is carried into the authorization request and
--     must come back inside the ID token. A token minted for a different
--     sign-in does not match.
--   * BINDING TO THE BROWSER SESSION — Headway's SPA holds a bearer token,
--     not a cookie, so there is no cookie to bind `state` to. Instead the
--     API mints a high-entropy `browser_token`, returns it to the browser
--     (which keeps it in sessionStorage for the duration of the redirect),
--     and stores only its SHA-256 here. The callback must present the
--     matching token. An attacker who tricks a victim's browser into
--     replaying the attacker's authorization response does not have the
--     victim's browser_token, so the callback is refused — this is the
--     no-cookie equivalent of state-bound-to-session.
--
-- SESSION FIXATION: this row is the entire pre-login session, and it is
-- CONSUMED at the moment a session token is issued. The bearer token handed
-- back is freshly minted with its own jti; nothing the browser held before
-- signing in carries any authority afterwards.
--
-- code_verifier is the PKCE (RFC 7636) verifier. It is stored server-side and
-- never leaves the API, so an authorization code intercepted in the redirect
-- cannot be exchanged by anyone else. Authorization Code + PKCE only; the
-- implicit flow is never used.
--
-- Rows expire (expires_at, minutes) and are swept on each start; the table
-- stays small by construction.

CREATE TABLE auth.oidc_login_states (
    state           TEXT PRIMARY KEY,
    nonce           TEXT NOT NULL,
    code_verifier   TEXT NOT NULL,
    -- SHA-256 hex of the browser_token handed to the browser. The token
    -- itself is never stored, exactly like a machine API key (migration
    -- 0013): possession is proved, not filed.
    browser_binding TEXT NOT NULL,
    redirect_uri    TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    consumed_at     TIMESTAMPTZ
);

CREATE INDEX oidc_login_states_expiry ON auth.oidc_login_states (expires_at);

COMMENT ON TABLE auth.oidc_login_states IS
    'In-flight OIDC authorization requests: state, nonce, PKCE verifier and '
    'the browser binding. Single-use — consumed_at is set by a conditional '
    'UPDATE so a replayed state loses the race.';
