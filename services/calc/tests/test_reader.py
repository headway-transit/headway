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
        ),
        (
            datetime(2026, 1, 15, 12, 1, tzinfo=timezone.utc),
            "veh-101",
            None,  # unassigned position stays unassigned — mapped, not coerced
            40.01,
            -75.0,
            "rec-x-00",
            None,  # LEFT JOIN: no trip, no block — NULL, never a dropped row
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
    assert positions[1].trip_id is None  # None passes through untouched
    assert positions[1].block_id is None


def test_reader_sql_columns_join_and_order_match_handoffs():
    conn = RecordingConnection(position_rows=[])
    load_vehicle_positions(conn, PERIOD_START, PERIOD_END)

    assert len(conn.executed) == 1
    sql, _ = conn.executed[0]
    assert (
        "SELECT p.time, p.vehicle_id, p.trip_id, p.latitude, p.longitude, "
        "p.source_record_id, t.block_id" in sql
    )
    assert "FROM canonical.vehicle_positions AS p" in sql
    # Handoff 0003: block_id joined from canonical.trips — LEFT JOIN so an
    # unassigned/unknown trip yields NULL, never a dropped position row.
    assert "LEFT JOIN canonical.trips AS t ON t.trip_id = p.trip_id" in sql
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
    # (migration 0012), in contract order.
    assert (
        "SELECT event_timestamp, service_date, passenger_event_id, vehicle_id, "
        "trip_id, trip_stop_sequence, event_type, event_count, source, "
        "source_record_id" in sql
    )
    assert "FROM canonical.passenger_events" in sql
    # Half-open on event_timestamp, UTC-midnight datetime binding.
    assert "WHERE event_timestamp >= %s AND event_timestamp < %s" in sql
    assert "<=" not in sql.split("WHERE", 1)[1]
    assert "ORDER BY event_timestamp, passenger_event_id, source_record_id" in sql
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
