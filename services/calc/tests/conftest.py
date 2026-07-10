"""Shared test helpers: golden fixture loading + a recording fake connection.

The RecordingConnection below is the shared fake-DB used by the reader/dq/
runner tests: it records every executed statement and every commit/rollback
boundary, serves canned canonical.vehicle_positions rows to SELECTs, and
returns deterministic generated ids (issue-0001, mv-0001, ...) so whole
RunReports are reproducible. It can be told to fail on a specific INSERT
target to simulate a mid-run persist failure.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pytest

from headway_calc.types import PassengerEvent, VehiclePosition

# services/calc/tests/conftest.py -> repo root is parents[3]
GOLDEN_DIR = Path(__file__).resolve().parents[3] / "tests" / "golden" / "vrm_vrh_v0"
UPT_GOLDEN_DIR = Path(__file__).resolve().parents[3] / "tests" / "golden" / "upt_v0"


def load_positions(raw: dict) -> list[VehiclePosition]:
    return [
        VehiclePosition(
            time=datetime.fromisoformat(p["time"]),
            vehicle_id=p["vehicle_id"],
            trip_id=p["trip_id"],
            latitude=p["latitude"],
            longitude=p["longitude"],
            source_record_id=p["source_record_id"],
            # block_id (handoff 0003) is absent from the pre-0.3.0 fixtures:
            # None, exactly like a feed omitting the optional GTFS field.
            block_id=p.get("block_id"),
        )
        for p in raw["positions"]
    ]


def load_events(raw_case: dict) -> list[PassengerEvent]:
    """Map one upt_v0 golden case's event rows onto PassengerEvent."""
    return [
        PassengerEvent(
            event_timestamp=datetime.fromisoformat(e["event_timestamp"]),
            service_date=date.fromisoformat(e["service_date"]),
            passenger_event_id=e["passenger_event_id"],
            vehicle_id=e["vehicle_id"],
            trip_id=e["trip_id"],
            trip_stop_sequence=e["trip_stop_sequence"],
            event_type=e["event_type"],
            event_count=e["event_count"],
            source=e["source"],
            source_record_id=e["source_record_id"],
        )
        for e in raw_case["events"]
    ]


@pytest.fixture(scope="session")
def golden_fixture() -> dict:
    return json.loads((GOLDEN_DIR / "fixture.json").read_text())


@pytest.fixture(scope="session")
def golden_expected() -> dict:
    return json.loads((GOLDEN_DIR / "expected.json").read_text())


@pytest.fixture(scope="session")
def golden_expected_v0_2() -> dict:
    """Expectations for CALC_VERSION 0.2.0 (gap policy: per-group exclusion +
    coverage) over the SAME fixture.json — see BASIS.md, calc 0.2.0 section."""
    return json.loads((GOLDEN_DIR / "expected_v0_2.json").read_text())


@pytest.fixture(scope="session")
def golden_block_fixture() -> dict:
    """Block fixture for vrh_v0 0.3.0 (handoff 0003): two trips in one block
    with a 600 s layover — see BASIS.md, calc 0.3.0 section."""
    return json.loads((GOLDEN_DIR / "fixture_block.json").read_text())


@pytest.fixture(scope="session")
def golden_expected_v0_3() -> dict:
    """Expectations for CALC_VERSION 0.3.0 (block-aware layover inclusion)
    over fixture_block.json — see BASIS.md, calc 0.3.0 section."""
    return json.loads((GOLDEN_DIR / "expected_v0_3.json").read_text())


@pytest.fixture(scope="session")
def golden_block_v04_fixture() -> dict:
    """Block fixture for vrh_v0 0.4.0 (handoff 0004): one block of three
    trips, the MIDDLE trip gapped — see BASIS.md, calc 0.4.0 section."""
    return json.loads((GOLDEN_DIR / "fixture_block_v04.json").read_text())


@pytest.fixture(scope="session")
def golden_expected_v0_4() -> dict:
    """Expectations for CALC_VERSION 0.4.0 (trip-level excision) over
    fixture_block_v04.json (plus fixture_block.json under 0.4.0) — see
    BASIS.md, calc 0.4.0 section."""
    return json.loads((GOLDEN_DIR / "expected_v0_4.json").read_text())


@pytest.fixture(scope="session")
def upt_golden_fixture() -> dict:
    """UPT fixture for upt_v0 0.1.0 (handoff 0005): a blocked case (missing
    share 1/3 > the FTA 2% threshold) and a factored case (share exactly
    0.02) — see tests/golden/upt_v0/BASIS.md."""
    return json.loads((UPT_GOLDEN_DIR / "fixture.json").read_text())


@pytest.fixture(scope="session")
def upt_golden_expected() -> dict:
    """Expectations for upt_v0 CALC_VERSION 0.1.0 over the UPT fixture —
    see tests/golden/upt_v0/BASIS.md."""
    return json.loads((UPT_GOLDEN_DIR / "expected.json").read_text())


def positions_to_rows(positions: list[VehiclePosition]) -> list[tuple]:
    """Render VehiclePositions as reader result rows (the handoff-0001
    canonical.vehicle_positions columns plus the trips.block_id join, handoff
    0003), in the reader's SQL order (vehicle_id, time, source_record_id) —
    the fake stands in for the database, so it honors the ORDER BY."""
    ordered = sorted(positions, key=lambda p: (p.vehicle_id, p.time, p.source_record_id))
    return [
        (
            p.time,
            p.vehicle_id,
            p.trip_id,
            p.latitude,
            p.longitude,
            p.source_record_id,
            p.block_id,
        )
        for p in ordered
    ]


def events_to_rows(events: list[PassengerEvent]) -> list[tuple]:
    """Render PassengerEvents as reader result rows (the handoff-0005
    canonical.passenger_events columns), in the reader's SQL order
    (event_timestamp, passenger_event_id, source_record_id) — the fake
    stands in for the database, so it honors the ORDER BY."""
    ordered = sorted(
        events,
        key=lambda e: (e.event_timestamp, e.passenger_event_id, e.source_record_id),
    )
    return [
        (
            e.event_timestamp,
            e.service_date,
            e.passenger_event_id,
            e.vehicle_id,
            e.trip_id,
            e.trip_stop_sequence,
            e.event_type,
            e.event_count,
            e.source,
            e.source_record_id,
        )
        for e in ordered
    ]


class RecordingCursor:
    def __init__(self, conn: "RecordingConnection"):
        self._conn = conn
        self._pending_one: tuple | None = None
        self._pending_all: list[tuple] = []

    def execute(self, sql, params=None):
        conn = self._conn
        conn.executed.append((sql, params))
        self._pending_one = None
        self._pending_all = []
        if sql.lstrip().upper().startswith("SELECT"):
            # Dispatch canned rows per reader query (handoff 0005 added the
            # passenger-events and operated-trips SELECTs alongside the
            # positions SELECT).
            if "canonical.passenger_events" in sql:
                self._pending_all = list(conn.passenger_event_rows)
            elif "SELECT DISTINCT trip_id" in sql:
                self._pending_all = list(conn.operated_trip_rows)
            else:
                self._pending_all = list(conn.position_rows)
        elif "INSERT INTO dq.issues" in sql:
            if conn.fail_on == "dq.issues":
                raise RuntimeError("simulated dq.issues insert failure")
            conn.issue_seq += 1
            self._pending_one = (f"issue-{conn.issue_seq:04d}",)
        elif "INSERT INTO computed.metric_values" in sql:
            if conn.fail_on == "computed.metric_values":
                raise RuntimeError("simulated metric_values insert failure")
            conn.mv_seq += 1
            self._pending_one = (f"mv-{conn.mv_seq:04d}",)
        # lineage.edges: no RETURNING, nothing to stage.

    def fetchone(self):
        return self._pending_one

    def fetchall(self):
        return self._pending_all


class RecordingConnection:
    """DB-API-shaped fake that records statements and transaction boundaries."""

    def __init__(
        self,
        position_rows: list[tuple] | None = None,
        fail_on: str | None = None,
        passenger_event_rows: list[tuple] | None = None,
        operated_trip_rows: list[tuple] | None = None,
    ):
        self.position_rows = position_rows or []
        self.passenger_event_rows = passenger_event_rows or []
        self.operated_trip_rows = operated_trip_rows or []
        self.fail_on = fail_on
        self.executed: list[tuple[str, tuple | None]] = []
        # Each commit records how many statements were executed at that point,
        # so tests can assert exactly which statements a transaction covered.
        self.commits: list[int] = []
        self.rollback_count = 0
        self.issue_seq = 0
        self.mv_seq = 0

    def cursor(self):
        return RecordingCursor(self)

    def commit(self):
        self.commits.append(len(self.executed))

    def rollback(self):
        self.rollback_count += 1

    # Convenience views for assertions -------------------------------------

    def statements_matching(self, fragment: str) -> list[tuple[str, tuple | None]]:
        return [(sql, params) for sql, params in self.executed if fragment in sql]
