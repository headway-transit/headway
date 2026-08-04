"""Uploading the agency's trip→block export — the screen that replaces a shell.

The derivation has existed as tools/block-labels/derive.py since handoff 0038
and was never run once, because running it means a terminal, a database
password and a Python invocation. The person who needs it is an ITS manager
who was a week into Linux when this started, and who had three commands
mangled by copy-paste in a single day (2026-08-03).

What matters here is not that a file uploads. It is that the endpoint REFUSES
the same things the CLI refuses, for the same reasons — because the labels it
writes end up on findings an auditor reads, and a mapping that guessed is
worse than no mapping at all.
"""

from __future__ import annotations

import io

from conftest import auth_header


def _seed_schedule(fake_db):
    """Two blocks, four trips, addressable by route + first departure."""
    # block "A" — route 67, departing 06:12 and 07:04
    fake_db.add_scheduled_trip("t1", "67", 6 * 3600 + 12 * 60, "blk-A")
    fake_db.add_scheduled_trip("t2", "67", 7 * 3600 + 4 * 60, "blk-A")
    # block "B" — route 225, departing 05:30
    fake_db.add_scheduled_trip("t3", "225", 5 * 3600 + 30 * 60, "blk-B")
    # a trip with no route short name: never addressable, never a candidate
    fake_db.add_canonical_trip("t4", "route-unknown", block_id="blk-C")


def _upload(client, fake_db, csv_text: str, *, path: str, user: str = "cora",
            schedule_date: str | None = None):
    kwargs = {}
    if schedule_date is not None:
        kwargs["data"] = {"schedule_date": schedule_date}
    return client.post(
        path,
        files={"file": ("tripblock.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        headers=auth_header(fake_db, user),
        **kwargs,
    )


GOOD = "67 - 1E - 06:12,67-1\n67 - 1E - 07:04,67-1\n225 - 2N - 05:30,225-6\n"


def test_preview_reports_what_would_happen_and_writes_nothing(client, fake_db):
    _seed_schedule(fake_db)
    r = _upload(client, fake_db, GOOD, path="/admin/block-labels/preview")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["rows_read"] == 3
    assert body["matched"] == 3
    assert body["labels_derived"] == 2
    assert body["conflicts"] == 0
    assert "Nothing has been saved" in body["note"]
    # THE POINT: a preview that wrote would make approval meaningless.
    assert fake_db.block_labels == {}


def test_load_writes_the_mapping_and_is_audited(client, fake_db):
    _seed_schedule(fake_db)
    r = _upload(client, fake_db, GOOD, path="/admin/block-labels/load")
    assert r.status_code == 200, r.text

    assert {b: v["block_label"] for b, v in fake_db.block_labels.items()} == {
        "blk-A": "67-1",
        "blk-B": "225-6",
    }
    assert fake_db.block_labels["blk-A"]["loaded_by"] == "cora"
    assert "admin upload by cora" in fake_db.block_labels["blk-A"]["derivation"]
    event = [
        e for e in fake_db.audit_events if e["action"] == "block_labels_loaded"
    ][-1]
    assert event["actor"] == "cora"


def test_provenance_matches_the_command_line_exactly(client, fake_db):
    """The CLI records the file's sha256 and the parse-config hash beside
    every label. A label loaded through the screen lands on the same
    findings, so the door somebody came in must not decide how well a
    federal figure's inputs are attributed."""
    import hashlib
    import json

    _seed_schedule(fake_db)
    r = _upload(client, fake_db, GOOD, path="/admin/block-labels/load")
    assert r.status_code == 200, r.text

    digest = hashlib.sha256(GOOD.encode()).hexdigest()
    row = fake_db.block_labels["blk-A"]
    # The bytes' own digest — a filename alone would let two different files
    # claim identical provenance.
    assert row["source"] == f"tripblock.csv sha256={digest}"
    # And the rules that read them, so "by what method?" is answerable later.
    assert "route_short_name, first scheduled departure" in row["derivation"]
    assert "config " in row["derivation"]
    assert "never guessed" in row["derivation"]

    event = [
        e for e in fake_db.audit_events if e["action"] == "block_labels_loaded"
    ][-1]
    # detail reaches the DB as JSON text (write_event serialises it), so the
    # fake holds exactly what Postgres would store in the jsonb column.
    detail = json.loads(event["detail"]) if isinstance(event["detail"], str) else event["detail"]
    assert detail["file_sha256"] == digest


def test_a_block_two_rows_disagree_about_is_excluded_not_chosen_between(
    client, fake_db
):
    """The refusal that matters most. If two rows give one block different
    names, picking either would put an invented name on a finding."""
    _seed_schedule(fake_db)
    conflicting = "67 - 1E - 06:12,67-1\n67 - 1E - 07:04,67-9\n"
    r = _upload(client, fake_db, conflicting, path="/admin/block-labels/load")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["conflicts"] == 1
    assert body["labels_derived"] == 0
    assert "left out rather than guessed at" in body["conflict_notes"][0]
    assert fake_db.block_labels == {}


def test_rows_that_do_not_match_the_schedule_are_reported_not_dropped(
    client, fake_db
):
    """An unmatched row is a fact about the export, and silently ignoring it
    would let a half-loaded mapping look complete."""
    _seed_schedule(fake_db)
    r = _upload(
        client, fake_db,
        "67 - 1E - 06:12,67-1\n999 - 9Z - 23:59,999-1\n",
        path="/admin/block-labels/preview",
    )
    body = r.json()
    assert body["unmatched"] == 1
    assert body["unmatched_examples"][0]["trip_name"] == "999 - 9Z - 23:59"
    assert body["unmatched_examples"][0]["reason"]


def test_an_unreadable_trip_name_is_counted_never_guessed(client, fake_db):
    _seed_schedule(fake_db)
    r = _upload(
        client, fake_db,
        "67 - 1E - 06:12,67-1\nnot a trip name at all,67-2\n",
        path="/admin/block-labels/preview",
    )
    body = r.json()
    assert body["unparseable"] == 1
    assert body["unparseable_examples"][0]["block_name"] == "67-2"


def test_a_header_row_is_tolerated_because_ssms_omits_one(client, fake_db):
    """SSMS does not write column headers when saving a grid unless someone
    changes a setting. Requiring one would fail the common case; refusing one
    would fail the careful case."""
    _seed_schedule(fake_db)
    with_header = "TripName,BlockName\n" + GOOD
    body = _upload(
        client, fake_db, with_header, path="/admin/block-labels/preview"
    ).json()
    assert body["rows_read"] == 3
    assert body["matched"] == 3


def test_a_third_column_is_read_as_the_service_day_not_discarded(
    client, fake_db
):
    """The real export carries a third column (service day). It used to be
    thrown away. Measured 2026-08-04, it is the ONLY thing that separates a
    weekday block from a Saturday one — 43.7% of keys on a real feed are
    ambiguous without it."""
    _seed_schedule(fake_db)
    three_col = "67 - 1E - 06:12,67-1,Weekday\n225 - 2N - 05:30,225-6,Saturday Service\n"
    body = _upload(
        client, fake_db, three_col, path="/admin/block-labels/preview"
    ).json()
    assert body["matched"] == 2
    assert body["labels_derived"] == 2
    # Every service day in the file gets a line saying what was done with it.
    assert {d["service_day"] for d in body["service_days"]} == {
        "Weekday", "Saturday Service"
    }


def _two_service_schedule(fake_db):
    """Route 42 at 13:00 runs on two services, on two different blocks — the
    exact shape that makes the base (route, start) key ambiguous."""
    fake_db.add_scheduled_trip("wk1", "42", 13 * 3600, "blk-wk", service_id="wk")
    fake_db.add_scheduled_trip("wk2", "42", 14 * 3600, "blk-wk", service_id="wk")
    fake_db.add_scheduled_trip("sa1", "42", 13 * 3600, "blk-sa", service_id="sa")
    fake_db.add_scheduled_trip("sa2", "42", 15 * 3600, "blk-sa", service_id="sa")


def test_the_service_day_turns_an_ambiguous_row_into_a_named_block(
    client, fake_db
):
    """The whole point of step 1. Same rows, same schedule — the only
    difference is whether the file carries its third column."""
    _two_service_schedule(fake_db)
    two_col = "42 - 42WD - 13:00,42-1\n42 - 42WD - 14:00,42-1\n"
    without = _upload(
        client, fake_db, two_col, path="/admin/block-labels/preview"
    ).json()
    # The 13:00 row is ambiguous (both services run it); the 14:00 row is
    # uniquely weekday, so the block still gets named — off ONE row. This is
    # why 43.7% ambiguous keys did not mean 43.7% unnamed blocks.
    assert without["ambiguous"] == 1
    assert without["matched"] == 1
    assert without["labels_derived"] == 1

    three_col = ("42 - 42WD - 13:00,42-1,Weekday\n"
                 "42 - 42WD - 14:00,42-1,Weekday\n")
    with_day = _upload(
        client, fake_db, three_col, path="/admin/block-labels/preview"
    ).json()
    # Same one block, but now BOTH rows support it rather than one — the
    # ambiguity is gone, not merely survived.
    assert with_day["ambiguous"] == 0
    assert with_day["matched"] == 2
    assert with_day["labels_derived"] == 1

    used = [d for d in with_day["service_days"] if d["used"]]
    assert len(used) == 1
    assert "Used to tell blocks apart" in used[0]["explanation"]


def test_a_service_day_that_cannot_be_paired_says_so_and_narrows_nothing(
    client, fake_db
):
    """Two services explaining one label equally well — overlapping schedule
    versions. The screen has to say it was NOT used, or a reader assumes the
    separation happened."""
    fake_db.add_scheduled_trip("a", "42", 13 * 3600, "blk-a", service_id="s1")
    fake_db.add_scheduled_trip("b", "42", 13 * 3600, "blk-b", service_id="s2")
    body = _upload(
        client, fake_db, "42 - 42WD - 13:00,42-1,Saturday Service\n",
        path="/admin/block-labels/preview",
    ).json()

    assert body["ambiguous"] == 1
    assert body["labels_derived"] == 0
    note = body["service_days"][0]
    assert note["used"] is False
    assert "Not used" in note["explanation"]


def test_an_empty_or_single_column_file_says_what_is_wrong(client, fake_db):
    _seed_schedule(fake_db)
    empty = _upload(client, fake_db, "   \n", path="/admin/block-labels/preview")
    assert empty.status_code == 422
    assert "empty" in empty.json()["detail"]

    one_col = _upload(
        client, fake_db, "67 - 1E - 06:12\n", path="/admin/block-labels/preview"
    )
    assert one_col.status_code == 422
    assert "two" in one_col.json()["detail"]


def test_only_a_certifying_official_may_load(client, fake_db):
    _seed_schedule(fake_db)
    for user in ("vera", "stella", "petra"):
        for path in ("/admin/block-labels/preview", "/admin/block-labels/load"):
            r = _upload(client, fake_db, GOOD, path=path, user=user)
            assert r.status_code == 403, (user, path)
    assert fake_db.block_labels == {}


def test_preview_and_load_agree_because_they_derive_identically(
    client, fake_db
):
    """The file is sent twice on purpose — nothing is cached between the two
    steps, so an operator can never approve numbers that describe a different
    file from the one that gets written."""
    _seed_schedule(fake_db)
    preview = _upload(
        client, fake_db, GOOD, path="/admin/block-labels/preview"
    ).json()
    loaded = _upload(client, fake_db, GOOD, path="/admin/block-labels/load").json()
    for field in ("rows_read", "matched", "ambiguous", "unmatched",
                  "unparseable", "labels_derived", "conflicts"):
        assert preview[field] == loaded[field], field


def test_naming_the_schedule_period_pairs_a_label_two_signups_share(
    client, fake_db
):
    """STEP 2. Two Saturday signups run the same route at the same time on
    different blocks. The label cannot choose between them — until the
    operator says which period the export describes."""
    import datetime as dt

    from conftest import UTC

    summer = dt.datetime(2026, 8, 1, tzinfo=UTC).date()
    autumn = dt.datetime(2026, 10, 3, tzinfo=UTC).date()
    fake_db.add_service_dates("sat-summer", summer)
    fake_db.add_service_dates("sat-autumn", autumn)
    fake_db.add_scheduled_trip("s1", "42", 13 * 3600, "blk-summer",
                               service_id="sat-summer")
    fake_db.add_scheduled_trip("a1", "42", 13 * 3600, "blk-autumn",
                               service_id="sat-autumn")
    csv_text = "42 - 42WD - 13:00,42-1,Saturday Service\n"

    without = _upload(
        client, fake_db, csv_text, path="/admin/block-labels/preview"
    ).json()
    assert without["ambiguous"] == 1
    assert without["labels_derived"] == 0
    assert without["service_days"][0]["used"] is False

    scoped = _upload(
        client, fake_db, csv_text, path="/admin/block-labels/preview",
        schedule_date="2026-08-01",
    ).json()
    assert scoped["ambiguous"] == 0
    assert scoped["matched"] == 1
    assert scoped["labels_derived"] == 1
    assert scoped["service_days"][0]["used"] is True


def test_an_unreadable_schedule_date_says_what_shape_to_use(client, fake_db):
    _seed_schedule(fake_db)
    r = _upload(client, fake_db, GOOD, path="/admin/block-labels/preview",
                schedule_date="last August")
    assert r.status_code == 422
    assert "2026-08-01" in r.json()["detail"]


def test_the_declared_period_is_recorded_in_the_audit_trail(client, fake_db):
    """It changes which blocks get named, so it belongs beside the file's
    digest — not only in the operator's memory."""
    import json

    _seed_schedule(fake_db)
    _upload(client, fake_db, GOOD, path="/admin/block-labels/load",
            schedule_date="2026-08-01")
    event = [
        e for e in fake_db.audit_events if e["action"] == "block_labels_loaded"
    ][-1]
    detail = json.loads(event["detail"]) if isinstance(event["detail"], str) else event["detail"]
    assert detail["schedule_date"] == "2026-08-01"
