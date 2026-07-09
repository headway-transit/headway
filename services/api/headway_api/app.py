"""Application factory.

The database connection and the session secret are INJECTED (app state /
environment), never module globals — so tests run against a fake connection
and production runs against the agency's own database (ADR-0004: the tenant
boundary is the connection itself).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import FastAPI

from . import __version__, auth
from .db import lifespan
from .routers import certify, dq, metrics


@dataclass(frozen=True)
class Settings:
    session_secret: str
    token_ttl_seconds: int = auth.DEFAULT_TOKEN_TTL_SECONDS


class MissingSessionSecret(RuntimeError):
    """Raised at startup rather than ever signing tokens with a default key."""


def settings_from_env() -> Settings:
    secret = os.environ.get("HEADWAY_SESSION_SECRET", "")
    if not secret:
        raise MissingSessionSecret(
            "HEADWAY_SESSION_SECRET is not set. The API refuses to start "
            "without a real session-signing secret — a guessable secret "
            "would let anyone forge a certifying official's session."
        )
    ttl = int(os.environ.get("HEADWAY_TOKEN_TTL_SECONDS", str(auth.DEFAULT_TOKEN_TTL_SECONDS)))
    return Settings(session_secret=secret, token_ttl_seconds=ttl)


def create_app(settings: Settings | None = None, db=None) -> FastAPI:
    """Build the API.

    - ``settings``: pass explicitly (tests) or omit to read from env.
    - ``db``: an injected connection (tests / embedding); omit to let the
      lifespan open a psycopg3 connection from HEADWAY_DATABASE_URL.
    """
    app = FastAPI(
        title="Headway API",
        version=__version__,
        description=(
            "Serves computed transit metrics with full lineage, the DQ "
            "resolution workflow, and the audited certification action. "
            "This API never computes a reported figure; it serves what the "
            "calculation library produced, joined to its provenance. "
            "Reported values are JSON strings (exact NUMERIC, never float). "
            "Auth: local accounts (ADR-0011); the native OIDC relying party "
            "is the next increment behind the same {sub, username, role} "
            "claim set."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings if settings is not None else settings_from_env()
    app.state.db = db
    app.include_router(auth.router)
    app.include_router(metrics.router)
    app.include_router(certify.router)
    app.include_router(dq.router)
    return app
