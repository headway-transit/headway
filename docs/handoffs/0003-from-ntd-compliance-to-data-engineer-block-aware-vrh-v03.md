# Handoff: ntd-compliance-engineer → data-engineer — Block-aware VRH (calc v0.3, closes divergence D1)

## Context
Definition verification against the 2026 NTD Policy Manual (REGULATORY_TRACKER.md, "Verified definitions", 2026-07-10) found divergence **D1**: FTA includes layover/recovery time in Vehicle Revenue Hours (Exhibit 35, manual p. 133; layover "typically ranges from 10 to 20 percent of the running time", p. 128), while calc 0.2.0's per-(vehicle, trip) grouping drops inter-trip time — VRH systematically undercounts. GTFS's `block_id` (trips.txt, optional field — verify semantics against the current GTFS reference at gtfs.org: trips sharing a block are operated by the same vehicle in sequence) is the schedule-native way to group consecutive trips and the layover between them.

## Inputs (what receiving roles are given)
- Verified definitions + divergence analysis: `services/calc/REGULATORY_TRACKER.md`.
- GTFS static already ingested; `trips.txt` carries `block_id` for many agencies (MBTA does for bus/subway — confirm at implementation).
- Existing calc package (0.1.0 and 0.2.0 retained runnable, per tracker rules).

### Specification
1. **Schema (Data Engineer):** migration `0011_trips_block_id.sql` — `ALTER TABLE canonical.trips ADD COLUMN block_id TEXT;` (nullable; absent in feeds that omit it). Transform: `gtfs_static.py` parses `block_id` (absent → NULL, no DQ noise — the field is optional per spec) and the writer upserts it. Existing rows backfill on next static-feed replay (upsert path).
2. **Calc (NTD role, vrh_v0 → CALC_VERSION 0.3.0):**
   - Reader joins `canonical.trips.block_id` so each position carries (vehicle_id, trip_id, block_id).
   - **Block grouping:** positions of the same vehicle whose trips share a `block_id` form one VRH group spanning consecutive trips. Groups where `block_id` IS NULL fall back to per-trip grouping (0.2.0 semantics) and emit one **info**-severity finding `block_unavailable` per affected vehicle-day (documented undercount).
   - **Layover inclusion:** elapsed time between the last position of trip N and the first position of trip N+1 *within the same block* is INCLUDED in VRH, up to `layover_max_seconds` (explicit input, default 1800 — an ENGINEERING PLACEHOLDER pending observed layover distributions; the manual's "10 to 20 percent of running time" is descriptive, not a cap). This is not telemetry interpolation: block membership makes the interval layover *by definition* (Exhibit 35), and elapsed wall-time between observed endpoints is measured, not inferred. An inter-trip interval exceeding `layover_max_seconds` is NOT counted and emits a **warning** finding `layover_exceeds_max` (vehicle possibly out of service mid-block).
   - **Within-trip gap rule unchanged** (gap_threshold_seconds, default 300): a gap inside a trip's running time still excludes per 0.2.0 policy — but the exclusion unit becomes the block group for VRH.
   - **Coverage/threshold machinery unchanged** (coverage over VRH groups; blocking `coverage_below_threshold` below coverage_threshold).
   - **VRM unchanged at 0.2.0** — layover miles are N/A per Exhibit 35; per-trip grouping remains correct for miles.
   - Lineage: input_record_ids cover all positions in included block groups.
3. **Goldens:** extend the golden set with a block case — two trips in one block with a 600 s inter-trip layover: v0.3 VRH includes the 600 s; v0.2 comparison value excludes it; hand-worked in BASIS.md. Retain all 0.1.0/0.2.0 goldens untouched.
4. **Tracker:** vrh_v0 0.3.0 row citing Exhibit 35 / pp. 128–133 (already-quoted source), status DEFINITIONS VERIFIED — D1 CLOSED (block-aware), remaining divergences D2–D6 unchanged; layover_max_seconds and coverage_threshold flagged as engineering placeholders.

## Outputs
- Data Engineer: migration 0011 + transform block_id parse/upsert + tests (fixture zip gains block_id column; absent-column case still green).
- NTD role: calc vrh_v0 0.3.0 per spec + goldens + property tests (monotonicity: v0.3 VRH ≥ v0.2 VRH on identical input; layover cap respected; determinism) + tracker row.
- Evidence: full pytest suites + a live re-run on the MBTA dataset comparing v0.2 vs v0.3 VRH (the delta approximates the recovered layover share; sanity-check against the manual's 10–20% description).

## Open Questions
- `layover_max_seconds` default (1800): engineering placeholder; observe MBTA inter-trip distributions and revisit; ultimately per-agency config alongside coverage_threshold (owner: NTD role → Backend config surface).
- Null-trip positions temporally inside a block's span: v0.3 ignores them for VRH (conservative); attributing them to the block is a possible v0.4 refinement (owner: NTD role).

## Verification Evidence
- Authored against the quoted 2026 manual definitions (tracker, 2026-07-10). Implementation evidence to be appended on completion.
