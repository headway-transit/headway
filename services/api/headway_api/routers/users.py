"""User management v0 (handoff 0025, design point 1).

Until this wave, user management existed ONLY as the installer's one-time
admin creation. The first real agency UAT (2026-07-28, partner agency ITS
manager) asked for the obvious: an admin page to manage users. This router
is its API — local accounts only (ADR-0011; the native OIDC relying party
remains the recorded next identity increment).

Rules, all enforced here and pinned by test:

- Every endpoint is certifying_official-only (the v0 admin role, the
  machine-keys precedent) and every state change is audited (append-only,
  same transaction as the change).
- Password rules are the INSTALLER'S rules (install/install.sh): at least 8
  characters, at most 72 bytes (bcrypt's limit — enforced loudly by
  auth.hash_password, never silent truncation). Username rules likewise:
  letters, numbers, dots, hyphens, underscores.
- GET /users never serves a password hash. Not truncated, not masked —
  absent.
- LOCKOUT FAIL-SAFE: deactivating or demoting the LAST active certifying
  official is refused (409, plain language). An agency must never be able
  to lock itself out of certification and user management from the UI.
- Deactivation refuses NEW sign-ins immediately (auth.py — with the same
  generic 401 as a wrong password, never an enumeration oracle). A session
  the user already holds expires on its own within the token lifetime;
  the deactivate response says so in plain language rather than implying
  an instant cutoff.
- Passwords set here are admin-performed resets. Self-service reset needs
  email infrastructure Headway does not have yet (recorded follow-up,
  handoff 0025 honest scope).
"""

from __future__ import annotations

import datetime as dt
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..audit import write_event
from ..auth import Identity, PasswordTooLong, VALID_ROLES, hash_password
from ..authz import ROLE_LABELS, require_certifying_official
from ..db import get_db

router = APIRouter(tags=["users"])

#: The installer's username rule (install/install.sh), verbatim.
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")

#: The installer's minimum password length (characters).
MIN_PASSWORD_CHARS = 8


class UserRecord(BaseModel):
    """One account as the admin surface sees it. NO password material —
    not hashed, not masked; the field does not exist here."""

    username: str
    role: str
    is_active: bool
    created_at: dt.datetime


class CreateUserRequest(BaseModel):
    username: str
    role: str
    password: str


class CreateUserResponse(UserRecord):
    audit_event_id: int


class ResetPasswordRequest(BaseModel):
    password: str


class ResetPasswordResponse(BaseModel):
    username: str
    audit_event_id: int


class ActiveChangeResponse(BaseModel):
    username: str
    is_active: bool
    #: Plain-language honesty about session lifetime on deactivation.
    note: str | None = None
    audit_event_id: int


class ChangeRoleRequest(BaseModel):
    role: str


class ChangeRoleResponse(BaseModel):
    username: str
    role: str
    #: Plain-language honesty: a session the user already holds keeps its
    #: old role until the token expires.
    note: str | None = None
    audit_event_id: int


_SELECT_USERS = (
    "SELECT username, role, is_active, created_at FROM auth.users "
    "ORDER BY created_at, username"
)

_SELECT_ONE_USER = (
    "SELECT user_id, role, is_active, created_at FROM auth.users "
    "WHERE username = %s"
)

# ON CONFLICT DO NOTHING + RETURNING: no row back means the username exists —
# race-free duplicate detection without leaking a constraint error.
_INSERT_USER = (
    "INSERT INTO auth.users (username, password_hash, role) "
    "VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING "
    "RETURNING user_id, created_at"
)

_UPDATE_PASSWORD = (
    "UPDATE auth.users SET password_hash = %s WHERE username = %s "
    "RETURNING user_id"
)

_UPDATE_ACTIVE = (
    "UPDATE auth.users SET is_active = %s WHERE username = %s "
    "RETURNING user_id"
)

_UPDATE_ROLE = (
    "UPDATE auth.users SET role = %s WHERE username = %s RETURNING user_id"
)

#: The lockout fail-safe's counting query: active certifying officials
#: OTHER than the named account.
_COUNT_OTHER_ACTIVE_ADMINS = (
    "SELECT count(*) FROM auth.users "
    "WHERE role = 'certifying_official' AND is_active AND username <> %s"
)


def _unknown_user_404(username: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=(
            f"No account named '{username}' exists on this Headway "
            f"instance. GET /users lists the accounts that do."
        ),
    )


def _validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(
            status_code=422,
            detail=(
                "Usernames can use only letters, numbers, dots, hyphens or "
                "underscores, with no spaces — the same rule the installer "
                "applies. Please choose a different username."
            ),
        )


def _validate_role(role: str) -> None:
    if role not in VALID_ROLES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{role}' is not a role Headway knows. The roles are: "
                f"viewer, data_steward, report_preparer, "
                f"certifying_official, and auditor (which can read "
                f"everything and change nothing)."
            ),
        )


def _hash_valid_password(password: str) -> str:
    """Installer rules: >= 8 characters, <= 72 bytes (bcrypt's limit,
    refused loudly — never silently truncated)."""
    if len(password) < MIN_PASSWORD_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                "That password is too short. Please use at least 8 "
                "characters — the same rule the installer applies."
            ),
        )
    try:
        return hash_password(password)
    except PasswordTooLong as exc:
        raise HTTPException(status_code=422, detail=str(exc))


def _lockout_409(username: str, action_clause: str) -> HTTPException:
    """The lockout fail-safe's refusal, in plain language. The click-through
    UI surfaces this message verbatim at the refused control."""
    return HTTPException(
        status_code=409,
        detail=(
            f"'{username}' is the last active certifying official on this "
            f"Headway instance. {action_clause} would leave no one able to "
            f"certify reports or manage users and branding, so Headway "
            f"refuses it. Make another account a certifying official "
            f"first, then try again."
        ),
    )


def _guard_last_active_admin(
    db, *, username: str, role: str, is_active: bool, action_clause: str
) -> None:
    """Refuse removing the last active certifying official's powers."""
    if role != "certifying_official" or not is_active:
        return  # the account holds no admin power to lose
    others = db.execute(_COUNT_OTHER_ACTIVE_ADMINS, (username,)).fetchone()[0]
    if others == 0:
        raise _lockout_409(username, action_clause)


@router.get("/users", response_model=list[UserRecord])
def list_users(
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> list[UserRecord]:
    """Every account on this instance — username, role, active state,
    created date. Certifying official only. Password hashes are never
    served, by any endpoint, ever."""
    rows = db.execute(_SELECT_USERS).fetchall()
    return [
        UserRecord(username=r[0], role=r[1], is_active=r[2], created_at=r[3])
        for r in rows
    ]


@router.post("/users", response_model=CreateUserResponse, status_code=201)
def create_user(
    body: CreateUserRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> CreateUserResponse:
    """Create a local account (certifying official only; audited). The
    password is bcrypt-hashed by the same helper the login path verifies
    against; the plaintext exists only inside this request."""
    _validate_username(body.username)
    _validate_role(body.role)
    password_hash = _hash_valid_password(body.password)

    with db.transaction():
        created = db.execute(
            _INSERT_USER, (body.username, password_hash, body.role)
        ).fetchone()
        if created is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"An account named '{body.username}' already exists on "
                    f"this Headway instance. Usernames must be unique — "
                    f"pick a different one, or manage the existing account "
                    f"instead."
                ),
            )
        user_id, created_at = created
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="user_created",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={"username": body.username, "role": body.role},
        )
    return CreateUserResponse(
        username=body.username,
        role=body.role,
        is_active=True,
        created_at=created_at,
        audit_event_id=audit_event_id,
    )


@router.post(
    "/users/{username}/reset-password", response_model=ResetPasswordResponse
)
def reset_password(
    username: str,
    body: ResetPasswordRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> ResetPasswordResponse:
    """Set a new password for an account (certifying official only;
    audited — the audit record never carries the password, only who reset
    whose). Admin-performed by design: self-service reset needs email
    infrastructure Headway does not have yet (recorded follow-up)."""
    row = db.execute(_SELECT_ONE_USER, (username,)).fetchone()
    if row is None:
        raise _unknown_user_404(username)
    user_id = row[0]
    password_hash = _hash_valid_password(body.password)

    with db.transaction():
        db.execute(_UPDATE_PASSWORD, (password_hash, username)).fetchone()
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="user_password_reset",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={"username": username},
        )
    return ResetPasswordResponse(
        username=username, audit_event_id=audit_event_id
    )


@router.post("/users/{username}/deactivate", response_model=ActiveChangeResponse)
def deactivate_user(
    username: str,
    request: Request,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> ActiveChangeResponse:
    """Deactivate an account (certifying official only; audited). New
    sign-ins are refused immediately — with the same generic message as a
    wrong password, so account state never leaks. LOCKOUT FAIL-SAFE: the
    last active certifying official cannot be deactivated (409)."""
    row = db.execute(_SELECT_ONE_USER, (username,)).fetchone()
    if row is None:
        raise _unknown_user_404(username)
    user_id, role, is_active, _created = row
    if not is_active:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The account '{username}' is already deactivated, so "
                f"there is nothing to change."
            ),
        )
    _guard_last_active_admin(
        db,
        username=username,
        role=role,
        is_active=is_active,
        action_clause="Deactivating this account",
    )

    ttl_minutes = max(
        1, request.app.state.settings.token_ttl_seconds // 60
    )
    with db.transaction():
        db.execute(_UPDATE_ACTIVE, (False, username)).fetchone()
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="user_deactivated",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={"username": username},
        )
    return ActiveChangeResponse(
        username=username,
        is_active=False,
        note=(
            f"New sign-ins for '{username}' are refused from now on. If "
            f"this person is signed in right now, that session ends on its "
            f"own within {ttl_minutes} minutes (when their current session "
            f"token expires)."
        ),
        audit_event_id=audit_event_id,
    )


@router.post("/users/{username}/reactivate", response_model=ActiveChangeResponse)
def reactivate_user(
    username: str,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> ActiveChangeResponse:
    """Reactivate a deactivated account (certifying official only;
    audited). The account signs in with the password it already had."""
    row = db.execute(_SELECT_ONE_USER, (username,)).fetchone()
    if row is None:
        raise _unknown_user_404(username)
    user_id, _role, is_active, _created = row
    if is_active:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The account '{username}' is already active, so there is "
                f"nothing to change."
            ),
        )

    with db.transaction():
        db.execute(_UPDATE_ACTIVE, (True, username)).fetchone()
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="user_reactivated",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={"username": username},
        )
    return ActiveChangeResponse(
        username=username, is_active=True, audit_event_id=audit_event_id
    )


@router.post("/users/{username}/role", response_model=ChangeRoleResponse)
def change_role(
    username: str,
    request: Request,
    body: ChangeRoleRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> ChangeRoleResponse:
    """Change an account's role (certifying official only; audited with
    the old AND new role). LOCKOUT FAIL-SAFE: the last active certifying
    official cannot be demoted (409) — same guard as deactivation."""
    _validate_role(body.role)
    row = db.execute(_SELECT_ONE_USER, (username,)).fetchone()
    if row is None:
        raise _unknown_user_404(username)
    user_id, old_role, is_active, _created = row
    if body.role == old_role:
        raise HTTPException(
            status_code=409,
            detail=(
                f"The account '{username}' already has the "
                f"{ROLE_LABELS[old_role]} role, so there is nothing to "
                f"change."
            ),
        )
    if body.role != "certifying_official":
        _guard_last_active_admin(
            db,
            username=username,
            role=old_role,
            is_active=is_active,
            action_clause=(
                f"Changing this account to the {ROLE_LABELS[body.role]} role"
            ),
        )

    with db.transaction():
        db.execute(_UPDATE_ROLE, (body.role, username)).fetchone()
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="user_role_changed",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={
                "username": username,
                "old_role": old_role,
                "new_role": body.role,
            },
        )
    ttl_minutes = max(1, request.app.state.settings.token_ttl_seconds // 60)
    return ChangeRoleResponse(
        username=username,
        role=body.role,
        note=(
            f"'{username}' is a {ROLE_LABELS[body.role]} from their next "
            f"sign-in. If this person is signed in right now, their current "
            f"session keeps the {ROLE_LABELS[old_role]} role for up to "
            f"{ttl_minutes} minutes (until their session token expires)."
        ),
        audit_event_id=audit_event_id,
    )
