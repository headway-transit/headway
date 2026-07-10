"""Unit tests for headway_calc.upt (upt_v0 0.1.0, handoff 0005).

Covers: the verified-TIDES-enum base count (boarding events with a trip
assignment only — bike boardings and non-passenger event types never
counted); NULL event_count -> apc_null_count warning + 0, cited by the
warning instead of lineage; the p. 151 validations at their exact boundary
(imbalance strictly greater than 10%, negative load in stop-sequence order
with the NULL-sequence-last convention); the p. 146 missing-trip rule at its
exact boundary (2% factored, above 2% blocked, zero-operated degenerate
period); the simulated-source rule; and the whole-boarding rounding.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from headway_calc.types import PassengerEvent
from headway_calc.upt import (
    ALIGHTING_EVENT_TYPE,
    BOARDING_EVENT_TYPE,
    CALC_NAME,
    CALC_VERSION,
    UNIT,
    compute_upt,
)

T0 = datetime(2026, 6, 15, 8, 0, 0, tzinfo=timezone.utc)
SERVICE_DATE = date(2026, 6, 15)


def make_event(
    pid: str,
    *,
    minute: int = 0,
    trip_id: str | None = "trip-1",
    seq: int | None = 1,
    event_type: str = BOARDING_EVENT_TYPE,
    count: int | None = 1,
    source: str = "tides",
    vehicle_id: str = "veh-1",
    source_record_id: str | None = None,
) -> PassengerEvent:
    return PassengerEvent(
        event_timestamp=T0.replace(minute=minute // 60, second=minute % 60),
        service_date=SERVICE_DATE,
        passenger_event_id=pid,
        vehicle_id=vehicle_id,
        trip_id=trip_id,
        trip_stop_sequence=seq,
        event_type=event_type,
        event_count=count,
        source=source,
        source_record_id=source_record_id or f"rec-{pid}",
    )


# --- base count (p. 143) ------------------------------------------------------


def test_counts_boardings_with_trip_assignment_only():
    events = [
        make_event("e1", minute=0, count=5),
        make_event("e2", minute=1, count=3),
        make_event("e3", minute=2, trip_id=None, count=7),  # revenue proxy: out
    ]
    result = compute_upt(events, ["trip-1"])
    assert result.calc_name == CALC_NAME
    assert result.calc_version == CALC_VERSION
    assert result.unit == UNIT
    assert result.value == Decimal("8")
    assert result.detail.total_boardings_counted == 8
    # Lineage covers exactly the counted boarding events.
    assert result.input_record_ids == ("rec-e1", "rec-e2")


def test_non_boarding_event_types_never_counted():
    """Only the verified TIDES boarding value counts — alightings, door
    events and BIKE boardings (not passengers per p. 143) contribute 0."""
    events = [
        make_event("e1", minute=0, count=5),
        make_event("e2", minute=1, event_type=ALIGHTING_EVENT_TYPE, count=5),
        make_event("e3", minute=2, event_type="Door opened", count=1),
        make_event("e4", minute=3, event_type="Individual bike boarded", count=2),
    ]
    result = compute_upt(events, ["trip-1"])
    assert result.value == Decimal("5")
    assert result.input_record_ids == ("rec-e1",)


def test_duplicate_source_record_ids_deduplicated_in_lineage():
    events = [
        make_event("e1", minute=0, count=2),
        make_event("e2", minute=1, count=3, source_record_id="rec-e1"),  # same raw record
    ]
    result = compute_upt(events, ["trip-1"])
    assert result.value == Decimal("5")
    assert result.input_record_ids == ("rec-e1",)


# --- NULL event_count: never a guessed number --------------------------------


def test_null_boarding_count_warns_and_contributes_zero():
    events = [
        make_event("e1", minute=0, count=4),
        make_event("e2", minute=1, count=None),
    ]
    result = compute_upt(events, ["trip-1"])
    assert result.value == Decimal("4")  # NULL -> 0, never the TIDES default 1
    null_warnings = [w for w in result.warnings if w.issue_type == "apc_null_count"]
    assert len(null_warnings) == 1
    assert null_warnings[0].severity == "warning"
    assert null_warnings[0].source_record_ids == ("rec-e2",)
    # Cited by the warning INSTEAD of lineage.
    assert result.input_record_ids == ("rec-e1",)


def test_null_alighting_count_warns_too():
    """Alighting counts feed the p. 151 validations; a NULL there is warned
    in the same never-guess spirit."""
    events = [
        make_event("e1", minute=0, count=4),
        make_event("e2", minute=1, seq=2, event_type=ALIGHTING_EVENT_TYPE, count=None),
    ]
    result = compute_upt(events, ["trip-1"])
    null_warnings = [w for w in result.warnings if w.issue_type == "apc_null_count"]
    assert len(null_warnings) == 1
    assert null_warnings[0].source_record_ids == ("rec-e2",)


# --- p. 151: imbalance --------------------------------------------------------


def test_imbalance_exactly_ten_percent_not_flagged():
    """p. 151 flags a difference GREATER THAN 10 percent — the boundary
    itself passes (exact comparison, no quantized ratio)."""
    events = [
        make_event("e1", minute=0, count=10),
        make_event("e2", minute=1, seq=2, event_type=ALIGHTING_EVENT_TYPE, count=9),
    ]
    result = compute_upt(events, ["trip-1"])
    assert [w.issue_type for w in result.warnings] == []


def test_imbalance_above_ten_percent_flagged_per_trip():
    events = [
        make_event("e1", minute=0, count=10),
        make_event("e2", minute=1, seq=2, event_type=ALIGHTING_EVENT_TYPE, count=8),
        # a second, balanced trip stays unflagged
        make_event("e3", minute=2, trip_id="trip-2", count=5),
        make_event(
            "e4", minute=3, trip_id="trip-2", seq=2,
            event_type=ALIGHTING_EVENT_TYPE, count=5,
        ),
    ]
    result = compute_upt(events, ["trip-1", "trip-2"])
    imbalance = [w for w in result.warnings if w.issue_type == "apc_count_imbalance"]
    assert len(imbalance) == 1
    assert "trip-1" in imbalance[0].title
    assert imbalance[0].source_record_ids == ("rec-e1", "rec-e2")
    # The figure stands: warnings never force None.
    assert result.value == Decimal("15")


def test_imbalance_with_zero_boardings_and_alightings_present():
    """B=0, A>0: |0-A| > 10% x 0 = 0 -> flagged (alightings with no
    boardings are definitionally imbalanced — and the load goes negative)."""
    events = [
        make_event("e1", minute=0, event_type=ALIGHTING_EVENT_TYPE, count=3),
    ]
    result = compute_upt(events, ["trip-1"])
    assert [w.issue_type for w in result.warnings] == [
        "apc_count_imbalance",
        "apc_negative_load",
    ]


# --- p. 151: negative load ----------------------------------------------------


def test_negative_load_flagged_once_citing_first_drop():
    events = [
        make_event("e1", minute=0, seq=1, count=2),
        make_event("e2", minute=1, seq=2, event_type=ALIGHTING_EVENT_TYPE, count=5),
        make_event("e3", minute=2, seq=3, event_type=ALIGHTING_EVENT_TYPE, count=1),
    ]
    result = compute_upt(events, ["trip-1"], imbalance_threshold=Decimal("999"))
    negative = [w for w in result.warnings if w.issue_type == "apc_negative_load"]
    assert len(negative) == 1  # one finding per trip: the first drop
    assert negative[0].source_record_ids == ("rec-e2",)


def test_negative_load_ordering_is_stop_sequence_not_timestamp():
    """p. 151 running load is ordered by trip_stop_sequence THEN
    event_timestamp: an alighting recorded EARLIER in wall-time but at a
    LATER stop must not produce a spurious negative load."""
    events = [
        # alighting at stop 2 arrives first in wall-time
        make_event("e1", minute=0, seq=2, event_type=ALIGHTING_EVENT_TYPE, count=3),
        make_event("e2", minute=1, seq=1, count=3),
    ]
    result = compute_upt(events, ["trip-1"])
    assert [w.issue_type for w in result.warnings] == []


def test_negative_load_null_sequence_sorts_last():
    """NULL trip_stop_sequence sorts after numbered stops (documented
    convention): a NULL-sequence alighting cannot precede the boardings."""
    events = [
        make_event("e1", minute=1, seq=None, event_type=ALIGHTING_EVENT_TYPE, count=3),
        make_event("e2", minute=2, seq=1, count=3),
    ]
    result = compute_upt(events, ["trip-1"])
    assert [w.issue_type for w in result.warnings] == []


# --- p. 146: missing-trip rule ------------------------------------------------


def test_no_missing_trips_factor_is_one():
    events = [make_event("e1", minute=0, count=7)]
    result = compute_upt(events, ["trip-1"])
    assert result.value == Decimal("7")
    assert result.detail.missing_trips == 0
    assert result.detail.missing_share == Decimal("0.0000")
    assert result.detail.factor_applied == Decimal("1.000000")


def test_share_exactly_two_percent_factors_up():
    """'2 percent or less of the total' factors up — the boundary is
    INCLUSIVE (exact comparison: missing > threshold x operated blocks)."""
    operated = [f"trip-{k}" for k in range(1, 51)]  # 50 trips, 1 missing
    events = [
        make_event(f"e{k}", minute=k, trip_id=f"trip-{k}", count=1)
        for k in range(1, 50)
    ]
    result = compute_upt(events, operated)
    assert result.blocking_issues == ()
    # 49 counted x 50/49 = 50 exactly.
    assert result.value == Decimal("50")
    assert result.detail.factor_applied == Decimal("1.020408")
    assert result.detail.missing_share == Decimal("0.0200")


def test_share_above_two_percent_blocks_with_value_none():
    operated = [f"trip-{k}" for k in range(1, 50)]  # 49 trips, 1 missing > 2%
    events = [
        make_event(f"e{k}", minute=k, trip_id=f"trip-{k}", count=1)
        for k in range(1, 49)
    ]
    result = compute_upt(events, operated)
    assert result.value is None
    assert len(result.blocking_issues) == 1
    blocking = result.blocking_issues[0]
    assert blocking.issue_type == "apc_missing_trips_above_fta_threshold"
    assert blocking.severity == "blocking"
    assert "trip-49" in blocking.description  # the missing trip is named
    assert result.detail.factor_applied is None
    # The counted base still travels in the detail (evidence, not a value).
    assert result.detail.total_boardings_counted == 48


def test_all_operated_trips_missing_blocks_without_division():
    result = compute_upt([], ["trip-1", "trip-2"])
    assert result.value is None
    assert result.blocking_issues[0].issue_type == (
        "apc_missing_trips_above_fta_threshold"
    )
    assert result.detail.missing_share == Decimal("1.0000")


def test_zero_operated_trips_degenerate_period():
    """Nothing operated, nothing missing: share 0, factor 1, the counted
    figure stands (here 0 over no events)."""
    result = compute_upt([], [])
    assert result.blocking_issues == ()
    assert result.value == Decimal("0")
    assert result.detail.operated_trips == 0
    assert result.detail.missing_share == Decimal("0")
    assert result.detail.factor_applied == Decimal("1.000000")


def test_any_event_type_marks_a_trip_as_not_missing():
    """'Missing' means ZERO passenger events — a door event alone means the
    APC reported for that trip (its counts may be zero, not absent)."""
    events = [
        make_event("e1", minute=0, count=4),
        make_event("e2", minute=1, seq=2, event_type=ALIGHTING_EVENT_TYPE, count=4),
        make_event("e3", minute=2, trip_id="trip-2", event_type="Door opened", count=None),
    ]
    result = compute_upt(events, ["trip-1", "trip-2"])
    assert result.detail.missing_trips == 0
    assert result.value == Decimal("4")
    # Door events are outside the boarding/alighting arithmetic: no
    # apc_null_count warning for their NULL counts.
    assert result.warnings == ()


def test_factored_value_rounds_to_whole_boardings_half_even():
    """counted=3, operated=100, missing=2 (share 0.02): 3 x 100/98 =
    3.0612... -> quantized Decimal 1 ROUND_HALF_EVEN -> 3."""
    operated = [f"trip-{k}" for k in range(1, 101)]
    # 98 covered trips, only 3 boardings total (counts 1,1,1,0,0,...).
    events = [
        make_event(
            f"e{k}", minute=k, trip_id=f"trip-{k}", count=(1 if k <= 3 else 0)
        )
        for k in range(1, 99)
    ]
    result = compute_upt(events, operated)
    assert result.blocking_issues == ()
    assert result.detail.total_boardings_counted == 3
    assert result.value == Decimal("3")  # 3.0612... rounds to 3, never guessed up


# --- simulated sources (handoff 0005) -----------------------------------------


def test_simulated_source_yields_one_info_and_source_mix():
    events = [
        make_event("e1", minute=0, count=2, source="tides"),
        make_event("e2", minute=1, count=3, source="tides_simulated"),
        make_event("e3", minute=2, count=1, source="tides_simulated"),
    ]
    result = compute_upt(events, ["trip-1"])
    assert len(result.infos) == 1
    info = result.infos[0]
    assert info.issue_type == "simulated_source_data"
    assert info.severity == "info"
    assert "tides_simulated" in info.title
    assert info.source_record_ids == ("rec-e2", "rec-e3")
    assert result.detail.source_mix == {"tides": 1, "tides_simulated": 2}
    # The figure stands (info severity), but the trail marks it uncertifiable.
    assert result.value == Decimal("6")


def test_all_real_tides_sources_no_info():
    events = [make_event("e1", minute=0, count=2)]
    result = compute_upt(events, ["trip-1"])
    assert result.infos == ()
    assert result.detail.source_mix == {"tides": 1}


# --- input validation ----------------------------------------------------------


def test_naive_event_timestamp_refused():
    with pytest.raises(ValueError, match="timezone-aware"):
        PassengerEvent(
            event_timestamp=datetime(2026, 6, 15, 8, 0, 0),  # naive
            service_date=SERVICE_DATE,
            passenger_event_id="pe-1",
            vehicle_id="veh-1",
            trip_id="trip-1",
            trip_stop_sequence=1,
            event_type=BOARDING_EVENT_TYPE,
            event_count=1,
            source="tides",
            source_record_id="rec-1",
        )


def test_negative_event_count_refused():
    with pytest.raises(ValueError, match="event_count"):
        make_event("e1", count=-1)
