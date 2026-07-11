"""headway_calc — Headway's deterministic calculation library (walking skeleton, ADR-0009).

The ONLY place any reported number originates. Pure, versioned, deterministic
functions: no network, no clock reads, no randomness, no hidden state.

All calculations in this package are v0: definitions are verified against the
2026 NTD Policy Manual but figures are NOT REPORTABLE pending the remaining
divergences — see REGULATORY_TRACKER.md. compute_vrm is CALC_VERSION 0.2.0
(gap policy: per-group exclusion + coverage, handoff 0002); compute_vrh is
CALC_VERSION 0.4.0 (trip-level excision, handoff 0004 — block-aware layover
inclusion per 0.3.0/handoff 0003, exclusion unit refined to the gapped trip
plus its adjacent layover intervals); compute_upt is CALC_VERSION 0.1.0
(Unlinked Passenger Trips over TIDES passenger events, handoff 0005 — the
p. 146 missing-trip rule with a REAL FTA 2% threshold); compute_voms is
CALC_VERSION 0.1.0 (monthly VOMS day-level proxy, handoff 0009).
compute_vrh_v0_3, compute_vrh_v0_2 and compute_vrm_v0_1/compute_vrh_v0_1 are
the retained earlier versions, kept runnable so historical submissions
recompute bit-for-bit. The compute_*_by_mode paths (handoff 0009) run the
UNCHANGED calc versions over per-mode input subsets (input selection, not a
semantics change — REGULATORY_TRACKER.md, "Mode scoping");
build_mr20_package assembles the NOT-REPORTABLE MR-20 preview package.
"""

from headway_calc.dq import route_blocking_issues, route_findings
from headway_calc.mode import (
    compute_upt_by_mode,
    compute_voms_by_mode,
    compute_vrh_by_mode,
    compute_vrm_by_mode,
    unknown_mode_finding,
)
from headway_calc.reader import (
    load_operated_trip_ids,
    load_passenger_events,
    load_vehicle_positions,
)
from headway_calc.types import (
    BlockingIssue,
    CalcResult,
    CoverageDetail,
    Finding,
    PassengerEvent,
    UptDetail,
    VehiclePosition,
    VomsDetail,
)
from headway_calc.upt import compute_upt
from headway_calc.voms import compute_voms
from headway_calc.vrm import compute_vrm, compute_vrm_v0_1
from headway_calc.vrh import (
    compute_vrh,
    compute_vrh_v0_1,
    compute_vrh_v0_2,
    compute_vrh_v0_3,
)

# NOTE: the runner (headway_calc.runner: run_period, RunReport) and the
# MR-20 generator (headway_calc.mr20: build_mr20_package) are NOT
# re-exported here on purpose — `python -m headway_calc.runner` /
# `python -m headway_calc.mr20` would then execute the module twice (runpy
# re-runs a module already imported by its package __init__, with duplicate
# class objects). Import them directly:
# `from headway_calc.runner import run_period, RunReport` /
# `from headway_calc.mr20 import build_mr20_package`.

__all__ = [
    "BlockingIssue",
    "CalcResult",
    "CoverageDetail",
    "Finding",
    "PassengerEvent",
    "UptDetail",
    "VehiclePosition",
    "VomsDetail",
    "compute_upt",
    "compute_upt_by_mode",
    "compute_voms",
    "compute_voms_by_mode",
    "compute_vrm",
    "compute_vrm_by_mode",
    "compute_vrm_v0_1",
    "compute_vrh",
    "compute_vrh_by_mode",
    "compute_vrh_v0_1",
    "compute_vrh_v0_2",
    "compute_vrh_v0_3",
    "load_operated_trip_ids",
    "load_passenger_events",
    "load_vehicle_positions",
    "route_blocking_issues",
    "route_findings",
    "unknown_mode_finding",
]
