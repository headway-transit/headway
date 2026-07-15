"""Golden-dataset regression tests for pmt_v0 CALC_VERSION 0.1.0 (handoff
0011).

Fixture: tests/golden/pmt_v0/fixture.json; expectations: expected.json,
hand-worked in BASIS.md — synthetic, NOT FTA-certified figures; regression
anchors only — EXCEPT the exhibit_44 block, which pins the 2026 NTD Policy
Manual's own worked example VERBATIM (pp. 154-155): 60,000,000/12,750,000 →
ATL 4.71; 4.71 × 13,400,000 = 63,114,000; and the per-schedule rows.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import load_events, load_stop_times

# compute_pmt pinned to the RETAINED 0.1.0 function (the test_golden.py
# convention): these goldens anchor pmt_v0 0.1.0 forever; 0.2.0 (attestation
# path, handoff 0019) has its own tests, and the no-attestation byte-for-byte
# equivalence is pinned in test_pmt_attestation.py.
from headway_calc.pmt import (
    ESTIMATION_METHOD,
    estimate_pmt_average_trip_length,
    estimate_pmt_from_average_trip_length,
)
from headway_calc.pmt import compute_pmt_v0_1_0 as compute_pmt


def _unit(case: dict) -> Decimal | None:
    raw = case["shape_dist_unit_miles"]
    return None if raw is None else Decimal(raw)


def _run(fixture: dict, name: str):
    case = fixture[name]
    return compute_pmt(
        load_events(case),
        case["operated_trip_ids"],
        load_stop_times(case),
        shape_dist_unit_miles=_unit(case),
    )


def test_golden_shape_case_hand_worked_load_profiles(
    pmt_golden_fixture, pmt_golden_expected
):
    """BASIS.md case 1: trip-A 18.5 + trip-B 11.0 = 29.50, priced from
    shape_dist deltas (the absurd coordinates prove the precedence)."""
    exp = pmt_golden_expected["shape_case"]["pmt_v0_0_1"]
    result = _run(pmt_golden_fixture, "shape_case")

    assert result.calc_name == exp["calc_name"]
    assert result.calc_version == exp["calc_version"]
    assert result.unit == exp["unit"]
    assert result.blocking_issues == ()
    assert result.warnings == ()
    assert result.infos == ()  # no fallback, no simulated sources
    assert result.value == Decimal(exp["value"])
    assert list(result.input_record_ids) == exp["input_record_ids"]
    assert result.detail.to_dict() == exp["detail"]


def test_golden_haversine_case_flagged_fallback(
    pmt_golden_fixture, pmt_golden_expected
):
    """BASIS.md case 2: NULL shape_dist → haversine legs R×Δφ; the divergence
    and the simulated source are both flagged as infos."""
    exp = pmt_golden_expected["haversine_case"]["pmt_v0_0_1"]
    result = _run(pmt_golden_fixture, "haversine_case")

    assert result.blocking_issues == ()
    assert result.warnings == ()
    assert result.value == Decimal(exp["value"])
    assert len(result.infos) == len(exp["infos"]) == 2
    for info, exp_info in zip(result.infos, exp["infos"]):
        assert info.issue_type == exp_info["issue_type"]
        assert info.severity == exp_info["severity"]
        assert list(info.source_record_ids) == exp_info["source_record_ids"]
    # The divergence direction is stated in plain language.
    fallback = result.infos[1]
    assert "UNDERSTATES" in fallback.description
    assert list(result.input_record_ids) == exp["input_record_ids"]
    assert result.detail.to_dict() == exp["detail"]


def test_golden_blocked_case_refuses_above_fta_threshold(
    pmt_golden_fixture, pmt_golden_expected
):
    """BASIS.md case 3: missing(1) + invalid-operated(2) of 4 = 0.75 > 2% →
    REFUSE with the p. 146 statistician citation; per-trip exclusion warnings
    carry the evidence; unoperated invalid trips warn without counting."""
    exp = pmt_golden_expected["blocked_case"]["pmt_v0_0_1"]
    result = _run(pmt_golden_fixture, "blocked_case")

    assert result.value is None
    assert len(result.blocking_issues) == len(exp["blocking"]) == 1
    blocking = result.blocking_issues[0]
    assert blocking.issue_type == exp["blocking"][0]["issue_type"]
    assert blocking.severity == exp["blocking"][0]["severity"]
    assert list(blocking.source_record_ids) == exp["blocking"][0]["source_record_ids"]
    assert "statistician" in blocking.description
    assert "trip-G" in blocking.description  # the missing trip is named
    assert "trip-F" in blocking.description  # the invalid operated trips too
    assert "trip-H" in blocking.description

    assert len(result.warnings) == len(exp["warnings"]) == 4
    for warning, exp_warning in zip(result.warnings, exp["warnings"]):
        assert warning.issue_type == exp_warning["issue_type"]
        assert warning.severity == exp_warning["severity"]
        assert exp_warning["trip_id"] in warning.title
        assert exp_warning["first_reason"] in warning.title
        assert list(warning.source_record_ids) == exp_warning["source_record_ids"]
    # trip-I's description names BOTH defects (priority pinned by the title).
    trip_i = result.warnings[2]
    assert "null_event_count" in trip_i.description
    assert "unplaceable_event" in trip_i.description

    assert result.infos == ()
    # Evidence travels on the blocked result too.
    assert list(result.input_record_ids) == exp["input_record_ids"]
    assert result.detail is not None
    assert result.detail.to_dict() == exp["detail"]


def test_golden_factored_case_factors_up_at_exactly_two_percent(
    pmt_golden_fixture, pmt_golden_expected
):
    """BASIS.md case 4: share exactly 0.02 is '2 percent or less' (p. 146):
    factored, never blocked. 98.00 × 50/49 = 100.00."""
    exp = pmt_golden_expected["factored_case"]["pmt_v0_0_1"]
    result = _run(pmt_golden_fixture, "factored_case")

    assert result.blocking_issues == ()
    assert result.warnings == ()
    assert result.infos == ()
    assert result.value == Decimal(exp["value"])
    assert list(result.input_record_ids) == exp["input_record_ids"]
    assert result.detail.to_dict() == exp["detail"]


def test_golden_factored_value_within_fta_factor_bounds(pmt_golden_fixture):
    """The factored figure respects the p. 146 bounds: >= the counted base,
    <= counted × 1/(1 − 0.02) at the threshold edge (here exactly on it)."""
    result = _run(pmt_golden_fixture, "factored_case")
    counted = result.detail.passenger_miles_counted
    assert result.value >= counted
    assert result.value <= counted / Decimal("0.98")


def test_golden_blocked_case_factors_when_threshold_raised(pmt_golden_fixture):
    """The same blocked fixture with an explicitly raised threshold (0.8 >
    0.75) factors up instead: 3.00 counted × 4/1 = 12.00 — the threshold is
    an explicit input, recorded in the detail."""
    case = pmt_golden_fixture["blocked_case"]
    result = compute_pmt(
        load_events(case),
        case["operated_trip_ids"],
        load_stop_times(case),
        missing_trip_threshold=Decimal("0.8"),
        shape_dist_unit_miles=Decimal(case["shape_dist_unit_miles"]),
    )
    assert result.blocking_issues == ()
    assert result.value == Decimal("12.00")
    assert result.detail.factor_applied == Decimal("4.000000")
    assert result.detail.missing_trip_threshold == Decimal("0.8")


# --- Exhibit 44 (pp. 154-155) — the manual's own numbers, verbatim ----------


def test_golden_exhibit_44_annual_worked_example_verbatim(pmt_golden_expected):
    exp = pmt_golden_expected["exhibit_44"]["annual"]
    estimate = estimate_pmt_average_trip_length(
        exp["mandatory_year_pmt"],
        exp["mandatory_year_upt"],
        exp["current_year_upt"],
        schedule_type="Annual",
    )
    # 60,000,000 / 12,750,000 → 4.71; 4.71 × 13,400,000 = 63,114,000.
    assert estimate.average_trip_length == Decimal(exp["average_trip_length"])
    assert estimate.estimated_pmt == Decimal(exp["estimated_pmt"])
    assert estimate.estimated_pmt == Decimal("63114000")
    assert estimate.schedule_type == "Annual"
    assert estimate.mandatory_year_pmt == Decimal(exp["mandatory_year_pmt"])
    assert estimate.mandatory_year_upt == Decimal(exp["mandatory_year_upt"])
    # The provenance label is the fixed estimation-method citation — never
    # presentable as computed PMT.
    assert estimate.method == ESTIMATION_METHOD
    assert "estimated" in estimate.method
    assert "Exhibit 44" in estimate.method


def test_golden_exhibit_44_per_schedule_rows_verbatim(pmt_golden_expected):
    for row in pmt_golden_expected["exhibit_44"]["per_schedule"]:
        estimate = estimate_pmt_from_average_trip_length(
            row["average_trip_length"],
            row["current_year_upt"],
            schedule_type=row["schedule_type"],
        )
        assert estimate.estimated_pmt == Decimal(row["estimated_pmt"])
        assert estimate.method == ESTIMATION_METHOD
        # ATL given directly: no mandatory-year pair is claimed.
        assert estimate.mandatory_year_pmt is None
        assert estimate.mandatory_year_upt is None


def test_golden_exhibit_44_estimate_serializes_with_method(pmt_golden_expected):
    exp = pmt_golden_expected["exhibit_44"]["annual"]
    estimate = estimate_pmt_average_trip_length(
        exp["mandatory_year_pmt"],
        exp["mandatory_year_upt"],
        exp["current_year_upt"],
    )
    d = estimate.to_dict()
    assert d["estimated_pmt"] == "63114000"
    assert d["average_trip_length"] == "4.71"
    assert d["method"] == ESTIMATION_METHOD
