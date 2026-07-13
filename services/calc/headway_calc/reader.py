"""Injectable readers for canonical.vehicle_positions (handoff 0001, plus the
canonical.trips.block_id join — handoff 0003, migration 0011, and the
canonical.routes.mode join — handoff 0009) and canonical.passenger_events
(handoff 0005, migration 0012; mode joined per handoff 0009).

The read side of the calc loop: SELECT canonical rows for one reporting
period and map them onto the frozen VehiclePosition dataclass. Takes any
DB-API 2.0 connection (paramstyle 'format'/'pyformat', i.e. %s placeholders —
psycopg-compatible); unit-testable with a fake connection, no live database
required. Stdlib only — this module never imports a driver.

block_id join (handoff 0003): each position carries (vehicle_id, trip_id,
block_id) so vrh_v0 0.3.0 can group a vehicle's trips by GTFS block. The join
is a LEFT JOIN — an unassigned position (trip_id NULL), an unknown trip, or a
feed omitting the optional block_id field all yield block_id NULL (the calc
then falls back to per-trip grouping and documents the undercount), never a
dropped row.

mode join (handoff 0009): each position AND each passenger event carries the
trip's route mode (canonical.routes.mode, LEFT JOIN canonical.trips →
canonical.routes). An unassigned row (trip_id NULL), an unknown trip, or an
unknown route yields mode NULL — mode-scoped computations bucket NULL mode as
'unknown' and surface the unknown-mode share as an info finding; a row is
NEVER dropped and a mode is NEVER guessed.

Boundary convention (documented, load-bearing): the period is HALF-OPEN in
UTC — ``time >= period_start 00:00:00 UTC AND time < period_end 00:00:00
UTC``, i.e. ``[period_start, period_end)``. Half-open periods tile a calendar
with no double-counted and no dropped instant: a June run is
``[2026-06-01, 2026-07-01)`` and the July run picks up exactly where it ends.
The DATE bounds are converted to timezone-aware UTC datetimes in Python
BEFORE binding, so the comparison against the TIMESTAMPTZ column never
depends on the database session time zone.

Ordering is deterministic and delegated to SQL: ``ORDER BY p.vehicle_id,
p.time, p.source_record_id`` (the same total order the calculations' internal
sort uses), so the same table state always yields the same row sequence.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from headway_calc.types import (
    DrTrip,
    OpsScheduledStop,
    PassengerEvent,
    StopTime,
    VehiclePosition,
)

#: Column names and order per handoff 0001 (canonical.vehicle_positions) plus
#: canonical.trips.block_id (handoff 0003, migration 0011) and
#: canonical.routes.mode (handoff 0009) via LEFT JOINs.
_SELECT_POSITIONS_SQL = (
    "SELECT p.time, p.vehicle_id, p.trip_id, p.latitude, p.longitude, "
    "p.source_record_id, t.block_id, r.mode "
    "FROM canonical.vehicle_positions AS p "
    "LEFT JOIN canonical.trips AS t ON t.trip_id = p.trip_id "
    "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id "
    "WHERE p.time >= %s AND p.time < %s "
    "ORDER BY p.vehicle_id, p.time, p.source_record_id"
)


#: Column names and order per the handoff-0005 canonical.passenger_events
#: contract (migration 0012) plus canonical.routes.mode (handoff 0009) via
#: LEFT JOINs. Deterministic ORDER BY: event_timestamp, then
#: passenger_event_id, then source_record_id (the same total order
#: headway_calc.upt sorts by internally).
_SELECT_PASSENGER_EVENTS_SQL = (
    "SELECT e.event_timestamp, e.service_date, e.passenger_event_id, "
    "e.vehicle_id, e.trip_id, e.trip_stop_sequence, e.event_type, "
    "e.event_count, e.source, e.source_record_id, r.mode "
    "FROM canonical.passenger_events AS e "
    "LEFT JOIN canonical.trips AS t ON t.trip_id = e.trip_id "
    "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id "
    "WHERE e.event_timestamp >= %s AND e.event_timestamp < %s "
    "ORDER BY e.event_timestamp, e.passenger_event_id, e.source_record_id"
)

#: Operated trips for the upt_v0 missing-trip rule (handoff 0005): the
#: distinct trips actually observed operating in canonical.vehicle_positions
#: over the period. Deterministic ORDER BY trip_id.
_SELECT_OPERATED_TRIP_IDS_SQL = (
    "SELECT DISTINCT trip_id FROM canonical.vehicle_positions "
    "WHERE trip_id IS NOT NULL AND time >= %s AND time < %s "
    "ORDER BY trip_id"
)


#: Stop geometry for pmt_v0 (handoff 0011, migration 0019): the scheduled
#: stop sequence of every trip that has at least one passenger event in the
#: period, each row joined with its stop's coordinates. LEFT JOIN — an
#: unknown stop or a stop without coordinates yields NULL lat/lon (the calc
#: then fails loudly for the affected trip; a point is never guessed).
#: Scoped to event trips: trips without events are missing under the p. 146
#: rule regardless, so their geometry is never consumed. Deterministic
#: ORDER BY (trip_id, stop_sequence — the PK — then stop_id).
_SELECT_TRIP_GEOMETRY_SQL = (
    "SELECT st.trip_id, st.stop_id, st.stop_sequence, "
    "s.latitude, s.longitude, st.shape_dist_traveled "
    "FROM canonical.stop_times AS st "
    "LEFT JOIN canonical.stops AS s ON s.stop_id = st.stop_id "
    "WHERE st.trip_id IN ("
    "SELECT DISTINCT e.trip_id FROM canonical.passenger_events AS e "
    "WHERE e.trip_id IS NOT NULL "
    "AND e.event_timestamp >= %s AND e.event_timestamp < %s) "
    "ORDER BY st.trip_id, st.stop_sequence, st.stop_id"
)


#: Demand-response trips (handoff 0013, migration 0021): columns per the
#: canonical.dr_trips contract, deterministic ORDER BY (pickup_timestamp,
#: dr_trip_id, source_record_id — the same total order headway_calc.dr sorts
#: by internally). The period bound applies to pickup_timestamp (the
#: hypertable time dimension).
_SELECT_DR_TRIPS_SQL = (
    "SELECT pickup_timestamp, service_date, dr_trip_id, vehicle_id, tos, "
    "request_timestamp, dispatch_timestamp, dropoff_timestamp, "
    "onboard_miles, pickup_odometer_miles, dropoff_odometer_miles, "
    "riders, attendants_companions, ada_related, sponsored, sponsor, "
    "no_show, interruption_after, driver_shift_id, dispatching_point_id, "
    "source, source_record_id "
    "FROM canonical.dr_trips "
    "WHERE pickup_timestamp >= %s AND pickup_timestamp < %s "
    "ORDER BY pickup_timestamp, dr_trip_id, source_record_id"
)


#: Ops schedule (handoff 0014): the scheduled stops — WITH times and the
#: trip's route/direction — of every trip observed operating in
#: canonical.vehicle_positions over the period. Input to the observed-
#: passage derivation (headway_calc.passages) and the ops calcs
#: (headway_calc.ops). LEFT JOINs: unknown stops/trips yield NULLs the
#: derivation counts loudly, never guesses. Deterministic ORDER BY
#: (trip_id, stop_sequence — the PK — then stop_id).
_SELECT_OPS_SCHEDULE_SQL = (
    "SELECT st.trip_id, st.stop_id, st.stop_sequence, "
    "s.latitude, s.longitude, st.arrival_seconds, st.departure_seconds, "
    "t.route_id, t.direction_id "
    "FROM canonical.stop_times AS st "
    "LEFT JOIN canonical.stops AS s ON s.stop_id = st.stop_id "
    "LEFT JOIN canonical.trips AS t ON t.trip_id = st.trip_id "
    "WHERE st.trip_id IN ("
    "SELECT DISTINCT trip_id FROM canonical.vehicle_positions "
    "WHERE trip_id IS NOT NULL AND time >= %s AND time < %s) "
    "ORDER BY st.trip_id, st.stop_sequence, st.stop_id"
)

#: The DISTINCT feed-declared agency timezones (canonical.agencies,
#: migration 0026) — otp_v0's schedule anchor. Deterministic ORDER BY.
_SELECT_AGENCY_TIMEZONES_SQL = (
    "SELECT DISTINCT timezone FROM canonical.agencies ORDER BY timezone"
)


def _utc_midnight(d: date) -> datetime:
    """The instant a DATE begins, as a timezone-aware UTC datetime."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _refuse_bad_period(period_start: date, period_end: date) -> None:
    """Refuses (ValueError) an empty or inverted period: an accidental
    zero-length period would silently compute over nothing."""
    if period_start >= period_end:
        raise ValueError(
            f"Refusing empty/inverted period: period_start={period_start.isoformat()} "
            f"must be strictly before period_end={period_end.isoformat()} "
            f"(half-open [start, end))."
        )


def load_vehicle_positions(
    conn,
    period_start: date,
    period_end: date,
) -> list[VehiclePosition]:
    """Load canonical vehicle positions for the half-open period [start, end).

    Bounds are UTC midnights of the given DATEs (see module docstring for the
    half-open convention). Rows arrive ordered by (vehicle_id, time,
    source_record_id), each carrying the trip's block_id and route mode (NULL
    when unassigned/unknown/absent — LEFT JOINs, see module docstring), and
    are mapped 1:1 onto VehiclePosition; the dataclass's own validation then
    fails loudly on any naive timestamp or out-of-range coordinate — a bad
    canonical row is surfaced, never coerced.

    Refuses (ValueError) an empty or inverted period: an accidental
    zero-length period would silently compute over nothing.
    """
    _refuse_bad_period(period_start, period_end)
    cur = conn.cursor()
    cur.execute(
        _SELECT_POSITIONS_SQL,
        (_utc_midnight(period_start), _utc_midnight(period_end)),
    )
    return [
        VehiclePosition(
            time=row[0],
            vehicle_id=row[1],
            trip_id=row[2],
            latitude=row[3],
            longitude=row[4],
            source_record_id=row[5],
            block_id=row[6],
            mode=row[7],
        )
        for row in cur.fetchall()
    ]


def load_passenger_events(
    conn,
    period_start: date,
    period_end: date,
) -> list[PassengerEvent]:
    """Load canonical passenger events for the half-open period [start, end).

    Bounds are UTC midnights of the given DATEs applied to ``event_timestamp``
    (the module's half-open convention — a June run is
    ``[2026-06-01, 2026-07-01)``). Rows arrive in deterministic order
    (event_timestamp, passenger_event_id, source_record_id), columns per the
    handoff-0005 canonical.passenger_events contract (migration 0012) plus
    the trip's route mode (NULL when unassigned/unknown — LEFT JOINs,
    handoff 0009), and are mapped 1:1 onto PassengerEvent — NULLs pass
    through as None
    (``event_count`` NULL is preserved, NEVER coalesced; the calc warns and
    counts 0), and the dataclass's own validation fails loudly on a naive
    timestamp or a negative count. Refuses (ValueError) an empty or inverted
    period.
    """
    _refuse_bad_period(period_start, period_end)
    cur = conn.cursor()
    cur.execute(
        _SELECT_PASSENGER_EVENTS_SQL,
        (_utc_midnight(period_start), _utc_midnight(period_end)),
    )
    return [
        PassengerEvent(
            event_timestamp=row[0],
            service_date=row[1],
            passenger_event_id=row[2],
            vehicle_id=row[3],
            trip_id=row[4],
            trip_stop_sequence=row[5],
            event_type=row[6],
            event_count=row[7],
            source=row[8],
            source_record_id=row[9],
            mode=row[10],
        )
        for row in cur.fetchall()
    ]


def load_trip_geometries(
    conn,
    period_start: date,
    period_end: date,
) -> list[StopTime]:
    """Load the stop geometry of every trip with passenger events in the
    half-open period [start, end) — pmt_v0's distance input (handoff 0011).

    One StopTime per canonical.stop_times row of an event trip, joined with
    its stop's coordinates (NULL lat/lon preserved as None — LEFT JOIN, see
    the SQL comment); ``shape_dist_traveled`` NULL stays None (migration
    0019: never fabricated). Deterministic order (trip_id, stop_sequence,
    stop_id); the dataclass's own validation fails loudly on out-of-range
    coordinates or a negative shape_dist. Refuses (ValueError) an empty or
    inverted period.
    """
    _refuse_bad_period(period_start, period_end)
    cur = conn.cursor()
    cur.execute(
        _SELECT_TRIP_GEOMETRY_SQL,
        (_utc_midnight(period_start), _utc_midnight(period_end)),
    )
    return [
        StopTime(
            trip_id=row[0],
            stop_id=row[1],
            stop_sequence=row[2],
            latitude=row[3],
            longitude=row[4],
            shape_dist_traveled=row[5],
        )
        for row in cur.fetchall()
    ]


def load_dr_trips(
    conn,
    period_start: date,
    period_end: date,
) -> list[DrTrip]:
    """Load canonical demand-response trips for the half-open period
    [start, end) — the DR calcs' input (handoff 0013, migration 0021).

    Bounds are UTC midnights of the given DATEs applied to
    ``pickup_timestamp`` (the module's half-open convention). Rows arrive in
    deterministic order (pickup_timestamp, dr_trip_id, source_record_id) and
    map 1:1 onto DrTrip — Decimal distances pass through as NUMERIC (NULL
    stays None, never coalesced), and the dataclass's own validation fails
    loudly on any structural contradiction (a broken pipeline, since the
    transform quarantines them). Refuses (ValueError) an empty or inverted
    period.
    """
    _refuse_bad_period(period_start, period_end)
    cur = conn.cursor()
    cur.execute(
        _SELECT_DR_TRIPS_SQL,
        (_utc_midnight(period_start), _utc_midnight(period_end)),
    )
    return [
        DrTrip(
            pickup_timestamp=row[0],
            service_date=row[1],
            dr_trip_id=row[2],
            vehicle_id=row[3],
            tos=row[4],
            request_timestamp=row[5],
            dispatch_timestamp=row[6],
            dropoff_timestamp=row[7],
            onboard_miles=row[8],
            pickup_odometer_miles=row[9],
            dropoff_odometer_miles=row[10],
            riders=row[11],
            attendants_companions=row[12],
            ada_related=row[13],
            sponsored=row[14],
            sponsor=row[15],
            no_show=row[16],
            interruption_after=row[17],
            driver_shift_id=row[18],
            dispatching_point_id=row[19],
            source=row[20],
            source_record_id=row[21],
        )
        for row in cur.fetchall()
    ]


def load_ops_schedule(
    conn,
    period_start: date,
    period_end: date,
) -> list[OpsScheduledStop]:
    """Load the scheduled stops (with times, coordinates and route/
    direction) of every trip observed operating in the half-open period
    [start, end) — the ops passage derivation's schedule input (handoff
    0014).

    One OpsScheduledStop per canonical.stop_times row of an observed trip;
    NULLs pass through as None (LEFT JOINs — a coordinate, schedule time,
    or trip linkage is never guessed). Deterministic order (trip_id,
    stop_sequence, stop_id). Refuses (ValueError) an empty or inverted
    period.
    """
    _refuse_bad_period(period_start, period_end)
    cur = conn.cursor()
    cur.execute(
        _SELECT_OPS_SCHEDULE_SQL,
        (_utc_midnight(period_start), _utc_midnight(period_end)),
    )
    return [
        OpsScheduledStop(
            trip_id=row[0],
            stop_id=row[1],
            stop_sequence=row[2],
            latitude=row[3],
            longitude=row[4],
            arrival_seconds=row[5],
            departure_seconds=row[6],
            route_id=row[7],
            direction_id=row[8],
        )
        for row in cur.fetchall()
    ]


def load_agency_timezones(conn) -> list[str]:
    """The DISTINCT feed-declared agency timezones (canonical.agencies,
    migration 0026), in deterministic order — otp_v0 refuses when this is
    empty or holds more than one distinct zone (a schedule anchor is never
    guessed)."""
    cur = conn.cursor()
    cur.execute(_SELECT_AGENCY_TIMEZONES_SQL, ())
    return [row[0] for row in cur.fetchall()]


def load_operated_trip_ids(
    conn,
    period_start: date,
    period_end: date,
) -> list[str]:
    """Load the distinct trip_ids observed operating in the half-open period.

    ``SELECT DISTINCT trip_id FROM canonical.vehicle_positions`` with a
    non-NULL trip_id and ``time`` in [start, end) — the operated-trips
    denominator of the upt_v0 missing-trip rule (2026 NTD Policy Manual
    p. 146, handoff 0005): an operated trip with zero passenger events is a
    missing trip. Deterministic order (trip_id). Refuses (ValueError) an
    empty or inverted period.
    """
    _refuse_bad_period(period_start, period_end)
    cur = conn.cursor()
    cur.execute(
        _SELECT_OPERATED_TRIP_IDS_SQL,
        (_utc_midnight(period_start), _utc_midnight(period_end)),
    )
    return [row[0] for row in cur.fetchall()]
