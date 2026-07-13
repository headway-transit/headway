"""GTFS-RT trip_updates normalizer: real FeedMessages built in-test.

Predictions are PREDICTIONS (handoff 0014): every row carries the frame's
header timestamp as feed_timestamp and only predicted_* time columns; a
frame with no header timestamp is quarantined whole — a prediction whose
made-at time is unknown is unusable, and a time is never guessed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from google.transit import gtfs_realtime_pb2

from headway_transform.envelope import validate_envelope
from headway_transform.trip_updates import (
    OUTPUT_KIND,
    TRANSFORM_NAME,
    TRANSFORM_VERSION,
    normalize,
)

from conftest import make_envelope_dict

HEADER_TS = 1_760_000_000
ARRIVAL_TS = 1_760_000_600
DEPARTURE_TS = 1_760_000_660


def build_feed(*, header_timestamp: int | None = HEADER_TS) -> gtfs_realtime_pb2.FeedMessage:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    if header_timestamp is not None:
        feed.header.timestamp = header_timestamp
    return feed


def add_trip_update(
    feed: gtfs_realtime_pb2.FeedMessage,
    entity_id: str,
    trip_id: str,
    *,
    route_id: str | None = "route-9",
    vehicle_id: str | None = "bus-101",
    schedule_relationship: int | None = None,
) -> gtfs_realtime_pb2.TripUpdate:
    entity = feed.entity.add()
    entity.id = entity_id
    update = entity.trip_update
    if trip_id:
        update.trip.trip_id = trip_id
    if route_id is not None:
        update.trip.route_id = route_id
    if schedule_relationship is not None:
        update.trip.schedule_relationship = schedule_relationship
    if vehicle_id is not None:
        update.vehicle.id = vehicle_id
    return update


def add_stop_time_update(
    update: gtfs_realtime_pb2.TripUpdate,
    *,
    stop_id: str | None = "stop-1",
    stop_sequence: int | None = 5,
    arrival_time: int | None = ARRIVAL_TS,
    arrival_delay: int | None = None,
    arrival_uncertainty: int | None = 30,
    departure_time: int | None = DEPARTURE_TS,
    schedule_relationship: int | None = None,
) -> None:
    stu = update.stop_time_update.add()
    if stop_id is not None:
        stu.stop_id = stop_id
    if stop_sequence is not None:
        stu.stop_sequence = stop_sequence
    if arrival_time is not None:
        stu.arrival.time = arrival_time
    if arrival_delay is not None:
        stu.arrival.delay = arrival_delay
    if arrival_uncertainty is not None:
        stu.arrival.uncertainty = arrival_uncertainty
    if departure_time is not None:
        stu.departure.time = departure_time
    if schedule_relationship is not None:
        stu.schedule_relationship = schedule_relationship


def envelope_for(feed: gtfs_realtime_pb2.FeedMessage):
    return validate_envelope(make_envelope_dict(feed.SerializeToString()))


def _utc(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def test_normalizes_stop_time_events_with_one_edge_per_row() -> None:
    feed = build_feed()
    update = add_trip_update(feed, "e1", "trip-1")
    add_stop_time_update(update, stop_id="stop-1", stop_sequence=5)
    add_stop_time_update(
        update, stop_id="stop-2", stop_sequence=6, arrival_time=None,
        arrival_uncertainty=None, departure_time=DEPARTURE_TS + 120,
    )
    envelope = envelope_for(feed)

    rows, edges, findings = normalize(envelope)

    assert findings == []
    assert len(rows) == 2
    assert len(edges) == 2  # exactly one edge per canonical row
    first = rows[0]
    assert first.feed_timestamp == _utc(HEADER_TS)
    assert first.trip_id == "trip-1"
    assert first.route_id == "route-9"
    assert first.vehicle_id == "bus-101"
    assert first.stop_id == "stop-1"
    assert first.stop_sequence == 5
    assert first.predicted_arrival == _utc(ARRIVAL_TS)
    assert first.arrival_uncertainty_seconds == 30
    assert first.predicted_departure == _utc(DEPARTURE_TS)
    assert first.trip_schedule_relationship == "SCHEDULED"
    assert first.stop_schedule_relationship == "SCHEDULED"
    assert first.source_record_id == envelope.record_id
    # No absolute arrival on the second event: None preserved, not derived.
    assert rows[1].predicted_arrival is None
    assert rows[1].predicted_departure == _utc(DEPARTURE_TS + 120)
    for edge in edges:
        assert edge.output_kind == OUTPUT_KIND == "canonical.trip_updates"
        assert edge.transform_name == TRANSFORM_NAME
        assert edge.transform_version == TRANSFORM_VERSION == "0.1.0"
        assert edge.input_kind == "raw.records"
        assert edge.input_id == envelope.record_id
    assert edges[0].output_id == (
        f"trip-1|5|stop-1|2025-10-09T08:53:20Z|{envelope.record_id}"
    )


def test_delay_only_event_keeps_delay_never_derives_a_time() -> None:
    feed = build_feed()
    update = add_trip_update(feed, "e1", "trip-1")
    add_stop_time_update(
        update, arrival_time=None, arrival_delay=90, arrival_uncertainty=None,
        departure_time=None,
    )
    rows, _edges, findings = normalize(envelope_for(feed))

    assert findings == []
    [row] = rows
    assert row.predicted_arrival is None  # never delay + schedule here
    assert row.arrival_delay_seconds == 90
    assert row.predicted_departure is None


def test_canceled_trip_emits_trip_level_row_not_a_drop() -> None:
    feed = build_feed()
    add_trip_update(
        feed, "e1", "trip-gone", vehicle_id=None,
        schedule_relationship=(
            gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.CANCELED
        ),
    )
    rows, edges, findings = normalize(envelope_for(feed))

    assert findings == []
    [row] = rows
    assert row.trip_id == "trip-gone"
    assert row.trip_schedule_relationship == "CANCELED"
    assert row.stop_id is None and row.stop_sequence is None
    assert row.stop_schedule_relationship is None
    assert row.predicted_arrival is None and row.predicted_departure is None
    assert len(edges) == 1


def test_skipped_stop_recorded_with_relationship() -> None:
    feed = build_feed()
    update = add_trip_update(feed, "e1", "trip-1")
    add_stop_time_update(
        update, arrival_time=None, arrival_uncertainty=None,
        departure_time=None,
        schedule_relationship=(
            gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.ScheduleRelationship.SKIPPED
        ),
    )
    rows, _edges, findings = normalize(envelope_for(feed))

    assert findings == []
    [row] = rows
    assert row.stop_schedule_relationship == "SKIPPED"


def test_missing_header_timestamp_quarantines_frame_whole() -> None:
    feed = build_feed(header_timestamp=None)
    update = add_trip_update(feed, "e1", "trip-1")
    add_stop_time_update(update)
    rows, edges, findings = normalize(envelope_for(feed))

    assert rows == [] and edges == []
    [finding] = findings
    assert finding.severity == "blocking"
    assert "header timestamp" in finding.title
    assert "never guessed" in finding.description


def test_trip_update_without_trip_id_quarantined() -> None:
    feed = build_feed()
    update = add_trip_update(feed, "e1", "", route_id="route-9")
    add_stop_time_update(update)
    add_trip_update(feed, "e2", "trip-ok").stop_time_update.add().stop_id = "s"
    rows, _edges, findings = normalize(envelope_for(feed))

    assert [r.trip_id for r in rows] == ["trip-ok"]
    [finding] = findings
    assert finding.issue_type == "malformed_entity"
    assert "no trip_id" in finding.title


def test_stop_time_update_with_no_stop_identity_quarantined() -> None:
    feed = build_feed()
    update = add_trip_update(feed, "e1", "trip-1")
    add_stop_time_update(update, stop_id=None, stop_sequence=None)
    add_stop_time_update(update, stop_id="stop-2", stop_sequence=None)
    rows, _edges, findings = normalize(envelope_for(feed))

    # The identity-less event is a finding; the stop_id-only event lands.
    assert [(r.stop_id, r.stop_sequence) for r in rows] == [("stop-2", None)]
    [finding] = findings
    assert "identifies no stop" in finding.title


def test_duplicate_stop_key_in_one_frame_kept_once_and_warned() -> None:
    feed = build_feed()
    update = add_trip_update(feed, "e1", "trip-1")
    add_stop_time_update(update, stop_id="stop-1", stop_sequence=5)
    add_stop_time_update(
        update, stop_id="stop-1", stop_sequence=5,
        arrival_time=ARRIVAL_TS + 60,
    )
    rows, edges, findings = normalize(envelope_for(feed))

    assert len(rows) == 1 == len(edges)
    assert rows[0].predicted_arrival == _utc(ARRIVAL_TS)  # first kept
    [finding] = findings
    assert "Duplicate" in finding.title
    assert "never silently absorbed" in finding.description


def test_entity_without_trip_update_quarantined() -> None:
    feed = build_feed()
    entity = feed.entity.add()
    entity.id = "e-weird"
    entity.vehicle.vehicle.id = "bus-1"  # a vehicle on the wrong topic
    rows, _edges, findings = normalize(envelope_for(feed))

    assert rows == []
    [finding] = findings
    assert "no TripUpdate" in finding.title


def test_undecodable_payload_is_blocking_finding() -> None:
    envelope = validate_envelope(make_envelope_dict(b"not a protobuf"))
    rows, edges, findings = normalize(envelope)
    assert rows == [] and edges == []
    [finding] = findings
    assert finding.issue_type == "undecodable_payload"
    assert finding.severity == "blocking"


def test_connector_malformed_parse_status_honored() -> None:
    feed = build_feed()
    envelope = validate_envelope(
        make_envelope_dict(
            feed.SerializeToString(),
            parse_status="malformed",
            parse_error="truncated read",
        )
    )
    rows, edges, findings = normalize(envelope)
    assert rows == [] and edges == []
    [finding] = findings
    assert finding.issue_type == "undecodable_payload"
    assert "truncated read" in finding.description


def test_findings_carry_transform_scoped_dedupe_keys() -> None:
    """Replay idempotency (migration 0023): the same frame re-delivered
    re-emits byte-identical findings whose dedupe keys collide — nothing
    new is written on replay."""
    feed = build_feed()
    update = add_trip_update(feed, "e1", "trip-1")
    add_stop_time_update(update, stop_id=None, stop_sequence=None)
    envelope = envelope_for(feed)

    _rows1, _e1, findings1 = normalize(envelope)
    _rows2, _e2, findings2 = normalize(envelope)
    assert [f.transform_dedupe_key() for f in findings1] == [
        f.transform_dedupe_key() for f in findings2
    ]
    assert all(
        key is not None and key.startswith("transform:")
        for key in (f.transform_dedupe_key() for f in findings1)
    )
