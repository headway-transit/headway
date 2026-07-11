# Basis for golden dataset `mode_scope`

**Basis statement:** synthetic hand-worked example — **NOT an FTA-certified
figure; regression anchor only.** These expectations pin the handoff-0009
mode dimension: the per-mode compute paths (`compute_vrm_by_mode`,
`compute_vrh_by_mode`, `compute_upt_by_mode`, `compute_voms_by_mode`) run
the UNCHANGED calc versions (vrm_v0 0.2.0, vrh_v0 0.4.0, upt_v0 0.1.0,
voms_v0 0.1.0) over per-mode input subsets — input selection, not a
semantics change (`services/calc/REGULATORY_TRACKER.md`, "Mode scoping").

## Fixture layout

Period `[2026-01-01, 2026-02-01)`; all activity on 2026-01-15. Geometry
reuses the `vrm_vrh_v0` BASIS.md hand-worked legs (sphere R = 3958.7613 mi;
one 0.01° meridian/equatorial leg = 0.69093419 mi).

| Bucket | Rows |
|---|---|
| `bus` | veh-101 / trip-A, `mode: "bus"`: 10 positions (`rec-a-00..09`), 60 s spacing, lat 40.00→40.09 on the −75.0 meridian; 1 boarding event count 5 (`rec-e-bus-1`, source `tides`) |
| `subway` | veh-202 / trip-B, `mode: "subway"`: 10 positions (`rec-b-00..09`), 120 s spacing, lon −75.00→−74.91 on the equator; 1 boarding event count 7 (`rec-e-sub-1`, source `tides`) |
| `unknown` | 2 UNASSIGNED positions (`rec-x-00/01`, trip NULL → mode NULL) and 1 unassigned boarding event count 4 (`rec-e-x-1`) — the NULL-mode bucket: counted and computed, never dropped, never guessed |

No `block_id` anywhere: vrh_v0 0.4.0 falls back per trip (one
`block_unavailable` info per vehicle-day — 2 on the fleet run, 1 each on the
bus/subway runs; none in the unknown bucket, which has no in-trip
positions).

## Hand computation

**VRM (vrm_v0 0.2.0).** Per the vrm_vrh_v0 BASIS: trip-A = 9 × 0.69093419 =
6.21840771 → **6.22**; trip-B (identical geometry on the equator) → **6.22**;
unknown bucket has zero in-trip groups → **0.00**. Fleet = 18 legs =
12.43681542 → **12.44**. Additivity check: 6.22 + 6.22 + 0.00 = **12.44** =
fleet — EXACT on this fixture (each subset's unquantized sum quantizes
without drift; post-quantization additivity is not an algebraic identity in
general, which the property tests bound explicitly).

**VRH (vrh_v0 0.4.0, per-trip fallback).** trip-A: 9 × 60 s = 540 s =
**0.15 h**; trip-B: 9 × 120 s = 1080 s = **0.30 h**; unknown: **0.00**.
Fleet = 1620 s = **0.45** = 0.15 + 0.30 + 0.00 — exact (whole-hundredth
values).

**UPT (upt_v0 0.1.0).** Operated trips derive from the SAME positions
(distinct in-trip trip_ids): fleet {trip-A, trip-B}; per mode: bus
{trip-A}, subway {trip-B}, unknown {} (unassigned positions carry no
trip). No missing trips anywhere → factor 1 everywhere. Counted boardings:
bus 5, subway 7; the unassigned event (count 4) is outside the
revenue-service proxy and counts NOWHERE — the unknown bucket's UPT is the
degenerate **0** (0 operated, 0 counted). Fleet = 5 + 7 = **12** =
5 + 7 + 0 — exact (integers, factor 1).

**VOMS (voms_v0 0.1.0).** One observed day (2026-01-15): fleet distinct
in-trip vehicles {veh-101, veh-202} → **2**; bus {veh-101} → **1**; subway
{veh-202} → **1**; unknown: no in-trip positions → **0** (days_observed 0).
NOTE: VOMS is NOT additive across modes — max ≠ sum in general (bounded by
max(per-mode) ≤ fleet ≤ Σ per-mode, property-tested); the coincidental
equality here (2 = 1 + 1 + 0, single day, disjoint vehicles) is NOT an
invariant. Every voms result over this period carries the
`voms_partial_observation` warning (1 observed day of 31).

**Unknown-mode share (the ONE per-run info finding).** Positions: 2 of 22
carry NULL mode (`rec-x-00/01`); events: 1 of 3 (`rec-e-x-1`) — pinned in
`expected.json` under `unknown_mode`.
