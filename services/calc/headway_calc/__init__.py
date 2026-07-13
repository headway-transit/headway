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
CALC_VERSION 0.1.0 (monthly VOMS day-level proxy, handoff 0009);
compute_pmt is CALC_VERSION 0.1.0 (Passenger Miles Traveled — running load
by stop_sequence × stop-to-stop segment distance over canonical.stop_times,
handoff 0011; shares upt_v0's p. 146/p. 151 thresholds; the Exhibit 44
average-trip-length estimator lives beside it in headway_calc.pmt as a
labeled ESTIMATE, never conflated with computed PMT).
compute_vrh_v0_3, compute_vrh_v0_2 and compute_vrm_v0_1/compute_vrh_v0_1 are
the retained earlier versions, kept runnable so historical submissions
recompute bit-for-bit. The Demand Response calcs (handoff 0013 —
compute_dr_vrh/upt/pmt at 0.1.0 and compute_dr_vrm/compute_dr_voms at 0.1.1
after the 2026-07-13 hardening pass, with compute_dr_vrm_v0_1_0/
compute_dr_voms_v0_1_0 retained runnable — headway_calc.dr) run over
canonical.dr_trips with Exhibit 36 span semantics and TX onboard-only
accounting, persisting under scope 'mode:DR' (+ 'mode:DR:tos:<tos>') only. The compute_*_by_mode paths (handoff 0009) run the
UNCHANGED calc versions over per-mode input subsets (input selection, not a
semantics change — REGULATORY_TRACKER.md, "Mode scoping");
build_mr20_package assembles the NOT-REPORTABLE MR-20 preview package.

OPERATIONS metrics (handoff 0014 — category 'ops', THE HONESTY BOUNDARY):
compute_otp is CALC_VERSION 0.1.0 (on-time performance over derived stop
passages; configurable window, TCQSM-cited defaults) and
compute_headway_adherence is CALC_VERSION 0.1.0 (cvh — coefficient of
variation of headway deviations), both in headway_calc.ops over
derive_stop_passages 0.1.0 (headway_calc.passages). They persist ONLY with
computed.metric_values.category='ops' (stamped by headway_calc.persist from
the calc registry), can never be certified (migration 0024 CHECK), never
enter MR-20/S&S or /public/metrics/certified, and their definitions live in
OPS_DEFINITIONS.md — never in REGULATORY_TRACKER.md, because they are not
regulatory figures.

NOTE: headway_calc.sampling (NTD Sampling Manual plan support, handoff 0012)
and headway_calc.sscls (the S&S major-event classifier, handoff 0010) stay
MODULE-SCOPED on purpose — they never write computed.metric_values (sampling
produces labeled SAMPLED ESTIMATES and plan/draw facilities; sscls writes
safety.event_classifications), so they are not part of this package-level
metric-calculation surface. Import them directly (headway_calc.sampling /
headway_calc.sscls).
"""

from headway_calc.dq import route_blocking_issues, route_findings
from headway_calc.dr import (
    compute_dr_pmt,
    compute_dr_pmt_by_tos,
    compute_dr_upt,
    compute_dr_upt_by_tos,
    compute_dr_voms,
    compute_dr_voms_by_tos,
    compute_dr_voms_v0_1_0,
    compute_dr_vrh,
    compute_dr_vrh_by_tos,
    compute_dr_vrm,
    compute_dr_vrm_by_tos,
    compute_dr_vrm_v0_1_0,
)
from headway_calc.mode import (
    compute_pmt_by_mode,
    compute_upt_by_mode,
    compute_voms_by_mode,
    compute_vrh_by_mode,
    compute_vrm_by_mode,
    unknown_mode_finding,
)
from headway_calc.ops import (
    compute_headway_adherence,
    compute_headway_adherence_by_route,
    compute_otp,
    compute_otp_by_route,
)
from headway_calc.passages import derive_stop_passages
from headway_calc.pmt import compute_pmt
from headway_calc.reader import (
    load_agency_timezones,
    load_dr_trips,
    load_operated_trip_ids,
    load_ops_schedule,
    load_passenger_events,
    load_trip_geometries,
    load_vehicle_positions,
)
from headway_calc.types import (
    BlockingIssue,
    CalcResult,
    CoverageDetail,
    DrTrip,
    Finding,
    HeadwayAdherenceDetail,
    OpsScheduledStop,
    OtpDetail,
    PassengerEvent,
    PmtDetail,
    StopPassage,
    StopTime,
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
    "DrTrip",
    "Finding",
    "HeadwayAdherenceDetail",
    "OpsScheduledStop",
    "OtpDetail",
    "PassengerEvent",
    "PmtDetail",
    "StopPassage",
    "StopTime",
    "UptDetail",
    "VehiclePosition",
    "VomsDetail",
    "compute_dr_pmt",
    "compute_headway_adherence",
    "compute_headway_adherence_by_route",
    "compute_otp",
    "compute_otp_by_route",
    "derive_stop_passages",
    "compute_dr_pmt_by_tos",
    "compute_dr_upt",
    "compute_dr_upt_by_tos",
    "compute_dr_voms",
    "compute_dr_voms_by_tos",
    "compute_dr_voms_v0_1_0",
    "compute_dr_vrh",
    "compute_dr_vrh_by_tos",
    "compute_dr_vrm",
    "compute_dr_vrm_by_tos",
    "compute_dr_vrm_v0_1_0",
    "compute_pmt",
    "compute_pmt_by_mode",
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
    "load_agency_timezones",
    "load_dr_trips",
    "load_operated_trip_ids",
    "load_ops_schedule",
    "load_passenger_events",
    "load_trip_geometries",
    "load_vehicle_positions",
    "route_blocking_issues",
    "route_findings",
    "unknown_mode_finding",
]
