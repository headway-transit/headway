"""Injectable reader for canonical.vehicle_positions. Matches handoff 0001,
plus the canonical.trips.block_id join (handoff 0003, migration 0011).

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

from headway_calc.types import VehiclePosition

#: Column names and order per handoff 0001 (canonical.vehicle_positions) plus
#: canonical.trips.block_id (handoff 0003, migration 0011) via LEFT JOIN.
_SELECT_POSITIONS_SQL = (
    "SELECT p.time, p.vehicle_id, p.trip_id, p.latitude, p.longitude, "
    "p.source_record_id, t.block_id "
    "FROM canonical.vehicle_positions AS p "
    "LEFT JOIN canonical.trips AS t ON t.trip_id = p.trip_id "
    "WHERE p.time >= %s AND p.time < %s "
    "ORDER BY p.vehicle_id, p.time, p.source_record_id"
)


def _utc_midnight(d: date) -> datetime:
    """The instant a DATE begins, as a timezone-aware UTC datetime."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def load_vehicle_positions(
    conn,
    period_start: date,
    period_end: date,
) -> list[VehiclePosition]:
    """Load canonical vehicle positions for the half-open period [start, end).

    Bounds are UTC midnights of the given DATEs (see module docstring for the
    half-open convention). Rows arrive ordered by (vehicle_id, time,
    source_record_id), each carrying the trip's block_id (NULL when
    unassigned/unknown/absent — LEFT JOIN, see module docstring), and are
    mapped 1:1 onto VehiclePosition; the dataclass's own validation then
    fails loudly on any naive timestamp or out-of-range coordinate — a bad
    canonical row is surfaced, never coerced.

    Refuses (ValueError) an empty or inverted period: an accidental
    zero-length period would silently compute over nothing.
    """
    if period_start >= period_end:
        raise ValueError(
            f"Refusing empty/inverted period: period_start={period_start.isoformat()} "
            f"must be strictly before period_end={period_end.isoformat()} "
            f"(half-open [start, end))."
        )
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
        )
        for row in cur.fetchall()
    ]
