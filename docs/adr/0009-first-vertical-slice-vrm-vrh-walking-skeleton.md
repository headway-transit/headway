# ADR-0009: First Vertical Slice — Walking Skeleton, VRM/VRH from GTFS-RT + GTFS Static

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

An architecture is only proven when a thin thread runs through every seam of it. Headway needs a first end-to-end vertical slice that is thin-but-complete.

It must exercise ingestion, normalization, deterministic calculation, lineage, API, and certification UI; produce a real NTD-reportable figure with full provenance; and — because Headway is an open-source adoption engine — be reproducible by anyone with zero agency onboarding. The choice of which figure and which data source is therefore both an architectural decision and a go-to-market one. Sources split sharply: GTFS/GTFS-RT are published openly by hundreds of agencies, while ridership sources (APC, farebox) are proprietary and walled behind agency onboarding.

## Decision Drivers

- Reproducibility with zero onboarding — the demo must run on publicly available data (the OSS adoption engine).
- The slice must produce a real, NTD-reportable figure with full provenance, not a toy.
- It must exercise every architectural seam (ingest → normalize → calc → lineage → API → certification UI).
- Determinism: the first figure must come from deterministic calculation logic (Constraint 1), no AI in the number.

## Considered Options

- **VRM/VRH from GTFS-RT + GTFS static** — built entirely on open, public feeds.
- **UPT (ridership) from APC/farebox first** — the headline NTD metric, but proprietary/walled data; rejected as the first slice, sequenced as slice 2.
- **A non-end-to-end "widest layer first" build** — e.g., all connectors, no calc; rejected: proves no seams and yields no certifiable number.

## Decision Outcome

Chosen option: "A walking-skeleton slice computing VRM/VRH from GTFS-RT + GTFS static", because it is the only first thread that is simultaneously end-to-end, deterministic, NTD-reportable, and reproducible by anyone.

The thread runs: GTFS-RT + GTFS static → Go ingest (ADR-0006/0008) → Python normalize into the canonical model (ADR-0003) + deterministic VRM/VRH calculation → explicit lineage graph (ADR-0007) → Python API (ADR-0008) → certification UI.

It is built entirely on OPEN, publicly available data — GTFS/GTFS-RT feeds published openly by hundreds of agencies via the Mobility Database / transit.land — so anyone can reproduce the demo with zero agency onboarding, which is the OSS adoption engine, while still producing a real NTD-reportable figure with full provenance and exercising every architectural seam.

UPT via APC/farebox was rejected as the FIRST slice: it is the headline ridership metric, but the data is proprietary and walled, so it cannot drive early traction — it is slice 2. VRM/VRH definitions here are pointers — verify against the current FTA NTD Reporting Manuals and record the version verified against; likewise verify current GTFS/GTFS-RT spec versions (gtfs.org).

### Consequences

- Good — a reproducible, zero-onboarding demo that produces a real provenance-backed NTD figure and validates the whole architecture end to end.
- Good — every downstream ADR (broker, model, connector contract, lineage, language policy) is exercised and de-risked early by one thin thread.
- Bad / cost — VRM/VRH is not the metric agencies find most exciting (UPT is), so the first demo undersells the eventual ridership story.
- Mitigation — sequence UPT via APC/farebox as slice 2, reusing the same seams the skeleton proved.
- Mitigation — keep the calculation deterministic and golden-dataset-tested so the VRM/VRH figure is genuinely certifiable, not illustrative.

## Links

- Depends on ADR-0002 (Kafka), ADR-0003 (canonical model), ADR-0006 (connector contract), ADR-0007 (lineage), ADR-0008 (language policy).
- Governs role files: Ingestion/Connector, Normalization, Calculation Library, Backend/API, Frontend/Certification.
