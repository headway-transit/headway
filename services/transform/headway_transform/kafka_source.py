"""Real Kafka MessageSource backed by kafka-python-ng (Apache-2.0).

Kept in its own module so the client library stays swappable behind the
MessageSource interface (consumer.py) and unit tests never import it.
Install with the 'kafka' extra: pip install 'headway-transform[kafka]'.

NOT yet verified against a live broker — no Kafka is available in the
authoring environment (see README Verification status).
"""

from __future__ import annotations

from typing import Optional


class KafkaMessageSource:
    """MessageSource over a kafka-python-ng KafkaConsumer.

    Offsets: enable_auto_commit=False; commit only after run_loop's writer
    commit, so a crash replays the message (at-least-once) instead of losing
    it. Content-addressed record_ids + ON CONFLICT DO NOTHING make the replay
    idempotent.
    """

    def __init__(
        self,
        topics: list[str],
        bootstrap_servers: str,
        group_id: str = "headway-transform",
        poll_timeout_ms: int = 1000,
        max_poll_interval_ms: int = 1_800_000,
    ) -> None:
        # Imported lazily so unit tests don't need the kafka extra installed.
        from kafka import KafkaConsumer  # type: ignore[import-not-found]

        self._poll_timeout_ms = poll_timeout_ms
        self._consumer = KafkaConsumer(
            *topics,
            bootstrap_servers=bootstrap_servers,
            group_id=group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            # A whole GTFS static feed is ONE message and one DB transaction
            # (raw record + every canonical row + lineage). At MBTA scale
            # that legitimately takes minutes, and the kafka-python default
            # deadline of 5 minutes expelled the consumer from the group
            # mid-message: the offset commit then failed, the message
            # redelivered, and the loop repeated forever — the live pipeline
            # stalled exactly this way from 2026-07-22 to 2026-07-30
            # (handoff 0032 evidence). 30 minutes bounds the largest
            # single-message unit of work we ship, not a hoped-for average.
            max_poll_interval_ms=max_poll_interval_ms,
        )
        self._buffer: list[tuple[str, Optional[bytes], bytes]] = []

    def poll(self) -> Optional[tuple[str, Optional[bytes], bytes]]:
        if not self._buffer:
            batches = self._consumer.poll(timeout_ms=self._poll_timeout_ms)
            for records in batches.values():
                for record in records:
                    self._buffer.append((record.topic, record.key, record.value))
        if not self._buffer:
            return None
        return self._buffer.pop(0)

    def commit(self) -> None:
        self._consumer.commit()

    def close(self) -> None:
        self._consumer.close()
