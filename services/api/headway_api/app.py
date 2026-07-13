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

from . import __version__, auth, webhooks
from .db import lifespan
from .machine_auth import RateLimiter
from .routers import (
    branding,
    certify,
    dq,
    ingest,
    machine_keys,
    machine_read,
    metrics,
    public,
    reports,
    safety,
    sampling,
    settings as settings_router,
)


@dataclass(frozen=True)
class Settings:
    session_secret: str
    token_ttl_seconds: int = auth.DEFAULT_TOKEN_TTL_SECONDS
    # In-process token buckets (handoff 0006, design point 6): per machine
    # key for ingest, per client IP for the public open-data endpoint.
    machine_requests_per_minute: int = 60
    public_requests_per_minute: int = 60


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


def create_app(
    settings: Settings | None = None,
    db=None,
    *,
    object_store=None,
    producer=None,
    webhook_sender=None,
) -> FastAPI:
    """Build the API.

    - ``settings``: pass explicitly (tests) or omit to read from env.
    - ``db``: an injected connection (tests / embedding); omit to let the
      lifespan open a psycopg3 connection from HEADWAY_DATABASE_URL.
    - ``object_store`` / ``producer``: injected ingest seams (handoff 0006 —
      fakes in tests); omit to let the lifespan wire MinIO/Kafka from the
      environment (S3_*/KAFKA_BROKERS, the ``ingest`` extra). When neither
      injection nor environment provides them, ingest refuses with a
      plain-language 503 — never a silent accept.
    - ``webhook_sender``: injected webhook HTTP seam (fake in tests); omit
      for the httpx sender (httpx is a core dependency).
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
    app.state.object_store = object_store
    app.state.producer = producer
    app.state.webhook_sender = (
        webhook_sender
        if webhook_sender is not None
        else webhooks.HttpxWebhookSender()
    )
    app.state.machine_rate_limiter = RateLimiter(
        app.state.settings.machine_requests_per_minute
    )
    app.state.public_rate_limiter = RateLimiter(
        app.state.settings.public_requests_per_minute
    )
    # CORS: off by default (production serves web same-origin / behind a
    # reverse proxy). Set HEADWAY_CORS_ORIGINS to a comma-separated origin
    # list for split-origin deployments (e.g. the Vite dev server at
    # http://localhost:5173). Found live 2026-07-11: the first real-browser
    # login failed silently cross-origin because no CORS headers existed —
    # mocked-fetch tests can never see this class of gap.
    _cors = [o.strip() for o in os.environ.get("HEADWAY_CORS_ORIGINS", "").split(",") if o.strip()]
    if _cors:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors,
            allow_credentials=False,  # bearer tokens in headers, not cookies
            allow_methods=["GET", "POST", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type"],
        )

    app.include_router(auth.router)
    app.include_router(metrics.router)
    app.include_router(certify.router)
    app.include_router(dq.router)
    app.include_router(machine_keys.router)
    app.include_router(machine_read.router)
    app.include_router(settings_router.router)
    app.include_router(ingest.router)
    app.include_router(webhooks.router)
    app.include_router(reports.router)
    app.include_router(public.router)
    app.include_router(branding.router)
    app.include_router(safety.router)
    app.include_router(sampling.router)
    return app
