"""Internal shared helpers for position-derived v0 calculations. Stdlib only.

Shared by vrm_v0 and vrh_v0: revenue-service filtering (trip-assignment
proxy), deterministic grouping/ordering, the 0.1.0 fail-loudly gap rule
(find_gap_issues — retained unchanged for historical recomputes), and the
0.2.0 gap policy (apply_gap_exclusion_policy — per-group exclusion + coverage,
handoff 0002). Not a public API; each calculation module remains the
versioned surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable

from headway_calc.types import (
    SEVERITY_BLOCKING,
    SEVERITY_WARNING,
    BlockingIssue,
    CoverageDetail,
    Finding,
    VehiclePosition,
)

#: Default maximum tolerated spacing (seconds) between consecutive in-trip
#: positions. Wider spacing is an unexplained telemetry gap: the calculation
#: refuses to sum across it (no interpolation) and raises a BlockingIssue.
#: This is an explicit input default, not a hidden constant — callers may
#: override it per run, and the value used is part of the run's provenance.
GAP_THRESHOLD_SECONDS: float = 300.0

#: Default certifiability line for calc 0.2.0 (handoff 0002, rule 4): if
#: clean_groups/total_groups falls below this share, the run refuses (one
#: blocking 'coverage_below_threshold' finding, value=None). An ENGINEERING
#: PLACEHOLDER, not an FTA number — an explicit input default pending
#: verification against the current NTD Policy Manual (REGULATORY_TRACKER.md)
#: and, ultimately, per-agency configuration.
COVERAGE_THRESHOLD: Decimal = Decimal("0.95")

#: Quantum for REPORTED coverage ratios (coverage, clean_position_share):
#: 0.0001, ROUND_HALF_EVEN — a documented engineering convention. The
#: threshold COMPARISON never uses the quantized value (see
#: apply_gap_exclusion_policy: exact integer cross-multiplication).
COVERAGE_QUANTUM = Decimal("0.0001")

GroupKey = tuple[str, str]


def group_in_trip_positions(
    positions: Iterable[VehiclePosition],
) -> dict[GroupKey, list[VehiclePosition]]:
    """Group positions by (vehicle_id, trip_id), keeping ONLY in-trip positions.

    Positions with trip_id=None are excluded: for v0, trip assignment is the
    revenue-service proxy (a documented approximation — see the calc module
    docstrings). Within each group, positions are sorted by (time,
    source_record_id) — the record-id tie-break makes ordering deterministic.
    Groups are returned in sorted key order (deterministic iteration).
    """
    groups: dict[GroupKey, list[VehiclePosition]] = {}
    for pos in positions:
        if pos.trip_id is None:
            continue
        groups.setdefault((pos.vehicle_id, pos.trip_id), []).append(pos)
    ordered: dict[GroupKey, list[VehiclePosition]] = {}
    for key in sorted(groups):
        ordered[key] = sorted(groups[key], key=lambda p: (p.time, p.source_record_id))
    return ordered


def find_gap_issues(
    groups: dict[GroupKey, list[VehiclePosition]],
    gap_threshold_seconds: float,
) -> list[BlockingIssue]:
    """Apply the fail-loudly gap rule to every group.

    For each pair of consecutive positions within a group whose time delta
    exceeds ``gap_threshold_seconds``, emit one BlockingIssue of type
    'telemetry_gap' naming the two bounding source_record_ids. No
    interpolation, no partial sum across the gap — the caller must return
    value=None if any issue exists.
    """
    issues: list[BlockingIssue] = []
    for (vehicle_id, trip_id), pts in groups.items():
        for prev, curr in zip(pts, pts[1:]):
            delta_s = (curr.time - prev.time).total_seconds()
            if delta_s > gap_threshold_seconds:
                issues.append(
                    BlockingIssue(
                        issue_type="telemetry_gap",
                        title=(
                            f"Telemetry gap of {delta_s:.0f}s in vehicle "
                            f"{vehicle_id} trip {trip_id}"
                        ),
                        description=(
                            f"Consecutive positions for (vehicle_id={vehicle_id!r}, "
                            f"trip_id={trip_id!r}) are {delta_s:.0f}s apart "
                            f"({prev.time.isoformat()} -> {curr.time.isoformat()}), "
                            f"exceeding the gap threshold of "
                            f"{gap_threshold_seconds:.0f}s. The calculation refuses "
                            f"to interpolate or sum across this gap; resolve the "
                            f"gap (or document its cause) before this figure can "
                            f"be computed."
                        ),
                        source_record_ids=(prev.source_record_id, curr.source_record_id),
                    )
                )
    return issues


def consumed_record_ids(groups: dict[GroupKey, list[VehiclePosition]]) -> tuple[str, ...]:
    """Deterministic, de-duplicated list of source_record_ids consumed."""
    seen: dict[str, None] = {}
    for pts in groups.values():
        for pos in pts:
            seen.setdefault(pos.source_record_id, None)
    return tuple(seen)


@dataclass(frozen=True)
class GapPolicyOutcome:
    """Result of applying the 0.2.0 gap policy to grouped positions.

    ``included`` holds the clean (gap-free) groups the figure may sum over;
    ``warnings`` carries one 'telemetry_gap_excluded' Finding per excluded
    group; ``blocking_issues`` is empty or exactly one
    'coverage_below_threshold' Finding; ``detail`` is the coverage detail the
    result carries (and persist writes to computed.metric_values.detail).
    """

    included: dict[GroupKey, list[VehiclePosition]]
    warnings: tuple[Finding, ...]
    blocking_issues: tuple[Finding, ...]
    detail: CoverageDetail


def _group_gaps(
    pts: list[VehiclePosition], gap_threshold_seconds: float
) -> list[tuple[VehiclePosition, VehiclePosition, float]]:
    """(prev, curr, delta_seconds) for every over-threshold gap in one group."""
    gaps: list[tuple[VehiclePosition, VehiclePosition, float]] = []
    for prev, curr in zip(pts, pts[1:]):
        delta_s = (curr.time - prev.time).total_seconds()
        if delta_s > gap_threshold_seconds:
            gaps.append((prev, curr, delta_s))
    return gaps


def apply_gap_exclusion_policy(
    groups: dict[GroupKey, list[VehiclePosition]],
    gap_threshold_seconds: float,
    coverage_threshold: Decimal,
) -> GapPolicyOutcome:
    """Calc 0.2.0 gap policy (handoff 0002): per-group exclusion + coverage.

    A group containing any gap > ``gap_threshold_seconds`` is EXCLUDED from
    the summed figure — no interpolation, no partial sum across a gap — and
    emits ONE warning Finding ('telemetry_gap_excluded') citing ALL of that
    group's source_record_ids (excluded groups' records are cited here, never
    in input_record_ids/lineage).

    Coverage: ``clean_groups / total_groups`` (clean-position share is also
    reported). If coverage falls below ``coverage_threshold``, ONE blocking
    Finding ('coverage_below_threshold') is emitted — the caller must return
    value=None. The comparison is exact integer cross-multiplication
    (``clean < threshold * total``), never the quantized reported ratio, so
    the threshold line has no rounding error. Empty input (zero groups) is
    full coverage by definition: nothing was excluded.
    """
    coverage_threshold = Decimal(str(coverage_threshold))
    included: dict[GroupKey, list[VehiclePosition]] = {}
    warnings: list[Finding] = []
    excluded_record_ids: dict[str, None] = {}
    clean_positions = 0
    total_positions = 0

    for (vehicle_id, trip_id), pts in groups.items():
        total_positions += len(pts)
        gaps = _group_gaps(pts, gap_threshold_seconds)
        if not gaps:
            included[(vehicle_id, trip_id)] = pts
            clean_positions += len(pts)
            continue
        for pos in pts:
            excluded_record_ids.setdefault(pos.source_record_id, None)
        largest = max(delta_s for _, _, delta_s in gaps)
        first_prev, first_curr, first_delta = gaps[0]
        warnings.append(
            Finding(
                issue_type="telemetry_gap_excluded",
                severity=SEVERITY_WARNING,
                title=(
                    f"Group excluded over telemetry gap of {largest:.0f}s: "
                    f"vehicle {vehicle_id} trip {trip_id}"
                ),
                description=(
                    f"Group (vehicle_id={vehicle_id!r}, trip_id={trip_id!r}) "
                    f"contains {len(gaps)} telemetry gap(s) exceeding the gap "
                    f"threshold of {gap_threshold_seconds:.0f}s (largest "
                    f"{largest:.0f}s; first {first_delta:.0f}s, "
                    f"{first_prev.time.isoformat()} -> "
                    f"{first_curr.time.isoformat()}). Per the calc 0.2.0 gap "
                    f"policy (handoff 0002) the ENTIRE group ({len(pts)} "
                    f"positions) is excluded from the summed figure — no "
                    f"interpolation, no partial sum across a gap — and the "
                    f"exclusion is reported via coverage."
                ),
                source_record_ids=tuple(p.source_record_id for p in pts),
            )
        )

    total_groups = len(groups)
    clean_groups = total_groups - len(warnings)
    excluded_groups = total_groups - clean_groups
    coverage = (
        Decimal(1) if total_groups == 0 else Decimal(clean_groups) / Decimal(total_groups)
    )
    share = (
        Decimal(1)
        if total_positions == 0
        else Decimal(clean_positions) / Decimal(total_positions)
    )
    detail = CoverageDetail(
        coverage=coverage.quantize(COVERAGE_QUANTUM, rounding=ROUND_HALF_EVEN),
        total_groups=total_groups,
        excluded_groups=excluded_groups,
        clean_position_share=share.quantize(COVERAGE_QUANTUM, rounding=ROUND_HALF_EVEN),
        gap_threshold_seconds=float(gap_threshold_seconds),
        coverage_threshold=coverage_threshold,
    )

    blocking_issues: tuple[Finding, ...] = ()
    # Exact threshold line: clean/total < threshold <=> clean < threshold*total.
    if Decimal(clean_groups) < coverage_threshold * Decimal(total_groups):
        blocking_issues = (
            Finding(
                issue_type="coverage_below_threshold",
                severity=SEVERITY_BLOCKING,
                title=(
                    f"Coverage {detail.coverage} below threshold "
                    f"{coverage_threshold}: {excluded_groups} of {total_groups} "
                    f"groups excluded"
                ),
                description=(
                    f"Only {clean_groups} of {total_groups} (vehicle_id, "
                    f"trip_id) groups are free of telemetry gaps > "
                    f"{gap_threshold_seconds:.0f}s: coverage {detail.coverage} "
                    f"(clean-position share {detail.clean_position_share}) is "
                    f"below the certifiability threshold of "
                    f"{coverage_threshold}. The calculation refuses to emit a "
                    f"value at this coverage; resolve (or document) the "
                    f"excluded groups' gaps — or run with an explicitly lower "
                    f"coverage_threshold — before this figure can be computed. "
                    f"The 0.95 default is an engineering placeholder pending "
                    f"FTA-manual verification (REGULATORY_TRACKER.md), not an "
                    f"FTA number."
                ),
                source_record_ids=tuple(excluded_record_ids),
            ),
        )

    return GapPolicyOutcome(
        included=included,
        warnings=tuple(warnings),
        blocking_issues=blocking_issues,
        detail=detail,
    )
