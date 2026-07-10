"""vrh_v0 — Vehicle Revenue Hours, walking-skeleton approximation.

Position-derived duration over positions with a trip assignment. Trip
assignment is used as the revenue-service proxy; there is no deadhead
handling. Definitions verified against the 2026 NTD Policy Manual (see
REGULATORY_TRACKER.md, calc vrh_v0): the FTA INCLUDES layover/recovery time
in VRH (Exhibit 35, p. 133), which 0.3.0 implements via GTFS block grouping —
closing divergence D1. Figures remain NOT REPORTABLE pending the remaining
divergences (D2–D6).

Versions (all runnable — shipped versions are never deleted):
- 0.3.0 (``compute_vrh``, the default path) — block-aware grouping per
  handoff 0003: a vehicle's trips sharing a GTFS block_id form ONE VRH group,
  and the inter-trip layover is INCLUDED up to layover_max_seconds (explicit
  input, default 1800 — an ENGINEERING PLACEHOLDER). NULL-block trips fall
  back to per-trip grouping (one 'block_unavailable' info finding per
  vehicle-day — documented undercount). Within-trip gap rule and
  coverage/threshold machinery unchanged from 0.2.0; the exclusion unit is
  the block group.
- 0.2.0 (``compute_vrh_v0_2``, retained UNCHANGED) — gap policy per handoff
  0002: gapped (vehicle_id, trip_id) groups are EXCLUDED from the figure (one
  warning finding each), coverage is reported, and the run refuses only when
  coverage falls below the explicit coverage_threshold input.
- 0.1.0 (``compute_vrh_v0_1``, retained UNCHANGED) — all-or-nothing gap
  refusal, so historical submissions recompute bit-for-bit.

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input positions.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable

from headway_calc._blocks import (
    LAYOVER_MAX_SECONDS,
    apply_block_gap_policy,
    block_consumed_record_ids,
    block_group_seconds,
    group_block_positions,
)
from headway_calc._grouping import (
    COVERAGE_THRESHOLD,
    GAP_THRESHOLD_SECONDS,
    apply_gap_exclusion_policy,
    consumed_record_ids,
    find_gap_issues,
    group_in_trip_positions,
)
from headway_calc.types import CalcResult, Finding, VehiclePosition

CALC_NAME = "vrh_v0"
CALC_VERSION = "0.3.0"
CALC_VERSION_0_2_0 = "0.2.0"
CALC_VERSION_0_1_0 = "0.1.0"
UNIT = "hours"

#: Quantum for the final Decimal aggregate: 0.01 hour.
HOURS_QUANTUM = Decimal("0.01")

_SECONDS_PER_HOUR = Decimal(3600)


def _seconds_to_hours(total_seconds: Decimal) -> Decimal:
    """Exact seconds converted to hours and quantized once (0.01 h,
    ROUND_HALF_EVEN — a documented, engineering rounding rule)."""
    return (total_seconds / _SECONDS_PER_HOUR).quantize(
        HOURS_QUANTUM, rounding=ROUND_HALF_EVEN
    )


def _sum_group_hours(groups) -> Decimal:
    """0.1.0/0.2.0 aggregate: within-group time deltas summed exactly across
    (vehicle_id, trip_id) groups, then converted/quantized once."""
    total_seconds = Decimal(0)
    for pts in groups.values():
        for prev, curr in zip(pts, pts[1:]):
            total_seconds += Decimal(str((curr.time - prev.time).total_seconds()))
    return _seconds_to_hours(total_seconds)


def compute_vrh(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
    coverage_threshold: Decimal = COVERAGE_THRESHOLD,
    layover_max_seconds: float = LAYOVER_MAX_SECONDS,
) -> CalcResult:
    """Compute vrh_v0 (version 0.3.0) — block-aware Vehicle Revenue Hours.

    Closes divergence D1 (handoff 0003): the FTA includes layover/recovery
    time in VRH (2026 NTD Policy Manual, Exhibit 35), so positions group by
    VRH BLOCK GROUP — a vehicle's trips sharing a GTFS block_id form one
    group spanning consecutive trips, and the elapsed time between the last
    position of trip N and the first position of trip N+1 within the same
    block is INCLUDED, up to ``layover_max_seconds`` (explicit input, default
    1800 — an ENGINEERING PLACEHOLDER pending observed layover
    distributions). An over-cap interval is NOT counted and emits one
    'layover_exceeds_max' warning finding. Trips whose block_id is NULL fall
    back to per-trip grouping (0.2.0 semantics) with one 'block_unavailable'
    info finding per affected vehicle-day (documented undercount; the figure
    stands). Only positions with a trip_id are considered (revenue-service
    proxy, unchanged).

    Gap policy: the within-trip gap rule is UNCHANGED (a within-trip gap >
    ``gap_threshold_seconds`` excludes — no interpolation), but the exclusion
    unit is the block group: one 'telemetry_gap_excluded' warning citing all
    of the group's records. Coverage/threshold machinery is unchanged from
    0.2.0, over block groups: below ``coverage_threshold`` (explicit input,
    default 0.95 — an engineering placeholder, not an FTA number) ONE
    blocking 'coverage_below_threshold' finding is emitted and value=None.

    ``input_record_ids`` covers ALL positions in included block groups.
    Returns a CalcResult with a Decimal value quantized to 0.01 hours
    (ROUND_HALF_EVEN, one final quantization) and a BlockCoverageDetail
    (0.2.0 coverage fields + layover_max_seconds provenance).
    """
    groups = group_block_positions(positions)
    policy = apply_block_gap_policy(
        groups, gap_threshold_seconds, coverage_threshold, layover_max_seconds
    )
    input_ids = block_consumed_record_ids(policy.included)

    total_seconds = Decimal(0)
    layover_warnings: list[Finding] = []
    for group in policy.included:
        seconds, findings = block_group_seconds(group, layover_max_seconds)
        total_seconds += seconds
        layover_warnings.extend(findings)
    warnings = policy.warnings + tuple(layover_warnings)

    if policy.blocking_issues:
        return CalcResult(
            value=None,
            unit=UNIT,
            calc_name=CALC_NAME,
            calc_version=CALC_VERSION,
            input_record_ids=input_ids,
            blocking_issues=policy.blocking_issues,
            warnings=warnings,
            infos=policy.infos,
            detail=policy.detail,
        )

    return CalcResult(
        value=_seconds_to_hours(total_seconds),
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION,
        input_record_ids=input_ids,
        blocking_issues=(),
        warnings=warnings,
        infos=policy.infos,
        detail=policy.detail,
    )


def compute_vrh_v0_2(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
    coverage_threshold: Decimal = COVERAGE_THRESHOLD,
) -> CalcResult:
    """Compute vrh_v0 version 0.2.0 — RETAINED UNCHANGED for reproducibility.

    Groups positions by (vehicle_id, trip_id); considers ONLY positions with a
    trip_id (revenue-service proxy for v0 — a documented approximation); sums
    the time deltas (in hours) between consecutive positions within each
    INCLUDED group ordered by time. Inter-trip time is NOT counted — the
    documented VRH undercount (divergence D1) that 0.3.0 (``compute_vrh``)
    closes with block-aware grouping.

    Gap policy (handoff 0002): identical to vrm_v0 0.2.0 — a group containing
    a gap > ``gap_threshold_seconds`` (explicit input, default 300) is
    EXCLUDED from the figure with one 'telemetry_gap_excluded' warning finding
    citing all of that group's records; coverage (clean_groups/total_groups,
    plus clean-position share) is carried in ``result.detail``; if coverage
    falls below ``coverage_threshold`` (explicit input, default 0.95 — an
    engineering placeholder, not an FTA number), ONE blocking
    'coverage_below_threshold' finding is emitted and value=None.

    ``input_record_ids`` contains ONLY records from included groups. Returns
    a CalcResult with a Decimal value quantized to 0.01 hours
    (ROUND_HALF_EVEN; total seconds are summed exactly, converted to hours in
    Decimal, then quantized once — a documented rounding rule). Superseded as
    the default by 0.3.0 per handoff 0003; kept runnable so historical
    submissions recompute bit-for-bit (versioning discipline: shipped
    versions are never deleted or rewritten).
    """
    groups = group_in_trip_positions(positions)
    policy = apply_gap_exclusion_policy(groups, gap_threshold_seconds, coverage_threshold)
    input_ids = consumed_record_ids(policy.included)

    if policy.blocking_issues:
        return CalcResult(
            value=None,
            unit=UNIT,
            calc_name=CALC_NAME,
            calc_version=CALC_VERSION_0_2_0,
            input_record_ids=input_ids,
            blocking_issues=policy.blocking_issues,
            warnings=policy.warnings,
            detail=policy.detail,
        )

    return CalcResult(
        value=_sum_group_hours(policy.included),
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION_0_2_0,
        input_record_ids=input_ids,
        blocking_issues=(),
        warnings=policy.warnings,
        detail=policy.detail,
    )


def compute_vrh_v0_1(
    positions: Iterable[VehiclePosition],
    gap_threshold_seconds: float = GAP_THRESHOLD_SECONDS,
) -> CalcResult:
    """Compute vrh_v0 version 0.1.0 — RETAINED UNCHANGED for reproducibility.

    The original all-or-nothing gap rule: identical to vrm_v0 0.1.0 — if
    consecutive positions within any group are more than
    ``gap_threshold_seconds`` apart, a blocking 'telemetry_gap' finding names
    the bounding source_record_ids and the result carries value=None.
    Superseded by 0.2.0 (``compute_vrh_v0_2``) per handoff 0002; kept runnable
    so historical submissions recompute bit-for-bit (versioning discipline:
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
        value=_sum_group_hours(groups),
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION_0_1_0,
        input_record_ids=input_ids,
        blocking_issues=(),
    )
