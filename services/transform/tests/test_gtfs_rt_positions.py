"""GTFS-RT vehicle-positions normalizer: real FeedMessages built in-test."""

from __future__ import annotations

from datetime import datetime, timezone

from google.transit import gtfs_realtime_pb2

from headway_transform.envelope import validate_envelope
from headway_transform.gtfs_rt_positions import (
    TRANSFORM_NAME,
    TRANSFORM_VERSION,
    normalize,
)

from conftest import make_envelope_dict, sha256_hex

HEADER_TS = 1_760_000_000
ENTITY_TS = 1_760_000_123


def build_feed(*, header_timestamp: int | None = HEADER_TS) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    if header_timestamp is not None:
        feed.header.timestamp = header_timestamp
    return feed


def add_vehicle(
    feed: gtfs_realtime_pb2.FeedMessage,
    entity_id: str,
    vehicle_id: str,
    *,
    timestamp: int | None = ENTITY_TS,
    trip_id: str | None = "trip-1",
    route_id: str | None = "route-9",
    lat: float = 44.98,
    lon: float = -93.27,
    bearing: float | None = 90.0,
    speed: float | None = 11.5,
    odometer: float | None = 120345.0,
) -> None:
    entity = feed.entity.add()
    entity.id = entity_id
    vp = entity.vehicle
    vp.vehicle.id = vehicle_id
    vp.position.latitude = lat
    vp.position.longitude = lon
    if bearing is not None:
        vp.position.bearing = bearing
    if speed is not None:
        vp.position.speed = speed
    if odometer is not None:
        vp.position.odometer = odometer
    if timestamp is not None:
        vp.timestamp = timestamp
    if trip_id is not None:
        vp.trip.trip_id = trip_id
    if route_id is not None:
        vp.trip.route_id = route_id


def envelope_for(feed: gtfs_realtime_pb2.FeedMessage):
    return validate_envelope(make_envelope_dict(feed.SerializeToString()))


def test_normalizes_entities_with_one_lineage_edge_per_row() -> None:
    feed = build_feed()
    add_vehicle(feed, "e1", "bus-101")
    add_vehicle(feed, "e2", "bus-202", trip_id=None, route_id=None,
                bearing=None, speed=None, odometer=None)
    envelope = envelope_for(feed)

    rows, edges, findings = normalize(envelope)

    assert len(rows) == 2
    assert len(edges) == 2  # exactly one edge per canonical row
    assert findings == []

    row = rows[0]
    assert row.vehicle_id == "bus-101"
    assert row.time == datetime.fromtimestamp(ENTITY_TS, tz=timezone.utc)
    assert row.trip_id == "trip-1"
    assert row.route_id == "route-9"
    assert abs(row.latitude - 44.98) < 1e-4
    assert abs(row.longitude - -93.27) < 1e-4
    assert abs(row.bearing - 90.0) < 1e-4
    assert abs(row.speed_mps - 11.5) < 1e-4
    assert abs(row.odometer_m - 120345.0) < 1e-3
    assert row.source_record_id == envelope.record_id

    # Unassigned position stays unassigned — never guessed.
    unassigned = rows[1]
    assert unassigned.trip_id is None
    assert unassigned.route_id is None
    assert unassigned.bearing is None
    assert unassigned.speed_mps is None
    assert unassigned.odometer_m is None

    for row, edge in zip(rows, edges):
        assert edge.output_kind == "canonical.vehicle_positions"
        assert edge.output_id == row.output_id
        assert edge.output_id.endswith(f"|{envelope.record_id}")
        assert "|" in edge.output_id and "Z|" in edge.output_id
        assert edge.transform_name == TRANSFORM_NAME == "normalize_gtfs_rt_positions"
        assert edge.transform_version == TRANSFORM_VERSION == "0.1.0"
        assert edge.input_kind == "raw.records"
        assert edge.input_id == envelope.record_id


def test_output_id_format_is_vehicle_time_record() -> None:
    feed = build_feed()
    add_vehicle(feed, "e1", "bus-7")
    envelope = envelope_for(feed)
    rows, edges, _ = normalize(envelope)
    expected_time = (
        datetime.fromtimestamp(ENTITY_TS, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )
    assert edges[0].output_id == f"bus-7|{expected_time}|{envelope.record_id}"


def test_missing_entity_timestamp_falls_back_to_header_and_is_noted() -> None:
    feed = build_feed(header_timestamp=HEADER_TS)
    add_vehicle(feed, "e1", "bus-1", timestamp=None)
    rows, edges, findings = normalize(envelope_for(feed))

    assert len(rows) == 1
    assert rows[0].time == datetime.fromtimestamp(HEADER_TS, tz=timezone.utc)
    assert len(edges) == 1
    noted = [f for f in findings if f.issue_type == "missing_entity_timestamp"]
    assert len(noted) == 1  # the fallback is noted, per fail-loudly
    assert noted[0].severity == "info"
    assert noted[0].source_record_ids


def test_no_timestamp_anywhere_is_a_finding_not_a_guess() -> None:
    feed = build_feed(header_timestamp=None)
    add_vehicle(feed, "e1", "bus-1", timestamp=None)
    envelope = envelope_for(feed)
    rows, edges, findings = normalize(envelope)

    assert rows == []
    assert edges == []
    assert len(findings) == 1
    assert findings[0].issue_type == "malformed_entity"
    assert findings[0].source_record_ids == [envelope.record_id]


def test_entity_without_vehicle_id_is_malformed_not_dropped() -> None:
    feed = build_feed()
    entity = feed.entity.add()
    entity.id = "no-vehicle-id"
    entity.vehicle.position.latitude = 1.0
    entity.vehicle.position.longitude = 2.0
    entity.vehicle.timestamp = ENTITY_TS
    add_vehicle(feed, "good", "bus-ok")

    envelope = envelope_for(feed)
    rows, edges, findings = normalize(envelope)

    assert [r.vehicle_id for r in rows] == ["bus-ok"]
    assert len(edges) == 1
    malformed = [f for f in findings if f.issue_type == "malformed_entity"]
    assert len(malformed) == 1
    assert malformed[0].source_record_ids == [envelope.record_id]


def test_undecodable_payload_is_a_finding_zero_rows_no_exception() -> None:
    garbage = b"\xff\xfe definitely not a FeedMessage protobuf \x00\x01"
    envelope = validate_envelope(make_envelope_dict(garbage))

    rows, edges, findings = normalize(envelope)  # must NOT raise

    assert rows == []
    assert edges == []
    assert len(findings) == 1
    assert findings[0].issue_type == "undecodable_payload"
    assert findings[0].severity == "blocking"
    assert findings[0].source_record_ids == [sha256_hex(garbage)]


def test_connector_flagged_malformed_payload_is_quarantined_not_parsed() -> None:
    payload = b"whatever"
    envelope = validate_envelope(
        make_envelope_dict(
            payload, parse_status="malformed", parse_error="connector saw truncation"
        )
    )
    rows, edges, findings = normalize(envelope)
    assert rows == [] and edges == []
    assert findings[0].issue_type == "undecodable_payload"
    assert "connector saw truncation" in findings[0].description
