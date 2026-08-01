# vp_v0 golden — BASIS

Hand-worked basis for `tests/golden/vp_v0/{fixture,expected}.json`, the
regression anchor for the Vanpool (VP mode) calcs `vp_vrm_v0` / `vp_vrh_v0` /
`vp_upt_v0` / `vp_voms_v0` 0.1.0 (handoff 0042).

**Synthetic, NOT FTA-certified.** The FTA manuals contain no worked VP
VRM/VRH/UPT/VOMS example to derive numbers from — and, more to the point,
**every VP figure REFUSES in v0**, so there is no reportable number to
certify. What this golden pins is the *refusal contract*: value `null`, the
naming blocking finding, and the honestly-labelled observed-movement context.

## Why every figure refuses (the load-bearing point)

The input is `canonical.vehicle_telematics_days` (migration 0034) — **measured
vehicle movement**, subject to the honesty wall (`contracts/fleet-telematics.v0.md`):
telematics distance is NOT revenue miles, engine time is NOT revenue hours.
The FTA vanpool rules (2026 NTD Policy Manual, quoted verbatim in
`services/calc/REGULATORY_TRACKER.md` → "Verified — Vanpool (VP mode)
reporting") require inputs telematics cannot supply:

- **VRM / VRH** — VRM/VRH are "the ... miles/hours vehicles travel while in
  revenue service" and "exclude ... Other non-revenue uses" (p. 128). A
  vanpool van is defined by "80 percent of the yearly mileage comes from
  commuting" (p. 36) — its own definition admits up to 20% personal mileage.
  VP VRM/VRH is rider-self-reported (p. 131) and must be a 100% count with
  no estimation (p. 122). Telematics carries no revenue-service declaration,
  so a VP VRM/VRH from it would be an unallowed estimate substituting
  all-movement for revenue service. → `vp_vrm_needs_revenue_service_declaration`,
  `vp_vrh_needs_revenue_service_declaration`.
- **UPT** — UPT is "the number of boardings" (p. 143); VP additionally counts
  the driver as a passenger unless the driver is a paid employee (p. 143).
  Telematics counts no boardings and knows no rider identities. →
  `vp_upt_needs_passenger_roster`.
- **VOMS** — for DR and VP, "The largest number of vehicles in revenue
  service at any one time" (Exhibit 38, p. 138). Telematics knows a vehicle
  moved, not that it was in revenue service. → `vp_voms_needs_revenue_service_declaration`.

## The scenario

Two simulated vanpool vans on service date 2026-07-15 (Samsara-shaped
telematics; all rows `samsara_simulated`):

| record | vehicle | measure / basis | value | note |
| --- | --- | --- | --- | --- |
| rec-vp-01 | van-42 | distance / ecu_odometer | 72000 m | the van's own odometer delta |
| rec-vp-02 | van-42 | distance / gps_distance | 72900 m | gateway GPS distance — **disagrees with the ECU odometer by 900 m** |
| rec-vp-03 | van-42 | engine_time / ecu_engine_time | 43200 s | engine runtime (12 h) — includes idling |
| rec-vp-04 | van-77 | distance / ecu_odometer | *absent* | only ONE reading landed → **UNMEASURED**, never zeroed |

## Worked expectations (identical across all four figures except the naming)

- **value = null** — the figure refuses; a `CalcResult` with a blocking
  finding must have `value=None` (the library invariant).
- **input_record_ids = []** — nothing was consumed into a figure (there is
  none); the records are cited by the findings instead.
- **blocking finding** — one, naming the missing input (see the table above).
- **warnings**:
  - `vp_telematics_basis_conflict` — van-42's ecu_odometer (72000) and
    gps_distance (72900) disagree by 900 m, over the 100 m default tolerance
    (Shared Constraint 7: surfaced, never averaged). `basis_conflicts = 1`.
  - `vp_telematics_series_unmeasured` — van-77's odometer series has one
    reading, value absent. `vehicle_days_unmeasured = 1`.
- **info**: `simulated_source_data` — all four series are `samsara_simulated`;
  a certifiable figure over simulated data is a contradiction, recorded
  independently of the refusal.
- **context detail** (honestly labelled, never a reportable figure):
  - `observed_distance_meters = "144900"` = 72000 + 72900 (measured distance
    rows only; the absent van-77 series contributes nothing, is not 0).
  - `observed_engine_seconds = "43200"`.
  - `by_basis = {ecu_odometer: 72000, gps_distance: 72900, ecu_engine_time: 43200}`
    — every basis kept distinct.
  - `vehicle_days_seen = 4`, `reportable = false`, `source_mix = {samsara_simulated: 4}`.

If any of these change, the calc's refusal contract or its honest accounting
changed — mint a new calc version and a new tracker row (the "no version
without a tracker entry" rule), never edit this file to match new behavior.
