# ops_v0 golden basis — hand-worked expectations

SYNTHETIC OPERATIONS data (handoff 0014). Nothing here is an FTA figure or
a TCQSM-certified example; this is a regression anchor whose every number
is worked by hand below. Definitions under test:
`services/calc/OPS_DEFINITIONS.md` (derive_stop_passages 0.1.0, otp_v0
0.1.0, headway_adherence_v0 0.1.0).

## World

Agency timezone `America/New_York`; service date **2026-07-09** (EDT,
UTC−4). GTFS schedule anchor "noon minus 12 h" = 2026-07-09T00:00−04:00 =
**2026-07-09T04:00:00Z**, so schedule second *s* maps to UTC instant
`04:00:00Z + s`.

Route R1 direction 0, stops on a north–south line at longitude −71.06:

| stop | latitude | note |
|---|---|---|
| S1 | 42.35 | |
| S2 | 42.36 | 0.01° lat ≈ 1113 m north of S1 |
| S3 | 42.37 | |
| S4-nocoords | NULL | scheduled but no coordinates — must be counted, never guessed |

Schedule (seconds after anchor; arrival = departure):

| trip | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| T1 | 28800 (12:00:00Z) | 29400 (12:10:00Z) | 30000 (12:20:00Z) | 30300 |
| T2 | 29700 (12:15:00Z) | 30300 (12:25:00Z) | 30900 (12:35:00Z) | — |

Scheduled headway T1→T2 at every stop: **900 s**.

## Case `clean_two_trips` — derivation

Each trip has three 3-position clusters (60 s apart) centered on a stop;
cluster edges sit 0.0018° ≈ 200 m from the stop, outside the 100 m radius,
so exactly the central position is the closest approach, its index is
never an endpoint, and both bounding gaps are 60 s ≤ 120 s. Extras:

- `rec-t1-03b-duplicate-timestamp` repeats 12:01:00 for bus-1/T1 → the
  re-polled report is collapsed: `positions_deduplicated = 1` (the first
  row by (time, source_record_id) order, rec-t1-03, is kept).
- `rec-unassigned` has trip_id NULL → not considered (19 considered of 20).
- S4-nocoords is scheduled for T1 → `stops_missing_coordinates = 1`;
  `stops_considered = 4 (T1) + 3 (T2) = 7`; `passages_derived = 6`.

Passages (closest-approach position per stop):

| trip | stop | observed (UTC) | record |
|---|---|---|---|
| T1 | S1 | 12:00:00 | rec-t1-02 |
| T1 | S2 | 12:12:00 | rec-t1-05 |
| T1 | S3 | 12:28:00 | rec-t1-08 |
| T2 | S1 | 12:14:00 | rec-t2-02 |
| T2 | S2 | 12:31:00 | rec-t2-05 |
| T2 | S3 | 12:50:00 | rec-t2-08 |

## otp_v0 — window −60 s … +300 s (the TCQSM-cited defaults)

Deviation = observed − scheduled:

| passage | scheduled | observed | deviation | class |
|---|---|---|---|---|
| T1/S1 | 12:00:00 | 12:00:00 | 0 | on time |
| T1/S2 | 12:10:00 | 12:12:00 | +120 | on time |
| T1/S3 | 12:20:00 | 12:28:00 | +480 | late |
| T2/S1 | 12:15:00 | 12:14:00 | −60 | on time (boundary: −60 ≥ −60) |
| T2/S2 | 12:25:00 | 12:31:00 | +360 | late |
| T2/S3 | 12:35:00 | 12:50:00 | +900 | late |

OTP = 3/6 = **50.00 %**. Mean deviation = (0+120+480−60+360+900)/6 =
1800/6 = **300.00 s**. Median = mean of the 3rd and 4th of
(−60, 0, 120, 360, 480, 900) = (120+360)/2 = **240.00 s**.
`input_record_ids` = the six passage records, sorted.

## headway_adherence_v0 — cvh

Pairs at each (R1, 0, stop), scheduled headway h = 900 s:

| stop | observed headway | deviation d = obs − 900 |
|---|---|---|
| S1 | 12:14:00 − 12:00:00 = 840 | −60 |
| S2 | 12:31:00 − 12:12:00 = 1140 | +240 |
| S3 | 12:50:00 − 12:28:00 = 1320 | +420 |

mean(d) = 200; population variance = ((−260)² + 40² + 220²)/3 =
(67600 + 1600 + 48400)/3 = 117600/3 = 39200; population stddev =
√39200 = 140√2 = 197.9898987… → **197.99** (quantized 0.01).
mean scheduled headway = **900.00**.
cvh = 197.9898987…/900 = 0.219988776… → **0.2200** (quantized 0.0001).

## Case `refusals` — every refusal reason exercised, passages = 0

T1 only, four positions: 12:00:00 AT S1 (index 0), 12:01:00 at 42.3518,
12:12:00 AT S2, 12:13:00 at 42.3618. Refusal precedence is
radius → endpoint → cadence (documented in headway_calc.passages):

- S1: closest approach is index 0 → `refused_endpoint_unbounded = 1`
  (the true pass may precede the observation window);
- S2: closest approach index 2, gap before = 12:12−12:01 = 660 s > 120 s →
  `refused_cadence_gap = 1`;
- S3: closest position is 42.3618, 0.0082° ≈ 913 m away > 100 m →
  `refused_not_reached = 1` (checked before the endpoint rule);
- S4-nocoords → `stops_missing_coordinates = 1`.

Zero passages → otp_v0 refuses with blocking `no_observed_passages` and
headway_adherence_v0 with blocking `no_headway_pairs`; nothing may be
persisted (CalcResult invariant + persist refusal + migration-0024
category never reached).
