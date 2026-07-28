"""GET /sources/status (handoff 0025, design point 2): read-only v0 —
what the database has actually SEEN per (source, connector), the canonical
vehicle-position liveness the ops endpoint computes, and the honest
connecting story (no add-source mutation exists anywhere)."""

import datetime as dt

from conftest import auth_header

from headway_api.routers import sources

UTC = dt.timezone.utc


def _seed_registry(fake_db):
    now = dt.datetime.now(UTC)
    # A live-ish GTFS-RT stream: two recent rows, one old, one malformed old.
    for age_minutes, status in ((5, "ok"), (30, "ok"), (60 * 50, "ok"),
                                (60 * 51, "malformed")):
        fake_db.add_raw_record(
            source="gtfs_rt",
            connector="headway-gtfs-rt",
            connector_version="0.1.0" if age_minutes > 60 else "0.2.0",
            parse_status=status,
            fetched_at=now - dt.timedelta(minutes=age_minutes, seconds=30),
            landed_at=now - dt.timedelta(minutes=age_minutes),
        )
    # A simulated APC source with a recent malformed row.
    fake_db.add_raw_record(
        source="tides_simulated",
        connector="headway-tides",
        parse_status="malformed",
        landed_at=now - dt.timedelta(minutes=10),
        fetched_at=now - dt.timedelta(minutes=11),
    )


# ---------------------------------------------------------------------------
# Authorization matrix
# ---------------------------------------------------------------------------


def test_anonymous_is_401(client):
    assert client.get("/sources/status").status_code == 401


def test_viewer_is_403_plain_language(client, fake_db):
    r = client.get("/sources/status", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 403
    assert "data steward" in r.json()["detail"]


def test_steward_preparer_and_certifier_can_read(client, fake_db):
    for username in ("stella", "petra", "cora"):
        r = client.get(
            "/sources/status", headers=auth_header(fake_db, username)
        )
        assert r.status_code == 200, username


# ---------------------------------------------------------------------------
# The status payload
# ---------------------------------------------------------------------------


def test_groups_by_source_and_connector_with_counts(client, fake_db):
    _seed_registry(fake_db)
    r = client.get("/sources/status", headers=auth_header(fake_db, "stella"))
    body = r.json()
    assert body["window_hours"] == 24
    assert [(s["source"], s["connector"]) for s in body["sources"]] == [
        ("gtfs_rt", "headway-gtfs-rt"),
        ("tides_simulated", "headway-tides"),
    ]
    rt = body["sources"][0]
    assert rt["records_total"] == 4
    assert rt["malformed_total"] == 1
    assert rt["records_in_window"] == 2  # the 5-min and 30-min rows
    assert rt["malformed_in_window"] == 0
    # The newest record's connector version is what is running now.
    assert rt["latest_connector_version"] == "0.2.0"
    assert rt["latest_age_seconds"] >= 0
    assert rt["simulated"] is False

    apc = body["sources"][1]
    assert apc["records_total"] == 1
    assert apc["malformed_total"] == 1
    assert apc["malformed_in_window"] == 1
    assert apc["simulated"] is True  # the UI badges simulated sources


def test_window_hours_param_bounds_the_recent_counts(client, fake_db):
    _seed_registry(fake_db)
    r = client.get(
        "/sources/status",
        params={"window_hours": 720},
        headers=auth_header(fake_db, "stella"),
    )
    rt = r.json()["sources"][0]
    assert r.json()["window_hours"] == 720
    assert rt["records_in_window"] == 4  # totals and window now agree
    assert rt["malformed_in_window"] == 1


def test_window_hours_out_of_bounds_is_422(client, fake_db):
    for bad in (0, 721):
        r = client.get(
            "/sources/status",
            params={"window_hours": bad},
            headers=auth_header(fake_db, "stella"),
        )
        assert r.status_code == 422, bad


def test_canonical_liveness_mirrors_the_ops_freshness(client, fake_db):
    _seed_registry(fake_db)
    fake_db.add_vehicle_position(
        time=dt.datetime.now(UTC) - dt.timedelta(seconds=90)
    )
    r = client.get("/sources/status", headers=auth_header(fake_db, "stella"))
    canonical = r.json()["canonical"]
    assert canonical["newest_vehicle_position_at"] is not None
    assert 85 <= canonical["age_seconds"] <= 120
    assert "newest normalized vehicle position" in canonical["note"]


def test_nothing_ingested_states_it_plainly_not_an_empty_200(client, fake_db):
    r = client.get("/sources/status", headers=auth_header(fake_db, "stella"))
    body = r.json()
    assert body["sources"] == []
    assert "No raw records have ever landed" in body["note"]
    assert canonical_never_none(body)


def canonical_never_none(body):
    canonical = body["canonical"]
    return (
        canonical["newest_vehicle_position_at"] is None
        and canonical["age_seconds"] is None
        and "No vehicle positions" in canonical["note"]
    )


def test_connecting_note_is_honest_and_names_the_guide(client, fake_db):
    """The binding no-fake-form rule: the API states how connecting REALLY
    works and points at the guide; there is no add-source mutation."""
    r = client.get("/sources/status", headers=auth_header(fake_db, "stella"))
    note = r.json()["connecting_note"]
    assert note == sources.CONNECTING_NOTE
    assert "not an in-app action yet" in note
    assert "docs/connecting-your-data.md" in note


def test_no_add_source_route_exists(client, fake_db):
    """Pin the honest scope: POST /sources (or /sources/status) must not
    exist in any form — 404/405, never a handler."""
    h = auth_header(fake_db, "cora")
    assert client.post("/sources", json={}, headers=h).status_code in (404, 405)
    assert client.post("/sources/status", json={}, headers=h).status_code in (
        404,
        405,
    )
