"""Tests for the TIDES passenger_events simulator.

Uses a fake DB-API connection (no live database) and seeded determinism.
"""

import csv
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import simulate  # noqa: E402
from simulate import (  # noqa: E402
    EVENT_ALIGHTED,
    EVENT_BOARDED,
    EVENT_TYPE_ENUM,
    FIELDNAMES,
    OperatedTrip,
    fetch_operated_trips,
    generate_events,
    write_csv,
)

SERVICE_DATE = date(2026, 7, 8)


def _ts(hour, minute=0):
    return datetime(2026, 7, 8, hour, minute, tzinfo=timezone.utc)


def make_trips(n=10):
    return [
        OperatedTrip(
            trip_id=f"trip-{i:03d}",
            vehicle_id=f"veh-{i:03d}",
            first_seen=_ts(6 + i % 12),
            last_seen=_ts(7 + i % 12, 30),
        )
        for i in range(n)
    ]


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows


class FakeConnection:
    """Minimal DB-API connection double: cursor().execute()/fetchall()."""

    def __init__(self, rows):
        self.cursor_obj = FakeCursor(rows)

    def cursor(self):
        return self.cursor_obj


def net_by_trip(rows):
    """(boardings, alightings) totals per trip_id."""
    totals = defaultdict(lambda: [0, 0])
    for r in rows:
        if r["event_type"] == EVENT_BOARDED:
            totals[r["trip_id_performed"]][0] += r["event_count"]
        elif r["event_type"] == EVENT_ALIGHTED:
            totals[r["trip_id_performed"]][1] += r["event_count"]
    return totals


def test_fetch_operated_trips_uses_injected_connection():
    rows = [
        ("trip-001", "veh-001", _ts(6), _ts(7)),
        ("trip-002", "veh-002", _ts(8), _ts(9)),
    ]
    conn = FakeConnection(rows)
    trips = fetch_operated_trips(conn, SERVICE_DATE)
    assert [t.trip_id for t in trips] == ["trip-001", "trip-002"]
    assert trips[0].vehicle_id == "veh-001"
    sql, params = conn.cursor_obj.executed[0]
    assert "canonical.vehicle_positions" in sql
    assert "canonical.trips" in sql
    # UTC day bounds for the service date.
    assert params[0] == datetime(2026, 7, 8, tzinfo=timezone.utc)
    assert params[1] == datetime(2026, 7, 9, tzinfo=timezone.utc)


def test_happy_path_rows_are_spec_valid():
    rows = generate_events(make_trips(), SERVICE_DATE, seed=42)
    assert rows, "expected events for operated trips"
    ids = set()
    for r in rows:
        assert set(FIELDNAMES) == set(r.keys())
        # Required TIDES fields all populated.
        assert r["passenger_event_id"]
        assert r["service_date"] == "2026-07-08"
        assert r["event_timestamp"]
        assert isinstance(r["trip_stop_sequence"], int) and r["trip_stop_sequence"] >= 1
        assert r["event_type"] in EVENT_TYPE_ENUM
        assert r["event_type"] in (EVENT_BOARDED, EVENT_ALIGHTED)
        assert r["vehicle_id"].startswith("veh-")
        assert isinstance(r["event_count"], int) and 1 <= r["event_count"] <= 30
        ids.add(r["passenger_event_id"])
    assert len(ids) == len(rows), "passenger_event_id must be unique"
    # Every operated trip has events, and each balances exactly by default.
    totals = net_by_trip(rows)
    assert set(totals) == {t.trip_id for t in make_trips()}
    for trip_id, (board, alight) in totals.items():
        assert board == alight, f"{trip_id} unbalanced by default: {board} vs {alight}"


def test_seeded_determinism():
    trips = make_trips()
    a = generate_events(trips, SERVICE_DATE, seed=7, imbalance_share=0.2)
    b = generate_events(trips, SERVICE_DATE, seed=7, imbalance_share=0.2)
    assert a == b, "same seed must give identical output"
    c = generate_events(trips, SERVICE_DATE, seed=8, imbalance_share=0.2)
    assert a != c, "different seed should change output"


def test_missing_trip_share_skips_that_share_of_trips():
    trips = make_trips(10)
    rows = generate_events(trips, SERVICE_DATE, seed=1, missing_trip_share=0.3)
    with_events = {r["trip_id_performed"] for r in rows}
    assert len(with_events) == 7, "30% of 10 operated trips must have no events"
    assert with_events < {t.trip_id for t in trips}


def test_imbalance_share_exceeds_ten_percent():
    trips = make_trips(10)
    rows = generate_events(trips, SERVICE_DATE, seed=3, imbalance_share=1.0)
    totals = net_by_trip(rows)
    assert len(totals) == 10
    for trip_id, (board, alight) in totals.items():
        assert board > 0
        assert abs(board - alight) > 0.10 * board, (
            f"{trip_id} not imbalanced enough: {board} vs {alight}"
        )


def test_negative_load_share_drops_running_load_below_zero():
    trips = make_trips(10)
    rows = generate_events(trips, SERVICE_DATE, seed=5, negative_load_share=1.0)
    by_trip = defaultdict(list)
    for r in rows:
        by_trip[r["trip_id_performed"]].append(r)
    assert len(by_trip) == 10
    for trip_id, trip_rows in by_trip.items():
        # Rows are generated in stop order; replay the running load.
        load = 0
        min_load = 0
        for r in trip_rows:
            if r["event_type"] == EVENT_BOARDED:
                load += r["event_count"]
            else:
                load -= r["event_count"]
            min_load = min(min_load, load)
        assert min_load < 0, f"{trip_id} load never went negative"


def test_defect_sets_are_disjoint():
    trips = make_trips(10)
    rows = generate_events(
        trips,
        SERVICE_DATE,
        seed=9,
        missing_trip_share=0.2,
        imbalance_share=0.2,
        negative_load_share=0.2,
    )
    totals = net_by_trip(rows)
    assert len(totals) == 8  # two trips missing entirely
    imbalanced = [t for t, (b, a) in totals.items() if b > 0 and abs(b - a) > 0.10 * b]
    assert len(imbalanced) >= 2


def test_write_csv_roundtrip(tmp_path):
    rows = generate_events(make_trips(3), SERVICE_DATE, seed=2)
    out = write_csv(rows, tmp_path)
    assert out == tmp_path / "passenger_events.csv"
    with out.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == FIELDNAMES
        read_back = list(reader)
    assert len(read_back) == len(rows)
    assert read_back[0]["event_type"] in EVENT_TYPE_ENUM


def test_run_end_to_end_with_fake_connection(tmp_path, capsys):
    db_rows = [
        ("trip-001", "veh-001", _ts(6), _ts(7)),
        ("trip-002", "veh-002", _ts(8), _ts(9)),
    ]
    args = simulate.parse_args(
        ["--service-date", "2026-07-08", "--seed", "4", "--out", str(tmp_path)]
    )
    out = simulate.run(FakeConnection(db_rows), args)
    assert out.exists()
    printed = capsys.readouterr().out
    assert "SIMULATED" in printed
    assert "tides_simulated" in printed


def test_every_row_carries_the_structural_sim_marker():
    """Every passenger_event_id is 'sim:'-prefixed — the STRUCTURAL
    simulated-data marker (2026-07-13 hardening pass): the TIDES connector
    hard-refuses sim-marked rows arriving under a non-simulated source
    label (Shared Constraint 2, full provenance), so this prefix is
    load-bearing, not cosmetic. It must survive every code path, including
    defect injection.
    """
    rows = generate_events(
        make_trips(6),
        SERVICE_DATE,
        seed=11,
        missing_trip_share=0.2,
        imbalance_share=0.2,
        negative_load_share=0.2,
    )
    assert rows
    for row in rows:
        assert row["passenger_event_id"].startswith("sim:"), row["passenger_event_id"]
