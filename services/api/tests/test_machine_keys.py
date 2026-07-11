"""Machine API keys: hash-at-rest, one-time issuance, revocation, scope
metadata — and the guarantee that key material never lands anywhere but the
single issuance response."""

import json

from conftest import auth_header, machine_header

from headway_api import machine_auth


def _issue(client, fake_db, **overrides):
    body = {
        "name": "APC vendor X",
        "scopes": ["ingest:tides"],
        "source_label": "tides_simulated",
    }
    body.update(overrides)
    return client.post(
        "/machine/keys", json=body, headers=auth_header(fake_db, "cora")
    )


def test_issuance_returns_full_key_once_with_warning(client, fake_db):
    r = _issue(client, fake_db)
    assert r.status_code == 201
    body = r.json()
    assert body["key"].startswith("hwk_")
    assert body["key_prefix"] == body["key"][:12]
    assert "ONLY time" in body["warning"]
    assert body["scopes"] == ["ingest:tides"]
    assert body["source_label"] == "tides_simulated"
    # Issuance is audited — with metadata only, never key material.
    events = [e for e in fake_db.audit_events if e["action"] == "machine_key_issued"]
    assert len(events) == 1
    assert events[0]["actor"] == "cora"
    detail = json.loads(events[0]["detail"])
    assert detail["key_prefix"] == body["key_prefix"]
    assert body["key"] not in events[0]["detail"]


def test_only_hash_stored_no_plaintext_in_any_sql_params(client, fake_db):
    r = _issue(client, fake_db)
    full_key = r.json()["key"]
    # The stored row holds the SHA-256 hex, nothing key-shaped.
    (row,) = fake_db.api_keys.values()
    assert row["key_hash"] == machine_auth.hash_key(full_key)
    assert full_key != row["key_hash"]
    # No captured SQL statement ever carried the plaintext key: the response
    # is the only place it exists.
    for sql, params in fake_db.executed:
        assert full_key not in repr(params), f"plaintext key leaked into: {sql}"
        assert full_key not in sql


def test_issuance_is_admin_only(client, fake_db):
    for user in ("vera", "stella", "petra"):
        r = client.post(
            "/machine/keys",
            json={"name": "x", "scopes": ["read:metrics"]},
            headers=auth_header(fake_db, user),
        )
        assert r.status_code == 403
    assert fake_db.api_keys == {}


def test_unknown_scope_refused_deny_by_default(client, fake_db):
    r = _issue(client, fake_db, scopes=["ingest:tides", "admin:everything"])
    assert r.status_code == 422
    assert "admin:everything" in r.json()["detail"]
    assert fake_db.api_keys == {}


def test_ingest_scope_requires_source_label(client, fake_db):
    r = _issue(client, fake_db, source_label=None)
    assert r.status_code == 422
    assert "source label" in r.json()["detail"]
    assert fake_db.api_keys == {}


def test_revoke_sets_revoked_at_and_audits(client, fake_db):
    key_row, _ = fake_db.add_api_key()
    r = client.delete(
        f"/machine/keys/{key_row['key_id']}", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 200
    assert key_row["revoked_at"] is not None
    events = [e for e in fake_db.audit_events if e["action"] == "machine_key_revoked"]
    assert len(events) == 1 and events[0]["subject_id"] == key_row["key_id"]
    # Soft revoke: the row still exists (keys are never deleted).
    assert key_row["key_id"] in fake_db.api_keys
    # Revoking again is a plain-language 409; an unknown id is a 404.
    assert (
        client.delete(
            f"/machine/keys/{key_row['key_id']}",
            headers=auth_header(fake_db, "cora"),
        ).status_code
        == 409
    )
    assert (
        client.delete(
            "/machine/keys/00000000-0000-0000-0000-000000000000",
            headers=auth_header(fake_db, "cora"),
        ).status_code
        == 404
    )


def test_revoked_key_gets_401_and_is_audited(client, fake_db):
    key_row, full_key = fake_db.add_api_key(revoked=True)
    r = client.post(
        "/ingest/tides/passenger-events",
        content=b"a,b\n",
        headers=machine_header(full_key),
    )
    assert r.status_code == 401
    assert "revoked" in r.json()["detail"]
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_auth_failed"
    ]
    assert len(events) == 1
    assert events[0]["actor"] == f"key:{key_row['key_prefix']}"
    assert json.loads(events[0]["detail"])["reason"] == "key revoked"


def test_unknown_key_gets_401_and_is_audited(client, fake_db):
    r = client.post(
        "/ingest/tides/passenger-events",
        content=b"a,b\n",
        headers=machine_header("hwk_this-key-was-never-issued-anywhere"),
    )
    assert r.status_code == 401
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_auth_failed"
    ]
    assert len(events) == 1
    assert events[0]["actor"] == "key:" + "hwk_this-key-was-never-issued-anywhere"[:12]


def test_session_jwt_is_not_a_machine_key(client, fake_db):
    # A human session token must never authenticate a machine endpoint.
    r = client.post(
        "/ingest/tides/passenger-events",
        content=b"a,b\n",
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 401
    assert "hwk_" in r.json()["detail"]


def test_wrong_scope_gets_403_and_is_audited(client, fake_db):
    key_row, full_key = fake_db.add_api_key(
        scopes=("read:metrics",), source_label=None
    )
    r = client.post(
        "/ingest/tides/passenger-events",
        content=b"a,b\n",
        headers=machine_header(full_key),
    )
    assert r.status_code == 403
    assert "ingest:tides" in r.json()["detail"]
    events = [
        e for e in fake_db.audit_events if e["action"] == "machine_scope_denied"
    ]
    assert len(events) == 1
    assert events[0]["actor"] == f"key:{key_row['key_prefix']}"


def test_listing_never_exposes_hashes_or_keys(client, fake_db):
    key_row, full_key = fake_db.add_api_key(name="listed key")
    fake_db.add_api_key(name="revoked key", revoked=True)
    r = client.get("/machine/keys", headers=auth_header(fake_db, "cora"))
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 2
    assert {i["name"] for i in items} == {"listed key", "revoked key"}
    raw = r.text
    assert key_row["key_hash"] not in raw
    assert full_key not in raw
    assert "key_hash" not in raw
    listed = next(i for i in items if i["name"] == "listed key")
    assert listed["key_prefix"] == key_row["key_prefix"]
    assert listed["revoked_at"] is None
    # Listing is admin-only too.
    r = client.get("/machine/keys", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 403
