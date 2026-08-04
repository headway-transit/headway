"""Block-label derivation (handoff 0038): the resolver's parse reused, the
match/ambiguous/unmatched/unparseable outcomes counted honestly, conflicts
refused, and the loader's provenance-bearing upsert.

Every fixture here is a SYNTHETIC TWIN (handoff 0016 discipline): the shapes
are the vendor export's, the values are invented. The real mapping file is
gitignored agency data and never enters the repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from headway_transform.adapters.resolution import (
    load_resolution_spec,
    parse_trip_name,
)
from headway_transform.block_labels import (
    AMBIGUOUS,
    ServiceDayPairing,
    pair_service_days,
    MATCHED,
    UNMATCHED,
    UNPARSEABLE,
    MappingFileError,
    MappingRow,
    TripWithBlock,
    derive_block_labels,
    load_block_labels,
    read_mapping_csv,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Builders (synthetic vocabulary throughout)
# ---------------------------------------------------------------------------


def _spec(tmp_path: Path):
    """The parse rules of the committed tripspark resolution config, as a
    synthetic standalone spec — parse is the only clause this derivation
    reads, and the committed config's direction gate must stay untouched."""
    doc = {
        "resolution_spec_version": 0,
        "source_label": "tripspark_streets",
        "target_contract": "tides_passenger_events",
        "trip": {
            "vendor_identifier": {"from_field": "trip_id_performed"},
            "parse": {
                "separator": " - ",
                "components": ["route", "pattern", "start_time"],
            },
            "match": {
                "route": {"component": "route", "gtfs_field": "route_short_name"},
                "start_time": {"component": "start_time", "format": "%H:%M"},
                "direction": {
                    "from_column": "DirectionKey",
                    "confirmed": False,
                    "unconfirmed_reason": "synthetic fixture",
                },
                "service": {
                    "from_field": "service_date",
                    "service_day_rollover": "not_confirmed",
                },
            },
        },
        "provenance": {
            "verified_against": {
                "schedule_feed": {
                    "retrieved": "2026-07-30",
                    "trips": 3,
                    "key_uniqueness": "synthetic fixture — invented schedule",
                },
                "vendor_export": {
                    "status": "none_available",
                    "note": "synthetic fixture — no vendor export exists",
                },
            },
            "verification_date": "2026-07-30",
            "notes": "synthetic fixture — invented vocabulary throughout",
        },
    }
    path = tmp_path / "resolution.v0.yaml"
    path.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return load_resolution_spec(path)


def trip(trip_id, short_name, departure, block_id, service_id=None):
    return TripWithBlock(
        trip_id=trip_id,
        route_short_name=short_name,
        first_departure_seconds=departure,
        block_id=block_id,
        service_id=service_id,
    )


def row(line_no, trip_name, block_name, service_day=None):
    return MappingRow(
        line_no=line_no,
        trip_name=trip_name,
        block_name=block_name,
        service_day=service_day,
    )


# ---------------------------------------------------------------------------
# The parse is the resolver's parse — reused, not reimplemented
# ---------------------------------------------------------------------------


def test_derivation_reads_trip_names_with_the_resolvers_own_parse(tmp_path):
    spec = _spec(tmp_path)
    ok = parse_trip_name(spec, "42 - 42WD - 13:00")
    assert ok.ok
    assert ok.parsed == {"route": "42", "pattern": "42WD", "start_time": "13:00"}
    assert ok.start_seconds == 13 * 3600

    bad = parse_trip_name(spec, "NULL")
    assert not bad.ok
    assert "1 part(s)" in bad.reason and "Nothing was assumed" in bad.reason


def test_the_committed_tripspark_config_has_agency_confirmed_direction(tmp_path):
    """Block-name derivation is independent of the direction gate, and the
    agency confirmed the direction mapping on 2026-07-31 — so the committed
    resolution.v0.yaml now carries confirmed: true. (Block-label derivation
    never touched it either way; this just tracks the current, live state.)"""
    committed = load_resolution_spec(
        REPO_ROOT / "adapters" / "tripspark" / "streets" / "resolution.v0.yaml"
    )
    assert committed.direction.confirmed is True
    assert committed.direction.values == {
        "1": 0, "2": 1, "3": 1, "4": 0, "5": 1, "6": 0, "7": 0,
    }


# ---------------------------------------------------------------------------
# The four outcomes, counted honestly
# ---------------------------------------------------------------------------


def test_a_unique_route_and_start_key_lands_the_block_label(tmp_path):
    result = derive_block_labels(
        _spec(tmp_path),
        [row(1, "42 - 42WD - 13:00", "42-9")],
        [trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1")],
    )
    assert result.counts == {
        MATCHED: 1,
        AMBIGUOUS: 0,
        UNMATCHED: 0,
        UNPARSEABLE: 0,
    }
    assert result.mapping == (("feed-block-uuid-1", "42-9", 1),)
    assert result.conflicts == ()


def test_several_trips_sharing_the_key_and_the_block_still_match(tmp_path):
    """Weekday and Saturday variants of the same departure often share the
    block; agreement across every candidate IS a match — the key names a
    block, not a trip."""
    result = derive_block_labels(
        _spec(tmp_path),
        [row(1, "42 - 42WD - 13:00", "42-9")],
        [
            trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1"),
            trip("feed-trip-2", "42", 13 * 3600, "feed-block-uuid-1"),
        ],
    )
    assert result.counts[MATCHED] == 1
    assert result.mapping == (("feed-block-uuid-1", "42-9", 1),)


def test_candidates_across_two_blocks_are_ambiguous_and_nothing_is_picked(
    tmp_path,
):
    result = derive_block_labels(
        _spec(tmp_path),
        [row(1, "42 - 42WD - 13:00", "42-9")],
        [
            trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1"),
            trip("feed-trip-2", "42", 13 * 3600, "feed-block-uuid-2"),
        ],
    )
    assert result.counts[AMBIGUOUS] == 1
    assert result.mapping == ()
    (outcome,) = result.outcomes
    assert outcome.candidate_block_ids == (
        "feed-block-uuid-1",
        "feed-block-uuid-2",
    )
    assert "nothing was picked" in outcome.reason


def test_a_blockless_candidate_makes_the_row_ambiguous_not_a_guess(tmp_path):
    """A candidate with no block cannot confirm the mapping — it might BE a
    different block. Ambiguous, with the absence stated."""
    result = derive_block_labels(
        _spec(tmp_path),
        [row(1, "42 - 42WD - 13:00", "42-9")],
        [
            trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1"),
            trip("feed-trip-2", "42", 13 * 3600, None),
        ],
    )
    assert result.counts[AMBIGUOUS] == 1
    (outcome,) = result.outcomes
    assert "no block at all" in outcome.reason


def test_no_candidate_at_all_is_unmatched_with_the_search_stated(tmp_path):
    result = derive_block_labels(
        _spec(tmp_path),
        [row(1, "42 - 42WD - 03:33", "42-9")],
        [trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1")],
    )
    assert result.counts[UNMATCHED] == 1
    (outcome,) = result.outcomes
    assert "'03:33'" in outcome.reason and "route '42'" in outcome.reason


def test_only_blockless_candidates_are_unmatched_with_the_reason_stated(
    tmp_path,
):
    result = derive_block_labels(
        _spec(tmp_path),
        [row(1, "42 - 42WD - 13:00", "42-9")],
        [trip("feed-trip-1", "42", 13 * 3600, None)],
    )
    assert result.counts[UNMATCHED] == 1
    (outcome,) = result.outcomes
    assert "none carries a block" in outcome.reason


def test_an_unreadable_trip_name_and_a_blank_label_are_unparseable(tmp_path):
    result = derive_block_labels(
        _spec(tmp_path),
        [
            row(1, "NULL", "42-9"),
            row(2, "42 - 42WD - 13:00", ""),
        ],
        [trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1")],
    )
    assert result.counts[UNPARSEABLE] == 2
    assert result.mapping == ()
    assert "Nothing was assumed" in result.outcomes[0].reason
    assert "no block name at all" in result.outcomes[1].reason


# ---------------------------------------------------------------------------
# Conflicts are refused, never resolved
# ---------------------------------------------------------------------------


def test_two_labels_for_one_feed_block_exclude_it_and_say_so(tmp_path):
    result = derive_block_labels(
        _spec(tmp_path),
        [
            row(1, "42 - 42WD - 13:00", "42-9"),
            row(2, "42 - 42WD - 15:00", "9-8"),
        ],
        [
            trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1"),
            trip("feed-trip-2", "42", 15 * 3600, "feed-block-uuid-1"),
        ],
    )
    assert result.counts[MATCHED] == 2
    assert result.mapping == ()
    (conflict,) = result.conflicts
    assert conflict.block_id == "feed-block-uuid-1"
    assert conflict.labels == ("42-9", "9-8")
    assert conflict.row_line_nos == (1, 2)
    assert any("excluded from the mapping" in line for line in result.summary_lines())


def test_many_rows_agreeing_on_one_label_are_one_mapping_entry(tmp_path):
    result = derive_block_labels(
        _spec(tmp_path),
        [
            row(1, "42 - 42WD - 13:00", "42-9"),
            row(2, "42 - 42WD - 15:00", "42-9"),
            row(3, "9 - 9S - 06:10", "9-8"),
        ],
        [
            trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1"),
            trip("feed-trip-2", "42", 15 * 3600, "feed-block-uuid-1"),
            trip("feed-trip-3", "9", 6 * 3600 + 600, "feed-block-uuid-2"),
        ],
    )
    assert result.mapping == (
        ("feed-block-uuid-1", "42-9", 2),
        ("feed-block-uuid-2", "9-8", 1),
    )


def test_derivation_is_deterministic_regardless_of_input_order(tmp_path):
    spec = _spec(tmp_path)
    rows = [
        row(1, "42 - 42WD - 13:00", "42-9"),
        row(2, "9 - 9S - 06:10", "9-8"),
    ]
    trips = [
        trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1"),
        trip("feed-trip-3", "9", 6 * 3600 + 600, "feed-block-uuid-2"),
    ]
    forwards = derive_block_labels(spec, rows, trips)
    backwards = derive_block_labels(spec, rows, list(reversed(trips)))
    assert forwards.mapping == backwards.mapping
    assert forwards.counts == backwards.counts


# ---------------------------------------------------------------------------
# The mapping file reader
# ---------------------------------------------------------------------------


def test_read_mapping_csv_handles_bom_header_and_blank_lines(tmp_path):
    path = tmp_path / "mapping.csv"
    path.write_bytes(
        b"\xef\xbb\xbfTripName,BlockName\r\n"
        b"42 - 42WD - 13:00,42-9\r\n"
        b"\r\n"
        b'"9 - 9S - 06:10","9-8"\r\n'
    )
    rows, sha256 = read_mapping_csv(path)
    assert [(r.trip_name, r.block_name) for r in rows] == [
        ("42 - 42WD - 13:00", "42-9"),
        ("9 - 9S - 06:10", "9-8"),
    ]
    assert len(sha256) == 64


def test_read_mapping_csv_without_a_header_reads_every_row(tmp_path):
    path = tmp_path / "mapping.csv"
    path.write_text("42 - 42WD - 13:00,42-9\n", encoding="utf-8")
    rows, _ = read_mapping_csv(path)
    assert len(rows) == 1
    assert rows[0].line_no == 1


def test_read_mapping_csv_refuses_a_file_that_is_not_two_columns(tmp_path):
    path = tmp_path / "mapping.csv"
    path.write_text(
        "42 - 42WD - 13:00,42-9\nonly-one-column\na,b,c\n", encoding="utf-8"
    )
    with pytest.raises(MappingFileError) as excinfo:
        read_mapping_csv(path)
    assert "2 bad line(s)" in str(excinfo.value)
    assert "line 2" in str(excinfo.value) and "line 3" in str(excinfo.value)


# ---------------------------------------------------------------------------
# The loader: provenance-bearing upsert, no commit of its own
# ---------------------------------------------------------------------------


class _RecordingCursor:
    def __init__(self, log):
        self.log = log

    def executemany(self, sql, rows):
        self.log.append((sql, list(rows)))

    def close(self):
        pass


class _RecordingConnection:
    def __init__(self):
        self.log = []
        self.committed = False

    def cursor(self):
        return _RecordingCursor(self.log)

    def commit(self):
        self.committed = True


def test_load_block_labels_upserts_with_provenance_and_does_not_commit(
    tmp_path,
):
    result = derive_block_labels(
        _spec(tmp_path),
        [row(1, "42 - 42WD - 13:00", "42-9")],
        [trip("feed-trip-1", "42", 13 * 3600, "feed-block-uuid-1")],
    )
    conn = _RecordingConnection()
    written = load_block_labels(
        conn,
        result,
        source="mapping.csv sha256=abc123",
        derivation="tools/block-labels/derive.py; parse config deadbeef",
        loaded_by="derive.py test",
    )
    assert written == 1
    ((sql, rows),) = conn.log
    assert "ON CONFLICT (block_id) DO UPDATE" in sql
    assert rows == [
        (
            "feed-block-uuid-1",
            "42-9",
            "mapping.csv sha256=abc123",
            "tools/block-labels/derive.py; parse config deadbeef",
            "derive.py test",
        )
    ]
    assert conn.committed is False


def test_load_block_labels_with_an_empty_mapping_writes_nothing(tmp_path):
    result = derive_block_labels(_spec(tmp_path), [], [])
    conn = _RecordingConnection()
    assert (
        load_block_labels(
            conn, result, source="s", derivation="d", loaded_by="t"
        )
        == 0
    )
    assert conn.log == []


# ---------------------------------------------------------------------------
# The service day (2026-08-04). Measured on two real feeds: the base
# (route, start) key is ambiguous for 43.7% of keys on Link Transit's
# published feed and 17.7% of trip names in the partner agency's export,
# because one route and start belongs to different blocks on a weekday and
# a Saturday. Adding direction moves it to 43.3% — nothing. Narrowing to
# the row's own service takes it to 24.3%.
# ---------------------------------------------------------------------------


def _two_service_schedule():
    """Route 42 at 13:00 runs on TWO services, on two different blocks.

    This is the exact shape that makes the base key ambiguous, and the only
    shape where the service day can earn its place.
    """
    return [
        trip("wk-1", "42", 13 * 3600, "block-weekday", service_id="svc-wk"),
        trip("wk-2", "42", 14 * 3600, "block-weekday", service_id="svc-wk"),
        trip("sa-1", "42", 13 * 3600, "block-saturday", service_id="svc-sa"),
        trip("sa-2", "42", 15 * 3600, "block-saturday", service_id="svc-sa"),
    ]


def test_without_a_service_day_the_shared_key_is_still_ambiguous(tmp_path):
    """The behaviour that has to stay intact: a two-column file loses
    nothing and gains nothing."""
    spec = _spec(tmp_path)
    result = derive_block_labels(
        spec, [row(1, "42 - 42WD - 13:00", "42-1")], _two_service_schedule()
    )
    assert result.counts.get(AMBIGUOUS) == 1
    assert result.mapping == ()


def test_a_confidently_paired_service_day_resolves_the_ambiguity(tmp_path):
    spec = _spec(tmp_path)
    rows = [
        row(1, "42 - 42WD - 13:00", "42-1", service_day="Weekday"),
        row(2, "42 - 42WD - 14:00", "42-1", service_day="Weekday"),
    ]
    trips = _two_service_schedule()
    pairings = pair_service_days(spec, rows, trips)

    assert pairings["Weekday"].confident
    assert pairings["Weekday"].service_id == "svc-wk"

    result = derive_block_labels(spec, rows, trips, pairings)
    assert result.counts.get(AMBIGUOUS, 0) == 0
    assert result.counts.get(MATCHED) == 2
    assert result.mapping == (("block-weekday", "42-1", 2),)


def test_the_name_itself_is_never_read(tmp_path):
    """'MUT', 'MUWT', 'F', 'Training' — 46 labels in the partner export, and
    only a couple are guessable. The pairing must work from the trips a
    label covers, so an opaque label pairs exactly as well as a plain one."""
    spec = _spec(tmp_path)
    rows = [
        row(1, "42 - 42WD - 13:00", "42-1", service_day="MUWT"),
        row(2, "42 - 42WD - 14:00", "42-1", service_day="MUWT"),
    ]
    pairings = pair_service_days(spec, rows, _two_service_schedule())
    assert pairings["MUWT"].confident
    assert pairings["MUWT"].service_id == "svc-wk"


def test_two_services_that_explain_a_label_equally_are_refused(tmp_path):
    """Overlapping schedule versions — Link Transit runs two Saturday
    services, one seasonal. A label cannot choose between them and must not
    try: the rows fall back to the unnarrowed key instead."""
    spec = _spec(tmp_path)
    trips = [
        trip("a", "42", 13 * 3600, "block-a", service_id="svc-sat-1"),
        trip("b", "42", 13 * 3600, "block-b", service_id="svc-sat-2"),
    ]
    rows = [row(1, "42 - 42WD - 13:00", "42-1", service_day="Saturday Service")]
    pairing = pair_service_days(spec, rows, trips)["Saturday Service"]

    assert not pairing.confident
    assert pairing.service_id is None
    assert "equally closely" in pairing.reason

    # And the derivation stays exactly as honest as it was before.
    result = derive_block_labels(spec, rows, trips, {"Saturday Service": pairing})
    assert result.counts.get(AMBIGUOUS) == 1
    assert result.mapping == ()


def test_a_label_no_single_service_explains_is_refused(tmp_path):
    """'Training' had 6,330 rows in the partner export and resolved zero
    blocks — a label can correspond to no GTFS service at all."""
    spec = _spec(tmp_path)
    trips = [trip("a", "42", 13 * 3600, "block-a", service_id="svc-wk")]
    rows = [
        row(1, "42 - 42WD - 13:00", "42-1", service_day="Training"),
        row(2, "42 - 42WD - 21:00", "42-2", service_day="Training"),
        row(3, "42 - 42WD - 22:00", "42-3", service_day="Training"),
    ]
    pairing = pair_service_days(spec, rows, trips)["Training"]
    assert not pairing.confident
    assert "no single service explains" in pairing.reason


def test_narrowing_never_turns_a_match_into_an_unmatched_row(tmp_path):
    """THE SAFETY RULE. If the pairing does not describe a row, the
    unnarrowed candidates stand. Precision that loses a correct answer is
    not precision."""
    spec = _spec(tmp_path)
    trips = [trip("only", "42", 13 * 3600, "block-only", service_id="svc-sa")]
    rows = [row(1, "42 - 42WD - 13:00", "42-1", service_day="Weekday")]
    # A pairing that points somewhere this row's candidates do not live.
    bogus = {
        "Weekday": ServiceDayPairing(
            service_day="Weekday", service_id="svc-wk", keys_in_export=1,
            keys_explained=1, coverage=1.0, similarity=1.0,
            runner_up_coverage=0.0, confident=True, reason="fixture",
        )
    }
    result = derive_block_labels(spec, rows, trips, bogus)
    assert result.counts.get(MATCHED) == 1
    assert result.mapping == (("block-only", "42-1", 1),)


def test_the_pairing_states_its_evidence(tmp_path):
    """A narrowing nobody can inspect is a narrowing nobody should trust."""
    spec = _spec(tmp_path)
    rows = [
        row(1, "42 - 42WD - 13:00", "42-1", service_day="Weekday"),
        row(2, "42 - 42WD - 14:00", "42-1", service_day="Weekday"),
    ]
    pairing = pair_service_days(spec, rows, _two_service_schedule())["Weekday"]
    assert pairing.keys_in_export == 2
    assert pairing.coverage == 1.0
    assert pairing.similarity == 1.0
    assert "covers 100%" in pairing.reason
    assert "matches it most closely" in pairing.reason


def test_a_service_that_is_a_subset_of_another_is_still_identified(tmp_path):
    """THE BUG A REAL FEED FOUND. Coverage alone cannot tell a service from a
    SUPERSET of it: on Link Transit every one of Sunday's 404 (route, start)
    keys also appears in the Saturday service's 470, so both "cover" the
    Sunday label 100% and a coverage contest ties. The pairing was refused
    for a label whose service was obvious.

    Similarity breaks the tie honestly by also penalising a service for the
    trips the label does NOT name.
    """
    spec = _spec(tmp_path)
    # Sunday: one trip. Saturday: that same trip plus two more.
    trips = [
        trip("sun", "42", 13 * 3600, "block-sun", service_id="svc-sun"),
        trip("sat-a", "42", 13 * 3600, "block-sat", service_id="svc-sat"),
        trip("sat-b", "42", 16 * 3600, "block-sat", service_id="svc-sat"),
        trip("sat-c", "42", 17 * 3600, "block-sat", service_id="svc-sat"),
    ]
    rows = [row(1, "42 - 42WD - 13:00", "42-1", service_day="Sunday Service")]
    pairing = pair_service_days(spec, rows, trips)["Sunday Service"]

    # Both services cover the label completely — that is the trap.
    assert pairing.coverage == 1.0
    # Similarity does not tie: 1/1 against 1/3.
    assert pairing.confident
    assert pairing.service_id == "svc-sun"

    result = derive_block_labels(spec, rows, trips, {"Sunday Service": pairing})
    assert result.mapping == (("block-sun", "42-1", 1),)


def test_naming_the_schedule_period_resolves_a_label_two_signups_share(
    tmp_path,
):
    """STEP 2. A feed carries every signup at once. Link Transit publishes two
    Saturday services — one running Jul 11-Aug 29, one from Sep 5 — and a
    label saying "Saturday Service" cannot choose between them, so step 1
    correctly refuses it and narrows nothing.

    Naming the period the export describes removes the other signup from the
    contest. The label then pairs, and the rows it covers stop being
    ambiguous.
    """
    spec = _spec(tmp_path)
    trips = [
        # Summer Saturday signup.
        trip("sum-1", "42", 13 * 3600, "block-summer", service_id="sat-summer"),
        # Autumn Saturday signup: same route, same start, different block.
        trip("aut-1", "42", 13 * 3600, "block-autumn", service_id="sat-autumn"),
    ]
    rows = [row(1, "42 - 42WD - 13:00", "42-1", service_day="Saturday Service")]

    # Without a period: two services explain the label equally — refused.
    unscoped = pair_service_days(spec, rows, trips)["Saturday Service"]
    assert not unscoped.confident
    assert derive_block_labels(
        spec, rows, trips, {"Saturday Service": unscoped}
    ).mapping == ()

    # Declaring the summer signup leaves exactly one candidate.
    scoped = pair_service_days(
        spec, rows, trips, active_service_ids={"sat-summer"}
    )["Saturday Service"]
    assert scoped.confident
    assert scoped.service_id == "sat-summer"
    assert derive_block_labels(
        spec, rows, trips, {"Saturday Service": scoped}
    ).mapping == (("block-summer", "42-1", 1),)


def test_a_wrong_schedule_period_cannot_strand_a_row(tmp_path):
    """THE SAFETY RULE, EXTENDED TO STEP 2. Scoping applies to the PAIRING,
    never to the candidate trips. So a date naming a signup this export does
    not describe can only fail to improve things — it can never turn a row
    that matches today into an unmatched one."""
    spec = _spec(tmp_path)
    trips = [trip("only", "42", 13 * 3600, "block-only", service_id="summer")]
    rows = [row(1, "42 - 42WD - 13:00", "42-1", service_day="Saturday Service")]

    pairings = pair_service_days(
        spec, rows, trips, active_service_ids={"a-different-signup"}
    )
    result = derive_block_labels(spec, rows, trips, pairings)
    assert result.counts.get(MATCHED) == 1
    assert result.counts.get(UNMATCHED, 0) == 0
    assert result.mapping == (("block-only", "42-1", 1),)
