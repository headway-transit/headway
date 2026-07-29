"""Findings in the agency's vocabulary — headway_calc.subjects (handoff 0029).

The rule under test, stated once: a finding is addressed to a person who has
to go fix something, so it must name the thing in the vocabulary that person
uses to find it — and it must never invent a name it does not have.

Covers the structured subject on Finding (the calc stays pure: it emits ids,
never labels), the persistence-time resolution into blocks/routes/times, the
two cases that decide whether the mechanism is honest — a trip with NO label
and a trip with NO row in canonical.trips — the stated caps, determinism,
and the additive/graceful behaviour that keeps a pre-migration database (and
every finding that has no subject) working exactly as before.

No live database: the recording fake connection serves the label rows.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest
from conftest import RecordingConnection

from headway_calc.dq import route_findings
from headway_calc.subjects import (
    CONTEXT_VERSION,
    GROUP_CAP,
    TRIP_IDS_PER_GROUP_CAP,
    _clock,
    resolve_contexts,
    resolver_kinds,
)
from headway_calc.types import SUBJECT_KINDS, SUBJECT_TRIPS, Finding, SubjectRef
from headway_calc.upt import compute_upt

PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 7, 1)


def label_row(
    trip_id,
    block_id=None,
    route_id=None,
    short_name=None,
    long_name=None,
    first_s=None,
    last_s=None,
):
    """One canonical.trips × routes × stop_times label row, the reader's
    column order. Every label defaults to ABSENT — the point of the module
    is that absence is representable."""
    return (trip_id, block_id, route_id, short_name, long_name, first_s, last_s)


def finding_with(ids, issue_type="apc_missing_trips_above_fta_threshold"):
    return Finding(
        issue_type=issue_type,
        title="t",
        description="d",
        severity="blocking",
        subject=SubjectRef(kind=SUBJECT_TRIPS, ids=tuple(ids)),
    )


# --- the vocabulary is closed, and closed against its resolvers -------------


def test_declared_kinds_and_implemented_resolvers_cannot_drift():
    """A kind without a resolver would produce a finding nobody can label —
    exactly the failure this mechanism exists to prevent."""
    assert tuple(sorted(SUBJECT_KINDS)) == resolver_kinds()


def test_unknown_subject_kind_is_refused_at_construction():
    with pytest.raises(ValueError, match="SubjectRef.kind must be one of"):
        SubjectRef(kind="canonical.unicorns", ids=("a",))


def test_subject_total_is_the_full_count_never_a_truncated_one():
    subject = SubjectRef(kind=SUBJECT_TRIPS, ids=tuple(f"t{i}" for i in range(500)))
    assert subject.total == 500


# --- a finding without a subject stays exactly as it was --------------------


def test_findings_without_subjects_issue_no_query_at_all():
    """Every pre-0029 call site must behave byte-for-byte as before."""
    conn = RecordingConnection()
    findings = [
        Finding(issue_type="coverage_below_threshold", title="t", description="d")
    ]
    assert resolve_contexts(conn, findings) == [None]
    assert conn.executed == []


def test_route_findings_without_subjects_writes_the_pre_0029_seven_columns():
    conn = RecordingConnection()
    route_findings(
        conn,
        [Finding(issue_type="coverage_below_threshold", title="t", description="d")],
        "vrm_v0",
        "0.2.0",
        PERIOD_START,
        PERIOD_END,
    )
    inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert len(inserts) == 1
    sql, params = inserts[0]
    assert "subject_context" not in sql
    assert len(params) == 7


# --- grouping is the feature ------------------------------------------------


def test_trips_are_grouped_by_block_with_route_and_time_span():
    """The dispatcher's sentence: '18 trips, Route 42, 06:14-14:22'."""
    conn = RecordingConnection(
        trip_label_rows=[
            label_row("t1", "225-4", "42", "42", "Dayton Transfer", 22440, 30000),
            label_row("t2", "225-4", "42", "42", "Dayton Transfer", 30600, 51720),
            label_row("t3", "68-2", "9", "9", "Riverside", 18000, 21600),
        ]
    )
    (context,) = resolve_contexts(conn, [finding_with(["t1", "t2", "t3"])])

    assert context["version"] == CONTEXT_VERSION
    assert context["kind"] == SUBJECT_TRIPS
    assert context["total"] == 3
    assert context["grouped_by"] == "block"
    assert context["group_count"] == 2
    # Chronological: the dispatcher's day runs forwards.
    assert [g["block_id"] for g in context["groups"]] == ["68-2", "225-4"]

    block = context["groups"][1]
    assert block["trip_count"] == 2
    assert block["first_departure"] == "06:14"
    assert block["last_departure"] == "14:22"
    assert block["route_count"] == 1
    assert block["routes"] == [
        {"route_id": "42", "short_name": "42", "long_name": "Dayton Transfer"}
    ]
    # The ids remain — the footnote, not the headline.
    assert block["trip_ids"] == ["t1", "t2"]
    assert "unmatched" not in context


def test_one_block_running_several_routes_names_them_all():
    conn = RecordingConnection(
        trip_label_rows=[
            label_row("t1", "B1", "42", "42", None, 3600, 7200),
            label_row("t2", "B1", "9", "9", None, 7500, 9000),
        ]
    )
    (context,) = resolve_contexts(conn, [finding_with(["t1", "t2"])])
    (group,) = context["groups"]
    assert group["route_count"] == 2
    assert [r["short_name"] for r in group["routes"]] == ["42", "9"]


def test_one_query_serves_a_whole_batch_of_findings():
    """66,286 findings in one live VRH run: a query per finding would make
    routing slower than the calculation that produced them."""
    conn = RecordingConnection(
        trip_label_rows=[
            label_row("t1", "B1", "42", "42", None, 3600, 7200),
            label_row("t2", "B2", "9", "9", None, 3600, 7200),
        ]
    )
    contexts = resolve_contexts(
        conn, [finding_with(["t1"]), finding_with(["t2"]), finding_with(["t1", "t2"])]
    )
    assert len(contexts) == 3
    assert [c["total"] for c in contexts] == [1, 1, 2]
    assert len(conn.statements_matching("t.block_id")) == 1


# --- NO LABEL IS EVER INVENTED ---------------------------------------------


def test_trip_with_no_block_no_route_name_and_no_schedule_shows_nothing():
    """Absent data renders as absent — never a guess, never a placeholder."""
    conn = RecordingConnection(trip_label_rows=[label_row("t1")])
    (context,) = resolve_contexts(conn, [finding_with(["t1"])])
    (group,) = context["groups"]
    assert group["block_id"] is None
    assert group["routes"] == []
    assert group["route_count"] == 0
    assert group["first_departure"] is None
    assert group["last_departure"] is None
    assert group["trip_count"] == 1
    assert "unmatched" not in context


def test_route_without_a_short_name_keeps_the_id_and_invents_no_name():
    conn = RecordingConnection(
        trip_label_rows=[label_row("t1", "B1", "route-uuid-1", None, None, 3600, 7200)]
    )
    (context,) = resolve_contexts(conn, [finding_with(["t1"])])
    (route,) = context["groups"][0]["routes"]
    assert route == {
        "route_id": "route-uuid-1",
        "short_name": None,
        "long_name": None,
    }


def test_group_with_only_some_scheduled_times_spans_only_what_it_knows():
    conn = RecordingConnection(
        trip_label_rows=[
            label_row("t1", "B1", "42", "42", None, None, None),
            label_row("t2", "B1", "42", "42", None, 22440, 30000),
        ]
    )
    (context,) = resolve_contexts(conn, [finding_with(["t1", "t2"])])
    (group,) = context["groups"]
    assert group["trip_count"] == 2
    assert group["first_departure"] == "06:14"
    assert group["last_departure"] == "08:20"


def test_trip_with_no_row_in_canonical_trips_is_reported_as_unmatched():
    """A trip Headway saw operating but that is not in the schedule feed.
    It gets its own honest bucket — never folded into a block it does not
    belong to, and never dropped."""
    conn = RecordingConnection(
        trip_label_rows=[label_row("t1", "B1", "42", "42", None, 3600, 7200)]
    )
    (context,) = resolve_contexts(conn, [finding_with(["t1", "ghost-1", "ghost-2"])])
    assert context["total"] == 3
    assert context["group_count"] == 1
    assert context["unmatched"] == {
        "trip_count": 2,
        "trip_ids": ["ghost-1", "ghost-2"],
    }


def test_every_trip_unmatched_still_produces_an_honest_context():
    conn = RecordingConnection(trip_label_rows=[])
    (context,) = resolve_contexts(conn, [finding_with(["a", "b"])])
    assert context["group_count"] == 0
    assert context["groups"] == []
    assert context["unmatched"]["trip_count"] == 2


# --- caps are stated, never silent ------------------------------------------


def test_group_cap_truncates_the_list_but_never_the_stated_total():
    rows = [
        label_row(f"t{i}", f"B{i:03d}", "42", "42", None, 3600 + i, 7200 + i)
        for i in range(GROUP_CAP + 12)
    ]
    conn = RecordingConnection(trip_label_rows=rows)
    (context,) = resolve_contexts(
        conn, [finding_with([r[0] for r in rows])]
    )
    assert context["group_count"] == GROUP_CAP + 12
    assert context["group_cap"] == GROUP_CAP
    assert len(context["groups"]) == GROUP_CAP


def test_trip_id_cap_truncates_the_sample_but_never_the_trip_count():
    n = TRIP_IDS_PER_GROUP_CAP + 7
    rows = [label_row(f"t{i:03d}", "B1", "42", "42", None, 3600, 7200) for i in range(n)]
    conn = RecordingConnection(trip_label_rows=rows)
    (context,) = resolve_contexts(conn, [finding_with([r[0] for r in rows])])
    (group,) = context["groups"]
    assert group["trip_count"] == n
    assert len(group["trip_ids"]) == TRIP_IDS_PER_GROUP_CAP
    assert context["trip_id_cap"] == TRIP_IDS_PER_GROUP_CAP


# --- clock conversion -------------------------------------------------------


def test_clock_renders_gtfs_service_day_seconds():
    assert _clock(0) == "00:00"
    assert _clock(22440) == "06:14"
    assert _clock(51720) == "14:22"


def test_clock_preserves_the_after_midnight_convention_instead_of_wrapping():
    """GTFS counts from noon-minus-12h of the SERVICE day. Wrapping 25:10 to
    01:10 would silently move the trip to the wrong day."""
    assert _clock(90600) == "25:10"


def test_clock_of_an_absent_or_impossible_time_is_absent():
    assert _clock(None) is None
    assert _clock(-60) is None


# --- determinism ------------------------------------------------------------


def test_the_same_finding_always_resolves_to_the_same_json():
    rows = [
        label_row("t2", "B1", "42", "42", None, 3600, 7200),
        label_row("t1", "B2", "9", "9", None, 7300, 9000),
        label_row("t3", "B1", "9", "9", None, 3700, 7300),
    ]
    first = resolve_contexts(
        RecordingConnection(trip_label_rows=rows), [finding_with(["t1", "t2", "t3"])]
    )[0]
    second = resolve_contexts(
        RecordingConnection(trip_label_rows=list(reversed(rows))),
        [finding_with(["t1", "t2", "t3"])],
    )[0]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# --- routing writes it, frozen ----------------------------------------------


def test_route_findings_freezes_the_resolved_context_on_the_row():
    conn = RecordingConnection(
        trip_label_rows=[label_row("t1", "225-4", "42", "42", None, 22440, 51720)]
    )
    route_findings(
        conn, [finding_with(["t1"])], "upt_v0", "0.2.0", PERIOD_START, PERIOD_END
    )
    (sql, params) = conn.statements_matching("INSERT INTO dq.issues")[0]
    assert "subject_context" in sql and "%s::jsonb" in sql
    stored = json.loads(params[7])
    assert stored["groups"][0]["block_id"] == "225-4"
    assert stored["groups"][0]["first_departure"] == "06:14"
    # The ids survive alongside the labels, so any reader can re-derive.
    assert stored["groups"][0]["trip_ids"] == ["t1"]


def test_a_subjectless_finding_in_a_mixed_batch_stores_null_not_an_empty_blob():
    """A finding about the run as a whole has nothing to point at. It must
    store NULL — indistinguishable from a pre-0035 row — not an empty
    structure that would render as a mysteriously blank panel."""
    conn = RecordingConnection(
        trip_label_rows=[label_row("t1", "B1", "42", "42", None, 3600, 7200)]
    )
    route_findings(
        conn,
        [
            Finding(
                issue_type="coverage_below_threshold", title="t", description="d"
            ),
            finding_with(["t1"]),
        ],
        "vrh_v0",
        "0.4.0",
        PERIOD_START,
        PERIOD_END,
    )
    inserts = conn.statements_matching("INSERT INTO dq.issues")
    assert inserts[0][1][7] is None
    assert inserts[1][1][7] is not None


def test_a_pre_0035_database_still_records_every_finding():
    """The migration is additive in BOTH directions: a display feature must
    never be the reason a data-quality finding fails to land."""
    conn = RecordingConnection(
        trip_label_rows=[label_row("t1", "B1", "42", "42", None, 3600, 7200)],
        subject_context_column_missing=True,
    )
    issue_ids = route_findings(
        conn, [finding_with(["t1"])], "upt_v0", "0.2.0", PERIOD_START, PERIOD_END
    )
    assert issue_ids == ["issue-0001"]
    (sql, params) = conn.statements_matching("INSERT INTO dq.issues")[0]
    assert "subject_context" not in sql
    assert len(params) == 7


# --- the UAT finding itself -------------------------------------------------


def test_the_all_affected_finding_leads_with_every_trip_not_an_enumeration():
    """1,111 of 1,111 is a different sentence from 3%: it points at the feed,
    not at the trips."""
    operated = [f"trip-{i}" for i in range(1111)]
    result = compute_upt([], operated)
    (blocking,) = result.blocking_issues
    assert "Every operated trip in this period is affected" in blocking.description
    assert "all 1,111" in blocking.description
    assert "no passenger-count data reached Headway" in blocking.description
    # Not an enumeration — and not a truncated one either.
    assert "trip-0" not in blocking.description
    assert blocking.subject.total == 1111
    # The regulatory sentence and its page cite survive VERBATIM.
    assert "2026 NTD Policy Manual p. 146" in blocking.description
    assert (
        "if the vehicle trips with missing data exceed 2 percent of total "
        "trips, agencies must have a qualified statistician approve the "
        "factoring method used to account for the missing percentage"
    ) in blocking.description


def test_the_partial_finding_says_the_share_the_way_a_person_reads_it():
    from test_upt import make_event  # noqa: PLC0415 — the upt event builder

    operated = [f"trip-{i}" for i in range(100)]
    events = [
        make_event(f"e{i}", minute=i, trip_id=f"trip-{i}", count=1)
        for i in range(95)
    ]
    result = compute_upt(events, operated)
    (blocking,) = result.blocking_issues
    assert "5.00%" in blocking.description
    assert "share 0.0500" in blocking.description
    assert result.detail.missing_share == Decimal("0.0500")
    assert blocking.subject.total == 5
