"""GTFS static loader: in-test zips built with zipfile."""

from __future__ import annotations

import io
import zipfile

from headway_transform.gtfs_static import (
    TRANSFORM_NAME,
    TRANSFORM_VERSION,
    normalize,
)

RECORD_ID = "ab" * 32


def build_zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    return buf.getvalue()


ROUTES_TXT = (
    "route_id,route_short_name,route_long_name,route_type\n"
    "R1,5,Fifth Street Local,3\n"
    "R2,,Green Line,0\n"
)
TRIPS_TXT = (
    "trip_id,route_id,service_id,direction_id\n"
    "T1,R1,WKDY,0\n"
    "T2,R1,WKDY,1\n"
    "T3,R2,SAT,\n"
)


def test_routes_and_trips_normalized_with_edges() -> None:
    routes, trips, edges, findings = normalize(
        build_zip({"routes.txt": ROUTES_TXT, "trips.txt": TRIPS_TXT}), RECORD_ID
    )

    assert findings == []
    assert [(r.route_id, r.short_name, r.long_name, r.mode) for r in routes] == [
        ("R1", "5", "Fifth Street Local", "bus"),
        ("R2", None, "Green Line", "tram"),
    ]
    assert [(t.trip_id, t.route_id, t.service_id, t.direction_id) for t in trips] == [
        ("T1", "R1", "WKDY", 0),
        ("T2", "R1", "WKDY", 1),
        ("T3", "R2", "SAT", None),
    ]
    # block_id is OPTIONAL per GTFS: an absent column is valid — NULL on every
    # row and NO DQ finding (asserted above: findings == []).
    assert [t.block_id for t in trips] == [None, None, None]

    # Exactly one lineage edge per canonical row, anchored to the feed record.
    assert len(edges) == len(routes) + len(trips)
    route_edges = [e for e in edges if e.output_kind == "canonical.routes"]
    trip_edges = [e for e in edges if e.output_kind == "canonical.trips"]
    assert sorted(e.output_id for e in route_edges) == ["R1", "R2"]
    assert sorted(e.output_id for e in trip_edges) == ["T1", "T2", "T3"]
    for edge in edges:
        assert edge.transform_name == TRANSFORM_NAME == "normalize_gtfs_static"
        assert edge.transform_version == TRANSFORM_VERSION == "0.2.0"
        assert edge.input_kind == "raw.records"
        assert edge.input_id == RECORD_ID


def test_trips_block_id_parsed_when_column_present() -> None:
    """block_id column (handoff 0003): non-empty values parsed, empty → NULL,
    never a DQ finding — the field is optional per the GTFS spec."""
    trips_txt = (
        "trip_id,route_id,service_id,direction_id,block_id\n"
        "T1,R1,WKDY,0,B-77\n"
        "T2,R1,WKDY,1,B-77\n"
        "T3,R2,SAT,, \n"  # whitespace-only block_id → NULL, no finding
    )
    _routes, trips, edges, findings = normalize(
        build_zip({"routes.txt": ROUTES_TXT, "trips.txt": trips_txt}), RECORD_ID
    )

    assert findings == []
    assert [(t.trip_id, t.block_id) for t in trips] == [
        ("T1", "B-77"),
        ("T2", "B-77"),
        ("T3", None),
    ]
    assert len([e for e in edges if e.output_kind == "canonical.trips"]) == 3


def test_unknown_route_type_gets_mode_unknown_plus_finding() -> None:
    routes_txt = (
        "route_id,route_short_name,route_long_name,route_type\n"
        "RX,X,Mystery Line,99\n"
    )
    routes, _trips, edges, findings = normalize(
        build_zip({"routes.txt": routes_txt, "trips.txt": "trip_id,route_id,service_id\n"}),
        RECORD_ID,
    )

    assert len(routes) == 1
    assert routes[0].mode == "unknown"  # emitted, not dropped — but flagged
    assert len([e for e in edges if e.output_id == "RX"]) == 1
    unknown = [f for f in findings if f.issue_type == "unknown_route_type"]
    assert len(unknown) == 1
    assert unknown[0].severity == "warning"
    assert unknown[0].source_record_ids == [RECORD_ID]


def test_missing_required_files_are_blocking_findings() -> None:
    routes, trips, edges, findings = normalize(
        build_zip({"agency.txt": "agency_id\nA1\n"}), RECORD_ID
    )
    assert routes == [] and trips == [] and edges == []
    types = sorted(f.issue_type for f in findings)
    assert types == ["malformed_entity", "malformed_entity"]
    assert all(f.severity == "blocking" for f in findings)


def test_bad_zip_is_undecodable_payload_finding_not_exception() -> None:
    routes, trips, edges, findings = normalize(b"not a zip at all", RECORD_ID)
    assert routes == [] and trips == [] and edges == []
    assert len(findings) == 1
    assert findings[0].issue_type == "undecodable_payload"
    assert findings[0].source_record_ids == [RECORD_ID]


def test_trip_missing_required_fields_quarantined_row_by_row() -> None:
    trips_txt = (
        "trip_id,route_id,service_id\n"
        "T-ok,R1,WKDY\n"
        ",R1,WKDY\n"  # missing trip_id
        "T-bad,,\n"  # missing route_id and service_id
    )
    _routes, trips, edges, findings = normalize(
        build_zip({"routes.txt": ROUTES_TXT, "trips.txt": trips_txt}), RECORD_ID
    )
    assert [t.trip_id for t in trips] == ["T-ok"]
    assert len([e for e in edges if e.output_kind == "canonical.trips"]) == 1
    malformed = [f for f in findings if f.issue_type == "malformed_entity"]
    assert len(malformed) == 2  # one per quarantined row — none silently skipped
