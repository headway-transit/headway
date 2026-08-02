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
