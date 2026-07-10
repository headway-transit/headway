"""Hypothesis property tests for vrm_v0 / vrh_v0 CALC_VERSION 0.2.0.

Gap-policy invariants (handoff 0002): the figure over included groups equals
the sum of per-group values (and exactly equals the figure over the clean
groups alone), excluding a group never increases the figure, coverage stays
in [0, 1], results are deterministic, and blocking findings imply value=None
(the certifiability line, exact at the threshold). Hypothesis is test-only —
the library itself contains no randomness.

VRH is pinned to the RETAINED 0.2.0 function (compute_vrh_v0_2 — superseded
as the default by the block-aware 0.3.0 per handoff 0003), aliased to the
name below so the test bodies are byte-identical to the 0.2.0 originals. The
0.3.0 invariants live in test_properties_v03.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc._grouping import GAP_THRESHOLD_SECONDS
from headway_calc.types import VehiclePosition
from headway_calc.vrh import compute_vrh_v0_2 as compute_vrh
from headway_calc.vrm import compute_vrm

T0 = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

#: A coverage threshold of 0 never blocks — it isolates the exclusion
#: arithmetic from the certifiability line in the invariants below.
NEVER_BLOCK = Decimal("0")

# Small coordinate deltas keep the geometry well-conditioned; spacing is kept
# strictly within the gap threshold so "clean" strategies never trip the gap rule.
coord_delta = st.floats(min_value=-0.02, max_value=0.02, allow_nan=False, allow_infinity=False)
spacing_seconds = st.integers(min_value=1, max_value=int(GAP_THRESHOLD_SECONDS))
extra_gap_seconds = st.integers(min_value=1, max_value=86400)


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
def gapped_group(draw, vehicle_id: str, trip_id: str, id_prefix: str):
    """A clean group with one over-threshold gap appended: always excluded."""
    group = draw(clean_group(vehicle_id, trip_id, id_prefix))
    last = group[-1]
    gap = timedelta(seconds=GAP_THRESHOLD_SECONDS + draw(extra_gap_seconds))
    group.append(
        VehiclePosition(
            time=last.time + gap,
            vehicle_id=last.vehicle_id,
            trip_id=last.trip_id,
            latitude=last.latitude,
            longitude=last.longitude,
            source_record_id=f"{id_prefix}-after-gap",
        )
    )
    return group


@st.composite
def mixed_groups(draw, max_groups: int = 4):
    """Independent groups (distinct keys), each clean or gapped; returns
    (groups, gapped_flags) so tests know the expected exclusions."""
    n_groups = draw(st.integers(min_value=1, max_value=max_groups))
    flags = draw(st.lists(st.booleans(), min_size=n_groups, max_size=n_groups))
    groups = []
    for g, is_gapped in enumerate(flags):
        strategy = gapped_group if is_gapped else clean_group
        groups.append(draw(strategy(f"veh-{g}", f"trip-{g}", f"rec-{g}")))
    return groups, flags


@given(mixed_groups())
@settings(max_examples=100, deadline=None)
def test_value_over_included_groups_equals_sum_of_per_group_values(data):
    """The figure equals (a) EXACTLY the figure over the clean groups alone
    (exclusion == removal) and (b) the sum of per-group values to within the
    per-group 0.01 quantization."""
    groups, flags = data
    flat = [p for g in groups for p in g]
    clean = [g for g, is_gapped in zip(groups, flags) if not is_gapped]
    flat_clean = [p for g in clean for p in g]
    for compute in (compute_vrm, compute_vrh):
        whole = compute(flat, coverage_threshold=NEVER_BLOCK)
        assert whole.value is not None
        # (a) exact: excluded groups contribute nothing.
        assert whole.value == compute(flat_clean, coverage_threshold=NEVER_BLOCK).value
        # (b) additive over the included-group partition, within quantization.
        parts = sum(
            (compute(g, coverage_threshold=NEVER_BLOCK).value for g in clean),
            Decimal("0"),
        )
        tolerance = Decimal("0.005") * len(clean) + Decimal("0.005")
        assert abs(whole.value - parts) <= tolerance
        # Provenance narrows correctly: included groups' records only.
        expected_ids = {p.source_record_id for p in flat_clean}
        assert set(whole.input_record_ids) == expected_ids


@given(mixed_groups(), extra_gap_seconds)
@settings(max_examples=100, deadline=None)
def test_excluding_a_group_never_increases_the_figure(data, extra):
    """Gapping one more group (so it becomes excluded) never raises the value."""
    groups, _ = data
    flat = [p for g in groups for p in g]
    last = groups[0][-1]
    gap = timedelta(seconds=GAP_THRESHOLD_SECONDS + extra)
    flat_more_excluded = flat + [
        VehiclePosition(
            time=last.time + gap,
            vehicle_id=last.vehicle_id,
            trip_id=last.trip_id,
            latitude=last.latitude,
            longitude=last.longitude,
            source_record_id="rec-extra-after-gap",
        )
    ]
    for compute in (compute_vrm, compute_vrh):
        before = compute(flat, coverage_threshold=NEVER_BLOCK).value
        after = compute(flat_more_excluded, coverage_threshold=NEVER_BLOCK).value
        assert after <= before


@given(mixed_groups())
@settings(max_examples=100, deadline=None)
def test_coverage_within_unit_interval_and_counts_exact(data):
    groups, flags = data
    flat = [p for g in groups for p in g]
    for compute in (compute_vrm, compute_vrh):
        detail = compute(flat, coverage_threshold=NEVER_BLOCK).detail
        assert Decimal("0") <= detail.coverage <= Decimal("1")
        assert Decimal("0") <= detail.clean_position_share <= Decimal("1")
        assert detail.total_groups == len(groups)
        assert detail.excluded_groups == sum(flags)


@given(mixed_groups())
@settings(max_examples=100, deadline=None)
def test_determinism_same_input_identical_result(data):
    groups, _ = data
    flat = [p for g in groups for p in g]
    for compute in (compute_vrm, compute_vrh):
        r1 = compute(flat)
        r2 = compute(flat)
        assert r1 == r2  # frozen dataclasses: full structural equality


@given(
    mixed_groups(),
    st.decimals(min_value="0", max_value="1", places=2, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=100, deadline=None)
def test_blocking_implies_none_and_tracks_the_exact_threshold_line(data, threshold):
    groups, flags = data
    flat = [p for g in groups for p in g]
    total = len(groups)
    clean = total - sum(flags)
    should_block = Decimal(clean) < threshold * Decimal(total)
    for compute in (compute_vrm, compute_vrh):
        result = compute(flat, coverage_threshold=threshold)
        assert bool(result.blocking_issues) == should_block
        if result.blocking_issues:
            assert result.value is None
            assert len(result.blocking_issues) == 1
            assert result.blocking_issues[0].issue_type == "coverage_below_threshold"
            assert result.blocking_issues[0].severity == "blocking"
        else:
            assert result.value is not None
        # Warnings carry their own severity regardless of the blocking outcome.
        assert len(result.warnings) == sum(flags)
        assert all(w.severity == "warning" for w in result.warnings)
