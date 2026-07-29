"""The agency's schedule, in memory, as trip resolution needs to see it.

A vendor APC export names a trip the way the agency's schedulers do — route,
pattern, start time — and Headway has to decide which GTFS trip that is
(handoff 0031). Deciding needs four facts per scheduled trip that live in
four different canonical tables:

    canonical.trips              trip_id, route_id, service_id, direction_id
    canonical.routes             route_short_name
    canonical.stop_times         the trip's FIRST scheduled departure
    canonical.service_calendars  which service_ids run on a given date
    + canonical.service_calendar_dates

This module reads them once per vendor file into a ``ScheduleIndex`` and
answers exactly one question: *which scheduled trips have this key?* It has
no opinion about what to do with the answer — zero, one or many candidates
all come back as they are, and the resolver decides (never this module, and
never by picking).

Why per file and not per process: a static feed is upserted whenever the
agency publishes, so an index cached across files would silently resolve
today's export against last month's schedule. Vendor files arrive daily at
most, and the whole index is one pass over trips + one pass over the first
stop time of each trip.

Service-day semantics are the GTFS ones, applied at read time from the
feed's own rows (calendar.txt weekday flags inside an INCLUSIVE date
interval, then calendar_dates.txt exceptions where 1 = added and 2 =
removed — GTFS Schedule Reference, gtfs.org, verified 2026-07-29). They are
NOT expanded at write time: the expansion is derivable, the source rows are
not.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable, Optional

from .gtfs_static import (
    SERVICE_ADDED,
    SERVICE_REMOVED,
    CanonicalServiceCalendar,
    CanonicalServiceCalendarDate,
)

#: Seconds in one service day. GTFS times may exceed 24:00:00 (a trip that
#: starts after midnight belongs to the previous service day), so a
#: wall-clock start time read from a vendor file can correspond to a GTFS
#: departure of either ``seconds`` or ``seconds + DAY_SECONDS``. Which one is
#: an agency convention the resolution spec declares — this constant is only
#: the arithmetic.
DAY_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class ScheduledTrip:
    """One canonical trip, flattened to what resolution matches on."""

    trip_id: str
    route_id: str
    route_short_name: Optional[str]
    service_id: str
    direction_id: Optional[int]
    #: Seconds after "noon minus 12 h" of the service day, from the trip's
    #: lowest-stop_sequence departure. None when the feed gives the first
    #: stop no departure time — such a trip is simply never a candidate on a
    #: start-time key, and the resolver says so rather than inventing one.
    first_departure_seconds: Optional[int]


@dataclass(frozen=True)
class ScheduleIndex:
    """Everything one vendor file resolves against, read once."""

    trips: tuple[ScheduledTrip, ...]
    calendars: tuple[CanonicalServiceCalendar, ...]
    calendar_dates: tuple[CanonicalServiceCalendarDate, ...]
    #: stop identifiers by the canonical.stops field they came from, e.g.
    #: {"stop_code": {"KE001": ("KE001",)}, "stop_id": {...}}. Values are
    #: tuples because a feed may repeat a code — ambiguity is reported, not
    #: resolved away.
    stops_by: dict[str, dict[str, tuple[str, ...]]] = field(
        default_factory=dict
    )
    _by_key: dict[tuple, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        trips: Iterable[ScheduledTrip],
        calendars: Iterable[CanonicalServiceCalendar] = (),
        calendar_dates: Iterable[CanonicalServiceCalendarDate] = (),
        stops_by: Optional[dict[str, dict[str, tuple[str, ...]]]] = None,
    ) -> "ScheduleIndex":
        trips = tuple(trips)
        by_key: dict[tuple, list[str]] = defaultdict(list)
        for trip in trips:
            by_key[
                (
                    trip.service_id,
                    "route_short_name",
                    trip.route_short_name,
                    trip.first_departure_seconds,
                    trip.direction_id,
                )
            ].append(trip.trip_id)
            by_key[
                (
                    trip.service_id,
                    "route_id",
                    trip.route_id,
                    trip.first_departure_seconds,
                    trip.direction_id,
                )
            ].append(trip.trip_id)
        return cls(
            trips=trips,
            calendars=tuple(calendars),
            calendar_dates=tuple(calendar_dates),
            stops_by=dict(stops_by or {}),
            _by_key={k: tuple(sorted(v)) for k, v in by_key.items()},
        )

    # --- service days ---------------------------------------------------

    def active_services(self, service_date: date) -> frozenset[str]:
        """The service_ids running on a date, per the feed's own calendar.

        GTFS order of operations (Schedule Reference, verified 2026-07-29):
        a calendar.txt row applies when the date falls inside its INCLUSIVE
        start/end interval AND that weekday is flagged available; a
        calendar_dates.txt row then ADDS (exception_type 1) or REMOVES
        (exception_type 2) the service for that exact date. Exceptions win.
        """
        weekday = service_date.weekday()
        active = {
            calendar.service_id
            for calendar in self.calendars
            if calendar.start_date <= service_date <= calendar.end_date
            and calendar.weekday_flags()[weekday]
        }
        for exception in self.calendar_dates:
            if exception.service_date != service_date:
                continue
            if exception.exception_type == SERVICE_ADDED:
                active.add(exception.service_id)
            elif exception.exception_type == SERVICE_REMOVED:
                active.discard(exception.service_id)
        return frozenset(active)

    def has_calendar(self) -> bool:
        """True when the feed defined service days at all."""
        return bool(self.calendars or self.calendar_dates)

    # --- candidates ------------------------------------------------------

    def candidates(
        self,
        services: Iterable[str],
        route_field: str,
        route_value: str,
        departure_seconds: int,
        direction_id: int,
    ) -> tuple[str, ...]:
        """Every scheduled trip_id with this key, across the given services.

        Returns ALL matches — zero, one, or several. Choosing is not this
        function's business, and there is no ordering preference hidden in
        it: the result is sorted so a caller that reports candidates reports
        them the same way twice.
        """
        found: set[str] = set()
        for service_id in services:
            found.update(
                self._by_key.get(
                    (
                        service_id,
                        route_field,
                        route_value,
                        departure_seconds,
                        direction_id,
                    ),
                    (),
                )
            )
        return tuple(sorted(found))

    def stop_exists(self, field_name: str, value: str) -> tuple[str, ...]:
        """The canonical stop_id(s) whose ``field_name`` equals ``value``."""
        return self.stops_by.get(field_name, {}).get(value, ())


#: canonical.trips + canonical.routes + the first scheduled departure of each
#: trip. The first departure is the departure_time of the trip's LOWEST
#: stop_sequence (DISTINCT ON), which is the GTFS definition of when the trip
#: starts; a trip whose first stop time is empty yields NULL and is simply
#: not a start-time candidate. Deterministic ORDER BY trip_id.
SELECT_SCHEDULED_TRIPS_SQL = (
    "SELECT t.trip_id, t.route_id, r.short_name, t.service_id, "
    "t.direction_id, f.departure_seconds "
    "FROM canonical.trips AS t "
    "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id "
    "LEFT JOIN LATERAL ("
    "SELECT st.departure_seconds FROM canonical.stop_times AS st "
    "WHERE st.trip_id = t.trip_id "
    "ORDER BY st.stop_sequence LIMIT 1) AS f ON TRUE "
    "ORDER BY t.trip_id"
)

SELECT_SERVICE_CALENDARS_SQL = (
    "SELECT service_id, monday, tuesday, wednesday, thursday, friday, "
    "saturday, sunday, start_date, end_date "
    "FROM canonical.service_calendars ORDER BY service_id"
)

SELECT_SERVICE_CALENDAR_DATES_SQL = (
    "SELECT service_id, service_date, exception_type "
    "FROM canonical.service_calendar_dates ORDER BY service_id, service_date"
)

SELECT_STOP_IDENTIFIERS_SQL = (
    "SELECT stop_id, stop_code FROM canonical.stops ORDER BY stop_id"
)


def load_schedule_index(connection: Any) -> ScheduleIndex:
    """Read the whole schedule index through a DB-API 2.0 connection.

    Four queries, no filters: resolution compares against the schedule as a
    whole, and a partial index would turn a schedule Headway has into an
    "unmatched" finding it does not deserve.
    """
    trips: list[ScheduledTrip] = []
    calendars: list[CanonicalServiceCalendar] = []
    calendar_dates: list[CanonicalServiceCalendarDate] = []
    stops_by: dict[str, dict[str, list[str]]] = {"stop_id": {}, "stop_code": {}}

    cursor = connection.cursor()
    try:
        cursor.execute(SELECT_SCHEDULED_TRIPS_SQL)
        for (
            trip_id,
            route_id,
            short_name,
            service_id,
            direction_id,
            departure_seconds,
        ) in cursor.fetchall():
            trips.append(
                ScheduledTrip(
                    trip_id=trip_id,
                    route_id=route_id,
                    route_short_name=short_name,
                    service_id=service_id,
                    direction_id=(
                        None if direction_id is None else int(direction_id)
                    ),
                    first_departure_seconds=(
                        None
                        if departure_seconds is None
                        else int(departure_seconds)
                    ),
                )
            )

        cursor.execute(SELECT_SERVICE_CALENDARS_SQL)
        for row in cursor.fetchall():
            calendars.append(
                CanonicalServiceCalendar(
                    service_id=row[0],
                    monday=bool(row[1]),
                    tuesday=bool(row[2]),
                    wednesday=bool(row[3]),
                    thursday=bool(row[4]),
                    friday=bool(row[5]),
                    saturday=bool(row[6]),
                    sunday=bool(row[7]),
                    start_date=row[8],
                    end_date=row[9],
                )
            )

        cursor.execute(SELECT_SERVICE_CALENDAR_DATES_SQL)
        for service_id, service_date, exception_type in cursor.fetchall():
            calendar_dates.append(
                CanonicalServiceCalendarDate(
                    service_id=service_id,
                    service_date=service_date,
                    exception_type=int(exception_type),
                )
            )

        cursor.execute(SELECT_STOP_IDENTIFIERS_SQL)
        for stop_id, stop_code in cursor.fetchall():
            stops_by["stop_id"].setdefault(stop_id, []).append(stop_id)
            if stop_code:
                stops_by["stop_code"].setdefault(stop_code, []).append(stop_id)
    finally:
        close = getattr(cursor, "close", None)
        if close is not None:
            close()

    return ScheduleIndex.build(
        trips,
        calendars,
        calendar_dates,
        {
            field_name: {k: tuple(v) for k, v in values.items()}
            for field_name, values in stops_by.items()
        },
    )
