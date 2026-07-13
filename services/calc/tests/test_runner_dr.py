"""Runner integration for the DR calcs (handoff 0013): whenever the period
holds canonical.dr_trips rows, run_period computes the five dr_*_v0 figures
and persists them under scope 'mode:DR' plus one scope per type of service
('mode:DR:tos:<tos>'), routing every DR finding to dq.issues; with no DR
rows, no DR outcome exists (covered by every pre-0013 runner test). Uses
the recording fake connection — no live database."""

from __future__ import annotations

from datetime import date

import pytest
from conftest import (
    RecordingConnection,
    dr_trips_to_rows,
    load_dr_trips,
    load_positions,
    positions_to_rows,
)

from headway_calc.runner import run_period

PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 8, 1)


@pytest.fixture()
def dr_rows(dr_golden_fixture):
    return dr_trips_to_rows(load_dr_trips(dr_golden_fixture["dispatch_day"]))


@pytest.fixture()
def clean_position_rows(golden_fixture):
    """The vrm/vrh golden fixture minus its gapped trip-C group (the
    test_runner.py clean_rows recipe), so the fleet metrics persist cleanly
    alongside the DR figures."""
    positions = [
        p for p in load_positions(golden_fixture) if p.trip_id != "trip-C"
    ]
    return positions_to_rows(positions)


def _outcomes_by_scope(report, scope):
    return {o.calc_name: o for o in report.outcomes if o.scope == scope}


def test_dr_figures_persist_under_mode_and_tos_scopes(dr_rows, clean_position_rows):
    conn = RecordingConnection(
        position_rows=clean_position_rows, dr_trip_rows=dr_rows
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.dr_trips_loaded == 12

    # Mode-level rows: all five DR calcs, feeding the EXISTING metrics.
    mode_outcomes = _outcomes_by_scope(report, "mode:DR")
    assert sorted(mode_outcomes) == [
        "dr_pmt_v0", "dr_upt_v0", "dr_voms_v0", "dr_vrh_v0", "dr_vrm_v0",
    ]
    expected_values = {
        "dr_vrh_v0": ("vrh", "hours", "4.25"),
        "dr_vrm_v0": ("vrm", "miles", "38.50"),
        "dr_upt_v0": ("upt", "unlinked_passenger_trips", "14"),
        "dr_voms_v0": ("voms", "vehicles", "3"),
        "dr_pmt_v0": ("pmt", "passenger_miles", "62.50"),
    }
    for calc_name, (metric, unit, value) in expected_values.items():
        outcome = mode_outcomes[calc_name]
        assert outcome.metric == metric
        assert outcome.unit == unit
        assert outcome.value == value
        assert outcome.persisted, calc_name
        assert outcome.calc_version == "0.1.0"
        # Every DR figure over simulated rows routed its info finding.
        assert len(outcome.routed_info_ids) == 1, calc_name

    # Per-TOS rows: the fixture holds DO and TX vehicle-days.
    do_outcomes = _outcomes_by_scope(report, "mode:DR:tos:DO")
    tx_outcomes = _outcomes_by_scope(report, "mode:DR:tos:TX")
    assert sorted(do_outcomes) == sorted(tx_outcomes) == sorted(mode_outcomes)
    assert do_outcomes["dr_vrh_v0"].value == "3.25"
    assert tx_outcomes["dr_vrh_v0"].value == "1.00"
    assert do_outcomes["dr_upt_v0"].value == "10"
    assert tx_outcomes["dr_upt_v0"].value == "4"
    assert do_outcomes["dr_voms_v0"].value == "2"
    assert tx_outcomes["dr_voms_v0"].value == "1"
    assert do_outcomes["dr_pmt_v0"].value == "42.50"
    assert tx_outcomes["dr_pmt_v0"].value == "20.00"
    assert do_outcomes["dr_vrm_v0"].value == "26.50"
    assert tx_outcomes["dr_vrm_v0"].value == "12.00"

    # DR figures NEVER persist under the fleet 'agency' scope.
    agency = _outcomes_by_scope(report, "agency")
    assert not any(name.startswith("dr_") for name in agency)

    # DR warnings routed to dq.issues with their own ids (dr_vrm's
    # unmeasured-distance warning, dr_upt's ADA/sponsored conflict, dr_pmt's
    # excluded booking — each on the mode scope AND its TOS scope).
    assert len(mode_outcomes["dr_vrm_v0"].routed_warning_ids) == 1
    assert len(mode_outcomes["dr_upt_v0"].routed_warning_ids) == 1
    assert len(mode_outcomes["dr_pmt_v0"].routed_warning_ids) == 1
    assert len(do_outcomes["dr_vrm_v0"].routed_warning_ids) == 1

    # The persisted SQL wrote metric rows with the DR scopes.
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    scopes_written = {params[4] for _sql, params in mv_inserts}
    assert {"agency", "mode:DR", "mode:DR:tos:DO", "mode:DR:tos:TX"} <= scopes_written


def test_dr_detail_and_report_serialization(dr_rows, clean_position_rows):
    conn = RecordingConnection(
        position_rows=clean_position_rows, dr_trip_rows=dr_rows
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)
    doc = report.to_dict()
    assert doc["dr_trips_loaded"] == 12
    dr_metrics = [m for m in doc["metrics"] if m["scope"].startswith("mode:DR")]
    assert len(dr_metrics) == 15  # 5 mode-level + 5 DO + 5 TX
    vrh = next(
        m
        for m in dr_metrics
        if m["calc_name"] == "dr_vrh_v0" and m["scope"] == "mode:DR"
    )
    assert vrh["detail"]["revenue_spans"] == 6
    assert vrh["detail"]["interruption_breaks"] == {"fuel": 1, "lunch": 1}
    assert vrh["detail"]["source_mix"] == {"dr_simulated": 12}
    # DR carries no coverage ratio (no completeness threshold is quoted for
    # DR) — the outcome's coverage accessor is None, not a KeyError.
    assert vrh["coverage"] is None


def test_no_dr_rows_no_dr_outcomes(clean_position_rows):
    conn = RecordingConnection(position_rows=clean_position_rows)
    report = run_period(conn, PERIOD_START, PERIOD_END)
    assert report.dr_trips_loaded == 0
    assert not any(o.scope.startswith("mode:DR") for o in report.outcomes)
