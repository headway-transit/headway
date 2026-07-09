"""Shared fixtures: envelope builders and a fake DB-API connection."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

# Make the package importable when tests run from the service directory
# without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def sha256_hex(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def make_envelope_dict(
    payload_bytes: bytes,
    *,
    source: str = "gtfs_rt",
    connector: str = "headway-gtfs-rt",
    content_type: str = "application/x-protobuf",
    payload_encoding: str = "base64",
    parse_status: str = "ok",
    **overrides,
) -> dict:
    doc = {
        "envelope_version": 0,
        "record_id": sha256_hex(payload_bytes),
        "source": source,
        "connector": connector,
        "connector_version": "0.1.0",
        "fetched_at": "2026-07-08T12:00:00Z",
        "content_type": content_type,
        "payload_encoding": payload_encoding,
        "payload": base64.b64encode(payload_bytes).decode("ascii"),
        "parse_status": parse_status,
    }
    doc.update(overrides)
    return doc


def envelope_json(payload: bytes, **overrides) -> bytes:
    return json.dumps(make_envelope_dict(payload, **overrides)).encode()


class FakeCursor:
    def __init__(self, log: list[tuple[str, tuple]]) -> None:
        self._log = log
        self.closed = False

    def execute(self, sql: str, params: tuple) -> None:
        self._log.append((sql, params))

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    """DB-API-ish connection capturing every (sql, params) executed."""

    def __init__(self, fail_on_sql_containing: str | None = None) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on_sql_containing = fail_on_sql_containing

    def cursor(self) -> FakeCursor:
        if self.fail_on_sql_containing is None:
            return FakeCursor(self.executed)
        outer = self

        class FailingCursor(FakeCursor):
            def execute(self, sql: str, params: tuple) -> None:
                if outer.fail_on_sql_containing in sql:
                    raise RuntimeError(
                        f"injected failure on SQL containing "
                        f"{outer.fail_on_sql_containing!r}"
                    )
                super().execute(sql, params)

        return FailingCursor(self.executed)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def sql_for(self, table: str) -> list[tuple[str, tuple]]:
        return [(sql, params) for sql, params in self.executed if table in sql]


@pytest.fixture
def fake_connection() -> FakeConnection:
    return FakeConnection()
