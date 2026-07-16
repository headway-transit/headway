# daytype_v0 golden basis — hand-worked day-type month (handoff 0020)

Synthetic fixture, NOT an FTA-certified figure; regression anchor only.
Regulatory basis: 2026 NTD Policy Manual (Full Reporting) pp. 154–156,
quoted verbatim in `services/calc/REGULATORY_TRACKER.md`, "Verified — Days
Operated and day-type schedules"; the per-day UPT arithmetic is upt_v0's
(p. 146 missing-trip rule, quoted under "Verified definitions — UPT").

## Calendar: February 2026, period [2026-02-01, 2026-03-01), 28 days

2026-02-01 is a Sunday. Day-of-week classification:

- Sundays: 1, 8, 15, 22 (4 dates)
- Saturdays: 7, 14, 21, 28 (4 dates)
- Weekdays: 2–6, 9–13, 16–20, 23–27 (20 dates)

Two agency declarations (`app.service_day_overrides`):

1. **2026-02-16 → assigned_day_type 'sunday'** (Washington's Birthday; the
   p. 156 holiday rule: "report holiday service under the day that most
   closely reflects the service"). Weekday count 20 → **19**; Sunday count
   4 → **5**.
2. **2026-02-14 → atypical = true** (special event), no reassignment: it
   stays a Saturday-schedule date, flagged atypical.

Final classification: **weekday 19 dates** (2,3,4,5,6,9,10,11,12,13,17,18,
19,20,23,24,25,26,27), **saturday 4 dates** (7, 14*, 21, 28 — * atypical),
**sunday 5 dates** (1, 8, 15, 16, 22).

## Case `typical_month`

Telemetry (in-trip positions) exists on exactly 6 dates; every other date
is UNOBSERVED (warned as an observed lower bound — never guessed):

| date | type | trips operated | boardings (per trip) | day UPT |
|---|---|---|---|---|
| 2026-02-02 | weekday | t-a, t-b | 30 + 20 | 50 |
| 2026-02-03 | weekday | t-c | 40 | 40 |
| 2026-02-07 | saturday (typical) | t-d | 25 | 25 |
| 2026-02-08 | sunday | t-f | 12 | 12 |
| 2026-02-14 | saturday (ATYPICAL) | t-e | 60 | 60 |
| 2026-02-16 | sunday (reassigned) | t-g | 18 | 18 |

Every operated trip has events (missing share 0 per day → factor
1.000000, the p. 146 ≤2% branch); alightings equal boardings on every trip
(no p. 151 warnings); every source is 'tides' (no simulated finding).

**daytype_days_operated_v0 (value = operated-date count, all splits):**

- weekday: **2** (02, 03); 17 unobserved weekday dates → one
  `daytype_days_unobserved` warning.
- saturday: **2** (07 typical + 14 atypical); unobserved 21, 28 → warning.
- sunday: **2** (08, 16); unobserved 1, 15, 22 → warning.

Lineage per day type = the earliest in-trip position record of each counted
date: weekday [p-0202-a, p-0203-a] (08:00 v1 sorts before 09:00 v2),
saturday [p-0207-a, p-0214-a], sunday [p-0208-a, p-0216-a].

**daytype_upt_avg_v0 (mean of per-day upt_v0 values over the split's
operated days; ONE 0.01 ROUND_HALF_EVEN quantization of the exact
fraction):**

- weekday typical: (50 + 40) / 2 = **45.00**
- saturday typical: 25 / 1 = **25.00** (the atypical 14th is EXCLUDED from
  the typical average — the documented convention, split stated)
- saturday ATYPICAL: 60 / 1 = **60.00** (its own split row — declared
  atypical days exist)
- sunday typical: (12 + 18) / 2 = **15.00** (the reassigned holiday's 18
  boardings land in the SUNDAY average per the declaration)

No atypical weekday/sunday dates exist → no atypical split rows for those
types; `atypical_flags_declared` is true period-wide (the 14th).

## Case `refused_day` (refusal inheritance — binding rule)

Positions only on 2026-02-02: trips t-a AND t-b operated; events exist for
t-a only (10 boardings). Per-day upt_v0: missing share 1/2 = 0.5 > 0.02 →
the day REFUSES (`apc_missing_trips_above_fta_threshold`, statistician
workflow). Therefore:

- weekday typical average: **REFUSED** — one summary
  `daytype_average_over_refused_days` naming 2026-02-02 PLUS the day's own
  blocking finding propagated date-prefixed (the same receipts). Value
  None; nothing persisted.
- saturday/sunday typical: zero operated days → `daytype_no_operated_days`
  (an average over nothing is never invented; 0 is never a stand-in).
- days_operated still counts weekday = 1 (Days Operated is
  observation-derived and blocking-free; the UPT refusal does not erase the
  fact that service ran).
