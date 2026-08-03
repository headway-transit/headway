# Handoff: platform → transform — Resolving vendor APC trips to GTFS trips

## Context
The TripSpark Streets adapter (handoff 0016) carries the vendor's `TripName` verbatim
into `trip_id_performed` — e.g. `"12 - 12WD - 21:30"` (route – pattern – start time) —
while the agency's GTFS `trip_id` is an opaque UUID. They do not match, so passenger
counts cannot attach to operated trips, and every UPT figure over that data is blocked.
This is the recorded open question in the adapter README ("per-agency join config"), and
it is now the long pole for the first agency's real APC data.

### Verified against the partner agency's LIVE GTFS (orchestrator, 2026-07-29)

Their published feed, 2,704 trips, 23 routes, 851 stops:

| Join key | Result |
| --- | --- |
| (service, route short name, start time) | **500 collisions affecting 1,000 trips** — 37% ambiguous. Unusable alone. |
| (service, route short name, start time, **direction**) | **1 collision affecting 2 trips** — 2,702 of 2,704 uniquely identified |
| `StopCode` → stop | their `stops.txt` carries `stop_code` on **851 of 851**, and `stop_id` equals `stop_code` (`KE001`) — the export's StopCode matches directly |

The export carries `DirectionKey` (column 17, **currently unmapped**) and `PatternName`,
so the discriminating field is already in the data. The stop join needs no mapping layer
for this agency, but must not *assume* that shape for the next one.

## Design (binding)

1. **Resolution happens in transform, not in the adapter.** The adapter is a declarative
   mapping onto the contract and has no database; resolution needs `canonical.trips`.
   The adapter's job is to carry the vendor's identifiers faithfully — extend it to map
   `DirectionKey` (and keep `PatternName` available) so the resolver has what it needs.
2. **The resolver is per-agency configuration, not code.** A declarative resolution spec
   (alongside the mapping spec, same validation discipline): how to parse the vendor trip
   name into components, which GTFS fields each component matches, the direction
   convention, and the timezone. Nothing agency-specific may be hardcoded in Python.
3. **Ambiguity and misses are findings, never guesses.** Three outcomes, all explicit:
   - **resolved** — exactly one GTFS trip matches: `trip_id_performed` becomes the
     canonical trip id, and the vendor's original identifier is PRESERVED alongside it
     (never overwritten — it is the agency's own vocabulary and the audit path back to
     their system);
   - **ambiguous** — more than one match: the row is not resolved, and a DQ finding names
     the candidates. Picking the first would be inventing a fact. (Live expectation: ~2
     trips of 2,704 on this feed.)
   - **unmatched** — no GTFS trip: a DQ finding, with the parsed components stated so a
     human can see *why* it missed (wrong service day? trip not in the feed? an added
     trip?).
   Counts of each outcome are reported per file so an agency sees resolution quality at
   a glance, not one row at a time.
4. **Stops resolve on `stop_code`, with the fallback stated.** Match the export's stop
   identifier against GTFS `stop_code` first, then `stop_id`; an unmatched stop is a
   finding, not a silent drop. Do not hardcode the observed `stop_id == stop_code`
   coincidence.
5. **Direction is a mapping, not an assumption.** The vendor's `DirectionKey` values must
   be mapped to GTFS `direction_id` in the config, with the mapping stated. If the
   agency's convention is unknown, the resolver refuses rather than assuming 0/1 —
   record it as a config the agency confirms.
6. **Honest scope:** no UPT changes, no calc changes, no backfill of previously ingested
   rows in this wave (record the re-resolution question); resolution runs at normalization
   time and its outcome is part of the row's lineage.

## Outputs
Adapter update (DirectionKey mapped) + resolution spec schema + validation; transform
resolver with tests covering all three outcomes, the timezone/service-day boundary, and
a per-file summary; DQ findings wired with the agency-vocabulary treatment from handoff
0029 (subject refs, no id walls); migration only if one is genuinely needed (next number
**0036** — 0035 is taken); docs: `docs/connecting-your-data.md` gains a plain-language
section on what resolution is and what an agency sees when it partially fails; connector
/adapter README updated. **Verification honesty:** no real vendor export exists on this
box. Verify against the partner agency's REAL GTFS (fetch it — it is public) combined
with synthetic APC rows in the proven 18-column shape, and state plainly that the real
export has never been run through it and what will need re-checking when it arrives.
Evidence appended here. No commits — the orchestrator integrates.

## Open Questions
- Re-resolution of rows ingested before a config exists (a backfill/repair path).
- Whether an agency's block column, if their export gains one, closes the block-name gap
  from handoff 0029 automatically once trips resolve — check when the real export lands.
- Service-day rollover for after-midnight trips (the adapter README's existing caveat).

## Outputs — evidence

### Response — transform (2026-07-29)

Contract accepted and implemented in full. Every design point below is
verified against the live repo, the test suite, the live TimescaleDB, and
the partner agency's real published GTFS — re-derived, not trusted from the
Context table. One honest limitation is stated up front and again at the
end: **no real vendor export has ever been run through this resolver** (the
agency sample is gitignored and agency-identifiable); verification used the
REAL schedule feed plus synthetic APC rows in the committed fixtures' proven
18-column shape.

---

#### What was built

| Artifact | Path |
| --- | --- |
| Resolution spec contract (schema) | `contracts/adapter-resolution.v0.schema.json` |
| Resolution spec contract (prose) | `contracts/adapter-resolution.v0.md` (+ row in `contracts/README.md`) |
| First real config (REFUSING on purpose) | `adapters/tripspark/streets/resolution.v0.yaml` |
| Migration | `db/migrations/0036_trip_resolution.sql` — `canonical.service_calendars`, `canonical.service_calendar_dates`, `canonical.stops.stop_code`, `canonical.passenger_events.{vendor_trip_ref,trip_resolution}` (CHECK: resolved/ambiguous/unmatched), all additive, nothing backfilled |
| Calendar + stop_code normalization | `services/transform/headway_transform/gtfs_static.py` → `normalize_gtfs_static` **0.5.0** |
| Schedule index | `services/transform/headway_transform/schedule_index.py` (per-file read, never cached across files) |
| Resolver + spec loader + findings | `services/transform/headway_transform/adapters/resolution.py` |
| Engine/registry/harness/consumer/writer wiring | `adapters/engine.py` (resolver hook, per-ROW resolution under fan-out, third lineage edge), `adapters/registry.py` (resolution specs load + cross-check at startup, fail-loud), `adapters/harness.py` (validates any `resolution.v0.yaml`), `consumer.py`, `writer.py` |
| Tests | `services/transform/tests/test_trip_resolution.py` (21 tests) + updates to `test_gtfs_static.py`, `test_hardening.py`, `test_writer.py`, `test_adapters.py`, `conftest.py` |
| Docs | `docs/connecting-your-data.md` §3 Path C gains "Matching your counts to your schedule"; `adapters/README.md`; `adapters/tripspark/streets/README.md` (DirectionKey row updated, open question 1 closed into the resolution section); `services/transform/README.md` |

Design points 1–6 mapped to implementation:

1. **Resolution in transform** — the resolver runs inside `run_adapter` at
   normalization time; the adapter mapping spec is untouched except by
   documentation. `DirectionKey` (col 17) and `PatternName` (col 13) were
   already declared positional columns; the resolution config reads
   `DirectionKey` as a declared `from_column` and names `pattern` as a parsed
   component, so both are available to the resolver **declaratively** — no
   change to the mapped contract record was needed (TIDES has no direction
   field to map INTO, and the resolver reads the raw row + mapped record).
2. **Per-agency configuration, not code** — `resolution.v0.yaml`, schema-
   validated + cross-checked against the sibling mapping spec (same label,
   referenced fields actually mapped, referenced columns actually declared)
   at registry startup AND in `adapters/validate`. Zero agency vocabulary in
   Python: grep `headway_transform` for `TripName|DirectionKey|tripspark` —
   no hits outside comments/docstrings describing the mechanism.
3. **Three explicit outcomes** — `trip_resolution` CHECK-constrained to
   exactly `resolved|ambiguous|unmatched`; ambiguous/unmatched rows keep the
   vendor's trip id in `trip_id`, record the outcome, and aggregate into
   `trip_resolution_ambiguous` / `trip_resolution_unmatched` warning findings
   that name candidates or the full parse (capped list, true totals stated —
   handoff 0029 house style, subject-first: "route 64, 06:30, direction 1 on
   2026-07-02", internal ids as the footnote). Per-file
   `trip_resolution_summary` info finding states N of M at a glance.
   The vendor id is PRESERVED: resolved rows carry it in `vendor_trip_ref`
   verbatim, and the mapped CONTRACT record keeps `trip_id_performed`
   untouched.
4. **Stops on stop_code with the fallback stated** — `stop.match_order:
   [stop_code, stop_id]` is DECLARED config; unknown stop codes and blank
   stop codes each become `stop_resolution_unmatched` warnings; nothing is
   written to the row in v0 (the passenger_events stop-column gap from
   handoff 0011 stands, restated in the contract prose).
5. **Direction is a mapping the agency confirms** — the committed config has
   `confirmed: false` + a plain-language `unconfirmed_reason`; the resolver
   REFUSES (maps the file exactly as before, resolves nothing, one
   `trip_resolution_not_confirmed` warning per file telling the agency the
   one thing to confirm). The schema forces `values` + `confirmed_by` +
   `confirmed_on` before `confirmed: true` is even representable.
6. **Honest scope** — no UPT/calc changes (services/calc untouched), no
   backfill (0 pre-0036 rows modified, proven below), resolution outcome in
   lineage via a third edge per resolved row
   (`resolve_trips:tripspark_streets`, version = config content hash,
   input = the canonical trip).

---

#### Re-derivation against the agency's REAL published GTFS

Fetched live myself (not reused from the orchestrator):
`https://myride.bft.org/Static/google_transit.zip`, 2026-07-29, sha256
`a2a2ded44525bb68afd6dbdd08fef76e66da17a4bab34dce43423aaead470feb`, feed
version "0626 Fixed Rev 1", validity 2026-06-14..2026-12-12.

The feed was pushed through the PRODUCTION `normalize_gtfs_static` 0.5.0
(not ad-hoc parsing), and the collision counts re-derived through the
production `ScheduleIndex`:

```
normalized: routes=23 trips=2704 stops=851 stop_times=75146 agencies=1
            calendars=3 calendar_dates=3 edges=78731 findings=0
stop_code coverage: 851 of 851 | stop_id == stop_code on 851 of 851
trips with a first departure: 2704 of 2704
(service, route_short_name, start): 500 colliding keys / 1000 trips of 2704
(service, route_short_name, start, direction): 1 colliding keys / 2 trips of 2704
residual collision: route 64, 06:30, direction 1, service 9e843cf6… ->
  ['4d54cbe5-5546-4281-88d5-a97b466148d0', '8a2e3786-6dac-4895-aa45-aae9a8dd1015']
services active 2026-07-02 (Thu): ['9e843cf6…']
services active 2026-07-04 (Sat, removed by exception): []   <- calendar_dates works
```

**The Context table's numbers check out exactly**: 500/1,000 without
direction, 1/2 with it, stop_code on 851/851 equal to stop_id. Additional
facts I derived that the summary did not state: the residual pair is route
64's 06:30 weekday departure (two schedule variants with different headsigns
and blocks — genuinely indistinguishable from (route, time, direction), so
`ambiguous` is the CORRECT answer for them, expected live rate 2 of 2,704);
dropping the service component collides 823 keys / 1,816 trips (measured
while choosing the key, recorded in the config's provenance); no trip in
this feed starts at or past 24:00:00 today, so the rollover question is
currently latent, not moot — the config still declares `not_confirmed`.
GTFS facts used (calendar semantics, stop_code definition, calendar.txt
conditional requirement) were verified against the GTFS Schedule Reference
at gtfs.org on 2026-07-29 and cited in code/migration comments.

#### The three outcomes, end to end, against the real feed

Synthetic 18-column rows (committed-fixture shape) aimed at real scheduled
facts, through the production `run_adapter` + `TripResolver`:

- Committed (UNCONFIRMED) config first — the honest live state:
  ```
  mapped: 5 | outcomes: {}   (nothing resolved — refusal, not failure)
  finding [warning] trip_resolution_not_confirmed: Passenger counts are not
    being matched to scheduled trips for tripspark_streets — one setting
    needs your confirmation
  row unchanged: trip_id: '42 - 42WD - 13:00'  vendor_trip_ref: None
    trip_resolution: None
  ```
- Then a confirmed VARIANT (direction values invented for verification only,
  marked as such in its provenance — the real mapping remains the agency's
  to state):
  ```
  total: 5 mapped: 5 | outcomes: {'resolved': 2, 'ambiguous': 1, 'unmatched': 2}
    resolved   '42 - 42WD - 13:00' -> a42e79cb-d75b-43f4-a535-801e2211837a
    ambiguous  '64 - 64WD - 06:30' -> - candidates=[4d54cbe5…, 8a2e3786…]
    unmatched  '42 - 42WD - 03:33' -> -   (no such start; parse stated)
    unmatched  '42 - 42WD - 13:00' -> -   (DirectionKey '9' unmapped; never guessed)
    resolved   '42 - 42WD - 13:00' -> a42e79cb-d75b-43f4-a535-801e2211837a
  resolved events: trip_id = canonical UUID, vendor_trip_ref = '42 - 42WD - 13:00'
  resolution lineage edges: 4 -> ['a42e79cb-d75b-43f4-a535-801e2211837a']
  stop finding: NOPE99 not in schedule, "checked against stop_code then
    stop_id … counts still land — nothing was dropped"
  deterministic re-run identical: True
  ```
  (10 canonical events from 5 rows — fan-out; each carries its row's single
  outcome. The service-day boundary is separately pinned by two unit tests:
  `not_confirmed` reports the after-midnight reading that WOULD match
  without using it; `calendar_date` resolves a GTFS 25:10 trip appearing at
  01:10 the next calendar day.)

#### Live database (compose TimescaleDB)

- Migration **0036 applied**: `applying 0036_trip_resolution.sql ... ok`,
  `schema_migrations` row at 2026-07-29 22:51:04 UTC. (It queued ~5 minutes
  behind the live transform consumer's in-flight transaction for the ALTER
  TABLE lock — expected, waited, no service was restarted.)
- New tables/columns present (information_schema check pasted in session):
  `service_calendars`, `service_calendar_dates`, `stops.stop_code`,
  `passenger_events.{vendor_trip_ref,trip_resolution}` all nullable TEXT.
- **Additive proven**: `count(*) where vendor_trip_ref is not null or
  trip_resolution is not null` over 204k live passenger_events = **0**.
- `load_schedule_index(conn)` ran against the live schema: 124,498 trips,
  0 calendars (the live feed was normalized before 0.5.0 — until it is
  re-ingested, resolution over it would honestly report "the schedule feed
  defines no service days", which is the designed fail-loud path, and the
  live adapter refuses on direction anyway).
- New INSERT round-trips: a row with `('GTFS-TRIP-X', '12 - 12WD - 21:30',
  'resolved')` inserted and read back inside a transaction, then rolled
  back (0 rows after). CHECK constraint verified in the catalog:
  `trip_resolution = ANY (ARRAY['resolved','ambiguous','unmatched'])`. A
  live bad-value insert attempt was abandoned after hitting hypertable
  chunk-lock contention with the busy consumer (timeout, rolled back,
  nothing landed) — the constraint's enforcement rests on the catalog
  definition plus Postgres semantics, and is additionally uncovered by no
  code path: the writer only ever binds the three literals or None.

#### Test + harness runs (captured this session)

```
services/transform: 203 passed in 4.15s   (was 182 before this wave; +21 in
                    test_trip_resolution.py, existing suites updated for the
                    9-tuple normalize and 12-column passenger-event insert)
adapters/validate:  ALL CHECKS PASSED — 4 adapters; tripspark/streets now
                    also reports: "resolution config ffcfcea68056: schema +
                    cross-spec checks OK (direction convention NOT CONFIRMED
                    — the resolver refuses and records a finding until the
                    agency confirms it)"
```

Pre-existing breakage found, NOT fixed (out of scope, other tree):
`tools/canonical-replace/tests/test_output_id_builders.py::test_routes_and_trips_builders_match_normalizer`
unpacks `normalize()` into 4 values; it already failed at HEAD (normalize
has returned 7 values since 0.3.0) and now needs 9. One-line fix for
whoever owns `tools/`.

#### Deliberately NOT built

- **No re-resolution/backfill** of previously ingested rows (open question
  stands; outcome-at-normalization-time is part of lineage, so repair is a
  re-run, not an UPDATE — recorded in the migration header).
- **No automatic direction inference** (e.g. correlating StopCode sequences
  against scheduled stop patterns to deduce the DirectionKey convention). It
  would probably work and it is exactly the kind of guess the handoff
  forbids; the agency confirming two values is minutes of work.
- **No stop id written onto passenger-event rows** — blocked on the
  contract-level stop-identity column (handoff 0011 gap), restated rather
  than smuggled in.
- **No calc/UPT changes, no API/UI surface** — other waves own those trees;
  the findings flow through the existing dq.issues path.
- **No `emit`-level resolution** — resolution is per vendor ROW by
  construction (a stop visit's board and alight are one trip).

#### What MUST be re-verified when the agency's real export arrives

1. **DirectionKey vocabulary** — the actual values and their meaning;
   agency confirms, `values`/`confirmed_by`/`confirmed_on` land, `confirmed:
   true`, re-drop a file, check the summary finding reports a plausible
   resolved rate (~2,702/2,704 of scheduled trips are uniquely keyed).
2. **TripName shape across a full day** — separator exactly `" - "`, start
   time exactly `%H:%M`, route component matches `route_short_name`
   verbatim (padding? leading zeros?) over thousands of rows, not 12.
3. **Service-day rollover** — an export spanning midnight settles
   `not_confirmed` vs `calendar_date`; the unmatched findings will point at
   it explicitly if the convention is the other one.
4. **StopCode coverage in production** — retired/new codes vs the loaded
   feed; the `stop_resolution_unmatched` counts are the measure.
5. **Re-ingest the agency's static feed** after deploy so 0.5.0 populates
   `service_calendars`/`stop_code` in the live database (upsert path —
   re-dropping the current zip suffices).
6. **The residual route-64 pair** — confirm with the agency which variant
   operates (or that their APC export carries a further discriminant, e.g. a
   block/pattern the config could match on in a v1 key).

### Open Questions (updated)
- Re-resolution/backfill path — unchanged, still open, recorded in 0036's
  header.
- Block-name gap (handoff 0029) — untouched here; note that once trips
  resolve, `canonical.trips.block_id` becomes reachable FROM passenger
  events via the resolved trip_id, which may close part of it for free —
  check when the real export lands.
- Service-day rollover — now a declared, refuse-by-default config field
  (`service_day_rollover`), no longer a silent caveat.
