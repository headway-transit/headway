"""Unit tests for headway_calc.persist with a fake DB-API connection.

No live database: the fake captures every SQL statement + params so the
INSERTs can be asserted against the handoff-0001 schema (plus the
migration-0010 detail column, handoff 0002) exactly.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from headway_calc.persist import persist_result
from headway_calc.types import BlockingIssue, CalcResult, CoverageDetail, Finding

FAKE_METRIC_VALUE_ID = "11111111-2222-3333-4444-555555555555"


class FakeCursor:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return (FAKE_METRIC_VALUE_ID,)


class FakeConnection:
    def __init__(self):
        self._cursor = FakeCursor()

    def cursor(self):
        return self._cursor


def _ok_result():
    return CalcResult(
        value=Decimal("12.44"),
        unit="miles",
        calc_name="vrm_v0",
        calc_version="0.1.0",
        input_record_ids=("rec-a-00", "rec-a-01", "rec-b-00"),
        blocking_issues=(),
    )


def _detail():
    return CoverageDetail(
        coverage=Decimal("0.6667"),
        total_groups=3,
        excluded_groups=1,
        clean_position_share=Decimal("0.8333"),
        gap_threshold_seconds=300.0,
        coverage_threshold=Decimal("0.5"),
    )


def test_persist_writes_metric_value_and_lineage_edges():
    conn = FakeConnection()
    metric_value_id = persist_result(
        conn, _ok_result(), period_start=date(2026, 1, 1), period_end=date(2026, 1, 31)
    )
    assert metric_value_id == FAKE_METRIC_VALUE_ID

    executed = conn._cursor.executed
    assert len(executed) == 1 + 3  # one metric_values insert + one edge per input record

    mv_sql, mv_params = executed[0]
    assert "INSERT INTO computed.metric_values" in mv_sql
    assert (
        "(metric, unit, period_start, period_end, scope, value, calc_name, calc_version, detail, category)"
        in mv_sql
    )
    # detail is bound as text and cast in SQL — driver-independent JSONB write.
    assert "%s::jsonb" in mv_sql
    assert "RETURNING metric_value_id" in mv_sql
    assert mv_params == (
        "vrm",
        "miles",
        date(2026, 1, 1),
        date(2026, 1, 31),
        "agency",
        Decimal("12.44"),
        "vrm_v0",
        "0.1.0",
        "{}",  # detail-less (0.1.0) result writes the column default
        "ntd",  # category derived from the calc registry (migration 0024)
    )
    # value passes through as Decimal, never float
    assert isinstance(mv_params[5], Decimal)

    for (edge_sql, edge_params), record_id in zip(
        executed[1:], ("rec-a-00", "rec-a-01", "rec-b-00")
    ):
        assert "INSERT INTO lineage.edges" in edge_sql
        assert (
            "(output_kind, output_id, transform_name, transform_version, input_kind, input_id)"
            in edge_sql
        )
        assert edge_params == (
            "computed.metric_values",
            FAKE_METRIC_VALUE_ID,
            "vrm_v0",
            "0.1.0",
            "raw.records",
            record_id,
        )


def test_persist_writes_coverage_detail_jsonb_exactly():
    """A 0.2.0 result's CoverageDetail lands as JSON: ratios as strings
    (Decimal-safe), counts as ints — parseable back to the exact dict."""
    conn = FakeConnection()
    result = CalcResult(
        value=Decimal("12.44"),
        unit="miles",
        calc_name="vrm_v0",
        calc_version="0.2.0",
        input_record_ids=("rec-a-00",),
        blocking_issues=(),
        warnings=(
            Finding(
                issue_type="telemetry_gap_excluded",
                title="excluded group",
                description="excluded group",
                source_record_ids=("rec-c-00", "rec-c-01"),
                severity="warning",
            ),
        ),
        detail=_detail(),
    )
    persist_result(conn, result, date(2026, 1, 1), date(2026, 1, 31))
    _, mv_params = conn._cursor.executed[0]
    assert json.loads(mv_params[8]) == {
        "coverage": "0.6667",
        "total_groups": 3,
        "excluded_groups": 1,
        "clean_position_share": "0.8333",
        "gap_threshold_seconds": 300.0,
        "coverage_threshold": "0.5",
    }


def test_persist_accepts_result_with_warnings():
    """Warning findings never refuse persistence — the figure stands, the
    exclusions live in dq.issues (routed by the runner)."""
    conn = FakeConnection()
    result = CalcResult(
        value=Decimal("0.45"),
        unit="hours",
        calc_name="vrh_v0",
        calc_version="0.2.0",
        input_record_ids=("rec-a-00",),
        blocking_issues=(),
        warnings=(
            Finding(
                issue_type="telemetry_gap_excluded",
                title="excluded group",
                description="excluded group",
                source_record_ids=("rec-c-00",),
                severity="warning",
            ),
        ),
        detail=_detail(),
    )
    metric_value_id = persist_result(conn, result, date(2026, 1, 1), date(2026, 1, 31))
    assert metric_value_id == FAKE_METRIC_VALUE_ID
    # Lineage covers input_record_ids only — never the excluded records.
    edge_ids = [params[5] for sql, params in conn._cursor.executed[1:]]
    assert edge_ids == ["rec-a-00"]


def test_persist_vrh_metric_mapping():
    conn = FakeConnection()
    result = CalcResult(
        value=Decimal("0.45"),
        unit="hours",
        calc_name="vrh_v0",
        calc_version="0.1.0",
        input_record_ids=("rec-a-00",),
        blocking_issues=(),
    )
    persist_result(conn, result, period_start=date(2026, 1, 1), period_end=date(2026, 1, 31))
    _, mv_params = conn._cursor.executed[0]
    assert mv_params[0] == "vrh"
    assert mv_params[1] == "hours"


def test_persist_refuses_result_with_blocking_issues():
    conn = FakeConnection()
    blocked = CalcResult(
        value=None,
        unit="miles",
        calc_name="vrm_v0",
        calc_version="0.1.0",
        input_record_ids=("rec-c-00",),
        blocking_issues=(
            BlockingIssue(
                issue_type="telemetry_gap",
                title="gap",
                description="gap",
                source_record_ids=("rec-c-01", "rec-c-02"),
            ),
        ),
    )
    with pytest.raises(ValueError, match="blocking issue"):
        persist_result(conn, blocked, date(2026, 1, 1), date(2026, 1, 31))
    assert conn._cursor.executed == []  # nothing written


def test_persist_refuses_coverage_blocked_result():
    """The 0.2.0 certifiability line composes with the persist guardrail:
    a coverage-blocked result is refused exactly like any blocked result."""
    conn = FakeConnection()
    blocked = CalcResult(
        value=None,
        unit="miles",
        calc_name="vrm_v0",
        calc_version="0.2.0",
        input_record_ids=("rec-a-00",),
        blocking_issues=(
            Finding(
                issue_type="coverage_below_threshold",
                title="coverage below threshold",
                description="coverage below threshold",
                source_record_ids=("rec-c-00",),
                severity="blocking",
            ),
        ),
        detail=_detail(),
    )
    with pytest.raises(ValueError, match="blocking issue"):
        persist_result(conn, blocked, date(2026, 1, 1), date(2026, 1, 31))
    assert conn._cursor.executed == []


def test_persist_refuses_none_value():
    conn = FakeConnection()
    empty = CalcResult(
        value=None,
        unit="miles",
        calc_name="vrm_v0",
        calc_version="0.1.0",
        input_record_ids=(),
        blocking_issues=(),
    )
    with pytest.raises(ValueError, match="value is None"):
        persist_result(conn, empty, date(2026, 1, 1), date(2026, 1, 31))
    assert conn._cursor.executed == []


def test_persist_refuses_unknown_calc_name():
    conn = FakeConnection()
    unknown = CalcResult(
        value=Decimal("1.00"),
        unit="widgets",
        calc_name="upt_v9",
        calc_version="9.9.9",
        input_record_ids=(),
        blocking_issues=(),
    )
    with pytest.raises(ValueError, match="Unknown calc_name"):
        persist_result(conn, unknown, date(2026, 1, 1), date(2026, 1, 31))
    assert conn._cursor.executed == []


def test_persist_stamps_ops_category_from_registry_never_caller():
    """The honesty boundary (handoff 0014 / migration 0024): an ops calc's
    figure persists with category='ops' — derived from the calc registry
    inside persist_result, with no caller-supplied way to mislabel it."""
    from headway_calc.persist import category_for_calc

    assert category_for_calc("otp_v0") == "ops"
    assert category_for_calc("headway_adherence_v0") == "ops"
    for ntd_calc in (
        "vrm_v0", "vrh_v0", "upt_v0", "voms_v0", "pmt_v0",
        "dr_vrm_v0", "dr_vrh_v0", "dr_upt_v0", "dr_voms_v0", "dr_pmt_v0",
    ):
        assert category_for_calc(ntd_calc) == "ntd"

    conn = FakeConnection()
    result = CalcResult(
        value=Decimal("97.50"),
        unit="percent",
        calc_name="otp_v0",
        calc_version="0.1.0",
        input_record_ids=("rec-1",),
        blocking_issues=(),
    )
    persist_result(conn, result, date(2026, 7, 9), date(2026, 7, 10))
    mv_sql, mv_params = conn._cursor.executed[0]
    assert "category" in mv_sql
    assert mv_params[0] == "otp"
    assert mv_params[-1] == "ops"


def test_mr20_select_hard_excludes_ops_category():
    """The MR-20 package's one read is WHERE-claused to category='ntd'
    (handoff 0014, design point 1) — a persisted ops figure cannot enter a
    certifiable package even before the database CHECK is considered."""
    from headway_calc.mr20 import _SELECT_LATEST_SQL

    assert "category = 'ntd'" in _SELECT_LATEST_SQL
