"""Injectable DB writer for the transform service.

Takes any DB-API 2.0 connection (psycopg against Postgres/TimescaleDB in
production, a fake capturing (sql, params) in unit tests) and writes rows
matching the handoff-0001 schema exactly:

- raw.records registry row per envelope (immutable; redelivery of the same
  content-addressed record_id is a no-op via ON CONFLICT DO NOTHING — the
  record already landed, nothing is lost);
- canonical.routes / canonical.trips / canonical.agencies /
  canonical.service_calendars / canonical.service_calendar_dates upserts
  (static feeds supersede);
- canonical.trip_updates inserts (handoff 0014 / migration 0025), ON
  CONFLICT DO NOTHING on the natural key (trip_id, feed_timestamp,
  source_record_id, COALESCE(stop_sequence, -1), COALESCE(stop_id, ''))
  for the same replay reason — predictions land labeled as predictions;
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
- canonical.vehicle_telematics_days inserts (handoff 0028 / migration 0034),
  ON CONFLICT DO NOTHING on the unique key (vehicle_id, window_start,
  measure, basis, source_record_id) for the same replay reason. These rows
  are MEASURED VEHICLE MOVEMENT, not revenue miles/hours — no calculation
  reads them (see telematics_vehicle_days.py, "the honesty wall");
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

Batching (handoff 0032 evidence, 2026-07-30): every multi-row method issues
ONE ``cursor.executemany`` per call instead of one ``execute`` round trip
per row. Semantics are unchanged — under psycopg 3 executemany runs the
same statement once per parameter set (pipelined), so ON CONFLICT clauses
behave exactly as before and a failure on any row still aborts the caller's
transaction — but the round trips collapse. This is not an optimization
nicety: a whole GTFS static feed is one message, and at MBTA scale
(3.2M stop_times + a lineage edge per entity) the per-row round trips made
one message outlast Kafka's poll deadline, expelling the consumer and
stalling the LIVE pipeline from 2026-07-22 to 2026-07-30 (see
kafka_source.py).

No tenant_id anywhere (ADR-0004).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol

from .envelope import Envelope
from .gtfs_rt_positions import CanonicalVehiclePosition
from .gtfs_static import (
    CanonicalAgency,
    CanonicalRoute,
    CanonicalServiceCalendar,
    CanonicalServiceCalendarDate,
    CanonicalStop,
    CanonicalStopTime,
    CanonicalTrip,
)
from .dr_trips import CanonicalDrTrip
from .model import DQFinding, LineageEdge
from .telematics_vehicle_days import CanonicalTelematicsDay
from .tides_passenger_events import CanonicalPassengerEvent
from .trip_updates import CanonicalTripUpdate


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
INSERT INTO canonical.stops (stop_id, name, latitude, longitude, stop_code)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (stop_id) DO UPDATE
SET name      = EXCLUDED.name,
    latitude  = EXCLUDED.latitude,
    longitude = EXCLUDED.longitude,
    stop_code = EXCLUDED.stop_code
""".strip()

UPSERT_SERVICE_CALENDAR_SQL = """
INSERT INTO canonical.service_calendars
    (service_id, monday, tuesday, wednesday, thursday, friday, saturday,
     sunday, start_date, end_date)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (service_id) DO UPDATE
SET monday     = EXCLUDED.monday,
    tuesday    = EXCLUDED.tuesday,
    wednesday  = EXCLUDED.wednesday,
    thursday   = EXCLUDED.thursday,
    friday     = EXCLUDED.friday,
    saturday   = EXCLUDED.saturday,
    sunday     = EXCLUDED.sunday,
    start_date = EXCLUDED.start_date,
    end_date   = EXCLUDED.end_date
""".strip()

UPSERT_SERVICE_CALENDAR_DATE_SQL = """
INSERT INTO canonical.service_calendar_dates
    (service_id, service_date, exception_type)
VALUES (%s, %s, %s)
ON CONFLICT (service_id, service_date) DO UPDATE
SET exception_type = EXCLUDED.exception_type
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

UPSERT_AGENCY_SQL = """
INSERT INTO canonical.agencies (agency_id, name, timezone)
VALUES (%s, %s, %s)
ON CONFLICT (agency_id) DO UPDATE
SET name     = EXCLUDED.name,
    timezone = EXCLUDED.timezone
""".strip()

INSERT_TRIP_UPDATE_SQL = """
INSERT INTO canonical.trip_updates
    (feed_timestamp, trip_id, route_id, vehicle_id, stop_id, stop_sequence,
     predicted_arrival, arrival_delay_seconds, arrival_uncertainty_seconds,
     predicted_departure, departure_delay_seconds,
     departure_uncertainty_seconds,
     trip_schedule_relationship, stop_schedule_relationship,
     source_record_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (trip_id, feed_timestamp, source_record_id,
             COALESCE(stop_sequence, -1), COALESCE(stop_id, '')) DO NOTHING
""".strip()

INSERT_VEHICLE_POSITION_SQL = """
INSERT INTO canonical.vehicle_positions
    ("time", vehicle_id, trip_id, route_id,
     latitude, longitude, bearing, speed_mps, odometer_m, source_record_id,
     vehicle_label)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (vehicle_id, "time", source_record_id) DO NOTHING
""".strip()

INSERT_PASSENGER_EVENT_SQL = """
INSERT INTO canonical.passenger_events
    (event_timestamp, service_date, passenger_event_id, vehicle_id,
     trip_id, trip_stop_sequence, event_type, event_count,
     source, source_record_id, vendor_trip_ref, trip_resolution,
     revenue_classification)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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

INSERT_TELEMATICS_DAY_SQL = """
INSERT INTO canonical.vehicle_telematics_days
    (window_start, window_end, service_date, vehicle_id, vehicle_label,
     measure, basis, unit, reading_kind, value,
     first_reading_at, first_reading_value,
     last_reading_at, last_reading_value,
     sample_count, max_sample_gap_seconds, polled_at,
     source, source_record_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
        %s, %s)
ON CONFLICT (vehicle_id, window_start, measure, basis, source_record_id)
DO NOTHING
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

    def _execute_many(self, sql: str, rows: list[tuple]) -> None:
        """One executemany per batch — never one round trip per row (see the
        module docstring: per-row round trips stalled the live pipeline).
        An empty batch executes nothing at all."""
        if not rows:
            return
        cursor = self.connection.cursor()
        try:
            cursor.executemany(sql, rows)
        finally:
            close = getattr(cursor, "close", None)
            if close is not None:
                close()

    def insert_raw_record(self, envelope: Envelope) -> None:
        """Land the raw.records registry row for a validated envelope.

        ``raw.records`` records where the bytes are DURABLY held, not how
        they happened to ride the wire (handoff 0036). A base64 envelope
        that carries ``payload_ref`` — the connector landed the exact bytes
        in the object store before producing — therefore registers as
        ``payload_encoding='object_ref'`` with that key, exactly like every
        object_ref source. Only a base64 envelope with no durable address
        (none are produced by current connectors; legacy replays still
        exist on the wire) lands as broker-only ``base64``.
        """
        if envelope.payload_encoding == "object_ref":
            encoding, payload_ref = "object_ref", envelope.payload
        elif envelope.payload_ref:
            encoding, payload_ref = "object_ref", envelope.payload_ref
        else:
            encoding, payload_ref = envelope.payload_encoding, None
        self._execute(
            INSERT_RAW_RECORD_SQL,
            (
                envelope.record_id,
                envelope.source,
                envelope.connector,
                envelope.connector_version,
                envelope.content_type,
                encoding,
                payload_ref,
                envelope.fetched_at,
                envelope.parse_status,
                envelope.parse_error,
            ),
        )

    def upsert_routes(self, routes: Iterable[CanonicalRoute]) -> None:
        self._execute_many(
            UPSERT_ROUTE_SQL,
            [
                (route.route_id, route.short_name, route.long_name, route.mode)
                for route in routes
            ],
        )

    def upsert_trips(self, trips: Iterable[CanonicalTrip]) -> None:
        self._execute_many(
            UPSERT_TRIP_SQL,
            [
                (
                    trip.trip_id,
                    trip.route_id,
                    trip.service_id,
                    trip.direction_id,
                    trip.block_id,
                )
                for trip in trips
            ],
        )

    def upsert_stops(self, stops: Iterable[CanonicalStop]) -> None:
        self._execute_many(
            UPSERT_STOP_SQL,
            [
                (
                    stop.stop_id,
                    stop.name,
                    stop.latitude,
                    stop.longitude,
                    stop.stop_code,
                )
                for stop in stops
            ],
        )

    def upsert_service_calendars(
        self, calendars: Iterable[CanonicalServiceCalendar]
    ) -> None:
        self._execute_many(
            UPSERT_SERVICE_CALENDAR_SQL,
            [
                (
                    calendar.service_id,
                    calendar.monday,
                    calendar.tuesday,
                    calendar.wednesday,
                    calendar.thursday,
                    calendar.friday,
                    calendar.saturday,
                    calendar.sunday,
                    calendar.start_date,
                    calendar.end_date,
                )
                for calendar in calendars
            ],
        )

    def upsert_service_calendar_dates(
        self, rows: Iterable[CanonicalServiceCalendarDate]
    ) -> None:
        self._execute_many(
            UPSERT_SERVICE_CALENDAR_DATE_SQL,
            [
                (row.service_id, row.service_date, row.exception_type)
                for row in rows
            ],
        )

    def upsert_stop_times(self, rows: Iterable[CanonicalStopTime]) -> None:
        self._execute_many(
            UPSERT_STOP_TIME_SQL,
            [
                (
                    row.trip_id,
                    row.stop_id,
                    row.stop_sequence,
                    row.arrival_seconds,
                    row.departure_seconds,
                    row.shape_dist_traveled,
                )
                for row in rows
            ],
        )

    def upsert_agencies(self, agencies: Iterable[CanonicalAgency]) -> None:
        self._execute_many(
            UPSERT_AGENCY_SQL,
            [
                (agency.agency_id, agency.name, agency.timezone)
                for agency in agencies
            ],
        )

    def insert_trip_updates(self, rows: Iterable[CanonicalTripUpdate]) -> None:
        self._execute_many(
            INSERT_TRIP_UPDATE_SQL,
            [
                (
                    row.feed_timestamp,
                    row.trip_id,
                    row.route_id,
                    row.vehicle_id,
                    row.stop_id,
                    row.stop_sequence,
                    row.predicted_arrival,
                    row.arrival_delay_seconds,
                    row.arrival_uncertainty_seconds,
                    row.predicted_departure,
                    row.departure_delay_seconds,
                    row.departure_uncertainty_seconds,
                    row.trip_schedule_relationship,
                    row.stop_schedule_relationship,
                    row.source_record_id,
                )
                for row in rows
            ],
        )

    def insert_vehicle_positions(
        self, rows: Iterable[CanonicalVehiclePosition]
    ) -> None:
        self._execute_many(
            INSERT_VEHICLE_POSITION_SQL,
            [
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
                    row.vehicle_label,
                )
                for row in rows
            ],
        )

    def insert_passenger_events(
        self, rows: Iterable[CanonicalPassengerEvent]
    ) -> None:
        self._execute_many(
            INSERT_PASSENGER_EVENT_SQL,
            [
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
                    row.vendor_trip_ref,
                    row.trip_resolution,
                    row.revenue_classification,
                )
                for row in rows
            ],
        )

    def insert_dr_trips(self, rows: Iterable[CanonicalDrTrip]) -> None:
        self._execute_many(
            INSERT_DR_TRIP_SQL,
            [
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
                )
                for row in rows
            ],
        )

    def insert_telematics_days(
        self, rows: Iterable[CanonicalTelematicsDay]
    ) -> None:
        self._execute_many(
            INSERT_TELEMATICS_DAY_SQL,
            [
                (
                    row.window_start,
                    row.window_end,
                    row.service_date,
                    row.vehicle_id,
                    row.vehicle_label,
                    row.measure,
                    row.basis,
                    row.unit,
                    row.reading_kind,
                    row.value,
                    row.first_reading_at,
                    row.first_reading_value,
                    row.last_reading_at,
                    row.last_reading_value,
                    row.sample_count,
                    row.max_sample_gap_seconds,
                    row.polled_at,
                    row.source,
                    row.source_record_id,
                )
                for row in rows
            ],
        )

    def insert_lineage_edges(self, edges: Iterable[LineageEdge]) -> None:
        self._execute_many(
            INSERT_LINEAGE_EDGE_SQL,
            [
                (
                    edge.output_kind,
                    edge.output_id,
                    edge.transform_name,
                    edge.transform_version,
                    edge.input_kind,
                    edge.input_id,
                )
                for edge in edges
            ],
        )

    def insert_dq_issues(self, findings: Iterable[DQFinding]) -> None:
        self._execute_many(
            INSERT_DQ_ISSUE_SQL,
            [
                (
                    finding.issue_type,
                    finding.severity,
                    finding.title,
                    finding.description,
                    finding.source_record_ids,
                    finding.transform_dedupe_key(),
                )
                for finding in findings
            ],
        )
