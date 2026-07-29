# Adapter Trip-Resolution Spec v0 (`resolution.v0.yaml`)

The machine contract is `adapter-resolution.v0.schema.json` — this document is
the prose companion (handoff 0031). A resolution spec sits NEXT TO an
adapter's `mapping.v0.yaml` and declares, per agency, how the vendor export's
own trip identifier is matched against the agency's GTFS schedule already in
`canonical.trips`. It is optional: an adapter without one carries the
vendor's identifier through untouched, exactly as before.

## Why this exists

A vendor APC export names a trip in the agency's operational vocabulary —
`"12 - 12WD - 21:30"`, route – pattern – start time — while the agency's GTFS
`trip_id` is an opaque id. They never match, so passenger counts cannot
attach to operated trips, and every UPT figure over that data is blocked.
The join is agency-specific (naming convention, direction vocabulary,
timezone, service-day rollover), so it is **configuration validated like a
contract**, never code.

## The join key is measured, not assumed

All four `trip.match` clauses are required, and that is an empirical
decision. On the first partner agency's live published feed (2,704 trips,
retrieved 2026-07-29, re-derived by the implementing agent — see handoff
0031 evidence):

| Key | Collisions |
| --- | --- |
| (service, route short name, start time) | 500 keys / 1,000 trips — 37% ambiguous |
| + direction | **1 key / 2 trips** |
| without service | 823 keys / 1,816 trips |

A weaker key does not resolve; it manufactures ambiguity.

## The three outcomes (all explicit, none a guess)

- **resolved** — exactly one scheduled trip matches. The canonical row's
  `trip_id` becomes that trip; the vendor's identifier is **preserved** in
  `vendor_trip_ref` (migration 0036) — it is the agency's own vocabulary and
  the audit path back into their system, and it is never overwritten. A
  lineage edge (`resolve_trips:<source_label>`, version = the spec's content
  hash) records that the assignment is a derived fact.
- **ambiguous** — more than one matches. The row keeps the vendor's
  identifier, `trip_resolution = 'ambiguous'`, and a DQ finding names the
  candidates. Picking the first would invent a fact.
- **unmatched** — none matches. Same row treatment, and the finding states
  what was parsed and what was searched — including, when relevant, the
  after-midnight reading that *would* have matched but is not confirmed.

Counts of all three are summarized once per file
(`trip_resolution_summary`), so resolution quality is visible at a glance.

## The refusal rule (direction)

GTFS assigns **no meaning** to `direction_id` 0 and 1 — which vendor value
maps to which is an agency fact. While `trip.match.direction.confirmed` is
`false`, the resolver resolves **nothing** for the source and records one
`trip_resolution_not_confirmed` finding per file, carrying the spec's
`unconfirmed_reason` verbatim. A 50/50 direction guess would attach counts
to the wrong trips with nothing downstream looking wrong; refusing is the
specified behavior. Confirming requires `values`, `confirmed_by`, and
`confirmed_on` — the schema enforces it.

## Service days and the midnight boundary

Candidates are limited to the GTFS services active on the row's service date
(`canonical.service_calendars` + `canonical.service_calendar_dates`,
migration 0036; the GTFS rules — weekday flags inside inclusive bounds,
exceptions win — are applied at read time). `service_day_rollover` declares
how the export dates a trip that runs past midnight: `calendar_date` also
searches the previous service day at `start + 24h`; `not_confirmed` does
not use that reading but names it in the unmatched finding when it would
have matched, so a human confirms the convention instead of diagnosing a
symptom.

## Stops (v0: checked, not written)

The optional `stop` clause checks the export's stop identifier against
`canonical.stops` in the declared `match_order` (e.g. `stop_code` then
`stop_id` — declared because some feeds make them equal by coincidence, and
a coincidence must not become an assumption). v0 writes nothing onto the
row — the canonical `passenger_events` subset carries no stop-identity
column yet (the handoff 0011 gap) — it exists so an unknown stop is a
finding, never a silence.

## Provenance (honesty is a schema field)

`provenance.verified_against.schedule_feed` records the feed the key's
uniqueness was **measured** against, in numbers.
`provenance.verified_against.vendor_export.status` states whether a real
vendor export has ever been run through the config (`none_available` /
`sample` / `production`) with a note on what remains unverified. The same
BINDING rule as mapping specs applies: no vendor documentation is quoted,
excerpted, cited, or paraphrased.

## Runtime guarantees

Loaded and cross-checked against the sibling mapping spec at registry
startup (label agreement, referenced fields mapped, referenced columns
declared) — a broken config fails the registry loudly. Resolution runs at
normalization time inside the adapter engine; per mapped **row** (a
boarding and alighting from one stop visit resolve once); deterministic
(same file + same spec + same schedule ⇒ identical rows, edges, findings);
and additive (rows written before a config existed keep NULL in both new
columns and are not rewritten — re-resolution is a recorded open question,
not a silent backfill).
