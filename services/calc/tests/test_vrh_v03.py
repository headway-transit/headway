"""Unit tests for the vrh_v0 0.3.0 block mechanics (handoff 0003).

Covers, with hand-built positions: the layover cap (over-cap interval NOT
counted + one layover_exceeds_max warning naming the bounding records); the
exclusion unit becoming the block group (a within-trip gap in ONE trip
excludes the WHOLE block); block_unavailable info grouping per vehicle-day;
the conservative null-trip rule; non-positive inter-trip intervals; and the
fail-loudly refusal of contradictory block_ids. No live database.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from headway_calc.types import VehiclePosition
from headway_calc.vrh import compute_vrh, compute_vrh_v0_2

T0 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

#: A coverage threshold of 0 never blocks — it isolates the block arithmetic
#: from the certifiability line (same convention as the 0.2.0 property tests).
NEVER_BLOCK = Decimal("0")


def _trip(
    vehicle_id: str,
    trip_id: str,
    block_id: str | None,
    start: datetime,
    n: int = 4,
    spacing_s: int = 60,
    id_prefix: str | None = None,
) -> list[VehiclePosition]:
    """One clean trip: n positions, fixed spacing, stationary coordinates."""
    prefix = id_prefix or f"rec-{trip_id}"
    return [
        VehiclePosition(
            time=start + timedelta(seconds=i * spacing_s),
            vehicle_id=vehicle_id,
            trip_id=trip_id,
            latitude=40.0,
            longitude=-75.0,
            source_record_id=f"{prefix}-{i:02d}",
            block_id=block_id,
        )
        for i in range(n)
    ]


def test_layover_over_cap_not_counted_and_warned():
    """A 2000 s inter-trip interval (> 1800 s default cap) is NOT counted:
    v0.3 equals the retained v0.2 value, plus one layover_exceeds_max warning
    naming the bounding records."""
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)  # ends T0+180s
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180 + 2000))
    positions = trip_1 + trip_2

    result = compute_vrh(positions)
    baseline = compute_vrh_v0_2(positions)
    assert result.calc_version == "0.3.0"
    assert result.blocking_issues == ()
    assert result.value == baseline.value  # the over-cap interval added 0

    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.issue_type == "layover_exceeds_max"
    assert warning.severity == "warning"
    assert warning.source_record_ids == ("rec-trip-1-03", "rec-trip-2-00")


def test_layover_at_cap_is_counted():
    """The cap is inclusive: an interval of exactly layover_max_seconds
    counts (only strictly-greater intervals are dropped)."""
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180 + 600))
    positions = trip_1 + trip_2

    result = compute_vrh(positions, layover_max_seconds=600)
    assert result.warnings == ()
    # 2 x 180 s running + 600 s layover = 960 s = 0.2666... -> 0.27 h.
    assert result.value == Decimal("0.27")

    capped = compute_vrh(positions, layover_max_seconds=599)
    assert capped.value == Decimal("0.10")  # 360 s running only
    assert [w.issue_type for w in capped.warnings] == ["layover_exceeds_max"]


def test_within_trip_gap_excludes_the_whole_block_group():
    """The within-trip gap rule is unchanged, but the exclusion unit is the
    block group: a gap inside trip-2 excludes trip-1's time too (v0.2 would
    still have counted trip-1's group)."""
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180 + 600))
    # Inject a 400 s within-trip gap into trip-2 (> 300 s default threshold).
    last = trip_2[-1]
    trip_2.append(
        VehiclePosition(
            time=last.time + timedelta(seconds=400),
            vehicle_id=last.vehicle_id,
            trip_id=last.trip_id,
            latitude=last.latitude,
            longitude=last.longitude,
            source_record_id="rec-trip-2-after-gap",
            block_id=last.block_id,
        )
    )
    positions = trip_1 + trip_2

    result = compute_vrh(positions, coverage_threshold=NEVER_BLOCK)
    assert result.blocking_issues == ()
    assert result.value == Decimal("0.00")  # the ONE block group is excluded
    assert result.input_record_ids == ()  # excluded records never in lineage

    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.issue_type == "telemetry_gap_excluded"
    assert "block blk-1" in warning.title
    # ALL of the block group's records are cited, both trips.
    assert set(warning.source_record_ids) == {p.source_record_id for p in positions}

    assert result.detail.total_groups == 1
    assert result.detail.excluded_groups == 1

    # The retained v0.2 (per-trip exclusion unit) still counts trip-1.
    baseline = compute_vrh_v0_2(positions, coverage_threshold=NEVER_BLOCK)
    assert baseline.value == Decimal("0.05")  # trip-1's 180 s


def test_block_unavailable_infos_group_per_vehicle_day():
    """NULL-block trips: one info per (vehicle, UTC day), citing all of that
    vehicle-day's fallback records; the figure stands (per-trip semantics)."""
    day_1 = _trip("veh-1", "trip-1", None, T0)
    day_1 += _trip("veh-1", "trip-2", None, T0 + timedelta(hours=1))
    day_2 = _trip("veh-1", "trip-3", None, T0 + timedelta(days=1))
    other = _trip("veh-2", "trip-4", None, T0)
    positions = day_1 + day_2 + other

    result = compute_vrh(positions)
    assert result.blocking_issues == () and result.warnings == ()
    # 4 fallback trips x 180 s = 720 s = 0.2 h; layover between trip-1 and
    # trip-2 is NOT counted without a block (the documented undercount).
    assert result.value == Decimal("0.20")

    assert [i.issue_type for i in result.infos] == ["block_unavailable"] * 3
    assert all(i.severity == "info" for i in result.infos)
    by_title = {
        ("veh-1" in i.title, "2026-01-15" in i.title, "2026-01-16" in i.title): i
        for i in result.infos
    }
    veh1_day1 = by_title[(True, True, False)]
    assert set(veh1_day1.source_record_ids) == {
        p.source_record_id for p in day_1
    }
    veh1_day2 = by_title[(True, False, True)]
    assert set(veh1_day2.source_record_ids) == {p.source_record_id for p in day_2}


def test_null_trip_positions_inside_a_block_span_are_ignored():
    """Conservative v0.3 rule (handoff 0003 open question): a trip_id-less
    position temporally inside the block's layover contributes nothing."""
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180 + 600))
    mid_layover = VehiclePosition(
        time=T0 + timedelta(seconds=180 + 300),
        vehicle_id="veh-1",
        trip_id=None,
        latitude=40.0,
        longitude=-75.0,
        source_record_id="rec-null-mid-layover",
        block_id=None,
    )
    with_null = compute_vrh(trip_1 + [mid_layover] + trip_2)
    without = compute_vrh(trip_1 + trip_2)
    assert with_null.value == without.value
    assert "rec-null-mid-layover" not in with_null.input_record_ids
    assert with_null.infos == ()  # a null-TRIP position is not a null block


def test_non_positive_inter_trip_interval_contributes_nothing():
    """Overlapping telemetry between block trips never subtracts time."""
    trip_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    # trip-2 starts exactly when trip-1 ends: 0 s interval.
    trip_2 = _trip("veh-1", "trip-2", "blk-1", T0 + timedelta(seconds=180))
    result = compute_vrh(trip_1 + trip_2)
    assert result.value == Decimal("0.10")  # 360 s running, nothing else
    assert result.warnings == ()


def test_inconsistent_block_id_for_one_trip_fails_loudly():
    trip = _trip("veh-1", "trip-1", "blk-1", T0)
    contradictory = VehiclePosition(
        time=T0 + timedelta(seconds=240),
        vehicle_id="veh-1",
        trip_id="trip-1",
        latitude=40.0,
        longitude=-75.0,
        source_record_id="rec-contradictory",
        block_id="blk-2",
    )
    with pytest.raises(ValueError, match="Inconsistent block_id"):
        compute_vrh(trip + [contradictory])


def test_same_block_id_on_different_vehicles_stays_separate():
    """Block groups are per (vehicle_id, block_id): two vehicles sharing a
    block_id never merge, and no cross-vehicle layover is counted."""
    veh_1 = _trip("veh-1", "trip-1", "blk-1", T0)
    veh_2 = _trip("veh-2", "trip-2", "blk-1", T0 + timedelta(seconds=600))
    result = compute_vrh(veh_1 + veh_2)
    assert result.detail.total_groups == 2
    assert result.value == Decimal("0.10")  # 2 x 180 s running only
