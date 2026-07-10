# Headway

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Headway is an open-source, autonomous transit data platform for public
transit agencies. It ingests operational data — GTFS and GTFS-Realtime
feeds, AVL, APC, farebox, and vehicle telemetry — into a durable, replayable
log, normalizes it into one canonical model, and produces the figures
agencies report to the National Transit Database (NTD).

Every reported number is computed by deterministic, versioned, unit-tested
calculation logic, and every number carries full provenance: you can walk any
reported value back through the pipeline to the raw source records that
produced it. AI features assist — anomaly detection, data-quality triage,
narrative drafting, natural-language query — but AI never computes a reported
number, and every AI output cites its sources and requires human review.

The whole platform runs on commodity open-source infrastructure. A small
agency can run everything on one Linux box with Docker Compose; larger
agencies and gov-cloud deployments run the identical artifacts under
Kubernetes. If a feature only works in the cloud, it is rejected.

## Quickstart

On a fresh Linux box, run the guided installer:

```sh
./install/install.sh
```

It checks the machine (Docker, ports, memory, disk), refuses to overwrite
an existing installation, generates `deploy/compose/.env` with strong
secrets, brings the stack up, applies the database migrations, and creates
your first administrator account — explaining every step and every failure
in plain language. `./install/install.sh --check` does a no-changes dry
run. See [`install/README.md`](install/README.md) for the full guide.

Prefer to do it by hand? See [`deploy/compose/`](deploy/compose/) — copy
`.env.example` to `.env`, set three passwords, and run
`docker compose up -d`.

## Repository layout (ADR-0010)

| Path | Contents |
| --- | --- |
| `contracts/` | Wire-contract schemas; published as versioned artifacts (ADR-0006) |
| `services/ingestion/` | Go: connector runtime, SDKs, first-party connectors |
| `services/transform/` | Python: normalization + dbt project |
| `services/calc/` | Python: deterministic calculation library |
| `services/api/` | Python: FastAPI backend |
| `services/ai/` | Python: AI layer + grounding eval harness |
| `web/` | TypeScript/React frontend |
| `db/` | Schema + migrations, including the lineage graph (ADR-0007) |
| `deploy/compose/` | Source-of-truth single-box stack (ADR-0005) |
| `deploy/helm/` | First-class parallel Kubernetes target (ADR-0005) |
| `security/` | Control mapping, threat model, SSO config |
| `docs/` | Docs site, `docs/adr/` (architecture decisions), `docs/handoffs/` |
| `tests/` | Cross-service suites: golden, conformance, parity |

## Where decisions live

- Architecture decision records: [`docs/adr/`](docs/adr/)
- Role charters and shared constraints: [`.claude/roles/`](.claude/roles/)

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
