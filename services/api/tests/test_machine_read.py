"""GET /machine/metrics — the read:metrics consumer (closes the handoff 0006
Response note 'issuable but no endpoint consumes it yet'): scope enforcement,
revoked-key 401, values/detail served verbatim like the human endpoint, the
per-key rate limit, filters, and per-request audit with actor key:<prefix>."""

import datetime as dt
import json
from decimal import Decimal

import pytest

from conftest import auth_header, machine_header

from headway_api.machine_auth import RateLimiter


@pytest.fixture
def read_key(fake_db):
    _, full_key = fake_db.add_api_key(
        name="dashboard reader", scopes=("read:metrics",), source_label=None
    )
    return full_key


def test_values_and_detail_served_verbatim_like_the_human_endpoint(
    client, fake_db, read_key
):
    detail = {
        "coverage": "0.9612",
        "total_groups": 2742,
        "excluded_groups": 106,
        "gap_threshold_seconds": 300.0,
        "coverage_threshold": "0.95",
    }
    fake_db.add_metric_value(value=Decimal("12794.92"), detail=detail)
    r = client.get("/machine/metrics", headers=machine_header(read_key))
    assert r.status_code == 200
    (row,) = r.json()
    # The figure is a STRING (exact NUMERIC, never float), detail verbatim.
    assert row["value"] == "12794.92"
    assert isinstance(row["value"], str)
    assert row["detail"] == detail
    assert isinstance(row["detail"]["coverage"], str)
    # Same shape as the human endpoint: byte-identical row for the same data.
    human = client.get("/metrics/values", headers=auth_header(fake_db, "vera"))
    assert r.json() == human.json()


def test_filters_match_the_human_endpoint(client, fake_db, read_key):
    fake_db.add_metric_value(metric="vrm", period_start=dt.date(2026, 5, 1),
                             period_end=dt.date(2026, 5, 31))
    june = fake_db.add_metric_value(metric="vrm",
                                    period_start=dt.date(2026, 6, 1),
                                    period_end=dt.date(2026, 6, 30))
    fake_db.add_metric_value(metric="vrh", unit="hours",
                             period_start=dt.date(2026, 6, 1),
                             period_end=dt.date(2026, 6, 30))
    r = client.get(
        "/machine/metrics",
        params={"metric": "vrm", "period_start": "2026-06-01",
                "period_end": "2026-06-30"},
        headers=machine_header(read_key),
    )
    assert r.status_code == 200
    (row,) = r.json()
    # The row's metric_value_id is the documented input to the existing
    # lineage endpoint (GET /metrics/values/{id}/lineage).
    assert row["metric_value_id"] == june["metric_value_id"]


def test_ingest_only_key_is_403_scope_denied_and_audited(client, fake_db):
    _, ingest_key = fake_db.add_api_key(
        name="simulator key", scopes=("ingest:tides",),
        source_label="tides_simulated",
    )
    r = client.get("/machine/metrics", headers=machine_header(ingest_key))
    assert r.status_code == 403
    assert "read:metrics" in r.json()["detail"]
    events = [e for e in fake_db.audit_events
              if e["action"] == "machine_scope_denied"]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")
    assert json.loads(events[0]["detail"])["required_scope"] == "read:metrics"


def test_revoked_key_is_401_and_audited(client, fake_db):
    _, revoked_key = fake_db.add_api_key(
        name="old reader", scopes=("read:metrics",), revoked=True
    )
    r = client.get("/machine/metrics", headers=machine_header(revoked_key))
    assert r.status_code == 401
    assert "revoked" in r.json()["detail"]
    events = [e for e in fake_db.audit_events
              if e["action"] == "machine_auth_failed"]
    assert len(events) == 1
    assert json.loads(events[0]["detail"])["reason"] == "key revoked"


def test_human_session_token_is_401_credential_type_separation(client, fake_db):
    r = client.get("/machine/metrics", headers=auth_header(fake_db, "cora"))
    assert r.status_code == 401
    assert "machine API key" in r.json()["detail"]


def test_successful_read_is_audited_with_key_actor(client, fake_db, read_key):
    fake_db.add_metric_value()
    r = client.get(
        "/machine/metrics", params={"metric": "vrm"},
        headers=machine_header(read_key),
    )
    assert r.status_code == 200
    events = [e for e in fake_db.audit_events
              if e["action"] == "machine_read_metrics"]
    assert len(events) == 1
    assert events[0]["actor"].startswith("key:hwk_")
    detail = json.loads(events[0]["detail"])
    assert detail["filters"]["metric"] == "vrm"
    assert detail["rows"] == 1


def test_rate_limit_429_with_retry_after_per_key(client, app, fake_db, read_key):
    app.state.machine_rate_limiter = RateLimiter(requests_per_minute=2)
    headers = machine_header(read_key)
    assert client.get("/machine/metrics", headers=headers).status_code == 200
    assert client.get("/machine/metrics", headers=headers).status_code == 200
    r = client.get("/machine/metrics", headers=headers)
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert "rate limit" in r.json()["detail"]
    # A different key has its own bucket.
    _, other_key = fake_db.add_api_key(
        name="other reader", scopes=("read:metrics",)
    )
    assert client.get(
        "/machine/metrics", headers=machine_header(other_key)
    ).status_code == 200
