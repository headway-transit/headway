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

## v0 semantics (documented approximation)

Trip assignment (`trip_id` present) is the revenue-service proxy; unassigned
positions are excluded; there is no deadhead handling. Distance is
position-derived haversine (trip-distance authority deferred to slice 2 per
handoff 0001).

## Verification status

### What ran (2026-07-08, Python 3.12.3, hypothesis 6.156.4)

```
$ cd services/calc && python3 -m pytest tests/ -q
........................                                                 [100%]
24 passed in 1.53s
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
invariants, and a stdlib-purity guardrail test over every core module.

### What is PENDING

- **Live-DB persist verification** — Docker/Postgres unavailable in this
  environment; `persist.py` is verified against a fake connection only. Must
  be exercised against a real TimescaleDB (with the `db/migrations/` schema
  applied) by the first environment that has one, including a lineage graph
  traversal from a `computed.metric_values` row back to `raw.records`.
- **FTA-manual verification of VRM/VRH semantics** — revenue-service
  inclusion, deadhead exclusion, and rounding conventions must be verified
  against the current published FTA NTD Reporting Manual before any figure is
  treated as reportable; tracked in `REGULATORY_TRACKER.md` (both calcs
  PRE-VERIFICATION). Verified semantics mint new calc versions with new
  golden datasets from certified inputs.
- **dq.issues routing** — `BlockingIssue`s are returned to the caller; the
  pipeline wiring that lands them in `dq.issues` with an owner is not part of
  this package's scope yet.
