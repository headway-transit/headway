"""upt_v0 0.3.0 — revenue classification of no-run boardings (handoff 0040).

Covers: the no-run ('unassigned') boarding split (revenue / excluded-non-
revenue / pending-review) driven by the schedule-derived revenue window; the
CRITICAL missing-trip-factor double-count guard (excluded/pending boardings
never touch the p. 146 denominators); the exclude-until-classified pending
default and its info roll-up; the byte-for-byte 0.2.0 retention for a feed
that sets no classification; and the window classifier's exact boundaries.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from headway_calc.revenue_window import (
    INSIDE_WINDOW,
    NO_WINDOW,
    OUTSIDE_WINDOW,
    RevenueWindow,
    build_windows,
)
from headway_calc.types import PassengerEvent
from headway_calc.upt import (
    BOARDING_EVENT_TYPE,
    compute_upt,
    compute_upt_v0_1_0,
    compute_upt_v0_2_0,
)

SERVICE_DATE = date(2026, 6, 15)
#: A revenue window 08:00–20:00 UTC for the service date.
FIRST_DEP = datetime(2026, 6, 15, 8, 0, tzinfo=timezone.utc)
LAST_ARR = datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc)
WINDOW = {SERVICE_DATE: RevenueWindow(SERVICE_DATE, FIRST_DEP, LAST_ARR)}


def boarding(
    pid: str,
    *,
    when: datetime,
    trip_id: str | None,
    count: int | None = 1,
    classification: str | None = None,
    event_type: str = BOARDING_EVENT_TYPE,
    seq: int | None = 1,
) -> PassengerEvent:
    return PassengerEvent(
        event_timestamp=when,
        service_date=SERVICE_DATE,
        passenger_event_id=pid,
        vehicle_id="veh-1",
        trip_id=trip_id,
        trip_stop_sequence=None if trip_id is None else seq,
        event_type=event_type,
        event_count=count,
        source="tides",
        source_record_id=f"rec-{pid}",
        revenue_classification=classification,
    )


# ---------------------------------------------------------------------------
# The window classifier
# ---------------------------------------------------------------------------

def test_window_classify_boundaries() -> None:
    w = RevenueWindow(SERVICE_DATE, FIRST_DEP, LAST_ARR)
    # strictly before first departure / after last arrival -> outside
    assert w.classify(FIRST_DEP - timedelta(seconds=1)) == OUTSIDE_WINDOW
    assert w.classify(LAST_ARR + timedelta(seconds=1)) == OUTSIDE_WINDOW
    # the bounds themselves are inside (a boarding at the first departure is
    # in service)
    assert w.classify(FIRST_DEP) == INSIDE_WINDOW
    assert w.classify(LAST_ARR) == INSIDE_WINDOW
    assert w.classify(datetime(2026, 6, 15, 12, tzinfo=timezone.utc)) == INSIDE_WINDOW


def test_window_absent_is_no_window() -> None:
    w = RevenueWindow(SERVICE_DATE, None, None)
    assert w.classify(FIRST_DEP) == NO_WINDOW


def test_build_windows_needs_a_timezone() -> None:
    # No agency timezone => no window is ever anchored to a guessed zone.
    assert build_windows({SERVICE_DATE: (28800, 72000)}, None) == {}
    built = build_windows({SERVICE_DATE: (0, 86400)}, "UTC")
    assert built[SERVICE_DATE].first_departure == datetime(
        2026, 6, 15, tzinfo=timezone.utc
    )


# ---------------------------------------------------------------------------
# The revenue split
# ---------------------------------------------------------------------------

def test_no_run_outside_window_excluded_non_revenue() -> None:
    events = [
        # a real assigned boarding, in service
        boarding("a1", when=FIRST_DEP + timedelta(hours=1), trip_id="trip-1", count=5),
        # a no-run ghost boarding BEFORE the first departure (prep/pull-out)
        boarding(
            "g1",
            when=FIRST_DEP - timedelta(minutes=30),
            trip_id=None,
            count=3,
            classification="unassigned",
        ),
    ]
    result = compute_upt(events, ["trip-1"], revenue_windows=WINDOW)
    # only the assigned boarding counts (5); the ghost is excluded
    assert result.value == Decimal("5")
    detail = result.detail.to_dict()
    split = detail["revenue_classification"]
    assert split["revenue_boardings"] == 5
    assert split["excluded_non_revenue_boardings"] == 3
    assert split["pending_review_boardings"] == 0
    # one warning cites the excluded ghost record
    excluded = [
        f for f in result.warnings if f.issue_type == "boarding_excluded_non_revenue"
    ]
    assert len(excluded) == 1
    assert excluded[0].source_record_ids == ("rec-g1",)


def test_no_run_inside_window_pending_review_held_out() -> None:
    events = [
        boarding("a1", when=FIRST_DEP + timedelta(hours=1), trip_id="trip-1", count=5),
        # a no-run boarding MID-SERVICE (could be a catch-up bus) -> pending
        boarding(
            "m1",
            when=FIRST_DEP + timedelta(hours=2),
            trip_id=None,
            count=7,
            classification="unassigned",
        ),
    ]
    result = compute_upt(events, ["trip-1"], revenue_windows=WINDOW)
    # the pending boarding is HELD OUT of the figure (exclude-until-classified)
    assert result.value == Decimal("5")
    split = result.detail.to_dict()["revenue_classification"]
    assert split["pending_review_boardings"] == 7
    assert split["excluded_non_revenue_boardings"] == 0
    assert split["pending_review_policy"] == "exclude_until_classified"
    # one per-boarding warning + one run-level info roll-up
    assert any(
        f.issue_type == "boarding_pending_revenue_review" for f in result.warnings
    )
    assert any(
        f.issue_type == "boardings_pending_revenue_review" for f in result.infos
    )


def test_no_window_holds_no_run_pending() -> None:
    events = [
        boarding("a1", when=FIRST_DEP + timedelta(hours=1), trip_id="trip-1", count=5),
        boarding(
            "g1",
            when=FIRST_DEP - timedelta(hours=3),
            trip_id=None,
            count=2,
            classification="unassigned",
        ),
    ]
    # no window supplied at all -> the ghost is held pending, never guessed
    result = compute_upt(events, ["trip-1"], revenue_windows={})
    split = result.detail.to_dict()["revenue_classification"]
    assert split["pending_review_boardings"] == 2
    assert split["excluded_non_revenue_boardings"] == 0


# ---------------------------------------------------------------------------
# The CRITICAL double-count guard
# ---------------------------------------------------------------------------

def test_excluded_boardings_do_not_distort_missing_trip_factor() -> None:
    """A no-run boarding has trip_id None, so it must touch NEITHER the
    counted base NOR the operated/missing denominators — the p. 146 factor is
    identical with and without the ghost boardings present."""
    assigned = [
        boarding("a1", when=FIRST_DEP + timedelta(hours=1), trip_id="trip-1", count=10),
    ]
    operated = ["trip-1", "trip-2"]  # trip-2 operated but no events -> 1 missing
    without_ghosts = compute_upt(assigned, operated, revenue_windows=WINDOW)
    with_ghosts = compute_upt(
        assigned
        + [
            boarding(
                "g1",
                when=FIRST_DEP - timedelta(minutes=10),
                trip_id=None,
                count=4,
                classification="unassigned",
            ),
            boarding(
                "m1",
                when=FIRST_DEP + timedelta(hours=3),
                trip_id=None,
                count=6,
                classification="unassigned",
            ),
        ],
        operated,
        revenue_windows=WINDOW,
    )
    a = without_ghosts.detail.to_dict()
    b = with_ghosts.detail.to_dict()
    # the missing-trip inputs and the factor are IDENTICAL — ghosts changed
    # nothing about the denominator (the double-count guard)
    for key in (
        "operated_trips",
        "trips_with_events",
        "missing_trips",
        "missing_share",
        "factor_applied",
    ):
        assert a[key] == b[key], key
    # and the reported value is identical (both factor 20 counted over the one
    # present trip)
    assert without_ghosts.value == with_ghosts.value


# ---------------------------------------------------------------------------
# Byte-for-byte 0.2.0 retention
# ---------------------------------------------------------------------------

def test_unclassified_feed_is_byte_for_byte_0_2_0() -> None:
    """A feed that sets no revenue_classification (every first-party TIDES
    feed) produces a detail with NO revenue split and computes exactly as
    0.2.0 — the change is strictly additive."""
    events = [
        boarding("a1", when=FIRST_DEP + timedelta(hours=1), trip_id="trip-1", count=5),
        # an unassigned trip_id but NO 0040 status (the pre-0040 proxy path)
        boarding("u1", when=FIRST_DEP, trip_id=None, count=9, classification=None),
    ]
    new = compute_upt(events, ["trip-1"], revenue_windows=WINDOW)
    v020 = compute_upt_v0_2_0(events, ["trip-1"])
    assert new.value == v020.value == Decimal("5")
    assert "revenue_classification" not in new.detail.to_dict()
    # modulo the version string, the whole result matches 0.2.0
    import dataclasses

    assert dataclasses.replace(new, calc_version="x") == dataclasses.replace(
        v020, calc_version="x"
    )


def test_retained_versions_ignore_classification() -> None:
    """The retained 0.1.0/0.2.0 versions strip any assignment status and read
    purely through the trip-assignment proxy — a 0040 event passed to them
    never triggers the split."""
    events = [
        boarding("a1", when=FIRST_DEP + timedelta(hours=1), trip_id="trip-1", count=5),
        boarding(
            "g1",
            when=FIRST_DEP - timedelta(minutes=30),
            trip_id=None,
            count=3,
            classification="unassigned",
        ),
    ]
    for fn, ver in ((compute_upt_v0_1_0, "0.1.0"), (compute_upt_v0_2_0, "0.2.0")):
        result = fn(events, ["trip-1"])
        assert result.calc_version == ver
        assert "revenue_classification" not in result.detail.to_dict()
        # value is the counted assigned boarding, factored over operated (1/1)
        assert result.value == Decimal("5")


def test_null_count_unassigned_boarding_warns_not_guessed() -> None:
    """A no-run boarding with a NULL count is warned (never coalesced to a
    guessed number) and contributes 0 to every split bucket."""
    events = [
        boarding("a1", when=FIRST_DEP + timedelta(hours=1), trip_id="trip-1", count=5),
        boarding(
            "g1",
            when=FIRST_DEP - timedelta(minutes=30),
            trip_id=None,
            count=None,
            classification="unassigned",
        ),
    ]
    result = compute_upt(events, ["trip-1"], revenue_windows=WINDOW)
    split = result.detail.to_dict().get("revenue_classification")
    # no boarding count to place: the split never appeared (all buckets 0)
    assert split is None
    assert any(f.issue_type == "apc_null_count" for f in result.warnings)
