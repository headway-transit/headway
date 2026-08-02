"""The single-sign-on configuration surface (handoff 0046, design point 7).

The honest card becomes a real screen. These tests pin what that screen is
allowed to do and, more importantly, what it is not: the client secret is
written once and never served back, `certifying_official` cannot be mapped,
every change is audited with what it was and what it became, and the test
action reports each step in language someone who has never configured OIDC
can act on.
"""

from __future__ import annotations

import json

import pytest

from conftest import (
    TEST_SECRET_ENCRYPTION_KEY,
    auth_header,
    configure_sso,
    map_claim,
)
from headway_api import secrets_at_rest


def _details(db, action):
    out = []
    for e in db.audit_events:
        if e["action"] == action:
            d = e["detail"]
            out.append(json.loads(d) if isinstance(d, str) else d)
    return out


VALID = {
    "discovery_url": (
        "https://idp.example.gov/realms/agency/.well-known/openid-configuration"
    ),
    "client_id": "headway-api",
    "client_secret": "provider-issued-client-secret",
    "redirect_uri": "https://headway.example.gov/auth/callback",
    "groups_claim": "groups",
    "username_claim": "preferred_username",
    "clock_skew_seconds": 120,
    "button_label": "Sign in with County SSO",
    "is_enabled": True,
}


# ---------------------------------------------------------------------------
# Who may configure it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("username", ["vera", "stella", "petra"])
def test_only_a_certifying_official_may_read_or_write_the_configuration(
    client, fake_db, username
):
    assert client.get(
        "/auth/oidc/config", headers=auth_header(fake_db, username)
    ).status_code == 403
    assert client.put(
        "/auth/oidc/config", json=VALID, headers=auth_header(fake_db, username)
    ).status_code == 403
    assert client.get(
        "/auth/oidc/mappings", headers=auth_header(fake_db, username)
    ).status_code == 403


def test_the_configuration_is_not_readable_without_signing_in(client):
    assert client.get("/auth/oidc/config").status_code == 401


# ---------------------------------------------------------------------------
# The client secret: encrypted at rest, show-once, never served back
# ---------------------------------------------------------------------------


def test_the_client_secret_is_encrypted_at_rest_and_never_served_back(
    client, fake_db
):
    saved = client.put(
        "/auth/oidc/config", json=VALID, headers=auth_header(fake_db, "cora")
    )
    assert saved.status_code == 200, saved.text

    stored = fake_db.oidc_provider["client_secret_encrypted"]
    assert stored.startswith("v1.aesgcm.")
    assert VALID["client_secret"] not in stored
    assert secrets_at_rest.decrypt(
        stored,
        associated_data=secrets_at_rest.AD_OIDC_CLIENT_SECRET,
        key=TEST_SECRET_ENCRYPTION_KEY,
    ) == VALID["client_secret"]

    read_back = client.get(
        "/auth/oidc/config", headers=auth_header(fake_db, "cora")
    )
    assert VALID["client_secret"] not in read_back.text
    assert read_back.json()["client_secret_set"] is True
    assert "client_secret" not in read_back.json()


def test_omitting_the_secret_keeps_the_stored_one(client, fake_db):
    client.put("/auth/oidc/config", json=VALID, headers=auth_header(fake_db, "cora"))
    stored = fake_db.oidc_provider["client_secret_encrypted"]

    edit = dict(VALID, groups_claim="roles")
    edit.pop("client_secret")
    r = client.put("/auth/oidc/config", json=edit, headers=auth_header(fake_db, "cora"))
    assert r.status_code == 200
    assert fake_db.oidc_provider["client_secret_encrypted"] == stored
    assert fake_db.oidc_provider["groups_claim"] == "roles"
    assert _details(fake_db, "sso_config_changed")[-1]["client_secret_changed"] is False


def test_the_secret_never_reaches_the_audit_trail(client, fake_db):
    client.put("/auth/oidc/config", json=VALID, headers=auth_header(fake_db, "cora"))
    dumped = json.dumps([{k: str(v) for k, v in e.items()} for e in fake_db.audit_events])
    assert VALID["client_secret"] not in dumped
    audited = _details(fake_db, "sso_config_changed")[0]
    assert audited["client_secret_changed"] is True
    assert "client_secret" not in json.dumps(audited["new"])


def test_with_no_at_rest_key_the_secret_is_refused_rather_than_stored(
    client, app, fake_db, monkeypatch
):
    """Fail loudly, applied to configuration: Headway never stores a secret
    in the clear because encryption was unavailable."""
    monkeypatch.delenv(secrets_at_rest.ENV_KEY, raising=False)
    monkeypatch.delenv(secrets_at_rest.ENV_KEY_FILE, raising=False)
    del app.state.secret_key

    r = client.put("/auth/oidc/config", json=VALID, headers=auth_header(fake_db, "cora"))
    assert r.status_code == 503
    assert "nowhere safe to keep this secret" in r.json()["detail"]
    assert fake_db.oidc_provider is None


def test_the_screen_is_told_up_front_when_secret_storage_is_unavailable(
    client, app, fake_db, monkeypatch
):
    """A warning before the admin types a credential beats a 503 after."""
    monkeypatch.delenv(secrets_at_rest.ENV_KEY, raising=False)
    monkeypatch.delenv(secrets_at_rest.ENV_KEY_FILE, raising=False)
    del app.state.secret_key
    r = client.get("/auth/oidc/config", headers=auth_header(fake_db, "cora"))
    assert r.json()["secret_storage_available"] is False


def test_turning_sso_on_without_a_secret_is_refused_in_plain_language(
    client, fake_db
):
    body = dict(VALID, client_secret="", is_enabled=True)
    r = client.put("/auth/oidc/config", json=body, headers=auth_header(fake_db, "cora"))
    assert r.status_code == 422
    assert "cannot be turned on without a client secret" in r.json()["detail"]
    assert "cannot show you the old one" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Validation, written for a zero-SQL reader
# ---------------------------------------------------------------------------


def test_an_http_discovery_url_is_refused_with_the_reason(client, fake_db):
    body = dict(
        VALID,
        discovery_url="http://idp.example.gov/.well-known/openid-configuration",
    )
    r = client.put("/auth/oidc/config", json=body, headers=auth_header(fake_db, "cora"))
    assert r.status_code == 422
    assert "must use https://" in r.json()["detail"]
    assert "take over every sign-in" in r.json()["detail"]


def test_an_http_redirect_uri_is_refused(client, fake_db):
    body = dict(VALID, redirect_uri="http://headway.example.gov/auth/callback")
    r = client.put("/auth/oidc/config", json=body, headers=auth_header(fake_db, "cora"))
    assert r.status_code == 422
    assert "must use https://" in r.json()["detail"]


def test_a_missing_ca_bundle_file_is_caught_when_the_form_is_saved(
    client, fake_db, tmp_path
):
    """The TLS-inspecting-proxy failure happens on the screen the admin is
    looking at, not at 8am on Monday for a member of staff."""
    body = dict(VALID, ca_bundle_path=str(tmp_path / "not-here.pem"))
    r = client.put("/auth/oidc/config", json=body, headers=auth_header(fake_db, "cora"))
    assert r.status_code == 422
    assert "There is no file at" in r.json()["detail"]
    assert "mounted into that container" in r.json()["detail"]

    real = tmp_path / "corp-ca.pem"
    real.write_text("-----BEGIN CERTIFICATE-----\n")
    ok = client.put(
        "/auth/oidc/config",
        json=dict(VALID, ca_bundle_path=str(real)),
        headers=auth_header(fake_db, "cora"),
    )
    assert ok.status_code == 200
    assert fake_db.oidc_provider["ca_bundle_path"] == str(real)


def test_the_clock_skew_tolerance_is_bounded(client, fake_db):
    for bad in (-1, 6000):
        r = client.put(
            "/auth/oidc/config",
            json=dict(VALID, clock_skew_seconds=bad),
            headers=auth_header(fake_db, "cora"),
        )
        assert r.status_code == 422


def test_a_configuration_change_is_audited_with_old_and_new(client, fake_db):
    client.put("/auth/oidc/config", json=VALID, headers=auth_header(fake_db, "cora"))
    client.put(
        "/auth/oidc/config",
        json=dict(VALID, groups_claim="roles", is_enabled=False),
        headers=auth_header(fake_db, "cora"),
    )
    second = _details(fake_db, "sso_config_changed")[1]
    assert second["old"]["groups_claim"] == "groups"
    assert second["old"]["is_enabled"] is True
    assert second["new"]["groups_claim"] == "roles"
    assert second["new"]["is_enabled"] is False


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------


def test_a_mapping_is_created_and_audited(client, fake_db):
    r = client.post(
        "/auth/oidc/mappings",
        json={
            "claim_value": "3f7a-transit-stewards",
            "headway_role": "data_steward",
            "note": "Transit data team",
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201
    assert r.json()["role_label"] == "data steward"
    audited = _details(fake_db, "sso_role_mapping_created")[0]
    assert audited["claim_value"] == "3f7a-transit-stewards"
    assert audited["headway_role"] == "data_steward"


def test_the_idp_cannot_be_given_the_certifying_official_role(client, fake_db):
    """The wave's central security decision, at the API layer. The message
    explains WHY, because an administrator told 'no' without a reason will
    look for a way around it."""
    r = client.post(
        "/auth/oidc/mappings",
        json={"claim_value": "domain-admins", "headway_role": "certifying_official"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "will not let your identity provider grant" in detail
    assert "legal attestation" in detail
    assert "Admin -> Users" in detail
    assert not fake_db.oidc_role_mappings


def test_an_unknown_role_is_refused_with_the_list_of_real_ones(client, fake_db):
    r = client.post(
        "/auth/oidc/mappings",
        json={"claim_value": "g", "headway_role": "superuser"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    assert "not a role Headway can grant from a group" in r.json()["detail"]
    assert "auditor" in r.json()["detail"]


def test_a_duplicate_claim_value_is_refused(client, fake_db):
    body = {"claim_value": "stewards", "headway_role": "data_steward"}
    assert client.post(
        "/auth/oidc/mappings", json=body, headers=auth_header(fake_db, "cora")
    ).status_code == 201
    again = client.post(
        "/auth/oidc/mappings",
        json={"claim_value": "stewards", "headway_role": "viewer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert again.status_code == 409
    assert "two deliberate steps in the audit trail" in again.json()["detail"]


def test_deleting_a_mapping_is_audited_and_leaves_accounts_alone(client, fake_db):
    mapping_id = map_claim(fake_db, "stewards", "data_steward")
    fake_db.add_user(
        "sso.steward", "data_steward", password_hash=None, auth_source="oidc",
        idp_issuer="https://idp.example.gov/realms/agency",
        idp_subject="idp-subject-0001",
    )
    r = client.delete(
        f"/auth/oidc/mappings/{mapping_id}", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 200
    assert not fake_db.oidc_role_mappings
    assert "sso.steward" in fake_db.users, (
        "deleting a mapping must not delete people's accounts as a side "
        "effect of a configuration edit"
    )
    audited = _details(fake_db, "sso_role_mapping_deleted")[0]
    assert audited["claim_value"] == "stewards"
    assert audited["headway_role"] == "data_steward"


def test_deleting_a_mapping_that_is_already_gone_is_a_404(client, fake_db):
    r = client.delete(
        "/auth/oidc/mappings/00000000-0000-0000-0000-000000000000",
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 404
    assert "Refresh the page" in r.json()["detail"]


# ---------------------------------------------------------------------------
# "Test this configuration"
# ---------------------------------------------------------------------------


def test_the_test_action_walks_the_whole_round_trip_and_passes(
    client, fake_db, fake_idp
):
    configure_sso(fake_db, fake_idp)
    map_claim(fake_db, "transit-data-stewards", "data_steward")
    r = client.post(
        "/auth/oidc/config/test", headers=auth_header(fake_db, "cora")
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True, body["steps"]
    steps = {s["step"]: s for s in body["steps"]}
    assert steps["reach your identity provider"]["ok"]
    assert fake_idp.issuer in steps["reach your identity provider"]["message"]
    assert steps["read the signing keys"]["ok"]
    assert "rotates them" in steps["read the signing keys"]["message"]
    assert steps["check the client id and secret"]["ok"]
    assert steps["check who would be allowed in"]["ok"]
    assert steps["single sign-on switch"]["ok"]


def test_the_test_action_catches_a_wrong_client_secret(client, fake_db, fake_idp):
    """The failure that discovery and JWKS both survive, and that otherwise
    only appears at the very last step of a real sign-in — usually to the
    first member of staff who tries."""
    configure_sso(fake_db, fake_idp, client_secret="a-stale-secret-from-a-rotation")
    map_claim(fake_db, "transit-data-stewards", "data_steward")
    r = client.post("/auth/oidc/config/test", headers=auth_header(fake_db, "cora"))
    body = r.json()
    assert body["ok"] is False
    step = [s for s in body["steps"] if s["step"] == "check the client id and secret"][0]
    assert step["ok"] is False
    assert "rejected Headway's client id or client secret" in step["message"]
    assert "no one was signed in" in step["message"]


def test_the_test_action_says_when_nobody_would_be_allowed_in(
    client, fake_db, fake_idp
):
    """Correct in configuration, useless in practice: everything reachable
    and not one group mapped, so every sign-in would be refused."""
    configure_sso(fake_db, fake_idp)
    r = client.post("/auth/oidc/config/test", headers=auth_header(fake_db, "cora"))
    body = r.json()
    assert body["ok"] is False
    step = [s for s in body["steps"] if s["step"] == "check who would be allowed in"][0]
    assert step["ok"] is False
    assert "every single sign-on attempt would be refused" in step["message"]


def test_the_test_action_says_when_sso_is_configured_but_still_switched_off(
    client, fake_db, fake_idp
):
    configure_sso(fake_db, fake_idp, enabled=False)
    map_claim(fake_db, "transit-data-stewards", "data_steward")
    body = client.post(
        "/auth/oidc/config/test", headers=auth_header(fake_db, "cora")
    ).json()
    step = [s for s in body["steps"] if s["step"] == "single sign-on switch"][0]
    assert step["ok"] is False
    assert "still turned off" in step["message"]


def test_the_test_action_explains_an_unreachable_provider(
    client, fake_db, fake_idp, fake_oidc_http
):
    configure_sso(fake_db, fake_idp)

    def unreachable(url):
        from headway_api.oidc import OidcConfigurationError, _network_message

        raise OidcConfigurationError(
            _network_message(url, ConnectionError("connection refused"))
        )

    fake_oidc_http.get_json = unreachable
    body = client.post(
        "/auth/oidc/config/test", headers=auth_header(fake_db, "cora")
    ).json()
    assert body["ok"] is False
    step = body["steps"][0]
    assert step["step"] == "reach your identity provider"
    assert "firewall rule, a proxy, or DNS" in step["message"]


def test_the_test_action_explains_a_tls_inspecting_proxy(
    client, fake_db, fake_idp, fake_oidc_http
):
    """The single most common way this integration fails in the field, and
    the one whose obvious workaround must never be offered."""
    configure_sso(fake_db, fake_idp)

    def cert_failure(url):
        from headway_api.oidc import OidcConfigurationError, _network_message

        raise OidcConfigurationError(
            _network_message(
                url,
                ConnectionError(
                    "certificate verify failed: unable to get local issuer certificate"
                ),
            )
        )

    fake_oidc_http.get_json = cert_failure
    body = client.post(
        "/auth/oidc/config/test", headers=auth_header(fake_db, "cora")
    ).json()
    message = body["steps"][0]["message"]
    assert "inspects encrypted traffic" in message
    assert "Certificate authority file" in message
    assert "will not turn certificate checking off" in message


def test_the_test_action_reports_nothing_configured_yet(client, fake_db):
    body = client.post(
        "/auth/oidc/config/test", headers=auth_header(fake_db, "cora")
    ).json()
    assert body["ok"] is False
    assert body["steps"][0]["step"] == "configuration"
    assert "Nothing is configured yet" in body["steps"][0]["message"]


def test_the_test_action_reports_a_secret_it_can_no_longer_decrypt(
    client, app, fake_db, fake_idp
):
    """The at-rest key changed (rotated, or a different file mounted). Loud,
    with what to do, and never a silent fall-through to an empty credential."""
    configure_sso(fake_db, fake_idp)
    app.state.secret_key = bytes.fromhex("ee" * 32)
    body = client.post(
        "/auth/oidc/config/test", headers=auth_header(fake_db, "cora")
    ).json()
    assert body["ok"] is False
    assert body["steps"][0]["step"] == "client secret"
    assert "encryption key has changed" in body["steps"][0]["message"]


def test_the_test_action_is_audited(client, fake_db, fake_idp):
    configure_sso(fake_db, fake_idp)
    map_claim(fake_db, "transit-data-stewards", "data_steward")
    r = client.post("/auth/oidc/config/test", headers=auth_header(fake_db, "cora"))
    audited = _details(fake_db, "sso_config_tested")[0]
    assert audited["ok"] is True
    assert {s["step"] for s in audited["steps"]} >= {"reach your identity provider"}
    assert r.json()["audit_event_id"] > 0


def test_the_test_action_never_carries_the_secret_into_its_response(
    client, fake_db, fake_idp
):
    configure_sso(fake_db, fake_idp)
    map_claim(fake_db, "transit-data-stewards", "data_steward")
    r = client.post("/auth/oidc/config/test", headers=auth_header(fake_db, "cora"))
    assert fake_idp.client_secret not in r.text


def test_saving_a_new_configuration_drops_the_cached_discovery_document(
    client, fake_db, fake_idp
):
    """A changed provider must never be tested, or used, against a cached
    document from the old one."""
    configure_sso(fake_db, fake_idp)
    map_claim(fake_db, "transit-data-stewards", "data_steward")
    client.post("/auth/oidc/config/test", headers=auth_header(fake_db, "cora"))
    fetches = fake_idp.discovery_fetches

    client.put(
        "/auth/oidc/config",
        json=dict(VALID, discovery_url=fake_idp.discovery_url),
        headers=auth_header(fake_db, "cora"),
    )
    client.post("/auth/oidc/config/test", headers=auth_header(fake_db, "cora"))
    assert fake_idp.discovery_fetches > fetches
