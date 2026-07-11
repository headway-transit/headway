"""Shared fixtures: a fake DB-API connection capturing every statement.

The fake understands just enough of the tool's SQL to act like the real
database: the key-column SELECT returns configured canonical rows, edge
count/delete statements operate on a configured list of lineage edges, and
every (sql, params) pair is recorded in order so tests can assert exactly
what would hit the database — and in what order.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Make replace.py importable when tests run from the tool directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _normalized(sql: str) -> str:
    return " ".join(sql.split()).lower()


class FakeCursor:
    def __init__(self, conn: "FakeConnection") -> None:
        self._conn = conn
        self._result: list[tuple] = []
        self.rowcount = -1
        self.closed = False

    def execute(self, sql: str, params: Any = None) -> None:
        conn = self._conn
        conn.executed.append((sql, params))
        s = _normalized(sql)

        if conn.fail_on_sql_containing and conn.fail_on_sql_containing in sql:
            raise RuntimeError(
                f"injected failure on SQL containing "
                f"{conn.fail_on_sql_containing!r}"
            )

        if s.startswith("select count(*) from lineage.edges"):
            kind, ids = params
            wanted = set(ids)
            n = sum(1 for k, i in conn.edges if k == kind and i in wanted)
            self._result = [(n,)]
        elif s.startswith("select"):
            self._result = list(conn.canonical_rows)
        elif s.startswith("delete from lineage.edges"):
            kind, ids = params
            wanted = set(ids)
            matched = [(k, i) for k, i in conn.edges if k == kind and i in wanted]
            for edge in matched:
                conn.edges.remove(edge)
            self.rowcount = len(matched)
        elif s.startswith("delete from"):
            self.rowcount = len(conn.canonical_rows)
            conn.canonical_rows = []
        elif s.startswith("insert into dq.issues"):
            conn.dq_rows.append(params)
            self.rowcount = 1
        else:  # pragma: no cover - unexpected SQL is a test failure signal
            raise AssertionError(f"fake connection got unexpected SQL: {sql}")

    def fetchone(self) -> tuple:
        return self._result[0]

    def fetchall(self) -> list[tuple]:
        return list(self._result)

    def close(self) -> None:
        self.closed = True


class FakeConnection:
    """DB-API-ish connection capturing every (sql, params) executed.

    canonical_rows: tuples shaped like the tool's key-column SELECT result.
    edges: list of (output_kind, output_id) lineage rows (duplicates allowed
    — e.g. a re-normalized route has several edges with the same output_id).
    """

    def __init__(
        self,
        canonical_rows: list[tuple] | None = None,
        edges: list[tuple[str, str]] | None = None,
        fail_on_sql_containing: str | None = None,
    ) -> None:
        self.canonical_rows = list(canonical_rows or [])
        self.edges = list(edges or [])
        self.executed: list[tuple[str, Any]] = []
        self.dq_rows: list[tuple] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on_sql_containing = fail_on_sql_containing

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def sql_like(self, fragment: str) -> list[tuple[str, Any]]:
        return [
            (sql, params)
            for sql, params in self.executed
            if fragment.lower() in _normalized(sql)
        ]


@pytest.fixture
def fake_connection() -> FakeConnection:
    return FakeConnection()
