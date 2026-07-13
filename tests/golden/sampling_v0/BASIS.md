# Golden basis — sampling_v0 0.1.0 (handoff 0012)

Hand-worked expectations for the three sampling_v0 facilities. Source of
every regulatory number: **FTA NTD Sampling Manual, March 31, 2009**
(`docs/reference/The_NTD_Sampling_Manual.pdf`), quoted verbatim in
`REGULATORY_TRACKER.md` ("Verified — NTD Sampling Manual" and "Sampling plan
tables — implementation quotes (sampling_v0)"). The worked APTL example is
synthetic (hand-worked here, NOT an FTA-certified figure); the sample-size
cells are the manual's own numbers, pinned one-for-one.

## 1. Sample-size cells (Tables 43.01 / 43.03 / 43.05 / 43.07)

`expected.json → table_cells` pins all 48 encoded cells as
`[mode_group, unit, option, frequency] → [per_period, annual]`, transcribed
cell-by-cell from the tables (per-period row = "<unit> for a
Quarter/Month/Week"; annual row = "Total Sample Size for Year"). Arithmetic
cross-check (not a derivation — both rows are quoted): per_period × 4/12/52
equals the annual cell for every cell EXCEPT one the manual itself prints
inconsistently — Table 43.07, One-Way Car Trips, Base Option, weekly:
"Trips for a Week **6**", "Total Sample Size for Year **288**" (6 × 52 =
312 ≠ 288). Verbatim rules: both cells are encoded exactly as printed and
pinned as printed (`MANUAL_PRINTED_ANOMALY` in test_golden_sampling.py);
Headway never "corrects" a published table by arithmetic. An agency using
this cell should note the discrepancy to its validation analyst.

Representative hand-transcriptions (one per table):

- Table 43.01, DR, APTL option, quarterly: "Vehicle Days for a Quarter 12",
  "Total Sample Size for Year 48" → (12, 48).
- Table 43.03, one-way trips, base option (column (3)), weekly: "Trips for a
  Week 11", "Total Sample Size for Year 572" → (11, 572).
- Table 43.05, CR, APTL option, monthly: "One-Way Car Trips for a Month 3",
  "Total Sample Size for Year 36" → (3, 36).
- Table 43.07, one-way train trips, base option, quarterly: "Trips for a
  Quarter 45", "Total Sample Size for Year 180" → (45, 180).

The annual totals also match the tracker's pre-implementation summary row
("Ready-to-use sample sizes … verbatim annual totals").

## 2. §83 APTL estimate — hand-worked

Sample: four DR vehicle-days (an APTL-option plan), observed by manual ride
check:

| unit | observed UPT | observed PMT |
|------|--------------|--------------|
| d1   | 12           | 60           |
| d2   | 8            | 20           |
| d3   | 0            | 0            |
| d4   | 20           | 130          |

- Sample total UPT = 12 + 8 + 0 + 20 = **40**
- Sample total PMT = 60 + 20 + 0 + 130 = **210**
- Sample APTL (§83.05(a), ratio of totals) = 210 ÷ 40 = **5.25**
- The §83.05(b)-BANNED average of per-unit ratios is not even well-defined
  here (d3 has zero passengers); over the defined units it would be
  (60/12 + 20/8 + 130/20) ÷ 3 = (5.00 + 2.50 + 6.50) ÷ 3 = 4.6667 ≠ 5.25 —
  the golden pins that the module returns 5.25, the ratio of totals.
- Expansion factor (§83.01(a)): 100% count of annual UPT = 250,000.
- Estimated annual PMT (§83.07(a)) = 250,000 × 5.25 = **1,312,500**.

By type of service days (§83.01(b) / §83.03(b) / §83.05(a)(2) — per-day-type
ratio of totals × per-day-type 100% UPT):

| day type | units (UPT, PMT) | totals | APTL | 100% UPT | estimated PMT |
|----------|------------------|--------|------|----------|----------------|
| Weekday  | w1 (10, 40), w2 (30, 140) | 40, 180 | 4.50 | 200,000 | 900,000 |
| Saturday | s1 (5, 30)       | 5, 30  | 6.00 | 30,000   | 180,000 |
| Sunday   | u1 (4, 10)       | 4, 10  | 2.50 | 20,000   | 50,000 |

Sum of the day-type estimates = 1,130,000 (the §83.07(b)-style two-step).

Quantization convention: APTL at 0.01 (the manual's own displayed precision —
Table 83.01 shows 4.93, Exhibit 44 shows 4.71), estimates at whole passenger
miles, ROUND_HALF_EVEN (the pmt_atl_estimate convention).

## 3. Sample draw — reproducibility anchor

Frame: `trip-01 … trip-10`; seed `headway-0012-golden-seed`; draw 4 without
replacement. The documented keyed-hash ordering (DRAW_METHOD, §63.03(b))
yields, deterministically and regardless of the frame's input order:

    trip-09, trip-02, trip-06, trip-10

This pin is the regression anchor for the drawer's procedure: any change to
the keying/ordering is a drawer version change, because recorded seeds must
reproduce their historical draws bit-for-bit forever.
