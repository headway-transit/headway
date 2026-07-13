"""Hypothesis property tests for the dr_*_v0 calcs CALC_VERSION 0.1.0
(handoff 0013).

Invariants over generated dispatch days:

- DETERMINISM / ORDER-INDEPENDENCE: same trips -> structurally identical
  results, regardless of input order;
- BLOCKING-FREE: no input ever produces a blocking finding (no completeness
  threshold is quoted for DR — every gap is a warning with its direction
  stated);
- TOS DECOMPOSITION: for the additive metrics (vrh/vrm/upt/pmt), the
  per-TOS values sum to the mode-level value — mixed vehicle-days are
  excluded identically everywhere (the vehicle-day-granular partition).
  UPT (integer) decomposes EXACTLY; the quantized metrics decompose within
  the documented final-quantization slack (each result quantizes once at
  0.01, so parts can each carry up to half a quantum of rounding);
- VOMS BOUNDS (not additive): max(per-TOS) <= mode <= sum(per-TOS);
- NO-SHOW ASYMMETRY: adding a marker-free no-show visit NEVER changes UPT
  and NEVER decreases revenue hours (Exhibit 36: revenue yes, boarding no).

Hypothesis is test-only — the library itself contains no randomness.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc.dr import (
    compute_dr_pmt,
    compute_dr_pmt_by_tos,
    compute_dr_upt,
    compute_dr_upt_by_tos,
    compute_dr_voms,
    compute_dr_voms_by_tos,
    compute_dr_vrh,
    compute_dr_vrh_by_tos,
    compute_dr_vrm,
    compute_dr_vrm_by_tos,
)
from headway_calc.types import DrTrip

DAY = date(2026, 7, 14)
BASE = datetime(2026, 7, 14, 6, 0, tzinfo=timezone.utc)

_ADDITIVE = (
    (compute_dr_vrh, compute_dr_vrh_by_tos),
    (compute_dr_vrm, compute_dr_vrm_by_tos),
    (compute_dr_upt, compute_dr_upt_by_tos),
    (compute_dr_pmt, compute_dr_pmt_by_tos),
)
_ALL = tuple(c for c, _ in _ADDITIVE) + (compute_dr_voms,)


@st.composite
def dispatch_days(draw):
    """A list of DrTrips across a few vehicles: varying TOS (mixed
    vehicle-days possible), shared rides, no-shows, interruption markers,
    and partially missing distance data."""
    n = draw(st.integers(min_value=0, max_value=12))
    trips: list[DrTrip] = []
    for i in range(n):
        vehicle = f"van-{draw(st.integers(min_value=0, max_value=3))}"
        tos = draw(st.sampled_from(["DO", "PT", "TX", "TN"]))
        start_min = draw(st.integers(min_value=0, max_value=600))
        duration = draw(st.integers(min_value=0, max_value=90))
        no_show = draw(st.booleans()) and draw(st.booleans())  # ~25%
        riders = 0 if no_show else draw(st.integers(min_value=0, max_value=4))
        attendants = 0 if no_show else draw(st.integers(min_value=0, max_value=2))
        has_distance = draw(st.booleans())
        onboard = (
            None
            if not has_distance
            else Decimal(draw(st.integers(min_value=0, max_value=200))) / 10
        )
        marker = draw(
            st.sampled_from(
                ["none", "none", "none", "lunch", "fuel", "garage_return"]
            )
        )
        sponsored = draw(st.booleans()) and not no_show
        trips.append(
            DrTrip(
                pickup_timestamp=BASE + timedelta(minutes=start_min),
                service_date=DAY,
                dr_trip_id=f"t-{i}",
                vehicle_id=vehicle,
                tos=tos,
                dropoff_timestamp=BASE + timedelta(minutes=start_min + duration),
                riders=riders,
                attendants_companions=attendants,
                ada_related=draw(st.booleans()),
                sponsored=sponsored,
                sponsor="Sponsor X" if sponsored else None,
                no_show=no_show,
                onboard_miles=onboard,
                interruption_after=marker,
                source=draw(st.sampled_from(["dr", "dr_simulated"])),
                source_record_id=f"rec-{i}",
            )
        )
    return trips


@settings(max_examples=60, deadline=None)
@given(dispatch_days(), st.randoms(use_true_random=False))
def test_order_independence_and_blocking_free(trips, rng):
    shuffled = list(trips)
    rng.shuffle(shuffled)
    for compute in _ALL:
        a, b = compute(trips), compute(shuffled)
        assert a == b
        assert a.blocking_issues == ()
        assert a.value is not None and a.value >= 0


@settings(max_examples=60, deadline=None)
@given(dispatch_days())
def test_tos_values_sum_to_mode_value_for_additive_metrics(trips):
    # UPT is an integer count: exact decomposition.
    upt_parts = compute_dr_upt_by_tos(trips)
    assert compute_dr_upt(trips).value == sum(
        (r.value for r in upt_parts.values()), Decimal(0)
    )
    # The quantized metrics decompose within the final-quantization slack:
    # every result (mode + each part) quantizes once at 0.01 ROUND_HALF_EVEN,
    # so the difference is bounded by half a quantum per figure involved.
    for compute, by_tos in ((compute_dr_vrh, compute_dr_vrh_by_tos),
                            (compute_dr_vrm, compute_dr_vrm_by_tos),
                            (compute_dr_pmt, compute_dr_pmt_by_tos)):
        mode_value = compute(trips).value
        parts = by_tos(trips)
        slack = Decimal("0.005") * (len(parts) + 1)
        assert abs(
            mode_value - sum((r.value for r in parts.values()), Decimal(0))
        ) <= slack


@settings(max_examples=60, deadline=None)
@given(dispatch_days())
def test_voms_bounds_across_tos(trips):
    mode_value = compute_dr_voms(trips).value
    parts = compute_dr_voms_by_tos(trips)
    if parts:
        assert max(r.value for r in parts.values()) <= mode_value
        assert mode_value <= sum(r.value for r in parts.values())
    else:
        assert mode_value == 0


@settings(max_examples=60, deadline=None)
@given(dispatch_days(), st.integers(min_value=0, max_value=600))
def test_no_show_never_boards_and_never_reduces_revenue_time(trips, start_min):
    """Adding a marker-free no-show visit to a marker-free vehicle's day:
    UPT identical, revenue hours never lower (the Exhibit 36 asymmetry as a
    law, not just a fixture)."""
    marker_free = [t for t in trips if t.interruption_after == "none"]
    no_show = DrTrip(
        pickup_timestamp=BASE + timedelta(minutes=start_min),
        service_date=DAY,
        dr_trip_id="t-ns-extra",
        vehicle_id="van-0",
        tos="DO",
        dropoff_timestamp=BASE + timedelta(minutes=start_min + 5),
        riders=0,
        attendants_companions=0,
        ada_related=False,
        sponsored=False,
        no_show=True,
        source="dr",
        source_record_id="rec-ns-extra",
    )
    # Keep van-0's day DO-uniform so the addition cannot create a mixed-TOS
    # exclusion (which may legitimately change both figures).
    base = [t for t in marker_free if not (t.vehicle_id == "van-0" and t.tos != "DO")]
    assert compute_dr_upt(base + [no_show]).value == compute_dr_upt(base).value
    assert compute_dr_vrh(base + [no_show]).value >= compute_dr_vrh(base).value
