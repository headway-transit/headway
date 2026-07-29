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
  and the rest). To reach the UI from elsewhere, pick a deliberate path — all three are
  walked through in plain language in [network-access.md](network-access.md):
  SSH-tunnel (`ssh -L 8080:localhost:8080 -L 8000:localhost:8000 <vm>`) — the right
  default for a one-person evaluation; the installer's office-access option
  (`./install/install.sh --reconfigure-access`, Compose profile `lan`: HTTPS via a
  pinned Caddy with a local CA); or your organization's own reverse proxy/VPN.

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

## The storage layer your `df` cannot see (virtualized installs)

Learned live from the first partner agency (2026-07-29): their Headway VM crashed
"out of storage" while the guest's own `df` showed **16% used**. Both statements
were true, because the exhaustion was one layer down — and most agency installs
run on that layer (vSphere, Hyper-V, Proxmox).

**Why it happens.** A *thin-provisioned* virtual disk grows every time a new
block is written and does not shrink when files are deleted. Docker image
rebuilds are exactly that workload: every `--update-from-source` writes fresh
image layers and build cache, the old ones are deleted in the guest, and the
virtual disk keeps the high-water mark. Add a forgotten VM *snapshot* — which
turns every write into growth in a delta file — and a 150 GB allocation can
exhaust its datastore while the guest believes it is nearly empty. When the
datastore fills, the hypervisor pauses or crashes the VM with no warning inside
the guest; from the console it looks like a mystery hang.

**What to ask your virtualization admin (once, at provisioning):**

- Is the disk thin- or thick-provisioned, and does the **datastore** have
  headroom beyond the sum of thin disks on it?
- Are there standing **snapshots** on the VM? Snapshots are for the minutes
  around a risky change, not for weeks — a snapshot left attached grows without
  bound and slows the VM.
- Is space reclamation wired through? Ubuntu runs `fstrim` weekly by default,
  but the discard only reaches the datastore when the virtual-disk layer
  passes it on (in vSphere terms: VMFS6 with unmap enabled, or an NFS
  datastore that honors hole-punching).

**What Headway does about its own share.** `--update-from-source` now cleans up
after itself: dangling image layers and build cache are pruned after every
successful update (running services, data volumes, and tagged release images —
including anything a rollback would need — are never touched). One-off manual
check, any time: `docker system df` shows what Docker holds; `docker image
prune -f` and `docker builder prune -f` are safe by the same rule.

**What this section is not.** Application-data growth — how long raw records,
telemetry and predictions are kept — is a records-retention question with legal
weight, owned by the agency and expressed per data class with its authority
cited (ADR-0012). Disk hygiene buys headroom; only a retention policy bounds
growth.
