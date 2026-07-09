# ADR-0004: Multi-Tenancy — Database-Per-Agency Default, Instance-Per-Agency Tier

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

Headway ships in two shapes from one codebase: a single-agency on-prem deploy an IT generalist runs on a box, and a hosted multi-agency service.

The hosted service serves cash-strapped public agencies, so it must amortize shared infrastructure to keep the price floor low — but it holds government fleet data, so tenant isolation is a security boundary, not a convenience. Crucially, the schema must be identical on-prem and hosted (Constraint 4 parity), and an agency must be able to graduate from hosted to self-hosted without a migration nightmare. How we partition tenants determines the blast radius of a bug, the price floor, and portability all at once.

## Decision Drivers

- Economics: amortize shared platform/broker/compute to keep hosted affordable for small agencies.
- Isolation: government data; a tenant boundary breach is a serious incident.
- On-prem / hosted parity: the hosted schema must equal the single-tenant on-prem schema.
- Data portability / anti-lock-in: an agency must be able to leave with its data.
- Postgres operational ceilings on databases and connections per cluster.

## Considered Options

- **Shared database + tenant_id column + row-level security (RLS)** — rejected as default (see below).
- **Database-per-agency on shared platform/broker/compute** — isolation without a full stack per tenant.
- **Instance-per-agency (dedicated namespace + full stack) for everyone** — maximal isolation, too costly as the default.

## Decision Outcome

Chosen option: "Database-per-agency as the default, with instance-per-agency as a paid isolation tier", because it isolates each agency in its own Postgres database while sharing the expensive platform/broker/compute layers — cheap enough for a low price floor, isolated enough for government data.

The schema stays tenant_id-FREE and therefore identical to the on-prem single-tenant schema, satisfying parity; the per-agency database becomes the natural unit of backup, restore, migration, and "graduate to self-hosted" export, satisfying portability. A full instance-per-agency (dedicated namespace and stack) is offered as a paid tier for agencies with a hard FedRAMP or isolation-boundary requirement.

Shared-DB-plus-RLS was rejected as the default: fleet-scale telemetry makes tenants noisy neighbors in one database, a single RLS misconfiguration is a cross-agency breach, and a tenant_id column would smear across the on-prem build where it is permanently inert — breaking parity for no benefit.

### Consequences

- Good — strong per-tenant isolation and blast-radius containment without a full stack per agency.
- Good — identical schema on-prem and hosted; clean per-agency export path.
- Bad / cost — the shared control plane (auth, routing, orchestration) remains a shared attack surface across tenants.
- Bad / cost — Postgres has practical ceilings on databases and connections per cluster, so one cluster does not scale to arbitrarily many agencies.
- Mitigation — per-agency credentials and encryption keys so a control-plane compromise does not hand over tenant data wholesale.
- Mitigation — shard agencies across multiple Postgres clusters at the hundreds-of-agencies scale; offer the instance-per-agency tier where a hard boundary is required.

## Links

- Relates to ADR-0005 (same artifacts deploy the single-box and the multi-tenant hosted stack).
- Governs role files: Platform/Infrastructure, Security/Compliance, Backend/API.
