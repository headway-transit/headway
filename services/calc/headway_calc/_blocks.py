"""Internal helpers for block-aware VRH (vrh_v0 CALC_VERSION 0.3.0). Stdlib only.

Handoff 0003, closing divergence D1 (REGULATORY_TRACKER.md): FTA INCLUDES
layover/recovery time in Vehicle Revenue Hours (2026 NTD Policy Manual,
Exhibit 35, manual p. 133; layover "typically ranges from 10 to 20 percent of
the running time", p. 128), so per-(vehicle_id, trip_id) grouping drops
inter-trip time and systematically undercounts VRH. GTFS ``block_id``
(trips.txt, OPTIONAL field — GTFS Schedule Reference, gtfs.org, verified
2026-07-09: "A block consists of a single trip or many sequential trips made
using the same vehicle, defined by shared service days and block_id") is the
schedule-native way to group a vehicle's consecutive trips: the interval
between them is layover BY DEFINITION, not telemetry interpolation — elapsed
wall-time between observed endpoints is measured, never inferred.

Not a public API; headway_calc.vrh remains the versioned surface. The
0.1.0/0.2.0 machinery in headway_calc._grouping is deliberately untouched —
shipped versions recompute bit-for-bit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable

from headway_calc._grouping import COVERAGE_QUANTUM, _group_gaps
from headway_calc.types import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    BlockCoverageDetail,
    Finding,
    VehiclePosition,
)

#: Default maximum inter-trip interval (seconds) counted as layover within a
#: block. An ENGINEERING PLACEHOLDER, not an FTA number — an explicit input
#: default pending observed layover distributions (the manual's "10 to 20
#: percent of the running time", p. 128, is descriptive, not a cap; see
#: REGULATORY_TRACKER.md, vrh_v0 0.3.0). An interval exceeding it is NOT
#: counted and emits one 'layover_exceeds_max' warning finding (vehicle
#: possibly out of service mid-block).
LAYOVER_MAX_SECONDS: float = 1800.0


@dataclass(frozen=True)
class BlockGroup:
    """One VRH group (calc 0.3.0): either a vehicle's trips sharing a non-NULL
    block_id, in block order, or a single NULL-block trip (per-trip fallback —
    0.2.0 semantics). ``trips`` pairs each trip_id with its time-ordered
    positions."""

    vehicle_id: str
    block_id: str | None
    trips: tuple[tuple[str, tuple[VehiclePosition, ...]], ...]

    @property
    def trip_ids(self) -> tuple[str, ...]:
        return tuple(trip_id for trip_id, _ in self.trips)

    @property
    def positions(self) -> tuple[VehiclePosition, ...]:
        return tuple(p for _, pts in self.trips for p in pts)

    @property
    def label(self) -> str:
        """Human-readable group identity for finding titles/descriptions."""
        if self.block_id is None:
            return f"vehicle {self.vehicle_id} trip {self.trip_ids[0]}"
        return f"vehicle {self.vehicle_id} block {self.block_id}"


def group_block_positions(
    positions: Iterable[VehiclePosition],
) -> tuple[BlockGroup, ...]:
    """Group in-trip positions into VRH block groups (calc 0.3.0).

    Same revenue-service proxy as 0.2.0: positions with trip_id=None are
    excluded (documented approximation; a null-trip position temporally inside
    a block's span is IGNORED for VRH — the conservative choice recorded as a
    handoff-0003 open question). Positions first group per (vehicle_id,
    trip_id), sorted by (time, source_record_id); a vehicle's trips sharing a
    non-NULL block_id then merge into ONE group with trips ordered by (first
    position time, trip_id), and each NULL-block trip stays its own group
    (0.2.0 fallback). Groups are returned in a deterministic order.

    Fails loudly (ValueError) if one (vehicle_id, trip_id) carries
    inconsistent block_ids — canonical.trips holds one block_id per trip, so
    contradictory input is a data-integrity violation, never resolved by a
    guess.
    """
    by_trip: dict[tuple[str, str], list[VehiclePosition]] = {}
    block_by_trip: dict[tuple[str, str], str | None] = {}
    for pos in positions:
        if pos.trip_id is None:
            continue
        key = (pos.vehicle_id, pos.trip_id)
        if key not in block_by_trip:
            block_by_trip[key] = pos.block_id
        elif block_by_trip[key] != pos.block_id:
            raise ValueError(
                f"Inconsistent block_id for (vehicle_id={key[0]!r}, "
                f"trip_id={key[1]!r}): {block_by_trip[key]!r} vs "
                f"{pos.block_id!r} (source_record_id="
                f"{pos.source_record_id!r}). canonical.trips carries one "
                f"block_id per trip; refusing to group over contradictory "
                f"input."
            )
        by_trip.setdefault(key, []).append(pos)

    groups: list[BlockGroup] = []
    blocks: dict[tuple[str, str], list[tuple[str, tuple[VehiclePosition, ...]]]] = {}
    for key in sorted(by_trip):
        vehicle_id, trip_id = key
        pts = tuple(sorted(by_trip[key], key=lambda p: (p.time, p.source_record_id)))
        block_id = block_by_trip[key]
        if block_id is None:
            groups.append(BlockGroup(vehicle_id, None, ((trip_id, pts),)))
        else:
            blocks.setdefault((vehicle_id, block_id), []).append((trip_id, pts))
    for (vehicle_id, block_id), trips in blocks.items():
        trips.sort(key=lambda item: (item[1][0].time, item[0]))
        groups.append(BlockGroup(vehicle_id, block_id, tuple(trips)))

    groups.sort(key=lambda g: (g.vehicle_id, g.block_id or "", g.trip_ids))
    return tuple(groups)


def block_consumed_record_ids(groups: Iterable[BlockGroup]) -> tuple[str, ...]:
    """Deterministic, de-duplicated list of source_record_ids consumed."""
    seen: dict[str, None] = {}
    for group in groups:
        for pos in group.positions:
            seen.setdefault(pos.source_record_id, None)
    return tuple(seen)


def block_group_seconds(
    group: BlockGroup, layover_max_seconds: float
) -> tuple[Decimal, list[Finding]]:
    """Exact VRH seconds of ONE block group, plus its layover findings.

    Within-trip time is the 0.2.0 rule unchanged: time deltas between
    consecutive positions of each trip. Inter-trip time — elapsed wall-time
    between the last position of trip N and the first position of trip N+1
    within the same block — is layover BY DEFINITION (Exhibit 35) and is
    INCLUDED up to ``layover_max_seconds``. An interval exceeding the cap is
    NOT counted and emits one 'layover_exceeds_max' warning finding naming
    the bounding records (vehicle possibly out of service mid-block); a
    non-positive interval (overlapping telemetry between trips) contributes
    nothing and never subtracts.
    """
    total_seconds = Decimal(0)
    findings: list[Finding] = []
    for _, pts in group.trips:
        for prev, curr in zip(pts, pts[1:]):
            total_seconds += Decimal(str((curr.time - prev.time).total_seconds()))
    for (trip_n, pts_n), (trip_n1, pts_n1) in zip(group.trips, group.trips[1:]):
        last, first = pts_n[-1], pts_n1[0]
        delta_s = (first.time - last.time).total_seconds()
        if delta_s > layover_max_seconds:
            findings.append(
                Finding(
                    issue_type="layover_exceeds_max",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Layover of {delta_s:.0f}s exceeds "
                        f"layover_max_seconds in {group.label}"
                    ),
                    description=(
                        f"Inter-trip interval between trip {trip_n!r} and "
                        f"trip {trip_n1!r} of {group.label} is {delta_s:.0f}s "
                        f"({last.time.isoformat()} -> {first.time.isoformat()}), "
                        f"exceeding layover_max_seconds "
                        f"{layover_max_seconds:.0f}s. The interval is NOT "
                        f"counted toward VRH — the vehicle was possibly out "
                        f"of service mid-block. The 1800s default is an "
                        f"ENGINEERING PLACEHOLDER pending observed layover "
                        f"distributions (REGULATORY_TRACKER.md), not an FTA "
                        f"number."
                    ),
                    source_record_ids=(last.source_record_id, first.source_record_id),
                )
            )
        elif delta_s > 0:
            total_seconds += Decimal(str(delta_s))
    return total_seconds, findings


@dataclass(frozen=True)
class BlockGapPolicyOutcome:
    """Result of applying the 0.3.0 gap policy to block groups.

    Same shape as the 0.2.0 GapPolicyOutcome — ``included`` holds the clean
    groups the figure may sum over, ``warnings`` carries one
    'telemetry_gap_excluded' Finding per excluded group, ``blocking_issues``
    is empty or exactly one 'coverage_below_threshold' Finding — plus
    ``infos``: one 'block_unavailable' Finding per vehicle-day whose trips
    fell back to per-trip grouping (block_id NULL, documented undercount).
    """

    included: tuple[BlockGroup, ...]
    warnings: tuple[Finding, ...]
    infos: tuple[Finding, ...]
    blocking_issues: tuple[Finding, ...]
    detail: BlockCoverageDetail


def _block_unavailable_infos(groups: tuple[BlockGroup, ...]) -> tuple[Finding, ...]:
    """One info Finding per (vehicle, UTC day) with NULL-block fallback groups.

    Fallback groups keep 0.2.0 per-trip semantics, so the layover between
    those trips is NOT counted — a documented undercount (FTA includes layover
    in VRH, Exhibit 35), not an exclusion: the trips' running time still
    counts and the figure stands. Absent block_id is valid GTFS (the field is
    optional), hence info severity, not a warning.
    """
    fallback: dict[tuple[str, date], list[BlockGroup]] = {}
    for group in groups:
        if group.block_id is not None:
            continue
        day = group.positions[0].time.astimezone(timezone.utc).date()
        fallback.setdefault((group.vehicle_id, day), []).append(group)

    infos: list[Finding] = []
    for (vehicle_id, day), day_groups in sorted(fallback.items()):
        trip_ids = tuple(tid for g in day_groups for tid in g.trip_ids)
        record_ids = block_consumed_record_ids(day_groups)
        infos.append(
            Finding(
                issue_type="block_unavailable",
                severity=SEVERITY_INFO,
                title=(
                    f"No block_id for vehicle {vehicle_id} on "
                    f"{day.isoformat()}: per-trip VRH fallback "
                    f"({len(day_groups)} trip(s))"
                ),
                description=(
                    f"Trips {', '.join(repr(t) for t in trip_ids)} of vehicle "
                    f"{vehicle_id} on {day.isoformat()} (UTC) carry no GTFS "
                    f"block_id in canonical.trips, so VRH grouped them "
                    f"per-trip (calc 0.2.0 semantics) instead of per-block. "
                    f"Inter-trip layover time for these trips is therefore "
                    f"NOT counted — a documented undercount: the FTA includes "
                    f"layover/recovery time in Vehicle Revenue Hours (2026 "
                    f"NTD Policy Manual, Exhibit 35). block_id is optional "
                    f"per the GTFS spec, so this is valid input, not a data "
                    f"error; the figure stands and includes each trip's "
                    f"running time."
                ),
                source_record_ids=record_ids,
            )
        )
    return tuple(infos)


def apply_block_gap_policy(
    groups: tuple[BlockGroup, ...],
    gap_threshold_seconds: float,
    coverage_threshold: Decimal,
    layover_max_seconds: float,
) -> BlockGapPolicyOutcome:
    """Calc 0.3.0 gap policy (handoff 0003): the 0.2.0 per-group exclusion +
    coverage machinery UNCHANGED, with the block group as the exclusion unit.

    The within-trip gap rule is unchanged (a gap > ``gap_threshold_seconds``
    between consecutive positions INSIDE a trip's running time) — but a group
    containing any such gap in ANY of its trips is excluded WHOLE: one
    'telemetry_gap_excluded' warning Finding citing ALL of the group's
    records. Inter-trip intervals are never telemetry gaps — block membership
    makes them layover by definition, governed solely by
    ``layover_max_seconds`` (see block_group_seconds).

    Coverage: ``clean_groups / total_groups`` over VRH block groups
    (clean-position share also reported), exact integer cross-multiplication
    at the threshold line, one blocking 'coverage_below_threshold' Finding
    below ``coverage_threshold`` — identical machinery to 0.2.0. ``infos``
    carries the per-vehicle-day 'block_unavailable' fallback documentation.
    """
    coverage_threshold = Decimal(str(coverage_threshold))
    included: list[BlockGroup] = []
    warnings: list[Finding] = []
    excluded_record_ids: dict[str, None] = {}
    clean_positions = 0
    total_positions = 0

    for group in groups:
        pts_all = group.positions
        total_positions += len(pts_all)
        gaps = [
            (trip_id, prev, curr, delta_s)
            for trip_id, pts in group.trips
            for prev, curr, delta_s in _group_gaps(list(pts), gap_threshold_seconds)
        ]
        if not gaps:
            included.append(group)
            clean_positions += len(pts_all)
            continue
        for pos in pts_all:
            excluded_record_ids.setdefault(pos.source_record_id, None)
        largest = max(delta_s for _, _, _, delta_s in gaps)
        first_trip, first_prev, first_curr, first_delta = gaps[0]
        warnings.append(
            Finding(
                issue_type="telemetry_gap_excluded",
                severity=SEVERITY_WARNING,
                title=(
                    f"Group excluded over telemetry gap of {largest:.0f}s: "
                    f"{group.label}"
                ),
                description=(
                    f"VRH group ({group.label}, trips "
                    f"{', '.join(repr(t) for t in group.trip_ids)}) contains "
                    f"{len(gaps)} within-trip telemetry gap(s) exceeding the "
                    f"gap threshold of {gap_threshold_seconds:.0f}s (largest "
                    f"{largest:.0f}s; first {first_delta:.0f}s in trip "
                    f"{first_trip!r}, {first_prev.time.isoformat()} -> "
                    f"{first_curr.time.isoformat()}). Per the calc 0.3.0 gap "
                    f"policy (handoff 0003; within-trip rule unchanged from "
                    f"0.2.0, exclusion unit now the block group) the ENTIRE "
                    f"group ({len(pts_all)} positions) is excluded from the "
                    f"summed figure — no interpolation, no partial sum across "
                    f"a gap — and the exclusion is reported via coverage."
                ),
                source_record_ids=tuple(p.source_record_id for p in pts_all),
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
    detail = BlockCoverageDetail(
        coverage=coverage.quantize(COVERAGE_QUANTUM, rounding=ROUND_HALF_EVEN),
        total_groups=total_groups,
        excluded_groups=excluded_groups,
        clean_position_share=share.quantize(COVERAGE_QUANTUM, rounding=ROUND_HALF_EVEN),
        gap_threshold_seconds=float(gap_threshold_seconds),
        coverage_threshold=coverage_threshold,
        layover_max_seconds=float(layover_max_seconds),
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
                    f"Only {clean_groups} of {total_groups} VRH block groups "
                    f"are free of within-trip telemetry gaps > "
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

    return BlockGapPolicyOutcome(
        included=tuple(included),
        warnings=tuple(warnings),
        infos=_block_unavailable_infos(groups),
        blocking_issues=blocking_issues,
        detail=detail,
    )
