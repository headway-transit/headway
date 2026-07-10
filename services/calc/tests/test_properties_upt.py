"""Hypothesis property tests for upt_v0 CALC_VERSION 0.1.0 (handoff 0005).

Invariants over generated fleets of operated trips with boarding/alighting
events (counts possibly NULL, sources mixed, some trips left without events):

- DETERMINISM: same input -> structurally identical result;
- ORDER-INDEPENDENCE: event order and operated-trip-id order are irrelevant;
- MONOTONICITY: adding a boarding event to a trip that already has events
  never decreases the reported UPT (and never decreases the counted base on
  ANY input). NOTE the deliberate scoping: a boarding event landing on a
  previously-MISSING trip legitimately may LOWER the reported figure — the
  real count replaces the p. 146 factor-up estimate for that trip (e.g.
  operated 50, missing 1, counted 98 -> 100 factored; a count-0 boarding on
  the missing trip yields 98 exactly). That is correct FTA arithmetic, not a
  regression, and is pinned by its own test;
- FACTOR-UP BOUNDS: when a value is emitted, counted <= reported <=
  quantize(counted / (1 - threshold)) — the threshold-edge bound (both ends
  quantized to whole boardings with the same documented rounding);
- BLOCKING-IMPLIES-NONE, exact at the p. 146 threshold line:
  missing > threshold x operated <=> blocked, blocked -> value None and ONE
  apc_missing_trips_above_fta_threshold finding.

Hypothesis is test-only — the library itself contains no randomness.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc.types import PassengerEvent
from headway_calc.upt import (
    ALIGHTING_EVENT_TYPE,
    BOARDING_EVENT_TYPE,
    MISSING_TRIP_THRESHOLD,
    compute_upt,
)

T0 = datetime(2026, 6, 15, 6, 0, 0, tzinfo=timezone.utc)
SERVICE_DATE = date(2026, 6, 15)

counts = st.one_of(st.none(), st.integers(min_value=0, max_value=50))
sources = st.sampled_from(["tides", "tides_simulated"])
event_types = st.sampled_from([BOARDING_EVENT_TYPE, ALIGHTING_EVENT_TYPE])


@st.composite
def fleet(draw):
    """(events, operated_trip_ids): 1-30 operated trips, each independently
    covered (1-4 boarding/alighting events) or left missing; plus 0-2
    unassigned events outside the revenue proxy."""
    n_trips = draw(st.integers(min_value=1, max_value=30))
    operated = [f"trip-{k:02d}" for k in range(n_trips)]
    events: list[PassengerEvent] = []
    seq = 0
    for trip_id in operated:
        if not draw(st.booleans()):
            continue  # missing trip: zero passenger events
        for _ in range(draw(st.integers(min_value=1, max_value=4))):
            seq += 1
            events.append(
                PassengerEvent(
                    event_timestamp=T0 + timedelta(seconds=seq),
                    service_date=SERVICE_DATE,
                    passenger_event_id=f"pe-{seq:04d}",
                    vehicle_id=f"veh-{trip_id}",
                    trip_id=trip_id,
                    trip_stop_sequence=draw(
                        st.one_of(st.none(), st.integers(min_value=1, max_value=9))
                    ),
                    event_type=draw(event_types),
                    event_count=draw(counts),
                    source=draw(sources),
                    source_record_id=f"rec-{seq:04d}",
                )
            )
    for _ in range(draw(st.integers(min_value=0, max_value=2))):
        seq += 1
        events.append(
            PassengerEvent(
                event_timestamp=T0 + timedelta(seconds=seq),
                service_date=SERVICE_DATE,
                passenger_event_id=f"pe-{seq:04d}",
                vehicle_id="veh-x",
                trip_id=None,
                trip_stop_sequence=1,
                event_type=BOARDING_EVENT_TYPE,
                event_count=draw(counts),
                source=draw(sources),
                source_record_id=f"rec-{seq:04d}",
            )
        )
    return events, operated


@given(fleet())
@settings(max_examples=100, deadline=None)
def test_determinism_same_input_identical_result(data):
    events, operated = data
    r1 = compute_upt(events, operated)
    r2 = compute_upt(events, operated)
    assert r1 == r2  # frozen dataclasses: full structural equality


@given(fleet())
@settings(max_examples=100, deadline=None)
def test_input_order_irrelevant(data):
    events, operated = data
    assert compute_upt(events, operated) == compute_upt(
        list(reversed(events)), list(reversed(operated))
    )


@given(fleet(), st.integers(min_value=0, max_value=50))
@settings(max_examples=100, deadline=None)
def test_adding_boarding_to_covered_trip_never_decreases_upt(data, extra_count):
    """Monotonicity on the counted path: a new boarding event on a trip that
    ALREADY has events leaves the missing-trip arithmetic untouched and adds
    a non-negative count — the reported UPT never decreases (None orders
    below any value: an unblocked run stays unblocked)."""
    events, operated = data
    covered = sorted({e.trip_id for e in events if e.trip_id is not None})
    if not covered:
        return  # nothing covered: the added event would change missing trips
    target = covered[0]
    extra = PassengerEvent(
        event_timestamp=T0 + timedelta(seconds=99999),
        service_date=SERVICE_DATE,
        passenger_event_id="pe-extra",
        vehicle_id="veh-extra",
        trip_id=target,
        trip_stop_sequence=1,
        event_type=BOARDING_EVENT_TYPE,
        event_count=extra_count,
        source="tides",
        source_record_id="rec-extra",
    )
    before = compute_upt(events, operated)
    after = compute_upt(list(events) + [extra], operated)
    # The counted base never decreases on ANY input.
    assert (
        after.detail.total_boardings_counted
        >= before.detail.total_boardings_counted
    )
    assert bool(after.blocking_issues) == bool(before.blocking_issues)
    if not before.blocking_issues:
        assert after.value >= before.value


def test_boarding_on_missing_trip_may_lower_the_factored_figure():
    """The documented monotonicity exception (module docstring): real data
    on a previously-missing trip replaces the factor-up estimate. 50
    operated, 49 covered x 2 boardings = 98 counted -> factored to 100; a
    count-0 boarding on the missing trip-49 yields exactly 98."""
    events = [
        PassengerEvent(
            event_timestamp=T0 + timedelta(seconds=k),
            service_date=SERVICE_DATE,
            passenger_event_id=f"pe-{k:02d}",
            vehicle_id=f"veh-{k:02d}",
            trip_id=f"trip-{k:02d}",
            trip_stop_sequence=1,
            event_type=BOARDING_EVENT_TYPE,
            event_count=2,
            source="tides",
            source_record_id=f"rec-{k:02d}",
        )
        for k in range(49)
    ]
    operated = [f"trip-{k:02d}" for k in range(50)]
    factored = compute_upt(events, operated)
    assert factored.value == Decimal("100")
    filler = PassengerEvent(
        event_timestamp=T0 + timedelta(seconds=999),
        service_date=SERVICE_DATE,
        passenger_event_id="pe-fill",
        vehicle_id="veh-49",
        trip_id="trip-49",
        trip_stop_sequence=1,
        event_type=BOARDING_EVENT_TYPE,
        event_count=0,
        source="tides",
        source_record_id="rec-fill",
    )
    measured = compute_upt(events + [filler], operated)
    assert measured.value == Decimal("98")  # < 100: estimate replaced by data


@given(fleet())
@settings(max_examples=100, deadline=None)
def test_factor_up_bounds_when_value_emitted(data):
    """counted <= reported <= quantize(counted / (1 - threshold)): the
    factor is >= 1 and, at the p. 146 threshold edge, at most
    1/(1 - 0.02). Quantization (whole boardings, ROUND_HALF_EVEN) is
    monotone, so the bounds hold on the quantized figures too."""
    events, operated = data
    result = compute_upt(events, operated)
    if result.blocking_issues:
        return
    counted = Decimal(result.detail.total_boardings_counted)
    upper = (counted / (Decimal(1) - MISSING_TRIP_THRESHOLD)).quantize(
        Decimal("1"), rounding=ROUND_HALF_EVEN
    )
    assert counted <= result.value <= upper
    assert result.detail.factor_applied >= Decimal(1)


@given(fleet())
@settings(max_examples=100, deadline=None)
def test_blocking_iff_exact_threshold_line_and_implies_none(data):
    """missing > threshold x operated (EXACT comparison) <=> blocked;
    blocked -> value None, ONE apc_missing_trips_above_fta_threshold
    finding, factor_applied None."""
    events, operated = data
    covered = {e.trip_id for e in events if e.trip_id is not None}
    missing = sum(1 for t in operated if t not in covered)
    should_block = Decimal(missing) > MISSING_TRIP_THRESHOLD * Decimal(len(operated))
    result = compute_upt(events, operated)
    assert bool(result.blocking_issues) == should_block
    if should_block:
        assert result.value is None
        assert len(result.blocking_issues) == 1
        assert result.blocking_issues[0].issue_type == (
            "apc_missing_trips_above_fta_threshold"
        )
        assert result.detail.factor_applied is None
    else:
        assert result.value is not None
        assert result.detail.factor_applied is not None


@given(fleet())
@settings(max_examples=100, deadline=None)
def test_lineage_covers_counted_boardings_and_source_mix_totals(data):
    """input_record_ids are exactly the distinct records of counted (non-NULL,
    trip-assigned) boarding events; source_mix always totals every event."""
    events, operated = data
    result = compute_upt(events, operated)
    expected_ids = {
        e.source_record_id
        for e in events
        if e.trip_id is not None
        and e.event_type == BOARDING_EVENT_TYPE
        and e.event_count is not None
    }
    assert set(result.input_record_ids) == expected_ids
    assert len(result.input_record_ids) == len(set(result.input_record_ids))
    assert sum(result.detail.source_mix.values()) == len(events)
    # Simulated-source rule: info present iff any non-'tides' event exists.
    has_simulated = any(e.source != "tides" for e in events)
    assert (
        any(i.issue_type == "simulated_source_data" for i in result.infos)
        == has_simulated
    )


@given(fleet())
@settings(max_examples=100, deadline=None)
def test_null_counts_warned_never_in_lineage(data):
    events, operated = data
    result = compute_upt(events, operated)
    null_events = [
        e
        for e in events
        if e.trip_id is not None
        and e.event_type in (BOARDING_EVENT_TYPE, ALIGHTING_EVENT_TYPE)
        and e.event_count is None
    ]
    null_warnings = [w for w in result.warnings if w.issue_type == "apc_null_count"]
    assert len(null_warnings) == len(null_events)
    for w in null_warnings:
        assert len(w.source_record_ids) == 1
        assert w.source_record_ids[0] not in result.input_record_ids
