"""The open-data endpoint: unauthenticated by design, certified figures only,
values as strings, detail verbatim (simulated flags shown), IP rate limit."""

import datetime as dt
from decimal import Decimal

from headway_api.machine_auth import RateLimiter

UTC = dt.timezone.utc


def test_serves_only_certified_figures_without_any_auth(client, fake_db):
    certified = fake_db.add_metric_value(
        certification_status="certified",
        value=Decimal("98765.432"),
        detail={"coverage": {"expected_days": "30", "simulated": True}},
    )
    fake_db.add_metric_value(certification_status="uncertified")
    r = client.get("/public/metrics/certified")  # NO Authorization header
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["metric_value_id"] == certified["metric_value_id"]
    assert row["certification_status"] == "certified"
    # Value is a string (NUMERIC precision), detail served verbatim —
    # transparency shows the simulated flag, it does not hide the figure.
    assert row["value"] == "98765.432"
    assert row["detail"] == {"coverage": {"expected_days": "30", "simulated": True}}
    # No PII surface: not even the certifier's name appears here.
    assert "certified_by" not in row


def test_empty_when_nothing_certified(client, fake_db):
    fake_db.add_metric_value(certification_status="uncertified")
    r = client.get("/public/metrics/certified")
    assert r.status_code == 200
    assert r.json() == []


def test_ip_rate_limit_429_with_retry_after(client, app, fake_db):
    fake_db.add_metric_value(certification_status="certified")
    app.state.public_rate_limiter = RateLimiter(requests_per_minute=2)
    assert client.get("/public/metrics/certified").status_code == 200
    assert client.get("/public/metrics/certified").status_code == 200
    r = client.get("/public/metrics/certified")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1


def test_ops_figure_can_never_surface_as_certified_open_data(client, fake_db):
    """THE HONESTY BOUNDARY (handoff 0014 / migration 0024), belt AND
    suspenders: even in the impossible state where an OPERATIONS figure
    carried certification_status='certified' (the database CHECK
    metric_values_ops_never_certified forbids it — proven live by attack),
    the public endpoint's hard "AND category = 'ntd'" clause still excludes
    it. The fake can represent the impossible row, so this pins the WHERE
    layer specifically."""
    ntd = fake_db.add_metric_value(certification_status="certified")
    fake_db.add_metric_value(
        metric="otp",
        unit="percent",
        calc_name="otp_v0",
        category="ops",
        certification_status="certified",  # unrepresentable in the real DB
        value=Decimal("87.50"),
    )
    r = client.get("/public/metrics/certified")
    assert r.status_code == 200
    rows = r.json()
    assert [row["metric_value_id"] for row in rows] == [ntd["metric_value_id"]]
    assert all(row["category"] == "ntd" for row in rows)


def test_uncertified_ops_figure_also_absent(client, fake_db):
    fake_db.add_metric_value(
        metric="headway_adherence",
        unit="ratio",
        calc_name="headway_adherence_v0",
        category="ops",
    )
    r = client.get("/public/metrics/certified")
    assert r.status_code == 200
    assert r.json() == []
