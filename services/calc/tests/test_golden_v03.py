"""Golden-dataset regression tests for vrh_v0 CALC_VERSION 0.3.0.

Block-aware layover inclusion per handoff 0003 (closes divergence D1: the FTA
includes layover/recovery time in VRH — Exhibit 35). Fixture:
tests/golden/vrm_vrh_v0/fixture_block.json (two trips of one vehicle in one
block, 600 s layover); expectations: expected_v0_3.json, hand-worked in
BASIS.md ("Calc 0.3.0" section) — NOT an FTA-certified figure; regression
anchor only.

Asserted here: v0.3 INCLUDES the 600 s layover (0.33 h); the retained v0.2
comparison value over the identical positions EXCLUDES it (0.17 h); VRM stays
0.2.0 (6.91 mi — layover miles N/A per Exhibit 35); and the ORIGINAL
no-block_id fixture falls back to per-trip grouping reproducing the 0.2.0
VRH value exactly, plus one block_unavailable INFO finding per vehicle-day.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import load_positions

from headway_calc.vrh import compute_vrh, compute_vrh_v0_2
from headway_calc.vrm import compute_vrm


def test_golden_v03_block_fixture_includes_layover(
    golden_block_fixture, golden_expected_v0_3
):
    exp = golden_expected_v0_3["block_fixture"]["vrh_v0_3"]
    positions = load_positions(golden_block_fixture)
    result = compute_vrh(
        positions,
        gap_threshold_seconds=golden_block_fixture["gap_threshold_seconds"],
        layover_max_seconds=golden_block_fixture["layover_max_seconds"],
    )

    assert result.calc_name == "vrh_v0"
    assert result.calc_version == "0.3.0"
    assert result.blocking_issues == ()
    assert result.warnings == ()  # 600 s <= 1800 s cap: no layover finding
    assert result.infos == ()  # block_id present: no fallback documentation
    assert result.value == Decimal(exp["value"])
    assert result.unit == exp["unit"]
    assert result.detail is not None
    assert result.detail.to_dict() == exp["detail"]
    # Lineage covers ALL positions of the included block group.
    assert sorted(result.input_record_ids) == exp["input_record_ids"]


def test_golden_v03_retained_v02_excludes_the_layover(
    golden_block_fixture, golden_expected_v0_3
):
    """The identical positions under the retained 0.2.0: per-trip grouping
    drops the 600 s — the hand-worked D1 undercount (BASIS.md)."""
    exp = golden_expected_v0_3["block_fixture"]
    positions = load_positions(golden_block_fixture)
    result = compute_vrh_v0_2(
        positions,
        gap_threshold_seconds=golden_block_fixture["gap_threshold_seconds"],
    )

    assert result.calc_version == "0.2.0"
    assert result.blocking_issues == ()
    assert result.value == Decimal(exp["vrh_v0_2_comparison"]["value"])
    assert result.detail.total_groups == exp["vrh_v0_2_comparison"]["total_groups"]
    # v0.3 - v0.2 == the 600 s layover, quantized: 0.33 - 0.17 = 0.16 h.
    v03_value = Decimal(exp["vrh_v0_3"]["value"])
    assert v03_value - result.value == Decimal("0.16")
    assert v03_value > result.value


def test_golden_v03_vrm_unchanged_at_v02(golden_block_fixture, golden_expected_v0_3):
    """VRM stays 0.2.0 on the block fixture: layover miles are N/A per
    Exhibit 35, so per-trip grouping remains correct for miles."""
    exp = golden_expected_v0_3["block_fixture"]["vrm_v0_2"]
    positions = load_positions(golden_block_fixture)
    result = compute_vrm(
        positions,
        gap_threshold_seconds=golden_block_fixture["gap_threshold_seconds"],
    )
    assert result.calc_version == "0.2.0"
    assert result.blocking_issues == ()
    assert result.value == Decimal(exp["value"])
    assert result.unit == exp["unit"]


def test_golden_v03_no_block_fixture_falls_back_per_trip(
    golden_fixture, golden_expected, golden_expected_v0_3
):
    """The ORIGINAL fixture (no block_id anywhere), clean subset, under v0.3:
    per-trip fallback reproduces the 0.2.0 value exactly, with one
    block_unavailable INFO finding per vehicle-day — the figure stands."""
    exp = golden_expected_v0_3["original_fixture_fallback"]
    excluded = set(golden_expected["clean_subset"]["excluded_trip_ids"])
    positions = [p for p in load_positions(golden_fixture) if p.trip_id not in excluded]
    result = compute_vrh(
        positions, gap_threshold_seconds=golden_fixture["gap_threshold_seconds"]
    )

    assert result.calc_version == "0.3.0"
    assert result.blocking_issues == ()
    assert result.warnings == ()
    assert result.value == Decimal(exp["vrh_value"])
    assert result.detail.to_dict() == exp["detail"]

    assert len(result.infos) == len(exp["infos"])
    for info, exp_info in zip(result.infos, exp["infos"]):
        assert info.issue_type == exp_info["issue_type"]
        assert info.severity == exp_info["severity"]
        assert exp_info["vehicle_id"] in info.title
        assert list(info.source_record_ids) == exp_info["source_record_ids"]
