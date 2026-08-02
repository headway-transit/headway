"""Authentication: local accounts, and the session token both paths mint.

ADR-0011 chose a native OIDC relying party PLUS local accounts. Both now
exist. This module owns local accounts and the normalized claim set; the
relying party lives in ``oidc.py`` + ``routers/oidc.py`` and produces the
SAME claim set, so nothing downstream can tell the two apart:

    {sub, username, role, jti, idp_issuer?, idp_subject?}

Everything downstream (authz.py, the routers, audit actor attribution)
consumes only that claim set, so OIDC is a new token *source*, not a rework
of authorization.

LOCAL ACCOUNTS SURVIVE, PERMANENTLY (handoff 0046). OIDC is beside them,
never instead of them: an installation with no internet or an IdP having a
bad morning must still be operable; the first OIDC configuration attempt will
be wrong and there must be a way in that does not depend on it; and
``install.sh --reset-admin-password`` keeps working. Nothing in the OIDC path
can disable this one.

NOTE — auth.users is NOT part of handoff 0001's schema contract. It is added
by migration ``db/migrations/0009_auth_users.sql`` with an explicit
``## Response — backend-engineer`` section appended to that handoff (schema
handoffs require explicit responses, not silent extension). Migration 0043
adds the federation columns and makes ``password_hash`` nullable, because a
federated account has no password and a dummy hash would be a lie a future
reader could mistake for a credential.

Password hashing: **bcrypt** (the ``bcrypt`` PyPI package, Apache-2.0 license
— OSI-approved permissive, satisfies ADR-0001). Session tokens: PyJWT (MIT),
HS256, secret from the HEADWAY_SESSION_SECRET environment variable, short
expiry (30 minutes by default).
"""

from __future__ import annotations

import datetime as dt
import secrets
from dataclasses import dataclass

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .audit import write_event
from .db import get_db

ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_SECONDS = 30 * 60

#: Every role a session token may carry. ``auditor`` (handoff 0046 /
#: migration 0042) reads broadly and writes nothing; it is NOT a rung on the
#: authz ladder — see authz.py.
VALID_ROLES = (
    "viewer",
    "data_steward",
    "report_preparer",
    "certifying_official",
    "auditor",
)

#: Roles that may never perform a state-changing request, enforced below at
#: the single authentication choke point. Kept here rather than imported from
#: authz.py because authz imports this module (and because the ban must hold
#: even if a future authz refactor forgets it).
_NO_WRITE_ROLES = frozenset({"auditor"})

#: HTTP methods that cannot change state. Everything else is a write.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# bcrypt only reads the first 72 bytes of a password; longer input must be
# rejected loudly, never silently truncated.
_BCRYPT_MAX_BYTES = 72


class PasswordTooLong(ValueError):
    """Raised instead of silently truncating a >72-byte password."""


#: A real bcrypt hash of a value nothing can be, so that a refusal for an
#: account that does not exist — or one that has no local password — costs the
#: same wall-clock as a refusal for a wrong password. Generated once at import,
#: never compared against anything a caller controls the other side of.
_DUMMY_HASH = bcrypt.hashpw(secrets.token_hex(32).encode("ascii"), bcrypt.gensalt())


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise PasswordTooLong(
            "Passwords longer than 72 bytes are not supported. Please choose "
            "a shorter password."
        )
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Verify a password against a stored bcrypt hash.

    ``password_hash is None`` is a FEDERATED account (migration 0043): it has
    no password, so no password can ever match it. Returning False here (and
    not raising) keeps the login surface's single generic refusal intact —
    the caller cannot tell a federated account from a wrong password.

    The comparison against ``_DUMMY_HASH`` in that case is NOT dead work. A
    generic message and a fast answer are not the same guarantee: bcrypt at
    this cost takes a few hundred milliseconds, so returning early would let
    anyone sort usernames into "local account" and "everything else" with a
    stopwatch — and the local accounts are the break-glass administrators.
    Every refusal on this path costs the same as a real check.
    """
    if password_hash is None:
        bcrypt.checkpw(password.encode("utf-8")[:_BCRYPT_MAX_BYTES], _DUMMY_HASH)
        return False
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        # A password this long can never have been stored, so it can never match.
        return False
    return bcrypt.checkpw(raw, password_hash.encode("ascii"))


@dataclass(frozen=True)
class Identity:
    """The normalized claim set — identical for local accounts and for OIDC
    relying-party logins (ADR-0011).

    ``idp_issuer`` / ``idp_subject`` are present ONLY for a federated
    session, and they exist for the certification guardrail: under SSO the
    audit trail must record who signed with at least the fidelity it had
    before, which means the IdP subject AND the Headway username, never just
    "an SSO user". A signature whose signer cannot be resolved years later —
    after the person has left, the username has been reused, the tenant has
    been migrated — is not a signature.

    ``jti`` is this session's identifier. A fresh one is minted on every
    login, which is what makes session fixation impossible: nothing the
    browser held before signing in carries any authority afterwards.
    """

    sub: str  # auth.users.user_id (the Headway account, for both auth paths)
    username: str
    role: str
    jti: str | None = None
    idp_issuer: str | None = None
    idp_subject: str | None = None

    @property
    def is_federated(self) -> bool:
        return self.idp_subject is not None

    def audit_actor_detail(self) -> dict:
        """The signer/actor attribution to fold into an audit ``detail``.

        Local sessions add nothing (the actor column already names them).
        Federated sessions add BOTH IdP identifiers, so the trail answers
        "who signed" without a lookup in a directory Headway does not own.
        """
        if not self.is_federated:
            return {"authenticated_via": "local"}
        return {
            "authenticated_via": "oidc",
            "idp_issuer": self.idp_issuer,
            "idp_subject": self.idp_subject,
        }


def new_session_id() -> str:
    """A fresh session identifier (JWT ``jti``). Minted per login, never reused."""
    return secrets.token_urlsafe(24)


def issue_token(
    *,
    secret: str,
    sub: str,
    username: str,
    role: str,
    ttl_seconds: int,
    jti: str | None = None,
    idp_issuer: str | None = None,
    idp_subject: str | None = None,
) -> str:
    """Mint a session token.

    A NEW ``jti`` is generated whenever one is not supplied, so every call to
    this function is a new session — there is no code path that re-issues a
    caller's existing session identifier after authentication.
    """
    now = dt.datetime.now(dt.timezone.utc)
    claims = {
        "sub": sub,
        "username": username,
        "role": role,
        "jti": jti or new_session_id(),
        "iat": now,
        "exp": now + dt.timedelta(seconds=ttl_seconds),
    }
    if idp_subject is not None:
        claims["idp_issuer"] = idp_issuer
        claims["idp_subject"] = idp_subject
    return jwt.encode(claims, secret, algorithm=ALGORITHM)


def decode_token(token: str, *, secret: str) -> Identity:
    """Decode and verify a session token; raises HTTPException(401) loudly."""
    try:
        claims = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Your session has expired. Please sign in again.",
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Your session could not be verified. Please sign in again.",
        )
    role = claims.get("role")
    if (
        not claims.get("sub")
        or not claims.get("username")
        or role not in VALID_ROLES
    ):
        raise HTTPException(
            status_code=401,
            detail="Your session is missing required account information. "
            "Please sign in again.",
        )
    return Identity(
        sub=claims["sub"],
        username=claims["username"],
        role=role,
        jti=claims.get("jti"),
        idp_issuer=claims.get("idp_issuer"),
        idp_subject=claims.get("idp_subject"),
    )


def get_current_identity(request: Request) -> Identity:
    """FastAPI dependency: the verified caller. 401 when absent/invalid.

    THE READ-ONLY-ROLE CHOKE POINT. Every authenticated endpoint in this API
    resolves its caller here, so this is the one place that can refuse a
    write for a read-only role and be certain nothing routes around it. An
    ``auditor`` may issue GET/HEAD/OPTIONS and nothing else — including the
    two read-SHAPED POSTs this API has (``/sandbox/preview``, which computes
    a what-if, and ``/raw/records/{id}/verify``, which raises a data-quality
    finding on a mismatch). Both are outside "reads everything, changes
    nothing", and refusing by method with no allow-list is deny-by-default
    that a future endpoint cannot fall outside of.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="You are not signed in. Please sign in to use Headway.",
        )
    settings = request.app.state.settings
    identity = decode_token(token.strip(), secret=settings.session_secret)
    if (
        identity.role in _NO_WRITE_ROLES
        and request.method.upper() not in _SAFE_METHODS
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                f"Your account is signed in as an {identity.role}, which can "
                f"read everything in Headway and change nothing in it. This "
                f"action would change something, so Headway refuses it. That "
                f"is deliberate: an auditor's account cannot alter what the "
                f"auditor is reviewing. If your work also needs to change "
                f"data, ask your Headway administrator for a separate account."
            ),
        )
    return identity


# ---------------------------------------------------------------------------
# Login endpoint (local accounts)
# ---------------------------------------------------------------------------

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str


_SELECT_USER = (
    "SELECT user_id, username, password_hash, role, is_active "
    "FROM auth.users WHERE username = %s"
)

_BAD_CREDENTIALS = HTTPException(
    status_code=401,
    detail="That username and password combination was not recognized.",
)


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db=Depends(get_db)) -> LoginResponse:
    """Sign in with a local Headway account.

    THIS PATH NEVER STOPS WORKING. It does not consult the OIDC
    configuration, so a misconfigured provider, an unreachable IdP, or an
    installation with no internet at all leaves it untouched — the
    break-glass guarantee of handoff 0046.
    """
    settings = request.app.state.settings
    row = db.execute(_SELECT_USER, (body.username,)).fetchone()
    if row is None:
        # Same message as a wrong password, and the same cost. The message was
        # always generic; without this the clock was not, and a username that
        # exists locally could be told from one that does not by timing a
        # single request. Nothing is audited here on purpose: there is no
        # account to attribute it to, and an unauthenticated caller must not
        # be able to write rows into audit.events by guessing names.
        verify_password(body.password, None)
        raise _BAD_CREDENTIALS
    user_id, username, password_hash, role, is_active = row
    if not verify_password(body.password, password_hash):
        # Covers a wrong password AND a federated account with no password
        # (password_hash IS NULL, migration 0043) — one generic refusal, so
        # the login surface never reveals how an account signs in.
        with db.transaction():
            write_event(
                db,
                actor=username,
                action="login_failed",
                subject_kind="auth.users",
                subject_id=str(user_id),
                detail={
                    "reason": (
                        "no local password (federated account)"
                        if password_hash is None
                        else "wrong password"
                    )
                },
            )
        raise _BAD_CREDENTIALS
    if not is_active:
        # Deactivated accounts get the SAME generic 401 as a wrong password
        # (handoff 0025, design point 1): whether an account exists, and in
        # what state, is never revealed by the login surface. The audit
        # trail keeps the real reason.
        with db.transaction():
            write_event(
                db,
                actor=username,
                action="login_denied",
                subject_kind="auth.users",
                subject_id=str(user_id),
                detail={"reason": "account deactivated"},
            )
        raise _BAD_CREDENTIALS
    # A NEW session identifier for a NEW session — session fixation has no
    # purchase here because no identifier survives the login.
    session_id = new_session_id()
    token = issue_token(
        secret=settings.session_secret,
        sub=str(user_id),
        username=username,
        role=role,
        ttl_seconds=settings.token_ttl_seconds,
        jti=session_id,
    )
    with db.transaction():
        write_event(
            db,
            actor=username,
            action="login",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={"role": role, "authenticated_via": "local"},
        )
    return LoginResponse(
        access_token=token,
        expires_in=settings.token_ttl_seconds,
        username=username,
        role=role,
    )
