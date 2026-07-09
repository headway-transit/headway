"""Unit tests for headway_calc.runner (and the CLI boundary) with the
recording fake connection — calc 0.2.0 gap policy (handoff 0002).

Covers: clean period → both metrics persisted (full coverage, no dq rows);
gapped period at the default coverage_threshold → warning + blocking dq rows
with each finding's OWN severity and NO metric_values insert; gapped period
with an explicitly lowered coverage_threshold → clean-group values persisted
with the exclusion warnings routed alongside (the golden case B); coverage
detail in the persisted row and the RunReport; determinism; threshold
pass-through; and the two-transaction fail-loudly-first ordering (a persist
failure never rolls back already-committed dq issues). No live database.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from conftest import RecordingConnection, load_positions, positions_to_rows

import headway_calc.runner as runner_module
from headway_calc._cli import main as cli_main
from headway_calc.runner import run_period
from headway_calc.types import CalcResult, Finding

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 2, 1)

#: Coverage detail of the full golden fixture (BASIS.md, calc 0.2.0 section):
#: 3 in-trip groups, trip-C excluded, 20 of 24 in-trip positions clean.
GAPPED_DETAIL = {
    "coverage": "0.6667",
    "total_groups": 3,
    "excluded_groups": 1,
    "clean_position_share": "0.8333",
    "gap_threshold_seconds": 300.0,
    "coverage_threshold": "0.95",
}

CLEAN_DETAIL = {
    "coverage": "1.0000",
    "total_groups": 2,
    "excluded_groups": 0,
    "clean_position_share": "1.0000",
    "gap_threshold_seconds": 300.0,
    "coverage_threshold": "0.95",
}


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
    assert report.coverage_threshold == Decimal("0.95")

    vrm, vrh = report.outcomes
    assert (vrm.calc_name, vrm.metric, vrm.unit) == ("vrm_v0", "vrm", "miles")
    assert (vrh.calc_name, vrh.metric, vrh.unit) == ("vrh_v0", "vrh", "hours")
    assert vrm.calc_version == "0.2.0"
    assert vrh.calc_version == "0.2.0"
    # Golden expected values (tests/golden/vrm_vrh_v0/expected.json).
    assert vrm.value == "12.44"
    assert vrh.value == "0.45"
    assert vrm.metric_value_id == "mv-0001"
    assert vrh.metric_value_id == "mv-0002"
    assert vrm.routed_blocking_ids == () and vrm.routed_warning_ids == ()
    assert vrh.routed_blocking_ids == () and vrh.routed_warning_ids == ()
    assert vrm.detail == CLEAN_DETAIL
    assert vrm.coverage == "1.0000"

    # No dq row was written; both metric values (+ lineage) were, carrying the
    # coverage detail JSONB.
    assert conn.statements_matching("INSERT INTO dq.issues") == []
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 2
    for _, params in mv_inserts:
        assert json.loads(params[8]) == CLEAN_DETAIL
    # One lineage edge per consumed record per metric (20 records each).
    assert len(conn.statements_matching("INSERT INTO lineage.edges")) == 40
    # One transaction: the value phase (no issue phase needed).
    assert len(conn.commits) == 1
    assert conn.commits[0] == len(conn.executed)  # everything committed
    assert conn.rollback_count == 0


# --- gapped period, default coverage threshold: blocked ----------------------


def test_gapped_period_below_default_coverage_blocks_and_routes_findings(gapped_rows):
    conn = RecordingConnection(position_rows=gapped_rows)
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.positions_loaded == 26
    assert report.persisted_count == 0
    assert report.blocked_count == 2
    assert report.routed_issue_count == 4  # per metric: 1 warning + 1 blocking
    assert report.routed_warning_count == 2
    assert report.routed_blocking_count == 2

    vrm, vrh = report.outcomes
    assert vrm.metric_value_id is None and vrm.value is None
    assert vrh.metric_value_id is None and vrh.value is None
    # Warnings are routed first, then the blocking coverage refusal.
    assert vrm.routed_warning_ids == ("issue-0001",)
    assert vrm.routed_blocking_ids == ("issue-0002",)
    assert vrh.routed_warning_ids == ("issue-0003",)
    assert vrh.routed_blocking_ids == ("issue-0004",)
    assert vrm.detail == GAPPED_DETAIL
    assert vrm.coverage == "0.6667"

    # The guardrail: NO metric value, NO lineage edge below the coverage line.
    assert conn.statements_matching("INSERT INTO computed.metric_values") == []
    assert conn.statements_matching("INSERT INTO lineage.edges") == []

    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 4
    for (sql, params), calc_name in zip(
        dq_inserts, ("vrm_v0", "vrm_v0", "vrh_v0", "vrh_v0")
    ):
        issue_type, severity, status, title, description, record_ids = params
        assert status == "open"
        assert calc_name in description and "0.2.0" in description
        assert "[2026-01-01, 2026-02-01)" in description
        if severity == "warning":
            assert issue_type == "telemetry_gap_excluded"
            assert "veh-202" in title and "trip-C" in title
            # The ENTIRE excluded group's records, per handoff 0002 rule 5.
            assert record_ids == ["rec-c-00", "rec-c-01", "rec-c-02", "rec-c-03"]
        else:
            assert severity == "blocking"
            assert issue_type == "coverage_below_threshold"
            assert "0.6667" in title and "0.95" in title
            assert record_ids == ["rec-c-00", "rec-c-01", "rec-c-02", "rec-c-03"]

    # One transaction: the issue phase (nothing to persist afterwards).
    assert len(conn.commits) == 1
    assert conn.commits[0] == len(conn.executed)
    assert conn.rollback_count == 0


# --- gapped period, lowered coverage threshold: persists with warnings -------


def test_gapped_period_with_lowered_threshold_persists_clean_group_values(gapped_rows):
    """Golden case B (expected_v0_2.json): coverage 2/3 passes an explicit
    0.5 threshold — clean-group values persist, exclusion warnings alongside."""
    conn = RecordingConnection(position_rows=gapped_rows)
    report = run_period(
        conn, PERIOD_START, PERIOD_END, coverage_threshold=Decimal("0.5")
    )

    assert report.coverage_threshold == Decimal("0.5")
    assert report.persisted_count == 2
    assert report.blocked_count == 0
    assert report.routed_warning_count == 2
    assert report.routed_blocking_count == 0

    expected_detail = dict(GAPPED_DETAIL, coverage_threshold="0.5")
    vrm, vrh = report.outcomes
    assert vrm.value == "12.44" and vrm.metric_value_id == "mv-0001"
    assert vrh.value == "0.45" and vrh.metric_value_id == "mv-0002"
    assert vrm.routed_warning_ids == ("issue-0001",)
    assert vrh.routed_warning_ids == ("issue-0002",)
    assert vrm.detail == expected_detail

    # dq rows: exactly the two warnings, with warning severity.
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 2
    for _, params in dq_inserts:
        assert params[0] == "telemetry_gap_excluded"
        assert params[1] == "warning"

    # Persisted rows carry the exact coverage detail JSONB.
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 2
    for _, params in mv_inserts:
        assert json.loads(params[8]) == expected_detail

    # Lineage narrows to included groups only: 20 clean records per metric,
    # never a rec-c-* (excluded) or rec-x-* (unassigned) record.
    edges = conn.statements_matching("INSERT INTO lineage.edges")
    assert len(edges) == 40
    edge_record_ids = {params[5] for _, params in edges}
    assert all(rid.startswith(("rec-a-", "rec-b-")) for rid in edge_record_ids)

    # Two transactions: issues first, then values.
    assert len(conn.commits) == 2
    assert conn.rollback_count == 0


# --- determinism ------------------------------------------------------------


def _stable_projection(report) -> dict:
    """The RunReport minus generated ids (metric_value_id / issue ids)."""
    d = report.to_dict()
    for m in d["metrics"]:
        m["metric_value_id"] = None
        m["routed_blocking_ids"] = len(m["routed_blocking_ids"])
        m["routed_warning_ids"] = len(m["routed_warning_ids"])
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
        calc_version="0.2.0",
        input_record_ids=("rec-a-00",),
        blocking_issues=(
            Finding(
                issue_type="coverage_below_threshold",
                title="simulated coverage refusal",
                description="simulated coverage refusal for ordering test",
                source_record_ids=("rec-a-00", "rec-a-01"),
                severity="blocking",
            ),
        ),
    )
    monkeypatch.setattr(
        runner_module,
        "compute_vrm",
        lambda positions, threshold, coverage_threshold: blocked_vrm,
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
    assert parsed["coverage_threshold"] == "0.95"
    assert parsed["positions_loaded"] == 22
    assert parsed["persisted_count"] == 2
    assert parsed["blocked_count"] == 0
    assert parsed["routed_blocking_count"] == 0
    assert parsed["routed_warning_count"] == 0
    assert [m["metric"] for m in parsed["metrics"]] == ["vrm", "vrh"]
    assert parsed["metrics"][0]["value"] == "12.44"
    assert parsed["metrics"][0]["persisted"] is True
    assert parsed["metrics"][0]["calc_version"] == "0.2.0"
    assert parsed["metrics"][0]["coverage"] == "1.0000"
    assert parsed["metrics"][0]["detail"] == CLEAN_DETAIL


def test_gap_threshold_override_is_recorded(clean_rows):
    report = run_period(
        RecordingConnection(position_rows=clean_rows),
        PERIOD_START,
        PERIOD_END,
        gap_threshold_seconds=600,
    )
    assert report.gap_threshold_seconds == 600.0


def test_coverage_threshold_override_is_recorded(clean_rows):
    report = run_period(
        RecordingConnection(position_rows=clean_rows),
        PERIOD_START,
        PERIOD_END,
        coverage_threshold=Decimal("0.5"),
    )
    assert report.coverage_threshold == Decimal("0.5")
    assert report.outcomes[0].detail["coverage_threshold"] == "0.5"


def test_cli_refuses_without_database_url(monkeypatch):
    monkeypatch.delenv("HEADWAY_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="HEADWAY_DATABASE_URL is not set"):
        cli_main(["--period-start", "2026-06-01", "--period-end", "2026-07-01"])


def test_cli_requires_both_period_flags():
    with pytest.raises(SystemExit):
        cli_main(["--period-start", "2026-06-01"])
