"""Injectable DB writer for the transform service.

Takes any DB-API 2.0 connection (psycopg against Postgres/TimescaleDB in
production, a fake capturing (sql, params) in unit tests) and writes rows
matching the handoff-0001 schema exactly:

- raw.records registry row per envelope (immutable; redelivery of the same
  content-addressed record_id is a no-op via ON CONFLICT DO NOTHING — the
  record already landed, nothing is lost);
- canonical.routes / canonical.trips upserts (static feeds supersede);
- canonical.vehicle_positions inserts, ON CONFLICT DO NOTHING on the unique
  key (vehicle_id, time, source_record_id) — at-least-once Kafka delivery
  makes exact replays of the same content-addressed record normal, and an
  identical row is not new data;
- canonical.passenger_events inserts (handoff 0005 / migration 0012), ON
  CONFLICT DO NOTHING on the unique key (passenger_event_id,
  event_timestamp, source_record_id) for the same replay reason;
- canonical.dr_trips inserts (handoff 0013 / migration 0021), ON CONFLICT
  DO NOTHING on the unique key (dr_trip_id, pickup_timestamp,
  source_record_id) for the same replay reason;
- lineage.edges inserts, ON CONFLICT DO NOTHING on the full natural key
  (output_kind, output_id, transform_name, transform_version, input_kind,
  input_id) — unique per migration 0023, so a replay adds zero duplicate
  edges (2026-07-13 hardening pass);
- dq.issues inserts carrying the transform-scoped dedupe_key (migration
  0023, UNIQUE WHERE NOT NULL + ON CONFLICT DO NOTHING): a replay's
  byte-identical findings write nothing new, while human-/AI-created
  issues (dedupe_key NULL, written elsewhere) are never deduplicated.

Transaction boundaries belong to the caller (the consumer commits per
message); this class only executes statements.

No tenant_id anywhere (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .envelope import Envelope
from .gtfs_rt_positions import CanonicalVehiclePosition
from .gtfs_static import (
    CanonicalRoute,
    CanonicalStop,
    CanonicalStopTime,
    CanonicalTrip,
)
from .dr_trips import CanonicalDrTrip
from .model import DQFinding, LineageEdge
from .tides_passenger_events import CanonicalPassengerEvent


class Connection(Protocol):
    """The slice of DB-API 2.0 this writer needs."""

    def cursor(self) -> Any: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...


INSERT_RAW_RECORD_SQL = """
INSERT INTO raw.records
    (record_id, source, connector, connector_version,
     content_type, payload_encoding, payload_ref,
     fetched_at, parse_status, parse_error)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (record_id) DO NOTHING
""".strip()

UPSERT_ROUTE_SQL = """
INSERT INTO canonical.routes (route_id, short_name, long_name, mode)
VALUES (%s, %s, %s, %s)
ON CONFLICT (route_id) DO UPDATE
SET short_name = EXCLUDED.short_name,
    long_name  = EXCLUDED.long_name,
    mode       = EXCLUDED.mode
""".strip()

UPSERT_TRIP_SQL = """
INSERT INTO canonical.trips (trip_id, route_id, service_id, direction_id, block_id)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (trip_id) DO UPDATE
SET route_id     = EXCLUDED.route_id,
    service_id   = EXCLUDED.service_id,
    direction_id = EXCLUDED.direction_id,
    block_id     = EXCLUDED.block_id
""".strip()

UPSERT_STOP_SQL = """
INSERT INTO canonical.stops (stop_id, name, latitude, longitude)
VALUES (%s, %s, %s, %s)
ON CONFLICT (stop_id) DO UPDATE
SET name      = EXCLUDED.name,
    latitude  = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude
""".strip()

UPSERT_STOP_TIME_SQL = """
INSERT INTO canonical.stop_times
    (trip_id, stop_id, stop_sequence,
     arrival_seconds, departure_seconds, shape_dist_traveled)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (trip_id, stop_sequence) DO UPDATE
SET stop_id             = EXCLUDED.stop_id,
    arrival_seconds     = EXCLUDED.arrival_seconds,
    departure_seconds   = EXCLUDED.departure_seconds,
    shape_dist_traveled = EXCLUDED.shape_dist_traveled
""".strip()

INSERT_VEHICLE_POSITION_SQL = """
INSERT INTO canonical.vehicle_positions
    ("time", vehicle_id, trip_id, route_id,
     latitude, longitude, bearing, speed_mps, odometer_m, source_record_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (vehicle_id, "time", source_record_id) DO NOTHING
""".strip()

INSERT_PASSENGER_EVENT_SQL = """
INSERT INTO canonical.passenger_events
    (event_timestamp, service_date, passenger_event_id, vehicle_id,
     trip_id, trip_stop_sequence, event_type, event_count,
     source, source_record_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (passenger_event_id, event_timestamp, source_record_id) DO NOTHING
""".strip()

INSERT_DR_TRIP_SQL = """
INSERT INTO canonical.dr_trips
    (pickup_timestamp, service_date, dr_trip_id, vehicle_id, tos,
     request_timestamp, dispatch_timestamp, dropoff_timestamp,
     pickup_lat, pickup_lon, dropoff_lat, dropoff_lon,
     onboard_miles, distance_source,
     pickup_odometer_miles, dropoff_odometer_miles,
     riders, attendants_companions, ada_related, sponsored, sponsor,
     no_show, interruption_after, driver_shift_id, dispatching_point_id,
     source, source_record_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (dr_trip_id, pickup_timestamp, source_record_id) DO NOTHING
""".strip()

INSERT_LINEAGE_EDGE_SQL = """
INSERT INTO lineage.edges
    (output_kind, output_id, transform_name, transform_version,
     input_kind, input_id)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (output_kind, output_id, transform_name, transform_version,
             input_kind, input_id) DO NOTHING
""".strip()

INSERT_DQ_ISSUE_SQL = """
INSERT INTO dq.issues
    (issue_type, severity, title, description, source_record_ids, dedupe_key)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
""".strip()


class DbWriter:
    """Writes normalizer output through an injected DB-API connection."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def _execute(self, sql: str, params: tuple) -> None:
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
        finally:
            close = getattr(cursor, "close", None)
            if close is not None:
                close()

    def insert_raw_record(self, envelope: Envelope) -> None:
        """Land the raw.records registry row for a validated envelope."""
        payload_ref = (
            envelope.payload if envelope.payload_encoding == "object_ref" else None
        )
        self._execute(
            INSERT_RAW_RECORD_SQL,
            (
                envelope.record_id,
                envelope.source,
                envelope.connector,
                envelope.connector_version,
                envelope.content_type,
                envelope.payload_encoding,
                payload_ref,
                envelope.fetched_at,
                envelope.parse_status,
                envelope.parse_error,
            ),
        )

    def upsert_routes(self, routes: Iterable[CanonicalRoute]) -> None:
        for route in routes:
            self._execute(
                UPSERT_ROUTE_SQL,
                (route.route_id, route.short_name, route.long_name, route.mode),
            )

    def upsert_trips(self, trips: Iterable[CanonicalTrip]) -> None:
        for trip in trips:
            self._execute(
                UPSERT_TRIP_SQL,
                (
                    trip.trip_id,
                    trip.route_id,
                    trip.service_id,
                    trip.direction_id,
                    trip.block_id,
                ),
            )

    def upsert_stops(self, stops: Iterable[CanonicalStop]) -> None:
        for stop in stops:
            self._execute(
                UPSERT_STOP_SQL,
                (stop.stop_id, stop.name, stop.latitude, stop.longitude),
            )

    def upsert_stop_times(self, rows: Iterable[CanonicalStopTime]) -> None:
        for row in rows:
            self._execute(
                UPSERT_STOP_TIME_SQL,
                (
                    row.trip_id,
                    row.stop_id,
                    row.stop_sequence,
                    row.arrival_seconds,
                    row.departure_seconds,
                    row.shape_dist_traveled,
                ),
            )

    def insert_vehicle_positions(
        self, rows: Iterable[CanonicalVehiclePosition]
    ) -> None:
        for row in rows:
            self._execute(
                INSERT_VEHICLE_POSITION_SQL,
                (
                    row.time,
                    row.vehicle_id,
                    row.trip_id,
                    row.route_id,
                    row.latitude,
                    row.longitude,
                    row.bearing,
                    row.speed_mps,
                    row.odometer_m,
                    row.source_record_id,
                ),
            )

    def insert_passenger_events(
        self, rows: Iterable[CanonicalPassengerEvent]
    ) -> None:
        for row in rows:
            self._execute(
                INSERT_PASSENGER_EVENT_SQL,
                (
                    row.event_timestamp,
                    row.service_date,
                    row.passenger_event_id,
                    row.vehicle_id,
                    row.trip_id,
                    row.trip_stop_sequence,
                    row.event_type,
                    row.event_count,
                    row.source,
                    row.source_record_id,
                ),
            )

    def insert_dr_trips(self, rows: Iterable[CanonicalDrTrip]) -> None:
        for row in rows:
            self._execute(
                INSERT_DR_TRIP_SQL,
                (
                    row.pickup_timestamp,
                    row.service_date,
                    row.dr_trip_id,
                    row.vehicle_id,
                    row.tos,
                    row.request_timestamp,
                    row.dispatch_timestamp,
                    row.dropoff_timestamp,
                    row.pickup_lat,
                    row.pickup_lon,
                    row.dropoff_lat,
                    row.dropoff_lon,
                    row.onboard_miles,
                    row.distance_source,
                    row.pickup_odometer_miles,
                    row.dropoff_odometer_miles,
                    row.riders,
                    row.attendants_companions,
                    row.ada_related,
                    row.sponsored,
                    row.sponsor,
                    row.no_show,
                    row.interruption_after,
                    row.driver_shift_id,
                    row.dispatching_point_id,
                    row.source,
                    row.source_record_id,
                ),
            )

    def insert_lineage_edges(self, edges: Iterable[LineageEdge]) -> None:
        for edge in edges:
            self._execute(
                INSERT_LINEAGE_EDGE_SQL,
                (
                    edge.output_kind,
                    edge.output_id,
                    edge.transform_name,
                    edge.transform_version,
                    edge.input_kind,
                    edge.input_id,
                ),
            )

    def insert_dq_issues(self, findings: Iterable[DQFinding]) -> None:
        for finding in findings:
            self._execute(
                INSERT_DQ_ISSUE_SQL,
                (
                    finding.issue_type,
                    finding.severity,
                    finding.title,
                    finding.description,
                    finding.source_record_ids,
                    finding.transform_dedupe_key(),
                ),
            )
