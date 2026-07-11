"""Hypothesis property tests for voms_v0 CALC_VERSION 0.1.0 (handoff 0009).

Invariants over generated fleets of vehicle-day observations:

- DETERMINISM / ORDER-INDEPENDENCE: same observations -> structurally
  identical result, regardless of input order;
- DEFINITIONAL: the value IS max over days of distinct in-trip vehicles
  (recomputed independently), an integer >= 0;
- MONOTONICITY: adding a vehicle-day observation NEVER decreases the value
  (a maximum only grows as observations are added);
- BLOCKING-FREE: no input ever produces a blocking finding (an observation
  gap can only understate a maximum); the partial-observation warning fires
  IFF days_observed < days_in_period;
- MODE BOUNDS (voms is NOT additive across modes):
  max(per-mode) <= fleet <= sum(per-mode) — max != sum in general, pinned by
  a concrete two-mode construction whose modes peak on different days.

Hypothesis is test-only — the library itself contains no randomness.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc.mode import compute_voms_by_mode
from headway_calc.types import VehiclePosition
from headway_calc.voms import compute_voms

PERIOD_START = date(2026, 7, 1)
PERIOD_END = date(2026, 7, 8)  # 7 days
DAYS = (PERIOD_END - PERIOD_START).days

MODES = ("bus", "subway", None)  # None -> the 'unknown' bucket


def _pos(day_index: int, vehicle: str, rid: str, mode: str | None) -> VehiclePosition:
    return VehiclePosition(
        time=datetime(2026, 7, 1 + day_index, 9, 0, tzinfo=timezone.utc),
        vehicle_id=vehicle,
        trip_id=f"trip-{vehicle}-{day_index}",
        latitude=40.0,
        longitude=-75.0,
        source_record_id=rid,
        mode=mode,
    )


@st.composite
def observations(draw):
    """A set of (day_index, vehicle, mode) vehicle-day observations rendered
    as in-trip positions (possibly several per vehicle-day)."""
    obs = draw(
        st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=DAYS - 1),
                st.integers(min_value=0, max_value=9),
                st.sampled_from(MODES),
            ),
            min_size=0,
            max_size=40,
        )
    )
    positions = [
        _pos(day, f"veh-{veh:02d}", f"rec-{k:03d}", mode)
        for k, (day, veh, mode) in enumerate(obs)
    ]
    return positions


def _expected_max(positions) -> int:
    per_day: dict[date, set[str]] = {}
    for p in positions:
        if p.trip_id is not None:
            per_day.setdefault(p.time.astimezone(timezone.utc).date(), set()).add(
                p.vehicle_id
            )
    return max((len(v) for v in per_day.values()), default=0)


@given(observations())
@settings(max_examples=100, deadline=None)
def test_determinism_and_order_independence(positions):
    r1 = compute_voms(positions, PERIOD_START, PERIOD_END)
    r2 = compute_voms(list(reversed(positions)), PERIOD_START, PERIOD_END)
    assert r1 == r2  # frozen dataclasses: full structural equality


@given(observations())
@settings(max_examples=100, deadline=None)
def test_value_is_max_of_daily_distinct_vehicle_counts(positions):
    result = compute_voms(positions, PERIOD_START, PERIOD_END)
    assert result.value == Decimal(_expected_max(positions))
    assert result.value >= 0
    assert result.value == result.value.to_integral_value()  # integer


@given(observations(), st.integers(min_value=0, max_value=DAYS - 1),
       st.integers(min_value=0, max_value=15))
@settings(max_examples=100, deadline=None)
def test_adding_a_vehicle_day_never_decreases_voms(positions, day, veh):
    """The spec-4 monotonicity property: one more observed vehicle-day can
    only raise (or keep) the maximum."""
    extra = _pos(day, f"veh-extra-{veh:02d}", "rec-extra", "bus")
    before = compute_voms(positions, PERIOD_START, PERIOD_END)
    after = compute_voms(positions + [extra], PERIOD_START, PERIOD_END)
    assert after.value >= before.value


@given(observations())
@settings(max_examples=100, deadline=None)
def test_blocking_free_and_partial_warning_iff_days_missing(positions):
    result = compute_voms(positions, PERIOD_START, PERIOD_END)
    assert result.blocking_issues == ()  # NEVER blocks, by design
    assert result.value is not None  # a maximum (possibly 0) always stands
    observed_days = {
        p.time.astimezone(timezone.utc).date()
        for p in positions
        if p.trip_id is not None
    }
    should_warn = len(observed_days) < DAYS
    warning_types = [w.issue_type for w in result.warnings]
    assert (warning_types == ["voms_partial_observation"]) == should_warn
    if not should_warn:
        assert result.warnings == ()


@given(observations())
@settings(max_examples=100, deadline=None)
def test_fleet_voms_bounded_by_per_mode_max_and_sum(positions):
    """voms is NOT additive across modes: modes may peak on different days,
    so only the bounds max(per-mode) <= fleet <= sum(per-mode) hold."""
    fleet = compute_voms(positions, PERIOD_START, PERIOD_END)
    by_mode = compute_voms_by_mode(positions, PERIOD_START, PERIOD_END)
    if not by_mode:
        assert fleet.value == Decimal(0)
        return
    per_mode_values = [r.value for r in by_mode.values()]
    assert max(per_mode_values) <= fleet.value <= sum(per_mode_values)


def test_voms_max_is_not_sum_across_modes_pinned():
    """Concrete pin (spec 4): two modes peaking on DIFFERENT days — the
    per-mode maxima sum to 6 while the fleet maximum is 4: max != sum."""
    positions = (
        # bus peaks day 0 with 3 vehicles, day 1 has 1
        [_pos(0, f"veh-b{k}", f"rec-b0-{k}", "bus") for k in range(3)]
        + [_pos(1, "veh-b0", "rec-b1-0", "bus")]
        # subway peaks day 1 with 3 vehicles, day 0 has 1
        + [_pos(0, "veh-s0", "rec-s0-0", "subway")]
        + [_pos(1, f"veh-s{k}", f"rec-s1-{k}", "subway") for k in range(3)]
    )
    fleet = compute_voms(positions, PERIOD_START, PERIOD_END)
    by_mode = compute_voms_by_mode(positions, PERIOD_START, PERIOD_END)
    assert by_mode["bus"].value == Decimal(3)
    assert by_mode["subway"].value == Decimal(3)
    assert fleet.value == Decimal(4)  # each day has 4 distinct vehicles
    assert fleet.value != by_mode["bus"].value + by_mode["subway"].value
    assert (
        max(by_mode["bus"].value, by_mode["subway"].value)
        <= fleet.value
        <= by_mode["bus"].value + by_mode["subway"].value
    )
