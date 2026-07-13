"""Golden-dataset regression tests for the dr_*_v0 calcs CALC_VERSION 0.1.0
(handoff 0013).

Fixture: tests/golden/dr_v0/fixture.json; expectations: expected.json,
hand-worked in BASIS.md — synthetic, NOT FTA-certified; regression anchors
only. Three sections:

1. the hand-worked three-vehicle dispatch day (DO shared ride, no-show,
   lunch/fuel breaks, unmeasured distances, ADA/sponsored splits, TX
   onboard-only accounting) through all five calcs + the per-TOS
   decomposition;
2. EVERY Exhibit 36 row — the verbatim classification table AND one
   behavioral scenario per row;
3. the Exhibit 40 Happy Transit VOMS scenario (6 unique vehicles, max 4
   simultaneous -> 4, atypical days included).
"""

from __future__ import annotations

from decimal import Decimal

from conftest import load_dr_trips

from headway_calc.dr import (
    EXHIBIT_36,
    compute_dr_pmt,
    compute_dr_pmt_by_tos,
    compute_dr_upt,
    compute_dr_upt_by_tos,
    compute_dr_voms,
    compute_dr_voms_by_tos,
    compute_dr_vrh,
    compute_dr_vrh_by_tos,
    compute_dr_vrm,
    compute_dr_vrm_by_tos,
)

_COMPUTES = {
    "dr_vrh": compute_dr_vrh,
    "dr_vrm": compute_dr_vrm,
    "dr_upt": compute_dr_upt,
    "dr_voms": compute_dr_voms,
    "dr_pmt": compute_dr_pmt,
}

_BY_TOS = {
    "dr_vrh": compute_dr_vrh_by_tos,
    "dr_vrm": compute_dr_vrm_by_tos,
    "dr_upt": compute_dr_upt_by_tos,
    "dr_voms": compute_dr_voms_by_tos,
    "dr_pmt": compute_dr_pmt_by_tos,
}


# --- section 2: every Exhibit 36 row ---------------------------------------


def test_exhibit_36_table_pinned_verbatim(dr_golden_expected):
    """The 8-row classification table matches the tracker's verbatim
    Exhibit 36 quotes, one for one — no row added, dropped, or reclassified
    without a new golden."""
    expected_rows = dr_golden_expected["exhibit36_rows"]
    assert len(EXHIBIT_36) == len(expected_rows) == 8
    for row, exp in zip(EXHIBIT_36, expected_rows):
        assert row.activity == exp["activity"]
        assert row.actual is exp["actual"]
        assert row.revenue is exp["revenue"]
        assert row.miles_not_applicable is exp["miles_not_applicable"]
    # The no-show row carries the tracker's quoted wording.
    no_show = next(r for r in EXHIBIT_36 if r.activity == "no_show_trip")
    assert "no-show" in no_show.description


def test_exhibit_36_every_row_realized_behaviorally(
    dr_golden_fixture, dr_golden_expected
):
    """One scenario per Exhibit 36 row: the span semantics produce exactly
    the hand-worked hours/miles (BASIS.md section 2)."""
    scenarios = dr_golden_fixture["exhibit36_scenarios"]
    expected = dr_golden_expected["exhibit36_scenarios"]
    assert set(scenarios) == set(expected) == {r.activity for r in EXHIBIT_36}
    for activity in sorted(scenarios):
        trips = load_dr_trips(scenarios[activity])
        exp = expected[activity]
        vrh = compute_dr_vrh(trips)
        vrm = compute_dr_vrm(trips)
        assert vrh.value == Decimal(exp["vrh"]), activity
        assert vrm.value == Decimal(exp["vrm"]), activity
        if "upt" in exp:
            assert compute_dr_upt(trips).value == Decimal(exp["upt"]), activity
        # Real-source scenarios: no simulated-source info finding.
        assert vrh.infos == () and vrm.infos == ()
        assert vrh.blocking_issues == () and vrm.blocking_issues == ()


# --- section 1: the hand-worked dispatch day --------------------------------


def _day_trips(fixture):
    return load_dr_trips(fixture["dispatch_day"])


def test_golden_dispatch_day_all_five_calcs(dr_golden_fixture, dr_golden_expected):
    trips = _day_trips(dr_golden_fixture)
    for key, compute in _COMPUTES.items():
        exp = dr_golden_expected["dispatch_day"][key]
        result = compute(trips)
        assert result.calc_name == exp["calc_name"], key
        assert result.calc_version == exp["calc_version"] == "0.1.0", key
        assert result.unit == exp["unit"], key
        assert result.value == Decimal(exp["value"]), key
        assert result.detail.to_dict() == exp["detail"], key
        assert result.blocking_issues == ()  # DR calcs never block (documented)
        if "input_record_ids" in exp:
            assert list(result.input_record_ids) == exp["input_record_ids"], key
        assert [f.issue_type for f in result.infos] == exp["info_issue_types"], key
        if "warnings" in exp:
            assert [
                (w.issue_type, list(w.source_record_ids)) for w in result.warnings
            ] == [
                (w["issue_type"], w["source_record_ids"]) for w in exp["warnings"]
            ], key


def test_golden_no_show_asymmetry_explicit(dr_golden_fixture):
    """The handoff-0013 explicit golden: a no-show is revenue time YES and
    UPT ZERO (Exhibit 36's no-show row against the pp. 143-144 boarding
    definition). Over the no_show_trip scenario (one completed trip
    10:00-10:20, then a no-show visit 10:30-10:35, no interruption
    markers): removing the no-show LOWERS revenue hours (the span no longer
    extends through the visit) and leaves UPT UNCHANGED."""
    scenario = dr_golden_fixture["exhibit36_scenarios"]["no_show_trip"]
    trips = load_dr_trips(scenario)
    without_no_show = [t for t in trips if not t.no_show]

    # Revenue time YES: 35 min with the no-show vs 20 min without.
    assert compute_dr_vrh(trips).value == Decimal("0.58")
    assert compute_dr_vrh(without_no_show).value == Decimal("0.33")

    # UPT ZERO: identical count with and without the no-show visit.
    assert compute_dr_upt(trips).value == Decimal("1")
    assert compute_dr_upt(without_no_show).value == Decimal("1")
    # ... and the no-show is visible in the detail, never in the count.
    assert compute_dr_upt(trips).detail.no_show_trips == 1


def test_golden_dispatch_day_by_tos(dr_golden_fixture, dr_golden_expected):
    """Per-TOS decomposition (BASIS.md section 1): the additive metrics'
    TOS parts sum to the mode figure; VOMS does not add (documented)."""
    trips = _day_trips(dr_golden_fixture)
    expected = dr_golden_expected["dispatch_day"]["by_tos"]
    for key, by_tos in _BY_TOS.items():
        results = by_tos(trips)
        assert sorted(results) == sorted(expected["DO"].keys() and ["DO", "TX"])
        for tos in ("DO", "TX"):
            assert results[tos].value == Decimal(expected[tos][key]), (key, tos)
    # Additivity of the additive metrics (VOMS excluded by design).
    for key in ("dr_vrh", "dr_vrm", "dr_upt", "dr_pmt"):
        mode_value = _COMPUTES[key](trips).value
        parts = _BY_TOS[key](trips)
        assert mode_value == sum(r.value for r in parts.values()), key


# --- section 3: Exhibit 40 Happy Transit ------------------------------------


def test_golden_exhibit_40_happy_transit(dr_golden_fixture, dr_golden_expected):
    """Six unique vehicles across the day, max four simultaneous -> VOMS 4
    (Exhibits 38 + 40 as quoted in the tracker: 'at any one time',
    INCLUDES atypical service)."""
    trips = load_dr_trips(dr_golden_fixture["exhibit40_happy_transit"])
    exp = dr_golden_expected["exhibit40_happy_transit"]
    result = compute_dr_voms(trips)
    assert result.value == Decimal(exp["value"]) == Decimal("4")
    assert result.detail.to_dict() == exp["detail"]
    assert result.detail.unique_vehicles == 6
    assert result.detail.includes_atypical_days is True
    # Lineage: the four vehicles in service at the peak instant.
    assert list(result.input_record_ids) == exp["input_record_ids"]
    # Real source: the simulated-source info finding is ABSENT.
    assert result.infos == ()
    assert result.warnings == () and result.blocking_issues == ()
