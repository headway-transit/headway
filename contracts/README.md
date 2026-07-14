# Headway Wire Contracts

This directory is the **single connector boundary** (ADR-0006): every connector — first-party, community, or vendor — is an independent process that produces messages to Kafka conforming to the schemas here. These schemas are published as versioned artifacts on release; vendors pin the published artifact, never this repository (ADR-0010). Conformance to these schemas, verified by the QA conformance harness, is the basis of connector certification.

## Contents

| File | Purpose |
| --- | --- |
| `raw-record-envelope.v0.schema.json` | The envelope every connector wraps a raw record in before producing to Kafka. |
| `topics.v0.md` | Topic naming convention and the v0 topic registry. |
| `demand-response-trip.v0.schema.json` | One demand-response trip (booking) record as exported by a dispatch platform — the payload row format of `raw.dr.trips` files (handoff 0013). |
| `demand-response-trip.v0.md` | Field semantics, regulatory pointers, and the worked Via-style CSV export mapping example for `demand_response_trip` v0. |
| `adapter-mapping.v0.schema.json` | The machine-validated format of vendor adapter mapping specs (`adapters/<vendor>/<product>/mapping.v0.yaml`, handoff 0015) — declarative vendor-export → open-contract mappings. |
| `adapter-mapping.v0.md` | Field semantics of the mapping-spec format, the declared-timezone and provenance rules (agency-sample-only, never vendor documentation), and the runtime guarantees. |

## Invariants (binding on every connector)

1. **Raw records are immutable.** The `record_id` is the lowercase hex SHA-256 of the exact raw payload bytes as received (content-addressed). The same bytes always yield the same `record_id`; a connector never rewrites a payload.
2. **Fail loudly.** A payload that fails to parse is still wrapped, produced, and landed — with `parse_status: "malformed"` — so a data-quality issue can be raised downstream. Connectors never drop input.
3. **Envelope versioning.** `envelope_version` is bumped per published contract version; consumers must reject versions they do not understand rather than guess.
4. Schemas in this directory are governed by the Platform Architect; changes require an ADR-linked handoff, and released versions are never edited in place.
