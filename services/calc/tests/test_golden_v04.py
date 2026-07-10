"""Golden-dataset regression tests for vrh_v0 CALC_VERSION 0.4.0.

Trip-level excision per handoff 0004: a within-trip gap excises ONLY the
gapped trip's running time plus its adjacent inter-trip layover intervals
(a layover interval counts only when BOTH bounding trips are clean); the
block's clean remainder stays. Fixture:
tests/golden/vrm_vrh_v0/fixture_block_v04.json (one block of three trips,
600 s layovers, the MIDDLE trip gapped); expectations: expected_v0_4.json,
hand-worked in BASIS.md ("Calc 0.4.0" section) — NOT an FTA-certified
figure; regression anchor only.

Asserted here: v0.4 keeps trips F+H's running time (0.17 h) and drops trip G
plus BOTH adjacent layovers; the retained v0.3 excludes the WHOLE block
(0.00 h) and the retained v0.2 also yields 0.17 h (no layover to recover on
this fixture); the default 0.95 threshold blocks at trip coverage 2/3; and
the CLEAN two-trip fixture_block.json under v0.4 reproduces the 0.3.0 value
0.33 h exactly (clean-adjacent layover still included).
"""

from __future__ import annotations

from decimal import Decimal

from conftest import load_positions

from headway_calc.vrh import compute_vrh, compute_vrh_v0_2, compute_vrh_v0_3


def test_golden_v04_middle_trip_excision_keeps_clean_remainder(
    golden_block_v04_fixture, golden_expected_v0_4
):
    exp = golden_expected_v0_4["block_v04_fixture"]["vrh_v0_4"]
    positions = load_positions(golden_block_v04_fixture)
    result = compute_vrh(
        positions,
        gap_threshold_seconds=golden_block_v04_fixture["gap_threshold_seconds"],
        coverage_threshold=Decimal(exp["coverage_threshold"]),
        layover_max_seconds=golden_block_v04_fixture["layover_max_seconds"],
    )

    assert result.calc_name == "vrh_v0"
    assert result.calc_version == "0.4.0"
    assert result.blocking_issues == ()
    assert result.value == Decimal(exp["value"])
    assert result.unit == exp["unit"]
    assert result.detail is not None
    assert result.detail.to_dict() == exp["detail"]
    # Lineage covers INCLUDED positions only (trips F and H).
    assert sorted(result.input_record_ids) == exp["input_record_ids"]

    # One telemetry_gap_excluded warning PER EXCISED TRIP, citing that
    # trip's records only (never trip-F's or trip-H's).
    assert len(result.warnings) == len(exp["warnings"])
    for warning, exp_warning in zip(result.warnings, exp["warnings"]):
        assert warning.issue_type == exp_warning["issue_type"]
        assert warning.severity == exp_warning["severity"]
        assert exp_warning["trip_id"] in warning.title
        assert list(warning.source_record_ids) == exp_warning["source_record_ids"]
    assert result.infos == ()  # block_id present: no fallback documentation


def test_golden_v04_default_threshold_blocks_at_trip_coverage(
    golden_block_v04_fixture, golden_expected_v0_4
):
    """Trip-denominated coverage 2/3 < 0.95 default: blocked, value None,
    one blocking finding citing the excised trip's records."""
    exp = golden_expected_v0_4["block_v04_fixture"][
        "vrh_v0_4_default_threshold_blocked"
    ]
    positions = load_positions(golden_block_v04_fixture)
    result = compute_vrh(
        positions,
        gap_threshold_seconds=golden_block_v04_fixture["gap_threshold_seconds"],
        layover_max_seconds=golden_block_v04_fixture["layover_max_seconds"],
    )

    assert result.value is None
    assert len(result.blocking_issues) == 1
    blocking = result.blocking_issues[0]
    assert blocking.issue_type == exp["blocking_issue_type"]
    assert list(blocking.source_record_ids) == exp["blocking_source_record_ids"]


def test_golden_v04_retained_v03_excludes_the_whole_block(
    golden_block_v04_fixture, golden_expected_v0_4
):
    """The identical positions under the retained 0.3.0: block-level
    exclusion drops trips F+H's clean running time too — the hand-worked
    harshness v0.4 refines away (BASIS.md)."""
    exp = golden_expected_v0_4["block_v04_fixture"]
    positions = load_positions(golden_block_v04_fixture)
    result = compute_vrh_v0_3(
        positions,
        gap_threshold_seconds=golden_block_v04_fixture["gap_threshold_seconds"],
        coverage_threshold=Decimal(exp["vrh_v0_3_comparison"]["coverage_threshold"]),
        layover_max_seconds=golden_block_v04_fixture["layover_max_seconds"],
    )

    assert result.calc_version == "0.3.0"
    assert result.blocking_issues == ()
    assert result.value == Decimal(exp["vrh_v0_3_comparison"]["value"])
    assert result.detail.total_groups == exp["vrh_v0_3_comparison"]["total_groups"]
    assert result.detail.excluded_groups == (
        exp["vrh_v0_3_comparison"]["excluded_groups"]
    )
    # v0.4 >= v0.3 on identical input: 0.17 h recovered from the clean trips.
    assert Decimal(exp["vrh_v0_4"]["value"]) >= result.value


def test_golden_v04_retained_v02_matches_on_this_fixture(
    golden_block_v04_fixture, golden_expected_v0_4
):
    """The identical positions under the retained 0.2.0: per-trip exclusion
    also drops only trip-G, and with both layovers excision-adjacent there is
    no layover left for v0.4 to recover — v0.4 == v0.2 here (>= in general)."""
    exp = golden_expected_v0_4["block_v04_fixture"]
    positions = load_positions(golden_block_v04_fixture)
    result = compute_vrh_v0_2(
        positions,
        gap_threshold_seconds=golden_block_v04_fixture["gap_threshold_seconds"],
        coverage_threshold=Decimal(exp["vrh_v0_2_comparison"]["coverage_threshold"]),
    )

    assert result.calc_version == "0.2.0"
    assert result.blocking_issues == ()
    assert result.value == Decimal(exp["vrh_v0_2_comparison"]["value"])
    assert result.detail.total_groups == exp["vrh_v0_2_comparison"]["total_groups"]
    assert Decimal(exp["vrh_v0_4"]["value"]) >= result.value


def test_golden_v04_clean_block_reproduces_v03_value_exactly(
    golden_block_fixture, golden_expected_v0_4
):
    """fixture_block.json (two CLEAN trips) under v0.4: nothing is excised
    and the clean-adjacent 600 s layover stays included — the 0.3.0 golden
    value 0.33 h is reproduced exactly, detail now trip-denominated."""
    exp = golden_expected_v0_4["clean_block_fixture_v0_4"]
    positions = load_positions(golden_block_fixture)
    result = compute_vrh(
        positions,
        gap_threshold_seconds=golden_block_fixture["gap_threshold_seconds"],
        layover_max_seconds=golden_block_fixture["layover_max_seconds"],
    )

    assert result.calc_version == "0.4.0"
    assert result.blocking_issues == ()
    assert result.warnings == ()
    assert result.value == Decimal(exp["value"])
    assert result.unit == exp["unit"]
    assert result.detail.to_dict() == exp["detail"]
