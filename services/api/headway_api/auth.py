"""Local-account authentication (ADR-0011).

This slice ships LOCAL ACCOUNTS only. The native OIDC relying party
(authorization-code + PKCE, per ADR-0011) is the NEXT increment and slots in
behind the exact same normalized claim set this module produces:

    {sub, username, role}

Everything downstream (authz.py, the routers, audit actor attribution)
consumes only that claim set, so adding the OIDC RP is a new token *source*,
not a rework of authorization.

NOTE — auth.users is NOT part of handoff 0001's schema contract. It is added
by migration ``db/migrations/0009_auth_users.sql`` with an explicit
``## Response — backend-engineer`` section appended to that handoff (schema
handoffs require explicit responses, not silent extension).

Password hashing: **bcrypt** (the ``bcrypt`` PyPI package, Apache-2.0 license
— OSI-approved permissive, satisfies ADR-0001). Session tokens: PyJWT (MIT),
HS256, secret from the HEADWAY_SESSION_SECRET environment variable, short
expiry (30 minutes by default).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .audit import write_event
from .db import get_db

ALGORITHM = "HS256"
DEFAULT_TOKEN_TTL_SECONDS = 30 * 60

VALID_ROLES = ("viewer", "data_steward", "report_preparer", "certifying_official")

# bcrypt only reads the first 72 bytes of a password; longer input must be
# rejected loudly, never silently truncated.
_BCRYPT_MAX_BYTES = 72


class PasswordTooLong(ValueError):
    """Raised instead of silently truncating a >72-byte password."""


def hash_password(password: str) -> str:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise PasswordTooLong(
            "Passwords longer than 72 bytes are not supported. Please choose "
            "a shorter password."
        )
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        # A password this long can never have been stored, so it can never match.
        return False
    return bcrypt.checkpw(raw, password_hash.encode("ascii"))


@dataclass(frozen=True)
class Identity:
    """The normalized claim set — identical for local accounts and, in the
    next increment, for OIDC RP logins (ADR-0011)."""

    sub: str  # auth.users.user_id (or, later, the OIDC subject)
    username: str
    role: str


def issue_token(
    *, secret: str, sub: str, username: str, role: str, ttl_seconds: int
) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    claims = {
        "sub": sub,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + dt.timedelta(seconds=ttl_seconds),
    }
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
    return Identity(sub=claims["sub"], username=claims["username"], role=role)


def get_current_identity(request: Request) -> Identity:
    """FastAPI dependency: the verified caller. 401 when absent/invalid."""
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail="You are not signed in. Please sign in to use Headway.",
        )
    settings = request.app.state.settings
    return decode_token(token.strip(), secret=settings.session_secret)


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
    "SELECT user_id, username, password_hash, role, disabled "
    "FROM auth.users WHERE username = %s"
)

_BAD_CREDENTIALS = HTTPException(
    status_code=401,
    detail="That username and password combination was not recognized.",
)


@router.post("/auth/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db=Depends(get_db)) -> LoginResponse:
    settings = request.app.state.settings
    row = db.execute(_SELECT_USER, (body.username,)).fetchone()
    if row is None:
        # Same message as a wrong password: do not reveal which usernames exist.
        raise _BAD_CREDENTIALS
    user_id, username, password_hash, role, disabled = row
    if not verify_password(body.password, password_hash):
        with db.transaction():
            write_event(
                db,
                actor=username,
                action="login_failed",
                subject_kind="auth.users",
                subject_id=str(user_id),
                detail={"reason": "wrong password"},
            )
        raise _BAD_CREDENTIALS
    if disabled:
        with db.transaction():
            write_event(
                db,
                actor=username,
                action="login_denied",
                subject_kind="auth.users",
                subject_id=str(user_id),
                detail={"reason": "account disabled"},
            )
        raise HTTPException(
            status_code=403,
            detail="This account has been disabled. Please contact your "
            "Headway administrator.",
        )
    token = issue_token(
        secret=settings.session_secret,
        sub=str(user_id),
        username=username,
        role=role,
        ttl_seconds=settings.token_ttl_seconds,
    )
    with db.transaction():
        write_event(
            db,
            actor=username,
            action="login",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={"role": role},
        )
    return LoginResponse(
        access_token=token,
        expires_in=settings.token_ttl_seconds,
        username=username,
        role=role,
    )
