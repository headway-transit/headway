"""Process boundary: ``python -m headway_transform`` — the container entrypoint.

Wires the real adapters from environment variables and runs the consumer
loop forever. This module is the ONLY place env vars are read; every library
module keeps taking injected dependencies (consumer.py's MessageSource /
DbWriter / ObjectFetcher seams), so unit tests never exercise the wiring
(the pure read_capped helper is the one unit-tested piece here).

Environment:
  KAFKA_BROKERS   (required) bootstrap servers, e.g. kafka:9092
  KAFKA_GROUP_ID  (optional) consumer group, default headway-transform
  DATABASE_URL    (optional) psycopg/libpq conninfo; when unset, the
                  standard libpq PG* variables are used (PGHOST, PGPORT,
                  PGUSER, PGPASSWORD, PGDATABASE) — preferred, because
                  credentials in a URL must be percent-encoded (2026-07-09
                  live-run finding).
  S3_ENDPOINT / S3_ACCESS_KEY / S3_SECRET_KEY / S3_BUCKET / S3_USE_SSL
                  (optional) MinIO/S3 for payload_encoding='object_ref'
                  payloads — same surface as the Go connectors and the API
                  ingest seam. When unset, the consumer quarantines
                  object_ref messages as blocking 'object_ref_unavailable'
                  dq.issues rows (loud, never dropped).
  HEADWAY_MAX_OBJECT_BYTES (optional) cap on a fetched object_ref payload,
                  default 268435456 (256 MiB). Fetches are stream-counted
                  and ABORTED over the cap (2026-07-13 hardening pass:
                  never buffer an unbounded body); the aborted message is
                  quarantined as a blocking transform_failure dq.issues row
                  naming the limit.
  IDLE_SLEEP_SECONDS (optional) sleep between empty polls, default 1.

Fail-loudly policy: missing required config is a refusal at startup, never a
guessed default.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from .consumer import (
    TOPIC_DR_TRIPS,
    TOPIC_GTFS_RT_TRIP_UPDATES,
    TOPIC_GTFS_RT_VEHICLE_POSITIONS,
    TOPIC_GTFS_STATIC_FEED,
    TOPIC_TIDES_PASSENGER_EVENTS,
    ObjectFetcher,
    ObjectTooLargeError,
    run_loop,
)
from .kafka_source import KafkaMessageSource
from .writer import DbWriter

logger = logging.getLogger("headway_transform")

TOPICS = [
    TOPIC_GTFS_RT_VEHICLE_POSITIONS,
    TOPIC_GTFS_RT_TRIP_UPDATES,
    TOPIC_GTFS_STATIC_FEED,
    TOPIC_TIDES_PASSENGER_EVENTS,
    TOPIC_DR_TRIPS,
]

#: Default cap on a fetched object_ref payload (2026-07-13 hardening pass).
#: Generous — the largest real payload so far (MBTA GTFS zip) is ~90 MiB.
DEFAULT_MAX_OBJECT_BYTES = 256 * 1024 * 1024


def read_capped(chunks, max_bytes: int, object_ref: str) -> bytes:
    """Assemble streamed chunks, aborting loudly over max_bytes.

    Stream-counted so an oversize (or hostile) object is refused after at
    most max_bytes of buffering — never read to completion first. The
    ObjectTooLargeError message names the limit; run_loop turns it into a
    blocking transform_failure dq.issues finding carrying that message.
    """
    parts: list[bytes] = []
    total = 0
    for chunk in chunks:
        total += len(chunk)
        if total > max_bytes:
            raise ObjectTooLargeError(
                f"object {object_ref!r} exceeds the {max_bytes}-byte fetch "
                "limit (HEADWAY_MAX_OBJECT_BYTES); fetch aborted after "
                f"{total} bytes — raise the limit explicitly if this "
                "payload is legitimately that large"
            )
        parts.append(chunk)
    return b"".join(parts)


def object_fetcher_from_env() -> Optional[ObjectFetcher]:
    """Build a MinIO-backed ObjectFetcher from S3_* env, or None when unset.

    None is a legitimate degraded mode: the consumer then writes a blocking
    'object_ref_unavailable' dq.issues row per object_ref message instead of
    guessing — nothing is silently dropped.
    """
    endpoint = os.environ.get("S3_ENDPOINT")
    if not endpoint:
        logger.warning(
            "S3_ENDPOINT is not set: object_ref payloads (GTFS static zips, "
            "TIDES CSVs) will be quarantined as dq.issues, not normalized."
        )
        return None
    # Lazy import: 's3' extra, process boundary only (see pyproject.toml).
    from minio import Minio  # type: ignore[import-not-found]

    client = Minio(
        endpoint,
        access_key=os.environ.get("S3_ACCESS_KEY"),
        secret_key=os.environ.get("S3_SECRET_KEY"),
        secure=os.environ.get("S3_USE_SSL", "").lower() == "true",
    )
    bucket = os.environ.get("S3_BUCKET", "headway-raw")
    max_bytes = int(
        os.environ.get("HEADWAY_MAX_OBJECT_BYTES", str(DEFAULT_MAX_OBJECT_BYTES))
    )

    def fetch(object_ref: str) -> bytes:
        response = client.get_object(bucket, object_ref)
        try:
            return read_capped(response.stream(64 * 1024), max_bytes, object_ref)
        finally:
            response.close()
            response.release_conn()

    return fetch


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    brokers = os.environ.get("KAFKA_BROKERS")
    if not brokers:
        raise SystemExit(
            "KAFKA_BROKERS is not set — refusing to guess a broker address."
        )
    if not os.environ.get("DATABASE_URL") and not any(
        os.environ.get(var) for var in ("PGHOST", "PGDATABASE", "PGSERVICE")
    ):
        raise SystemExit(
            "No database configured (DATABASE_URL or libpq PG* variables) — "
            "refusing to guess a connection."
        )

    # Lazy import: 'db' extra, process boundary only.
    import psycopg  # type: ignore[import-not-found]

    # Empty conninfo -> libpq PG* env vars. run_loop drives commit/rollback
    # explicitly, so the default (non-autocommit) transaction mode is correct.
    connection = psycopg.connect(os.environ.get("DATABASE_URL", ""))
    writer = DbWriter(connection)
    source = KafkaMessageSource(
        TOPICS,
        bootstrap_servers=brokers,
        group_id=os.environ.get("KAFKA_GROUP_ID", "headway-transform"),
    )
    fetcher = object_fetcher_from_env()
    idle_sleep = float(os.environ.get("IDLE_SLEEP_SECONDS", "1"))

    logger.info("consuming %s from %s", TOPICS, brokers)
    try:
        # run_loop exits on an empty poll; wrap it to run forever. Kafka
        # offsets are committed AFTER the DB commits (at-least-once; replays
        # are idempotent via content-addressed record_ids + ON CONFLICT).
        while True:
            processed = run_loop(source, writer, fetcher)
            if processed:
                source.commit()
            else:
                time.sleep(idle_sleep)
    finally:
        source.close()
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
