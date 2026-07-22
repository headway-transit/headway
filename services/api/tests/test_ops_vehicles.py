"""GET /ops/vehicles/latest (handoff 0023, design point 2): the live-map
feed. Latest position per vehicle inside a staleness window, rows verbatim,
per-vehicle SIMULATED flag, ops-category envelope, cap + staleness honesty."""

import datetime as dt

from conftest import auth_header

from headway_api.routers import ops

UTC = dt.timezone.utc


def _ago(seconds):
    return dt.datetime.now(UTC) - dt.timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Authorization matrix
# ---------------------------------------------------------------------------


def test_anonymous_is_401(client):
    assert client.get("/ops/vehicles/latest").status_code == 401


def test_any_signed_in_role_can_read(client, fake_db):
    fake_db.add_vehicle_position(vehicle_id="bus-1", time=_ago(10))
    for username in ("vera", "stella", "petra", "cora"):
        r = client.get(
            "/ops/vehicles/latest", headers=auth_header(fake_db, username)
        )
        assert r.status_code == 200, username
        assert r.json()["vehicle_count"] == 1


# ---------------------------------------------------------------------------
# The ops honesty boundary (handoff 0014 / migration 0024)
# ---------------------------------------------------------------------------


def test_envelope_states_the_ops_boundary(client, fake_db):
    r = client.get("/ops/vehicles/latest", headers=auth_header(fake_db, "vera"))
    body = r.json()
    assert body["category"] == "ops"
    assert "never" in body["ops_note"] and "certif" in body["ops_note"]
    assert body["as_of"] is not None


# ---------------------------------------------------------------------------
# Latest-per-vehicle within the window, rows verbatim
# ---------------------------------------------------------------------------


def test_latest_position_per_vehicle_wins(client, fake_db):
    fake_db.add_vehicle_position(
        vehicle_id="bus-1", time=_ago(120), latitude=42.1, longitude=-71.1
    )
    newer = fake_db.add_vehicle_position(
        vehicle_id="bus-1", time=_ago(30), latitude=42.2, longitude=-71.2,
        bearing=270.0, speed_mps=8.5, trip_id="t-77", route_id="r-66",
    )
    fake_db.add_vehicle_position(vehicle_id="bus-2", time=_ago(60))
    r = client.get("/ops/vehicles/latest", headers=auth_header(fake_db, "vera"))
    body = r.json()
    assert body["vehicle_count"] == 2
    by_id = {v["vehicle_id"]: v for v in body["vehicles"]}
    v1 = by_id["bus-1"]
    assert v1["latitude"] == newer["latitude"]
    assert v1["longitude"] == newer["longitude"]
    assert v1["bearing"] == 270.0
    assert v1["speed_mps"] == 8.5
    assert v1["trip_id"] == "t-77"
    assert v1["route_id"] == "r-66"
    assert v1["source_record_id"] == newer["source_record_id"]
    assert 25 <= v1["age_seconds"] <= 40


def test_unassigned_position_stays_unassigned(client, fake_db):
    fake_db.add_vehicle_position(vehicle_id="bus-9", time=_ago(5))
    r = client.get("/ops/vehicles/latest", headers=auth_header(fake_db, "vera"))
    v = r.json()["vehicles"][0]
    # Nullable by design: never guessed, served null.
    assert v["trip_id"] is None
    assert v["route_id"] is None
    assert v["bearing"] is None
    assert v["speed_mps"] is None


def test_staleness_window_excludes_old_positions(client, fake_db):
    fake_db.add_vehicle_position(vehicle_id="bus-old", time=_ago(600))
    r = client.get("/ops/vehicles/latest", headers=auth_header(fake_db, "vera"))
    assert r.json()["vehicle_count"] == 0  # default window is 300 s
    r = client.get(
        "/ops/vehicles/latest",
        params={"max_age_seconds": 3600},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.json()["vehicle_count"] == 1


def test_max_age_bounds_are_enforced(client, fake_db):
    for bad in (0, -5, ops.MAX_AGE_CEILING_SECONDS + 1):
        r = client.get(
            "/ops/vehicles/latest",
            params={"max_age_seconds": bad},
            headers=auth_header(fake_db, "vera"),
        )
        assert r.status_code == 422, bad


# ---------------------------------------------------------------------------
# The SIMULATED badge stays renderable per vehicle
# ---------------------------------------------------------------------------


def test_simulated_source_rows_keep_their_flag(client, fake_db):
    fake_db.add_vehicle_position(
        vehicle_id="sim-1", time=_ago(10), source="tides_simulated"
    )
    fake_db.add_vehicle_position(
        vehicle_id="real-1", time=_ago(10), source="gtfs_rt_vehicle_positions"
    )
    r = client.get("/ops/vehicles/latest", headers=auth_header(fake_db, "vera"))
    by_id = {v["vehicle_id"]: v for v in r.json()["vehicles"]}
    assert by_id["sim-1"]["simulated"] is True
    assert by_id["sim-1"]["source"] == "tides_simulated"
    assert by_id["real-1"]["simulated"] is False


# ---------------------------------------------------------------------------
# Staleness + cap honesty
# ---------------------------------------------------------------------------


def test_empty_window_with_stale_feed_says_so(client, fake_db):
    fake_db.add_vehicle_position(vehicle_id="bus-1", time=_ago(1200))
    r = client.get("/ops/vehicles/latest", headers=auth_header(fake_db, "vera"))
    body = r.json()
    assert body["vehicle_count"] == 0
    assert body["newest_position_at"] is not None
    assert "stale" in body["note"]
    assert "empty fleet" in body["note"]


def test_no_positions_ever_is_a_data_availability_state(client, fake_db):
    r = client.get("/ops/vehicles/latest", headers=auth_header(fake_db, "vera"))
    body = r.json()
    assert body["vehicle_count"] == 0
    assert body["newest_position_at"] is None
    assert "ever been ingested" in body["note"]


def test_cap_is_loud_never_silent(client, fake_db, monkeypatch):
    monkeypatch.setattr(ops, "MAX_VEHICLES", 2)
    for n in range(3):
        fake_db.add_vehicle_position(vehicle_id=f"bus-{n}", time=_ago(10))
    r = client.get("/ops/vehicles/latest", headers=auth_header(fake_db, "vera"))
    body = r.json()
    assert body["truncated"] is True
    assert body["vehicle_count"] == 2
    assert body["total_in_window"] == 3
    assert "2 of 3" in body["note"]
