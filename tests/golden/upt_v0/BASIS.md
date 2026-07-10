# Basis for golden dataset `upt_v0`

**Basis statement:** synthetic hand-worked example — **NOT an FTA-certified
figure; regression anchor only.** These expectations pin `upt_v0` 0.1.0
(handoff 0005). The regulatory definitions the calc implements ARE verified
(2026 NTD Policy Manual pp. 143/146/151, quoted in
`services/calc/REGULATORY_TRACKER.md`), but the fixture data are invented and
carry `source = "tides_simulated"` / `"tides"` labels solely to exercise the
calc's rules; no figure here is reportable.

Event vocabulary: the verified TIDES `event_type` enum values
`"Passenger boarded"` / `"Passenger alighted"`
(TIDES-transit/TIDES `spec/passenger_events.schema.json`, main branch,
verified 2026-07-10 — repo HEAD `7ddaa7ab`, schema file last changed
`d887d42c`).

Defaults exercised: `missing_trip_threshold = 0.02` (p. 146 — a REAL FTA
threshold), `imbalance_threshold = 0.10` (p. 151 validation example).

## Case 1 — `blocked_case`: missing share 1/3 > 2% → refused

Operated trips (the vehicle_positions proxy): `trip-1`, `trip-2`, `trip-3`.
Events exist for trip-1 and trip-2 only; **trip-3 has zero passenger events →
missing**. All 8 events carry `source = "tides_simulated"`.

| event | trip | seq | type | count | note |
|---|---|---|---|---|---|
| pe-a-01 | trip-1 | 1 | boarded | 5 | counted |
| pe-a-02 | trip-1 | 2 | boarded | 3 | counted |
| pe-a-03 | trip-1 | 2 | alighted | 2 | |
| pe-a-04 | trip-1 | 3 | alighted | 6 | |
| pe-a-05 | trip-2 | 1 | alighted | 4 | load −4 → negative-load defect |
| pe-a-06 | trip-2 | 2 | boarded | 10 | counted |
| pe-a-07 | trip-2 | 3 | boarded | NULL | `apc_null_count`, contributes 0 |
| pe-a-08 | (none) | 1 | boarded | 7 | unassigned → revenue proxy excludes |

**Base count (p. 143 — boardings with a trip assignment):**
`5 + 3 + 10 + 0(NULL) = 18`; the unassigned boarding of 7 is NOT counted
(trip assignment is the v0 revenue-service proxy, as in vrm/vrh).
`total_boardings_counted = 18`.

**Lineage:** the counted, non-NULL boarding events only →
`input_record_ids = [rec-e-01, rec-e-02, rec-e-06]` (rec-e-07 is cited by its
`apc_null_count` warning instead; rec-e-08 is outside the proxy).

**p. 151 validations, hand-worked:**

- trip-1: boardings 8, alightings 8 → |8−8| = 0 ≤ 0.10×8 = 0.8 → no
  imbalance. Load in stop order: +5 → +3 (8) → −2 (6) → −6 (0) — never
  negative.
- trip-2: boardings 10 (NULL → 0), alightings 4 → |10−4| = 6 > 0.10×10 = 1
  → **one `apc_count_imbalance` warning** citing rec-e-05..07. Load in stop
  order: −4 at seq 1 → **`apc_negative_load` warning** citing rec-e-05 (the
  record at which the load first drops below zero).

**Missing-trip rule (p. 146):** missing = 1 (trip-3), operated = 3 →
share = 1/3 = 0.3333 (reported quantized 0.0001). Exact comparison:
`1 > 0.02 × 3 = 0.06` → **above the FTA 2% threshold** → ONE blocking
`apc_missing_trips_above_fta_threshold`, `value = None`,
`factor_applied = null` ("agencies must have a qualified statistician approve
the factoring method" — a human workflow, never guessed).

**Simulated sources:** all 8 events are `tides_simulated` → one
`simulated_source_data` info citing all 8 records;
`source_mix = {"tides_simulated": 8}`.

Expected warnings, in the calc's deterministic order (null-counts, then
imbalances, then negative loads): `apc_null_count` (rec-e-07),
`apc_count_imbalance` (trip-2), `apc_negative_load` (trip-2).

## Case 2 — `factored_case`: missing share exactly 2% → deterministic factor-up

Operated trips: `trip-01` … `trip-50` (50 trips). Trips 01–49 each have one
boarding event (count 2, stop 1) and one alighting event (count 2, stop 2),
`source = "tides"`; **trip-50 has zero passenger events → missing**.

- Base count: `49 × 2 = 98` boardings. `total_boardings_counted = 98`.
- Every trip balanced (|2−2| = 0) with load 2 → 0: no p. 151 warnings.
- All sources `"tides"`: no info finding; `source_mix = {"tides": 98}`.
- Missing share: `1/50 = 0.02` exactly. Exact comparison:
  `1 > 0.02 × 50 = 1.00` is **false** → at (not above) the threshold →
  factor up per p. 146 ("2 percent or less of the total").
- **Factor:** `operated/(operated − missing) = 50/49 = 1.0204081632…`;
  reported in detail quantized 0.000001 ROUND_HALF_EVEN → `1.020408`.
- **Reported UPT** from the EXACT fraction (never the rounded factor):
  `98 × 50 / 49 = 4900 / 49 = 100` exactly → quantized to whole boardings
  (Decimal 1, ROUND_HALF_EVEN — documented engineering rounding; the manual
  prescribes no rounding rule) → **`100`**.
- Bounds check (property-tested in general): `100 ≥ 98 = counted` and
  `100 ≤ 98/0.98 = 100` — the factored figure sits exactly at the
  threshold-edge bound `counted × 1/(1 − 0.02)`.
- `input_record_ids`: the 49 boarding records `rec-b-01-1 … rec-b-49-1` in
  event-timestamp order.
