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

| sscls_v0 | 0.1.0 | Safety & Security major-event classifier per handoff 0010: pure deterministic safety.events→classification ('major' \| 'non_major' \| 'not_reportable') implementing Exhibit 5 (p. 16) and the p. 17 rules AS QUOTED in "Verified — Safety & Security reporting" below. Mode-dependent (rail vs non-rail per the event's AGENCY-SUPPLIED mode — Predominant Use Rule p. 15 applied by the enterer, never inferred; rail-ness via the transform's GTFS route_type→mode map, an ENGINEERING mapping): fatality (≥1, all modes — confirmed within 30 days, incl. suicides); injury ≥1 immediate-transport (NON-RAIL incl. ferry, per the tracker label "(non-rail/ferry)" — documented interpretation); property damage ≥ $25,000 exact Decimal (NON-RAIL); rail serious-injury flag (quoted criteria); rail substantial-damage flag (quoted criteria); rail-to-rail collision automatically reportable (Example 4B); assault with transit-vehicle contact evaluated as collision (Scenario E — explanation note, never a threshold); evacuation_life_safety → major (any mode) and rail derailment by category → major — BOTH conditions encoded by the handoff-0010 schema design with the p. 17 verbatim quotes PENDING (flagged in each citation); cyber + substantial_damage → major (Scenario G). ≥1 threshold met = ONE report (p. 14; structural DB CHECK: 'major' ⇔ thresholds_met non-empty). No threshold met → S&S-50 non-major scope per p. 3 (injury-threshold events; non-major fires; assaults on a transit worker, injury NOT required) else not_reportable. NULL property damage = not assessed, NEVER $0, never meets the threshold. RUNAWAY-TRAIN rule NOT implemented (no capture field in the binding schema; no quoted condition). Sole writer of safety.event_classifications (migration 0017, append-only). Goldens: Example 4 scenarios A/B/E/G hand-worked from the documented outcomes; C/D/F/H SKIPPED pending quote extraction | 2026 S&S Policy Manual V1, Exhibit 5 p. 16 + pp. 14–19 — EXACTLY as quoted in "Verified — Safety & Security reporting (verified 2026-07-12)" below; no regulatory number entered from memory | DEFINITIONS VERIFIED (quoted below), NOT REPORTABLE — open items, owner NTD role: (1) verbatim p. 17 collision/evacuation/derailment/runaway rule text must be quoted here (evacuation/derailment conditions currently carry a PENDING-quote caveat; runaway unimplemented); (2) the "(non-rail/ferry)" injury-threshold and "(non-rail)" damage-threshold mode-grouping interpretation must be confirmed against Exhibit 5's layout; (3) Example 4 scenarios C/D/F/H outcomes must be quoted before their goldens can exist; (4) no tow-away threshold implemented (towed is a supporting field for rail substantial damage only) pending a verbatim quote; (5) CR/AR per-mode nuances are flagged in ss50 output, not applied. **[Superseding note, 2026-07-12, same day: the "S&S addendum" second/third passes closed items (1), (3) and (4) and found a behavioral bug — single-injury Other Safety Events over-classified as major (p. 22). Fixed in sscls_v0 0.1.1 (next row); 0.1.0 retained runnable as `classify_event_v0_1_0` so live rows classified under it stay reproducible. This status text stands unedited as history.]** | 2026 Safety & Security Policy Manual V1, pp. 3–19 / verified 2026-07-12 (S&S section below) |
| sscls_v0 | 0.1.1 | Correction round per the "S&S addendum" (second pass, pp. 17–22) and "S&S addendum 2" (third pass, pp. 21–27) sections below — same classifier surface as 0.1.0 plus: **(a) BUG FIX — Other Safety Events exception (p. 22):** events that are NOT collisions/fires/security/hazmat/acts-of-God/derailments (in Headway's vocabulary: effective categories 'evacuation' and 'other') meet the injury threshold only at TWO or more injured persons (any mode — Example 4D is rail); a single immediate-transport injury with no other threshold is NON-major with basis `other_safety_event_single_injury` ("reported on the Non-Major Summary Report" — flows to the ss50 generator's injury counts); 0.1.0 over-classified these as major. **(b)** Rail collisions meet "an injury … threshold" at ONE immediate-transport injury (p. 17; Example 4C). **(c)** Non-rail collision tow-away threshold `collision_towaway` (p. 17: "Involve a transit revenue vehicle and the towing away of any vehicles (transit or non-transit) from the scene"). **(d)** Rail collision at a grade crossing/intersection → `rail_collision_grade_crossing` (p. 17). **(e)** Rail vehicle-contact assault/homicide reportable with NO injury → `rail_collision_vehicle_contact_assault` (p. 17); non-rail keeps the "resulting in an injury or fatality" qualifier via the ordinary thresholds. **(f)** `runaway_train` (rail; migration-0018 field; p. 17 verbatim definition). **(g)** `rail_evacuation_to_row` (rail; migration-0018 field; p. 17: evacuations to controlled rail ROW incl. self-evacuations, platform excluded except life safety); evacuation_life_safety now cites the verbatim non-rail rule. **(h)** Derailment cites the verbatim rule (mainline + yard + non-revenue). **(i)** Rail serious injury: verbatim p. 21 criteria, automatically reportable, transport NOT required ("may or may not have been transported") — flag-triggered independent of the injuries count, inert on non-rail (Example 6C asymmetry golden). **(j)** Rail collision with any vehicle towed away IS substantial damage (Example 7C, p. 27) — mechanical even when the flag is unset; p. 25 substantial-damage exclusions and the p. 25 property-damage summing rule (all involved property + wreckage clearing, Example 7A) are entry-form hints, never silent logic, as are the p. 20 fatality nuances and p. 22 injury exclusions. Goldens: ALL EIGHT Example 4 scenarios (A–H) + Examples 6C/6E/6F/7C hand-worked from the verbatim solutions. Known vocabulary gap (open question, owner NTD role): hazmat spills / acts of God have no category and would arrive as 'other', wrongly receiving the two-injury exception — flagged in the API field hint. "Involve an individual" (rail collisions) has no dedicated field (in practice captured via injury/fatality — Example 4C); Example 7B rescue-train dispatch is captured via the substantial_damage flag's "rescue" wording. 0.1.0 retained runnable | 2026 S&S Policy Manual V1 — "Verified — Safety & Security reporting", "S&S addendum — verbatim rules for sscls" (pp. 17–22) and "S&S addendum 2 — damage + injury definitions verbatim" (pp. 21–27) below; no regulatory number entered from memory | DEFINITIONS VERIFIED (verbatim quotes below), NOT REPORTABLE as a submission (no NTD-portal e-filing; CR/AR nuances flagged in ss50 output, not applied). Open items, owner NTD role: (1) 'hazmat'/'act_of_god' category vocabulary increment (see gap above); (2) "(non-rail/ferry)" Exhibit 5 layout confirmation for the injury/damage threshold grouping (unchanged from 0.1.0); (3) "Involve an individual" capture field | 2026 Safety & Security Policy Manual V1, pp. 3–27 / verified 2026-07-12 (three passes; S&S sections below) |

| voms_v0 | 0.1.0 | Monthly Vehicles Operated in Maximum Service per handoff 0009 (PRE-VERIFICATION approximation): per mode (and fleet-wide), the **maximum over service days of the count of distinct vehicles observed in revenue service** (positions with a trip assignment — the same revenue-service proxy as vrm/vrh) that day; **day = the UTC calendar date of the position's event time** (documented v0 convention, NOT an agency service day); integer value, unit 'vehicles'; detail JSONB {days_observed, days_in_period, peak_day (EARLIEST day attaining the maximum — deterministic tie-break), per_day_counts {min, max, mean-as-string (0.0001 ROUND_HALF_EVEN)}}; lineage over the peak day's in-trip records only. **BLOCKING-FREE by design — the coverage machinery does NOT apply**: vrm/vrh SUM over telemetry (a gap corrupts the summed figure), but VOMS is a MAX of daily distinct-vehicle counts — a within-day gap cannot inflate the count and missing telemetry can only lower a day's count or drop a day, i.e. understate a maximum, never overstate it; the potential undercount is surfaced as ONE warning 'voms_partial_observation' whenever days_observed < days_in_period (empty input = observed maximum 0 + the warning, never a guess). Runs on the runner's --per-mode (MR-20) path: fleet scope 'agency' + per-mode scope 'mode:<mode>' rows | Monthly VOMS — 2025 NTD Monthly and Weekly Reference Policy Manual, Form MR-20, p. 33 (quoted verbatim): "VOMS is the number of revenue vehicles/passenger cars operated to meet the maximum service requirement during the month of service reported. VOMS excludes atypical days or one-time special events." | PRE-VERIFICATION, NOT REPORTABLE — documented divergences: **(a)** "maximum service requirement" is schedule-peak SIMULTANEITY; the day-level distinct-vehicle max counts every vehicle used at any point of the peak day and is therefore an UPPER-BOUND proxy — verify against the Policy Manual VOMS section before any figure is treated as reportable; **(b)** the p. 33 atypical-day / one-time-special-event exclusion is NOT implemented (needs an agency calendar policy — open question, owner NTD role); **(c)** rail VOMS counts passenger cars; GTFS-RT carries one vehicle per trainset (existing divergence D2 — rail modes non-reportable pending consist data). | 2025 NTD Monthly and Weekly Reference Policy Manual (`docs/reference/2025 NTD Mthly-Wkly-Ref-Manual_20250828.pdf`), p. 33 / verified 2026-07-11 |

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

## Verified — Monthly Ridership form MR-20 (verified 2026-07-11)

Source: **2025 NTD Monthly and Weekly Reference Policy Manual** (`docs/reference/2025 NTD Mthly-Wkly-Ref-Manual_20250828.pdf`), "Monthly Ridership Reporting (Form MR-20)", manual pp. 32–33.

- **The four MR-20 data points, quoted (p. 32):** "The MR-20 form requires agencies to report the following data points: • Unlinked Passenger Trips (UPT) • Actual Vehicle (Passenger Car) Revenue Hours • Actual Vehicle (Passenger Car) Revenue Miles • Vehicles Operated in Annual Maximum Service (VOMS)".
- **Per-mode reporting (p. 32):** "Full Reporters must report Monthly Ridership data for each mode of public transportation service that the agency operates … required to report on all modes reported on an agency's P-20 form."
- **Monthly sampling relief (p. 32):** monthly UPT via the agency's annual sampling procedure "may not meet FTA's confidence and precision levels for annual data (±10 percent precision for a 95 percent confidence level) but does meet FTA's requirements for reporting monthly data on the … MR-20."
- **Monthly VOMS (p. 33):** "VOMS is the number of revenue vehicles/passenger cars operated to meet the maximum service requirement during the month … excludes atypical days or one-time special events"; explicitly may differ from annual S-10 VOMS (month vs fiscal-year window).
- **Bonus — WE-20 weekly form (p. 34):** sampled agencies report a reference week (second full week of the month) of weekday 5-day UPT + VRM, due seven business days after the reference week ends.

**Implications for Headway (gap list to a real MR generator):**
1. **Per-mode is mandatory** — our calcs are fleet-wide (documented limitation since handoff 0005); mode dimension (from canonical.routes.mode) must flow into grouping + metric_values scope before an MR-20 package is honest. This supersedes "field format" as the primary gap.
2. **VOMS is a missing calc** — monthly max vehicles in service (computable from canonical.vehicle_positions: peak distinct vehicles in revenue service, atypical-day exclusion needs a policy rule) → new calc + tracker row.
3. Our UPT/VRM/VRH map 1:1 to the other three fields (with all existing divergence caveats D1–D6 still governing reportability).

## Mode scoping (2026-07-11) — handoff 0009

MR-20 requires the four data points **per mode** (p. 32, quoted above), so
the calc library gained a mode dimension. This section documents it; the
existing calc rows above are deliberately NOT edited.

- **No version bump — input selection, not a semantics change.** The
  per-mode paths (`headway_calc.mode`: `compute_vrm_by_mode`,
  `compute_vrh_by_mode`, `compute_upt_by_mode`, `compute_voms_by_mode`)
  partition the run's input rows by mode and apply the UNCHANGED, shipped
  calc versions to each subset — byte-for-byte the same math as the
  fleet-wide run, exactly as running a calc over a different period is not a
  new version. vrm_v0 stays 0.2.0, vrh_v0 stays 0.4.0, upt_v0 stays 0.1.0,
  voms_v0 is 0.1.0. Under the versioning rule ("changing calculation logic
  mints a new version"), no calculation logic changed; what changed is WHICH
  rows are selected as input, and that selection is recorded per row in
  `computed.metric_values.scope`.
- **Scope encoding — no migration.** Mode-scoped rows carry
  `scope = 'mode:<mode>'` in the existing handoff-0001 `scope` column (TEXT,
  default 'agency'); fleet-wide rows keep `scope = 'agency'` unchanged (full
  backward compatibility — existing goldens untouched).
- **Mode source.** `canonical.routes.mode` LEFT JOINed onto every position
  and passenger event via `canonical.trips` (reader, handoff 0009). The mode
  vocabulary is the transform's GTFS route_type→mode map
  (`headway_transform.gtfs_static.ROUTE_TYPE_TO_MODE`, cited to gtfs.org in
  that module).
- **The 'unknown' bucket — never dropped, never guessed.** A NULL mode
  (unassigned row, unknown trip, or unknown route) buckets as
  `mode:unknown`, is computed like any other bucket, and is surfaced as ONE
  info finding per per-mode run (`unknown_mode_share`, routed under the
  identity `mode_dimension 0.1.0` — a run-level input-selection note, not a
  calculation; citations truncate at 100 records, full counts always
  stated).
- **Findings per scope.** Mode-scoped runs route their findings to
  dq.issues exactly like fleet runs, the description naming the scope; the
  structural guardrail (blocking findings ⇒ no metric_values row) holds PER
  SCOPED RESULT — a gapped mode blocks only its own scope. A finding over
  the same records may therefore appear once for 'agency' and once per
  affected mode scope — deliberate: each row documents a different figure.
- **upt_v0 factor-up note.** On the per-mode path the p. 146 factor-up
  applies PER MODE (mode-average boardings; each mode's operated-trips
  denominator derives from the same loaded positions) — closer to the
  manual's per-mode/TOS totals than the documented fleet-wide factor of the
  'agency' row (upt_v0 row above, limitation (3); property-pinned: fleet
  and per-mode sums legitimately differ when trips are missing, and a mode
  whose own missing share exceeds 2% blocks even when the fleet share does
  not). The 'agency' row's behavior is unchanged.
- **Additivity.** vrm/vrh/upt are additive across the mode partition
  (golden-pinned exact sums; property-tested with the quantization bound
  made explicit — each figure quantizes once, so independently quantized
  per-mode figures may drift from the fleet figure by at most half a
  quantum each). **voms is NOT additive**: modes may peak on different days,
  so only max(per-mode) ≤ fleet ≤ Σ(per-mode) holds (property-pinned).
- **Runner surface.** `run_period(..., per_mode=True)` /
  `python -m headway_calc.runner --per-mode` (default OFF — pre-0009
  behavior byte-identical); the per-mode path also runs voms_v0 (fleet +
  per mode). The MR-20 generator (`python -m headway_calc.mr20 --month
  YYYY-MM [--run]`) consumes the persisted rows — latest per
  metric+scope+period — and emits the NOT-REPORTABLE preview package
  (banner + programmatically enumerated caveats: flag-derived +
  missing-cells + the fixed D1–D6 list; missing cell = explicit null +
  reason; rail modes per the route_type map flagged
  non_reportable_pending_d2).

## Verified — Safety & Security reporting (verified 2026-07-12)

Source: **2026 Safety & Security Policy Manual V1** (`docs/reference/2026 Safety & Security Manual V1.pdf`), pp. 3–19 read; **2025 S&S Manual V1-1** also on file for cross-reference.

- **The five forms (Exhibit 1, p. 3):** S&S-20 CEO Certification (all Full Reporters); S&S-30 Security Configuration (all); S&S-40 Major Event Report (safety events: all except Commuter Rail/Alaska Railroad modes; security events: all); S&S-50 Non-Major Monthly Summary (all; "CR and AR modes must only report non-major assaults on a transit worker").
- **Reporting cycle (p. 4):** "The S&S reporting module covers the 12-month calendar year" (may differ from fiscal year); all 2026 data due January 31, 2027; prior year editable "until the end of April the following calendar year."
- **S&S-40 timing (Exhibit 2, p. 4):** "due no later than 30 days after the date of the event."
- **S&S-50 timing (p. 4 + Exhibit 3, p. 5):** submitted "for each mode and TOS … every month, **even if no event occurs**"; due end of the following month (January→Feb 28 … December→Jan 31).
- **S&S-30 (p. 8):** one per mode/TOS, due Feb 28; seven security-configuration types (Exhibit 4).
- **S&S-20 (p. 7):** CEO completes by end of February; auto-tallies only SUBMITTED reports; "Once submitted, agencies cannot resubmit"; Submit gated until every S&S-30/50 is closed and no S&S-40 is Open/Returned/Submitted.
- **Major-event thresholds (Exhibit 5, p. 16):** Fatalities: "Confirmed within 30 days, and include suicides." Injuries (non-rail/ferry): "Immediate transport away from the scene for medical attention for one or more persons." Property damage (non-rail): "equal to or exceeding $25,000." Rail serious injuries: hospitalization >48h commencing within 7 days; any bone fracture (except simple fractures of fingers, toes, or nose); severe hemorrhages or nerve/muscle/tendon damage; internal organs; 2nd/3rd-degree burns or burns >5% of body surface. Rail substantial damage: disrupts operations AND adversely affects structural strength/performance/operating characteristics such that towing, rescue, on-site maintenance, or immediate removal is required.
- **Collisions/evacuations/derailments/runaway trains (p. 17):** verbatim rules on file; rail-to-rail collisions automatically reportable (Example 4B); assault/homicide involving contact with a transit vehicle reportable as collision (Scenario E).
- **Predominant Use Rule (p. 15):** multi-mode events reported in ONE mode — rail wins over non-rail; otherwise by passenger volume.
- **Scope (p. 14):** occurs at revenue/maintenance facility or rail yard, on right-of-way/infrastructure, during transit-related maintenance, or involves a transit revenue vehicle (in revenue service or not, p. 18); exclusions incl. off-property events coming to rest on property, administrative-building occupational events, natural-cause deaths.
- **Cyber Security Major Event (Scenario G, p. 19):** unauthorized access to agency servers disrupting operations meets the substantial-damage threshold and "is reportable as a Cyber Security Major Event." NOTE: the phrase is spelled "Cyber Security" — a literal grep for "cybersecurity" returns zero hits in both manuals (verification-method lesson recorded).
- **Non-major (S&S-50 scope, p. 3):** injury-threshold events + non-major fires + non-major assaults on transit workers; "Assaults on a transit worker do not require an injury to be reportable on the S&S-50."

Reportability status: definitions verified and quoted. Headway has NO S&S implementation yet — handoff 0010 designs it. S&S events are not derivable from GTFS-RT telemetry: the source is structured manual entry (the original ingestion charter's "manual entry with validation") plus future CAD/incident-system connectors.

### S&S addendum — verbatim rules for sscls (verified 2026-07-12, second pass)

Source: 2026 S&S Policy Manual, printed pp. 17–22 (PDF pages 28–33).

- **Collisions, rail (p. 17):** reportable when they "Meet an injury, fatality, substantial damage, or evacuation threshold; Include suicides, attempted suicides, and assaults or homicides that involve contact with a transit vehicle; Occur at a rail grade crossing or intersection; Involve an individual; Involve a rail transit vehicle and a second rail transit vehicle; or Include collisions that do not involve a transit vehicle but meet a threshold."
- **Collisions, non-rail/ferry (p. 17):** "Meet an injury, fatality, property damage, or evacuation threshold; Involve a transit revenue vehicle and the towing away of any vehicles (transit or non-transit) from the scene; Include suicides, attempted suicides, assaults, or homicides resulting in an injury or fatality that involve contact with a transit vehicle; or Include collisions that do not involve a transit revenue vehicle but meet a threshold." → the `towed` field IS a non-rail collision threshold condition (revenue vehicle + any tow-away).
- **Evacuations (p. 17):** non-rail: "Evacuation of a transit facility or vehicle for life-safety reasons." Rail adds: "Evacuations to controlled rail right-of-way (excludes evacuation to a platform, except for life safety)," covering "Both transit-directed evacuations and self-evacuations."
- **Derailments (p. 17, rail only):** "Both mainline and yard derailments and non-revenue vehicle derailments."
- **Runaway Train (p. 17, rail only, revenue vehicles):** "movement of a rail transit vehicle on the mainline, yard, or shop that is uncommanded, uncontrolled, or unmanned due to an incapacitated, sleeping, or absent operator, or the failure of a rail transit vehicle's electrical, mechanical, or software system or subsystem."
- **Other Safety Events exception (p. 22) — CLASSIFIER-CRITICAL:** Other Safety Events are "events that are NOT collisions, fires, security events, hazardous material spills, acts of God, or derailments … include slips, trips, falls, smoke events, fumes, runaway trains and electric shock. Only report these events when they meet either the fatality, evacuation, or property damage threshold or result in two or more injured persons. Other Safety Events that result in one person immediately transported from the scene for medical attention but do not trigger any other major reporting thresholds are reported on the Non-Major Summary Report."
- **Fatality nuances (p. 20):** illness/overdose/natural-cause deaths not reportable; "Deaths of undetermined cause in a rail right-of-way that may be the result of collision or electrocution are reportable"; fatality counted "if it is confirmed to have occurred within 30 days of the event."
- **Injury exclusions (p. 22):** transport solely for illness, natural causes, exposure, intoxication, overdose, or unrelated mental-health evaluation is not an injury; "Declarations or allegations of self-harm with no evident injury" not reportable; but a passenger's heart attack caused by a collision IS a reportable injury.
- **Example 4 solutions verbatim (pp. 18–19):** C: rail maintenance vehicle collides with a person in yard, one injury → "reportable as a Rail Transit Collision (include one Other vehicle)." D: two workers injured maintaining rail infrastructure → "reportable as an Other Safety Event" (two injuries — consistent with the p. 22 rule). F: pre-revenue streetcar testing fatality → "reportable to the NTD as a fatal rail collision." H: two Roadeo bus riders injured, EMS transport → "Reportable as a Major Safety Event due to the involvement of a transit vehicle."
- **Example 5 non-reportable (p. 20):** private vehicle hits city-street bus stop (no transit vehicle) → not reportable; construction worker injured building a rail extension → construction-related, not reportable.

### S&S addendum 2 — damage + injury definitions verbatim (verified 2026-07-12, third pass)

Source: 2026 S&S Policy Manual, printed pp. 21–27 (PDF pages 32–38).

- **Injury (p. 21):** "any harm to persons as a result of an event that requires immediate medical attention away from the scene. It does not include harm resulting from a drug overdose, exposure to the elements, illness, natural causes, or occupational safety events occurring in administrative buildings." "You must report each person transported away from the scene for medical attention as an injury, whether or not the person appears to be injured." Seeking care hours/days later, or after leaving on foot, "do not constitute immediate medical transportation away from the scene." Transport may be "by transit vehicle, an ambulance, another emergency vehicle, private vehicle, or via stretcher to the hospital" (p. 22).
- **Serious injury (rail, p. 21) — automatically reportable, transport not required:** "Requires hospitalization for more than 48 hours within 7 days of the event; Results in a fracture of any bone (except simple fractures of fingers, toes, or nose); Causes severe hemorrhages, or nerve, muscle, or tendon damage; Involves an internal organ; or Involves second- or third-degree burns or any burns affecting more than 5 percent of the body surface."
- **Property damage, non-rail (p. 25):** "estimated property damage equal to or exceeding $25,000, regardless of injuries or other thresholds. Estimated damage includes not only damage to transit property but also the cost of clearing wreckage and damage to all other vehicles and property involved in or affected by the event." "While the damage threshold for a major event is $25,000, any damage incurred must be included for any reportable event." Estimation methods FTA allows: standard totals per event type; case-by-case estimates; amount paid to repair/replace; insurance estimates.
- **Substantial damage, rail (p. 25):** "damage to any involved vehicles, facilities, equipment, rolling stock, or infrastructure that: Disrupts the operations of the rail transit agency, AND Adversely affects the structural strength, performance, or operating characteristics of the vehicle, facility, equipment, rolling stock, or infrastructure, such that it requires towing, rescue, on-site maintenance, or immediate removal prior to safe operation." **Exclusions:** "Cracked windows; Dents, bends, or small puncture holes in the body; Broken lights or mirrors; or Removal from service under the vehicle's own power for minor repair or maintenance, testing, or video and event recorder download."
- **Example 6 (p. 23):** 6C — person struck by train, leaves, hospitalized 5 days that evening for internal injury → serious injury, reportable major; "The same scenario resulting from a collision with a bus would not be reportable." 6E — mental-health transport with no associated event → not reportable. 6F — passenger spits on operator, no medical transport → "not reported on the S&S-40. However, the assault on a transit worker is reported on the S&S-50 Monthly Summary form."
- **Example 7 (p. 27):** 7A — bus vs private car: $15,000 (car, Kelley-Blue-Book-style present value) + $12,000 (bus body) = report $27,000 (damage sums across ALL involved property). 7B — rescue train dispatched → "Substantial damage." 7C — rail vehicle collides with private vehicle, which is towed away → "Substantial damage."
