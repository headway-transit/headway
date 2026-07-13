# Sizing guide — what to run Headway on

Headway's charter is commodity hardware: the full platform — ingestion, Kafka, TimescaleDB,
MinIO, transform, calculation, API, web — runs on **one Linux box a small agency can
afford**. This guide says how big that box should be, based on **measured** usage from a
live deployment ingesting a large agency's real feeds (MBTA GTFS + GTFS-Realtime + passenger
events; ~3M schedule rows, ~2.5M realtime predictions, ~6M lineage edges at time of
measurement), not vendor optimism. Where a number is a floor from the installer's own
pre-checks, it says so.

## Quick answer

| Tier | vCPU | RAM | Disk (SSD) | Fits |
| --- | --- | --- | --- | --- |
| Evaluation | 2 | 8 GB | 40 GB | Installer test-drive, demo data, light feeds. The installer's hard floor is 4 GB RAM / 20 GB disk — it will warn-and-continue there, but a loaded TimescaleDB + Kafka on 4 GB is not a fair evaluation. |
| **Pilot (recommended)** | **4** | **16 GB** | **100 GB** | A real agency's feeds running continuously, weeks-to-months of retained data, the full UI in daily use. |
| Production / large feeds | 8 | 32 GB | 250 GB+ | Big-agency realtime volumes or long retention. |

OS: a current Ubuntu LTS (22.04/24.04) or equivalent with Docker Engine. Virtualization
(VMware/Hyper-V/KVM/cloud) is fine — Headway has no bare-metal needs.

## Where the resources actually go

Measured container memory on the reference deployment (16 GB would fit all of this):
TimescaleDB is the largest consumer by far (it will happily use what you give it — most of
its footprint is cache, not need), Kafka ~350 MB, transform ~1.7 GB during heavy replay,
MinIO ~250 MB, everything else under 150 MB each. CPU is bursty: normalization replays and
calculation runs use what's available and finish faster with more cores; steady-state
ingestion is light.

Disk grows with what you keep:
- **Raw records are immutable and content-addressed** — they only grow. Budget for your
  feed volume; GTFS-Realtime is the driver (a large agency's vehicle-position stream is
  hundreds of MB/day raw).
- **Normalized realtime predictions are the largest canonical table class**: measured at
  roughly 1 GB/hour normalized for a large agency's full trip-update stream. Headway ships
  with that connector **off by default** for exactly this reason — turn it on with a
  retention decision, not before. Smaller agencies see a small fraction of this.
- The reference deployment's database reached ~11 GB after two weeks of heavy multi-feed
  ingestion including deliberate large replays.

## Network

- **Outbound HTTPS only**: ghcr.io (signed images at install/upgrade time) and your data
  sources (GTFS/GTFS-RT URLs, vendor endpoints). No inbound access from the internet is
  needed or expected.
- **All service ports bind to 127.0.0.1 by default** (API 8000, web 8080, Grafana 3000,
  and the rest). To reach the UI from your workstation, either SSH-tunnel
  (`ssh -L 8080:localhost:8080 <vm>`) — the right default for an evaluation — or
  deliberately re-bind behind your organization's reverse proxy/TLS for shared use.

## Connecting agency data systems (what to line up)

The supported patterns are documented in [connecting-your-data.md](connecting-your-data.md).
For data living in a SQL database (report servers, vendor back-ends), the pilot-proven
pattern is **export-to-drop**: a scheduled job (e.g. SQL Agent) writes CSVs from
DBA-curated **read-only views** to a directory the Headway box can read — Headway's
file-drop intake handles stability, quarantine, and provenance from there. To prepare:

1. A **read-only database account** scoped to specific views (never tables, never write).
2. A firewall rule from the Headway host to the database host (TLS on).
3. One DBA-blessed view per data set — the view is the stable contract, so vendor schema
   changes don't silently break the mapping.

Native database polling connectors are on the [roadmap](../ROADMAP.md); the export pattern
is not a stopgap — it is the least-privilege integration most agency DBAs prefer.

---
*Numbers in this guide are re-measured when the reference deployment changes materially;
if your measured reality disagrees, please open an issue — honest numbers are the point.*
