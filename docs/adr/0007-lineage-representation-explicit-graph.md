# ADR-0007: Lineage Representation — Explicit Lineage Graph

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

Constraint 2 makes full provenance a first-class schema concern: every reported value must trace back to the raw records and transformation versions that produced it, and "explain this number" must work from a submission cell all the way back to raw ingest.

Because Headway's numbers land in NTD submissions, an auditor in an FTA triennial review may ask exactly how a VRM figure was derived — and the answer must be a query, not an archaeology project. The chain is multi-hop: raw record → canonical row → computed value. We need to decide how provenance is physically represented so that multi-hop "explain this number" is fast and direct.

## Decision Drivers

- "Explain this number" is a first-class, on-demand operation, not a batch reconstruction.
- Multi-hop lineage (raw → canonical → computed) must be first-class and directly queryable.
- Anchors already exist: content-addressed raw record ids (ADR-0006) and transform-version stamps from the calculation library.
- We already have raw immutability and replay from the Kafka log (ADR-0002), so we need not reconstruct history from a derivation log.

## Considered Options

- **Derivation-log / event-sourced lineage** — store operations, reconstruct provenance on demand; rejected: on-demand "explain" is complex, and the Kafka log already supplies raw immutability + replay.
- **Embedded per-row provenance references** — inline input refs on each row; rejected: coarse, row bloat, awkward multi-hop traversal.
- **Explicit lineage graph** — dedicated edge tables linking computed values → transforms/versions → input rows → content-addressed raw ids.

## Decision Outcome

Chosen option: "An explicit lineage graph in dedicated edge tables", because it makes "explain this number" a direct graph traversal rather than a computation.

Provenance is stored as explicit edges: each computed value ← transform + version ← input rows ← content-addressed raw record id. Multi-hop traversal (raw → canonical → computed) is first-class and directly queryable, so an auditor's question is answered by walking edges.

The derivation-log / event-sourced option was rejected because on-demand "explain" becomes complex to reconstruct, and — critically — the Kafka log (ADR-0002) already provides raw immutability and replay, so we do not need an event-sourced store to recover raw history. Embedded per-row references were rejected as too coarse: they bloat rows, and multi-hop traversal through inline references is awkward and slow.

### Consequences

- Good — "explain this number" is a fast graph query; multi-hop provenance is native, satisfying Constraint 2 in a way an auditor can exercise directly.
- Good — cleanly composes with ADR-0006 raw ids and calculation-library version stamps as the graph's leaf and edge labels.
- Bad / cost — the edge tables add write volume and storage on every computation.
- Bad / cost — the graph must be kept consistent as transforms evolve.
- Mitigation — anchor leaves to content-addressed raw ids (dedupe, stable identity) and stamp every edge with the transform + calculation-library version; index the edge tables for traversal.
- Mitigation — rely on the Kafka log for raw replay rather than duplicating raw payloads in the graph.

## Links

- Depends on ADR-0006 (content-addressed raw record ids) and ADR-0002 (the log that supplies raw immutability/replay).
- Relates to ADR-0003 (canonical rows are the middle hop) and feeds ADR-0009 (the slice threads lineage end to end).
- Governs role files: Canonical Model / Lineage, Calculation Library.
