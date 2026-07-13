# headway-calc

Headway's deterministic calculation library — **the only place any reported
number originates** (walking skeleton per ADR-0009, schema contract per
handoff `docs/handoffs/0001`, gap policy per handoff `docs/handoffs/0002`,
block-aware VRH per handoff `docs/handoffs/0003`, trip-level excision per
handoff `docs/handoffs/0004`, Unlinked Passenger Trips over TIDES passenger
events per handoff `docs/handoffs/0005`).
Pure, versioned functions: stdlib-only core, no network, no clock reads, no
randomness, no hidden state; time comes exclusively from inputs, and results
are `Decimal`, never float.

## Contents

- `headway_calc/types.py` — frozen dataclasses: `VehiclePosition` (now
  carrying the trip's GTFS `block_id`, joined by the reader),
  `PassengerEvent` (canonical.passenger_events per handoff 0005 — TIDES
  vocabulary; `event_count` NULL preserved as None, never coalesced),
  `CalcResult`
  (carries `input_record_ids` for lineage, `blocking_issues`, `warnings`,
  `infos`, and the coverage `detail`; invariant: blocking findings ⇒
  `value=None` — warnings/infos never force None), `Finding` (with
  `severity`: `'blocking'`/`'warning'`/`'info'`; the 0.1.0 name
  `BlockingIssue` stays importable, defaulting to blocking),
  `CoverageDetail`, `BlockCoverageDetail` (0.3.0: adds
  `layover_max_seconds` provenance), `TripExcisionCoverageDetail` (0.4.0:
  trip-denominated coverage + `total_trips`/`trips_excised`/
  `blocks_touched`/`layover_intervals_dropped`), `UptDetail` (upt_v0:
  counted boardings, operated/missing trips, missing share, applied factor,
  source mix, both thresholds).
- `headway_calc/distance.py` — haversine miles (float per leg, one final
  Decimal quantization to 0.01 mi, ROUND_HALF_EVEN — rule documented in the
  module, pre-verification).
- `headway_calc/vrm.py` — `vrm_v0`: `compute_vrm` (0.2.0, the default path —
  deliberately NOT block-aware: layover miles are N/A per Exhibit 35) and
  `compute_vrm_v0_1` (0.1.0, retained unchanged for bit-for-bit historical
  recomputes).
- `headway_calc/vrh.py` — `vrh_v0`: `compute_vrh` (0.4.0, the default path —
  trip-level excision, handoff 0004), `compute_vrh_v0_3` (0.3.0, block-level
  exclusion, retained unchanged), `compute_vrh_v0_2` (0.2.0,
  retained unchanged) and `compute_vrh_v0_1` (0.1.0, retained unchanged).
- `headway_calc/upt.py` — `upt_v0`: `compute_upt` (0.1.0 — Unlinked
  Passenger Trips over TIDES passenger events, handoff 0005; the p. 146
  missing-trip rule with the REAL FTA 2% threshold; see "Unlinked Passenger
  Trips" below).
- `headway_calc/voms.py` — `voms_v0`: `compute_voms` (0.1.0 — monthly
  Vehicles Operated in Maximum Service, handoff 0009: max over UTC service
  days of distinct in-trip vehicles; BLOCKING-FREE by design, partial
  observation is a warning; see "Mode dimension, VOMS and the MR-20
  package" below).
- `headway_calc/mode.py` — the handoff-0009 mode dimension:
  `compute_{vrm,vrh,upt,voms}_by_mode` run the UNCHANGED calc versions over
  per-mode input subsets (input selection, not a semantics change — no
  version bump; `REGULATORY_TRACKER.md`, "Mode scoping"); NULL mode buckets
  as `'unknown'` (never dropped, never guessed) and is surfaced by ONE
  `unknown_mode_share` info finding per per-mode run.
- `headway_calc/mr20.py` — `build_mr20_package` + the
  `python -m headway_calc.mr20 --month YYYY-MM [--run]` CLI: the
  NOT-REPORTABLE MR-20 preview package (four data points per mode + fleet,
  full per-cell provenance, explicit-null missing cells, programmatic
  caveats, rail modes pending D2).
- `headway_calc/_blocks.py` — internal 0.3.0/0.4.0 machinery: block
  grouping, layover accounting, the block gap policy (0.3.0), the
  trip-excision policy (0.4.0), and the `block_unavailable`
  per-vehicle-day info findings. The 0.1.0/0.2.0 machinery in
  `_grouping.py` is untouched.
- `headway_calc/persist.py` — injectable DB-API writer:
  `computed.metric_values` (including the coverage `detail` JSONB, migration
  0010) + one `lineage.edges` row per consumed raw record (ADR-0007; for
  0.2.0 that means included groups only). Refuses results carrying blocking
  issues or `value=None`; warnings never refuse.
- `headway_calc/reader.py` — injectable DB-API readers over a **half-open
  UTC period** `[period_start, period_end)` (`time >= start AND time < end`;
  DATE bounds bound as timezone-aware UTC midnights so the comparison never
  depends on the DB session time zone): `load_vehicle_positions`
  (`canonical.vehicle_positions` ordered by `(vehicle_id, time,
  source_record_id)`, with `canonical.trips.block_id` LEFT JOINed onto every
  position — handoff 0003 / migration 0011; NULL when unassigned/absent,
  never a dropped row), `load_passenger_events`
  (`canonical.passenger_events` per handoff 0005 / migration 0012, half-open
  on `event_timestamp`, ordered by `(event_timestamp, passenger_event_id,
  source_record_id)`; NULLs pass through) and `load_operated_trip_ids`
  (`SELECT DISTINCT trip_id` from the positions table — the operated-trips
  denominator of the upt_v0 missing-trip rule).
- `headway_calc/dq.py` — routes `Finding`s into `dq.issues` with **each
  finding's own severity** (warning stays warning, blocking stays blocking;
  one row per finding, status `'open'`, description naming the calc, version,
  period, and the severity-specific consequence). `route_blocking_issues`
  (0.1.0 entry point) is retained and refuses non-blocking findings. Never
  swallows an insert failure; never commits (transaction control is the
  runner's).
- `headway_calc/settings.py` — injectable reader for `app.settings`
  (migration 0014, the audited per-agency policy surface):
  `load_policy_settings(conn)` returns a frozen `PolicySettings` with the
  four seeded knobs (`coverage_threshold`, `gap_threshold_seconds`,
  `layover_max_seconds`, `missing_trip_threshold`; decimals parsed via
  `Decimal`, never float; ints for the seconds knobs). Fails LOUDLY
  (typed `SettingsError`) when the table exists but a knob is missing or
  unparseable — never a silently substituted code default; the ONE
  tolerated absence is the table itself (SQLSTATE 42P01, a
  pre-migration-0014 database → `None` + a WARNING, code defaults apply).
- `headway_calc/runner.py` — `run_period(conn, start, end,
  gap_threshold_seconds=None, coverage_threshold=None,
  layover_max_seconds=None, missing_trip_threshold=None,
  imbalance_threshold=None, read_settings=True)`: closes the
  canonical→computed loop (settings → reader →
  compute_vrm 0.2.0 / compute_vrh 0.4.0 / compute_upt 0.1.0 → dq routing →
  persist) and returns a frozen `RunReport` carrying all five inputs, each
  threshold's provenance (`threshold_sources`) and
  per-metric detail. Threshold precedence: explicit argument >
  `app.settings` row > code default. See "Runner" below.
- `headway_calc/_cli.py` — the ONE process boundary (argv, env, psycopg);
  exempt from the stdlib-purity guardrail, contains no calculation logic.
- `REGULATORY_TRACKER.md` — calc/version → citation → verification status.
  VRM/VRH/deadhead/layover definitions are VERIFIED against the 2026 NTD
  Policy Manual (quoted in the tracker); divergence D1 (layover inclusion)
  is CLOSED by vrh_v0 0.3.0 and retained by 0.4.0; UPT definitions
  (pp. 143/146/151) are VERIFIED and quoted for upt_v0 0.1.0 with the TIDES
  enum citation; **no figure is
  reportable** pending the remaining divergences D2–D6, the flagged
  `coverage_threshold` 0.95 engineering placeholder (`layover_max_seconds`
  1800 is now data-informed and exhibit-aligned per handoff 0004, per-agency
  configurable), and — for UPT — the simulated-only data and the pp. 147–148
  APC certification workflow.
- Golden dataset: `tests/golden/vrm_vrh_v0/` (repo root) — synthetic
  hand-worked example (see its `BASIS.md`); regression anchor only, not an
  FTA-certified figure. `expected.json` pins 0.1.0; `expected_v0_2.json`
  pins the 0.2.0 gap policy over the same fixture; `fixture_block.json` +
  `expected_v0_3.json` pin the 0.3.0 block case (600 s layover included);
  `fixture_block_v04.json` + `expected_v0_4.json` pin the 0.4.0 trip-level
  excision case (three-trip block, middle trip gapped). For UPT:
  `tests/golden/upt_v0/` pins the blocked case (missing share 1/3 > 2%) and
  the factored case (share exactly 0.02 → 98 × 50/49 = 100), hand-worked in
  its `BASIS.md`. Handoff 0009 adds `tests/golden/voms_v0/` (three days,
  distinct-vehicle counts 2/3/2 → 3), `tests/golden/mode_scope/` (two modes
  + the unknown bucket; per-mode values summing exactly to the fleet values
  for vrm/vrh/upt) and `tests/golden/mr20/` (canned metric rows → the exact
  package JSON), each with its own hand-worked `BASIS.md`.

## Unlinked Passenger Trips — upt_v0 0.1.0

Per handoff 0005, `compute_upt(events, operated_trip_ids, *,
missing_trip_threshold=Decimal("0.02"), imbalance_threshold=Decimal("0.10"))`
computes UPT from TIDES passenger events (2026 NTD Policy Manual p. 143:
"the number of boardings on public transportation vehicles"):

- **Verified TIDES vocabulary.** Boardings are events with the verbatim
  `event_type` `"Passenger boarded"` (alightings: `"Passenger alighted"`) —
  verified 2026-07-10 against TIDES-transit/TIDES
  `spec/passenger_events.schema.json` (repo HEAD `7ddaa7ab`, schema file
  last changed `d887d42c`; citation in `REGULATORY_TRACKER.md`). Bike
  boardings are not passengers per p. 143 and are never counted.
- **Base count.** Sum of `event_count` over boarding events with a trip
  assignment (`trip_id` not None — the same revenue-service proxy as
  vrm/vrh, a documented approximation). A NULL `event_count` contributes 0
  and one `apc_null_count` **warning** citing the record — never coalesced
  to the TIDES default 1, and cited by the warning instead of lineage.
- **p. 151 validations** ("agencies may flag trips or blocks where the
  difference between boardings and alightings is greater than 10 percent,
  or trips where the passenger load drops below zero"): per trip,
  |boardings − alightings| > `imbalance_threshold` × boardings → one
  `apc_count_imbalance` **warning**; the running load (events ordered by
  `trip_stop_sequence` then `event_timestamp`; NULL sequence last —
  documented convention) dropping below zero → one `apc_negative_load`
  **warning** citing the record of the first drop. The figure stands.
- **p. 146 missing-trip rule** (the 0.02 default is a REAL FTA threshold,
  not a placeholder): operated trips (distinct `trip_id`s observed in
  `canonical.vehicle_positions` over the period) with ZERO passenger events
  are missing. Share ≤ 2% → **deterministic, FTA-sanctioned factor-up**:
  `UPT = counted × operated/(operated − missing)`, computed from the exact
  fraction and quantized to whole boardings (Decimal 1, ROUND_HALF_EVEN — a
  documented engineering rounding; the manual prescribes none), with the
  factor and all inputs recorded in the `UptDetail` JSONB. Share > 2% → ONE
  **blocking** `apc_missing_trips_above_fta_threshold` and `value=None` —
  the statistician-approved factoring the manual requires is a human
  workflow, never guessed.
- **Simulated-source rule (binding, handoff 0005).** Any event with
  `source != "tides"` (e.g. `"tides_simulated"`) yields ONE
  `simulated_source_data` **info** finding listing the sources; the
  `source_mix` (event counts per source) is ALWAYS in the detail — a
  certifiable figure containing simulated records is a contradiction the DQ
  trail must make visible.
- **Lineage**: `input_record_ids` are the distinct records of counted
  boarding events; NULL-count and unassigned events never appear there.
- **Fleet-wide limitation**: the factor-up is fleet-wide in v0, not per
  mode/TOS (handoff 0005 open question; see `REGULATORY_TRACKER.md`).

## Passenger Miles Traveled — pmt_v0 0.1.0 (handoff 0011)

`headway_calc.pmt.compute_pmt(events, operated_trip_ids, stop_times, ...)`
— PMT per the 2026 NTD Policy Manual pp. 143–155 (verified; tracker section
"Verified — Passenger Miles Traveled"): per trip, the running passenger
load by stop_sequence × each segment's distance between consecutive
scheduled stops (canonical.stop_times + canonical.stops, migration 0019),
summed over VALID trips, quantized 0.01 mile. The load-bearing rules — the
per-segment distance-source precedence (shape_dist deltas need an EXPLICIT
feed-unit conversion; haversine fallback is a flagged, documented
understating divergence), the pp. 151–152 invalid-trip discard discipline
(unlike upt_v0, a defective load profile is EXCLUDED and counts against the
p. 146 2% rule; above the line the run REFUSES with the statistician
citation), the TIDES `trip_stop_sequence`-is-ordinal join assumption, and
the never-guess treatment of NULL counts/coordinates/sequences — are
specified in the module docstring and the tracker row; goldens (incl. the
manual's own Exhibit 44 worked example, verbatim) are hand-worked in
`tests/golden/pmt_v0/BASIS.md`. The runner computes pmt_v0 on the default
path (and per mode on `--per-mode`), sharing upt_v0's
`missing_trip_threshold`/`imbalance_threshold` knobs; the persisted metric
is `pmt` (unit `passenger_miles`).

**Estimator, never conflated with computed PMT:**
`estimate_pmt_average_trip_length` /
`estimate_pmt_from_average_trip_length` implement the Exhibit 44
average-trip-length method (pp. 154–155) as pure functions whose results
carry the fixed `ESTIMATION_METHOD` provenance label; they persist nothing.

## NTD sampling support — sampling_v0 0.1.0 (handoff 0012)

`headway_calc.sampling` — the sampling tier for agencies WITHOUT full APC
coverage (FTA NTD Sampling Manual, March 31, 2009; tracker sections
"Verified — NTD Sampling Manual" + "Sampling plan tables — implementation
quotes"). Three pure facilities, none of which writes
`computed.metric_values`:

- **Plan selector** — `plan_requirement(mode, unit, efficiency_option,
  frequency)` returns the required per-period AND annual sample sizes as
  VERBATIM cells of Tables 43.01/43.03/43.05/43.07 (all 48 cells pinned
  one-for-one in `tests/test_golden_sampling.py`, including the manual's
  own printed per-week-vs-annual inconsistency in Table 43.07, kept AS
  PRINTED), with the §41.01/§41.03 eligibility rules attached as
  plain-language guidance strings — never silent logic.
- **§83 APTL estimator** — `sample_aptl` (sample total PMT ÷ sample total
  UPT — the §83.05(a) ratio of totals), `estimate_annual_pmt` (100% UPT
  expansion factor × sample APTL, §83.01(a)/§83.07(a)) and
  `estimate_pmt_by_service_day`. The §83.05(b) ban ("You must not determine
  the sample APTL as the average of the APTL across individual service
  units") is STRUCTURAL: the input is per-unit (UPT, PMT) observation
  pairs, no per-unit ratio exists anywhere in the API, and a
  merge-invariance Hypothesis property proves the computed quantity is a
  ratio of totals. Every result carries the `SAMPLING_ESTIMATION_METHOD`
  provenance label — a sampled ESTIMATE, never conflated with computed
  pmt_v0.
- **Sample drawer** — `draw_sample(service_units, sample_size, seed)`:
  keyed-hash (SHA-256) random ordering under a caller-supplied RECORDED
  seed — a §63.03(b) "any other method", without replacement BY
  CONSTRUCTION, deterministic per (seed, frame) forever (golden
  reproducibility anchor + prefix-consistency property, which is what makes
  random oversampling sound). The module itself contains no randomness
  (purity guardrail): the API generates the seed with a CSPRNG and records
  it.

Hand-worked goldens: `tests/golden/sampling_v0/BASIS.md`. Persistence/API:
migration 0020 (`sampling.plans`/`draws`/`measurements`, all append-only by
trigger) + the `/sampling/*` endpoints in services/api.

## Demand Response — dr_vrh/dr_vrm/dr_upt/dr_voms/dr_pmt 0.1.0 (handoff 0013)

`headway_calc/dr.py` computes the five DR figures over `canonical.dr_trips`
(migration 0021 — the `demand_response_trip` v0 wire contract normalized;
one row per booking, from dispatch platforms, not GTFS-RT). Every rule is a
verbatim quote in `REGULATORY_TRACKER.md`, "Verified — Demand Response /
on-demand reporting":

- **dr_vrh/dr_vrm** — Exhibit 36 semantics: revenue SPANS first pickup →
  last dropoff per (vehicle, service_date), BROKEN at interruption markers
  (lunch/fuel/garage/dispatch returns, p. 129); waiting, empty
  inter-passenger travel and no-show visits inside a span are revenue BY
  CONSTRUCTION; TX vehicle-days count merged passenger-onboard windows only
  (the p. 129 TX rule). Miles prefer the whole-span odometer delta; an
  unmeasurable leg contributes 0 + a warning (documented undercount, never
  an interpolated distance); a TX overlap summed without boundary odometers
  warns as a possible overcount. `EXHIBIT_36` encodes all eight exhibit
  rows verbatim and every row is golden-pinned (table + one behavioral
  scenario each — `tests/golden/dr_v0/BASIS.md`).
- **dr_upt** — riders + NON-employee attendants/companions (pp. 143–144);
  ADA split in total, NEVER in the sponsored split (a both-flagged trip
  warns and counts as ADA); sponsored split in total, by sponsor label.
  Explicit golden: a no-show is revenue time YES and UPT ZERO.
- **dr_voms** — "largest number of vehicles in revenue service at any one
  time … (INCLUDES atypical service)": true simultaneity over the revenue
  intervals, every day counted — the OPPOSITE of voms_v0's non-DR
  atypical-day divergence (voms_v0 is deliberately not reused). Golden:
  Exhibit 40's Happy Transit (6 unique, 4 simultaneous → 4).
- **dr_pmt** — onboard-distance sums × persons per booking (no load-profile
  path); feeds the EXISTING `pmt` metric persistence.

The DR calcs NEVER block (no completeness threshold is quoted for DR —
inventing one, or borrowing p. 146 from the 100%-count context, would be a
regulatory number from the wrong context); every gap is a warning with its
direction stated. Contradictory vehicle-days (mixed TOS; interruption while
a passenger onboard) are excluded with warnings. Figures persist under
scope `mode:DR` plus `mode:DR:tos:<tos>` ONLY — never `agency` — whenever
the period holds dr_trips rows (`run_period` wiring; TOS partition is
vehicle-day-granular so per-TOS values decompose the mode figure,
property-tested). Simulated sources (`source != 'dr'`) always flag
`simulated_source_data`.

## Mode dimension, VOMS and the MR-20 package — handoff 0009

MR-20 (2025 NTD Monthly and Weekly Reference Policy Manual pp. 32–33,
verified — see `REGULATORY_TRACKER.md`, "Verified — Monthly Ridership form
MR-20") requires UPT, VRH, VRM and VOMS **per mode**. The pieces:

- **Mode on every row.** The reader LEFT JOINs `canonical.routes.mode` (via
  `canonical.trips`) onto every position and passenger event. NULL mode
  (unassigned row / unknown trip / unknown route) buckets as `'unknown'` —
  counted, computed, surfaced (ONE `unknown_mode_share` info per per-mode
  run, citations truncated at 100 records), never dropped, never guessed.
- **Per-mode compute paths, NO version bump.** `headway_calc.mode` runs the
  unchanged `compute_vrm` (0.2.0) / `compute_vrh` (0.4.0) / `compute_upt`
  (0.1.0) / `compute_voms` (0.1.0) over each mode's subset — subsetting
  inputs by mode is input selection, not a semantics change (tracker, "Mode
  scoping"). Rows persist with `scope = 'mode:<mode>'` alongside the
  unchanged `scope = 'agency'` row (the handoff-0001 `scope` column — no
  migration). The blocking guardrail holds per scoped result; the upt
  factor-up applies per mode on this path (closer to the manual than the
  fleet-wide factor, which the `'agency'` row retains unchanged).
- **voms_v0 0.1.0** (`compute_voms(positions, period_start, period_end)`):
  per UTC service day (the UTC calendar date of position time — documented
  convention), the count of distinct in-trip vehicles; the figure is the
  **maximum over days** (integer, unit `'vehicles'`; detail: days observed/
  in period, peak day — earliest on ties — and a min/max/mean per-day
  summary; lineage over the peak day's records). PRE-VERIFICATION proxy
  with divergences (a) day-level max ≠ schedule-peak simultaneity (upper
  bound), (b) no atypical-day exclusion, (c) rail passenger cars (D2) —
  tracker row voms_v0. **Blocking-free by design**: coverage machinery
  guards SUMS against gaps, but an observation gap can only UNDERSTATE a
  maximum — so partial observation is ONE `voms_partial_observation`
  warning (days_observed < days_in_period), never a refusal.
- **Additivity**: vrm/vrh/upt are additive across the mode partition
  (golden-pinned exact sums; property tests carry the explicit
  quantization bound). **voms is NOT additive** — modes may peak on
  different days; only `max(per-mode) ≤ fleet ≤ Σ(per-mode)` holds
  (property-pinned, max ≠ sum construction included).
- **MR-20 generator**:

  ```
  export HEADWAY_DATABASE_URL=postgresql://…/agency_db
  python -m headway_calc.mr20 --month 2026-07           # assemble only
  python -m headway_calc.mr20 --month 2026-07 --run     # run_period(per_mode=True) first
  ```

  Assembles the latest `computed.metric_values` row per metric+scope for
  the month's half-open period into the four MR-20 data points per mode +
  fleet. Every cell carries `{value, unit, metric_value_id, calc_name,
  calc_version, certification_status, flags, coverage}`; a missing cell is
  an **explicit null + reason** (never invented); rail modes (per the
  transform's route_type map: tram/subway/rail/cable_tram/funicular/
  monorail) carry `non_reportable_pending_d2: true`; the header is the
  NOT-REPORTABLE banner plus programmatically enumerated caveats
  (flag-derived + missing-cells + the fixed D1–D6 list). The package is the
  artifact the web report view can later consume verbatim.

## Safety & Security — sscls_v0 classifier + ss50 generator (handoff 0010)

S&S events are NOT derivable from telemetry: the source is validated manual
entry (`POST /safety/events`, migration 0017: `safety.events` append-only —
corrections supersede via `superseded_by`, never edit or delete). Two calc
pieces, both governed by the tracker's "Verified — Safety & Security
reporting (verified 2026-07-12)" section — the only permitted source of the
regulatory facts:

- **`headway_calc.sscls` — sscls_v0 0.1.1** (0.1.0 retained runnable as
  `classify_event_v0_1_0`; its single-injury Other-Safety-Event bug is
  pinned by test), the pure deterministic events→classification per
  Exhibit 5 (p. 16) and the pp. 17–22 rules AS QUOTED (tracker section +
  its two addenda). Rail vs non-rail thresholds keyed on the
  agency-supplied mode; $25,000 damage as exact Decimal (summed across all
  involved property + wreckage clearing, p. 25 — an entry hint); injury =
  immediate transport, but Other Safety Events (effective categories
  'evacuation'/'other' — NOT collisions/fires/security/hazmat/acts-of-God/
  derailments, p. 22) need TWO or more injured persons and a single-injury
  Other event is explicitly S&S-50; rail collisions meet the injury
  threshold at ONE injury (Example 4C); rail serious injury per the
  verbatim p. 21 criteria — automatically reportable, transport NOT
  required; rail substantial damage per the verbatim p. 25 criteria, with
  a rail-collision tow-away counting mechanically (Example 7C); non-rail
  collision tow-away threshold (revenue vehicle + any vehicle towed,
  p. 17); rail-to-rail collision auto-reportable (Example 4B); rail
  collision at a grade crossing (p. 17); rail vehicle-contact assault
  needs no injury (p. 17) while non-rail assault-with-contact is evaluated
  as a collision per Scenario E; runaway train and evacuation-to-
  controlled-ROW (rail; migration-0018 fields, p. 17 verbatim);
  evacuation for life safety (any mode); derailments incl. yard and
  non-revenue; cyber + substantial damage per Scenario G. ≥ 1 threshold
  met = ONE report (p. 14) — structurally pinned by the migration-0017
  CHECK ('major' ⇔ thresholds_met non-empty). No threshold → S&S-50
  non-major scope (p. 3 + p. 22) → else not_reportable. NULL damage is
  "not assessed", never $0. It is the SOLE writer of
  `safety.event_classifications` (`record_classification`). Goldens: ALL
  EIGHT Example 4 scenarios (A–H) plus Examples 6C/6E/6F/7C, hand-worked
  from the verbatim tracker solutions. Known gap (tracker row, owner NTD):
  hazmat/act-of-God events have no category and arrive as 'other'.
- **`headway_calc.ss50`** — `python -m headway_calc.ss50 --month YYYY-MM`
  emits the NOT-REPORTABLE S&S-50 preview: per-mode/per-TOS non-major
  counts with per-cell provenance (event_ids), EXPLICIT ZERO ROWS for every
  operated mode ("even if no event occurs" — operated modes derived exactly
  like the handoff-0009 per-mode path), superseded/unclassified/major
  events excluded and listed, CR/AR nuance FLAGGED not applied.
  `--ss40-event EVENT_ID` emits the S&S-40 detail export (every met
  threshold's supporting fields; due = occurred_at + 30 days, Exhibit 2,
  p. 4).

## Trip-level excision — 0.4.0 (default for VRH)

Per handoff 0004, `compute_vrh` (CALC_VERSION `0.4.0`) refines the exclusion
unit from the block group to *the gapped trip plus its adjacent layover
intervals* — definitional correctness (layover inclusion, D1) no longer
requires discarding a gapped block's sound data:

- **Grouping and layover accounting unchanged from 0.3.0** — block-aware
  grouping, NULL-block per-trip fallback with `block_unavailable` info
  findings, inter-trip intervals counted as layover up to
  `layover_max_seconds`, over-cap intervals not counted + one
  `layover_exceeds_max` warning.
- **Exclusion unit refined.** A within-trip gap (> `gap_threshold_seconds`)
  excises ONLY that trip's running time and the inter-trip layover intervals
  immediately adjacent to it (both sides, where present) — a layover
  interval counts only when BOTH bounding trips are clean, and an excised
  trip is never bridged. The block's remaining clean trips and their other
  layover intervals stay in the figure. One `telemetry_gap_excluded`
  **warning** per excised trip, citing that trip's records.
- **Coverage returns to trip denomination**: `coverage = clean_trips /
  total_trips` (directly comparable to 0.2.0's group coverage). The detail
  JSONB carries the trip coverage, the block statistics (`blocks_touched`,
  `trips_excised`, `layover_intervals_dropped`) and all three thresholds.
- **Lineage**: `input_record_ids` cover INCLUDED positions only; excised
  trips' records are cited by their findings.
- **`layover_max_seconds` 1800 is now data-informed and exhibit-aligned**
  (no longer a bare placeholder): the measured MBTA inter-trip interval
  distribution (2026-07-10, 7,400 in-block intervals: p50 = 30 s, p90 =
  109 s, p99 = 7,124 s, 2.7% > 1,800 s) shows a long tail of out-of-service
  parking, which Exhibit 35 explicitly excludes from revenue hours ("Bus
  arrives at the end of the route, parks, and goes out of service… →
  Vehicle Revenue Hours: No"). Still per-agency configurable, not an
  FTA-published number.
- **Monotonicity (property-tested)**: v0.4 ≥ v0.2 and v0.4 ≥ v0.3 on
  identical input — block-level exclusion is strictly harsher.
- `compute_vrh_v0_3` retains 0.3.0 unchanged (block-level exclusion) for
  bit-for-bit historical recomputes.

## Block-aware VRH — 0.3.0 (retained): layover inclusion

Per handoff 0003, `compute_vrh_v0_3` (CALC_VERSION `0.3.0`) closes divergence
D1 — the FTA **includes** layover/recovery time in VRH (2026 NTD Policy
Manual, Exhibit 35, p. 133; see `REGULATORY_TRACKER.md`):

- **Block grouping.** Positions of the same vehicle whose trips share a GTFS
  `block_id` (joined from `canonical.trips`, migration 0011) form ONE VRH
  group spanning consecutive trips. Groups with `block_id` NULL fall back to
  per-trip grouping (0.2.0 semantics) and emit one `block_unavailable`
  **info** finding per affected vehicle-day — a documented undercount, the
  figure stands.
- **Layover inclusion.** Elapsed time between the last position of trip N and
  the first position of trip N+1 *within the same block* is INCLUDED, up to
  `layover_max_seconds` (explicit input, default 1800 — **an ENGINEERING
  PLACEHOLDER** pending observed layover distributions; the manual's "10 to
  20 percent of running time" is descriptive, not a cap). This is measured
  elapsed wall-time between observed endpoints — block membership makes the
  interval layover *by definition* — never telemetry interpolation. An
  over-cap interval is NOT counted and emits one `layover_exceeds_max`
  **warning** finding (vehicle possibly out of service mid-block).
- **Within-trip gap rule unchanged** (`gap_threshold_seconds`, default 300):
  a gap inside a trip's running time still excludes per the 0.2.0 policy —
  but the exclusion unit is the BLOCK group (all its trips' records cited by
  the one `telemetry_gap_excluded` warning).
- **Coverage/threshold machinery unchanged**, over VRH block groups; the
  detail JSONB additionally carries `layover_max_seconds`. Lineage covers
  all positions of included block groups.
- **VRM stays 0.2.0** — layover *miles* are N/A per Exhibit 35; per-trip
  grouping remains correct for miles.
- `compute_vrh_v0_2` retains 0.2.0 unchanged (per-trip VRH, the documented
  D1 undercount) for bit-for-bit historical recomputes.

## Gap policy — 0.2.0: per-group exclusion + coverage

Per handoff 0002, `compute_vrm` (CALC_VERSION `0.2.0`, still the VRM default)
and `compute_vrh_v0_2`:

- **Per-group exclusion.** A `(vehicle_id, trip_id)` group containing a gap >
  `gap_threshold_seconds` (explicit input, default 300) is **excluded** from
  the summed figure — no interpolation, no partial sum across a gap. Each
  excluded group emits one `telemetry_gap_excluded` **warning** finding
  citing ALL of that group's `source_record_ids`.
- **Coverage.** `coverage = clean_groups / total_groups` (clean-position
  share also reported) is carried on the result as `detail` and persisted to
  `computed.metric_values.detail` (JSONB): `{coverage, total_groups,
  excluded_groups, clean_position_share, gap_threshold_seconds,
  coverage_threshold}` — ratios rendered as strings (Decimal-safe), quantized
  0.0001 ROUND_HALF_EVEN (documented engineering convention; the threshold
  comparison itself is exact integer cross-multiplication).
- **Certifiability line.** If coverage falls below `coverage_threshold`
  (explicit input, default 0.95 — **an engineering placeholder, not an FTA
  number**; see `REGULATORY_TRACKER.md`), the run emits ONE **blocking**
  `coverage_below_threshold` finding and `value=None` — never a certifiable
  value over an unresolved DQ gap. `persist_result` additionally refuses any
  such result.
- **Provenance narrows correctly.** `input_record_ids` (→ `lineage.edges`)
  cover **included groups only**; excluded groups' records are cited by their
  warning findings in `dq.issues` instead.

### Retained 0.1.0 (all-or-nothing refusal)

`compute_vrm_v0_1`/`compute_vrh_v0_1` keep the original rule unchanged: ANY
over-threshold gap anywhere records a blocking `telemetry_gap` finding naming
the bounding `source_record_ids` and returns `value=None`. Shipped versions
are never deleted or rewritten — historical submissions recompute
bit-for-bit, and the 0.1.0 goldens/property tests stay pinned to these
functions.

## Runner: closing the canonical→computed loop

```
export HEADWAY_DATABASE_URL=postgresql://…/agency_db
python -m headway_calc.runner --period-start 2026-06-01 --period-end 2026-07-01
# optional: --gap-threshold-seconds 300 --coverage-threshold 0.95 \
#           --layover-max-seconds 1800 --missing-trip-threshold 0.02 \
#           --imbalance-threshold 0.10 --ignore-settings --per-mode
```

`--per-mode` (default OFF — pre-0009 behavior byte-identical): additionally
runs voms_v0 and one mode-scoped result per metric per mode (scope
`'mode:<mode>'`), routing mode-scoped findings with their scope named and
the ONE run-level `unknown_mode_share` info. The MR-20 path
(`python -m headway_calc.mr20 --run`) turns it on.

### Threshold precedence — explicit flag > app.settings row > code default

Per threshold, the highest-precedence source wins, and the `RunReport`
records each threshold's provenance in `threshold_sources`
(`"explicit" | "settings" | "default"`):

1. **explicit** — the CLI flag / `run_period` argument;
2. **settings** — the `app.settings` row (migration 0014, the ONE audited
   place an agency sets calc policy — a value set through the settings API
   governs the next run with no flag needed). Applies to the four seeded
   knobs: `coverage_threshold`, `gap_threshold_seconds`,
   `layover_max_seconds`, `missing_trip_threshold` (`imbalance_threshold`
   is not a settings knob);
3. **default** — the calc library's documented code defaults. Reached only
   when `app.settings` does not exist (a pre-migration-0014 database —
   the runner logs a WARNING and proceeds, never silently) or under
   `--ignore-settings`.

A settings table that exists but cannot be trusted (a seeded knob row
missing, or a value unparseable / of the wrong `value_type`) raises a typed
`headway_calc.settings.SettingsError` and the run REFUSES before reading a
single canonical row — the runner never substitutes a guessed threshold for
an agency's audited policy.

`--ignore-settings` skips the `app.settings` read entirely (thresholds:
explicit flags, else code defaults). It exists for **reproducing historical
runs**: per `REGULATORY_TRACKER.md`'s rule ("shipped versions are never
deleted or rewritten"), a historical reproduction uses the PINNED calc
versions plus the EXPLICIT thresholds recorded in the original `RunReport` —
never whatever `app.settings` holds today.

Loads `canonical.vehicle_positions` (with `block_id` joined),
`canonical.passenger_events` and the operated trip_ids for the
**half-open** period `[period-start, period-end)` (UTC — June is
`[2026-06-01, 2026-07-01)`, so consecutive months tile with no
double-counted and no dropped instant), runs `vrm_v0` at CALC_VERSION 0.2.0,
`vrh_v0` at CALC_VERSION 0.4.0 (block-aware with trip-level excision;
`--layover-max-seconds` passes through; the per-metric `detail` in the
report carries the trip coverage plus `trips_excised`/`blocks_touched`/
`layover_intervals_dropped`) and `upt_v0` at CALC_VERSION 0.1.0
(`--missing-trip-threshold`/`--imbalance-threshold` pass through; its
`detail` carries the counted boardings, missing share, applied factor and
source mix), and prints the `RunReport` as JSON (all five
inputs recorded, each with its provenance in `threshold_sources` — see
"Threshold precedence" above). Per metric:

- **every finding is routed to `dq.issues` with its own severity** —
  block-fallback infos stay info, excised-trip and over-cap-layover
  warnings stay warnings, coverage refusals stay blocking;
- **blocking findings present** (coverage below threshold) → **no
  `computed.metric_values` row is written** for that metric (the guardrail:
  never emit a certifiable value over an unresolved gap), so certification
  (which refuses on any open blocking issue) is reachable exactly when
  coverage passes;
- **no blocking findings** → the value is persisted with its coverage
  `detail` JSONB and lineage edges (included groups only) via
  `persist.persist_result`; its warnings stand alongside as the routed
  `dq.issues` rows.

`python -m headway_calc.runner` requires `psycopg`
(`pip install 'headway-calc[persist]'`) and `HEADWAY_DATABASE_URL`; the
library API (`headway_calc.runner.run_period`) takes any injected DB-API
connection and needs neither.

### Transaction design — two transactions, fail-loudly-first

`run_period` deliberately uses **two** transactions, in this order:

1. **Issues first, committed first.** Every `dq.issues` row for the run
   (warnings AND blocking) is inserted and committed in its own transaction
   before any value is written. Evidence of a data problem must never be
   lost: if the value phase later fails (constraint violation, dropped
   connection, bug), the findings are already durable and an operator sees
   *why* figures are blocked (or which groups were excluded).
2. **Values second, all-or-nothing.** All non-blocked metrics'
   `computed.metric_values` + `lineage.edges` rows commit as one unit, so a
   partial run never leaves half-written figures; a failure rolls back this
   phase only and propagates.

A single overall transaction was rejected because a failed persist would roll
the routed issues back with it — silently destroying the run's DQ evidence,
the opposite of fail-loudly. The ordering is regression-tested
(`tests/test_runner.py::test_persist_failure_does_not_roll_back_committed_dq_issues`).

## v0 semantics (documented approximation)

Trip assignment (`trip_id` present) is the revenue-service proxy; unassigned
positions are excluded; there is no deadhead handling. Distance is
position-derived haversine (trip-distance authority deferred to slice 2 per
handoff 0001).

## Verification status

### What ran (2026-07-12, handoff 0012 — NTD sampling support)

```
$ cd services/calc && python3 -m pytest tests/ -q
406 passed in 14.22s
```

(319 pre-0012 tests unchanged plus 87 new: all 48 Tables 43.01–43.07 cells
pinned one-for-one against `tests/golden/sampling_v0/expected.json`
(hand-transcribed in BASIS.md, incl. the manual's own printed Table 43.07
weekly inconsistency kept AS PRINTED), the hand-worked §83 APTL example and
by-service-day variants, the verbatim §83.05(a)/(b) quote pins + the
structural average-of-ratios-unconstructible shape test, selector
validation/guidance tests, drawer refusals + the pinned reproducibility
anchor, and Hypothesis properties: draw reproducibility, without-
replacement, frame-order independence, prefix consistency (random
oversampling soundness), APTL permutation- and merge-invariance.) LIVE
(2026-07-12): the full plan→draw→measure→estimate walkthrough ran against
the compose stack through the API — evidence in handoff 0012, "Outputs —
backend evidence".

### What ran (2026-07-12, handoff 0011 — Passenger Miles Traveled)

```
$ cd services/calc && python3 -m pytest tests/ -q
319 passed in 12.24s
```

(294 pre-0011 tests green — runner tests updated for the fourth default
metric — plus 25 new: pmt goldens incl. the verbatim Exhibit 44 worked
example, unit tests for the distance precedence/unit discipline/degenerate
inputs/estimator refusals, Hypothesis properties, and the runner
pass-through with geometry.) Live (2026-07-12): migration 0019 applied and
psql-verified; normalize_gtfs_static 0.3.0 replayed over the ingested MBTA
feed (10,309 stops / 3,077,103 stop_times / 3,200,393 lineage edges, 0
findings); `python -m headway_calc.runner --period-start 2026-07-09
--period-end 2026-07-10 --per-mode` produced an HONEST PMT REFUSAL in every
scope (missing+invalid share 0.3659 fleet-wide vs the p. 146 0.02 line —
driven by the TIDES ordinal-sequence join gap on rail/subway and the
simulated events' imbalances), with the blocking receipts, 6,494 per-trip
exclusion warnings, and zero pmt metric rows verified from a separate psql
connection and served by the live API. Full evidence: handoff 0011,
"Outputs — evidence".

```
$ cd services/calc && python3 -m pytest tests/ -q
294 passed in 12.12s
```

(245 pre-0010 tests unchanged and green, plus 49 new: sscls unit + ALL
EIGHT Example-4 goldens + Examples 6C/6E/6F/7C + the flag-space invariant
enumeration over BOTH classifier versions + the retained-0.1.0 bug pin;
ss50 unit + package + ss40-export + CLI + the classifier→generator
flow-through for single-injury Other Safety Events and zero-injury worker
assaults.) Live: migrations 0017 and 0018 applied and psql-inspected,
append-only proven by attack; realistic events POSTed through the running
API landed with their sscls_v0 classifications (verified from a separate
psql connection); `python -m headway_calc.ss50 --month 2026-07` and
`--ss40-event` ran against the live database — full evidence in handoff
0010, "Outputs — backend evidence".

### What ran (2026-07-11, Python 3.12.3, hypothesis 6.156.4)

```
$ cd services/calc && python3 -m pytest tests/ -q
........................................................................ [ 29%]
........................................................................ [ 58%]
........................................................................ [ 88%]
.............................                                            [100%]
245 passed in 11.25s
```

(185 pre-0009 tests unchanged and green — the per-mode path defaults OFF —
plus 60 new: voms unit/golden/property, mode unit/golden/property, per-mode
runner end-to-end, mr20 unit + exact-package golden.)

upt_v0 golden tests explicitly (handoff 0005, hand-worked in
`tests/golden/upt_v0/BASIS.md`):

```
$ python3 -m pytest tests/test_golden_upt.py -v
tests/test_golden_upt.py::test_golden_blocked_case_refuses_above_fta_threshold PASSED [ 25%]
tests/test_golden_upt.py::test_golden_factored_case_factors_up_at_exactly_two_percent PASSED [ 50%]
tests/test_golden_upt.py::test_golden_factored_value_within_fta_factor_bounds PASSED [ 75%]
tests/test_golden_upt.py::test_golden_blocked_case_becomes_factored_when_threshold_raised PASSED [100%]
4 passed in 0.10s
```

Coverage: everything from 0.1.0/0.2.0/0.3.0 (all prior golden
fixtures/expectations byte-identical; the 0.3.0 golden/unit/property test
bodies unchanged, now pinned to the retained `compute_vrh_v0_3` exactly as
the 0.1.0/0.2.0 suites pin `compute_vrh_v0_1`/`compute_vrh_v0_2`); NEW for
0.4.0 — trip-excision golden (three-trip block, 600 s layovers, middle trip
gapped 400 s: v0.4 keeps trips F+H at `0.17` h and drops trip G plus BOTH
adjacent layovers; retained v0.3 drops the whole block to `0.00` h; retained
v0.2 also `0.17` h — no clean-adjacent layover survives on this fixture;
default 0.95 threshold blocks at trip coverage 2/3; the CLEAN two-trip block
fixture reproduces the 0.3.0 value `0.33` h exactly under v0.4); 0.4.0 unit
tests (middle- and edge-trip excision with the far layover surviving, one
warning per excised trip citing only that trip's records, adjacent gapped
trips, a fully-excised block counting as excluded_groups, NULL-block
fallback excision keeping `block_unavailable` infos and blocks_touched=0,
lineage narrowing to included positions, the surviving-interval layover cap
still warning, trip-denominated blocking); 0.4.0 Hypothesis properties over
schedules WITH per-trip gap injection (MONOTONICITY on ARBITRARY input:
v0.4 VRH ≥ v0.2 VRH with identical lineage AND v0.4 VRH ≥ v0.3 VRH; cap 0
collapses to the v0.2 value exactly; figure monotone in the cap with exact
clean-adjacent interval accounting and one warning per over-cap
clean-adjacent interval; one telemetry_gap_excluded warning per excised trip
citing exactly that trip's records; determinism/order-independence as full
structural equality; blocking ⇔ the exact coverage threshold line over
TRIPS with blocking-implies-None retained); runner end-to-end now asserting
the vrh 0.4.0 detail JSONB (trip coverage + trips_excised/blocks_touched/
layover_intervals_dropped + layover_max_seconds). Migrations 0010+0011 are
statically asserted by `db/test_migrations_static.py`.

NEW for upt_v0 0.1.0 (handoff 0005) — golden fixture `tests/golden/upt_v0/`
(blocked case: 3 operated trips, 1 missing → share 1/3 > the FTA 2%
threshold → ONE blocking finding, value None, with the p. 151 imbalance/
negative-load defects and the NULL-count row asserted as warnings and the
all-simulated source mix as the info finding; factored case: 50 operated
trips, 49 covered → share exactly 0.02 → 98 counted × 50/49 = 100,
hand-worked in BASIS.md); upt unit tests (verified-enum counting incl. bike
exclusion, NULL-count warning + lineage exclusion, imbalance boundary
exactly-10%-passes, negative-load stop-sequence ordering with the
NULL-sequence-last convention, missing-rule boundaries at exactly 2% /
above 2% / all-missing / zero-operated degenerate, whole-boarding
ROUND_HALF_EVEN, simulated source mix); upt Hypothesis properties
(determinism and order-independence as full structural equality;
monotonicity — adding a boarding event to a covered trip never decreases
the reported UPT, and the counted base never decreases on any input, with
the documented factor-replacement exception pinned by its own test;
factor-up bounds counted ≤ reported ≤ quantize(counted/(1−0.02));
blocking ⇔ the exact p. 146 threshold line with blocking-implies-None;
lineage = counted boardings exactly, source_mix totals, NULL-count warnings
never in lineage); reader tests for `load_passenger_events` /
`load_operated_trip_ids` (contract columns, half-open UTC bounds,
deterministic order, NULL passthrough); runner end-to-end for the UPT
golden through `run_period` (factored persists with 49 lineage edges;
blocked routes info/warnings/blocking with their own severities and
persists no upt value while vrm/vrh persist independently).

NEW for the app.settings wiring (handoff 0002 Response follow-up,
2026-07-11) — `tests/test_settings.py` (`load_policy_settings`: seeded rows
→ frozen `PolicySettings` with Decimal-never-float parsing; missing table →
`None` + rollback + WARNING; missing knob row / unparseable decimal or
integer (incl. `NaN`/`Infinity`) / wrong `value_type` → typed
`SettingsError`; non-42P01 database errors propagate) and settings
precedence/provenance runner tests in `tests/test_runner.py`
(settings-govern-when-no-flag over the gapped fixture — the agency's 0.5
coverage row persists what the code default would block, sources
`"settings"`; explicit-flag-wins — sources `"explicit"`; missing table →
code defaults + `"default"` + warning; corrupt value → loud typed refusal
before ANY canonical read, no commit; the full explicit>settings>default
precedence matrix over all four knobs; `read_settings=False` /
`--ignore-settings` never queries the table and still honors explicit
flags; imbalance_threshold never `"settings"`; seeded settings reproduce
the default run exactly — determinism intact across the settings path).

NEW for handoff 0009 (mode dimension, voms_v0, MR-20 generator) — voms
golden `tests/golden/voms_v0/` (three UTC days, distinct-vehicle counts
2/3/2 → 3, exact vs partial period, peak-day lineage) and unit tests
(distinct-not-position counting, unassigned exclusion, UTC day convention,
earliest-day tie-break, empty-input zero, blocking-free, detail shape,
period refusal); voms Hypothesis properties (determinism/order-independence,
value ≡ max of daily distinct counts, adding a vehicle-day never decreases,
blocking-free with the partial-observation warning iff days are missing,
max(per-mode) ≤ fleet ≤ Σ(per-mode) with the max ≠ sum construction
pinned); mode golden `tests/golden/mode_scope/` (bus/subway/unknown; per-mode
values summing EXACTLY to the fleet values for vrm/vrh/upt) and unit tests
(bucketing, partitioning, per-mode operated-trips denominator ≡ fleet union,
zero-event mode blocks honestly, unknown-mode finding counts + 100-record
citation truncation); mode Hypothesis properties (vrh exact additivity on
the 36 s quantum grid, vrm additivity within the documented quantization
bound, upt exact additivity on fully-covered fleets with the fleet-vs-
per-mode factor divergence pinned 498 vs 500, per-mode lineage partitioning
the fleet lineage); per-mode runner end-to-end (default OFF byte-identical,
16 scoped outcomes with scope bound on every INSERT, scoped dq descriptions,
ONE unknown_mode_share info, per-scope blocking independence, determinism,
--per-mode CLI); mr20 tests (month-period rule, latest-per-metric+scope SQL
shape, EXACT package JSON golden `tests/golden/mr20/`, missing-cell
null+reason, rail-pending-D2 per the transform map, flag-derived caveats,
empty-table package, CLI boundary). Reader tests now assert the routes.mode
LEFT JOINs on both queries and NULL-mode passthrough.

### What is PENDING

- **Live re-run on the MBTA dataset (orchestrator's job)** — this increment
  was implemented and unit/golden-tested against fake connections only, per
  the working agreement. The orchestrator re-runs
  `python -m headway_calc.runner` live and compares v0.2/v0.3/v0.4 VRH over
  the same period (handoff 0004, Outputs): expected trip-level coverage
  ≈ 0.91 and VRH ≈ the v0.2 value plus layover recovered over
  clean-adjacent intervals. Handoff 0009 adds the live per-mode + voms +
  package run (`python -m headway_calc.runner --per-mode`, then
  `python -m headway_calc.mr20 --month …`) — also the orchestrator's step.
- **Reportability** — definitions are VERIFIED (tracker) and D1 is CLOSED,
  but no figure is reportable until divergences D2–D6 are addressed and
  `coverage_threshold` 0.95 is verified against FTA completeness
  expectations (`layover_max_seconds` 1800 is now data-informed and
  exhibit-aligned per the measured 2026-07-10 inter-trip distribution —
  per-agency config remains future work). The handoff-0004 open question
  (partial retention of an excised trip's layover intervals) is deferred;
  the conservative both-sides drop stands.
- **dq.issues ownership** — routing lands findings in `dq.issues` with their
  own severity via `headway_calc.dq` / `run_period`; owner assignment and the
  resolution workflow remain the DQ workflow's scope (Backend), not this
  package's. Whether excluded-group warnings auto-resolve when a later
  replay fills the gap is an open handoff-0002 question (owner: Data
  Engineer, slice 2).
- **UPT reportability** — upt_v0 definitions are VERIFIED (pp. 143/146/151
  quoted in the tracker; TIDES enum verified against the live spec repo),
  but NOT REPORTABLE: all current passenger events are simulated
  (`source = "tides_simulated"`, flagged per run), APC certification per
  pp. 147–148 is an agency workflow, and the p. 146 factor-up is fleet-wide
  in v0 (mode-awareness limitation, handoff 0005 open question). The live
  run against ingested simulator output is the orchestrator's job once
  migration 0012 + the TIDES connector land (parallel handoff-0005 work).
