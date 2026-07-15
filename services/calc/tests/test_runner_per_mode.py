"""Runner tests for the handoff-0009 per-mode path (run_period(per_mode=True))
with the recording fake connection. No live database.

Covers: the default (per_mode=False) staying byte-identically pre-0009 even
over mode-carrying rows; the full per-mode run over the mode_scope golden
fixture (agency rows unchanged + voms + one scoped row per metric per mode,
scope in the INSERT, mode-scoped dq descriptions naming their scope, the ONE
run-level unknown_mode_share info); per-scope blocking independence (a gapped
mode blocks ONLY its scope); and the CLI --per-mode flag.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal

from conftest import (
    RecordingConnection,
    events_to_rows,
    load_events,
    load_positions,
    positions_to_rows,
)

from headway_calc._cli import _parse_args as cli_parse_args
from headway_calc.runner import run_period
from headway_calc.types import VehiclePosition

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 2, 1)


def _mode_conn(mode_golden_fixture) -> RecordingConnection:
    positions = load_positions(mode_golden_fixture)
    events = load_events(mode_golden_fixture)
    operated = sorted({p.trip_id for p in positions if p.trip_id is not None})
    return RecordingConnection(
        position_rows=positions_to_rows(positions),
        passenger_event_rows=events_to_rows(events),
        operated_trip_rows=[(t,) for t in operated],
    )


# --- default OFF: pre-0009 behavior byte-identical ---------------------------


def test_per_mode_default_off_no_voms_no_mode_rows(mode_golden_fixture):
    conn = _mode_conn(mode_golden_fixture)
    report = run_period(conn, PERIOD_START, PERIOD_END)

    assert report.per_mode is False
    assert report.run_info_ids == ()
    # vrm, vrh, upt, pmt — no voms, no mode rows.
    assert len(report.outcomes) == 4
    assert [o.metric for o in report.outcomes] == ["vrm", "vrh", "upt", "pmt"]
    assert {o.scope for o in report.outcomes} == {"agency"}
    # pmt is honestly BLOCKED here: the fake serves no stop geometry, so both
    # event trips are geometry_unavailable — 2 of 2 operated > the 2% line.
    persisted_metrics = [o.metric for o in report.outcomes if o.persisted]
    assert persisted_metrics == ["vrm", "vrh", "upt"]
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert [p[4] for _, p in mv_inserts] == ["agency"] * 3
    # No unknown_mode_share, no voms findings routed on the default path.
    dq_types = [p[0] for _, p in conn.statements_matching("INSERT INTO dq.issues")]
    assert "unknown_mode_share" not in dq_types
    assert "voms_partial_observation" not in dq_types


# --- the full per-mode run over the mode_scope golden fixture ----------------


def test_per_mode_run_emits_agency_plus_scoped_rows(
    mode_golden_fixture, mode_golden_expected
):
    conn = _mode_conn(mode_golden_fixture)
    report = run_period(conn, PERIOD_START, PERIOD_END, per_mode=True)

    assert report.per_mode is True
    # 5 agency outcomes (vrm, vrh, upt, pmt + voms) + 5 metrics x 3 buckets.
    assert len(report.outcomes) == 20
    # pmt is honestly BLOCKED wherever the (geometry-less) fake leaves its
    # event trips unusable: agency + bus + subway; the degenerate unknown
    # bucket (no operated trips, no placeable events) persists 0.00.
    assert report.persisted_count == 17 and report.blocked_count == 3

    # Agency rows first, unchanged values (golden), then per-metric buckets.
    expected_order = (
        [
            ("vrm", "agency"),
            ("vrh", "agency"),
            ("upt", "agency"),
            ("pmt", "agency"),
            ("voms", "agency"),
        ]
        + [("vrm", f"mode:{m}") for m in ("bus", "subway", "unknown")]
        + [("vrh", f"mode:{m}") for m in ("bus", "subway", "unknown")]
        + [("upt", f"mode:{m}") for m in ("bus", "subway", "unknown")]
        + [("pmt", f"mode:{m}") for m in ("bus", "subway", "unknown")]
        + [("voms", f"mode:{m}") for m in ("bus", "subway", "unknown")]
    )
    assert [(o.metric, o.scope) for o in report.outcomes] == expected_order

    # The pmt blocking is per scope, with the geometry gap named.
    pmt_blocked = [
        o for o in report.outcomes if o.metric == "pmt" and not o.persisted
    ]
    assert [(o.scope) for o in pmt_blocked] == [
        "agency",
        "mode:bus",
        "mode:subway",
    ]
    for o in pmt_blocked:
        assert o.detail["invalid_trip_reasons"] == {"geometry_unavailable": 1} or (
            o.scope == "agency"
            and o.detail["invalid_trip_reasons"] == {"geometry_unavailable": 2}
        )

    by_key = {(o.metric, o.scope): o for o in report.outcomes}
    exp = mode_golden_expected
    for metric in ("vrm", "vrh", "upt", "voms"):
        assert by_key[(metric, "agency")].value == exp["fleet"][metric]
        for bucket, value in exp["per_mode"][metric].items():
            assert by_key[(metric, f"mode:{bucket}")].value == value

    # Calc versions unchanged on the mode-scoped rows (input selection, not
    # a semantics change — no version bump).
    assert by_key[("vrm", "mode:bus")].calc_version == "0.2.0"
    assert by_key[("vrh", "mode:bus")].calc_version == "0.4.0"
    assert by_key[("upt", "mode:bus")].calc_version == "0.2.0"
    assert by_key[("voms", "mode:bus")].calc_version == "0.1.0"
    assert by_key[("voms", "agency")].unit == "vehicles"

    # The scope column is bound on every INSERT (param index 4); the three
    # blocked pmt scopes persist NO row (the structural guardrail).
    blocked_keys = {("pmt", "agency"), ("pmt", "mode:bus"), ("pmt", "mode:subway")}
    mv_inserts = conn.statements_matching("INSERT INTO computed.metric_values")
    assert [(p[0], p[4]) for _, p in mv_inserts] == [
        key for key in expected_order if key not in blocked_keys
    ]

    # ONE run-level unknown_mode_share info routed (the fixture carries
    # NULL-mode rows), counted in the report's info total.
    assert len(report.run_info_ids) == 1
    dq_inserts = conn.statements_matching("INSERT INTO dq.issues")
    unknown_rows = [p for _, p in dq_inserts if p[0] == "unknown_mode_share"]
    assert len(unknown_rows) == 1
    assert unknown_rows[0][1] == "info"
    assert "mode_dimension" in unknown_rows[0][4]  # routed identity named

    # Mode-scoped findings name their scope; agency findings do not.
    vrh_infos = [p for _, p in dq_inserts if p[0] == "block_unavailable"]
    assert len(vrh_infos) == 4  # 2 agency vehicle-days + bus + subway
    agency_infos = [p for p in vrh_infos if "Metric-value scope" not in p[4]]
    scoped_infos = [p for p in vrh_infos if "Metric-value scope" in p[4]]
    assert len(agency_infos) == 2
    assert sorted(
        "mode:bus" if "'mode:bus'" in p[4] else "mode:subway" for p in scoped_infos
    ) == ["mode:bus", "mode:subway"]

    # voms warnings: agency + 3 buckets, all voms_partial_observation.
    voms_warnings = [p for _, p in dq_inserts if p[0] == "voms_partial_observation"]
    assert len(voms_warnings) == 4
    assert {p[1] for p in voms_warnings} == {"warning"}

    # Two transactions, issues first; nothing rolled back.
    assert len(conn.commits) == 2
    assert conn.commits[-1] == len(conn.executed)
    assert conn.rollback_count == 0

    # Report JSON carries the new fields.
    parsed = json.loads(report.to_json())
    assert parsed["per_mode"] is True
    assert len(parsed["run_info_ids"]) == 1
    assert parsed["routed_info_count"] == report.routed_info_count
    assert {m["scope"] for m in parsed["metrics"]} == {
        "agency",
        "mode:bus",
        "mode:subway",
        "mode:unknown",
    }


def test_per_mode_run_is_deterministic(mode_golden_fixture):
    def _stable(report):
        d = report.to_dict()
        d["run_info_ids"] = len(d["run_info_ids"])
        for m in d["metrics"]:
            m["metric_value_id"] = None
            m["routed_blocking_ids"] = len(m["routed_blocking_ids"])
            m["routed_warning_ids"] = len(m["routed_warning_ids"])
            m["routed_info_ids"] = len(m["routed_info_ids"])
        return d

    report_a = run_period(
        _mode_conn(mode_golden_fixture), PERIOD_START, PERIOD_END, per_mode=True
    )
    report_b = run_period(
        _mode_conn(mode_golden_fixture), PERIOD_START, PERIOD_END, per_mode=True
    )
    assert _stable(report_a) == _stable(report_b)


# --- per-scope blocking independence -----------------------------------------


def _gapped_two_mode_rows() -> list[tuple]:
    """bus trip-A clean (10 positions, 60 s), subway trip-C gapped (400 s
    within-trip gap): agency vrm coverage 1/2 and subway 0/1 fall below the
    default 0.95 while bus (1/1) passes."""
    positions = [
        VehiclePosition(
            time=datetime(2026, 1, 15, 12, i, tzinfo=timezone.utc),
            vehicle_id="veh-101",
            trip_id="trip-A",
            latitude=40.0 + 0.01 * i,
            longitude=-75.0,
            source_record_id=f"rec-a-{i:02d}",
            mode="bus",
        )
        for i in range(10)
    ]
    gap_times = [
        datetime(2026, 1, 15, 13, 0, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 15, 13, 1, 0, tzinfo=timezone.utc),
        datetime(2026, 1, 15, 13, 7, 40, tzinfo=timezone.utc),  # 400 s gap
        datetime(2026, 1, 15, 13, 8, 40, tzinfo=timezone.utc),
    ]
    positions += [
        VehiclePosition(
            time=t,
            vehicle_id="veh-202",
            trip_id="trip-C",
            latitude=41.0 + 0.01 * i,
            longitude=-75.0,
            source_record_id=f"rec-c-{i:02d}",
            mode="subway",
        )
        for i, t in enumerate(gap_times)
    ]
    return positions_to_rows(positions)


def test_blocking_is_per_scope_gapped_mode_blocks_only_its_rows():
    conn = RecordingConnection(position_rows=_gapped_two_mode_rows())
    report = run_period(conn, PERIOD_START, PERIOD_END, per_mode=True)

    by_key = {(o.metric, o.scope): o for o in report.outcomes}
    # Agency vrm/vrh: coverage 1/2 = 0.5 < 0.95 -> blocked.
    assert not by_key[("vrm", "agency")].persisted
    assert not by_key[("vrh", "agency")].persisted
    # bus: 1/1 clean -> persists the golden trip-A values.
    assert by_key[("vrm", "mode:bus")].value == "6.22"
    assert by_key[("vrh", "mode:bus")].value == "0.15"
    # subway: 0/1 -> blocked for vrm/vrh, with its own scoped blocking rows.
    assert not by_key[("vrm", "mode:subway")].persisted
    assert not by_key[("vrh", "mode:subway")].persisted
    assert len(by_key[("vrm", "mode:subway")].routed_blocking_ids) == 1
    # voms never blocks — even the gapped subway subset persists a maximum.
    assert by_key[("voms", "agency")].value == "2"
    assert by_key[("voms", "mode:subway")].value == "1"

    # The guardrail holds per scoped row: no INSERT for any blocked scope.
    mv_scopes = {
        (p[0], p[4])
        for _, p in conn.statements_matching("INSERT INTO computed.metric_values")
    }
    assert ("vrm", "agency") not in mv_scopes
    assert ("vrm", "mode:subway") not in mv_scopes
    assert ("vrm", "mode:bus") in mv_scopes
    assert ("voms", "mode:subway") in mv_scopes


# --- CLI flag ----------------------------------------------------------------


def test_cli_per_mode_flag_parses_and_defaults_off():
    base = ["--period-start", "2026-06-01", "--period-end", "2026-07-01"]
    assert cli_parse_args(base).per_mode is False
    assert cli_parse_args(base + ["--per-mode"]).per_mode is True
