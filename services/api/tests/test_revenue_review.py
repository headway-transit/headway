"""The revenue review queue: listing held boardings, and the audited
classification that closes one — with its justification note (handoff 0040).

The rules under test are the ones the wave exists to enforce: a boarding of
unknown revenue status stays out of the figure, a verdict without a written
reason is not recordable through any path, classifying patches no persisted
number, and a certified period is never rewritten behind the official who
signed it.
"""

import datetime as dt
import json

from conftest import auth_header

UTC = dt.timezone.utc


def test_queue_lists_pending_boardings_with_the_context_to_decide(
    client, fake_db
):
    fake_db.add_boarding_review(
        passenger_event_id="pe-1", vehicle_id="3684", event_count=4
    )
    r = client.get(
        "/revenue-review/boardings", headers=auth_header(fake_db, "vera")
    )
    assert r.status_code == 200
    (row,) = r.json()["boardings"]
    assert row["passenger_event_id"] == "pe-1"
    assert row["vehicle_id"] == "3684"
    assert row["event_count"] == 4
    assert row["service_date"] == "2026-07-09"
    # Headway states its own position: it declined to guess, and says why.
    assert row["suggested_verdict"] == "pending_review"
    assert "catch-up bus" in row["suggested_reason"]
    assert row["verdict"] is None
    assert row["justification"] is None
    assert r.json()["total"] == 1


def test_classified_boardings_are_not_in_the_pending_queue(client, fake_db):
    fake_db.add_boarding_review(passenger_event_id="pe-open")
    fake_db.add_boarding_review(
        passenger_event_id="pe-done",
        verdict="revenue",
        justification="Extra bus sent to recover the route; real riders.",
        classified_by="stella",
        classified_at=dt.datetime(2026, 7, 16, 10, 0, tzinfo=UTC),
    )
    r = client.get(
        "/revenue-review/boardings", headers=auth_header(fake_db, "vera")
    )
    assert [b["passenger_event_id"] for b in r.json()["boardings"]] == [
        "pe-open"
    ]
    assert r.json()["total"] == 1

    r = client.get(
        "/revenue-review/boardings",
        params={"status": "classified"},
        headers=auth_header(fake_db, "vera"),
    )
    (row,) = r.json()["boardings"]
    assert row["passenger_event_id"] == "pe-done"
    assert row["verdict"] == "revenue"
    assert row["classified_by"] == "stella"


def test_unknown_queue_filter_is_explained_in_plain_language(client, fake_db):
    r = client.get(
        "/revenue-review/boardings",
        params={"status": "maybe"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422
    assert "'pending'" in r.json()["detail"]


def test_queue_pages_by_keyset_without_skipping_or_repeating(client, fake_db):
    for minute in range(5):
        fake_db.add_boarding_review(
            passenger_event_id=f"pe-{minute}",
            event_timestamp=dt.datetime(2026, 7, 9, 15, minute, tzinfo=UTC),
        )
    first = client.get(
        "/revenue-review/boardings",
        params={"limit": 2},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert [b["passenger_event_id"] for b in first["boardings"]] == [
        "pe-0",
        "pe-1",
    ]
    assert first["has_more"] is True
    assert first["total"] == 5  # the whole queue, never the page

    second = client.get(
        "/revenue-review/boardings",
        params={"limit": 2, "cursor": first["next_cursor"]},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert [b["passenger_event_id"] for b in second["boardings"]] == [
        "pe-2",
        "pe-3",
    ]
    last = client.get(
        "/revenue-review/boardings",
        params={"limit": 2, "cursor": second["next_cursor"]},
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert [b["passenger_event_id"] for b in last["boardings"]] == ["pe-4"]
    assert last["has_more"] is False
    assert last["next_cursor"] is None


def test_unreadable_page_marker_refuses_instead_of_resetting(client, fake_db):
    r = client.get(
        "/revenue-review/boardings",
        params={"cursor": "not-a-marker-we-issued"},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 422
    assert "page marker" in r.json()["detail"]


def test_counts_report_rows_and_the_boardings_they_hold(client, fake_db):
    fake_db.add_boarding_review(passenger_event_id="pe-a", event_count=4)
    fake_db.add_boarding_review(passenger_event_id="pe-b", event_count=7)
    fake_db.add_boarding_review(
        passenger_event_id="pe-c",
        event_count=2,
        verdict="revenue",
        justification="Catch-up bus, confirmed with dispatch.",
        classified_by="stella",
        classified_at=dt.datetime(2026, 7, 16, tzinfo=UTC),
    )
    fake_db.add_boarding_review(
        passenger_event_id="pe-d",
        event_count=3,
        verdict="non_revenue",
        justification="Counter double-fired during layover.",
        classified_by="stella",
        classified_at=dt.datetime(2026, 7, 16, tzinfo=UTC),
    )
    counts = client.get(
        "/revenue-review/boardings/counts",
        headers=auth_header(fake_db, "vera"),
    ).json()
    assert counts["pending"] == 2
    # Rows and boardings are different numbers and both are told.
    assert counts["pending_boardings"] == 11
    assert counts["classified"] == 2
    assert counts["classified_revenue_boardings"] == 2
    assert counts["classified_non_revenue_boardings"] == 3


def test_classify_records_verdict_note_author_and_audit_event(
    client, fake_db
):
    review = fake_db.add_boarding_review(passenger_event_id="pe-1")
    note = (
        "Extra bus sent at 15:10 to recover the route after the 14:40 ran "
        "late; dispatch confirms these are real riders."
    )
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": note},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["verdict"] == "revenue"
    assert body["justification"] == note
    assert body["classified_by"] == "stella"
    # Said out loud in the response: the number has NOT moved yet.
    assert body["recompute_required"] is True

    assert review["verdict"] == "revenue"
    assert review["justification"] == note
    assert review["classified_by"] == "stella"
    assert review["classified_at"] is not None

    (event,) = [
        e
        for e in fake_db.audit_events
        if e["action"] == "boarding_revenue_classify"
    ]
    assert event["actor"] == "stella"
    assert event["subject_kind"] == "dq.boarding_revenue_reviews"
    assert event["subject_id"] == "pe-1"
    # The reason is IN the audit row: an auditor reading audit.events alone
    # can see why, without joining anywhere.
    detail = json.loads(event["detail"])
    assert detail["justification"] == note
    assert detail["figure_recomputed"] is False
    assert fake_db.tx_log[-1] == "commit"


def test_classify_closes_the_boardings_data_quality_finding(client, fake_db):
    fake_db.add_boarding_review(
        passenger_event_id="pe-1", source_record_id="rec-9"
    )
    issue = fake_db.add_dq_issue(
        issue_type="boarding_pending_revenue_review",
        severity="warning",
        status="open",
        source_record_ids=["rec-9"],
    )
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={
            "verdict": "non_revenue",
            "justification": "Mechanic boarding during pull-in; not a rider.",
        },
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200
    assert r.json()["dq_issue_id"] == issue["issue_id"]
    assert issue["status"] == "resolved"
    # The DQ trail and the review trail tell the SAME story about this
    # boarding — the resolution text is built from the decision.
    assert "NON-REVENUE" in issue["resolution"]
    assert "Mechanic boarding during pull-in" in issue["resolution"]
    assert "next time the calculation runs" in issue["resolution"]


def test_classify_without_an_open_finding_still_records_and_says_so(
    client, fake_db
):
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": "Real riders."},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200
    # Null, honestly — not a fabricated link.
    assert r.json()["dq_issue_id"] is None


def test_blank_justification_is_refused_with_an_example(client, fake_db):
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    for blank in ("", "   ", "\n\t "):
        r = client.post(
            "/revenue-review/boardings/pe-1/classify",
            json={"verdict": "revenue", "justification": blank},
            headers=auth_header(fake_db, "stella"),
        )
        assert r.status_code == 422, blank
    assert fake_db.boarding_reviews["pe-1"]["verdict"] is None


def test_invisible_justification_is_refused_too(client, fake_db):
    """A note nobody can read is not a reason.

    An external adversarial review (2026-08-01) landed a verdict whose entire
    justification was a single ZERO-WIDTH SPACE. It passed BOTH guards: Python
    str.strip() does not treat U+200B as whitespace, and PostgreSQL's
    one-argument btrim() removes the SPACE character only. The guarantee we
    state — the justification is required, enforced in the schema — was false
    for every invisible codepoint. Migration 0041 fixes the database side.
    """
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    invisible = (
        "​",  # zero-width space — the one the review actually used
        "‌‍",  # zero-width non-joiner + joiner
        "﻿",  # zero-width no-break space (BOM)
        "⁠",  # word joiner
        " ",  # non-breaking space: blank, but not an ASCII space
        " ​ \t\n",  # mixed with ordinary whitespace
    )
    for blank in invisible:
        r = client.post(
            "/revenue-review/boardings/pe-1/classify",
            json={"verdict": "revenue", "justification": blank},
            headers=auth_header(fake_db, "stella"),
        )
        assert r.status_code == 422, repr(blank)
    # Nothing recorded: the boarding still waits for a real answer.
    assert fake_db.boarding_reviews["pe-1"]["verdict"] is None


def test_a_real_note_carrying_an_invisible_character_still_works(client, fake_db):
    """The guard strips invisible padding; it must not reject real prose that
    happens to carry one (a paste out of a word processor)."""
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={
            "verdict": "revenue",
            "justification": "​extra bus sent to recover the route at 15:10",
        },
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200
    assert (
        fake_db.boarding_reviews["pe-1"]["justification"]
        == "extra bus sent to recover the route at 15:10"
    )


def test_justification_is_required_by_the_schema_not_just_the_form(
    client, fake_db
):
    """Omitting the field entirely is refused too — there is no default."""
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 422
    assert fake_db.boarding_reviews["pe-1"]["verdict"] is None


def test_unknown_verdict_is_refused_and_names_the_safe_answer(
    client, fake_db
):
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "probably_revenue", "justification": "not sure"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 422
    # There is no "include it anyway" state; leaving it queued IS the answer.
    assert "leave it in the queue" in r.text


def test_classifying_twice_is_refused_and_names_the_first_decider(
    client, fake_db
):
    fake_db.add_boarding_review(
        passenger_event_id="pe-1",
        verdict="non_revenue",
        justification="Prep boarding.",
        classified_by="stella",
        classified_at=dt.datetime(2026, 7, 16, tzinfo=UTC),
    )
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": "changed my mind"},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 409
    assert "already classified as non-revenue by stella" in r.json()["detail"]
    assert fake_db.boarding_reviews["pe-1"]["verdict"] == "non_revenue"


def test_classify_refuses_to_rewrite_a_certified_period(client, fake_db):
    fake_db.add_boarding_review(
        passenger_event_id="pe-1", service_date=dt.date(2026, 7, 9)
    )
    fake_db.add_metric_value(
        metric="upt",
        unit="unlinked_passenger_trips",
        period_start=dt.date(2026, 7, 1),
        period_end=dt.date(2026, 8, 1),
        certification_status="certified",
    )
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": "Real riders."},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "already been certified" in detail
    assert "re-certified deliberately" in detail
    # Refused loudly means nothing was written — not the verdict, not a
    # half-finished audit row.
    assert fake_db.boarding_reviews["pe-1"]["verdict"] is None
    assert not [
        e
        for e in fake_db.audit_events
        if e["action"] == "boarding_revenue_classify"
    ]
    assert fake_db.tx_log[-1] == "rollback"


def test_an_uncertified_period_covering_the_boarding_does_not_block(
    client, fake_db
):
    fake_db.add_boarding_review(
        passenger_event_id="pe-1", service_date=dt.date(2026, 7, 9)
    )
    fake_db.add_metric_value(
        metric="upt",
        period_start=dt.date(2026, 7, 1),
        period_end=dt.date(2026, 8, 1),
        certification_status="uncertified",
    )
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": "Real riders."},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200


def test_a_certified_period_that_does_not_cover_the_boarding_does_not_block(
    client, fake_db
):
    fake_db.add_boarding_review(
        passenger_event_id="pe-1", service_date=dt.date(2026, 7, 9)
    )
    fake_db.add_metric_value(
        metric="upt",
        period_start=dt.date(2026, 6, 1),
        period_end=dt.date(2026, 7, 1),
        certification_status="certified",
    )
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": "Real riders."},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 200


def test_viewer_may_read_the_queue_but_not_classify(client, fake_db):
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    assert (
        client.get(
            "/revenue-review/boardings", headers=auth_header(fake_db, "vera")
        ).status_code
        == 200
    )
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": "Real riders."},
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 403
    assert fake_db.boarding_reviews["pe-1"]["verdict"] is None
    assert not [
        e
        for e in fake_db.audit_events
        if e["action"] == "boarding_revenue_classify"
    ]


def test_report_preparer_may_classify_the_data_steward_bar_is_a_floor(
    client, fake_db
):
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    r = client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": "Real riders."},
        headers=auth_header(fake_db, "petra"),
    )
    assert r.status_code == 200


def test_queue_requires_a_signed_in_identity(client, fake_db):
    assert client.get("/revenue-review/boardings").status_code == 401


def test_unknown_boarding_is_a_plain_language_404(client, fake_db):
    r = client.get(
        "/revenue-review/boardings/pe-nope",
        headers=auth_header(fake_db, "vera"),
    )
    assert r.status_code == 404
    assert "revenue review queue" in r.json()["detail"]

    r = client.post(
        "/revenue-review/boardings/pe-nope/classify",
        json={"verdict": "revenue", "justification": "Real riders."},
        headers=auth_header(fake_db, "stella"),
    )
    assert r.status_code == 404


def test_one_boarding_reads_back_with_its_decision(client, fake_db):
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={
            "verdict": "non_revenue",
            "justification": "Driver prep boarding before pull-out.",
        },
        headers=auth_header(fake_db, "stella"),
    )
    row = client.get(
        "/revenue-review/boardings/pe-1", headers=auth_header(fake_db, "vera")
    ).json()
    assert row["verdict"] == "non_revenue"
    assert row["justification"] == "Driver prep boarding before pull-out."
    assert row["classified_by"] == "stella"


def test_classifying_writes_no_metric_value(client, fake_db):
    """The whole recompute-honesty rule, pinned: no persisted figure moves."""
    fake_db.add_boarding_review(passenger_event_id="pe-1")
    value = fake_db.add_metric_value(
        metric="upt",
        period_start=dt.date(2026, 7, 1),
        period_end=dt.date(2026, 8, 1),
        value=1000,
    )
    before = dict(value)
    client.post(
        "/revenue-review/boardings/pe-1/classify",
        json={"verdict": "revenue", "justification": "Real riders."},
        headers=auth_header(fake_db, "stella"),
    )
    assert fake_db.metric_values[value["metric_value_id"]] == before
