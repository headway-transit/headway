"""Golden-dataset regression tests for upt_v0 CALC_VERSION 0.1.0 (handoff 0005).

Fixture: tests/golden/upt_v0/fixture.json; expectations: expected.json,
hand-worked in BASIS.md — synthetic, NOT an FTA-certified figure; regression
anchor only. Two cases:

- ``blocked_case`` — 3 operated trips, events for 2 (18 boardings counted by
  hand), one trip missing -> share 1/3 > the FTA 2% threshold (2026 NTD
  Policy Manual p. 146) -> ONE blocking finding, value None; the p. 151
  defect rows (imbalance, negative load) and the NULL-count row assert as
  warnings, and the all-simulated source mix asserts as the info finding.
- ``factored_case`` — 50 operated trips, events for 49 -> share exactly 0.02
  -> deterministic FTA-sanctioned factor-up 50/49: 98 counted x 50/49 = 100
  reported (hand-worked in BASIS.md).
"""

from __future__ import annotations

from decimal import Decimal

from conftest import load_events

from headway_calc.upt import compute_upt


def test_golden_blocked_case_refuses_above_fta_threshold(
    upt_golden_fixture, upt_golden_expected
):
    case = upt_golden_fixture["blocked_case"]
    exp = upt_golden_expected["blocked_case"]["upt_v0_0_1"]
    result = compute_upt(load_events(case), case["operated_trip_ids"])

    assert result.calc_name == exp["calc_name"]
    assert result.calc_version == exp["calc_version"]
    assert result.unit == exp["unit"]
    # Blocked: value None, ONE apc_missing_trips_above_fta_threshold finding
    # (statistician workflow required per p. 146 — never a guessed number).
    assert result.value is None
    assert len(result.blocking_issues) == len(exp["blocking"]) == 1
    blocking = result.blocking_issues[0]
    assert blocking.issue_type == exp["blocking"][0]["issue_type"]
    assert blocking.severity == exp["blocking"][0]["severity"]
    assert list(blocking.source_record_ids) == exp["blocking"][0]["source_record_ids"]
    assert "trip-3" in blocking.description  # the missing trip is named
    assert "statistician" in blocking.description

    # The p. 151 defects and the NULL count stand as warnings alongside.
    assert len(result.warnings) == len(exp["warnings"])
    for warning, exp_warning in zip(result.warnings, exp["warnings"]):
        assert warning.issue_type == exp_warning["issue_type"]
        assert warning.severity == exp_warning["severity"]
        assert list(warning.source_record_ids) == exp_warning["source_record_ids"]
        if "trip_id" in exp_warning:
            assert exp_warning["trip_id"] in warning.title

    # All-simulated sources: ONE info citing every simulated record.
    assert len(result.infos) == len(exp["infos"]) == 1
    info = result.infos[0]
    assert info.issue_type == exp["infos"][0]["issue_type"]
    assert info.severity == exp["infos"][0]["severity"]
    assert list(info.source_record_ids) == exp["infos"][0]["source_record_ids"]
    assert "tides_simulated" in info.title

    # Detail travels even on a blocked result (the evidence always persists
    # to the routed dq rows / report).
    assert result.detail is not None
    assert result.detail.to_dict() == exp["detail"]

    # Lineage: counted boarding events only — never the NULL-count boarding
    # (cited by its warning), never the unassigned boarding.
    assert list(result.input_record_ids) == exp["input_record_ids"]


def test_golden_factored_case_factors_up_at_exactly_two_percent(
    upt_golden_fixture, upt_golden_expected
):
    case = upt_golden_fixture["factored_case"]
    exp = upt_golden_expected["factored_case"]["upt_v0_0_1"]
    result = compute_upt(load_events(case), case["operated_trip_ids"])

    # Share exactly 0.02 is "2 percent or less of the total" (p. 146):
    # factored, never blocked. 98 counted x 50/49 = 100 (BASIS.md).
    assert result.blocking_issues == ()
    assert result.warnings == ()
    assert result.infos == ()  # all-'tides' sources: no simulated finding
    assert result.value == Decimal(exp["value"])
    assert result.unit == exp["unit"]
    assert result.detail.to_dict() == exp["detail"]
    assert list(result.input_record_ids) == exp["input_record_ids"]


def test_golden_factored_value_within_fta_factor_bounds(
    upt_golden_fixture, upt_golden_expected
):
    """The factored figure respects the p. 146 bounds: >= the counted base,
    <= counted x 1/(1 - 0.02) at the threshold edge (here it sits exactly on
    the edge: 98/0.98 = 100)."""
    case = upt_golden_fixture["factored_case"]
    result = compute_upt(load_events(case), case["operated_trip_ids"])
    counted = Decimal(result.detail.total_boardings_counted)
    assert result.value >= counted
    assert result.value <= counted / Decimal("0.98")


def test_golden_blocked_case_becomes_factored_when_threshold_raised(
    upt_golden_fixture,
):
    """The same blocked fixture with an explicitly raised threshold (0.5 >
    1/3) factors up instead: 18 counted x 3/2 = 27 — the threshold is an
    explicit input, recorded in the detail."""
    case = upt_golden_fixture["blocked_case"]
    result = compute_upt(
        load_events(case),
        case["operated_trip_ids"],
        missing_trip_threshold=Decimal("0.5"),
    )
    assert result.blocking_issues == ()
    assert result.value == Decimal("27")
    assert result.detail.factor_applied == Decimal("1.500000")
    assert result.detail.missing_trip_threshold == Decimal("0.5")
