"""Unit tests for headway_calc.passages — derive_stop_passages 0.1.0
(handoff 0014). Tolerances and refusal semantics per the module docstring
and services/calc/OPS_DEFINITIONS.md; the golden cases live in
tests/golden/ops_v0 (BASIS.md)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from headway_calc.passages import (
    MAX_PASSAGE_GAP_SECONDS,
    MIN_OCCURRENCE_POSITIONS,
    OCCURRENCE_SPLIT_SECONDS,
    derive_stop_passages,
)
from headway_calc.types import OpsScheduledStop, VehiclePosition

T0 = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


def _stop(seq=1, stop_id="S1", lat=42.35, lon=-71.06, trip_id="T1"):
    return OpsScheduledStop(
        trip_id=trip_id,
        stop_id=stop_id,
        stop_sequence=seq,
        latitude=lat,
        longitude=lon,
        arrival_seconds=28800,
        departure_seconds=28800,
        route_id="R1",
        direction_id=0,
    )


def _pos(offset_s, lat, rec, trip_id="T1", vehicle_id="bus-1", lon=-71.06):
    return VehiclePosition(
        time=T0 + timedelta(seconds=offset_s),
        vehicle_id=vehicle_id,
        trip_id=trip_id,
        latitude=lat,
        longitude=lon,
        source_record_id=rec,
    )


def _clean_run():
    """Three positions bracketing S1: passage at the middle one."""
    return [
        _pos(-60, 42.3482, "r1"),
        _pos(0, 42.35, "r2"),
        _pos(60, 42.3518, "r3"),
    ]


def test_clean_passage_at_closest_approach():
    passages, stats = derive_stop_passages(_clean_run(), [_stop()])
    [p] = passages
    assert p.observed_time == T0
    assert p.source_record_id == "r2"
    assert p.bounding_gap_seconds == 60.0
    assert p.route_id == "R1" and p.direction_id == 0
    assert stats.passages_derived == 1


def test_unassigned_positions_not_considered():
    rows = _clean_run() + [
        VehiclePosition(
            time=T0, vehicle_id="ghost", trip_id=None, latitude=42.35,
            longitude=-71.06, source_record_id="r-none",
        )
    ]
    _passages, stats = derive_stop_passages(rows, [_stop()])
    assert stats.positions_considered == 3


def test_same_trip_id_on_two_service_days_splits_occurrences():
    day2 = timedelta(days=1)
    rows = _clean_run() + [
        _pos(int(day2.total_seconds()) + off, lat, rec + "-d2")
        for off, lat, rec in ((-60, 42.3482, "r1"), (0, 42.35, "r2"), (60, 42.3518, "r3"))
    ]
    passages, stats = derive_stop_passages(rows, [_stop()])
    assert stats.occurrences == 2
    assert len(passages) == 2
    assert passages[0].observed_time == T0
    assert passages[1].observed_time == T0 + day2
    assert OCCURRENCE_SPLIT_SECONDS < day2.total_seconds()


def test_occurrence_with_too_few_positions_skipped_and_counted():
    rows = _clean_run()[:MIN_OCCURRENCE_POSITIONS - 1]
    passages, stats = derive_stop_passages(rows, [_stop()])
    assert passages == ()
    assert stats.occurrences_skipped_few_positions == 1


def test_duplicate_timestamps_collapsed_keeping_first_record():
    rows = _clean_run() + [_pos(0, 42.3501, "r2-dup")]
    passages, stats = derive_stop_passages(rows, [_stop()])
    assert stats.positions_deduplicated == 1
    [p] = passages
    assert p.source_record_id == "r2"  # first by (time, record) order


def test_equidistant_tie_breaks_to_earliest_position():
    # Positions symmetric around the stop; both 200 m away — but a middle
    # position AT the stop is absent, so closest approach ties between
    # index 1 and index 2 at equal distance: the earlier wins.
    rows = [
        _pos(-60, 42.3464, "r0"),
        _pos(0, 42.3492, "r1"),   # ~89 m south of S1 (inside the radius)
        _pos(60, 42.3508, "r2"),  # ~89 m north — exactly equidistant
        _pos(120, 42.3536, "r3"),
    ]
    passages, _stats = derive_stop_passages(rows, [_stop()])
    [p] = passages
    assert p.source_record_id == "r1"


def test_endpoint_closest_approach_refused():
    rows = [
        _pos(0, 42.35, "r1"),  # closest is the FIRST observation
        _pos(60, 42.3518, "r2"),
        _pos(120, 42.3536, "r3"),
    ]
    passages, stats = derive_stop_passages(rows, [_stop()])
    assert passages == ()
    assert stats.refused_endpoint_unbounded == 1


def test_bounding_gap_over_tolerance_refused():
    rows = [
        _pos(-(MAX_PASSAGE_GAP_SECONDS + 1), 42.3482, "r1"),
        _pos(0, 42.35, "r2"),
        _pos(60, 42.3518, "r3"),
    ]
    passages, stats = derive_stop_passages(rows, [_stop()])
    assert passages == ()
    assert stats.refused_cadence_gap == 1


def test_stop_never_approached_refused():
    far_stop = _stop(stop_id="S-far", lat=42.40)
    passages, stats = derive_stop_passages(_clean_run(), [far_stop])
    assert passages == ()
    assert stats.refused_not_reached == 1


def test_stop_without_coordinates_counted_never_guessed():
    bare = OpsScheduledStop(
        trip_id="T1", stop_id="S-node", stop_sequence=9, latitude=None,
        longitude=None, arrival_seconds=30000, departure_seconds=30000,
        route_id="R1", direction_id=0,
    )
    passages, stats = derive_stop_passages(_clean_run(), [_stop(), bare])
    assert len(passages) == 1
    assert stats.stops_missing_coordinates == 1


def test_trip_without_schedule_counted():
    rows = _clean_run() + [
        _pos(off, lat, rec, trip_id="T-added")
        for off, lat, rec in ((0, 42.35, "a1"), (60, 42.3518, "a2"), (120, 42.3536, "a3"))
    ]
    _passages, stats = derive_stop_passages(rows, [_stop()])
    assert stats.trips_without_schedule == 1


def test_derivation_is_deterministic_under_input_order():
    rows = _clean_run()
    schedule = [_stop(), _stop(seq=2, stop_id="S2", lat=42.36)]
    a = derive_stop_passages(rows, schedule)
    b = derive_stop_passages(list(reversed(rows)), list(reversed(schedule)))
    assert a == b
