"""Unit tests for headway_calc.mode (handoff 0009): bucketing, partitioning,
the per-mode operated-trips denominator, and the ONE per-run
unknown-mode-share info finding.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from headway_calc.mode import (
    MODE_UNKNOWN,
    compute_upt_by_mode,
    mode_bucket,
    operated_trip_ids_by_mode,
    partition_events_by_mode,
    partition_positions_by_mode,
    scope_for_mode,
    unknown_mode_finding,
)
from headway_calc.types import PassengerEvent, VehiclePosition

T0 = datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)


def _pos(vehicle, trip, rid, mode=None):
    return VehiclePosition(
        time=T0,
        vehicle_id=vehicle,
        trip_id=trip,
        latitude=40.0,
        longitude=-75.0,
        source_record_id=rid,
        mode=mode,
    )


def _ev(pid, trip, rid, mode=None, count=1):
    return PassengerEvent(
        event_timestamp=T0,
        service_date=date(2026, 7, 1),
        passenger_event_id=pid,
        vehicle_id="veh-1",
        trip_id=trip,
        trip_stop_sequence=1,
        event_type="Passenger boarded",
        event_count=count,
        source="tides",
        source_record_id=rid,
        mode=mode,
    )


def test_mode_bucket_null_is_unknown_never_guessed():
    assert mode_bucket(None) == MODE_UNKNOWN == "unknown"
    assert mode_bucket("bus") == "bus"


def test_scope_for_mode_matches_the_handoff_format():
    assert scope_for_mode("bus") == "mode:bus"
    assert scope_for_mode("unknown") == "mode:unknown"


def test_partition_positions_sorted_keys_nothing_dropped():
    positions = [
        _pos("v1", "t1", "r1", "subway"),
        _pos("v2", "t2", "r2", "bus"),
        _pos("v3", None, "r3", None),  # NULL mode -> unknown, never dropped
        _pos("v4", "t4", "r4", "bus"),
    ]
    buckets = partition_positions_by_mode(positions)
    assert list(buckets) == ["bus", "subway", "unknown"]  # sorted
    assert [p.source_record_id for p in buckets["bus"]] == ["r2", "r4"]
    assert [p.source_record_id for p in buckets["unknown"]] == ["r3"]
    # Partition: every position in exactly one bucket.
    assert sum(len(b) for b in buckets.values()) == len(positions)


def test_partition_events_sorted_keys_nothing_dropped():
    events = [
        _ev("p1", "t1", "r1", "bus"),
        _ev("p2", None, "r2", None),
    ]
    buckets = partition_events_by_mode(events)
    assert list(buckets) == ["bus", "unknown"]
    assert sum(len(b) for b in buckets.values()) == len(events)


def test_operated_trip_ids_by_mode_distinct_and_union_equals_fleet():
    positions = [
        _pos("v1", "t1", "r1", "bus"),
        _pos("v1", "t1", "r2", "bus"),  # duplicate trip: distinct counting
        _pos("v2", "t2", "r3", "subway"),
        _pos("v3", "t3", "r4", None),  # in-trip but unknown mode
        _pos("v4", None, "r5", None),  # unassigned: no operated trip anywhere
    ]
    by_mode = operated_trip_ids_by_mode(positions)
    assert by_mode == {"bus": ["t1"], "subway": ["t2"], "unknown": ["t3"]}
    # The fleet denominator is exactly the union of the per-mode ones.
    fleet = sorted({p.trip_id for p in positions if p.trip_id is not None})
    assert sorted(t for trips in by_mode.values() for t in trips) == fleet


def test_upt_by_mode_covers_modes_with_operated_trips_but_no_events():
    """A mode observed operating with ZERO passenger events still gets a
    result — its missing share is 1, so the p. 146 rule blocks it (the
    honest outcome, never an invented zero)."""
    positions = [
        _pos("v1", "t1", "r1", "bus"),
        _pos("v2", "t2", "r2", "subway"),
    ]
    events = [_ev("p1", "t1", "re1", "bus", count=3)]
    by_mode = compute_upt_by_mode(events, positions)
    assert sorted(by_mode) == ["bus", "subway"]
    assert str(by_mode["bus"].value) == "3"
    subway = by_mode["subway"]
    assert subway.value is None
    assert [f.issue_type for f in subway.blocking_issues] == [
        "apc_missing_trips_above_fta_threshold"
    ]


def test_unknown_mode_finding_none_when_every_row_has_a_mode():
    positions = [_pos("v1", "t1", "r1", "bus")]
    events = [_ev("p1", "t1", "re1", "bus")]
    assert unknown_mode_finding(positions, events) is None


def test_unknown_mode_finding_counts_and_cites():
    positions = [
        _pos("v1", "t1", "r1", "bus"),
        _pos("v2", None, "r2", None),
    ]
    events = [_ev("p1", None, "re1", None)]
    finding = unknown_mode_finding(positions, events)
    assert finding is not None
    assert finding.issue_type == "unknown_mode_share"
    assert finding.severity == "info"
    assert "1 of 2 vehicle positions" in finding.description
    assert "1 of 1 passenger events" in finding.description
    assert "NEVER dropped" in finding.description
    assert set(finding.source_record_ids) == {"r2", "re1"}


def test_unknown_mode_finding_citations_truncate_at_100():
    """Live periods can carry hundreds of thousands of unassigned positions;
    the finding cites the first 100 records and states the full counts."""
    positions = [_pos(f"v{k}", None, f"r{k:04d}", None) for k in range(250)]
    finding = unknown_mode_finding(positions, [])
    assert len(finding.source_record_ids) == 100
    assert "250 of 250 vehicle positions" in finding.description
    assert "first 100 of 250" in finding.description
