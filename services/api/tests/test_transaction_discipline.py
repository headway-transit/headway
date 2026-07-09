"""Regression tests for the 2026-07-10 uncommitted-transaction bug.

Found live: the API returned 201 for a certification while cert.certifications
stayed empty. Cause: the lifespan opened the psycopg3 connection with the
default autocommit=False, so the first plain execute() began an implicit
transaction that was never committed, and every router `with db.transaction():`
block nested as a SAVEPOINT inside it — releasing the savepoint, committing
nothing. The unit-test fake modeled transaction() as a real commit and masked
it. These tests pin the fix at the two layers a unit suite can reach:

1. the production lifespan MUST open the connection with autocommit=True;
2. a fake that mimics psycopg3's actual nesting semantics proves the router
   pattern (`with db.transaction():`) only persists under autocommit=True.

The full protection is the CI integration job against a real PostgreSQL
(GitHub Actions service container) — tracked as a follow-up; a fake can prove
the pattern, only a real database proves the system.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from headway_api.db import lifespan
from fastapi import FastAPI


@pytest.mark.anyio
async def test_lifespan_opens_connection_with_autocommit_true(monkeypatch):
    """The production connection MUST be autocommit=True (see module docstring)."""
    recorded = {}

    class FakeConn:
        def close(self):
            pass

    def fake_connect(dsn, **kwargs):
        recorded["dsn"] = dsn
        recorded["kwargs"] = kwargs
        return FakeConn()

    monkeypatch.setenv("HEADWAY_DATABASE_URL", "postgresql://x@localhost/x")
    app = FastAPI()
    app.state.db = None
    with mock.patch.dict("sys.modules"):
        import psycopg  # noqa: F401 — ensure importable name exists to patch

        monkeypatch.setattr("psycopg.connect", fake_connect)
        async with lifespan(app):
            pass

    assert recorded["kwargs"].get("autocommit") is True, (
        "lifespan opened the database connection without autocommit=True — "
        "psycopg3's implicit-transaction trap makes every router "
        "transaction() block a never-committed SAVEPOINT (2026-07-10 bug)."
    )


class Psycopg3SemanticsFake:
    """A connection fake honest about psycopg3's transaction nesting.

    - autocommit=False: first execute() begins an implicit transaction;
      transaction() blocks nest as savepoints; nothing persists until an
      explicit outer commit() (which the API never issues).
    - autocommit=True: plain execute() persists immediately; transaction()
      blocks persist their statements on successful exit.

    `persisted` is what an OUTSIDE observer (psql) would see.
    """

    def __init__(self, autocommit: bool) -> None:
        self.autocommit = autocommit
        self.persisted: list[str] = []
        self._implicit_txn: list[str] = []
        self._in_implicit = False
        self._depth = 0
        self._block: list[str] = []

    def execute(self, sql, params=None):
        if self._depth > 0:
            self._block.append(sql)
        elif self.autocommit:
            self.persisted.append(sql)
        else:
            self._in_implicit = True
            self._implicit_txn.append(sql)
        return self

    def fetchall(self):
        return []

    def fetchone(self):
        return None

    def transaction(self):
        fake = self

        class _Block:
            def __enter__(self):
                fake._depth += 1
                return fake

            def __exit__(self, exc_type, exc, tb):
                fake._depth -= 1
                if exc_type is not None:
                    fake._block.clear()
                    return False
                if fake._depth == 0:
                    if fake.autocommit and not fake._in_implicit:
                        # genuine BEGIN/COMMIT block
                        fake.persisted.extend(fake._block)
                    else:
                        # SAVEPOINT released inside the never-committed
                        # implicit transaction: visible only inside it.
                        fake._implicit_txn.extend(fake._block)
                    fake._block.clear()
                return False

        return _Block()


def _router_write_pattern(conn) -> None:
    """The exact shape every state-changing router uses."""
    conn.execute("SELECT 1")  # any earlier read on the same connection
    with conn.transaction():
        conn.execute("INSERT INTO cert.certifications ...")
        conn.execute("UPDATE computed.metric_values ...")
        conn.execute("INSERT INTO audit.events ...")


def test_router_pattern_persists_nothing_under_default_autocommit_false():
    """Reproduces the live bug: 2xx behavior, zero rows visible outside."""
    conn = Psycopg3SemanticsFake(autocommit=False)
    _router_write_pattern(conn)
    assert conn.persisted == [], (
        "under autocommit=False the writes should be trapped in the implicit "
        "transaction — if this list is non-empty the fake no longer models "
        "the psycopg3 semantics that caused the 2026-07-10 bug"
    )
    assert len(conn._implicit_txn) == 4  # all four statements are in limbo


def test_router_pattern_persists_under_autocommit_true():
    conn = Psycopg3SemanticsFake(autocommit=True)
    _router_write_pattern(conn)
    assert "INSERT INTO cert.certifications ..." in conn.persisted
    assert "INSERT INTO audit.events ..." in conn.persisted
    assert len(conn.persisted) == 4
