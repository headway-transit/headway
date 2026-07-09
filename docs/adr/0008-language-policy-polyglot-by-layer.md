# ADR-0008: Language Policy — Polyglot by Layer

- Status: Accepted
- Date: 2026-07-08
- Deciders: Founding Architect (Headway)

## Context and Problem Statement

Headway spans a high-throughput streaming ingestion runtime, a deterministic calculation and transform layer, an AI/data-quality layer, a request/response API, and a web UI.

These layers have genuinely different performance profiles and draw on different contributor pools — the civic-tech and transit-data community skews heavily Python, while the fleet-telemetry hot path needs a runtime that won't choke under load. A single-language mandate would either cap throughput on the streaming runtime or raise the contribution barrier on the calc/AI layers. We need a policy that fits each layer to its job and its contributors without fragmenting the codebase arbitrarily.

## Decision Drivers

- Throughput on the fleet-telemetry ingestion/streaming hot path.
- Contributor accessibility: the calc/AI/transform layers must be welcoming to the Python-heavy civic-tech pool.
- Fit for purpose per layer rather than one-size-fits-all.
- The API layer serves already-computed results over request/response and is NOT on the telemetry hot path.

## Considered Options

- **Python-first monolith, Go/Rust by exception** — rejected: Python's throughput ceiling is a poor fit for the streaming runtime at fleet scale.
- **Polyglot by layer** — choose the language per layer's job and contributor pool.
- **Go/Rust-first backend across the board** — rejected: a steep barrier for the civic-tech pool on exactly the calc/AI layers where we most want contributions.

## Decision Outcome

Chosen option: "Polyglot by layer", because each layer's performance profile and contributor pool point to a different best choice, and forcing one language onto all of them costs either throughput or contributors.

The policy:
- **Python** for the calculation, AI, and transform layers — Python-natural work and the natural language of the civic-tech contributor pool.
- **Go** for the performance-critical streaming and ingestion runtime and other high-throughput services.
- **TypeScript/React** for the frontend.
- **Python (FastAPI, contract-first OpenAPI)** for the API/Backend layer, because it serves already-computed results over request/response and does not sit on the fleet-telemetry hot path — so Python's throughput ceiling is irrelevant there while its ecosystem and contributor reach help.

### Consequences

- Good — each layer uses the right tool: Go where throughput matters, Python where determinism and contributor reach matter, TS/React on the client.
- Good — the calculation library (where all reported numbers originate, Constraint 1) stays in Python, keeping it accessible to reviewers and testers.
- Bad / cost — a polyglot codebase means multiple toolchains, CI lanes, and cross-language boundaries to maintain and document.
- Mitigation — the wire contract (ADR-0006) and content-addressed records make the cross-language seams explicit and testable.
- Mitigation — provide Python and Go SDKs so the boundaries stay ergonomic; keep language-per-layer boundaries aligned with service boundaries.

## Links

- Relates to ADR-0006 (Python + Go SDKs and the Go connector-runtime base image) and ADR-0002 (Go streaming runtime on Kafka).
- Feeds ADR-0009 (Go ingest + Python normalize/calc/API in the first slice).
- Governs role files: Ingestion Runtime, Calculation Library, Backend/API, Frontend.
