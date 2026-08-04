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


def _upload(client, fake_db, csv_text: str, *, path: str, user: str = "cora"):
    return client.post(
        path,
        files={"file": ("tripblock.csv", io.BytesIO(csv_text.encode()), "text/csv")},
        headers=auth_header(fake_db, user),
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


def test_extra_columns_are_ignored_so_the_service_day_can_ride_along(
    client, fake_db
):
    """The real export carries a third column (service day). It is not part of
    the join key, and rejecting the file over it would send an operator back to
    SSMS for nothing."""
    _seed_schedule(fake_db)
    three_col = "67 - 1E - 06:12,67-1,Weekday\n225 - 2N - 05:30,225-6,Saturday Service\n"
    body = _upload(
        client, fake_db, three_col, path="/admin/block-labels/preview"
    ).json()
    assert body["matched"] == 2
    assert body["labels_derived"] == 2


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
