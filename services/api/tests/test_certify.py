"""The certification action: happy path, blocking-DQ refusal, and the
guarantee that nothing certifies without an audit record."""

import json

import pytest

from conftest import auth_header

from headway_api.audit import AuditWriteRefused, write_event


def test_certify_happy_path_writes_cert_status_and_audit(client, fake_db):
    mv1 = fake_db.add_metric_value(metric="vrm")
    mv2 = fake_db.add_metric_value(metric="vrh", unit="hours")
    ids = [mv1["metric_value_id"], mv2["metric_value_id"]]
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": ids,
            "attestation": "I certify these June 2026 figures are accurate.",
        "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["certified_by"] == "cora"
    assert sorted(body["metric_value_ids"]) == sorted(ids)

    # cert.certifications row
    assert len(fake_db.certifications) == 1
    cert = fake_db.certifications[0]
    assert cert["certified_by"] == "cora"
    assert cert["metric_value_ids"] == ids
    # computed.metric_values status update
    assert mv1["certification_status"] == "certified"
    assert mv2["certification_status"] == "certified"
    # audit.events row with actor, action, subject, and detail
    certify_events = [e for e in fake_db.audit_events if e["action"] == "certify"]
    assert len(certify_events) == 1
    event = certify_events[0]
    assert event["actor"] == "cora"
    assert event["subject_kind"] == "cert.certifications"
    assert event["subject_id"] == cert["certification_id"]
    detail = json.loads(event["detail"])
    assert detail["metric_value_ids"] == ids
    assert detail["attestation"].startswith("I certify")
    assert body["audit_event_id"] == event["event_id"]
    # All of it committed as one transaction.
    assert fake_db.tx_log[-1] == "commit"


def test_certify_refused_409_when_open_blocking_dq_issue(client, fake_db):
    mv = fake_db.add_metric_value()
    fake_db.add_dq_issue(severity="blocking", status="open",
                         title="Vehicle 42 odometer conflict")
    r = client.post(
        "/certifications",
        json={"metric_value_ids": [mv["metric_value_id"]], "attestation": "ok", "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409
    assert "blocking" in r.json()["detail"]
    # Refusal left no trace of a certification: transaction rolled back.
    assert fake_db.certifications == []
    assert mv["certification_status"] == "uncertified"
    assert not any(e["action"] == "certify" for e in fake_db.audit_events)
    assert fake_db.tx_log[-1] == "rollback"


def test_certify_refused_when_blocking_issue_owned_but_not_resolved(client, fake_db):
    mv = fake_db.add_metric_value()
    fake_db.add_dq_issue(severity="blocking", status="owned", owner="stella")
    r = client.post(
        "/certifications",
        json={"metric_value_ids": [mv["metric_value_id"]], "attestation": "ok", "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409


def test_certify_allowed_once_blocking_issue_resolved(client, fake_db):
    mv = fake_db.add_metric_value()
    fake_db.add_dq_issue(severity="blocking", status="resolved",
                         resolution="re-ingested feed")
    fake_db.add_dq_issue(severity="warning", status="open")  # warnings don't block
    r = client.post(
        "/certifications",
        json={"metric_value_ids": [mv["metric_value_id"]], "attestation": "ok", "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201


def test_certify_unknown_metric_value_404(client, fake_db):
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": ["00000000-0000-0000-0000-000000000000"],
            "attestation": "ok",
        "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 404
    assert fake_db.certifications == []


def test_certify_already_certified_409(client, fake_db):
    mv = fake_db.add_metric_value(certification_status="certified")
    r = client.post(
        "/certifications",
        json={"metric_value_ids": [mv["metric_value_id"]], "attestation": "ok", "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409
    assert "already certified" in r.json()["detail"]


def test_certify_requires_nonempty_attestation(client, fake_db):
    mv = fake_db.add_metric_value()
    r = client.post(
        "/certifications",
        json={"metric_value_ids": [mv["metric_value_id"]], "attestation": "", "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 422


def test_audit_helper_refuses_to_be_a_noop():
    with pytest.raises(AuditWriteRefused):
        write_event(
            None,
            actor="cora",
            action="certify",
            subject_kind="cert.certifications",
            subject_id="x",
            detail={},
        )


def test_audit_helper_refuses_anonymous_events(fake_db):
    with pytest.raises(AuditWriteRefused):
        write_event(
            fake_db,
            actor="",
            action="certify",
            subject_kind=None,
            subject_id=None,
            detail={},
        )


def test_certify_refuses_ops_figures_with_plain_language_409(client, fake_db):
    """The honesty boundary (handoff 0014 / migration 0024): an OPERATIONS
    figure can never be certified — refused explicitly, before any write,
    with nothing left behind."""
    ntd = fake_db.add_metric_value(metric="vrm")
    ops = fake_db.add_metric_value(
        metric="otp", unit="percent", calc_name="otp_v0", category="ops"
    )
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": [ntd["metric_value_id"], ops["metric_value_id"]],
            "attestation": "Attempting to certify an operations metric.",
        "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "operations metrics" in detail
    assert "never be certified" in detail
    assert ops["metric_value_id"] in detail
    # Nothing changed for ANY selected figure; no cert row, no audit row.
    assert ntd["certification_status"] == "uncertified"
    assert ops["certification_status"] == "uncertified"
    assert fake_db.certifications == []
    assert [e for e in fake_db.audit_events if e["action"] == "certify"] == []


def test_open_blocking_ops_finding_never_gates_ntd_certification(client, fake_db):
    """dq.issues.category (migration 0024): an unresolved blocking
    OPERATIONS finding (e.g. an otp_v0 cadence refusal) must not freeze
    federal certification — only category='ntd' blocking issues gate."""
    mv = fake_db.add_metric_value()
    fake_db.add_dq_issue(
        severity="blocking",
        status="open",
        category="ops",
        issue_type="no_observed_passages",
        title="OTP refused for July — cadence cannot support any passage",
    )
    r = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv["metric_value_id"]],
            "attestation": "June figures verified.",
        "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 201
    assert mv["certification_status"] == "certified"

    # And an NTD blocking issue still refuses — the gate itself is intact.
    mv2 = fake_db.add_metric_value(metric="vrh", unit="hours")
    fake_db.add_dq_issue(severity="blocking", status="open", category="ntd")
    r2 = client.post(
        "/certifications",
        json={
            "metric_value_ids": [mv2["metric_value_id"]],
            "attestation": "July figures verified.",
        "signer_full_name": "Cora Certifier", "signer_title": "Chief Executive Officer"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r2.status_code == 409
