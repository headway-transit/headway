"""Unit tests for headway_calc.runner (and the CLI boundary) with the
recording fake connection — vrm_v0 0.2.0 (handoff 0002) + vrh_v0 0.3.0
(block-aware, handoff 0003).

Covers: clean period → both metrics persisted (full coverage; the golden
fixture carries no block_id, so vrh routes its block_unavailable INFO rows
and the figure stands); gapped period at the default coverage_threshold →
info + warning + blocking dq rows with each finding's OWN severity and NO
metric_values insert; gapped period with an explicitly lowered
coverage_threshold → clean-group values persisted with the findings routed
alongside (the golden case B); coverage detail in the persisted row and the
RunReport; determinism; threshold/layover pass-through; and the
two-transaction fail-loudly-first ordering (a persist failure never rolls
back already-committed dq issues). No live database.
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
#: 3 in-trip groups, trip-C excluded, 20 of 24 in-trip positions clean. The
#: fixture has no block_id, so vrh_v0 0.3.0's per-trip fallback yields the
#: SAME group counts, plus the layover_max_seconds provenance field.
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

VRH_GAPPED_DETAIL = dict(GAPPED_DETAIL, layover_max_seconds=1800.0)
VRH_CLEAN_DETAIL = dict(CLEAN_DETAIL, layover_max_seconds=1800.0)

#: block_unavailable info rows the no-block_id golden fixture produces for
#: vrh_v0 0.3.0: one per vehicle-day, in (vehicle_id, day) order.
CLEAN_INFO_RECORD_IDS = [
    [f"rec-a-{i:02d}" for i in range(10)],  # veh-101 / 2026-01-15
    [f"rec-b-{i:02d}" for i in range(10)],  # veh-202 / 2026-01-15
]
GAPPED_INFO_RECORD_IDS = [
    [f"rec-a-{i:02d}" for i in range(10)],  # veh-101 / 2026-01-15
    # veh-202 / 2026-01-15: trip-B and the gapped trip-C are both fallbacks.
    [f"rec-b-{i:02d}" for i in range(10)] + [f"rec-c-{i:02d}" for i in range(4)],
]


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


def test_clean_period_persists_both_metrics_and_routes_only_infos(clean_rows):
    conn = RecordingConnection(position_rows=clean_rows)
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.period_start == PERIOD_START
    assert report.period_end == PERIOD_END
    assert report.positions_loaded == 22
    assert report.persisted_count == 2
    assert report.blocked_count == 0
    assert report.coverage_threshold == Decimal("0.95")
    assert report.layover_max_seconds == 1800.0
    # The fixture has no block_id: vrh 0.3.0 documents the per-trip fallback
    # with one INFO per vehicle-day — nothing blocking, nothing excluded.
    assert report.routed_issue_count == 2
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 0
    assert report.routed_blocking_count == 0

    vrm, vrh = report.outcomes
    assert (vrm.calc_name, vrm.metric, vrm.unit) == ("vrm_v0", "vrm", "miles")
    assert (vrh.calc_name, vrh.metric, vrh.unit) == ("vrh_v0", "vrh", "hours")
    assert vrm.calc_version == "0.2.0"
    assert vrh.calc_version == "0.3.0"
    # Golden expected values (tests/golden/vrm_vrh_v0/expected.json; the
    # no-block fallback reproduces the 0.2.0 VRH value exactly).
    assert vrm.value == "12.44"
    assert vrh.value == "0.45"
    assert vrm.metric_value_id == "mv-0001"
    assert vrh.metric_value_id == "mv-0002"
    assert vrm.routed_blocking_ids == () and vrm.routed_warning_ids == ()
    assert vrm.routed_info_ids == ()
    assert vrh.routed_blocking_ids == () and vrh.routed_warning_ids == ()
    assert vrh.routed_info_ids == ("issue-0001", "issue-0002")
    assert vrm.detail == CLEAN_DETAIL
    assert vrh.detail == VRH_CLEAN_DETAIL
    assert vrm.coverage == "1.0000"

    # dq rows: exactly the two vrh info rows, with info severity.
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 2
    for (_, params), record_ids in zip(dq_inserts, CLEAN_INFO_RECORD_IDS):
        assert params[0] == "block_unavailable"
        assert params[1] == "info"
        assert params[5] == record_ids

    # Both metric values (+ lineage) were written, carrying the coverage
    # detail JSONB (vrh's with the layover_max_seconds provenance).
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 2
    assert json.loads(mv_inserts[0][1][8]) == CLEAN_DETAIL
    assert json.loads(mv_inserts[1][1][8]) == VRH_CLEAN_DETAIL
    # One lineage edge per consumed record per metric (20 records each).
    assert len(conn.statements_matching("INSERT INTO lineage.edges")) == 40
    # Two transactions: the info rows first, then the value phase.
    assert len(conn.commits) == 2
    assert conn.commits[-1] == len(conn.executed)  # everything committed
    assert conn.rollback_count == 0


# --- gapped period, default coverage threshold: blocked ----------------------


def test_gapped_period_below_default_coverage_blocks_and_routes_findings(gapped_rows):
    conn = RecordingConnection(position_rows=gapped_rows)
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.positions_loaded == 26
    assert report.persisted_count == 0
    assert report.blocked_count == 2
    # vrm: 1 warning + 1 blocking; vrh: 2 infos + 1 warning + 1 blocking.
    assert report.routed_issue_count == 6
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 2
    assert report.routed_blocking_count == 2

    vrm, vrh = report.outcomes
    assert vrm.metric_value_id is None and vrm.value is None
    assert vrh.metric_value_id is None and vrh.value is None
    # Per metric: infos routed first, then warnings, then blocking.
    assert vrm.routed_info_ids == ()
    assert vrm.routed_warning_ids == ("issue-0001",)
    assert vrm.routed_blocking_ids == ("issue-0002",)
    assert vrh.routed_info_ids == ("issue-0003", "issue-0004")
    assert vrh.routed_warning_ids == ("issue-0005",)
    assert vrh.routed_blocking_ids == ("issue-0006",)
    assert vrm.detail == GAPPED_DETAIL
    assert vrh.detail == VRH_GAPPED_DETAIL
    assert vrm.coverage == "0.6667"

    # The guardrail: NO metric value, NO lineage edge below the coverage line.
    assert conn.statements_matching("INSERT INTO computed.metric_values") == []
    assert conn.statements_matching("INSERT INTO lineage.edges") == []

    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 6
    for (sql, params), calc_name in zip(
        dq_inserts, ("vrm_v0", "vrm_v0", "vrh_v0", "vrh_v0", "vrh_v0", "vrh_v0")
    ):
        issue_type, severity, status, title, description, record_ids = params
        assert status == "open"
        expected_version = "0.2.0" if calc_name == "vrm_v0" else "0.3.0"
        assert calc_name in description and expected_version in description
        assert "[2026-01-01, 2026-02-01)" in description
        if severity == "info":
            assert issue_type == "block_unavailable"
        elif severity == "warning":
            assert issue_type == "telemetry_gap_excluded"
            assert "veh-202" in title and "trip-C" in title
            # The ENTIRE excluded group's records, per handoff 0002 rule 5.
            assert record_ids == ["rec-c-00", "rec-c-01", "rec-c-02", "rec-c-03"]
        else:
            assert severity == "blocking"
            assert issue_type == "coverage_below_threshold"
            assert "0.6667" in title and "0.95" in title
            assert record_ids == ["rec-c-00", "rec-c-01", "rec-c-02", "rec-c-03"]
    # vrh's per-vehicle-day info rows cite the fallback trips' records.
    info_params = [p for _, p in dq_inserts if p[1] == "info"]
    assert [p[5] for p in info_params] == GAPPED_INFO_RECORD_IDS

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
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 2
    assert report.routed_blocking_count == 0

    expected_vrm_detail = dict(GAPPED_DETAIL, coverage_threshold="0.5")
    expected_vrh_detail = dict(VRH_GAPPED_DETAIL, coverage_threshold="0.5")
    vrm, vrh = report.outcomes
    assert vrm.value == "12.44" and vrm.metric_value_id == "mv-0001"
    assert vrh.value == "0.45" and vrh.metric_value_id == "mv-0002"
    assert vrm.routed_warning_ids == ("issue-0001",)
    assert vrh.routed_info_ids == ("issue-0002", "issue-0003")
    assert vrh.routed_warning_ids == ("issue-0004",)
    assert vrm.detail == expected_vrm_detail
    assert vrh.detail == expected_vrh_detail

    # dq rows: two exclusion warnings + vrh's two fallback infos, each with
    # its own severity.
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 4
    assert [(p[0], p[1]) for _, p in dq_inserts] == [
        ("telemetry_gap_excluded", "warning"),  # vrm
        ("block_unavailable", "info"),  # vrh, veh-101
        ("block_unavailable", "info"),  # vrh, veh-202
        ("telemetry_gap_excluded", "warning"),  # vrh
    ]

    # Persisted rows carry the exact coverage detail JSONB.
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 2
    assert json.loads(mv_inserts[0][1][8]) == expected_vrm_detail
    assert json.loads(mv_inserts[1][1][8]) == expected_vrh_detail

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
        m["routed_info_ids"] = len(m["routed_info_ids"])
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

    # The dq issues were inserted AND committed before the failing insert:
    # statements are [SELECT, vrm blocking dq insert, vrh's 2 info dq
    # inserts, failing mv insert]; the sole commit boundary covers exactly
    # the first four.
    assert conn.executed[0][0].startswith("SELECT")
    for sql, _ in conn.executed[1:4]:
        assert "INSERT INTO dq.issues" in sql
    assert "INSERT INTO computed.metric_values" in conn.executed[4][0]
    assert conn.commits == [4]  # committed through the dq inserts, no further
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
    assert parsed["layover_max_seconds"] == 1800.0
    assert parsed["positions_loaded"] == 22
    assert parsed["persisted_count"] == 2
    assert parsed["blocked_count"] == 0
    assert parsed["routed_blocking_count"] == 0
    assert parsed["routed_warning_count"] == 0
    assert parsed["routed_info_count"] == 2
    assert [m["metric"] for m in parsed["metrics"]] == ["vrm", "vrh"]
    assert parsed["metrics"][0]["value"] == "12.44"
    assert parsed["metrics"][0]["persisted"] is True
    assert parsed["metrics"][0]["calc_version"] == "0.2.0"
    assert parsed["metrics"][0]["coverage"] == "1.0000"
    assert parsed["metrics"][0]["detail"] == CLEAN_DETAIL
    assert parsed["metrics"][1]["calc_version"] == "0.3.0"
    assert parsed["metrics"][1]["detail"] == VRH_CLEAN_DETAIL
    assert parsed["metrics"][1]["info_count"] == 2


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


def test_layover_max_seconds_override_passes_through_to_vrh(clean_rows):
    report = run_period(
        RecordingConnection(position_rows=clean_rows),
        PERIOD_START,
        PERIOD_END,
        layover_max_seconds=900,
    )
    assert report.layover_max_seconds == 900.0
    vrm, vrh = report.outcomes
    assert vrh.detail["layover_max_seconds"] == 900.0
    # VRM is unchanged at 0.2.0: no layover field in its detail.
    assert "layover_max_seconds" not in vrm.detail


def test_cli_refuses_without_database_url(monkeypatch):
    monkeypatch.delenv("HEADWAY_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="HEADWAY_DATABASE_URL is not set"):
        cli_main(["--period-start", "2026-06-01", "--period-end", "2026-07-01"])


def test_cli_requires_both_period_flags():
    with pytest.raises(SystemExit):
        cli_main(["--period-start", "2026-06-01"])
