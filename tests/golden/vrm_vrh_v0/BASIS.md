# Basis for golden dataset `vrm_vrh_v0`

**Basis statement:** synthetic hand-worked example, values computed by hand
from the haversine formula — **NOT an FTA-certified figure; regression anchor
only.** These expectations pin the behavior of `vrm_v0` 0.1.0 and `vrh_v0`
0.1.0 (pre-verification walking-skeleton approximations, see
`services/calc/REGULATORY_TRACKER.md`). When the calculations are verified
against the current published FTA NTD Reporting Manual, new calc versions get
new golden datasets built from certified inputs; this one stays as the v0
regression anchor.

## Fixture layout

Earth model (from `headway_calc.distance`): sphere, `R = 3958.7613` statute
miles (mean radius 6371.0088 km / 1.609344). Gap threshold: 300 s (default).

| Group | Positions | Spacing | Geometry |
|---|---|---|---|
| `veh-101` / `trip-A` | 10 (`rec-a-00`..`rec-a-09`) | 60 s | lon fixed −75.0; lat 40.00 → 40.09 in +0.01° steps (9 meridian legs) |
| `veh-202` / `trip-B` | 10 (`rec-b-00`..`rec-b-09`) | 120 s | lat fixed 0.0 (equator); lon −75.00 → −74.91 in +0.01° steps (9 equatorial legs) |
| `veh-202` / `trip-C` | 4 (`rec-c-00`..`rec-c-03`) | 60 s, **400 s**, 60 s | contains a 400 s gap between `rec-c-01` (13:01:00) and `rec-c-02` (13:07:40) |
| unassigned | 2 (`rec-x-00`, `rec-x-01`) | — | `trip_id = null` → excluded by the v0 revenue-service proxy |

## Hand computation — VRM (clean subset: trip-A + trip-B)

Haversine: `a = sin²(Δφ/2) + cos φ₁ · cos φ₂ · sin²(Δλ/2)`,
`c = 2·atan2(√a, √(1−a))`, `d = R·c`.

**Trip-A legs (pure meridian, Δλ = 0):** `a = sin²(Δφ/2)`, so `c = Δφ` exactly.

- `Δφ = 0.01° = 0.01 × π/180 rad = 1.7453292519943296 × 10⁻⁴ rad`
- `d = R·Δφ = 3958.7613 × 1.7453292519943296 × 10⁻⁴ = 0.69093419 mi` per leg
  (the small-angle sine error is `≈ x³/6 ≈ 1.1 × 10⁻¹³ rad`, far below the
  0.01-mile quantum)
- 9 legs: `9 × 0.69093419 = 6.21840771 mi` → quantized **6.22 mi**

**Trip-B legs (equator, φ₁ = φ₂ = 0):** `a = sin²(Δλ/2)`, so `c = Δλ` — the
identical geometry rotated onto the equator:

- `d = R·Δλ = 0.69093419 mi` per leg; 9 legs → **6.22 mi**

**Clean VRM total:** `18 × 0.69093419 = 12.43681542 mi` → quantize to 0.01 mi
(ROUND_HALF_EVEN) = **`12.44` miles**. (Float check: the implementation sums
IEEE-754 doubles to `12.436815417396051`, agreeing to ~10⁻⁹ mi; both quantize
to 12.44.) Per-group values quantized independently: **`6.22`** each.

## Hand computation — VRH (clean subset)

- Trip-A: 9 deltas × 60 s = 540 s = 540/3600 h = **0.15 h**
- Trip-B: 9 deltas × 120 s = 1080 s = 1080/3600 h = **0.30 h**
- Clean VRH total: 1620 s / 3600 = 0.45 → quantized **`0.45` hours**

## Gap group — expected refusal

Trip-C spacing: 13:00:00 → 13:01:00 (60 s), 13:01:00 → 13:07:40 (**400 s >
300 s threshold**), 13:07:40 → 13:08:40 (60 s). Expected on the full fixture,
for both `vrm_v0` and `vrh_v0`:

- `value = None` (never a partial or interpolated number),
- exactly one `BlockingIssue` with `issue_type = "telemetry_gap"` and
  `source_record_ids = ("rec-c-01", "rec-c-02")` (the bounding records).

The two unassigned positions (`rec-x-00`, `rec-x-01`) must never appear in
`input_record_ids` and must not contribute distance or time.

## Calc 0.2.0 — gap policy: per-group exclusion + coverage (`expected_v0_2.json`)

Same fixture, `vrm_v0`/`vrh_v0` **CALC_VERSION 0.2.0** (handoff 0002): a group
containing a gap > 300 s is **excluded** from the figure (one
`telemetry_gap_excluded` **warning** finding citing all of the group's
records) instead of refusing the whole run; the run refuses only when
coverage falls below the explicit `coverage_threshold` input (default 0.95 —
an engineering placeholder, **not an FTA number**).

Hand-worked coverage over the full fixture (in-trip groups only; the
unassigned `rec-x-*` positions are outside the revenue-service proxy and
count toward neither ratio):

- groups: trip-A (clean), trip-B (clean), trip-C (**gapped → excluded**)
  → `total_groups = 3`, `excluded_groups = 1`, `clean_groups = 2`
- `coverage = 2/3 = 0.6666…` → quantized to 0.0001 (ROUND_HALF_EVEN, a
  documented engineering convention) = **`0.6667`**
- `clean_position_share = (10 + 10) / (10 + 10 + 4) = 20/24 = 0.8333…` →
  **`0.8333`**

The threshold comparison itself is exact (integer cross-multiplication,
`clean < threshold × total`), never the quantized ratio.

### Case A — default `coverage_threshold = 0.95`: blocked

`2 < 0.95 × 3 = 2.85` → coverage below threshold. Expected for both calcs:

- `value = None`, **nothing persisted**;
- exactly one **blocking** finding, `issue_type = "coverage_below_threshold"`,
  citing the excluded records `rec-c-00..rec-c-03`;
- one **warning** finding, `issue_type = "telemetry_gap_excluded"`, citing
  `rec-c-00..rec-c-03` (the whole excluded group, not just the gap bounds);
- `detail = {coverage: "0.6667", total_groups: 3, excluded_groups: 1,
  clean_position_share: "0.8333", gap_threshold_seconds: 300.0,
  coverage_threshold: "0.95"}`;
- `input_record_ids` = included groups only (`rec-a-*`, `rec-b-*`) — excluded
  records are cited by the warning, never by lineage.

### Case B — explicit `coverage_threshold = 0.5`: persists clean-group values

`2 ≥ 0.5 × 3 = 1.5` → coverage passes. The figure is the sum over the
included groups — exactly the clean-subset values hand-worked above:

- **VRM `12.44` miles**, **VRH `0.45` hours** (`calc_version = "0.2.0"`);
- one `telemetry_gap_excluded` **warning** (citing `rec-c-00..rec-c-03`), no
  blocking finding;
- same `detail` as Case A except `coverage_threshold: "0.5"`;
- `input_record_ids` = `rec-a-00..09`, `rec-b-00..09` only.

The 0.1.0 expectations above are untouched: they pin the retained
`compute_vrm_v0_1`/`compute_vrh_v0_1` functions (all-or-nothing gap refusal)
so historical submissions recompute bit-for-bit.
