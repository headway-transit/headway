# headway-calc

Headway's deterministic calculation library — **the only place any reported
number originates** (walking skeleton per ADR-0009, schema contract per
handoff `docs/handoffs/0001`). Pure, versioned functions: stdlib-only core, no
network, no clock reads, no randomness, no hidden state; time comes
exclusively from inputs, and results are `Decimal`, never float.

## Contents

- `headway_calc/types.py` — frozen dataclasses: `VehiclePosition`,
  `CalcResult` (carries `input_record_ids` for lineage and `blocking_issues`;
  invariant: blocking issues ⇒ `value=None`), `BlockingIssue`.
- `headway_calc/distance.py` — haversine miles (float per leg, one final
  Decimal quantization to 0.01 mi, ROUND_HALF_EVEN — rule documented in the
  module, pre-verification).
- `headway_calc/vrm.py` — `vrm_v0` 0.1.0, Vehicle Revenue Miles approximation.
- `headway_calc/vrh.py` — `vrh_v0` 0.1.0, Vehicle Revenue Hours approximation.
- `headway_calc/persist.py` — injectable DB-API writer:
  `computed.metric_values` + one `lineage.edges` row per consumed raw record
  (ADR-0007). Refuses results carrying blocking issues or `value=None`.
- `headway_calc/reader.py` — injectable DB-API reader for
  `canonical.vehicle_positions` over a **half-open UTC period**
  `[period_start, period_end)` (`time >= start AND time < end`; DATE bounds
  bound as timezone-aware UTC midnights so the comparison never depends on
  the DB session time zone), ordered by `(vehicle_id, time,
  source_record_id)`.
- `headway_calc/dq.py` — routes `BlockingIssue`s into `dq.issues` (one row
  per issue: severity `'blocking'`, status `'open'`, description naming the
  calc, version, and period). Never swallows an insert failure; never
  commits (transaction control is the runner's).
- `headway_calc/runner.py` — `run_period(conn, start, end)`: closes the
  canonical→computed loop (reader → compute_vrm/compute_vrh → dq routing or
  persist) and returns a frozen `RunReport`. See "Runner" below.
- `headway_calc/_cli.py` — the ONE process boundary (argv, env, psycopg);
  exempt from the stdlib-purity guardrail, contains no calculation logic.
- `REGULATORY_TRACKER.md` — calc/version → citation → verification status.
  Both v0 calcs are **PRE-VERIFICATION**.
- Golden dataset: `tests/golden/vrm_vrh_v0/` (repo root) — synthetic
  hand-worked example (see its `BASIS.md`); regression anchor only, not an
  FTA-certified figure.

## Fail-loudly gap rule

If consecutive in-trip positions in a (vehicle_id, trip_id) group are more
than `GAP_THRESHOLD_SECONDS` (default 300, an explicit input default — not a
hidden constant) apart, the calculation records a `telemetry_gap`
`BlockingIssue` naming the bounding `source_record_ids` and returns
`value=None`. No interpolation, no partial sum, no guessed number — the caller
gets issues. `persist_result` additionally refuses to write any such result.

## Runner: closing the canonical→computed loop

```
export HEADWAY_DATABASE_URL=postgresql://…/agency_db
python -m headway_calc.runner --period-start 2026-06-01 --period-end 2026-07-01
# optional: --gap-threshold-seconds 300
```

Loads `canonical.vehicle_positions` for the **half-open** period
`[period-start, period-end)` (UTC — June is `[2026-06-01, 2026-07-01)`, so
consecutive months tile with no double-counted and no dropped instant), runs
`vrm_v0` and `vrh_v0`, and prints the `RunReport` as JSON. Per metric:

- **blocking issues present** → the issues are routed to `dq.issues` and **no
  `computed.metric_values` row is written** for that metric (the guardrail:
  never emit a certifiable value over an unresolved gap);
- **clean** → the value is persisted with its lineage edges via
  `persist.persist_result`.

`python -m headway_calc.runner` requires `psycopg`
(`pip install 'headway-calc[persist]'`) and `HEADWAY_DATABASE_URL`; the
library API (`headway_calc.runner.run_period`) takes any injected DB-API
connection and needs neither.

### Transaction design — two transactions, fail-loudly-first

`run_period` deliberately uses **two** transactions, in this order:

1. **Issues first, committed first.** Every `dq.issues` row for the run is
   inserted and committed in its own transaction before any value is written.
   Evidence of a data problem must never be lost: if the value phase later
   fails (constraint violation, dropped connection, bug), the blocking issues
   are already durable and an operator sees *why* figures are blocked.
2. **Values second, all-or-nothing.** All clean metrics'
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

### What ran (2026-07-08, Python 3.12.3, hypothesis 6.156.4)

```
$ cd services/calc && python3 -m pytest tests/ -q
.............................................                            [100%]
45 passed in 1.31s
```

Golden tests explicitly:

```
$ python3 -m pytest tests/test_golden.py -v
tests/test_golden.py::test_golden_vrm_clean_subset PASSED                [ 20%]
tests/test_golden.py::test_golden_vrm_per_group PASSED                   [ 40%]
tests/test_golden.py::test_golden_vrh_clean_subset PASSED                [ 60%]
tests/test_golden.py::test_golden_vrh_per_group PASSED                   [ 80%]
tests/test_golden.py::test_golden_full_fixture_refuses_over_gap PASSED   [100%]
5 passed in 0.09s
```

Coverage: golden regression (exact Decimal values + gap refusal + unassigned
exclusion), Hypothesis properties (non-negativity, additivity across group
partitions, determinism, order-independence, gap refusal), persist SQL/params
against the handoff-0001 schema via a fake DB-API connection, type
invariants, and a stdlib-purity guardrail test over every core module
(`headway_calc/_cli.py` is the one documented exemption — the process
boundary, no calculation logic). New with the runner increment: reader
SQL/params (half-open UTC bounds, exact handoff columns, deterministic ORDER
BY, row→dataclass mapping), dq routing fields (severity/status/description
naming calc+period, TEXT[] record ids, failures never swallowed), runner
end-to-end over the golden fixture (clean → both metrics persisted, no dq
rows; gapped → dq rows and NO metric_values insert), RunReport determinism,
and the two-transaction ordering (persist failure preserves committed dq
issues; dq-routing failure aborts before any value write).

### What is PENDING

- **Live-DB verification (reader + dq + persist + runner)** —
  Docker/Postgres unavailable in this environment; all database-touching
  modules are verified against fake connections only. A live
  `python -m headway_calc.runner` against a real TimescaleDB (with the
  `db/migrations/` schema applied) is PENDING for the first environment that
  has one, including a lineage graph traversal from a
  `computed.metric_values` row back to `raw.records` and a check that a
  blocked run lands `dq.issues` rows and nothing in `computed.metric_values`.
- **FTA-manual verification of VRM/VRH semantics** — revenue-service
  inclusion, deadhead exclusion, and rounding conventions must be verified
  against the current published FTA NTD Reporting Manual before any figure is
  treated as reportable; tracked in `REGULATORY_TRACKER.md` (both calcs
  PRE-VERIFICATION). Verified semantics mint new calc versions with new
  golden datasets from certified inputs.
- **dq.issues ownership** — routing now lands blocking issues in `dq.issues`
  (severity `'blocking'`, status `'open'`) via `headway_calc.dq` /
  `run_period`; owner assignment and the resolution workflow remain the DQ
  workflow's scope (Backend), not this package's.
