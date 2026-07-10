"""Normalizer: raw.tides.passenger_events -> canonical.passenger_events.

Parses one TIDES passenger_events CSV file (stdlib csv) into
CanonicalPassengerEvent dataclasses per handoff 0005 (migration 0012,
column-for-column), with one LineageEdge per row back to the file's
content-addressed record_id, and a DQFinding for every row that could not
be normalized — never a silent skip.

Field names, required fields, the event_type enumeration and the
missing-value tokens below were verified against the TIDES spec
(TIDES-transit/TIDES spec/passenger_events.schema.json, main branch,
fetched 2026-07-10) — VERIFY against the current published spec before
extending.

Simulated-data rule (handoff 0005, binding): the envelope source
('tides' | 'tides_simulated') is carried verbatim into every row's source
column so simulated records stay permanently distinguishable in provenance.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timezone

from .model import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    DQFinding,
    LineageEdge,
)

TRANSFORM_NAME = "normalize_tides_passenger_events"
TRANSFORM_VERSION = "0.1.0"

TOPIC = "raw.tides.passenger_events"
OUTPUT_KIND = "canonical.passenger_events"
INPUT_KIND = "raw.records"

# Fields with "constraints": {"required": true} in the verified TIDES schema:
# passenger_event_id, service_date, event_timestamp, trip_stop_sequence
# (integer, minimum 1), event_type, vehicle_id. trip_id_performed and
# event_count (integer, minimum 0) are optional.
REQUIRED_FIELDS = (
    "passenger_event_id",
    "service_date",
    "event_timestamp",
    "trip_stop_sequence",
    "event_type",
    "vehicle_id",
)

# The full event_type enum from the verified TIDES schema (16 values,
# fetched 2026-07-10). Any value outside this set is a DQFinding, never a
# guess — the UPT calc's boarding/alighting selection depends on exact
# membership.
EVENT_TYPES = frozenset(
    {
        "Vehicle arrived at stop",
        "Vehicle departed stop",
        "Door opened",
        "Door closed",
        "Passenger boarded",
        "Passenger alighted",
        "Kneel was engaged",
        "Kneel was disengaged",
        "Ramp was deployed",
        "Ramp was raised",
        "Ramp deployment failed",
        "Lift was deployed",
        "Lift was raised",
        "Individual bike boarded",
        "Individual bike alighted",
        "Bike rack deployed",
    }
)

# Tokens the verified TIDES schema declares as missingValues: an event_count
# of "NA"/"NaN"/"" is an ABSENT count (stored NULL, never coalesced), not a
# malformed one.
MISSING_VALUES = frozenset({"NA", "NaN", ""})


@dataclass(frozen=True)
class CanonicalPassengerEvent:
    """One canonical.passenger_events row (handoff 0005 / migration 0012)."""

    event_timestamp: datetime  # TIMESTAMPTZ NOT NULL — event time (hypertable)
    service_date: date  # DATE NOT NULL
    passenger_event_id: str  # TEXT NOT NULL
    vehicle_id: str  # TEXT NOT NULL
    trip_id: str | None  # TEXT — TIDES trip_id_performed; optional, never guessed
    trip_stop_sequence: int | None  # INTEGER
    event_type: str  # TEXT NOT NULL — verified TIDES enum member
    event_count: int | None  # INTEGER — NULL preserved as NULL, never coalesced
    source: str  # TEXT NOT NULL — envelope source ('tides' | 'tides_simulated')
    source_record_id: str  # TEXT NOT NULL REFERENCES raw.records

    @property
    def output_id(self) -> str:
        """Natural key rendered as text for lineage.edges.output_id."""
        return (
            f"{self.passenger_event_id}|{rfc3339(self.event_timestamp)}"
            f"|{self.source_record_id}"
        )


def rfc3339(dt: datetime) -> str:
    """Render a timezone-aware datetime as RFC 3339 in UTC with a 'Z' suffix."""
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _cell(row: dict[str, str], name: str) -> str:
    """A row value with TIDES missing-value tokens normalized to ''."""
    value = (row.get(name) or "").strip()
    return "" if value in MISSING_VALUES else value


def normalize(
    csv_bytes: bytes, record_id: str, source: str
) -> tuple[list[CanonicalPassengerEvent], list[LineageEdge], list[DQFinding]]:
    """Normalize one TIDES passenger_events CSV file.

    Returns (rows, lineage_edges, dq_findings). Every emitted row has exactly
    one lineage edge (input = the file's record_id) and carries the envelope
    source verbatim; every row that cannot be normalized is a DQFinding
    ('malformed_passenger_event' citing the record_id and row number) — the
    row is skipped from canonical, but NEVER silently.
    """
    rows: list[CanonicalPassengerEvent] = []
    edges: list[LineageEdge] = []
    findings: list[DQFinding] = []

    try:
        # utf-8-sig: CSV exports commonly carry a BOM.
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        findings.append(
            DQFinding(
                issue_type="undecodable_payload",
                severity=SEVERITY_BLOCKING,
                title="TIDES passenger_events payload is not readable CSV text",
                description=(
                    f"Record {record_id}: {exc}. File was not normalized; "
                    "raw record retained."
                ),
                source_record_ids=[record_id],
            )
        )
        return rows, edges, findings

    def _malformed(index: int, problems: list[str]) -> DQFinding:
        return DQFinding(
            issue_type="malformed_passenger_event",
            severity=SEVERITY_WARNING,
            title="TIDES passenger_events row could not be normalized",
            description=(
                f"Record {record_id}, passenger_events row {index}: "
                + "; ".join(problems)
                + ". Row quarantined, not dropped silently."
            ),
            source_record_ids=[record_id],
        )

    row_count = 0
    for index, row in enumerate(csv.DictReader(io.StringIO(text, newline=""))):
        row_count += 1
        problems: list[str] = []

        missing = [name for name in REQUIRED_FIELDS if not _cell(row, name)]
        if missing:
            problems.append(
                "missing required field(s) "
                + ", ".join(missing)
                + " (required per the TIDES passenger_events schema)"
            )

        # event_timestamp: TIDES declares Frictionless type 'datetime'
        # (default format: ISO 8601 YYYY-MM-DDThh:mm:ssZ in UTC — Table
        # Schema spec, specs.frictionlessdata.io, verified 2026-07-10). A
        # timestamp with no UTC offset is ambiguous: the zone is never
        # guessed — the row becomes a finding instead.
        event_timestamp: datetime | None = None
        raw_timestamp = _cell(row, "event_timestamp")
        if raw_timestamp:
            try:
                event_timestamp = datetime.fromisoformat(raw_timestamp)
            except ValueError:
                problems.append(
                    f"event_timestamp {raw_timestamp!r} is not an ISO 8601 "
                    "datetime"
                )
            else:
                if event_timestamp.tzinfo is None:
                    problems.append(
                        f"event_timestamp {raw_timestamp!r} carries no UTC "
                        "offset (TIDES datetime is ISO 8601 in UTC); the "
                        "timezone is never guessed"
                    )
                    event_timestamp = None

        service_date: date | None = None
        raw_date = _cell(row, "service_date")
        if raw_date:
            try:
                service_date = date.fromisoformat(raw_date)
            except ValueError:
                problems.append(
                    f"service_date {raw_date!r} is not an ISO 8601 date"
                )

        raw_sequence = _cell(row, "trip_stop_sequence")
        trip_stop_sequence: int | None = None
        if raw_sequence:
            try:
                trip_stop_sequence = int(raw_sequence)
            except ValueError:
                problems.append(
                    f"trip_stop_sequence {raw_sequence!r} is not an integer"
                )
            else:
                if trip_stop_sequence < 1:
                    problems.append(
                        f"trip_stop_sequence {trip_stop_sequence} violates "
                        "the TIDES schema constraint minimum 1"
                    )

        event_type = _cell(row, "event_type")
        if event_type and event_type not in EVENT_TYPES:
            problems.append(
                f"event_type {event_type!r} is not in the verified TIDES "
                "event_type enumeration"
            )

        # event_count is OPTIONAL per the verified TIDES schema; an absent
        # column or missing-value token is NULL — preserved as NULL, never
        # coalesced (not to 0, not to the schema's documented default of 1):
        # a fabricated count would silently corrupt UPT (fail loudly instead).
        event_count: int | None = None
        raw_count = _cell(row, "event_count")
        if raw_count:
            try:
                event_count = int(raw_count)
            except ValueError:
                problems.append(f"event_count {raw_count!r} is not an integer")
            else:
                if event_count < 0:
                    problems.append(
                        f"event_count {event_count} violates the TIDES "
                        "schema constraint minimum 0"
                    )

        if problems:
            findings.append(_malformed(index, problems))
            continue

        assert event_timestamp is not None and service_date is not None
        event = CanonicalPassengerEvent(
            event_timestamp=event_timestamp,
            service_date=service_date,
            passenger_event_id=_cell(row, "passenger_event_id"),
            vehicle_id=_cell(row, "vehicle_id"),
            trip_id=_cell(row, "trip_id_performed") or None,
            trip_stop_sequence=trip_stop_sequence,
            event_type=event_type,
            event_count=event_count,
            source=source,
            source_record_id=record_id,
        )
        rows.append(event)
        edges.append(
            LineageEdge(
                output_kind=OUTPUT_KIND,
                output_id=event.output_id,
                transform_name=TRANSFORM_NAME,
                transform_version=TRANSFORM_VERSION,
                input_kind=INPUT_KIND,
                input_id=record_id,
            )
        )

    if row_count == 0:
        findings.append(
            DQFinding(
                issue_type="empty_passenger_events_file",
                severity=SEVERITY_INFO,
                title="TIDES passenger_events file contains no data rows",
                description=(
                    f"Record {record_id}: the CSV has no data rows (header "
                    "only, or empty file). Nothing normalized; recorded so "
                    "an empty delivery is visible, not silent."
                ),
                source_record_ids=[record_id],
            )
        )

    return rows, edges, findings
