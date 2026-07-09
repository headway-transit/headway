"""Login, password hashing, and token verification."""

import jwt as pyjwt
import pytest

from conftest import TEST_SECRET, auth_header, token_for

from headway_api import auth


def test_password_hash_round_trip():
    h = auth.hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert auth.verify_password("correct horse battery staple", h)
    assert not auth.verify_password("wrong password", h)


def test_password_longer_than_72_bytes_is_rejected_not_truncated():
    with pytest.raises(auth.PasswordTooLong):
        auth.hash_password("x" * 73)
    # And a long password can never verify against anything.
    h = auth.hash_password("x" * 72)
    assert not auth.verify_password("x" * 73, h)


def test_login_issues_token_with_claim_set(client, fake_db):
    r = client.post(
        "/auth/login", json={"username": "cora", "password": "certifier-pass-1"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "certifying_official"
    claims = pyjwt.decode(body["access_token"], TEST_SECRET, algorithms=["HS256"])
    # The normalized claim set the OIDC RP (next increment) will also produce.
    assert claims["sub"] == fake_db.users["cora"]["user_id"]
    assert claims["username"] == "cora"
    assert claims["role"] == "certifying_official"
    assert claims["exp"] > claims["iat"]
    # Successful login is audit-logged.
    assert any(e["action"] == "login" and e["actor"] == "cora"
               for e in fake_db.audit_events)


def test_login_wrong_password_401_and_audited(client, fake_db):
    r = client.post("/auth/login", json={"username": "cora", "password": "nope"})
    assert r.status_code == 401
    assert "not recognized" in r.json()["detail"]
    assert any(e["action"] == "login_failed" for e in fake_db.audit_events)


def test_login_unknown_user_same_message_as_wrong_password(client):
    r = client.post("/auth/login", json={"username": "ghost", "password": "x"})
    assert r.status_code == 401
    assert "not recognized" in r.json()["detail"]


def test_login_disabled_account_403(client, fake_db):
    r = client.post(
        "/auth/login", json={"username": "dora", "password": "disabled-pass-1"}
    )
    assert r.status_code == 403
    assert "disabled" in r.json()["detail"]
    assert any(e["action"] == "login_denied" for e in fake_db.audit_events)


def test_no_token_is_401_with_plain_message(client):
    r = client.get("/metrics/values")
    assert r.status_code == 401
    assert "not signed in" in r.json()["detail"]


def test_expired_token_is_401(client, fake_db):
    headers = auth_header(fake_db, "vera", ttl_seconds=-10)
    r = client.get("/metrics/values", headers=headers)
    assert r.status_code == 401
    assert "expired" in r.json()["detail"]


def test_garbage_token_is_401(client):
    r = client.get(
        "/metrics/values", headers={"Authorization": "Bearer not.a.token"}
    )
    assert r.status_code == 401
    assert "could not be verified" in r.json()["detail"]


def test_token_signed_with_wrong_secret_is_401(client, fake_db):
    forged = pyjwt.encode(
        {"sub": "x", "username": "cora", "role": "certifying_official"},
        "some-other-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )
    r = client.get(
        "/metrics/values", headers={"Authorization": f"Bearer {forged}"}
    )
    assert r.status_code == 401


def test_token_with_unknown_role_is_401(client):
    bad_role = pyjwt.encode(
        {"sub": "x", "username": "cora", "role": "superadmin"},
        TEST_SECRET,
        algorithm="HS256",
    )
    r = client.get(
        "/metrics/values", headers={"Authorization": f"Bearer {bad_role}"}
    )
    assert r.status_code == 401


def test_token_helper_matches_login_token_shape(fake_db):
    t = token_for(fake_db, "vera")
    claims = pyjwt.decode(t, TEST_SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "username", "role", "iat", "exp"}
