"""Hypothesis property tests for pmt_v0 CALC_VERSION 0.1.0 (handoff 0011).

Invariants over generated fleets of operated trips with balanced load
profiles over simple two-stop shape geometry (plus missing and defective
trips):

- DETERMINISM and ORDER-INDEPENDENCE: event order, operated-trip order and
  stop_times order are irrelevant to the result;
- FACTOR-UP BOUNDS: when a value is emitted, counted <= reported <=
  quantize(counted / (1 - threshold)) — the threshold-edge bound;
- BLOCKING-IMPLIES-NONE, exact at the p. 146 threshold line:
  (missing + invalid-operated) > threshold x operated <=> blocked;
- NON-NEGATIVITY: the value and every detail count are >= 0; a valid
  trip's contribution never prices a negative load (negative-load trips are
  excluded by construction).

Hypothesis is test-only — the library itself contains no randomness.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc.distance import MILES_QUANTUM
from headway_calc.pmt import compute_pmt
from headway_calc.types import PassengerEvent, StopTime
from headway_calc.upt import (
    ALIGHTING_EVENT_TYPE,
    BOARDING_EVENT_TYPE,
    MISSING_TRIP_THRESHOLD,
)

T0 = datetime(2026, 6, 15, 6, 0, 0, tzinfo=timezone.utc)
SERVICE_DATE = date(2026, 6, 15)


@st.composite
def fleet(draw):
    """(events, operated_trip_ids, stop_times): 1-25 operated trips over
    two-stop geometry (shape_dist 0 -> 0.5-5 miles, unit 1). Each trip is
    independently: missing (no events), valid (board n / alight n), or
    defective (imbalanced counts, or an alight-first negative load)."""
    n_trips = draw(st.integers(min_value=1, max_value=25))
    operated = [f"trip-{k:02d}" for k in range(n_trips)]
    events: list[PassengerEvent] = []
    stop_times: list[StopTime] = []
    seq = 0

    def add_event(trip_id, stop_seq, event_type, count):
        nonlocal seq
        seq += 1
        events.append(
            PassengerEvent(
                event_timestamp=T0 + timedelta(seconds=seq),
                service_date=SERVICE_DATE,
                passenger_event_id=f"pe-{seq:04d}",
                vehicle_id=f"veh-{trip_id}",
                trip_id=trip_id,
                trip_stop_sequence=stop_seq,
                event_type=event_type,
                event_count=count,
                source=draw(st.sampled_from(["tides", "tides_simulated"])),
                source_record_id=f"rec-{seq:04d}",
            )
        )

    for trip_id in operated:
        miles_tenths = draw(st.integers(min_value=5, max_value=50))
        stop_times.append(
            StopTime(trip_id, f"{trip_id}-a", 1, 42.0, -71.0, 0.0)
        )
        stop_times.append(
            StopTime(
                trip_id, f"{trip_id}-b", 2, 42.1, -71.0, miles_tenths / 10.0
            )
        )
        kind = draw(st.sampled_from(["missing", "valid", "imbalance", "negative"]))
        if kind == "missing":
            continue
        n = draw(st.integers(min_value=1, max_value=40))
        if kind == "valid":
            add_event(trip_id, 1, BOARDING_EVENT_TYPE, n)
            add_event(trip_id, 2, ALIGHTING_EVENT_TYPE, n)
        elif kind == "imbalance":
            # |n - 2n| = n > 0.10 x n: always over the p. 151 line.
            add_event(trip_id, 1, BOARDING_EVENT_TYPE, n)
            add_event(trip_id, 2, ALIGHTING_EVENT_TYPE, 2 * n)
        else:
            # Alight before any boarding: running load < 0, but balanced.
            add_event(trip_id, 1, ALIGHTING_EVENT_TYPE, n)
            add_event(trip_id, 2, BOARDING_EVENT_TYPE, n)
    return events, operated, stop_times


@given(fleet(), st.randoms(use_true_random=False))
@settings(max_examples=60, deadline=None)
def test_order_independence_and_determinism(data, rng):
    events, operated, stop_times = data
    baseline = compute_pmt(
        events, operated, stop_times, shape_dist_unit_miles=Decimal("1")
    )
    shuffled_events = list(events)
    shuffled_operated = list(operated)
    shuffled_stop_times = list(stop_times)
    rng.shuffle(shuffled_events)
    rng.shuffle(shuffled_operated)
    rng.shuffle(shuffled_stop_times)
    again = compute_pmt(
        shuffled_events,
        shuffled_operated,
        shuffled_stop_times,
        shape_dist_unit_miles=Decimal("1"),
    )
    assert again.value == baseline.value
    assert again.input_record_ids == baseline.input_record_ids
    assert [w.issue_type for w in again.warnings] == [
        w.issue_type for w in baseline.warnings
    ]
    assert again.detail.to_dict() == baseline.detail.to_dict()


@given(fleet())
@settings(max_examples=60, deadline=None)
def test_blocking_exact_at_threshold_and_factor_bounds(data):
    events, operated, stop_times = data
    result = compute_pmt(
        events, operated, stop_times, shape_dist_unit_miles=Decimal("1")
    )
    detail = result.detail
    unusable = detail.missing_trips + sum(
        1
        for t in operated
        if t in {  # invalid AND operated (all our defects are operated trips)
            w.title.split()[1] for w in result.warnings
        }
    )
    should_block = Decimal(unusable) > MISSING_TRIP_THRESHOLD * Decimal(
        len(set(operated))
    )
    if should_block:
        assert result.value is None
        assert [b.issue_type for b in result.blocking_issues] == [
            "apc_missing_trips_above_fta_threshold"
        ]
    else:
        assert result.blocking_issues == ()
        counted = detail.passenger_miles_counted
        assert result.value >= counted
        upper = (counted / (Decimal(1) - MISSING_TRIP_THRESHOLD)).quantize(
            MILES_QUANTUM, rounding=ROUND_HALF_EVEN
        )
        assert result.value <= upper
        assert result.value >= 0


@given(fleet())
@settings(max_examples=60, deadline=None)
def test_detail_counts_are_consistent(data):
    events, operated, stop_times = data
    result = compute_pmt(
        events, operated, stop_times, shape_dist_unit_miles=Decimal("1")
    )
    d = result.detail
    assert d.valid_trips + d.invalid_trips == d.trips_with_events
    assert d.missing_trips <= d.operated_trips
    assert sum(d.invalid_trip_reasons.values()) == d.invalid_trips
    assert d.passenger_miles_counted >= 0
    # Lineage covers valid trips only: exactly 2 records per valid trip in
    # this fleet shape.
    assert len(result.input_record_ids) == 2 * d.valid_trips
