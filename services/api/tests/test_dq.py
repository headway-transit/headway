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


def test_get_one_issue_by_id_any_signed_in_role(client, fake_db):
    """GET /dq/issues/{id} (handoff 0026): the deep-link target a calc-run
    refusal points at — served directly, never via the whole-queue list."""
    issue = fake_db.add_dq_issue(severity="blocking", title="coverage gap")
    r = client.get(
        f"/dq/issues/{issue['issue_id']}", headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 200
    body = r.json()
    assert body["issue_id"] == issue["issue_id"]
    assert body["severity"] == "blocking"
    assert body["title"] == "coverage gap"


def test_get_one_issue_unknown_and_malformed_ids_are_404(client, fake_db):
    r = client.get(
        "/dq/issues/00000000-0000-0000-0000-000000000000",
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 404
    r = client.get(
        "/dq/issues/not-a-uuid", headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 404
    assert "No data-quality issue with that id" in r.json()["detail"]


def test_get_one_issue_requires_authentication(client, fake_db):
    issue = fake_db.add_dq_issue()
    assert client.get(f"/dq/issues/{issue['issue_id']}").status_code == 401


def test_counts_path_still_wins_over_the_id_route(client, fake_db):
    """Route-order pin: /dq/issues/counts must resolve to the counts
    endpoint, never capture 'counts' as an issue id."""
    fake_db.add_dq_issue()
    r = client.get("/dq/issues/counts", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    assert r.json()["total"] == 1


# --- the finding's subject, in the agency's vocabulary (handoff 0029) -------

#: One resolved, frozen context exactly as headway_calc.subjects writes it.
SUBJECT_CONTEXT = {
    "version": 1,
    "kind": "canonical.trips",
    "total": 3,
    "grouped_by": "block",
    "group_count": 2,
    "group_cap": 25,
    "trip_id_cap": 20,
    "groups": [
        {
            "block_id": "225-4",
            "trip_count": 2,
            "routes": [
                {"route_id": "42", "short_name": "42", "long_name": "Dayton"}
            ],
            "route_count": 1,
            "first_departure": "06:14",
            "last_departure": "14:22",
            "trip_ids": ["t1", "t2"],
        },
        {
            "block_id": None,
            "trip_count": 1,
            "routes": [],
            "route_count": 0,
            "first_departure": None,
            "last_departure": None,
            "trip_ids": ["t3"],
        },
    ],
}


def test_list_serves_the_frozen_subject_context_verbatim(client, fake_db):
    """The API neither re-resolves a label nor fills one in: what the calc
    runner froze at write time is what a reader sees, years later."""
    fake_db.add_dq_issue(subject_context=SUBJECT_CONTEXT)
    (row,) = client.get(
        "/dq/issues", headers=auth_header(fake_db, "vera")
    ).json()
    assert row["subject_context"] == SUBJECT_CONTEXT
    # Absence stays absence — no invented block, no invented route.
    assert row["subject_context"]["groups"][1]["block_id"] is None
    assert row["subject_context"]["groups"][1]["routes"] == []


def test_one_issue_by_id_serves_the_subject_context(client, fake_db):
    issue = fake_db.add_dq_issue(subject_context=SUBJECT_CONTEXT)
    r = client.get(
        f"/dq/issues/{issue['issue_id']}", headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 200
    assert r.json()["subject_context"]["groups"][0]["block_id"] == "225-4"


def test_pre_migration_rows_serve_subject_context_as_null(client, fake_db):
    """97,067 rows in the live queue predate migration 0035. Every one of
    them must keep serving exactly as it did — null, not an empty object,
    and certainly not a placeholder label."""
    fake_db.add_dq_issue()
    (row,) = client.get(
        "/dq/issues", headers=auth_header(fake_db, "vera")
    ).json()
    assert "subject_context" in row and row["subject_context"] is None


def test_subject_context_needs_authentication_like_every_other_field(
    client, fake_db
):
    fake_db.add_dq_issue(subject_context=SUBJECT_CONTEXT)
    assert client.get("/dq/issues").status_code == 401
