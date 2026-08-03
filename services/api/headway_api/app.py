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

from . import __version__, auth, client_identity, webhooks
from .db import lifespan
from .machine_auth import FailureAuditThrottle, RateLimiter
from .routers import (
    datasets,
    attestations,
    audit_trail,
    branding,
    calc_runs,
    certify,
    dq,
    evidence,
    geometry,
    history,
    ingest,
    machine_keys,
    machine_read,
    metrics,
    oidc as oidc_router,
    ops,
    public,
    raw_records,
    reports,
    revenue_review,
    safety,
    sampling,
    sandbox,
    settings as settings_router,
    sources,
    users,
)


@dataclass(frozen=True)
class Settings:
    session_secret: str
    token_ttl_seconds: int = auth.DEFAULT_TOKEN_TTL_SECONDS
    # In-process token buckets (handoff 0006, design point 6): per machine
    # key for ingest, per client IP for the public open-data endpoint.
    machine_requests_per_minute: int = 60
    public_requests_per_minute: int = 60
    # Per client IP for the UNAUTHENTICATED single-sign-on surface. Lower than
    # the others on purpose: starting a sign-in makes Headway open an outbound
    # connection to the identity provider, so an unlimited /auth/oidc/start is
    # a way to spend this box's request workers — and the worker that cannot
    # be spent is the one serving local login, the break-glass path. A person
    # signs in once or twice a day, so 30 a minute is generous per person.
    # (It used to say "generous even for a whole agency arriving behind one
    # reverse-proxy address" — which was sizing around an identity bug.
    # ``trusted_proxies`` below is the actual fix: raising a shared allowance
    # never stopped one caller from spending all of it.)
    sso_requests_per_minute: int = 30
    # Per SIGNED-IN ACCOUNT, across every authenticated endpoint, enforced at
    # the auth choke point. Until now the only rate limits in this API covered
    # machine keys and the two unauthenticated surfaces; a signed-in human
    # session — including an ``auditor``, an account deliberately handed to
    # someone outside the agency — could issue requests as fast as the box
    # would answer. Sized for a UI, not a person: one screen can fire dozens of
    # requests (the review worklist issues one per row), so this must be high
    # enough that nobody meets it by working, and low enough that a script
    # cannot use one account as a load generator.
    human_requests_per_minute: int = 600
    # Per signed-in account, for the evidence bundle ALONE. Its own bucket
    # because its cost is measured rather than assumed: 142 MB of peak
    # allocation and 4.3 seconds for one capped bundle
    # (tests/bench_evidence_cost.py). At the blanket limit above, one account
    # could ask for 600 of those a minute. Ten is more than an auditor who
    # actually reads them will ever need.
    evidence_bundle_requests_per_minute: int = 10
    #: Addresses/CIDRs whose ``X-Forwarded-For`` this installation believes
    #: (see client_identity). EMPTY means trust nothing and use the peer
    #: address — unspoofable, and correct for a directly exposed API. Set
    #: HEADWAY_TRUSTED_PROXIES on any deployment with a reverse proxy in
    #: front, or every caller shares one bucket.
    trusted_proxies: tuple[str, ...] = ()


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
    # Validated here so a typo refuses at startup (InvalidTrustedProxy) rather
    # than silently leaving every caller in one bucket.
    trusted = client_identity.parse_trusted_proxies(
        os.environ.get("HEADWAY_TRUSTED_PROXIES")
    )
    return Settings(
        session_secret=secret,
        token_ttl_seconds=ttl,
        trusted_proxies=trusted,
        human_requests_per_minute=_positive_int_env(
            "HEADWAY_HUMAN_REQUESTS_PER_MINUTE",
            Settings.human_requests_per_minute,
        ),
        evidence_bundle_requests_per_minute=_positive_int_env(
            "HEADWAY_EVIDENCE_BUNDLE_REQUESTS_PER_MINUTE",
            Settings.evidence_bundle_requests_per_minute,
        ),
    )


def _positive_int_env(name: str, default: int) -> int:
    """A tunable limit from the environment, refusing nonsense at startup.

    Zero is ALLOWED and means "refuse everything" — a legitimate way to close
    a surface without a code change. Negative and non-numeric are not: they
    would be silently coerced into something the operator did not ask for.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"{name} is {raw!r}, which is not a whole number. Headway refuses "
            f"to start rather than guess a rate limit."
        ) from exc
    if value < 0:
        raise ValueError(
            f"{name} is {value}, which is not a number of requests. Use 0 to "
            f"refuse every request to that surface, or a positive number."
        )
    return value


def create_app(
    settings: Settings | None = None,
    db=None,
    *,
    object_store=None,
    producer=None,
    webhook_sender=None,
    calc_run_launcher=None,
    raw_payload_reader=None,
    oidc_metadata=None,
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
    - ``calc_run_launcher``: injected calc-run dispatch seam (handoff 0026 —
      a fake in tests records launches instead of spawning subprocesses);
      omit for the real background-thread launcher in routers/calc_runs.py.
    - ``raw_payload_reader``: injected raw-payload read seam (handoff 0035 —
      a fake in tests serves bytes from a dict). Omit and the raw-record
      inspector builds the live reader on first use from the same seams
      ingest uses: the object store for ``payload_encoding='object_ref'``
      and the ingest envelope stream (KAFKA_BROKERS) for the inline
      ``base64`` payloads GTFS-Realtime frames arrive as. Missing
      configuration refuses in plain words — never an empty preview.
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
            "Auth: local accounts AND a native OIDC relying party "
            "(ADR-0011), both producing the same {sub, username, role} claim "
            "set. Local accounts are never disabled by single sign-on — an "
            "IdP outage, an air-gapped box, or a misconfigured provider all "
            "leave the local path working."
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
    # None = the real background-thread launcher (routers/calc_runs.py picks
    # it up at request time); tests inject a recording fake.
    app.state.calc_run_launcher = calc_run_launcher
    # None = built on first use from app.state.object_store + KAFKA_BROKERS
    # (routers/raw_records.py); tests inject a fake reader.
    app.state.raw_payload_reader = raw_payload_reader
    # Compiled once, here, rather than per request — and read through
    # ``getattr`` at the call sites, so a bare test app that builds no state
    # still behaves exactly as it did before trusted proxies existed.
    app.state.trusted_proxy_networks = client_identity.networks(
        app.state.settings.trusted_proxies
    )
    app.state.machine_rate_limiter = RateLimiter(
        app.state.settings.machine_requests_per_minute
    )
    # Per SIGNED-IN ACCOUNT, enforced at the auth choke point so no
    # authenticated endpoint can be added outside it. Its own instance: a
    # machine key flooding ingest must not spend a person's allowance.
    app.state.human_rate_limiter = RateLimiter(
        app.state.settings.human_requests_per_minute
    )
    # The evidence bundle's own, much tighter bucket — the one endpoint whose
    # per-request cost has been measured rather than assumed.
    app.state.evidence_rate_limiter = RateLimiter(
        app.state.settings.evidence_bundle_requests_per_minute
    )
    # Coalesce repeated auth/scope FAILURE audit writes so rejected requests
    # (which never reach the in-body rate limiter) cannot amplify into
    # unbounded audit.events INSERTs — adversarial-review finding F1.
    app.state.machine_audit_throttle = FailureAuditThrottle()
    # The same coalescing for the UNAUTHENTICATED single-sign-on surface
    # (handoff 0046). Separate instance so a flood of forged OIDC callbacks
    # cannot suppress the audit record of a genuine machine-key failure, and
    # vice versa — one attacker must not be able to blind the trail to
    # another.
    app.state.login_audit_throttle = FailureAuditThrottle()
    # Discovery/JWKS cache, shared across requests so key rotation is handled
    # once per process rather than per sign-in. Tests inject a fake.
    app.state.oidc_metadata = oidc_metadata
    app.state.public_rate_limiter = RateLimiter(
        app.state.settings.public_requests_per_minute
    )
    # Its own bucket, for the same reason login_audit_throttle is its own
    # instance: a flood against single sign-on must not exhaust the budget
    # that serves the public transparency endpoint, or the reverse.
    app.state.sso_rate_limiter = RateLimiter(
        app.state.settings.sso_requests_per_minute
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
    app.include_router(calc_runs.router)
    app.include_router(metrics.router)
    app.include_router(history.router)
    app.include_router(ops.router)
    app.include_router(geometry.router)
    app.include_router(certify.router)
    app.include_router(evidence.router)
    app.include_router(attestations.router)
    app.include_router(dq.router)
    app.include_router(machine_keys.router)
    app.include_router(machine_read.router)
    app.include_router(settings_router.router)
    app.include_router(datasets.router)
    app.include_router(ingest.router)
    app.include_router(webhooks.router)
    app.include_router(reports.router)
    app.include_router(public.router)
    app.include_router(raw_records.router)
    app.include_router(revenue_review.router)
    app.include_router(branding.router)
    app.include_router(safety.router)
    app.include_router(sampling.router)
    app.include_router(sandbox.router)
    app.include_router(users.router)
    app.include_router(sources.router)
    app.include_router(oidc_router.router)
    app.include_router(audit_trail.router)
    return app
