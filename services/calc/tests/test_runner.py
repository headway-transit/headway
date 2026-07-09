"""Unit tests for headway_calc.runner (and the CLI boundary) with the
recording fake connection.

Covers: clean period → both metrics persisted, no dq rows; gapped period →
dq rows with correct fields and NO metric_values insert; determinism of the
RunReport; and the two-transaction fail-loudly-first ordering (a persist
failure never rolls back already-committed dq issues). No live database.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from conftest import RecordingConnection, load_positions, positions_to_rows

import headway_calc.runner as runner_module
from headway_calc._cli import main as cli_main
from headway_calc.runner import run_period
from headway_calc.types import BlockingIssue, CalcResult

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 2, 1)


@pytest.fixture()
def clean_rows(golden_fixture):
    """Golden fixture minus the gapped trip-C group (the certified clean
    subset per expected.json); the unassigned rec-x-* rows stay in."""
    positions = [
        p for p in load_positions(golden_fixture) if p.trip_id != "trip-C"
    ]
    return positions_to_rows(positions)


@pytest.fixture()
def gapped_rows(golden_fixture):
    """The full golden fixture, including trip-C's 400s telemetry gap."""
    return positions_to_rows(load_positions(golden_fixture))


# --- clean period ----------------------------------------------------------


def test_clean_period_persists_both_metrics_and_routes_nothing(clean_rows):
    conn = RecordingConnection(position_rows=clean_rows)
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.period_start == PERIOD_START
    assert report.period_end == PERIOD_END
    assert report.positions_loaded == 22
    assert report.persisted_count == 2
    assert report.blocked_count == 0
    assert report.routed_issue_count == 0

    vrm, vrh = report.outcomes
    assert (vrm.calc_name, vrm.metric, vrm.unit) == ("vrm_v0", "vrm", "miles")
    assert (vrh.calc_name, vrh.metric, vrh.unit) == ("vrh_v0", "vrh", "hours")
    # Golden expected values (tests/golden/vrm_vrh_v0/expected.json).
    assert vrm.value == "12.44"
    assert vrh.value == "0.45"
    assert vrm.metric_value_id == "mv-0001"
    assert vrh.metric_value_id == "mv-0002"
    assert vrm.routed_issue_ids == ()
    assert vrh.routed_issue_ids == ()

    # No dq row was written; both metric values (+ lineage) were.
    assert conn.statements_matching("INSERT INTO dq.issues") == []
    assert len(conn.statements_matching("INSERT INTO computed.metric_values")) == 2
    # One lineage edge per consumed record per metric (20 records each).
    assert len(conn.statements_matching("INSERT INTO lineage.edges")) == 40
    # One transaction: the value phase (no issue phase needed).
    assert len(conn.commits) == 1
    assert conn.commits[0] == len(conn.executed)  # everything committed
    assert conn.rollback_count == 0


# --- gapped period ---------------------------------------------------------


def test_gapped_period_routes_issues_and_never_writes_values(gapped_rows):
    conn = RecordingConnection(position_rows=gapped_rows)
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.positions_loaded == 26
    assert report.persisted_count == 0
    assert report.blocked_count == 2
    assert report.routed_issue_count == 2

    vrm, vrh = report.outcomes
    assert vrm.metric_value_id is None and vrm.value is None
    assert vrh.metric_value_id is None and vrh.value is None
    assert vrm.routed_issue_ids == ("issue-0001",)
    assert vrh.routed_issue_ids == ("issue-0002",)

    # The guardrail: NO metric value, NO lineage edge over an unresolved gap.
    assert conn.statements_matching("INSERT INTO computed.metric_values") == []
    assert conn.statements_matching("INSERT INTO lineage.edges") == []

    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 2
    for (sql, params), calc_name in zip(dq_inserts, ("vrm_v0", "vrh_v0")):
        issue_type, severity, status, title, description, record_ids = params
        assert issue_type == "telemetry_gap"
        assert severity == "blocking"
        assert status == "open"
        assert "veh-202" in title and "trip-C" in title
        assert calc_name in description and "0.1.0" in description
        assert "[2026-01-01, 2026-02-01)" in description
        # The bounding records of the 400s gap, per the golden expectation.
        assert record_ids == ["rec-c-01", "rec-c-02"]

    # One transaction: the issue phase (nothing to persist afterwards).
    assert len(conn.commits) == 1
    assert conn.commits[0] == len(conn.executed)
    assert conn.rollback_count == 0


# --- determinism ------------------------------------------------------------


def _stable_projection(report) -> dict:
    """The RunReport minus generated ids (metric_value_id / issue ids)."""
    d = report.to_dict()
    for m in d["metrics"]:
        m["metric_value_id"] = None
        m["routed_issue_ids"] = len(m["routed_issue_ids"])
    return d


@pytest.mark.parametrize("rows_fixture", ["clean_rows", "gapped_rows"])
def test_same_rows_twice_yield_identical_reports(rows_fixture, request):
    rows = request.getfixturevalue(rows_fixture)
    report_a = run_period(RecordingConnection(position_rows=rows), PERIOD_START, PERIOD_END)
    report_b = run_period(RecordingConnection(position_rows=rows), PERIOD_START, PERIOD_END)
    assert _stable_projection(report_a) == _stable_projection(report_b)


# --- transaction ordering: fail-loudly-first --------------------------------


def test_persist_failure_does_not_roll_back_committed_dq_issues(
    monkeypatch, clean_rows
):
    """Simulate a mixed run: vrm blocked (issues routed + committed in
    transaction 1), vrh clean but its metric_values INSERT fails. The failure
    must propagate, roll back ONLY the value phase, and leave the committed
    dq issues untouched."""
    blocked_vrm = CalcResult(
        value=None,
        unit="miles",
        calc_name="vrm_v0",
        calc_version="0.1.0",
        input_record_ids=("rec-a-00",),
        blocking_issues=(
            BlockingIssue(
                issue_type="telemetry_gap",
                title="simulated gap",
                description="simulated gap for ordering test",
                source_record_ids=("rec-a-00", "rec-a-01"),
            ),
        ),
    )
    monkeypatch.setattr(
        runner_module, "compute_vrm", lambda positions, threshold: blocked_vrm
    )

    conn = RecordingConnection(
        position_rows=clean_rows, fail_on="computed.metric_values"
    )
    with pytest.raises(RuntimeError, match="simulated metric_values insert failure"):
        run_period(conn, PERIOD_START, PERIOD_END)

    # The dq issue was inserted AND committed before the failing insert:
    # statements are [SELECT, dq insert, failing mv insert]; the sole commit
    # boundary covers exactly the first two.
    assert [sql for sql, _ in conn.executed[:2]][0].startswith("SELECT")
    assert "INSERT INTO dq.issues" in conn.executed[1][0]
    assert "INSERT INTO computed.metric_values" in conn.executed[2][0]
    assert conn.commits == [2]  # committed through the dq insert, no further
    # The value phase alone was rolled back; the commit record stands.
    assert conn.rollback_count == 1


def test_dq_routing_failure_aborts_before_any_value_write(gapped_rows):
    """If even the evidence cannot be recorded, the run fails loudly before
    a single metric value is attempted."""
    conn = RecordingConnection(position_rows=gapped_rows, fail_on="dq.issues")
    with pytest.raises(RuntimeError, match="simulated dq.issues insert failure"):
        run_period(conn, PERIOD_START, PERIOD_END)
    assert conn.statements_matching("INSERT INTO computed.metric_values") == []
    assert conn.commits == []


# --- report serialization & CLI boundary ------------------------------------


def test_run_report_json_is_parseable_and_complete(clean_rows):
    report = run_period(
        RecordingConnection(position_rows=clean_rows), PERIOD_START, PERIOD_END
    )
    parsed = json.loads(report.to_json())
    assert parsed["period_start"] == "2026-01-01"
    assert parsed["period_end"] == "2026-02-01"
    assert parsed["period_convention"] == "half-open [period_start, period_end), UTC"
    assert parsed["gap_threshold_seconds"] == 300.0
    assert parsed["positions_loaded"] == 22
    assert parsed["persisted_count"] == 2
    assert parsed["blocked_count"] == 0
    assert [m["metric"] for m in parsed["metrics"]] == ["vrm", "vrh"]
    assert parsed["metrics"][0]["value"] == "12.44"
    assert parsed["metrics"][0]["persisted"] is True


def test_gap_threshold_override_is_recorded(clean_rows):
    report = run_period(
        RecordingConnection(position_rows=clean_rows),
        PERIOD_START,
        PERIOD_END,
        gap_threshold_seconds=600,
    )
    assert report.gap_threshold_seconds == 600.0


def test_cli_refuses_without_database_url(monkeypatch):
    monkeypatch.delenv("HEADWAY_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="HEADWAY_DATABASE_URL is not set"):
        cli_main(["--period-start", "2026-06-01", "--period-end", "2026-07-01"])


def test_cli_requires_both_period_flags():
    with pytest.raises(SystemExit):
        cli_main(["--period-start", "2026-06-01"])
