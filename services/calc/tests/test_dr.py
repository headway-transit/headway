"""Unit tests for headway_calc.dr (handoff 0013): the fail-loudly edges the
goldens do not exercise — contradictions, unmeasured/overlap distance
warnings, TOS partitioning of mixed vehicle-days, boundary conventions, and
DrTrip's own structural validation."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.dr import (
    DEADHEAD_LEG_TYPES,
    NO_DEADHEAD_TOS,
    compute_dr_pmt,
    compute_dr_upt,
    compute_dr_upt_by_tos,
    compute_dr_voms,
    compute_dr_vrh,
    compute_dr_vrh_by_tos,
    compute_dr_vrm,
    partition_by_tos,
)
from headway_calc.types import DrTrip

DAY = date(2026, 7, 14)


def _ts(hour, minute=0):
    return datetime(2026, 7, 14, hour, minute, tzinfo=timezone.utc)


def make_trip(
    trip_id,
    pickup,
    dropoff,
    *,
    vehicle="van-1",
    tos="DO",
    riders=1,
    attendants=0,
    ada=False,
    sponsored=False,
    sponsor=None,
    no_show=False,
    onboard=None,
    pickup_odo=None,
    dropoff_odo=None,
    interruption="none",
    source="dr",
):
    return DrTrip(
        pickup_timestamp=pickup,
        service_date=DAY,
        dr_trip_id=trip_id,
        vehicle_id=vehicle,
        tos=tos,
        dropoff_timestamp=dropoff,
        riders=riders,
        attendants_companions=attendants,
        ada_related=ada,
        sponsored=sponsored,
        sponsor=sponsor,
        no_show=no_show,
        onboard_miles=None if onboard is None else Decimal(onboard),
        pickup_odometer_miles=None if pickup_odo is None else Decimal(pickup_odo),
        dropoff_odometer_miles=None if dropoff_odo is None else Decimal(dropoff_odo),
        interruption_after=interruption,
        source=source,
        source_record_id=f"rec-{trip_id}",
    )


# --- DrTrip structural validation (bad canonical rows surface loudly) -------


def test_drtrip_refuses_contradictions():
    with pytest.raises(ValueError, match="dropoff precedes pickup"):
        make_trip("t-neg", _ts(10), _ts(9))
    with pytest.raises(ValueError, match="tos"):
        make_trip("t-tos", _ts(10), _ts(11), tos="XX")
    with pytest.raises(ValueError, match="interruption_after"):
        make_trip("t-int", _ts(10), _ts(11), interruption="coffee")
    with pytest.raises(ValueError, match="never a boarding"):
        make_trip("t-ns", _ts(10), _ts(11), no_show=True, riders=1)
    with pytest.raises(ValueError, match="timezone-aware"):
        make_trip("t-naive", datetime(2026, 7, 14, 10), _ts(11))
    with pytest.raises(ValueError, match=">= 0"):
        make_trip("t-odo", _ts(10), _ts(11), onboard="-1")


# --- empty input -------------------------------------------------------------


def test_empty_input_yields_zero_never_a_guess():
    for compute in (compute_dr_vrh, compute_dr_vrm, compute_dr_upt, compute_dr_voms, compute_dr_pmt):
        result = compute([])
        assert result.value == Decimal(0)
        assert result.blocking_issues == ()
        assert result.warnings == () and result.infos == ()
        assert result.input_record_ids == ()


def test_input_order_is_irrelevant():
    trips = [
        make_trip("t-1", _ts(8), _ts(8, 30), onboard="3", pickup_odo="0", dropoff_odo="3"),
        make_trip("t-2", _ts(9), _ts(9, 30), onboard="4", pickup_odo="5", dropoff_odo="9"),
        make_trip("t-3", _ts(10), _ts(10, 30), vehicle="van-2", onboard="5"),
    ]
    for compute in (compute_dr_vrh, compute_dr_vrm, compute_dr_upt, compute_dr_voms, compute_dr_pmt):
        assert compute(trips) == compute(list(reversed(trips)))


# --- exclusion contradictions -------------------------------------------------


def test_mixed_tos_vehicle_day_excluded_with_warning():
    trips = [
        make_trip("t-do", _ts(8), _ts(8, 30), tos="DO", onboard="3"),
        make_trip("t-tx", _ts(9), _ts(9, 30), tos="TX", onboard="4"),
        make_trip("t-ok", _ts(8), _ts(9), vehicle="van-2", tos="DO", onboard="5"),
    ]
    result = compute_dr_vrh(trips)
    # Only van-2 counts: 1 hour.
    assert result.value == Decimal("1.00")
    assert result.detail.vehicle_days == 2
    assert result.detail.vehicle_days_counted == 1
    assert result.detail.vehicle_days_excluded == 1
    (warning,) = result.warnings
    assert warning.issue_type == "dr_mixed_tos_vehicle_day"
    assert set(warning.source_record_ids) == {"rec-t-do", "rec-t-tx"}
    # Excluded records never in lineage.
    assert list(result.input_record_ids) == ["rec-t-ok"]


def test_mixed_tos_vehicle_day_excluded_in_every_tos_bucket_too():
    """partition_by_tos keeps a mixed vehicle-day WHOLE in every bucket it
    touches, so each per-TOS figure re-detects and re-excludes it — the
    per-TOS values stay the mode figure's decomposition (a split day would
    otherwise masquerade as uniform and be silently priced)."""
    trips = [
        make_trip("t-do", _ts(8), _ts(8, 30), tos="DO", onboard="3"),
        make_trip("t-tx", _ts(9), _ts(9, 30), tos="TX", onboard="4"),
        make_trip("t-ok", _ts(8), _ts(9), vehicle="van-2", tos="DO", onboard="5"),
    ]
    buckets = partition_by_tos(trips)
    assert {t.dr_trip_id for t in buckets["DO"]} == {"t-do", "t-tx", "t-ok"}
    assert {t.dr_trip_id for t in buckets["TX"]} == {"t-do", "t-tx"}

    by_tos = compute_dr_vrh_by_tos(trips)
    assert by_tos["DO"].value == Decimal("1.00")  # van-2 only
    assert by_tos["TX"].value == Decimal("0.00")  # mixed day excluded
    assert [w.issue_type for w in by_tos["DO"].warnings] == ["dr_mixed_tos_vehicle_day"]
    assert [w.issue_type for w in by_tos["TX"].warnings] == ["dr_mixed_tos_vehicle_day"]
    # Additivity across buckets holds (counted groups identical).
    assert compute_dr_vrh(trips).value == sum(r.value for r in by_tos.values())


def test_interruption_while_passenger_onboard_excludes_vehicle_day():
    trips = [
        # t-a marked 'lunch' at its 10:00 dropoff while t-b is onboard
        # (09:30 -> 10:30): contradictory data, never repaired.
        make_trip("t-a", _ts(9), _ts(10), interruption="lunch", onboard="3"),
        make_trip("t-b", _ts(9, 30), _ts(10, 30), onboard="4"),
    ]
    result = compute_dr_vrh(trips)
    assert result.value == Decimal("0.00")
    (warning,) = result.warnings
    assert warning.issue_type == "dr_interruption_during_ride"
    assert set(warning.source_record_ids) == {"rec-t-a", "rec-t-b"}
    assert result.input_record_ids == ()


def test_shared_ride_booked_after_marked_trip_stays_in_span():
    """A break takes effect at the marked trip's DROPOFF: a shared-ride
    booking picked up after the marked trip but dropped before its dropoff
    belongs to the current span (no phantom overlap across the break)."""
    trips = [
        # t-a 09:00-10:00 marked lunch; t-b 09:10-09:50 (inside t-a's
        # window); t-c 10:30-11:00 after lunch.
        make_trip("t-a", _ts(9), _ts(10), interruption="lunch"),
        make_trip("t-b", _ts(9, 10), _ts(9, 50)),
        make_trip("t-c", _ts(10, 30), _ts(11)),
    ]
    result = compute_dr_vrh(trips)
    # Span 1: 09:00-10:00 (t-a + t-b); span 2: 10:30-11:00 -> 1.5 h.
    assert result.value == Decimal("1.50")
    assert result.detail.revenue_spans == 2
    assert result.detail.interruption_breaks == {"lunch": 1}
    assert result.warnings == ()


# --- distance accounting edges ------------------------------------------------


def test_tx_overlap_without_boundary_odometers_summed_and_warned():
    trips = [
        make_trip("t-i", _ts(9), _ts(9, 30), tos="TX", onboard="6"),
        make_trip("t-j", _ts(9, 10), _ts(9, 40), tos="TX", onboard="6"),
    ]
    result = compute_dr_vrm(trips)
    # No boundary odometer pair: per-booking sum 12 (possible overcount).
    assert result.value == Decimal("12.00")
    assert result.detail.tx_summed_overlap_intervals == 1
    (warning,) = result.warnings
    assert warning.issue_type == "dr_tx_shared_distance_summed"
    assert "OVERCOUNT" in warning.description


def test_tx_no_show_contributes_nothing():
    trips = [
        make_trip("t-k", _ts(10), _ts(10, 20), tos="TX", onboard="4"),
        make_trip(
            "t-l", _ts(10, 30), _ts(10, 35), tos="TX", no_show=True, riders=0
        ),
    ]
    assert compute_dr_vrh(trips).value == Decimal("0.33")  # 20 min only
    assert compute_dr_vrm(trips).value == Decimal("4.00")
    assert compute_dr_upt(trips).value == Decimal("0") + Decimal("1")


def test_unmeasured_distances_warn_and_understate_never_guess():
    trips = [
        make_trip("t-g", _ts(9), _ts(9, 30)),  # no distance data at all
        make_trip("t-h", _ts(9, 45), _ts(10, 15), onboard="4.5"),
    ]
    result = compute_dr_vrm(trips)
    assert result.value == Decimal("4.50")
    assert result.detail.missing_onboard_distances == 1
    assert result.detail.unmeasured_empty_legs == 1
    (warning,) = result.warnings
    assert warning.issue_type == "dr_distance_unmeasured"
    assert "UNDERSTATES" in warning.description

    pmt = compute_dr_pmt(trips)
    assert pmt.value == Decimal("4.50")
    assert pmt.detail.trips_excluded_missing_distance == 1
    assert [w.issue_type for w in pmt.warnings] == ["dr_onboard_distance_missing"]
    # The excluded booking's record is cited by the warning, not lineage.
    assert "rec-t-g" not in pmt.input_record_ids
    assert pmt.warnings[0].source_record_ids == ("rec-t-g",)


# --- UPT splits ----------------------------------------------------------------


def test_upt_splits_and_sponsor_breakdown():
    trips = [
        make_trip("t-1", _ts(8), _ts(8, 30), riders=2, attendants=1, ada=True),
        make_trip(
            "t-2", _ts(9), _ts(9, 30), riders=1,
            sponsored=True, sponsor="Medicaid NEMT",
        ),
        make_trip(
            "t-3", _ts(10), _ts(10, 30), riders=3,
            sponsored=True, sponsor="Meals-On-Wheels",
        ),
    ]
    result = compute_dr_upt(trips)
    assert result.value == Decimal("7")
    detail = result.detail
    assert detail.ada_related_upt == 3
    assert detail.sponsored_upt == 4
    assert detail.sponsored_by_sponsor == {
        "Meals-On-Wheels": 3,
        "Medicaid NEMT": 1,
    }
    assert detail.ada_sponsored_conflicts == 0
    assert result.warnings == ()


def test_upt_ada_never_sponsored_conflict_warns_and_counts_as_ada():
    trips = [
        make_trip(
            "t-conflict", _ts(8), _ts(8, 30), riders=1,
            ada=True, sponsored=True, sponsor="Medicaid NEMT",
        ),
    ]
    result = compute_dr_upt(trips)
    assert result.value == Decimal("1")
    assert result.detail.ada_related_upt == 1
    assert result.detail.sponsored_upt == 0  # NEVER in the sponsored split
    (warning,) = result.warnings
    assert warning.issue_type == "dr_ada_sponsored_conflict"


# --- VOMS conventions -----------------------------------------------------------


def test_voms_closed_interval_boundary_counts_simultaneous():
    """Documented convention: intervals are closed — a vehicle ending at the
    instant another starts counts simultaneous at that instant."""
    trips = [
        make_trip("t-1", _ts(8), _ts(9), vehicle="van-1"),
        make_trip("t-2", _ts(9), _ts(10), vehicle="van-2"),
    ]
    result = compute_dr_voms(trips)
    assert result.value == Decimal("2")
    assert result.detail.peak_start == _ts(9).isoformat()


def test_voms_same_vehicle_never_double_counted():
    trips = [
        make_trip("t-1", _ts(8), _ts(9), interruption="lunch"),
        make_trip("t-2", _ts(10), _ts(11)),
    ]
    assert compute_dr_voms(trips).value == Decimal("1")


# --- simulated-source rule --------------------------------------------------------


def test_simulated_source_info_on_every_calc():
    trips = [
        make_trip("t-sim", _ts(8), _ts(8, 30), onboard="3", source="dr_simulated"),
    ]
    for compute in (compute_dr_vrh, compute_dr_vrm, compute_dr_upt, compute_dr_voms, compute_dr_pmt):
        result = compute(trips)
        (info,) = result.infos
        assert info.issue_type == "simulated_source_data"
        assert "dr_simulated" in info.title
        assert info.source_record_ids == ("rec-t-sim",)
        assert "NOT certifiable" in info.description


# --- documented regulatory vocabulary ----------------------------------------------


def test_deadhead_vocabulary_pinned():
    """The p. 130 leg types and the TX/TN no-deadhead rule are code-level
    vocabulary (classification only — measurement needs a shift-level feed,
    module docstring)."""
    assert len(DEADHEAD_LEG_TYPES) == 6
    assert NO_DEADHEAD_TOS == ("TX", "TN")


def test_upt_by_tos_partition_and_values():
    trips = [
        make_trip("t-do", _ts(8), _ts(8, 30), tos="DO", riders=2),
        make_trip("t-tn", _ts(9), _ts(9, 30), vehicle="van-2", tos="TN", riders=1),
    ]
    results = compute_dr_upt_by_tos(trips)
    assert sorted(results) == ["DO", "TN"]
    assert results["DO"].value == Decimal("2")
    assert results["TN"].value == Decimal("1")
