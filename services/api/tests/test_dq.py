"""DQ issue list + audited resolution workflow."""

import json

from conftest import auth_header


def test_list_issues_and_filter_by_status(client, fake_db):
    fake_db.add_dq_issue(status="open", title="gap A")
    fake_db.add_dq_issue(status="resolved", title="gap B",
                         resolution="re-ingested")
    r = client.get("/dq/issues", headers=auth_header(fake_db, "vera"))
    assert r.status_code == 200
    assert len(r.json()["issues"]) == 2
    assert r.json()["total"] == 2

    r = client.get("/dq/issues", params={"status": "open"},
                   headers=auth_header(fake_db, "vera"))
    (row,) = r.json()["issues"]
    assert row["title"] == "gap A"
    assert row["severity"] == "warning"  # severity is text, never a color code
    # The total follows the filter — it is the whole queue UNDER THAT
    # FILTER, never the page and never the unfiltered queue.
    assert r.json()["total"] == 1


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
    ).json()["issues"]
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
    ).json()["issues"]
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
    ).json()["issues"]
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
    ).json()["issues"]
    assert "subject_context" in row and row["subject_context"] is None


def test_subject_context_needs_authentication_like_every_other_field(
    client, fake_db
):
    fake_db.add_dq_issue(subject_context=SUBJECT_CONTEXT)
    assert client.get("/dq/issues").status_code == 401


# --- the queue is BOUNDED, always (handoff 0030) ----------------------------
#
# Until this wave GET /dq/issues returned every row: 98,497 issues, 850 MB
# of JSON, 17 s, and a frozen browser tab on the screen a data steward lives
# in. These tests pin that an unbounded request is now IMPOSSIBLE, that the
# ordering is total so pages cannot drop or repeat a row, and that the total
# always describes the whole queue rather than the page.

import datetime as dt  # noqa: E402

from conftest import UTC  # noqa: E402


def _seed_queue(fake_db, n, **overrides):
    """n issues, all sharing ONE created_at — the live shape (98,497 rows
    across 31 distinct timestamps), and the case a created_at-only ordering
    gets wrong."""
    same_instant = dt.datetime(2026, 7, 22, 3, 0, tzinfo=UTC)
    return [
        fake_db.add_dq_issue(
            created_at=same_instant, title=f"finding {i:04d}", **overrides
        )
        for i in range(n)
    ]


def test_the_list_is_bounded_by_default(client, fake_db):
    """No caller has to ask for a page — asking for nothing gets one."""
    _seed_queue(fake_db, 120)
    body = client.get("/dq/issues", headers=auth_header(fake_db, "vera")).json()
    assert len(body["issues"]) == 50  # DEFAULT_PAGE_LIMIT
    assert body["limit"] == 50
    # ...and the response says what it is NOT showing.
    assert body["total"] == 120
    assert body["has_more"] is True
    assert body["next_cursor"]


def test_no_limit_can_reach_the_whole_queue(client, fake_db):
    """The cap is enforced, not advertised: every way of asking for more
    than the maximum is refused outright rather than quietly clamped —
    a clamped 100,000 would look like it had returned everything."""
    _seed_queue(fake_db, 5)
    for bad in (201, 100000, 0, -1):
        r = client.get(
            "/dq/issues",
            params={"limit": bad},
            headers=auth_header(fake_db, "vera"),
        )
        assert r.status_code == 422, bad
    r = client.get(
        "/dq/issues", params={"limit": 200}, headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 200


def _walk(client, fake_db, **params):
    """Every page, followed by cursor, as a caller would."""
    seen, cursor, pages = [], None, 0
    while True:
        query = dict(params)
        if cursor:
            query["cursor"] = cursor
        body = client.get(
            "/dq/issues", params=query, headers=auth_header(fake_db, "vera")
        ).json()
        seen.extend(body["issues"])
        pages += 1
        cursor = body["next_cursor"]
        assert pages < 100, "cursor did not terminate"
        if not cursor:
            assert body["has_more"] is False
            return seen, pages, body


def test_paging_covers_every_row_exactly_once(client, fake_db):
    """Deterministic AND total: 137 rows sharing one created_at, walked in
    pages of 10, must come back 137 times — not 130, not 140."""
    _seed_queue(fake_db, 137)
    seen, pages, last = _walk(client, fake_db, limit=10)
    assert len(seen) == 137
    assert len({i["issue_id"] for i in seen}) == 137
    assert pages == 14  # 13 full pages + the remainder
    assert last["total"] == 137


def test_the_last_page_says_it_is_the_last(client, fake_db):
    """An exact multiple of the page size is the sharp edge: the walk must
    stop, not hand back an empty page that looks like more work."""
    _seed_queue(fake_db, 20)
    seen, pages, last = _walk(client, fake_db, limit=10)
    assert len(seen) == 20
    assert pages == 2  # NOT 3 — no empty trailing page
    assert last["has_more"] is False and last["next_cursor"] is None


def test_a_cursor_past_the_end_is_an_honest_empty_page(client, fake_db):
    issues = _seed_queue(fake_db, 3)
    body = client.get(
        "/dq/issues", params={"limit": 3}, headers=auth_header(fake_db, "vera")
    ).json()
    assert body["has_more"] is False
    # Forge a cursor beyond the last row: an empty page, with the total
    # still telling the truth about the queue.
    import base64

    beyond = base64.urlsafe_b64encode(
        f"{dt.datetime(2099, 1, 1, tzinfo=UTC).isoformat()}|"
        f"{issues[0]['issue_id']}".encode()
    ).decode().rstrip("=")
    body = client.get(
        "/dq/issues",
        params={"cursor": beyond},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert body["issues"] == []
    assert body["total"] == 3
    assert body["has_more"] is False


def test_a_meaningless_cursor_is_refused_not_silently_reset(client, fake_db):
    """Serving page one for an unreadable marker would make a caller
    walking the queue believe it had seen rows it never received."""
    _seed_queue(fake_db, 3)
    for bad in ("not-base64!!", "", "Zm9v", "MjAyNi0wMS0wMXxub3QtYS11dWlk"):
        r = client.get(
            "/dq/issues",
            params={"cursor": bad},
            headers=auth_header(fake_db, "vera"),
        )
        assert r.status_code == 422, bad
        assert "page marker" in r.json()["detail"]


def test_rows_inserted_behind_the_reader_do_not_shift_the_page(client, fake_db):
    """The live queue grows while a steward reads it. Keyset paging is
    anchored to the last row SERVED, so a finding raised mid-walk cannot
    push an unread row past the reader."""
    _seed_queue(fake_db, 20)
    first = client.get(
        "/dq/issues", params={"limit": 10}, headers=auth_header(fake_db, "vera")
    ).json()
    # A calc run lands 30 new findings, timestamped now (after everything).
    for i in range(30):
        fake_db.add_dq_issue(
            created_at=dt.datetime(2026, 7, 23, 3, 0, tzinfo=UTC),
            title=f"new {i}",
        )
    second = client.get(
        "/dq/issues",
        params={"limit": 10, "cursor": first["next_cursor"]},
        headers=auth_header(fake_db, "vera"),
    ).json()
    page_one = {i["issue_id"] for i in first["issues"]}
    page_two = {i["issue_id"] for i in second["issues"]}
    assert page_one.isdisjoint(page_two)  # nothing served twice
    # ...and the total tells the truth about the queue as it is NOW.
    assert second["total"] == 50


def test_provenance_is_not_in_the_queue_but_is_one_request_away(
    client, fake_db
):
    """source_record_ids left the list (716 MB of an 850 MB response) and
    lives on the per-issue endpoint — COMPLETE, never truncated. This is a
    relocation of provenance, not a reduction of it."""
    ids = [f"sha256:{i:064x}" for i in range(500)]
    issue = fake_db.add_dq_issue(source_record_ids=ids)
    (row,) = client.get(
        "/dq/issues", headers=auth_header(fake_db, "vera")
    ).json()["issues"]
    assert "source_record_ids" not in row
    detail = client.get(
        f"/dq/issues/{issue['issue_id']}", headers=auth_header(fake_db, "vera")
    ).json()
    assert detail["source_record_ids"] == ids  # all 500, in order


def test_severity_filter_narrows_the_queue_on_the_SERVER(client, fake_db):
    """The /dq severity cards used to filter the fully-downloaded queue in
    the browser. With one page loaded that would have filtered the PAGE —
    a card reading '8,824 blocking' above two visible rows. The filter runs
    where the rows are."""
    _seed_queue(fake_db, 30, severity="warning")
    _seed_queue(fake_db, 5, severity="blocking")
    body = client.get(
        "/dq/issues",
        params={"severity": "blocking"},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert body["total"] == 5
    assert len(body["issues"]) == 5
    assert {i["severity"] for i in body["issues"]} == {"blocking"}


def test_severity_and_status_filters_combine(client, fake_db):
    _seed_queue(fake_db, 4, severity="blocking", status="open")
    _seed_queue(fake_db, 6, severity="blocking", status="resolved")
    _seed_queue(fake_db, 3, severity="warning", status="open")
    body = client.get(
        "/dq/issues",
        params={"severity": "blocking", "status": "open"},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert body["total"] == 4


def test_unknown_severity_is_explained_like_an_unknown_status(client, fake_db):
    r = client.get(
        "/dq/issues",
        params={"severity": "critical"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422
    assert "Valid severities are" in r.json()["detail"]


def test_counts_carry_the_whole_queue_effort_total(client, fake_db):
    """The /dq header's documented-effort line used to be summed from the
    whole downloaded queue. With one page loaded that sum would silently
    have become 'effort on the 50 issues you can see', so the server sums
    it over the same rows it counts."""
    fake_db.add_dq_issue(status="resolved", resolution_minutes=45)
    fake_db.add_dq_issue(status="resolved", resolution_minutes=15)
    fake_db.add_dq_issue(status="open")  # unmeasured — null, never zero
    body = client.get(
        "/dq/issues/counts", headers=auth_header(fake_db, "vera")
    ).json()
    assert body["resolution_minutes_total"] == 60
    assert body["total"] == 3
    # Under a filter it covers exactly the filtered rows, like every other
    # number this endpoint returns.
    filtered = client.get(
        "/dq/issues/counts",
        params={"status": "open"},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert filtered["resolution_minutes_total"] == 0


def test_counts_and_the_page_total_agree_under_the_same_filter(
    client, fake_db
):
    """The 0017 guarantee, kept at page scale: the cards can never disagree
    with the table below them."""
    _seed_queue(fake_db, 11, status="open")
    _seed_queue(fake_db, 7, status="resolved")
    page = client.get(
        "/dq/issues",
        params={"status": "open", "limit": 5},
        headers=auth_header(fake_db, "vera"),
    ).json()
    counts = client.get(
        "/dq/issues/counts",
        params={"status": "open"},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert page["total"] == counts["total"] == 11
    assert len(page["issues"]) == 5  # the page is not the queue, and says so


def test_the_page_still_requires_authentication(client, fake_db):
    _seed_queue(fake_db, 2)
    assert client.get("/dq/issues", params={"limit": 1}).status_code == 401
