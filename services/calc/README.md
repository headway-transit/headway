# headway-calc

Headway's deterministic calculation library — **the only place any reported
number originates** (walking skeleton per ADR-0009, schema contract per
handoff `docs/handoffs/0001`, gap policy per handoff `docs/handoffs/0002`,
block-aware VRH per handoff `docs/handoffs/0003`).
Pure, versioned functions: stdlib-only core, no network, no clock reads, no
randomness, no hidden state; time comes exclusively from inputs, and results
are `Decimal`, never float.

## Contents

- `headway_calc/types.py` — frozen dataclasses: `VehiclePosition` (now
  carrying the trip's GTFS `block_id`, joined by the reader), `CalcResult`
  (carries `input_record_ids` for lineage, `blocking_issues`, `warnings`,
  `infos`, and the coverage `detail`; invariant: blocking findings ⇒
  `value=None` — warnings/infos never force None), `Finding` (with
  `severity`: `'blocking'`/`'warning'`/`'info'`; the 0.1.0 name
  `BlockingIssue` stays importable, defaulting to blocking),
  `CoverageDetail`, `BlockCoverageDetail` (0.3.0: adds
  `layover_max_seconds` provenance).
- `headway_calc/distance.py` — haversine miles (float per leg, one final
  Decimal quantization to 0.01 mi, ROUND_HALF_EVEN — rule documented in the
  module, pre-verification).
- `headway_calc/vrm.py` — `vrm_v0`: `compute_vrm` (0.2.0, the default path —
  deliberately NOT block-aware: layover miles are N/A per Exhibit 35) and
  `compute_vrm_v0_1` (0.1.0, retained unchanged for bit-for-bit historical
  recomputes).
- `headway_calc/vrh.py` — `vrh_v0`: `compute_vrh` (0.3.0, the default path —
  block-aware layover inclusion, handoff 0003), `compute_vrh_v0_2` (0.2.0,
  retained unchanged) and `compute_vrh_v0_1` (0.1.0, retained unchanged).
- `headway_calc/_blocks.py` — internal 0.3.0 machinery: block grouping,
  layover accounting, the block gap policy, and the `block_unavailable`
  per-vehicle-day info findings. The 0.1.0/0.2.0 machinery in
  `_grouping.py` is untouched.
- `headway_calc/persist.py` — injectable DB-API writer:
  `computed.metric_values` (including the coverage `detail` JSONB, migration
  0010) + one `lineage.edges` row per consumed raw record (ADR-0007; for
  0.2.0 that means included groups only). Refuses results carrying blocking
  issues or `value=None`; warnings never refuse.
- `headway_calc/reader.py` — injectable DB-API reader for
  `canonical.vehicle_positions` over a **half-open UTC period**
  `[period_start, period_end)` (`time >= start AND time < end`; DATE bounds
  bound as timezone-aware UTC midnights so the comparison never depends on
  the DB session time zone), ordered by `(vehicle_id, time,
  source_record_id)`, with `canonical.trips.block_id` LEFT JOINed onto every
  position (handoff 0003 / migration 0011; NULL when unassigned/absent,
  never a dropped row).
- `headway_calc/dq.py` — routes `Finding`s into `dq.issues` with **each
  finding's own severity** (warning stays warning, blocking stays blocking;
  one row per finding, status `'open'`, description naming the calc, version,
  period, and the severity-specific consequence). `route_blocking_issues`
  (0.1.0 entry point) is retained and refuses non-blocking findings. Never
  swallows an insert failure; never commits (transaction control is the
  runner's).
- `headway_calc/runner.py` — `run_period(conn, start, end,
  gap_threshold_seconds=None, coverage_threshold=None,
  layover_max_seconds=None)`: closes the canonical→computed loop (reader →
  compute_vrm 0.2.0 / compute_vrh 0.3.0 → dq routing → persist) and returns
  a frozen `RunReport` carrying all three inputs and per-metric coverage
  detail. See "Runner" below.
- `headway_calc/_cli.py` — the ONE process boundary (argv, env, psycopg);
  exempt from the stdlib-purity guardrail, contains no calculation logic.
- `REGULATORY_TRACKER.md` — calc/version → citation → verification status.
  VRM/VRH/deadhead/layover definitions are VERIFIED against the 2026 NTD
  Policy Manual (quoted in the tracker); divergence D1 (layover inclusion)
  is CLOSED by vrh_v0 0.3.0; **no figure is reportable** pending the
  remaining divergences D2–D6 and the flagged engineering placeholders
  (`coverage_threshold` 0.95, `layover_max_seconds` 1800).
- Golden dataset: `tests/golden/vrm_vrh_v0/` (repo root) — synthetic
  hand-worked example (see its `BASIS.md`); regression anchor only, not an
  FTA-certified figure. `expected.json` pins 0.1.0; `expected_v0_2.json`
  pins the 0.2.0 gap policy over the same fixture; `fixture_block.json` +
  `expected_v0_3.json` pin the 0.3.0 block case (600 s layover included).

## Block-aware VRH — 0.3.0 (default for VRH): layover inclusion

Per handoff 0003, `compute_vrh` (CALC_VERSION `0.3.0`) closes divergence D1 —
the FTA **includes** layover/recovery time in VRH (2026 NTD Policy Manual,
Exhibit 35, p. 133; see `REGULATORY_TRACKER.md`):

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
#           --layover-max-seconds 1800
```

Loads `canonical.vehicle_positions` (with `block_id` joined) for the
**half-open** period `[period-start, period-end)` (UTC — June is
`[2026-06-01, 2026-07-01)`, so consecutive months tile with no
double-counted and no dropped instant), runs `vrm_v0` at CALC_VERSION 0.2.0
and `vrh_v0` at CALC_VERSION 0.3.0 (block-aware; `--layover-max-seconds`
passes through), and prints the `RunReport` as JSON (all three inputs
recorded). Per metric:

- **every finding is routed to `dq.issues` with its own severity** —
  block-fallback infos stay info, excluded-group and over-cap-layover
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

### What ran (2026-07-09, Python 3.12.3, hypothesis 6.156.4)

```
$ cd services/calc && python3 -m pytest tests/ -q
........................................................................ [ 76%]
......................                                                   [100%]
94 passed in 4.17s
```

0.3.0 golden tests explicitly (block case per handoff 0003, hand-worked in
`tests/golden/vrm_vrh_v0/BASIS.md`):

```
$ python3 -m pytest tests/test_golden_v03.py -v
tests/test_golden_v03.py::test_golden_v03_block_fixture_includes_layover PASSED [ 25%]
tests/test_golden_v03.py::test_golden_v03_retained_v02_excludes_the_layover PASSED [ 50%]
tests/test_golden_v03.py::test_golden_v03_vrm_unchanged_at_v02 PASSED    [ 75%]
tests/test_golden_v03.py::test_golden_v03_no_block_fixture_falls_back_per_trip PASSED [100%]
4 passed in 0.11s
```

Coverage: everything from 0.1.0/0.2.0 (goldens byte-identical; the 0.2.0
golden/property test bodies unchanged, now pinned to the retained
`compute_vrh_v0_2` exactly as the 0.1.0 suites pin `compute_vrh_v0_1`); NEW
for 0.3.0 — block golden (two trips, one block, 600 s layover: v0.3 `0.33` h
INCLUDES it, retained v0.2 `0.17` h excludes it, VRM stays 0.2.0 at
`6.91` mi; no-block fixture falls back per-trip reproducing `0.45` h plus
per-vehicle-day `block_unavailable` infos); 0.3.0 unit tests (layover cap
inclusive at the line, over-cap interval not counted + warned with bounding
records, within-trip gap excluding the WHOLE block group, vehicle-day info
grouping, null-trip positions inside a block ignored, non-positive intervals
contributing nothing, contradictory block_ids failing loudly, same block_id
on two vehicles never merging); 0.3.0 Hypothesis properties (MONOTONICITY:
v0.3 VRH ≥ v0.2 VRH on identical gap-free input; cap 0 collapses to the v0.2
value exactly; figure monotone in the cap with exact interval accounting and
one warning per over-cap interval; determinism/order-independence as full
structural equality; blocking ⇔ the exact coverage threshold line over block
groups with blocking-implies-None retained); reader block_id LEFT JOIN
SQL/mapping; runner end-to-end with per-severity dq routing (info rows
included), the vrh 0.3.0 detail JSONB carrying `layover_max_seconds`, and
`--layover-max-seconds` pass-through; and the stdlib-purity guardrail now
also covering `_blocks.py`. Migrations 0010+0011 are statically asserted by
`db/test_migrations_static.py` (9 passed); the transform suite (block_id
parse/upsert, absent-column case) is 38 passed.

### What is PENDING

- **Live re-run on the MBTA dataset (orchestrator's job)** — this increment
  was implemented and unit/golden-tested against fake connections only, per
  the working agreement. The orchestrator applies
  `db/migrations/0011_trips_block_id.sql`, replays the GTFS static feed (the
  upsert path backfills `block_id`), and re-runs
  `python -m headway_calc.runner` live, comparing v0.2 vs v0.3 VRH — the
  delta approximates the recovered layover share and should be
  sanity-checked against the manual's "10 to 20 percent of running time"
  description (handoff 0003, Outputs).
- **Reportability** — definitions are VERIFIED (tracker) and D1 is CLOSED,
  but no figure is reportable until divergences D2–D6 are addressed and the
  engineering placeholders are verified: `coverage_threshold` 0.95 (FTA
  completeness expectations) and `layover_max_seconds` 1800 (observed MBTA
  inter-trip layover distributions; ultimately per-agency config — handoff
  0003 open question).
- **dq.issues ownership** — routing lands findings in `dq.issues` with their
  own severity via `headway_calc.dq` / `run_period`; owner assignment and the
  resolution workflow remain the DQ workflow's scope (Backend), not this
  package's. Whether excluded-group warnings auto-resolve when a later
  replay fills the gap is an open handoff-0002 question (owner: Data
  Engineer, slice 2).
