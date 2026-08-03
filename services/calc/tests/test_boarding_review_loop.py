"""upt_v0 0.4.0 — the human-in-the-loop revenue review, closed (handoff 0040).

0.3.0 could hold an ambiguous no-run boarding pending FOREVER: nothing could
answer it, so the figure could never be completed. These tests cover the loop
that closes it — the calculation hands undecided boardings over as review
items, a person answers one in dq.boarding_revenue_reviews, and the NEXT run
reads that answer back and carries the person's reasoning into the figure's
receipt.

The rules pinned here are the ones an FTA reviewer would ask about:

- a decision changes the figure only on a re-run, and only in the direction
  the human said;
- a human-counted boarding is added AFTER the p. 146 factor-up, never
  multiplied by it — the factor is about missing TRIPS, and a no-run boarding
  is not a trip;
- the missing-trip factor itself is byte-identical with and without human
  decisions (the double-count guard, still structural);
- the justification, the author and the timestamp reach the detail VERBATIM;
- a run with no decisions is byte-for-byte 0.3.0, and 0.3.0 stays runnable.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from headway_calc.boarding_reviews import (
    load_boarding_reviews,
    persist_review_items,
)
from headway_calc.revenue_window import RevenueWindow
from headway_calc.types import (
    BoardingReviewItem,
    HumanBoardingVerdict,
    PassengerEvent,
)
from headway_calc.upt import (
    BOARDING_EVENT_TYPE,
    compute_upt,
    compute_upt_v0_3_0,
)

SERVICE_DATE = date(2026, 6, 15)
FIRST_DEP = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
LAST_ARR = datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc)
WINDOW = {SERVICE_DATE: RevenueWindow(SERVICE_DATE, FIRST_DEP, LAST_ARR)}
MIDDAY = datetime(2026, 6, 15, 15, 10, tzinfo=timezone.utc)
DAWN = datetime(2026, 6, 15, 5, 30, tzinfo=timezone.utc)


def boarding(
    pid: str,
    *,
    when: datetime,
    trip_id: str | None,
    count: int | None = 1,
    classification: str | None = None,
) -> PassengerEvent:
    return PassengerEvent(
        event_timestamp=when,
        service_date=SERVICE_DATE,
        passenger_event_id=pid,
        vehicle_id="3684",
        trip_id=trip_id,
        trip_stop_sequence=None if trip_id is None else 1,
        event_type=BOARDING_EVENT_TYPE,
        event_count=count,
        source="tides",
        source_record_id=f"rec-{pid}",
        revenue_classification=classification,
    )


def verdict(
    pid: str, ruling: str, *, note: str = "Confirmed with dispatch."
) -> HumanBoardingVerdict:
    return HumanBoardingVerdict(
        passenger_event_id=pid,
        verdict=ruling,
        justification=note,
        classified_by="stella",
        classified_at=datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Handing undecided boardings over
# ---------------------------------------------------------------------------

def test_pending_boardings_are_emitted_as_review_items() -> None:
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1"),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    result = compute_upt(events, ["t1"], revenue_windows=WINDOW)
    (item,) = result.review_items
    assert item.passenger_event_id == "ghost"
    assert item.source_record_id == "rec-ghost"
    assert item.vehicle_id == "3684"
    assert item.event_count == 4
    assert item.service_date == SERVICE_DATE
    # The calculation states its own position rather than nudging a reviewer.
    assert item.suggested_verdict == "pending_review"
    assert "catch-up bus" in item.suggested_reason


def test_auto_excluded_boardings_are_never_queued_for_a_human() -> None:
    """Prep boardings are DECIDED, on the schedule's evidence. Putting them in
    a queue would be asking a person to re-do work the manual already
    settles."""
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1"),
        boarding("prep", when=DAWN, trip_id=None, count=2,
                 classification="unassigned"),
    ]
    result = compute_upt(events, ["t1"], revenue_windows=WINDOW)
    assert result.review_items == ()
    assert result.detail.excluded_non_revenue_boardings == 2


def test_a_run_with_nothing_ambiguous_hands_over_nothing() -> None:
    result = compute_upt(
        [boarding("assigned", when=MIDDAY, trip_id="t1")],
        ["t1"],
        revenue_windows=WINDOW,
    )
    assert result.review_items == ()


# ---------------------------------------------------------------------------
# Reading the decision back
# ---------------------------------------------------------------------------

def test_human_revenue_verdict_counts_the_boarding_on_the_next_run() -> None:
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    held = compute_upt(events, ["t1"], revenue_windows=WINDOW)
    assert held.value == Decimal("10")
    assert held.detail.pending_review_boardings == 4

    decided = compute_upt(
        events,
        ["t1"],
        revenue_windows=WINDOW,
        boarding_reviews={
            "ghost": verdict(
                "ghost",
                "revenue",
                note=(
                    "Extra bus sent at 15:10 to recover the route; dispatch "
                    "confirms these are real riders."
                ),
            )
        },
    )
    assert decided.value == Decimal("14")
    assert decided.detail.pending_review_boardings == 0
    assert decided.detail.human_revenue_boardings == 4
    assert decided.review_items == ()
    # It is in the figure, so its raw record is in the figure's lineage.
    assert "rec-ghost" in decided.input_record_ids


def test_human_non_revenue_verdict_excludes_the_boarding() -> None:
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    decided = compute_upt(
        events,
        ["t1"],
        revenue_windows=WINDOW,
        boarding_reviews={
            "ghost": verdict(
                "ghost",
                "non_revenue",
                note="Counter double-fired during layover.",
            )
        },
    )
    assert decided.value == Decimal("10")
    assert decided.detail.human_non_revenue_boardings == 4
    assert decided.detail.pending_review_boardings == 0
    # Excluded boardings are cited by their finding, never by lineage.
    assert "rec-ghost" not in decided.input_record_ids


def test_a_decision_about_another_boarding_does_not_release_this_one() -> None:
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    decided = compute_upt(
        events,
        ["t1"],
        revenue_windows=WINDOW,
        boarding_reviews={"some-other-event": verdict("some-other-event",
                                                      "revenue")},
    )
    assert decided.detail.pending_review_boardings == 4
    assert decided.value == Decimal("10")


def test_a_decision_cannot_reopen_an_auto_excluded_prep_boarding() -> None:
    """The queue is the only door. A verdict keyed to a boarding the schedule
    already settled changes nothing — otherwise a stale review row could
    silently re-count prep activity."""
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("prep", when=DAWN, trip_id=None, count=2,
                 classification="unassigned"),
    ]
    decided = compute_upt(
        events,
        ["t1"],
        revenue_windows=WINDOW,
        boarding_reviews={"prep": verdict("prep", "revenue")},
    )
    assert decided.value == Decimal("10")
    assert decided.detail.excluded_non_revenue_boardings == 2
    assert decided.detail.human_revenue_boardings == 0


# ---------------------------------------------------------------------------
# The receipt
# ---------------------------------------------------------------------------

def test_the_justification_reaches_the_detail_verbatim() -> None:
    note = (
        "Unit's counter double-fired during layover at Elm & 3rd; confirmed "
        "with dispatch 2026-07-16."
    )
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    result = compute_upt(
        events,
        ["t1"],
        revenue_windows=WINDOW,
        boarding_reviews={"ghost": verdict("ghost", "non_revenue", note=note)},
    )
    detail = result.detail.to_dict()["revenue_classification"]
    (entry,) = detail["human_classifications"]
    assert entry["justification"] == note  # verbatim, never summarised
    assert entry["classified_by"] == "stella"
    assert entry["classified_at"] == "2026-07-16T10:00:00+00:00"
    assert entry["verdict"] == "non_revenue"
    assert entry["passenger_event_id"] == "ghost"
    assert entry["vehicle_id"] == "3684"
    assert entry["event_count"] == 4
    assert detail["human_non_revenue_boardings"] == 4


def test_the_decision_is_also_an_info_finding_in_the_dq_trail() -> None:
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    result = compute_upt(
        events,
        ["t1"],
        revenue_windows=WINDOW,
        boarding_reviews={
            "ghost": verdict("ghost", "revenue", note="Real riders.")
        },
    )
    (info,) = [
        f for f in result.infos
        if f.issue_type == "boarding_classified_by_review"
    ]
    assert info.severity == "info"  # decided, not outstanding
    assert "stella" in info.title
    assert "Real riders." in info.description
    assert info.source_record_ids == ("rec-ghost",)
    # ...and the boarding is no longer in the pending warning stream.
    assert not [
        f for f in result.warnings
        if f.issue_type == "boarding_pending_revenue_review"
    ]


# ---------------------------------------------------------------------------
# The arithmetic guards
# ---------------------------------------------------------------------------

def test_human_boardings_are_added_after_the_factor_up_not_multiplied() -> None:
    """The p. 146 factor accounts for TRIPS with missing data. A no-run
    boarding is not a trip and was never in the denominator, so scaling a
    human-confirmed head count by the factor would invent riders."""
    # 50 operated trips, 49 of them carrying events: missing share 1/50 =
    # 0.02, exactly the p. 146 line, so the factor-up applies at 50/49.
    operated = [f"t{i}" for i in range(1, 51)]
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=100),
        boarding("ghost", when=MIDDAY, trip_id=None, count=100,
                 classification="unassigned"),
    ]
    events += [
        boarding(f"e{i}", when=MIDDAY, trip_id=f"t{i}", count=0)
        for i in range(2, 50)
    ]
    result = compute_upt(
        events,
        operated,
        revenue_windows=WINDOW,
        boarding_reviews={"ghost": verdict("ghost", "revenue")},
    )
    assert result.detail.total_boardings_counted == 100
    assert result.detail.human_revenue_boardings == 100
    assert result.detail.factor_applied == Decimal("1.020408")
    # Correct: 100 × 50/49 = 102.04… → 102 whole boardings, THEN + 100 the
    # human confirmed = 202. Multiplying instead would give
    # (100 + 100) × 50/49 = 204.08… → 204: two riders nobody ever observed.
    assert result.value == Decimal("202")


def test_human_decisions_do_not_move_the_missing_trip_factor() -> None:
    """The double-count guard, still structural: a no-run boarding has no
    trip, so it enters neither the counted base nor the operated/missing
    denominators — decided or not."""
    base = [boarding("assigned", when=MIDDAY, trip_id="t1", count=10)]
    ghosts = [
        boarding("g1", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
        boarding("g2", when=MIDDAY, trip_id=None, count=3,
                 classification="unassigned"),
    ]
    without = compute_upt(base, ["t1", "t2"], revenue_windows=WINDOW)
    with_decided = compute_upt(
        base + ghosts,
        ["t1", "t2"],
        revenue_windows=WINDOW,
        boarding_reviews={
            "g1": verdict("g1", "revenue"),
            "g2": verdict("g2", "non_revenue"),
        },
    )
    for field in (
        "operated_trips",
        "trips_with_events",
        "missing_trips",
        "missing_share",
        "factor_applied",
    ):
        assert getattr(without.detail, field) == getattr(
            with_decided.detail, field
        ), field


def test_a_human_decision_does_not_cure_a_p146_refusal() -> None:
    """A blocked run stays blocked. Classifying a boarding is not a
    statistician's approval of a factoring method."""
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    result = compute_upt(
        events,
        [f"t{i}" for i in range(1, 11)],  # 9 of 10 missing — way over 2%
        revenue_windows=WINDOW,
        boarding_reviews={"ghost": verdict("ghost", "revenue")},
    )
    assert result.value is None
    assert [f.issue_type for f in result.blocking_issues] == [
        "apc_missing_trips_above_fta_threshold"
    ]
    # The decision is still recorded — the evidence travels on a blocked run.
    assert result.detail.human_revenue_boardings == 4


# ---------------------------------------------------------------------------
# Retention: 0.3.0 stays reproducible
# ---------------------------------------------------------------------------

def test_no_decisions_is_byte_for_byte_0_3_0() -> None:
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    current = compute_upt(events, ["t1"], revenue_windows=WINDOW)
    retained = compute_upt_v0_3_0(events, ["t1"], revenue_windows=WINDOW)
    assert current.value == retained.value
    assert current.detail.to_dict() == retained.detail.to_dict()
    assert "human_classifications" not in current.detail.to_dict()[
        "revenue_classification"
    ]
    assert current.calc_version == "0.5.0"
    assert retained.calc_version == "0.3.0"


def test_retained_0_3_0_ignores_recorded_decisions_entirely() -> None:
    """A figure certified under 0.3.0 must recompute identically no matter
    what has been decided since."""
    events = [
        boarding("assigned", when=MIDDAY, trip_id="t1", count=10),
        boarding("ghost", when=MIDDAY, trip_id=None, count=4,
                 classification="unassigned"),
    ]
    retained = compute_upt_v0_3_0(events, ["t1"], revenue_windows=WINDOW)
    assert retained.value == Decimal("10")
    assert retained.detail.pending_review_boardings == 4
    assert retained.detail.human_revenue_boardings == 0


# ---------------------------------------------------------------------------
# The queue's two database ends
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.rows: list = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        q = " ".join(sql.split())
        self.conn.executed.append((q, params))
        if q.startswith("SELECT 1 FROM information_schema.tables"):
            self.rows = [(1,)] if self.conn.table_exists else []
        elif q.startswith("INSERT INTO dq.boarding_revenue_reviews"):
            pid = params[0]
            if pid in self.conn.decided:
                self.rowcount = 0  # the UPSERT's WHERE refused it
            else:
                self.conn.queued[pid] = params
                self.rowcount = 1
            self.rows = []
        elif q.startswith("SELECT passenger_event_id, verdict"):
            self.rows = list(self.conn.decided_rows)
        else:  # pragma: no cover - the fake knows only this module's SQL
            raise AssertionError(f"unexpected SQL: {q}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


class FakeConn:
    def __init__(self, *, table_exists=True, decided=(), decided_rows=()):
        self.table_exists = table_exists
        self.decided = set(decided)
        self.decided_rows = list(decided_rows)
        self.queued: dict = {}
        self.executed: list = []

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.executed.append(("rollback", None))


ITEM = BoardingReviewItem(
    passenger_event_id="ghost",
    source_record_id="rec-ghost",
    service_date=SERVICE_DATE,
    event_timestamp=MIDDAY,
    vehicle_id="3684",
    event_count=4,
    suggested_verdict="pending_review",
    suggested_reason="ambiguous mid-service no-run boarding",
)


def test_persist_writes_one_queue_row_per_undecided_boarding() -> None:
    conn = FakeConn()
    written = persist_review_items(
        conn,
        [ITEM],
        calc_name="upt_v0",
        calc_version="0.4.0",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 7, 1),
    )
    assert written == 1
    assert conn.queued["ghost"][:6] == (
        "ghost", "rec-ghost", SERVICE_DATE, MIDDAY, "3684", 4,
    )


def test_persist_never_overwrites_a_decision_a_human_already_made() -> None:
    conn = FakeConn(decided={"ghost"})
    assert (
        persist_review_items(
            conn,
            [ITEM],
            calc_name="upt_v0",
            calc_version="0.4.0",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 7, 1),
        )
        == 0
    )
    assert "ghost" not in conn.queued


def test_persist_on_a_pre_migration_database_warns_and_does_not_crash(caplog):
    conn = FakeConn(table_exists=False)
    with caplog.at_level("WARNING"):
        assert (
            persist_review_items(
                conn,
                [ITEM],
                calc_name="upt_v0",
                calc_version="0.4.0",
                period_start=date(2026, 6, 1),
                period_end=date(2026, 7, 1),
            )
            == 0
        )
    assert "dq.boarding_revenue_reviews does not exist" in caplog.text
    assert "still held OUT of the figure" in caplog.text


def test_persist_of_nothing_touches_the_database_not_at_all() -> None:
    conn = FakeConn()
    assert (
        persist_review_items(
            conn,
            [],
            calc_name="upt_v0",
            calc_version="0.4.0",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 7, 1),
        )
        == 0
    )
    assert conn.executed == []


def test_load_returns_decisions_keyed_by_boarding() -> None:
    conn = FakeConn(
        decided_rows=[
            (
                "ghost",
                "revenue",
                "Extra bus, confirmed with dispatch.",
                "stella",
                datetime(2026, 7, 16, 10, 0, tzinfo=timezone.utc),
            )
        ]
    )
    loaded = load_boarding_reviews(conn, date(2026, 6, 1), date(2026, 7, 1))
    assert loaded["ghost"].verdict == "revenue"
    assert loaded["ghost"].justification == "Extra bus, confirmed with dispatch."
    assert loaded["ghost"].classified_by == "stella"
