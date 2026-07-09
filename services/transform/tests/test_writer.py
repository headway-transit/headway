"""DbWriter unit tests with a fake DB-API connection capturing (sql, params)."""

from __future__ import annotations

from datetime import datetime, timezone

from headway_transform.envelope import validate_envelope
from headway_transform.gtfs_rt_positions import CanonicalVehiclePosition
from headway_transform.gtfs_static import CanonicalRoute, CanonicalTrip
from headway_transform.model import DQFinding, LineageEdge
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
    writer.upsert_trips([CanonicalTrip("T1", "R1", "WKDY", 0)])

    route_sql, route_params = fake_connection.sql_for("canonical.routes")[0]
    assert "ON CONFLICT (route_id) DO UPDATE" in route_sql
    assert route_params == ("R1", "5", "Fifth St", "bus")

    trip_sql, trip_params = fake_connection.sql_for("canonical.trips")[0]
    assert "ON CONFLICT (trip_id) DO UPDATE" in trip_sql
    assert trip_params == ("T1", "R1", "WKDY", 0)


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
    assert params == ("malformed_entity", "warning", "t", "d", ["ef" * 32])
