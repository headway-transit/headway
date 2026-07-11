"""Load-bearing tests: the tool's output_id builders must reproduce the
lineage.edges.output_id EXACTLY as each normalizer wrote it.

Each test feeds a tiny fixture through the REAL transform function
(headway_transform.*.normalize) and asserts that the builder, given only the
key columns the tool SELECTs from the canonical table, rebuilds the edge's
output_id byte-for-byte. If a normalizer's format ever changes, these tests
fail before the tool can delete rows while missing their edges — the
2026-07-10 stale-lineage failure mode."""

from __future__ import annotations

import base64
import io
import zipfile
from datetime import timedelta, timezone

from google.transit import gtfs_realtime_pb2

import replace
from headway_transform import gtfs_rt_positions, gtfs_static, tides_passenger_events
from headway_transform.envelope import Envelope

RECORD_ID = "ab" * 32  # content-addressed sha256 hex shape


# --- canonical.passenger_events -----------------------------------------

PASSENGER_CSV = (
    "passenger_event_id,service_date,event_timestamp,trip_stop_sequence,"
    "event_type,vehicle_id,trip_id_performed,event_count\n"
    "pe-0001,2026-07-09,2026-07-09T12:34:56Z,1,Passenger boarded,veh-9,trip-3,2\n"
    "pe-0002,2026-07-09,2026-07-09T12:34:56.789012Z,2,Passenger alighted,veh-9,trip-3,1\n"
).encode()


def _passenger_rows_and_edges():
    rows, edges, findings = tides_passenger_events.normalize(
        PASSENGER_CSV, RECORD_ID, "tides_simulated"
    )
    assert findings == [], "fixture must normalize cleanly"
    assert len(rows) == len(edges) == 2
    return rows, edges


def test_passenger_events_builder_matches_normalizer():
    rows, edges = _passenger_rows_and_edges()
    spec = replace.ALLOWLIST["canonical.passenger_events"]
    for row, edge in zip(rows, edges):
        built = spec.build_output_id(
            row.passenger_event_id, row.event_timestamp, row.source_record_id
        )
        assert built == edge.output_id
        assert spec.output_kind == edge.output_kind


def test_passenger_events_builder_handles_fractional_seconds():
    # Second fixture row carries microseconds; the rendering must match.
    rows, edges = _passenger_rows_and_edges()
    row, edge = rows[1], edges[1]
    assert row.event_timestamp.microsecond == 789012
    spec = replace.ALLOWLIST["canonical.passenger_events"]
    assert (
        spec.build_output_id(
            row.passenger_event_id, row.event_timestamp, row.source_record_id
        )
        == edge.output_id
    )


def test_passenger_events_builder_normalizes_session_timezone():
    # Postgres returns timestamptz in the session timezone, not necessarily
    # UTC. The same instant at +02:00 must rebuild the identical output_id.
    rows, edges = _passenger_rows_and_edges()
    row, edge = rows[0], edges[0]
    shifted = row.event_timestamp.astimezone(timezone(timedelta(hours=2)))
    spec = replace.ALLOWLIST["canonical.passenger_events"]
    assert (
        spec.build_output_id(row.passenger_event_id, shifted, row.source_record_id)
        == edge.output_id
    )


# --- canonical.vehicle_positions -----------------------------------------


def _vehicle_envelope() -> Envelope:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = 1783600000
    entity = feed.entity.add()
    entity.id = "e1"
    entity.vehicle.vehicle.id = "veh-42"
    entity.vehicle.position.latitude = 42.35
    entity.vehicle.position.longitude = -71.06
    entity.vehicle.timestamp = 1783600123
    entity.vehicle.trip.trip_id = "trip-7"
    entity.vehicle.trip.route_id = "route-1"
    payload = feed.SerializeToString()
    return Envelope(
        envelope_version=0,
        record_id=RECORD_ID,
        source="gtfs_rt",
        connector="headway-gtfs-rt",
        connector_version="0.1.0",
        fetched_at="2026-07-09T12:00:00Z",
        content_type="application/x-protobuf",
        payload_encoding="base64",
        payload=base64.b64encode(payload).decode("ascii"),
        parse_status="ok",
    )


def test_vehicle_positions_builder_matches_normalizer():
    rows, edges, findings = gtfs_rt_positions.normalize(_vehicle_envelope())
    assert findings == [], "fixture must normalize cleanly"
    assert len(rows) == len(edges) == 1
    row, edge = rows[0], edges[0]

    spec = replace.ALLOWLIST["canonical.vehicle_positions"]
    built = spec.build_output_id(row.vehicle_id, row.time, row.source_record_id)
    assert built == edge.output_id
    assert spec.output_kind == edge.output_kind


# --- canonical.routes / canonical.trips ----------------------------------


def _gtfs_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "routes.txt",
            "route_id,route_short_name,route_long_name,route_type\n"
            "route-1,1,One Line,3\n",
        )
        zf.writestr(
            "trips.txt",
            "trip_id,route_id,service_id,direction_id,block_id\n"
            "trip-7,route-1,svc-wk,0,blk-1\n",
        )
    return buffer.getvalue()


def test_routes_and_trips_builders_match_normalizer():
    routes, trips, edges, findings = gtfs_static.normalize(_gtfs_zip(), RECORD_ID)
    assert findings == [], "fixture must normalize cleanly"
    assert len(routes) == len(trips) == 1

    by_kind = {edge.output_kind: edge for edge in edges}
    route_spec = replace.ALLOWLIST["canonical.routes"]
    trip_spec = replace.ALLOWLIST["canonical.trips"]

    route_edge = by_kind[route_spec.output_kind]
    assert route_spec.build_output_id(routes[0].route_id) == route_edge.output_id

    trip_edge = by_kind[trip_spec.output_kind]
    assert trip_spec.build_output_id(trips[0].trip_id) == trip_edge.output_id
