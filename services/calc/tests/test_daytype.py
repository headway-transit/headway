"""Unit tests for headway_calc.daytype (handoff 0020): classification,
Days Operated, day-type averages, splits, refusal inheritance, per-mode
scoping and the attestation pass-through."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.attestation import AttestationContext
from headway_calc.daytype import (
    DAYTYPE_VERSION,
    SPLIT_ATYPICAL,
    SPLIT_TYPICAL,
    classify_days,
    compute_days_operated,
    compute_daytype_upt_avg,
    compute_daytype_upt_avg_by_mode,
    scope_for_daytype,
)
from headway_calc.types import (
    PassengerEvent,
    ServiceDayOverride,
    VehiclePosition,
)

UTC = timezone.utc
PERIOD = (date(2026, 7, 1), date(2026, 7, 8))  # Wed 1 .. Tue 7 (half-open)


def override(day, assigned=None, atypical=False, reason="declared"):
    return ServiceDayOverride(
        service_date=day,
        assigned_day_type=assigned,
        atypical=atypical,
        reason=reason,
        updated_by="certifier",
        updated_at=datetime(2026, 6, 30, tzinfo=UTC),
    )


def pos(day, hour, vehicle="v1", trip="t1", rid=None, mode=None):
    return VehiclePosition(
        time=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
        vehicle_id=vehicle,
        trip_id=trip,
        latitude=42.0,
        longitude=-71.0,
        source_record_id=rid or f"p-{day.isoformat()}-{vehicle}-{hour}",
        mode=mode,
    )


def board(day, hour, pid, trip="t1", count=10, source="tides", mode=None):
    return PassengerEvent(
        event_timestamp=datetime(day.year, day.month, day.day, hour, tzinfo=UTC),
        service_date=day,
        passenger_event_id=pid,
        vehicle_id="v1",
        trip_id=trip,
        trip_stop_sequence=1,
        event_type="Passenger boarded",
        event_count=count,
        source=source,
        source_record_id=f"r-{pid}",
        mode=mode,
    )


# ---------------------------------------------------------------------------
# classification (daytype_v0 0.1.0)
# ---------------------------------------------------------------------------


def test_day_of_week_classification_and_period_bounds():
    cls = classify_days(*PERIOD, [])
    assert len(cls) == 7
    assert cls[date(2026, 7, 1)].day_type == "weekday"  # Wednesday
    assert cls[date(2026, 7, 4)].day_type == "saturday"
    assert cls[date(2026, 7, 5)].day_type == "sunday"
    assert all(not c.atypical and c.override is None for c in cls.values())


def test_override_reassigns_and_flags():
    ov = override(date(2026, 7, 3), assigned="sunday")
    ov2 = override(date(2026, 7, 6), atypical=True)
    cls = classify_days(*PERIOD, [ov, ov2])
    assert cls[date(2026, 7, 3)].day_type == "sunday"
    assert cls[date(2026, 7, 3)].override is ov
    assert cls[date(2026, 7, 6)].day_type == "weekday"  # flag only
    assert cls[date(2026, 7, 6)].atypical is True


def test_overrides_outside_the_period_are_ignored():
    cls = classify_days(*PERIOD, [override(date(2026, 8, 1), assigned="sunday")])
    assert all(c.override is None for c in cls.values())


def test_duplicate_override_dates_refuse():
    with pytest.raises(ValueError, match="Two service-day overrides"):
        classify_days(
            *PERIOD,
            [
                override(date(2026, 7, 3), assigned="sunday"),
                override(date(2026, 7, 3), atypical=True),
            ],
        )


def test_empty_or_inverted_period_refuses():
    with pytest.raises(ValueError, match="empty/inverted"):
        classify_days(date(2026, 7, 1), date(2026, 7, 1), [])


def test_meaningless_or_invalid_override_rows_refuse():
    with pytest.raises(ValueError, match="meaningless"):
        override(date(2026, 7, 3))  # neither reassigns nor flags
    with pytest.raises(ValueError, match="assigned_day_type"):
        override(date(2026, 7, 3), assigned="holiday")
    with pytest.raises(ValueError, match="reason"):
        override(date(2026, 7, 3), assigned="sunday", reason="   ")


def test_scope_grammar():
    assert scope_for_daytype("weekday") == "daytype:weekday"
    assert (
        scope_for_daytype("saturday", SPLIT_ATYPICAL)
        == "daytype:saturday:atypical"
    )
    assert (
        scope_for_daytype("sunday", SPLIT_TYPICAL, "bus")
        == "mode:bus:daytype:sunday"
    )
    assert (
        scope_for_daytype("sunday", SPLIT_ATYPICAL, "bus")
        == "mode:bus:daytype:sunday:atypical"
    )


# ---------------------------------------------------------------------------
# daytype_days_operated_v0
# ---------------------------------------------------------------------------


def test_days_operated_counts_observed_days_and_warns_unobserved():
    positions = [
        pos(date(2026, 7, 1), 8),
        pos(date(2026, 7, 4), 8, trip="t2"),
    ]
    results = compute_days_operated(positions, *PERIOD, [])
    assert results["weekday"].value == Decimal(1)
    assert results["saturday"].value == Decimal(1)
    assert results["sunday"].value == Decimal(0)
    for r in results.values():
        assert r.blocking_issues == ()  # blocking-free by design
    # The period's ONLY saturday (2026-07-04) is observed -> no warning;
    # weekday and sunday have unobserved dates -> warned lower bounds.
    assert results["saturday"].warnings == ()
    for day_type in ("weekday", "sunday"):
        assert [w.issue_type for w in results[day_type].warnings] == [
            "daytype_days_unobserved"
        ]
    detail = results["weekday"].detail.to_dict()
    assert detail["days_in_period_of_type"] == 5
    assert detail["unobserved_dates"] == [
        "2026-07-02", "2026-07-03", "2026-07-06", "2026-07-07",
    ]
    assert detail["daytype_version"] == DAYTYPE_VERSION
    assert detail["atypical_flags_declared"] is False


def test_days_operated_ignores_unassigned_positions_and_no_warning_when_full():
    # Only 2026-07-04 is a saturday; observe it and every other day type
    # date too -> no unobserved warning anywhere.
    positions = []
    d = PERIOD[0]
    while d < PERIOD[1]:
        positions.append(pos(d, 8, trip=f"t-{d.day}"))
        d = date(2026, 7, d.day + 1)
    positions.append(  # unassigned: never counts a day on its own
        VehiclePosition(
            time=datetime(2026, 7, 2, 9, tzinfo=UTC),
            vehicle_id="vX",
            trip_id=None,
            latitude=42.0,
            longitude=-71.0,
            source_record_id="p-unassigned",
        )
    )
    results = compute_days_operated(positions, *PERIOD, [])
    assert all(r.warnings == () for r in results.values())
    assert results["weekday"].value == Decimal(5)


def test_days_operated_lineage_is_the_earliest_in_trip_record_per_day():
    d = date(2026, 7, 1)
    positions = [
        pos(d, 9, vehicle="v2", rid="later"),
        pos(d, 8, vehicle="v1", rid="earliest"),
    ]
    result = compute_days_operated(positions, *PERIOD, [])["weekday"]
    assert list(result.input_record_ids) == ["earliest"]


def test_days_operated_holiday_reassignment_moves_the_count():
    ov = override(date(2026, 7, 3), assigned="sunday")  # Friday -> sunday
    positions = [pos(date(2026, 7, 3), 8)]
    results = compute_days_operated(positions, *PERIOD, [ov])
    assert results["sunday"].value == Decimal(1)
    assert results["weekday"].value == Decimal(0)
    sunday_detail = results["sunday"].detail.to_dict()
    assert sunday_detail["overrides_applied"] == [ov.to_provenance_dict()]


# ---------------------------------------------------------------------------
# daytype_upt_avg_v0
# ---------------------------------------------------------------------------


def test_average_is_mean_of_per_day_upt_quantized_once():
    positions = [
        pos(date(2026, 7, 1), 8, trip="t1"),
        pos(date(2026, 7, 2), 8, trip="t2"),
        pos(date(2026, 7, 6), 8, trip="t3"),
    ]
    events = [
        board(date(2026, 7, 1), 9, "e1", trip="t1", count=10),
        board(date(2026, 7, 2), 9, "e2", trip="t2", count=11),
        board(date(2026, 7, 6), 9, "e3", trip="t3", count=13),
    ]
    result = compute_daytype_upt_avg(events, positions, *PERIOD, [])[
        ("weekday", SPLIT_TYPICAL)
    ]
    # (10 + 11 + 13) / 3 = 11.333... -> 11.33 (0.01 ROUND_HALF_EVEN, once).
    assert result.value == Decimal("11.33")
    detail = result.detail.to_dict()
    assert detail["sum_upt"] == "34"
    assert detail["days_operated"] == 3


def test_atypical_days_are_excluded_from_typical_and_get_their_own_split():
    ov = override(date(2026, 7, 2), atypical=True, reason="parade")
    positions = [
        pos(date(2026, 7, 1), 8, trip="t1"),
        pos(date(2026, 7, 2), 8, trip="t2"),
    ]
    events = [
        board(date(2026, 7, 1), 9, "e1", trip="t1", count=10),
        board(date(2026, 7, 2), 9, "e2", trip="t2", count=99),
    ]
    results = compute_daytype_upt_avg(events, positions, *PERIOD, [ov])
    typical = results[("weekday", SPLIT_TYPICAL)]
    atypical = results[("weekday", SPLIT_ATYPICAL)]
    assert typical.value == Decimal("10.00")
    assert atypical.value == Decimal("99.00")
    assert typical.detail.to_dict()["atypical_flags_declared"] is True
    # No declared atypical saturday/sunday -> no atypical splits for them.
    assert ("saturday", SPLIT_ATYPICAL) not in results
    assert ("sunday", SPLIT_ATYPICAL) not in results


def test_unflagged_period_states_all_typical_and_emits_no_atypical_split():
    positions = [pos(date(2026, 7, 1), 8)]
    events = [board(date(2026, 7, 1), 9, "e1")]
    results = compute_daytype_upt_avg(events, positions, *PERIOD, [])
    assert set(results) == {
        ("weekday", SPLIT_TYPICAL),
        ("saturday", SPLIT_TYPICAL),
        ("sunday", SPLIT_TYPICAL),
    }
    detail = results[("weekday", SPLIT_TYPICAL)].detail.to_dict()
    assert detail["atypical_flags_declared"] is False
    assert detail["atypical_dates"] == []


def test_zero_operated_days_refuses_never_zero_fills():
    results = compute_daytype_upt_avg([], [], *PERIOD, [])
    for result in results.values():
        assert result.value is None
        assert [b.issue_type for b in result.blocking_issues] == [
            "daytype_no_operated_days"
        ]
        assert "never invented" in result.blocking_issues[0].description


def test_refused_day_refuses_the_split_with_propagated_receipts():
    positions = [
        pos(date(2026, 7, 1), 8, trip="t1"),
        pos(date(2026, 7, 1), 9, vehicle="v2", trip="t2"),
        pos(date(2026, 7, 2), 8, trip="t3"),
    ]
    # Day 1: t2 has no events -> missing share 1/2 > 0.02 -> day refuses.
    events = [
        board(date(2026, 7, 1), 9, "e1", trip="t1", count=10),
        board(date(2026, 7, 2), 9, "e2", trip="t3", count=20),
    ]
    result = compute_daytype_upt_avg(events, positions, *PERIOD, [])[
        ("weekday", SPLIT_TYPICAL)
    ]
    assert result.value is None
    types = [b.issue_type for b in result.blocking_issues]
    assert types[0] == "daytype_average_over_refused_days"
    assert "apc_missing_trips_above_fta_threshold" in types
    assert "2026-07-01" in result.blocking_issues[0].description
    # The clean day's accounting still travels in the detail.
    per_day = result.detail.to_dict()["per_day"]
    assert [d["blocked"] for d in per_day] == [True, False]


def test_per_day_warnings_propagate_date_prefixed():
    positions = [pos(date(2026, 7, 1), 8, trip="t1")]
    # Boardings without alightings -> p. 151 imbalance warning on the day.
    events = [board(date(2026, 7, 1), 9, "e1", trip="t1", count=10)]
    result = compute_daytype_upt_avg(events, positions, *PERIOD, [])[
        ("weekday", SPLIT_TYPICAL)
    ]
    assert result.value == Decimal("10.00")
    assert [w.issue_type for w in result.warnings] == ["apc_count_imbalance"]
    assert result.warnings[0].title.startswith("[2026-07-01]")


def test_simulated_sources_aggregate_to_one_info():
    positions = [
        pos(date(2026, 7, 1), 8, trip="t1"),
        pos(date(2026, 7, 2), 8, trip="t2"),
    ]
    events = [
        board(date(2026, 7, 1), 9, "e1", trip="t1", source="tides_simulated"),
        board(date(2026, 7, 2), 9, "e2", trip="t2", source="tides_simulated"),
    ]
    result = compute_daytype_upt_avg(events, positions, *PERIOD, [])[
        ("weekday", SPLIT_TYPICAL)
    ]
    infos = [i for i in result.infos if i.issue_type == "simulated_source_data"]
    assert len(infos) == 1  # ONE aggregated info, not one per day
    assert "tides_simulated" in infos[0].title
    assert result.detail.to_dict()["source_mix"] == {"tides_simulated": 2}


def test_attestation_selector_receives_the_result_scope_and_day():
    positions = [
        pos(date(2026, 7, 1), 8, trip="t1"),
        pos(date(2026, 7, 1), 9, vehicle="v2", trip="t2"),
    ]
    events = [board(date(2026, 7, 1), 9, "e1", trip="t1", count=10)]
    attestation = AttestationContext(
        attestation_id="7",
        statistician_name="Dr. Q. Statistician",
        statistician_credentials="MS Statistics",
        method_description="uniform factor-up",
        document_reference="doc-1",
        metric="upt",
        scope_pattern="daytype:*",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 8, 1),
        entered_by="certifier",
        entered_at=datetime(2026, 6, 30, tzinfo=UTC),
        revoked_at=None,
    )
    calls: list[tuple[str, date]] = []

    def selector(scope, d):
        calls.append((scope, d))
        return (attestation,) if scope == "daytype:weekday" else ()

    result = compute_daytype_upt_avg(
        events, positions, *PERIOD, [], attestations_for_day=selector
    )[("weekday", SPLIT_TYPICAL)]
    assert ("daytype:weekday", date(2026, 7, 1)) in calls
    # >2% missing share WITH a governing attestation: factored, not refused,
    # and the attestation provenance rides the day's accounting.
    assert result.value == Decimal("20.00")  # 10 x 2/1 (factor 2), one day
    per_day = result.detail.to_dict()["per_day"]
    assert per_day[0]["attestation"]["attestation_id"] == "7"


# ---------------------------------------------------------------------------
# per-mode scoping
# ---------------------------------------------------------------------------


def test_per_mode_buckets_and_unknown_mode_never_dropped():
    d = date(2026, 7, 1)
    positions = [
        pos(d, 8, vehicle="v1", trip="t-bus", mode="bus"),
        pos(d, 8, vehicle="v2", trip="t-null", mode=None),
    ]
    events = [
        board(d, 9, "e1", trip="t-bus", count=10, mode="bus"),
        board(d, 9, "e2", trip="t-null", count=5, mode=None),
    ]
    results = compute_daytype_upt_avg_by_mode(events, positions, *PERIOD, [])
    assert results[("bus", "weekday", SPLIT_TYPICAL)].value == Decimal("10.00")
    assert results[("unknown", "weekday", SPLIT_TYPICAL)].value == Decimal(
        "5.00"
    )
