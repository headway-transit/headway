"""run_period × statistician attestations (handoff 0019): the loop from a
recorded cert.attestations row to a persisted, provenance-carrying figure —
and every boundary where the attestation must NOT act.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

from conftest import RecordingConnection, events_to_rows

from headway_calc.runner import run_period
from headway_calc.types import PassengerEvent
from headway_calc.upt import BOARDING_EVENT_TYPE

PERIOD_START = date(2026, 7, 9)
PERIOD_END = date(2026, 7, 10)
T0 = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


def _boarding(pe_id, trip, count, second):
    return PassengerEvent(
        event_timestamp=T0.replace(second=second % 60, minute=second // 60),
        service_date=PERIOD_START,
        passenger_event_id=pe_id,
        vehicle_id="veh-1",
        trip_id=trip,
        trip_stop_sequence=1,
        event_type=BOARDING_EVENT_TYPE,
        event_count=count,
        source="tides",
        source_record_id=f"rec-{pe_id}",
    )


#: 10 boardings on 1 of 10 operated trips → missing share 0.9 > 2%.
EVENT_ROWS = events_to_rows([_boarding("1", "trip-1", 10, 0)])
OPERATED_ROWS = [(f"trip-{i}",) for i in range(1, 11)]


def _attestation_row(
    attestation_id="att-42",
    metric="upt",
    scope_pattern="agency",
    revoked_at=None,
):
    return (
        attestation_id,
        "Dr. R. Fisher",
        "PhD statistics",
        "Route-stratified expansion factoring",
        "dms://approvals/2026/upt-factoring.pdf",
        metric,
        scope_pattern,
        date(2026, 7, 1),
        date(2026, 8, 1),
        "certifier",
        datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        revoked_at,
    )


def _outcome(report, metric, scope="agency"):
    return next(
        o for o in report.outcomes if o.metric == metric and o.scope == scope
    )


def test_without_attestation_rows_upt_blocks_exactly_as_before():
    conn = RecordingConnection(
        passenger_event_rows=EVENT_ROWS, operated_trip_rows=OPERATED_ROWS
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)
    upt = _outcome(report, "upt")
    assert not upt.persisted
    assert len(upt.routed_blocking_ids) == 1
    assert report.attestations_loaded == 0


def test_attestation_row_unblocks_upt_and_persists_provenance():
    conn = RecordingConnection(
        passenger_event_rows=EVENT_ROWS,
        operated_trip_rows=OPERATED_ROWS,
        attestation_rows=[_attestation_row()],
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)
    assert report.attestations_loaded == 1
    upt = _outcome(report, "upt")
    assert upt.persisted
    assert upt.value == "100"  # 10 counted × 10/1
    assert upt.routed_blocking_ids == ()
    assert upt.detail["attestation"]["attestation_id"] == "att-42"
    # The attested info finding was routed to dq.issues (severity info) and
    # the persisted detail JSONB carries the attestation dict verbatim.
    assert len(upt.routed_info_ids) == 1
    persisted_details = [
        params[8]
        for sql, params in conn.executed
        if "INSERT INTO computed.metric_values" in sql and params[0] == "upt"
    ]
    assert len(persisted_details) == 1
    assert (
        json.loads(persisted_details[0])["attestation"]["statistician_name"]
        == "Dr. R. Fisher"
    )
    # pmt is untouched by a metric='upt' attestation (blocked: everything
    # missing, no geometry).
    pmt = _outcome(report, "pmt")
    assert not pmt.persisted


def test_scope_mismatched_attestation_changes_nothing():
    conn = RecordingConnection(
        passenger_event_rows=EVENT_ROWS,
        operated_trip_rows=OPERATED_ROWS,
        attestation_rows=[_attestation_row(scope_pattern="mode:bus")],
    )
    report = run_period(conn, PERIOD_START, PERIOD_END)
    assert report.attestations_loaded == 1  # loaded, but out of scope
    upt = _outcome(report, "upt")
    assert not upt.persisted
    assert len(upt.routed_blocking_ids) == 1


def test_pre_migration_database_missing_table_refuses_as_before(caplog):
    conn = RecordingConnection(
        passenger_event_rows=EVENT_ROWS,
        operated_trip_rows=OPERATED_ROWS,
        attestations_table_missing=True,
    )
    with caplog.at_level("WARNING"):
        report = run_period(conn, PERIOD_START, PERIOD_END)
    assert report.attestations_loaded == 0
    assert not _outcome(report, "upt").persisted
    assert any(
        "cert.attestations does not exist" in r.message for r in caplog.records
    )


def test_per_mode_scope_isolation_mode_pattern_reaches_only_its_scope():
    """A 'mode:bus'-scoped attestation factors the bus-scoped row on the
    per-mode path but NOT the fleet 'agency' row (hard limit 3 through the
    runner's selector)."""
    events = [_boarding("1", "trip-1", 10, 0)]
    bus_events = [
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
    # Positions give the per-mode operated denominators; without positions
    # the mode buckets come from events alone (operated buckets empty →
    # share 0 for the bucket). Keep it simple: no positions → the fleet
    # 'agency' row uses OPERATED_ROWS (share 0.9, blocked without an
    # in-scope attestation), while mode:bus has zero operated trips (share
    # 0 — persists on its own merits either way). The assertion that
    # matters: the 'agency' figure is NOT factored by the mode:bus pattern.
    conn = RecordingConnection(
        passenger_event_rows=events_to_rows(bus_events),
        operated_trip_rows=OPERATED_ROWS,
        attestation_rows=[_attestation_row(scope_pattern="mode:bus")],
    )
    report = run_period(conn, PERIOD_START, PERIOD_END, per_mode=True)
    agency_upt = _outcome(report, "upt", "agency")
    assert not agency_upt.persisted  # the mode-scoped attestation never
    assert len(agency_upt.routed_blocking_ids) == 1  # leaks to 'agency'
