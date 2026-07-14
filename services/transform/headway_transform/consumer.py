"""Consumer loop skeleton: envelope validate -> route by topic -> normalize -> write.

The Kafka client is deliberately hidden behind the tiny MessageSource
interface (poll() -> (topic, key, value) | None), so the client library is
swappable and unit tests run with an in-memory fake. The real implementation
(kafka-python-ng, Apache-2.0, installed via the 'kafka' extra) lives in
headway_transform.kafka_source.

Poison-message policy (fail loudly, never silently):
- invalid envelope  -> dq.issues row ('invalid_envelope'); if the message
  still carries enough envelope fields, a raw.records row with
  parse_status='malformed' is landed too, so the record is quarantined,
  never dropped;
- unhandled topic   -> raw.records row + dq.issues row ('unhandled_topic');
- normalizer/writer failure -> rollback + dq.issues row ('transform_failure');
- every failure is logged AND recorded; the loop continues — it never
  crashes on one message and never swallows an error without a trace.
"""

from __future__ import annotations

import json
import logging
from typing import Callable, Optional, Protocol

from . import (
    dr_trips,
    gtfs_rt_positions,
    gtfs_static,
    tides_passenger_events,
    trip_updates,
)
from .adapters import AdapterRegistry, run_adapter
from .envelope import Envelope, EnvelopeValidationError, parse_envelope
from .model import SEVERITY_BLOCKING, SEVERITY_WARNING, DQFinding
from .writer import DbWriter

logger = logging.getLogger(__name__)

TOPIC_GTFS_RT_VEHICLE_POSITIONS = "raw.gtfs_rt.vehicle_positions"
TOPIC_GTFS_RT_TRIP_UPDATES = "raw.gtfs_rt.trip_updates"
TOPIC_GTFS_STATIC_FEED = "raw.gtfs_static.feed"
TOPIC_TIDES_PASSENGER_EVENTS = "raw.tides.passenger_events"
TOPIC_DR_TRIPS = "raw.dr.trips"
TOPIC_VENDOR_FILES = "raw.vendor.files"

# Fetches object-store bytes for payload_encoding='object_ref' envelopes
# (GTFS static zips, TIDES passenger_events CSVs). Injected; the consumer
# has no object-store client.
ObjectFetcher = Callable[[str], bytes]


class ObjectTooLargeError(Exception):
    """An object_ref payload exceeded the configured fetch size cap.

    Raised by the process-boundary fetcher (__main__.py, 2026-07-13
    hardening pass: object fetches are stream-counted against
    HEADWAY_MAX_OBJECT_BYTES instead of buffering without bound). run_loop
    quarantines it as a blocking transform_failure dq.issues row whose
    description carries this exception's message — which names the limit.
    """


class MessageSource(Protocol):
    """Minimal message-source interface the loop consumes.

    poll() returns (topic, key, value) for the next message, or None when no
    message is currently available (the loop exits on None in run_loop's
    single-pass mode; a production wrapper may loop forever).
    """

    def poll(self) -> Optional[tuple[str, Optional[bytes], bytes]]: ...


def _quarantine_invalid_envelope(
    writer: DbWriter, raw_value: bytes, error: EnvelopeValidationError
) -> None:
    """Record an invalid envelope as raw.records (when possible) + dq.issues."""
    record_ids: list[str] = []
    # Best effort: if the message is JSON with the raw.records fields intact,
    # land the registry row so the payload stays addressable.
    try:
        doc = json.loads(raw_value)
    except (json.JSONDecodeError, UnicodeDecodeError):
        doc = None
    if isinstance(doc, dict):
        required = (
            "record_id",
            "source",
            "connector",
            "connector_version",
            "content_type",
            "payload_encoding",
            "fetched_at",
        )
        if all(isinstance(doc.get(field), str) and doc[field] for field in required):
            quarantined = Envelope(
                envelope_version=0,
                record_id=doc["record_id"],
                source=doc["source"],
                connector=doc["connector"],
                connector_version=doc["connector_version"],
                fetched_at=doc["fetched_at"],
                content_type=doc["content_type"],
                payload_encoding=doc["payload_encoding"],
                payload=str(doc.get("payload") or ""),
                parse_status="malformed",
                parse_error=f"envelope contract violation: {error}",
            )
            writer.insert_raw_record(quarantined)
            record_ids = [doc["record_id"]]

    writer.insert_dq_issues(
        [
            DQFinding(
                issue_type="invalid_envelope",
                severity=SEVERITY_BLOCKING,
                title="Kafka message is not a valid raw-record envelope v0",
                description=(
                    f"Message rejected by contract validation: {error}. "
                    + (
                        "Raw record landed with parse_status='malformed'."
                        if record_ids
                        else "Message carried too few envelope fields to land "
                        "a raw.records row; quarantined as this issue only."
                    )
                ),
                source_record_ids=record_ids,
            )
        ]
    )


def _handle_vehicle_positions(writer: DbWriter, envelope: Envelope) -> None:
    rows, edges, findings = gtfs_rt_positions.normalize(envelope)
    writer.insert_vehicle_positions(rows)
    writer.insert_lineage_edges(edges)
    writer.insert_dq_issues(findings)


def _handle_trip_updates(writer: DbWriter, envelope: Envelope) -> None:
    rows, edges, findings = trip_updates.normalize(envelope)
    writer.insert_trip_updates(rows)
    writer.insert_lineage_edges(edges)
    writer.insert_dq_issues(findings)


def _handle_gtfs_static(
    writer: DbWriter,
    envelope: Envelope,
    object_fetcher: Optional[ObjectFetcher],
) -> None:
    if envelope.payload_encoding == "object_ref":
        if object_fetcher is None:
            writer.insert_dq_issues(
                [
                    DQFinding(
                        issue_type="object_ref_unavailable",
                        severity=SEVERITY_BLOCKING,
                        title="GTFS static feed payload could not be fetched",
                        description=(
                            f"Record {envelope.record_id} references object "
                            f"{envelope.payload!r} but no object fetcher is "
                            "configured; feed not normalized (raw record "
                            "retained, nothing dropped)."
                        ),
                        source_record_ids=[envelope.record_id],
                    )
                ]
            )
            return
        zip_bytes = object_fetcher(envelope.payload)
    else:
        zip_bytes = envelope.decode_payload()

    routes, trips, stops, stop_times, agencies, edges, findings = (
        gtfs_static.normalize(zip_bytes, envelope.record_id)
    )
    writer.upsert_routes(routes)
    writer.upsert_trips(trips)
    writer.upsert_stops(stops)
    writer.upsert_stop_times(stop_times)
    writer.upsert_agencies(agencies)
    writer.insert_lineage_edges(edges)
    writer.insert_dq_issues(findings)


def _handle_tides_passenger_events(
    writer: DbWriter,
    envelope: Envelope,
    object_fetcher: Optional[ObjectFetcher],
) -> None:
    if envelope.payload_encoding == "object_ref":
        if object_fetcher is None:
            writer.insert_dq_issues(
                [
                    DQFinding(
                        issue_type="object_ref_unavailable",
                        severity=SEVERITY_BLOCKING,
                        title="TIDES passenger_events payload could not be fetched",
                        description=(
                            f"Record {envelope.record_id} references object "
                            f"{envelope.payload!r} but no object fetcher is "
                            "configured; file not normalized (raw record "
                            "retained, nothing dropped)."
                        ),
                        source_record_ids=[envelope.record_id],
                    )
                ]
            )
            return
        csv_bytes = object_fetcher(envelope.payload)
    else:
        csv_bytes = envelope.decode_payload()

    rows, edges, findings = tides_passenger_events.normalize(
        csv_bytes, envelope.record_id, envelope.source
    )
    writer.insert_passenger_events(rows)
    writer.insert_lineage_edges(edges)
    writer.insert_dq_issues(findings)


def _handle_dr_trips(
    writer: DbWriter,
    envelope: Envelope,
    object_fetcher: Optional[ObjectFetcher],
) -> None:
    if envelope.payload_encoding == "object_ref":
        if object_fetcher is None:
            writer.insert_dq_issues(
                [
                    DQFinding(
                        issue_type="object_ref_unavailable",
                        severity=SEVERITY_BLOCKING,
                        title="demand_response_trips payload could not be fetched",
                        description=(
                            f"Record {envelope.record_id} references object "
                            f"{envelope.payload!r} but no object fetcher is "
                            "configured; file not normalized (raw record "
                            "retained, nothing dropped)."
                        ),
                        source_record_ids=[envelope.record_id],
                    )
                ]
            )
            return
        csv_bytes = object_fetcher(envelope.payload)
    else:
        csv_bytes = envelope.decode_payload()

    rows, edges, findings = dr_trips.normalize(
        csv_bytes, envelope.record_id, envelope.source
    )
    writer.insert_dr_trips(rows)
    writer.insert_lineage_edges(edges)
    writer.insert_dq_issues(findings)


def _fetch_file_payload(
    writer: DbWriter,
    envelope: Envelope,
    object_fetcher: Optional[ObjectFetcher],
    what: str,
) -> Optional[bytes]:
    """Payload bytes for a file-carrying envelope (object_ref or base64).

    Returns None after writing the blocking 'object_ref_unavailable' finding
    when no fetcher is configured — loud degraded mode, never a drop.
    """
    if envelope.payload_encoding != "object_ref":
        return envelope.decode_payload()
    if object_fetcher is None:
        writer.insert_dq_issues(
            [
                DQFinding(
                    issue_type="object_ref_unavailable",
                    severity=SEVERITY_BLOCKING,
                    title=f"{what} payload could not be fetched",
                    description=(
                        f"Record {envelope.record_id} references object "
                        f"{envelope.payload!r} but no object fetcher is "
                        "configured; file not normalized (raw record "
                        "retained, nothing dropped)."
                    ),
                    source_record_ids=[envelope.record_id],
                )
            ]
        )
        return None
    return object_fetcher(envelope.payload)


def _handle_vendor_file(
    writer: DbWriter,
    envelope: Envelope,
    object_fetcher: Optional[ObjectFetcher],
    adapter_registry: Optional[AdapterRegistry],
) -> None:
    """Route a raw.vendor.files message through its registered adapter.

    Fail-closed source labels (handoff 0015): the envelope source must match
    a REGISTERED mapping spec. An unregistered label — or a consumer running
    without a registry — refuses the file with a blocking DQ issue; the raw
    record is retained (already landed), zero canonical rows are written, and
    nothing is guessed.
    """
    if adapter_registry is None:
        writer.insert_dq_issues(
            [
                DQFinding(
                    issue_type="adapter_registry_unavailable",
                    severity=SEVERITY_BLOCKING,
                    title="Vendor file arrived but no adapter registry is configured",
                    description=(
                        f"Record {envelope.record_id} (source "
                        f"{envelope.source!r}) arrived on raw.vendor.files "
                        "but this consumer has no adapter registry (set "
                        "HEADWAY_ADAPTERS_DIR to the adapters/ directory). "
                        "File refused, raw record retained — fail closed, "
                        "never guessed."
                    ),
                    source_record_ids=[envelope.record_id],
                )
            ]
        )
        return

    spec = adapter_registry.lookup(envelope.source)
    if spec is None:
        logger.warning(
            "unregistered vendor source label %r; refusing", envelope.source
        )
        writer.insert_dq_issues(
            [
                DQFinding(
                    issue_type="unregistered_adapter_source",
                    severity=SEVERITY_BLOCKING,
                    title=(
                        f"Vendor file source label {envelope.source!r} is not "
                        "a registered adapter"
                    ),
                    description=(
                        f"Record {envelope.record_id} carries source "
                        f"{envelope.source!r}, which matches no registered "
                        "mapping spec (registered: "
                        + (", ".join(adapter_registry.labels()) or "<none>")
                        + "). File REFUSED — raw record retained, zero "
                        "canonical rows written. Register a mapping spec "
                        "(adapters/README.md) or fix the connector's source "
                        "label; an unregistered label is never mapped by "
                        "guesswork (fail closed)."
                    ),
                    source_record_ids=[envelope.record_id],
                )
            ]
        )
        return

    file_bytes = _fetch_file_payload(
        writer, envelope, object_fetcher, f"Vendor file ({envelope.source})"
    )
    if file_bytes is None:
        return

    result = run_adapter(spec, file_bytes, envelope.record_id, envelope.source)
    writer.insert_passenger_events(result.passenger_events)
    writer.insert_dr_trips(result.dr_trips)
    writer.insert_lineage_edges(result.edges)
    writer.insert_dq_issues(result.findings)


def process_message(
    writer: DbWriter,
    topic: str,
    value: bytes,
    object_fetcher: Optional[ObjectFetcher] = None,
    adapter_registry: Optional[AdapterRegistry] = None,
) -> None:
    """Process one message: validate, land raw record, route, normalize, write.

    Raises nothing for data problems (they become dq.issues rows); unexpected
    infrastructure errors propagate to run_loop's per-message handler.
    """
    try:
        envelope = parse_envelope(value)
    except EnvelopeValidationError as error:
        logger.warning("invalid envelope on %s: %s", topic, error)
        _quarantine_invalid_envelope(writer, value, error)
        return

    # Every validated envelope lands in the raw.records registry first —
    # normalization failures must never orphan the lineage anchor.
    writer.insert_raw_record(envelope)

    if topic == TOPIC_GTFS_RT_VEHICLE_POSITIONS:
        _handle_vehicle_positions(writer, envelope)
    elif topic == TOPIC_GTFS_RT_TRIP_UPDATES:
        _handle_trip_updates(writer, envelope)
    elif topic == TOPIC_GTFS_STATIC_FEED:
        _handle_gtfs_static(writer, envelope, object_fetcher)
    elif topic == TOPIC_TIDES_PASSENGER_EVENTS:
        _handle_tides_passenger_events(writer, envelope, object_fetcher)
    elif topic == TOPIC_DR_TRIPS:
        _handle_dr_trips(writer, envelope, object_fetcher)
    elif topic == TOPIC_VENDOR_FILES:
        _handle_vendor_file(writer, envelope, object_fetcher, adapter_registry)
    else:
        logger.warning("no normalizer for topic %s", topic)
        writer.insert_dq_issues(
            [
                DQFinding(
                    issue_type="unhandled_topic",
                    severity=SEVERITY_WARNING,
                    title=f"No normalizer registered for topic {topic}",
                    description=(
                        f"Record {envelope.record_id} arrived on {topic!r}, "
                        "which this consumer has no normalizer for. Raw "
                        "record landed; nothing normalized, nothing dropped."
                    ),
                    source_record_ids=[envelope.record_id],
                )
            ]
        )


def run_loop(
    source: MessageSource,
    writer: DbWriter,
    object_fetcher: Optional[ObjectFetcher] = None,
    max_messages: Optional[int] = None,
    adapter_registry: Optional[AdapterRegistry] = None,
) -> int:
    """Consume messages until the source yields None (or max_messages).

    Per-message failures are logged AND written as dq.issues rows, then the
    loop continues — a poison message never kills the consumer and is never
    dropped without a trace. Returns the number of messages processed.
    """
    processed = 0
    while max_messages is None or processed < max_messages:
        polled = source.poll()
        if polled is None:
            break
        topic, _key, value = polled
        try:
            process_message(writer, topic, value, object_fetcher, adapter_registry)
            writer.connection.commit()
        except Exception as exc:  # noqa: BLE001 — quarantine path, never a bare pass
            logger.exception("message on %s failed; quarantining", topic)
            writer.connection.rollback()
            try:
                writer.insert_dq_issues(
                    [
                        DQFinding(
                            issue_type="transform_failure",
                            severity=SEVERITY_BLOCKING,
                            title=f"Unhandled failure processing a message on {topic}",
                            description=(
                                "Processing raised "
                                f"{type(exc).__name__}: {exc} "
                                "(full stack trace in the service logs); the "
                                "transaction was rolled back and the message "
                                "quarantined as this issue. Kafka retains the "
                                "message bytes for replay."
                            ),
                            source_record_ids=[],
                        )
                    ]
                )
                writer.connection.commit()
            except Exception:  # noqa: BLE001
                # Even the quarantine write failed (e.g. DB down). Log loudly
                # and re-raise: continuing here WOULD be a silent drop.
                logger.exception(
                    "failed to write dq.issues quarantine row for %s; aborting loop",
                    topic,
                )
                raise
        processed += 1
    return processed
