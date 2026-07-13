# Basis for golden dataset `dr_v0`

**Basis statement:** synthetic hand-worked examples — **NOT FTA-certified
figures; regression anchors only.** These expectations pin the five Demand
Response calcs at 0.1.0 (`dr_vrh_v0`, `dr_vrm_v0`, `dr_upt_v0`,
`dr_voms_v0`, `dr_pmt_v0` — handoff 0013). Every regulatory rule realized
here is one of the quotes in `services/calc/REGULATORY_TRACKER.md`,
*"Verified — Demand Response / on-demand reporting (verified 2026-07-12)"*
(2026 NTD Full Reporting Policy Manual pp. 33, 37–39, 129–139, 143–144);
the fixture data are invented and no figure here is reportable (all
dispatch-day trips carry `source = "dr_simulated"`).

Rules under test, quoted in the tracker:

- **p. 129 DR revenue time:** "revenue time includes all travel time from
  the point of the first passenger pick-up to the last passenger drop-off,
  as long as the vehicle does not return to the garage or dispatching point
  or have interruptions in service, such as lunch breaks or vehicle fueling
  and servicing."
- **p. 129 TX rule:** "agencies must report only the miles and hours when a
  transit passenger is onboard as revenue service."
- **Exhibit 36 (pp. 134–135)** verbatim classifications — every row is
  pinned as a table entry AND as a behavioral scenario below.
- **Exhibits 38 + 40 (pp. 138–139) DR VOMS:** "The largest number of
  vehicles in revenue service at any one time … (INCLUDES atypical
  service)"; Exhibit 40's Happy Transit scenario: six unique vehicles, max
  four simultaneous → VOMS = 4.
- **pp. 143–144 UPT:** non-employee attendants/companions count; ADA split
  in total, never sponsored; sponsored split in total.

## 1. `dispatch_day` — the hand-worked full dispatch day (2026-07-14)

### van-1 (DO): shared ride, no-show, lunch + fuel breaks

| Trip | Window (UTC) | Odometer | Onboard mi | Persons | Flags |
|---|---|---|---|---|---|
| A | 08:00–08:20 | 100.0→104.0 | 4.0 | 1 | ADA |
| B | 08:30–09:00 | 106.0→112.0 | 6.0 | 2+1 att | sponsored “Medicaid NEMT” |
| C | 08:40–08:55 | 108.0→111.0 | 3.0 | 1 | ADA; **shared** with B (overlapping window) |
| D | 09:10–09:15 | 114.0→114.0 | 0 | 0 | **no-show**; `interruption_after=lunch` |
| E | 10:00–10:30 | 116.0→121.0 | 5.0 | 2 | `interruption_after=fuel` |
| F | 10:45–11:00 | (none) | 3.0 | 1 | **ADA AND sponsored** “Meals-On-Wheels” (conflict); `interruption_after=dispatch_return` |

Spans (p. 129 rule — breaks at lunch/fuel; the `dispatch_return` marker on
F is the day's FINAL activity, so it breaks nothing — the return to
dispatch after the last dropoff is deadhead by construction, Exhibit 36
row 6):

1. **08:00 → 09:15** (A, B, C, D): first pickup A to last dropoff D —
   includes the shared ride's overlap once, the 08:20–08:30 empty travel
   (row 4: revenue yes/yes), and the travel to + wait at the no-show (rows
   7 + 3: revenue). Duration **75 min**. Miles by whole-span odometer:
   114.0 − 100.0 = **14.0** (= 4.0 A + 2.0 empty + 6.0 B-window ⊇ C + 2.0
   empty-to-no-show + 0 wait ✓). Lunch travel after (114.0→116.0, 2 mi;
   09:15→10:00) is neither revenue nor deadhead (p. 130) — excluded by the
   span break ✓.
2. **10:00 → 10:30** (E): 30 min; odometer 121.0 − 116.0 = **5.0**. Fuel
   gap (121→122, 10:30–10:45) excluded ✓.
3. **10:45 → 11:00** (F): 15 min; F has no odometer pair → onboard_sum
   fallback = onboard_miles **3.0** (no empty legs, nothing missing).

van-1: VRH = 75+30+15 = 120 min = **2.00 h**; VRM = 14+5+3 = **22.0 mi**.

### van-2 (DO): unmeasured distances

| Trip | Window | Distance data | Persons |
|---|---|---|---|
| G | 09:00–09:30 | **none** | 1 |
| H | 09:45–10:15 | onboard_miles 4.5 (gps) | 1 |

One span 09:00→10:15 = 75 min = **1.25 h**. Span odometer unavailable (G
has no pickup reading) → onboard_sum: G unmeasured (**contributes 0**,
`missing_onboard_distances = 1`), H 4.5; the 09:30→09:45 empty leg has no
odometer pair (`unmeasured_empty_legs = 1`, contributes 0). VRM = **4.5**
with one `dr_distance_unmeasured` warning citing rec-dr-07/08 (documented
UNDERCOUNT — Exhibit 36 prices the empty leg as revenue).

### van-3 (TX): onboard-only accounting

| Trip | Window | Odometer | Onboard mi | Persons |
|---|---|---|---|---|
| I | 09:00–09:30 | 50.0→56.0 | 6.0 | 1 |
| J | 09:10–09:40 | 52.0→58.0 | 6.0 | 1 (shared with I) |
| K | 10:00–10:20 | 62.0→66.0 | 4.0 | 2 |
| L | 10:30–10:35 | (none) | — | 0 (**TX no-show**) |

Merged onboard intervals (p. 129 TX rule): [09:00, 09:40] (I∪J — the
shared overlap counts ONCE) and [10:00, 10:20] (K). The 09:40–10:00 empty
travel and the no-show visit L contribute NOTHING (no passenger onboard).
VRH = 40+20 min = **1.00 h**. VRM by interval boundary odometers:
(58.0−50.0) + (66.0−62.0) = 8.0 + 4.0 = **12.0** (a naive per-booking sum
would double-count the I/J overlap: 6+6+4 = 16 ✗).

### Mode-level totals

- **dr_vrh = 2.00 + 1.25 + 1.00 = "4.25"** (255 min; quantized 0.01 h).
- **dr_vrm = 22.0 + 4.5 + 12.0 = "38.50"** (distance_sources:
  span_odometer 4 — van-1 spans 1–2, van-3 intervals 1–2; onboard_sum 2 —
  van-1 span 3, van-2).
- **dr_upt = "14"**: A 1 + B 3 + C 1 + E 2 + F 1 (van-1 = 8) + G 1 + H 1
  (van-2 = 2) + I 1 + J 1 + K 2 (van-3 = 4). Riders 13 + attendants 1.
  No-shows D and L: revenue time yes, **UPT ZERO** (the Exhibit 36
  asymmetry). ADA split = A+C+F = **3** (F counts as ADA despite its
  sponsored flag — "never sponsored"; one `dr_ada_sponsored_conflict`
  warning). Sponsored split = B = **3** ("Medicaid NEMT": 3).
- **dr_voms = "3"**: intervals van-1 [08:00–09:15], [10:00–10:30],
  [10:45–11:00]; van-2 [09:00–10:15]; van-3 [09:00–09:40], [10:00–10:20].
  At 09:00 three vehicles are in revenue service simultaneously (van-1
  span 1, van-2, van-3 interval 1) — the first instant attaining the
  maximum (`peak_start` 09:00). Unique vehicles 3. Lineage = the trips of
  the three covering intervals (rec-dr-01..04, 07, 08, 09, 10).
- **dr_pmt = "62.50"**: onboard distance × persons per completed booking —
  van-1: 4·1 + 6·3 + 3·1 + 5·2 + 3·1 = 38.0; van-2: G EXCLUDED (no
  measurable distance, one `dr_onboard_distance_missing` warning), H
  4.5·1; van-3: 6·1 + 6·1 + 4·2 = 20.0. Sources: odometer_pair 7
  (A,B,C,E,I,J,K), onboard_miles 2 (F,H).

### Per-TOS decomposition (input selection at vehicle-day granularity)

| Metric | DO (van-1 + van-2) | TX (van-3) | Sum = mode? |
|---|---|---|---|
| dr_vrh | 195 min = **"3.25"** | **"1.00"** | 4.25 ✓ |
| dr_vrm | **"26.50"** | **"12.00"** | 38.50 ✓ |
| dr_upt | **"10"** | **"4"** | 14 ✓ |
| dr_pmt | **"42.50"** | **"20.00"** | 62.50 ✓ |
| dr_voms | **"2"** (09:00: van-1 + van-2) | **"1"** | NOT additive (documented) |

## 2. `exhibit36_scenarios` — every Exhibit 36 row as a fixture

The classification table itself (8 rows) is pinned verbatim against
`headway_calc.dr.EXHIBIT_36`. Each row also has a behavioral scenario
realizing it through the span semantics (all `source = "dr"`, single
vehicle-day, DO):

| Row (tracker wording) | Scenario | Hand computation |
|---|---|---|
| idle at dispatching point → NOT actual, NOT revenue | one trip 10:00–10:30 (odo 0→5) | nothing before the pickup exists in revenue: VRH "0.50", VRM "5.00" |
| depart dispatch to pick up passenger → actual yes, revenue NO | same + dispatch_timestamp 09:40 | the 09:40–10:00 approach is NOT revenue: VRH stays "0.50" (not 0.83) |
| wait for passenger at pickup → actual + REVENUE hours (miles N/A) | a lone no-show: arrive 10:00, depart 10:06, odometer unchanged | VRH "0.10" (wait IS revenue time), VRM "0.00" (miles N/A), UPT "0" |
| travel between dropoff and next pickup with NO passengers onboard → yes/yes | trips 10:00–10:20 (odo 0→4) and 10:30–10:50 (odo 6→10) | span 10:00–10:50 = 50 min → VRH "0.83"; span odometer 0→10 → VRM "10.00" (the 2 empty miles INCLUDED) |
| lunch travel/eating → no/no | same two trips, `lunch` after the first, second at 11:00–11:20 | two spans, 20+20 min → VRH "0.67"; miles 4+4 → VRM "8.00" (the 2 lunch-travel miles EXCLUDED) |
| return to dispatch empty → actual yes, revenue NO | as lunch, marker `dispatch_return` | VRH "0.67", VRM "8.00" — the return leg excluded |
| no-show trip → actual + REVENUE (yes/yes) | trip 10:00–10:20 (odo 0→4), then no-show visit 10:30–10:35 (odo 6→6) | span extends to the no-show departure: 35 min → VRH "0.58"; span odometer 0→6 → VRM "6.00" (the 2 miles TO the no-show INCLUDED — yes/yes); **UPT "1"** (the no-show boards nobody) |
| fueling → no | as lunch, marker `fuel` | VRH "0.67", VRM "8.00" |

Quantization: one final 0.01 quantize (ROUND_HALF_EVEN) per figure — 50 min
= 0.8333… → "0.83"; 40 min = 0.6667… → "0.67"; 35 min = 0.5833… → "0.58".

## 3. `exhibit40_happy_transit` — the DR VOMS golden

Six unique vehicles (hv-1..hv-6), one revenue interval each, per the
scenario structure quoted in the tracker (six unique across the day, max
four simultaneous):

```
hv-1 06:00────10:00
hv-2   06:30────10:30
hv-3     07:00────11:00
hv-4         09:00────13:00     ← 09:00–10:00: hv-1..4 = 4 (peak)
hv-5                11:30───15:00
hv-6                     13:30───17:00
```

Maximum simultaneous = **4** (09:00, the first attaining instant), unique
vehicles 6 → `dr_voms = "4"`, exactly Exhibit 40's Happy Transit outcome.
Atypical-day inclusion is definitional (`includes_atypical_days` true —
the opposite of voms_v0's non-DR exclusion; do not reuse voms_v0 for DR).
Source is `"dr"`, so this case also pins the ABSENCE of the
simulated-source info finding on real-source data.
