# Acme StopCount → TIDES `passenger_events` (reference adapter — INVENTED format)

> Synthetic template. No real vendor or agency data. See `../../README.md`
> for the feature matrix and `adapters/README.md` for the rules real adapters
> follow.

**The invented story:** fixed-route buses carry "Acme StopCount" automatic
passenger counters; the back office exports one HEADERLESS comma-delimited
file per unit per day — one row per stop visit, with an `Ons` column and an
`Offs` column on the same row. Device clocks are agency-local
(America/Chicago).

This product exists to exercise the two mapping-spec v0 extensions added for
the first real adapter (TripSpark Streets, 2026-07-16):

1. **Headerless positional columns** — `source_format.csv.header: false` +
   `columns`: the spec declares the positions (from the sample); a row whose
   field count differs from the declared width quarantines with a reason
   (there is no header to refuse a wrong export against, so the defense is
   per-row).
2. **`emit` fan-out** — one stop-visit row emits up to two TIDES events
   (`Passenger boarded` from `Ons`, `Passenger alighted` from `Offs`), each
   emission overriding `passenger_event_id` (concat `suffix` keeps the two
   ids distinct), `event_type`, and `event_count`. A zero/blank count
   suppresses that emission with a declared reason (aggregated
   `adapter_emissions_filtered` info finding); a row with BOTH emissions
   suppressed — a dwell ping — counts as filtered. Rows are atomic: if any
   non-suppressed emission fails, the whole row quarantines and emits
   nothing.

## Source columns → contract fields

| Position | Column | Maps to | How |
| --- | --- | --- | --- |
| 1 | `RowKey` | `passenger_event_id` | per emission: concat + suffix `:ons` / `:offs` |
| 2 | `UnitNo` | `vehicle_id` | string |
| 3 | `Ons` | `event_count` (boarded emission) | integer; `0`/blank suppresses the emission |
| 4 | `Offs` | `event_count` (alighted emission) | integer; `0`/blank suppresses the emission |
| 5 | `StopRef` | — | not mapped in v0 (TIDES stop identity is a pending contract increment) |
| 6 | `StopSeq` | `trip_stop_sequence` | integer (TIDES minimum 1 enforced by contract validation) |
| 7 | `Kind` | — (filter) | only `VISIT` rows map; `TEST` self-tests filtered with a reason |
| 8 | `LocalTime` | `event_timestamp` | `datetime` `%Y-%m-%d %H:%M:%S`, localized to America/Chicago, emitted UTC |
| — | — | `service_date` | `local_date_of` event_timestamp |

## Fixture (`stopcount_day.csv`, 10 reader rows)

3 mapped (both-counts → 2 records; ons-only → 1; offs-only → 1 = **4 emitted
records**), 3 filtered (0/0 dwell ping + blank/blank row via emission
suppression; one `TEST` row via the row filter), 4 quarantined (non-integer
`Ons`; stop sequence 0 rejected by contract validation; one 9-field row and
one 7-field row — width mismatches against the declared 8 positional
columns).
