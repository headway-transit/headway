"""headway_calc — Headway's deterministic calculation library (walking skeleton, ADR-0009).

The ONLY place any reported number originates. Pure, versioned, deterministic
functions: no network, no clock reads, no randomness, no hidden state.

All calculations in this package are v0: definitions are verified against the
2026 NTD Policy Manual but figures are NOT REPORTABLE pending the remaining
divergences — see REGULATORY_TRACKER.md. compute_vrm is CALC_VERSION 0.2.0
(gap policy: per-group exclusion + coverage, handoff 0002); compute_vrh is
CALC_VERSION 0.4.0 (trip-level excision, handoff 0004 — block-aware layover
inclusion per 0.3.0/handoff 0003, exclusion unit refined to the gapped trip
plus its adjacent layover intervals). compute_vrh_v0_3, compute_vrh_v0_2 and
compute_vrm_v0_1/compute_vrh_v0_1 are the retained earlier versions, kept
runnable so historical submissions recompute bit-for-bit.
"""

from headway_calc.dq import route_blocking_issues, route_findings
from headway_calc.reader import load_vehicle_positions
from headway_calc.types import (
    BlockingIssue,
    CalcResult,
    CoverageDetail,
    Finding,
    VehiclePosition,
)
from headway_calc.vrm import compute_vrm, compute_vrm_v0_1
from headway_calc.vrh import (
    compute_vrh,
    compute_vrh_v0_1,
    compute_vrh_v0_2,
    compute_vrh_v0_3,
)

# NOTE: the runner (headway_calc.runner: run_period, RunReport) is NOT
# re-exported here on purpose — `python -m headway_calc.runner` would then
# execute the module twice (runpy re-runs a module already imported by its
# package __init__, with duplicate class objects). Import it directly:
# `from headway_calc.runner import run_period, RunReport`.

__all__ = [
    "BlockingIssue",
    "CalcResult",
    "CoverageDetail",
    "Finding",
    "VehiclePosition",
    "compute_vrm",
    "compute_vrm_v0_1",
    "compute_vrh",
    "compute_vrh_v0_1",
    "compute_vrh_v0_2",
    "compute_vrh_v0_3",
    "load_vehicle_positions",
    "route_blocking_issues",
    "route_findings",
]
