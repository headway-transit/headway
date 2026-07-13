# Handoff: platform-architect → ingestion, transform — Vendor adapter framework v0 (TripSpark Streets first; mapping BLOCKED on sample)

## Context
Direct vendor integrations are the platform's biggest adoption lever (project direction, 2026-07-13): agencies' operational data lives in Trapeze/TripSpark, Swiftly, Clever Devices, Ecolane, Spare, etc. The first real flow is a partner agency: MDT manual passenger counts → TripSpark → files pushed to an agency storage server (consumed today by Streets reports). ADR-0006 rule: Headway core speaks ONLY open contracts (TIDES passenger_events, demand_response_trip, GTFS/GTFS-RT). Vendors get ADAPTERS — declarative mappings from their export formats onto those contracts — never bespoke pipeline forks. The hardened file-drop machinery (stability guard, size caps, fail-closed source labels, per-row quarantine) is the intake; adapters are a mapping layer in front of it.

## Design (binding)
1. **Mapping-spec format** (`adapters/<vendor>/<product>/mapping.v0.yaml` + prose doc): source format declaration (CSV dialect/fixed-width/XML), field → contract-field mappings with type coercions, constant/derived fields (e.g. mode, TOS), unit conversions, timezone declaration (NEVER guessed), row-filter predicates, and REQUIRED provenance block: vendor, product, export name/version the spec was verified against, verification date, and sample-fixture reference. A spec without a verified sample fixture cannot be registered — field semantics never from memory or vendor docs alone.
2. **Adapter runtime** (Go or transform-side Python — implementer chooses per where the contract lands; document the choice): reads the mapping spec, transforms vendor files into contract-conformant records, runs the CONTRACT's validation, quarantines per-row per the hardening patterns, stamps envelope source as `<vendor>_<product>` (registered label; the fail-closed label rules apply). Content addressing on the ORIGINAL vendor bytes (raw record = what the vendor pushed; the mapped record carries lineage to it).
3. **Validation harness**: `adapters/validate` — given a mapping spec + fixture files, prove: every mapped record passes contract validation; every fixture row is either mapped or explicitly quarantined with a reason; round-trip determinism. CI-runnable; a registered adapter without green harness fixtures fails the build.
4. **First adapter: TripSpark Streets (BLOCKED — needs the partner agency's sample)**: manual MDT passenger counts → TIDES passenger_events (or ride-check measurements for the sampling module — decide from the sample's granularity). Everything about its fields waits for the real export; the framework ships with a synthetic reference adapter (`adapters/_reference/`) exercising every mapping-spec feature as the harness's own fixture.
5. **Registry + docs**: `adapters/README.md` — how the community adds a vendor (spec + fixtures + harness green + provenance block); explicit note that adapters map an agency's OWN exports (no reverse-engineering of licensed software; agencies own their data).

## Outputs
Framework + reference adapter + harness + registry docs, suites green, evidence here. TripSpark mapping lands as a follow-up the day a sample export exists.

## Open Questions
- Sample TripSpark Streets export from the partner agency (format, headers, cadence, companion files).
- Whether MDT manual counts map better to TIDES passenger_events or sampling measurements — decide from sample granularity.
- Adapter distribution model (in-repo vs community repo) — Community Maintainer question once a second external adapter appears.
