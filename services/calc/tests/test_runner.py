"""Unit tests for headway_calc.runner (and the CLI boundary) with the
recording fake connection — vrm_v0 0.2.0 (handoff 0002) + vrh_v0 0.4.0
(block-aware with trip-level excision, handoff 0004) + upt_v0 0.1.0
(handoff 0005).

Covers: clean period → vrm/vrh persisted (full coverage; the golden fixture
carries no block_id, so vrh routes its block_unavailable INFO rows and the
figure stands) while upt/pmt REFUSE with 'no_data_in_period' (the empty
passenger-events table plus zero operated trips is NO count evidence — the
runner's empty-input guard replaced the old degenerate-zero persistence
after a real agency's empty June run persisted 0.00s); gapped period at the
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

#: What upt_v0/pmt_v0 now do over an EMPTY passenger-events table and zero
#: operated trips (the fake connection's default): the runner's empty-input
#: guard REFUSES with one blocking 'no_data_in_period' finding per calc —
#: the old degenerate-zero persistence invented a 0/0.00 out of no evidence
#: (a real agency's empty June run persisted exactly those figures).
NO_DATA_ISSUE_TYPE = "no_data_in_period"

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


def test_clean_period_persists_telemetry_metrics_and_refuses_upt_pmt(clean_rows):
    conn = RecordingConnection(position_rows=clean_rows)
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.period_start == PERIOD_START
    assert report.period_end == PERIOD_END
    assert report.positions_loaded == 22
    assert report.passenger_events_loaded == 0
    assert report.operated_trips_loaded == 0
    assert report.stop_times_loaded == 0
    # vrm/vrh persist (telemetry present, full coverage); upt/pmt REFUSE —
    # no passenger events and no operated trips is no count evidence.
    assert report.persisted_count == 2
    assert report.blocked_count == 2
    assert report.coverage_threshold == Decimal("0.95")
    assert report.layover_max_seconds == 1800.0
    assert report.missing_trip_threshold == Decimal("0.02")
    assert report.imbalance_threshold == Decimal("0.10")
    # The fixture has no block_id: vrh 0.3.0 documents the per-trip fallback
    # with one INFO per vehicle-day; upt/pmt each route ONE blocking
    # no_data_in_period finding.
    assert report.routed_issue_count == 4
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 0
    assert report.routed_blocking_count == 2

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
    assert upt.calc_version == "0.4.0"  # handoff 0040: revenue classification
    assert pmt.calc_version == "0.2.0"
    # Golden expected values (tests/golden/vrm_vrh_v0/expected.json; the
    # no-block fallback reproduces the 0.2.0 VRH value exactly). No
    # passenger events / operated trips: upt and pmt REFUSED — no invented 0s.
    assert vrm.value == "12.44"
    assert vrh.value == "0.45"
    assert upt.value is None
    assert pmt.value is None
    assert vrm.metric_value_id == "mv-0001"
    assert vrh.metric_value_id == "mv-0002"
    assert upt.metric_value_id is None
    assert pmt.metric_value_id is None
    assert vrm.routed_blocking_ids == () and vrm.routed_warning_ids == ()
    assert vrm.routed_info_ids == ()
    assert vrh.routed_blocking_ids == () and vrh.routed_warning_ids == ()
    assert vrh.routed_info_ids == ("issue-0001", "issue-0002")
    assert upt.routed_blocking_ids == ("issue-0003",)
    assert upt.routed_warning_ids == () and upt.routed_info_ids == ()
    assert pmt.routed_blocking_ids == ("issue-0004",)
    assert pmt.routed_warning_ids == () and pmt.routed_info_ids == ()
    assert vrm.detail == CLEAN_DETAIL
    assert vrh.detail == VRH_CLEAN_DETAIL
    assert upt.detail is None  # no compute ran; nothing is fabricated
    assert pmt.detail is None
    assert vrm.coverage == "1.0000"
    assert upt.coverage is None
    assert pmt.coverage is None

    # dq rows: the two vrh info rows, then upt's and pmt's blocking
    # no_data_in_period rows (no source records exist by definition).
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 4
    for (_, params), record_ids in zip(dq_inserts[:2], CLEAN_INFO_RECORD_IDS):
        assert params[0] == "block_unavailable"
        assert params[1] == "info"
        assert params[5] == record_ids
    for _, params in dq_inserts[2:]:
        assert params[0] == NO_DATA_ISSUE_TYPE
        assert params[1] == "blocking"
        assert params[5] == []

    # Only the two telemetry metric values (+ lineage) were written; no
    # computed.metric_values row exists for the refused upt/pmt.
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 2
    assert json.loads(mv_inserts[0][1][8]) == CLEAN_DETAIL
    assert json.loads(mv_inserts[1][1][8]) == VRH_CLEAN_DETAIL
    # One lineage edge per consumed record per metric (20 records each for
    # vrm/vrh; the refused upt/pmt consumed nothing).
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
    # vrm/vrh blocked below the coverage line; upt and pmt (no events, no
    # operated trips) REFUSE with no_data_in_period — blocking is PER
    # METRIC, never cross-metric, and a refusal is never a persisted 0.
    assert report.persisted_count == 0
    assert report.blocked_count == 4
    # vrm: 1 warning + 1 blocking; vrh: 2 infos + 1 warning + 1 blocking;
    # upt/pmt: 1 no_data_in_period blocking each.
    assert report.routed_issue_count == 8
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 2
    assert report.routed_blocking_count == 4

    vrm, vrh, upt, pmt = report.outcomes
    assert vrm.metric_value_id is None and vrm.value is None
    assert vrh.metric_value_id is None and vrh.value is None
    assert upt.metric_value_id is None and upt.value is None
    assert pmt.metric_value_id is None and pmt.value is None
    # Per metric: infos routed first, then warnings, then blocking.
    assert vrm.routed_info_ids == ()
    assert vrm.routed_warning_ids == ("issue-0001",)
    assert vrm.routed_blocking_ids == ("issue-0002",)
    assert vrh.routed_info_ids == ("issue-0003", "issue-0004")
    assert vrh.routed_warning_ids == ("issue-0005",)
    assert vrh.routed_blocking_ids == ("issue-0006",)
    assert upt.routed_blocking_ids == ("issue-0007",)
    assert pmt.routed_blocking_ids == ("issue-0008",)
    assert vrm.detail == GAPPED_DETAIL
    assert vrh.detail == VRH_GAPPED_DETAIL
    assert vrm.coverage == "0.6667"

    # The guardrail: NO metric value, NO lineage edge anywhere — every
    # metric either blocked on coverage or refused on no data.
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert mv_inserts == []
    assert conn.statements_matching("INSERT INTO lineage.edges") == []

    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 8
    # The last two rows are upt's and pmt's no_data_in_period refusals.
    for _, params in dq_inserts[6:]:
        assert params[0] == NO_DATA_ISSUE_TYPE
        assert params[1] == "blocking"
        assert params[5] == []
    for (sql, params), calc_name in zip(
        dq_inserts[:6], ("vrm_v0", "vrm_v0", "vrh_v0", "vrh_v0", "vrh_v0", "vrh_v0")
    ):
        # Migration 0035 appended subject_context to the INSERT (handoff
        # 0029): every finding whose subject names canonical rows carries
        # the resolved, frozen context; a finding about the run as a whole
        # carries NULL and renders exactly as it always did.
        (
            issue_type, severity, status, title, description, record_ids,
            category, subject_context,
        ) = params
        assert category == "ntd"
        assert status == "open"
        expected_version = "0.2.0" if calc_name == "vrm_v0" else "0.4.0"
        assert calc_name in description and expected_version in description
        assert "[2026-01-01, 2026-02-01)" in description
        if severity == "info":
            assert issue_type == "block_unavailable"
        elif severity == "warning":
            assert issue_type == "telemetry_gap_excluded"
            # Route, vehicle, when (handoff 0032): the title leads with the
            # vehicle handle (no label in the fixture, short id kept whole);
            # the trip id stays in the description — the footnote, not the
            # headline.
            assert "veh-202" in title and "telemetry silence" in title
            assert "trip-C" in description
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

    # One transaction: the issue phase alone — nothing persisted a value.
    assert len(conn.commits) == 1
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
    # vrm/vrh persist under the lowered threshold; upt/pmt still REFUSE —
    # a threshold knob cannot conjure count data that does not exist.
    assert report.persisted_count == 2
    assert report.blocked_count == 2
    assert report.routed_info_count == 2
    assert report.routed_warning_count == 2
    assert report.routed_blocking_count == 2

    expected_vrm_detail = dict(GAPPED_DETAIL, coverage_threshold="0.5")
    expected_vrh_detail = dict(VRH_GAPPED_DETAIL, coverage_threshold="0.5")
    vrm, vrh, upt, pmt = report.outcomes
    assert vrm.value == "12.44" and vrm.metric_value_id == "mv-0001"
    assert vrh.value == "0.45" and vrh.metric_value_id == "mv-0002"
    assert upt.value is None and upt.metric_value_id is None
    assert pmt.value is None and pmt.metric_value_id is None
    assert vrm.routed_warning_ids == ("issue-0001",)
    assert vrh.routed_info_ids == ("issue-0002", "issue-0003")
    assert vrh.routed_warning_ids == ("issue-0004",)
    assert upt.routed_blocking_ids == ("issue-0005",)
    assert pmt.routed_blocking_ids == ("issue-0006",)
    assert vrm.detail == expected_vrm_detail
    assert vrh.detail == expected_vrh_detail

    # dq rows: two exclusion warnings + vrh's two fallback infos, each with
    # its own severity, then upt's and pmt's no_data_in_period refusals.
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 6
    assert [(p[0], p[1]) for _, p in dq_inserts] == [
        ("telemetry_gap_excluded", "warning"),  # vrm
        ("block_unavailable", "info"),  # vrh, veh-101
        ("block_unavailable", "info"),  # vrh, veh-202
        ("telemetry_gap_excluded", "warning"),  # vrh
        (NO_DATA_ISSUE_TYPE, "blocking"),  # upt
        (NO_DATA_ISSUE_TYPE, "blocking"),  # pmt
    ]

    # Persisted rows carry the exact detail JSONB.
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

    # The dq issues were inserted AND committed before the failing insert.
    # Asserted by SHAPE rather than by fixed indices: since handoff 0029 the
    # routing phase also issues reads (the subject label SELECT and the
    # migration-0035 column probe), and the invariant under test is the
    # ORDERING — every finding durable before any value is attempted — not
    # how many statements it takes.
    dq_at = [
        i for i, (sql, _) in enumerate(conn.executed)
        if "INSERT INTO dq.issues" in sql
    ]
    mv_at = [
        i for i, (sql, _) in enumerate(conn.executed)
        if "INSERT INTO computed.metric_values" in sql
    ]
    # vrm's blocking refusal + vrh's 2 block_unavailable infos + upt's and
    # pmt's no_data_in_period refusals; then the one metric-value insert
    # (vrh's, the only non-blocked result) that fails.
    assert len(dq_at) == 5 and len(mv_at) == 1
    assert max(dq_at) < mv_at[0]
    # Everything before the first finding lands is a READ — no write of any
    # kind precedes the evidence.
    for sql, _ in conn.executed[: dq_at[0]]:
        assert sql.lstrip().startswith("SELECT")
    # The sole commit boundary sits after every dq insert and before the
    # value phase (whose first statement is the identical-figure probe
    # SELECT preceding the metric-value insert): committed through the
    # findings, no further.
    assert conn.commits == [mv_at[0] - 1]
    assert max(dq_at) < mv_at[0] - 1
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
    assert parsed["persisted_count"] == 2
    assert parsed["blocked_count"] == 2
    assert parsed["routed_blocking_count"] == 2
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
    # upt/pmt refused (no count data): no value, no detail, one blocking id.
    assert parsed["metrics"][2]["calc_version"] == "0.4.0"  # handoff 0040
    assert parsed["metrics"][2]["unit"] == "unlinked_passenger_trips"
    assert parsed["metrics"][2]["value"] is None
    assert parsed["metrics"][2]["persisted"] is False
    assert parsed["metrics"][2]["coverage"] is None
    assert parsed["metrics"][2]["detail"] is None
    assert parsed["metrics"][2]["blocking_issue_count"] == 1
    assert parsed["metrics"][3]["calc_version"] == "0.2.0"
    assert parsed["metrics"][3]["unit"] == "passenger_miles"
    assert parsed["metrics"][3]["value"] is None
    assert parsed["metrics"][3]["coverage"] is None
    assert parsed["metrics"][3]["detail"] is None
    assert parsed["metrics"][3]["blocking_issue_count"] == 1


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


def test_upt_threshold_overrides_pass_through(clean_rows, upt_golden_fixture):
    # Real count data (the golden factored case) so upt actually computes —
    # over an empty count table it now refuses and carries no detail.
    case = upt_golden_fixture["factored_case"]
    report = run_period(
        RecordingConnection(
            position_rows=clean_rows,
            passenger_event_rows=events_to_rows(load_events(case)),
            operated_trip_rows=[(t,) for t in case["operated_trip_ids"]],
        ),
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
    # settings row, not the code default 0.95, drew the certifiability line
    # for vrm/vrh (upt/pmt still refuse on no count data).
    assert report.persisted_count == 2 and report.blocked_count == 2
    assert report.routed_blocking_count == 2
    # The persisted detail JSONB carries the settings-provided value; its
    # origin story is the report's threshold_sources.
    vrm = report.outcomes[0]
    assert vrm.detail["coverage_threshold"] == "0.5"
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert len(mv_inserts) == 2
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
    # 0.95 blocks the gapped fixture's vrm/vrh exactly as in the
    # default-threshold test; upt/pmt refuse on no count data.
    assert report.blocked_count == 4 and report.routed_blocking_count == 4


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
    assert report.persisted_count == 2
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


# --- identical re-run: one figure on record, never two -----------------------


def test_identical_rerun_reuses_the_existing_figure_rows(clean_rows):
    """Running the same period twice over unchanged data reports the run
    honestly (the run happened, findings routed) but persists NO second
    metric_values row: outcomes carry the EXISTING row ids with
    already_on_record=True, and the report JSON says so."""
    existing_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    conn = RecordingConnection(
        position_rows=clean_rows,
        identical_metric_value_rows=[(existing_id,)],
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)

    # vrm/vrh find their identical figures already on record; upt/pmt still
    # refuse on no count data exactly as in a first run.
    assert report.persisted_count == 2
    vrm, vrh, _upt, _pmt = report.outcomes
    for outcome in (vrm, vrh):
        assert outcome.already_on_record is True
        assert outcome.metric_value_id == existing_id
        assert outcome.value is not None
    assert conn.statements_matching("INSERT INTO computed.metric_values") == []
    assert conn.statements_matching("INSERT INTO lineage.edges") == []

    parsed = json.loads(report.to_json())
    assert parsed["metrics"][0]["already_on_record"] is True
    assert parsed["metrics"][0]["metric_value_id"] == existing_id


# --- the empty period: refuse, never a persisted 0.00 ------------------------


def test_fully_empty_period_refuses_every_metric_and_persists_nothing():
    """The flagged real case: a run over a period with NO data of any kind
    (an agency's month before its connections were flowing) must refuse all
    four metrics — the old behavior persisted official-looking 0.00s."""
    conn = RecordingConnection()  # no positions, no events, no trips
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.positions_loaded == 0
    assert report.passenger_events_loaded == 0
    assert report.operated_trips_loaded == 0
    assert report.persisted_count == 0
    assert report.blocked_count == 4
    assert report.routed_blocking_count == 4
    for outcome in report.outcomes:
        assert outcome.value is None
        assert outcome.metric_value_id is None
        assert len(outcome.routed_blocking_ids) == 1
        assert outcome.detail is None

    # Every dq row is a blocking no_data_in_period naming the calc and the
    # period, in plain words, with no source records (none exist).
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(dq_inserts) == 4
    for (_, params), calc_name in zip(
        dq_inserts, ("vrm_v0", "vrh_v0", "upt_v0", "pmt_v0")
    ):
        issue_type, severity, _status, title, description, record_ids = params[:6]
        assert issue_type == NO_DATA_ISSUE_TYPE
        assert severity == "blocking"
        assert title == "No data covers this period"
        assert calc_name in description
        assert "2026-01-01" in description and "2026-02-01" in description
        assert "no figure is reported" in description
        assert record_ids == []

    # Nothing was written outside the issue phase: no value, no lineage,
    # exactly one commit (the committed evidence).
    assert conn.statements_matching("INSERT INTO computed.metric_values") == []
    assert conn.statements_matching("INSERT INTO lineage.edges") == []
    assert len(conn.commits) == 1
    assert conn.rollback_count == 0


def test_fully_empty_period_refuses_per_mode_voms_too():
    """per_mode=True over an empty period: voms_v0 refuses like the rest
    (its calc is blocking-free, so the guard is the only wall between an
    empty month and a persisted VOMS of 0)."""
    conn = RecordingConnection()
    report = run_period(conn, PERIOD_START, PERIOD_END, per_mode=True)

    assert report.persisted_count == 0
    assert report.blocked_count == 5  # vrm, vrh, upt, pmt + fleet voms
    voms = next(o for o in report.outcomes if o.calc_name == "voms_v0")
    assert voms.value is None and voms.metric_value_id is None
    assert len(voms.routed_blocking_ids) == 1
    # No mode-scoped rows exist: empty input has no mode buckets.
    assert all(o.scope == "agency" for o in report.outcomes)


def test_preview_over_empty_period_refuses_like_a_real_run():
    """The sandbox honesty wall extends to the empty period: no threshold
    variant can conjure a figure out of no evidence."""
    from headway_calc.runner import PreviewVariant, preview_period

    conn = RecordingConnection()
    report = preview_period(
        conn,
        PERIOD_START,
        PERIOD_END,
        variants=[
            PreviewVariant(label="defaults"),
            PreviewVariant(label="loose", coverage_threshold="0.5"),
        ],
    )
    for variant in report.variants:
        for outcome in variant.outcomes:
            assert outcome.blocked and outcome.value is None
            assert [f.issue_type for f in outcome.findings] == [
                NO_DATA_ISSUE_TYPE
            ]
    # The no-writes guarantee stands.
    assert conn.statements_matching("INSERT INTO") == []
    assert conn.commits == []


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


def test_no_run_boardings_classified_through_runner(clean_rows):
    """Handoff 0040 end-to-end: a no-run boarding OUTSIDE the schedule-derived
    revenue window is excluded from UPT as non-revenue, the split lands in the
    persisted detail, and the missing-trip factor is untouched (the ghost's
    trip_id is None, so it never enters the denominator)."""
    from datetime import datetime, timezone

    from conftest import events_to_rows
    from headway_calc.types import PassengerEvent

    svc = date(2026, 1, 15)

    def ev(pid, hour, trip_id, count, classification=None):
        return PassengerEvent(
            event_timestamp=datetime(2026, 1, 15, hour, tzinfo=timezone.utc),
            service_date=svc,
            passenger_event_id=pid,
            vehicle_id="veh-101",
            trip_id=trip_id,
            trip_stop_sequence=None if trip_id is None else 1,
            event_type="Passenger boarded",
            event_count=count,
            source="tides",
            source_record_id=f"rec-{pid}",
            revenue_classification=classification,
        )

    events = [
        ev("a1", 12, "trip-A", 5),  # assigned, in-service -> revenue
        ev("g1", 4, None, 3, "unassigned"),  # pre-service ghost -> excluded
    ]
    conn = RecordingConnection(
        position_rows=clean_rows,
        passenger_event_rows=events_to_rows(events),
        operated_trip_rows=[("trip-A",)],
        agency_timezone_rows=[("UTC",)],
        # revenue window 08:00–20:00 UTC on the service date (seconds since
        # local midnight): the pre-service ghost at 04:00 falls OUTSIDE.
        revenue_window_rows=[(svc, 8 * 3600, 20 * 3600)],
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)

    upt = report.outcomes[2]
    assert upt.calc_version == "0.4.0"
    assert upt.persisted and upt.value == "5"  # only the assigned boarding
    split = upt.detail["revenue_classification"]
    assert split["revenue_boardings"] == 5
    assert split["excluded_non_revenue_boardings"] == 3
    assert split["pending_review_boardings"] == 0
    # double-count guard: one operated trip, zero missing (a1 has events),
    # so factor 1 — the ghost never inflated operated/missing.
    assert upt.detail["operated_trips"] == 1
    assert upt.detail["missing_trips"] == 0
    assert upt.detail["factor_applied"] == "1.000000"
