# Handoff: ntd-compliance-engineer → ntd-compliance-engineer — MR-20: mode dimension, voms_v0, package generator

## Context
MR-20 verified 2026-07-11 (tracker, "Verified — Form MR-20", manual pp. 32–33): four data points **per mode** — UPT, Actual Vehicle Revenue Hours, Actual Vehicle Revenue Miles, VOMS. Our calcs are fleet-wide and VOMS doesn't exist. This handoff closes both and ships the first MR-20 package generator (preview → generator; reportability caveats D1–D6 + simulated-data still govern).

## Specification
1. **Mode dimension — no migration needed.** `computed.metric_values.scope` (TEXT, default 'agency') carries mode scopes as `mode:<mode>` (e.g. `mode:bus`), mode from `canonical.routes.mode` joined via trips. Reader gains mode on each position/event (LEFT JOIN; NULL route/mode → scope bucket `mode:unknown`, counted + surfaced as an info finding, never dropped). Every existing calc (vrm 0.2, vrh 0.4, upt 0.1) gains a mode-scoped run path producing one metric_values row PER MODE plus the existing fleet-wide row (scope 'agency' unchanged — full backward compat; existing goldens untouched). Runner: `--per-mode` flag (default on for the MR path, off preserves current behavior in existing tests).
2. **voms_v0 0.1.0 (new calc, PRE-VERIFICATION).** Quoted basis (p. 33): "VOMS is the number of revenue vehicles/passenger cars operated to meet the maximum service requirement during the month of service reported. VOMS excludes atypical days or one-time special events." v0 approximation: per mode (and fleet), the **maximum over service days of the count of distinct vehicles observed in revenue service** (in-trip positions) that day. Documented divergences: (a) "maximum service requirement" is schedule-peak simultaneity — day-level distinct-vehicle max is an upper-bound proxy (verify against Policy Manual VOMS section before reportable); (b) atypical-day exclusion NOT implemented (needs agency calendar policy — open question); (c) passenger-car counting for rail (existing D2). Integer value, unit 'vehicles', detail JSONB {days_observed, peak_day, per_day_counts summary}, lineage over that peak day's records.
3. **MR-20 package generator.** `headway_calc/mr20.py`: given conn + year-month, assemble per-mode {upt, vrm, vrh, voms} from computed.metric_values (latest per metric+scope+period), emit a package dict/JSON mirroring the four MR-20 data points per mode + fleet totals, each cell carrying {value, metric_value_id, calc_version, certification_status, flags (simulated/pre-verification), coverage}. Missing cell = explicit null + reason (never invented). Package header: NOT-REPORTABLE banner enumerating governing caveats (pull from tracker facts: D1–D6, simulated source, VOMS proxy). CLI: `python -m headway_calc.mr20 --month 2026-07`. This is the artifact the web report view can later consume verbatim.
4. **Goldens + tracker.** voms golden (hand-worked: 3 days, distinct vehicle counts 2/3/2 → 3); per-mode split golden (two modes' positions → two scoped rows summing to fleet row); mr20 package golden (canned metric rows → exact package JSON). Tracker rows: voms_v0 (quote p. 33 verbatim, divergences a/b/c), mode-dimension note on existing calcs' rows is NOT edited — append a "Mode scoping (2026-07-11)" section instead.

## Verification
Full calc suite green (185 + new); db static green (no migration expected); evidence appended here. Live per-mode + voms + package run against MBTA data is the orchestrator's step.

### Evidence (2026-07-11, Python 3.12.3)

```
$ cd services/calc && python3 -m pytest tests/ -q
........................................................................ [ 29%]
........................................................................ [ 58%]
........................................................................ [ 88%]
.............................                                            [100%]
245 passed in 11.08s

$ cd db && python3 -m pytest test_migrations_static.py -q
..............                                                           [100%]
14 passed in 0.10s
```

245 = the 185 pre-0009 tests (unchanged and green; `--per-mode` defaults
OFF) + 60 new (voms unit/golden/property, mode unit/golden/property,
per-mode runner end-to-end incl. per-scope blocking independence, mr20 unit
+ exact-package golden + CLI boundary). No migration: mode scopes ride the
handoff-0001 `computed.metric_values.scope` column. New goldens:
`tests/golden/voms_v0/` (2/3/2 → 3), `tests/golden/mode_scope/` (per-mode
sums = fleet for vrm/vrh/upt; voms max ≠ sum), `tests/golden/mr20/` (canned
rows → exact package JSON), each with a hand-worked BASIS.md. Tracker: new
voms_v0 0.1.0 row (p. 33 quoted verbatim, divergences a/b/c) + appended
"Mode scoping (2026-07-11)" section (existing calc rows untouched, versions
NOT bumped — input selection, not a semantics change).

## Open Questions
- Atypical-day exclusion policy (agency calendar) — owner NTD role, future increment.
- Whether MR-20 wants passenger-car VRH/VRM for rail modes (existing D2) — package flags rail modes as non-reportable pending D2.
