"""Normalizer: raw.gtfs_rt.trip_updates -> canonical.trip_updates.

Decodes a base64 GTFS-Realtime FeedMessage protobuf frame (payload semantics
per gtfs.org/documentation/realtime/reference — verify against the current
published spec) using gtfs-realtime-bindings (Apache-2.0), and emits:

- CanonicalTripUpdate rows matching canonical.trip_updates (migration 0025,
  handoff 0014) column-for-column: ONE ROW PER (TripUpdate, StopTimeUpdate),
  plus one TRIP-LEVEL row (stop fields None) for updates carrying no
  stop-time events (e.g. CANCELED trips — a cancellation is data);
- exactly one LineageEdge per row;
- a DQFinding for every payload/entity/stop-time event that could not be
  normalized — NEVER a silent skip (role guardrail: fail loudly).

PREDICTIONS ARE PREDICTIONS (handoff 0014, binding): every emitted time is
what the agency's real-time system predicted as of the frame's header
timestamp, carried in ``feed_timestamp`` and in the ``predicted_*`` column
names. Nothing here is an observed arrival and nothing here may feed an NTD
figure (the migration-0024 category boundary governs downstream use).

Event-time policy: the FeedMessage header timestamp is the frame's
prediction time. A frame WITHOUT a header timestamp is quarantined whole
(blocking) — a prediction whose made-at time is unknown is unusable, and a
time is never guessed. Per-StopTimeUpdate times come only from
StopTimeEvent.time (absolute POSIX); a delay-only event keeps its delay in
``*_delay_seconds`` with predicted time None — deriving an absolute time
from delay + schedule is a versioned calc's job, never the normalizer's.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from .envelope import Envelope, PayloadDecodeError
from .gtfs_rt_positions import rfc3339
from .model import (
    SEVERITY_BLOCKING,
    SEVERITY_WARNING,
    DQFinding,
    LineageEdge,
)

TRANSFORM_NAME = "normalize_gtfs_rt_trip_updates"
TRANSFORM_VERSION = "0.1.0"

TOPIC = "raw.gtfs_rt.trip_updates"
OUTPUT_KIND = "canonical.trip_updates"
INPUT_KIND = "raw.records"


@dataclass(frozen=True)
class CanonicalTripUpdate:
    """One canonical.trip_updates row (migration 0025, column-for-column).

    A stop-time row carries at least one of stop_id/stop_sequence; a
    TRIP-LEVEL row (an update with no stop-time events, e.g. CANCELED)
    carries None for all stop-scoped fields.
    """

    feed_timestamp: datetime  # TIMESTAMPTZ NOT NULL — prediction time
    trip_id: str  # TEXT NOT NULL
    route_id: str | None
    vehicle_id: str | None
    stop_id: str | None
    stop_sequence: int | None
    predicted_arrival: datetime | None
    arrival_delay_seconds: int | None
    arrival_uncertainty_seconds: int | None
    predicted_departure: datetime | None
    departure_delay_seconds: int | None
    departure_uncertainty_seconds: int | None
    trip_schedule_relationship: str  # enum name verbatim, e.g. 'SCHEDULED'
    stop_schedule_relationship: str | None  # None on trip-level rows
    source_record_id: str  # TEXT NOT NULL REFERENCES raw.records

    @property
    def stop_key(self) -> str:
        """The stop identity half of the natural key, rendered as text.

        Mirrors the migration-0025 unique index's COALESCE pair:
        (stop_sequence, -1) and (stop_id, '').
        """
        seq = -1 if self.stop_sequence is None else self.stop_sequence
        return f"{seq}|{self.stop_id or ''}"

    @property
    def output_id(self) -> str:
        """Natural key rendered as text for lineage.edges.output_id."""
        return (
            f"{self.trip_id}|{self.stop_key}|"
            f"{rfc3339(self.feed_timestamp)}|{self.source_record_id}"
        )


def _epoch_utc(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def _relationship_name(enum_wrapper, value: int) -> str:
    """The spec's enum name for a schedule_relationship value, verbatim.

    An out-of-vocabulary integer (a future spec revision) is rendered as
    'UNKNOWN(<n>)' — surfaced as data, never dropped and never guessed.
    """
    try:
        return enum_wrapper.Name(value)
    except ValueError:
        return f"UNKNOWN({value})"


def normalize(
    envelope: Envelope,
) -> tuple[list[CanonicalTripUpdate], list[LineageEdge], list[DQFinding]]:
    """Normalize one raw.gtfs_rt.trip_updates envelope.

    Returns (rows, lineage_edges, dq_findings). Every row has exactly one
    lineage edge; every failure is a DQFinding. This function does not raise
    for bad payload content — undecodable input is data, and data problems
    are dq.issues rows, not crashes (the consumer quarantines them).
    """
    record_id = envelope.record_id

    if envelope.parse_status == "malformed":
        return (
            [],
            [],
            [
                DQFinding(
                    issue_type="undecodable_payload",
                    severity=SEVERITY_BLOCKING,
                    title="Connector flagged GTFS-RT trip_updates payload as malformed",
                    description=(
                        f"Envelope for record {record_id} arrived with "
                        f"parse_status='malformed' (connector "
                        f"{envelope.connector} {envelope.connector_version}): "
                        f"{envelope.parse_error or 'no parse_error supplied'}. "
                        "Payload was not normalized; raw record retained."
                    ),
                    source_record_ids=[record_id],
                )
            ],
        )

    try:
        payload_bytes = envelope.decode_payload()
    except PayloadDecodeError as exc:
        return (
            [],
            [],
            [
                DQFinding(
                    issue_type="undecodable_payload",
                    severity=SEVERITY_BLOCKING,
                    title="GTFS-RT trip_updates payload could not be decoded from envelope",
                    description=(
                        f"Record {record_id}: {exc}. Payload was not "
                        "normalized; raw record retained."
                    ),
                    source_record_ids=[record_id],
                )
            ],
        )

    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(payload_bytes)
    except DecodeError as exc:
        return (
            [],
            [],
            [
                DQFinding(
                    issue_type="undecodable_payload",
                    severity=SEVERITY_BLOCKING,
                    title="GTFS-RT trip_updates payload is not a parseable FeedMessage",
                    description=(
                        f"Record {record_id}: protobuf decode failed: {exc}. "
                        "Payload was not normalized; raw record retained."
                    ),
                    source_record_ids=[record_id],
                )
            ],
        )

    # The frame's prediction time. Without it every prediction in the frame
    # is unanchored — quarantine the whole record, never guess a time.
    if not feed.header.HasField("timestamp"):
        return (
            [],
            [],
            [
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_BLOCKING,
                    title="GTFS-RT trip_updates frame has no header timestamp",
                    description=(
                        f"Record {record_id}: the FeedMessage header carries "
                        "no timestamp, so the frame's prediction time is "
                        "unknown. Predictions without a made-at time are "
                        "unusable; the frame was quarantined whole (raw "
                        "record retained) — a time is never guessed."
                    ),
                    source_record_ids=[record_id],
                )
            ],
        )
    feed_timestamp = _epoch_utc(int(feed.header.timestamp))

    trip_rel_enum = gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship
    stop_rel_enum = (
        gtfs_realtime_pb2.TripUpdate.StopTimeUpdate.ScheduleRelationship
    )

    rows: list[CanonicalTripUpdate] = []
    edges: list[LineageEdge] = []
    findings: list[DQFinding] = []
    # In-record natural-key dedupe: the writer's ON CONFLICT would silently
    # absorb an in-record duplicate; detecting it here keeps the drop LOUD.
    seen_keys: set[tuple[str, str]] = set()

    def _emit(row: CanonicalTripUpdate) -> None:
        key = (row.trip_id, row.stop_key)
        if key in seen_keys:
            findings.append(
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_WARNING,
                    title="Duplicate trip/stop prediction inside one frame",
                    description=(
                        f"Record {record_id}: trip {row.trip_id!r} carries "
                        f"more than one update for stop key {row.stop_key!r} "
                        "in the same frame. The first occurrence was kept; "
                        "this duplicate was quarantined as this finding, "
                        "never silently absorbed."
                    ),
                    source_record_ids=[record_id],
                )
            )
            return
        seen_keys.add(key)
        rows.append(row)
        edges.append(
            LineageEdge(
                output_kind=OUTPUT_KIND,
                output_id=row.output_id,
                transform_name=TRANSFORM_NAME,
                transform_version=TRANSFORM_VERSION,
                input_kind=INPUT_KIND,
                input_id=record_id,
            )
        )

    for index, entity in enumerate(feed.entity):
        if not entity.HasField("trip_update"):
            findings.append(
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_WARNING,
                    title="trip_updates entity carries no TripUpdate",
                    description=(
                        f"Record {record_id}, entity {entity.id or index}: "
                        "no trip_update field on a raw.gtfs_rt.trip_updates "
                        "frame. Entity was quarantined, not dropped silently."
                    ),
                    source_record_ids=[record_id],
                )
            )
            continue

        update = entity.trip_update
        trip = update.trip
        if not trip.trip_id:
            # GTFS-RT permits route-only trip descriptors, but a prediction
            # that names no trip cannot be joined to a schedule — quarantined
            # as unusable, never guessed onto a trip.
            findings.append(
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_WARNING,
                    title="TripUpdate has no trip_id",
                    description=(
                        f"Record {record_id}, entity {entity.id or index}: "
                        "the TripDescriptor carries no trip_id, so the "
                        "prediction cannot be anchored to a scheduled trip. "
                        "Entity was quarantined, not dropped silently."
                    ),
                    source_record_ids=[record_id],
                )
            )
            continue

        trip_relationship = _relationship_name(
            trip_rel_enum,
            trip.schedule_relationship
            if trip.HasField("schedule_relationship")
            else trip_rel_enum.SCHEDULED,
        )
        route_id = trip.route_id or None
        vehicle_id = (
            update.vehicle.id
            if update.HasField("vehicle") and update.vehicle.id
            else None
        )

        if not update.stop_time_update:
            # Trip-level row: an update with no stop-time events (typically
            # CANCELED). The cancellation itself is data — landed as a row,
            # never dropped and never inflated into fake stop events.
            _emit(
                CanonicalTripUpdate(
                    feed_timestamp=feed_timestamp,
                    trip_id=trip.trip_id,
                    route_id=route_id,
                    vehicle_id=vehicle_id,
                    stop_id=None,
                    stop_sequence=None,
                    predicted_arrival=None,
                    arrival_delay_seconds=None,
                    arrival_uncertainty_seconds=None,
                    predicted_departure=None,
                    departure_delay_seconds=None,
                    departure_uncertainty_seconds=None,
                    trip_schedule_relationship=trip_relationship,
                    stop_schedule_relationship=None,
                    source_record_id=record_id,
                )
            )
            continue

        for stu_index, stu in enumerate(update.stop_time_update):
            stop_id = stu.stop_id or None
            stop_sequence = (
                int(stu.stop_sequence)
                if stu.HasField("stop_sequence")
                else None
            )
            if stop_id is None and stop_sequence is None:
                findings.append(
                    DQFinding(
                        issue_type="malformed_entity",
                        severity=SEVERITY_WARNING,
                        title="StopTimeUpdate identifies no stop",
                        description=(
                            f"Record {record_id}, trip {trip.trip_id!r}, "
                            f"stop_time_update {stu_index}: neither stop_id "
                            "nor stop_sequence is present (the GTFS-RT spec "
                            "requires at least one). Event was quarantined, "
                            "not dropped silently."
                        ),
                        source_record_ids=[record_id],
                    )
                )
                continue

            def _event(field_name: str):
                """(predicted_time, delay_seconds, uncertainty_seconds)."""
                if not stu.HasField(field_name):
                    return None, None, None
                event = getattr(stu, field_name)
                predicted = (
                    _epoch_utc(int(event.time))
                    if event.HasField("time")
                    else None
                )
                delay = int(event.delay) if event.HasField("delay") else None
                uncertainty = (
                    int(event.uncertainty)
                    if event.HasField("uncertainty")
                    else None
                )
                return predicted, delay, uncertainty

            arr_time, arr_delay, arr_unc = _event("arrival")
            dep_time, dep_delay, dep_unc = _event("departure")
            stop_relationship = _relationship_name(
                stop_rel_enum,
                stu.schedule_relationship
                if stu.HasField("schedule_relationship")
                else stop_rel_enum.SCHEDULED,
            )

            _emit(
                CanonicalTripUpdate(
                    feed_timestamp=feed_timestamp,
                    trip_id=trip.trip_id,
                    route_id=route_id,
                    vehicle_id=vehicle_id,
                    stop_id=stop_id,
                    stop_sequence=stop_sequence,
                    predicted_arrival=arr_time,
                    arrival_delay_seconds=arr_delay,
                    arrival_uncertainty_seconds=arr_unc,
                    predicted_departure=dep_time,
                    departure_delay_seconds=dep_delay,
                    departure_uncertainty_seconds=dep_unc,
                    trip_schedule_relationship=trip_relationship,
                    stop_schedule_relationship=stop_relationship,
                    source_record_id=record_id,
                )
            )

    return rows, edges, findings
