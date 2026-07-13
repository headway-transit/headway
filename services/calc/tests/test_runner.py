"""Unit tests for headway_calc.runner (and the CLI boundary) with the
recording fake connection — vrm_v0 0.2.0 (handoff 0002) + vrh_v0 0.4.0
(block-aware with trip-level excision, handoff 0004) + upt_v0 0.1.0
(handoff 0005).

Covers: clean period → all three metrics persisted (full coverage; the
golden fixture carries no block_id, so vrh routes its block_unavailable INFO
rows and the figure stands; the empty passenger-events table yields the
upt_v0 degenerate zero over zero operated trips); gapped period at the
default coverage_threshold → info + warning + blocking dq rows with each
finding's OWN severity and NO metric_values insert for the blocked metrics;
gapped period with an explicitly lowered coverage_threshold → clean-group
values persisted with the findings routed alongside (the golden case B); the
UPT golden fixture end-to-end (factored persists with lineage, blocked
routes its blocking finding and persists nothing); coverage/upt detail in
the persisted row and the RunReport; determinism; threshold/layover
pass-through; and the two-transaction fail-loudly-first ordering (a persist
failure never rolls back already-committed dq issues). No live database.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from decimal import Decimal

import pytest
from conftest import (
    SEEDED_SETTINGS_ROWS,
    RecordingConnection,
    events_to_rows,
    load_events,
    load_positions,
    positions_to_rows,
)

import headway_calc.runner as runner_module
from headway_calc._cli import _parse_args as cli_parse_args
from headway_calc._cli import main as cli_main
from headway_calc.runner import run_period
from headway_calc.settings import InvalidSettingValueError
from headway_calc.types import CalcResult, Finding

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 2, 1)

#: Coverage detail of the full golden fixture (BASIS.md, calc 0.2.0 section):
#: 3 in-trip groups, trip-C excluded, 20 of 24 in-trip positions clean. The
#: fixture has no block_id, so vrh_v0 0.4.0's per-trip fallback yields the
#: SAME counts (trip-denominated coverage == group coverage when every group
#: is one trip), plus the layover_max_seconds provenance field and the
#: handoff-0004 trip-excision statistics.
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

VRH_GAPPED_DETAIL = dict(
    GAPPED_DETAIL,
    layover_max_seconds=1800.0,
    total_trips=3,
    trips_excised=1,
    blocks_touched=0,  # trip-C is a NULL-block fallback, not a block
    layover_intervals_dropped=0,
)
VRH_CLEAN_DETAIL = dict(
    CLEAN_DETAIL,
    layover_max_seconds=1800.0,
    total_trips=2,
    trips_excised=0,
    blocks_touched=0,
    layover_intervals_dropped=0,
)

#: upt_v0 detail over an EMPTY passenger-events table and zero operated
#: trips (the fake connection's default): the degenerate period — nothing
#: operated, nothing missing, factor 1, counted 0.
UPT_EMPTY_DETAIL = {
    "total_boardings_counted": 0,
    "operated_trips": 0,
    "trips_with_events": 0,
    "missing_trips": 0,
    "missing_share": "0.0000",
    "factor_applied": "1.000000",
    "source_mix": {},
    "missing_trip_threshold": "0.02",
    "imbalance_threshold": "0.10",
}

#: pmt_v0 detail over the same empty passenger-events/geometry tables
#: (handoff 0011): the degenerate period — counted 0.00 passenger miles.
PMT_EMPTY_DETAIL = {
    "passenger_miles_counted": "0.00",
    "operated_trips": 0,
    "trips_with_events": 0,
    "valid_trips": 0,
    "invalid_trips": 0,
    "missing_trips": 0,
    "invalid_trip_reasons": {},
    "missing_or_invalid_share": "0.0000",
    "factor_applied": "1.000000",
    "distance_source_segments": {"haversine": 0, "shape_dist_traveled": 0},
    "shape_dist_unit_miles": None,
    "source_mix": {},
    "missing_trip_threshold": "0.02",
    "imbalance_threshold": "0.10",
}

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


def test_clean_period_persists_all_metrics_and_routes_only_infos(clean_rows):
    conn = RecordingConnection(position_rows=clean_rows)
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.period_start == PERIOD_START
    assert report.period_end == PERIOD_END
    assert report.positions_loaded == 22
    assert report.passenger_events_loaded == 0
    assert report.operated_trips_loaded == 0
    assert report.stop_times_loaded == 0
    assert report.persisted_count == 4
    assert report.blocked_count == 0
    assert report.coverage_threshold == Decimal("0.95")
    assert report.layover_max_seconds == 1800.0
    assert report.missing_trip_threshold == Decimal("0.02")
    assert report.imbalance_threshold == Decimal("0.10")
    # The fixture has no block_id: vrh 0.3.0 documents the per-trip fallback
    # with one INFO per vehicle-day — nothing blocking, nothing excluded.
    assert report.routed_issue_count == 2
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 0
    assert report.routed_blocking_count == 0

    vrm, vrh, upt, pmt = report.outcomes
    assert (vrm.calc_name, vrm.metric, vrm.unit) == ("vrm_v0", "vrm", "miles")
    assert (vrh.calc_name, vrh.metric, vrh.unit) == ("vrh_v0", "vrh", "hours")
    assert (upt.calc_name, upt.metric, upt.unit) == (
        "upt_v0",
        "upt",
        "unlinked_passenger_trips",
    )
    assert (pmt.calc_name, pmt.metric, pmt.unit) == (
        "pmt_v0",
        "pmt",
        "passenger_miles",
    )
    assert vrm.calc_version == "0.2.0"
    assert vrh.calc_version == "0.4.0"
    assert upt.calc_version == "0.1.0"
    assert pmt.calc_version == "0.1.0"
    # Golden expected values (tests/golden/vrm_vrh_v0/expected.json; the
    # no-block fallback reproduces the 0.2.0 VRH value exactly). No
    # passenger events / operated trips: upt and pmt are the degenerate 0s.
    assert vrm.value == "12.44"
    assert vrh.value == "0.45"
    assert upt.value == "0"
    assert pmt.value == "0.00"
    assert vrm.metric_value_id == "mv-0001"
    assert vrh.metric_value_id == "mv-0002"
    assert upt.metric_value_id == "mv-0003"
    assert pmt.metric_value_id == "mv-0004"
    assert vrm.routed_blocking_ids == () and vrm.routed_warning_ids == ()
    assert vrm.routed_info_ids == ()
    assert vrh.routed_blocking_ids == () and vrh.routed_warning_ids == ()
    assert vrh.routed_info_ids == ("issue-0001", "issue-0002")
    assert upt.routed_blocking_ids == () and upt.routed_warning_ids == ()
    assert upt.routed_info_ids == ()
    assert pmt.routed_blocking_ids == () and pmt.routed_warning_ids == ()
    assert pmt.routed_info_ids == ()
    assert vrm.detail == CLEAN_DETAIL
    assert vrh.detail == VRH_CLEAN_DETAIL
    assert upt.detail == UPT_EMPTY_DETAIL
    assert pmt.detail == PMT_EMPTY_DETAIL
    assert vrm.coverage == "1.0000"
    assert upt.coverage is None  # UptDetail carries missing_share instead
    assert pmt.coverage is None  # PmtDetail likewise

    # dq rows: exactly the two vrh info rows, with info severity.
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 2
    for (_, params), record_ids in zip(dq_inserts, CLEAN_INFO_RECORD_IDS):
        assert params[0] == "block_unavailable"
        assert params[1] == "info"
        assert params[5] == record_ids

    # All four metric values (+ lineage) were written, carrying the detail
    # JSONB (vrh's with the layover_max_seconds provenance, upt's UptDetail,
    # pmt's PmtDetail).
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 4
    assert json.loads(mv_inserts[0][1][8]) == CLEAN_DETAIL
    assert json.loads(mv_inserts[1][1][8]) == VRH_CLEAN_DETAIL
    assert json.loads(mv_inserts[2][1][8]) == UPT_EMPTY_DETAIL
    assert json.loads(mv_inserts[3][1][8]) == PMT_EMPTY_DETAIL
    # One lineage edge per consumed record per metric (20 records each for
    # vrm/vrh; upt/pmt consumed no passenger events).
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
    # vrm/vrh blocked; upt and pmt (no events, no operated trips) persist
    # their degenerate 0s — blocking is PER METRIC, never cross-metric.
    assert report.persisted_count == 2
    assert report.blocked_count == 2
    # vrm: 1 warning + 1 blocking; vrh: 2 infos + 1 warning + 1 blocking.
    assert report.routed_issue_count == 6
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 2
    assert report.routed_blocking_count == 2

    vrm, vrh, upt, pmt = report.outcomes
    assert vrm.metric_value_id is None and vrm.value is None
    assert vrh.metric_value_id is None and vrh.value is None
    assert upt.metric_value_id == "mv-0001" and upt.value == "0"
    assert pmt.metric_value_id == "mv-0002" and pmt.value == "0.00"
    # Per metric: infos routed first, then warnings, then blocking.
    assert vrm.routed_info_ids == ()
    assert vrm.routed_warning_ids == ("issue-0001",)
    assert vrm.routed_blocking_ids == ("issue-0002",)
    assert vrh.routed_info_ids == ("issue-0003", "issue-0004")
    assert vrh.routed_warning_ids == ("issue-0005",)
    assert vrh.routed_blocking_ids == ("issue-0006",)
    assert upt.routed_blocking_ids == ()
    assert vrm.detail == GAPPED_DETAIL
    assert vrh.detail == VRH_GAPPED_DETAIL
    assert vrm.coverage == "0.6667"

    # The guardrail: NO metric value, NO lineage edge for the metrics below
    # the coverage line — the only values written are upt's and pmt's (with
    # no consumed passenger events, no lineage edges).
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 2
    assert [p[0] for _, p in mv_inserts] == ["upt", "pmt"]
    assert conn.statements_matching("INSERT INTO lineage.edges") == []

    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 6
    for (sql, params), calc_name in zip(
        dq_inserts, ("vrm_v0", "vrm_v0", "vrh_v0", "vrh_v0", "vrh_v0", "vrh_v0")
    ):
        issue_type, severity, status, title, description, record_ids = params
        assert status == "open"
        expected_version = "0.2.0" if calc_name == "vrm_v0" else "0.4.0"
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

    # Two transactions: the issue phase, then upt's value phase.
    assert len(conn.commits) == 2
    assert conn.commits[-1] == len(conn.executed)
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
    assert report.persisted_count == 4
    assert report.blocked_count == 0
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 2
    assert report.routed_blocking_count == 0

    expected_vrm_detail = dict(GAPPED_DETAIL, coverage_threshold="0.5")
    expected_vrh_detail = dict(VRH_GAPPED_DETAIL, coverage_threshold="0.5")
    vrm, vrh, upt, pmt = report.outcomes
    assert vrm.value == "12.44" and vrm.metric_value_id == "mv-0001"
    assert vrh.value == "0.45" and vrh.metric_value_id == "mv-0002"
    assert upt.value == "0" and upt.metric_value_id == "mv-0003"
    assert pmt.value == "0.00" and pmt.metric_value_id == "mv-0004"
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

    # Persisted rows carry the exact detail JSONB.
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 4
    assert json.loads(mv_inserts[0][1][8]) == expected_vrm_detail
    assert json.loads(mv_inserts[1][1][8]) == expected_vrh_detail
    assert json.loads(mv_inserts[2][1][8]) == UPT_EMPTY_DETAIL
    assert json.loads(mv_inserts[3][1][8]) == PMT_EMPTY_DETAIL

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
    # statements are [5 SELECTs (app.settings, then the 4 reader SELECTs:
    # positions, passenger events, operated trips, trip geometry), vrm
    # blocking dq insert, vrh's 2 info dq inserts, failing mv insert]; the
    # sole commit boundary covers exactly the first eight.
    for sql, _ in conn.executed[0:5]:
        assert sql.lstrip().startswith("SELECT")
    for sql, _ in conn.executed[5:8]:
        assert "INSERT INTO dq.issues" in sql
    assert "INSERT INTO computed.metric_values" in conn.executed[8][0]
    assert conn.commits == [8]  # committed through the dq inserts, no further
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
    assert parsed["missing_trip_threshold"] == "0.02"
    assert parsed["imbalance_threshold"] == "0.10"
    # Provenance: the fake serves the migration-0014 seed rows, so the four
    # knobs came from app.settings; imbalance is not a settings knob.
    assert parsed["threshold_sources"] == {
        "gap_threshold_seconds": "settings",
        "coverage_threshold": "settings",
        "layover_max_seconds": "settings",
        "missing_trip_threshold": "settings",
        "imbalance_threshold": "default",
    }
    assert parsed["positions_loaded"] == 22
    assert parsed["passenger_events_loaded"] == 0
    assert parsed["operated_trips_loaded"] == 0
    assert parsed["stop_times_loaded"] == 0
    assert parsed["persisted_count"] == 4
    assert parsed["blocked_count"] == 0
    assert parsed["routed_blocking_count"] == 0
    assert parsed["routed_warning_count"] == 0
    assert parsed["routed_info_count"] == 2
    assert [m["metric"] for m in parsed["metrics"]] == [
        "vrm",
        "vrh",
        "upt",
        "pmt",
    ]
    assert parsed["metrics"][0]["value"] == "12.44"
    assert parsed["metrics"][0]["persisted"] is True
    assert parsed["metrics"][0]["calc_version"] == "0.2.0"
    assert parsed["metrics"][0]["coverage"] == "1.0000"
    assert parsed["metrics"][0]["detail"] == CLEAN_DETAIL
    assert parsed["metrics"][1]["calc_version"] == "0.4.0"
    assert parsed["metrics"][1]["detail"] == VRH_CLEAN_DETAIL
    assert parsed["metrics"][1]["info_count"] == 2
    assert parsed["metrics"][2]["calc_version"] == "0.1.0"
    assert parsed["metrics"][2]["unit"] == "unlinked_passenger_trips"
    assert parsed["metrics"][2]["coverage"] is None
    assert parsed["metrics"][2]["detail"] == UPT_EMPTY_DETAIL
    assert parsed["metrics"][3]["calc_version"] == "0.1.0"
    assert parsed["metrics"][3]["unit"] == "passenger_miles"
    assert parsed["metrics"][3]["coverage"] is None
    assert parsed["metrics"][3]["detail"] == PMT_EMPTY_DETAIL


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
    vrm, vrh, upt, _pmt = report.outcomes
    assert vrh.detail["layover_max_seconds"] == 900.0
    # VRM is unchanged at 0.2.0: no layover field in its detail.
    assert "layover_max_seconds" not in vrm.detail


def test_upt_threshold_overrides_pass_through(clean_rows):
    report = run_period(
        RecordingConnection(position_rows=clean_rows),
        PERIOD_START,
        PERIOD_END,
        missing_trip_threshold=Decimal("0.05"),
        imbalance_threshold=Decimal("0.20"),
    )
    assert report.missing_trip_threshold == Decimal("0.05")
    assert report.imbalance_threshold == Decimal("0.20")
    upt = report.outcomes[2]
    assert upt.detail["missing_trip_threshold"] == "0.05"
    assert upt.detail["imbalance_threshold"] == "0.20"
    # The VRM/VRH detail is untouched by the upt thresholds.
    assert "missing_trip_threshold" not in report.outcomes[0].detail


# --- upt golden fixture end-to-end through the runner ------------------------


def test_upt_factored_case_persists_value_and_lineage_through_runner(
    clean_rows, upt_golden_fixture
):
    """The upt_v0 golden factored case (49 of 50 operated trips covered ->
    98 x 50/49 = 100, BASIS.md) flows through run_period: value persisted
    with the UptDetail JSONB and one lineage edge per counted boarding."""
    case = upt_golden_fixture["factored_case"]
    conn = RecordingConnection(
        position_rows=clean_rows,
        passenger_event_rows=events_to_rows(load_events(case)),
        operated_trip_rows=[(t,) for t in case["operated_trip_ids"]],
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.passenger_events_loaded == 98
    assert report.operated_trips_loaded == 50
    upt = report.outcomes[2]
    assert upt.persisted and upt.value == "100"
    assert upt.detail["factor_applied"] == "1.020408"
    assert upt.detail["missing_share"] == "0.0200"
    assert upt.detail["source_mix"] == {"tides": 98}
    # Lineage: 20 vrm + 20 vrh clean records + 49 counted boarding events.
    edges = conn.statements_matching("INSERT INTO lineage.edges")
    upt_edges = [p for _, p in edges if p[2] == "upt_v0"]
    assert len(upt_edges) == 49
    assert all(p[5].endswith("-1") for p in upt_edges)  # boarding records only


def test_upt_blocked_case_routes_blocking_and_persists_nothing_for_upt(
    clean_rows, upt_golden_fixture
):
    """The upt_v0 golden blocked case (missing share 1/3 > the FTA 2%
    threshold) through run_period: the warnings/info/blocking rows land in
    dq.issues with their own severities, and NO upt metric value is written
    (vrm/vrh persist independently — blocking is per metric)."""
    case = upt_golden_fixture["blocked_case"]
    conn = RecordingConnection(
        position_rows=clean_rows,
        passenger_event_rows=events_to_rows(load_events(case)),
        operated_trip_rows=[(t,) for t in case["operated_trip_ids"]],
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)

    upt = report.outcomes[2]
    assert not upt.persisted and upt.value is None
    # 1 simulated info + 3 warnings (null count, imbalance, negative load)
    # + 1 blocking, routed after vrh's 2 block_unavailable infos.
    assert len(upt.routed_info_ids) == 1
    assert len(upt.routed_warning_ids) == 3
    assert len(upt.routed_blocking_ids) == 1
    dq_params = [p for _, p in conn.statements_matching("INSERT INTO dq.issues")]
    upt_types = [
        (p[0], p[1])
        for p in dq_params
        if p[0].startswith(("apc_", "simulated_", "pmt_"))
    ]
    assert upt_types == [
        # upt_v0's findings...
        ("simulated_source_data", "info"),
        ("apc_null_count", "warning"),
        ("apc_count_imbalance", "warning"),
        ("apc_negative_load", "warning"),
        ("apc_missing_trips_above_fta_threshold", "blocking"),
        # ...then pmt_v0's over the same fixture (handoff 0011): no geometry
        # rows exist in this fake, so both event trips are excluded and the
        # missing-data share breaches the same p. 146 line.
        ("simulated_source_data", "info"),
        ("pmt_invalid_trip_excluded", "warning"),
        ("pmt_invalid_trip_excluded", "warning"),
        ("apc_missing_trips_above_fta_threshold", "blocking"),
    ]
    # No upt/pmt metric value, no upt/pmt lineage edge.
    mv_params = [
        p for _, p in conn.statements_matching("INSERT INTO computed.metric_values")
    ]
    assert [p[0] for p in mv_params] == ["vrm", "vrh"]
    edges = conn.statements_matching("INSERT INTO lineage.edges")
    assert all(p[2] not in ("upt_v0", "pmt_v0") for _, p in edges)


def test_pmt_haversine_case_persists_value_and_lineage_through_runner(
    clean_rows, pmt_golden_fixture
):
    """The pmt_v0 golden haversine case (BASIS.md case 2: 4.15 passenger
    miles over NULL shape_dist geometry) flows through run_period: the
    geometry SELECT is dispatched (stop_times_loaded reported), the value
    persists with the PmtDetail JSONB, both info findings route, and one
    lineage edge lands per consumed passenger-event record."""
    from conftest import load_stop_times, stop_times_to_rows

    case = pmt_golden_fixture["haversine_case"]
    conn = RecordingConnection(
        position_rows=clean_rows,
        passenger_event_rows=events_to_rows(load_events(case)),
        operated_trip_rows=[(t,) for t in case["operated_trip_ids"]],
        stop_time_rows=stop_times_to_rows(load_stop_times(case)),
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.stop_times_loaded == 3
    pmt = report.outcomes[3]
    assert pmt.persisted and pmt.value == "4.15"
    assert pmt.detail["distance_source_segments"] == {
        "haversine": 2,
        "shape_dist_traveled": 0,
    }
    assert pmt.detail["source_mix"] == {"tides_simulated": 4}
    # Both infos routed: the simulated-source rule and the haversine
    # divergence flag (upt routes its own simulated info alongside).
    assert len(pmt.routed_info_ids) == 2
    dq_types = [p[0] for _, p in conn.statements_matching("INSERT INTO dq.issues")]
    assert "haversine_distance_fallback" in dq_types
    # Lineage: one edge per consumed event record (boardings AND alightings
    # feed the load profile).
    edges = conn.statements_matching("INSERT INTO lineage.edges")
    pmt_edges = [p for _, p in edges if p[2] == "pmt_v0"]
    assert [p[5] for p in pmt_edges] == ["rec-c-1", "rec-c-2", "rec-c-3", "rec-c-4"]


# --- app.settings wiring: explicit > settings > default (handoff 0002) -------

#: Agency-set app.settings rows, every knob deliberately different from the
#: code defaults (and from the migration-0014 seeds).
AGENCY_SETTINGS_ROWS = [
    ("coverage_threshold", "0.90", "decimal"),
    ("gap_threshold_seconds", "600", "integer"),
    ("layover_max_seconds", "900", "integer"),
    ("missing_trip_threshold", "0.05", "decimal"),
]

#: The four settings knobs: explicit run_period argument, the value the
#: report records for it, the AGENCY_SETTINGS_ROWS value, the code default.
PRECEDENCE_MATRIX = [
    ("gap_threshold_seconds", 450, 450.0, 600.0, 300.0),
    (
        "coverage_threshold",
        Decimal("0.85"),
        Decimal("0.85"),
        Decimal("0.90"),
        Decimal("0.95"),
    ),
    ("layover_max_seconds", 1200, 1200.0, 900.0, 1800.0),
    (
        "missing_trip_threshold",
        Decimal("0.03"),
        Decimal("0.03"),
        Decimal("0.05"),
        Decimal("0.02"),
    ),
]


def test_settings_rows_govern_the_run_when_no_flag_is_given(gapped_rows):
    """A coverage_threshold set through the audited settings API (0.5 here —
    below the gapped fixture's 2/3 coverage) governs the run with NO flag:
    the previously-blocked metrics persist, and the report says so."""
    conn = RecordingConnection(
        position_rows=gapped_rows,
        settings_rows=[
            ("coverage_threshold", "0.5", "decimal"),
            ("gap_threshold_seconds", "300", "integer"),
            ("layover_max_seconds", "1800", "integer"),
            ("missing_trip_threshold", "0.02", "decimal"),
        ],
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.coverage_threshold == Decimal("0.5")
    assert report.threshold_sources == {
        "gap_threshold_seconds": "settings",
        "coverage_threshold": "settings",
        "layover_max_seconds": "settings",
        "missing_trip_threshold": "settings",
        "imbalance_threshold": "default",  # not an app.settings knob
    }
    # Identical behavior to the explicit --coverage-threshold 0.5 run: the
    # settings row, not the code default 0.95, drew the certifiability line.
    assert report.persisted_count == 4 and report.blocked_count == 0
    assert report.routed_blocking_count == 0
    # The persisted detail JSONB carries the settings-provided value; its
    # origin story is the report's threshold_sources.
    vrm = report.outcomes[0]
    assert vrm.detail["coverage_threshold"] == "0.5"
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 4
    assert json.loads(mv_inserts[0][1][8])["coverage_threshold"] == "0.5"


def test_explicit_flag_wins_over_settings_row(gapped_rows):
    """Settings say 0.5 (would persist); the explicit argument says 0.95 —
    the explicit flag governs and the report attributes it."""
    conn = RecordingConnection(
        position_rows=gapped_rows,
        settings_rows=[
            ("coverage_threshold", "0.5", "decimal"),
            ("gap_threshold_seconds", "300", "integer"),
            ("layover_max_seconds", "1800", "integer"),
            ("missing_trip_threshold", "0.02", "decimal"),
        ],
    )
    report = run_period(
        conn, PERIOD_START, PERIOD_END, coverage_threshold=Decimal("0.95")
    )

    assert report.coverage_threshold == Decimal("0.95")
    assert report.threshold_sources["coverage_threshold"] == "explicit"
    # The un-flagged knobs still come from settings.
    assert report.threshold_sources["gap_threshold_seconds"] == "settings"
    # 0.95 blocks the gapped fixture exactly as in the default-threshold test.
    assert report.blocked_count == 2 and report.routed_blocking_count == 2


def test_missing_settings_table_falls_back_to_code_defaults_with_warning(
    clean_rows, caplog
):
    """Pre-migration-0014 databases keep working: relation-does-not-exist is
    the ONE tolerated absence — code defaults, sources 'default', an explicit
    WARNING, and the aborted statement rolled back."""
    conn = RecordingConnection(position_rows=clean_rows, settings_table_missing=True)
    with caplog.at_level(logging.WARNING, logger="headway_calc.settings"):
        report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.gap_threshold_seconds == 300.0
    assert report.coverage_threshold == Decimal("0.95")
    assert report.layover_max_seconds == 1800.0
    assert report.missing_trip_threshold == Decimal("0.02")
    assert set(report.threshold_sources.values()) == {"default"}
    assert report.persisted_count == 4
    assert any(
        "app.settings does not exist" in r.getMessage() for r in caplog.records
    )
    # The failed settings SELECT was rolled back; the run then proceeded
    # normally (issues transaction + values transaction).
    assert conn.rollback_count == 1
    assert len(conn.commits) == 2


def test_corrupt_setting_value_refuses_the_run_before_any_canonical_read(
    gapped_rows,
):
    """A row that cannot be parsed NEVER becomes a guessed threshold: the
    typed error propagates and the run stops before reading canonical rows,
    routing findings, or writing values."""
    conn = RecordingConnection(
        position_rows=gapped_rows,
        settings_rows=[
            ("coverage_threshold", "ninety-five percent", "decimal"),
            ("gap_threshold_seconds", "300", "integer"),
            ("layover_max_seconds", "1800", "integer"),
            ("missing_trip_threshold", "0.02", "decimal"),
        ],
    )
    with pytest.raises(InvalidSettingValueError, match="coverage_threshold"):
        run_period(conn, PERIOD_START, PERIOD_END)

    # Only the settings SELECT ran: no canonical reads, no dq rows, no
    # metric values, no commits.
    assert len(conn.executed) == 1
    assert "app.settings" in conn.executed[0][0]
    assert conn.statements_matching("INSERT INTO") == []
    assert conn.commits == []


def test_read_settings_false_skips_the_settings_read(clean_rows):
    """The library face of --ignore-settings: app.settings is never queried,
    so an agency's rows cannot govern a historical reproduction."""
    conn = RecordingConnection(
        position_rows=clean_rows, settings_rows=AGENCY_SETTINGS_ROWS
    )
    report = run_period(conn, PERIOD_START, PERIOD_END, read_settings=False)

    assert conn.statements_matching("app.settings") == []
    assert report.coverage_threshold == Decimal("0.95")
    assert report.gap_threshold_seconds == 300.0
    assert set(report.threshold_sources.values()) == {"default"}


def test_read_settings_false_still_honors_explicit_flags(clean_rows):
    conn = RecordingConnection(
        position_rows=clean_rows, settings_rows=AGENCY_SETTINGS_ROWS
    )
    report = run_period(
        conn,
        PERIOD_START,
        PERIOD_END,
        coverage_threshold=Decimal("0.85"),
        read_settings=False,
    )
    assert report.coverage_threshold == Decimal("0.85")
    assert report.threshold_sources["coverage_threshold"] == "explicit"
    assert report.threshold_sources["gap_threshold_seconds"] == "default"


@pytest.mark.parametrize(
    "knob, explicit_arg, explicit_value, settings_value, default_value",
    PRECEDENCE_MATRIX,
    ids=[row[0] for row in PRECEDENCE_MATRIX],
)
def test_precedence_matrix_explicit_over_settings_over_default(
    clean_rows, knob, explicit_arg, explicit_value, settings_value, default_value
):
    """For each of the four knobs: explicit argument > app.settings row >
    code default, with the source recorded per threshold."""
    # explicit beats a differing settings row
    report = run_period(
        RecordingConnection(
            position_rows=clean_rows, settings_rows=AGENCY_SETTINGS_ROWS
        ),
        PERIOD_START,
        PERIOD_END,
        **{knob: explicit_arg},
    )
    assert getattr(report, knob) == explicit_value
    assert report.threshold_sources[knob] == "explicit"
    # ...and the OTHER three knobs still come from settings.
    other_sources = {
        k: v
        for k, v in report.threshold_sources.items()
        if k not in (knob, "imbalance_threshold")
    }
    assert set(other_sources.values()) == {"settings"}

    # settings row beats the code default
    report = run_period(
        RecordingConnection(
            position_rows=clean_rows, settings_rows=AGENCY_SETTINGS_ROWS
        ),
        PERIOD_START,
        PERIOD_END,
    )
    assert getattr(report, knob) == settings_value
    assert report.threshold_sources[knob] == "settings"

    # code default when the table does not exist
    report = run_period(
        RecordingConnection(position_rows=clean_rows, settings_table_missing=True),
        PERIOD_START,
        PERIOD_END,
    )
    assert getattr(report, knob) == default_value
    assert report.threshold_sources[knob] == "default"


def test_imbalance_threshold_is_not_a_settings_knob(clean_rows):
    """imbalance_threshold is not seeded in app.settings: its source is only
    ever explicit or default, even when every other knob comes from settings."""
    report = run_period(
        RecordingConnection(
            position_rows=clean_rows, settings_rows=AGENCY_SETTINGS_ROWS
        ),
        PERIOD_START,
        PERIOD_END,
        imbalance_threshold=Decimal("0.20"),
    )
    assert report.threshold_sources["imbalance_threshold"] == "explicit"
    assert report.imbalance_threshold == Decimal("0.20")


def test_seeded_settings_values_reproduce_the_default_run_exactly(gapped_rows):
    """The migration-0014 seeds equal the code defaults, so a settings-read
    run and an --ignore-settings run over the same rows differ ONLY in the
    recorded sources — determinism intact across the settings path."""
    report_settings = run_period(
        RecordingConnection(
            position_rows=gapped_rows, settings_rows=SEEDED_SETTINGS_ROWS
        ),
        PERIOD_START,
        PERIOD_END,
    )
    report_defaults = run_period(
        RecordingConnection(position_rows=gapped_rows, settings_table_missing=True),
        PERIOD_START,
        PERIOD_END,
    )
    a = _stable_projection(report_settings)
    b = _stable_projection(report_defaults)
    assert a.pop("threshold_sources") == {
        "gap_threshold_seconds": "settings",
        "coverage_threshold": "settings",
        "layover_max_seconds": "settings",
        "missing_trip_threshold": "settings",
        "imbalance_threshold": "default",
    }
    assert b.pop("threshold_sources") == {
        "gap_threshold_seconds": "default",
        "coverage_threshold": "default",
        "layover_max_seconds": "default",
        "missing_trip_threshold": "default",
        "imbalance_threshold": "default",
    }
    assert a == b


def test_cli_ignore_settings_flag_parses_and_defaults_off():
    base = ["--period-start", "2026-06-01", "--period-end", "2026-07-01"]
    assert cli_parse_args(base).ignore_settings is False
    assert cli_parse_args(base + ["--ignore-settings"]).ignore_settings is True


def test_cli_refuses_without_database_url(monkeypatch):
    monkeypatch.delenv("HEADWAY_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit, match="HEADWAY_DATABASE_URL is not set"):
        cli_main(["--period-start", "2026-06-01", "--period-end", "2026-07-01"])


def test_cli_requires_both_period_flags():
    with pytest.raises(SystemExit):
        cli_main(["--period-start", "2026-06-01"])
