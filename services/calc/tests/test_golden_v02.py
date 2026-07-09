"""Golden-dataset regression tests for vrm_v0 / vrh_v0 CALC_VERSION 0.2.0.

Gap policy per handoff 0002 (per-group exclusion + coverage), over the SAME
fixture as the 0.1.0 goldens. Expectations: tests/golden/vrm_vrh_v0/
expected_v0_2.json, hand-worked in BASIS.md ("Calc 0.2.0" section) — NOT an
FTA-certified figure; regression anchor only.

Two cases: (A) the full fixture at the DEFAULT coverage_threshold 0.95 →
coverage 2/3 is below the line, ONE blocking coverage_below_threshold finding,
value None, and (B) an explicit coverage_threshold 0.5 → the gapped trip-C
group is excluded with one warning finding and the figure equals the
clean-group values (VRM 12.44 mi / VRH 0.45 h) with exact coverage detail.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import load_positions

from headway_calc.vrh import compute_vrh
from headway_calc.vrm import compute_vrm


def test_golden_v02_default_threshold_blocks_below_coverage(
    golden_fixture, golden_expected_v0_2
):
    """Full fixture, default coverage_threshold 0.95: blocked, value None."""
    exp = golden_expected_v0_2["default_coverage_threshold"]
    positions = load_positions(golden_fixture)
    threshold = golden_fixture["gap_threshold_seconds"]

    for compute in (compute_vrm, compute_vrh):
        result = compute(positions, gap_threshold_seconds=threshold)
        assert result.calc_version == "0.2.0"
        assert result.value is None

        assert len(result.blocking_issues) == 1
        blocking = result.blocking_issues[0]
        assert blocking.issue_type == exp["blocking_issue"]["issue_type"]
        assert blocking.severity == exp["blocking_issue"]["severity"]
        assert (
            sorted(blocking.source_record_ids)
            == exp["blocking_issue"]["source_record_ids"]
        )

        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert warning.issue_type == exp["warning"]["issue_type"]
        assert warning.severity == exp["warning"]["severity"]
        assert list(warning.source_record_ids) == exp["warning"]["source_record_ids"]

        assert result.detail is not None
        assert result.detail.to_dict() == exp["detail"]

        # Provenance narrows correctly even when blocked: included groups only.
        for rec_id in exp["warning"]["source_record_ids"]:
            assert rec_id not in result.input_record_ids


def test_golden_v02_lowered_threshold_excludes_gapped_group(
    golden_fixture, golden_expected_v0_2
):
    """Full fixture, explicit coverage_threshold 0.5: clean-group values."""
    exp = golden_expected_v0_2["lowered_coverage_threshold"]
    positions = load_positions(golden_fixture)
    threshold = golden_fixture["gap_threshold_seconds"]
    coverage_threshold = Decimal(exp["coverage_threshold"])

    for compute, metric_exp in (
        (compute_vrm, exp["vrm"]),
        (compute_vrh, exp["vrh"]),
    ):
        result = compute(
            positions,
            gap_threshold_seconds=threshold,
            coverage_threshold=coverage_threshold,
        )
        assert result.calc_version == "0.2.0"
        assert result.blocking_issues == ()
        assert result.value == Decimal(metric_exp["value"])
        assert result.unit == metric_exp["unit"]

        assert len(result.warnings) == 1
        warning = result.warnings[0]
        assert warning.issue_type == exp["warning"]["issue_type"]
        assert warning.severity == exp["warning"]["severity"]
        assert list(warning.source_record_ids) == exp["warning"]["source_record_ids"]

        assert result.detail is not None
        assert result.detail.to_dict() == exp["detail"]

        # input_record_ids ONLY from included groups (handoff 0002, rule 5).
        assert sorted(result.input_record_ids) == exp["input_record_ids"]


def test_golden_v02_clean_subset_full_coverage(golden_fixture, golden_expected):
    """The 0.1.0 clean subset under 0.2.0: full coverage, identical values —
    the policy change alters nothing when there is nothing to exclude."""
    excluded = set(golden_expected["clean_subset"]["excluded_trip_ids"])
    positions = [p for p in load_positions(golden_fixture) if p.trip_id not in excluded]
    threshold = golden_fixture["gap_threshold_seconds"]

    for compute, exp_value in (
        (compute_vrm, golden_expected["clean_subset"]["vrm"]["value"]),
        (compute_vrh, golden_expected["clean_subset"]["vrh"]["value"]),
    ):
        result = compute(positions, gap_threshold_seconds=threshold)
        assert result.calc_version == "0.2.0"
        assert result.blocking_issues == ()
        assert result.warnings == ()
        assert result.value == Decimal(exp_value)
        assert result.detail.to_dict() == {
            "coverage": "1.0000",
            "total_groups": 2,
            "excluded_groups": 0,
            "clean_position_share": "1.0000",
            "gap_threshold_seconds": 300.0,
            "coverage_threshold": "0.95",
        }
