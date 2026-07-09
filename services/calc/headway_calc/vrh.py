"""vrh_v0 — Vehicle Revenue Hours, walking-skeleton approximation.

PRE-VERIFICATION (v0): position-derived duration over positions with a trip
assignment. Trip assignment is used as the revenue-service proxy; there is no
deadhead/layover handling. The FTA NTD definition of Vehicle Revenue Hours
MUST be verified against the current published FTA NTD Reporting Manual before
any figure from this calculation is treated as reportable. See
REGULATORY_TRACKER.md (calc vrh_v0).

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input positions.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable

from headway_calc._grouping import (
    GAP_THRESHOLD_SECONDS,
    consumed_record_ids,
    find_gap_issues,
    group_in_trip_positions,
)
from headway_calc.types import CalcResult, VehiclePosition

CALC_NAME = "vrh_v0"
CALC_VERSION = "0.1.0"
UNIT = "hours"

#: Quantum for the final Decimal aggregate: 0.01 hour.
HOURS_QUANTUM = Decimal("0.01")

_SECONDS_PER_HOUR = Decimal(3600)


def compute_vrh(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
) -> CalcResult:
    """Compute vrh_v0 (version 0.1.0) — Vehicle Revenue Hours, pre-verification.

    Groups positions by (vehicle_id, trip_id); considers ONLY positions with a
    trip_id (revenue-service proxy for v0 — a documented approximation); sums
    the time deltas (in hours) between consecutive positions within each group
    ordered by time.

    Gap rule (fail loudly): identical to vrm_v0 — if consecutive positions
    within a group are more than ``gap_threshold_seconds`` (default
    GAP_THRESHOLD_SECONDS=300, an explicit input default) apart, no
    interpolation and no summing across the gap; a 'telemetry_gap'
    BlockingIssue names the bounding source_record_ids and the result carries
    value=None. The caller gets issues, never a guessed number.

    Returns a CalcResult with a Decimal value quantized to 0.01 hours
    (ROUND_HALF_EVEN; total seconds are summed exactly, converted to hours in
    Decimal, then quantized once — a documented, pre-verification rounding
    rule).
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

    total_seconds = Decimal(0)
    for pts in groups.values():
        for prev, curr in zip(pts, pts[1:]):
            total_seconds += Decimal(str((curr.time - prev.time).total_seconds()))

    value = (total_seconds / _SECONDS_PER_HOUR).quantize(
        HOURS_QUANTUM, rounding=ROUND_HALF_EVEN
    )
    return CalcResult(
        value=value,
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION,
        input_record_ids=input_ids,
        blocking_issues=(),
    )
