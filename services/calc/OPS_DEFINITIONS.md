# OPS_DEFINITIONS — Headway operations-metric definitions

**Everything in this file is an OPERATIONS metric, never a regulatory
figure.** This is the operations analogue of `REGULATORY_TRACKER.md`, under
the same quote-or-own-it discipline (handoff 0014, design point 1): a
definition is either **Verified** — quoted verbatim from a fetchable public
industry source with a page citation and verification date — or it is an
**explicitly Headway-owned operational definition**, versioned, with the
formula shown. Nothing here cites an FTA manual, because nothing here is an
FTA figure.

The boundary is structural (migration 0024): every figure these
calculations persist carries `computed.metric_values.category = 'ops'`
(stamped by `headway_calc.persist` from the calc registry — no caller can
mislabel it); the database CHECK `metric_values_ops_never_certified` makes
a certified ops row unrepresentable; the certification route refuses ops
ids in plain language; the MR-20/S&S package reads and
`/public/metrics/certified` carry hard `category = 'ntd'` WHERE clauses;
and ops dq findings (`dq.issues.category = 'ops'`) never gate
certification. UIs must render every ops figure visibly distinct:
**"Operations metric — not an NTD reported figure."**

Versioning follows the calc-library rule: changing a formula, tolerance,
or definition mints a NEW version; shipped versions are never deleted or
rewritten.

---

## Verified — on-time performance window (TCQSM 3rd Edition)

> "this edition of the TCQSM defines 'on-time' as a departure from a
> timepoint as 1 min early to 5 min late or an arrival at the route
> terminal up to 5 min late."

— *Transit Capacity and Quality of Service Manual, Third Edition* (TCRP
Report 165, Transportation Research Board), Chapter 5 "Quality of Service
Methods", p. 5-29 (margin note: "TCQSM definition of 'on-time.'").
Fetched and verified 2026-07-13 from the TRB public copy:
`https://onlinepubs.trb.org/onlinepubs/tcrp/tcrp_rpt_165ch-05.pdf`.
Context, same page: "A review of U.S. transit agencies that publically
report their on-time performance found that many use an 'on-time'
definition of 1 min early to 5 min late."

This is the basis of the seeded defaults (migration 0024):
`otp_early_tolerance_seconds = 60`, `otp_late_tolerance_seconds = 300` —
per-agency `app.settings` knobs with the same audited provenance
discipline as `coverage_threshold` (a run records each tolerance's source
as `explicit` / `settings` / `default`).

> "on-time performance is the percent of schedule deviations (actual
> departure minus scheduled departure) that fall within a defined range
> (e.g., 1 min early to 5 min late)"

— ibid., p. 5-28 (the reliability-measures overview).

**Documented divergences of otp_v0 0.1.0 from the TCQSM measurement
setting** (Headway-owned choices, not TCQSM claims):

- TCQSM measures departures **at timepoints** (and arrival at the route
  terminal). Headway's canonical model does not yet carry the GTFS
  `timepoint` flag, so otp_v0 measures at **every scheduled stop with a
  usable schedule time and a supportable observed passage** — the
  passage-derivation refusals below decide "supportable".
- The observed passage instant (closest telemetry approach to the stop)
  is neither a pure arrival nor a pure departure; deviations compare it to
  the scheduled **arrival** time where present (the rider promise at a
  stop), falling back to the scheduled departure. Measurement uncertainty
  is bounded by the derivation's cadence tolerance (≤ ±60 s), small
  against the 6-minute window.

## Verified — headway adherence, coefficient of variation (TCQSM 3rd Edition)

> "The bunching effect can be measured in terms of headway adherence—the
> regularity of transit vehicle arrivals with respect to the scheduled
> headway. It is calculated as the coefficient of variation of headways
> cvh: the standard deviation of headways (representing the range of
> actual headways), divided by the average (mean) headway."

— ibid., p. 5-30 (subscript formatting flattened by text extraction:
"cvh" is c\_v\_h in print).

> "Headway adherence is calculated as the coefficient of variation of
> headway deviations (the standard deviation divided by the mean scheduled
> headway) […]"

> "If the dataset included all of the trips for the study time period—for
> example, when all buses are AVL-equipped and their data are included in
> the dataset—then the population standard deviation would be used."

— ibid., Calculation Example 3 ("Headway Deviation"), p. 5-92. Fetched and
verified 2026-07-13, same source URL.

headway_adherence_v0 implements the **Example 3 formulation** (deviations
against the *scheduled* headway) because Headway aggregates across stops
and periods where the scheduled headway varies; the population standard
deviation is used per the quoted rule — the input is the full set of
supportable AVL-derived passages for the period, not a hand-collected
sample. Both choices are pinned by goldens.

Note the TCQSM also describes **excess wait time** on the same pages; the
choice of cvh over excess wait time for v0 is recorded in handoff 0014's
open questions (excess wait time is the natural second formula for v1).

---

## Headway operational definition — derive_stop_passages 0.1.0

**Owner: Headway. No external source defines this derivation.** It turns
`canonical.vehicle_positions` × the observed trips' scheduled stops
(`canonical.stop_times` × `canonical.stops` × `canonical.trips`) into
observed stop passages. Deterministic; versioned; changing any tolerance
mints a new version. Implementation: `headway_calc/passages.py`.

Method:

1. Positions group per (trip_id, vehicle_id) and split into trip
   **occurrences** where consecutive positions are > 3 h apart (GTFS
   trip_ids recur every service day). Rows repeating the previous vehicle
   timestamp are collapsed (the same report re-polled) and counted.
2. The passage instant for each scheduled stop with coordinates is the
   event time of the occurrence's **closest-approach position**
   (equirectangular planar approximation — sub-percent error at the
   ~100 m scale in play; ties break to the earliest position). This is a
   measurement with stated uncertainty, never an interpolation: no
   position is invented between reports.
3. A passage is **refused** — per-reason counts travel inside every ops
   figure's `detail.derivation` and the run's
   `ops_passage_derivation_summary` finding — when:
   - the closest approach is farther than **100 m** from the stop
     (`refused_not_reached`);
   - the closest approach is the occurrence's first or last position
     (`refused_endpoint_unbounded` — the true pass may lie outside the
     observed window);
   - either inter-position gap bounding the closest approach exceeds
     **120 s** (`refused_cadence_gap` — the instant would carry more than
     ±60 s of uncertainty).

**Where the tolerances come from — the measured MBTA cadence
(2026-07-13, live `canonical.vehicle_positions`, 2,238,739 within-trip
consecutive gaps over [2026-07-09, 2026-07-11)):**

| statistic | value |
|---|---|
| inter-position gap p25 / p50 / p75 | 24 s / 30 s / 34 s |
| p90 / p95 / p99 | 45 s / 59 s / 99 s |
| share of gaps > 60 s / > 120 s / > 300 s | 4.02 % / 0.70 % / 0.21 % |
| duplicate-timestamp share (same report re-polled) | 12.36 % |
| max gap | 87,220 s |
| movement between distinct reports p50 / p90 | 104 m / 364 m |

- `MAX_PASSAGE_GAP_SECONDS = 120`: above the measured p99 (99 s) — normal
  30 s polling always qualifies, real gaps refuse; per-stop timing then
  carries at most ±60 s of uncertainty, supportable against a 6-minute
  on-time window. **This is also the refusal line the handoff requires:
  where cadence cannot support a per-stop passage, the derivation refuses
  it rather than emit it** — and otp_v0 refuses outright
  (`no_observed_passages`, blocking) when nothing supportable remains.
- `STOP_RADIUS_METERS = 100`: the median movement between distinct reports
  is 104 m, so a vehicle truly passing a stop is typically observed within
  ~52 m of it; 100 m accepts normal cadence without claiming passages the
  data cannot support.
- `OCCURRENCE_SPLIT_SECONDS = 10800`, `MIN_OCCURRENCE_POSITIONS = 3`:
  structural bounds (service-day recurrence; fewer than 3 positions cannot
  bound any passage).

These tolerances are part of the derivation's identity, **not** policy
knobs: an agency changing them would change what "an observed passage"
means, so they change only with a new derivation version.

## Headway operational definition — otp_v0 0.1.0 (metric `otp`, unit `percent`)

**Formula (window verified above; everything else Headway-owned):**

```
deviation_i = observed_passage_i − scheduled_time_i          (seconds)
on_time_i   = (−E ≤ deviation_i ≤ L)                          E, L ≥ 0
OTP         = 100 × |{i : on_time_i}| / N                     N = usable passages
```

quantized to 0.01 (ROUND_HALF_EVEN), computed from exact integer/Fraction
arithmetic — floating point never touches the figure. `E`/`L` are the
`otp_early_tolerance_seconds` / `otp_late_tolerance_seconds` knobs
(defaults 60/300, TCQSM-cited above; both boundaries inclusive).

Schedule anchoring (Headway-owned, deterministic):

- GTFS schedule times are integer seconds after **"noon minus 12 h"**
  local to the agency (the GTFS Schedule Reference convention — verify at
  gtfs.org; immune to DST transitions).
- The agency timezone is **feed-declared**: `canonical.agencies`
  (migration 0026, from `agency.txt`, whose `agency_timezone` the GTFS
  spec requires and requires to be uniform per feed). otp_v0 **refuses**
  (blocking `agency_timezone_unknown` / `agency_timezone_ambiguous`) when
  it is absent or conflicting — a schedule anchor is never guessed.
- The service day of a passage resolves deterministically: among the
  observation's local date and its two calendar neighbors, the candidate
  whose scheduled instant lies closest to the observation wins — exact
  for any deviation under 12 h, correct for past-midnight (> 24:00:00)
  schedule times.
- Timezone data is stdlib `zoneinfo` over the deployment's pinned tzdata —
  a versioned input, the same determinism posture as the feed itself.

Refusals: `no_observed_passages` (blocking) when no derived passage has a
usable scheduled time. Passages whose schedule row carries neither arrival
nor departure seconds are counted (`passages_unscheduled`), never
interpolated. Per-route figures (`scope = 'route:<route_id>'`; unknown
trips bucket as `route:unknown`) require ≥ 20 passages
(`MIN_PASSAGES_PER_ROUTE`, Headway-defined); thinner routes are reported
in the `ops_routes_below_min_sample` finding instead of served.

## Headway operational definition — headway_adherence_v0 0.1.0 (metric `headway_adherence`, unit `ratio`)

**Formula (the TCQSM Example-3 formulation, verified above; the pairing
rule is Headway-owned):**

At each (route_id, direction_id, stop_id), order the observed passages by
observed time and take consecutive pairs (i, i+1):

```
scheduled_headway_i = s_{i+1} − s_i        (scheduled seconds; departure
                                            preferred, arrival fallback)
observed_headway_i  = t_{i+1} − t_i        (observed passage instants)
deviation_i         = observed_headway_i − scheduled_headway_i

cvh = pstdev({deviation_i}) / mean({scheduled_headway_i})
```

pooled over all groups in scope; population standard deviation per the
quoted TCQSM rule; evaluated exactly (integer seconds → Fraction variance
→ 50-digit Decimal square root), quantized to 0.0001 ROUND_HALF_EVEN.
Lower is steadier; TCQSM reads cvh against its LOS bands — Headway serves
the number, never a grade.

Pair exclusions — counted in the detail, never silent:

- `pairs_excluded_unscheduled`: a member has no scheduled time;
- `pairs_excluded_inverted`: non-positive scheduled or observed headway
  (overtaking, duplicate passage);
- `pairs_excluded_over_cap`: scheduled headway > 7200 s
  (`MAX_SCHEDULED_HEADWAY_SECONDS`, Headway-defined — a service gap, not
  a headway).

The scheduled headway comes from the **same pair's** scheduled times, so
no service calendar is needed and a trip missing from observation widens
both sides of one pair instead of silently distorting the figure — the
honest choice while observation coverage is partial. Consequence
(documented limitation): completely unoperated or unobserved trips do not
lengthen measured headways; this metric measures the regularity of the
service that was observed, not schedule delivery. Per-route figures
require ≥ 10 usable pairs (`MIN_PAIRS_PER_ROUTE`, Headway-defined).

---

## Prediction data — canonical.trip_updates (context, no metric)

GTFS-Realtime TripUpdate stop-time events are normalized into
`canonical.trip_updates` (migration 0025) with every time column named
`predicted_*` and the frame's header timestamp as `feed_timestamp`:
**predictions are predictions**, never observations, and nothing in this
file consumes them. Prediction-accuracy metrics (predictions vs observed
passages) are the natural v1 noted in handoff 0014.
