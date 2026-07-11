"""Authenticated HTTPS ingest: TIDES passenger_events CSV (handoff 0006, pt 5).

The API acts as a CONNECTOR here, honoring the wire contract exactly as the
file-drop connector does (services/ingestion/connectors/tides/tides.go — the
binding precedent for envelope shape, ordering, and the header sanity check):

- the raw bytes are content-addressed (sha256 → record_id, ADR-0007),
- stored to the object store at ``raw/tides/<record_id>.csv``,
- and produced as a v0 raw-record envelope
  (contracts/raw-record-envelope.v0.schema.json) to
  ``raw.tides.passenger_events`` (contracts/topics.v0.md), keyed by record_id.

STORE-BEFORE-PRODUCE, always: a consumer must never see an envelope whose
object does not exist (the tides.go ordering precedent).

The envelope ``source`` is the KEY's bound source_label — a client-supplied
source (header, query, anything) is IGNORED, never trusted; that is how
simulated data stays permanently distinguishable from a real vendor's
(handoff 0005 binding rule, carried into 0006 design point 5).

parse_status comes from the same header sanity check tides.go performs
(required TIDES passenger_events columns present — verified against
TIDES-transit/TIDES spec/passenger_events.schema.json, commit
d887d42ce081f3fb6155664a3c486101d62ec52b, per the tides.go citation). A
malformed body is STILL stored and produced, flagged malformed — fail loudly,
never dropped (Guardrail 7).

The object store (MinIO) and Kafka producer (kafka-python-ng) live behind
small protocols on app.state — injectable fakes in tests, real clients wired
from the environment in the lifespan. When either is not configured the
endpoint refuses with a plain-language 503: it never accepts bytes it cannot
land (a silent accept would be a silent drop).
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import os
from typing import Optional, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import __version__
from ..audit import write_event
from ..db import get_db
from ..machine_auth import (
    SCOPE_INGEST_TIDES,
    MachineIdentity,
    enforce_rate_limit,
    require_machine_scope,
)

router = APIRouter(tags=["ingest"])

# Connector identity recorded on every envelope this endpoint produces.
CONNECTOR_NAME = "headway-api-ingest"
CONNECTOR_VERSION = __version__  # the producing package's version
TOPIC = "raw.tides.passenger_events"  # contracts/topics.v0.md
CONTENT_TYPE = "text/csv"

# 32 MiB body cap (handoff 0006, design point 5). Above this is a 413.
MAX_BODY_BYTES = 32 * 1024 * 1024

# Required TIDES passenger_events columns — the same header sanity check as
# the file-drop connector (tides.go RequiredColumns, verified against
# TIDES-transit/TIDES spec/passenger_events.schema.json at commit
# d887d42ce081f3fb6155664a3c486101d62ec52b). Used ONLY to set parse_status;
# row-level semantics belong to the Data Engineer's normalizer.
REQUIRED_TIDES_COLUMNS = (
    "passenger_event_id",
    "service_date",
    "event_timestamp",
    "trip_stop_sequence",
    "event_type",
    "vehicle_id",
)


def object_key(record_id: str) -> str:
    """Content-addressed object-store key (same layout as tides.go)."""
    return f"raw/tides/{record_id}.csv"


# ---------------------------------------------------------------------------
# Injectable seams: object store + producer protocols (app.state)
# ---------------------------------------------------------------------------


class ObjectStore(Protocol):
    """The one object-store operation ingest needs. MinIO in production;
    a fake recording (key, data) in tests."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...


class Producer(Protocol):
    """The one Kafka operation ingest needs. kafka-python-ng in production;
    a fake recording (topic, key, value) in tests."""

    def produce(self, topic: str, key: bytes, value: bytes) -> None: ...


class MinioObjectStore:
    """MinIO adapter (``minio`` package, from the ``ingest`` extra)."""

    def __init__(self, client, bucket: str):
        self._client = client
        self._bucket = bucket

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(
            self._bucket, key, io.BytesIO(data), len(data), content_type=content_type
        )

    def get(self, key: str) -> Optional[bytes]:
        """Fetch one object's bytes, or None when it does not exist. Added
        for the branding logo (routers/branding.py LogoStore); ingest itself
        never reads back."""
        from minio.error import S3Error

        try:
            response = self._client.get_object(self._bucket, key)
        except S3Error as exc:
            if exc.code in ("NoSuchKey", "NoSuchObject"):
                return None
            raise
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()


class KafkaEnvelopeProducer:
    """kafka-python-ng adapter (from the ``ingest`` extra). Flushes per send:
    ingest returns 202 only after the broker acknowledged the envelope."""

    def __init__(self, kafka_producer):
        self._producer = kafka_producer

    def produce(self, topic: str, key: bytes, value: bytes) -> None:
        # .get() forces the send to complete (or raise) before we answer 202.
        self._producer.send(topic, key=key, value=value).get(timeout=30)


def object_store_from_env() -> Optional[ObjectStore]:
    """MinIO client from the same env vars the Go connectors use (S3_ENDPOINT,
    S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET, S3_USE_SSL). None when not
    configured — the endpoint then refuses loudly with 503."""
    endpoint = os.environ.get("S3_ENDPOINT")
    access_key = os.environ.get("S3_ACCESS_KEY")
    secret_key = os.environ.get("S3_SECRET_KEY")
    if not endpoint or not access_key or not secret_key:
        return None
    # Imported lazily: the ``ingest`` extra is optional and tests use fakes.
    from minio import Minio

    client = Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=os.environ.get("S3_USE_SSL", "").lower() == "true",
    )
    return MinioObjectStore(client, os.environ.get("S3_BUCKET", "headway-raw"))


def producer_from_env() -> Optional[Producer]:
    """Kafka producer from KAFKA_BROKERS (same env var as the Go connectors).
    None when not configured — the endpoint then refuses loudly with 503."""
    brokers = os.environ.get("KAFKA_BROKERS")
    if not brokers:
        return None
    # Imported lazily: the ``ingest`` extra is optional and tests use fakes.
    from kafka import KafkaProducer

    return KafkaEnvelopeProducer(
        KafkaProducer(bootstrap_servers=brokers.split(","), acks="all")
    )


# ---------------------------------------------------------------------------
# Header sanity check (parse_status only — the tides.go precedent)
# ---------------------------------------------------------------------------


def check_tides_header(body: bytes) -> Optional[str]:
    """Return None when every required TIDES column is present in the header
    row, else a human-readable reason. Mirrors tides.go checkHeader: first
    record only, BOM-tolerant, never inspects data rows."""
    try:
        text = body.decode("utf-8-sig")  # tolerate a UTF-8 BOM, like tides.go
    except UnicodeDecodeError as exc:
        return f"body is not decodable as UTF-8 CSV: {exc}"
    try:
        header = next(csv.reader(io.StringIO(text)), None)
    except csv.Error as exc:
        return f"read header row: {exc}"
    if not header:
        return "read header row: file is empty"
    seen = {name.strip() for name in header}
    missing = [c for c in REQUIRED_TIDES_COLUMNS if c not in seen]
    if missing:
        return "missing required TIDES columns: " + ", ".join(missing)
    return None


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


class IngestResponse(BaseModel):
    record_id: str
    parse_status: str


@router.post(
    "/ingest/tides/passenger-events",
    response_model=IngestResponse,
    status_code=202,
)
async def ingest_passenger_events(
    request: Request,
    identity: MachineIdentity = Depends(require_machine_scope(SCOPE_INGEST_TIDES)),
    db=Depends(get_db),
) -> IngestResponse:
    # Per-key token bucket (60 req/min default). In-process — the documented
    # single-instance limitation (machine_auth.RateLimiter docstring).
    enforce_rate_limit(request.app.state.machine_rate_limiter, identity.key_prefix)

    store = getattr(request.app.state, "object_store", None)
    producer = getattr(request.app.state, "producer", None)
    if store is None or producer is None:
        # Never a silent accept: bytes we cannot land are refused loudly.
        raise HTTPException(
            status_code=503,
            detail=(
                "Ingest is not configured on this Headway instance: the "
                "object store or the message broker connection is missing. "
                "Nothing was stored. Please contact your Headway "
                "administrator."
            ),
        )

    if not identity.source_label:
        # Issuance refuses ingest keys without a bound source, so this only
        # fires on a miswired row — refuse loudly rather than ever produce an
        # envelope with an invalid (empty) source.
        raise HTTPException(
            status_code=403,
            detail=(
                "This machine API key is not bound to a data source label, "
                "so Headway cannot stamp the records it pushes. Please ask a "
                "Headway administrator to issue a new ingest key with a "
                "source label."
            ),
        )

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "This file is larger than the 32 MiB ingest limit. Please "
                "split it into smaller files and push each one separately."
            ),
        )
    if not body:
        raise HTTPException(
            status_code=422,
            detail=(
                "The request body is empty. Send the TIDES passenger_events "
                "CSV file as the raw request body."
            ),
        )

    record_id = hashlib.sha256(body).hexdigest()
    key = object_key(record_id)

    # Header sanity check ONLY classifies parse_status; a malformed body is
    # still stored and produced — fail loudly, never dropped (Guardrail 7).
    parse_error = check_tides_header(body)
    parse_status = "ok" if parse_error is None else "malformed"

    # The envelope, EXACTLY per contracts/raw-record-envelope.v0.schema.json.
    # source is the KEY's bound source_label — any client-supplied source
    # (header, query parameter, anything) is deliberately ignored.
    envelope: dict = {
        "envelope_version": 0,
        "record_id": record_id,
        "source": identity.source_label,
        "connector": CONNECTOR_NAME,
        "connector_version": CONNECTOR_VERSION,
        "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "content_type": CONTENT_TYPE,
        "payload_encoding": "object_ref",
        "payload": key,
        "parse_status": parse_status,
    }
    if parse_error is not None:
        envelope["parse_error"] = (
            f"tides passenger_events header check failed: {parse_error}"
        )

    # Store BEFORE produce (tides.go precedent): a consumer must never see an
    # envelope whose object does not exist. Both operations are idempotent by
    # content-addressed record_id, so a retry after a mid-flight failure is safe.
    store.put(key, body, CONTENT_TYPE)
    producer.produce(
        TOPIC,
        key=record_id.encode("ascii"),
        value=json.dumps(envelope).encode("utf-8"),
    )

    # Successful key use is audited at the endpoint level (design point 4);
    # the record itself — key material never — appears only as ids/metadata.
    with db.transaction():
        write_event(
            db,
            actor=identity.actor,
            action="ingest",
            subject_kind="raw.records",
            subject_id=record_id,
            detail={
                "topic": TOPIC,
                "object_key": key,
                "source": identity.source_label,
                "parse_status": parse_status,
                "bytes": len(body),
            },
        )
    return IngestResponse(record_id=record_id, parse_status=parse_status)
