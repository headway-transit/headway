"""Golden-dataset regression tests for the ops slice (handoff 0014):
derive_stop_passages 0.1.0, otp_v0 0.1.0, headway_adherence_v0 0.1.0.

Fixture: tests/golden/ops_v0/fixture.json; expectations: expected.json,
hand-worked in BASIS.md — SYNTHETIC operations data, regression anchor
only. Two cases: clean_two_trips (every number worked by hand) and
refusals (all three cadence/geometry refusal reasons + the honest
blocking refusals of both calcs over zero passages).
"""

from __future__ import annotations

from decimal import Decimal

from conftest import load_ops_case_positions, load_ops_schedule_rows

from headway_calc.ops import compute_headway_adherence, compute_otp
from headway_calc.passages import derive_stop_passages


def _derive(fixture, case):
    return derive_stop_passages(
        load_ops_case_positions(fixture, case),
        load_ops_schedule_rows(fixture),
    )


def test_golden_derivation_clean_two_trips(ops_golden_fixture, ops_golden_expected):
    passages, stats = _derive(ops_golden_fixture, "clean_two_trips")
    exp = ops_golden_expected["derivation"]["clean_two_trips"]
    assert stats.to_dict() == exp["stats"]
    assert [
        {
            "trip_id": p.trip_id,
            "stop_id": p.stop_id,
            "observed_time": p.observed_time.isoformat(),
            "source_record_id": p.source_record_id,
            "bounding_gap_seconds": p.bounding_gap_seconds,
        }
        for p in passages
    ] == exp["passages"]


def test_golden_derivation_refusals_every_reason_counted(
    ops_golden_fixture, ops_golden_expected
):
    passages, stats = _derive(ops_golden_fixture, "refusals")
    exp = ops_golden_expected["derivation"]["refusals"]
    assert passages == ()
    assert stats.to_dict() == exp["stats"]


def test_golden_otp_clean_two_trips(ops_golden_fixture, ops_golden_expected):
    passages, stats = _derive(ops_golden_fixture, "clean_two_trips")
    meta = ops_golden_expected["otp_v0_0_1"]
    exp = meta["clean_two_trips"]
    result = compute_otp(
        passages, stats, ops_golden_fixture["agency_timezones"]
    )
    assert result.calc_name == meta["calc_name"]
    assert result.calc_version == meta["calc_version"]
    assert result.unit == meta["unit"]
    assert result.value == Decimal(exp["value"])
    detail = result.detail.to_dict()
    derivation = detail.pop("derivation")
    assert detail == exp["detail"]
    assert derivation == ops_golden_expected["derivation"]["clean_two_trips"]["stats"]
    assert result.blocking_issues == () and result.warnings == ()
    assert list(result.input_record_ids) == exp["input_record_ids"]


def test_golden_otp_refusals_blocks_never_guesses(
    ops_golden_fixture, ops_golden_expected
):
    passages, stats = _derive(ops_golden_fixture, "refusals")
    result = compute_otp(
        passages, stats, ops_golden_fixture["agency_timezones"]
    )
    assert result.value is None
    [issue] = result.blocking_issues
    assert (
        issue.issue_type
        == ops_golden_expected["otp_v0_0_1"]["refusals"]["blocking_issue_type"]
    )
    assert result.input_record_ids == ()


def test_golden_headway_adherence_clean_two_trips(
    ops_golden_fixture, ops_golden_expected
):
    passages, stats = _derive(ops_golden_fixture, "clean_two_trips")
    meta = ops_golden_expected["headway_adherence_v0_0_1"]
    exp = meta["clean_two_trips"]
    result = compute_headway_adherence(passages, stats)
    assert result.calc_name == meta["calc_name"]
    assert result.calc_version == meta["calc_version"]
    assert result.unit == meta["unit"]
    assert result.value == Decimal(exp["value"])
    detail = result.detail.to_dict()
    derivation = detail.pop("derivation")
    assert detail == exp["detail"]
    assert derivation == ops_golden_expected["derivation"]["clean_two_trips"]["stats"]
    assert result.blocking_issues == () and result.warnings == ()
    assert list(result.input_record_ids) == exp["input_record_ids"]


def test_golden_headway_adherence_refusals_blocks(
    ops_golden_fixture, ops_golden_expected
):
    passages, stats = _derive(ops_golden_fixture, "refusals")
    result = compute_headway_adherence(passages, stats)
    assert result.value is None
    [issue] = result.blocking_issues
    assert issue.issue_type == (
        ops_golden_expected["headway_adherence_v0_0_1"]["refusals"][
            "blocking_issue_type"
        ]
    )
