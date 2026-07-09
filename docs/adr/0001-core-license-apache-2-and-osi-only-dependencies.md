# ADR-0001: Core License Apache-2.0 and OSI-Only Dependency Policy

- Status: Accepted (amended 2026-07-08 — dependency license tiers, see Amendment 1)
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

Headway is meant to be the single source of truth for an agency's fleet and the substrate for FTA National Transit Database reporting. That role only holds if the platform is genuinely open: an agency, a competing vendor, or a state DOT must be able to run, inspect, fork, and self-host the core without asking anyone's permission and without a proprietary service on the critical path.

A permissive license also has to protect the connector and embedder ecosystem — copyleft on the core would contaminate downstream integrators. And we want one umbrella licensing rule that later component choices (broker, schema registry, geocoder) simply inherit, rather than re-litigating "is this open enough?" for every component.

## Decision Drivers

- Constraint 3 (open-source core, permissive license) and Constraint 4 (on-prem parity) are non-negotiable.
- Anti-vendor-capture: no single company may hold a chokepoint on a core capability.
- Ecosystem safety: connectors and embedders must be linkable under any license, including proprietary.
- Source-available is not open-source: attractive tools ship under licenses (BSL, Confluent Community License) that are NOT OSI-approved.
- Enforceability: the policy must be machine-checkable, not a matter of good intentions.

## Considered Options

- **Apache-2.0 core + OSI-only dependency gate** — OSI-approved, permissive, explicit patent grant and contribution terms.
- **MIT / BSD-2/3-Clause core** — permissive and simple, but no patent grant, which matters for shared civic infrastructure.
- **Copyleft core (GPL/AGPL)** — rejected: copyleft contaminates connectors and embedders, breaking the ecosystem goal.

## Decision Outcome

Chosen option: "Apache-2.0 core with an OSI-only dependency policy enforced in CI", because Apache-2.0 is OSI-approved and permissive and — unlike MIT/BSD — carries an explicit patent grant and contribution terms that matter for a civic-infrastructure project with many contributors.

No core capability may depend on a non-OSI-approved or proprietary service on the critical path; proprietary providers may exist only as optional, off-critical-path adapters. A CI license gate scans the full dependency tree and fails the build on any dependency whose license is not on the OSI-approved allowlist. Source-available licenses that are not OSI-approved — notably the Business Source License (Redpanda) and the Confluent Community License (Confluent Schema Registry) — are treated as non-OSI and cannot be defaults; this ruling directly drives ADR-0002 and ADR-0006.

### Consequences

- Good — one machine-enforced rule closes the "is this open enough?" question for every downstream component.
- Good — the patent grant and permissive terms keep the connector/embedder ecosystem unencumbered.
- Good — the core stays forkable and self-hostable, satisfying the anti-single-vendor-capture goal.
- Bad / cost — best-in-class tools (Redpanda, Confluent Schema Registry) are excluded as defaults purely on license grounds, sometimes costing ergonomics or performance headroom.
- Bad / cost — the CI license gate needs a curated allowlist kept current as upstream projects relicense.
- Mitigation — allow excluded tools as documented, self-hosted opt-in swaps behind the same interface, never on the default critical path.
- Mitigation — treat the OSI list plus a short reviewed exceptions file as the source of truth, and re-review on dependency bumps.

## Amendment 1 — Dependency license tiers (2026-07-08)

The walking-skeleton build surfaced the first concrete case the original text under-specified: `psycopg` (the standard PostgreSQL Python driver) is **LGPL-3.0-with-exception** — OSI-approved, but weak-copyleft rather than permissive. The gate policy is therefore clarified into three tiers:

1. **Headway's own code (core):** Apache-2.0. Non-negotiable; unchanged.
2. **Dependencies — permissive (Apache-2.0, MIT, BSD, ISC, and equivalents):** allowed without ceremony. This is the default expectation.
3. **Dependencies — weak-copyleft (LGPL, MPL-2.0, EPL-class):** allowed as ordinary, *unmodified, dynamically-linked/imported library* dependencies, each entry recorded in the CI gate's reviewed allowlist file with a one-line rationale. Copying their source into the Headway tree, or modifying and vendoring them, is NOT covered by this tier and requires a new ADR-level decision.
4. **Strong copyleft (GPL, AGPL) and all non-OSI licenses (BSL, Confluent Community License, SSPL, proprietary):** excluded from the core critical path. Documented, self-hosted opt-in swaps remain permitted per the original Mitigation.

Precedent entries for the allowlist: `psycopg` (LGPL-3.0-with-exception; unmodified driver import; the standard PostgreSQL adapter for Python). The CI license gate implements exactly these tiers: permissive passes, weak-copyleft passes only if allowlisted, everything else fails the build.

## Links

- Relates to and governs ADR-0002 (broker license call) and ADR-0006 (schema-registry license call).
- Governs role files: PLATFORM_ARCHITECT, DEVOPS_ENGINEER, SECURITY_ENGINEER, COMMUNITY_MAINTAINER, and every connector-producing role.
