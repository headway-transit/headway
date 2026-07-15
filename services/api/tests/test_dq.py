"""DQ issue list + audited resolution workflow."""

import json

from conftest import auth_header


def test_list_issues_and_filter_by_status(client, fake_db):
    fake_db.add_dq_issue(status="open", title="gap A")
    fake_db.add_dq_issue(status="resolved", title="gap B",
                         resolution="re-ingested")
    r = client.get("/dq/issues", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    assert len(r.json()) == 2

    r = client.get("/dq/issues", params={"status": "open"},
                   headers=auth_header(fake_db, "vera"))
    (row,) = r.json()
    assert row["title"] == "gap A"
    assert row["severity"] == "warning"  # severity is text, never a color code


def test_list_issues_invalid_status_is_explained(client, fake_db):
    r = client.get("/dq/issues", params={"status": "closed"},
                   headers=auth_header(fake_db, "vera"))
    assert r.status_code == 422
    assert "Valid statuses are" in r.json()["detail"]


def test_resolve_updates_issue_and_writes_audit_event(client, fake_db):
    issue = fake_db.add_dq_issue()
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/resolve",
        json={"resolution": "Feed outage confirmed with vendor; data replayed."},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "resolved"
    assert issue["status"] == "resolved"
    assert issue["resolution"].startswith("Feed outage")
    events = [e for e in fake_db.audit_events if e["action"] == "dq_resolve"]
    assert len(events) == 1
    assert events[0]["actor"] == "stella"
    assert events[0]["subject_kind"] == "dq.issues"
    assert events[0]["subject_id"] == issue["issue_id"]
    assert json.loads(events[0]["detail"])["resolution"].startswith("Feed outage")
    assert body["audit_event_id"] == events[0]["event_id"]
    assert fake_db.tx_log[-1] == "commit"


def test_resolve_unknown_issue_404(client, fake_db):
    r = client.post(
        "/dq/issues/00000000-0000-0000-0000-000000000000/resolve",
        json={"resolution": "x"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 404


def test_resolve_with_minutes_persists_and_audits_old_to_new(client, fake_db):
    issue = fake_db.add_dq_issue()
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/resolve",
        json={"resolution": "Replayed the feed.", "resolution_minutes": 45},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200
    assert r.json()["resolution_minutes"] == 45
    # Persisted on the issue row...
    assert issue["resolution_minutes"] == 45
    # ...and audited with the old and new value (settings-router precedent).
    (event,) = [e for e in fake_db.audit_events if e["action"] == "dq_resolve"]
    detail = json.loads(event["detail"])
    assert detail["resolution_minutes_old"] is None
    assert detail["resolution_minutes_new"] == 45
    assert fake_db.tx_log[-1] == "commit"
    # And the list endpoint serves it back.
    rows = client.get(
        "/dq/issues", headers=auth_header(fake_db, "vera")
    ).json()
    assert rows[0]["resolution_minutes"] == 45


def test_resolve_without_minutes_backward_compatible(client, fake_db):
    issue = fake_db.add_dq_issue()
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/resolve",
        json={"resolution": "Fixed."},  # the pre-0016 body, unchanged
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200
    assert r.json()["resolution_minutes"] is None
    assert issue["resolution_minutes"] is None  # NULL, never coalesced to 0
    (event,) = [e for e in fake_db.audit_events if e["action"] == "dq_resolve"]
    detail = json.loads(event["detail"])
    assert detail["resolution_minutes_new"] is None


def test_resolve_negative_minutes_422_plain_language_changes_nothing(
    client, fake_db
):
    issue = fake_db.add_dq_issue()
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/resolve",
        json={"resolution": "x", "resolution_minutes": -5},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 422
    assert "zero or more" in r.text  # the plain-language explanation
    assert issue["status"] == "open"
    assert issue["resolution_minutes"] is None
    assert not any(e["action"] == "dq_resolve" for e in fake_db.audit_events)


def test_list_issues_rows_include_resolution_minutes_null_by_default(
    client, fake_db
):
    fake_db.add_dq_issue()
    (row,) = client.get(
        "/dq/issues", headers=auth_header(fake_db, "vera")
    ).json()
    assert "resolution_minutes" in row and row["resolution_minutes"] is None


def test_resolve_already_resolved_409_no_second_audit_event(client, fake_db):
    issue = fake_db.add_dq_issue(status="resolved", resolution="done")
    r = client.post(
        f"/dq/issues/{issue['issue_id']}/resolve",
        json={"resolution": "again"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 409
    assert "already closed" in r.json()["detail"]
    assert not any(e["action"] == "dq_resolve" for e in fake_db.audit_events)
