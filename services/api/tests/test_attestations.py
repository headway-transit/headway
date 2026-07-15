"""Statistician attestations (handoff 0019, design point A): entry,
revocation-never-deletion, the 'attested' DQ closure, and the hard limits at
the API surface.
"""

from __future__ import annotations

import datetime as dt

from conftest import UTC, auth_header


def _attestation_payload(**overrides):
    payload = {
        "statistician_name": "Dr. R. Fisher",
        "statistician_credentials": "PhD statistics; 12 years transit sampling",
        "method_description": "Route-stratified expansion factoring",
        "document_reference": "dms://approvals/2026/upt-factoring.pdf",
        "metric": "upt",
        "scope_pattern": "agency",
        "period_start": "2026-07-01",
        "period_end": "2026-08-01",
    }
    payload.update(overrides)
    return payload


# --- entry ---------------------------------------------------------------------


def test_create_attestation_certifying_official_only(client, fake_db):
    for username in ("vera", "stella", "petra"):
        r = client.post(
            "/attestations",
            json=_attestation_payload(),
            headers=auth_header(fake_db, username),
        )
        assert r.status_code == 403, username
    assert fake_db.attestations == {}

    r = client.post(
        "/attestations",
        json=_attestation_payload(),
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["statistician_name"] == "Dr. R. Fisher"
    assert body["metric"] == "upt"
    assert body["entered_by"] == "cora"
    assert body["revoked_at"] is None
    # Audited in the same transaction.
    events = [
        e for e in fake_db.audit_events if e["action"] == "attestation_create"
    ]
    assert len(events) == 1
    assert events[0]["subject_id"] == body["attestation_id"]


def test_create_attestation_refuses_unknown_metric_and_bad_period(
    client, fake_db
):
    r = client.post(
        "/attestations",
        json=_attestation_payload(metric="vrm"),
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422  # only upt/pmt have a p. 146 factoring rule

    r = client.post(
        "/attestations",
        json=_attestation_payload(
            period_start="2026-08-01", period_end="2026-08-01"
        ),
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422
    assert fake_db.attestations == {}


def test_list_and_get_attestations_any_role(client, fake_db):
    att = fake_db.add_attestation()
    revoked = fake_db.add_attestation(
        metric="pmt",
        revoked_at=dt.datetime(2026, 7, 3, tzinfo=UTC),
        revoked_by="cora",
        revocation_reason="method superseded",
    )
    r = client.get("/attestations", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    assert {a["attestation_id"] for a in r.json()} == {
        att["attestation_id"],
        revoked["attestation_id"],
    }
    # include_revoked=false filters to the live set.
    r = client.get(
        "/attestations?include_revoked=false",
        headers=auth_header(fake_db, "vera"),
    )
    assert [a["attestation_id"] for a in r.json()] == [att["attestation_id"]]
    # metric filter.
    r = client.get(
        "/attestations?metric=pmt", headers=auth_header(fake_db, "vera")
    )
    assert [a["attestation_id"] for a in r.json()] == [
        revoked["attestation_id"]
    ]
    r = client.get(
        f"/attestations/{att['attestation_id']}",
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 200
    assert r.json()["attestation_id"] == att["attestation_id"]


# --- revocation (never deletion) -------------------------------------------------


def test_revoke_sets_trio_and_audits_never_deletes(client, fake_db):
    att = fake_db.add_attestation()
    r = client.post(
        f"/attestations/{att['attestation_id']}/revoke",
        json={"reason": "Statistician withdrew the approval."},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["revoked_at"] is not None
    assert body["revoked_by"] == "cora"
    assert body["revocation_reason"] == "Statistician withdrew the approval."
    # The row still exists — revocation is never deletion.
    assert att["attestation_id"] in fake_db.attestations
    events = [
        e for e in fake_db.audit_events if e["action"] == "attestation_revoke"
    ]
    assert len(events) == 1

    # Second revocation refuses: append-only, one-way.
    r = client.post(
        f"/attestations/{att['attestation_id']}/revoke",
        json={"reason": "again"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409


def test_revoke_requires_certifying_official(client, fake_db):
    att = fake_db.add_attestation()
    r = client.post(
        f"/attestations/{att['attestation_id']}/revoke",
        json={"reason": "nope"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 403
    assert fake_db.attestations[att["attestation_id"]]["revoked_at"] is None


# --- the 'attested' DQ closure ---------------------------------------------------


def _refusal_issue(fake_db, **overrides):
    return fake_db.add_dq_issue(
        issue_type="apc_missing_trips_above_fta_threshold",
        severity="blocking",
        title="Missing-trip share 0.9000 exceeds the FTA 2% threshold",
        **overrides,
    )


def test_attest_closes_p146_refusal_with_explicit_state(client, fake_db):
    att = fake_db.add_attestation()
    issue = _refusal_issue(fake_db)
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/attest",
        json={"attestation_id": att["attestation_id"]},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "attested"
    assert body["attestation_id"] == att["attestation_id"]
    assert "Dr. R. Fisher" in body["resolution"]
    assert "p. 146" in body["resolution"]
    assert fake_db.dq_issues[issue["issue_id"]]["status"] == "attested"
    events = [e for e in fake_db.audit_events if e["action"] == "dq_attest"]
    assert len(events) == 1


def test_attest_refuses_non_p146_issue_citing_the_sampling_hard_limit(
    client, fake_db
):
    att = fake_db.add_attestation()
    issue = fake_db.add_dq_issue(severity="blocking", issue_type="gap")
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/attest",
        json={"attestation_id": att["attestation_id"]},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 409
    # The p. 149 hard-limit quote, verbatim, in the refusal.
    assert (
        "must not collect a smaller sample than the chosen sampling plan "
        "prescribes" in r.json()["detail"]
    )
    assert fake_db.dq_issues[issue["issue_id"]]["status"] == "open"


def test_attest_refuses_revoked_or_unknown_attestation_and_closed_issue(
    client, fake_db
):
    issue = _refusal_issue(fake_db)
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/attest",
        json={"attestation_id": "00000000-0000-0000-0000-000000000000"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 404

    revoked = fake_db.add_attestation(
        revoked_at=dt.datetime(2026, 7, 3, tzinfo=UTC),
        revoked_by="cora",
        revocation_reason="withdrawn",
    )
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/attest",
        json={"attestation_id": revoked["attestation_id"]},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 409

    att = fake_db.add_attestation()
    resolved = _refusal_issue(
        fake_db, status="resolved", resolution="fixed upstream"
    )
    r = client.post(
        f"/dq/issues/{resolved['issue_id']}/attest",
        json={"attestation_id": att["attestation_id"]},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 409


def test_attest_requires_data_steward(client, fake_db):
    att = fake_db.add_attestation()
    issue = _refusal_issue(fake_db)
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/attest",
        json={"attestation_id": att["attestation_id"]},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 403


def test_attested_state_unblocks_certification_gate(client, fake_db):
    """The certify gate counts open/owned blocking issues; 'attested' is a
    closed state — the p. 146 refusal stops gating once attested."""
    att = fake_db.add_attestation()
    issue = _refusal_issue(fake_db)
    mv = fake_db.add_metric_value()
    refused = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv["metric_value_id"]],
            "attestation": "ok",
            "signer_full_name": "Cora Certifier",
            "signer_title": "CEO",
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert refused.status_code == 409  # blocked while the refusal is open
    client.post(
        f"/dq/issues/{issue['issue_id']}/attest",
        json={"attestation_id": att["attestation_id"]},
        headers=auth_header(fake_db, "stella"),
    )
    allowed = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv["metric_value_id"]],
            "attestation": "ok",
            "signer_full_name": "Cora Certifier",
            "signer_title": "CEO",
        },
        headers=auth_header(fake_db, "cora"),
    )
    assert allowed.status_code == 201


def test_attested_is_a_listable_status_filter(client, fake_db):
    att = fake_db.add_attestation()
    issue = _refusal_issue(fake_db)
    client.post(
        f"/dq/issues/{issue['issue_id']}/attest",
        json={"attestation_id": att["attestation_id"]},
        headers=auth_header(fake_db, "stella"),
    )
    r = client.get(
        "/dq/issues?status=attested", headers=auth_header(fake_db, "vera")
    )
    assert [i["issue_id"] for i in r.json()] == [issue["issue_id"]]


# --- HARD LIMIT 1 at the API surface ---------------------------------------------


def test_hard_limit_attestations_never_unblock_sampling_undersampling(
    client, fake_db
):
    """p. 149: 'agencies must not collect a smaller sample than the chosen
    sampling plan prescribes.' — with attestations ON RECORD, an
    undersampled plan's estimate still refuses, and the estimate endpoint
    has no attestation input at all."""
    fake_db.add_attestation()  # upt, agency-wide
    fake_db.add_attestation(metric="pmt", scope_pattern="*")
    plan = fake_db.add_sampling_plan(status="active")
    fake_db.add_sampling_draw(
        plan["plan_id"], selected_units=[f"u{i}" for i in range(12)]
    )
    for i in range(12):  # 12 of the 48 required — undersampled
        fake_db.add_sampling_measurement(plan["plan_id"], f"u{i}")
    r = client.post(
        f"/sampling/plans/{plan['plan_id']}/estimate",
        json={"annual_upt_100pct": "250000"},
        headers=auth_header(fake_db, "petra"),
    )
    assert r.status_code == 422
    assert "follow the sampling technique exactly" in r.json()["detail"]
    # And structurally: no attestation parameter exists on the endpoint.
    from headway_api.routers import sampling as sampling_router

    import inspect

    params = inspect.signature(sampling_router.generate_estimate).parameters
    assert not any("attest" in p.lower() for p in params)
