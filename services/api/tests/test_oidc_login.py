"""The federated sign-in path end to end (handoff 0046).

Every test here drives the REAL endpoints: start, the provider hop, callback.
The provider is a fake transport over real RSA keys, and its token endpoint
verifies PKCE and the client secret for real, so a break in either fails here
the way it would fail against Entra ID.

What is being pinned:

* the flow works, and produces a session that names BOTH the Headway username
  and the IdP subject;
* an unmapped claim grants nothing and creates nothing;
* the IdP can neither grant nor revoke ``certifying_official``;
* ``state`` is single-use and bound to the browser that started the sign-in;
* local accounts keep working throughout — the break-glass guarantee;
* every failure returns one generic message, and the audit trail keeps the
  real reason without letting an anonymous caller amplify writes into it.
"""

from __future__ import annotations

import datetime as dt
import json

import jwt as pyjwt
import pytest

from conftest import (
    TEST_SECRET,
    UTC,
    auth_header,
    configure_sso,
    map_claim,
    sso_sign_in,
)


def _details(db, action):
    out = []
    for e in db.audit_events:
        if e["action"] == action:
            detail = e["detail"]
            out.append(json.loads(detail) if isinstance(detail, str) else detail)
    return out


def _reasons(db):
    return [d["reason"] for d in _details(db, "sso_login_failed")]


@pytest.fixture
def sso(fake_db, fake_idp):
    configure_sso(fake_db, fake_idp)
    map_claim(fake_db, "transit-data-stewards", "data_steward")
    map_claim(fake_db, "external-audit-readonly", "auditor")
    return fake_idp


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


def test_a_mapped_user_signs_in_and_is_provisioned(client, fake_db, sso):
    r = sso_sign_in(client, sso, username="sso.steward", groups=["transit-data-stewards"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "sso.steward"
    assert body["role"] == "data_steward"

    account = fake_db.users["sso.steward"]
    assert account["auth_source"] == "oidc"
    assert account["idp_issuer"] == sso.issuer
    assert account["idp_subject"] == "idp-subject-0001"
    # A federated account has NO password (migration 0043): a dummy hash
    # would be a lie a future reader could mistake for a credential.
    assert account["password_hash"] is None

    provisioned = _details(fake_db, "sso_user_provisioned")
    assert provisioned and provisioned[0]["idp_subject"] == "idp-subject-0001"


def test_the_session_names_both_the_username_and_the_idp_subject(client, fake_db, sso):
    """The certification guardrail. "An SSO user" is not a signer; a
    signature whose signer cannot be resolved years later is not a
    signature."""
    r = sso_sign_in(client, sso, groups=["transit-data-stewards"])
    claims = pyjwt.decode(
        r.json()["access_token"], TEST_SECRET, algorithms=["HS256"]
    )
    assert claims["username"] == "sso.steward"
    assert claims["idp_issuer"] == sso.issuer
    assert claims["idp_subject"] == "idp-subject-0001"
    assert claims["jti"]

    logins = _details(fake_db, "login")
    federated = [d for d in logins if d.get("authenticated_via") == "oidc"]
    assert federated[0]["idp_subject"] == "idp-subject-0001"
    assert federated[0]["idp_issuer"] == sso.issuer


def test_a_certifying_official_signing_in_by_sso_signs_with_full_attribution(
    client, fake_db, sso
):
    """The signed certification document records who signed with at least the
    fidelity it had before federation existed — the Headway username AND the
    IdP subject, inside the signed bytes, forever."""
    fake_db.add_user(
        "sso.official", "certifying_official", password_hash=None,
        auth_source="oidc", idp_issuer=sso.issuer, idp_subject="idp-subject-cert",
    )
    r = sso_sign_in(
        client, sso, sub="idp-subject-cert", username="sso.official",
        groups=["transit-data-stewards"],
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert r.json()["role"] == "certifying_official"

    mv = fake_db.add_metric_value()
    certified = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv["metric_value_id"]],
            "attestation": "I attest these figures are correct.",
            "signer_full_name": "Test Certifier",
            "signer_title": "Chief Financial Officer",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert certified.status_code == 201, certified.text
    document = json.loads(certified.json()["canonical_document"])
    certifier = document["certifier"]
    assert certifier["username"] == "sso.official"
    assert certifier["idp_issuer"] == sso.issuer
    assert certifier["idp_subject"] == "idp-subject-cert"
    assert certifier["authenticated_via"] == "oidc"

    audited = _details(fake_db, "certify")[0]
    assert audited["idp_subject"] == "idp-subject-cert"
    assert audited["authenticated_via"] == "oidc"


def test_a_local_certification_document_is_unchanged_by_this_wave(client, fake_db):
    """Federation must not rewrite the shape of a LOCAL signature. A local
    certifier's document carries the same keys it always did, so previously
    signed records and new ones stay comparable."""
    mv = fake_db.add_metric_value()
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv["metric_value_id"]],
            "attestation": "I attest.",
            "signer_full_name": "Cora Certifier",
            "signer_title": "CFO",
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201
    certifier = json.loads(r.json()["canonical_document"])["certifier"]
    assert set(certifier) == {"username", "role", "typed_full_name", "typed_title"}


# ---------------------------------------------------------------------------
# Deny-by-default: an unmapped claim grants NOTHING
# ---------------------------------------------------------------------------


def test_an_unmapped_claim_grants_nothing_and_creates_nothing(client, fake_db, sso):
    before = set(fake_db.users)
    r = sso_sign_in(
        client, sso, username="unmapped.user", groups=["some-other-department"]
    )
    assert r.status_code == 401
    assert set(fake_db.users) == before, "no account may be created"
    assert "could not sign you in" in r.json()["detail"]
    assert any("no configured mapping matched" in x for x in _reasons(fake_db))


def test_no_groups_at_all_grants_nothing(client, fake_db, sso):
    r = sso_sign_in(client, sso, username="unmapped.user", groups=[])
    assert r.status_code == 401
    assert "unmapped.user" not in fake_db.users


def test_an_unmapped_user_never_falls_back_to_viewer(client, fake_db, sso):
    """The specific failure mode deny-by-default exists to prevent: a
    fallback role is how an IdP group nobody audited becomes access nobody
    granted."""
    r = sso_sign_in(client, sso, username="unmapped.user", groups=["unknown-group"])
    assert r.status_code == 401
    assert not any(u.get("role") == "viewer" and u["username"] == "unmapped.user"
                   for u in fake_db.users.values())


def test_claim_matching_is_exact_and_case_sensitive(client, fake_db, sso):
    """No prefixes, no globs, no regular expressions and no case folding. A
    pattern language here is a place for a mistake to hide, and Entra ID
    emits opaque group object ids anyway, which are exact by nature."""
    for near_miss in ("Headway-Stewards", "headway-steward", "transit-data-stewards-2",
                      "stewards"):
        r = sso_sign_in(client, sso, username="nearmiss.user", groups=[near_miss])
        assert r.status_code == 401, near_miss
    assert "nearmiss.user" not in fake_db.users


def test_surrounding_whitespace_in_a_claim_value_is_trimmed_not_rejected(
    client, fake_db, sso
):
    """The one normalization applied, deliberately: a provider that pads a
    group value should not produce a sign-in failure nobody can diagnose.
    Everything inside the value is still matched exactly."""
    r = sso_sign_in(
        client, sso, username="padded.claim", groups=["  transit-data-stewards  "]
    )
    assert r.status_code == 200
    assert r.json()["role"] == "data_steward"


def test_several_matching_mappings_resolve_to_the_least_privileged(
    client, fake_db, sso
):
    """A configuration that says two things at once is answered with the
    safest of them, and the audit record names every mapping that matched so
    the ambiguity is visible rather than silently resolved upward."""
    map_claim(fake_db, "transit-planning-readonly", "viewer")
    r = sso_sign_in(
        client, sso, username="dual.mapped",
        groups=["transit-data-stewards", "transit-planning-readonly"],
    )
    assert r.status_code == 200
    assert r.json()["role"] == "viewer"
    detail = _details(fake_db, "sso_user_provisioned")[0]
    assert sorted(detail["claim_values_matched"]) == [
        "transit-data-stewards", "transit-planning-readonly"
    ]


def test_the_auditor_role_is_grantable_from_a_group(client, fake_db, sso):
    """An auditor grant creates no ability to change anything, so federating
    it costs nothing — and offboarding an auditor in the directory should
    offboard them here."""
    r = sso_sign_in(
        client, sso, username="ext.auditor", groups=["external-audit-readonly"]
    )
    assert r.status_code == 200
    assert r.json()["role"] == "auditor"
    denied = client.post(
        "/users",
        json={"username": "x.y", "role": "viewer", "password": "abcd1234"},
        headers={"Authorization": f"Bearer {r.json()['access_token']}"},
    )
    assert denied.status_code == 403


# ---------------------------------------------------------------------------
# The IdP may not grant, or revoke, certifying_official
# ---------------------------------------------------------------------------


def test_the_idp_cannot_escalate_anyone_to_certifying_official(
    client, fake_db, sso
):
    """Even with a mapping row that says otherwise — the login path re-checks
    rather than trusting the row it read, because a row can arrive from a
    hand-edited database or a restored backup."""
    fake_db.oidc_role_mappings["hand-edited"] = {
        "mapping_id": "hand-edited",
        "claim_value": "domain-admins",
        "headway_role": "certifying_official",
        "note": "planted, as if by direct SQL",
        "created_by": "someone",
        "created_at": dt.datetime(2026, 8, 1, tzinfo=UTC),
    }
    r = sso_sign_in(client, sso, username="escalation.attempt", groups=["domain-admins"])
    assert r.status_code == 401
    assert "escalation.attempt" not in fake_db.users


def test_resolve_role_filters_certifying_official_out():
    from headway_api.routers.oidc import resolve_role

    role, matched = resolve_role(
        ("admins",), [("admins", "certifying_official")]
    )
    assert role is None
    assert matched == ["admins"]
    assert "certifying_official" not in __import__(
        "headway_api.routers.oidc", fromlist=["x"]
    ).IDP_GRANTABLE_ROLES


def test_the_idp_cannot_revoke_a_locally_granted_certifying_official(
    client, fake_db, sso
):
    """The mirror rule. If a group membership could remove it, the set of
    people who may sign a federal submission would still be controlled from
    the directory — just by subtraction."""
    fake_db.add_user(
        "sso.official", "certifying_official", password_hash=None, auth_source="oidc",
        idp_issuer=sso.issuer, idp_subject="idp-subject-cert",
    )
    r = sso_sign_in(
        client, sso, sub="idp-subject-cert", username="sso.official",
        groups=["transit-data-stewards"],  # maps to data_steward
    )
    assert r.status_code == 200
    assert r.json()["role"] == "certifying_official"
    assert fake_db.users["sso.official"]["role"] == "certifying_official"

    retained = _details(fake_db, "sso_role_retained_local")
    assert retained[0]["mapped_role"] == "data_steward"
    assert retained[0]["retained_role"] == "certifying_official"
    assert "cannot grant or revoke" in retained[0]["reason"]


def test_the_last_admin_lockout_fail_safe_is_consulted_on_the_sso_path(
    client, fake_db, sso
):
    """Migration 0032, applied to the federated path. `cora` is the only
    active certifying official; a directory change must not be able to leave
    this agency with nobody who can certify."""
    fake_db.users.pop("cora")
    fake_db.add_user(
        "sso.official", "certifying_official", password_hash=None, auth_source="oidc",
        idp_issuer=sso.issuer, idp_subject="idp-subject-cert",
    )
    assert sum(
        1 for u in fake_db.users.values()
        if u["role"] == "certifying_official" and u["is_active"]
    ) == 1

    r = sso_sign_in(
        client, sso, sub="idp-subject-cert", username="sso.official",
        groups=["external-audit-readonly"],  # the directory says: read-only now
    )
    assert r.status_code == 200
    assert r.json()["role"] == "certifying_official"
    retained = _details(fake_db, "sso_role_retained_local")[0]
    assert retained["would_have_been_last_certifying_official"] is True


def test_the_admin_lockout_guard_still_covers_a_federated_account(client, fake_db, sso):
    """And the ordinary admin path refuses to deactivate the last certifying
    official even when that account is a federated one."""
    fake_db.users.pop("cora")
    fake_db.add_user(
        "sso.official", "certifying_official", password_hash=None, auth_source="oidc",
        idp_issuer=sso.issuer, idp_subject="idp-subject-cert",
    )
    fake_db.add_user("cora2", "certifying_official", password_hash=None,
                     auth_source="oidc", idp_issuer=sso.issuer,
                     idp_subject="idp-subject-cert-2")
    # Two admins: deactivating one is fine.
    ok = client.post(
        "/users/cora2/deactivate", headers=auth_header(fake_db, "sso.official")
    )
    assert ok.status_code == 200
    # One left: refused.
    refused = client.post(
        "/users/sso.official/deactivate", headers=auth_header(fake_db, "sso.official")
    )
    assert refused.status_code == 409
    assert "last active certifying official" in refused.json()["detail"]


def test_an_ordinary_role_change_from_the_idp_is_applied_and_audited(
    client, fake_db, sso
):
    fake_db.add_user(
        "sso.steward", "viewer", password_hash=None, auth_source="oidc",
        idp_issuer=sso.issuer, idp_subject="idp-subject-0001",
    )
    r = sso_sign_in(client, sso, groups=["transit-data-stewards"])
    assert r.json()["role"] == "data_steward"
    assert fake_db.users["sso.steward"]["role"] == "data_steward"
    changed = _details(fake_db, "sso_role_synchronized")[0]
    assert changed["old_role"] == "viewer"
    assert changed["new_role"] == "data_steward"


# ---------------------------------------------------------------------------
# state / nonce / PKCE / session fixation
# ---------------------------------------------------------------------------


def test_a_replayed_state_is_refused(client, fake_db, sso):
    """Single use, enforced by a conditional UPDATE so two concurrent
    callbacks cannot both win."""
    started = client.post("/auth/oidc/start").json()
    code = sso.authorize(started["authorization_url"])
    sso.codes[code]["claims"] = {"groups": ["transit-data-stewards"]}
    payload = {
        "code": code,
        "state": started["state"],
        "browser_token": started["browser_token"],
    }
    assert client.post("/auth/oidc/callback", json=payload).status_code == 200

    replayed = client.post("/auth/oidc/callback", json=payload)
    assert replayed.status_code == 401
    assert any("replayed" in x for x in _reasons(fake_db))


def test_a_state_this_api_never_issued_is_refused(client, fake_db, sso):
    r = client.post(
        "/auth/oidc/callback",
        json={"code": "anything", "state": "invented", "browser_token": "x"},
    )
    assert r.status_code == 401
    assert r.json()["detail"].startswith("Headway could not sign you in")


def test_an_expired_state_is_refused(client, fake_db, sso):
    started = client.post("/auth/oidc/start").json()
    row = fake_db.oidc_login_states[started["state"]]
    row["expires_at"] = dt.datetime.now(UTC) - dt.timedelta(seconds=1)
    code = sso.authorize(started["authorization_url"])
    r = client.post(
        "/auth/oidc/callback",
        json={
            "code": code,
            "state": started["state"],
            "browser_token": started["browser_token"],
        },
    )
    assert r.status_code == 401
    assert any("expired" in x for x in _reasons(fake_db))


def test_a_callback_from_a_different_browser_is_refused(client, fake_db, sso):
    """The no-cookie equivalent of state-bound-to-session: an attacker who
    feeds their own authorization response to a victim's browser does not
    have the victim's browser token."""
    started = client.post("/auth/oidc/start").json()
    code = sso.authorize(started["authorization_url"])
    r = client.post(
        "/auth/oidc/callback",
        json={
            "code": code,
            "state": started["state"],
            "browser_token": "a-token-from-somewhere-else",
        },
    )
    assert r.status_code == 401
    assert any("browser binding" in x for x in _reasons(fake_db))


def test_the_browser_token_is_never_stored_in_the_clear(client, fake_db, sso):
    started = client.post("/auth/oidc/start").json()
    row = fake_db.oidc_login_states[started["state"]]
    assert row["browser_binding"] != started["browser_token"]
    assert started["browser_token"] not in json.dumps(
        {k: str(v) for k, v in row.items()}
    )


def test_the_pkce_verifier_never_leaves_the_api(client, fake_db, sso):
    started = client.post("/auth/oidc/start").json()
    verifier = fake_db.oidc_login_states[started["state"]]["code_verifier"]
    assert verifier not in json.dumps(started)
    assert verifier not in started["authorization_url"]


def test_the_token_exchange_actually_sends_the_pkce_verifier(client, fake_db, sso):
    """The fake provider verifies S256 for real, so a missing or wrong
    verifier fails at the token endpoint the way a provider would fail it."""
    r = sso_sign_in(client, sso, groups=["transit-data-stewards"])
    assert r.status_code == 200
    exchange = [c for c in sso.token_calls if not c.get("probe")][-1]
    assert exchange["data"]["grant_type"] == "authorization_code"
    assert exchange["data"]["code_verifier"]
    assert exchange["auth"] == (sso.client_id, sso.client_secret)


def test_each_started_sign_in_gets_a_new_session_and_state(client, fake_db, sso):
    first = sso_sign_in(client, sso, groups=["transit-data-stewards"])
    second = sso_sign_in(client, sso, groups=["transit-data-stewards"])
    a = pyjwt.decode(first.json()["access_token"], TEST_SECRET, algorithms=["HS256"])
    b = pyjwt.decode(second.json()["access_token"], TEST_SECRET, algorithms=["HS256"])
    assert a["jti"] != b["jti"]
    # And the pre-login rows are consumed, so nothing the browser held before
    # signing in carries any authority afterwards.
    assert all(row["consumed_at"] is not None
               for row in fake_db.oidc_login_states.values())


def test_a_stale_id_token_nonce_is_refused_end_to_end(client, fake_db, sso):
    started = client.post("/auth/oidc/start").json()
    code = sso.authorize(started["authorization_url"])
    sso.codes[code]["nonce"] = "a-nonce-from-a-different-sign-in"
    sso.codes[code]["claims"] = {"groups": ["transit-data-stewards"]}
    r = client.post(
        "/auth/oidc/callback",
        json={
            "code": code,
            "state": started["state"],
            "browser_token": started["browser_token"],
        },
    )
    assert r.status_code == 401
    assert any("nonce did not match" in x for x in _reasons(fake_db))


# ---------------------------------------------------------------------------
# Local accounts survive — the break-glass guarantee
# ---------------------------------------------------------------------------


def test_local_sign_in_works_while_sso_is_configured_and_enabled(client, fake_db, sso):
    r = client.post(
        "/auth/login", json={"username": "cora", "password": "certifier-pass-1"}
    )
    assert r.status_code == 200
    assert r.json()["role"] == "certifying_official"


def test_local_sign_in_works_when_the_idp_is_completely_unreachable(
    client, fake_db, sso, fake_oidc_http
):
    """An IdP outage, or an air-gapped box. The local path does not consult
    the OIDC configuration at all, so there is nothing for the outage to
    break."""
    def unreachable(url):
        from headway_api.oidc import OidcConfigurationError

        raise OidcConfigurationError("Headway could not reach the provider.")

    fake_oidc_http.get_json = unreachable
    assert client.post("/auth/oidc/start").status_code == 503

    r = client.post(
        "/auth/login", json={"username": "cora", "password": "certifier-pass-1"}
    )
    assert r.status_code == 200


def test_the_environment_kill_switch_turns_sso_off_without_the_database(
    client, app, fake_db, sso
):
    """Break-glass: the first OIDC configuration attempt will be wrong, and
    there must be a way in that does not depend on the thing being
    configured."""
    app.state.oidc_disabled = True
    assert client.get("/auth/oidc/status").json() == {
        "enabled": False, "button_label": ""
    }
    assert client.post("/auth/oidc/start").status_code == 404
    r = client.post(
        "/auth/login", json={"username": "cora", "password": "certifier-pass-1"}
    )
    assert r.status_code == 200


def test_a_federated_account_cannot_be_signed_into_with_a_password(
    client, fake_db, sso
):
    """It has no password (migration 0043), and the refusal is the SAME
    generic message as a wrong password, so the login surface never reveals
    how an account signs in."""
    fake_db.add_user(
        "sso.official", "data_steward", password_hash=None, auth_source="oidc",
        idp_issuer=sso.issuer, idp_subject="idp-subject-cert",
    )
    federated = client.post(
        "/auth/login", json={"username": "sso.official", "password": "anything-at-all"}
    )
    wrong_password = client.post(
        "/auth/login", json={"username": "cora", "password": "wrong"}
    )
    no_such_user = client.post(
        "/auth/login", json={"username": "nobody.here", "password": "wrong"}
    )
    assert federated.status_code == wrong_password.status_code == 401
    assert no_such_user.status_code == 401
    assert (
        federated.json()["detail"]
        == wrong_password.json()["detail"]
        == no_such_user.json()["detail"]
    )
    reasons = [d["reason"] for d in _details(fake_db, "login_failed")]
    assert "no local password (federated account)" in reasons


def test_sso_will_not_silently_take_over_an_existing_local_account(
    client, fake_db, sso
):
    """Otherwise anyone who can create a user with the right name at the IdP
    takes over a Headway account — and destroys its break-glass password on
    the way in."""
    r = sso_sign_in(client, sso, username="cora", groups=["transit-data-stewards"])
    assert r.status_code == 401
    assert fake_db.users["cora"]["auth_source"] == "local"
    assert fake_db.users["cora"]["password_hash"] is not None
    refused = _details(fake_db, "sso_provisioning_refused")
    assert refused and "local account already uses this username" in refused[0]["reason"]


def test_a_deactivated_federated_account_is_refused(client, fake_db, sso):
    fake_db.add_user(
        "sso.official", "data_steward", password_hash=None, auth_source="oidc",
        idp_issuer=sso.issuer, idp_subject="idp-subject-cert", is_active=False,
    )
    r = sso_sign_in(
        client, sso, sub="idp-subject-cert", username="sso.official",
        groups=["transit-data-stewards"],
    )
    assert r.status_code == 401
    assert any("deactivated" in x for x in _reasons(fake_db))


# ---------------------------------------------------------------------------
# No-leak errors, and no audit amplification
# ---------------------------------------------------------------------------


def test_every_sign_in_failure_returns_the_identical_message(client, fake_db, sso):
    """A probing caller learns nothing: not whether the account exists, not
    whether it was mapped, not which check failed."""
    messages = set()

    unmapped = sso_sign_in(client, sso, username="a.person", groups=["nope"])
    messages.add(unmapped.json()["detail"])

    forged_state = client.post(
        "/auth/oidc/callback",
        json={"code": "x", "state": "invented", "browser_token": "y"},
    )
    messages.add(forged_state.json()["detail"])

    fake_db.add_user(
        "deactivated.user", "viewer", password_hash=None, auth_source="oidc",
        idp_issuer=sso.issuer, idp_subject="idp-subject-gone", is_active=False,
    )
    deactivated = sso_sign_in(
        client, sso, sub="idp-subject-gone", username="deactivated.user",
        groups=["transit-data-stewards"],
    )
    messages.add(deactivated.json()["detail"])

    bad_audience = sso_sign_in(
        client, sso, groups=["transit-data-stewards"], aud="a-different-app"
    )
    messages.add(bad_audience.json()["detail"])

    assert len(messages) == 1, messages
    assert "audit trail" in messages.pop()


def test_repeated_forged_callbacks_do_not_amplify_into_the_audit_table(
    client, fake_db, sso
):
    """The machine_auth.FailureAuditThrottle pattern applied to the
    unauthenticated sign-in surface: the FIRST failure is recorded so probing
    stays visible, and the rest are counted, not written. Without it an
    unauthenticated actor turns one request into one INSERT, forever, at no
    cost to themselves."""
    for _ in range(200):
        client.post(
            "/auth/oidc/callback",
            json={"code": "x", "state": "invented", "browser_token": "y"},
        )
    written = _details(fake_db, "sso_login_failed")
    assert 0 < len(written) <= 2, f"{len(written)} audit rows for 200 requests"
    assert written[0]["reason"].startswith("state unknown")


def test_the_suppressed_count_is_folded_into_the_next_recorded_event(
    client, app, fake_db, sso
):
    """Coalesced, not dropped: the trail still says how many were hidden."""
    throttle = app.state.login_audit_throttle
    for _ in range(5):
        client.post(
            "/auth/oidc/callback",
            json={"code": "x", "state": "invented", "browser_token": "y"},
        )
    throttle.window = 0.0  # the window elapses
    client.post(
        "/auth/oidc/callback",
        json={"code": "x", "state": "invented", "browser_token": "y"},
    )
    written = _details(fake_db, "sso_login_failed")
    assert written[-1]["suppressed_since_last"] == 4


def test_the_status_endpoint_tells_an_anonymous_caller_almost_nothing(
    client, fake_db, sso
):
    r = client.get("/auth/oidc/status")
    assert r.status_code == 200
    assert set(r.json()) == {"enabled", "button_label"}
    assert r.json()["enabled"] is True
    assert r.json()["button_label"] == "Sign in with County SSO"
    body = r.text
    assert sso.client_id not in body
    assert sso.issuer not in body
    assert sso.client_secret not in body


def test_start_and_callback_are_refused_when_sso_is_not_enabled(client, fake_db, fake_idp):
    configure_sso(fake_db, fake_idp, enabled=False)
    assert client.get("/auth/oidc/status").json()["enabled"] is False
    assert client.post("/auth/oidc/start").status_code == 404
    assert client.post(
        "/auth/oidc/callback",
        json={"code": "x", "state": "y", "browser_token": "z"},
    ).status_code == 404


def test_nothing_in_the_audit_trail_ever_carries_the_client_secret(
    client, fake_db, sso
):
    sso_sign_in(client, sso, groups=["transit-data-stewards"])
    sso_sign_in(client, sso, groups=["nope"])
    dumped = json.dumps(
        [{k: str(v) for k, v in e.items()} for e in fake_db.audit_events]
    )
    assert sso.client_secret not in dumped


# ---------------------------------------------------------------------------
# No built-in group name, and no naming convention a customer must adopt
# ---------------------------------------------------------------------------


def test_no_group_name_is_built_in_anywhere(client, fake_db, fake_idp):
    """A product rename must never require a CUSTOMER to edit THEIR identity
    provider.

    So there is no default group, no seeded mapping, and no fallback: with a
    provider configured and NOT ONE mapping, every sign-in is refused no
    matter what the user's groups are called. An agency maps the groups its
    directory already has; Headway never expects to find a group of its own.
    """
    configure_sso(fake_db, fake_idp)
    assert fake_db.oidc_role_mappings == {}, "no migration may seed a mapping"

    for index, groups in enumerate((
        ["transit-data-stewards"],
        ["GIS-Admins"],
        ["Finance"],
        ["headway-stewards"],  # even a product-shaped name grants nothing
        ["b7f1c0de-0000-4000-8000-abcdefabcdef"],  # an Entra ID object id
    )):
        r = sso_sign_in(
            client, fake_idp, username=f"nobody{index}",
            groups=groups, sub=f"idp-subject-nobody-{index}",
        )
        assert r.status_code == 401, groups
    assert not any(u["auth_source"] == "oidc" for u in fake_db.users.values())


def test_any_group_name_at_all_can_be_mapped(client, fake_db, fake_idp):
    """The other half: whatever an agency's groups are called — including
    names with capitals, spaces, or an opaque directory object id — mapping
    one grants exactly the role the admin chose."""
    configure_sso(fake_db, fake_idp)
    for claim, username in (
        ("GIS-Admins", "gis.person"),
        ("Transit Finance", "finance.person"),
        ("b7f1c0de-0000-4000-8000-abcdefabcdef", "entra.person"),
    ):
        map_claim(fake_db, claim, "viewer")
        r = sso_sign_in(
            client, fake_idp, username=username, groups=[claim],
            sub=f"idp-subject-{username}",
        )
        assert r.status_code == 200, f"{claim} -> {r.text}"
        assert r.json()["role"] == "viewer"


def test_the_group_claim_name_itself_is_configurable(client, fake_db, fake_idp):
    """'groups' is the common case, not an assumption. An installation whose
    provider calls it 'roles' (or 'wids', or anything else) configures that,
    and nothing else changes."""
    configure_sso(fake_db, fake_idp, groups_claim="roles")
    map_claim(fake_db, "Transit-Data-Stewards", "data_steward")

    # Sent under 'groups' — the configured claim is 'roles', so nothing matches.
    ignored = sso_sign_in(
        client, fake_idp, username="wrong.claim",
        groups=["Transit-Data-Stewards"], sub="idp-subject-wrong-claim",
    )
    assert ignored.status_code == 401

    # Sent under 'roles' — matched.
    matched = sso_sign_in(
        client, fake_idp, username="right.claim", groups=[],
        roles=["Transit-Data-Stewards"], sub="idp-subject-right-claim",
    )
    assert matched.status_code == 200
    assert matched.json()["role"] == "data_steward"
