"""Hypothesis property tests for vrh_v0 CALC_VERSION 0.4.0 (handoff 0004).

Trip-excision invariants over schedules with per-trip gap injection (unlike
the 0.3.0 suite, gaps are allowed everywhere — the 0.4.0 monotonicity claims
hold on ARBITRARY input, not just gap-free input):
- MONOTONICITY vs 0.2.0: v0.4 VRH >= v0.2 VRH on identical input — the
  excision unit is the same trip, and v0.4 only ADDS capped, non-negative
  clean-adjacent layover time (identical lineage: both include exactly the
  clean trips' records);
- MONOTONICITY vs 0.3.0: v0.4 VRH >= v0.3 VRH on identical input —
  block-level exclusion is strictly harsher (it also drops the gapped
  block's clean trips and layovers);
- the layover cap is respected: cap 0 collapses v0.4 to the v0.2 value
  exactly, the figure is monotone in layover_max_seconds with exact interval
  accounting, and every over-cap CLEAN-ADJACENT interval emits one
  layover_exceeds_max warning (excision-adjacent intervals are dropped, not
  warned);
- one telemetry_gap_excluded warning PER excised trip, citing exactly that
  trip's records;
- determinism / input-order irrelevance (full structural equality);
- blocking-implies-None, exact at the coverage threshold line over TRIPS.

Hypothesis is test-only — the library itself contains no randomness.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc._blocks import LAYOVER_MAX_SECONDS
from headway_calc._grouping import GAP_THRESHOLD_SECONDS
from headway_calc.types import VehiclePosition
from headway_calc.vrh import compute_vrh, compute_vrh_v0_2, compute_vrh_v0_3

T0 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

#: A coverage threshold of 0 never blocks — it isolates the excision
#: arithmetic from the certifiability line (suite convention).
NEVER_BLOCK = Decimal("0")

# Spacing kept strictly within the gap threshold so clean running segments
# never trip the within-trip gap rule; inter-trip intervals range past the
# layover cap; injected within-trip gaps always exceed the threshold.
spacing_seconds = st.integers(min_value=1, max_value=int(GAP_THRESHOLD_SECONDS))
inter_trip_seconds = st.integers(min_value=1, max_value=2 * int(LAYOVER_MAX_SECONDS))
extra_gap_seconds = st.integers(min_value=1, max_value=86400)


@st.composite
def vehicle_schedule(draw, vehicle_index: int):
    """One vehicle's day: 1-3 sequential trips, all sharing one block (or
    none — the per-trip fallback), each trip independently gapped or clean
    (a gapped trip gets one over-threshold within-trip spacing appended).

    Returns (positions, has_block, clean_flags, intervals) where clean_flags
    aligns with the trips in schedule order and intervals lists the
    inter-trip interval lengths (block layover candidates; empty when
    block_id is None).
    """
    vehicle_id = f"veh-{vehicle_index}"
    n_trips = draw(st.integers(min_value=1, max_value=3))
    block_id = f"blk-{vehicle_index}" if draw(st.booleans()) else None
    t = T0
    positions: list[VehiclePosition] = []
    clean_flags: list[bool] = []
    intervals: list[int] = []
    for trip in range(n_trips):
        if trip > 0:
            gap = draw(inter_trip_seconds)
            if block_id is not None:
                intervals.append(gap)
            t = t + timedelta(seconds=gap)
        trip_id = f"trip-{vehicle_index}-{trip}"
        n = draw(st.integers(min_value=2, max_value=6))
        for i in range(n):
            positions.append(
                VehiclePosition(
                    time=t,
                    vehicle_id=vehicle_id,
                    trip_id=trip_id,
                    latitude=40.0,
                    longitude=-75.0,
                    source_record_id=f"rec-{vehicle_index}-{trip}-{i:03d}",
                    block_id=block_id,
                )
            )
            if i < n - 1:
                t = t + timedelta(seconds=draw(spacing_seconds))
        gapped = draw(st.booleans())
        if gapped:
            t = t + timedelta(
                seconds=GAP_THRESHOLD_SECONDS + draw(extra_gap_seconds)
            )
            positions.append(
                VehiclePosition(
                    time=t,
                    vehicle_id=vehicle_id,
                    trip_id=trip_id,
                    latitude=40.0,
                    longitude=-75.0,
                    source_record_id=f"rec-{vehicle_index}-{trip}-gap",
                    block_id=block_id,
                )
            )
        clean_flags.append(not gapped)
    return positions, block_id is not None, tuple(clean_flags), tuple(intervals)


@st.composite
def fleet_schedule(draw, max_vehicles: int = 3):
    """Independent vehicles' schedules; returns (flat_positions, vehicles)
    where vehicles is a list of (positions, has_block, clean_flags,
    intervals) per vehicle."""
    n_vehicles = draw(st.integers(min_value=1, max_value=max_vehicles))
    vehicles = [draw(vehicle_schedule(v)) for v in range(n_vehicles)]
    positions = [p for pts, _, _, _ in vehicles for p in pts]
    return positions, vehicles


def _clean_adjacent_intervals(vehicles) -> list[int]:
    """Inter-trip intervals whose BOTH bounding trips are clean, block
    vehicles only — exactly the intervals v0.4 may count as layover."""
    eligible: list[int] = []
    for _, has_block, flags, intervals in vehicles:
        if not has_block:
            continue
        for i, seconds in enumerate(intervals):
            if flags[i] and flags[i + 1]:
                eligible.append(seconds)
    return eligible


def _trip_counts(vehicles) -> tuple[int, int]:
    total = sum(len(flags) for _, _, flags, _ in vehicles)
    excised = sum(1 for _, _, flags, _ in vehicles for ok in flags if not ok)
    return total, excised


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_monotonicity_v04_never_below_v02_on_any_input(data):
    """v0.4 VRH >= v0.2 VRH on IDENTICAL input, gaps included: the excision
    unit is the same trip, and v0.4 only adds capped, non-negative
    clean-adjacent layover time."""
    positions, _ = data
    v04 = compute_vrh(positions, coverage_threshold=NEVER_BLOCK)
    v02 = compute_vrh_v0_2(positions, coverage_threshold=NEVER_BLOCK)
    assert v04.blocking_issues == () and v02.blocking_issues == ()
    assert v04.value >= v02.value
    # Identical lineage: both include exactly the clean trips' records.
    assert set(v04.input_record_ids) == set(v02.input_record_ids)


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_monotonicity_v04_never_below_v03_on_any_input(data):
    """v0.4 VRH >= v0.3 VRH on IDENTICAL input: block-level exclusion is
    strictly harsher — it also drops the gapped block's clean trips and
    their layover intervals."""
    positions, _ = data
    v04 = compute_vrh(positions, coverage_threshold=NEVER_BLOCK)
    v03 = compute_vrh_v0_3(positions, coverage_threshold=NEVER_BLOCK)
    assert v04.blocking_issues == () and v03.blocking_issues == ()
    assert v04.value >= v03.value
    # v0.3's lineage never exceeds v0.4's: whole-block exclusion drops
    # every record trip-level excision would have kept.
    assert set(v03.input_record_ids) <= set(v04.input_record_ids)


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_layover_cap_zero_collapses_to_v02_exactly(data):
    """layover_max_seconds=0 counts no inter-trip time: the v0.4 figure
    equals the retained v0.2 figure exactly, and every positive
    clean-adjacent in-block interval is warned as over-cap (never the
    excision-adjacent ones — those are dropped, not warned)."""
    positions, vehicles = data
    capped = compute_vrh(
        positions, coverage_threshold=NEVER_BLOCK, layover_max_seconds=0
    )
    v02 = compute_vrh_v0_2(positions, coverage_threshold=NEVER_BLOCK)
    assert capped.value == v02.value
    over_cap = [w for w in capped.warnings if w.issue_type == "layover_exceeds_max"]
    assert len(over_cap) == len(_clean_adjacent_intervals(vehicles))


@given(
    fleet_schedule(),
    st.integers(min_value=0, max_value=3600),
    st.integers(min_value=0, max_value=3600),
)
@settings(max_examples=100, deadline=None)
def test_figure_monotone_in_layover_cap_and_bounded(data, cap_a, cap_b):
    """Raising the cap never lowers the figure; the layover contribution is
    exactly the clean-adjacent intervals <= cap; over-cap clean-adjacent
    intervals are warned."""
    positions, vehicles = data
    lo, hi = sorted((cap_a, cap_b))
    result_lo = compute_vrh(
        positions, coverage_threshold=NEVER_BLOCK, layover_max_seconds=lo
    )
    result_hi = compute_vrh(
        positions, coverage_threshold=NEVER_BLOCK, layover_max_seconds=hi
    )
    assert result_lo.value <= result_hi.value

    # Exact accounting at cap hi over the cap-0 baseline, to within the two
    # 0.01 h quantizations.
    baseline = compute_vrh(
        positions, coverage_threshold=NEVER_BLOCK, layover_max_seconds=0
    )
    eligible_intervals = _clean_adjacent_intervals(vehicles)
    eligible = sum(s for s in eligible_intervals if s <= hi)
    expected_delta = Decimal(eligible) / Decimal(3600)
    assert abs((result_hi.value - baseline.value) - expected_delta) <= Decimal("0.01")
    over_cap = [w for w in result_hi.warnings if w.issue_type == "layover_exceeds_max"]
    assert len(over_cap) == sum(1 for s in eligible_intervals if s > hi)


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_one_warning_per_excised_trip_citing_that_trips_records(data):
    positions, vehicles = data
    total, excised = _trip_counts(vehicles)
    result = compute_vrh(positions, coverage_threshold=NEVER_BLOCK)
    gap_warnings = [
        w for w in result.warnings if w.issue_type == "telemetry_gap_excluded"
    ]
    assert len(gap_warnings) == excised
    # Each warning cites exactly ONE trip's records; together they cite the
    # gapped trips' records and nothing else.
    by_trip: dict[tuple[str, str], set[str]] = {}
    for p in positions:
        by_trip.setdefault((p.vehicle_id, p.trip_id), set()).add(p.source_record_id)
    warned = [frozenset(w.source_record_ids) for w in gap_warnings]
    gapped_trip_records = [
        frozenset(recs)
        for recs in by_trip.values()
        if any(rid.endswith("-gap") for rid in recs)
    ]
    assert sorted(warned, key=sorted) == sorted(gapped_trip_records, key=sorted)
    assert result.detail.total_trips == total
    assert result.detail.trips_excised == excised


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_determinism_same_input_identical_result(data):
    positions, _ = data
    r1 = compute_vrh(positions)
    r2 = compute_vrh(positions)
    assert r1 == r2  # frozen dataclasses: full structural equality


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_input_order_irrelevant(data):
    positions, _ = data
    assert compute_vrh(positions) == compute_vrh(list(reversed(positions)))


@given(
    fleet_schedule(max_vehicles=4),
    st.decimals(
        min_value="0", max_value="1", places=2, allow_nan=False, allow_infinity=False
    ),
)
@settings(max_examples=100, deadline=None)
def test_blocking_implies_none_and_tracks_the_exact_trip_threshold_line(
    data, threshold
):
    """Retained 0.2.0 invariant, now over TRIPS: coverage below the exact
    threshold line blocks with ONE coverage_below_threshold finding and
    value=None; at/above it, a value always stands."""
    positions, vehicles = data
    total, excised = _trip_counts(vehicles)
    clean = total - excised
    should_block = Decimal(clean) < threshold * Decimal(total)
    result = compute_vrh(positions, coverage_threshold=threshold)
    assert bool(result.blocking_issues) == should_block
    if result.blocking_issues:
        assert result.value is None
        assert len(result.blocking_issues) == 1
        assert result.blocking_issues[0].issue_type == "coverage_below_threshold"
        assert result.blocking_issues[0].severity == "blocking"
    else:
        assert result.value is not None
    assert result.detail.total_trips == total
    assert result.detail.trips_excised == excised
