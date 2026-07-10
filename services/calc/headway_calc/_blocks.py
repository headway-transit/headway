"""Internal helpers for block-aware VRH (vrh_v0 CALC_VERSION 0.3.0 and the
0.4.0 trip-level excision refinement). Stdlib only.

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
    TripExcisionCoverageDetail,
    VehiclePosition,
)

#: Default maximum inter-trip interval (seconds) counted as layover within a
#: block. As of handoff 0004 (vrh_v0 0.4.0) this default is DATA-INFORMED and
#: EXHIBIT-ALIGNED, no longer a bare placeholder: the measured MBTA inter-trip
#: interval distribution (2026-07-10, 7,400 in-block intervals: p50 = 30 s,
#: p90 = 109 s, p99 = 7,124 s, 2.7% > 1,800 s) shows a long tail of
#: out-of-service parking, which Exhibit 35 explicitly EXCLUDES from revenue
#: hours ("Bus arrives at the end of the route, parks, and goes out of
#: service… → Vehicle Revenue Hours: No"). Still not an FTA-published number —
#: an explicit, per-agency-configurable input default (REGULATORY_TRACKER.md,
#: vrh_v0 0.4.0; the manual's "10 to 20 percent of the running time", p. 128,
#: is descriptive, not a cap). An interval exceeding it is NOT counted and
#: emits one 'layover_exceeds_max' warning finding (vehicle possibly out of
#: service mid-block).
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


# --------------------------------------------------------------------------
# vrh_v0 CALC_VERSION 0.4.0 — trip-level excision (handoff 0004). The 0.3.0
# machinery above is deliberately untouched: shipped versions recompute
# bit-for-bit (compute_vrh_v0_3 keeps calling it).
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ExcisedBlockGroup:
    """One block group after 0.4.0 trip-level excision.

    ``clean`` is a per-trip flag tuple aligned with ``group.trips``: True for
    trips free of within-trip gaps (their running time counts), False for
    excised trips. Adjacency for layover accounting is judged on the ORIGINAL
    trip sequence — an excised trip's neighbors are never bridged.
    """

    group: BlockGroup
    clean: tuple[bool, ...]

    @property
    def clean_trip_positions(self) -> tuple[VehiclePosition, ...]:
        return tuple(
            p
            for (_, pts), ok in zip(self.group.trips, self.clean)
            if ok
            for p in pts
        )


def excised_consumed_record_ids(
    excised_groups: Iterable[ExcisedBlockGroup],
) -> tuple[str, ...]:
    """Deterministic, de-duplicated record ids of INCLUDED (clean) trips only.

    Excised trips' records are cited by their 'telemetry_gap_excluded'
    findings instead — they never reach input_record_ids/lineage (handoff
    0002 rule 5, unchanged in spirit; the unit is now the trip)."""
    seen: dict[str, None] = {}
    for eg in excised_groups:
        for pos in eg.clean_trip_positions:
            seen.setdefault(pos.source_record_id, None)
    return tuple(seen)


def excised_group_seconds(
    excised: ExcisedBlockGroup, layover_max_seconds: float
) -> tuple[Decimal, list[Finding]]:
    """Exact VRH seconds of ONE trip-excised block group + layover findings.

    Clean trips contribute their 0.2.0 running time (time deltas between
    consecutive positions). An inter-trip layover interval contributes only
    when BOTH bounding trips are clean (handoff 0004: an interval adjacent to
    an excised trip is dropped — the gap makes the vehicle's whereabouts over
    that interval unaccounted for; the drop is tallied in the detail's
    layover_intervals_dropped, no finding). A counted interval follows the
    0.3.0 rule: included up to ``layover_max_seconds``; an over-cap interval
    is NOT counted and emits one 'layover_exceeds_max' warning; a
    non-positive interval contributes nothing and never subtracts. Excised
    trips are never bridged: the interval between trip N-1 and trip N+1
    around an excised trip N does not exist.
    """
    total_seconds = Decimal(0)
    findings: list[Finding] = []
    group = excised.group
    for (_, pts), ok in zip(group.trips, excised.clean):
        if not ok:
            continue
        for prev, curr in zip(pts, pts[1:]):
            total_seconds += Decimal(str((curr.time - prev.time).total_seconds()))
    for i in range(len(group.trips) - 1):
        if not (excised.clean[i] and excised.clean[i + 1]):
            continue  # adjacent to an excised trip: dropped, tallied in detail
        trip_n, pts_n = group.trips[i]
        trip_n1, pts_n1 = group.trips[i + 1]
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
                        f"counted toward VRH — the long tail of the measured "
                        f"inter-trip distribution is out-of-service parking, "
                        f"which Exhibit 35 excludes from revenue hours. The "
                        f"1800s default is data-informed and exhibit-aligned "
                        f"(REGULATORY_TRACKER.md, vrh_v0 0.4.0), per-agency "
                        f"configurable, not an FTA-published number."
                    ),
                    source_record_ids=(last.source_record_id, first.source_record_id),
                )
            )
        elif delta_s > 0:
            total_seconds += Decimal(str(delta_s))
    return total_seconds, findings


@dataclass(frozen=True)
class TripExcisionPolicyOutcome:
    """Result of applying the 0.4.0 trip-excision policy to block groups.

    ``included`` holds the groups retaining at least one clean trip, each
    with its per-trip clean flags; ``warnings`` carries one
    'telemetry_gap_excluded' Finding PER EXCISED TRIP (citing that trip's
    records only); ``blocking_issues`` is empty or exactly one
    'coverage_below_threshold' Finding (trip-denominated); ``infos`` is the
    unchanged per-vehicle-day 'block_unavailable' fallback documentation.
    """

    included: tuple[ExcisedBlockGroup, ...]
    warnings: tuple[Finding, ...]
    infos: tuple[Finding, ...]
    blocking_issues: tuple[Finding, ...]
    detail: TripExcisionCoverageDetail


def apply_trip_excision_policy(
    groups: tuple[BlockGroup, ...],
    gap_threshold_seconds: float,
    coverage_threshold: Decimal,
    layover_max_seconds: float,
) -> TripExcisionPolicyOutcome:
    """Calc 0.4.0 gap policy (handoff 0004): trip-level excision.

    The within-trip gap rule is unchanged (a gap > ``gap_threshold_seconds``
    between consecutive positions inside a trip's running time) — but the
    exclusion unit is refined from the block group to THE GAPPED TRIP PLUS
    ITS ADJACENT LAYOVER INTERVALS: the trip's running time is excised, the
    inter-trip intervals immediately adjacent to it (both sides, where
    present) are dropped (a layover interval counts only when BOTH bounding
    trips are clean), and the block's remaining clean trips and their other
    layover intervals stay in the figure. One 'telemetry_gap_excluded'
    warning Finding PER EXCISED TRIP, citing that trip's records.

    Coverage returns to TRIP denomination: ``clean_trips / total_trips``
    (directly comparable to 0.2.0's group coverage), exact integer
    cross-multiplication at the threshold line, one blocking
    'coverage_below_threshold' Finding below ``coverage_threshold`` — the
    0.2.0 machinery with the trip as the unit. The detail carries the trip
    coverage, the block statistics (blocks_touched, trips_excised,
    layover_intervals_dropped) and all three thresholds. ``infos`` is the
    unchanged 0.3.0 per-vehicle-day 'block_unavailable' documentation.
    """
    coverage_threshold = Decimal(str(coverage_threshold))
    included: list[ExcisedBlockGroup] = []
    warnings: list[Finding] = []
    excluded_record_ids: dict[str, None] = {}
    clean_positions = 0
    total_positions = 0
    total_trips = 0
    clean_trips = 0
    blocks_touched = 0
    layover_intervals_dropped = 0
    fully_excised_groups = 0

    for group in groups:
        flags: list[bool] = []
        for trip_id, pts in group.trips:
            total_trips += 1
            total_positions += len(pts)
            gaps = _group_gaps(list(pts), gap_threshold_seconds)
            if not gaps:
                flags.append(True)
                clean_trips += 1
                clean_positions += len(pts)
                continue
            flags.append(False)
            for pos in pts:
                excluded_record_ids.setdefault(pos.source_record_id, None)
            largest = max(delta_s for _, _, delta_s in gaps)
            first_prev, first_curr, first_delta = gaps[0]
            where = (
                f"vehicle {group.vehicle_id} block {group.block_id} "
                f"trip {trip_id}"
                if group.block_id is not None
                else f"vehicle {group.vehicle_id} trip {trip_id}"
            )
            warnings.append(
                Finding(
                    issue_type="telemetry_gap_excluded",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Trip excised over telemetry gap of {largest:.0f}s: "
                        f"{where}"
                    ),
                    description=(
                        f"Trip {trip_id!r} of {group.label} contains "
                        f"{len(gaps)} within-trip telemetry gap(s) exceeding "
                        f"the gap threshold of {gap_threshold_seconds:.0f}s "
                        f"(largest {largest:.0f}s; first {first_delta:.0f}s, "
                        f"{first_prev.time.isoformat()} -> "
                        f"{first_curr.time.isoformat()}). Per the calc 0.4.0 "
                        f"gap policy (handoff 0004; within-trip rule unchanged "
                        f"from 0.2.0, exclusion unit refined from the block "
                        f"group to the gapped trip) this trip's running time "
                        f"({len(pts)} positions) AND its adjacent inter-trip "
                        f"layover intervals are excised from the summed figure "
                        f"— no interpolation, no partial sum across a gap — "
                        f"while the block's remaining clean trips stay. The "
                        f"exclusion is reported via trip-denominated coverage."
                    ),
                    source_record_ids=tuple(p.source_record_id for p in pts),
                )
            )
        clean_flags = tuple(flags)
        if not all(clean_flags):
            if group.block_id is not None:
                blocks_touched += 1
            for i in range(len(clean_flags) - 1):
                if not (clean_flags[i] and clean_flags[i + 1]):
                    layover_intervals_dropped += 1
            if not any(clean_flags):
                fully_excised_groups += 1
        if any(clean_flags):
            included.append(ExcisedBlockGroup(group, clean_flags))

    trips_excised = total_trips - clean_trips
    coverage = (
        Decimal(1) if total_trips == 0 else Decimal(clean_trips) / Decimal(total_trips)
    )
    share = (
        Decimal(1)
        if total_positions == 0
        else Decimal(clean_positions) / Decimal(total_positions)
    )
    detail = TripExcisionCoverageDetail(
        coverage=coverage.quantize(COVERAGE_QUANTUM, rounding=ROUND_HALF_EVEN),
        total_groups=len(groups),
        excluded_groups=fully_excised_groups,
        clean_position_share=share.quantize(COVERAGE_QUANTUM, rounding=ROUND_HALF_EVEN),
        gap_threshold_seconds=float(gap_threshold_seconds),
        coverage_threshold=coverage_threshold,
        layover_max_seconds=float(layover_max_seconds),
        total_trips=total_trips,
        trips_excised=trips_excised,
        blocks_touched=blocks_touched,
        layover_intervals_dropped=layover_intervals_dropped,
    )

    blocking_issues: tuple[Finding, ...] = ()
    # Exact threshold line: clean/total < threshold <=> clean < threshold*total.
    if Decimal(clean_trips) < coverage_threshold * Decimal(total_trips):
        blocking_issues = (
            Finding(
                issue_type="coverage_below_threshold",
                severity=SEVERITY_BLOCKING,
                title=(
                    f"Coverage {detail.coverage} below threshold "
                    f"{coverage_threshold}: {trips_excised} of {total_trips} "
                    f"trips excised"
                ),
                description=(
                    f"Only {clean_trips} of {total_trips} trips are free of "
                    f"within-trip telemetry gaps > "
                    f"{gap_threshold_seconds:.0f}s: trip-denominated coverage "
                    f"{detail.coverage} (clean-position share "
                    f"{detail.clean_position_share}) is below the "
                    f"certifiability threshold of {coverage_threshold}. The "
                    f"calculation refuses to emit a value at this coverage; "
                    f"resolve (or document) the excised trips' gaps — or run "
                    f"with an explicitly lower coverage_threshold — before "
                    f"this figure can be computed. The 0.95 default is an "
                    f"engineering placeholder pending FTA-manual verification "
                    f"(REGULATORY_TRACKER.md), not an FTA number."
                ),
                source_record_ids=tuple(excluded_record_ids),
            ),
        )

    return TripExcisionPolicyOutcome(
        included=tuple(included),
        warnings=tuple(warnings),
        infos=_block_unavailable_infos(groups),
        blocking_issues=blocking_issues,
        detail=detail,
    )
