# Handoff: ntd-compliance-engineer → ntd-compliance-engineer — Trip-level excision (vrh_v0 0.4.0)

## Context
The 2026-07-10 live comparison (tracker, vrh_v0 0.3.0 row) exposed the cost of block-level exclusion: one gapped trip poisons its entire block, dropping coverage from 0.9122 (trip-denominated, v0.2) to 0.8046 (block-denominated, v0.3) and discarding clean running time. Definitional correctness (layover inclusion) should not require throwing away sound data. v0.4 refines the **exclusion unit** from the block to *the gapped trip plus its adjacent layover intervals*.

Empirical inputs (measured 2026-07-10 on the MBTA dataset, 7,400 inter-trip intervals within blocks): p50 = 30 s, p90 = 109 s, p99 = 7,124 s, 2.7% > 1,800 s, 49 negative overlaps. The long tail is out-of-service parking, which Exhibit 35 explicitly excludes from revenue hours ("Bus arrives at the end of the route, parks, and goes out of service… → Vehicle Revenue Hours: No"). The 1,800 s `layover_max_seconds` default is therefore **data-informed and exhibit-aligned**, no longer a bare placeholder (still per-agency configurable).

## Inputs
- vrh_v0 0.3.0 implementation (`_blocks.py`) and its tests/goldens — retained runnable per tracker rules.
- Verified definitions + Exhibit 35 quotes: `services/calc/REGULATORY_TRACKER.md`.

### Specification — vrh_v0, CALC_VERSION 0.4.0
1. **Grouping unchanged from 0.3.0** (block-aware; NULL-block per-trip fallback with info finding; inter-trip intervals are layover, counted up to `layover_max_seconds`, over-cap intervals not counted + warning — all per handoff 0003).
2. **Exclusion unit refined:** a within-trip gap (> `gap_threshold_seconds`) excises ONLY:
   - that trip's running time, and
   - the inter-trip layover intervals immediately adjacent to it (both sides, where present) — a layover interval counts only when BOTH bounding trips are clean.
   The block's remaining clean trips and their other layover intervals stay in the figure. One warning finding `telemetry_gap_excluded` per excised trip, citing that trip's records.
3. **Coverage returns to trip denomination:** `coverage = clean_trips / total_trips` (directly comparable to 0.2.0's group coverage). The detail JSONB reports both trip-level coverage and the block statistics (blocks_touched, trips_excised, layover_intervals_dropped) plus all thresholds.
4. **Lineage:** input_record_ids cover included positions only (excised trips' records cited by their findings).
5. **Versioning:** 0.1.0/0.2.0/0.3.0 all retained runnable; 0.4.0 becomes the default `compute_vrh`. Tracker row cites Exhibit 35 for both layover inclusion AND the out-of-service exclusion that justifies the cap, plus the measured distribution above.
6. **Expected live result (verify):** trip-level coverage ≈ 0.91 on the current MBTA dataset; VRH ≈ v0.2 value + layover recovered over clean-adjacent intervals; v0.4 ≥ v0.2 on identical input (property test), v0.4 ≥ v0.3 on identical input (block-exclusion is strictly harsher — property test).

## Outputs
- Calc 0.4.0 per spec + goldens (extend the block fixture: one block of three trips where the middle trip is gapped → v0.4 keeps trips 1+3's running time, drops both adjacent layovers and trip 2; hand-worked in BASIS.md) + property tests + tracker row + README.
- Live re-run evidence appended here: trip-level coverage, v0.2/v0.3/v0.4 values on the same period.

## Open Questions
- Whether an excised trip's layover intervals could be *partially* retained when the gap is provably outside the layover-adjacent running segments — deferred; conservative both-sides drop stands for 0.4.0.

## Verification Evidence
- Authored against tracker-quoted Exhibit 35 definitions and the measured 2026-07-10 interval distribution.
- **2026-07-10 (later) — implemented and live-verified.** 115 calc tests green (21 new; all prior suites/goldens byte-identical). Live three-way on the same data, coverage_threshold=0 for comparison:
  - Full period 07-09..07-12 (1,344,444 positions): v0.2 = 9,614.61 h @ cov 0.9126 · v0.3 = 8,203.46 h @ cov 0.7967 · **v0.4 = 9,758.55 h @ cov 0.9126** (1,566 trips excised, 1,271 layover intervals dropped). v0.4 recovers +143.94 h (+1.5%) of layover over v0.2 while restoring the +1,555.09 h of clean running time v0.3's block-level exclusion discarded. Spec expectation (coverage ≈ 0.91, v0.4 ≥ both) met exactly.
  - Today-only 07-10..07-11 (611,132 positions, first continuous overnight window): identical pattern — v0.4 = 4,415.53 h @ cov 0.9140, +1.5% over v0.2. The layover-recovery rate is stable across windows, confirming the trip-assignment mechanism.
  - Steady-state observation: even continuous collection yields trip coverage ≈ 0.914 — ~8.6% of MBTA vehicle-trips have genuine within-trip reporting gaps (tunnels, dropouts) independent of cold starts. The 0.95 default coverage threshold therefore refuses on this feed structurally; the per-agency threshold decision (handoff 0002 open question) now has its empirical basis.
