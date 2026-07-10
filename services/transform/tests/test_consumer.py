"""Consumer loop: routing, quarantine of poison messages, loop survival."""

from __future__ import annotations

import json

from google.transit import gtfs_realtime_pb2

from headway_transform.consumer import run_loop
from headway_transform.writer import DbWriter

from conftest import FakeConnection, envelope_json, make_envelope_dict

TOPIC_VP = "raw.gtfs_rt.vehicle_positions"


class FakeMessageSource:
    def __init__(self, messages: list[tuple[str, bytes | None, bytes]]) -> None:
        self._messages = list(messages)

    def poll(self):
        if not self._messages:
            return None
        return self._messages.pop(0)


def build_vp_payload() -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1_760_000_000
    entity = feed.entity.add()
    entity.id = "e1"
    entity.vehicle.vehicle.id = "bus-1"
    entity.vehicle.position.latitude = 44.9
    entity.vehicle.position.longitude = -93.2
    entity.vehicle.timestamp = 1_760_000_050
    return feed.SerializeToString()


def test_good_message_lands_raw_record_rows_and_edges(fake_connection) -> None:
    source = FakeMessageSource([(TOPIC_VP, b"key", envelope_json(build_vp_payload()))])
    processed = run_loop(source, DbWriter(fake_connection))

    assert processed == 1
    assert len(fake_connection.sql_for("raw.records")) == 1
    assert len(fake_connection.sql_for("canonical.vehicle_positions")) == 1
    assert len(fake_connection.sql_for("lineage.edges")) == 1
    assert fake_connection.sql_for("dq.issues") == []
    assert fake_connection.commits == 1


def test_invalid_envelope_quarantined_as_dq_issue_loop_continues() -> None:
    conn = FakeConnection()
    bad = json.dumps({"envelope_version": 0, "record_id": "nope"}).encode()
    good = envelope_json(build_vp_payload())
    source = FakeMessageSource([(TOPIC_VP, None, bad), (TOPIC_VP, None, good)])

    processed = run_loop(source, DbWriter(conn))

    assert processed == 2  # poison message did not kill the loop
    dq = conn.sql_for("dq.issues")
    assert len(dq) == 1
    assert dq[0][1][0] == "invalid_envelope"
    # The good message still normalized fully.
    assert len(conn.sql_for("canonical.vehicle_positions")) == 1


def test_invalid_envelope_with_registry_fields_still_lands_raw_record() -> None:
    conn = FakeConnection()
    # Valid registry fields but a contract violation (unknown extra property).
    doc = make_envelope_dict(b"some-bytes")
    doc["tenant_id"] = "forbidden"
    source = FakeMessageSource([(TOPIC_VP, None, json.dumps(doc).encode())])

    run_loop(source, DbWriter(conn))

    raw = conn.sql_for("raw.records")
    assert len(raw) == 1
    assert raw[0][1][8] == "malformed"  # parse_status
    dq = conn.sql_for("dq.issues")
    assert dq[0][1][0] == "invalid_envelope"
    assert dq[0][1][4] == [doc["record_id"]]  # source_record_ids anchors it


def test_non_json_message_quarantined_without_crash() -> None:
    conn = FakeConnection()
    source = FakeMessageSource([(TOPIC_VP, None, b"\x00garbage not json")])
    processed = run_loop(source, DbWriter(conn))
    assert processed == 1
    dq = conn.sql_for("dq.issues")
    assert len(dq) == 1
    assert dq[0][1][0] == "invalid_envelope"
    assert conn.sql_for("raw.records") == []  # nothing to land, but issue raised


def test_undecodable_protobuf_payload_becomes_dq_issue() -> None:
    conn = FakeConnection()
    source = FakeMessageSource(
        [(TOPIC_VP, None, envelope_json(b"not a protobuf"))]
    )
    run_loop(source, DbWriter(conn))
    assert len(conn.sql_for("raw.records")) == 1  # raw record always lands
    assert conn.sql_for("canonical.vehicle_positions") == []
    dq = conn.sql_for("dq.issues")
    assert len(dq) == 1
    assert dq[0][1][0] == "undecodable_payload"


def test_unhandled_topic_lands_record_and_dq_issue() -> None:
    conn = FakeConnection()
    msg = envelope_json(b"payload", source="gtfs_rt", content_type="application/x-protobuf")
    source = FakeMessageSource([("raw.gtfs_rt.alerts", None, msg)])
    run_loop(source, DbWriter(conn))
    assert len(conn.sql_for("raw.records")) == 1
    dq = conn.sql_for("dq.issues")
    assert dq[0][1][0] == "unhandled_topic"


def test_gtfs_static_object_ref_without_fetcher_is_blocking_issue() -> None:
    conn = FakeConnection()
    doc = make_envelope_dict(
        b"zipbytes",
        source="gtfs_static",
        connector="headway-gtfs-static",
        content_type="application/zip",
        payload_encoding="object_ref",
        payload="objects/feed.zip",
    )
    source = FakeMessageSource(
        [("raw.gtfs_static.feed", None, json.dumps(doc).encode())]
    )
    run_loop(source, DbWriter(conn))
    dq = conn.sql_for("dq.issues")
    assert dq[0][1][0] == "object_ref_unavailable"
    assert dq[0][1][1] == "blocking"


def test_gtfs_static_with_fetcher_normalizes_routes_and_trips() -> None:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("routes.txt", "route_id,route_type\nR1,3\n")
        zf.writestr("trips.txt", "trip_id,route_id,service_id\nT1,R1,WKDY\n")
    zip_bytes = buf.getvalue()

    conn = FakeConnection()
    doc = make_envelope_dict(
        zip_bytes,
        source="gtfs_static",
        connector="headway-gtfs-static",
        content_type="application/zip",
        payload_encoding="object_ref",
        payload="objects/feed.zip",
    )
    # record_id in conftest is the sha of the raw bytes; keep it consistent.
    source = FakeMessageSource(
        [("raw.gtfs_static.feed", None, json.dumps(doc).encode())]
    )
    fetched: list[str] = []

    def fetcher(key: str) -> bytes:
        fetched.append(key)
        return zip_bytes

    run_loop(source, DbWriter(conn), object_fetcher=fetcher)

    assert fetched == ["objects/feed.zip"]
    assert len(conn.sql_for("canonical.routes")) == 1
    assert len(conn.sql_for("canonical.trips")) == 1
    assert len(conn.sql_for("lineage.edges")) == 2  # one per canonical row


def test_tides_passenger_events_routed_with_fetcher_normalizes_rows() -> None:
    csv_bytes = (
        "passenger_event_id,service_date,event_timestamp,trip_id_performed,"
        "trip_stop_sequence,event_type,vehicle_id,event_count\n"
        "PE-1,2026-07-08,2026-07-08T12:00:00Z,T1,1,Passenger boarded,bus-1,2\n"
        "PE-2,2026-07-08,2026-07-08T12:01:00Z,T1,2,Passenger alighted,bus-1,1\n"
    ).encode("utf-8")

    conn = FakeConnection()
    doc = make_envelope_dict(
        csv_bytes,
        source="tides_simulated",
        connector="headway-tides",
        content_type="text/csv",
        payload_encoding="object_ref",
        payload="objects/passenger_events.csv",
    )
    source = FakeMessageSource(
        [("raw.tides.passenger_events", None, json.dumps(doc).encode())]
    )
    fetched: list[str] = []

    def fetcher(key: str) -> bytes:
        fetched.append(key)
        return csv_bytes

    run_loop(source, DbWriter(conn), object_fetcher=fetcher)

    assert fetched == ["objects/passenger_events.csv"]
    assert len(conn.sql_for("raw.records")) == 1
    events = conn.sql_for("canonical.passenger_events")
    assert len(events) == 2
    # Envelope source carried verbatim onto every row (handoff 0005 rule).
    assert [params[8] for _sql, params in events] == [
        "tides_simulated",
        "tides_simulated",
    ]
    assert len(conn.sql_for("lineage.edges")) == 2  # one per canonical row
    assert conn.sql_for("dq.issues") == []


def test_tides_passenger_events_object_ref_without_fetcher_is_blocking_issue() -> None:
    conn = FakeConnection()
    doc = make_envelope_dict(
        b"csv-bytes",
        source="tides",
        connector="headway-tides",
        content_type="text/csv",
        payload_encoding="object_ref",
        payload="objects/passenger_events.csv",
    )
    source = FakeMessageSource(
        [("raw.tides.passenger_events", None, json.dumps(doc).encode())]
    )
    run_loop(source, DbWriter(conn))
    dq = conn.sql_for("dq.issues")
    assert dq[0][1][0] == "object_ref_unavailable"
    assert dq[0][1][1] == "blocking"
    assert conn.sql_for("canonical.passenger_events") == []


def test_writer_failure_rolls_back_and_quarantines_then_continues() -> None:
    conn = FakeConnection(fail_on_sql_containing="canonical.vehicle_positions")
    good = envelope_json(build_vp_payload())
    source = FakeMessageSource([(TOPIC_VP, None, good), (TOPIC_VP, None, good)])

    processed = run_loop(source, DbWriter(conn))

    assert processed == 2  # loop survived the failing writes
    assert conn.rollbacks == 2
    dq = conn.sql_for("dq.issues")
    assert len(dq) == 2
    assert all(params[0] == "transform_failure" for _sql, params in dq)
    assert all(params[1] == "blocking" for _sql, params in dq)
