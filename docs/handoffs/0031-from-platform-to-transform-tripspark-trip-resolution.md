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
(appended by the implementing agent)
