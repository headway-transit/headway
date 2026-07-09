# ADR-0011: Identity — Native OIDC Relying Party + Local Accounts; Keycloak as Optional Profile

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement
Certification actions must be authenticated, authorized, and audit-logged from the first walking-skeleton release — there is no bootstrap exception to that guardrail. The shared constraints require SSO via OIDC/SAML with support for Entra ID, Google, Okta, and local accounts. A bundled Keycloak-class broker satisfies that but adds a second JVM (beside Kafka, ADR-0002) to the small-agency single box, straining the affordability constraint. How does identity ship in the default stack?

## Decision Drivers
- The single-box Compose footprint a small agency can afford (Constraint 4); Kafka already claims the largest share.
- Entra ID, Google, and Okta are all standards-compliant OIDC providers — a native relying party reaches all three without a broker.
- The certification UI needs working authn/authz on day one (ADR-0009).
- An IT generalist must be able to operate the default stack; Keycloak administration is a skill of its own.

## Considered Options
- **Native OIDC relying-party support + local accounts in the API; Keycloak as an optional profile** (chosen)
- Bundle Keycloak from day one — one auth path forever including SAML, but a second JVM and broker ops on every small-agency box.
- A lighter bundled broker (Ory/Authentik/Dex-class) — smaller than Keycloak but uneven SAML support and enterprise maturity; would require verification before commitment.

## Decision Outcome
Chosen option: **native OIDC + local accounts**, because it gives every named IdP (Entra ID, Google, Okta — all OIDC) plus local accounts with zero additional infrastructure on the default box, and defers the broker to the deployments that actually need it.

- The API implements a standards-based **OIDC relying party** (authorization-code + PKCE; verify flow details against the current published OIDC specifications — never from memory) and **local accounts** with modern password hashing, both producing one normalized internal claim set consumed by RBAC (Backend).
- **Keycloak ships as an optional Compose/Helm profile** — enabled by agencies that need SAML-only IdPs or IdP aggregation. When enabled, the API simply treats Keycloak as its OIDC provider; the native RP code path is unchanged.
- The Security Engineer still owns the identity design, the claim-set contract, and review of the RP implementation; SAML support lives in the Keycloak profile rather than in core API code.

### Consequences
- Good — no second JVM on the small box; the walking skeleton has real, standards-based auth from day one; local accounts work fully offline/air-gapped.
- Bad / cost — the API owns more security-critical auth code than a broker delegation would; SAML requires enabling the optional profile.
- Mitigation — the RP implementation uses a well-maintained, permissively-licensed OIDC library (verify license per ADR-0001) rather than hand-rolled flows; Security Engineer review + tests are gating; the claim-set contract is identical with and without the broker, so enabling Keycloak later is config, not code.

## Links
- Relates to ADR-0001, ADR-0002 (footprint), ADR-0005 (optional profile packaging), ADR-0009; governs role files SECURITY_ENGINEER, BACKEND_ENGINEER, DEVOPS_ENGINEER.
