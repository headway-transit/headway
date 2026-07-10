# Regulatory-Change Tracker — headway-calc

The durable memory mapping every calculation (and version) to the authoritative
source it implements. **Rule: no calculation version ships without a row here,
and no regulatory number enters code from memory** — every definition,
threshold, and rounding convention is a pointer to a published source that must
be verified against the current reporting-year guidance before implementation.
Changing calculation logic mints a new version and a new row; shipped versions
are never deleted or rewritten.

| calc_name | version | What it implements | Citation (pointer — verify, never from memory) | Verification status | Source version verified / date |
|---|---|---|---|---|---|
| vrm_v0 | 0.1.0 | Vehicle Revenue Miles approximation: haversine distance summed between consecutive vehicle positions grouped by (vehicle_id, trip_id); trip assignment used as revenue-service proxy; fail-loud telemetry-gap rule (default 300 s, explicit input); Decimal quantized 0.01 mi, ROUND_HALF_EVEN (engineering placeholder) | FTA NTD definitions of Vehicle Revenue Miles/Hours — FTA NTD Reporting Manuals (current reporting year) | PRE-VERIFICATION — walking-skeleton approximation (position-derived, trip-assignment as revenue proxy, no deadhead handling). MUST be verified against the current published FTA NTD Reporting Manual before any figure is treated as reportable. | none / not yet verified |
| vrh_v0 | 0.1.0 | Vehicle Revenue Hours approximation: time deltas summed between consecutive in-trip vehicle positions, same grouping and fail-loud gap rule as vrm_v0; Decimal quantized 0.01 h, ROUND_HALF_EVEN (engineering placeholder) | FTA NTD definitions of Vehicle Revenue Miles/Hours — FTA NTD Reporting Manuals (current reporting year) | PRE-VERIFICATION — walking-skeleton approximation (position-derived, trip-assignment as revenue proxy, no deadhead handling). MUST be verified against the current published FTA NTD Reporting Manual before any figure is treated as reportable. | none / not yet verified |
| vrm_v0 | 0.2.0 | Gap policy per handoff 0002: same distance semantics as 0.1.0, but a (vehicle_id, trip_id) group containing a gap > gap_threshold_seconds (explicit input, default 300 s) is EXCLUDED from the figure (one warning DQ finding 'telemetry_gap_excluded' per group, citing all its records); coverage = clean_groups/total_groups (clean-position share also reported) carried in the persisted detail JSONB; run refuses (ONE blocking 'coverage_below_threshold' finding, value None, nothing persisted) when coverage < coverage_threshold (explicit input, default 0.95 — an ENGINEERING PLACEHOLDER, not an FTA number); input_record_ids/lineage cover included groups only; coverage ratios quantized 0.0001 ROUND_HALF_EVEN (engineering convention); 0.1.0 retained runnable (compute_vrm_v0_1) | FTA NTD definitions of Vehicle Revenue Miles/Hours and completeness/sampling expectations — 2025 NTD Full Reporting Policy Manual (current reporting year) | DEFINITIONS VERIFIED, NOT REPORTABLE — VRM/VRH/deadhead/layover definitions verified and quoted (see "Verified definitions" below). Implementation partially aligned: divergences D1–D6 documented in the Divergence analysis; for VRM, D1 is negligible (layover miles N/A per Exhibit 35) and the nearest reportable target is bus-mode VRM pending D3/D4. coverage_threshold 0.95 remains an engineering placeholder. | 2026 NTD Policy Manual (Full Reporting), pp. 128–136 + 2025 NTD Full Reporting Policy Manual (identical text) / verified 2026-07-10 |
| vrh_v0 | 0.2.0 | Gap policy per handoff 0002: same duration semantics as 0.1.0 with per-group exclusion + coverage identical to vrm_v0 0.2.0 (warning 'telemetry_gap_excluded' per excluded group; blocking 'coverage_below_threshold' below coverage_threshold, default 0.95 — ENGINEERING PLACEHOLDER; detail JSONB with coverage/threshold provenance; lineage over included groups only); 0.1.0 retained runnable (compute_vrh_v0_1) | FTA NTD definitions of Vehicle Revenue Miles/Hours and completeness/sampling expectations — 2025 NTD Full Reporting Policy Manual (current reporting year) | DEFINITIONS VERIFIED, NOT REPORTABLE — definitions verified and quoted (see "Verified definitions"). **Material divergence D1: FTA includes layover/recovery time in VRH (Exhibit 35; typically 10–20% of running time); per-trip grouping drops it → VRH systematically undercounts.** Closure requires block-aware grouping (GTFS block_id, calc v0.3). D2 (rail passenger-car measure) also applies. coverage_threshold 0.95 remains an engineering placeholder. | 2026 NTD Policy Manual (Full Reporting), pp. 128–136 + 2025 NTD Full Reporting Policy Manual (identical text) / verified 2026-07-10 |
| vrh_v0 | 0.3.0 | Block-aware VRH per handoff 0003: a vehicle's trips sharing a GTFS block_id (canonical.trips.block_id, migration 0011; trips.txt optional field per the GTFS Schedule Reference, gtfs.org — "many sequential trips made using the same vehicle") form ONE VRH group, and the inter-trip interval is layover BY DEFINITION and INCLUDED, up to layover_max_seconds (explicit input, default 1800 s — ENGINEERING PLACEHOLDER, see below; over-cap interval NOT counted + warning 'layover_exceeds_max'). NULL-block trips fall back to per-trip grouping (0.2.0 semantics) with one info 'block_unavailable' per vehicle-day (documented undercount). Within-trip gap rule unchanged (gap_threshold_seconds, default 300 s), exclusion unit now the block group; coverage/threshold machinery unchanged over block groups (blocking 'coverage_below_threshold' below coverage_threshold, default 0.95 — ENGINEERING PLACEHOLDER); detail JSONB adds layover_max_seconds provenance; lineage covers all positions of included block groups; VRM stays 0.2.0 (layover miles N/A per Exhibit 35); 0.2.0/0.1.0 retained runnable (compute_vrh_v0_2, compute_vrh_v0_1) | FTA inclusion of layover/recovery time in VRH — 2026 NTD Policy Manual (Full Reporting), Exhibit 35 (p. 133: layover at end of route → Vehicle Revenue Hours **Yes**, miles N/A) and pp. 128–133 ("Revenue hours … include … Layover/recovery time"; "Layover time typically ranges from 10 to 20 percent of the running time" — descriptive, not a cap); already quoted under "Verified definitions" | DEFINITIONS VERIFIED — **D1 CLOSED (block-aware layover inclusion)**; NOT REPORTABLE — remaining divergences D2–D6 unchanged (rail passenger-car measure D2 foremost). ENGINEERING PLACEHOLDERS flagged: layover_max_seconds 1800 s (pending observed MBTA inter-trip layover distributions; ultimately per-agency config) and coverage_threshold 0.95 (pending FTA completeness verification). Live v0.2-vs-v0.3 comparison DONE 2026-07-10 (MBTA, 2026-07-09..11, 850,928 positions): over the identical included set (3,302 clean block groups) layover recovery = +72.56 h = **+1.4% of running time** — far below the manual's descriptive 10–20% because MBTA GTFS-RT assigns the next trip_id during layover, so per-trip grouping already captured most layover inside trip groups; D1 real but empirically small on this feed. Caveats recorded: clean-subset selection bias (vehicles dark at layover are in the excluded blocks) and the 1800 s layover cap need the observed inter-trip distribution. Naive cross-version comparison is confounded (block-level exclusion: 802/4,104 groups → coverage 0.8046 vs per-trip 0.9122; v0.4 candidate: excise only the gapped trip + adjacent layovers instead of the whole block — open design question, owner NTD role). | 2026 NTD Policy Manual (Full Reporting), pp. 128–136 + 2025 NTD Full Reporting Policy Manual (identical text) / verified 2026-07-10; GTFS Schedule Reference trips.txt block_id (gtfs.org) / verified 2026-07-09 |
| vrh_v0 | 0.4.0 | Trip-level excision per handoff 0004: grouping and layover accounting UNCHANGED from 0.3.0 (block-aware; NULL-block per-trip fallback + info 'block_unavailable' per vehicle-day; inter-trip interval is layover BY DEFINITION, included up to layover_max_seconds, default 1800 s — see status; over-cap interval NOT counted + warning 'layover_exceeds_max'), but the EXCLUSION UNIT is refined from the block group to the gapped trip plus its adjacent layover intervals: a within-trip gap (> gap_threshold_seconds, default 300 s) excises ONLY that trip's running time and the inter-trip layover intervals immediately adjacent to it (both sides, where present — a layover interval counts only when BOTH bounding trips are clean; an excised trip is never bridged); the block's remaining clean trips and their other layover intervals stay in the figure; one warning 'telemetry_gap_excluded' PER EXCISED TRIP citing that trip's records. Coverage returns to TRIP denomination: clean_trips/total_trips (directly comparable to 0.2.0's group coverage; blocking 'coverage_below_threshold' below coverage_threshold, default 0.95 — ENGINEERING PLACEHOLDER); detail JSONB carries the trip coverage, the block statistics (blocks_touched, trips_excised, layover_intervals_dropped) and all three thresholds; lineage covers INCLUDED positions only (excised trips' records cited by their findings); VRM stays 0.2.0; 0.3.0/0.2.0/0.1.0 retained runnable (compute_vrh_v0_3, compute_vrh_v0_2, compute_vrh_v0_1) | Exhibit 35 BOTH directions — 2026 NTD Policy Manual (Full Reporting), p. 133: layover at end of route → Vehicle Revenue Hours **Yes** (inclusion, as 0.3.0), AND "Bus arrives at the end of the route, parks, and goes out of service… → Vehicle Revenue Hours: **No**" (out-of-service exclusion — the justification for capping long inter-trip intervals); pp. 128–133 ("Revenue hours … include … Layover/recovery time"; "Layover time typically ranges from 10 to 20 percent of the running time" — descriptive, not a cap); measured MBTA inter-trip interval distribution (2026-07-10, 7,400 in-block intervals): p50 = 30 s, p90 = 109 s, p99 = 7,124 s, 2.7% > 1,800 s, 49 negative overlaps — the long tail is out-of-service parking | DEFINITIONS VERIFIED — D1 remains CLOSED (layover inclusion retained); NOT REPORTABLE — remaining divergences **D2–D6 unchanged** (rail passenger-car measure D2 foremost). layover_max_seconds 1800 s is now **data-informed and exhibit-aligned** (the measured distribution shows 97.3% of in-block intervals under the cap and a long tail of out-of-service parking that Exhibit 35 excludes), **per-agency configurable** — no longer a bare placeholder, still not an FTA-published number. coverage_threshold 0.95 remains an ENGINEERING PLACEHOLDER (pending FTA completeness verification). Open question (handoff 0004): partial retention of an excised trip's layover intervals when the gap is provably outside the layover-adjacent running segments — deferred; the conservative both-sides drop stands. Live v0.2/v0.3/v0.4 re-run on the MBTA dataset PENDING — orchestrator (expected: trip-level coverage ≈ 0.91; v0.4 ≥ v0.2 and v0.4 ≥ v0.3 on identical input — property-tested). | 2026 NTD Policy Manual (Full Reporting), pp. 128–136 + 2025 NTD Full Reporting Policy Manual (identical text) / verified 2026-07-10; MBTA inter-trip interval distribution measured 2026-07-10 (handoff 0004) |
| upt_v0 | 0.1.0 | Unlinked Passenger Trips per handoff 0005: deterministic sum of `event_count` over TIDES boarding events (`event_type = "Passenger boarded"`, verified enum — see citation; bike boardings are NOT passengers per the p. 143 definition) with a trip assignment (`trip_id` from `trip_id_performed` — the same revenue-service proxy as vrm/vrh, documented approximation); NULL `event_count` contributes 0 + one warning `apc_null_count` citing the record (never coalesced to the TIDES default 1); p. 151 validations AS QUOTED: per-trip \|boardings−alightings\| > imbalance_threshold × boardings (explicit input, default 0.10 — the manual's example figure) → warning `apc_count_imbalance`; running load (ordered by trip_stop_sequence then event_timestamp, NULL sequence last — documented convention) dropping below zero → warning `apc_negative_load`; **missing-trip rule (p. 146)**: operated trips (SELECT DISTINCT trip_id FROM canonical.vehicle_positions over the period) with zero passenger events are missing; missing/operated ≤ missing_trip_threshold (explicit input, default 0.02 — **a REAL FTA threshold, not a placeholder**; exact comparison, never the quantized share) → deterministic factor-up UPT = counted × operated/(operated−missing) from the exact fraction, quantized to whole boardings (Decimal 1, ROUND_HALF_EVEN — engineering rounding convention, the manual prescribes none), factor + inputs in detail JSONB; share > threshold → ONE blocking `apc_missing_trips_above_fta_threshold`, value None (statistician approval is a human workflow); simulated-source rule (handoff 0005): any `source != "tides"` → ONE info `simulated_source_data`, source_mix always in detail; lineage over counted boarding events only | UPT definition — 2026 NTD Policy Manual (Full Reporting) p. 143 ("Unlinked Passenger Trips (UPT) are the number of boardings…"); missing-trip 2% rule — p. 146; APC validation examples — p. 151 (all quoted under "Verified definitions — UPT" below); TIDES `event_type` enum — TIDES-transit/TIDES `spec/passenger_events.schema.json`, main branch (repo HEAD `7ddaa7ab820eeca1cc7a681ba9ae79a72ba10af1`, schema file last changed `d887d42ce081f3fb6155664a3c486101d62ec52b` 2023-12-11), verified 2026-07-10 | DEFINITIONS VERIFIED (p. 143/146/151 quoted below; TIDES enum verified against the live spec repo) — **NOT REPORTABLE**: (1) all current passenger events are SIMULATED (`source = "tides_simulated"`; every consuming run carries the `simulated_source_data` info finding — a certifiable figure containing simulated records is a contradiction); (2) APC use for NTD reporting requires FTA approval/benchmarking per pp. 147–148 (±5% vs manual counts, discard rate < 50%, next benchmarking RY 2028) — an agency workflow outside calc logic; (3) factor-up is FLEET-WIDE in v0, not per mode/TOS (handoff 0005 open question — mode-awareness increment, owner NTD role); (4) the p. 149 sampling floor (95% confidence, ±10% precision) is a future sampling path, unused here | 2026 NTD Policy Manual (Full Reporting), pp. 143–151 (PDF pp. 161–169) / verified 2026-07-10; TIDES passenger_events schema (github.com/TIDES-transit/TIDES) / verified 2026-07-10 |

## Verified definitions — FTA NTD Policy Manual (verified 2026-07-10)

Source: **2026 NTD Policy Manual, Full Reporting** (`docs/reference/National Transit Database 2026 Policy Manual_ Full Reporting.pdf`), chapter "Service Data Requirements" → "Service Supplied", manual pp. 128–136 (PDF pp. 146–154), including Exhibits 35–37 (worked miles/hours truth tables for bus, demand-response, and rail). Cross-checked against the **2025 NTD Full Reporting Policy Manual** (`docs/reference/2025 NTD Full Reporting Policy Manual.pdf`, manual pp. ~126–134, PDF pp. 144–152): all key definitional sentences are textually identical across the two reporting years.

Exact quotes (2026 manual):

- **Revenue Service** (p. 128): "A transit vehicle is in revenue service when it is providing public transportation and is available to carry passengers. Non-public transportation activities, such as exclusive school bus service and charter service are not considered revenue service. Revenue service includes both fare and fare-free services."
- **VRM/VRH** (p. 128): "Actual Vehicle Revenue Hours (VRH) and Actual Vehicle Revenue Miles (VRM) are the hours and miles vehicles travel while in revenue service. Revenue hours for conventional scheduled services include the following: • Running time • Layover/recovery time." And: "Revenue miles include the distances traveled during running time and layover/recovery time."
- **Layover** (p. 128): "Usually, agencies schedule layover/recovery time at the end of each trip. … Layover time typically ranges from 10 to 20 percent of the running time."
- **Exclusions** (p. 129): "VRM and VRH exclude the miles and hours related to the following: • Deadhead time • Operator training • Maintenance testing • Other non-revenue uses of the vehicles."
- **Rail measures** (p. 129): "There are two different types of measures of VRH and VRM for rail service: train revenue hours/miles and passenger car revenue hours/miles. … a train with four passenger cars traveling one mile would be four passenger car revenue miles."
- **Demand Response** (p. 129): "For DR service, revenue time includes all travel time from the point of the first passenger pick-up to the last passenger drop-off, as long as the vehicle does not return to the garage or dispatching point or have interruptions in service…"
- **Deadhead** (p. 129): "When transit vehicles are 'deadheading,' they operate closed door and do not carry passengers. Deadhead includes … Leaving or returning to the garage or yard facility …; Changing routes; When the driver does not have the duty to carry passengers."
- **Accuracy requirement** (p. 135): "Transit agencies must report accurate, true statistics for VRM (i.e., no estimates)."
- **Exhibit 35** (p. 133, bus): layover at end of route → Vehicle Revenue Hours **Yes** (miles N/A); route operated with no passengers boarding → revenue **Yes**; all deadhead legs → revenue **No**.
- **Exhibit 35, out-of-service row** (p. 133, bus; verified for calc vrh_v0 0.4.0, handoff 0004): "Bus arrives at the end of the route, parks, and goes out of service… → Vehicle Revenue Hours: **No**" — the exhibit-side justification for capping long inter-trip intervals (`layover_max_seconds`): the measured long tail of in-block intervals is out-of-service parking, not layover.

## Verified definitions — UPT (calc upt_v0, handoff 0005; verified 2026-07-10)

Source: **2026 NTD Policy Manual, Full Reporting**
(`docs/reference/National Transit Database 2026 Policy Manual_ Full
Reporting.pdf`), chapter "Service Data Requirements" → "Service Consumed" and
"Collecting Service Consumed Data", manual pp. 143–151 (PDF pp. 161–169).

Exact quotes (2026 manual):

- **UPT definition** (p. 143): "Unlinked Passenger Trips (UPT) are the number
  of boardings on public transportation vehicles during the fiscal year.
  Transit agencies must count passengers each time they board vehicles, no
  matter how many vehicles they use to travel from their origin to their
  destination. If a transit vehicle changes routes while passengers are
  onboard (interlining), transit agencies should not recount the passengers.
  Employees or contractors on transit agency business are not passengers."
- **100% counts / missing-trip rule** (p. 146): "Sometimes transit agencies
  performing 100 percent counts will miss passenger counts on some vehicle
  trips because of personnel problems or equipment failures. If these vehicle
  trips are 2 percent or less of the total, transit agencies should factor up
  the data to account for the missing trips. However, if the vehicle trips
  with missing data exceed 2 percent of total trips, agencies must have a
  qualified statistician approve the factoring method used to account for the
  missing percentage." — the calc's `missing_trip_threshold` default 0.02 is
  this REAL FTA threshold (NOT an engineering placeholder); above it the calc
  refuses (blocking `apc_missing_trips_above_fta_threshold`) because the
  statistician approval is a human workflow.
- **APC validation examples** (p. 151): "First, develop processes to throw
  out any trips with invalid APC data. … For example, agencies may flag trips
  or blocks where the difference between boardings and alightings is greater
  than 10 percent, or trips where the passenger load drops below zero." —
  implemented as the `apc_count_imbalance` (default `imbalance_threshold`
  0.10, the manual's example figure) and `apc_negative_load` warnings.
- **APC certification** (pp. 147–148): "The use of APCs for NTD reporting
  requires FTA approval." … "FTA will only certify APC systems for NTD
  reporting if the percent difference between manual and APC data in the
  sample, for both UPT and PMT, is less than 5 percent." … "FTA will also
  only certify APC systems if the proportion of trips without valid APC data
  (the discard rate) is less than 50 percent of the number of trips on
  APC-equipped vehicles." "The next benchmarking year is Report Year (RY)
  2028." — recorded for context; certification is an agency workflow, not
  calc logic.
- **Sampling floor** (p. 149): "Minimum confidence of 95 percent; and
  Minimum precision level of ±10 percent." — future sampling-path
  parameters, not used by upt_v0.

TIDES event vocabulary: `event_type` enum verified 2026-07-10 against
TIDES-transit/TIDES `spec/passenger_events.schema.json` (main branch — repo
HEAD `7ddaa7ab820eeca1cc7a681ba9ae79a72ba10af1`; the schema file's last
change is commit `d887d42ce081f3fb6155664a3c486101d62ec52b`, 2023-12-11). The
enum contains exactly 16 values; the passenger boarding/alighting values are
verbatim **"Passenger boarded"** and **"Passenger alighted"** (the bike
variants "Individual bike boarded"/"Individual bike alighted" are not
passengers under the p. 143 definition and are never counted).
`event_count` is "Count for this event, e.g., 3 for a Passenger Boarding
event with 3 boardings, default is `1`" — the canonical contract nevertheless
preserves NULL as NULL, and the calc warns (`apc_null_count`) and counts 0
rather than silently applying the schema default.

## Divergence analysis — calc 0.2.0 vs. verified definitions (2026-07-10)

Definitions are now VERIFIED; the implementation is **partially aligned**, with these enumerated divergences blocking reportability:

| # | Divergence | FTA rule (verified) | calc 0.2.0 behavior | Impact / closure path |
|---|---|---|---|---|
| D1 | **Layover/recovery time** | INCLUDED in VRH (Exhibit 35; "typically 10 to 20 percent of running time") | Grouping by (vehicle_id, trip_id) drops time between trips → layover largely uncounted | **VRH systematically undercounts, plausibly 10–20%.** Closure: block-aware grouping via GTFS `block_id` (schema extension to canonical.trips + new calc version; requires handoff). VRM impact negligible (layover miles N/A). |
| D2 | **Rail passenger-car measure** | Rail VRM/VRH reported per passenger car (4-car train × 1 mi = 4 car-mi); CR/AR exclude locomotives | Counts each GTFS-RT vehicle (trainset) once | **Rail undercounted by consist size.** GTFS-RT carries no consist data. Closure: consist/AVL source or scope reportability to bus modes (MB/CB/RB) until then. |
| D3 | **Revenue-service proxy** | In revenue service = providing public transportation and available to carry passengers; deadhead/training/maintenance excluded | trip_id-assignment used as proxy; excludes unassigned movement | Sound for typical GTFS-RT practice (deadhead unassigned), but agency practice varies; "not available to board despite operating" edge cases (cf. Exhibit 37 rail row) unhandled. Documented residual risk; mitigate per-agency at onboarding. |
| D4 | **Measurement fidelity** | "accurate, true statistics … no estimates" (p. 135) | Haversine between 30 s position samples chord-cuts curves → slight understatement | Position-derived is measurement, not estimation, but fidelity must be validated against odometer/shape distance (slice-2 AVL-vs-odometer conflict work feeds this). |
| D5 | **Demand-response definition** | DR revenue time = first pick-up → last drop-off (different rule) | Not implemented | Out of scope for fixed-route calc; DR calc is its own future version. |
| D6 | **Excluded activities** | Charter/school/training/maintenance excluded | Excluded only insofar as they carry no trip_id | Covered by D3 proxy caveat. |

**Reportability position:** no 0.x figure is reportable. The nearest reportable target is **bus-mode VRM** (D1 negligible for miles, D2 bus-exempt), pending D3 per-agency confirmation and D4 fidelity validation. VRH requires D1 closure (block-aware v0.3) first.

## Open verification items (owner: NTD & Compliance Engineer)

- Revenue-service inclusion and deadhead exclusion for VRM/VRH: verify against
  the current published FTA NTD Reporting Manual for the applicable reporting
  year; record the manual version and verification date here before minting
  any post-v0 version.
- Rounding/unit conventions for reportable VRM/VRH: v0's 0.01 quantum with
  ROUND_HALF_EVEN is an explicit engineering placeholder, not a verified FTA
  convention — verify and cite before reportability.
- Trip-distance authority (shape-based vs position-derived) is deferred to
  slice 2 per handoff 0001; v0 uses position-derived haversine, flagged here
  and in the calc docstrings.
- ~~2025 NTD Full Reporting Policy Manual access~~ **RESOLVED 2026-07-10**:
  both the 2025 and 2026 Full Reporting Policy Manuals were supplied to
  `docs/reference/` and the VRM/VRH/deadhead/layover definitions are quoted
  above with page citations. Definitions VERIFIED; reportability now gated on
  the enumerated divergences D1–D6 (see Divergence analysis), not on source
  access.
- ~~D1 — block-aware VRH (layover inclusion)~~ **CLOSED (calc vrh_v0 0.3.0,
  handoff 0003)**: GTFS `block_id` landed in canonical.trips (migration 0011,
  transform 0.2.0 parses/upserts it) and vrh_v0 0.3.0 groups per block,
  including inter-trip layover up to `layover_max_seconds` (1800 s default —
  an ENGINEERING PLACEHOLDER pending observed layover distributions;
  ultimately per-agency config). Residual undercount remains exactly where
  `block_id` is absent in the feed (documented per run via `block_unavailable`
  info findings). Live v0.2-vs-v0.3 MBTA comparison (sanity check against the
  manual's 10–20% description) PENDING — orchestrator.
- ~~layover_max_seconds 1800 s placeholder~~ **RESOLVED as data-informed
  (calc vrh_v0 0.4.0, handoff 0004)**: the MBTA inter-trip interval
  distribution was measured 2026-07-10 (7,400 in-block intervals: p50 =
  30 s, p90 = 109 s, p99 = 7,124 s, 2.7% > 1,800 s, 49 negative overlaps).
  The long tail is out-of-service parking, which Exhibit 35 excludes from
  revenue hours — the 1,800 s default is therefore data-informed and
  exhibit-aligned, per-agency configurable; it is still not an FTA-published
  number.
- **Trip-excision open question (handoff 0004, owner: NTD role)**: whether an
  excised trip's layover intervals could be PARTIALLY retained when the gap
  is provably outside the layover-adjacent running segments — deferred; the
  conservative both-sides drop stands for 0.4.0.
- **Live v0.2/v0.3/v0.4 comparison (orchestrator)**: re-run on the MBTA
  dataset pending — expected trip-level coverage ≈ 0.91 and VRH ≈ the v0.2
  value plus layover recovered over clean-adjacent intervals.
- **D2 — rail passenger-car measure**: needs consist data not present in
  GTFS-RT; until available, scope reportability to bus modes.
- **coverage_threshold default (0.95)**: an engineering placeholder chosen for
  calc 0.2.0's certifiability line, NOT an FTA number. FTA
  completeness/sampling expectations must be verified against the current NTD
  Policy Manual before this default is treated as more than a placeholder;
  ultimately per-agency configuration (handoff 0002 open question, owner: NTD
  role, then Backend for the config surface).
- **upt_v0 mode-awareness (handoff 0005 open question, owner: NTD role)**:
  the p. 146 factor-up is applied FLEET-WIDE in v0; the manual speaks of
  totals per mode/TOS. Revisit at the mode-awareness increment (requires mode
  attribution on trips).
- **upt_v0 reportability gates**: (1) simulated-only data — every current
  passenger event carries `source = "tides_simulated"` and each consuming run
  emits the `simulated_source_data` info finding; (2) APC certification per
  pp. 147–148 (FTA approval, ±5% benchmarking vs manual counts, discard rate
  < 50%, next benchmarking RY 2028) is an agency workflow that must exist
  before any APC-derived UPT is reportable; (3) the p. 149 sampling floor
  (95% confidence, ±10% precision) applies only if the 100%-count path is
  abandoned — not implemented.
