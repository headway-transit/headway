# ADR-0006: Connector Contract — Uniform Kafka-Producer Wire Contract + Apicurio Registry

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

Headway ingests from an open-ended set of sources — GTFS-RT, APC, farebox, J1939, vendor-specific feeds — written by first parties, the community, and vendors.

If connectors could hook into the platform through more than one mechanism, we'd get a two-tier ecosystem (a privileged fast-path and everyone else) and a second execution model to maintain. We also want the connector boundary to double as a vendor certification surface, so no single vendor can capture the platform by being the only one who can integrate deeply. We need exactly one wire boundary that every connector obeys, and a schema authority for it that is license-clean under ADR-0001.

## Decision Drivers

- One integration model for all connectors — no privileged fast-path, no two-tier ecosystem.
- The boundary is also the vendor certification surface (anti-single-vendor-capture).
- Fail-loudly and provenance: connectors must produce content-addressed raw records that lineage (ADR-0007) can anchor to.
- Ergonomics for contributors without a second execution model.
- Schema-registry license cleanliness per ADR-0001.

## Considered Options

- **Uniform Kafka-producer wire contract** — every connector is an independent process producing to Kafka against a versioned schema-registry contract.
- **In-process Python fast-path alongside the wire contract** — rejected: a second execution model that splits the ecosystem into privileged and non-privileged tiers.
- **Schema registry:** Apicurio Registry / Karapace (Apache-2.0) vs. Confluent Schema Registry (Confluent Community License, not OSI-approved — rejected).

## Decision Outcome

Chosen option: "A single uniform Kafka-producer wire contract, with Apicurio Registry as the schema authority", because one wire boundary keeps the ecosystem flat and makes the contract itself the certification surface.

Every connector — first-party, community, or vendor — is an independent process that produces to Kafka (ADR-0002) against a versioned, registry-governed schema. Ergonomics are delivered not by a second boundary but by rich SDKs (Python and Go) and a Go connector-runtime base image that handles Kafka production, schema validation, checkpointing, back-pressure, and replay — so contributors get ease without a fast-path.

The schema registry is Apicurio Registry (Apache-2.0), with Karapace as an interchangeable alternative; Confluent Schema Registry is rejected because the Confluent Community License is NOT OSI-approved (ADR-0001) and would put a non-open component on the critical path.

### Consequences

- Good — a single, uniform, versioned boundary that is simultaneously the integration contract and the vendor certification surface.
- Good — a license-clean registry on the critical path.
- Good — content-addressed raw records emitted here become the anchor nodes for lineage (ADR-0007).
- Bad / cost — every connector pays process and Kafka-production overhead; there is no ultra-low-latency in-process shortcut for first-party code.
- Mitigation — the Go connector-runtime base image and the Python/Go SDKs absorb the boilerplate so the wire contract stays ergonomic.
- Mitigation — schema evolution is governed by registry compatibility rules to keep the boundary stable.

## Links

- Relates to ADR-0002 (connectors produce to Kafka) and ADR-0001 (registry license call).
- Feeds ADR-0007 (content-addressed raw records are lineage roots) and ADR-0009 (the slice's Go ingest connector).
- Governs role files: Ingestion/Connector Framework, Vendor Certification, DevEx/SDK.
