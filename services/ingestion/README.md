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
- **A partially-copied file is never ingested** (2026-07-13 hardening pass) —
  see "File-drop robustness" below.
- **Bounded reads everywhere** — file-drop reads and the GTFS static fetch
  are capped (default 256 MiB; configurable). Oversize input is a loud
  refusal (file moved to `rejected/` / fetch error), never a truncated
  record and never a silent skip.
- **The file-drop source label is enforced, not conventional** — no
  default; simulator-marked content under a real label is hard-refused
  (Shared Constraint 2). See "File-drop robustness" below.

## File-drop robustness (TIDES + DR + vendor-file connectors, 2026-07-13 hardening pass)

**Partial-copy stability guard.** The reviewers confirmed that a file still
being copied into the drop directory could be ingested mid-copy — silent
truncation of a real export. The scanners now rescan the drop directory
every `POLL_INTERVAL` and ingest a file only after it is **stable**: seen
with an identical size *and* mtime on two consecutive scans, i.e. unchanged
for one full scan interval. A growing file is skipped with an INFO log
("file not yet stable") each scan until it settles, then ingested exactly
once (content addressing dedupes any re-produce).

**Rename-into-place convention (recommended to agencies).** The settle
check is a safety net, not an invitation to copy slowly. Export processes
SHOULD write the file under a name the scanner ignores (e.g.
`passenger_events_2026-07-13.csv.tmp` or a dotfile) and `rename(2)`/`mv` it
to its final `passenger_events*.csv` / `demand_response_trips*.csv` name
only when complete. Rename is atomic on the same filesystem, so the scanner
only ever sees complete files — the stability guard then merely costs one
scan interval of latency.

**Source label is required and enforced.** `TIDES_SOURCE` / `DR_SOURCE`
have **no default**: a connector with a drop dir configured and no source
label refuses to start with a plain-language error (fail closed). Labels
ending `_simulated` declare simulated data (handoff 0005 binding rule).
Enforcement is also structural: the Headway simulators mark every row's id
with the `sim:` prefix, and a scanner configured with a *non*-simulated
label hard-refuses any file carrying that marker — moved to `rejected/`,
logged as an ERROR naming the fix, never landed (Shared Constraint 2: full
provenance; simulated data must never be able to masquerade as real).

**Size caps and `rejected/`.** Dropped files over `DROP_MAX_FILE_BYTES`
(default 256 MiB) are refused before being read into memory. Every refused
file (oversize or provenance) is *moved* to `<drop dir>/rejected/` and
loudly logged — preserved for human inspection, never deleted, never
silently skipped, and out of the scanner's rescan path so the refusal does
not repeat forever.

## Layout

| Path | What |
| --- | --- |
| `internal/envelope/` | Raw-record envelope v0 builder + schema-shaped validation |
| `internal/producer/` | `Producer` interface; Kafka impl (franz-go) + in-memory fake |
| `connectors/gtfsrt/` | GTFS-Realtime poller (vehicle_positions / trip_updates / alerts → `raw.gtfs_rt.*`, base64 payload) |
| `connectors/gtfsstatic/` | GTFS static zip fetcher (→ `raw.gtfs_static.feed`, `object_ref` payload; bytes landed at `raw/gtfs_static/<record_id>.zip` via an `ObjectStore` interface: MinIO impl + fake) |
| `connectors/tides/` | TIDES passenger_events file-drop scanner (periodic scan of `TIDES_DROP_DIR` every `POLL_INTERVAL` for `passenger_events*.csv` → `raw.tides.passenger_events`, `object_ref` payload; bytes landed at `raw/tides/<record_id>.csv`; partial-copy stability guard + size cap + simulated-source enforcement per "File-drop robustness" above; processed files moved to `processed/`, refused files to `rejected/`; header sanity check against the required TIDES columns sets `parse_status` only) |
| `connectors/dr/` | Demand-response trips file-drop scanner (handoff 0013; periodic scan of `DR_DROP_DIR` every `POLL_INTERVAL` for `demand_response_trips*.csv` → `raw.dr.trips`, `object_ref` payload; bytes landed at `raw/dr/<record_id>.csv`; same robustness guards as the TIDES scanner; processed files moved to `processed/`, refused files to `rejected/`; header sanity check against the required `demand_response_trip` v0 columns — `contracts/demand-response-trip.v0.schema.json` — sets `parse_status` only) |
| `connectors/vendorfile/` | Generic vendor-export file-drop scanner for the adapter framework (handoff 0015; periodic scan of `VENDOR_DROP_DIR` every `POLL_INTERVAL` for `*.csv` → `raw.vendor.files`, `object_ref` payload; ORIGINAL vendor bytes landed content-addressed at `raw/vendor/<record_id>.csv`; same robustness guards as the TIDES/DR scanners; deliberately NO header/content check — `parse_status` is always `ok`, because only the registered mapping spec (`adapters/<vendor>/<product>/mapping.v0.yaml`) knows the vendor format; all interpretation, per-row quarantine and the fail-closed unregistered-label refusal happen in the transform adapter runtime) |
| `cmd/headway-ingest/` | The service binary: env config, connector startup, SIGINT/SIGTERM clean shutdown, `log/slog` JSON logging |

GTFS / GTFS-Realtime payload *semantics* are defined by the specs at
gtfs.org and are the Data Engineer's concern; this service captures bytes and
transport only. GTFS-RT parse classification uses the pinned MobilityData
bindings (`gtfs-realtime-bindings/golang/gtfs v1.0.0`). TIDES
passenger_events semantics are defined by the TIDES spec
(TIDES-transit/TIDES on GitHub, `spec/passenger_events.schema.json`); the
connector's header check was verified against commit
`d887d42ce081f3fb6155664a3c486101d62ec52b` (2026-07-10) — re-verify against
the current spec before extending. Simulated drops (from
`tools/tides-simulator`) MUST run with `TIDES_SOURCE=tides_simulated` so
provenance permanently distinguishes them (handoff 0005 binding rule).

## Configuration (environment)

| Variable | Meaning |
| --- | --- |
| `KAFKA_BROKERS` | Comma-separated broker list (required) |
| `GTFS_RT_VEHICLE_POSITIONS_URL` | Poll this vehicle-positions feed (optional) |
| `GTFS_RT_TRIP_UPDATES_URL` | Poll this trip-updates feed (optional) |
| `GTFS_RT_ALERTS_URL` | Poll this alerts feed (optional) |
| `GTFS_STATIC_URL` | Fetch this GTFS static zip once at startup (optional) |
| `GTFS_STATIC_MAX_BYTES` | Cap on the fetched zip, plain bytes; default 268435456 (256 MiB). Oversize responses are refused, never truncated |
| `TIDES_DROP_DIR` | Scan this directory every `POLL_INTERVAL` for TIDES `passenger_events*.csv` drops (optional) |
| `TIDES_SOURCE` | Envelope `source` for TIDES drops — **REQUIRED with `TIDES_DROP_DIR`, no default** (fail closed); simulator drops MUST use `tides_simulated` |
| `DR_DROP_DIR` | Scan this directory every `POLL_INTERVAL` for `demand_response_trips*.csv` drops (optional, handoff 0013) |
| `DR_SOURCE` | Envelope `source` for DR drops — **REQUIRED with `DR_DROP_DIR`, no default** (fail closed); simulator drops MUST use `dr_simulated` |
| `VENDOR_DROP_DIR` | Scan this directory every `POLL_INTERVAL` for vendor-export `*.csv` drops (optional, handoff 0015) |
| `VENDOR_SOURCE` | Envelope `source` for vendor drops — **REQUIRED with `VENDOR_DROP_DIR`, no default** (fail closed). Must be the REGISTERED adapter mapping-spec label `<vendor>_<product>` (see `adapters/README.md`), or `<vendor>_<product>_simulated` for synthetic data; the transform runtime refuses unregistered labels with a blocking DQ issue |
| `DROP_MAX_FILE_BYTES` | Cap on a dropped file, plain bytes; default 268435456 (256 MiB). Oversize files are moved to `rejected/` and logged |
| `POLL_INTERVAL` | Go duration for GTFS-RT polling AND drop-dir rescans, default `30s`; also the file-drop partial-copy settle time |
| `AGENCY_ID` | Optional envelope `agency_id` (multi-feed disambiguation only) |
| `S3_ENDPOINT` | MinIO/S3 endpoint `host:port` (required with `GTFS_STATIC_URL`, `TIDES_DROP_DIR`, `DR_DROP_DIR` or `VENDOR_DROP_DIR`) |
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

Unit tests, build, and vet **pass** (2026-07-13, toolchain auto-selected by
the go.mod directive; host go1.22+ with `GOTOOLCHAIN=auto`; 37 tests):

```
$ go build ./... && go vet ./... && go test ./... -count=1
?   .../cmd/headway-ingest    [no test files]
ok  .../connectors/dr         0.016s
ok  .../connectors/gtfsrt     0.004s
ok  .../connectors/gtfsstatic 0.004s
ok  .../connectors/tides      0.015s
ok  .../internal/envelope     0.001s
?   .../internal/producer     [no test files]
```

Covered by fakes/httptest: envelope determinism + SHA-256 known vector +
required-field completeness; GTFS-RT happy path / malformed-never-dropped /
consecutive-duplicate skip; GTFS static envelope + content-addressed object
key + broken-zip-still-landed + land-before-produce ordering + oversize
response refused with the limit named; TIDES and DR drop envelopes +
missing-required-column-still-landed-and-produced-as-malformed + source
carried verbatim (`tides_simulated` / `dr_simulated`) + processed-move
idempotent re-scan + land-before-produce ordering; and per the 2026-07-13
hardening pass, on both file-drop scanners: growing-file-never-ingested-
until-stable (the reviewers' partial-copy regression, ingest exactly once
with the complete bytes), empty-source refusal naming the env var,
simulator-marked-content-under-real-label hard refusal (and its
counterpart ingesting under a `*_simulated` label), oversize file moved to
`rejected/` with the limit named, and the periodic `Run` loop ingesting
then stopping cleanly on cancel.

**Live-verified 2026-07-13** against the running Compose stack (evidence:
`docs/reviews/2026-07-13-hardening-pass.md`, Batch B): the mid-copy
scenario — a simulator CSV slow-written into `DR_DROP_DIR` at ~512 B/s
while the connector scanned every 3 s — was skipped on four consecutive
scans ("file not yet stable", 1024→2560→4096→5130 bytes) and ingested
exactly once when stable, with `record_id` equal to the complete file's
sha256; startup without `DR_SOURCE` refused fatally with the
plain-language error; the same simulator file dropped under
`DR_SOURCE=dr` was refused ("16 row(s) carry the simulator marker") and
preserved in `rejected/`.

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
re-ingest idempotent). The file-drop scanners rescan every `POLL_INTERVAL`
(2026-07-13 hardening pass — required by the partial-copy stability guard);
there is still no inotify-style watcher, and the pending-file state is
in-memory (a restart just re-observes candidates for one extra interval —
the `processed/` move plus content-addressed `record_id` keep re-scans
idempotent).
