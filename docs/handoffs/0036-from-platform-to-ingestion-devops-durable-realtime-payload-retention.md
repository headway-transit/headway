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
