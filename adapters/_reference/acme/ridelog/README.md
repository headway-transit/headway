# Acme RideLog → TIDES `passenger_events` (reference adapter — INVENTED format)

> Synthetic template. No real vendor or agency data. See `../../README.md`
> for the feature matrix and `adapters/README.md` for the rules real adapters
> follow.

**The invented story:** fixed-route buses carry "Acme RideLog" mobile data
terminals; operators key passenger boardings/alightings at each stop. The
back office exports one semicolon-delimited file per day with two banner
lines, a UTF-8 BOM, and single-quote quoting. Device clocks are agency-local
(America/Chicago).

## Source columns → contract fields

| RideLog column | Sample value | Maps to | How |
| --- | --- | --- | --- |
| `RecType` | `CNT` / `HB` / `LOG` | — (filter) | only `CNT` passenger-count records map; heartbeats and sign-ons are filtered with a reason |
| `Seq` | `00001` | `passenger_event_id` | `concat` UnitNo `:` Seq |
| `UnitNo` | `1207` | `vehicle_id` | string |
| `LocalTime` | `03/07/2026 08:15:00` | `event_timestamp` | `datetime` `%m/%d/%Y %H:%M:%S`, localized to America/Chicago, emitted UTC |
| — | — | `service_date` | `local_date_of` event_timestamp (the local wall date) |
| `Dir` | `B` / `A` | `event_type` | `enum_map`: B → `Passenger boarded`, A → `Passenger alighted` (TIDES enum members; anything else quarantines) |
| `Cnt` | `2` / empty | `event_count` | integer; empty = ABSENT (NULL downstream, never coalesced) |
| `StopSeq` | `1` | `trip_stop_sequence` | integer (TIDES minimum 1 enforced by contract validation) |

## Fixtures

- `ridelog_mixed_day.csv` — 11 reader rows: 2 mapped, 2 filtered, 7
  quarantined (bad integer, unmapped enum, DST-nonexistent time,
  DST-ambiguous time, missing vehicle_id, stop sequence 0, unterminated-quote
  absorption).
- `ridelog_empty_day.csv` — header-only delivery (surfaced as an info
  finding, never silent).
- `ridelog_wrong_export.csv` — a different Acme export dropped in the wrong
  directory: the header is missing the spec's source columns, so the WHOLE
  file is refused (`adapter_source_mismatch`, blocking) and nothing is mapped
  by guesswork.
