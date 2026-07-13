"""Unit tests for headway_calc.ops — otp_v0 0.1.0 + headway_adherence_v0
0.1.0 (handoff 0014, OPERATIONS metrics; definitions in
services/calc/OPS_DEFINITIONS.md)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.ops import (
    MAX_SCHEDULED_HEADWAY_SECONDS,
    MIN_PAIRS_PER_ROUTE,
    MIN_PASSAGES_PER_ROUTE,
    compute_headway_adherence,
    compute_headway_adherence_by_route,
    compute_otp,
    compute_otp_by_route,
    routes_below_min_sample,
    scope_for_route,
)
from headway_calc.passages import PassageDerivationStats
from headway_calc.types import StopPassage

TZ = ("America/New_York",)

#: 2026-07-09 is EDT (UTC-4): schedule anchor = 2026-07-09T04:00:00Z.
ANCHOR = datetime(2026, 7, 9, 4, 0, tzinfo=timezone.utc)


def _stats() -> PassageDerivationStats:
    return PassageDerivationStats(
        positions_considered=0,
        positions_deduplicated=0,
        occurrences=0,
        occurrences_skipped_few_positions=0,
        trips_observed=0,
        trips_without_schedule=0,
        stops_considered=0,
        stops_missing_coordinates=0,
        passages_derived=0,
        refused_not_reached=0,
        refused_endpoint_unbounded=0,
        refused_cadence_gap=0,
    )


def _passage(
    *,
    trip_id="T1",
    stop_id="S1",
    stop_sequence=1,
    observed_offset_seconds=28800,
    arrival_seconds=28800,
    departure_seconds=None,
    route_id="R1",
    direction_id=0,
    rec="rec-1",
) -> StopPassage:
    from datetime import timedelta

    return StopPassage(
        trip_id=trip_id,
        vehicle_id="bus-1",
        route_id=route_id,
        direction_id=direction_id,
        stop_id=stop_id,
        stop_sequence=stop_sequence,
        observed_time=ANCHOR + timedelta(seconds=observed_offset_seconds),
        scheduled_arrival_seconds=arrival_seconds,
        scheduled_departure_seconds=departure_seconds,
        bounding_gap_seconds=60.0,
        distance_m=10.0,
        source_record_id=rec,
    )


# ---------------------------------------------------------------------------
# otp_v0
# ---------------------------------------------------------------------------

def test_otp_refuses_without_agency_timezone():
    result = compute_otp([_passage()], _stats(), [])
    assert result.value is None
    [issue] = result.blocking_issues
    assert issue.issue_type == "agency_timezone_unknown"
    assert "never guessed" in issue.description


def test_otp_refuses_on_conflicting_timezones():
    result = compute_otp(
        [_passage()], _stats(), ["America/New_York", "America/Chicago"]
    )
    [issue] = result.blocking_issues
    assert issue.issue_type == "agency_timezone_ambiguous"


def test_otp_duplicate_timezone_rows_of_one_zone_are_fine():
    result = compute_otp(
        [_passage()], _stats(), ["America/New_York", "America/New_York"]
    )
    assert result.value == Decimal("100.00")


@pytest.mark.parametrize(
    "offset, on_time",
    [
        (28800 - 60, True),   # exactly the early boundary: on time
        (28800 - 61, False),  # one second earlier: early
        (28800 + 300, True),  # exactly the late boundary: on time
        (28800 + 301, False), # one second later: late
    ],
)
def test_otp_window_boundaries_inclusive(offset, on_time):
    result = compute_otp(
        [_passage(observed_offset_seconds=offset)], _stats(), TZ
    )
    assert (result.value == Decimal("100.00")) is on_time


def test_otp_departure_fallback_when_arrival_missing():
    passage = _passage(arrival_seconds=None, departure_seconds=28800)
    result = compute_otp([passage], _stats(), TZ)
    assert result.value == Decimal("100.00")
    assert result.detail.passages_unscheduled == 0


def test_otp_unscheduled_passages_counted_never_interpolated():
    scheduled = _passage()
    unscheduled = _passage(
        stop_id="S9", arrival_seconds=None, departure_seconds=None, rec="rec-2"
    )
    result = compute_otp([scheduled, unscheduled], _stats(), TZ)
    assert result.detail.passages_considered == 1
    assert result.detail.passages_unscheduled == 1
    # The unscheduled passage's record never enters lineage.
    assert list(result.input_record_ids) == ["rec-1"]


def test_otp_refuses_over_zero_usable_passages():
    unscheduled = _passage(arrival_seconds=None, departure_seconds=None)
    result = compute_otp([unscheduled], _stats(), TZ)
    assert result.value is None
    [issue] = result.blocking_issues
    assert issue.issue_type == "no_observed_passages"


def test_otp_service_day_resolution_past_midnight():
    """A 25:00:00 schedule time (seconds 90000, service day 2026-07-09) is
    2026-07-10T05:00:00Z; an observation 2 minutes later must resolve to
    the PREVIOUS service day and deviate +120, not appear ~23 h early on
    its own calendar day."""
    from datetime import timedelta

    passage = StopPassage(
        trip_id="T-owl",
        vehicle_id="bus-1",
        route_id="R1",
        direction_id=0,
        stop_id="S1",
        stop_sequence=1,
        observed_time=ANCHOR + timedelta(seconds=90000 + 120),
        scheduled_arrival_seconds=90000,
        scheduled_departure_seconds=None,
        bounding_gap_seconds=60.0,
        distance_m=5.0,
        source_record_id="rec-owl",
    )
    result = compute_otp([passage], _stats(), TZ)
    assert result.value == Decimal("100.00")
    assert result.detail.deviation_mean_seconds == Decimal("120.00")


def test_otp_negative_tolerance_refused():
    with pytest.raises(ValueError):
        compute_otp([_passage()], _stats(), TZ, early_tolerance_seconds=-1)


def test_otp_explicit_window_recorded_in_detail():
    result = compute_otp(
        [_passage(observed_offset_seconds=28800 + 200)],
        _stats(),
        TZ,
        early_tolerance_seconds=0,
        late_tolerance_seconds=100,
    )
    assert result.value == Decimal("0.00")  # +200 s > 100 s: late
    assert result.detail.early_tolerance_seconds == 0
    assert result.detail.late_tolerance_seconds == 100


def test_otp_by_route_enforces_min_sample_and_buckets_unknown():
    on_route = [
        _passage(stop_id=f"S{i}", stop_sequence=i, rec=f"rec-{i}")
        for i in range(1, MIN_PASSAGES_PER_ROUTE + 1)
    ]
    thin = [_passage(route_id="R-thin", rec="rec-thin")]
    unknown = [_passage(route_id=None, rec="rec-unknown")]
    results = compute_otp_by_route(on_route + thin + unknown, _stats(), TZ)
    assert set(results) == {"R1"}
    assert results["R1"].detail.passages_considered == MIN_PASSAGES_PER_ROUTE
    below = routes_below_min_sample(on_route + thin + unknown)
    assert below == {"R-thin": 1, "unknown": 1}
    assert scope_for_route(None) == "route:unknown"
    assert scope_for_route("R1") == "route:R1"


# ---------------------------------------------------------------------------
# headway_adherence_v0
# ---------------------------------------------------------------------------

def _pair(stop_id, sched_a, sched_b, obs_a, obs_b, rec_prefix, route_id="R1"):
    """Two consecutive passages at one stop (departure-seconds scheduled)."""
    return [
        _passage(
            trip_id=f"{rec_prefix}-a", stop_id=stop_id,
            observed_offset_seconds=obs_a, arrival_seconds=None,
            departure_seconds=sched_a, rec=f"{rec_prefix}-a",
            route_id=route_id,
        ),
        _passage(
            trip_id=f"{rec_prefix}-b", stop_id=stop_id,
            observed_offset_seconds=obs_b, arrival_seconds=None,
            departure_seconds=sched_b, rec=f"{rec_prefix}-b",
            route_id=route_id,
        ),
    ]


def test_headway_perfect_adherence_is_zero():
    passages = _pair("S1", 28800, 29700, 28800, 29700, "p")
    result = compute_headway_adherence(passages, _stats())
    assert result.value == Decimal("0.0000")
    assert result.detail.pairs_counted == 1
    assert result.detail.mean_scheduled_headway_seconds == Decimal("900.00")


def test_headway_uses_departure_before_arrival():
    passages = [
        _passage(
            trip_id="a", observed_offset_seconds=28800,
            arrival_seconds=28000, departure_seconds=28800, rec="a",
        ),
        _passage(
            trip_id="b", observed_offset_seconds=29700,
            arrival_seconds=28900, departure_seconds=29700, rec="b",
        ),
    ]
    result = compute_headway_adherence(passages, _stats())
    # Departure-based scheduled headway 900 == observed 900 → cvh 0.
    assert result.value == Decimal("0.0000")


def test_headway_excludes_inverted_and_over_cap_pairs_loudly():
    inverted = _pair("S1", 29700, 28800, 28800, 29700, "inv")  # sched < 0
    over_cap = _pair(
        "S2", 28800, 28800 + MAX_SCHEDULED_HEADWAY_SECONDS + 1,
        28800, 28800 + MAX_SCHEDULED_HEADWAY_SECONDS + 1, "cap",
    )
    unscheduled = [
        _passage(trip_id="u-a", stop_id="S3", observed_offset_seconds=28800,
                 arrival_seconds=None, departure_seconds=None, rec="u-a"),
        _passage(trip_id="u-b", stop_id="S3", observed_offset_seconds=29700,
                 arrival_seconds=None, departure_seconds=29700, rec="u-b"),
    ]
    good = _pair("S4", 28800, 29700, 28800, 29760, "good")
    result = compute_headway_adherence(
        inverted + over_cap + unscheduled + good, _stats()
    )
    assert result.detail.pairs_counted == 1
    assert result.detail.pairs_excluded_inverted == 1
    assert result.detail.pairs_excluded_over_cap == 1
    assert result.detail.pairs_excluded_unscheduled == 1
    # Only the counted group's records enter lineage.
    assert list(result.input_record_ids) == ["good-a", "good-b"]


def test_headway_refuses_over_zero_pairs():
    result = compute_headway_adherence([_passage()], _stats())
    assert result.value is None
    [issue] = result.blocking_issues
    assert issue.issue_type == "no_headway_pairs"


def test_headway_groups_never_pair_across_stops_or_directions():
    # Same route, two stops: one passage each — no pair anywhere.
    passages = [
        _passage(trip_id="a", stop_id="S1", rec="a"),
        _passage(trip_id="b", stop_id="S2", observed_offset_seconds=29700,
                 arrival_seconds=29700, rec="b"),
    ]
    result = compute_headway_adherence(passages, _stats())
    assert result.value is None


def test_headway_by_route_enforces_min_pairs():
    # MIN_PAIRS_PER_ROUTE pairs on R1 (spread across stops), 1 pair on thin.
    passages: list[StopPassage] = []
    for i in range(MIN_PAIRS_PER_ROUTE):
        passages.extend(
            _pair(f"S{i}", 28800, 29700, 28800, 29700 + 30 * i, f"r1-{i}")
        )
    passages.extend(
        _pair("S-thin", 28800, 29700, 28800, 29700, "thin", route_id="R-thin")
    )
    results = compute_headway_adherence_by_route(passages, _stats())
    assert set(results) == {"R1"}
    assert results["R1"].detail.pairs_counted == MIN_PAIRS_PER_ROUTE
