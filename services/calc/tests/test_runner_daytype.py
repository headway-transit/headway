"""run_daytype_period (handoff 0020): two-transaction discipline, scope
persistence, settings precedence, the migration-0031 tolerance, and the
attestation binding — over the RecordingConnection fake."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from conftest import RecordingConnection, events_to_rows, positions_to_rows

from headway_calc.runner import run_daytype_period
from headway_calc.types import PassengerEvent, VehiclePosition

UTC = timezone.utc
PERIOD = (date(2026, 7, 1), date(2026, 7, 8))


def pos(day, hour, vehicle="v1", trip="t1"):
    return VehiclePosition(
        time=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
        vehicle_id=vehicle,
        trip_id=trip,
        latitude=42.0,
        longitude=-71.0,
        source_record_id=f"p-{day.isoformat()}-{vehicle}-{hour}",
    )


def board(day, hour, pid, trip="t1", count=10, source="tides"):
    return PassengerEvent(
        event_timestamp=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
        service_date=day,
        passenger_event_id=pid,
        vehicle_id="v1",
        trip_id=trip,
        trip_stop_sequence=1,
        event_type="Passenger boarded",
        event_count=count,
        source=source,
        source_record_id=f"r-{pid}",
    )


def _conn(**kwargs):
    positions = [
        pos(date(2026, 7, 1), 8, trip="t1"),
        pos(date(2026, 7, 4), 8, trip="t2"),
    ]
    events = [
        board(date(2026, 7, 1), 9, "e1", trip="t1", count=10),
        board(date(2026, 7, 4), 9, "e2", trip="t2", count=20),
    ]
    kwargs.setdefault("position_rows", positions_to_rows(positions))
    kwargs.setdefault("passenger_event_rows", events_to_rows(events))
    return RecordingConnection(**kwargs)


def test_daytype_run_persists_scoped_rows_and_routes_findings_first():
    conn = _conn()
    report = run_daytype_period(conn, *PERIOD)

    # Three days_operated rows + three typical averages (no atypical
    # declarations -> no atypical splits); both metrics share the daytype
    # scopes, so key on (metric, scope).
    by_metric_scope = {(o.metric, o.scope): o for o in report.outcomes}
    assert set(by_metric_scope) == {
        (metric, f"daytype:{day_type}")
        for metric in ("days_operated", "upt_avg")
        for day_type in ("weekday", "saturday", "sunday")
    }
    assert by_metric_scope[("days_operated", "daytype:weekday")].value == "1"
    assert by_metric_scope[("days_operated", "daytype:saturday")].value == "1"
    assert by_metric_scope[("days_operated", "daytype:sunday")].value == "0"
    assert by_metric_scope[("upt_avg", "daytype:weekday")].value == "10.00"
    assert by_metric_scope[("upt_avg", "daytype:saturday")].value == "20.00"
    # Sunday never operated: the average refuses; nothing persisted for it.
    sunday_avg = by_metric_scope[("upt_avg", "daytype:sunday")]
    assert sunday_avg.value is None
    assert not sunday_avg.persisted
    assert len(sunday_avg.routed_blocking_ids) == 1

    # Two transactions: all dq.issues inserts precede the first commit;
    # metric_values inserts land between the commits (fail-loudly-first).
    assert len(conn.commits) == 2
    first_commit = conn.commits[0]
    issue_positions = [
        i for i, (sql, _p) in enumerate(conn.executed) if "dq.issues" in sql
    ]
    value_positions = [
        i
        for i, (sql, _p) in enumerate(conn.executed)
        if "computed.metric_values" in sql and sql.startswith("INSERT")
    ]
    assert issue_positions and max(issue_positions) < first_commit
    assert value_positions and min(value_positions) >= first_commit

    # Classification travels in the report.
    assert report.classification["2026-07-04"]["day_type"] == "saturday"
    assert report.daytype_version == "0.1.0"


def test_daytype_thresholds_resolve_settings_then_default():
    conn = _conn()
    report = run_daytype_period(conn, *PERIOD)
    assert report.threshold_sources == {
        "missing_trip_threshold": "settings",
        "imbalance_threshold": "default",
    }
    explicit = run_daytype_period(
        _conn(), *PERIOD, missing_trip_threshold="0.5"
    )
    assert explicit.threshold_sources["missing_trip_threshold"] == "explicit"
    assert explicit.missing_trip_threshold == Decimal("0.5")


def test_pre_migration_0031_database_loads_no_overrides_and_proceeds():
    conn = _conn(service_day_overrides_table_missing=True)
    report = run_daytype_period(conn, *PERIOD)
    assert report.overrides_loaded == 0
    # Day-of-week classification, all typical — stated, not assumed.
    assert all(not c["atypical"] for c in report.classification.values())
    assert all(not c["override"] for c in report.classification.values())


def test_overrides_shape_the_run():
    ov_rows = [
        (
            date(2026, 7, 4),
            None,
            True,
            "street festival",
            "certifier",
            datetime(2026, 6, 30, tzinfo=UTC),
        )
    ]
    conn = _conn(service_day_override_rows=ov_rows)
    report = run_daytype_period(conn, *PERIOD)
    by_metric_scope = {(o.metric, o.scope): o for o in report.outcomes}
    # The only operated saturday is atypical: its own split row persists,
    # and the typical saturday average refuses (zero typical operated days).
    assert (
        by_metric_scope[("upt_avg", "daytype:saturday:atypical")].value
        == "20.00"
    )
    assert by_metric_scope[("upt_avg", "daytype:saturday")].value is None
    assert report.overrides_loaded == 1
    assert report.classification["2026-07-04"]["atypical"] is True


def test_per_mode_adds_mode_daytype_scopes():
    positions = [
        pos(date(2026, 7, 1), 8, trip="t1"),
    ]
    events = [
        board(date(2026, 7, 1), 9, "e1", trip="t1", count=10),
    ]
    # Attach a mode to both rows.
    positions = [
        VehiclePosition(
            time=p.time,
            vehicle_id=p.vehicle_id,
            trip_id=p.trip_id,
            latitude=p.latitude,
            longitude=p.longitude,
            source_record_id=p.source_record_id,
            mode="bus",
        )
        for p in positions
    ]
    events = [
        PassengerEvent(
            event_timestamp=e.event_timestamp,
            service_date=e.service_date,
            passenger_event_id=e.passenger_event_id,
            vehicle_id=e.vehicle_id,
            trip_id=e.trip_id,
            trip_stop_sequence=e.trip_stop_sequence,
            event_type=e.event_type,
            event_count=e.event_count,
            source=e.source,
            source_record_id=e.source_record_id,
            mode="bus",
        )
        for e in events
    ]
    conn = RecordingConnection(
        position_rows=positions_to_rows(positions),
        passenger_event_rows=events_to_rows(events),
    )
    report = run_daytype_period(conn, *PERIOD, per_mode=True)
    scopes = {(o.metric, o.scope) for o in report.outcomes}
    assert ("upt_avg", "mode:bus:daytype:weekday") in scopes
    assert report.per_mode is True


def test_value_phase_failure_rolls_back_values_but_keeps_issues():
    conn = _conn(fail_on="computed.metric_values")
    try:
        run_daytype_period(conn, *PERIOD)
        raise AssertionError("expected the simulated persist failure")
    except RuntimeError:
        pass
    # Issues were committed first; the value phase rolled back.
    assert len(conn.commits) == 1
    assert conn.rollback_count == 1
