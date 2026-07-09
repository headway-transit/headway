"""Unit tests for types and distance helpers."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.distance import EARTH_RADIUS_MILES, haversine_miles, miles_to_decimal
from headway_calc.types import BlockingIssue, CalcResult, VehiclePosition


def test_haversine_zero_distance():
    assert haversine_miles(40.0, -75.0, 40.0, -75.0) == 0.0


def test_haversine_meridian_leg_matches_arc_length():
    # Pure meridian leg: haversine reduces to R * delta-phi.
    d = haversine_miles(40.0, -75.0, 40.01, -75.0)
    assert d == pytest.approx(EARTH_RADIUS_MILES * math.radians(0.01), rel=1e-9)


def test_haversine_symmetry():
    assert haversine_miles(40.0, -75.0, 40.01, -74.99) == pytest.approx(
        haversine_miles(40.01, -74.99, 40.0, -75.0), rel=1e-12
    )


def test_miles_to_decimal_quantizes_half_even():
    assert miles_to_decimal(12.436815417396051) == Decimal("12.44")
    assert miles_to_decimal(0.0) == Decimal("0.00")
    # banker's rounding on the exact half
    assert miles_to_decimal(0.125) == Decimal("0.12")
    assert miles_to_decimal(0.135) == Decimal("0.14")


def test_vehicle_position_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone-aware"):
        VehiclePosition(
            time=datetime(2026, 1, 15, 12, 0, 0),  # naive
            vehicle_id="veh-1",
            trip_id="trip-A",
            latitude=40.0,
            longitude=-75.0,
            source_record_id="rec-1",
        )


def test_vehicle_position_rejects_out_of_range_coordinates():
    t = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="latitude"):
        VehiclePosition(t, "veh-1", "trip-A", 91.0, -75.0, "rec-1")
    with pytest.raises(ValueError, match="longitude"):
        VehiclePosition(t, "veh-1", "trip-A", 40.0, -181.0, "rec-1")


def test_calc_result_invariant_no_value_with_blocking_issues():
    issue = BlockingIssue("telemetry_gap", "t", "d", ("rec-1", "rec-2"))
    with pytest.raises(ValueError, match="value=None"):
        CalcResult(
            value=Decimal("1.00"),
            unit="miles",
            calc_name="vrm_v0",
            calc_version="0.1.0",
            input_record_ids=("rec-1",),
            blocking_issues=(issue,),
        )


def test_calc_result_rejects_float_value():
    with pytest.raises(TypeError, match="Decimal"):
        CalcResult(
            value=1.0,  # float forbidden
            unit="miles",
            calc_name="vrm_v0",
            calc_version="0.1.0",
            input_record_ids=(),
            blocking_issues=(),
        )
