# Handoff: platform → ingestion+devops — Durable realtime payload retention (close the chain-of-custody hole)

## Context

Handoff 0035's inspector wave measured the platform's largest standing evidence gap:
**55,784 of 55,811 raw records — 99.9%, and every realtime lineage leaf — store their
bytes only in the Kafka envelope** (`payload_encoding = base64`, `payload_ref` NULL).
The GTFS-Realtime connector never writes the object store; it base64-encodes the frame
into the ingest envelope and produces to `raw.gtfs_rt.*`. The broker is the only place
those bytes exist, and broker retention is a deployment knob, not a records policy.

On this box the retained window starts **2026-07-23 14:33 UTC** (offset 39,271 of
60,281 at measurement time). Every figure computed from earlier realtime records walks
back to a label and a hash whose bytes **cannot be produced at all** — the API says so
honestly (410 `not_retained`, by design, no DQ finding), but honesty about a hole is
not the same as not having one.

Set against ADR-0012 this is a chain-of-custody defect: the 2026 NTD Policy Manual
(on file) requires source documents retained *"for a minimum of three years"*, the
Independent Auditor Statement instructs the auditor to sample three months of them,
and the data these leaves support is exactly the VRM/VRH the first partner agency's
figures rest on. A triennial review asking for the source records behind an
eight-month-old VRH figure would today get a label and no bytes. **Every day this
ships later is another day of evidence permanently lost on every running install** —
including the partner agency's VM, whose broker has its own (default, likely 7-day)
retention window.

## Design (binding)

1. **Land realtime frames in the object store like every other connector.** The
   GTFS-Realtime connector gains the store-before-produce step the tides/samsara/
   vendorfile connectors already have (`objectstore.go` pattern): write the exact
   received bytes to the raw bucket **before** producing the envelope. Ordering is
   the platform's store-before-produce fence — a frame that cannot be durably stored
   is not produced (fail loudly, retry with backoff; never produce-then-hope).

   *Why this option and not long/infinite topic retention:* the broker is the wire,
   not the system of record (ADR-0006 posture). Topic retention is a per-deployment
   knob any operator can mis-set once and silently destroy three years of evidence;
   object-store contents are what ADR-0012's per-class retention policy, backups, and
   the inspector's `ObjectStorePayloadReader` already govern and read. Uniformity is
   itself a control: one retention story, one reader path, no source is special.

2. **Object key = content address.** `record_id` is already the lowercase-hex SHA-256
   of the payload bytes (migration 0002). Key objects deterministically as
   `raw/gtfs_rt/<feed>/<record_id>.pb` — or an equivalent scheme where the full key is
   derivable from columns `raw.records` already holds. This is what makes backfill
   possible without touching the immutable index (design point 5).

3. **Contract change is additive only.** The ingest envelope for `raw.gtfs_rt.*`
   keeps carrying the inline base64 payload (transform continues to normalize
   straight off the wire with no new MinIO dependency); the envelope/record gains the
   object reference additively. New `raw.records` rows for gtfs_rt land with
   `payload_encoding = object_ref` + `payload_ref` set, exactly like every other
   source. If keeping the inline copy alongside `object_ref` collides with an
   existing envelope-schema exclusivity assumption, resolve it additively (same spec
   version per the ratified additive-extension rule) and record the resolution; do
   not bump to v1 for this.

4. **Backfill what the broker still holds — now, before it ages out.** A one-shot
   tool (suggested: `tools/` or a connector subcommand — your call, record it) that
   scans `raw.gtfs_rt.*` from the earliest retained offset, re-hashes every payload,
   and for each hash matching a `raw.records` row with `payload_ref` NULL writes the
   bytes to the deterministic key from design point 2. Idempotent (content-addressed
   writes make re-runs harmless), resumable, and it reports counts: matched/written/
   already-present/unmatched. It must **re-hash before writing** — the message key is
   not trusted as proof of identity (0035's rule).

5. **`raw.records` is never mutated.** The immutability trigger stands. Legacy rows
   keep `payload_encoding = base64` forever; instead the API's payload reader
   (`headway_api/raw_payloads.py`) resolves base64 rows by checking the object store
   at the deterministic key **first** (re-hash on read, as always), falling back to
   the bounded envelope-stream lookup, then 410. After backfill, a legacy record whose
   bytes were rescued verifies from durable storage; the row itself is untouched.

6. **DevOps wiring.** The gtfsrt connector container gains the MinIO env/creds the
   other connectors already receive (compose + install.sh); bootstrap already creates
   the bucket. No object-store lifecycle/expiry rules on the raw bucket — deletion is
   ADR-0012 tombstone territory, not an infra knob; say so in a comment where an
   operator would look for one. Update `docs/sizing.md` with the measured growth rate
   (design point 8) so the disk line item is honest.

7. **The honest position on what is already unrecoverable.** Measure and record, in
   this handoff's evidence section: (a) how many gtfs_rt records on this box have
   bytes neither in the object store nor the retained broker window, by earliest/
   latest `fetched_at`; (b) how many persisted figures have at least one such leaf
   (lineage walk). No DQ finding is raised — 0035 ruled `not_retained` is not a
   defect in the record, and nothing about the figures' computation changed — but the
   numbers belong in writing here, and `docs/` wherever retention is described should
   state plainly that records ingested before durable landing was deployed may be
   label-only. The 410 remains the API's answer for them, permanently.

8. **Measure, don't estimate, the storage cost.** Real per-frame sizes (VP vs TU vs
   alerts differ by an order of magnitude), frames/day at current poll cadence, and
   the projected 3-year footprint. If TU frames make per-frame objects expensive,
   note options (e.g. poll-cadence config, compression) but **do not** implement
   sampling or dropping — every received frame lands. Fail loudly if the store
   refuses writes (disk full is a page, not a skip).

## Outputs

Connector change + `objectstore` reuse + tests (Go unit; integration against
disposable MinIO via `sg docker -c` if it runs, else say so); backfill tool + run it
live on this box and report the counts; API reader fallback change + tests (api suite
green — note CI now installs `[test,ingest]` for the api matrix job); compose/install
wiring; sizing/docs updates; the unrecoverable-set measurement (design point 7);
evidence appended here. No commits — the orchestrator integrates.

## Open Questions

- Partner-agency rollout: after integrate, `--update-from-source` on their VM stops
  their ongoing loss; their broker window likely still holds ~7 days to backfill —
  worth a same-day nudge to Tony once merged.
- Whether replayed/duplicate frames (same hash re-fetched later) should refresh any
  object metadata (harmless either way; content addressing dedupes).
- Whether `raw.gtfs_rt.*` topic retention should be *shortened* once the store is
  authoritative (broker back to being just the wire) — DevOps judgment, later.
- Bulk verification over a figure's whole evidence chain (0035 open item) gets much
  cheaper once leaves live in the store — natural v1 after this.

## Outputs — evidence

**2026-07-31, Ingestion + DevOps (built by a Fable agent; integrated and
live-verified by the orchestrator after the agent hit its usage limit before
writing this section). Everything below was RUN and OBSERVED on this box.**

### What shipped (files)

- `services/ingestion/connectors/gtfsrt/objectstore.go` — `ObjectKey(recordID)`
  = `raw/gtfs_rt/<record_id>.pb` (content-addressed) + a `MinioStore` that never
  rewrites an existing key.
- `services/ingestion/connectors/gtfsrt/gtfsrt.go` + `main.go` wiring —
  **store-before-produce**: a frame is landed durably before its envelope is
  produced; a frame that cannot be stored is not produced (fail loudly). The
  envelope keeps carrying the inline base64 payload (design point 3, additive)
  so transform normalizes off the wire with no new MinIO dependency.
- `contracts/raw-record-envelope.v0.schema.json` + `contracts/topics.v0.md` —
  the object reference added additively (same spec version).
- `services/api/headway_api/raw_payloads.py` — the reader now resolves a
  `base64` row **object-store-first** at the deterministic key (re-hash on
  read), then falls back to the bounded envelope-stream lookup, then 410.
  `raw.records` is never mutated (immutability trigger stands, design point 5).
- `services/ingestion/cmd/headway-gtfsrt-backfill/` — the one-shot rescue tool
  (dry-run flag, idempotent, resumable, re-hashes before writing, fails loudly).
- `deploy/compose/compose.yaml` — gtfsrt connector gets the MinIO env; a
  comment marks the deliberate absence of any lifecycle/expiry rule on the raw
  bucket (deletion is ADR-0012 tombstone territory, not an infra knob).
- `docs/sizing.md` — measured growth line (below).
- Tests: transform 209 (+2), api 470 (+10, raw_records 52), Go builds + `go vet`
  clean, gtfsrt unit + integration tests.

### The honest unrecoverable measurement (design point 7), live

Against the live DB and broker, `2026-07-31`:

| Fact | Value |
| --- | --- |
| gtfs_rt raw records, bytes NOT in the object store at ingest | 56,718 (100% of gtfs_rt; every one `payload_encoding=base64`, `payload_ref` NULL) |
| Broker retention boundary (earliest retained VP offset 39,271) | **2026-07-23 14:33:10 UTC** |
| Records BEFORE the boundary — **bytes permanently gone** | **35,106** (fetched 2026-07-09 14:15 → 2026-07-23 14:33) |
| Records at/after the boundary — still in the broker window | 21,616 |
| `raw.gtfs_rt.trip_updates` / `.alerts` retained | 113→113 / 0→0 — **retain nothing**; their few records are in the lost set |
| Persisted figures with ≥1 permanently-lost lineage leaf | **375 of 805** — **3 certified**, 372 uncertified |

The 3 **certified** figures with a lost leaf are the sharpest edge: someone
attested to them, and their source records can no longer be produced. Per
handoff 0035 this raises **no** DQ finding (nothing about the figures'
computation changed; `not_retained` is not a record defect) and the API's
answer for those leaves stays a permanent, honest 410. `docs/sizing.md` states
plainly that records ingested before durable landing may be label-only.

### The rescue, run live

The backfill was run (dry-run then live) against the retained window:

```
TOTAL [LIVE, 16.8s]: scanned=21617 matched=21616 written=54
  already_present=21562 row_has_ref=0 unmatched=1 key_mismatch=0
  write_failures=0 bytes=1,102,303,489 (~1.1 GB)
rows_still_unrescued=35106  (the permanently-lost set above)
```

`already_present=21562` because the Fable agent had already run the rescue
during its work; this orchestrator run wrote the 54 that accumulated since.
`unmatched=1` is a single `connector='proof'` test record whose hash matches
no index row — expected debris, not a defect. **Verified in MinIO:** 21,616
objects now live under `raw/gtfs_rt/`, and a sampled key
(`000166134f…c7f298.pb`) maps to a real gtfs_rt `raw.records` row fetched
2026-07-25 — bytes that were broker-only are now durable at the content
address the reader checks first.

### Measured storage cost (design point 8)

Rescued 21,616 VP frames = ~1.10 GB → **~51 KB/frame average** (min 282 B, max
90,281 B). This box polls VP roughly every ~30 s; TU/alerts are negligible here.
At ~51 KB/frame and a ~30 s cadence a 3-year VP footprint is on the order of a
few hundred GB uncompressed — real, and now the sizing doc's problem to state
rather than a surprise. No sampling or frame-dropping was introduced: every
received frame lands, and a store write failure is a loud failure, never a skip.

### Still open / for the deployment

- **The running ingestion container is still the pre-change image** (2 weeks
  old), so new frames land base64-only until it is rebuilt — `--update-from-source`
  on each box (including the partner VM) is what stops the ongoing loss. The 54
  freshly-rescued frames are the accumulation since the agent's run; that trickle
  continues until the rebuild.
- Object-store outage path is covered by a test but was not exercised by
  stopping MinIO here.
- Partner-agency nudge (Open Questions): their broker likely still holds ~7 days
  — worth backfilling there right after they update.
