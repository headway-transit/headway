"""GTFS static loader: in-test zips built with zipfile.

0.3.0 (handoff 0011): stops.txt + stop_times.txt join routes.txt + trips.txt;
every emitted row keeps exactly one lineage edge; NULLs (coordinates,
times, shape_dist_traveled) are preserved, never fabricated.
"""

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
STOPS_TXT = (
    "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
    "S1,First St,42.35,-71.06,0\n"
    "S2,Second St,42.36,-71.07,\n"
    "node-1,Concourse,,,3\n"  # generic node: coords legitimately absent
)
STOP_TIMES_TXT = (
    "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
    "T1,10:40:00,10:40:30,S1,1\n"
    "T1,25:05:00,,S2,2\n"  # >24h service time; empty departure is valid GTFS
)


def base_zip(**overrides: str) -> bytes:
    files = {
        "routes.txt": ROUTES_TXT,
        "trips.txt": TRIPS_TXT,
        "stops.txt": STOPS_TXT,
        "stop_times.txt": STOP_TIMES_TXT,
    }
    files.update(overrides)
    return build_zip(files)


def test_routes_and_trips_normalized_with_edges() -> None:
    routes, trips, stops, stop_times, edges, findings = normalize(
        base_zip(), RECORD_ID
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
    assert len(edges) == len(routes) + len(trips) + len(stops) + len(stop_times)
    route_edges = [e for e in edges if e.output_kind == "canonical.routes"]
    trip_edges = [e for e in edges if e.output_kind == "canonical.trips"]
    stop_edges = [e for e in edges if e.output_kind == "canonical.stops"]
    st_edges = [e for e in edges if e.output_kind == "canonical.stop_times"]
    assert sorted(e.output_id for e in route_edges) == ["R1", "R2"]
    assert sorted(e.output_id for e in trip_edges) == ["T1", "T2", "T3"]
    assert sorted(e.output_id for e in stop_edges) == ["S1", "S2", "node-1"]
    assert sorted(e.output_id for e in st_edges) == ["T1:1", "T1:2"]
    for edge in edges:
        assert edge.transform_name == TRANSFORM_NAME == "normalize_gtfs_static"
        assert edge.transform_version == TRANSFORM_VERSION == "0.3.0"
        assert edge.input_kind == "raw.records"
        assert edge.input_id == RECORD_ID


def test_stops_normalized_with_nullable_node_coordinates() -> None:
    _r, _t, stops, _st, _e, findings = normalize(base_zip(), RECORD_ID)

    assert findings == []
    assert [(s.stop_id, s.name, s.latitude, s.longitude) for s in stops] == [
        ("S1", "First St", 42.35, -71.06),
        ("S2", "Second St", 42.36, -71.07),
        # location_type 3 (generic node): coordinates legitimately absent —
        # NULL preserved, NO finding, never a guessed point.
        ("node-1", "Concourse", None, None),
    ]


def test_stop_times_parse_gtfs_times_and_preserve_null_shape_dist() -> None:
    _r, _t, _s, stop_times, _e, findings = normalize(base_zip(), RECORD_ID)

    assert findings == []
    assert [
        (
            st.trip_id,
            st.stop_id,
            st.stop_sequence,
            st.arrival_seconds,
            st.departure_seconds,
            st.shape_dist_traveled,
        )
        for st in stop_times
    ] == [
        ("T1", "S1", 1, 10 * 3600 + 40 * 60, 10 * 3600 + 40 * 60 + 30, None),
        # 25:05:00 — GTFS times exceed 24h past midnight; empty departure is
        # valid on non-timepoint rows → NULL, no finding. The feed omits
        # shape_dist_traveled entirely → NULL preserved, NO finding
        # (handoff 0011: never fabricate a distance).
        ("T1", "S2", 2, 25 * 3600 + 5 * 60, None, None),
    ]


def test_stop_times_shape_dist_traveled_parsed_when_present() -> None:
    stop_times_txt = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,shape_dist_traveled\n"
        "T1,10:40:00,10:40:00,S1,1,0\n"
        "T1,10:45:00,10:45:00,S2,2,1.25\n"
        "T1,10:50:00,10:50:00,S1,3,\n"  # empty value → NULL, no finding
    )
    _r, _t, _s, stop_times, _e, findings = normalize(
        base_zip(**{"stop_times.txt": stop_times_txt}), RECORD_ID
    )
    assert findings == []
    assert [st.shape_dist_traveled for st in stop_times] == [0.0, 1.25, None]


def test_stop_missing_required_coordinates_is_warning_stored_null() -> None:
    stops_txt = (
        "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
        "S-bad,No Coords Platform,,,0\n"
    )
    _r, _t, stops, _st, _e, findings = normalize(
        base_zip(**{"stops.txt": stops_txt}), RECORD_ID
    )
    assert [(s.stop_id, s.latitude, s.longitude) for s in stops] == [
        ("S-bad", None, None)
    ]
    missing = [f for f in findings if f.issue_type == "stop_missing_coordinates"]
    assert len(missing) == 2  # one per absent coordinate
    assert all(f.severity == "warning" for f in missing)
    assert all(f.source_record_ids == [RECORD_ID] for f in missing)


def test_stop_malformed_or_out_of_range_coordinate_null_plus_warning() -> None:
    stops_txt = (
        "stop_id,stop_name,stop_lat,stop_lon,location_type\n"
        "S-x,Bad Lat,not-a-number,-71.06,0\n"
        "S-y,Bad Lon,42.35,-181.0,0\n"
    )
    _r, _t, stops, _st, _e, findings = normalize(
        base_zip(**{"stops.txt": stops_txt}), RECORD_ID
    )
    assert [(s.stop_id, s.latitude, s.longitude) for s in stops] == [
        ("S-x", None, -71.06),
        ("S-y", 42.35, None),
    ]
    malformed = [f for f in findings if f.issue_type == "malformed_entity"]
    assert len(malformed) == 2
    assert all(f.severity == "warning" for f in malformed)


def test_stop_time_malformed_time_and_negative_shape_dist_warned() -> None:
    stop_times_txt = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence,shape_dist_traveled\n"
        "T1,10:99:00,10:40:00,S1,1,-5\n"
    )
    _r, _t, _s, stop_times, _e, findings = normalize(
        base_zip(**{"stop_times.txt": stop_times_txt}), RECORD_ID
    )
    assert [
        (st.arrival_seconds, st.departure_seconds, st.shape_dist_traveled)
        for st in stop_times
    ] == [(None, 10 * 3600 + 40 * 60, None)]
    warned = [f for f in findings if f.issue_type == "malformed_entity"]
    assert len(warned) == 2  # bad arrival_time + negative shape_dist
    assert all(f.severity == "warning" for f in warned)


def test_stop_time_missing_identity_quarantined_row_by_row() -> None:
    stop_times_txt = (
        "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
        "T1,10:40:00,10:40:00,S1,1\n"
        ",10:41:00,10:41:00,S2,2\n"  # missing trip_id
        "T1,10:42:00,10:42:00,,3\n"  # missing stop_id
        "T1,10:43:00,10:43:00,S1,minus\n"  # non-integer stop_sequence
        "T1,10:44:00,10:44:00,S1,-2\n"  # negative stop_sequence
    )
    _r, _t, _s, stop_times, edges, findings = normalize(
        base_zip(**{"stop_times.txt": stop_times_txt}), RECORD_ID
    )
    assert [(st.trip_id, st.stop_sequence) for st in stop_times] == [("T1", 1)]
    assert (
        len([e for e in edges if e.output_kind == "canonical.stop_times"]) == 1
    )
    quarantined = [f for f in findings if f.issue_type == "malformed_entity"]
    assert len(quarantined) == 4  # one per quarantined row — none silent


def test_trips_block_id_parsed_when_column_present() -> None:
    """block_id column (handoff 0003): non-empty values parsed, empty → NULL,
    never a DQ finding — the field is optional per the GTFS spec."""
    trips_txt = (
        "trip_id,route_id,service_id,direction_id,block_id\n"
        "T1,R1,WKDY,0,B-77\n"
        "T2,R1,WKDY,1,B-77\n"
        "T3,R2,SAT,, \n"  # whitespace-only block_id → NULL, no finding
    )
    _routes, trips, _stops, _st, edges, findings = normalize(
        base_zip(**{"trips.txt": trips_txt}), RECORD_ID
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
    routes, _trips, _stops, _st, edges, findings = normalize(
        base_zip(
            **{
                "routes.txt": routes_txt,
                "trips.txt": "trip_id,route_id,service_id\n",
            }
        ),
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
    routes, trips, stops, stop_times, edges, findings = normalize(
        build_zip({"agency.txt": "agency_id\nA1\n"}), RECORD_ID
    )
    assert routes == [] and trips == [] and edges == []
    assert stops == [] and stop_times == []
    types = sorted(f.issue_type for f in findings)
    # routes.txt, trips.txt, stops.txt, stop_times.txt each blockingly absent.
    assert types == ["malformed_entity"] * 4
    assert all(f.severity == "blocking" for f in findings)


def test_bad_zip_is_undecodable_payload_finding_not_exception() -> None:
    routes, trips, stops, stop_times, edges, findings = normalize(
        b"not a zip at all", RECORD_ID
    )
    assert routes == [] and trips == [] and edges == []
    assert stops == [] and stop_times == []
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
    _routes, trips, _stops, _st, edges, findings = normalize(
        base_zip(**{"trips.txt": trips_txt}), RECORD_ID
    )
    assert [t.trip_id for t in trips] == ["T-ok"]
    assert len([e for e in edges if e.output_kind == "canonical.trips"]) == 1
    malformed = [f for f in findings if f.issue_type == "malformed_entity"]
    assert len(malformed) == 2  # one per quarantined row — none silently skipped
