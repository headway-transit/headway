# ADR-0003: Canonical Data Model — TIDES-Compatible Hybrid

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

Every source — GTFS-RT, GTFS static, APC, farebox, J1939 — normalizes into one canonical model, and every NTD figure (VRM, VRH, UPT, PMT, VOMS) is computed from it. The model therefore has two masters that can pull in different directions.

It must be complete and stable enough to derive certifiable regulatory numbers, and it should interoperate with the emerging community standard so Headway is not an island. The Transit ITS Data Exchange Specification (TIDES) is the natural interoperability target, but it is young and evolving, and gaps in it could block an NTD calculation. We must decide how tightly the core model binds to TIDES.

## Decision Drivers

- Reporting completeness first: the model must never lack a field an NTD calculation needs.
- Interoperability and community-standard credibility (adoption, contributor familiarity, data exchange).
- Insulation from external spec churn — a breaking TIDES release must not break a reporting calculation.
- Anti-hallucination discipline: spec versions are pointers to verify, not facts to memorize.

## Considered Options

- **TIDES-aligned core** — adopt TIDES as the core model directly; rejected: couples our reporting substrate to a young, moving spec whose gaps could block an NTD calc.
- **Bespoke reporting-first core, no special TIDES status** — rejected: forfeits the interoperability and community-standard story that aids adoption.
- **TIDES-compatible hybrid** — bespoke reporting-driven core that adopts TIDES structures/vocabulary where they map cleanly.

## Decision Outcome

Chosen option: "TIDES-compatible hybrid", because it lets the core stay reporting-driven and stable while still speaking the community's vocabulary.

The core is a bespoke, reporting-first canonical model, but wherever a TIDES structure or field maps cleanly it adopts TIDES naming and shape, so the model is TIDES-compatible without being bound to TIDES' release cadence. TIDES is tracked in two roles: as an input adapter (we ingest TIDES-shaped data) and as an alignment target (we converge toward it where doing so does not compromise reporting).

The specific structures, fields, and versions of TIDES, GTFS, and GTFS-Realtime referenced here are pointers — verify against the current published specifications (tides spec, gtfs.org) and record the version verified against before implementing.

### Consequences

- Good — reporting calculations rest on a stable core we control.
- Good — interoperability and community credibility come for free where mappings are clean.
- Good — decoupling means a breaking TIDES release is an adapter/mapping problem, not a core-schema emergency.
- Bad / cost — ongoing mapping-maintenance burden as TIDES evolves; two vocabularies to reconcile at the seam.
- Mitigation — keep TIDES mappings in a versioned adapter layer with conformance tests.
- Mitigation — re-verify spec versions on each mapping change and stamp the verified version.

## Links

- Feeds ADR-0009 (the first slice normalizes GTFS-RT + GTFS static into this model).
- Relates to ADR-0007 (canonical rows are lineage nodes between raw and computed).
- Governs role files: Canonical Model / Normalization, Calculation Library.
