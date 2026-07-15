"""Summary-card counts (handoff 0017, design point 2): GET /dq/issues/counts
and GET /safety/events/counts compose EXACTLY the queries their list
endpoints use (same filters), so a card total can never disagree with the
table it sits above. Missing vocabulary buckets are explicit zeros."""

import datetime as dt

from conftest import auth_header

UTC = dt.timezone.utc


# ---------------------------------------------------------------------------
# /dq/issues/counts
# ---------------------------------------------------------------------------


def _seed_dq(fake_db):
    fake_db.add_dq_issue(severity="blocking", status="open")
    fake_db.add_dq_issue(severity="warning", status="open")
    fake_db.add_dq_issue(severity="warning", status="resolved",
                         resolved_at=dt.datetime.now(UTC), resolution="fixed")
    fake_db.add_dq_issue(severity="info", status="owned", owner="stella")


def test_dq_counts_match_the_list(client, fake_db):
    _seed_dq(fake_db)
    r = client.get("/dq/issues/counts", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 4
    assert body["by_severity"] == {"blocking": 1, "warning": 2, "info": 1}
    assert body["by_status"] == {"open": 2, "owned": 1, "resolved": 1}
    listed = client.get(
        "/dq/issues", headers=auth_header(fake_db, "vera")
    ).json()
    assert len(listed) == body["total"]


def test_dq_counts_respect_the_same_status_filter_as_the_list(client, fake_db):
    _seed_dq(fake_db)
    r = client.get(
        "/dq/issues/counts",
        params={"status": "open"},
        headers=auth_header(fake_db, "vera"),
    )
    body = r.json()
    assert body["total"] == 2
    assert body["by_severity"] == {"blocking": 1, "warning": 1, "info": 0}
    assert body["by_status"] == {"open": 2, "owned": 0, "resolved": 0}


def test_dq_counts_empty_state_is_explicit_zeros(client, fake_db):
    r = client.get("/dq/issues/counts", headers=auth_header(fake_db, "vera"))
    assert r.json() == {
        "total": 0,
        "by_severity": {"blocking": 0, "warning": 0, "info": 0},
        "by_status": {"open": 0, "owned": 0, "resolved": 0},
    }


def test_dq_counts_bad_status_and_auth(client, fake_db):
    r = client.get(
        "/dq/issues/counts",
        params={"status": "nonsense"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422
    assert client.get("/dq/issues/counts").status_code == 401


# ---------------------------------------------------------------------------
# /safety/events/counts
# ---------------------------------------------------------------------------


def _seed_safety(fake_db):
    june = dt.datetime(2026, 6, 10, 12, 0, tzinfo=UTC)
    major = fake_db.add_safety_event(occurred_at=june, mode="bus")
    fake_db.add_safety_classification(major["event_id"], "major",
                                      thresholds_met=["fatality"])
    non_major = fake_db.add_safety_event(occurred_at=june, mode="bus")
    fake_db.add_safety_classification(non_major["event_id"], "non_major")
    nr = fake_db.add_safety_event(occurred_at=june, mode="rail")
    fake_db.add_safety_classification(nr["event_id"], "not_reportable")
    fake_db.add_safety_event(occurred_at=june, mode="bus")  # unclassified
    superseded = fake_db.add_safety_event(
        occurred_at=june, mode="bus",
        superseded_by=non_major["event_id"],
    )
    fake_db.add_safety_classification(superseded["event_id"], "non_major")
    july = dt.datetime(2026, 7, 3, 9, 0, tzinfo=UTC)
    other_month = fake_db.add_safety_event(occurred_at=july, mode="bus")
    fake_db.add_safety_classification(other_month["event_id"], "non_major")


def test_safety_counts_match_the_list(client, fake_db):
    _seed_safety(fake_db)
    r = client.get(
        "/safety/events/counts", headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 6
    assert body["by_classification"] == {
        "major": 1,
        "non_major": 3,
        "not_reportable": 1,
    }
    assert body["unclassified"] == 1
    assert body["superseded"] == 1
    listed = client.get(
        "/safety/events", headers=auth_header(fake_db, "vera")
    ).json()
    assert len(listed) == body["total"]


def test_safety_counts_respect_month_and_mode_filters(client, fake_db):
    _seed_safety(fake_db)
    r = client.get(
        "/safety/events/counts",
        params={"month": "2026-06", "mode": "bus"},
        headers=auth_header(fake_db, "vera"),
    )
    body = r.json()
    assert body["total"] == 4  # rail + the July event are filtered out
    assert body["by_classification"]["non_major"] == 2
    assert body["by_classification"]["not_reportable"] == 0
    assert body["unclassified"] == 1


def test_safety_counts_empty_state_is_explicit_zeros(client, fake_db):
    r = client.get(
        "/safety/events/counts", headers=auth_header(fake_db, "vera")
    )
    assert r.json() == {
        "total": 0,
        "by_classification": {
            "major": 0,
            "non_major": 0,
            "not_reportable": 0,
        },
        "unclassified": 0,
        "superseded": 0,
    }


def test_safety_counts_bad_month_and_auth(client, fake_db):
    r = client.get(
        "/safety/events/counts",
        params={"month": "June"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422
    assert client.get("/safety/events/counts").status_code == 401
