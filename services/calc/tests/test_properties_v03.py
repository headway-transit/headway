"""Hypothesis property tests for vrh_v0 CALC_VERSION 0.3.0 (handoff 0003).

Block-policy invariants over gap-free schedules (block schedules generated
with clean trips, arbitrary inter-trip intervals):
- MONOTONICITY: v0.3 VRH >= v0.2 VRH on identical input — block grouping can
  only ADD (capped, non-negative) layover time to the per-trip sum;
- the layover cap is respected: cap 0 collapses v0.3 to the v0.2 value
  exactly, the figure is monotone in layover_max_seconds, and every over-cap
  in-block interval emits one layover_exceeds_max warning;
- determinism (full structural equality);
- blocking-implies-None retained, exact at the coverage threshold line over
  BLOCK groups (mixed clean/gapped schedules).

Note (documented divergence-by-design): under WITHIN-TRIP gaps the exclusion
unit becomes the whole block group, so v0.3 >= v0.2 is only claimed for
gap-free input — see test_vrh_v03.py for the gapped-block regression.
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

# Pinned to the RETAINED 0.3.0 function (handoff 0004: 0.4.0 is the default
# compute_vrh; shipped versions recompute bit-for-bit) — bodies unchanged.
from headway_calc.vrh import compute_vrh_v0_2
from headway_calc.vrh import compute_vrh_v0_3 as compute_vrh

T0 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

#: A coverage threshold of 0 never blocks — it isolates the block arithmetic
#: from the certifiability line (same convention as the 0.2.0 suite).
NEVER_BLOCK = Decimal("0")

# Spacing kept strictly within the gap threshold so "clean" trips never trip
# the within-trip gap rule; inter-trip intervals range past the layover cap.
spacing_seconds = st.integers(min_value=1, max_value=int(GAP_THRESHOLD_SECONDS))
inter_trip_seconds = st.integers(min_value=1, max_value=2 * int(LAYOVER_MAX_SECONDS))
extra_gap_seconds = st.integers(min_value=1, max_value=86400)


@st.composite
def vehicle_schedule(draw, vehicle_index: int):
    """One vehicle's day: 1–3 sequential clean trips, all sharing one block
    (or none — the per-trip fallback). Returns (positions, in_block_intervals)
    where in_block_intervals lists the inter-trip interval lengths that block
    membership makes layover (empty when block_id is None)."""
    vehicle_id = f"veh-{vehicle_index}"
    n_trips = draw(st.integers(min_value=1, max_value=3))
    block_id = f"blk-{vehicle_index}" if draw(st.booleans()) else None
    t = T0
    positions: list[VehiclePosition] = []
    intervals: list[int] = []
    for trip in range(n_trips):
        if trip > 0:
            gap = draw(inter_trip_seconds)
            if block_id is not None:
                intervals.append(gap)
            t = t + timedelta(seconds=gap)
        n = draw(st.integers(min_value=2, max_value=6))
        for i in range(n):
            positions.append(
                VehiclePosition(
                    time=t,
                    vehicle_id=vehicle_id,
                    trip_id=f"trip-{vehicle_index}-{trip}",
                    latitude=40.0,
                    longitude=-75.0,
                    source_record_id=f"rec-{vehicle_index}-{trip}-{i:03d}",
                    block_id=block_id,
                )
            )
            if i < n - 1:
                t = t + timedelta(seconds=draw(spacing_seconds))
    return positions, intervals


@st.composite
def fleet_schedule(draw, max_vehicles: int = 3):
    """Independent vehicles' schedules; returns (flat_positions, intervals)."""
    n_vehicles = draw(st.integers(min_value=1, max_value=max_vehicles))
    positions: list[VehiclePosition] = []
    intervals: list[int] = []
    for v in range(n_vehicles):
        pts, ivals = draw(vehicle_schedule(v))
        positions.extend(pts)
        intervals.extend(ivals)
    return positions, intervals


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_monotonicity_v03_never_below_v02(data):
    """v0.3 VRH >= v0.2 VRH on identical (gap-free) input: block grouping
    only ADDS capped, non-negative layover time to the per-trip sum."""
    positions, _ = data
    v03 = compute_vrh(positions)
    v02 = compute_vrh_v0_2(positions)
    assert v03.blocking_issues == () and v02.blocking_issues == ()
    assert v03.value >= v02.value
    # Identical lineage: block grouping regroups, it never drops records.
    assert set(v03.input_record_ids) == set(v02.input_record_ids)


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_layover_cap_zero_collapses_to_v02_exactly(data):
    """layover_max_seconds=0 counts no inter-trip time: the v0.3 figure
    equals the retained v0.2 figure exactly, and every positive in-block
    interval is warned as over-cap."""
    positions, intervals = data
    capped = compute_vrh(positions, layover_max_seconds=0)
    v02 = compute_vrh_v0_2(positions)
    assert capped.value == v02.value
    over_cap = [w for w in capped.warnings if w.issue_type == "layover_exceeds_max"]
    assert len(over_cap) == len(intervals)


@given(fleet_schedule(), st.integers(min_value=0, max_value=3600), st.integers(min_value=0, max_value=3600))
@settings(max_examples=100, deadline=None)
def test_figure_monotone_in_layover_cap_and_bounded(data, cap_a, cap_b):
    """Raising the cap never lowers the figure; the layover contribution is
    bounded by the eligible intervals; over-cap intervals are warned."""
    positions, intervals = data
    lo, hi = sorted((cap_a, cap_b))
    result_lo = compute_vrh(positions, layover_max_seconds=lo)
    result_hi = compute_vrh(positions, layover_max_seconds=hi)
    assert result_lo.value <= result_hi.value

    # Exact accounting at cap hi: counted layover == sum of intervals <= hi,
    # so the delta over the cap-0 baseline matches to within quantization.
    baseline = compute_vrh(positions, layover_max_seconds=0)
    eligible = sum(s for s in intervals if s <= hi)
    expected_delta = Decimal(eligible) / Decimal(3600)
    assert abs((result_hi.value - baseline.value) - expected_delta) <= Decimal("0.01")
    over_cap = [w for w in result_hi.warnings if w.issue_type == "layover_exceeds_max"]
    assert len(over_cap) == sum(1 for s in intervals if s > hi)


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


@given(fleet_schedule())
@settings(max_examples=100, deadline=None)
def test_block_unavailable_infos_exactly_for_null_block_vehicles(data):
    """One info per NULL-block vehicle-day (all schedules are single-day),
    none for vehicles with a block; the figure always stands."""
    positions, _ = data
    result = compute_vrh(positions)
    null_block_vehicles = {p.vehicle_id for p in positions if p.block_id is None}
    assert len(result.infos) == len(null_block_vehicles)
    assert all(i.issue_type == "block_unavailable" for i in result.infos)
    assert all(i.severity == "info" for i in result.infos)
    assert result.value is not None


@st.composite
def mixed_fleet(draw, max_vehicles: int = 4):
    """Vehicles with an optional WITHIN-TRIP gap injected into their last
    trip; returns (positions, expected_total_groups, expected_excluded)."""
    n_vehicles = draw(st.integers(min_value=1, max_value=max_vehicles))
    positions: list[VehiclePosition] = []
    total_groups = 0
    excluded_groups = 0
    for v in range(n_vehicles):
        pts, _ = draw(vehicle_schedule(v))
        gapped = draw(st.booleans())
        trip_ids = {p.trip_id for p in pts}
        has_block = pts[0].block_id is not None
        total_groups += 1 if has_block else len(trip_ids)
        if gapped:
            last = max(pts, key=lambda p: p.time)
            gap = timedelta(seconds=GAP_THRESHOLD_SECONDS + draw(extra_gap_seconds))
            pts.append(
                VehiclePosition(
                    time=last.time + gap,
                    vehicle_id=last.vehicle_id,
                    trip_id=last.trip_id,
                    latitude=last.latitude,
                    longitude=last.longitude,
                    source_record_id=f"rec-{v}-after-gap",
                    block_id=last.block_id,
                )
            )
            # The exclusion unit is the whole block group (or the one trip).
            excluded_groups += 1
        positions.extend(pts)
    return positions, total_groups, excluded_groups


@given(
    mixed_fleet(),
    st.decimals(min_value="0", max_value="1", places=2, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, deadline=None)
def test_blocking_implies_none_and_tracks_the_exact_threshold_line(data, threshold):
    """Retained 0.2.0 invariant over BLOCK groups: coverage below the exact
    threshold line blocks with ONE coverage_below_threshold finding and
    value=None; at/above it, a value always stands."""
    positions, total, excluded = data
    clean = total - excluded
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
    assert result.detail.total_groups == total
    assert result.detail.excluded_groups == excluded
    gap_warnings = [
        w for w in result.warnings if w.issue_type == "telemetry_gap_excluded"
    ]
    assert len(gap_warnings) == excluded
