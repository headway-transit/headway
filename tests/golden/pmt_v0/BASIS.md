# Basis for golden dataset `pmt_v0`

**Basis statement:** the four calc cases are synthetic hand-worked examples —
**NOT FTA-certified figures; regression anchors only.** They pin `pmt_v0`
0.1.0 (handoff 0011). The regulatory definitions the calc implements ARE
verified (2026 NTD Policy Manual, Full Reporting, pp. 143–155, quoted in
`services/calc/REGULATORY_TRACKER.md`, "Verified — Passenger Miles
Traveled"), but the fixture data are invented and carry `source = "tides"` /
`"tides_simulated"` labels solely to exercise the calc's rules; no calc-case
figure here is reportable. The `exhibit_44` block is different in kind: its
numbers are the manual's own worked example, VERBATIM (p. 154–155, Exhibit
44) — the one golden whose expected values come from the published source
itself.

Defaults exercised: `missing_trip_threshold = 0.02` (p. 146 — a REAL FTA
threshold), `imbalance_threshold = 0.10` (p. 151 validation example).
Distance quantum: 0.01 mile, ROUND_HALF_EVEN (the vrm_v0 engineering
convention, `headway_calc.distance`).

## Case 1 — `shape_case`: multi-stop load profiles over shape_dist deltas

`shape_dist_unit_miles = 1` (fixture units are miles). The stop COORDINATES
in this case are deliberately absurd (whole degrees apart, ≈ 69-mile legs):
if haversine were ever preferred over present shape deltas, the value would
explode and the golden fails loudly — pinning the distance-source precedence.

**trip-A** — stops seq 1..4, `shape_dist_traveled` = 0.0, 1.0, 2.5, 4.0 mi
(segment lengths 1.0, 1.5, 1.5):

| seq | boarded | alighted | load AFTER stop | next segment | passenger-miles |
|---|---|---|---|---|---|
| 1 | 5 | — | 5 | 1.0 mi | 5 × 1.0 = 5.0 |
| 2 | 3 | 2 | 6 | 1.5 mi | 6 × 1.5 = 9.0 |
| 3 | — | 3 | 3 | 1.5 mi | 3 × 1.5 = 4.5 |
| 4 | — | 3 | 0 | — | — |

Boardings 8 = alightings 8 (balanced); load never negative. Trip PMT =
5.0 + 9.0 + 4.5 = **18.5**.

**trip-B** — stops seq 1..3, sdt 0.0, 2.0, 3.0 (segments 2.0, 1.0):
board 4 at s1 (load 4 × 2.0 = 8.0), alight 1 at s2 (load 3 × 1.0 = 3.0),
alight 3 at s3. Balanced 4 = 4. Trip PMT = **11.0**.

Fleet: counted = 18.5 + 11.0 = **29.50**. Operated = {trip-A, trip-B}, both
with valid events → missing 0, invalid 0, share 0.0000, factor 1.000000 →
**value 29.50**. 5 shape segments, 0 haversine (no fallback info). All
`"tides"` → no simulated finding. Lineage: all 8 event records (both
boardings AND alightings feed a load profile), trip-A's then trip-B's in
event order.

## Case 2 — `haversine_case`: NULL shape_dist → flagged haversine fallback

MBTA-shaped geometry: `shape_dist_traveled` NULL everywhere, no unit given.
Stops sit on ONE meridian (longitude −71.00), latitudes 42.00 / 42.01 /
42.03, so each haversine leg reduces analytically to arc length = R × Δφ
(with Δλ = 0 the haversine `c` equals Δφ exactly):

- leg 1 (0.01°): 3958.7613 mi × 0.01° × π/180 = 3958.7613 × 0.000174532925…
  = **0.6909394 mi** (7 s.f.)
- leg 2 (0.02°): 2 × leg 1 = **1.3818788 mi**

Events: board 2 at s1 → load 2 over leg 1; board 1 + alight 1 at s2 (net 0)
→ load 2 over leg 2; alight 2 at s3. Balanced 3 = 3.

PMT = 2 × leg1 + 2 × leg2 = 6 × leg1 = 6 × 0.6909394 = 4.1456366 →
quantized **4.15**. Factor 1 (nothing missing/invalid) → **value 4.15**.

Findings: all four events are `tides_simulated` → ONE `simulated_source_data`
info citing all 4 records; 2 of 2 counted segments haversine-priced → ONE
`haversine_distance_fallback` info (the handoff-0011 documented divergence —
straight-line understates path distance — flagged on every figure it
touches). `distance_source_segments = {haversine: 2, shape_dist_traveled: 0}`.

## Case 3 — `blocked_case`: missing + invalid trips breach the 2% rule

Operated = {trip-E, trip-F, trip-G, trip-H} (all with 2-stop geometry,
sdt 0 → 1.0 mi, unit 1).

- **trip-E** valid: board 3 at s1, alight 3 at s2 → 3 passengers × 1.0 mi =
  3.0 passenger miles.
- **trip-F** invalid — `negative_load` (p. 151 "trips where the passenger
  load drops below zero"): alight 4 at s1 (running load −4) before board 4
  at s2. Balanced (4 = 4), so the imbalance check does NOT fire — the
  negative load alone invalidates.
- **trip-G** missing: zero passenger events.
- **trip-H** invalid — `count_imbalance` (p. 151 "difference between
  boardings and alightings is greater than 10 percent"): board 10, alight 5;
  |10 − 5| = 5 > 0.10 × 10 = 1. Running load never negative (10 → 5).
- **trip-I** (NOT operated) invalid — two defects, pinning the documented
  reason PRIORITY: a NULL `event_count` (`null_event_count`) AND a NULL
  `trip_stop_sequence` (`unplaceable_event`); the FIRST reason in priority
  order is `null_event_count` (the warning title carries it; the description
  names both).
- **trip-J** (NOT operated) invalid — `geometry_unavailable`: events fine,
  but no canonical.stop_times rows exist for the trip.

Missing-data share (p. 146; invalid trips count per the pp. 151–152 discard
discipline): missing 1 (G) + invalid∩operated 2 (F, H) = 3 of 4 operated =
0.75. Exact comparison 3 > 0.02 × 4 → **REFUSED**: ONE blocking
`apc_missing_trips_above_fta_threshold` (the statistician-approval quote),
`value = null`, `factor_applied = null`. Trips I and J warn but do NOT count
against the share (not operated) — `invalid_trips = 4` while the share is
3/4.

Evidence still travels: counted = **3.00** (trip-E), lineage = trip-E's two
records only; each invalid trip's records are cited by its own
`pmt_invalid_trip_excluded` warning (warnings in sorted trip order: F, H, I,
J).

## Case 4 — `factored_case`: share exactly 2% → deterministic factor-up

50 operated trips; trips 01–49 each carry one boarding (2) at s1 and one
alighting (2) at s2 over a 1.0-mile shape segment → 2.0 passenger miles per
trip; **trip-50 has zero passenger events → missing**.

- Counted: 49 × 2.0 = **98.00**.
- Missing share 1/50 = 0.02 exactly; exact comparison
  `1 > 0.02 × 50 = 1.00` is **false** → at (not above) the threshold →
  factor up per p. 146 ("2 percent or less of the total").
- Factor: 50/49 = 1.0204081632… → reported quantized 0.000001 → `1.020408`.
- **Value** from the EXACT fraction (never the rounded factor):
  98.00 × 50/49 = 4900/49 = 100 exactly → **100.00** (0.01-mile quantum).
- 49 shape segments; all sources `"tides"` → no info findings.

## `exhibit_44` — the manual's own worked example, VERBATIM (pp. 154–155)

Method (p. 154): "estimate PMT data in a non-sampling year by multiplying
the average trip length from the most recent mandatory year by the UPT for
the current year." These are the published numbers, not synthetic ones:

- **Annual:** mandatory year PMT 60,000,000 / UPT 12,750,000 → average trip
  length **4.71** (two decimals, as printed); current-year UPT 13,400,000 →
  estimated PMT 4.71 × 13,400,000 = **63,114,000**.
- **Per schedule type** (given ATLs × current-year UPT):
  Weekday 5.0 × 10,500,000 = **52,500,000**; Saturday 3.5 × 2,100,000 =
  **7,350,000**; Sunday 4.0 × 800,000 = **3,200,000**.

The estimator is a SEPARATE pure function with its own provenance label
(`headway_calc.pmt.ESTIMATION_METHOD`) — an estimate by the Exhibit 44
method, never conflated with computed PMT.
