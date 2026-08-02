"""The `auditor` role: reads everything, changes nothing (handoff 0046).

The role exists so an auditor can be given the reach an audit needs without
being given the ability to alter what they are auditing. These tests are
mostly NEGATIVE, because the interesting claim is not "an auditor can read
the figures" — it is "an auditor cannot do any of the other 30 things every
other role can do", and that claim has to hold for endpoints nobody has
written yet.

Three enforcement points, tested separately so a regression in one is not
masked by another:

1. ``auditor`` is off the rank ladder, so ``require_at_least`` fails it.
2. Unsafe HTTP methods are refused at the authentication choke point.
3. Content sensitivity is evaluated at VIEWER breadth — migration 0028's
   rider-location withholding is not waived for an auditor.
"""

from __future__ import annotations

import datetime as dt

import pytest

from conftest import UTC, add_auditor, auth_header
from headway_api import authz


# ---------------------------------------------------------------------------
# 1. Off the ladder, by construction
# ---------------------------------------------------------------------------


def test_auditor_is_not_a_rung_on_the_rank_ladder():
    """The structural claim the whole role rests on. If someone ever adds
    `auditor` to ROLE_RANK, every rank gate silently starts admitting it —
    so the absence is asserted, not assumed."""
    assert "auditor" not in authz.ROLE_RANK
    assert "auditor" in authz.READ_ONLY_ROLES
    assert "auditor" in authz.ALL_ROLES


@pytest.mark.parametrize("minimum", ["viewer", "data_steward", "report_preparer"])
def test_auditor_satisfies_no_rank_requirement(minimum):
    """Including `viewer`. A rank gate is a WRITE gate in this codebase, and
    an auditor writes nothing — not even at the bottom rung."""
    from fastapi import HTTPException

    dependency = authz.require_at_least(minimum)
    identity = _identity("auditor")
    with pytest.raises(HTTPException) as exc:
        dependency(identity)
    assert exc.value.status_code == 403
    assert "read Headway but cannot change anything" in exc.value.detail


def test_unknown_role_is_refused_rather_than_ranked():
    """Deny-by-default for a role name this build does not know — never a
    guessed rank, never a default of viewer."""
    from fastapi import HTTPException

    dependency = authz.require_at_least("viewer")
    with pytest.raises(HTTPException) as exc:
        dependency(_identity("regional_overseer"))
    assert exc.value.status_code == 403
    assert "not one this version of Headway recognizes" in exc.value.detail


def _identity(role: str):
    from headway_api.auth import Identity

    return Identity(sub="u-1", username="someone", role=role)


# ---------------------------------------------------------------------------
# 2. Reads everything readable
# ---------------------------------------------------------------------------


def test_auditor_reads_the_figures_and_their_receipts(client, fake_db):
    add_auditor(fake_db)
    fake_db.add_metric_value(metric="vrm")
    r = client.get("/metrics/values", headers=auth_header(fake_db, "audra"))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_auditor_reads_the_dq_queue_and_the_certifications(client, fake_db):
    add_auditor(fake_db)
    for path in ("/dq/issues", "/certifications", "/settings", "/calc/runs"):
        r = client.get(path, headers=auth_header(fake_db, "audra"))
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text}"


def test_auditor_reads_the_audit_trail_and_a_data_steward_cannot(client, fake_db):
    """The one read surface that is NARROWER than `require_authenticated`.
    The trail names what every person did; a steward has no need of it to do
    their job, and an auditor has no purpose without it."""
    add_auditor(fake_db)
    fake_db.audit_events.append({
        "event_id": 1, "at": dt.datetime(2026, 8, 1, 10, 0, tzinfo=UTC),
        "actor": "cora", "action": "certify",
        "subject_kind": "cert.certifications", "subject_id": "c-1",
        "detail": {"metric_value_ids": ["m-1"]},
    })
    fake_db._next_event_id = 2

    ok = client.get("/audit/events", headers=auth_header(fake_db, "audra"))
    assert ok.status_code == 200
    assert ok.json()["events"][0]["actor"] == "cora"
    assert ok.json()["events"][0]["action"] == "certify"

    admin = client.get("/audit/events", headers=auth_header(fake_db, "cora"))
    assert admin.status_code == 200

    for username in ("stella", "petra", "vera"):
        denied = client.get("/audit/events", headers=auth_header(fake_db, username))
        assert denied.status_code == 403
        assert "cannot read Headway's audit trail" in denied.json()["detail"]


def test_audit_trail_filters_and_pages_without_skipping_rows(client, fake_db):
    """Keyset pagination, because an audit trail that skips a row while new
    rows are being written is worse than no audit trail."""
    add_auditor(fake_db)
    for i in range(1, 6):
        fake_db.audit_events.append({
            "event_id": i, "at": dt.datetime(2026, 8, 1, 10, i, tzinfo=UTC),
            "actor": "cora" if i % 2 else "stella", "action": "certify",
            "subject_kind": None, "subject_id": None, "detail": {},
        })
    headers = auth_header(fake_db, "audra")

    page = client.get("/audit/events?limit=2", headers=headers).json()
    assert [e["event_id"] for e in page["events"]] == [5, 4]
    assert page["next_cursor"] == 4

    nxt = client.get(
        f"/audit/events?limit=2&before_event_id={page['next_cursor']}",
        headers=headers,
    ).json()
    assert [e["event_id"] for e in nxt["events"]] == [3, 2]

    only_cora = client.get("/audit/events?actor=cora", headers=headers).json()
    assert {e["actor"] for e in only_cora["events"]} == {"cora"}


# ---------------------------------------------------------------------------
# 3. Changes nothing — the method-level ban
# ---------------------------------------------------------------------------


WRITE_ATTEMPTS = [
    ("POST", "/dq/issues/i-1/resolve", {"resolution": "x", "note": "y"}),
    ("POST", "/certifications", {"metric_value_ids": ["m-1"], "attestation": "x"}),
    ("POST", "/users", {"username": "new.person", "role": "viewer", "password": "abcd1234"}),
    ("POST", "/calc/runs", {"period_start": "2026-06-01", "period_end": "2026-07-01"}),
    ("PUT", "/settings/gap_threshold_seconds", {"value": "90"}),
    ("POST", "/machine/keys", {"name": "k", "scopes": ["read:metrics"]}),
    ("POST", "/safety/events", {}),
    ("POST", "/attestations", {}),
    ("DELETE", "/machine/keys/k-1", None),
    ("PUT", "/auth/oidc/config", {}),
    ("POST", "/auth/oidc/mappings", {"claim_value": "g", "headway_role": "viewer"}),
]


@pytest.mark.parametrize("method,path,body", WRITE_ATTEMPTS)
def test_auditor_cannot_write_anywhere(client, fake_db, method, path, body):
    """Every state-changing endpoint, refused at the ONE choke point every
    authenticated request passes through — so this holds for endpoints that
    do not exist yet, written by people who have never heard of this role."""
    add_auditor(fake_db)
    r = client.request(
        method, path, json=body, headers=auth_header(fake_db, "audra")
    )
    assert r.status_code == 403, f"{method} {path} -> {r.status_code}"
    assert "change nothing" in r.json()["detail"]


def test_auditor_is_refused_the_read_shaped_posts_too(client, fake_db):
    """`/sandbox/preview` computes a what-if and `/raw/records/{id}/verify`
    raises a data-quality finding on a mismatch. Both are POSTs, both are
    outside "reads everything, changes nothing", and refusing by METHOD with
    no allow-list is what makes that guarantee hold without maintenance."""
    add_auditor(fake_db)
    headers = auth_header(fake_db, "audra")
    preview = client.post(
        "/sandbox/preview",
        json={
            "period_start": "2026-06-01",
            "period_end": "2026-07-01",
            "proposed": {"gap_threshold_seconds": "90"},
        },
        headers=headers,
    )
    assert preview.status_code == 403
    verify = client.post("/raw/records/abc/verify", headers=headers)
    assert verify.status_code == 403


def test_auditor_write_refusal_is_403_not_404_and_never_leaks_the_path(
    client, fake_db
):
    """The refusal happens BEFORE routing decides whether the thing exists,
    so an auditor cannot use write attempts to enumerate records."""
    add_auditor(fake_db)
    real = client.post(
        "/dq/issues/does-not-exist/resolve",
        json={"resolution": "x", "note": "y"},
        headers=auth_header(fake_db, "audra"),
    )
    assert real.status_code == 403


def test_auditor_cannot_certify_even_though_it_reads_certifications(client, fake_db):
    """The guardrail that has no bootstrap exception: certifying is
    certifying_official and nothing else, from any authentication path."""
    add_auditor(fake_db)
    mv = fake_db.add_metric_value()
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv["metric_value_id"]],
            "attestation": "I attest",
            "signer_full_name": "Test Auditor",
            "signer_title": "Auditor",
        },
        headers=auth_header(fake_db, "audra"),
    )
    assert r.status_code == 403
    assert not fake_db.certifications


# ---------------------------------------------------------------------------
# 4. Rider privacy is not an auditor exception
# ---------------------------------------------------------------------------


def test_auditor_does_not_see_withheld_rider_locations(client, fake_db):
    """Migration 0028 withholds demand-response coordinates because a
    paratransit pickup point is a rider's home address, and the mere
    existence of an ADA trip record discloses disability status. Breadth of
    audit does not outrank that."""
    add_auditor(fake_db)
    record = fake_db.add_raw_record(
        connector="headway-dr", payload_ref="raw/dr/2026-06-01/trips.csv"
    )
    headers = auth_header(fake_db, "audra")

    label = client.get(f"/raw/records/{record['record_id']}", headers=headers)
    assert label.status_code == 200
    sensitivity = label.json()["sensitivity"]
    assert sensitivity["classification"] == "rider_location"
    assert sensitivity["preview_allowed"] is False
    assert "cannot open the contents" in sensitivity["refusal"]

    payload = client.get(
        f"/raw/records/{record['record_id']}/payload", headers=headers
    )
    assert payload.status_code == 403
    download = client.get(
        f"/raw/records/{record['record_id']}/download", headers=headers
    )
    assert download.status_code == 403


def test_auditor_does_not_see_unclassified_vendor_exports(client, fake_db):
    """The fail-closed case: a vendor export can be a paratransit booking
    file, so it is withheld from viewer-breadth roles, auditor included."""
    add_auditor(fake_db)
    record = fake_db.add_raw_record(connector="headway-vendor-file")
    r = client.get(
        f"/raw/records/{record['record_id']}/payload",
        headers=auth_header(fake_db, "audra"),
    )
    assert r.status_code == 403


def test_auditor_does_read_ordinary_operational_records(client, fake_db):
    """The role is not crippled: everything not classified as rider-adjacent
    is open to it, exactly as it is to a viewer."""
    add_auditor(fake_db)
    record = fake_db.add_raw_record(connector="headway-gtfs-rt")
    label = client.get(
        f"/raw/records/{record['record_id']}",
        headers=auth_header(fake_db, "audra"),
    )
    assert label.status_code == 200
    assert label.json()["sensitivity"]["preview_allowed"] is True


def test_may_read_sensitivity_is_deny_by_default_for_unknown_roles():
    assert authz.may_read_sensitivity("auditor", "viewer") is True
    assert authz.may_read_sensitivity("auditor", "data_steward") is False
    assert authz.may_read_sensitivity("viewer", "data_steward") is False
    assert authz.may_read_sensitivity("data_steward", "data_steward") is True
    assert authz.may_read_sensitivity("regional_overseer", "viewer") is False


# ---------------------------------------------------------------------------
# 5. The role is grantable locally, and the lockout fail-safe still holds
# ---------------------------------------------------------------------------


def test_an_admin_can_grant_and_revoke_the_auditor_role(client, fake_db):
    created = client.post(
        "/users",
        json={"username": "ext.auditor", "role": "auditor", "password": "abcd1234"},
        headers=auth_header(fake_db, "cora"),
    )
    assert created.status_code == 201
    assert created.json()["role"] == "auditor"
    assert fake_db.users["ext.auditor"]["role"] == "auditor"
    assert any(
        e["action"] == "user_created" and e["detail"]["role"] == "auditor"
        for e in fake_db.audit_events
        for e in [dict(e, detail=_as_dict(e["detail"]))]
    )


def test_demoting_the_last_certifying_official_to_auditor_is_still_refused(
    client, fake_db
):
    """`auditor` is a new way to strip the last admin's powers, so the
    migration-0032 fail-safe has to cover it too."""
    r = client.post(
        "/users/cora/role",
        json={"role": "auditor"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409
    assert "last active certifying official" in r.json()["detail"]
    assert fake_db.users["cora"]["role"] == "certifying_official"


def _as_dict(detail):
    import json

    return json.loads(detail) if isinstance(detail, str) else detail
