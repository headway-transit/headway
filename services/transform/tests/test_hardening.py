"""2026-07-13 hardening-pass regressions (Batch B — intake robustness).

Pins the reviewers' three reproduced hostile-CSV inputs — an oversized
field, a NUL cell, and a stray/unterminated quote — against every CSV
normalizer: each becomes a PER-ROW quarantine finding while the remaining
good rows still land. Also pins the decompression budget (zip-bomb guard),
the capped object fetch, and the consumer's transform_failure finding
carrying the failure's actual message.
"""

from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest

from conftest import FakeConnection, sha256_hex

from headway_transform import consumer, dr_trips, gtfs_static, tides_passenger_events
from headway_transform.__main__ import read_capped
from headway_transform.consumer import ObjectTooLargeError, run_loop
from headway_transform.row_guard import field_problems, iter_rows
from headway_transform.writer import DbWriter

RECORD_ID = "ab" * 32

OVERSIZED = "x" * (csv.field_size_limit() + 10)


# --------------------------------------------------------------------------
# row_guard unit behavior
# --------------------------------------------------------------------------

def test_iter_rows_survives_mid_iteration_csv_error() -> None:
    text = f"a,b\n1,ok\n2,{OVERSIZED}\n3,fine\n"
    out = list(iter_rows(csv.DictReader(io.StringIO(text, newline=""))))
    # Row 1 parses, row 2 is a captured error, row 3 still parses.
    assert out[0][1] == {"a": "1", "b": "ok"}
    assert out[1][1] is None and "field larger than field limit" in out[1][2]
    assert out[2][1] == {"a": "3", "b": "fine"}


def test_field_problems_detects_nul_and_absorbed_lines() -> None:
    assert field_problems({"a": "clean"}) == []
    [nul] = field_problems({"a": "bad\x00cell"})
    assert "NUL byte" in nul
    [merge] = field_problems({"a": "one\ntwo\nthree"})
    assert "2 absorbed line(s)" in merge


# --------------------------------------------------------------------------
# DR trips: the three reviewer inputs, per-row quarantine, good rows land
# --------------------------------------------------------------------------

DR_HEADER = (
    "dr_trip_id,service_date,vehicle_id,mode,tos,pickup_timestamp,"
    "dropoff_timestamp,riders,attendants_companions,ada_related,"
    "sponsored,sponsor,no_show"
)


def dr_row(trip_id: str, vehicle: str = "van-1") -> str:
    return (
        f"{trip_id},2026-07-14,{vehicle},DR,DO,2026-07-14T13:00:00Z,"
        "2026-07-14T13:20:00Z,1,0,true,false,,false"
    )


def test_dr_oversized_field_quarantines_one_row_rest_land() -> None:
    csv_bytes = "\n".join(
        [DR_HEADER, dr_row("drt-1"), dr_row("drt-2", OVERSIZED), dr_row("drt-3")]
    ).encode()
    rows, edges, findings = dr_trips.normalize(csv_bytes, RECORD_ID, "dr")
    assert [r.dr_trip_id for r in rows] == ["drt-1", "drt-3"]
    assert len(edges) == 2
    [finding] = findings
    assert finding.issue_type == "malformed_dr_trip"
    assert "field larger than field limit" in finding.description
    assert "row 1" in finding.description


def test_dr_nul_cell_quarantined_before_it_reaches_postgres() -> None:
    csv_bytes = "\n".join(
        [DR_HEADER, dr_row("drt-1"), dr_row("drt\x002"), dr_row("drt-3")]
    ).encode()
    rows, _edges, findings = dr_trips.normalize(csv_bytes, RECORD_ID, "dr")
    assert [r.dr_trip_id for r in rows] == ["drt-1", "drt-3"]
    [finding] = findings
    assert finding.issue_type == "malformed_dr_trip"
    assert "NUL byte" in finding.description
    # The poisoned value must never appear in an emitted row.
    assert all("\x00" not in r.dr_trip_id for r in rows)


def test_dr_stray_quote_absorption_counted_not_silent() -> None:
    # The stray quote on row 1 absorbs rows 2-3 into one field; previously
    # the csv module swallowed them without a trace.
    absorbed = dr_row('"drt-2')  # unterminated opening quote
    csv_bytes = "\n".join(
        [DR_HEADER, dr_row("drt-1"), absorbed, dr_row("drt-3"), dr_row("drt-4")]
    ).encode()
    rows, _edges, findings = dr_trips.normalize(csv_bytes, RECORD_ID, "dr")
    assert [r.dr_trip_id for r in rows] == ["drt-1"]
    assert len(findings) == 1
    assert findings[0].issue_type == "malformed_dr_trip"
    assert "absorbed line(s)" in findings[0].description
    assert "never silently swallowed" in findings[0].description


# --------------------------------------------------------------------------
# TIDES passenger events: the same three inputs
# --------------------------------------------------------------------------

TIDES_HEADER = (
    "passenger_event_id,service_date,event_timestamp,trip_id_performed,"
    "trip_stop_sequence,event_type,vehicle_id,event_count"
)


def tides_row(event_id: str) -> str:
    return (
        f"{event_id},2026-07-08,2026-07-08T12:00:00Z,trip-1,1,"
        "Passenger boarded,veh-1,2"
    )


def test_tides_oversized_field_quarantines_one_row_rest_land() -> None:
    csv_bytes = "\n".join(
        [TIDES_HEADER, tides_row("pe-1"), tides_row(OVERSIZED), tides_row("pe-3")]
    ).encode()
    rows, edges, findings = tides_passenger_events.normalize(
        csv_bytes, RECORD_ID, "tides"
    )
    assert [r.passenger_event_id for r in rows] == ["pe-1", "pe-3"]
    assert len(edges) == 2
    [finding] = findings
    assert finding.issue_type == "malformed_passenger_event"
    assert "field larger than field limit" in finding.description


def test_tides_nul_cell_quarantined_before_it_reaches_postgres() -> None:
    csv_bytes = "\n".join(
        [TIDES_HEADER, tides_row("pe-1"), tides_row("pe\x002"), tides_row("pe-3")]
    ).encode()
    rows, _edges, findings = tides_passenger_events.normalize(
        csv_bytes, RECORD_ID, "tides"
    )
    assert [r.passenger_event_id for r in rows] == ["pe-1", "pe-3"]
    [finding] = findings
    assert "NUL byte" in finding.description


def test_tides_stray_quote_absorption_counted_not_silent() -> None:
    csv_bytes = "\n".join(
        [
            TIDES_HEADER,
            tides_row("pe-1"),
            tides_row('"pe-2'),  # unterminated opening quote
            tides_row("pe-3"),
            tides_row("pe-4"),
        ]
    ).encode()
    rows, _edges, findings = tides_passenger_events.normalize(
        csv_bytes, RECORD_ID, "tides"
    )
    assert [r.passenger_event_id for r in rows] == ["pe-1"]
    assert len(findings) == 1
    assert "absorbed line(s)" in findings[0].description


# --------------------------------------------------------------------------
# GTFS static: per-row quarantine + decompression budget
# --------------------------------------------------------------------------

def build_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


GTFS_FILES = {
    "agency.txt": "agency_id,agency_name,agency_timezone\nA1,Example Transit,America/New_York\n",
    "routes.txt": "route_id,route_short_name,route_long_name,route_type\nR1,5,Fifth,3\n",
    "trips.txt": "trip_id,route_id,service_id,direction_id\nT1,R1,WKDY,0\nT2,R1,WKDY,1\n",
    "stops.txt": "stop_id,stop_name,stop_lat,stop_lon,location_type\nS1,First,42.35,-71.06,0\n",
    "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nT1,10:40:00,10:40:30,S1,1\n",
}


def test_gtfs_nul_cell_quarantines_row_not_file() -> None:
    files = dict(GTFS_FILES)
    files["trips.txt"] = (
        "trip_id,route_id,service_id,direction_id\n"
        "T1,R1,WKDY,0\n"
        "T\x00bad,R1,WKDY,0\n"
        "T2,R1,WKDY,1\n"
    )
    _r, trips, _s, _st, _agencies, _e, findings = gtfs_static.normalize(
        build_zip(files), RECORD_ID
    )
    assert [t.trip_id for t in trips] == ["T1", "T2"]
    nul_findings = [f for f in findings if "NUL byte" in f.description]
    assert len(nul_findings) == 1
    assert nul_findings[0].issue_type == "malformed_entity"


def test_gtfs_oversized_field_quarantines_row_not_file() -> None:
    files = dict(GTFS_FILES)
    files["routes.txt"] = (
        "route_id,route_short_name,route_long_name,route_type\n"
        "R1,5,Fifth,3\n"
        f"R2,5,{OVERSIZED},3\n"
        "R3,6,Sixth,3\n"
    )
    routes, _t, _s, _st, _agencies, _e, findings = gtfs_static.normalize(
        build_zip(files), RECORD_ID
    )
    assert [r.route_id for r in routes] == ["R1", "R3"]
    assert any("field larger than field limit" in f.description for f in findings)


def test_gtfs_member_over_decompression_budget_aborts_with_named_limit() -> None:
    # Small limits injected for test speed; the real defaults are generous.
    zip_bytes = build_zip(GTFS_FILES)
    routes, trips, stops, stop_times, _agencies, edges, findings = gtfs_static.normalize(
        zip_bytes, RECORD_ID, max_member_bytes=16
    )
    assert routes == [] and trips == [] and stops == [] and stop_times == []
    assert edges == []
    [finding] = findings
    assert finding.issue_type == "transform_failure"
    assert finding.severity == "blocking"
    assert "16 bytes" in finding.description
    assert "ABORTED" in finding.description


def test_gtfs_total_decompression_budget_enforced_across_members() -> None:
    zip_bytes = build_zip(GTFS_FILES)
    _r, _t, _s, _st, _agencies, _e, findings = gtfs_static.normalize(
        zip_bytes, RECORD_ID, max_total_bytes=100
    )
    [finding] = findings
    assert finding.issue_type == "transform_failure"
    assert "whole-archive" in finding.description
    assert "100 bytes" in finding.description


# --------------------------------------------------------------------------
# Capped object fetch + the consumer's quarantine finding
# --------------------------------------------------------------------------

def test_read_capped_returns_within_budget_and_aborts_over() -> None:
    chunks = [b"a" * 10, b"b" * 10]
    assert read_capped(iter(chunks), 20, "raw/x") == b"a" * 10 + b"b" * 10
    with pytest.raises(ObjectTooLargeError) as exc_info:
        read_capped(iter([b"a" * 10, b"b" * 10, b"c"]), 20, "raw/x")
    assert "20-byte fetch limit" in str(exc_info.value)
    assert "HEADWAY_MAX_OBJECT_BYTES" in str(exc_info.value)


class OneMessageSource:
    def __init__(self, topic: str, value: bytes) -> None:
        self.messages = [(topic, None, value)]

    def poll(self):
        return self.messages.pop(0) if self.messages else None


def _object_ref_envelope(topic_payload: bytes, source: str) -> bytes:
    return json.dumps(
        {
            "envelope_version": 0,
            "record_id": sha256_hex(topic_payload),
            "source": source,
            "connector": "headway-dr",
            "connector_version": "0.2.0",
            "fetched_at": "2026-07-13T12:00:00Z",
            "content_type": "text/csv",
            "payload_encoding": "object_ref",
            "payload": "raw/dr/" + sha256_hex(topic_payload) + ".csv",
            "parse_status": "ok",
        }
    ).encode()


def test_oversize_object_fetch_becomes_transform_failure_naming_limit() -> None:
    payload = b"whatever"
    value = _object_ref_envelope(payload, "dr")

    def exploding_fetcher(object_ref: str) -> bytes:
        # What __main__.py's capped fetcher raises with a small limit.
        return read_capped(iter([b"123456", b"789"]), 5, object_ref)

    connection = FakeConnection()
    processed = run_loop(
        OneMessageSource(consumer.TOPIC_DR_TRIPS, value),
        DbWriter(connection),
        exploding_fetcher,
    )
    assert processed == 1
    assert connection.rollbacks == 1
    dq = connection.sql_for("dq.issues")
    assert len(dq) == 1
    _sql, params = dq[0]
    assert params[0] == "transform_failure"
    # The finding must NAME the limit (via the exception's message).
    assert "ObjectTooLargeError" in params[3]
    assert "5-byte fetch limit" in params[3]


def test_transform_failure_finding_carries_exception_message() -> None:
    payload = b"whatever"
    value = _object_ref_envelope(payload, "dr")

    def failing_fetcher(object_ref: str) -> bytes:
        raise RuntimeError("minio unreachable at minio:9000")

    connection = FakeConnection()
    run_loop(
        OneMessageSource(consumer.TOPIC_DR_TRIPS, value),
        DbWriter(connection),
        failing_fetcher,
    )
    dq = connection.sql_for("dq.issues")
    assert len(dq) == 1
    _sql, params = dq[0]
    assert params[0] == "transform_failure"
    assert "RuntimeError" in params[3]
    assert "minio unreachable" in params[3]
