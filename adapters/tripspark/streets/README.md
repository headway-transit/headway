# TripSpark Streets APC → TIDES `passenger_events`

The FIRST real vendor adapter (handoff 0015 follow-up, 2026-07-16). It maps
the partner agency's **APC stop-visit data pull** — a scheduled CSV export
from the agency's own fixed-route reporting warehouse — onto TIDES
`passenger_events`. Everything in this directory is derived exclusively from
the agency's own sample export and the agency's description of its own data
(handoff 0015 Addendum, BINDING: no vendor documentation is quoted,
excerpted, cited, or paraphrased in any committed artifact).

**Registered source label:** `tripspark_streets` — point the vendor-file
connector at a drop directory with `VENDOR_SOURCE=tripspark_streets`
(`adapters/README.md`, "Running an adapter in the pipeline").

## The export

- **Headerless CSV**, UTF-8 with BOM, comma-delimited: 18 positional columns
  per row, declared in `mapping.v0.yaml` (`source_format.csv.header: false`
  + `columns`). There is no header to check a wrong export against, so a row
  whose field count differs from the declared 18 positions quarantines with
  a reason.
- **One row per APC stop-visit report.** Timestamps (`EventDateISO`) are
  ISO-8601 **local** wall-clock times; the zone is declared
  (`America/Los_Angeles`), never guessed — DST-ambiguous/nonexistent wall
  times quarantine.
- The export **repeats stop rows with 0/0 counts** while a vehicle dwells
  ("dwell pings"). They carry no passenger activity and are suppressed with
  a declared reason (harmless under summation either way; suppression keeps
  the canonical table free of zero-information events).

## Column → contract mapping

| Pos | Column | Maps to | How |
| --- | --- | --- | --- |
| 1 | `VehicleLocationAPCKey` | `passenger_event_id` (part) | the export's unique row key; concat with StopCode + per-emission suffix `:board` / `:alight` |
| 2 | `VehicleName` | `vehicle_id` | string |
| 3 | `TotalCount` | — | onboard-load counter; **drifts, not mapped in v0** |
| 4 | `BoardCount` | `event_count` (boarded emission) | integer; `0`/blank suppresses the emission with a reason |
| 5 | `AlightCount` | `event_count` (alighted emission) | integer; `0`/blank suppresses the emission with a reason |
| 6 | `UnmodifiedAlightCount` | — | pre-balancing alight count; **future provenance surface, not mapped in v0** |
| 7 | `APCSource` | — | not mapped in v0 (candidate future provenance: count-source discrimination) |
| 8–9 | `IsTripper`, `IsDetour` | — | not mapped in v0 |
| 10 | `TripName` | `trip_id_performed` | "route - pattern - trip start time"; the stable trip identifier in this export |
| 11–13 | `RouteName`, `RouteShortName`, `PatternName` | — | redundant with the trip identity; deliberately not carried |
| 14 | `StopName` | — | display text; deliberately not carried |
| 15 | `StopCode` | `passenger_event_id` (part) | the stop identifier (matches the agency's GTFS `stop_code`); preserved inside the event id — see open questions |
| 16 | `PatternPointRank` | `trip_stop_sequence` | the stop's rank within the pattern (integer; TIDES minimum 1 enforced by contract validation) |
| 17 | `DirectionKey` | — | not mapped in v0 (direction is derivable from the trip/pattern identity) |
| 18 | `EventDateISO` | `event_timestamp` | `datetime` `%Y-%m-%dT%H:%M:%S`, localized to America/Los_Angeles, emitted UTC |
| — | — | `service_date` | `local_date_of` event_timestamp (see caveat below) |

**Fan-out (`emit`):** one stop-visit row emits a `Passenger boarded` record
(count = `BoardCount`) and/or a `Passenger alighted` record (count =
`AlightCount`). Rows are atomic — if either non-suppressed emission fails
coercion or contract validation, the whole row quarantines and emits
nothing. A row with both emissions suppressed (a dwell ping) counts as
filtered.

**Filter:** rows with a blank `TripName` (unassigned APC reports) are out of
scope by declaration — this spec maps the *assigned* export.

## Caveats and open questions

1. **Trip-identifier resolution (future, per-agency join config).**
   `TripName` is carried verbatim into `trip_id_performed`. Joining it to
   canonical GTFS `trip_id`s (route short name + pattern + start time →
   scheduled trip) needs a per-agency resolution config; until then,
   trip-level metrics that join APC events to GTFS trips will not match
   these events.
2. **`StopCode` → GTFS `stop_id` resolution.** The canonical
   `passenger_events` subset carries no stop-identity column yet (the same
   gap that leaves rail PMT events unplaceable — handoff 0011). `StopCode`
   matches the agency's GTFS `stop_code`; it is preserved inside
   `passenger_event_id` (`<rowkey>:<stopcode>:<board|alight>`) so no
   information is lost, and moves to a first-class column when the contract
   gains one.
3. **`service_date` is the local CALENDAR date** of the event. The export's
   service-day rollover convention for after-midnight trips is not
   derivable from the verified sample (an evening window); verify against a
   sample spanning midnight before trusting day-boundary aggregations.
4. **`UnmodifiedAlightCount`** (pre-balancing) and **`APCSource`** are
   candidate future provenance surfaces (how much did balancing move the
   counts; which counting mechanism produced them) — not mapped in v0.
5. **The balancing log** the warehouse also maintains is its own future
   adapter (a corrections/audit feed), not part of this spec.

## Fixtures

The committed fixtures are fully **synthetic** re-creations of the sample's
shape (see the provenance block): same 18 headerless positional columns,
formats, and edge cases — invented stop/route/trip vocabulary throughout.

- `stop_visits.csv` — 12 rows: 3 mapped (both-counts → 2 records;
  board-only; alight-only = **4 emitted records**), 4 filtered (two repeated
  same-stop 0/0 dwell pings + one more dwell ping via emission suppression;
  one unassigned-style blank-TripName row via the filter), 5 quarantined
  (non-integer count, non-ISO timestamp, DST spring-forward wall time,
  pattern rank 0 rejected by contract validation, 17-field width mismatch).
- `wrong_width_export.csv` — a different 12-column export dropped in the
  wrong directory: every row quarantines on width (the headerless analog of
  the header-mismatch file refusal).
