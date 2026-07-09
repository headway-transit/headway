"""vrm_v0 — Vehicle Revenue Miles, walking-skeleton approximation.

PRE-VERIFICATION (v0): position-derived haversine distance over positions with
a trip assignment. Trip assignment is used as the revenue-service proxy; there
is no deadhead handling. The FTA NTD definition of Vehicle Revenue Miles
(revenue-service inclusion, deadhead exclusion, rounding convention) MUST be
verified against the current published FTA NTD Reporting Manual before any
figure from this calculation is treated as reportable. See
REGULATORY_TRACKER.md (calc vrm_v0).

Versions (both runnable — shipped versions are never deleted):
- 0.2.0 (``compute_vrm``, the default path) — gap policy per handoff 0002:
  gapped (vehicle_id, trip_id) groups are EXCLUDED from the figure (one
  warning finding each), coverage is reported, and the run refuses only when
  coverage falls below the explicit coverage_threshold input.
- 0.1.0 (``compute_vrm_v0_1``, retained UNCHANGED) — all-or-nothing gap
  refusal, so historical submissions recompute bit-for-bit.

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input positions.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from headway_calc._grouping import (
    COVERAGE_THRESHOLD,
    GAP_THRESHOLD_SECONDS,
    apply_gap_exclusion_policy,
    consumed_record_ids,
    find_gap_issues,
    group_in_trip_positions,
)
from headway_calc.distance import haversine_miles, miles_to_decimal
from headway_calc.types import CalcResult, VehiclePosition

CALC_NAME = "vrm_v0"
CALC_VERSION = "0.2.0"
CALC_VERSION_0_1_0 = "0.1.0"
UNIT = "miles"


def _sum_group_miles(groups) -> float:
    total_miles = 0.0
    for pts in groups.values():
        for prev, curr in zip(pts, pts[1:]):
            total_miles += haversine_miles(
                prev.latitude, prev.longitude, curr.latitude, curr.longitude
            )
    return total_miles


def compute_vrm(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
    coverage_threshold: Decimal = COVERAGE_THRESHOLD,
) -> CalcResult:
    """Compute vrm_v0 (version 0.2.0) — Vehicle Revenue Miles, pre-verification.

    Groups positions by (vehicle_id, trip_id); considers ONLY positions with a
    trip_id (revenue-service proxy for v0 — a documented approximation, no
    deadhead handling); sums haversine miles between consecutive positions
    within each INCLUDED group ordered by time.

    Gap policy (handoff 0002): a group containing a gap >
    ``gap_threshold_seconds`` (explicit input, default 300) is EXCLUDED from
    the figure — one warning finding ('telemetry_gap_excluded') per excluded
    group, citing all of that group's records. Coverage
    (clean_groups/total_groups, plus clean-position share) is carried in
    ``result.detail``. If coverage falls below ``coverage_threshold``
    (explicit input, default 0.95 — an engineering placeholder, not an FTA
    number), the run emits ONE blocking finding ('coverage_below_threshold')
    and value=None: never a certifiable value over an unresolved DQ gap.

    ``input_record_ids`` contains ONLY records from included groups (excluded
    groups' records are cited by their warning findings — handoff 0002 rule
    5). Returns a CalcResult with a Decimal value quantized to 0.01 miles
    (ROUND_HALF_EVEN — see headway_calc.distance for the documented,
    pre-verification rounding rule).
    """
    groups = group_in_trip_positions(positions)
    policy = apply_gap_exclusion_policy(groups, gap_threshold_seconds, coverage_threshold)
    input_ids = consumed_record_ids(policy.included)

    if policy.blocking_issues:
        return CalcResult(
            value=None,
            unit=UNIT,
            calc_name=CALC_NAME,
            calc_version=CALC_VERSION,
            input_record_ids=input_ids,
            blocking_issues=policy.blocking_issues,
            warnings=policy.warnings,
            detail=policy.detail,
        )

    return CalcResult(
        value=miles_to_decimal(_sum_group_miles(policy.included)),
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION,
        input_record_ids=input_ids,
        blocking_issues=(),
        warnings=policy.warnings,
        detail=policy.detail,
    )


def compute_vrm_v0_1(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
) -> CalcResult:
    """Compute vrm_v0 version 0.1.0 — RETAINED UNCHANGED for reproducibility.

    The original all-or-nothing gap rule: if consecutive positions within any
    group are more than ``gap_threshold_seconds`` apart, no interpolation and
    no summing across the gap — a blocking 'telemetry_gap' finding is recorded
    naming the bounding source_record_ids, and the result carries value=None.
    Superseded by 0.2.0 (``compute_vrm``) per handoff 0002; kept runnable so
    historical submissions recompute bit-for-bit (versioning discipline:
    shipped versions are never deleted or rewritten).
    """
    groups = group_in_trip_positions(positions)
    issues = find_gap_issues(groups, gap_threshold_seconds)
    input_ids = consumed_record_ids(groups)

    if issues:
        return CalcResult(
            value=None,
            unit=UNIT,
            calc_name=CALC_NAME,
            calc_version=CALC_VERSION_0_1_0,
            input_record_ids=input_ids,
            blocking_issues=tuple(issues),
        )

    return CalcResult(
        value=miles_to_decimal(_sum_group_miles(groups)),
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION_0_1_0,
        input_record_ids=input_ids,
        blocking_issues=(),
    )
