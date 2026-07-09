"""Hypothesis property tests for vrm_v0 / vrh_v0 CALC_VERSION 0.1.0.

Invariants: non-negativity, additivity across group partitions (no gaps),
determinism, and gap-refusal. Hypothesis is test-only — the library itself
contains no randomness.

Pinned to the RETAINED 0.1.0 functions (compute_vrm_v0_1/compute_vrh_v0_1 —
all-or-nothing gap refusal), aliased to the names below so the test bodies are
byte-identical to the 0.1.0 originals. The 0.2.0 gap-policy invariants live in
test_properties_v02.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc._grouping import GAP_THRESHOLD_SECONDS
from headway_calc.types import VehiclePosition
from headway_calc.vrh import compute_vrh_v0_1 as compute_vrh
from headway_calc.vrm import compute_vrm_v0_1 as compute_vrm

T0 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

# Small coordinate deltas keep the geometry well-conditioned; spacing is kept
# strictly within the gap threshold so "clean" strategies never trip the gap rule.
coord_delta = st.floats(min_value=-0.02, max_value=0.02, allow_nan=False, allow_infinity=False)
spacing_seconds = st.integers(min_value=1, max_value=int(GAP_THRESHOLD_SECONDS))


@st.composite
def clean_group(draw, vehicle_id: str, trip_id: str, id_prefix: str):
    """A single (vehicle, trip) group with no telemetry gaps."""
    n = draw(st.integers(min_value=1, max_value=8))
    lat = draw(st.floats(min_value=-60.0, max_value=60.0, allow_nan=False, allow_infinity=False))
    lon = draw(st.floats(min_value=-179.0, max_value=179.0, allow_nan=False, allow_infinity=False))
    t = T0
    positions = []
    for i in range(n):
        positions.append(
            VehiclePosition(
                time=t,
                vehicle_id=vehicle_id,
                trip_id=trip_id,
                latitude=lat,
                longitude=lon,
                source_record_id=f"{id_prefix}-{i:03d}",
            )
        )
        t = t + timedelta(seconds=draw(spacing_seconds))
        lat = min(90.0, max(-90.0, lat + draw(coord_delta)))
        lon = min(180.0, max(-180.0, lon + draw(coord_delta)))
    return positions


@st.composite
def clean_groups(draw, max_groups: int = 4):
    """A list of independent gap-free groups (distinct (vehicle, trip) keys)."""
    n_groups = draw(st.integers(min_value=1, max_value=max_groups))
    return [
        draw(clean_group(f"veh-{g}", f"trip-{g}", f"rec-{g}"))
        for g in range(n_groups)
    ]


@given(clean_groups())
@settings(max_examples=100, deadline=None)
def test_non_negativity(groups):
    flat = [p for g in groups for p in g]
    for compute in (compute_vrm, compute_vrh):
        result = compute(flat)
        assert result.blocking_issues == ()
        assert result.value is not None
        assert result.value >= Decimal("0")


@given(clean_groups())
@settings(max_examples=100, deadline=None)
def test_additivity_over_group_partition(groups):
    """VRM/VRH over the union of groups == sum over each group (no gaps).

    Additivity holds to within the final 0.01 quantization: each per-group
    quantization introduces at most half a quantum of error.
    """
    flat = [p for g in groups for p in g]
    for compute in (compute_vrm, compute_vrh):
        whole = compute(flat).value
        parts = sum((compute(g).value for g in groups), Decimal("0"))
        tolerance = Decimal("0.005") * len(groups) + Decimal("0.005")
        assert abs(whole - parts) <= tolerance


@given(clean_groups())
@settings(max_examples=100, deadline=None)
def test_determinism_same_input_identical_result(groups):
    flat = [p for g in groups for p in g]
    for compute in (compute_vrm, compute_vrh):
        r1 = compute(flat)
        r2 = compute(flat)
        assert r1 == r2  # frozen dataclasses: full structural equality


@given(clean_groups())
@settings(max_examples=100, deadline=None)
def test_input_order_irrelevant(groups):
    flat = [p for g in groups for p in g]
    for compute in (compute_vrm, compute_vrh):
        assert compute(flat).value == compute(list(reversed(flat))).value


@given(clean_group("veh-g", "trip-g", "rec-g"), st.integers(min_value=1, max_value=86400))
@settings(max_examples=100, deadline=None)
def test_gap_refusal(group, extra_gap_seconds):
    """Injecting a >threshold gap forces value=None + a telemetry_gap issue."""
    gap = timedelta(seconds=GAP_THRESHOLD_SECONDS + extra_gap_seconds)
    last = group[-1]
    gapped = group + [
        VehiclePosition(
            time=last.time + gap,
            vehicle_id=last.vehicle_id,
            trip_id=last.trip_id,
            latitude=last.latitude,
            longitude=last.longitude,
            source_record_id="rec-after-gap",
        )
    ]
    for compute in (compute_vrm, compute_vrh):
        result = compute(gapped)
        assert result.value is None
        assert any(i.issue_type == "telemetry_gap" for i in result.blocking_issues)
        issue = result.blocking_issues[-1]
        assert issue.source_record_ids == (last.source_record_id, "rec-after-gap")
