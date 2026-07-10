"""Unit tests for the vrh_v0 0.4.0 trip-excision mechanics (handoff 0004).

Covers, with hand-built positions: the refined exclusion unit (gapped trip +
BOTH adjacent layover intervals; the block's clean remainder stays,
including layover intervals between clean-adjacent trips); one
telemetry_gap_excluded warning PER excised trip citing that trip's records
only; edge-trip excision (only one adjacent interval exists); adjacent
gapped trips; a fully-excised block; the NULL-block fallback under trip
excision; lineage narrowing to included positions; the retained layover cap
on surviving intervals; and trip-denominated coverage/blocking. No live
database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from headway_calc.types import VehiclePosition
from headway_calc.vrh import compute_vrh, compute_vrh_v0_2, compute_vrh_v0_3

T0 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

#: A coverage threshold of 0 never blocks — it isolates the excision
#: arithmetic from the certifiability line (same convention as the 0.2.0 and
#: 0.3.0 suites).
NEVER_BLOCK = Decimal("0")


def _trip(
    vehicle_id: str,
    trip_id: str,
    block_id: str | None,
    start: datetime,
    n: int = 4,
    spacing_s: int = 60,
) -> list[VehiclePosition]:
    """One clean trip: n positions, fixed spacing, stationary coordinates.
    Running time = (n - 1) * spacing_s (default 180 s)."""
    return [
        VehiclePosition(
            time=start + timedelta(seconds=i * spacing_s),
            vehicle_id=vehicle_id,
            trip_id=trip_id,
            latitude=40.0,
            longitude=-75.0,
            source_record_id=f"rec-{trip_id}-{i:02d}",
            block_id=block_id,
        )
        for i in range(n)
    ]


def _gap_position(after: list[VehiclePosition], gap_s: int) -> VehiclePosition:
    """A position gap_s after a trip's last one — injects a within-trip gap."""
    last = after[-1]
    return VehiclePosition(
        time=last.time + timedelta(seconds=gap_s),
        vehicle_id=last.vehicle_id,
        trip_id=last.trip_id,
        latitude=last.latitude,
        longitude=last.longitude,
        source_record_id=f"rec-{last.trip_id}-after-gap",
        block_id=last.block_id,
    )


def _three_trip_block(gapped: str | None) -> list[VehiclePosition]:
    """veh-1 / blk-1: three 180 s trips with 600 s layovers; optionally
    inject a 400 s within-trip gap into the named trip."""
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180 + 600))
    trip_3 = _trip(
        "veh-1", "trip-3", "blk-1", T0 + timedelta(seconds=2 * (180 + 600))
    )
    trips = {"trip-1": trip_1, "trip-2": trip_2, "trip-3": trip_3}
    if gapped is not None:
        trips[gapped].append(_gap_position(trips[gapped], 400))
    return trip_1 + trip_2 + trip_3


def test_middle_trip_excision_drops_both_adjacent_layovers():
    """Gap in trip-2: trips 1+3's running time stays, trip-2 and BOTH
    layovers go — and the excised trip is never bridged."""
    positions = _three_trip_block(gapped="trip-2")
    result = compute_vrh(positions, coverage_threshold=NEVER_BLOCK)

    assert result.calc_version == "0.4.0"
    assert result.blocking_issues == ()
    # 2 x 180 s clean running time only: no layover interval survives.
    assert result.value == Decimal("0.10")
    assert result.detail.total_trips == 3
    assert result.detail.trips_excised == 1
    assert result.detail.blocks_touched == 1
    assert result.detail.layover_intervals_dropped == 2
    assert result.detail.excluded_groups == 0  # the block still contributes
    assert result.detail.coverage == Decimal("0.6667")

    # The retained v0.3 drops the WHOLE block; v0.4 recovers 360 s.
    v03 = compute_vrh_v0_3(positions, coverage_threshold=NEVER_BLOCK)
    assert v03.value == Decimal("0.00")
    assert result.value > v03.value


def test_edge_trip_excision_keeps_the_far_layover():
    """Gap in trip-1 (an edge trip: only ONE adjacent interval exists):
    layover 1-2 is dropped, layover 2-3 stays (both bounding trips clean)."""
    positions = _three_trip_block(gapped="trip-1")
    result = compute_vrh(positions, coverage_threshold=NEVER_BLOCK)

    # trips 2+3 running (360 s) + the surviving 600 s layover = 960 s.
    assert result.value == Decimal("0.27")
    assert result.detail.trips_excised == 1
    assert result.detail.layover_intervals_dropped == 1

    # v0.4 >= v0.2 strictly here: v0.2 never counted the surviving layover.
    v02 = compute_vrh_v0_2(positions, coverage_threshold=NEVER_BLOCK)
    assert v02.value == Decimal("0.10")
    assert result.value > v02.value


def test_one_warning_per_excised_trip_citing_that_trips_records_only():
    positions = _three_trip_block(gapped="trip-2")
    trip_2_ids = {
        p.source_record_id for p in positions if p.trip_id == "trip-2"
    }
    result = compute_vrh(positions, coverage_threshold=NEVER_BLOCK)

    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.issue_type == "telemetry_gap_excluded"
    assert warning.severity == "warning"
    assert "trip-2" in warning.title and "blk-1" in warning.title
    # ONLY the excised trip's records — never its clean neighbors'.
    assert set(warning.source_record_ids) == trip_2_ids

    # Lineage = included positions only.
    assert set(result.input_record_ids) == {
        p.source_record_id for p in positions if p.trip_id != "trip-2"
    }


def test_two_gapped_trips_emit_two_warnings_and_drop_their_intervals():
    """Gaps in trips 1 and 2: two warnings (one per trip), both layover
    intervals dropped (1-2 has two gapped bounds — dropped once), only
    trip-3's running time stands."""
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180 + 600))
    trip_3 = _trip(
        "veh-1", "trip-3", "blk-1", T0 + timedelta(seconds=2 * (180 + 600))
    )
    trip_1.append(_gap_position(trip_1, 400))
    trip_2.append(_gap_position(trip_2, 500))
    result = compute_vrh(trip_1 + trip_2 + trip_3, coverage_threshold=NEVER_BLOCK)

    assert result.value == Decimal("0.05")  # trip-3's 180 s only
    assert [w.issue_type for w in result.warnings] == [
        "telemetry_gap_excluded",
        "telemetry_gap_excluded",
    ]
    assert result.detail.trips_excised == 2
    assert result.detail.layover_intervals_dropped == 2
    assert result.detail.blocks_touched == 1


def test_fully_excised_block_contributes_nothing_and_counts_as_excluded():
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180 + 600))
    trip_1.append(_gap_position(trip_1, 400))
    trip_2.append(_gap_position(trip_2, 400))
    # A second, clean vehicle keeps the figure alive.
    clean = _trip("veh-2", "trip-9", "blk-9", T0)
    result = compute_vrh(
        trip_1 + trip_2 + clean, coverage_threshold=NEVER_BLOCK
    )

    assert result.value == Decimal("0.05")  # veh-2's 180 s
    assert result.detail.total_groups == 2
    assert result.detail.excluded_groups == 1  # blk-1: every trip excised
    assert result.detail.blocks_touched == 1
    assert result.detail.trips_excised == 2
    # No blk-1 record reaches lineage.
    assert all(rid.startswith("rec-trip-9") for rid in result.input_record_ids)


def test_null_block_fallback_excises_per_trip_and_keeps_the_info():
    """A gapped NULL-block trip is excised exactly like 0.2.0 (the fallback
    group IS one trip); block_unavailable info documentation is unchanged and
    blocks_touched stays 0 (no block was touched)."""
    trip_1 = _trip("veh-1", "trip-1", None, T0)
    trip_2 = _trip("veh-1", "trip-2", None, T0 + timedelta(seconds=180 + 600))
    trip_2.append(_gap_position(trip_2, 400))
    result = compute_vrh(trip_1 + trip_2, coverage_threshold=NEVER_BLOCK)

    assert result.value == Decimal("0.05")  # trip-1's 180 s, no layover
    assert result.detail.total_trips == 2
    assert result.detail.trips_excised == 1
    assert result.detail.blocks_touched == 0
    assert result.detail.layover_intervals_dropped == 0
    assert result.detail.excluded_groups == 1  # trip-2's fallback group
    assert [i.issue_type for i in result.infos] == ["block_unavailable"]
    assert [w.issue_type for w in result.warnings] == ["telemetry_gap_excluded"]
    assert "vehicle veh-1 trip trip-2" in result.warnings[0].title


def test_surviving_layover_still_capped_with_warning():
    """The 0.3.0 layover cap governs intervals between clean-adjacent trips
    unchanged: over-cap interval NOT counted + one layover_exceeds_max
    warning naming the bounding records."""
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180 + 2000))
    result = compute_vrh(trip_1 + trip_2)

    assert result.value == Decimal("0.10")  # 360 s running, 2000 s > 1800 cap
    assert [w.issue_type for w in result.warnings] == ["layover_exceeds_max"]
    assert result.warnings[0].source_record_ids == (
        "rec-trip-1-03",
        "rec-trip-2-00",
    )
    assert result.detail.layover_intervals_dropped == 0  # capped, not excised


def test_trip_denominated_coverage_drives_the_blocking_line():
    """2 clean of 3 trips: 2/3 passes an explicit 0.6 threshold exactly as a
    trip ratio (the 0.3.0 block ratio would have been 0/1 — blocked)."""
    positions = _three_trip_block(gapped="trip-2")
    passing = compute_vrh(positions, coverage_threshold=Decimal("0.6"))
    assert passing.blocking_issues == ()
    assert passing.value == Decimal("0.10")

    blocked = compute_vrh(positions, coverage_threshold=Decimal("0.95"))
    assert blocked.value is None
    assert len(blocked.blocking_issues) == 1
    blocking = blocked.blocking_issues[0]
    assert blocking.issue_type == "coverage_below_threshold"
    assert blocking.severity == "blocking"
    assert "trips excised" in blocking.title
    # The blocking finding cites the excised trip's records only.
    assert set(blocking.source_record_ids) == {
        p.source_record_id for p in positions if p.trip_id == "trip-2"
    }
