"""Golden-dataset regression tests for voms_v0 CALC_VERSION 0.1.0 (handoff 0009).

Fixture: tests/golden/voms_v0/fixture.json; expectations: expected.json,
hand-worked in BASIS.md — synthetic, NOT an FTA-certified figure; regression
anchor only. Three UTC service days with distinct in-trip vehicle counts
2/3/2 -> maximum 3, exercised over an exactly-observed period (no warning)
and a wider partial period (one voms_partial_observation warning; the figure
stands).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import load_positions

from headway_calc.voms import compute_voms


def _case(fixture, expected, case_name):
    exp = expected["voms_v0_0_1"][case_name]
    result = compute_voms(
        load_positions(fixture),
        date.fromisoformat(exp["period_start"]),
        date.fromisoformat(exp["period_end"]),
    )
    return result, exp, expected["voms_v0_0_1"]


def test_golden_exact_period_2_3_2_yields_3(voms_golden_fixture, voms_golden_expected):
    result, exp, meta = _case(voms_golden_fixture, voms_golden_expected, "exact_period")
    assert result.calc_name == meta["calc_name"]
    assert result.calc_version == meta["calc_version"]
    assert result.unit == meta["unit"]
    assert result.value == Decimal(exp["value"])
    assert result.detail.to_dict() == exp["detail"]
    assert result.blocking_issues == ()  # blocking-free by design
    assert result.warnings == ()  # 3 of 3 days observed: no warning
    # Lineage: the PEAK day's in-trip records only (BASIS.md); day-1/day-3
    # records and the unassigned rec-vx-00 never appear.
    assert list(result.input_record_ids) == exp["input_record_ids"]


def test_golden_partial_period_warns_and_figure_stands(
    voms_golden_fixture, voms_golden_expected
):
    result, exp, _ = _case(voms_golden_fixture, voms_golden_expected, "partial_period")
    assert result.value == Decimal(exp["value"])  # unchanged maximum
    assert result.detail.to_dict() == exp["detail"]
    assert result.blocking_issues == ()  # NEVER blocks — undercount risk only
    assert len(result.warnings) == len(exp["warnings"]) == 1
    warning = result.warnings[0]
    assert warning.issue_type == exp["warnings"][0]["issue_type"]
    assert warning.severity == exp["warnings"][0]["severity"]
    assert list(warning.source_record_ids) == exp["warnings"][0]["source_record_ids"]
    assert list(result.input_record_ids) == exp["input_record_ids"]


def test_golden_unassigned_position_never_counts(voms_golden_fixture):
    """Removing the unassigned rec-vx-00 changes nothing: it was never
    counted (the revenue-service proxy)."""
    positions = [
        p for p in load_positions(voms_golden_fixture) if p.trip_id is not None
    ]
    result = compute_voms(positions, date(2026, 7, 1), date(2026, 7, 4))
    assert result.value == Decimal("3")
    assert result.detail.per_day_counts == {"min": 2, "max": 3, "mean": "2.3333"}
