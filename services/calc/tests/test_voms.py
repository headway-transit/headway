"""Unit tests for voms_v0 CALC_VERSION 0.1.0 (handoff 0009).

Semantics under test: per UTC service day, the count of DISTINCT vehicles
with at least one in-trip position; the figure is the maximum over days.
Blocking-free by design (an observation gap can only understate a maximum);
partial observation is a warning; the empty period yields an observed
maximum of zero vehicles, never a guess.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from headway_calc.types import VehiclePosition
from headway_calc.voms import compute_voms

PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 4)


def _pos(day: int, hour: int, vehicle: str, trip: str | None, rid: str, mode=None):
    return VehiclePosition(
        time=datetime(2026, 7, day, hour, 0, tzinfo=timezone.utc),
        vehicle_id=vehicle,
        trip_id=trip,
        latitude=40.0,
        longitude=-75.0,
        source_record_id=rid,
        mode=mode,
    )


def test_metadata_and_integer_value():
    result = compute_voms(
        [_pos(1, 8, "veh-1", "trip-1", "rec-1")], PERIOD_START, PERIOD_END
    )
    assert result.calc_name == "voms_v0"
    assert result.calc_version == "0.1.0"
    assert result.unit == "vehicles"
    assert result.value == Decimal("1")
    # Integer by nature: the Decimal has no fractional digits.
    assert result.value == result.value.to_integral_value()


def test_distinct_vehicles_per_day_not_position_count():
    """Ten positions from one vehicle on one day are ONE operated vehicle."""
    positions = [
        _pos(1, 8, "veh-1", "trip-1", f"rec-{k}") for k in range(10)
    ]
    result = compute_voms(positions, PERIOD_START, PERIOD_END)
    assert result.value == Decimal("1")


def test_unassigned_positions_never_count():
    """The revenue-service proxy: a trip-less position counts no vehicle."""
    positions = [
        _pos(1, 8, "veh-1", "trip-1", "rec-1"),
        _pos(1, 9, "veh-9", None, "rec-x"),  # unassigned — excluded
    ]
    result = compute_voms(positions, PERIOD_START, PERIOD_END)
    assert result.value == Decimal("1")
    assert "rec-x" not in result.input_record_ids


def test_maximum_over_days_and_peak_day_lineage():
    positions = [
        _pos(1, 8, "veh-1", "trip-1", "rec-d1-a"),
        _pos(2, 8, "veh-1", "trip-2", "rec-d2-a"),
        _pos(2, 9, "veh-2", "trip-3", "rec-d2-b"),
        _pos(3, 8, "veh-1", "trip-4", "rec-d3-a"),
    ]
    result = compute_voms(positions, PERIOD_START, PERIOD_END)
    assert result.value == Decimal("2")
    detail = result.detail.to_dict()
    assert detail["peak_day"] == "2026-07-02"
    # Lineage covers the PEAK day's records only.
    assert list(result.input_record_ids) == ["rec-d2-a", "rec-d2-b"]


def test_peak_day_tie_breaks_to_earliest_day():
    positions = [
        _pos(3, 8, "veh-1", "trip-3", "rec-d3-a"),  # day 3 first in input
        _pos(3, 9, "veh-2", "trip-4", "rec-d3-b"),
        _pos(1, 8, "veh-1", "trip-1", "rec-d1-a"),  # day 1 ties at 2 vehicles
        _pos(1, 9, "veh-2", "trip-2", "rec-d1-b"),
    ]
    result = compute_voms(positions, PERIOD_START, PERIOD_END)
    assert result.value == Decimal("2")
    assert result.detail.peak_day == "2026-07-01"  # earliest, deterministic
    assert list(result.input_record_ids) == ["rec-d1-a", "rec-d1-b"]


def test_service_day_is_utc_calendar_date():
    """A non-UTC timestamp is converted to UTC BEFORE taking the date: 23:30
    at -05:00 is 04:30 UTC the NEXT day (the documented day convention)."""
    est = timezone(timedelta(hours=-5))
    positions = [
        VehiclePosition(
            time=datetime(2026, 7, 1, 23, 30, tzinfo=est),  # 2026-07-02 UTC
            vehicle_id="veh-1",
            trip_id="trip-1",
            latitude=40.0,
            longitude=-75.0,
            source_record_id="rec-1",
        ),
        _pos(2, 8, "veh-2", "trip-2", "rec-2"),
    ]
    result = compute_voms(positions, PERIOD_START, PERIOD_END)
    # Both land on UTC day 2026-07-02: 2 distinct vehicles, one day.
    assert result.value == Decimal("2")
    assert result.detail.days_observed == 1
    assert result.detail.peak_day == "2026-07-02"


def test_partial_observation_warns_and_never_blocks():
    result = compute_voms(
        [_pos(1, 8, "veh-1", "trip-1", "rec-1")], PERIOD_START, PERIOD_END
    )
    assert result.blocking_issues == ()  # blocking-free by design
    assert len(result.warnings) == 1
    warning = result.warnings[0]
    assert warning.issue_type == "voms_partial_observation"
    assert warning.severity == "warning"
    assert warning.source_record_ids == ()  # no records for unobserved days
    assert "1 of the 3 days" in warning.description
    assert result.value == Decimal("1")  # the figure stands


def test_full_observation_has_no_warning():
    positions = [_pos(d, 8, "veh-1", f"trip-{d}", f"rec-{d}") for d in (1, 2, 3)]
    result = compute_voms(positions, PERIOD_START, PERIOD_END)
    assert result.warnings == ()
    assert result.blocking_issues == ()
    assert result.detail.days_observed == 3
    assert result.detail.days_in_period == 3


def test_empty_input_yields_zero_with_warning_never_a_guess():
    result = compute_voms([], PERIOD_START, PERIOD_END)
    assert result.value == Decimal("0")
    assert result.blocking_issues == ()
    assert [w.issue_type for w in result.warnings] == ["voms_partial_observation"]
    detail = result.detail.to_dict()
    assert detail["days_observed"] == 0
    assert detail["peak_day"] is None
    assert detail["per_day_counts"] == {"min": None, "max": None, "mean": None}
    assert result.input_record_ids == ()


def test_detail_shape_and_mean_as_string():
    positions = [
        _pos(1, 8, "veh-1", "trip-1", "rec-1"),
        _pos(2, 8, "veh-1", "trip-2", "rec-2"),
        _pos(2, 9, "veh-2", "trip-3", "rec-3"),
    ]
    detail = compute_voms(positions, PERIOD_START, PERIOD_END).detail.to_dict()
    assert detail == {
        "days_observed": 2,
        "days_in_period": 3,
        "peak_day": "2026-07-02",
        # min/max exact integer counts; mean Decimal-as-string (0.0001,
        # ROUND_HALF_EVEN).
        "per_day_counts": {"min": 1, "max": 2, "mean": "1.5000"},
    }


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 7, 1), date(2026, 7, 1)),  # empty
        (date(2026, 7, 4), date(2026, 7, 1)),  # inverted
    ],
)
def test_refuses_empty_or_inverted_period(start, end):
    with pytest.raises(ValueError, match="empty/inverted period"):
        compute_voms([], start, end)
