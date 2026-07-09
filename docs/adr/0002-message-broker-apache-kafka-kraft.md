# ADR-0002: Message Broker — Apache Kafka (KRaft) Default, Redpanda Opt-In

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

The whole platform is a streaming pipeline: connectors produce raw source records; normalization, calculation, and lineage consume from and produce to a durable log. The broker is the backbone.

It must sustain fleet-scale telemetry throughput (thousands of vehicles emitting AVL / GTFS-RT / J1939 at high frequency), run identically on a single small-agency box and in gov-cloud (Constraint 4), be affordable, and be license-clean under ADR-0001. The immutable, replayable log is also load-bearing for lineage (ADR-0007) — it means we never need to reconstruct raw history from a derivation log. We must pick a default broker and a policy for alternatives.

## Decision Drivers

- Throughput and back-pressure headroom at fleet scale.
- Ecosystem depth: connect/consumer libraries, schema-registry integration, operational tooling.
- On-prem parity: the same broker artifact must run in Docker Compose on one box and in Kubernetes in gov-cloud.
- Affordability and operability by an IT generalist, not a streaming specialist.
- License cleanliness per ADR-0001 (OSI-approved only on the critical path).
- Durable, replayable log to underpin provenance and "explain this number".

## Considered Options

- **NATS JetStream** — lighter footprint, simpler ops; rejected as default for a lower throughput/ecosystem ceiling on the hot path.
- **Apache Kafka in KRaft mode (no ZooKeeper)** — Apache-2.0, deepest ecosystem, highest throughput ceiling.
- **Redpanda Community Edition as default** — Kafka-API-compatible, no JVM; rejected on license (BSL, not OSI-approved).

## Decision Outcome

Chosen option: "Apache Kafka in KRaft mode as the default broker", because it is Apache-2.0 (OSI-clean per ADR-0001), has the deepest ecosystem and highest throughput ceiling for fleet-scale ingestion, and KRaft removes the ZooKeeper dependency that historically made Kafka painful to self-host.

NATS JetStream was rejected as the default: lighter and easier, but a lower throughput/ecosystem ceiling than we want on the fleet-telemetry hot path. Redpanda-as-default was rejected on license grounds — Redpanda Community Edition is BSL, which is source-available but NOT OSI-approved (ADR-0001), so it cannot be a default or sit on the critical path. Redpanda remains a documented, self-hosted, drop-in opt-in swap (it speaks the Kafka API) for operators who accept its license and want its footprint.

### Consequences

- Good — license-clean and maximal ecosystem on the critical path.
- Good — a replayable durable log that ADR-0006 (schema registry) and ADR-0007 (lineage) both build on.
- Bad / cost — the JVM footprint is heavier on a small single box than NATS or Redpanda, raising the minimum RAM for the small-agency deploy.
- Mitigation — publish explicit sizing guidance for the single-box tier and tune broker heap/partition defaults for small deployments.
- Mitigation — document the Redpanda opt-in swap for operators who need a lighter Kafka-API-compatible runtime.

## Links

- Relates to ADR-0001 (the license rule that excluded Redpanda-as-default).
- Feeds ADR-0006 (connectors produce to Kafka against a schema registry) and ADR-0007 (the log underpins lineage).
- Governs role files: Platform/Infrastructure, Ingestion/Connector Framework.
