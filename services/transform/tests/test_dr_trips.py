"""DR trips normalizer (handoff 0013): CSV bytes built in-test, plus the
consumer routing and writer insert for the raw.dr.trips path."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import json

from conftest import FakeConnection, make_envelope_dict, sha256_hex

from headway_transform import consumer
from headway_transform.dr_trips import (
    TRANSFORM_NAME,
    TRANSFORM_VERSION,
    normalize,
)
from headway_transform.writer import DbWriter

RECORD_ID = "cd" * 32

HEADER = (
    "dr_trip_id,service_date,vehicle_id,mode,tos,request_timestamp,"
    "dispatch_timestamp,pickup_timestamp,dropoff_timestamp,pickup_lat,"
    "pickup_lon,dropoff_lat,dropoff_lon,onboard_miles,distance_source,"
    "pickup_odometer_miles,dropoff_odometer_miles,riders,"
    "attendants_companions,ada_related,sponsored,sponsor,no_show,"
    "interruption_after,driver_shift_id,dispatching_point_id"
)

GOOD_ROW = (
    "drt-1,2026-07-14,van-1,DR,DO,2026-07-14T12:40:00Z,2026-07-14T12:50:00Z,"
    "2026-07-14T13:00:00Z,2026-07-14T13:20:00Z,42.36,-71.06,42.37,-71.11,"
    "4.20,odometer,10000.00,10004.20,2,1,true,false,,false,none,shift-1,dp-1"
)


def build_csv(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def test_happy_path_row_edge_and_source_carried() -> None:
    csv_bytes = build_csv(
        GOOD_ROW,
        # A sponsored no-show with minimal optional data: revenue-time row,
        # zero boardings, distances unmeasured (empty stays NULL).
        "drt-2,2026-07-14,van-1,DR,DO,,,2026-07-14T14:00:00Z,"
        "2026-07-14T14:05:00Z,,,,,,,,,0,0,false,true,Medicaid NEMT,true,"
        "lunch,shift-1,dp-1",
    )
    rows, edges, findings = normalize(csv_bytes, RECORD_ID, "dr")

    assert findings == []
    assert len(rows) == 2
    first, second = rows

    assert first.dr_trip_id == "drt-1"
    assert first.service_date == date(2026, 7, 14)
    assert first.tos == "DO"
    assert first.pickup_timestamp == datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
    assert first.dropoff_timestamp == datetime(2026, 7, 14, 13, 20, tzinfo=timezone.utc)
    assert first.onboard_miles == Decimal("4.20")
    assert first.pickup_odometer_miles == Decimal("10000.00")
    assert first.dropoff_odometer_miles == Decimal("10004.20")
    assert first.riders == 2 and first.attendants_companions == 1
    assert first.ada_related is True and first.sponsored is False
    assert first.sponsor is None
    assert first.no_show is False
    assert first.interruption_after == "none"
    assert first.driver_shift_id == "shift-1"
    assert first.dispatching_point_id == "dp-1"

    assert second.no_show is True
    assert second.riders == 0 and second.attendants_companions == 0
    assert second.sponsored is True and second.sponsor == "Medicaid NEMT"
    # Unmeasured distances stay NULL — never coalesced to 0.
    assert second.onboard_miles is None
    assert second.pickup_odometer_miles is None
    assert second.dropoff_odometer_miles is None
    assert second.request_timestamp is None and second.dispatch_timestamp is None
    assert second.interruption_after == "lunch"

    # Envelope source carried verbatim onto every row.
    assert all(r.source == "dr" for r in rows)
    assert all(r.source_record_id == RECORD_ID for r in rows)

    # Exactly one lineage edge per canonical row, anchored to the file record.
    assert len(edges) == 2
    assert [e.output_id for e in edges] == [
        f"drt-1|2026-07-14T13:00:00Z|{RECORD_ID}",
        f"drt-2|2026-07-14T14:00:00Z|{RECORD_ID}",
    ]
    for edge in edges:
        assert edge.output_kind == "canonical.dr_trips"
        assert edge.transform_name == TRANSFORM_NAME == "normalize_dr_trips"
        assert edge.transform_version == TRANSFORM_VERSION == "0.1.1"
        assert edge.input_kind == "raw.records"
        assert edge.input_id == RECORD_ID


def test_simulated_source_carried_verbatim() -> None:
    """Handoff 0013 binding rule (inherited from handoff 0005): simulator
    output stays permanently distinguishable — source 'dr_simulated' flows
    verbatim to every row."""
    rows, _edges, findings = normalize(build_csv(GOOD_ROW), RECORD_ID, "dr_simulated")
    assert findings == []
    assert [r.source for r in rows] == ["dr_simulated"]


def test_contradictions_quarantined_never_repaired() -> None:
    csv_bytes = build_csv(
        GOOD_ROW,
        # dropoff before pickup.
        GOOD_ROW.replace("2026-07-14T13:20:00Z", "2026-07-14T12:59:00Z").replace(
            "drt-1", "drt-neg"
        ),
        # decreasing odometer.
        GOOD_ROW.replace("10004.20", "9999.00").replace("drt-1", "drt-odo"),
        # sponsored without a sponsor label.
        GOOD_ROW.replace(",true,false,,false,", ",true,true,,false,").replace(
            "drt-1", "drt-nosponsor"
        ),
        # sponsor label on an unsponsored trip.
        GOOD_ROW.replace(",true,false,,false,", ",true,false,Medicaid NEMT,false,").replace(
            "drt-1", "drt-strayspons"
        ),
        # no-show carrying boardings.
        GOOD_ROW.replace(",false,none,", ",true,none,").replace("drt-1", "drt-noshow"),
    )
    rows, edges, findings = normalize(csv_bytes, RECORD_ID, "dr")

    assert [r.dr_trip_id for r in rows] == ["drt-1"]
    assert len(edges) == 1
    malformed = [f for f in findings if f.issue_type == "malformed_dr_trip"]
    assert len(malformed) == 5  # one per quarantined row — none silently skipped
    assert all(f.severity == "warning" for f in malformed)
    assert all(f.source_record_ids == [RECORD_ID] for f in malformed)
    descriptions = "\n".join(f.description for f in malformed)
    assert "precedes" in descriptions  # negative duration named
    assert "decreasing odometer" in descriptions
    assert "sponsor is empty" in descriptions
    assert "unsponsored trip" in descriptions
    assert "never a boarding" in descriptions


def test_bad_enums_and_types_quarantined() -> None:
    csv_bytes = build_csv(
        GOOD_ROW.replace(",DO,", ",XX,").replace("drt-1", "drt-tos"),
        GOOD_ROW.replace(",DR,", ",MB,").replace("drt-1", "drt-mode"),
        GOOD_ROW.replace(",none,", ",coffee,").replace("drt-1", "drt-int"),
        GOOD_ROW.replace(",2,1,", ",-1,1,").replace("drt-1", "drt-riders"),
        GOOD_ROW.replace(",true,false,", ",maybe,false,").replace("drt-1", "drt-bool"),
        # naive pickup timestamp: the timezone is never guessed.
        GOOD_ROW.replace("2026-07-14T13:00:00Z", "2026-07-14T13:00:00").replace(
            "drt-1", "drt-naive"
        ),
    )
    rows, _edges, findings = normalize(csv_bytes, RECORD_ID, "dr")
    assert rows == []
    assert len(findings) == 6
    descriptions = "\n".join(f.description for f in findings)
    assert "'XX'" in descriptions
    assert "'MB'" in descriptions
    assert "'coffee'" in descriptions
    assert "-1" in descriptions
    assert "'maybe'" in descriptions
    assert "no UTC offset" in descriptions


def test_empty_file_is_single_info_finding() -> None:
    for csv_bytes in (b"", (HEADER + "\n").encode("utf-8")):
        rows, edges, findings = normalize(csv_bytes, RECORD_ID, "dr")
        assert rows == [] and edges == []
        assert len(findings) == 1
        assert findings[0].issue_type == "empty_dr_trips_file"
        assert findings[0].severity == "info"
        assert findings[0].source_record_ids == [RECORD_ID]


def test_consumer_routes_dr_topic_with_fetcher() -> None:
    """Replay path: an object_ref envelope on raw.dr.trips is fetched,
    normalized, and written (rows + edges + raw record)."""
    csv_bytes = build_csv(GOOD_ROW)
    record_id = sha256_hex(csv_bytes)
    key = f"raw/dr/{record_id}.csv"
    value = json.dumps(
        make_envelope_dict(
            csv_bytes,
            source="dr_simulated",
            connector="headway-dr",
            content_type="text/csv",
            payload_encoding="object_ref",
            payload=key,
        )
    ).encode()
    conn = FakeConnection()
    writer = DbWriter(conn)
    consumer.process_message(
        writer, consumer.TOPIC_DR_TRIPS, value, object_fetcher={key: csv_bytes}.__getitem__
    )
    assert len(conn.sql_for("INSERT INTO raw.records")) == 1
    inserts = conn.sql_for("INSERT INTO canonical.dr_trips")
    assert len(inserts) == 1
    assert "ON CONFLICT (dr_trip_id, pickup_timestamp, source_record_id) DO NOTHING" in inserts[0][0]
    params = inserts[0][1]
    assert params[2] == "drt-1"  # dr_trip_id
    assert params[-2] == "dr_simulated"  # source
    assert params[-1] == record_id  # source_record_id
    edges = conn.sql_for("INSERT INTO lineage.edges")
    assert len(edges) == 1
    assert edges[0][1][0] == "canonical.dr_trips"


def test_consumer_dr_object_ref_without_fetcher_is_blocking_issue() -> None:
    csv_bytes = build_csv(GOOD_ROW)
    value = json.dumps(
        make_envelope_dict(
            csv_bytes,
            source="dr",
            connector="headway-dr",
            content_type="text/csv",
            payload_encoding="object_ref",
            payload="raw/dr/whatever.csv",
        )
    ).encode()
    conn = FakeConnection()
    consumer.process_message(DbWriter(conn), consumer.TOPIC_DR_TRIPS, value, None)
    assert conn.sql_for("INSERT INTO canonical.dr_trips") == []
    issues = conn.sql_for("INSERT INTO dq.issues")
    assert len(issues) == 1
    assert issues[0][1][0] == "object_ref_unavailable"
    assert issues[0][1][1] == "blocking"


def test_writer_binds_nulls_not_zeros(fake_connection) -> None:
    """An unmeasured distance binds None, never 0 (migration 0021 rule)."""
    csv_bytes = build_csv(
        "drt-9,2026-07-14,van-2,DR,TX,,,2026-07-14T15:00:00Z,"
        "2026-07-14T15:10:00Z,,,,,,,,,1,0,false,false,,false,none,,",
    )
    rows, _edges, findings = normalize(csv_bytes, RECORD_ID, "dr")
    assert findings == []
    DbWriter(fake_connection).insert_dr_trips(rows)
    inserts = fake_connection.sql_for("INSERT INTO canonical.dr_trips")
    assert len(inserts) == 1
    params = inserts[0][1]
    # onboard_miles, distance_source, both odometer readings: None.
    assert params[12] is None and params[13] is None
    assert params[14] is None and params[15] is None
    # driver_shift_id / dispatching_point_id empty -> None.
    assert params[23] is None and params[24] is None
