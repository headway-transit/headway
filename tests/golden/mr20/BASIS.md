# Basis for golden dataset `mr20`

**Basis statement:** synthetic hand-checked example — **NOT an FTA-certified
package; regression anchor only.** `expected.json` is the EXACT JSON package
`headway_calc.mr20.build_mr20_package` must emit over the canned
`computed.metric_values` rows in `fixture.json` for month `2026-06` (period
`[2026-06-01, 2026-07-01)`, half-open UTC). The MR-20 form structure is
verified (2025 NTD Monthly and Weekly Reference Policy Manual pp. 32–33,
quoted in `services/calc/REGULATORY_TRACKER.md`, "Verified — Monthly
Ridership form MR-20"); the row values are invented.

## Canned rows → package cells (hand-checked)

`fixture.json` carries the latest row per (metric, scope) as the generator's
SELECT would return them (the fake connection serves them verbatim):

| scope | upt | vrh | vrm | voms |
|---|---|---|---|---|
| `agency` (fleet) | 44632 | 5321.75 | 61234.88 | 412 |
| `mode:bus` | 30011 | 4102.50 | 45120.33 | 339 |
| `mode:subway` | 14621 | 1219.25 | 16114.55 | **ABSENT** |

Hand-checked package rules pinned by `expected.json`:

- **Cell provenance verbatim:** every present cell carries the row's value
  (as text), unit, metric_value_id, calc_name, calc_version,
  certification_status, and `coverage` from the detail JSONB (vrm/vrh only —
  upt evidences completeness via missing_share and voms via days_observed,
  so their `coverage` is null, never a guessed ratio).
- **Flags derived from row FACTS** (sorted): `pre_verification` (calc_version
  0.x — all cells), `uncertified` (certification_status ≠ 'certified' — all
  cells), `simulated_source_data` (detail.source_mix contains a non-'tides'
  source — the three upt cells, whose canned source_mix is all
  `tides_simulated`), `voms_day_level_proxy` (every voms cell) and
  `voms_partial_observation` (voms detail days_observed 28 < days_in_period
  30 — both voms cells).
- **Missing cell = explicit null + reason:** `mode:subway` has NO voms row →
  `{"value": null, "reason": ...}` naming metric, scope and period — never
  an invented number.
- **Rail pending D2:** `subway` is a rail-running mode per the transform's
  GTFS route_type→mode map (`headway_transform.gtfs_static`:
  route_types 0/1/2/5/7/12 → tram/subway/rail/cable_tram/funicular/monorail)
  → `non_reportable_pending_d2: true`; `bus` → false.
- **NOT-REPORTABLE header:** `reportable: false`, the fixed banner, and the
  programmatically enumerated caveats: one per flag present (flag-name
  order), the missing-cells caveat (a cell IS missing), then the fixed
  divergence list D1 (closed) – D6 verbatim.
- **Determinism:** modes sorted (`bus` before `subway`), flags sorted,
  caveat order fixed, `data_points` in the p. 32 form order
  (upt, vrh, vrm, voms).
