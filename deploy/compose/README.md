# Headway on one box — Docker Compose

This directory is the source of truth for running the whole Headway platform
on a single commodity Linux machine (ADR-0005). It is written for an IT
generalist: you need Docker Engine with the Compose plugin installed, and
nothing else.

## Bring it up

```sh
cd deploy/compose
cp .env.example .env      # open .env and set the three required passwords
docker compose up -d
```

That is the whole procedure for the infrastructure stack. To also run the
Headway application services (as they land in the repo):

```sh
docker compose --profile app up -d --build
```

Check status with `docker compose ps` — every service should report
`healthy`. If a password is missing from `.env`, the stack refuses to start
and says which variable is unset; that is deliberate (fail loudly, never boot
with baked-in credentials).

To stop: `docker compose down`. Data survives in named volumes; add `-v` only
if you intend to erase everything.

## What each service is

| Service | One sentence |
| --- | --- |
| `kafka` | Apache Kafka (KRaft mode, no ZooKeeper) — the durable, replayable message log every connector produces into and the pipeline consumes from (ADR-0002). |
| `timescaledb` | PostgreSQL 16 + TimescaleDB — the agency database holding raw-record references, the canonical model, telemetry, and reporting data. |
| `apicurio` | Apicurio Registry — the schema authority every connector's wire contract is validated against (ADR-0006); stores its state in Kafka (kafkasql) so nothing is lost on restart. |
| `minio` | MinIO — S3-compatible object storage for raw payload objects (e.g. GTFS zips); stands in identically for cloud object storage on-prem. |
| `prometheus` | Prometheus — collects metrics from the stack. |
| `grafana` | Grafana — dashboards over Prometheus (console at http://localhost:3000). |
| `ingestion` (profile `app`) | The Go connector runtime that pulls agency feeds (GTFS/GTFS-RT) and produces content-addressed raw records to Kafka. |
| `keycloak` (profile `sso-broker`, commented) | Optional identity broker for SAML-only IdPs or IdP aggregation (ADR-0011); the default stack uses the API's native OIDC + local accounts instead. |

`transform`, `api`, and `web` have commented placeholders in `compose.yaml`
and join the `app` profile in the next slice waves.

Host-published ports (all bound to 127.0.0.1 only): Kafka dev listener 29092,
Postgres 5432, Apicurio 8081, MinIO 9000/9001, Prometheus 9090, Grafana 3000.

## Verification status

Per the shared constraint **verification before assertion**:

- **Verified (authoring environment, 2026-07-08):**
  - Authored against ADR-0002 (Kafka KRaft), ADR-0005 (Compose-primary),
    ADR-0006 (Apicurio), ADR-0010 (repo layout), ADR-0011 (no default
    Keycloak).
  - YAML syntax of `compose.yaml` and `prometheus/prometheus.yml` validated
    with `python3 -c "import yaml; yaml.safe_load(...)"` — both parse clean.
- **PENDING — not yet verified (Docker is unavailable in the authoring
  environment; nothing below has been executed):**
  - `docker compose config` (interpolation/schema check).
  - Live cold-start boot: `docker compose up` with all healthchecks green.
  - The `apicurio` healthcheck assumes `curl` exists in the image — confirm
    at first boot and substitute a different probe if absent.
  - Image tags pinned here must be confirmed pullable and current.
  - Kafka heap (512 MiB) is a starting point, not a measured ceiling —
    single-box sizing must be measured under real load (ADR-0002).

The first Docker-capable environment must run `docker compose config` and a
cold-start `docker compose up`, record the log and `docker compose ps` output
as evidence, and update this section. Until then this stack is authored, not
proven.
