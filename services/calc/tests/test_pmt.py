"""Unit tests for pmt_v0 0.1.0 (handoff 0011) — the rules the goldens don't
already pin: distance-source precedence edges, the feed-defined
shape_dist unit discipline, zero-load segments, degenerate inputs, and the
Exhibit 44 estimator's refusals.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.pmt import (
    CALC_NAME,
    CALC_VERSION,
    UNIT,
    average_trip_length,
    compute_pmt,
    estimate_pmt_from_average_trip_length,
)
from headway_calc.types import PassengerEvent, StopTime
from headway_calc.upt import ALIGHTING_EVENT_TYPE, BOARDING_EVENT_TYPE

T0 = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
SERVICE_DATE = date(2026, 6, 1)


def ev(pe_id, trip, seq, etype, count, second, source="tides"):
    return PassengerEvent(
        event_timestamp=T0.replace(second=second % 60, minute=second // 60),
        service_date=SERVICE_DATE,
        passenger_event_id=pe_id,
        vehicle_id="veh-1",
        trip_id=trip,
        trip_stop_sequence=seq,
        event_type=(
            BOARDING_EVENT_TYPE if etype == "b" else ALIGHTING_EVENT_TYPE
        ),
        event_count=count,
        source=source,
        source_record_id=f"rec-{pe_id}",
    )


def stop(trip, stop_id, seq, lat=42.0, lon=-71.0, sdt=None):
    return StopTime(
        trip_id=trip,
        stop_id=stop_id,
        stop_sequence=seq,
        latitude=lat,
        longitude=lon,
        shape_dist_traveled=sdt,
    )


def simple_trip_events(trip="trip-1"):
    """Board 2 at seq 1, alight 2 at seq 2 — balanced, non-negative."""
    return [
        ev("1", trip, 1, "b", 2, 0),
        ev("2", trip, 2, "a", 2, 1),
    ]


def test_shape_dist_present_without_unit_falls_back_and_flags():
    """Feed-defined units (GTFS spec): shape data without an explicit
    conversion is UNUSED — haversine fallback plus BOTH info flags."""
    stops = [
        stop("trip-1", "S1", 1, 42.00, -71.0, sdt=0.0),
        stop("trip-1", "S2", 2, 42.01, -71.0, sdt=999.0),
    ]
    result = compute_pmt(simple_trip_events(), ["trip-1"], stops)
    assert result.blocking_issues == ()
    info_types = [i.issue_type for i in result.infos]
    assert info_types == [
        "haversine_distance_fallback",
        "shape_dist_unit_unknown",
    ]
    assert result.detail.distance_source_segments == {
        "shape_dist_traveled": 0,
        "haversine": 2 - 1,  # one counted segment
    }
    # 2 passengers x R x 0.01 deg: the 999.0 sdt never leaked into the value.
    assert result.value == Decimal("1.38")


def test_non_monotonic_shape_dist_segment_falls_back_to_haversine():
    stops = [
        stop("trip-1", "S1", 1, 42.00, -71.0, sdt=5.0),
        stop("trip-1", "S2", 2, 42.01, -71.0, sdt=1.0),  # decreasing: defect
    ]
    result = compute_pmt(
        simple_trip_events(),
        ["trip-1"],
        stops,
        shape_dist_unit_miles=Decimal("1"),
    )
    assert result.detail.distance_source_segments["haversine"] == 1
    assert result.detail.distance_source_segments["shape_dist_traveled"] == 0
    assert result.value == Decimal("1.38")


def test_zero_load_segment_with_no_distance_source_stays_valid():
    """A segment travelled by ZERO passengers contributes exactly 0
    passenger miles whatever its length — an uncomputable distance there
    must not invalidate the trip (mathematical identity, not a guess)."""
    stops = [
        stop("trip-1", "S1", 1, 42.00, -71.0, sdt=None),
        stop("trip-1", "S2", 2, 42.01, -71.0, sdt=None),
        # A coordinate-less node: distance to it is uncomputable...
        stop("trip-1", "S3", 3, None, None, sdt=None),
    ]
    # ...but everyone alighted at seq 2, so the S2->S3 load is 0.
    result = compute_pmt(simple_trip_events(), ["trip-1"], stops)
    assert result.blocking_issues == ()
    assert result.warnings == ()
    assert result.detail.valid_trips == 1
    assert result.value == Decimal("1.38")


def test_nonzero_load_segment_without_distance_invalidates_trip():
    stops = [
        stop("trip-1", "S1", 1, 42.00, -71.0),
        stop("trip-1", "S2", 2, None, None),  # under load: uncomputable
        stop("trip-1", "S3", 3, 42.02, -71.0),
    ]
    events = [
        ev("1", "trip-1", 1, "b", 2, 0),
        ev("2", "trip-1", 3, "a", 2, 1),
    ]
    result = compute_pmt(events, ["trip-1"], stops)
    assert result.detail.invalid_trip_reasons == {"geometry_incomplete": 1}
    assert result.warnings[0].issue_type == "pmt_invalid_trip_excluded"
    # 1 of 1 operated trips unusable -> above the 2% line -> refused.
    assert result.value is None
    assert result.blocking_issues[0].issue_type == (
        "apc_missing_trips_above_fta_threshold"
    )


def test_duplicate_stop_sequence_is_geometry_incomplete():
    stops = [
        stop("trip-1", "S1", 1),
        stop("trip-1", "S2", 2),
        stop("trip-1", "S2-dup", 2),
    ]
    result = compute_pmt(simple_trip_events(), ["trip-1"], stops)
    assert result.detail.invalid_trip_reasons == {"geometry_incomplete": 1}


def test_event_sequence_outside_schedule_is_unplaceable():
    stops = [stop("trip-1", "S1", 1), stop("trip-1", "S2", 2)]
    events = simple_trip_events() + [ev("3", "trip-1", 9, "b", 1, 2)]
    result = compute_pmt(events, ["trip-1"], stops)
    assert result.detail.invalid_trip_reasons == {"unplaceable_event": 1}


def test_unassigned_and_non_passenger_events_are_outside_the_profile():
    stops = [
        stop("trip-1", "S1", 1, 42.00, -71.0),
        stop("trip-1", "S2", 2, 42.01, -71.0),
    ]
    unassigned = ev("u", None, 1, "b", 50, 3)
    bike = PassengerEvent(
        event_timestamp=T0,
        service_date=SERVICE_DATE,
        passenger_event_id="bike-1",
        vehicle_id="veh-1",
        trip_id="trip-1",
        trip_stop_sequence=1,
        event_type="Individual bike boarded",
        event_count=1,
        source="tides",
        source_record_id="rec-bike-1",
    )
    result = compute_pmt(
        simple_trip_events() + [unassigned, bike], ["trip-1"], stops
    )
    # Same value as without them; neither record enters lineage.
    assert result.value == Decimal("1.38")
    assert "rec-u" not in result.input_record_ids
    assert "rec-bike-1" not in result.input_record_ids
    # ...but both still count in the source mix (they were loaded rows).
    assert result.detail.source_mix == {"tides": 4}


def test_degenerate_period_no_operated_trips_no_events():
    result = compute_pmt([], [], [])
    assert result.calc_name == CALC_NAME
    assert result.calc_version == CALC_VERSION
    assert result.unit == UNIT
    assert result.blocking_issues == ()
    assert result.value == Decimal("0.00")
    assert result.detail.factor_applied == Decimal("1.000000")
    assert result.detail.missing_or_invalid_share == Decimal("0.0000")


def test_operated_trips_without_events_are_missing():
    """Events for none of 2 operated trips -> share 1 -> refused."""
    result = compute_pmt([], ["trip-1", "trip-2"], [])
    assert result.value is None
    assert result.detail.missing_trips == 2
    assert result.detail.missing_or_invalid_share == Decimal("1.0000")


def test_shape_dist_unit_must_be_positive():
    with pytest.raises(ValueError, match="shape_dist_unit_miles"):
        compute_pmt([], [], [], shape_dist_unit_miles=Decimal("0"))
    with pytest.raises(ValueError, match="shape_dist_unit_miles"):
        compute_pmt([], [], [], shape_dist_unit_miles=Decimal("-1"))


def test_shape_dist_unit_conversion_applies():
    """A meters-per-unit feed: 1609.344 m segment x 1/1609.344 mi per m."""
    stops = [
        stop("trip-1", "S1", 1, sdt=0.0),
        stop("trip-1", "S2", 2, sdt=1609.344),
    ]
    result = compute_pmt(
        simple_trip_events(),
        ["trip-1"],
        stops,
        shape_dist_unit_miles=Decimal("1") / Decimal("1609.344"),
    )
    # 2 passengers x exactly 1 mile.
    assert result.value == Decimal("2.00")
    assert result.detail.distance_source_segments["shape_dist_traveled"] == 1


def test_estimator_refuses_degenerate_inputs():
    with pytest.raises(ValueError, match="UPT > 0"):
        average_trip_length("60000000", "0")
    with pytest.raises(ValueError, match="PMT >= 0"):
        average_trip_length("-1", "12750000")
    with pytest.raises(ValueError, match="average trip length"):
        estimate_pmt_from_average_trip_length("0", "1000")
    with pytest.raises(ValueError, match="UPT"):
        estimate_pmt_from_average_trip_length("4.71", "-1")
    with pytest.raises(ValueError, match="schedule_type"):
        estimate_pmt_from_average_trip_length("4.71", "1000", "Holiday")
