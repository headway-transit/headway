"""Unit tests for sampling_v0 0.1.0 (handoff 0012): plan-selector
validation, the §83 estimator's refusals and — critically — the §83.05(b)
average-of-ratios ban, and the §63.03 drawer's refusals.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

import pytest

from headway_calc import sampling
from headway_calc.sampling import (
    APTL_AVERAGE_OF_RATIOS_BAN,
    APTL_RATIO_OF_TOTALS_RULE,
    ELIGIBILITY_GUIDANCE,
    RETENTION_NOTE,
    SampledPmtEstimate,
    UnitObservation,
    draw_sample,
    estimate_annual_pmt,
    estimate_pmt_by_service_day,
    plan_requirement,
    sample_aptl,
)

# --- plan selector ---------------------------------------------------------------


def test_unknown_mode_refused_with_choices():
    with pytest.raises(ValueError, match="DR \\(demand response\\)"):
        plan_requirement("ferry", "vehicle_days", "aptl", "quarterly")


def test_unit_must_match_mode_table_41_01():
    # Bus never samples in vehicle days (Table 41.01).
    with pytest.raises(ValueError, match="Table 41.01"):
        plan_requirement("MB", "vehicle_days", "aptl", "quarterly")
    # DR never samples in one-way trips.
    with pytest.raises(ValueError, match="vehicle days"):
        plan_requirement("DR", "one_way_trips", "aptl", "quarterly")


def test_unknown_option_and_frequency_refused():
    with pytest.raises(ValueError, match="efficiency option"):
        plan_requirement("DR", "vehicle_days", "grouped", "quarterly")
    with pytest.raises(ValueError, match="quarterly"):
        plan_requirement("DR", "vehicle_days", "aptl", "yearly")


def test_grouping_option_is_bus_only():
    with pytest.raises(ValueError, match="bus \\(MB, TB\\) option only"):
        plan_requirement("DR", "vehicle_days", "aptl_grouped", "quarterly")
    with pytest.raises(ValueError, match="route grouping"):
        plan_requirement("CR", "one_way_car_trips", "aptl_grouped", "weekly")


def test_eligibility_guidance_is_plain_language_strings_not_logic():
    """§41.01/§41.03 ride along as guidance on EVERY requirement — the
    selector never decides eligibility for the agency."""
    req = plan_requirement("MB", "one_way_trips", "aptl", "monthly")
    assert req.guidance[: len(ELIGIBILITY_GUIDANCE)] == ELIGIBILITY_GUIDANCE
    joined = " ".join(req.guidance)
    assert "New Mode" in joined
    assert "no longer have the original raw sample data" in joined
    assert "mandatory sampling year" in joined
    assert "your determination" in joined  # guidance, not silent logic


def test_vanpool_grouping_and_base_caveats_attached():
    vp = plan_requirement("VP", "vehicle_days", "aptl", "monthly")
    assert any("commuters exclusively" in g for g in vp.guidance)
    grouped = plan_requirement("MB", "one_way_trips", "aptl_grouped", "weekly")
    assert any(
        "separately for individual route groups" in g for g in grouped.guidance
    )
    base = plan_requirement("CR", "one_way_car_trips", "base", "weekly")
    assert any("Section 70" in g for g in base.guidance)


def test_requirement_to_dict_round_trips_the_api_shape():
    req = plan_requirement("HR", "one_way_car_trips", "base", "quarterly")
    d = req.to_dict()
    assert d["required_per_period"] == 72
    assert d["required_annual"] == 288
    assert d["selector_name"] == "sampling_v0"
    assert d["selector_version"] == "0.1.0"


def test_retention_note_cites_the_2026_manual_p150():
    assert "3 years" in RETENTION_NOTE
    assert "p. 150" in RETENTION_NOTE


# --- §83 estimator ---------------------------------------------------------------


def test_the_8305b_ban_verbatim_and_the_ratio_rule_verbatim():
    """Pins the exact §83.05(b) sentence (and §83.05(a)) as quoted in the
    tracker — the regulatory anchor for the whole estimator shape."""
    assert APTL_AVERAGE_OF_RATIOS_BAN == (
        "You must not determine the sample APTL as the average of the APTL "
        "across individual service units in the sample."
    )
    assert APTL_RATIO_OF_TOTALS_RULE == (
        "You must determine the sample APTL for a given sample as the "
        "ratio of sample total PMT over sample total UPT"
    )


def test_average_of_ratios_is_unconstructible_by_shape():
    """The §83.05(b) ban is structural, not a runtime check:

    - the observation type carries NO ratio/APTL field;
    - the module exposes NO per-unit APTL function (nothing accepts a
      single observation and returns a ratio);
    - the estimate dataclass carries totals and ONE ratio-of-totals.

    So the banned average-of-ratios cannot be assembled from this API."""
    assert "aptl" not in {
        f.lower() for f in UnitObservation.__dataclass_fields__
    }
    for name, fn in inspect.getmembers(sampling, inspect.isfunction):
        if name.startswith("_"):
            continue
        signature = inspect.signature(fn)
        # No public function takes a single UnitObservation (per-unit ratio
        # entry point); the estimators take iterables of observations.
        for parameter in signature.parameters.values():
            assert parameter.annotation != "UnitObservation", (
                f"{name} exposes a per-unit entry point"
            )
    fields = SampledPmtEstimate.__dataclass_fields__
    assert "sample_aptl" in fields and "unit_aptls" not in fields


def test_ratio_of_totals_differs_from_average_of_ratios_and_wins():
    # Per-unit ratios 5.00, 2.50, 6.50 → banned average 4.67; totals ratio
    # 210/40 = 5.25. The module can only produce 5.25.
    obs = [
        UnitObservation("d1", 12, Decimal("60")),
        UnitObservation("d2", 8, Decimal("20")),
        UnitObservation("d4", 20, Decimal("130")),
    ]
    assert sample_aptl(obs) == Decimal("5.25")


def test_zero_passenger_unit_is_fine_but_empty_or_zero_total_sample_refused():
    obs = [
        UnitObservation("a", 0, Decimal("0")),
        UnitObservation("b", 10, Decimal("25")),
    ]
    assert sample_aptl(obs) == Decimal("2.50")
    with pytest.raises(ValueError, match="empty sample"):
        sample_aptl([])
    with pytest.raises(ValueError, match="ratio of sample total PMT"):
        sample_aptl([UnitObservation("a", 0, Decimal("0"))])


def test_observation_refuses_negative_counts_and_unknown_day_type():
    with pytest.raises(ValueError, match="zero or more boardings"):
        UnitObservation("u", -1, Decimal("5"))
    with pytest.raises(ValueError, match="zero or more passenger miles"):
        UnitObservation("u", 1, Decimal("-5"))
    with pytest.raises(ValueError, match="service-day type"):
        UnitObservation("u", 1, Decimal("5"), service_day_type="Holiday")


def test_estimate_refuses_non_positive_expansion_factor():
    obs = [UnitObservation("a", 10, Decimal("25"))]
    with pytest.raises(ValueError, match="§83.01\\(a\\)"):
        estimate_annual_pmt(obs, 0)
    with pytest.raises(ValueError, match="positive 100% count"):
        estimate_annual_pmt(obs, "-5")


def test_estimate_carries_the_provenance_label_always():
    estimate = estimate_annual_pmt(
        [UnitObservation("a", 10, Decimal("25"))], 1000
    )
    assert "estimated — sampled average passenger trip length" in estimate.method
    assert "not a computed PMT measurement" in estimate.method
    assert estimate.to_dict()["method"] == estimate.method
    # Value serialization: strings, never floats (repo non-negotiable).
    assert estimate.to_dict()["estimated_pmt"] == "2500"
    assert estimate.to_dict()["sample_aptl"] == "2.50"


def test_aptl_quantization_half_even_at_two_decimals():
    # 100 / 3 = 33.333… → 33.33; 10.125 / 2 = 5.0625 → 5.06 (half-even).
    assert sample_aptl(
        [UnitObservation("a", 3, Decimal("100"))]
    ) == Decimal("33.33")
    assert sample_aptl(
        [UnitObservation("a", 2, Decimal("10.125"))]
    ) == Decimal("5.06")


def test_by_service_day_refuses_unlabeled_and_missing_expansion_factor():
    labeled = UnitObservation("w1", 10, Decimal("40"), "Weekday")
    unlabeled = UnitObservation("x1", 5, Decimal("10"))
    with pytest.raises(ValueError, match="unlabeled unit\\(s\\): x1"):
        estimate_pmt_by_service_day(
            [labeled, unlabeled], {"Weekday": 1000}
        )
    with pytest.raises(ValueError, match="never guessed"):
        estimate_pmt_by_service_day([labeled], {})
    with pytest.raises(ValueError, match="Unknown service-day type"):
        estimate_pmt_by_service_day([labeled], {"Holiday": 5, "Weekday": 10})
    with pytest.raises(ValueError, match="§83.01\\(b\\)"):
        estimate_pmt_by_service_day([labeled], {"Weekday": 0})


# --- §63.03 drawer ---------------------------------------------------------------


def test_draw_refuses_empty_seed_bad_size_and_duplicates():
    frame = ["u1", "u2", "u3"]
    with pytest.raises(ValueError, match="recorded seed"):
        draw_sample(frame, 2, "")
    with pytest.raises(ValueError, match="at least 1"):
        draw_sample(frame, 0, "seed")
    with pytest.raises(ValueError, match="without replacement"):
        draw_sample(frame, 4, "seed")
    with pytest.raises(ValueError, match="duplicate unit id\\(s\\): u2"):
        draw_sample(["u1", "u2", "u2"], 2, "seed")


def test_draw_records_seed_method_and_version():
    draw = draw_sample(["u1", "u2", "u3"], 2, "seed-xyz")
    assert draw.seed == "seed-xyz"
    assert draw.sample_size == 2
    assert draw.frame_size == 3
    assert "§63.03" in draw.method
    assert "without replacement" in draw.method
    assert (draw.drawer_name, draw.drawer_version) == ("sampling_v0", "0.1.0")
    assert draw.to_dict()["selected_units"] == list(draw.selected_units)


def test_draw_full_frame_is_a_permutation():
    frame = [f"u{i}" for i in range(20)]
    draw = draw_sample(frame, 20, "s")
    assert sorted(draw.selected_units) == sorted(frame)
