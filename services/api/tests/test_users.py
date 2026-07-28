"""User management v0 (handoff 0025, design point 1): certifying-official-
only endpoints, installer validation rules, append-only audit on every
change, no password hash ever served, the deactivated-login refusal, and
the LOCKOUT FAIL-SAFE — the last active certifying official can be neither
deactivated nor demoted."""

import json

from conftest import auth_header


def _actions(fake_db):
    return [e["action"] for e in fake_db.audit_events]


# ---------------------------------------------------------------------------
# Authorization matrix: every endpoint, every role
# ---------------------------------------------------------------------------


def test_every_users_endpoint_requires_authentication(client):
    assert client.get("/users").status_code == 401
    assert client.post("/users", json={}).status_code == 401
    assert client.post("/users/vera/reset-password", json={}).status_code == 401
    assert client.post("/users/vera/deactivate").status_code == 401
    assert client.post("/users/vera/reactivate").status_code == 401
    assert client.post("/users/vera/role", json={}).status_code == 401


def test_every_users_endpoint_is_certifying_official_only(client, fake_db):
    """viewer, data_steward AND report_preparer are all denied — user
    management is the v0 admin surface (the machine-keys precedent)."""
    for username in ("vera", "stella", "petra"):
        h = auth_header(fake_db, username)
        assert client.get("/users", headers=h).status_code == 403, username
        assert (
            client.post(
                "/users",
                json={"username": "n", "role": "viewer", "password": "x" * 8},
                headers=h,
            ).status_code
            == 403
        ), username
        assert (
            client.post(
                "/users/vera/reset-password",
                json={"password": "x" * 8},
                headers=h,
            ).status_code
            == 403
        ), username
        assert (
            client.post("/users/vera/deactivate", headers=h).status_code == 403
        ), username
        assert (
            client.post("/users/dora/reactivate", headers=h).status_code == 403
        ), username
        assert (
            client.post(
                "/users/vera/role", json={"role": "data_steward"}, headers=h
            ).status_code
            == 403
        ), username
    # Nothing changed and nothing was audited by the denied attempts.
    assert "nova" not in fake_db.users
    assert fake_db.users["vera"]["is_active"] is True
    assert fake_db.audit_events == []


# ---------------------------------------------------------------------------
# GET /users
# ---------------------------------------------------------------------------


def test_list_users_serves_accounts_without_any_password_material(
    client, fake_db
):
    r = client.get("/users", headers=auth_header(fake_db, "cora"))
    assert r.status_code == 200
    body = r.json()
    assert [u["username"] for u in body] == [
        "vera", "stella", "petra", "cora", "dora",
    ]
    dora = body[-1]
    assert dora["role"] == "viewer"
    assert dora["is_active"] is False
    assert dora["created_at"]
    # No hashes, ever — the field does not exist in the payload.
    for u in body:
        assert set(u) == {"username", "role", "is_active", "created_at"}
        for value in u.values():
            assert "$2b$" not in str(value)  # bcrypt marker


# ---------------------------------------------------------------------------
# POST /users — create
# ---------------------------------------------------------------------------


def test_create_user_hashes_password_and_audits(client, fake_db):
    r = client.post(
        "/users",
        json={
            "username": "nadia.ops",
            "role": "data_steward",
            "password": "a-fine-password",
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "nadia.ops"
    assert body["role"] == "data_steward"
    assert body["is_active"] is True
    assert "password" not in body and "password_hash" not in body

    stored = fake_db.users["nadia.ops"]
    assert stored["password_hash"] != "a-fine-password"
    assert stored["password_hash"].startswith("$2b$")

    events = [e for e in fake_db.audit_events if e["action"] == "user_created"]
    assert len(events) == 1
    assert events[0]["actor"] == "cora"
    assert events[0]["subject_kind"] == "auth.users"
    detail = json.loads(events[0]["detail"])
    assert detail == {"username": "nadia.ops", "role": "data_steward"}
    assert body["audit_event_id"] == events[0]["event_id"]

    # And the new account can actually sign in.
    login = client.post(
        "/auth/login",
        json={"username": "nadia.ops", "password": "a-fine-password"},
    )
    assert login.status_code == 200
    assert login.json()["role"] == "data_steward"


def test_create_user_duplicate_username_is_409(client, fake_db):
    r = client.post(
        "/users",
        json={"username": "vera", "role": "viewer", "password": "x" * 8},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]
    assert fake_db.audit_events == []


def test_create_user_invalid_username_is_422_installer_rule(client, fake_db):
    for bad in ("has space", "wr0ng!", "semi;colon", ""):
        r = client.post(
            "/users",
            json={"username": bad, "role": "viewer", "password": "x" * 8},
            headers=auth_header(fake_db, "cora"),
        )
        assert r.status_code == 422, bad
        assert "letters, numbers, dots, hyphens or underscores" in (
            r.json()["detail"]
        )
    assert fake_db.audit_events == []


def test_create_user_unknown_role_is_422_naming_the_four_roles(
    client, fake_db
):
    r = client.post(
        "/users",
        json={"username": "eve", "role": "superadmin", "password": "x" * 8},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    for role in ("viewer", "data_steward", "report_preparer",
                 "certifying_official"):
        assert role in detail
    assert "eve" not in fake_db.users


def test_create_user_short_password_is_422(client, fake_db):
    r = client.post(
        "/users",
        json={"username": "eve", "role": "viewer", "password": "short7!"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    assert "at least 8 characters" in r.json()["detail"]
    assert "eve" not in fake_db.users


def test_create_user_over_72_byte_password_is_422_never_truncated(
    client, fake_db
):
    r = client.post(
        "/users",
        json={"username": "eve", "role": "viewer", "password": "x" * 73},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    assert "72 bytes" in r.json()["detail"]
    assert "eve" not in fake_db.users


# ---------------------------------------------------------------------------
# POST /users/{username}/reset-password
# ---------------------------------------------------------------------------


def test_reset_password_changes_login_and_audits(client, fake_db):
    old_hash = fake_db.users["vera"]["password_hash"]
    r = client.post(
        "/users/vera/reset-password",
        json={"password": "brand-new-pass"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    assert fake_db.users["vera"]["password_hash"] != old_hash

    # Old password refused, new password accepted.
    assert (
        client.post(
            "/auth/login", json={"username": "vera", "password": "viewer-pass-1"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"username": "vera", "password": "brand-new-pass"}
        ).status_code
        == 200
    )

    events = [
        e for e in fake_db.audit_events if e["action"] == "user_password_reset"
    ]
    assert len(events) == 1
    assert events[0]["actor"] == "cora"
    # The audit detail carries WHO, never the password (in any form).
    assert json.loads(events[0]["detail"]) == {"username": "vera"}


def test_reset_password_unknown_user_is_404(client, fake_db):
    r = client.post(
        "/users/ghost/reset-password",
        json={"password": "x" * 8},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 404
    assert "ghost" in r.json()["detail"]


def test_reset_password_enforces_installer_rules(client, fake_db):
    old_hash = fake_db.users["vera"]["password_hash"]
    assert (
        client.post(
            "/users/vera/reset-password",
            json={"password": "seven77"},
            headers=auth_header(fake_db, "cora"),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/users/vera/reset-password",
            json={"password": "x" * 73},
            headers=auth_header(fake_db, "cora"),
        ).status_code
        == 422
    )
    assert fake_db.users["vera"]["password_hash"] == old_hash
    assert fake_db.audit_events == []


# ---------------------------------------------------------------------------
# Deactivate / reactivate — and the login refusal in between
# ---------------------------------------------------------------------------


def test_deactivate_then_login_refused_then_reactivate(client, fake_db):
    r = client.post(
        "/users/vera/deactivate", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_active"] is False
    assert "refused from now on" in body["note"]
    assert fake_db.users["vera"]["is_active"] is False

    # The deactivated account's login is the SAME generic 401 as a wrong
    # password — no enumeration oracle.
    denied = client.post(
        "/auth/login", json={"username": "vera", "password": "viewer-pass-1"}
    )
    wrong = client.post(
        "/auth/login", json={"username": "cora", "password": "nope"}
    )
    assert denied.status_code == wrong.status_code == 401
    assert denied.json()["detail"] == wrong.json()["detail"]

    r = client.post(
        "/users/vera/reactivate", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 200
    assert r.json()["is_active"] is True
    assert fake_db.users["vera"]["is_active"] is True

    # Reactivated: the original password works again.
    assert (
        client.post(
            "/auth/login", json={"username": "vera", "password": "viewer-pass-1"}
        ).status_code
        == 200
    )

    assert _actions(fake_db).count("user_deactivated") == 1
    assert _actions(fake_db).count("user_reactivated") == 1


def test_deactivate_already_inactive_is_409(client, fake_db):
    r = client.post(
        "/users/dora/deactivate", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 409
    assert "already deactivated" in r.json()["detail"]


def test_reactivate_already_active_is_409(client, fake_db):
    r = client.post(
        "/users/vera/reactivate", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 409
    assert "already active" in r.json()["detail"]


def test_deactivate_unknown_user_is_404(client, fake_db):
    r = client.post(
        "/users/ghost/deactivate", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# THE LOCKOUT FAIL-SAFE (handoff 0025: pin by test)
# ---------------------------------------------------------------------------


def test_last_active_certifying_official_cannot_be_deactivated(
    client, fake_db
):
    """cora is the only active certifying official in the fixture — the
    fail-safe must refuse, in plain language, and change nothing."""
    r = client.post(
        "/users/cora/deactivate", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "last active certifying official" in detail
    assert "certifying official first" in detail
    assert fake_db.users["cora"]["is_active"] is True
    assert fake_db.audit_events == []


def test_last_active_certifying_official_cannot_be_demoted(client, fake_db):
    r = client.post(
        "/users/cora/role",
        json={"role": "viewer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409
    assert "last active certifying official" in r.json()["detail"]
    assert fake_db.users["cora"]["role"] == "certifying_official"
    assert fake_db.audit_events == []


def test_second_active_admin_unlocks_deactivation(client, fake_db):
    """With ANOTHER active certifying official, cora may be deactivated —
    the guard counts active admins, it does not freeze the admin role."""
    fake_db.add_user("carl", "certifying_official", password_hash="$2b$x")
    r = client.post(
        "/users/cora/deactivate", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 200
    assert fake_db.users["cora"]["is_active"] is False


def test_deactivated_admin_does_not_count_toward_the_guard(client, fake_db):
    """An INACTIVE second certifying official must not satisfy the guard —
    it counts active admins only."""
    fake_db.add_user(
        "carl", "certifying_official", is_active=False, password_hash="$2b$x"
    )
    r = client.post(
        "/users/cora/deactivate", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 409
    assert fake_db.users["cora"]["is_active"] is True


def test_promoting_to_certifying_official_never_trips_the_guard(
    client, fake_db
):
    r = client.post(
        "/users/petra/role",
        json={"role": "certifying_official"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    assert fake_db.users["petra"]["role"] == "certifying_official"
    # And now cora CAN step down — two active admins exist.
    r = client.post(
        "/users/cora/role",
        json={"role": "viewer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    assert fake_db.users["cora"]["role"] == "viewer"


# ---------------------------------------------------------------------------
# POST /users/{username}/role
# ---------------------------------------------------------------------------


def test_role_change_audits_old_and_new(client, fake_db):
    r = client.post(
        "/users/vera/role",
        json={"role": "report_preparer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "report_preparer"
    assert "next sign-in" in body["note"]
    events = [
        e for e in fake_db.audit_events if e["action"] == "user_role_changed"
    ]
    assert len(events) == 1
    assert json.loads(events[0]["detail"]) == {
        "username": "vera",
        "old_role": "viewer",
        "new_role": "report_preparer",
    }


def test_role_change_to_same_role_is_409(client, fake_db):
    r = client.post(
        "/users/vera/role",
        json={"role": "viewer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409
    assert "already has" in r.json()["detail"]


def test_role_change_unknown_role_is_422(client, fake_db):
    r = client.post(
        "/users/vera/role",
        json={"role": "admin"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    assert fake_db.users["vera"]["role"] == "viewer"
