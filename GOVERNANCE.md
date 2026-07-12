# Headway Governance

Headway exists so that any transit agency — and any vendor serving one — can run, inspect, fork, and extend its entire reporting pipeline without anyone's permission. This document is the charter that keeps that true as the project grows.

## The anti-capture rule

**No single company or individual may hold unilateral control over Headway.** Concretely:

- No single organization may hold exclusive merge rights, sole release-signing keys, or a veto over the roadmap.
- Maintainership is personal, not corporate: seats belong to people, and no more than half of the maintainers may share one employer. If hiring changes break that ratio, the affected maintainers choose which of them steps back to emeritus until balance is restored.
- Cloud-managed offerings built on Headway are packaging, not privilege: no core capability may be reserved for, or degraded outside of, any hosted product (constraint 3 of [`_SHARED_CONSTRAINTS.md`](.claude/roles/_SHARED_CONSTRAINTS.md)).
- The eight shared constraints are constitutional. Changing them requires a public ADR with unanimous maintainer approval, not a majority.

## How decisions are made

- **Day-to-day changes**: pull requests reviewed under [`CONTRIBUTING.md`](CONTRIBUTING.md); any maintainer may merge a passing, reviewed PR.
- **Architecture and cross-cutting decisions**: an ADR in [`docs/adr/`](docs/adr/) (MADR format), opened as a PR so discussion is public. Interface changes between subsystems additionally require a handoff document ([`docs/handoffs/`](docs/handoffs/)). Adopted as of this document: substantial new directions (new module, new external dependency class, governance change) open as a **Request for Comments** — an ADR PR labeled `rfc` held open for at least 14 days.
- **Disagreement**: maintainers seek consensus; failing that, a majority of maintainers decides, recorded in the ADR with the dissent noted. Constitutional items (above) require unanimity.

## Maintainers

- **Becoming one**: sustained, high-quality contribution across several months; nominated by an existing maintainer; accepted by consensus of the others. The bar includes fluency in the project's verification norms, not just code.
- **Stepping back**: maintainers inactive for six months move to emeritus (honored, no merge rights) after a friendly ping; any maintainer may return from emeritus by asking.
- **Removal**: for conduct or trust violations, by consensus of the other maintainers.
- **Bootstrap note**: the project currently has a single founding maintainer; the first order of governance business is growing that number. Until there are three or more maintainers, the anti-capture employer ratio is aspirational and this document is the public commitment to it.

## Releases

Releases are tagged from `main`, built and signed by CI (Cosign keyless, SBOM attached — see [`docs/supply-chain.md`](docs/supply-chain.md)). Release notes trace to merged PRs. No unsigned or unscanned artifact is ever published as a release.

## Connector certification

Third-party connectors are certified by **conformance, never by payment or partnership**: a connector that passes the conformance requirements against the published wire contract ([`contracts/`](contracts/)) earns the badge; the results are public; the badge is revocable if conformance regresses. Certification never requires the vendor's code to be open source — the *contract* is the boundary — but certified status grants no core privilege.

## Scope of this document

This charter governs the Headway project and its official repositories and releases. Agencies' own deployments are their own; vendors' own products are their own.
