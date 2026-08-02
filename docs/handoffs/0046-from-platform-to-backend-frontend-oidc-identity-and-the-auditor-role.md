# Handoff: platform → backend+frontend — OIDC identity + the auditor role

## Context

**ADR-0011 decided this two months ago and it was never built.** The decision:
a **native OIDC relying party plus local accounts** in the API, with Keycloak as
an optional profile — because Entra ID, Google and Okta are all standards
compliant, so a relying party reaches all three without putting a second JVM
beside Kafka on a small agency's single box.

What exists today is an **honest card in the admin area** that says single
sign-on is designed and not yet built (`AdminView.tsx`). That card has been
telling the truth for weeks. This wave makes it obsolete.

**It is pre-production blocking**, and the project lead has named it as such.
The partner agency runs Microsoft Entra ID, so it is a real requester with a
real deadline, not a checkbox. An agency that cannot put Headway behind its own
identity provider cannot put Headway in front of its staff: account lifecycle,
offboarding, and MFA all live in the IdP, and a compliance system whose accounts
are managed separately from the agency's directory is an audit finding in
itself.

**This wave also adds the `auditor` role**, because a role is worth adding once,
alongside the identity work that has to map claims onto roles anyway, rather
than twice. Handoff 0045 (the submission audit module) depends on it for its
outward-facing view.

## Design (binding)

### 1. Local accounts survive, permanently

OIDC is added **beside** local accounts, never instead of them. Reasons, all
load-bearing:

- **On-prem parity.** An installation with no internet, or an IdP outage, must
  still be operable. Headway is deployed on single boxes at small agencies.
- **Break-glass.** There must always be a way in when the IdP is misconfigured —
  and the first OIDC configuration attempt *will* be misconfigured.
- **`install.sh --reset-admin-password` must keep working** for the local admin.

An installation that never configures OIDC loses nothing.

### 2. Certification actions keep their guardrail, whoever authenticated

The shared constraint is that certifying actions are authenticated, authorized
and audit-logged with no bootstrap exception. Under SSO the audit trail must
record **who signed** with at least the fidelity it has today — the IdP subject
and the Headway username, not just "an SSO user". A signature whose signer
cannot be resolved years later is not a signature. The Ed25519 signing ceremony
(handoff 0019) is unchanged; only the authentication in front of it changes.

### 3. Role mapping is EXPLICIT, never inferred

Headway roles are `viewer` → `data_steward` → `report_preparer` →
`certifying_official` (an escalating rank in `authz.py`), plus `auditor` from
this wave.

- Mapping from IdP claims (group/role claim) to Headway roles is **configured by
  an admin and recorded**, never guessed from claim names that happen to look
  familiar.
- **An unmapped claim grants nothing.** Deny-by-default; a user whose groups map
  to no Headway role gets no access, not `viewer`.
- **The IdP may not silently escalate anyone to `certifying_official`.** Signing
  a federal submission is the highest-consequence action in the product;
  granting it must be a deliberate, audited act inside Headway. (Open question
  below: whether that role is *only* ever grantable locally.)
- Every mapping change is audited: who changed it, when, from what to what.

### 4. The `auditor` role

A role that can **read everything and change nothing**: figures, receipts,
lineage, raw records (subject to the existing sensitivity rules — migration 0028
withholding still applies, and an auditor is not an exception to rider privacy),
DQ findings, certifications, and the audit trail itself. It cannot compute,
classify, resolve, certify, or configure.

Where it sits in the rank order needs care: it is not simply "above
`certifying_official`" — it is a **different axis** (breadth of read, zero
write). Model it explicitly rather than forcing it into the existing ladder, or
an auditor will inherit write permissions from rank comparison.

### 5. The OIDC mechanics that actually bite

Non-negotiable, and where security-sensitive review should concentrate:

- **Authorization Code flow with PKCE.** No implicit flow.
- **`state` and `nonce` validated**, single-use, bound to the browser session.
- **ID token validation in full**: signature against the provider's JWKS,
  `iss`, `aud`, `exp`/`iat` with a stated clock-skew tolerance, and **key
  rotation handled** (cached JWKS with refresh, not a pinned key that breaks at
  the provider's next rotation).
- **Session fixation**: a new session identifier is issued on login; the
  pre-login session is discarded.
- **Discovery document and JWKS fetched over TLS**, with an explicit trust store
  story for an agency behind a TLS-inspecting proxy — this is exactly the
  environment Headway runs in, and it is where OIDC integrations fail in
  practice.
- **Generic failure messages**: a failed login must not reveal whether an
  account exists, matching the existing no-leak behaviour.
- Login attempts audited, successful and failed, with the same
  failure-audit coalescing as `machine_auth.py` (handoff finding F1) so an
  unauthenticated actor cannot amplify writes into `audit.events`.

### 6. Provisioning

Just-in-time provisioning on first successful login **only for claims that map
to a configured role** — an unmapped user is refused and nothing is created.
Deactivation follows the existing `is_active` path; the last-admin lockout
protection (migration 0032) still applies and must be tested against the SSO
path, not only the local one.

### 7. The admin surface

The honest SSO card becomes a real configuration screen: provider discovery URL,
client id, client secret (**stored encrypted at rest / show-once**, sharing the
at-rest key work already queued for the Admin→Integrations wave), the claim to
read for groups, the claim→role mapping table, and a **"test this configuration"
action that proves the round trip before anyone depends on it.** Written for a
zero-SQL reader: the error messages here are the difference between a working
integration and a support call.

## Outputs

Native OIDC relying party (PKCE, full ID-token validation, JWKS rotation) +
local accounts preserved + explicit audited claim→role mapping + the `auditor`
role modelled on its own axis + JIT provisioning that refuses unmapped users +
the admin configuration screen with a test action + encrypted-at-rest client
secret; tests at every layer including negative tests (bad `iss`, bad `aud`,
expired token, rotated key, unmapped claim, last-admin lockout via SSO);
live-verified against a real provider — Entra ID if the partner agency can
supply a test tenant, otherwise a local Keycloak, **and say plainly which one
was used**; docs for an administrator who has never configured OIDC.

Sequence: relying party + local-accounts-preserved first, then role mapping,
then the `auditor` role, then the admin screen.

## Open Questions

- **May the IdP ever grant `certifying_official`,** or must that role always be
  granted locally inside Headway even when authentication is federated?
  (Recommended: grantable only locally — the signature is the product's most
  consequential act and its provenance should not depend on a group membership
  Headway does not control. Needs the project lead's call.)
- **SAML.** ADR-0011 chose OIDC natively with Keycloak as the SAML path. Some
  agencies are SAML-only; is the Keycloak profile a sufficient answer, or does a
  native SAML SP eventually get built?
- **Is `auditor` one role or two** (internal auditor vs external reviewer with
  cross-agency reach)? Handoff 0045's outward view depends on the answer.
- **Session lifetime under SSO** — does Headway honor the IdP's session, keep
  its own, and what happens to a long certification session when the IdP token
  expires mid-ceremony?

---

## Response — backend+frontend (Wave F)

Accepted and built. The honest SSO card is obsolete.

### What shipped

**Migrations 0042–0043.**
- `0042_auditor_role.sql` — admits `auditor` to `auth.users.role`.
- `0043_oidc_relying_party.sql` — `auth.oidc_provider` (one row, client
  secret encrypted at rest), `auth.oidc_role_mappings` (claim → role, with a
  CHECK that cannot hold `certifying_official`), `auth.oidc_login_states`
  (state / nonce / PKCE verifier / browser binding, single-use), and the
  `auth.users` federation columns. `password_hash` becomes NULLABLE with a
  CHECK making the two account shapes mutually exclusive — a federated
  account has no password, and a dummy hash would be a lie a future reader
  could mistake for a credential.

**The relying party** — `services/api/headway_api/oidc.py`. Authorization
code + PKCE (S256) only; the implicit flow is not implemented. Full ID-token
validation: signature against the provider JWKS, `iss`, `aud` (+ `azp` when
multi-audience), `exp`/`iat` with a stated 120-second default skew that is
configurable per provider, `nonce`, and a required `sub`. An **asymmetric-only
algorithm allow-list** applied at the header *before* a key is selected, so
`none` and `HS256`-with-the-public-key never reach a verifier. **JWKS cached
with refresh**, re-fetched on an unrecognized `kid` — that is what a rotation
looks like from here — with the refresh-on-miss rate limited so invented
`kid`s cannot turn Headway into an amplifier pointed at the provider.

**Endpoints** — `services/api/headway_api/routers/oidc.py`:
`GET/POST /auth/oidc/status|start|callback` (unauthenticated),
`GET/PUT /auth/oidc/config`, `POST /auth/oidc/config/test`,
`GET/POST/DELETE /auth/oidc/mappings` (certifying-official only, all audited).

**Encryption at rest** — `services/api/headway_api/secrets_at_rest.py`.
AES-256-GCM with associated data binding a ciphertext to its column; key from
`HEADWAY_SECRET_ENCRYPTION_KEY` / `_KEY_FILE`, the same shape as the Ed25519
signing key. **With no key configured the API refuses to store the secret**
rather than storing it in the clear, and the admin screen says so *before*
the administrator types one.

**The audit trail is now readable** — `GET /audit/events` (new router
`audit_trail.py`), keyset-paginated, auditor and certifying official only.
Without it, "an auditor reads the audit trail" was not true for anyone
without database access, which is every external auditor.

**The admin screen** — `web/src/views/AdminView.tsx`: provider settings,
show-once client secret, the mapping table, and the test action, with every
server refusal shown verbatim at the control that caused it.

**Docs** — `docs/single-sign-on.md`, written for an administrator who has
never configured OIDC and has no SQL.

### The `certifying_official` question — our call, and why

**Recommendation implemented: the IdP may NOT grant `certifying_official`.**
Enforced in three independent places — the CHECK in migration 0043, the
mapping API's validation, and the login path, which re-checks rather than
trusting the row it read (a row can arrive from hand-edited SQL or a restored
backup).

The reason is not tidiness. If a group membership could grant it, the set of
people allowed to sign a federal submission would be edited in a directory
Headway does not control, by administrators the transit department may never
see, with nothing in Headway's audit trail showing the change.

**We also made it non-revocable by the IdP**, which the handoff did not ask
for and which we think is the more important half. If removing a group
membership stripped the certifying role, the directory would still control
who may certify — just by subtraction — and a routine offboarding could
strand an agency with nobody able to certify. So a user holding
`certifying_official` keeps it through an SSO sign-in whose mapping says
otherwise, audited as `sso_role_retained_local`, and that audit record states
whether this was the last active certifying official (the migration-0032
counting query is run on the federated path for exactly that line).

Authentication is federated. Authorization for the highest-consequence action
is not.

### The `auditor` role — modelled on its own axis

`ROLE_RANK` is **unchanged**. `auditor` is not in it, and that is the whole
design: every write gate here is `rank(caller) >= rank(required)`, so a rung
would hand an auditor every write at or below it by arithmetic. Three
enforcement points, none of which a future wave has to remember:

1. **Off the ladder** — `require_at_least` fails it by construction, so an
   endpoint written next month by someone who has never heard of this role is
   already safe from it.
2. **No unsafe HTTP method**, refused in `auth.get_current_identity` — the one
   choke point every authenticated request passes. This deliberately also
   refuses the two read-*shaped* POSTs (`/sandbox/preview`, which computes,
   and `/raw/records/{id}/verify`, which raises a DQ finding). Refusing by
   method with **no allow-list** is what makes the guarantee hold without
   maintenance.
3. **Viewer breadth for content sensitivity** (`authz.may_read_sensitivity`,
   replacing a raw `ROLE_RANK[...]` index in `raw_records.py` that would have
   raised `KeyError` for an off-ladder role). **Migration 0028's rider-location
   withholding is NOT waived** — an auditor cannot open demand-response
   payloads. Rider privacy is not an auditor exception.

The frontend mirrors the same axis in `web/src/auth/session.ts`, so the UI
hides exactly what the API refuses.

### Certification under SSO

The signed canonical document's `certifier` block gains `idp_issuer`,
`idp_subject` and `authenticated_via` **only for a federated signer**. A local
certifier's document is byte-for-byte what it always was, so records signed
before and after this wave stay comparable and no previously signed
certification is retrospectively a different shape. Both identifiers are
inside the signed bytes, so neither can be altered without breaking Ed25519
verification. The handoff-0019 ceremony is otherwise untouched.

### Live verification — Keycloak 26.0, over real TLS. NOT Entra ID.

**Stated plainly: no Microsoft Entra ID test tenant was available, so nothing
here is an Entra ID verification.** The provider used was Keycloak 26.0 in a
disposable Docker container, served over HTTPS with a self-signed CA — which
also let us exercise the trust-store story an agency behind a TLS-inspecting
proxy needs.

`20/20` live checks passed against the real provider, driving a real browser
hop (cookies, Keycloak's own login form, a real 302):

- discovery over TLS with the configured CA bundle; PKCE S256 advertised;
- **the same provider WITHOUT the CA bundle is refused**, with the message an
  administrator would actually see ("inspects encrypted traffic… Certificate
  authority file… will not turn certificate checking off");
- a real authorization code, exchanged with PKCE, and an ID token validated in
  full against the live JWKS;
- the live group claim read and mapped; unmapped claims and an empty mapping
  table both grant nothing; a planted `certifying_official` mapping still
  grants nothing; least privilege wins on multiple matches;
- **negative, against the live provider**: replayed authorization code
  refused, wrong PKCE verifier refused, a genuinely signed live token refused
  against another sign-in's nonce and against a different client id;
- the admin test action's credential probe accepts the real secret and
  catches a wrong one.

**Key rotation, live**: `3/3` — a sign-in, then a new realm RSA key made
active at Keycloak, then another sign-in with a different `kid`, both verified
by the **same running process** with no restart. A pinned key would have
failed the second one.

**What we could not verify:** Entra ID and Okta specifics (group claims as
object GUIDs, `upn` as the username claim, tenant-specific issuer strings) are
handled in code and unit-tested, but not exercised against those products.
Google Workspace emits no group claim by default, so a Google installation
needs the groups configured at the provider first — untested here.

### Coordinator corrections applied

**1. No real-person-shaped fixture identities.** Test identities were renamed
to unmistakably synthetic ones matching the suite's existing convention
(`vera`/`stella`/`petra`/`cora`/`dora`, `certifier`, `dsteward`): the auditor
fixture is `audra`, and the federated ones are `sso.steward`, `sso.official`,
`unmapped.user`, `nearmiss.user`, `dual.mapped`, `deactivated.user`,
`escalation.attempt`. **Convention for future waves: fixture accounts are
role-shaped or role-mnemonic, never "Firstname Lastname".**

**2. A product rename must never require a customer to edit their IdP.**
Audited and confirmed:
- **No group name is hardcoded, defaulted, or seeded anywhere** — no migration
  seeds a mapping, and there is no fallback role, so with zero mappings every
  sign-in is refused whatever the groups are called. Pinned by
  `test_no_group_name_is_built_in_anywhere` (which includes a `headway-*`
  group, to prove even a product-shaped name grants nothing) and
  `test_any_group_name_at_all_can_be_mapped`.
- **The group claim name is configured, not assumed** — the `'groups'` default
  is the OIDC-conventional claim, and an installation using `roles` or `wids`
  configures it. Pinned by `test_the_group_claim_name_itself_is_configurable`.
- **The admin screen's example is obviously an example and says so**
  (`your-directory-group-name` placeholder + "use whatever your groups are
  already called… Headway does not require any particular naming").
- **One externally-visible product-name identifier found and fixed**: the
  credential probe sent `code=headway-configuration-test-…` to the customer's
  identity provider, landing in *their* logs; it is now
  `sso-configuration-test-…`.
- No defaults for client id or redirect URI; scopes are the standard
  `openid profile email`; no cookies; audience is the admin-configured client
  id. Test group fixtures were renamed to directory-style names
  (`transit-data-stewards`, `external-audit-readonly`).
- Left alone deliberately, per instruction: `HEADWAY_*` env vars, the
  `headway_role` API field name, and plain-language UI copy — internal, to be
  renamed centrally.

### Tests

- `cd services/api && python -m pytest -q` → **669 passed** (baseline 522;
  +147). New files: `test_auditor_role.py` (29), `test_oidc_login.py` (41),
  `test_oidc_admin.py` (32), `test_oidc_token_validation.py` (31),
  `test_secrets_at_rest.py` (13), plus a session-fixation test in
  `test_auth.py`.
- `cd web && npx vitest run` → **434 passed** (baseline 411; +23, all in
  `admin-sso.test.tsx`), axe-clean.
- The negative tests the handoff asked for are all present and named: bad
  `iss`, bad `aud`, expired token, token issued in the future, rotated signing
  key, unpublished key, replayed `state`, replayed `nonce`, forged browser
  binding, `alg: none`, `HS256`-with-public-key, unmapped claim, IdP
  escalation to `certifying_official`, last-admin lockout via the SSO path,
  auditor cannot write anywhere, auditor does not see withheld sensitive
  payloads.

### Deferred, and honestly flagged

1. **The "Sign in with…" button is not on the sign-in screen.**
   `web/src/views/LoginView.tsx` is outside this wave's lane, so it was not
   touched. The API is complete and the client functions
   (`getSsoStatus`/`startSsoLogin`/`finishSsoLogin`) are shipped; wiring is a
   one-file follow-up. **The admin screen says this in plain words** rather
   than implying a sign-in flow that is not connected.
2. **`auditor` cannot be granted from the local Users screen** — adding it to
   the `ROLES` tuple in `web/src/views/AdminUsersView.tsx` (one line) is
   outside this lane. The role is grantable today via `POST /users` and via
   SSO mapping.
3. **Session lifetime under SSO** (open question) — unchanged: Headway keeps
   its own 30-minute session and does not track the IdP's. A certification
   ceremony that outlives the Headway token behaves exactly as it did before
   federation. Refresh tokens are not stored.
4. **`auditor` as one role or two** (open question) — shipped as one. Nothing
   here forecloses an external-reviewer variant for handoff 0045.
5. **Native SAML** — not built; ADR-0011's Keycloak profile stands.
6. `GET /users` and `GET /machine/keys` remain certifying-official only; an
   auditor does not see the account roster. Deliberate, and worth revisiting
   if 0045 needs separation-of-duties evidence.

## Coordinator verification — two adversarial reviews (2026-08-02)

Wave F was not merged on its own report. Two independent adversarial reviews
were run against the branch before merge — one on the OIDC token and session
surface, one on whether the `auditor` role can reach a write — alongside the
suites, typecheck, lint, static migration checks, and the integration suite
against a real PostgreSQL with every migration applied to a fresh database.

**The wave's own account held up.** Both reviews confirmed the parts that
matter most: signature verified before any claim is trusted, the asymmetric-
only algorithm allow-list applied at the header so `none` and
HS256-with-the-public-key never reach a verifier, PKCE S256-only with
single-use state consumed by `UPDATE … WHERE consumed_at IS NULL … RETURNING`,
a fresh session on login, deny-by-default claim mapping, AES-256-GCM with a
fresh nonce per call, and `certifying_official` unreachable from the IdP in
three independent places. The auditor review enumerated **all 39 write routes**
and found no path an auditor can reach: the unsafe-method refusal at the
authentication choke point stops it before any role gate runs, and the role's
absence from `ROLE_RANK` fails every rank comparison by construction.

### Fixed before merge

1. **The unauthenticated sign-in surface could starve local login.**
   `/auth/oidc/start` and `/auth/oidc/callback` had no rate limit, discovery
   failures were not cached, and the network budget was 10s. Every endpoint in
   this API is synchronous, so requests waiting on an unreachable provider hold
   worker threads — and the request that must never queue behind them is
   `POST /auth/login`. The break-glass guarantee was logically sound and
   operationally reachable. Now: a dedicated per-IP bucket
   (`sso_requests_per_minute`, separate instance so an SSO flood cannot spend
   the public endpoint's budget), a 15s negative cache on discovery failures,
   and a 4s timeout.
2. **A federated username could forge an audit actor.** JIT provisioning wrote
   the IdP's string into `auth.users.username` and `audit.events.actor` with
   no validation, so a directory that lets a user edit their own `email` claim
   could mint an account named `sso:anonymous` — the exact actor this module
   writes for anonymous failures. Now validated against a rule wide enough for
   UPNs and emails, narrow enough to exclude `:`, whitespace, control and
   zero-width characters, and any reserved actor prefix.
3. **`azp` was only checked when `aud` had more than one entry.** OIDC Core
   3.1.3.7 requires it whenever present; without it, a second client in the
   same tenant able to request Headway's audience could sign its users in.
4. **Clearing the client secret while enabling SSO was permitted.** The guard
   consulted the stored secret as well as the one being written, so
   `{"client_secret": "", "is_enabled": true}` wrote NULL and enabled SSO in one
   statement — degrading a confidential client to a public one, from a screen
   that reported success.
5. **`key_available()` created the at-rest encryption key as a side effect of
   a GET**, and raised `PermissionError` through to a 500 on the read-only
   secret mounts that Docker and Kubernetes normally provide. A read must not
   mint the key every secret is then encrypted under.
6. **Discovery documents could name `http://` endpoints.** The discovery URL
   itself was pinned to HTTPS; the addresses inside it — including the
   `token_endpoint` the client secret is sent to — were not.
7. **Local login was a username-existence oracle by timing** (~240ms for a
   real local account, immediate otherwise). Pre-existing for missing rows;
   this wave added a second fast path for federated accounts. Both now cost a
   full bcrypt round. The message was always generic; the clock was not.
8. **Reading the audit trail was the one unlogged read in the system.** An
   oversight surface that can be swept invisibly lets the reviewed party watch
   the reviewer. Now audited with the filters and the row count.
9. **The full webhook URL was written into `audit.events`.** Harmless while
   that table needed database access to read; the `auditor` role is the first
   credential that reads it over HTTP, and for Slack, Teams and Zapier
   receivers the URL *is* the credential. Now the origin only — which is what
   this module's own rule, stated ninety lines above the offending line,
   already required.
10. **`require_certifying_official` refused 26 endpoints with a message about
    certifying**, only six of which certify — so `GET /users` told the reader
    they could not certify figures. Also `role_label` rendered "a auditor".

`services/api/openapi.json` was also regenerated: the wave added eight
endpoints and left the published integration contract describing the API
without them (ADR-0006), which CI would have caught.

### Accepted as the wave shipped them

- **The `certifying_official` non-revocation decision.** Escalated by the wave
  as beyond its brief, and correct: if a group membership could strip the role,
  the set of people who may sign a federal submission would still be controlled
  from the directory, by subtraction. The brief specified the grant half only;
  the wave found the mirror and reasoned it out. Ratified.
- **`auditor` does not read the account roster** (deferred item 6). The wave
  decided this deliberately and disclosed it. Left as shipped — 0045 is where
  separation-of-duties evidence will say whether it needs revisiting. Only the
  refusal messages were wrong, and those are fixed.

### Still open

- **Failure-audit throttling buckets on `request.client.host`**, which behind
  the documented reverse proxy is one value for every user, so a flood of
  forged callbacks can suppress the record of genuine failures sharing a reason
  for the 60s window. The same argument that gave OIDC its own throttle
  instance applies inside the OIDC surface.
- **A demotion to `auditor` is not immediate** — the target's existing token
  keeps its old role until expiry (30 min). Disclosed in the response body; no
  revocation list exists.
- **The single-use state `UPDATE` is exercised only against the in-memory fake.**
  The SQL reads correctly and the semantics are right, but no test proves the
  concurrency claim on a real engine. The integration suite is where that
  belongs.
