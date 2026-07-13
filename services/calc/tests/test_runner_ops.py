"""Unit tests for run_ops_period (handoff 0014) with the recording fake
connection: the OPERATIONS run — otp_v0 + headway_adherence_v0 over the
ops golden world — persists with category='ops', routes every finding with
category='ops', keeps the two-transaction fail-loudly-first ordering, and
never mixes with the NTD calcs."""

from __future__ import annotations

import json
from datetime import date

from conftest import (
    RecordingConnection,
    load_ops_case_positions,
    load_ops_schedule_rows,
    positions_to_rows,
)

from headway_calc._cli import _parse_args as cli_parse_args
from headway_calc.runner import run_ops_period

PERIOD_START = date(2026, 7, 9)
PERIOD_END = date(2026, 7, 10)


def _ops_schedule_to_rows(schedule) -> list[tuple]:
    return [
        (
            s.trip_id, s.stop_id, s.stop_sequence, s.latitude, s.longitude,
            s.arrival_seconds, s.departure_seconds, s.route_id, s.direction_id,
        )
        for s in schedule
    ]


def _conn(ops_golden_fixture, case: str) -> RecordingConnection:
    return RecordingConnection(
        position_rows=positions_to_rows(
            load_ops_case_positions(ops_golden_fixture, case)
        ),
        ops_schedule_rows=_ops_schedule_to_rows(
            load_ops_schedule_rows(ops_golden_fixture)
        ),
        agency_timezone_rows=[
            (tz,) for tz in ops_golden_fixture["agency_timezones"]
        ],
    )


def test_ops_run_persists_both_metrics_with_category_ops(ops_golden_fixture):
    conn = _conn(ops_golden_fixture, "clean_two_trips")
    report = run_ops_period(conn, PERIOD_START, PERIOD_END)

    assert report.persisted_count == 2  # 6 passages < per-route minimums
    assert report.blocked_count == 0
    by_name = {o.calc_name: o for o in report.outcomes}
    assert by_name["otp_v0"].value == "50.00"
    assert by_name["otp_v0"].metric == "otp"
    assert by_name["headway_adherence_v0"].value == "0.2200"
    assert by_name["headway_adherence_v0"].metric == "headway_adherence"
    assert all(o.scope == "agency" for o in report.outcomes)

    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 2
    for sql, params in mv_inserts:
        assert "category" in sql
        assert params[-1] == "ops"  # stamped from the calc registry

    # Lineage: one edge per consumed passage record per metric.
    edges = conn.statements_matching("INSERT INTO lineage.edges")
    assert len(edges) == 12  # 6 records × 2 metrics


def test_ops_run_routes_every_finding_with_category_ops(ops_golden_fixture):
    conn = _conn(ops_golden_fixture, "clean_two_trips")
    report = run_ops_period(conn, PERIOD_START, PERIOD_END)

    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    # Run-level findings only on the clean case: the derivation summary +
    # the thin-routes info (R1 has 6 < MIN_PASSAGES_PER_ROUTE).
    assert len(dq_inserts) == 2
    types = [params[0] for _sql, params in dq_inserts]
    assert types == [
        "ops_passage_derivation_summary",
        "ops_routes_below_min_sample",
    ]
    for _sql, params in dq_inserts:
        assert params[-1] == "ops"  # category — never gates certification
        assert "never gates certification" in params[4]
    assert report.routes_below_min_sample == {"R1": 6}
    assert len(report.run_info_ids) == 2

    # Two-transaction ordering: the first commit covers ALL dq inserts and
    # NO metric value insert.
    first_commit_statements = conn.executed[: conn.commits[0]]
    assert any(
        "INSERT INTO dq.issues" in sql for sql, _p in first_commit_statements
    )
    assert not any(
        "INSERT INTO computed.metric_values" in sql
        for sql, _p in first_commit_statements
    )


def test_ops_run_blocked_case_persists_nothing(ops_golden_fixture):
    conn = _conn(ops_golden_fixture, "refusals")
    report = run_ops_period(conn, PERIOD_START, PERIOD_END)

    assert report.persisted_count == 0
    assert report.blocked_count == 2
    assert report.passages_derived == 0
    assert conn.statements_matching("INSERT INTO computed.metric_values") == []
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    blocking_types = sorted(
        params[0] for _sql, params in dq_inserts if params[1] == "blocking"
    )
    assert blocking_types == ["no_headway_pairs", "no_observed_passages"]
    assert all(params[-1] == "ops" for _sql, params in dq_inserts)


def test_ops_run_reads_settings_with_provenance(ops_golden_fixture):
    conn = _conn(ops_golden_fixture, "clean_two_trips")
    report = run_ops_period(conn, PERIOD_START, PERIOD_END)
    assert report.otp_early_tolerance_seconds == 60
    assert report.otp_late_tolerance_seconds == 300
    assert report.tolerance_sources == {
        "otp_early_tolerance_seconds": "settings",
        "otp_late_tolerance_seconds": "settings",
    }

    explicit = run_ops_period(
        _conn(ops_golden_fixture, "clean_two_trips"),
        PERIOD_START,
        PERIOD_END,
        otp_late_tolerance_seconds=600,
    )
    assert explicit.tolerance_sources["otp_late_tolerance_seconds"] == "explicit"
    assert explicit.otp_late_tolerance_seconds == 600

    defaults = run_ops_period(
        _conn(ops_golden_fixture, "clean_two_trips"),
        PERIOD_START,
        PERIOD_END,
        read_settings=False,
    )
    assert defaults.tolerance_sources == {
        "otp_early_tolerance_seconds": "default",
        "otp_late_tolerance_seconds": "default",
    }


def test_ops_report_serializes_with_category_and_derivation(ops_golden_fixture):
    conn = _conn(ops_golden_fixture, "clean_two_trips")
    report = run_ops_period(conn, PERIOD_START, PERIOD_END)
    doc = json.loads(report.to_json())
    assert doc["category"] == "ops"
    assert doc["derivation"]["derivation_name"] == "derive_stop_passages"
    assert doc["derivation"]["passages_derived"] == 6
    assert doc["agency_timezones"] == ["America/New_York"]
    assert doc["metrics"][0]["scope"] == "agency"


def test_cli_ops_flag_parses_with_tolerance_overrides():
    args = cli_parse_args(
        [
            "--period-start", "2026-07-09",
            "--period-end", "2026-07-10",
            "--ops",
            "--otp-early-tolerance-seconds", "30",
            "--otp-late-tolerance-seconds", "240",
        ]
    )
    assert args.ops is True
    assert args.otp_early_tolerance_seconds == 30
    assert args.otp_late_tolerance_seconds == 240
