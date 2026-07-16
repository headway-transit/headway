"""Golden-dataset regression tests for the day-type calcs (handoff 0020).

Fixture: tests/golden/daytype_v0/fixture.json; expectations: expected.json,
hand-worked in BASIS.md — synthetic, NOT an FTA-certified figure; regression
anchor only. February 2026 with a holiday reassignment (2026-02-16 →
sunday schedule, the p. 156 rule) and one declared atypical Saturday
(2026-02-14), plus a refused-day case pinning the binding refusal
inheritance (a day-type average over a refused UPT day refuses with the
same receipts).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from conftest import load_events, load_overrides, load_positions

from headway_calc.daytype import (
    compute_days_operated,
    compute_daytype_upt_avg,
)

PERIOD = (date(2026, 2, 1), date(2026, 3, 1))


def test_golden_days_operated_full_detail(
    daytype_golden_fixture, daytype_golden_expected
):
    case = daytype_golden_fixture["typical_month"]
    exp_all = daytype_golden_expected["typical_month"]["days_operated"]
    results = compute_days_operated(
        load_positions(case),
        *PERIOD,
        load_overrides(daytype_golden_fixture),
    )
    assert sorted(results) == sorted(exp_all)
    for day_type, exp in exp_all.items():
        result = results[day_type]
        assert result.calc_name == exp["calc_name"]
        assert result.calc_version == exp["calc_version"]
        assert result.unit == exp["unit"]
        assert result.value == Decimal(exp["value"])
        assert result.blocking_issues == ()
        assert [w.issue_type for w in result.warnings] == exp[
            "warning_issue_types"
        ]
        assert list(result.input_record_ids) == exp["input_record_ids"]
        assert result.detail.to_dict() == exp["detail"]


def test_golden_upt_averages_full_detail(
    daytype_golden_fixture, daytype_golden_expected
):
    case = daytype_golden_fixture["typical_month"]
    exp_all = daytype_golden_expected["typical_month"]["upt_avg"]
    results = compute_daytype_upt_avg(
        load_events(case),
        load_positions(case),
        *PERIOD,
        load_overrides(daytype_golden_fixture),
    )
    keyed = {f"{dt}|{split}": r for (dt, split), r in results.items()}
    # sunday/weekday have no atypical split (no declared atypical dates of
    # those types); saturday has both. Blocked splits are absent from the
    # expectations but present in the results only if refused — here every
    # emitted split has a value except none (all clean).
    assert sorted(keyed) == sorted(exp_all)
    for key, exp in exp_all.items():
        result = keyed[key]
        assert result.calc_name == exp["calc_name"]
        assert result.calc_version == exp["calc_version"]
        assert result.unit == exp["unit"]
        assert result.blocking_issues == ()
        assert result.warnings == ()  # balanced boardings/alightings
        assert result.infos == ()  # all-'tides' sources
        assert result.value == Decimal(exp["value"])
        assert list(result.input_record_ids) == exp["input_record_ids"]
        assert result.detail.to_dict() == exp["detail"]


def test_golden_holiday_boardings_land_in_the_sunday_average(
    daytype_golden_fixture, daytype_golden_expected
):
    """The p. 156 rule made concrete: the reassigned Monday's 18 boardings
    are in the SUNDAY average and in no weekday figure."""
    case = daytype_golden_fixture["typical_month"]
    results = compute_daytype_upt_avg(
        load_events(case),
        load_positions(case),
        *PERIOD,
        load_overrides(daytype_golden_fixture),
    )
    sunday = results[("sunday", "typical")].detail.to_dict()
    weekday = results[("weekday", "typical")].detail.to_dict()
    assert "2026-02-16" in sunday["dates"]
    assert "2026-02-16" not in weekday["dates"]


def test_golden_refused_day_blocks_the_average_with_the_same_receipts(
    daytype_golden_fixture, daytype_golden_expected
):
    case = daytype_golden_fixture["refused_day"]
    exp = daytype_golden_expected["refused_day"]
    positions = load_positions(case)
    events = load_events(case)
    overrides = load_overrides(daytype_golden_fixture)

    averages = compute_daytype_upt_avg(
        events, positions, *PERIOD, overrides
    )
    weekday = averages[("weekday", "typical")]
    assert weekday.value is None
    assert [b.issue_type for b in weekday.blocking_issues] == exp[
        "weekday_typical_blocking_issue_types"
    ]
    # The propagated day-level refusal carries the date AND the statistician
    # sentence — the same receipt upt_v0 would have routed.
    propagated = weekday.blocking_issues[1]
    assert propagated.title.startswith("[2026-02-02]")
    assert "statistician" in propagated.description
    assert weekday.detail.to_dict()["per_day"] == exp["weekday_per_day"]

    for day_type in exp["no_operated_day_types"]:
        result = averages[(day_type, "typical")]
        assert result.value is None
        assert [b.issue_type for b in result.blocking_issues] == [
            "daytype_no_operated_days"
        ]

    # Days Operated is observation-derived and blocking-free: the UPT
    # refusal does not erase the fact that service ran on 2026-02-02.
    days = compute_days_operated(positions, *PERIOD, overrides)
    assert days["weekday"].value == Decimal(exp["weekday_days_operated"])
