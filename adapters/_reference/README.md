# `_reference/` — the synthetic reference adapter ("Acme Transit Suite")

**Everything here is invented.** There is no Acme Transit Suite vendor and no
real agency data in these fixtures. This directory exists for two reasons:

1. it is the validation harness's own test bed — `adapters/validate` (and CI)
   prove the framework against fixtures that exercise EVERY mapping-spec
   feature and every quarantine path;
2. it is the community's template — copy one of the two products and replace
   the invented format with your agency's real export (see
   `adapters/README.md`, including the binding trade-secret rules).

Because the fixtures are synthetic, both specs declare
`provenance.verified_against.synthetic: true`, which REQUIRES their source
labels to end in `_simulated` (`acme_ridelog_simulated`,
`acme_paravan_simulated`) so synthetic rows are permanently distinguishable in
provenance. Real adapters use the `sample:` provenance block and plain
`<vendor>_<product>` labels.

## Feature coverage matrix

| Mapping-spec feature | Exercised by |
| --- | --- |
| CSV dialect: delimiter / quotechar | ridelog (`;` + `'`), paravan (`\|` + `"`) |
| Encoding declaration | ridelog (`utf-8-sig`, fixture carries a real BOM), paravan (`cp1252`, fixture carries 0xE9 "José") |
| Banner lines (`skip_leading_rows`) | ridelog (2 banner lines) |
| Filters: `equals` / `in` + required reasons | ridelog (RecType equals CNT), paravan (Status in C, NS) |
| Coercions: `string` | ridelog vehicle_id, paravan dr_trip_id |
| `integer` (+ failure quarantine) | ridelog Cnt/StopSeq ("twelve" quarantines) |
| `decimal` (+ failure quarantine) | paravan TripKm/odometers ("abc" quarantines) |
| `number` (float contract fields) | paravan PULat/PULon |
| `boolean` via true/false value lists (+ failure) | paravan ADA/Spon ("MAYBE" quarantines) |
| `date` (default ISO format) | paravan RunDate |
| `datetime` + declared timezone | ridelog (America/Chicago), paravan (America/Denver, day-first format) |
| DST nonexistent wall time quarantined | ridelog fixture row at 2026-03-08 02:30 (spring-forward gap) |
| DST ambiguous wall time quarantined | ridelog fixture row at 2026-11-01 01:30 (fall-back repeat) |
| `enum_map` to strings (+ unmapped quarantine) | ridelog Dir B/A → TIDES event types ("X" quarantines); paravan SvcType D/P → DO/PT ("T" quarantines) |
| `enum_map` to booleans | paravan Status C/NS → no_show false/true |
| Constants | paravan `mode: DR`, `distance_source: odometer` |
| Derived: `concat` | ridelog passenger_event_id = UnitNo:Seq |
| Derived: `local_date_of` | ridelog service_date from event_timestamp |
| Unit conversion (km → statute miles, exact Decimal) | paravan onboard_miles + odometer pair |
| Absent optional stays NULL (never coalesced) | ridelog empty Cnt → event_count NULL |
| Contract validation: JSON Schema (DR) | paravan Pax −1 (riders minimum 0) |
| Contract validation: normalizer cross-field rules | paravan dropoff-before-pickup, no-show-with-boardings, sponsor-on-unsponsored; ridelog missing vehicle_id, trip_stop_sequence 0 |
| row_guard structural quarantine | ridelog unterminated-quote row absorbing the following line |
| Empty file surfaced (not silent) | ridelog_empty_day.csv |
| Header/spec mismatch refuses whole file | ridelog_wrong_export.csv (`file_refused: true`) |

One feature is exercised in unit tests rather than fixtures: `datetime` with an
explicit `%z` offset (`services/transform/tests/test_adapters.py`).

## Products

- `acme/ridelog/` — "RideLog" fixed-route MDT passenger-count export →
  **TIDES `passenger_events`**.
- `acme/paravan/` — "ParaVan" paratransit booking export →
  **`demand_response_trip` v0**.
