"""Database access: an injected psycopg3 connection, never a module-global.

The connection is placed on ``app.state.db`` by whoever builds the app:
- production: a psycopg3 connection opened from HEADWAY_DATABASE_URL in the
  lifespan handler (one database per agency, ADR-0004 — the tenant boundary is
  the connection itself, so per-request tenant routing slots in here later);
- tests: a fake connection object with the same execute()/transaction() shape.

All queries in this service target the canonical schema names from handoff
0001 exactly (computed.metric_values, lineage.edges, cert.certifications,
audit.events, dq.issues) plus auth.users (migration 0009, responded to in the
handoff — not silently extended).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request


class DatabaseNotConfigured(RuntimeError):
    """Raised when a request needs the database but none was injected.

    This is deliberately loud: serving a data endpoint without a database
    would mean inventing or defaulting figures, which this API must never do.
    """


def get_db(request: Request):
    """FastAPI dependency: the injected database connection."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise DatabaseNotConfigured(
            "The Headway database connection is not configured. The API "
            "refuses to serve data it cannot read from the database."
        )
    return db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open a real psycopg3 connection if a DSN is configured.

    When ``app.state.db`` was already injected (tests, embedding), it is left
    untouched. Live verification against a real PostgreSQL is PENDING — the
    authoring environment has no Docker/Postgres (see README).
    """
    opened_here = None
    if getattr(app.state, "db", None) is None:
        dsn = os.environ.get("HEADWAY_DATABASE_URL")
        if dsn:
            # Imported lazily so the test suite never needs libpq at import time.
            import psycopg

            # autocommit=True is REQUIRED, not a style choice. With psycopg3's
            # default (autocommit=False) the first plain execute() on this
            # long-lived connection opens an implicit transaction that nothing
            # ever commits, and every router `with db.transaction():` block
            # then nests as a SAVEPOINT inside it — writes never reach disk,
            # yet the API returns 2xx. Found live 2026-07-10: a certification
            # returned 201 while cert.certifications stayed empty. With
            # autocommit=True, single statements commit immediately and
            # transaction() blocks are genuine BEGIN/COMMIT atomic units.
            opened_here = psycopg.connect(dsn, autocommit=True)
            app.state.db = opened_here
    try:
        yield
    finally:
        if opened_here is not None:
            opened_here.close()
            app.state.db = None
