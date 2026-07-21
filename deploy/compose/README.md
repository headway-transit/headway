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

Secrets note (handoff 0019): alongside the session secret, `.env` holds
`HEADWAY_SIGNING_KEY` — the installation's Ed25519 certification signing key
(64 hex chars; `openssl rand -hex 32`; the installer generates it). It lives
ONLY in `.env` (mode 600) or a secret file — never in the database, never in
the repository. Without it the API runs but refuses to certify (503, nothing
written): a certification is never recorded unsigned. Rotating it changes
the key fingerprint on new certificates; keep the old key if you need to
re-verify certificates it signed (see `services/api/README.md`).

To stop: `docker compose down`. Data survives in named volumes; add `-v` only
if you intend to erase everything.

## Which app images run: `HEADWAY_IMAGE_TAG`

`HEADWAY_IMAGE_TAG` in `.env` (handoff 0022) selects the app images for
`ingestion`, `transform` and `api`: `local` (default) means images built
from this source tree; a release tag (e.g. `v0.2.0-alpha`) means the
cosign-signed images published to ghcr. The supported way to move between
releases is `./install/install.sh --upgrade`, which verifies every
signature *before* pulling and records the previous tag for rollback —
plain-language guide in [`docs/updating.md`](../../docs/updating.md).
Two honest notes: with a release tag set, never run `up --build` (a local
build would overwrite the verified image under the release's name), and
`web` always stays a local build because its API address is baked in at
build time (see the compose file's comments).

## Bootstrap (automatic provisioning)

Plain `docker compose up` also runs two one-shot init containers — no manual
topic or bucket creation is needed (the 2026-07-09 live run found both had to
be created by hand; these close that gap):

- `bootstrap-kafka` — creates the five v0 topics from
  `contracts/topics.v0.md` with `kafka-topics.sh --create --if-not-exists`
  (single-node: 1 partition, replication factor 1).
- `bootstrap-minio` — creates the raw-payload bucket (`S3_BUCKET`, default
  `headway-raw`) with `mc mb --ignore-existing`.

Both are idempotent and exit 0 on every run; in `docker compose ps -a` they
show `Exited (0)`, which is their healthy state. The `ingestion` service
waits for both to complete successfully before starting, so the connector
never produces to missing topics or writes to a missing bucket.

## What each service is

| Service | One sentence |
| --- | --- |
| `kafka` | Apache Kafka (KRaft mode, no ZooKeeper) — the durable, replayable message log every connector produces into and the pipeline consumes from (ADR-0002). |
| `timescaledb` | PostgreSQL 16 + TimescaleDB — the agency database holding raw-record references, the canonical model, telemetry, and reporting data. |
| `apicurio` | Apicurio Registry — the schema authority every connector's wire contract is validated against (ADR-0006); stores its state in Kafka (kafkasql) so nothing is lost on restart. |
| `minio` | MinIO — S3-compatible object storage for raw payload objects (e.g. GTFS zips); stands in identically for cloud object storage on-prem. |
| `prometheus` | Prometheus — collects metrics from the stack. |
| `grafana` | Grafana — dashboards over Prometheus (console at http://localhost:3000). |
| `bootstrap-kafka` | One-shot init container that creates the v0 Kafka topics (idempotent; exits 0). |
| `bootstrap-minio` | One-shot init container that creates the MinIO raw-payload bucket (idempotent; exits 0). |
| `ingestion` (profile `app`) | The Go connector runtime that pulls agency feeds (GTFS/GTFS-RT) and produces content-addressed raw records to Kafka. |
| `caddy` (profile `lan`) | The office doorway: a pinned Caddy (Apache-2.0) terminating HTTPS with its built-in local CA (`local_certs`) and proxying exactly two upstreams — `/` → web, `/api/*` → API — under one https origin. Managed by `install/install.sh --reconfigure-access`; plain-language guide in `docs/network-access.md`. |
| `keycloak` (profile `sso-broker`, commented) | Optional identity broker for SAML-only IdPs or IdP aggregation (ADR-0011); the default stack uses the API's native OIDC + local accounts instead. |

`transform`, `api`, and `web` have live services under the `app` profile in `compose.yaml`
and join the `app` profile in the next slice waves.

Host-published ports (all bound to 127.0.0.1 only): Kafka dev listener 29092,
Postgres 5432, Apicurio 8081, MinIO 9000/9001, Prometheus 9090, Grafana 3000.

## Profile `lan` — office network access

The one deliberate exception to "127.0.0.1 only": with the `lan` profile
active, `caddy` publishes ports 80 and 443 on all interfaces so other
computers in the office can reach the web app and API over HTTPS — and
nothing else (admin surfaces above stay loopback-only, on purpose). The
installer owns the wiring — the confirmed office address
(`HEADWAY_LAN_ADDRESS`), the origin list (`HEADWAY_CORS_ORIGINS`), the
rebuilt web bundle (`VITE_API_BASE_URL=https://<address>/api`), and
`COMPOSE_PROFILES=app,lan` move together via
`./install/install.sh --reconfigure-access` (both directions, re-runnable).
Do not hand-edit one of the four without the others; `docs/network-access.md`
explains the whole design, the browser-certificate story, and what must
never be exposed.

## Verification status

Per the shared constraint **verification before assertion**:

- **Verified (authoring environment, 2026-07-08):**
  - Authored against ADR-0002 (Kafka KRaft), ADR-0005 (Compose-primary),
    ADR-0006 (Apicurio), ADR-0010 (repo layout), ADR-0011 (no default
    Keycloak).
  - YAML syntax of `compose.yaml` and `prometheus/prometheus.yml` validated
    with `python3 -c "import yaml; yaml.safe_load(...)"` — both parse clean.
- **Verified (live Docker stack, 2026-07-09 — see handoff 0001
  "Verification Evidence" for the full record):**
  - Cold-start `docker compose up`: all 6 infrastructure healthchecks green
    (Kafka, TimescaleDB, Apicurio, MinIO, Prometheus, Grafana), pinned image
    tags pulled successfully; `ingestion` built and ran the MBTA end-to-end
    walking skeleton.
  - That run found topics and the bucket had to be created manually — the
    gap now closed by the `bootstrap-kafka`/`bootstrap-minio` init services.
- **Verified (live Docker stack, 2026-07-13 — see handoff 0016 "Outputs —
  evidence" for the full record):**
  - The `lan` profile's `caddy` (pinned 2.10.2) booted healthy in a
    disposable project against this file's real service definition; issued
    a local-CA certificate for the box's LAN IP; served the web app and API
    through one HTTPS origin against the LAN interface address, with a real
    login + metrics fetch and correct CORS headers through the proxy; admin
    ports confirmed unreachable from the LAN address.
  - That test found and fixed three live bugs in this file/dir: the `api`
    build context predated the in-repo `headway-calc` dependency (now repo
    root, like `transform`); the `web` and `caddy` healthchecks probed
    `localhost`, which busybox wget resolves to `::1` while the servers
    listen IPv4-only (now `127.0.0.1`); and Caddy needs `default_sni` for
    bare-IP addresses because browsers send no TLS server name for them.
- **PENDING — not yet verified:**
  - Live execution of the `bootstrap-kafka`/`bootstrap-minio` init services
    (authored after the 2026-07-09 run; both exit 0 with everything already
    existing, but that must be observed on the next `docker compose up`,
    without restarting the currently running stack out of band).
  - The `minio/mc` image tag pinned for `bootstrap-minio` must be confirmed
    pullable at that same run.
  - Kafka heap (512 MiB) is a starting point, not a measured ceiling —
    single-box sizing must be measured under real load (ADR-0002).
  - The `lan` profile as the *installer* drives it (question → `.env`
    wiring → `docker compose up` with `COMPOSE_PROFILES=app,lan`) on a
    fresh box — part of the standing fresh-box installer pending.
