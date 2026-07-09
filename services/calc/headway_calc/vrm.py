"""vrm_v0 — Vehicle Revenue Miles, walking-skeleton approximation.

PRE-VERIFICATION (v0): position-derived haversine distance over positions with
a trip assignment. Trip assignment is used as the revenue-service proxy; there
is no deadhead handling. The FTA NTD definition of Vehicle Revenue Miles
(revenue-service inclusion, deadhead exclusion, rounding convention) MUST be
verified against the current published FTA NTD Reporting Manual before any
figure from this calculation is treated as reportable. See
REGULATORY_TRACKER.md (calc vrm_v0).

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input positions.
"""

from __future__ import annotations

from typing import Iterable

from headway_calc._grouping import (
    GAP_THRESHOLD_SECONDS,
    consumed_record_ids,
    find_gap_issues,
    group_in_trip_positions,
)
from headway_calc.distance import haversine_miles, miles_to_decimal
from headway_calc.types import CalcResult, VehiclePosition

CALC_NAME = "vrm_v0"
CALC_VERSION = "0.1.0"
UNIT = "miles"


def compute_vrm(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
) -> CalcResult:
    """Compute vrm_v0 (version 0.1.0) — Vehicle Revenue Miles, pre-verification.

    Groups positions by (vehicle_id, trip_id); considers ONLY positions with a
    trip_id (revenue-service proxy for v0 — a documented approximation, no
    deadhead handling); sums haversine miles between consecutive positions
    within each group ordered by time.

    Gap rule (fail loudly): if consecutive positions within a group are more
    than ``gap_threshold_seconds`` (default GAP_THRESHOLD_SECONDS=300, an
    explicit input default) apart, no interpolation and no summing across the
    gap — a BlockingIssue of type 'telemetry_gap' is recorded naming the
    bounding source_record_ids, and the result carries value=None. The caller
    gets issues, never a guessed number.

    Returns a CalcResult with a Decimal value quantized to 0.01 miles
    (ROUND_HALF_EVEN — see headway_calc.distance for the documented,
    pre-verification rounding rule).
    """
    groups = group_in_trip_positions(positions)
    issues = find_gap_issues(groups, gap_threshold_seconds)
    input_ids = consumed_record_ids(groups)

    if issues:
        return CalcResult(
            value=None,
            unit=UNIT,
            calc_name=CALC_NAME,
            calc_version=CALC_VERSION,
            input_record_ids=input_ids,
            blocking_issues=tuple(issues),
        )

    total_miles = 0.0
    for pts in groups.values():
        for prev, curr in zip(pts, pts[1:]):
            total_miles += haversine_miles(
                prev.latitude, prev.longitude, curr.latitude, curr.longitude
            )

    return CalcResult(
        value=miles_to_decimal(total_miles),
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION,
        input_record_ids=input_ids,
        blocking_issues=(),
    )
