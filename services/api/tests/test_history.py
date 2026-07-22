"""GET /metrics/history (handoff 0023, design point 4): persisted figures
only, verbatim, receipt-linkable; the bucket param GROUPS by a calendar key
derived from each figure's own period — never sums, never averages, never
invents a number no calc produced."""

import datetime as dt
from decimal import Decimal

from conftest import auth_header

from headway_api.routers import history

UTC = dt.timezone.utc


def _seed_series(fake_db):
    """Three monthly vrm figures (May–July) + one bus-scope + one ops row."""
    rows = []
    for month, value in ((5, "100.5"), (6, "200.25"), (7, "300")):
        rows.append(
            fake_db.add_metric_value(
                metric="vrm",
                period_start=dt.date(2026, month, 1),
                period_end=dt.date(2026, month + 1, 1),
                value=Decimal(value),
                computed_at=dt.datetime(2026, month, 28, 12, 0, tzinfo=UTC),
            )
        )
    rows.append(
        fake_db.add_metric_value(
            metric="vrm",
            scope="mode:bus",
            period_start=dt.date(2026, 7, 1),
            period_end=dt.date(2026, 8, 1),
            value=Decimal("42.42"),
        )
    )
    rows.append(
        fake_db.add_metric_value(
            metric="otp",
            unit="ratio",
            category="ops",
            period_start=dt.date(2026, 7, 1),
            period_end=dt.date(2026, 8, 1),
            value=Decimal("0.91"),
        )
    )
    return rows


# ---------------------------------------------------------------------------
# Authorization matrix
# ---------------------------------------------------------------------------


def test_anonymous_is_401(client):
    assert client.get("/metrics/history").status_code == 401


def test_viewer_can_read(client, fake_db):
    _seed_series(fake_db)
    r = client.get("/metrics/history", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Verbatim figures, receipts, flags
# ---------------------------------------------------------------------------


def test_points_are_verbatim_with_receipts_and_flags(client, fake_db):
    seeded = _seed_series(fake_db)
    r = client.get(
        "/metrics/history",
        params={"metric": "vrm", "scope": "agency"},
        headers=auth_header(fake_db, "vera"),
    )
    body = r.json()
    points = [p for b in body["buckets"] for p in b["points"]]
    assert [p["value"] for p in points] == ["100.5", "200.25", "300"]
    seeded_ids = {mv["metric_value_id"] for mv in seeded}
    for p in points:
        assert p["metric_value_id"] in seeded_ids  # receipt-linkable
        assert p["certification_status"] == "uncertified"
        assert p["category"] == "ntd"
        assert p["simulated"] is False
    assert body["grouping_note"].startswith("Buckets group")
    assert "never sums" in body["grouping_note"]


def test_simulated_detail_flags_the_point(client, fake_db):
    fake_db.add_metric_value(
        detail={"source_mix": {"tides_simulated": 3}},
    )
    r = client.get("/metrics/history", headers=auth_header(fake_db, "vera"))
    p = r.json()["buckets"][0]["points"][0]
    assert p["simulated"] is True
    assert p["detail"] == {"source_mix": {"tides_simulated": 3}}  # verbatim


def test_ops_rows_keep_their_category_label(client, fake_db):
    _seed_series(fake_db)
    r = client.get(
        "/metrics/history",
        params={"metric": "otp"},
        headers=auth_header(fake_db, "vera"),
    )
    points = [p for b in r.json()["buckets"] for p in b["points"]]
    assert len(points) == 1
    assert points[0]["category"] == "ops"


# ---------------------------------------------------------------------------
# Buckets: grouping keys, never arithmetic
# ---------------------------------------------------------------------------


def test_month_buckets_group_by_period_start(client, fake_db):
    _seed_series(fake_db)
    r = client.get(
        "/metrics/history",
        params={"metric": "vrm"},
        headers=auth_header(fake_db, "vera"),
    )
    body = r.json()
    assert body["bucket"] == "month"
    assert [b["bucket_key"] for b in body["buckets"]] == [
        "2026-05", "2026-06", "2026-07"
    ]
    july = body["buckets"][2]
    assert len(july["points"]) == 2  # agency + mode:bus figures, both served
    # GROUPING ONLY: a bucket holds points and a key — no aggregate field
    # exists anywhere for the server to have computed.
    assert set(july.keys()) == {"bucket_key", "points"}


def test_bucket_key_derivations(client, fake_db):
    fake_db.add_metric_value(
        period_start=dt.date(2026, 7, 14), period_end=dt.date(2026, 7, 15)
    )
    headers = auth_header(fake_db, "vera")
    expected = {
        "day": "2026-07-14",
        "week": "2026-W29",
        "month": "2026-07",
        "quarter": "2026-Q3",
    }
    for bucket, key in expected.items():
        r = client.get(
            "/metrics/history",
            params={"bucket": bucket},
            headers=headers,
        )
        assert [b["bucket_key"] for b in r.json()["buckets"]] == [key], bucket


def test_unknown_bucket_is_422(client, fake_db):
    r = client.get(
        "/metrics/history",
        params={"bucket": "fortnight"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Filters + window
# ---------------------------------------------------------------------------


def test_mode_is_shorthand_for_the_mode_scope(client, fake_db):
    _seed_series(fake_db)
    r = client.get(
        "/metrics/history",
        params={"metric": "vrm", "mode": "bus"},
        headers=auth_header(fake_db, "vera"),
    )
    body = r.json()
    assert body["scope"] == "mode:bus"  # echoed as applied
    points = [p for b in body["buckets"] for p in b["points"]]
    assert [p["value"] for p in points] == ["42.42"]


def test_mode_and_scope_together_is_422(client, fake_db):
    r = client.get(
        "/metrics/history",
        params={"mode": "bus", "scope": "agency"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422
    assert "not both" in r.json()["detail"]


def test_calc_version_filter(client, fake_db):
    fake_db.add_metric_value(calc_version="0.1.0", value=Decimal("1"))
    fake_db.add_metric_value(calc_version="0.2.0", value=Decimal("2"))
    r = client.get(
        "/metrics/history",
        params={"calc_version": "0.2.0"},
        headers=auth_header(fake_db, "vera"),
    )
    points = [p for b in r.json()["buckets"] for p in b["points"]]
    assert [p["value"] for p in points] == ["2"]


def test_from_to_window(client, fake_db):
    _seed_series(fake_db)
    r = client.get(
        "/metrics/history",
        params={"metric": "vrm", "from": "2026-06-01", "to": "2026-07-01"},
        headers=auth_header(fake_db, "vera"),
    )
    body = r.json()
    points = [p for b in body["buckets"] for p in b["points"]]
    assert [p["value"] for p in points] == ["200.25"]
    assert body["period_from"] == "2026-06-01"
    assert body["period_to"] == "2026-07-01"


# ---------------------------------------------------------------------------
# Bound + cap honesty
# ---------------------------------------------------------------------------


def test_cap_is_loud_never_silent(client, fake_db, monkeypatch):
    monkeypatch.setattr(history, "MAX_HISTORY_POINTS", 2)
    _seed_series(fake_db)
    r = client.get(
        "/metrics/history",
        params={"metric": "vrm"},
        headers=auth_header(fake_db, "vera"),
    )
    body = r.json()
    assert body["truncated"] is True
    assert body["point_count"] == 2
    assert body["total_matching"] == 4
    assert "first 2 of 4" in body["note"]
