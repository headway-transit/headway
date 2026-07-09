# Headway Ingestion Service (walking skeleton)

First-party ingestion connectors for the ADR-0009 walking skeleton. Each
connector fetches raw source bytes, wraps the **exact bytes as received** in
the raw-record envelope (`contracts/raw-record-envelope.v0.schema.json`,
ADR-0006), and produces to Kafka on the topics in `contracts/topics.v0.md`,
keyed by `record_id` (lowercase hex SHA-256 of the payload bytes — the
content-addressed identity of ADR-0007).

Invariants (Ingestion Engineer guardrails):

- **Payload bytes are never mutated.** Source parsers run only to classify
  `parse_status`; the raw bytes are what is enveloped, landed, and produced.
- **Malformed input is never dropped.** An unparseable frame or broken zip is
  still landed/produced with `parse_status: "malformed"` and a `parse_error`,
  and logged loudly as a DQ hook (Guardrail 7).
- **Re-ingest is idempotent by construction** — same bytes → same `record_id`.
  The GTFS-RT poller also skips identical *consecutive* frames (same
  `record_id` as the previous poll) and logs the skip.

## Layout

| Path | What |
| --- | --- |
| `internal/envelope/` | Raw-record envelope v0 builder + schema-shaped validation |
| `internal/producer/` | `Producer` interface; Kafka impl (franz-go) + in-memory fake |
| `connectors/gtfsrt/` | GTFS-Realtime poller (vehicle_positions / trip_updates / alerts → `raw.gtfs_rt.*`, base64 payload) |
| `connectors/gtfsstatic/` | GTFS static zip fetcher (→ `raw.gtfs_static.feed`, `object_ref` payload; bytes landed at `raw/gtfs_static/<record_id>.zip` via an `ObjectStore` interface: MinIO impl + fake) |
| `cmd/headway-ingest/` | The service binary: env config, connector startup, SIGINT/SIGTERM clean shutdown, `log/slog` JSON logging |

GTFS / GTFS-Realtime payload *semantics* are defined by the specs at
gtfs.org and are the Data Engineer's concern; this service captures bytes and
transport only. GTFS-RT parse classification uses the pinned MobilityData
bindings (`gtfs-realtime-bindings/golang/gtfs v1.0.0`).

## Configuration (environment)

| Variable | Meaning |
| --- | --- |
| `KAFKA_BROKERS` | Comma-separated broker list (required) |
| `GTFS_RT_VEHICLE_POSITIONS_URL` | Poll this vehicle-positions feed (optional) |
| `GTFS_RT_TRIP_UPDATES_URL` | Poll this trip-updates feed (optional) |
| `GTFS_RT_ALERTS_URL` | Poll this alerts feed (optional) |
| `GTFS_STATIC_URL` | Fetch this GTFS static zip once at startup (optional) |
| `POLL_INTERVAL` | Go duration for GTFS-RT polling, default `30s` |
| `AGENCY_ID` | Optional envelope `agency_id` (multi-feed disambiguation only) |
| `S3_ENDPOINT` | MinIO/S3 endpoint `host:port` (required with `GTFS_STATIC_URL`) |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | Object-store credentials (inject from the secret store; never logged) |
| `S3_BUCKET` | Raw bucket, default `headway-raw` |
| `S3_USE_SSL` | `true` for TLS; default `false` (on-prem MinIO) |

At least one connector URL must be set.

## Dependency licenses (verified in the module cache at build)

| Dependency | Version | License |
| --- | --- | --- |
| `github.com/twmb/franz-go` (+ `pkg/kmsg`) | v1.21.5 / v1.13.1 | **BSD-3-Clause** (not Apache-2.0 as the scope assumed — verified against the LICENSE file; OSI-permissive, compliant with Guardrail 3) |
| `github.com/minio/minio-go/v7` | v7.2.1 | Apache-2.0 |
| `github.com/MobilityData/gtfs-realtime-bindings/golang/gtfs` | v1.0.0 | Apache-2.0 |
| `google.golang.org/protobuf` | v1.36.11 | BSD-3-Clause |

## Verification status

Unit tests, build, and vet **pass** (2026-07-08, `go1.25.0 linux/amd64`, toolchain
auto-selected by the go.mod directive; host had go1.22.2 with `GOTOOLCHAIN=auto`):

```
$ go mod tidy && go build ./... && go vet ./... && go test ./...
?   .../cmd/headway-ingest    [no test files]
ok  .../connectors/gtfsrt     0.009s
ok  .../connectors/gtfsstatic 0.011s
ok  .../internal/envelope     0.003s
?   .../internal/producer     [no test files]
```

Covered by fakes/httptest: envelope determinism + SHA-256 known vector +
required-field completeness; GTFS-RT happy path / malformed-never-dropped /
consecutive-duplicate skip; GTFS static envelope + content-addressed object
key + broken-zip-still-landed + land-before-produce ordering.

**PENDING (not verified — no Docker in the authoring environment):**

- Live Kafka produce path (`internal/producer/kafka.go`) — exercised only
  through the `Producer` interface with the fake; needs the Compose stack
  (Kafka KRaft, ADR-0002).
- Live MinIO landing (`connectors/gtfsstatic/objectstore.go` MinIO impl).
- Docker image build (`Dockerfile` is written but untested).
- Apicurio schema registration, replay-from-raw-store proof, and
  backpressure/at-least-once demonstration under a slow consumer.

## Deliberately out of scope (next increments)

Walking skeleton only: no connector-runtime base image, no checkpointing, no
backpressure tuning, no DQ-issue rows (malformed records are landed and
logged; the `dq.issues` emission hook comes with the Data Engineer's rule
engine), no source-schema descriptor registry, GTFS static is a one-shot
fetch (no re-poll/If-Modified-Since), GTFS-RT dedupe cursor is in-memory
(restart re-produces the current frame; safe because `record_id` makes
re-ingest idempotent).
