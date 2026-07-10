"""Shared test fakes. NO test in this suite touches the network or a live DB."""

from __future__ import annotations

import pytest


class CapturingCursor:
    """DB-API-shaped cursor that records every (sql, params) it executes."""

    def __init__(self, existing_ids: frozenset[str], executed: list[tuple[str, tuple]]):
        self._existing_ids = existing_ids
        self._executed = executed
        self._row = None
        self.closed = False

    def execute(self, sql: str, params=()):
        self._executed.append((sql, tuple(params)))
        # Existence is decided on the record id: the last bound parameter.
        record_id = params[-1] if params else None
        self._row = (1,) if record_id in self._existing_ids else None

    def fetchone(self):
        return self._row

    def close(self):
        self.closed = True


class CapturingConnection:
    """Fake DB-API connection: answers existence by id, captures all queries."""

    def __init__(self, existing_ids=()):
        self.existing_ids = frozenset(existing_ids)
        self.executed: list[tuple[str, tuple]] = []
        self.cursors: list[CapturingCursor] = []

    def cursor(self):
        cursor = CapturingCursor(self.existing_ids, self.executed)
        self.cursors.append(cursor)
        return cursor


@pytest.fixture
def capturing_connection():
    def _make(existing_ids=()):
        return CapturingConnection(existing_ids)

    return _make
