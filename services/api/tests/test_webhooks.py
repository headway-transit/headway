"""Webhooks: subscription CRUD (secret write-only), post-commit dispatch with
a verifiable HMAC signature, one retry, and the guarantee that a delivery
failure never touches the certification response."""

import hashlib
import hmac
import json

from conftest import auth_header

SECRET = "shared-hmac-secret-for-the-receiver-1"


def _certify(client, fake_db, mv_ids):
    return client.post(
        "/certifications",
        json={"metric_value_ids": mv_ids, "attestation": "June figures are accurate."},
        headers=auth_header(fake_db, "cora"),
    )


# ---------------------------------------------------------------------------
# Subscription CRUD
# ---------------------------------------------------------------------------


def test_create_subscription_audited_and_secret_never_returned(client, fake_db):
    r = client.post(
        "/webhooks",
        json={
            "url": "https://city.example/webhooks/headway",
            "event_types": ["certification.created"],
            "secret": SECRET,
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201
    assert SECRET not in r.text
    assert "secret" not in r.json()
    sub_id = r.json()["subscription_id"]
    # Stored (to sign with) but audited without the secret.
    assert fake_db.webhook_subscriptions[sub_id]["secret"] == SECRET
    events = [e for e in fake_db.audit_events if e["action"] == "webhook_subscribed"]
    assert len(events) == 1 and SECRET not in events[0]["detail"]
    # Listing never returns it either.
    r = client.get("/webhooks", headers=auth_header(fake_db, "cora"))
    assert r.status_code == 200 and SECRET not in r.text


def test_subscription_crud_is_admin_only(client, fake_db):
    body = {
        "url": "https://x.example/h",
        "event_types": ["certification.created"],
        "secret": SECRET,
    }
    assert (
        client.post("/webhooks", json=body, headers=auth_header(fake_db, "petra"))
        .status_code
        == 403
    )
    assert (
        client.get("/webhooks", headers=auth_header(fake_db, "vera")).status_code
        == 403
    )


def test_unknown_event_type_and_bad_url_refused(client, fake_db):
    r = client.post(
        "/webhooks",
        json={
            "url": "https://x.example/h",
            "event_types": ["dq.issue_raised"],
            "secret": SECRET,
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    r = client.post(
        "/webhooks",
        json={
            "url": "ftp://x.example/h",
            "event_types": ["certification.created"],
            "secret": SECRET,
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422


def test_delete_subscription_soft_revokes_and_audits(client, fake_db):
    sub = fake_db.add_webhook_subscription()
    r = client.delete(
        f"/webhooks/{sub['subscription_id']}", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 200
    assert sub["revoked_at"] is not None
    assert any(e["action"] == "webhook_unsubscribed" for e in fake_db.audit_events)
    assert (
        client.delete(
            f"/webhooks/{sub['subscription_id']}",
            headers=auth_header(fake_db, "cora"),
        ).status_code
        == 409
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def test_dispatch_after_commit_with_verifiable_hmac(
    client, fake_db, fake_webhook_sender
):
    sub = fake_db.add_webhook_subscription(secret=SECRET)
    mv = fake_db.add_metric_value()
    r = _certify(client, fake_db, [mv["metric_value_id"]])
    assert r.status_code == 201
    certification_id = r.json()["certification_id"]

    assert len(fake_webhook_sender.deliveries) == 1
    url, body, headers = fake_webhook_sender.deliveries[0]
    assert url == sub["url"]
    # The signature verifies when recomputed exactly as a receiver would.
    expected = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    assert headers["X-Headway-Signature"] == f"sha256={expected}"
    assert int(headers["X-Headway-Timestamp"]) > 0
    payload = json.loads(body)
    assert payload["event_type"] == "certification.created"
    assert payload["certification_id"] == certification_id
    assert payload["metric_value_ids"] == [mv["metric_value_id"]]
    # Values as strings — NUMERIC, never float.
    assert payload["values"] == [
        {
            "metric_value_id": mv["metric_value_id"],
            "metric": "vrm",
            "value": "1234.567",
        }
    ]
    assert payload["certified_by"] == "cora"
    assert payload["certified_at"]
    # Post-commit: the certification transaction committed BEFORE any
    # delivery audit — the certify audit event precedes the delivery event.
    certify_id = next(
        e["event_id"] for e in fake_db.audit_events if e["action"] == "certify"
    )
    delivered_id = next(
        e["event_id"]
        for e in fake_db.audit_events
        if e["action"] == "webhook_delivered"
    )
    assert certify_id < delivered_id


def test_failed_delivery_retries_once_then_audits_failure(
    client, fake_db, fake_webhook_sender
):
    fake_db.add_webhook_subscription(secret=SECRET)
    mv = fake_db.add_metric_value()
    fake_webhook_sender.outcomes = [500, 502]  # both attempts fail
    r = _certify(client, fake_db, [mv["metric_value_id"]])
    # The certification is COMMITTED and answers 201 regardless.
    assert r.status_code == 201
    assert len(fake_db.certifications) == 1
    assert mv["certification_status"] == "certified"
    # Exactly one retry (two attempts), then an audited failure.
    assert len(fake_webhook_sender.deliveries) == 2
    events = [
        e for e in fake_db.audit_events if e["action"] == "webhook_delivery_failed"
    ]
    assert len(events) == 1
    detail = json.loads(events[0]["detail"])
    assert detail["attempts"] == 2 and detail["status"] == 502


def test_retry_succeeds_on_second_attempt(client, fake_db, fake_webhook_sender):
    fake_db.add_webhook_subscription(secret=SECRET)
    mv = fake_db.add_metric_value()
    fake_webhook_sender.outcomes = [500, 200]
    r = _certify(client, fake_db, [mv["metric_value_id"]])
    assert r.status_code == 201
    assert len(fake_webhook_sender.deliveries) == 2
    events = [e for e in fake_db.audit_events if e["action"] == "webhook_delivered"]
    assert len(events) == 1
    assert json.loads(events[0]["detail"])["attempts"] == 2


def test_connection_error_never_fails_certification(
    client, fake_db, fake_webhook_sender
):
    fake_db.add_webhook_subscription(secret=SECRET)
    mv = fake_db.add_metric_value()
    fake_webhook_sender.outcomes = [
        ConnectionError("receiver down"),
        ConnectionError("receiver still down"),
    ]
    r = _certify(client, fake_db, [mv["metric_value_id"]])
    assert r.status_code == 201
    events = [
        e for e in fake_db.audit_events if e["action"] == "webhook_delivery_failed"
    ]
    assert len(events) == 1
    assert "receiver still down" in json.loads(events[0]["detail"])["error"]


def test_revoked_subscription_gets_nothing(client, fake_db, fake_webhook_sender):
    fake_db.add_webhook_subscription(secret=SECRET, revoked=True)
    mv = fake_db.add_metric_value()
    r = _certify(client, fake_db, [mv["metric_value_id"]])
    assert r.status_code == 201
    assert fake_webhook_sender.deliveries == []


def test_no_sender_configured_is_an_audited_failure_not_an_error(
    fake_db, settings
):
    from fastapi.testclient import TestClient

    from headway_api.app import create_app

    app = create_app(settings=settings, db=fake_db, webhook_sender=None)
    app.state.webhook_sender = None  # simulate a deployment with no sender
    fake_db.add_webhook_subscription(secret=SECRET)
    mv = fake_db.add_metric_value()
    with TestClient(app) as client:
        r = _certify(client, fake_db, [mv["metric_value_id"]])
    assert r.status_code == 201
    events = [
        e for e in fake_db.audit_events if e["action"] == "webhook_delivery_failed"
    ]
    assert len(events) == 1
    assert "no webhook sender configured" in json.loads(events[0]["detail"])["reason"]
