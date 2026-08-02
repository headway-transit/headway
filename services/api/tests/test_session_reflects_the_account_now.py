"""Revoking access has to actually revoke access.

A session token is a signed snapshot of an account taken at sign-in. Nothing
downstream ever looked at the account again, so for the token's whole lifetime
— thirty minutes by default — the snapshot won.

Handoff 0046 left one half of this open ("a demotion to auditor is not
immediate ... no revocation list exists"). The other half was not recorded
anywhere: ``is_active`` was read once, at login, so DEACTIVATING AN ACCOUNT DID
NOT END ITS SESSION. That is the action an administrator takes when someone
leaves or when an outside auditor's engagement ends, and it appeared to work
while doing nothing for half an hour.

What follows are the claims an administrator is entitled to make after
clicking the button.
"""

from __future__ import annotations

import pytest

from conftest import add_auditor, auth_header

PROBE = "/metrics/values"


def _token(fake_db, username: str) -> dict:
    """Headers for a session minted from the account AS IT IS NOW. Every test
    below then changes the account underneath this token, exactly as an
    administrator would while the person is still working."""
    return auth_header(fake_db, username)


# ---------------------------------------------------------------------------
# Deactivation
# ---------------------------------------------------------------------------


def test_deactivating_an_account_ends_its_session_immediately(client, fake_db):
    """THE ONE THAT MATTERS. Before this, a deactivated account kept working
    until its token expired — so 'revoke this person's access' was a promise
    the product did not keep."""
    headers = _token(fake_db, "vera")
    assert client.get(PROBE, headers=headers).status_code == 200

    fake_db.users["vera"]["is_active"] = False

    refused = client.get(PROBE, headers=headers)
    assert refused.status_code == 401
    assert "deactivated" in refused.json()["detail"]


def test_a_deactivated_auditors_evidence_bundle_stops_too(
    client, fake_db, fake_store
):
    """The role deliberately handed to someone OUTSIDE the agency, on the
    endpoint that hands them the filing. Ending that engagement has to end it
    on the surface built for them, not thirty minutes later."""
    from test_evidence_bundle import _certify, _seed

    add_auditor(fake_db)
    mv = _seed(fake_db, fake_store)
    certification_id = _certify(client, fake_db, mv)
    headers = _token(fake_db, "audra")
    url = f"/certifications/{certification_id}/evidence"
    assert client.get(url, headers=headers).status_code == 200

    fake_db.users["audra"]["is_active"] = False

    assert client.get(url, headers=headers).status_code == 401


def test_a_deleted_account_ends_its_session_too(client, fake_db):
    """No row is not 'no opinion'. A token signed for an account that is gone
    is not a session."""
    headers = _token(fake_db, "vera")
    assert client.get(PROBE, headers=headers).status_code == 200

    del fake_db.users["vera"]

    refused = client.get(PROBE, headers=headers)
    assert refused.status_code == 401
    assert "no longer exists" in refused.json()["detail"]


# ---------------------------------------------------------------------------
# Role changes
# ---------------------------------------------------------------------------


def _resolve(client, headers, issue_id, note):
    return client.post(
        f"/dq/issues/{issue_id}/resolve",
        json={"resolution": note},
        headers=headers,
    )


def test_a_demotion_narrows_what_the_existing_token_can_do(client, fake_db):
    """Handoff 0046's open item. The token still says data_steward; the
    account says auditor; the account wins, and the write is refused by the
    read-only guard — on the SAME token that could write a moment ago."""
    first = fake_db.add_dq_issue()
    second = fake_db.add_dq_issue()
    headers = _token(fake_db, "stella")
    assert _resolve(
        client, headers, first["issue_id"], "fixed before the demotion"
    ).status_code == 200

    fake_db.users["stella"]["role"] = "auditor"

    refused = _resolve(
        client, headers, second["issue_id"], "must not be recorded"
    )
    assert refused.status_code == 403
    assert "signed in as an auditor" in refused.json()["detail"]
    assert fake_db.dq_issues[second["issue_id"]]["status"] == "open"
    # Reading still works: a demotion narrows, it does not evict.
    assert client.get(PROBE, headers=headers).status_code == 200


def test_a_promotion_takes_effect_without_signing_in_again(client, fake_db):
    """Same mechanism, the harmless direction. Worth pinning: if only the
    restricting direction were live, the check would be doing half its job and
    the half it skipped would be the one users notice."""
    issue = fake_db.add_dq_issue()
    headers = _token(fake_db, "vera")
    assert _resolve(
        client, headers, issue["issue_id"], "too junior to say this"
    ).status_code == 403

    fake_db.users["vera"]["role"] = "data_steward"

    assert _resolve(
        client, headers, issue["issue_id"], "fixed after the promotion"
    ).status_code == 200


def test_a_role_this_build_does_not_know_is_refused_not_guessed_at(
    client, fake_db
):
    """A role written by a newer version, or by hand in psql. Refusing is the
    only safe reading: mapping an unknown role onto a known one is how an
    account quietly gains permissions nobody granted."""
    headers = _token(fake_db, "vera")
    fake_db.users["vera"]["role"] = "superuser"

    refused = client.get(PROBE, headers=headers)
    assert refused.status_code == 401
    assert "not one this version of Headway recognizes" in refused.json()["detail"]


# ---------------------------------------------------------------------------
# The check is at the choke point, so it cannot be routed around
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", [PROBE, "/dq/issues", "/sources/status", "/certifications"]
)
def test_every_authenticated_surface_sees_the_deactivation(client, fake_db, path):
    """It sits in ``get_current_identity``, which every authenticated endpoint
    resolves through — coverage by construction, not by remembering."""
    headers = _token(fake_db, "cora")
    assert client.get(path, headers=headers).status_code == 200

    fake_db.users["cora"]["is_active"] = False

    assert client.get(path, headers=headers).status_code == 401


def test_the_dual_credential_path_checks_the_account_too(client, fake_db):
    """``/metrics/values/{id}/lineage`` accepts a human session OR a machine
    key, and resolves the human half by calling get_current_identity directly
    rather than through FastAPI. A direct call is exactly where a new
    dependency gets missed."""
    mv = fake_db.add_metric_value()
    fake_db.add_edge(
        "computed.metric_values", mv["metric_value_id"], "vrm_v0", "0.1.0",
        "raw.records", "a" * 64,
    )
    headers = _token(fake_db, "vera")
    url = f"/metrics/values/{mv['metric_value_id']}/lineage"
    assert client.get(url, headers=headers).status_code == 200

    fake_db.users["vera"]["is_active"] = False

    # The dual-credential surface answers ONE generic 401 on purpose, so a
    # prober cannot tell which credential kind failed or why.
    assert client.get(url, headers=headers).status_code == 401
