"""Property-based tests (Hypothesis) for the ops slice (handoff 0014):
derive_stop_passages 0.1.0, otp_v0 0.1.0, headway_adherence_v0 0.1.0.

Invariants:
- derivation accounting identity: every scheduled stop considered is
  derived or refused under exactly one named reason (fail-loudly — nothing
  silent);
- derivation determinism under input permutation;
- otp_v0: value == 100 * on_time / considered, classification counts
  partition the considered passages, 0 <= value <= 100;
- headway_adherence_v0: cvh >= 0; exactly-scheduled observations give 0.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc.ops import compute_headway_adherence, compute_otp
from headway_calc.passages import derive_stop_passages
from headway_calc.types import OpsScheduledStop, StopPassage, VehiclePosition

T0 = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
ANCHOR = datetime(2026, 7, 9, 4, 0, tzinfo=timezone.utc)
TZ = ("America/New_York",)


# ---------------------------------------------------------------------------
# derivation
# ---------------------------------------------------------------------------

@st.composite
def small_world(draw):
    """A few trips with random position tracks + a random stop schedule."""
    n_trips = draw(st.integers(min_value=1, max_value=3))
    positions: list[VehiclePosition] = []
    schedule: list[OpsScheduledStop] = []
    for t in range(n_trips):
        trip_id = f"T{t}"
        n_pos = draw(st.integers(min_value=1, max_value=12))
        offset = 0
        for i in range(n_pos):
            offset += draw(st.integers(min_value=0, max_value=200))
            lat = 42.35 + draw(
                st.integers(min_value=-40, max_value=40)
            ) * 0.0001
            positions.append(
                VehiclePosition(
                    time=T0 + timedelta(seconds=offset),
                    vehicle_id=f"bus-{t}",
                    trip_id=trip_id,
                    latitude=lat,
                    longitude=-71.06,
                    source_record_id=f"rec-{t}-{i}",
                )
            )
        n_stops = draw(st.integers(min_value=0, max_value=4))
        for s in range(n_stops):
            has_coords = draw(st.booleans())
            schedule.append(
                OpsScheduledStop(
                    trip_id=trip_id,
                    stop_id=f"S{s}",
                    stop_sequence=s + 1,
                    latitude=(
                        42.35 + s * 0.0005 if has_coords else None
                    ),
                    longitude=-71.06 if has_coords else None,
                    arrival_seconds=28800 + 300 * s,
                    departure_seconds=28800 + 300 * s,
                    route_id="R1",
                    direction_id=0,
                )
            )
    return positions, schedule


@given(small_world())
@settings(max_examples=60, deadline=None)
def test_derivation_accounting_identity(world):
    positions, schedule = world
    passages, stats = derive_stop_passages(positions, schedule)
    assert stats.passages_derived == len(passages)
    assert stats.stops_considered == (
        stats.passages_derived
        + stats.stops_missing_coordinates
        + stats.refused_not_reached
        + stats.refused_endpoint_unbounded
        + stats.refused_cadence_gap
    )
    assert stats.occurrences >= stats.occurrences_skipped_few_positions
    for p in passages:
        assert p.bounding_gap_seconds <= 120.0


@given(small_world(), st.randoms())
@settings(max_examples=30, deadline=None)
def test_derivation_deterministic_under_permutation(world, rng):
    positions, schedule = world
    baseline = derive_stop_passages(positions, schedule)
    shuffled_p = list(positions)
    shuffled_s = list(schedule)
    rng.shuffle(shuffled_p)
    rng.shuffle(shuffled_s)
    assert derive_stop_passages(shuffled_p, shuffled_s) == baseline


# ---------------------------------------------------------------------------
# otp_v0
# ---------------------------------------------------------------------------

def _stats_zero():
    from headway_calc.passages import PassageDerivationStats

    return PassageDerivationStats(
        positions_considered=0, positions_deduplicated=0, occurrences=0,
        occurrences_skipped_few_positions=0, trips_observed=0,
        trips_without_schedule=0, stops_considered=0,
        stops_missing_coordinates=0, passages_derived=0,
        refused_not_reached=0, refused_endpoint_unbounded=0,
        refused_cadence_gap=0,
    )


@st.composite
def deviated_passages(draw):
    n = draw(st.integers(min_value=1, max_value=40))
    passages = []
    for i in range(n):
        deviation = draw(st.integers(min_value=-1800, max_value=1800))
        passages.append(
            StopPassage(
                trip_id=f"T{i}",
                vehicle_id="bus-1",
                route_id="R1",
                direction_id=0,
                stop_id=f"S{i % 5}",
                stop_sequence=i % 5 + 1,
                observed_time=ANCHOR + timedelta(seconds=28800 + deviation),
                scheduled_arrival_seconds=28800,
                scheduled_departure_seconds=None,
                bounding_gap_seconds=60.0,
                distance_m=10.0,
                source_record_id=f"rec-{i}",
            )
        )
    return passages


@given(deviated_passages())
@settings(max_examples=60, deadline=None)
def test_otp_value_is_exact_share_and_counts_partition(passages):
    result = compute_otp(passages, _stats_zero(), TZ)
    detail = result.detail
    assert (
        detail.on_time_count + detail.early_count + detail.late_count
        == detail.passages_considered
        == len(passages)
    )
    # Exact share, quantized 0.01 — recomputed independently.
    assert result.value == (
        Decimal(100 * detail.on_time_count) / Decimal(detail.passages_considered)
    ).quantize(Decimal("0.01"))
    assert Decimal("0") <= result.value <= Decimal("100")


# ---------------------------------------------------------------------------
# headway_adherence_v0
# ---------------------------------------------------------------------------

@st.composite
def paired_passages(draw):
    """Consecutive passages at one stop with random scheduled/observed
    headways (positive, under the cap)."""
    n = draw(st.integers(min_value=2, max_value=25))
    exact = draw(st.booleans())
    passages = []
    sched = 28800
    observed = 28800
    for i in range(n):
        if i:
            sched_gap = draw(st.integers(min_value=60, max_value=3600))
            sched += sched_gap
            observed += sched_gap if exact else draw(
                st.integers(min_value=1, max_value=5400)
            )
        passages.append(
            StopPassage(
                trip_id=f"T{i}",
                vehicle_id="bus-1",
                route_id="R1",
                direction_id=0,
                stop_id="S1",
                stop_sequence=1,
                observed_time=ANCHOR + timedelta(seconds=observed),
                scheduled_arrival_seconds=None,
                scheduled_departure_seconds=sched,
                bounding_gap_seconds=60.0,
                distance_m=10.0,
                source_record_id=f"rec-{i}",
            )
        )
    return passages, exact


@given(paired_passages())
@settings(max_examples=60, deadline=None)
def test_headway_cvh_nonnegative_and_zero_iff_exact(pair_case):
    passages, exact = pair_case
    result = compute_headway_adherence(passages, _stats_zero())
    assert result.value is not None
    assert result.value >= Decimal("0")
    if exact:
        assert result.value == Decimal("0.0000")
        assert result.detail.stddev_deviation_seconds == Decimal("0.00")
