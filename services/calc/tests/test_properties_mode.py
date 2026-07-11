"""Hypothesis property tests for the handoff-0009 per-mode compute paths.

The spec-4 additivity property — per-mode values sum to the fleet value for
the additive metrics vrm/vrh/upt on identical input — with the quantization
caveat made explicit:

- VRH: EXACT equality on a strategy whose time deltas are multiples of 36 s
  (36 s = 0.01 h, the reported quantum), so every subset's exact sum
  quantizes without drift;
- UPT: EXACT equality on fully-covered fleets (integer counts, factor 1
  everywhere). With missing trips the p. 146 factor-up applies PER MODE on
  the mode path (mode-average boardings) vs FLEET-WIDE on the agency path
  (fleet-average) — sums may legitimately differ, pinned by a concrete
  construction (the tracker's documented fleet-wide-factor limitation; the
  per-mode figure is the one closer to the manual's per-mode totals);
- VRM: haversine sums are floats, so post-quantization additivity is not an
  algebraic identity — the property asserts the documented bound
  |fleet - sum(per-mode)| <= 0.005 x (n_buckets + 1) (each figure is
  quantized once, half-even, to 0.01 mi), with EXACT equality pinned by the
  mode_scope golden;
- PARTITION: every mode-scoped path consumes each input row exactly once —
  the per-mode lineage union equals the fleet lineage on clean input.

voms is NOT additive (max != sum) — see test_properties_voms.py.

Hypothesis is test-only — the library itself contains no randomness.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from headway_calc.mode import (
    compute_upt_by_mode,
    compute_vrh_by_mode,
    compute_vrm_by_mode,
)
from headway_calc.types import PassengerEvent, VehiclePosition
from headway_calc.upt import compute_upt
from headway_calc.vrh import compute_vrh
from headway_calc.vrm import compute_vrm

T0 = datetime(2026, 7, 1, 6, 0, tzinfo=timezone.utc)
SERVICE_DATE = date(2026, 7, 1)
MODES = ("bus", "subway", "ferry")


@st.composite
def fleets_on_the_36s_grid(draw):
    """Per mode: 0-3 vehicles, one trip each, 2-6 positions whose deltas are
    multiples of 36 s (= the 0.01 h VRH quantum) and <= 288 s (< the 300 s
    gap threshold: everything clean). Colocated coordinates keep VRM at 0 —
    this strategy drives the VRH exactness property."""
    positions: list[VehiclePosition] = []
    rid = 0
    for mode in MODES:
        for v in range(draw(st.integers(min_value=0, max_value=3))):
            vehicle = f"veh-{mode}-{v}"
            trip = f"trip-{mode}-{v}"
            t = T0
            n = draw(st.integers(min_value=2, max_value=6))
            for k in range(n):
                if k:
                    t = t + timedelta(
                        seconds=36 * draw(st.integers(min_value=1, max_value=8))
                    )
                rid += 1
                positions.append(
                    VehiclePosition(
                        time=t,
                        vehicle_id=vehicle,
                        trip_id=trip,
                        latitude=40.0,
                        longitude=-75.0,
                        source_record_id=f"rec-{rid:04d}",
                        mode=mode,
                    )
                )
    return positions


@st.composite
def meridian_fleets(draw):
    """Per mode: 0-3 vehicles, one clean trip each, positions stepping up a
    meridian in 0.001-0.02 degree legs at 60 s spacing — real nonzero
    haversine distances for the VRM near-additivity bound."""
    positions: list[VehiclePosition] = []
    rid = 0
    for mode in MODES:
        for v in range(draw(st.integers(min_value=0, max_value=3))):
            vehicle = f"veh-{mode}-{v}"
            trip = f"trip-{mode}-{v}"
            lat = draw(
                st.floats(min_value=-60.0, max_value=60.0, allow_nan=False)
            )
            n = draw(st.integers(min_value=2, max_value=6))
            for k in range(n):
                rid += 1
                positions.append(
                    VehiclePosition(
                        time=T0 + timedelta(seconds=60 * k),
                        vehicle_id=vehicle,
                        trip_id=trip,
                        latitude=lat
                        + k * draw(st.floats(min_value=0.001, max_value=0.02)),
                        longitude=-75.0,
                        source_record_id=f"rec-{rid:04d}",
                        mode=mode,
                    )
                )
    return positions


@st.composite
def fully_covered_fleets(draw):
    """Per mode: 0-4 operated trips, EVERY trip covered by 1-3 boarding
    events with integer counts (no missing trips anywhere -> factor 1 on
    the fleet AND in every mode: the exact-additivity regime)."""
    positions: list[VehiclePosition] = []
    events: list[PassengerEvent] = []
    rid = 0
    for mode in MODES:
        for tnum in range(draw(st.integers(min_value=0, max_value=4))):
            trip = f"trip-{mode}-{tnum}"
            vehicle = f"veh-{mode}-{tnum}"
            rid += 1
            positions.append(
                VehiclePosition(
                    time=T0,
                    vehicle_id=vehicle,
                    trip_id=trip,
                    latitude=40.0,
                    longitude=-75.0,
                    source_record_id=f"rec-p-{rid:04d}",
                    mode=mode,
                )
            )
            for e in range(draw(st.integers(min_value=1, max_value=3))):
                rid += 1
                events.append(
                    PassengerEvent(
                        event_timestamp=T0 + timedelta(seconds=rid),
                        service_date=SERVICE_DATE,
                        passenger_event_id=f"pe-{rid:04d}",
                        vehicle_id=vehicle,
                        trip_id=trip,
                        trip_stop_sequence=e + 1,
                        event_type="Passenger boarded",
                        event_count=draw(st.integers(min_value=0, max_value=50)),
                        source="tides",
                        source_record_id=f"rec-e-{rid:04d}",
                        mode=mode,
                    )
                )
    return positions, events


@given(fleets_on_the_36s_grid())
@settings(max_examples=100, deadline=None)
def test_vrh_per_mode_values_sum_exactly_to_fleet_on_the_quantum_grid(positions):
    fleet = compute_vrh(positions)
    by_mode = compute_vrh_by_mode(positions)
    assert fleet.blocking_issues == ()
    assert sum((r.value for r in by_mode.values()), Decimal(0)) == fleet.value
    # Same math per subset: the mode results carry the unchanged version.
    assert all(r.calc_version == "0.4.0" for r in by_mode.values())


@given(meridian_fleets())
@settings(max_examples=100, deadline=None)
def test_vrm_per_mode_sum_matches_fleet_within_the_quantization_bound(positions):
    """Each figure is quantized ONCE to 0.01 mi (half-even, max error
    0.005), so |fleet - sum| is bounded by 0.005 x (buckets + 1). Exact
    equality is pinned by the mode_scope golden, not asserted here — it is
    not an algebraic identity of independently quantized sums."""
    fleet = compute_vrm(positions)
    by_mode = compute_vrm_by_mode(positions)
    assert fleet.blocking_issues == ()
    mode_sum = sum((r.value for r in by_mode.values()), Decimal(0))
    bound = Decimal("0.005") * (len(by_mode) + 1)
    assert abs(fleet.value - mode_sum) <= bound


@given(meridian_fleets())
@settings(max_examples=100, deadline=None)
def test_per_mode_lineage_partitions_the_fleet_lineage(positions):
    fleet = compute_vrm(positions)
    by_mode = compute_vrm_by_mode(positions)
    union: set[str] = set()
    total = 0
    for result in by_mode.values():
        union.update(result.input_record_ids)
        total += len(result.input_record_ids)
    assert union == set(fleet.input_record_ids)
    assert total == len(union)  # each record consumed by exactly one mode


@given(fully_covered_fleets())
@settings(max_examples=100, deadline=None)
def test_upt_per_mode_values_sum_exactly_to_fleet_when_nothing_is_missing(data):
    positions, events = data
    operated = sorted({p.trip_id for p in positions if p.trip_id is not None})
    fleet = compute_upt(events, operated)
    by_mode = compute_upt_by_mode(events, positions)
    assert fleet.blocking_issues == ()
    assert sum((r.value for r in by_mode.values()), Decimal(0)) == fleet.value
    assert all(r.detail.factor_applied == Decimal("1.000000") for r in by_mode.values())


def test_upt_factor_up_differs_fleet_wide_vs_per_mode_pinned():
    """Concrete pin: with missing trips the fleet-wide p. 146 factor-up
    spreads a bus data gap at the FLEET average boardings while the per-mode
    path uses the BUS average — 498 vs 500. This is the tracker's documented
    upt_v0 fleet-wide-factor limitation surfacing; the per-mode figure is
    the one aligned with the manual's per-mode totals."""

    def _boarding(pid, trip, vehicle, count, mode, rid):
        return PassengerEvent(
            event_timestamp=T0 + timedelta(seconds=int(pid.split("-")[-1])),
            service_date=SERVICE_DATE,
            passenger_event_id=pid,
            vehicle_id=vehicle,
            trip_id=trip,
            trip_stop_sequence=1,
            event_type="Passenger boarded",
            event_count=count,
            source="tides",
            source_record_id=rid,
            mode=mode,
        )

    def _position(trip, vehicle, mode, rid):
        return VehiclePosition(
            time=T0,
            vehicle_id=vehicle,
            trip_id=trip,
            latitude=40.0,
            longitude=-75.0,
            source_record_id=rid,
            mode=mode,
        )

    positions: list[VehiclePosition] = []
    events: list[PassengerEvent] = []
    seq = 0
    # bus: 100 operated trips, 2 missing, 98 covered x 2 boardings = 196.
    for k in range(100):
        positions.append(_position(f"trip-bus-{k:03d}", f"veh-b-{k:03d}", "bus", f"rp-b-{k:03d}"))
        if k >= 2:  # trips 000 and 001 stay missing
            seq += 1
            events.append(
                _boarding(f"pe-{seq:04d}", f"trip-bus-{k:03d}", f"veh-b-{k:03d}", 2, "bus", f"re-b-{k:03d}")
            )
    # subway: 300 operated trips, all covered x 1 boarding = 300.
    for k in range(300):
        positions.append(_position(f"trip-sub-{k:03d}", f"veh-s-{k:03d}", "subway", f"rp-s-{k:03d}"))
        seq += 1
        events.append(
            _boarding(f"pe-{seq:04d}", f"trip-sub-{k:03d}", f"veh-s-{k:03d}", 1, "subway", f"re-s-{k:03d}")
        )
    operated = sorted({p.trip_id for p in positions})
    fleet = compute_upt(events, operated)
    by_mode = compute_upt_by_mode(events, positions)

    # Fleet: counted 496, 2 of 400 missing (share 0.005 <= 0.02) ->
    # 496 x 400/398 = 498.49... -> 498 (half-even to whole boardings).
    assert fleet.value == Decimal("498")
    # Per mode: bus 196 x 100/98 = 200 exactly; subway 300 (nothing missing).
    assert by_mode["bus"].value == Decimal("200")
    assert by_mode["subway"].value == Decimal("300")
    assert by_mode["bus"].value + by_mode["subway"].value == Decimal("500")
    assert fleet.value != by_mode["bus"].value + by_mode["subway"].value
