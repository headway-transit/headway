# headway-calc

Headway's deterministic calculation library — **the only place any reported
number originates** (walking skeleton per ADR-0009, schema contract per
handoff `docs/handoffs/0001`, gap policy per handoff `docs/handoffs/0002`).
Pure, versioned functions: stdlib-only core, no network, no clock reads, no
randomness, no hidden state; time comes exclusively from inputs, and results
are `Decimal`, never float.

## Contents

- `headway_calc/types.py` — frozen dataclasses: `VehiclePosition`,
  `CalcResult` (carries `input_record_ids` for lineage, `blocking_issues`,
  `warnings`, and the 0.2.0 coverage `detail`; invariant: blocking findings ⇒
  `value=None` — warnings never force None), `Finding` (with `severity`:
  `'blocking'`/`'warning'`; the 0.1.0 name `BlockingIssue` stays importable,
  defaulting to blocking), `CoverageDetail`.
- `headway_calc/distance.py` — haversine miles (float per leg, one final
  Decimal quantization to 0.01 mi, ROUND_HALF_EVEN — rule documented in the
  module, pre-verification).
- `headway_calc/vrm.py` — `vrm_v0`: `compute_vrm` (0.2.0, the default path)
  and `compute_vrm_v0_1` (0.1.0, retained unchanged for bit-for-bit
  historical recomputes).
- `headway_calc/vrh.py` — `vrh_v0`: `compute_vrh` (0.2.0) and
  `compute_vrh_v0_1` (0.1.0, retained unchanged).
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
  source_record_id)`.
- `headway_calc/dq.py` — routes `Finding`s into `dq.issues` with **each
  finding's own severity** (warning stays warning, blocking stays blocking;
  one row per finding, status `'open'`, description naming the calc, version,
  period, and the severity-specific consequence). `route_blocking_issues`
  (0.1.0 entry point) is retained and refuses non-blocking findings. Never
  swallows an insert failure; never commits (transaction control is the
  runner's).
- `headway_calc/runner.py` — `run_period(conn, start, end,
  gap_threshold_seconds=None, coverage_threshold=None)`: closes the
  canonical→computed loop (reader → compute_vrm/compute_vrh 0.2.0 → dq
  routing → persist) and returns a frozen `RunReport` carrying both
  thresholds and per-metric coverage detail. See "Runner" below.
- `headway_calc/_cli.py` — the ONE process boundary (argv, env, psycopg);
  exempt from the stdlib-purity guardrail, contains no calculation logic.
- `REGULATORY_TRACKER.md` — calc/version → citation → verification status.
  All rows (0.1.0 and 0.2.0) are **PRE-VERIFICATION**; the 2026-07-10
  attempt to verify against the 2025 NTD Full Reporting Policy Manual was
  bot-blocked (transit.dot.gov 403) — definitions must be quoted in the
  tracker before any figure is reportable.
- Golden dataset: `tests/golden/vrm_vrh_v0/` (repo root) — synthetic
  hand-worked example (see its `BASIS.md`); regression anchor only, not an
  FTA-certified figure. `expected.json` pins 0.1.0; `expected_v0_2.json`
  pins the 0.2.0 gap policy over the same fixture.

## Gap policy — 0.2.0 (default): per-group exclusion + coverage

Per handoff 0002, `compute_vrm`/`compute_vrh` (CALC_VERSION `0.2.0`):

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
# optional: --gap-threshold-seconds 300 --coverage-threshold 0.95
```

Loads `canonical.vehicle_positions` for the **half-open** period
`[period-start, period-end)` (UTC — June is `[2026-06-01, 2026-07-01)`, so
consecutive months tile with no double-counted and no dropped instant), runs
`vrm_v0` and `vrh_v0` at CALC_VERSION 0.2.0, and prints the `RunReport` as
JSON (both thresholds recorded). Per metric:

- **every finding is routed to `dq.issues` with its own severity** —
  excluded-group warnings stay warnings, coverage refusals stay blocking;
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
....................................................................     [100%]
68 passed in 2.48s
```

Golden tests explicitly (0.1.0 pinned to the retained functions; 0.2.0 over
the same fixture):

```
$ python3 -m pytest tests/test_golden.py tests/test_golden_v02.py -v
tests/test_golden.py::test_golden_vrm_clean_subset PASSED                [ 12%]
tests/test_golden.py::test_golden_vrm_per_group PASSED                   [ 25%]
tests/test_golden.py::test_golden_vrh_clean_subset PASSED                [ 37%]
tests/test_golden.py::test_golden_vrh_per_group PASSED                   [ 50%]
tests/test_golden.py::test_golden_full_fixture_refuses_over_gap PASSED   [ 62%]
tests/test_golden_v02.py::test_golden_v02_default_threshold_blocks_below_coverage PASSED [ 75%]
tests/test_golden_v02.py::test_golden_v02_lowered_threshold_excludes_gapped_group PASSED [ 87%]
tests/test_golden_v02.py::test_golden_v02_clean_subset_full_coverage PASSED [100%]
8 passed in 0.12s
```

Coverage: 0.1.0 golden regression (exact Decimal values + gap refusal +
unassigned exclusion, pinned to `compute_vrm_v0_1`/`compute_vrh_v0_1`) and
0.1.0 Hypothesis properties, both byte-identical test bodies; 0.2.0 goldens
(default 0.95 threshold → blocked with exact coverage detail; explicit 0.5
threshold → clean-group values 12.44 mi / 0.45 h with one warning and exact
detail; clean subset → full coverage, values unchanged); 0.2.0 Hypothesis
properties (figure over included groups == figure over clean groups exactly
and == sum of per-group values within quantization, excluding a group never
increases the figure, coverage/clean-position share in [0, 1] with exact
counts, determinism, blocking ⇔ the exact threshold line with
blocking-implies-None); persist SQL/params including the `%s::jsonb` detail
write and warning-tolerant persistence; dq routing with per-finding severity
(and the 0.1.0 entry point refusing non-blocking findings); runner end-to-end
over the golden fixture for all three regimes (clean, blocked, persist-with-
warnings) including lineage narrowing to included groups; RunReport
determinism and JSON completeness; the two-transaction ordering; type
invariants (severity validation, warnings coexisting with a value); and the
stdlib-purity guardrail over every core module (`headway_calc/_cli.py` is the
one documented exemption). Migration 0010 is statically asserted by
`db/test_migrations_static.py` (8 passed).

### What is PENDING

- **Live-DB verification of calc 0.2.0 (migration 0010 + runner)** — this
  increment was implemented and unit/golden-tested against fake connections
  only, per the working agreement; the orchestrator applies
  `db/migrations/0010_metric_values_detail.sql` and re-runs
  `python -m headway_calc.runner` live (including a check that a
  sub-threshold run lands warning+blocking `dq.issues` rows and nothing in
  `computed.metric_values`, and that a passing run's row carries the
  coverage detail JSONB with lineage back to included-group records only).
- **FTA-manual verification of VRM/VRH semantics** — revenue-service
  inclusion, deadhead/layover exclusion, and rounding conventions must be
  verified against the 2025 NTD Full Reporting Policy Manual before any
  figure is treated as reportable; the 2026-07-10 verification attempt was
  bot-blocked (transit.dot.gov 403 — handoff 0002), so all tracker rows stay
  PRE-VERIFICATION until the manual is supplied and definitions are quoted.
  The 0.95 `coverage_threshold` default is likewise an engineering
  placeholder, not an FTA number.
- **dq.issues ownership** — routing lands findings in `dq.issues` with their
  own severity via `headway_calc.dq` / `run_period`; owner assignment and the
  resolution workflow remain the DQ workflow's scope (Backend), not this
  package's. Whether excluded-group warnings auto-resolve when a later
  replay fills the gap is an open handoff-0002 question (owner: Data
  Engineer, slice 2).
