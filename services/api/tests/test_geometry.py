"""/geometry/stops + /geometry/routes (handoff 0023, design point 3):
GeoJSON for the map. Stops verbatim (missing coordinates counted, never
invented); routes as the HONEST SCHEMATIC — the most common trip pattern's
stop sequence, labeled schematic_stop_sequence everywhere, because Headway
has never ingested shapes.txt."""

from conftest import auth_header

from headway_api.routers import geometry


def _seed_stops(fake_db):
    fake_db.add_stop("s1", name="Alpha Sq", latitude=42.1, longitude=-71.1)
    fake_db.add_stop("s2", name="Beta St", latitude=42.2, longitude=-71.2)
    fake_db.add_stop("s3", name="Gamma Ctr", latitude=42.3, longitude=-71.3)


# ---------------------------------------------------------------------------
# /geometry/stops
# ---------------------------------------------------------------------------


def test_stops_anonymous_is_401(client):
    assert client.get("/geometry/stops").status_code == 401


def test_stops_feature_collection_shape(client, fake_db):
    _seed_stops(fake_db)
    r = client.get("/geometry/stops", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert body["stop_count"] == 3
    assert body["category"] == "ops"
    assert "never" in body["ops_note"]
    f = body["features"][0]
    assert f["type"] == "Feature"
    assert f["geometry"]["type"] == "Point"
    # GeoJSON positions are [longitude, latitude] (RFC 7946).
    assert f["geometry"]["coordinates"] == [-71.1, 42.1]
    assert f["properties"] == {"stop_id": "s1", "name": "Alpha Sq"}


def test_stop_without_coordinates_is_counted_never_invented(client, fake_db):
    _seed_stops(fake_db)
    fake_db.add_stop("s4", name="Generic Node", latitude=None, longitude=None)
    r = client.get("/geometry/stops", headers=auth_header(fake_db, "vera"))
    body = r.json()
    assert body["stop_count"] == 3
    assert body["stops_without_coordinates"] == 1
    assert all(
        f["properties"]["stop_id"] != "s4" for f in body["features"]
    )


def test_stops_etag_revalidation(client, fake_db):
    _seed_stops(fake_db)
    headers = auth_header(fake_db, "vera")
    r1 = client.get("/geometry/stops", headers=headers)
    etag = r1.headers["etag"]
    assert etag
    r2 = client.get("/geometry/stops", headers=headers)
    assert r2.headers["etag"] == etag  # same content, same validator
    r304 = client.get(
        "/geometry/stops", headers={**headers, "If-None-Match": etag}
    )
    assert r304.status_code == 304
    assert r304.content == b""
    # Moving a stop changes the content hash: the client refetches.
    fake_db.add_stop("s1", name="Alpha Sq", latitude=42.9, longitude=-71.1)
    r3 = client.get(
        "/geometry/stops", headers={**headers, "If-None-Match": etag}
    )
    assert r3.status_code == 200
    assert r3.headers["etag"] != etag


def test_stops_cap_is_loud(client, fake_db, monkeypatch):
    monkeypatch.setattr(geometry, "MAX_STOPS", 2)
    _seed_stops(fake_db)
    r = client.get("/geometry/stops", headers=auth_header(fake_db, "vera"))
    body = r.json()
    assert body["truncated"] is True
    assert body["stop_count"] == 2
    assert body["total_stops"] == 3
    assert body["note"] is not None


# ---------------------------------------------------------------------------
# /geometry/routes — the honest schematic
# ---------------------------------------------------------------------------


def _seed_route_with_patterns(fake_db):
    """Route r1: pattern (s1,s2,s3) driven by two trips, pattern (s1,s3) by
    one — the two-trip pattern is the route's most common."""
    _seed_stops(fake_db)
    fake_db.add_canonical_route("r1", short_name="66", long_name="Alpha-Gamma",
                                mode="bus")
    fake_db.add_canonical_trip("t1", "r1")
    fake_db.add_canonical_trip("t2", "r1")
    fake_db.add_canonical_trip("t3", "r1")
    fake_db.add_trip_stops("t1", ["s1", "s2", "s3"])
    fake_db.add_trip_stops("t2", ["s1", "s2", "s3"])
    fake_db.add_trip_stops("t3", ["s1", "s3"])


def test_routes_anonymous_is_401(client):
    assert client.get("/geometry/routes").status_code == 401


def test_routes_serve_the_most_common_pattern_as_schematic(client, fake_db):
    _seed_route_with_patterns(fake_db)
    r = client.get("/geometry/routes", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    # The honesty label, at collection level AND on every feature.
    assert body["geometry_kind"] == "schematic_stop_sequence"
    assert "shapes.txt" in body["geometry_note"]
    assert "not streets" in body["geometry_note"]
    assert body["category"] == "ops"
    assert body["route_count"] == 1
    f = body["features"][0]
    assert f["properties"]["geometry_kind"] == "schematic_stop_sequence"
    assert f["properties"]["route_id"] == "r1"
    assert f["properties"]["short_name"] == "66"
    assert f["properties"]["mode"] == "bus"
    assert f["properties"]["pattern_trip_count"] == 2
    assert f["properties"]["stop_count"] == 3
    # The polyline is the three stops of the winning pattern, in order,
    # as [lon, lat] pairs — straight lines between stops, nothing more.
    assert f["geometry"]["type"] == "LineString"
    assert f["geometry"]["coordinates"] == [
        [-71.1, 42.1], [-71.2, 42.2], [-71.3, 42.3]
    ]


def test_routes_pattern_tie_break_is_deterministic(client, fake_db):
    _seed_stops(fake_db)
    fake_db.add_canonical_route("r1", mode="bus")
    fake_db.add_canonical_trip("t1", "r1")
    fake_db.add_canonical_trip("t2", "r1")
    fake_db.add_trip_stops("t1", ["s2", "s3"])
    fake_db.add_trip_stops("t2", ["s1", "s2"])
    r = client.get("/geometry/routes", headers=auth_header(fake_db, "vera"))
    f = r.json()["features"][0]
    # Both patterns have one trip; the lexicographically first stop
    # sequence (s1,s2) wins — same tie-break as the SQL.
    assert f["geometry"]["coordinates"] == [[-71.1, 42.1], [-71.2, 42.2]]


def test_routes_missing_stop_coordinates_are_counted(client, fake_db):
    _seed_stops(fake_db)
    fake_db.add_stop("s-nocoord", name="Node", latitude=None, longitude=None)
    fake_db.add_canonical_route("r1", mode="bus")
    fake_db.add_canonical_trip("t1", "r1")
    fake_db.add_trip_stops("t1", ["s1", "s-nocoord", "s3"])
    r = client.get("/geometry/routes", headers=auth_header(fake_db, "vera"))
    f = r.json()["features"][0]
    # The located stops connect; the coordinate-less one is skipped and
    # COUNTED — never given an invented point.
    assert f["geometry"]["coordinates"] == [[-71.1, 42.1], [-71.3, 42.3]]
    assert f["properties"]["stops_missing_coordinates"] == 1


def test_route_with_fewer_than_two_located_stops_is_excluded_loudly(
    client, fake_db
):
    _seed_stops(fake_db)
    fake_db.add_stop("n1", latitude=None, longitude=None)
    fake_db.add_stop("n2", latitude=None, longitude=None)
    fake_db.add_canonical_route("r-undrawable", mode="bus")
    fake_db.add_canonical_trip("t1", "r-undrawable")
    fake_db.add_trip_stops("t1", ["n1", "n2"])
    r = client.get("/geometry/routes", headers=auth_header(fake_db, "vera"))
    body = r.json()
    assert body["route_count"] == 0
    assert body["routes_without_geometry"] == 1


def test_routes_are_cached_per_process_with_stated_staleness(client, fake_db):
    _seed_route_with_patterns(fake_db)
    headers = auth_header(fake_db, "vera")
    r1 = client.get("/geometry/routes", headers=headers)
    body = r1.json()
    # The staleness bound is stated in the response.
    assert body["cache_ttl_seconds"] == geometry.ROUTES_CACHE_TTL_SECONDS
    assert body["computed_at"] is not None
    pattern_queries = [
        q for q, _p in fake_db.executed if q.startswith("WITH trip_patterns")
    ]
    assert len(pattern_queries) == 1
    r2 = client.get("/geometry/routes", headers=headers)
    assert r2.json()["features"] == body["features"]
    pattern_queries = [
        q for q, _p in fake_db.executed if q.startswith("WITH trip_patterns")
    ]
    assert len(pattern_queries) == 1  # served from cache, not recomputed
    # ETag revalidation: a matching validator is a 304 with no body.
    etag = r1.headers["etag"]
    r304 = client.get(
        "/geometry/routes", headers={**headers, "If-None-Match": etag}
    )
    assert r304.status_code == 304
    assert r304.content == b""
