"""Unit tests for headway_calc.reader with the recording fake connection.

Asserts the SQL shape (columns exactly per handoff 0001, half-open bounds,
deterministic ORDER BY), the UTC-datetime parameter binding, and the row →
VehiclePosition mapping. No live database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from conftest import RecordingConnection, load_positions, positions_to_rows

from headway_calc.reader import load_vehicle_positions

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
        ),
        (
            datetime(2026, 1, 15, 12, 1, tzinfo=timezone.utc),
            "veh-101",
            None,  # unassigned position stays unassigned — mapped, not coerced
            40.01,
            -75.0,
            "rec-x-00",
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
    assert positions[1].trip_id is None  # None passes through untouched


def test_reader_sql_columns_and_order_match_handoff():
    conn = RecordingConnection(position_rows=[])
    load_vehicle_positions(conn, PERIOD_START, PERIOD_END)

    assert len(conn.executed) == 1
    sql, _ = conn.executed[0]
    assert (
        "SELECT time, vehicle_id, trip_id, latitude, longitude, source_record_id"
        in sql
    )
    assert "FROM canonical.vehicle_positions" in sql
    assert "ORDER BY vehicle_id, time, source_record_id" in sql


def test_reader_uses_half_open_utc_bounds():
    conn = RecordingConnection(position_rows=[])
    load_vehicle_positions(conn, date(2026, 6, 1), date(2026, 7, 1))

    sql, params = conn.executed[0]
    # Half-open: inclusive lower bound, EXCLUSIVE upper bound.
    assert "WHERE time >= %s AND time < %s" in sql
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
