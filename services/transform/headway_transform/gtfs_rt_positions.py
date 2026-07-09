"""Normalizer: raw.gtfs_rt.vehicle_positions -> canonical.vehicle_positions.

Decodes a base64 GTFS-Realtime FeedMessage protobuf frame (payload semantics
per gtfs.org/documentation/realtime/reference — verify against the current
published spec) using gtfs-realtime-bindings (Apache-2.0), and emits:

- CanonicalVehiclePosition rows matching canonical.vehicle_positions
  (handoff 0001) column-for-column;
- exactly one LineageEdge per row (output_id '<vehicle_id>|<time RFC3339>|<record_id>');
- a DQFinding for every payload/entity that could not be normalized —
  NEVER a silent skip (role guardrail: fail loudly).

Event-time policy (handoff 0001: "time" is event time, never ingest time):
- entity VehiclePosition.timestamp when present;
- else the FeedMessage header timestamp, noted as an info-severity
  DQFinding (issue_type 'missing_entity_timestamp');
- if BOTH are absent the entity becomes a DQFinding ('malformed_entity');
  we never guess a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from google.protobuf.message import DecodeError
from google.transit import gtfs_realtime_pb2

from .envelope import Envelope, PayloadDecodeError
from .model import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    DQFinding,
    LineageEdge,
)

TRANSFORM_NAME = "normalize_gtfs_rt_positions"
TRANSFORM_VERSION = "0.1.0"

TOPIC = "raw.gtfs_rt.vehicle_positions"
OUTPUT_KIND = "canonical.vehicle_positions"
INPUT_KIND = "raw.records"


@dataclass(frozen=True)
class CanonicalVehiclePosition:
    """One canonical.vehicle_positions row (handoff 0001, column-for-column)."""

    time: datetime  # TIMESTAMPTZ NOT NULL — event time from the feed
    vehicle_id: str  # TEXT NOT NULL
    trip_id: str | None  # TEXT — unassigned stays unassigned, never guessed
    route_id: str | None  # TEXT
    latitude: float  # DOUBLE PRECISION NOT NULL
    longitude: float  # DOUBLE PRECISION NOT NULL
    bearing: float | None  # REAL
    speed_mps: float | None  # REAL
    odometer_m: float | None  # DOUBLE PRECISION
    source_record_id: str  # TEXT NOT NULL REFERENCES raw.records

    @property
    def output_id(self) -> str:
        """Natural key rendered as text for lineage.edges.output_id."""
        return f"{self.vehicle_id}|{rfc3339(self.time)}|{self.source_record_id}"


def rfc3339(dt: datetime) -> str:
    """Render a UTC datetime as RFC 3339 with a 'Z' suffix."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch_utc(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def normalize(
    envelope: Envelope,
) -> tuple[list[CanonicalVehiclePosition], list[LineageEdge], list[DQFinding]]:
    """Normalize one raw.gtfs_rt.vehicle_positions envelope.

    Returns (rows, lineage_edges, dq_findings). Every row has exactly one
    lineage edge; every failure is a DQFinding. This function does not raise
    for bad payload content — undecodable input is data, and data problems
    are dq.issues rows, not crashes (the consumer quarantines them).
    """
    record_id = envelope.record_id

    # Connector already flagged the payload malformed: honor that loudly and
    # do not attempt to normalize (the record still lands in raw.records).
    if envelope.parse_status == "malformed":
        return (
            [],
            [],
            [
                DQFinding(
                    issue_type="undecodable_payload",
                    severity=SEVERITY_BLOCKING,
                    title="Connector flagged GTFS-RT payload as malformed",
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
                    title="GTFS-RT payload could not be decoded from envelope",
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
                    title="GTFS-RT payload is not a parseable FeedMessage",
                    description=(
                        f"Record {record_id}: protobuf decode failed: {exc}. "
                        "Payload was not normalized; raw record retained."
                    ),
                    source_record_ids=[record_id],
                )
            ],
        )

    header_ts: int | None = (
        int(feed.header.timestamp) if feed.header.HasField("timestamp") else None
    )

    rows: list[CanonicalVehiclePosition] = []
    edges: list[LineageEdge] = []
    findings: list[DQFinding] = []

    for index, entity in enumerate(feed.entity):
        problems: list[str] = []

        if not entity.HasField("vehicle"):
            problems.append("entity has no VehiclePosition")
            vehicle = None
        else:
            vehicle = entity.vehicle
            if not (
                vehicle.HasField("vehicle") and vehicle.vehicle.id
            ):
                problems.append("VehiclePosition has no vehicle descriptor id")
            if not vehicle.HasField("position"):
                problems.append("VehiclePosition has no position")

        # Event time: entity timestamp, else header timestamp (noted), else
        # this entity is a finding — a time is never guessed.
        event_time: datetime | None = None
        if vehicle is not None and not problems:
            if vehicle.HasField("timestamp"):
                event_time = _epoch_utc(int(vehicle.timestamp))
            elif header_ts is not None:
                event_time = _epoch_utc(header_ts)
                findings.append(
                    DQFinding(
                        issue_type="missing_entity_timestamp",
                        severity=SEVERITY_INFO,
                        title="Vehicle position used feed header timestamp",
                        description=(
                            f"Record {record_id}, entity {entity.id or index}: "
                            "VehiclePosition carries no timestamp; the "
                            "FeedMessage header timestamp "
                            f"{rfc3339(_epoch_utc(header_ts))} was used as "
                            "event time. Header time is feed snapshot time, "
                            "not vehicle report time."
                        ),
                        source_record_ids=[record_id],
                    )
                )
            else:
                problems.append(
                    "neither VehiclePosition.timestamp nor FeedMessage header "
                    "timestamp is present; event time cannot be determined "
                    "and is never guessed"
                )

        if problems or vehicle is None or event_time is None:
            findings.append(
                DQFinding(
                    issue_type="malformed_entity",
                    severity=SEVERITY_WARNING,
                    title="GTFS-RT entity could not be normalized",
                    description=(
                        f"Record {record_id}, entity {entity.id or index}: "
                        + "; ".join(problems)
                        + ". Entity was quarantined, not dropped silently."
                    ),
                    source_record_ids=[record_id],
                )
            )
            continue

        trip = vehicle.trip if vehicle.HasField("trip") else None
        row = CanonicalVehiclePosition(
            time=event_time,
            vehicle_id=vehicle.vehicle.id,
            trip_id=(trip.trip_id if trip is not None and trip.trip_id else None),
            route_id=(trip.route_id if trip is not None and trip.route_id else None),
            latitude=vehicle.position.latitude,
            longitude=vehicle.position.longitude,
            bearing=(
                vehicle.position.bearing
                if vehicle.position.HasField("bearing")
                else None
            ),
            speed_mps=(
                vehicle.position.speed
                if vehicle.position.HasField("speed")
                else None
            ),
            odometer_m=(
                vehicle.position.odometer
                if vehicle.position.HasField("odometer")
                else None
            ),
            source_record_id=record_id,
        )
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

    return rows, edges, findings
