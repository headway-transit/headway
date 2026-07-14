# Acme ParaVan → `demand_response_trip` v0 (reference adapter — INVENTED format)

> Synthetic template. No real vendor or agency data. See `../../README.md`
> for the feature matrix and `adapters/README.md` for the rules real adapters
> follow.

**The invented story:** a paratransit operation books trips in "Acme ParaVan";
the dispatch workstation (a legacy Windows box, hence cp1252) exports one
pipe-delimited booking file per service day. Times are local wall clock
(America/Denver), day-first; distances are kilometers.

## Source columns → contract fields

| ParaVan column | Sample value | Maps to | How |
| --- | --- | --- | --- |
| `BookingRef` | `AC-1001` | `dr_trip_id` | string |
| `RunDate` | `2026-03-07` | `service_date` | date (ISO) |
| `Van` | `V-12` | `vehicle_id` | string |
| `SvcType` | `D` / `P` | `tos` | `enum_map`: D → DO, P → PT (anything else quarantines) |
| `Status` | `C` / `NS` / `X` | filter + `no_show` | X (cancelled) filtered with reason; `enum_map` C → false, NS → true |
| `PUTime`, `DOTime` | `07/03/2026 08:05` | `pickup_timestamp`, `dropoff_timestamp` | `datetime` `%d/%m/%Y %H:%M` (day-first), localized America/Denver, emitted UTC |
| `PULat`, `PULon` | `46.59`, `-112.03` | `pickup_lat`, `pickup_lon` | number |
| `TripKm` | `5.2` | `onboard_miles` | decimal + unit kilometers → statute miles (exact Decimal) |
| `OdoStartKm`, `OdoEndKm` | `120010.4` | `pickup/dropoff_odometer_miles` | decimal + km → miles |
| `Pax`, `Escorts` | `1`, `1` | `riders`, `attendants_companions` | integer (contract minimum 0; the export applies the non-employee rule at source) |
| `ADA` | `Y` / `N` | `ada_related` | boolean (true: Y/YES, false: N/NO) |
| `Spon` | `Y` / `N` | `sponsored` | boolean |
| `SponsorCode` | `MEDICAID` | `sponsor` | string; empty = absent (contract: required iff sponsored) |
| `Driver` | `José M` | `driver_shift_id` | string (cp1252 exercised) |
| — | — | `mode` | const `DR` |
| — | — | `distance_source` | const `odometer` |

## Fixture

`paravan_bookings.csv` — 11 rows: 3 mapped (a completed ADA trip, a proper
no-show with zero boardings, a sponsored trip), 1 filtered (cancelled), 7
quarantined: dropoff-before-pickup and sponsor-on-unsponsored and
no-show-with-boardings (normalizer cross-field contract rules), unmapped
`SvcType`, negative `Pax` (JSON-Schema `riders` minimum), non-decimal
`TripKm`, unparseable `ADA` flag.
