# Headway Role System

Headway is built by specialized Claude Code sessions, each operating under a single **role**. A role file is a governing contract: it defines what that role owns, the technologies it uses, who it hands off to, its definition of done, its guardrails, the domain knowledge it must hold, and its first 90 days of work. Roles keep parallel sessions coherent, prevent overlapping ownership, and make every session accountable to the same non-negotiable constraints.

## How to invoke a role

Start a Claude Code session with:

> **Assume the role defined in `.claude/roles/{FILE}` and its shared constraints.**

The session must first read `.claude/roles/_SHARED_CONSTRAINTS.md` in full, then the named role file. `_SHARED_CONSTRAINTS.md` is binding on every role — it holds the eight non-negotiable constraints (expanded with violation/correct examples), the canonical terminology, the common Definition of Done, the anti-hallucination rule for regulatory facts, and the inter-role handoff format. Where a role file and the shared constraints appear to conflict, the shared constraints win; raise the conflict as an open question in a handoff document rather than resolving it silently.

## The rule of handoffs

**Cross-role work requires an explicit handoff document.** No role begins work that depends on another role's output based on a verbal, implied, or inferred handoff. Handoffs are markdown files under `docs/handoffs/`, named `NNNN-from-<role>-to-<role>-<slug>.md`, with these sections: **Context**, **Inputs**, **Outputs**, **Open Questions**, and **Verification Evidence**. The receiving role appends a `## Response` accepting the contract or raising blockers. Interface or schema changes after a handoff require a new handoff, not an edit-in-place. The exact template is in `_SHARED_CONSTRAINTS.md`.

## The two rules that override everything

1. **AI never computes a reported number.** Every regulatory figure originates only in the deterministic, versioned, unit-tested calculation library. AI features analyze computed results, cite their source records, are labeled AI-generated, and require human review.
2. **Verification before assertion.** No role reports a task complete by inference. State is verified against the live repository, test suite, and running services — with evidence — before any completion claim.

## Ratified architecture decisions

Cross-cutting technical choices are recorded as Architecture Decision Records (MADR format) under [`docs/adr/`](../../docs/adr/), owned by the Platform Architect. A role must not silently contradict an accepted ADR; propose a change via the ADR process (recorded as a handoff) instead. The ratified set:

| ADR | Decision |
| --- | --- |
| 0001 | Core license: Apache-2.0; OSI-approved-only dependency policy + CI license gate |
| 0002 | Message broker: Apache Kafka (KRaft) default; Redpanda (BSL) documented opt-in swap only |
| 0003 | Canonical data model: TIDES-compatible hybrid (bespoke reporting-first core; TIDES adopted where it maps, tracked as input adapter + alignment target) |
| 0004 | Multi-tenancy: database-per-agency default (tenant_id-free schema; per-agency DB = backup + portability unit) + instance-per-agency isolation tier; shared-DB+RLS rejected |
| 0005 | Deployment: Compose-primary + Helm parallel; parity unit = identical images + one config schema; CI parity gate boots both and asserts identical behavior |
| 0006 | Connector contract: uniform Kafka-producer wire contract + Apicurio (Apache-2.0) schema registry as the single connector boundary & certification surface |
| 0007 | Lineage: explicit lineage graph (provenance edge tables); "explain this number" is a graph traversal |
| 0008 | Language policy: polyglot by layer — Python (calc/AI/transform), Go (streaming/ingestion + hot paths), TypeScript (frontend), Python/FastAPI (API) |
| 0009 | First vertical slice: walking skeleton — VRM/VRH from GTFS-RT + GTFS static |
| 0010 | Repo topology: monorepo with a published `contracts/` directory (versioned artifacts; vendors pin the published contract, never the repo) |
| 0011 | Identity: native OIDC relying party + local accounts in the API; Keycloak as an optional Compose/Helm profile (SAML-only IdPs / IdP aggregation) |

## Roles

| File | Role | Core ownership |
| --- | --- | --- |
| [`_SHARED_CONSTRAINTS.md`](_SHARED_CONSTRAINTS.md) | *(binding on all)* | Eight constraints, terminology, common Definition of Done, handoff format |
| [`PLATFORM_ARCHITECT.md`](PLATFORM_ARCHITECT.md) | Platform Architect | System boundaries, ADRs, data-model governance, license compliance, on-prem/cloud parity enforcement |
| [`INGESTION_ENGINEER.md`](INGESTION_ENGINEER.md) | Ingestion Engineer | Connector framework, source adapters, backpressure, replay, raw-record immutability |
| [`DATA_ENGINEER.md`](DATA_ENGINEER.md) | Data Engineer | Normalization to the canonical model, TimescaleDB schema, lineage, DQ rule engine, transformation layer |
| [`NTD_COMPLIANCE_ENGINEER.md`](NTD_COMPLIANCE_ENGINEER.md) | NTD & Compliance Engineer | Deterministic NTD calculation library, sampling, edit-check validation, submission packages, regulatory change tracking |
| [`AI_SYSTEMS_ENGINEER.md`](AI_SYSTEMS_ENGINEER.md) | AI Systems Engineer | Anomaly detection, DQ triage, grounded narrative + NL query with mandatory citations, grounding eval harness |
| [`BACKEND_ENGINEER.md`](BACKEND_ENGINEER.md) | Backend Engineer | REST + webhook API, RBAC + multi-tenancy, audit logging |
| [`FRONTEND_ENGINEER.md`](FRONTEND_ENGINEER.md) | Frontend Engineer | Dashboards, DQ resolution UI, report review/certification UI, WCAG 2.1 AA, plain language |
| [`DEVOPS_ENGINEER.md`](DEVOPS_ENGINEER.md) | DevOps / Platform Engineer | Docker Compose + Helm paths, gov-cloud reference architecture, SBOM/supply-chain, upgrade tooling |
| [`SECURITY_ENGINEER.md`](SECURITY_ENGINEER.md) | Security Engineer | 800-53-aligned controls, SSO/OIDC, secrets, threat model, dependency + container scanning |
| [`QA_ENGINEER.md`](QA_ENGINEER.md) | QA Engineer | Test strategy, golden-dataset regression per NTD calc, connector conformance, fleet-scale load testing |
| [`DOCS_ENGINEER.md`](DOCS_ENGINEER.md) | Documentation Engineer | Install/ops guides, connector docs, "explain this number" provenance docs, contributor onboarding |
| [`COMMUNITY_MAINTAINER.md`](COMMUNITY_MAINTAINER.md) | Community Maintainer | Contribution standards, RFC process, connector certification program, release notes, anti-capture governance |

## Ownership boundaries at a glance

The pipeline runs **ingest → normalize → calculate → serve → review/certify**, with governance, security, delivery, testing, docs, and community wrapped around it:

- **Ingestion** lands immutable raw records → **Data** normalizes them into the canonical model with lineage and DQ issues → **NTD & Compliance** computes every reported number deterministically from canonical tables → **Backend** serves those numbers (with provenance) behind authz + audit → **Frontend** shows them for human review and certification.
- **AI Systems** sits *on top of* computed results — never inside the number.
- **Platform Architect** governs boundaries and the canonical-model spec; **Security** and **DevOps** enforce posture and parity across the whole thing; **QA** proves it; **Docs** explains it; **Community** governs how it grows without single-vendor capture.

Any two roles that touch the same interface resolve it through the Platform Architect's ADR process, recorded as a handoff.
