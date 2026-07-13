"""Machine (service-account) authentication: API keys per handoff 0006.

Key format: ``hwk_<32 bytes url-safe random>`` — the ``hwk_`` prefix makes a
leaked key grep-able and distinguishes it from a session JWT. The full key is
returned exactly ONCE at issuance; only its SHA-256 hex digest is stored.

Why SHA-256 and not bcrypt: the correct hash depends on the entropy of what is
being hashed. Passwords are low-entropy human choices, so they need a slow,
salted, work-factor hash (bcrypt — see auth.py) to make dictionary attacks
expensive. These keys are 32 bytes of ``secrets.token_urlsafe`` randomness —
there is no dictionary to walk, and brute-forcing ~256 bits of entropy through
SHA-256 is infeasible. A fast hash is therefore the correct at-rest protection
here, and it keeps per-request verification cheap (bcrypt on every machine
request would add ~100ms of pure waste). This distinction is deliberate and
documented, not an oversight (handoff 0006, design point 1).

Scope checks are DENY-BY-DEFAULT: a key holds exactly the scopes it was issued
with, and an endpoint names the one scope it requires; anything else is a 403.
Every authentication failure and scope denial is audit-logged with actor
``key:<key_prefix>`` (design point 4 — success is audited by the endpoint that
performs the state change, so success and denial both land in audit.events).
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from .audit import write_event
from .auth import Identity, get_current_identity
from .db import get_db

KEY_PREFIX = "hwk_"
# First 12 chars ('hwk_' + 8 random chars): enough to identify a key in the
# UI, logs, and audit trail without ever exposing usable key material.
KEY_ID_PREFIX_LEN = 12

# v0 scope registry (handoff 0006, design point 3; ingest:dr added by
# handoff 0013). A scope not in this tuple cannot be issued, and an endpoint
# can only require a scope from this tuple — deny-by-default in both
# directions.
SCOPE_INGEST_TIDES = "ingest:tides"
SCOPE_INGEST_DR = "ingest:dr"
SCOPE_READ_METRICS = "read:metrics"
KNOWN_SCOPES = (SCOPE_INGEST_TIDES, SCOPE_INGEST_DR, SCOPE_READ_METRICS)

#: Scopes that push raw records and therefore REQUIRE a bound source_label
#: at issuance (the envelope source is always the key's label, never
#: client-supplied — the handoff-0005 rule, generalized by handoff 0013).
INGEST_SCOPES = (SCOPE_INGEST_TIDES, SCOPE_INGEST_DR)


@dataclass(frozen=True)
class NewKey:
    """A freshly generated key. ``full_key`` exists only in this object and in
    the one-time issuance response — it is never stored or logged."""

    full_key: str
    key_hash: str
    key_prefix: str


def generate_key() -> NewKey:
    full = KEY_PREFIX + secrets.token_urlsafe(32)
    return NewKey(
        full_key=full,
        key_hash=hash_key(full),
        key_prefix=full[:KEY_ID_PREFIX_LEN],
    )


def hash_key(full_key: str) -> str:
    """SHA-256 hex of the full key — see the module docstring for why a fast
    hash is correct for high-entropy random keys (unlike passwords)."""
    return hashlib.sha256(full_key.encode("ascii")).hexdigest()


@dataclass(frozen=True)
class MachineIdentity:
    """The verified machine caller — the machine analogue of auth.Identity."""

    key_id: str
    name: str
    key_prefix: str
    scopes: tuple[str, ...]
    source_label: str | None

    @property
    def actor(self) -> str:
        """Audit actor attribution: ``key:<key_prefix>`` (design point 4)."""
        return f"key:{self.key_prefix}"


_SELECT_KEY_BY_HASH = (
    "SELECT key_id, name, key_prefix, scopes, source_label, revoked_at "
    "FROM auth.api_keys WHERE key_hash = %s"
)

_NOT_A_MACHINE_KEY = HTTPException(
    status_code=401,
    detail=(
        "This endpoint requires a Headway machine API key, sent as "
        "'Authorization: Bearer hwk_...'. No valid key was provided. "
        "A Headway administrator can issue one via POST /machine/keys."
    ),
)


def get_machine_identity(request: Request, db=Depends(get_db)) -> MachineIdentity:
    """FastAPI dependency: resolve ``Authorization: Bearer hwk_...`` to an
    unrevoked auth.api_keys row. 401 (plain language) otherwise; failures are
    audit-logged with the presented key's prefix so a probing or revoked key
    is visible in the audit trail without ever logging key material."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token.startswith(KEY_PREFIX):
        raise _NOT_A_MACHINE_KEY
    presented_prefix = token[:KEY_ID_PREFIX_LEN]
    row = db.execute(_SELECT_KEY_BY_HASH, (hash_key(token),)).fetchone()
    if row is None:
        with db.transaction():
            write_event(
                db,
                actor=f"key:{presented_prefix}",
                action="machine_auth_failed",
                subject_kind="auth.api_keys",
                subject_id=None,
                detail={"reason": "unknown key", "path": request.url.path},
            )
        raise HTTPException(
            status_code=401,
            detail=(
                "This machine API key is not recognized. Please check the "
                "key, or ask a Headway administrator to issue a new one."
            ),
        )
    key_id, name, key_prefix, scopes, source_label, revoked_at = row
    if revoked_at is not None:
        with db.transaction():
            write_event(
                db,
                actor=f"key:{key_prefix}",
                action="machine_auth_failed",
                subject_kind="auth.api_keys",
                subject_id=str(key_id),
                detail={"reason": "key revoked", "path": request.url.path},
            )
        raise HTTPException(
            status_code=401,
            detail=(
                "This machine API key has been revoked and can no longer be "
                "used. Please ask a Headway administrator to issue a new one."
            ),
        )
    return MachineIdentity(
        key_id=str(key_id),
        name=name,
        key_prefix=key_prefix,
        scopes=tuple(scopes),
        source_label=source_label,
    )


def require_machine_scope(scope: str):
    """Dependency factory: the caller's key must hold exactly ``scope``.

    Deny-by-default: an unknown scope name here is a programming error and
    refuses at import time; a key without the scope gets a plain-language 403
    that is audit-logged (design point 4 — denial audited)."""
    if scope not in KNOWN_SCOPES:
        raise ValueError(f"Unknown machine scope {scope!r}; add it to KNOWN_SCOPES")

    def dependency(
        request: Request,
        identity: MachineIdentity = Depends(get_machine_identity),
        db=Depends(get_db),
    ) -> MachineIdentity:
        if scope not in identity.scopes:
            with db.transaction():
                write_event(
                    db,
                    actor=identity.actor,
                    action="machine_scope_denied",
                    subject_kind="auth.api_keys",
                    subject_id=identity.key_id,
                    detail={
                        "required_scope": scope,
                        "held_scopes": list(identity.scopes),
                        "path": request.url.path,
                    },
                )
            raise HTTPException(
                status_code=403,
                detail=(
                    f"This machine API key ('{identity.name}') does not have "
                    f"the '{scope}' permission it needs for this endpoint. "
                    f"Keys hold only the permissions they were issued with; "
                    f"a Headway administrator can issue a key with the right "
                    f"permissions."
                ),
            )
        return identity

    return dependency


# ---------------------------------------------------------------------------
# Rate limiting — in-process token bucket (handoff 0006, design point 6)
# ---------------------------------------------------------------------------


@dataclass
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    """Token bucket per string key (a key prefix, or a client IP).

    DOCUMENTED LIMITATION: this is IN-PROCESS state. It protects a
    single-instance deployment (the on-prem Compose stack) exactly as
    designed; a multi-instance hosted deployment multiplies the effective
    limit by the instance count. Distributed rate limiting is the hosted-tier
    increment (handoff 0006, Open Questions) — this class is the seam it
    replaces.
    """

    def __init__(
        self,
        requests_per_minute: int = 60,
        clock=time.monotonic,
    ):
        self.capacity = float(requests_per_minute)
        self.refill_per_second = requests_per_minute / 60.0
        self.clock = clock
        self._buckets: dict[str, _Bucket] = {}

    def try_acquire(self, key: str) -> float | None:
        """Take one token for ``key``. Returns None when allowed, or the
        number of seconds to wait (for Retry-After) when the bucket is dry."""
        now = self.clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=self.capacity, updated=now)
            self._buckets[key] = bucket
        bucket.tokens = min(
            self.capacity,
            bucket.tokens + (now - bucket.updated) * self.refill_per_second,
        )
        bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return None
        return (1.0 - bucket.tokens) / self.refill_per_second


def enforce_rate_limit(limiter: RateLimiter, key: str) -> None:
    """429 with Retry-After (whole seconds, rounded up) when the bucket is dry."""
    retry_after = limiter.try_acquire(key)
    if retry_after is not None:
        seconds = max(1, int(retry_after + 0.999))
        raise HTTPException(
            status_code=429,
            detail=(
                "This client is sending requests faster than its rate limit "
                f"allows. Please wait {seconds} second(s) and try again."
            ),
            headers={"Retry-After": str(seconds)},
        )


# ---------------------------------------------------------------------------
# Dual-credential access: human session OR machine key (handoff 0006
# follow-up — the lineage endpoint)
# ---------------------------------------------------------------------------

_DUAL_AUTH_401 = HTTPException(
    status_code=401,
    detail=(
        "This request could not be authenticated. The credential is "
        "missing, invalid, expired, or revoked. Please check it, or "
        "contact your Headway administrator."
    ),
)


def require_human_session_or_machine_scope(scope: str):
    """Dependency factory: accept EITHER a signed-in human session OR a
    machine API key holding ``scope``. Built for the lineage endpoint
    (``GET /metrics/values/{id}/lineage``) — the follow-up increment noted
    in handoff 0006's Response and routers/machine_read.py.

    ORDER OF ATTEMPTS — dispatch on the Bearer token's shape, exactly one
    path per request:

    1. MACHINE: a Bearer token carrying the ``hwk_`` key prefix is treated
       as a machine key and never as a session token. It must resolve to an
       unrevoked auth.api_keys row (else 401) holding ``scope`` (else the
       same audited, plain-language 403 as require_machine_scope), and the
       request then spends from the same per-key token bucket as every
       other machine endpoint (429 + Retry-After when dry). Returns the
       MachineIdentity so the endpoint can audit the successful read with
       actor ``key:<key_prefix>`` (design point 4).
    2. HUMAN: any other credential is verified as a session token exactly
       as auth.get_current_identity does. The human path is UNCHANGED —
       any signed-in role, no rate limit, no extra audit; the same read
       semantics as every other signed-in GET.

    FAILURE MESSAGES MUST NOT LEAK WHICH CREDENTIAL TYPE WAS EXPECTED:
    every authentication failure on either path — absent header, malformed
    or expired session token, unknown or revoked machine key — raises the
    SAME generic 401 (``_DUAL_AUTH_401``), so a probing caller learns
    nothing about which kinds of credential the endpoint accepts or why
    theirs failed. The audit trail keeps the specific reason (machine-key
    failures are audit-logged with the presented prefix inside
    get_machine_identity BEFORE the response is made generic); only the
    HTTP response is generic. Scope denial stays a specific 403 — by then
    the caller has already proven possession of a valid key.
    """
    machine_scope_check = require_machine_scope(scope)

    def dependency(
        request: Request, db=Depends(get_db)
    ) -> Identity | MachineIdentity:
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        token = token.strip()
        if scheme.lower() == "bearer" and token.startswith(KEY_PREFIX):
            try:
                identity = get_machine_identity(request, db)
                machine_scope_check(request, identity, db)
            except HTTPException as exc:
                if exc.status_code == 401:
                    # The specific reason is already in audit.events;
                    # the wire response stays generic.
                    raise _DUAL_AUTH_401
                raise
            enforce_rate_limit(
                request.app.state.machine_rate_limiter, identity.key_prefix
            )
            return identity
        try:
            return get_current_identity(request)
        except HTTPException:
            raise _DUAL_AUTH_401

    return dependency
