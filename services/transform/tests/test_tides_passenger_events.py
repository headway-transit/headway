"""TIDES passenger_events normalizer: CSV bytes built in-test."""

from __future__ import annotations

from datetime import date, datetime, timezone

from headway_transform.tides_passenger_events import (
    TRANSFORM_NAME,
    TRANSFORM_VERSION,
    normalize,
)

RECORD_ID = "ab" * 32

HEADER = (
    "passenger_event_id,service_date,event_timestamp,trip_id_performed,"
    "trip_stop_sequence,event_type,vehicle_id,event_count"
)


def build_csv(*rows: str, header: str = HEADER) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def test_happy_path_rows_edges_and_source_carried() -> None:
    csv_bytes = build_csv(
        "PE-1,2026-07-08,2026-07-08T12:00:00Z,T1,1,Passenger boarded,bus-1,2",
        "PE-2,2026-07-08,2026-07-08T12:05:00-04:00,T1,2,Passenger alighted,bus-1,1",
        "PE-3,2026-07-08,2026-07-08T12:06:00Z,,3,Door opened,bus-1,",
    )
    rows, edges, findings = normalize(csv_bytes, RECORD_ID, "tides")

    assert findings == []
    assert [
        (
            r.passenger_event_id,
            r.service_date,
            r.event_timestamp,
            r.trip_id,
            r.trip_stop_sequence,
            r.event_type,
            r.event_count,
        )
        for r in rows
    ] == [
        (
            "PE-1",
            date(2026, 7, 8),
            datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc),
            "T1",
            1,
            "Passenger boarded",
            2,
        ),
        (
            "PE-2",
            date(2026, 7, 8),
            datetime(2026, 7, 8, 16, 5, tzinfo=timezone.utc),
            "T1",
            2,
            "Passenger alighted",
            1,
        ),
        (
            "PE-3",
            date(2026, 7, 8),
            datetime(2026, 7, 8, 12, 6, tzinfo=timezone.utc),
            None,  # trip_id_performed empty → NULL, never guessed
            3,
            "Door opened",
            None,  # event_count empty → NULL preserved, never coalesced
        ),
    ]
    # Envelope source carried verbatim onto every row.
    assert all(r.source == "tides" for r in rows)
    assert all(r.source_record_id == RECORD_ID for r in rows)

    # Exactly one lineage edge per canonical row, anchored to the file record.
    assert len(edges) == len(rows) == 3
    assert [e.output_id for e in edges] == [
        f"PE-1|2026-07-08T12:00:00Z|{RECORD_ID}",
        f"PE-2|2026-07-08T16:05:00Z|{RECORD_ID}",  # rendered in UTC
        f"PE-3|2026-07-08T12:06:00Z|{RECORD_ID}",
    ]
    for edge in edges:
        assert edge.output_kind == "canonical.passenger_events"
        assert edge.transform_name == TRANSFORM_NAME == "normalize_tides_passenger_events"
        assert edge.transform_version == TRANSFORM_VERSION == "0.1.1"
        assert edge.input_kind == "raw.records"
        assert edge.input_id == RECORD_ID


def test_simulated_source_carried_verbatim() -> None:
    """Handoff 0005 binding rule: simulator output stays permanently
    distinguishable — source 'tides_simulated' flows verbatim to every row."""
    csv_bytes = build_csv(
        "PE-1,2026-07-08,2026-07-08T12:00:00Z,T1,1,Passenger boarded,bus-1,1",
    )
    rows, _edges, findings = normalize(csv_bytes, RECORD_ID, "tides_simulated")
    assert findings == []
    assert [r.source for r in rows] == ["tides_simulated"]


def test_malformed_row_quarantined_other_rows_still_land() -> None:
    csv_bytes = build_csv(
        "PE-1,2026-07-08,2026-07-08T12:00:00Z,T1,1,Passenger boarded,bus-1,1",
        "PE-2,2026-07-08,2026-07-08T12:01:00Z,T1,2,Passenger boarded,,1",  # no vehicle_id
        "PE-3,2026-07-08,not-a-timestamp,T1,3,Passenger boarded,bus-1,1",
        "PE-4,2026-07-08,2026-07-08T12:03:00Z,T1,4,Passenger boarded,bus-1,many",
        "PE-5,2026-07-08,2026-07-08T12:04:00Z,T1,5,Passenger alighted,bus-1,3",
    )
    rows, edges, findings = normalize(csv_bytes, RECORD_ID, "tides")

    assert [r.passenger_event_id for r in rows] == ["PE-1", "PE-5"]
    assert len(edges) == 2
    malformed = [f for f in findings if f.issue_type == "malformed_passenger_event"]
    assert len(malformed) == 3  # one per quarantined row — none silently skipped
    assert all(f.severity == "warning" for f in malformed)
    assert all(f.source_record_ids == [RECORD_ID] for f in malformed)
    # Row numbers cited in the descriptions (0-based over data rows).
    assert "row 1" in malformed[0].description
    assert "vehicle_id" in malformed[0].description
    assert "row 2" in malformed[1].description
    assert "not-a-timestamp" in malformed[1].description
    assert "row 3" in malformed[2].description
    assert "event_count" in malformed[2].description
    assert all(RECORD_ID in f.description for f in malformed)


def test_unknown_event_type_is_finding_not_guess() -> None:
    csv_bytes = build_csv(
        "PE-1,2026-07-08,2026-07-08T12:00:00Z,T1,1,Passenger Boarded,bus-1,1",
    )
    rows, edges, findings = normalize(csv_bytes, RECORD_ID, "tides")

    # 'Passenger Boarded' (wrong case) is NOT in the verified TIDES enum.
    assert rows == [] and edges == []
    assert len(findings) == 1
    assert findings[0].issue_type == "malformed_passenger_event"
    assert "Passenger Boarded" in findings[0].description


def test_event_count_null_preserved_never_zero() -> None:
    # Column present but empty / TIDES missing-value token, and column absent
    # entirely: all three land as None — never coalesced to 0 (or the TIDES
    # documented default of 1).
    csv_bytes = build_csv(
        "PE-1,2026-07-08,2026-07-08T12:00:00Z,T1,1,Passenger boarded,bus-1,",
        "PE-2,2026-07-08,2026-07-08T12:01:00Z,T1,2,Passenger boarded,bus-1,NA",
    )
    rows, _edges, findings = normalize(csv_bytes, RECORD_ID, "tides")
    assert findings == []
    assert [r.event_count for r in rows] == [None, None]
    assert all(r.event_count is None for r in rows)  # explicitly None, NOT 0

    header_without_count = HEADER.rsplit(",", 1)[0]
    csv_bytes = build_csv(
        "PE-3,2026-07-08,2026-07-08T12:02:00Z,T1,3,Passenger alighted,bus-1",
        header=header_without_count,
    )
    rows, _edges, findings = normalize(csv_bytes, RECORD_ID, "tides")
    assert findings == []
    assert [r.event_count for r in rows] == [None]


def test_naive_timestamp_is_finding_not_guess() -> None:
    csv_bytes = build_csv(
        "PE-1,2026-07-08,2026-07-08T12:00:00,T1,1,Passenger boarded,bus-1,1",
    )
    rows, edges, findings = normalize(csv_bytes, RECORD_ID, "tides")

    assert rows == [] and edges == []
    assert len(findings) == 1
    assert findings[0].issue_type == "malformed_passenger_event"
    assert "no UTC offset" in findings[0].description
    assert findings[0].source_record_ids == [RECORD_ID]


def test_empty_file_is_single_info_finding() -> None:
    for csv_bytes in (b"", (HEADER + "\n").encode("utf-8")):
        rows, edges, findings = normalize(csv_bytes, RECORD_ID, "tides")
        assert rows == [] and edges == []
        assert len(findings) == 1
        assert findings[0].issue_type == "empty_passenger_events_file"
        assert findings[0].severity == "info"
        assert findings[0].source_record_ids == [RECORD_ID]
