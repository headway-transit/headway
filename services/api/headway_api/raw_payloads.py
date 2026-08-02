"""Reading, classifying and decoding the bytes behind a raw record.

This module is the machinery under ``routers/raw_records.py`` — the last
link in the chain of custody (handoff 0035). It answers four questions
about one ``raw.records`` row, and nothing else:

1. **Where do the bytes live?** Headway stores raw payloads in two places,
   and which one is a property of the record, not a guess:
   ``payload_encoding = 'object_ref'`` means the object store holds them at
   ``payload_ref``; ``payload_encoding = 'base64'`` means they rode inline
   in the ingest envelope on the Kafka topic (contracts/topics.v0.md — the
   GTFS-Realtime connector is the only base64 producer today, and
   ``raw.records`` is deliberately an index, not a payload table:
   migration 0002). Both are read behind ONE seam so tests use fakes.
2. **Who may look inside?** Sensitivity follows the payload, not the
   storage layer (docs/data-classification.md). Demand-response /
   paratransit payloads carry rider pickup and dropoff coordinates — rider
   home and destination addresses — so the preview enforces the same
   withholding migration 0028 already enforces on the analyst SQL path.
3. **Can it be read back?** Honest failure modes, each distinct and each
   named: the store is not configured, the object is gone (a genuine
   finding), the envelope stream no longer retains the message (by design,
   not a defect), the store is unreachable.
4. **What is inside?** A bounded, decoded preview for the two payload kinds
   v0 decodes — GTFS-Realtime protobuf and text/delimited text — and a
   plain statement of type plus a download offer for everything else. No
   decoder ever invents a field name, a column label or a value.

Nothing here mutates anything. Raw records are immutable by database
trigger (migration 0002); this module only ever reads.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import logging
import os
from dataclasses import dataclass
from typing import Iterable, Iterator, Optional, Protocol

_log = logging.getLogger("headway_api.raw_payloads")

# ---------------------------------------------------------------------------
# The record, as this module needs it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawRecord:
    """One ``raw.records`` row, verbatim. Absent columns stay ``None``."""

    record_id: str
    source: str
    connector: str
    connector_version: str
    content_type: str
    payload_encoding: str
    payload_ref: Optional[str]
    fetched_at: dt.datetime
    landed_at: dt.datetime
    parse_status: str
    parse_error: Optional[str]


#: The columns ``routers/raw_records.py`` selects, in this order.
RECORD_COLUMNS = (
    "record_id, source, connector, connector_version, content_type, "
    "payload_encoding, payload_ref, fetched_at, landed_at, parse_status, "
    "parse_error"
)


def record_from_row(row) -> RawRecord:
    return RawRecord(
        record_id=str(row[0]),
        source=row[1],
        connector=row[2],
        connector_version=row[3],
        content_type=row[4],
        payload_encoding=row[5],
        payload_ref=row[6],
        fetched_at=row[7],
        landed_at=row[8],
        parse_status=row[9],
        parse_error=row[10],
    )


# ---------------------------------------------------------------------------
# Sensitivity — who may look inside (docs/data-classification.md)
# ---------------------------------------------------------------------------

#: Classification labels. These are the payload's class, not the storage's:
#: "Raw ingested records (object store) — inherits the highest class of its
#: contents" (docs/data-classification.md).
CLASS_RIDER_LOCATION = "rider_location"
CLASS_UNDETERMINED = "undetermined"
CLASS_INTERNAL = "internal"

#: The demand-response connector produces exactly one thing: a
#: ``demand_response_trip`` v0 CSV (contracts/topics.v0.md, raw.dr.trips).
DR_CONNECTORS = frozenset({"headway-dr"})

#: Object-key layout the DR connector and the DR ingest endpoint both use
#: (services/ingestion/connectors/dr, routers/ingest.dr_object_key). The
#: machine-ingest connector name (``headway-api-ingest``) lands BOTH TIDES
#: and DR files, so the key prefix — not the connector — is what separates
#: them.
DR_OBJECT_PREFIX = "raw/dr/"

#: The generic vendor-export connector. What a vendor export MEANS is
#: defined only by the registered mapping spec (adapters/<vendor>/<product>/
#: mapping.v0.yaml), which the API does not hold — and one of the reference
#: specs (acme/paravan) targets ``demand_response_trip``. A vendor export can
#: therefore be a paratransit booking file, so it is gated fail-closed rather
#: than assumed harmless.
VENDOR_CONNECTOR = "headway-vendor-file"

#: The role floor for a payload that can carry rider locations. The
#: four-role model is an escalating hierarchy (authz.py), so this admits
#: data steward, report preparer and certifying official, and excludes the
#: broadest read role — the same shape as migration 0028's decision to
#: withhold DR coordinates from the read-only analyst role.
RESTRICTED_MINIMUM_ROLE = "data_steward"
OPEN_MINIMUM_ROLE = "viewer"


@dataclass(frozen=True)
class Sensitivity:
    classification: str
    label: str
    minimum_role: str
    reason: str
    #: Plain-language refusal served to a caller below ``minimum_role``.
    refusal: Optional[str]


_RIDER_LOCATION_REASON = (
    "This is a demand-response (paratransit) source record. Its rows carry "
    "pickup and dropoff coordinates, which are rider home and destination "
    "addresses, and an ADA paratransit trip record can disclose disability "
    "status by its mere existence. Headway already withholds these "
    "coordinates from the read-only analyst database role (migration 0028); "
    "the same withholding applies here, because a raw record is as sensitive "
    "as the payload inside it."
)

_UNDETERMINED_REASON = (
    "This is a vendor export. What its columns mean is defined only by the "
    "registered mapping spec for this source, which the raw-record index "
    "does not hold — and a vendor export can be a paratransit booking file "
    "carrying rider addresses. Headway applies the stricter rule rather than "
    "assume the safer one."
)

_INTERNAL_REASON = (
    "Agency operational data (docs/data-classification.md). Any signed-in "
    "role may open it; every look is recorded in the audit trail."
)


def _refusal(sensitivity_reason: str) -> str:
    return (
        "Your account cannot open the contents of this raw record. "
        + sensitivity_reason
        + " You can still see this record's label and prove its bytes are "
        "unaltered — only the contents are withheld. Ask your Headway "
        "administrator if your work requires this access."
    )


#: Stand-in served instead of ``parse_error`` when a record's contents are
#: withheld from the caller.
PARSE_ERROR_WITHHELD = (
    "A parser message was recorded for this record, but it is withheld from "
    "your account along with the contents. Parser output can quote fragments "
    "of the payload it failed on, so it is treated as content rather than as "
    "a label. The record's parse status above still tells you the file was "
    "malformed."
)


def visible_parse_error(
    parse_error: Optional[str], *, readable: bool
) -> Optional[str]:
    """``parse_error`` for a caller who may not read this record's contents.

    Migration 0028 already withholds this column from the read-only analyst
    SQL role, and says why in its own header: it is "populated from parser
    output that can quote fragments of a malformed payload verbatim —
    **content, not metadata**". The API had no matching rule, so the same
    column that is unreadable over psql was served over HTTP to every
    signed-in role, including ``auditor``, for records whose payload is
    withheld. Two enforcement layers for one privacy decision had drifted
    apart, and the weaker one was this side. (External review, 2026-08-02.)

    No live leak was found: every writer today — ``routers/ingest.py``'s
    ``_check_header`` ("never inspects data rows") and the Go connectors'
    ``checkHeader`` — reports only missing column names taken from a
    constant. That invariant is held by convention across two languages and
    nothing enforces it, so this closes the hole at the read side, where it
    stays closed no matter what a future connector writes.

    ``parse_status`` is deliberately NOT withheld: "this file was malformed"
    is a fact about the record, and hiding it would turn a withheld reason
    into an apparently healthy record.
    """
    if parse_error is None or readable:
        return parse_error
    return PARSE_ERROR_WITHHELD


def classify(record: RawRecord) -> Sensitivity:
    """The withholding rule, decided from the record's own ingest metadata.

    Deliberately NOT decided from downstream evidence (e.g. joining
    ``canonical.dr_trips.source_record_id``): a paratransit file that has
    landed but not yet been transformed must be withheld from the first
    second it exists, not from the moment a transform proves what it was.
    """
    is_dr = record.connector in DR_CONNECTORS or (
        (record.payload_ref or "").startswith(DR_OBJECT_PREFIX)
    )
    if is_dr:
        return Sensitivity(
            classification=CLASS_RIDER_LOCATION,
            label="Rider locations — restricted",
            minimum_role=RESTRICTED_MINIMUM_ROLE,
            reason=_RIDER_LOCATION_REASON,
            refusal=_refusal(_RIDER_LOCATION_REASON),
        )
    if record.connector == VENDOR_CONNECTOR:
        return Sensitivity(
            classification=CLASS_UNDETERMINED,
            label="Vendor export — contents not classified, restricted",
            minimum_role=RESTRICTED_MINIMUM_ROLE,
            reason=_UNDETERMINED_REASON,
            refusal=_refusal(_UNDETERMINED_REASON),
        )
    return Sensitivity(
        classification=CLASS_INTERNAL,
        label="Agency operational data",
        minimum_role=OPEN_MINIMUM_ROLE,
        reason=_INTERNAL_REASON,
        refusal=None,
    )


# ---------------------------------------------------------------------------
# Reading the bytes back — the seam
# ---------------------------------------------------------------------------

LOCATION_OBJECT_STORE = "object_store"
LOCATION_ENVELOPE_STREAM = "ingest_envelope_stream"

#: Reason codes for "the bytes are not readable". Each is a DIFFERENT thing
#: and is reported as a different thing; none of them is silently an empty
#: preview.
REASON_NOT_CONFIGURED = "not_configured"
REASON_OBJECT_MISSING = "object_missing"
REASON_NOT_RETAINED = "not_retained"
REASON_STORE_UNREACHABLE = "store_unreachable"

#: HTTP status per reason. A missing object is 404 because the evidence bag
#: really is gone; an expired stream window is 410 Gone because the bytes
#: were never kept, by design, and that is a different sentence.
REASON_STATUS = {
    REASON_NOT_CONFIGURED: 503,
    REASON_OBJECT_MISSING: 404,
    REASON_NOT_RETAINED: 410,
    REASON_STORE_UNREACHABLE: 503,
}


class PayloadUnavailable(Exception):
    """The stored bytes could not be read. Always carries a reason code and
    a sentence a transit operations manager can act on."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message

    @property
    def status_code(self) -> int:
        return REASON_STATUS.get(self.reason, 503)


@dataclass(frozen=True)
class PayloadHandle:
    """An open read of one record's payload."""

    location: str
    #: Total stored size in bytes when known cheaply, else None.
    size_bytes: Optional[int]
    chunks: Iterator[bytes]


class RawPayloadReader(Protocol):
    """The one thing the raw-record endpoints need from storage."""

    def open(self, record: RawRecord) -> PayloadHandle: ...

    def size(self, record: RawRecord) -> Optional[int]:
        """Stored size without reading the bytes; None when not cheap."""


#: Streaming chunk size for hashing and download.
CHUNK_BYTES = 1024 * 1024


class ObjectStorePayloadReader:
    """``payload_encoding = 'object_ref'`` — the object store at ``payload_ref``.

    Uses the injected store's streaming read when it has one (MinIO does)
    and falls back to a whole-object read otherwise, so a 24 MB GTFS static
    zip is hashed a megabyte at a time rather than held whole.
    """

    def __init__(self, store):
        self._store = store

    def _key(self, record: RawRecord) -> str:
        key = record.payload_ref
        if not key:
            raise PayloadUnavailable(
                REASON_OBJECT_MISSING,
                "This record says its bytes are in the object store but "
                "records no object key, so Headway cannot find them. The "
                "record's identity is intact; its payload is not locatable. "
                "This is a pipeline defect worth reporting.",
            )
        return key

    def size(self, record: RawRecord) -> Optional[int]:
        return self.size_key(self._key(record))

    def size_key(self, key: str) -> Optional[int]:
        stat = getattr(self._store, "stat", None)
        if stat is None:
            return None
        try:
            size = stat(key)
            if size is None:
                # The store answered, and the answer is that the object is
                # not there. That is a finding, not a missing measurement.
                raise PayloadUnavailable(
                    REASON_OBJECT_MISSING, _missing_object_message(key)
                )
            return size
        except PayloadUnavailable:
            raise
        except Exception as exc:  # pragma: no cover - live-store failure path
            raise PayloadUnavailable(
                REASON_STORE_UNREACHABLE,
                "Headway could not reach the object store that holds this "
                f"record's bytes ({exc.__class__.__name__}). The record "
                "itself is unaffected; try again, or ask your administrator "
                "to check the object store.",
            ) from exc

    def open(self, record: RawRecord) -> PayloadHandle:
        return self.open_key(self._key(record))

    def open_key(self, key: str) -> PayloadHandle:
        stream = getattr(self._store, "stream", None)
        try:
            if stream is not None:
                size, chunks = stream(key)
                if chunks is None:
                    raise PayloadUnavailable(
                        REASON_OBJECT_MISSING, _missing_object_message(key)
                    )
                return PayloadHandle(LOCATION_OBJECT_STORE, size, chunks)
            data = self._store.get(key)
        except PayloadUnavailable:
            raise
        except Exception as exc:  # pragma: no cover - live-store failure path
            raise PayloadUnavailable(
                REASON_STORE_UNREACHABLE,
                "Headway could not reach the object store that holds this "
                f"record's bytes ({exc.__class__.__name__}). The record "
                "itself is unaffected; try again, or ask your administrator "
                "to check the object store.",
            ) from exc
        if data is None:
            raise PayloadUnavailable(REASON_OBJECT_MISSING, _missing_object_message(key))
        return PayloadHandle(LOCATION_OBJECT_STORE, len(data), iter((data,)))


def _missing_object_message(key: str) -> str:
    return (
        "This record is registered in Headway's ingest index, but the bytes "
        f"are not in the object store at {key}. A raw record is supposed to "
        "be immutable and permanent, so this is a real finding: the evidence "
        "for anything computed from this record cannot be produced. Report "
        "it to whoever administers this installation."
    )


#: Deterministic object-store keys for base64 (broker-inline) records, by
#: source (handoff 0036). The GTFS-Realtime connector now lands every frame
#: at this key BEFORE producing, and the backfill tool rescued what the
#: broker still held to the same key — but legacy ``raw.records`` rows keep
#: ``payload_encoding='base64'`` forever (the index is immutable by
#: trigger), so the key must be derivable from the row's own columns. It is:
#: source + record_id, nothing else. Mirrors ``gtfsrt.ObjectKey`` in
#: services/ingestion/connectors/gtfsrt/objectstore.go.
DERIVED_KEY_FORMATS_BY_SOURCE = {
    "gtfs_rt": "raw/gtfs_rt/{record_id}.pb",
}


def derived_object_key(record: RawRecord) -> Optional[str]:
    """The content-addressed key a base64 record's bytes would have been
    durably landed at, or None when no scheme exists for its source."""
    fmt = DERIVED_KEY_FORMATS_BY_SOURCE.get(record.source)
    if fmt is None:
        return None
    return fmt.format(record_id=record.record_id)


#: Which topics can carry a given source's inline (base64) envelopes.
#: Straight from contracts/topics.v0.md — connectors must not invent topics,
#: and neither does this reader. GTFS-Realtime is the only base64 producer.
ENVELOPE_TOPICS_BY_SOURCE = {
    "gtfs_rt": (
        "raw.gtfs_rt.vehicle_positions",
        "raw.gtfs_rt.trip_updates",
        "raw.gtfs_rt.alerts",
    ),
}

#: Bounded lookup. The envelope carries ``fetched_at``, and the broker can
#: seek by timestamp, so the search starts just before the record was
#: fetched and gives up after a small number of messages rather than
#: scanning a topic that holds tens of thousands of frames.
LOOKUP_BACKOFF_SECONDS = 300
LOOKUP_MAX_MESSAGES = 400
LOOKUP_TIMEOUT_MS = 6000


class EnvelopeStreamPayloadReader:
    """``payload_encoding = 'base64'`` — the ingest envelope on the broker.

    Historically the GTFS-Realtime connector wrote nothing to the object
    store: it base64-encoded the exact bytes into the envelope keyed by
    ``record_id`` and the broker was the only place those bytes existed.
    Since handoff 0036 the connector lands frames durably and the composite
    reader checks the object store FIRST; this reader is the fallback for
    legacy rows whose bytes were never rescued, bounded by the broker's
    retention window — after which it says so in plain words instead of
    pretending the record was never readable.

    The payload is verified against the record id before it is returned: a
    message whose bytes do not hash to the record id is not this record.
    """

    def __init__(self, consumer_factory):
        self._consumer_factory = consumer_factory

    def size(self, record: RawRecord) -> Optional[int]:
        # Reading the broker is not cheap enough to do for a label.
        return None

    def open(self, record: RawRecord) -> PayloadHandle:
        topics = ENVELOPE_TOPICS_BY_SOURCE.get(record.source)
        if not topics:
            raise PayloadUnavailable(
                REASON_NOT_RETAINED,
                "This record's bytes rode inline in the ingest envelope, and "
                f"Headway does not know which topic carries source "
                f"'{record.source}'. The record's identity is intact; its "
                "bytes cannot be read back on this installation.",
            )
        data = self._consumer_factory(record, topics)
        if data is None:
            raise PayloadUnavailable(
                REASON_NOT_RETAINED,
                "This record's bytes rode inline in the ingest envelope "
                "rather than being written to the object store, and the "
                "broker no longer retains that message. The record's "
                "identity and its place in the trail are unaffected — but "
                "Headway cannot show you these bytes or re-verify them. "
                "Retaining realtime frames for longer is a deployment "
                "setting, not something this screen can fix.",
            )
        return PayloadHandle(LOCATION_ENVELOPE_STREAM, len(data), iter((data,)))


class CompositeRawPayloadReader:
    """Routes by ``payload_encoding`` — the record says where its bytes are.

    For ``base64`` (broker-inline) records the resolution order is the
    handoff-0036 design, in these exact steps:

    1. **Object store at the deterministic key first.** The connector now
       lands frames durably and the backfill rescued the retained window, so
       a legacy row's bytes are usually in the store even though the
       immutable row itself still says ``base64``. The bytes are re-hashed
       before use — an object that does not hash to the record id is not
       this record and is skipped loudly.
    2. **The bounded envelope-stream lookup** (which re-hashes too).
    3. **The honest 410**: never kept, no longer retained, said plainly.
    """

    def __init__(self, object_reader=None, stream_reader=None):
        self._object_reader = object_reader
        self._stream_reader = stream_reader

    # -- base64: the rescued-object fast path ------------------------------

    def _open_rescued(self, record: RawRecord) -> tuple[Optional[PayloadHandle], bool]:
        """The record's bytes from the object store at the derived key, hash-
        verified. Returns ``(handle, store_unreachable)``: ``handle`` is the
        verified bytes or None; ``store_unreachable`` is True when the store
        could not be reached, as opposed to the object being confirmed absent.

        The distinction is load-bearing: a broker miss AFTER a confirmed-absent
        object is permanent loss (410), but a broker miss after an UNREACHABLE
        store is a transient outage (503) — the bytes may be sitting durably in
        the store we simply couldn't read. Collapsing the two would let a MinIO
        blip make the API falsely declare a rescued record's evidence gone
        forever (the exact failure this retention wave exists to prevent)."""
        key = derived_object_key(record)
        if key is None or self._object_reader is None:
            return None, False
        open_key = getattr(self._object_reader, "open_key", None)
        if open_key is None:
            return None, False
        try:
            handle = open_key(key)
            data = b"".join(handle.chunks)
        except PayloadUnavailable as exc:
            # Object confirmed missing → fall through to the broker; the bytes
            # may be on the wire. Store UNREACHABLE → also try the broker, but
            # remember it, so a broker miss is reported as a transient 503,
            # never a permanent 410 that would falsely claim lost evidence.
            return None, exc.reason == REASON_STORE_UNREACHABLE
        if hashlib.sha256(data).hexdigest() != record.record_id:
            # A content-addressed object whose bytes do not hash to its key
            # is storage corruption. It is NOT this record's bytes, so it is
            # never served; the broker fallback may still hold the real
            # ones. Logged loudly — a verify on a record whose only copy is
            # this corrupt object will answer 410, and this log line is the
            # trail from that answer to the corrupt object.
            _log.error(
                "object at derived key %s does not hash to record_id %s; "
                "ignoring it (possible object-store corruption)",
                key,
                record.record_id,
            )
            return None, False
        return PayloadHandle(LOCATION_OBJECT_STORE, len(data), iter((data,))), False

    # A rescued record whose object store is unreachable and whose broker has
    # aged out must NOT be reported as permanent loss — the bytes may be in the
    # store; we simply cannot reach it. This is a transient 503, retryable.
    _STORE_DOWN_NO_BROKER = (
        "Headway could not reach the object store to read this record's bytes, "
        "and this installation has no broker connection (KAFKA_BROKERS) to fall "
        "back on. This is a transient storage outage, not confirmed data loss — "
        "the record's identity and place in the trail are unaffected, and its "
        "bytes should be readable again once the object store is reachable. "
        "Try again shortly."
    )
    _STORE_DOWN_BROKER_MISS = (
        "Headway could not reach the object store to read this record's bytes, "
        "and the broker no longer retains the envelope to fall back on. This is "
        "a transient storage outage, not confirmed data loss — Headway cannot "
        "tell right now whether the bytes are durably stored, so it will not "
        "declare them gone. Try again once the object store is reachable."
    )

    def _base64_open(self, record: RawRecord) -> PayloadHandle:
        rescued, store_unreachable = self._open_rescued(record)
        if rescued is not None:
            return rescued
        store_was_checked = (
            self._object_reader is not None
            and derived_object_key(record) is not None
        )
        if self._stream_reader is None:
            if store_unreachable:
                raise PayloadUnavailable(
                    REASON_STORE_UNREACHABLE, self._STORE_DOWN_NO_BROKER
                )
            if store_was_checked:
                raise PayloadUnavailable(
                    REASON_NOT_RETAINED,
                    "This record's bytes rode inline in the ingest envelope. "
                    "Headway checked the object store at the address they "
                    "would have been durably landed at and they are not "
                    "there, and this installation has no broker connection "
                    "(KAFKA_BROKERS) to search the envelope stream with. The "
                    "record's identity and its place in the trail are "
                    "unaffected; its bytes cannot be produced here.",
                )
            raise PayloadUnavailable(
                REASON_NOT_CONFIGURED,
                "This record's bytes rode inline in the ingest envelope, "
                "and this Headway installation has no broker connection "
                "configured to read it back. Nothing is wrong with the "
                "record; the API is missing its KAFKA_BROKERS setting.",
            )
        try:
            return self._stream_reader.open(record)
        except PayloadUnavailable as exc:
            if store_unreachable and exc.reason in (
                REASON_NOT_RETAINED,
                REASON_NOT_CONFIGURED,
            ):
                # The store — where a rescued record's bytes live — was
                # unreachable, and the broker fallback also came up empty.
                # This is a transient outage, not permanent loss.
                raise PayloadUnavailable(
                    REASON_STORE_UNREACHABLE, self._STORE_DOWN_BROKER_MISS
                ) from exc
            if exc.reason == REASON_NOT_RETAINED and store_was_checked:
                raise PayloadUnavailable(
                    REASON_NOT_RETAINED,
                    "This record's bytes rode inline in the ingest envelope "
                    "before durable landing was deployed. Headway checked "
                    "the object store at the address they would have been "
                    "rescued to, and the broker — which no longer retains "
                    "that message. The record's identity and its place in "
                    "the trail are unaffected, but these bytes were never "
                    "durably kept and can no longer be produced. Records "
                    "ingested since durable landing do not have this gap.",
                ) from exc
            raise

    # -- routing ------------------------------------------------------------

    def _for(self, record: RawRecord):
        if record.payload_encoding == "object_ref":
            if self._object_reader is None:
                raise PayloadUnavailable(
                    REASON_NOT_CONFIGURED,
                    "This Headway installation has no object store "
                    "configured, so the bytes behind this record cannot be "
                    "read. Nothing is wrong with the record; the API is "
                    "missing its S3_* settings.",
                )
            return self._object_reader
        if record.payload_encoding == "base64":
            return None  # handled by _base64_open / size below
        raise PayloadUnavailable(
            REASON_NOT_RETAINED,
            f"This record records an unknown payload encoding "
            f"'{record.payload_encoding}', so Headway will not guess where "
            "its bytes are.",
        )

    def size(self, record: RawRecord) -> Optional[int]:
        reader = self._for(record)
        if reader is not None:
            return reader.size(record)
        # base64: a rescued object's size is cheap; absence is honest None
        # (measured on open), never an error at label time.
        key = derived_object_key(record)
        size_key = getattr(self._object_reader, "size_key", None)
        if key is not None and size_key is not None:
            try:
                return size_key(key)
            except PayloadUnavailable:
                return None
        return None

    def open(self, record: RawRecord) -> PayloadHandle:
        reader = self._for(record)
        if reader is not None:
            return reader.open(record)
        return self._base64_open(record)


# ---------------------------------------------------------------------------
# Live wiring (same env surface as ingest: S3_* and KAFKA_BROKERS)
# ---------------------------------------------------------------------------


def _kafka_envelope_lookup(record: RawRecord, topics) -> Optional[bytes]:
    """Bounded, timestamp-seeked scan for one record's envelope.

    Imported lazily: the broker client is in the optional ``ingest`` extra,
    exactly like the producer side.
    """
    import base64

    from kafka import KafkaConsumer, TopicPartition

    brokers = os.environ.get("KAFKA_BROKERS", "")
    if not brokers:
        return None
    consumer = KafkaConsumer(
        bootstrap_servers=brokers.split(","),
        enable_auto_commit=False,
        consumer_timeout_ms=LOOKUP_TIMEOUT_MS,
    )
    try:
        seek_ms = int(
            (record.fetched_at.timestamp() - LOOKUP_BACKOFF_SECONDS) * 1000
        )
        wanted = record.record_id.encode()
        for topic in topics:
            partitions = consumer.partitions_for_topic(topic)
            if not partitions:
                continue
            tps = [TopicPartition(topic, p) for p in partitions]
            offsets = consumer.offsets_for_times({tp: seek_ms for tp in tps})
            starts = {
                tp: (off.offset if off is not None else None)
                for tp, off in offsets.items()
            }
            if all(v is None for v in starts.values()):
                continue
            consumer.assign(tps)
            for tp, start in starts.items():
                consumer.seek(tp, start if start is not None else 0)
            scanned = 0
            for message in consumer:
                scanned += 1
                if scanned > LOOKUP_MAX_MESSAGES:
                    break
                if message.key != wanted:
                    continue
                envelope = json.loads(message.value)
                if envelope.get("payload_encoding") != "base64":
                    continue
                payload = base64.b64decode(envelope["payload"], validate=True)
                # The message key is not trusted on its own: the bytes must
                # hash to the record id or they are not this record.
                if hashlib.sha256(payload).hexdigest() != record.record_id:
                    continue
                return payload
        return None
    finally:
        consumer.close()


def payload_reader_from_env(object_store) -> CompositeRawPayloadReader:
    """The live reader: object store from ``app.state`` (the same MinIO
    client ingest uses), envelope stream from ``KAFKA_BROKERS``."""
    object_reader = (
        ObjectStorePayloadReader(object_store) if object_store is not None else None
    )
    stream_reader = (
        EnvelopeStreamPayloadReader(_kafka_envelope_lookup)
        if os.environ.get("KAFKA_BROKERS")
        else None
    )
    return CompositeRawPayloadReader(object_reader, stream_reader)


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------


def digest_and_size(chunks: Iterable[bytes]) -> tuple[str, int]:
    """SHA-256 over the stored bytes, a chunk at a time."""
    digest = hashlib.sha256()
    size = 0
    for chunk in chunks:
        digest.update(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def read_capped(chunks: Iterable[bytes], cap: int) -> tuple[bytes, bool]:
    """First ``cap`` bytes, plus whether more bytes followed."""
    buffer = bytearray()
    more = False
    for chunk in chunks:
        if len(buffer) >= cap:
            more = True
            break
        buffer.extend(chunk)
    if len(buffer) > cap:
        more = True
        del buffer[cap:]
    return bytes(buffer), more


# ---------------------------------------------------------------------------
# Decoders — the window
# ---------------------------------------------------------------------------

DECODER_GTFS_RT = "gtfs_realtime"
DECODER_DELIMITED = "delimited_text"
DECODER_TEXT = "text"
DECODER_NONE = "none"

#: Bounded preview caps. Every one of these appears in the response so the
#: reader is never left guessing whether they saw everything.
MAX_ENTITIES = 25
MAX_STOP_TIME_UPDATES = 3
MAX_TEXT_ROWS = 20
MAX_LINE_CHARS = 500
#: How many bytes the preview reads at all. A GTFS-Realtime frame must be
#: whole to parse (protobuf is not resumable), so the whole frame is read up
#: to this bound; text is decoded from the first slice only.
MAX_DECODE_BYTES = 4 * 1024 * 1024

#: Connectors whose CONTRACT declares a comma-delimited CSV with a header
#: row — the header check both the Go connectors and routers/ingest.py run
#: reads exactly this dialect. For any other CSV the delimiter and the
#: column names are the registered mapping spec's business, so the preview
#: shows lines verbatim instead of guessing a shape.
COMMA_CSV_CONTRACT_CONNECTORS = frozenset(
    {"headway-tides", "headway-dr", "headway-api-ingest"}
)

TEXT_CONTENT_TYPES = frozenset({"application/json"})


def decoder_for(record: RawRecord) -> str:
    if record.source == "gtfs_rt" and record.content_type == "application/x-protobuf":
        return DECODER_GTFS_RT
    if (
        record.content_type == "text/csv"
        and record.connector in COMMA_CSV_CONTRACT_CONNECTORS
    ):
        return DECODER_DELIMITED
    if record.content_type.startswith("text/") or record.content_type in TEXT_CONTENT_TYPES:
        return DECODER_TEXT
    return DECODER_NONE


def decoder_note(record: RawRecord) -> str:
    kind = decoder_for(record)
    if kind == DECODER_GTFS_RT:
        return (
            "A GTFS-Realtime feed message. Headway can show its header and "
            "its entities with their real values."
        )
    if kind == DECODER_DELIMITED:
        return (
            "A comma-separated file whose contract declares a header row, so "
            "the first row's own labels name the columns."
        )
    if kind == DECODER_TEXT:
        return "A text file. Headway can show its first lines exactly as stored."
    return (
        f"Headway has no reader for {record.content_type} yet, so it will "
        "state what the file is and offer the exact bytes for download "
        "rather than show you a decoded version it cannot vouch for."
    )


def _iso(seconds: int) -> Optional[str]:
    """POSIX seconds rendered as UTC. A rendering of the same number — the
    verbatim integer is served alongside it."""
    try:
        return (
            dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    except (OverflowError, OSError, ValueError):
        return None


def _enum_name(descriptor, value) -> Optional[str]:
    try:
        return descriptor.values_by_number[value].name
    except KeyError:  # pragma: no cover - a value outside the pinned spec
        return None


def _opt(message, field: str):
    """proto2 presence: absent stays absent, it never becomes a zero."""
    return getattr(message, field) if message.HasField(field) else None


def decode_gtfs_realtime(payload: bytes) -> dict:
    """Decode a GTFS-Realtime ``FeedMessage``.

    Field meanings are the GTFS-Realtime specification's (gtfs.org) — this
    function transports them, it does not define them. Decoding uses the
    same pinned Apache-2.0 bindings the transform service normalizes with,
    so what an auditor reads here is what the pipeline read.
    """
    from google.protobuf.message import DecodeError
    from google.transit import gtfs_realtime_pb2

    feed = gtfs_realtime_pb2.FeedMessage()
    try:
        feed.ParseFromString(payload)
    except DecodeError as exc:
        return {
            "decoded": False,
            "decode_error": (
                "These bytes are not a readable GTFS-Realtime feed message "
                f"({exc}). That is a finding about the source feed, not about "
                "Headway's copy: the bytes shown are exactly what arrived."
            ),
        }

    header = feed.header
    kinds = {"vehicle": 0, "trip_update": 0, "alert": 0, "other": 0}
    for entity in feed.entity:
        if entity.HasField("vehicle"):
            kinds["vehicle"] += 1
        elif entity.HasField("trip_update"):
            kinds["trip_update"] += 1
        elif entity.HasField("alert"):
            kinds["alert"] += 1
        else:
            kinds["other"] += 1

    entities = [_decode_entity(e) for e in feed.entity[:MAX_ENTITIES]]
    header_ts = _opt(header, "timestamp")
    return {
        "decoded": True,
        "decode_error": None,
        "gtfs_realtime_version": header.gtfs_realtime_version or None,
        "incrementality": _enum_name(
            gtfs_realtime_pb2.FeedHeader.Incrementality.DESCRIPTOR,
            header.incrementality,
        ),
        "header_timestamp": header_ts,
        "header_timestamp_utc": _iso(header_ts) if header_ts is not None else None,
        "entity_count": len(feed.entity),
        "entity_kinds": kinds,
        "entities": entities,
    }


def _decode_entity(entity) -> dict:
    from google.transit import gtfs_realtime_pb2

    out: dict = {
        "entity_id": entity.id or None,
        "is_deleted": _opt(entity, "is_deleted"),
        "kind": None,
    }
    if entity.HasField("vehicle"):
        vehicle = entity.vehicle
        timestamp = _opt(vehicle, "timestamp")
        position = vehicle.position if vehicle.HasField("position") else None
        trip = vehicle.trip if vehicle.HasField("trip") else None
        descriptor = vehicle.vehicle if vehicle.HasField("vehicle") else None
        out.update(
            {
                "kind": "vehicle_position",
                "vehicle_id": _opt(descriptor, "id") if descriptor else None,
                "vehicle_label": _opt(descriptor, "label") if descriptor else None,
                "trip_id": _opt(trip, "trip_id") if trip else None,
                "route_id": _opt(trip, "route_id") if trip else None,
                "direction_id": _opt(trip, "direction_id") if trip else None,
                "latitude": position.latitude if position else None,
                "longitude": position.longitude if position else None,
                "bearing": _opt(position, "bearing") if position else None,
                "speed": _opt(position, "speed") if position else None,
                "timestamp": timestamp,
                "timestamp_utc": _iso(timestamp) if timestamp is not None else None,
                "current_status": (
                    _enum_name(
                        gtfs_realtime_pb2.VehiclePosition.VehicleStopStatus.DESCRIPTOR,
                        vehicle.current_status,
                    )
                    if vehicle.HasField("current_status")
                    else None
                ),
                "stop_id": _opt(vehicle, "stop_id"),
                "occupancy_status": (
                    _enum_name(
                        gtfs_realtime_pb2.VehiclePosition.OccupancyStatus.DESCRIPTOR,
                        vehicle.occupancy_status,
                    )
                    if vehicle.HasField("occupancy_status")
                    else None
                ),
            }
        )
        return out
    if entity.HasField("trip_update"):
        update = entity.trip_update
        trip = update.trip
        descriptor = update.vehicle if update.HasField("vehicle") else None
        timestamp = _opt(update, "timestamp")
        out.update(
            {
                "kind": "trip_update",
                "trip_id": _opt(trip, "trip_id"),
                "route_id": _opt(trip, "route_id"),
                "start_date": _opt(trip, "start_date"),
                "schedule_relationship": (
                    _enum_name(
                        gtfs_realtime_pb2.TripDescriptor.ScheduleRelationship.DESCRIPTOR,
                        trip.schedule_relationship,
                    )
                    if trip.HasField("schedule_relationship")
                    else None
                ),
                "vehicle_id": _opt(descriptor, "id") if descriptor else None,
                "vehicle_label": _opt(descriptor, "label") if descriptor else None,
                "timestamp": timestamp,
                "timestamp_utc": _iso(timestamp) if timestamp is not None else None,
                "delay": _opt(update, "delay"),
                "stop_time_update_count": len(update.stop_time_update),
                "stop_time_updates": [
                    {
                        "stop_id": _opt(stu, "stop_id"),
                        "stop_sequence": _opt(stu, "stop_sequence"),
                        "arrival_time": (
                            _opt(stu.arrival, "time")
                            if stu.HasField("arrival")
                            else None
                        ),
                        "arrival_delay": (
                            _opt(stu.arrival, "delay")
                            if stu.HasField("arrival")
                            else None
                        ),
                        "departure_time": (
                            _opt(stu.departure, "time")
                            if stu.HasField("departure")
                            else None
                        ),
                        "departure_delay": (
                            _opt(stu.departure, "delay")
                            if stu.HasField("departure")
                            else None
                        ),
                    }
                    for stu in update.stop_time_update[:MAX_STOP_TIME_UPDATES]
                ],
            }
        )
        return out
    if entity.HasField("alert"):
        alert = entity.alert
        out.update(
            {
                "kind": "alert",
                "cause": _enum_name(
                    gtfs_realtime_pb2.Alert.Cause.DESCRIPTOR, alert.cause
                ),
                "effect": _enum_name(
                    gtfs_realtime_pb2.Alert.Effect.DESCRIPTOR, alert.effect
                ),
                "header_text": _translated(alert.header_text),
                "description_text": _translated(alert.description_text),
                "informed_entity_count": len(alert.informed_entity),
            }
        )
        return out
    out["kind"] = "unrecognized"
    return out


def _translated(translated_string) -> Optional[str]:
    for translation in translated_string.translation:
        return translation.text or None
    return None


def decode_delimited(payload: bytes, truncated_bytes: bool) -> dict:
    """First rows of a comma-separated file whose contract declares a header.

    The header labels come from the file's OWN first row — nothing is
    supplied from a schema Headway happens to know. A file that cannot be
    read as UTF-8 says so rather than being mangled into something readable.
    """
    text, encoding_note = _decode_text(payload)
    if text is None:
        return {"readable": False, "note": encoding_note}
    rows: list[list[str]] = []
    try:
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            rows.append([_clip(cell) for cell in row])
            if len(rows) > MAX_TEXT_ROWS:
                break
    except csv.Error as exc:
        return {
            "readable": False,
            "note": (
                f"Headway could not read this file as comma-separated text "
                f"({exc}). The exact bytes are still available to download."
            ),
        }
    # The reader stops one row past the cap, so "it stopped early and the
    # bytes were whole" is exactly what a complete file looks like.
    complete = not truncated_bytes and len(rows) <= MAX_TEXT_ROWS
    if truncated_bytes and rows:
        # The last row of a byte-truncated slice may itself be cut in half;
        # dropping it is honest, keeping it would show a fabricated row.
        rows = rows[:-1]
    header = rows[0] if rows else None
    data_rows = rows[1 : MAX_TEXT_ROWS + 1] if rows else []
    return {
        "readable": True,
        "complete": complete,
        "note": encoding_note,
        "header": header,
        "header_source": (
            "the file's own first row (this source's contract declares a "
            "header row)"
            if header
            else None
        ),
        "rows": data_rows,
    }


def decode_text(payload: bytes, truncated_bytes: bool) -> dict:
    """First lines of a text file, exactly as stored.

    No delimiter is inferred and no column is named: for a vendor export,
    what the columns mean is defined only by its registered mapping spec,
    and a guessed header would be a fabricated label on real data.
    """
    text, encoding_note = _decode_text(payload)
    if text is None:
        return {
            "readable": False,
            "complete": False,
            "note": encoding_note,
            "lines": [],
        }
    lines = text.splitlines()
    complete = not truncated_bytes and len(lines) <= MAX_TEXT_ROWS
    shown = [_clip(line) for line in lines[:MAX_TEXT_ROWS]]
    if truncated_bytes and shown:
        shown = shown[:-1]
    return {
        "readable": True,
        "complete": complete,
        "note": encoding_note,
        "lines": shown,
    }


def _decode_text(payload: bytes) -> tuple[Optional[str], Optional[str]]:
    try:
        return payload.decode("utf-8-sig"), None
    except UnicodeDecodeError as exc:
        return (
            None,
            (
                "These bytes are not valid UTF-8 text "
                f"({exc.reason} at byte {exc.start}), so Headway will not "
                "render them as text — a re-encoded preview would not be the "
                "record. Download the exact bytes to inspect them."
            ),
        )


def _clip(value: str) -> str:
    if len(value) <= MAX_LINE_CHARS:
        return value
    return value[:MAX_LINE_CHARS] + "…"
