# ADR-0005: Deployment Substrate — Compose-Primary, Helm-Parallel, Parity by CI

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

Headway must run in two very different places from one set of artifacts: a single commodity box that a small-agency IT generalist administers, and a Kubernetes-based gov-cloud for scale and FedRAMP-aware isolation (Constraint 4).

The risk is drift — the on-prem stack and the cloud stack silently diverging until a feature works in one and fails in the other. We need a source-of-truth deployment format for the small-agency case, a first-class path for the scaled case, and a mechanism that makes "these two deploys are the same" a tested fact rather than a hope.

## Decision Drivers

- The small-agency single-box deploy must be trivially operable by a generalist.
- Kubernetes must be a first-class scale/gov-cloud target, not an afterthought.
- Same artifacts on-prem and hosted (Constraint 4); no cloud-only capability.
- Drift between the two must be caught mechanically, early.
- Time-to-first-deploy must stay short; don't let parity tooling delay adoption.

## Considered Options

- **Compose-only, Kubernetes out of scope** — rejected: forfeits the scale/gov-cloud target.
- **Single-source manifest generator (Kompose-style)** — rejected: mediocre output on both ends, idiomatic on neither, and delays first deploy while fighting the generator.
- **Compose source-of-truth + Helm/Kubernetes parallel, parity at the artifact layer, proven by a CI gate.**

## Decision Outcome

Chosen option: "Compose-primary plus Helm-parallel, with parity proven by CI", because it gives the small agency a dead-simple Docker Compose deploy while making Kubernetes a fully supported parallel target — without a brittle generator in the middle.

The parity guarantee lives at the ARTIFACT layer: identical container images plus one documented configuration schema that both Helm values and Compose environment variables map onto — not a single shared manifest. A CI parity gate stands up BOTH the Compose stack and a Helm/k3s stack and runs the identical smoke, health, and migration suite against each, so any divergence is caught by a failing test.

The single-source generator approach was rejected: Kompose-style generation tends to produce mediocre output on both ends and would delay first deploy. Catching drift by test is more robust than preventing it with a lowest-common-denominator abstraction.

### Consequences

- Good — the generalist gets a simple Compose deploy; the platform team gets idiomatic Helm.
- Good — drift surfaces as a red CI run, not a production incident.
- Bad / cost — two deployment definitions to maintain (Compose and Helm) instead of one generated source.
- Bad / cost — the parity gate spins up two full stacks in CI, adding pipeline time and infrastructure cost.
- Mitigation — the shared config schema and shared container images keep the two definitions thin and mechanically comparable.
- Mitigation — keep the parity smoke suite fast; run the full matrix on a sensible cadence rather than every commit if runtime becomes a problem.

## Links

- Relates to ADR-0004 (the same artifacts run the single-box and multi-tenant hosted deploys).
- Relates to ADR-0002 (the broker artifact must run identically in both substrates).
- Governs role files: Platform/Infrastructure, DevEx/CI.
