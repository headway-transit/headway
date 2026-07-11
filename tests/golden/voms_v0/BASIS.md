# Basis for golden dataset `voms_v0`

**Basis statement:** synthetic hand-worked example — **NOT an FTA-certified
figure; regression anchor only.** These expectations pin `voms_v0` 0.1.0
(handoff 0009). The regulatory definition the calc approximates IS verified
(2025 NTD Monthly and Weekly Reference Policy Manual p. 33, quoted in
`services/calc/REGULATORY_TRACKER.md`, calc voms_v0), but the fixture data
are invented and the calc is a documented day-level PROXY (divergences a/b/c
in the tracker row); no figure here is reportable.

Verified quote (p. 33): "VOMS is the number of revenue vehicles/passenger
cars operated to meet the maximum service requirement during the month of
service reported. VOMS excludes atypical days or one-time special events."

v0 semantics under test: per UTC service day (the UTC calendar date of the
position's event time — documented convention), the count of DISTINCT
vehicles with at least one in-trip position (trip assignment = the v0
revenue-service proxy); the figure is the maximum of those daily counts.
Blocking-free by design (an observation gap can only understate a maximum);
partial observation is a warning.

## Fixture layout — 3 service days, distinct-vehicle counts 2/3/2

| UTC day | In-trip vehicles (records) | Distinct count |
|---|---|---|
| 2026-07-01 | veh-1 (`rec-v1-00`, `rec-v1-01` — two positions, ONE vehicle), veh-2 (`rec-v2-00`) | **2** |
| 2026-07-02 | veh-1 (`rec-v3-00`), veh-2 (`rec-v4-00`), veh-3 (`rec-v5-00`) | **3** |
| 2026-07-03 | veh-2 (`rec-v6-00`), veh-3 (`rec-v7-00`) | **2** |

Also on 2026-07-01: one UNASSIGNED position (`rec-vx-00`, veh-9,
`trip_id = null`) — outside the revenue-service proxy, so veh-9 never counts
(day 1 stays 2, not 3).

## Hand computation

- Daily counts: 2, 3, 2 → **maximum = 3** → `value = "3"` (integer Decimal,
  unit `vehicles`).
- `peak_day = 2026-07-02` (the single maximum; the calc's tie-break — the
  EARLIEST day attaining the maximum — is exercised by unit tests, not this
  fixture).
- `per_day_counts`: min = 2, max = 3, mean = (2+3+2)/3 = 7/3 = 2.3333… →
  quantized 0.0001 ROUND_HALF_EVEN = **"2.3333"** (string — the
  Decimal-as-text convention).
- **Lineage** = the PEAK day's in-trip records only, in (time, vehicle_id,
  source_record_id) order: `rec-v3-00, rec-v4-00, rec-v5-00` (all at
  09:00:00 → vehicle_id order). Day-1/day-3 records and the unassigned
  `rec-vx-00` never appear in lineage.

### Case 1 — exact period `[2026-07-01, 2026-07-04)`

`days_in_period = 3 = days_observed = 3` → **no warning**; the figure stands
with full observation.

### Case 2 — partial period `[2026-07-01, 2026-07-08)`

Same positions, wider period: `days_in_period = 7 > days_observed = 3` →
**one warning `voms_partial_observation`** (empty `source_record_ids` — an
unobserved day has no records to cite; the counts are named in the
description). Value, peak day, per-day summary and lineage are UNCHANGED
(the observed maximum stands; missing days can only mean the true maximum is
at least 3 — an undercount risk, never an overstated figure, which is why
voms_v0 has no blocking coverage machinery).
