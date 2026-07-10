"""Unit tests for types and distance helpers."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.distance import EARTH_RADIUS_MILES, haversine_miles, miles_to_decimal
from headway_calc.types import (
    BlockCoverageDetail,
    BlockingIssue,
    CalcResult,
    CoverageDetail,
    Finding,
    VehiclePosition,
)


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


# --- Finding severity + 0.2.0 result fields (handoff 0002) -------------------


def test_blocking_issue_is_a_finding_with_blocking_default_severity():
    issue = BlockingIssue("telemetry_gap", "t", "d", ("rec-1",))
    assert BlockingIssue is Finding  # 0.1.0 name kept importable
    assert issue.severity == "blocking"


def test_finding_rejects_unknown_severity():
    with pytest.raises(ValueError, match="severity"):
        Finding("telemetry_gap_excluded", "t", "d", ("rec-1",), severity="fatal")


def _warning():
    return Finding(
        "telemetry_gap_excluded", "t", "d", ("rec-c-00",), severity="warning"
    )


def test_calc_result_allows_value_alongside_warnings():
    """The blocking-implies-None invariant binds BLOCKING findings only."""
    result = CalcResult(
        value=Decimal("12.44"),
        unit="miles",
        calc_name="vrm_v0",
        calc_version="0.2.0",
        input_record_ids=("rec-a-00",),
        blocking_issues=(),
        warnings=(_warning(),),
    )
    assert result.value == Decimal("12.44")


def test_calc_result_rejects_warning_severity_in_blocking_issues():
    with pytest.raises(ValueError, match="blocking_issues"):
        CalcResult(
            value=None,
            unit="miles",
            calc_name="vrm_v0",
            calc_version="0.2.0",
            input_record_ids=(),
            blocking_issues=(_warning(),),
        )


def test_calc_result_rejects_blocking_severity_in_warnings():
    with pytest.raises(ValueError, match="warnings"):
        CalcResult(
            value=Decimal("1.00"),
            unit="miles",
            calc_name="vrm_v0",
            calc_version="0.2.0",
            input_record_ids=(),
            blocking_issues=(),
            warnings=(BlockingIssue("telemetry_gap", "t", "d", ("rec-1",)),),
        )


# --- 0.3.0 additions: info severity, infos field, block detail (handoff 0003)


def _info():
    return Finding(
        "block_unavailable", "t", "d", ("rec-a-00",), severity="info"
    )


def test_finding_accepts_info_severity():
    assert _info().severity == "info"


def test_vehicle_position_block_id_defaults_to_none():
    t = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    assert VehiclePosition(t, "veh-1", "trip-A", 40.0, -75.0, "rec-1").block_id is None
    carried = VehiclePosition(t, "veh-1", "trip-A", 40.0, -75.0, "rec-1", "blk-1")
    assert carried.block_id == "blk-1"


def test_calc_result_allows_value_alongside_infos():
    """Info findings never force value=None — they document, not exclude."""
    result = CalcResult(
        value=Decimal("0.45"),
        unit="hours",
        calc_name="vrh_v0",
        calc_version="0.3.0",
        input_record_ids=("rec-a-00",),
        blocking_issues=(),
        infos=(_info(),),
    )
    assert result.value == Decimal("0.45")


def test_calc_result_rejects_non_info_severity_in_infos():
    with pytest.raises(ValueError, match="infos"):
        CalcResult(
            value=Decimal("0.45"),
            unit="hours",
            calc_name="vrh_v0",
            calc_version="0.3.0",
            input_record_ids=(),
            blocking_issues=(),
            infos=(_warning(),),
        )


def test_calc_result_rejects_info_severity_in_warnings():
    with pytest.raises(ValueError, match="warnings"):
        CalcResult(
            value=Decimal("0.45"),
            unit="hours",
            calc_name="vrh_v0",
            calc_version="0.3.0",
            input_record_ids=(),
            blocking_issues=(),
            warnings=(_info(),),
        )


def test_block_coverage_detail_to_dict_adds_layover_max_seconds():
    detail = BlockCoverageDetail(
        coverage=Decimal("1.0000"),
        total_groups=1,
        excluded_groups=0,
        clean_position_share=Decimal("1.0000"),
        gap_threshold_seconds=300.0,
        coverage_threshold=Decimal("0.95"),
        layover_max_seconds=1800.0,
    )
    assert detail.to_dict() == {
        "coverage": "1.0000",
        "total_groups": 1,
        "excluded_groups": 0,
        "clean_position_share": "1.0000",
        "gap_threshold_seconds": 300.0,
        "coverage_threshold": "0.95",
        "layover_max_seconds": 1800.0,
    }


def test_coverage_detail_to_dict_renders_ratios_as_strings():
    detail = CoverageDetail(
        coverage=Decimal("0.6667"),
        total_groups=3,
        excluded_groups=1,
        clean_position_share=Decimal("0.8333"),
        gap_threshold_seconds=300.0,
        coverage_threshold=Decimal("0.95"),
    )
    assert detail.to_dict() == {
        "coverage": "0.6667",
        "total_groups": 3,
        "excluded_groups": 1,
        "clean_position_share": "0.8333",
        "gap_threshold_seconds": 300.0,
        "coverage_threshold": "0.95",
    }
