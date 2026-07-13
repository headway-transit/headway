"""Golden-dataset regression tests for sampling_v0 0.1.0 (handoff 0012).

Expectations: tests/golden/sampling_v0/expected.json, hand-worked in
BASIS.md. The table_cells block pins EVERY encoded cell of Tables
43.01/43.03/43.05/43.07 (FTA NTD Sampling Manual, 2009) one-for-one — a
sample-size regression is a regulatory defect, so no cell escapes pinning.
The APTL example is synthetic (hand-worked), the draw pin is the drawer's
permanent reproducibility anchor.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from conftest import SAMPLING_GOLDEN_DIR

from headway_calc.sampling import (
    SAMPLING_ESTIMATION_METHOD,
    UnitObservation,
    all_table_cells,
    draw_sample,
    estimate_annual_pmt,
    estimate_pmt_by_service_day,
    plan_requirement,
    sample_aptl,
)

#: Module-level ONLY for the parametrize decorators below (pytest builds
#: parameter sets at collection time, before fixtures exist); everything
#: else uses the conftest `sampling_golden_expected` fixture over the same
#: SAMPLING_GOLDEN_DIR file.
EXPECTED = json.loads((SAMPLING_GOLDEN_DIR / "expected.json").read_text())


def _observations(rows) -> list[UnitObservation]:
    return [
        UnitObservation(
            unit_id=r["unit_id"],
            observed_upt=r["observed_upt"],
            observed_pmt=Decimal(r["observed_pmt"]),
            service_day_type=r.get("service_day_type"),
        )
        for r in rows
    ]


# --- 1. every table cell pinned -------------------------------------------------


def test_every_encoded_cell_is_pinned_and_no_pin_is_orphaned(
    sampling_golden_expected,
):
    """The expected.json cell set and the module's cell set are IDENTICAL —
    a new/changed/removed cell must show up here as a diff."""
    encoded = {
        "|".join(key): [per_period, annual]
        for key, (per_period, annual) in all_table_cells().items()
    }
    assert encoded == sampling_golden_expected["table_cells"]


@pytest.mark.parametrize(
    "cell_key,sizes", sorted(EXPECTED["table_cells"].items())
)
def test_cell_verbatim(cell_key, sizes):
    group, unit, option, frequency = cell_key.split("|")
    # Look the cell up through the public selector via a representative mode.
    mode = {
        "demand_response": "DR",
        "commuter_vanpool": "VP",
        "bus": "MB",
        "commuter_rail": "CR",
        "other_rail": "LR",
    }[group]
    req = plan_requirement(mode, unit, option, frequency)
    assert req.required_per_period == sizes[0]
    assert req.required_annual == sizes[1]
    # Both quoted numbers appear verbatim in the citation string.
    assert f"= {sizes[0]}" in req.citation
    assert f"Year = {sizes[1]}" in req.citation
    assert "FTA NTD Sampling Manual, March 31, 2009" in req.citation


#: The ONE cell where the manual's own printed rows disagree with the
#: periods-per-year arithmetic: Table 43.07, One-Way Car Trips, Base Option,
#: weekly prints "Trips for a Week 6" and "Total Sample Size for Year 288"
#: (6 x 52 = 312, not 288). VERBATIM RULES: both cells are encoded exactly
#: as printed — never "corrected" from memory or arithmetic (BASIS.md §1).
MANUAL_PRINTED_ANOMALY = ("other_rail", "one_way_car_trips", "base", "weekly")


def test_per_period_times_periods_equals_annual_cross_check():
    """Arithmetic cross-check of the transcription (BASIS.md §1) — both rows
    are quoted cells; this guards against a mistyped digit in either. The
    single manual-printed inconsistency is pinned AS PRINTED."""
    periods = {"quarterly": 4, "monthly": 12, "weekly": 52}
    for key, (per_period, annual) in all_table_cells().items():
        frequency = key[3]
        if key == MANUAL_PRINTED_ANOMALY:
            assert (per_period, annual) == (6, 288)  # as printed, 312 != 288
            continue
        assert per_period * periods[frequency] == annual


@pytest.mark.parametrize("case", EXPECTED["mode_to_cell_spotchecks"])
def test_mode_level_spotchecks(case):
    req = plan_requirement(
        case["mode"], case["unit"], case["option"], case["frequency"]
    )
    assert req.required_per_period == case["per_period"]
    assert req.required_annual == case["annual"]
    assert case["table_contains"] in req.table


# --- 2. §83 APTL hand-worked example --------------------------------------------


def test_golden_aptl_ratio_of_totals(sampling_golden_expected):
    case = sampling_golden_expected["aptl_example"]
    obs = _observations(case["observations"])
    assert sample_aptl(obs) == Decimal(case["sample_aptl"])
    # The banned average-of-ratios over the defined units differs — the
    # module returns the ratio of totals (BASIS.md §2).
    assert Decimal(case["sample_aptl"]) != Decimal(
        case["banned_average_of_ratios_over_defined_units"]
    )


def test_golden_annual_estimate(sampling_golden_expected):
    case = sampling_golden_expected["aptl_example"]
    estimate = estimate_annual_pmt(
        _observations(case["observations"]), case["annual_upt_100pct"]
    )
    assert estimate.scope == "annual"
    assert estimate.sample_size == len(case["observations"])
    assert estimate.sample_total_upt == case["sample_total_upt"]
    assert estimate.sample_total_pmt == Decimal(case["sample_total_pmt"])
    assert estimate.sample_aptl == Decimal(case["sample_aptl"])
    assert estimate.expansion_factor_upt == Decimal(case["annual_upt_100pct"])
    assert estimate.estimated_pmt == Decimal(case["estimated_annual_pmt"])
    assert estimate.method == SAMPLING_ESTIMATION_METHOD
    assert "ESTIMATE" in estimate.method


def test_golden_by_service_day_estimates(sampling_golden_expected):
    case = sampling_golden_expected["by_service_day_example"]
    estimates = estimate_pmt_by_service_day(
        _observations(case["observations"]),
        {k: Decimal(v) for k, v in case["upt_100pct_by_day_type"].items()},
    )
    assert [e.scope for e in estimates] == [
        x["scope"] for x in case["expected"]
    ]
    for got, exp in zip(estimates, case["expected"]):
        assert got.sample_size == exp["sample_size"]
        assert got.sample_total_upt == exp["sample_total_upt"]
        assert got.sample_total_pmt == Decimal(exp["sample_total_pmt"])
        assert got.sample_aptl == Decimal(exp["sample_aptl"])
        assert got.estimated_pmt == Decimal(exp["estimated_pmt"])
        assert got.method == SAMPLING_ESTIMATION_METHOD
    assert sum(e.estimated_pmt for e in estimates) == Decimal(
        case["sum_of_day_type_estimates"]
    )


# --- 3. draw reproducibility anchor ----------------------------------------------


def test_golden_draw_pinned_forever(sampling_golden_expected):
    """The drawer's permanent regression anchor (BASIS.md §3): recorded
    seeds must reproduce their historical draws bit-for-bit forever, so any
    procedure change MUST fail here and mint a new drawer version."""
    case = sampling_golden_expected["draw_example"]
    draw = draw_sample(case["frame"], case["sample_size"], case["seed"])
    assert list(draw.selected_units) == case["selected_units"]
    assert draw.seed == case["seed"]
    assert draw.frame_size == len(case["frame"])
    # Input order never matters — the ordering is keyed, not positional.
    reversed_draw = draw_sample(
        list(reversed(case["frame"])), case["sample_size"], case["seed"]
    )
    assert reversed_draw.selected_units == draw.selected_units
