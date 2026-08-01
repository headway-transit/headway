"""Unit tests for headway_calc.reader with the recording fake connection.

Asserts the SQL shape (columns per handoff 0001 plus the trips.block_id LEFT
JOIN per handoff 0003 and the handoff-0005 canonical.passenger_events /
operated-trips queries, half-open bounds, deterministic ORDER BY), the
UTC-datetime parameter binding, and the row → dataclass mapping. No live
database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from conftest import (
    RecordingConnection,
    events_to_rows,
    load_events,
    load_positions,
    positions_to_rows,
)

from headway_calc.reader import (
    load_operated_trip_ids,
    load_passenger_events,
    load_vehicle_positions,
)

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 2, 1)


def _sample_rows():
    return [
        (
            datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
            "veh-101",
            "trip-A",
            40.0,
            -75.0,
            "rec-a-00",
            "blk-1",
            "bus",  # canonical.routes.mode joined via trips (handoff 0009)
            "5335",  # vehicle_label, migration 0037 (handoff 0032)
            "42",  # canonical.routes.short_name joined via trips (handoff 0032)
        ),
        (
            datetime(2026, 1, 15, 12, 1, tzinfo=timezone.utc),
            "veh-101",
            None,  # unassigned position stays unassigned — mapped, not coerced
            40.01,
            -75.0,
            "rec-x-00",
            None,  # LEFT JOIN: no trip, no block — NULL, never a dropped row
            None,  # LEFT JOIN: no trip, no route, no mode — NULL, never guessed
            None,  # a feed without labels stores NULL — never an invented name
            None,  # no trip, no route, no short name — NULL, never guessed
        ),
    ]


def test_reader_maps_rows_to_dataclasses():
    conn = RecordingConnection(position_rows=_sample_rows())
    positions = load_vehicle_positions(conn, PERIOD_START, PERIOD_END)

    assert len(positions) == 2
    first = positions[0]
    assert first.time == datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    assert first.vehicle_id == "veh-101"
    assert first.trip_id == "trip-A"
    assert first.latitude == 40.0
    assert first.longitude == -75.0
    assert first.source_record_id == "rec-a-00"
    assert first.block_id == "blk-1"  # joined from canonical.trips
    assert first.mode == "bus"  # joined from canonical.routes (handoff 0009)
    assert first.vehicle_label == "5335"  # migration 0037 (handoff 0032)
    assert first.route_short_name == "42"  # joined from canonical.routes
    assert positions[1].trip_id is None  # None passes through untouched
    assert positions[1].block_id is None
    assert positions[1].mode is None  # NULL mode stays None, never guessed
    assert positions[1].vehicle_label is None  # absent stays absent
    assert positions[1].route_short_name is None


def test_reader_sql_columns_join_and_order_match_handoffs():
    conn = RecordingConnection(position_rows=[])
    load_vehicle_positions(conn, PERIOD_START, PERIOD_END)

    assert len(conn.executed) == 1
    sql, _ = conn.executed[0]
    assert (
        "SELECT p.time, p.vehicle_id, p.trip_id, p.latitude, p.longitude, "
        "p.source_record_id, t.block_id, r.mode" in sql
    )
    assert "FROM canonical.vehicle_positions AS p" in sql
    # Handoff 0003: block_id joined from canonical.trips — LEFT JOIN so an
    # unassigned/unknown trip yields NULL, never a dropped position row.
    assert "LEFT JOIN canonical.trips AS t ON t.trip_id = p.trip_id" in sql
    # Handoff 0009: mode joined from canonical.routes via trips — LEFT JOIN
    # so an unknown trip/route yields NULL mode, never a dropped row.
    assert "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id" in sql
    assert "ORDER BY p.vehicle_id, p.time, p.source_record_id" in sql


def test_reader_uses_half_open_utc_bounds():
    conn = RecordingConnection(position_rows=[])
    load_vehicle_positions(conn, date(2026, 6, 1), date(2026, 7, 1))

    sql, params = conn.executed[0]
    # Half-open: inclusive lower bound, EXCLUSIVE upper bound.
    assert "WHERE p.time >= %s AND p.time < %s" in sql
    assert "<=" not in sql.split("WHERE", 1)[1]
    # DATE bounds bound as timezone-aware UTC midnights, never naive/dates —
    # the comparison must not depend on the DB session time zone.
    assert params == (
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
    )
    assert params[0].tzinfo is timezone.utc
    assert params[1].tzinfo is timezone.utc


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 6, 1), date(2026, 6, 1)),  # empty
        (date(2026, 7, 1), date(2026, 6, 1)),  # inverted
    ],
)
def test_reader_refuses_empty_or_inverted_period(start, end):
    conn = RecordingConnection(position_rows=[])
    with pytest.raises(ValueError, match="empty/inverted period"):
        load_vehicle_positions(conn, start, end)
    assert conn.executed == []  # refused before touching the database


def test_passenger_events_sql_columns_bounds_and_order_match_handoff_0005():
    conn = RecordingConnection()
    load_passenger_events(conn, date(2026, 6, 1), date(2026, 7, 1))

    assert len(conn.executed) == 1
    sql, params = conn.executed[0]
    # Columns per the handoff-0005 canonical.passenger_events contract
    # (migration 0012), in contract order, plus routes.mode (handoff 0009).
    assert (
        "SELECT e.event_timestamp, e.service_date, e.passenger_event_id, "
        "e.vehicle_id, e.trip_id, e.trip_stop_sequence, e.event_type, "
        "e.event_count, e.source, e.source_record_id, r.mode" in sql
    )
    assert "FROM canonical.passenger_events AS e" in sql
    # Handoff 0009: mode joined trips → routes — LEFT JOINs so an
    # unassigned/unknown trip yields NULL mode, never a dropped event row.
    assert "LEFT JOIN canonical.trips AS t ON t.trip_id = e.trip_id" in sql
    assert "LEFT JOIN canonical.routes AS r ON r.route_id = t.route_id" in sql
    # Half-open on event_timestamp, UTC-midnight datetime binding.
    assert "WHERE e.event_timestamp >= %s AND e.event_timestamp < %s" in sql
    assert "<=" not in sql.split("WHERE", 1)[1]
    assert (
        "ORDER BY e.event_timestamp, e.passenger_event_id, e.source_record_id"
        in sql
    )
    assert params == (
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


def test_passenger_events_roundtrip_golden_fixture(upt_golden_fixture):
    """Golden events rendered as DB rows map back to identical dataclasses,
    NULLs (trip_id, event_count) passing through untouched."""
    expected_events = load_events(upt_golden_fixture["blocked_case"])
    conn = RecordingConnection(passenger_event_rows=events_to_rows(expected_events))
    loaded = load_passenger_events(conn, PERIOD_START, PERIOD_END)
    assert sorted(loaded, key=lambda e: e.passenger_event_id) == sorted(
        expected_events, key=lambda e: e.passenger_event_id
    )
    # NULL preservation: the fixture's NULL-count and unassigned events
    # arrive as None, never coalesced.
    by_id = {e.passenger_event_id: e for e in loaded}
    assert by_id["pe-a-07"].event_count is None
    assert by_id["pe-a-08"].trip_id is None


def test_operated_trip_ids_sql_and_mapping():
    conn = RecordingConnection(operated_trip_rows=[("trip-1",), ("trip-2",)])
    trips = load_operated_trip_ids(conn, date(2026, 6, 1), date(2026, 7, 1))

    assert trips == ["trip-1", "trip-2"]
    sql, params = conn.executed[0]
    assert "SELECT DISTINCT trip_id FROM canonical.vehicle_positions" in sql
    assert "trip_id IS NOT NULL" in sql
    assert "time >= %s AND time < %s" in sql
    assert "ORDER BY trip_id" in sql
    assert params == (
        datetime(2026, 6, 1, tzinfo=timezone.utc),
        datetime(2026, 7, 1, tzinfo=timezone.utc),
    )


@pytest.mark.parametrize(
    "loader", [load_passenger_events, load_operated_trip_ids]
)
def test_new_loaders_refuse_empty_or_inverted_period(loader):
    conn = RecordingConnection()
    with pytest.raises(ValueError, match="empty/inverted period"):
        loader(conn, date(2026, 6, 1), date(2026, 6, 1))
    assert conn.executed == []  # refused before touching the database


def test_reader_roundtrips_golden_fixture(golden_fixture):
    """Golden positions rendered as DB rows map back to identical dataclasses."""
    expected_positions = load_positions(golden_fixture)
    conn = RecordingConnection(position_rows=positions_to_rows(expected_positions))
    loaded = load_vehicle_positions(conn, PERIOD_START, PERIOD_END)
    # Same multiset of positions, in the reader's deterministic SQL order.
    assert sorted(loaded, key=lambda p: p.source_record_id) == sorted(
        expected_positions, key=lambda p: p.source_record_id
    )
    assert [p.source_record_id for p in loaded] == [
        p.source_record_id
        for p in sorted(
            expected_positions,
            key=lambda p: (p.vehicle_id, p.time, p.source_record_id),
        )
    ]


def test_pre_0037_database_falls_back_to_the_label_free_select():
    """A vocabulary feature must never stop a calculation from reading its
    inputs: on a database without canonical.vehicle_positions.vehicle_label
    (SQLSTATE 42703) the reader rolls back and re-reads without the column —
    labels are then honestly None and titles fall back to the shortened
    vehicle_id."""
    rows = [
        (
            datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
            "veh-101",
            "trip-A",
            40.0,
            -75.0,
            "rec-a-00",
            "blk-1",
            "bus",
            None,  # the fallback SELECT binds NULL for vehicle_label
            "42",
        ),
    ]
    conn = RecordingConnection(
        position_rows=rows, vehicle_label_column_missing=True
    )
    positions = load_vehicle_positions(conn, PERIOD_START, PERIOD_END)

    # The failed 0037 statement was rolled back, then the fallback ran.
    assert conn.rollback_count == 1
    selects = conn.statements_matching("FROM canonical.vehicle_positions")
    assert len(selects) == 2
    assert "p.vehicle_label" in selects[0][0]
    assert "p.vehicle_label" not in selects[1][0]

    # Every other field still loads; the label is honestly absent.
    (position,) = positions
    assert position.vehicle_id == "veh-101"
    assert position.vehicle_label is None
    assert position.route_short_name == "42"


# ---------------------------------------------------------------------------
# Handoff 0040: revenue_classification + revenue windows
# ---------------------------------------------------------------------------

def test_passenger_events_load_revenue_classification():
    """The assignment status (migration 0039) rides each loaded event."""
    from headway_calc.reader import load_passenger_events
    from headway_calc.types import PassengerEvent

    events = [
        PassengerEvent(
            event_timestamp=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            service_date=date(2026, 6, 15),
            passenger_event_id="pe-1",
            vehicle_id="v1",
            trip_id=None,
            trip_stop_sequence=None,
            event_type="Passenger boarded",
            event_count=1,
            source="tides",
            source_record_id="rec-1",
            revenue_classification="unassigned",
        ),
    ]
    conn = RecordingConnection(passenger_event_rows=events_to_rows(events))
    (loaded,) = load_passenger_events(conn, PERIOD_START, PERIOD_END)
    assert loaded.revenue_classification == "unassigned"
    assert "e.revenue_classification" in conn.executed[0][0]


def test_pre_0039_database_falls_back_to_classification_free_select():
    """On a database without canonical.passenger_events.revenue_classification
    (SQLSTATE 42703) the reader rolls back and re-reads without it — the
    status is then honestly None and upt uses the trip-assignment proxy."""
    from headway_calc.reader import load_passenger_events

    # Rows in the 12-column shape the fallback SELECT returns (NULL at 11).
    rows = [
        (
            datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
            date(2026, 6, 15),
            "pe-1",
            "v1",
            "trip-1",
            1,
            "Passenger boarded",
            2,
            "tides",
            "rec-1",
            "bus",
            None,  # the fallback binds NULL for revenue_classification
        ),
    ]
    conn = RecordingConnection(
        passenger_event_rows=rows, revenue_classification_column_missing=True
    )
    (loaded,) = load_passenger_events(conn, PERIOD_START, PERIOD_END)
    assert conn.rollback_count == 1
    selects = conn.statements_matching("FROM canonical.passenger_events")
    assert "e.revenue_classification" in selects[0][0]
    assert "e.revenue_classification" not in selects[1][0]
    assert loaded.revenue_classification is None
    assert loaded.trip_id == "trip-1"


def test_load_revenue_window_seconds_maps_and_orders():
    from headway_calc.reader import load_revenue_window_seconds

    conn = RecordingConnection(
        revenue_window_rows=[
            (date(2026, 6, 15), 28800, 72000),
            (date(2026, 6, 16), None, 71000),
        ]
    )
    windows = load_revenue_window_seconds(conn, PERIOD_START, PERIOD_END)
    assert windows == {
        date(2026, 6, 15): (28800, 72000),
        date(2026, 6, 16): (None, 71000),
    }
    assert "MIN(st.departure_seconds)" in conn.executed[0][0]


def test_load_revenue_window_seconds_pre_0019_returns_empty():
    """A database without canonical.stop_times (SQLSTATE 42P01) yields no
    windows — every no-run boarding is then held pending, never guessed."""
    from headway_calc.reader import load_revenue_window_seconds

    conn = RecordingConnection(stop_times_table_missing=True)
    assert load_revenue_window_seconds(conn, PERIOD_START, PERIOD_END) == {}
    assert conn.rollback_count == 1
