# ADR-0010: Repository Topology — Monorepo with a Published `contracts/` Directory

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement
The nine founding ADRs fixed a polyglot platform (Go ingestion, Python calc/API/AI/transform, TypeScript frontend — ADR-0008) whose connector boundary is a public wire contract (ADR-0006) that third-party vendors must build against without core commit access. The first deliverable is a walking skeleton that touches every layer at once (ADR-0009). Where does the code live?

## Decision Drivers
- The walking skeleton (and most early work) is cross-layer; coordinated multi-repo PRs are heavy for a small founding team.
- A schema change and all of its consumers should be reviewable and mergeable atomically.
- Vendors certifying connectors must be able to pin the wire contract without cloning or tracking the platform repo.
- One CI pipeline must produce the same artifacts for Compose and gov-cloud (ADR-0005).

## Considered Options
- **Monorepo with a top-level `contracts/` directory, published as versioned artifacts** (chosen)
- Monorepo plus a separate `headway-contracts` repo — cleanest vendor optics, but every schema change becomes a two-repo dance and the skeleton spans two repos on day one.
- Polyrepo by service — independent versioning, but cross-cutting changes need N coordinated PRs; rejected for a small team and a cross-layer first deliverable.

## Decision Outcome
Chosen option: **monorepo with `contracts/`**, because atomic cross-layer changes, a single CI, and one landing place for the walking skeleton outweigh the ceremony costs — and the vendor need is met by *publishing* `contracts/` as versioned artifacts (schema-registry artifacts + tagged releases), so vendors pin the published contract, never the repo.

Canonical top-level layout (paths referenced by the role files):

```
headway/
  contracts/        # wire-contract schemas; published versioned (ADR-0006)
  services/
    ingestion/      # Go: connector runtime, SDKs, first-party connectors
    transform/      # Python: normalization + dbt project
    calc/           # Python: deterministic calculation library
    api/            # Python: FastAPI backend
    ai/             # Python: AI layer + grounding eval harness
  web/              # TypeScript/React frontend
  db/               # schema + migrations (incl. lineage graph, ADR-0007)
  deploy/
    compose/        # source-of-truth single-box stack (ADR-0005)
    helm/           # first-class parallel target (ADR-0005)
  security/         # control mapping, threat model, SSO config
  docs/             # docs site, adr/, handoffs/
  tests/            # cross-service suites: golden, conformance, parity
```

### Consequences
- Good — one PR can change a contract and every consumer; one CI; trivial onboarding (`git clone`, one repo).
- Good — the certification surface is the *published artifact*, decoupling vendors from repo history.
- Bad / cost — per-language tooling discipline required in one tree (Go module/workspace, uv/poetry, pnpm) and CI must path-filter to keep builds fast.
- Mitigation — language-scoped directories own their toolchain files; CI triggers by path; `contracts/` publishing is automated on tag.

## Links
- Relates to ADR-0005, ADR-0006, ADR-0008, ADR-0009; governs role files PLATFORM_ARCHITECT, INGESTION_ENGINEER, DEVOPS_ENGINEER, COMMUNITY_MAINTAINER.
