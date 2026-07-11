"""Detector math (hand-worked), severities, plain language, determinism.

No test here touches a network, clock, or database: detectors are pure
functions over injected history rows.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from headway_ai.anomaly import (
    COVERAGE_DROP_THRESHOLD,
    ISSUE_TYPE_CALC_VERSION_CHANGE,
    ISSUE_TYPE_COVERAGE_DROP,
    ISSUE_TYPE_SWING,
    SWING_THRESHOLD,
    AnomalyFinding,
    detect_all,
    detect_calc_version_changes,
    detect_coverage_drops,
    detect_metric_swings,
    normalize_history,
)


def row(
    mvid: str,
    value: str,
    period_start: str,
    period_end: str,
    *,
    metric: str = "vrm",
    calc_version: str = "0.2.0",
    detail: dict | None = None,
) -> dict:
    return {
        "metric_value_id": mvid,
        "metric": metric,
        "value": value,
        "period_start": period_start,
        "period_end": period_end,
        "calc_version": calc_version,
        "detail": detail if detail is not None else {},
    }


MAY = ("2026-05-01", "2026-06-01")
JUNE = ("2026-06-01", "2026-07-01")
JULY = ("2026-07-01", "2026-08-01")


class TestSwingDetectorMath:
    def test_exactly_at_threshold_does_not_flag(self):
        # Hand-worked: 100.00 -> 125.00 is a delta of 25.00; the threshold
        # boundary is 0.25 * 100.00 = 25.00 exactly. Strictly-greater rule:
        # no finding. Same for the downward boundary 100.00 -> 75.00.
        history = [
            row("mv-1", "100.00", *MAY),
            row("mv-2", "125.00", *JUNE),
            row("mv-3", "93.75", *JULY),  # |93.75-125.00| = 31.25 == 0.25*125.00
        ]
        assert detect_metric_swings(history) == ()

    def test_just_over_threshold_flags_upward(self):
        # 100.00 -> 125.01: delta 25.01 > 25.00.
        history = [row("mv-1", "100.00", *MAY), row("mv-2", "125.01", *JUNE)]
        findings = detect_metric_swings(history)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.issue_type == ISSUE_TYPE_SWING
        assert finding.severity == "warning"
        assert finding.cited_metric_value_ids == ("mv-1", "mv-2")

    def test_just_over_threshold_flags_downward(self):
        # 100.00 -> 74.99: delta 25.01 > 25.00.
        history = [row("mv-1", "100.00", *MAY), row("mv-2", "74.99", *JUNE)]
        assert len(detect_metric_swings(history)) == 1

    def test_zero_previous_value_flags_any_change(self):
        # |5.00 - 0| > 0.25 * 0 — exact Decimal comparison, no division.
        history = [row("mv-1", "0.00", *MAY), row("mv-2", "5.00", *JUNE)]
        assert len(detect_metric_swings(history)) == 1

    def test_zero_to_zero_does_not_flag(self):
        history = [row("mv-1", "0.00", *MAY), row("mv-2", "0.00", *JUNE)]
        assert detect_metric_swings(history) == ()

    def test_custom_threshold_is_exact_decimal(self):
        # threshold 0.10: 100.00 -> 110.00 is exactly at, 110.01 is over.
        at = [row("mv-1", "100.00", *MAY), row("mv-2", "110.00", *JUNE)]
        over = [row("mv-1", "100.00", *MAY), row("mv-2", "110.01", *JUNE)]
        assert detect_metric_swings(at, swing_threshold=Decimal("0.10")) == ()
        assert len(detect_metric_swings(over, swing_threshold=Decimal("0.10"))) == 1

    def test_threshold_must_be_decimal_and_positive(self):
        history = [row("mv-1", "100.00", *MAY), row("mv-2", "200.00", *JUNE)]
        with pytest.raises(TypeError):
            detect_metric_swings(history, swing_threshold=0.25)  # float refused
        with pytest.raises(ValueError):
            detect_metric_swings(history, swing_threshold=Decimal("0"))

    def test_different_metrics_are_never_compared(self):
        history = [
            row("mv-1", "100.00", *MAY, metric="vrm"),
            row("mv-2", "9000.00", *JUNE, metric="vrh"),
        ]
        assert detect_metric_swings(history) == ()

    def test_consecutive_pairs_only_within_metric(self):
        # Three periods -> two comparisons; both swings flag independently.
        history = [
            row("mv-1", "100.00", *MAY),
            row("mv-2", "200.00", *JUNE),
            row("mv-3", "100.00", *JULY),
        ]
        findings = detect_metric_swings(history)
        assert [f.cited_metric_value_ids for f in findings] == [
            ("mv-1", "mv-2"),
            ("mv-2", "mv-3"),
        ]


class TestCoverageDropDetector:
    def test_exactly_at_threshold_does_not_flag(self):
        # 0.97 -> 0.92 is a drop of exactly 0.05: strictly-greater, no flag.
        history = [
            row("mv-1", "100.00", *MAY, detail={"coverage": "0.97"}),
            row("mv-2", "101.00", *JUNE, detail={"coverage": "0.92"}),
        ]
        assert detect_coverage_drops(history) == ()

    def test_drop_over_threshold_flags(self):
        # 0.98 -> 0.92: drop 0.06 > 0.05.
        history = [
            row("mv-1", "100.00", *MAY, detail={"coverage": "0.98"}),
            row("mv-2", "101.00", *JUNE, detail={"coverage": "0.92"}),
        ]
        findings = detect_coverage_drops(history)
        assert len(findings) == 1
        assert findings[0].issue_type == ISSUE_TYPE_COVERAGE_DROP
        assert findings[0].severity == "warning"
        assert findings[0].cited_metric_value_ids == ("mv-1", "mv-2")
        # Both coverage strings restated verbatim — never a derived delta.
        assert "0.98" in findings[0].description
        assert "0.92" in findings[0].description
        assert "0.06" not in findings[0].description

    def test_coverage_increase_never_flags(self):
        history = [
            row("mv-1", "100.00", *MAY, detail={"coverage": "0.80"}),
            row("mv-2", "101.00", *JUNE, detail={"coverage": "0.99"}),
        ]
        assert detect_coverage_drops(history) == ()

    def test_rows_without_coverage_are_skipped(self):
        # upt_v0's UptDetail has no coverage ratio: not an anomaly here.
        history = [
            row("mv-1", "100.00", *MAY, metric="upt", detail={"missing_share": "0.01"}),
            row("mv-2", "10.00", *JUNE, metric="upt", detail={"missing_share": "0.01"}),
        ]
        assert detect_coverage_drops(history) == ()

    def test_unparseable_coverage_fails_loudly(self):
        history = [
            row("mv-1", "100.00", *MAY, detail={"coverage": "0.97"}),
            row("mv-2", "101.00", *JUNE, detail={"coverage": "not-a-number"}),
        ]
        with pytest.raises(ValueError, match="unparseable coverage"):
            detect_coverage_drops(history)


class TestCalcVersionChangeDetector:
    def test_version_change_emits_info_citing_both_rows(self):
        history = [
            row("mv-1", "100.00", *MAY, metric="vrh", calc_version="0.3.0"),
            row("mv-2", "101.00", *JUNE, metric="vrh", calc_version="0.4.0"),
        ]
        findings = detect_calc_version_changes(history)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.issue_type == ISSUE_TYPE_CALC_VERSION_CHANGE
        assert finding.severity == "info"
        assert finding.cited_metric_value_ids == ("mv-1", "mv-2")
        assert "0.3.0" in finding.description
        assert "0.4.0" in finding.description
        assert "not directly comparable" in finding.description

    def test_same_version_never_flags(self):
        history = [
            row("mv-1", "100.00", *MAY),
            row("mv-2", "500.00", *JUNE),  # huge swing, same version
        ]
        assert detect_calc_version_changes(history) == ()


class TestFindingContract:
    def test_blocking_severity_is_unrepresentable(self):
        with pytest.raises(ValueError, match="never blocks"):
            AnomalyFinding(
                issue_type=ISSUE_TYPE_SWING,
                severity="blocking",
                metric="vrm",
                title="t",
                description="cites mv-1",
                cited_metric_value_ids=("mv-1",),
            )

    def test_description_must_cite_every_metric_value_id(self):
        with pytest.raises(ValueError, match="must cite metric_value_id"):
            AnomalyFinding(
                issue_type=ISSUE_TYPE_SWING,
                severity="warning",
                metric="vrm",
                title="t",
                description="mentions mv-1 only",
                cited_metric_value_ids=("mv-1", "mv-2"),
            )

    def test_descriptions_are_plain_language_and_cite_ids(self):
        history = [
            row("mv-prev", "120.00", *MAY),
            row("mv-cur", "168.00", *JUNE),
        ]
        (finding,) = detect_metric_swings(history)
        for cited in ("mv-prev", "mv-cur"):
            assert cited in finding.description
        # Raw value strings restated verbatim; no derived percent anywhere.
        assert "120.00" in finding.description and "168.00" in finding.description
        assert "%" not in finding.description
        assert "48" not in finding.description  # never states the computed delta (168-120)
        assert "0.40" not in finding.description  # never states the computed ratio
        # The human-decides / never-corrects stance is restated to the reader.
        for phrase in ("does not block", "human", "no reported figure was changed"):
            assert phrase in finding.description

    def test_flags_never_carry_corrected_values(self):
        # The finding restates only the two raw values; it never proposes a
        # replacement, fill, or adjusted number.
        history = [row("mv-1", "0.00", *MAY), row("mv-2", "80.00", *JUNE)]
        (finding,) = detect_metric_swings(history)
        assert finding.severity in ("info", "warning")
        assert "80.00" in finding.description and "0.00" in finding.description


class TestNormalizationAndDeterminism:
    def test_normalize_orders_rows_regardless_of_input_order(self):
        shuffled = [
            row("mv-2", "101.00", *JUNE),
            row("mv-1", "100.00", *MAY),
        ]
        ordered = normalize_history(shuffled)
        assert [r.metric_value_id for r in ordered] == ["mv-1", "mv-2"]

    def test_missing_key_fails_loudly(self):
        bad = {"metric_value_id": "mv-1", "metric": "vrm", "value": "1"}
        with pytest.raises(ValueError, match="missing required key"):
            normalize_history([bad])

    def test_non_decimal_value_fails_loudly(self):
        with pytest.raises(ValueError, match="not a valid Decimal"):
            normalize_history([row("mv-1", "twelve", *MAY)])

    def test_detect_all_is_deterministic_and_ordered(self):
        history = [
            row("mv-3", "40.00", *JULY, calc_version="0.3.0", detail={"coverage": "0.80"}),
            row("mv-1", "100.00", *MAY, detail={"coverage": "0.97"}),
            row("mv-2", "101.00", *JUNE, detail={"coverage": "0.90"}),
        ]
        first = detect_all(history)
        second = detect_all(list(reversed(history)))
        assert first == second
        # swing (mv-2 -> mv-3), coverage drops (both pairs), version change.
        assert [f.issue_type for f in first] == [
            ISSUE_TYPE_SWING,
            ISSUE_TYPE_COVERAGE_DROP,
            ISSUE_TYPE_COVERAGE_DROP,
            ISSUE_TYPE_CALC_VERSION_CHANGE,
        ]
        assert all(f.severity in ("info", "warning") for f in first)
