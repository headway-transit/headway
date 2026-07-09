"""Golden-dataset regression tests for vrm_v0 / vrh_v0 CALC_VERSION 0.1.0.

Fixture basis: synthetic hand-worked example (tests/golden/vrm_vrh_v0/BASIS.md)
— NOT an FTA-certified figure; regression anchor only.

Pinned to the RETAINED 0.1.0 functions (compute_vrm_v0_1/compute_vrh_v0_1 —
all-or-nothing gap refusal), aliased to the names below so the test bodies are
byte-identical to the 0.1.0 originals; historical submissions recompute
bit-for-bit. The 0.2.0 gap policy has its own goldens in test_golden_v02.py.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import load_positions

from headway_calc.vrh import compute_vrh_v0_1 as compute_vrh
from headway_calc.vrm import compute_vrm_v0_1 as compute_vrm


def _clean_subset(fixture, expected):
    excluded = set(expected["clean_subset"]["excluded_trip_ids"])
    return [
        p for p in load_positions(fixture) if p.trip_id not in excluded
    ]


def test_golden_vrm_clean_subset(golden_fixture, golden_expected):
    exp = golden_expected["clean_subset"]
    result = compute_vrm(
        _clean_subset(golden_fixture, golden_expected),
        gap_threshold_seconds=golden_fixture["gap_threshold_seconds"],
    )
    assert result.blocking_issues == ()
    assert result.value == Decimal(exp["vrm"]["value"])
    assert result.unit == "miles"
    assert result.calc_name == "vrm_v0"
    assert result.calc_version == "0.1.0"
    assert sorted(result.input_record_ids) == exp["input_record_ids"]


def test_golden_vrm_per_group(golden_fixture, golden_expected):
    positions = _clean_subset(golden_fixture, golden_expected)
    for key, exp_value in golden_expected["clean_subset"]["vrm"]["per_group"].items():
        vehicle_id, trip_id = key.split("|")
        group = [p for p in positions if p.vehicle_id == vehicle_id and p.trip_id == trip_id]
        assert group, f"empty golden group {key}"
        result = compute_vrm(group)
        assert result.value == Decimal(exp_value), key


def test_golden_vrh_clean_subset(golden_fixture, golden_expected):
    exp = golden_expected["clean_subset"]
    result = compute_vrh(
        _clean_subset(golden_fixture, golden_expected),
        gap_threshold_seconds=golden_fixture["gap_threshold_seconds"],
    )
    assert result.blocking_issues == ()
    assert result.value == Decimal(exp["vrh"]["value"])
    assert result.unit == "hours"
    assert result.calc_name == "vrh_v0"
    assert result.calc_version == "0.1.0"
    assert sorted(result.input_record_ids) == exp["input_record_ids"]


def test_golden_vrh_per_group(golden_fixture, golden_expected):
    positions = _clean_subset(golden_fixture, golden_expected)
    for key, exp_value in golden_expected["clean_subset"]["vrh"]["per_group"].items():
        vehicle_id, trip_id = key.split("|")
        group = [p for p in positions if p.vehicle_id == vehicle_id and p.trip_id == trip_id]
        result = compute_vrh(group)
        assert result.value == Decimal(exp_value), key


def test_golden_full_fixture_refuses_over_gap(golden_fixture, golden_expected):
    """The full fixture contains a >threshold gap: both calcs must refuse."""
    exp = golden_expected["full_fixture"]
    positions = load_positions(golden_fixture)
    threshold = golden_fixture["gap_threshold_seconds"]

    for compute in (compute_vrm, compute_vrh):
        result = compute(positions, gap_threshold_seconds=threshold)
        assert result.value is None
        assert len(result.blocking_issues) == 1
        issue = result.blocking_issues[0]
        assert issue.issue_type == exp["blocking_issue"]["issue_type"]
        assert list(issue.source_record_ids) == exp["blocking_issue"]["source_record_ids"]
        # Unassigned (trip_id null) positions are never consumed.
        for rec_id in exp["ignored_unassigned_record_ids"]:
            assert rec_id not in result.input_record_ids
