"""Internal shared helpers for position-derived v0 calculations. Stdlib only.

Shared by vrm_v0 and vrh_v0: revenue-service filtering (trip-assignment
proxy), deterministic grouping/ordering, and the fail-loudly gap rule.
Not a public API; each calculation module remains the versioned surface.
"""

from __future__ import annotations

from typing import Iterable

from headway_calc.types import BlockingIssue, VehiclePosition

#: Default maximum tolerated spacing (seconds) between consecutive in-trip
#: positions. Wider spacing is an unexplained telemetry gap: the calculation
#: refuses to sum across it (no interpolation) and raises a BlockingIssue.
#: This is an explicit input default, not a hidden constant — callers may
#: override it per run, and the value used is part of the run's provenance.
GAP_THRESHOLD_SECONDS: float = 300.0

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
