"""Unit tests for headway_calc.dq with the recording fake connection.

Asserts the dq.issues INSERT matches handoff 0001 exactly (columns, severity
'blocking', status 'open', TEXT[] source_record_ids), that descriptions name
the calculation and period, that ids come back in order, and that insert
failures are NEVER swallowed. No live database.
"""

from __future__ import annotations

from datetime import date

import pytest
from conftest import RecordingConnection

from headway_calc.dq import route_blocking_issues
from headway_calc.types import BlockingIssue

PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 7, 1)


def _issues():
    return [
        BlockingIssue(
            issue_type="telemetry_gap",
            title="Telemetry gap of 400s in vehicle veh-202 trip trip-C",
            description="Consecutive positions are 400s apart.",
            source_record_ids=("rec-c-01", "rec-c-02"),
        ),
        BlockingIssue(
            issue_type="telemetry_gap",
            title="Telemetry gap of 500s in vehicle veh-303 trip trip-D",
            description="Consecutive positions are 500s apart.",
            source_record_ids=("rec-d-00", "rec-d-01"),
        ),
    ]


def test_route_inserts_one_row_per_issue_with_handoff_columns():
    conn = RecordingConnection()
    issue_ids = route_blocking_issues(
        conn, _issues(), "vrm_v0", "0.1.0", PERIOD_START, PERIOD_END
    )

    assert issue_ids == ["issue-0001", "issue-0002"]
    assert len(conn.executed) == 2

    for (sql, params), issue in zip(conn.executed, _issues()):
        assert "INSERT INTO dq.issues" in sql
        assert (
            "(issue_type, severity, status, title, description, source_record_ids)"
            in sql
        )
        assert "RETURNING issue_id" in sql
        issue_type, severity, status, title, description, record_ids = params
        assert issue_type == issue.issue_type
        assert severity == "blocking"
        assert status == "open"
        assert title == issue.title
        # Description keeps the issue's own text and adds calc + period context.
        assert description.startswith(issue.description)
        assert "vrm_v0" in description
        assert "0.1.0" in description
        assert "[2026-06-01, 2026-07-01)" in description
        # TEXT[] binding: a list, in the issue's order.
        assert record_ids == list(issue.source_record_ids)
        assert isinstance(record_ids, list)


def test_route_returns_ids_in_input_order():
    conn = RecordingConnection()
    first = route_blocking_issues(
        conn, _issues(), "vrh_v0", "0.1.0", PERIOD_START, PERIOD_END
    )
    second = route_blocking_issues(
        conn, _issues()[:1], "vrh_v0", "0.1.0", PERIOD_START, PERIOD_END
    )
    assert first == ["issue-0001", "issue-0002"]
    assert second == ["issue-0003"]


def test_route_never_swallows_insert_failure():
    conn = RecordingConnection(fail_on="dq.issues")
    with pytest.raises(RuntimeError, match="simulated dq.issues insert failure"):
        route_blocking_issues(
            conn, _issues(), "vrm_v0", "0.1.0", PERIOD_START, PERIOD_END
        )


def test_route_does_not_commit():
    """Transaction control belongs to the caller (runner's two-phase design)."""
    conn = RecordingConnection()
    route_blocking_issues(conn, _issues(), "vrm_v0", "0.1.0", PERIOD_START, PERIOD_END)
    assert conn.commits == []


def test_route_empty_issue_list_writes_nothing():
    conn = RecordingConnection()
    assert (
        route_blocking_issues(conn, [], "vrm_v0", "0.1.0", PERIOD_START, PERIOD_END)
        == []
    )
    assert conn.executed == []
