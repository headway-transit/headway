"""Role gates: viewer can read, only certifying_official certifies,
data_steward+ resolves DQ issues. Denials are 403 in plain language."""

from conftest import auth_header


def test_viewer_can_read_metric_values(client, fake_db):
    fake_db.add_metric_value()
    r = client.get("/metrics/values", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_viewer_cannot_certify(client, fake_db):
    mv = fake_db.add_metric_value()
    r = client.post(
        "/certifications",
        json={"metric_value_ids": [mv["metric_value_id"]], "attestation": "ok"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 403
    detail = r.json()["detail"]
    assert "viewer" in detail and "certifying official" in detail
    # Nothing was certified and nothing was audit-logged as certified.
    assert fake_db.certifications == []
    assert mv["certification_status"] == "uncertified"
    assert not any(e["action"] == "certify" for e in fake_db.audit_events)


def test_report_preparer_cannot_certify_separation_of_duties(client, fake_db):
    mv = fake_db.add_metric_value()
    r = client.post(
        "/certifications",
        json={"metric_value_ids": [mv["metric_value_id"]], "attestation": "ok"},
        headers=auth_header(fake_db, "petra"),
    )
    assert r.status_code == 403
    assert fake_db.certifications == []


def test_viewer_cannot_resolve_dq_issue(client, fake_db):
    issue = fake_db.add_dq_issue()
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/resolve",
        json={"resolution": "checked"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 403
    assert "data steward" in r.json()["detail"]
    assert issue["status"] == "open"


def test_certifying_official_can_resolve_dq_issue_role_hierarchy(client, fake_db):
    issue = fake_db.add_dq_issue()
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/resolve",
        json={"resolution": "verified against odometer records"},
        headers=auth_header(fake_db, "cora"),
    )
    assert r.status_code == 200
