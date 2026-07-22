"""Database access: an injected connection or a per-request pooled one.

Two modes, selected by whoever builds the app (never a module global):

- tests / embedding: a connection object with the psycopg3 ``execute()`` /
  ``transaction()`` shape is INJECTED on ``app.state.db`` and every request
  shares it (the fake keeps state in dicts);
- production: the lifespan opens a **psycopg_pool ConnectionPool** from
  HEADWAY_DATABASE_URL (one database per agency, ADR-0004 — the tenant
  boundary is the connection itself, so per-request tenant routing slots in
  here later) and ``get_db`` checks a connection out PER REQUEST.

Why a pool (handoff 0023, design point 1 — measured, not guessed): the
previous single long-lived connection made psycopg3 serialize every sibling
request behind whichever query held the connection lock — a 1.5 ms count was
measured at 3.7 s because it queued behind a slow one. Handlers here are sync
(FastAPI runs them in its threadpool), so with one connection per request the
requests genuinely overlap. Authz/audit semantics are unchanged: the same
dependency yields the same execute()/transaction() surface, and every
router's write+audit block still commits atomically on its own connection.

All queries in this service target the canonical schema names from handoff
0001 exactly (computed.metric_values, lineage.edges, cert.certifications,
audit.events, dq.issues) plus auth.users (migration 0009, responded to in the
handoff — not silently extended).
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

#: Pool bounds — sized for a small agency box (on-prem parity): a handful of
#: dashboard users polling, not a public API. Overridable by environment for
#: larger deployments; the pool blocks (then times out loudly) rather than
#: opening unbounded connections against the agency database.
DEFAULT_POOL_MIN = 2
DEFAULT_POOL_MAX = 8


class DatabaseNotConfigured(RuntimeError):
    """Raised when a request needs the database but none was injected.

    This is deliberately loud: serving a data endpoint without a database
    would mean inventing or defaulting figures, which this API must never do.
    """


def get_db(request: Request):
    """FastAPI dependency: the injected connection, or one checked out of the
    production pool for exactly this request.

    The injected connection (tests, embedding) wins when present — identical
    behavior to every wave before the pool. Otherwise a pooled psycopg3
    connection is yielded and returned to the pool when the request ends.
    """
    db = getattr(request.app.state, "db", None)
    if db is not None:
        yield db
        return
    pool = getattr(request.app.state, "db_pool", None)
    if pool is None:
        raise DatabaseNotConfigured(
            "The Headway database connection is not configured. The API "
            "refuses to serve data it cannot read from the database."
        )
    with pool.connection() as conn:
        yield conn


def _configure_pooled_connection(conn) -> None:
    """Every pooled connection is autocommit=True — REQUIRED, not a style
    choice. With psycopg3's default (autocommit=False) the first plain
    execute() opens an implicit transaction that nothing ever commits, and
    every router `with db.transaction():` block then nests as a SAVEPOINT
    inside it — writes never reach disk, yet the API returns 2xx. Found live
    2026-07-10: a certification returned 201 while cert.certifications stayed
    empty. With autocommit=True, single statements commit immediately and
    transaction() blocks are genuine BEGIN/COMMIT atomic units."""
    conn.autocommit = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Open the connection pool if a DSN is configured.

    When ``app.state.db`` was already injected (tests, embedding), it is left
    untouched and no pool is opened.
    """
    opened_pool = None
    if getattr(app.state, "db", None) is None:
        dsn = os.environ.get("HEADWAY_DATABASE_URL")
        if dsn:
            # Imported lazily so the test suite never needs libpq at import time.
            from psycopg_pool import ConnectionPool

            opened_pool = ConnectionPool(
                dsn,
                min_size=int(
                    os.environ.get("HEADWAY_DB_POOL_MIN", str(DEFAULT_POOL_MIN))
                ),
                max_size=int(
                    os.environ.get("HEADWAY_DB_POOL_MAX", str(DEFAULT_POOL_MAX))
                ),
                configure=_configure_pooled_connection,
                # Fail loudly at startup if the database is unreachable,
                # rather than booting an API that cannot serve data.
                open=True,
            )
            app.state.db_pool = opened_pool
    # Ingest seams (handoff 0006): when not injected, wire MinIO and Kafka
    # from the same env vars the Go connectors use. Imported here (not at
    # module top) because routers.ingest imports this module. None stays None:
    # the ingest endpoint then refuses with a plain-language 503 rather than
    # ever silently accepting bytes it cannot land.
    from .routers.ingest import object_store_from_env, producer_from_env

    if getattr(app.state, "object_store", None) is None:
        app.state.object_store = object_store_from_env()
    if getattr(app.state, "producer", None) is None:
        app.state.producer = producer_from_env()
    try:
        yield
    finally:
        if opened_pool is not None:
            opened_pool.close()
            app.state.db_pool = None
