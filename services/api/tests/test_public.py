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
