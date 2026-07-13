"""DbWriter unit tests with a fake DB-API connection capturing (sql, params)."""

from __future__ import annotations

from datetime import datetime, timezone

from datetime import date

from headway_transform.envelope import validate_envelope
from headway_transform.gtfs_rt_positions import CanonicalVehiclePosition
from headway_transform.gtfs_static import (
    CanonicalRoute,
    CanonicalStop,
    CanonicalStopTime,
    CanonicalTrip,
)
from headway_transform.model import DQFinding, LineageEdge
from headway_transform.tides_passenger_events import CanonicalPassengerEvent
from headway_transform.writer import DbWriter

from conftest import make_envelope_dict

TIME = datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)


def test_insert_raw_record_base64(fake_connection) -> None:
    envelope = validate_envelope(make_envelope_dict(b"payload-bytes"))
    DbWriter(fake_connection).insert_raw_record(envelope)

    [(sql, params)] = fake_connection.executed
    assert "INSERT INTO raw.records" in sql
    assert "ON CONFLICT (record_id) DO NOTHING" in sql
    assert params == (
        envelope.record_id,
        "gtfs_rt",
        "headway-gtfs-rt",
        "0.1.0",
        "application/x-protobuf",
        "base64",
        None,  # payload_ref only set for object_ref
        "2026-07-08T12:00:00Z",
        "ok",
        None,
    )
    # No tenant_id column anywhere (ADR-0004).
    assert "tenant" not in sql.lower()


def test_insert_raw_record_object_ref_sets_payload_ref(fake_connection) -> None:
    envelope = validate_envelope(
        make_envelope_dict(
            b"zip-bytes",
            payload_encoding="object_ref",
            payload="objects/feed-2026-07-08.zip",
            content_type="application/zip",
        )
    )
    DbWriter(fake_connection).insert_raw_record(envelope)
    [(_sql, params)] = fake_connection.executed
    assert params[6] == "objects/feed-2026-07-08.zip"


def test_upsert_routes_and_trips_sql(fake_connection) -> None:
    writer = DbWriter(fake_connection)
    writer.upsert_routes([CanonicalRoute("R1", "5", "Fifth St", "bus")])
    writer.upsert_trips([CanonicalTrip("T1", "R1", "WKDY", 0, "B-77")])

    route_sql, route_params = fake_connection.sql_for("canonical.routes")[0]
    assert "ON CONFLICT (route_id) DO UPDATE" in route_sql
    assert route_params == ("R1", "5", "Fifth St", "bus")

    trip_sql, trip_params = fake_connection.sql_for("canonical.trips")[0]
    assert "ON CONFLICT (trip_id) DO UPDATE" in trip_sql
    assert "block_id     = EXCLUDED.block_id" in trip_sql
    assert trip_params == ("T1", "R1", "WKDY", 0, "B-77")


def test_upsert_trip_without_block_id_binds_null(fake_connection) -> None:
    """Feeds omitting the optional block_id upsert NULL (backfill-safe)."""
    DbWriter(fake_connection).upsert_trips([CanonicalTrip("T2", "R1", "WKDY", 1)])
    _sql, params = fake_connection.sql_for("canonical.trips")[0]
    assert params == ("T2", "R1", "WKDY", 1, None)


def test_upsert_stops_and_stop_times_sql(fake_connection) -> None:
    writer = DbWriter(fake_connection)
    writer.upsert_stops([CanonicalStop("S1", "First St", 42.35, -71.06)])
    writer.upsert_stop_times(
        [CanonicalStopTime("T1", "S1", 1, 38400, 38430, 1.25)]
    )

    stop_sql, stop_params = fake_connection.sql_for("canonical.stops")[0]
    assert "ON CONFLICT (stop_id) DO UPDATE" in stop_sql
    assert stop_params == ("S1", "First St", 42.35, -71.06)

    st_sql, st_params = fake_connection.sql_for("canonical.stop_times")[0]
    assert "ON CONFLICT (trip_id, stop_sequence) DO UPDATE" in st_sql
    assert "shape_dist_traveled = EXCLUDED.shape_dist_traveled" in st_sql
    assert st_params == ("T1", "S1", 1, 38400, 38430, 1.25)


def test_upsert_stop_and_stop_time_nulls_bind_null(fake_connection) -> None:
    """NULL coordinates, times and shape_dist_traveled are preserved as NULL
    (handoff 0011: never fabricated)."""
    writer = DbWriter(fake_connection)
    writer.upsert_stops([CanonicalStop("node-1", None, None, None)])
    writer.upsert_stop_times(
        [CanonicalStopTime("T1", "S2", 2, None, None, None)]
    )
    _sql, stop_params = fake_connection.sql_for("canonical.stops")[0]
    assert stop_params == ("node-1", None, None, None)
    _sql, st_params = fake_connection.sql_for("canonical.stop_times")[0]
    assert st_params == ("T1", "S2", 2, None, None, None)


def test_insert_vehicle_positions_conflict_do_nothing_on_unique_key(
    fake_connection,
) -> None:
    row = CanonicalVehiclePosition(
        time=TIME,
        vehicle_id="bus-1",
        trip_id="T1",
        route_id="R1",
        latitude=44.9,
        longitude=-93.2,
        bearing=None,
        speed_mps=None,
        odometer_m=None,
        source_record_id="cd" * 32,
    )
    DbWriter(fake_connection).insert_vehicle_positions([row])

    [(sql, params)] = fake_connection.executed
    assert "INSERT INTO canonical.vehicle_positions" in sql
    assert 'ON CONFLICT (vehicle_id, "time", source_record_id) DO NOTHING' in sql
    assert params == (
        TIME, "bus-1", "T1", "R1", 44.9, -93.2, None, None, None, "cd" * 32
    )


def test_insert_passenger_events_conflict_do_nothing_on_unique_key(
    fake_connection,
) -> None:
    row = CanonicalPassengerEvent(
        event_timestamp=TIME,
        service_date=date(2026, 7, 8),
        passenger_event_id="PE-1",
        vehicle_id="bus-1",
        trip_id="T1",
        trip_stop_sequence=1,
        event_type="Passenger boarded",
        event_count=2,
        source="tides_simulated",
        source_record_id="cd" * 32,
    )
    DbWriter(fake_connection).insert_passenger_events([row])

    [(sql, params)] = fake_connection.executed
    assert "INSERT INTO canonical.passenger_events" in sql
    assert (
        "ON CONFLICT (passenger_event_id, event_timestamp, source_record_id) "
        "DO NOTHING" in sql
    )
    assert params == (
        TIME,
        date(2026, 7, 8),
        "PE-1",
        "bus-1",
        "T1",
        1,
        "Passenger boarded",
        2,
        "tides_simulated",
        "cd" * 32,
    )
    # No tenant_id column anywhere (ADR-0004).
    assert "tenant" not in sql.lower()


def test_insert_passenger_event_null_count_binds_none_not_zero(
    fake_connection,
) -> None:
    """A NULL event_count is bound as None — preserved, never coalesced."""
    row = CanonicalPassengerEvent(
        event_timestamp=TIME,
        service_date=date(2026, 7, 8),
        passenger_event_id="PE-2",
        vehicle_id="bus-1",
        trip_id=None,
        trip_stop_sequence=2,
        event_type="Passenger alighted",
        event_count=None,
        source="tides",
        source_record_id="cd" * 32,
    )
    DbWriter(fake_connection).insert_passenger_events([row])
    [(_sql, params)] = fake_connection.executed
    assert params[7] is None  # event_count — None, NOT 0
    assert params[4] is None  # trip_id stays unassigned


def test_insert_lineage_edges(fake_connection) -> None:
    edge = LineageEdge(
        output_kind="canonical.vehicle_positions",
        output_id="bus-1|2026-07-08T12:00:00Z|" + "cd" * 32,
        transform_name="normalize_gtfs_rt_positions",
        transform_version="0.1.0",
        input_kind="raw.records",
        input_id="cd" * 32,
    )
    DbWriter(fake_connection).insert_lineage_edges([edge])
    [(sql, params)] = fake_connection.executed
    assert "INSERT INTO lineage.edges" in sql
    # Replay idempotency (migration 0023): the full natural key is the
    # conflict target — a redelivered message adds zero duplicate edges.
    assert "ON CONFLICT (output_kind, output_id, transform_name" in sql
    assert "DO NOTHING" in sql
    assert params == (
        edge.output_kind,
        edge.output_id,
        "normalize_gtfs_rt_positions",
        "0.1.0",
        "raw.records",
        edge.input_id,
    )


def test_insert_dq_issues(fake_connection) -> None:
    finding = DQFinding(
        issue_type="malformed_entity",
        severity="warning",
        title="t",
        description="d",
        source_record_ids=["ef" * 32],
    )
    DbWriter(fake_connection).insert_dq_issues([finding])
    [(sql, params)] = fake_connection.executed
    assert "INSERT INTO dq.issues" in sql
    # Replay idempotency (migration 0023): transform findings carry a
    # dedupe_key; the partial unique index is the conflict target.
    assert "ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING" in sql
    key = finding.transform_dedupe_key()
    assert params == ("malformed_entity", "warning", "t", "d", ["ef" * 32], key)


def test_transform_dedupe_key_is_stable_and_scoped() -> None:
    kwargs = dict(
        issue_type="malformed_dr_trip",
        severity="warning",
        title="t",
        description="d, row 3",
        source_record_ids=["ef" * 32],
    )
    a, b = DQFinding(**kwargs), DQFinding(**kwargs)
    # Deterministic: a replay's byte-identical finding gets the same key.
    assert a.transform_dedupe_key() == b.transform_dedupe_key()
    # Scoped: recognizably transform-origin, never colliding with keys any
    # other origin might someday mint.
    assert a.transform_dedupe_key().startswith("transform:")
    # Different identity -> different key.
    other = DQFinding(**{**kwargs, "description": "d, row 4"})
    assert other.transform_dedupe_key() != a.transform_dedupe_key()


def test_finding_without_source_records_never_deduped(fake_connection) -> None:
    # No source-record anchor = no stable subject identity: dedupe_key is
    # NULL, so the partial unique index never collapses two such findings
    # (human-/AI-created rows also stay NULL — never deduplicated).
    finding = DQFinding(
        issue_type="transform_failure",
        severity="blocking",
        title="t",
        description="d",
        source_record_ids=[],
    )
    assert finding.transform_dedupe_key() is None
    DbWriter(fake_connection).insert_dq_issues([finding])
    [(_, params)] = fake_connection.executed
    assert params[-1] is None


def test_upsert_agencies_sql(fake_connection) -> None:
    from headway_transform.gtfs_static import CanonicalAgency

    DbWriter(fake_connection).upsert_agencies(
        [CanonicalAgency(agency_id="A1", name="Example Transit", timezone="America/New_York")]
    )
    [(sql, params)] = fake_connection.executed
    assert "INSERT INTO canonical.agencies" in sql
    assert "ON CONFLICT (agency_id) DO UPDATE" in sql
    assert params == ("A1", "Example Transit", "America/New_York")


def test_insert_trip_updates_conflict_do_nothing_on_natural_key(
    fake_connection,
) -> None:
    from headway_transform.trip_updates import CanonicalTripUpdate

    row = CanonicalTripUpdate(
        feed_timestamp=TIME,
        trip_id="T1",
        route_id="R1",
        vehicle_id="bus-1",
        stop_id="S1",
        stop_sequence=5,
        predicted_arrival=TIME,
        arrival_delay_seconds=90,
        arrival_uncertainty_seconds=30,
        predicted_departure=None,
        departure_delay_seconds=None,
        departure_uncertainty_seconds=None,
        trip_schedule_relationship="SCHEDULED",
        stop_schedule_relationship="SCHEDULED",
        source_record_id="cd" * 32,
    )
    DbWriter(fake_connection).insert_trip_updates([row])

    [(sql, params)] = fake_connection.executed
    assert "INSERT INTO canonical.trip_updates" in sql
    # Migration 0025 natural key, COALESCEd exactly like the unique index —
    # replays (at-least-once delivery) write nothing new.
    assert (
        "ON CONFLICT (trip_id, feed_timestamp, source_record_id,\n"
        "             COALESCE(stop_sequence, -1), COALESCE(stop_id, '')) DO NOTHING"
    ) in sql
    assert params == (
        TIME, "T1", "R1", "bus-1", "S1", 5, TIME, 90, 30, None, None, None,
        "SCHEDULED", "SCHEDULED", "cd" * 32,
    )


def test_insert_trip_update_trip_level_row_binds_nulls(fake_connection) -> None:
    from headway_transform.trip_updates import CanonicalTripUpdate

    row = CanonicalTripUpdate(
        feed_timestamp=TIME,
        trip_id="T-gone",
        route_id=None,
        vehicle_id=None,
        stop_id=None,
        stop_sequence=None,
        predicted_arrival=None,
        arrival_delay_seconds=None,
        arrival_uncertainty_seconds=None,
        predicted_departure=None,
        departure_delay_seconds=None,
        departure_uncertainty_seconds=None,
        trip_schedule_relationship="CANCELED",
        stop_schedule_relationship=None,
        source_record_id="cd" * 32,
    )
    DbWriter(fake_connection).insert_trip_updates([row])

    [(_sql, params)] = fake_connection.executed
    assert params == (
        TIME, "T-gone", None, None, None, None, None, None, None, None,
        None, None, "CANCELED", None, "cd" * 32,
    )
