"""Single sign-on: the endpoints (ADR-0011, handoff 0046).

Three surfaces live here, with very different audiences:

1. **The sign-in path** — ``/auth/oidc/status``, ``/auth/oidc/start``,
   ``/auth/oidc/callback``. Unauthenticated by necessity (nobody is signed in
   yet), so every one of them is written as if it is being probed, because it
   is. One generic failure message; the specific reason goes to the audit
   trail; failure audit writes are coalesced so an unauthenticated actor
   cannot amplify a flood of bad requests into unbounded ``audit.events``
   INSERTs (the ``machine_auth.FailureAuditThrottle`` pattern, adversarial
   finding F1).

2. **The configuration surface** — ``/auth/oidc/config`` and
   ``/auth/oidc/mappings``, certifying-official only, every change audited
   with what it was and what it became. The client secret is encrypted at
   rest, written once, and never served back by any endpoint here.

3. **The test action** — ``POST /auth/oidc/config/test``. It exists because
   the first OIDC configuration attempt is always wrong, and the difference
   between a working integration and a support call is whether the person
   configuring it finds out now or on Monday morning.

THE ROLE RULES, IN ONE PLACE
----------------------------
* An **unmapped claim grants NOTHING**. Not viewer, not read-only. A user
  whose groups match no mapping is refused and NO ACCOUNT IS CREATED.
* Several matches resolve to the **least privileged** of them, and the audit
  record names all of them, so an accidental double-grant is visible instead
  of silently taking the higher one.
* The IdP can neither **grant nor revoke ``certifying_official``**. Granting
  is refused at three layers (the DB CHECK in migration 0043, the mapping
  API, and this login path, which re-checks rather than trusting the row it
  read). Revoking is refused because it is the same control by the other
  hand: a directory administrator removing a group membership must not be
  able to leave an agency with nobody who can certify — the migration-0032
  lockout fail-safe, applied to the federated path.
"""

from __future__ import annotations

import datetime as dt
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import oidc as oidc_lib
from .. import secrets_at_rest
from ..audit import write_event
from ..auth import Identity, issue_token, new_session_id
from ..authz import ROLE_LABELS, require_certifying_official, role_label
from ..db import get_db
from ..machine_auth import enforce_rate_limit

router = APIRouter(tags=["sso"])

#: Roles an IdP claim may map to. ``certifying_official`` is absent on
#: purpose — see the module docstring and migration 0043.
IDP_GRANTABLE_ROLES = ("viewer", "auditor", "data_steward", "report_preparer")

#: Tie-break order when a user's claims match several mappings: LEAST
#: authority first. ``viewer`` reads the operational surface; ``auditor``
#: reads that plus the audit trail and still writes nothing; the two
#: stewardship roles can change data. Taking the least is the safe answer to
#: a configuration that says two things at once, and the audit record names
#: every mapping that matched so the ambiguity is visible.
_MAPPING_PRECEDENCE = ("viewer", "auditor", "data_steward", "report_preparer")

#: Set HEADWAY_OIDC_DISABLED=1 to force single sign-on off without touching
#: the database. This is the break-glass switch: it works when the database
#: is reachable and when the configuration in it is wrong, and it needs
#: nothing but a restart. Local accounts are never affected either way.
ENV_DISABLED = "HEADWAY_OIDC_DISABLED"


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

_SELECT_PROVIDER = (
    "SELECT discovery_url, client_id, client_secret_encrypted, redirect_uri, "
    "groups_claim, username_claim, clock_skew_seconds, ca_bundle_path, "
    "button_label, is_enabled, updated_by, updated_at "
    "FROM auth.oidc_provider WHERE singleton"
)

_UPSERT_PROVIDER = (
    "INSERT INTO auth.oidc_provider (singleton, discovery_url, client_id, "
    "client_secret_encrypted, redirect_uri, groups_claim, username_claim, "
    "clock_skew_seconds, ca_bundle_path, button_label, is_enabled, "
    "updated_by, updated_at) "
    "VALUES (true, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) "
    "ON CONFLICT (singleton) DO UPDATE SET discovery_url = EXCLUDED.discovery_url, "
    "client_id = EXCLUDED.client_id, "
    "client_secret_encrypted = EXCLUDED.client_secret_encrypted, "
    "redirect_uri = EXCLUDED.redirect_uri, "
    "groups_claim = EXCLUDED.groups_claim, "
    "username_claim = EXCLUDED.username_claim, "
    "clock_skew_seconds = EXCLUDED.clock_skew_seconds, "
    "ca_bundle_path = EXCLUDED.ca_bundle_path, "
    "button_label = EXCLUDED.button_label, "
    "is_enabled = EXCLUDED.is_enabled, "
    "updated_by = EXCLUDED.updated_by, updated_at = now() "
    "RETURNING updated_at"
)

_SELECT_MAPPINGS = (
    "SELECT mapping_id, claim_value, headway_role, note, created_by, "
    "created_at FROM auth.oidc_role_mappings ORDER BY claim_value"
)

_INSERT_MAPPING = (
    "INSERT INTO auth.oidc_role_mappings (claim_value, headway_role, note, "
    "created_by) VALUES (%s, %s, %s, %s) "
    "ON CONFLICT (claim_value) DO NOTHING RETURNING mapping_id, created_at"
)

_DELETE_MAPPING = (
    "DELETE FROM auth.oidc_role_mappings WHERE mapping_id = %s "
    "RETURNING claim_value, headway_role"
)

_INSERT_LOGIN_STATE = (
    "INSERT INTO auth.oidc_login_states (state, nonce, code_verifier, "
    "browser_binding, redirect_uri, expires_at) VALUES (%s, %s, %s, %s, %s, %s)"
)

#: SINGLE USE, enforced by the database rather than by a read-then-write in
#: Python: two concurrent callbacks replaying one state cannot both match
#: ``consumed_at IS NULL``, so exactly one wins and the other is refused.
_CONSUME_LOGIN_STATE = (
    "UPDATE auth.oidc_login_states SET consumed_at = now() "
    "WHERE state = %s AND consumed_at IS NULL AND expires_at > now() "
    "RETURNING nonce, code_verifier, browser_binding, redirect_uri"
)

_SWEEP_LOGIN_STATES = (
    "DELETE FROM auth.oidc_login_states WHERE expires_at < now()"
)

_SELECT_USER_BY_IDP = (
    "SELECT user_id, username, role, is_active FROM auth.users "
    "WHERE idp_issuer = %s AND idp_subject = %s"
)

_SELECT_USER_BY_USERNAME = (
    "SELECT user_id, role, is_active, auth_source FROM auth.users "
    "WHERE username = %s"
)

_INSERT_FEDERATED_USER = (
    "INSERT INTO auth.users (username, role, auth_source, idp_issuer, "
    "idp_subject) VALUES (%s, %s, 'oidc', %s, %s) "
    "ON CONFLICT (username) DO NOTHING RETURNING user_id"
)

_UPDATE_FEDERATED_ROLE = (
    "UPDATE auth.users SET role = %s WHERE user_id = %s RETURNING username"
)

_TOUCH_LAST_LOGIN = (
    "UPDATE auth.users SET last_login_at = now() WHERE user_id = %s"
)

#: The migration-0032 lockout counting query, reused verbatim from
#: routers/users.py so the federated path and the admin path agree on what
#: "the last active certifying official" means.
_COUNT_OTHER_ACTIVE_ADMINS = (
    "SELECT count(*) FROM auth.users "
    "WHERE role = 'certifying_official' AND is_active AND username <> %s"
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class SsoStatus(BaseModel):
    """What the sign-in screen may know before anyone is signed in.

    Deliberately tiny: whether the button should appear and what it should
    say. No discovery URL, no client id, no issuer — an unauthenticated
    caller learns nothing about the agency's identity provider that it could
    not learn by clicking the button.
    """

    enabled: bool
    button_label: str


class StartLoginResponse(BaseModel):
    authorization_url: str
    state: str
    #: Kept in the browser for the length of the redirect and sent back at
    #: the callback. This is what binds the sign-in to THIS browser in a
    #: bearer-token app that has no cookie to bind to.
    browser_token: str


class CallbackRequest(BaseModel):
    code: str
    state: str
    browser_token: str


class CallbackResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    username: str
    role: str


class RoleMapping(BaseModel):
    mapping_id: str
    claim_value: str
    headway_role: str
    role_label: str
    note: str | None = None
    created_by: str
    created_at: dt.datetime


class CreateMappingRequest(BaseModel):
    claim_value: str = Field(min_length=1)
    headway_role: str
    note: str | None = None


class CreateMappingResponse(RoleMapping):
    audit_event_id: int


class DeleteMappingResponse(BaseModel):
    claim_value: str
    headway_role: str
    audit_event_id: int


class ProviderConfigResponse(BaseModel):
    """The configuration as an admin sees it.

    ``client_secret_set`` is a boolean and there is no field that could ever
    carry the secret. Show-once means show once.
    """

    configured: bool
    discovery_url: str | None = None
    client_id: str | None = None
    client_secret_set: bool = False
    redirect_uri: str | None = None
    groups_claim: str = "groups"
    username_claim: str = "preferred_username"
    clock_skew_seconds: int = 120
    ca_bundle_path: str | None = None
    button_label: str = "Sign in with single sign-on"
    is_enabled: bool = False
    updated_by: str | None = None
    updated_at: dt.datetime | None = None
    #: True when the installation has an at-rest encryption key. False means
    #: a secret cannot be saved at all, and the screen says so BEFORE the
    #: admin types one.
    secret_storage_available: bool = True
    #: Set when the environment kill switch is on, so the screen can explain
    #: why sign-in is off despite the configuration looking correct.
    disabled_by_environment: bool = False


class UpdateProviderRequest(BaseModel):
    discovery_url: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    #: Omit (null) to KEEP the stored secret. Empty string clears it.
    client_secret: str | None = None
    redirect_uri: str = Field(min_length=1)
    groups_claim: str = Field(default="groups", min_length=1)
    username_claim: str = Field(default="preferred_username", min_length=1)
    clock_skew_seconds: int = Field(default=120, ge=0, le=600)
    ca_bundle_path: str | None = None
    button_label: str = Field(default="Sign in with single sign-on", min_length=1)
    is_enabled: bool = False


class UpdateProviderResponse(ProviderConfigResponse):
    audit_event_id: int


class TestStep(BaseModel):
    step: str
    ok: bool
    message: str


class TestConfigResponse(BaseModel):
    ok: bool
    steps: list[TestStep]
    audit_event_id: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _limit_sso(request: Request) -> None:
    """Token-bucket the unauthenticated sign-in surface, per client IP.

    Absent in tests that build the app without ``sso_rate_limiter``; those
    exercise the sign-in logic, not the limiter, and must not fail because a
    fixture predates it.
    """
    limiter = getattr(request.app.state, "sso_rate_limiter", None)
    if limiter is None:
        return
    enforce_rate_limit(limiter, request.client.host if request.client else "unknown")


def _throttle_gate(request: Request, reason: str) -> Optional[int]:
    """Failure-audit coalescing for the unauthenticated sign-in surface.

    Identical in shape and intent to ``machine_auth._failure_audit_gate``:
    the FIRST failure per (client IP, reason) inside the window is recorded
    so probing stays visible, and further identical failures are counted and
    folded into the next recorded event. Without this, an attacker replaying
    forged callbacks writes one audit row per request at no cost to
    themselves, which is a write-amplification denial of service against the
    database that the audit trail lives in.
    """
    throttle = getattr(request.app.state, "login_audit_throttle", None)
    if throttle is None:
        return 0
    bucket = request.client.host if request.client else "unknown"
    return throttle.on_failure(bucket, reason)


def _audit_login_failure(
    db, request: Request, *, reason: str, actor: str = "sso:anonymous",
    detail: Optional[dict] = None,
) -> None:
    suppressed = _throttle_gate(request, reason)
    if suppressed is None:
        return
    with db.transaction():
        write_event(
            db,
            actor=actor,
            action="sso_login_failed",
            subject_kind="auth.oidc_provider",
            subject_id=None,
            detail={
                "reason": reason,
                "path": request.url.path,
                **(detail or {}),
                **({"suppressed_since_last": suppressed} if suppressed else {}),
            },
        )


def _metadata(request: Request) -> oidc_lib.ProviderMetadata:
    """The process-wide discovery/JWKS cache. Tests inject a factory."""
    cache = getattr(request.app.state, "oidc_metadata", None)
    if cache is None:
        cache = oidc_lib.ProviderMetadata()
        request.app.state.oidc_metadata = cache
    return cache


def _env_disabled(request: Request) -> bool:
    import os

    override = getattr(request.app.state, "oidc_disabled", None)
    if override is not None:
        return bool(override)
    return os.environ.get(ENV_DISABLED, "").strip().lower() in ("1", "true", "yes")


def _load_provider_row(db):
    return db.execute(_SELECT_PROVIDER).fetchone()


def _config_from_row(request: Request, row, *, decrypt_secret: bool) -> oidc_lib.ProviderConfig:
    """Build the runtime config, decrypting the client secret only when a
    code exchange is about to need it. The plaintext lives inside one request
    and is never stored on app state."""
    (
        discovery_url, client_id, secret_encrypted, redirect_uri, groups_claim,
        username_claim, clock_skew, ca_bundle, button_label, is_enabled,
        _updated_by, _updated_at,
    ) = row
    client_secret = None
    if decrypt_secret and secret_encrypted:
        client_secret = secrets_at_rest.decrypt(
            secret_encrypted,
            associated_data=secrets_at_rest.AD_OIDC_CLIENT_SECRET,
            key=secrets_at_rest.get_key(request.app),
        )
    return oidc_lib.ProviderConfig(
        discovery_url=discovery_url,
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        groups_claim=groups_claim,
        username_claim=username_claim,
        clock_skew_seconds=clock_skew,
        ca_bundle_path=ca_bundle,
        button_label=button_label,
        is_enabled=is_enabled,
    )


def resolve_role(groups: tuple[str, ...], mappings: list[tuple[str, str]]) -> tuple[str | None, list[str]]:
    """Map claim values onto a Headway role. Returns (role, matched_claims).

    DENY-BY-DEFAULT: no match returns ``None``, and the caller refuses the
    sign-in and creates nothing. There is no fallback role, deliberately —
    a fallback is how an IdP group that nobody audited becomes access that
    nobody granted.

    ``certifying_official`` is filtered out here even if a row somehow holds
    it (hand-edited SQL, a restored backup from a future version): this path
    re-checks rather than trusting what it read.
    """
    by_claim = {claim: role for claim, role in mappings}
    matched = [g for g in groups if g in by_claim]
    roles = {
        by_claim[claim]
        for claim in matched
        if by_claim[claim] in IDP_GRANTABLE_ROLES
    }
    if not roles:
        return None, matched
    for candidate in _MAPPING_PRECEDENCE:
        if candidate in roles:
            return candidate, matched
    return None, matched


# ---------------------------------------------------------------------------
# The sign-in path
# ---------------------------------------------------------------------------


@router.get("/auth/oidc/status", response_model=SsoStatus)
def sso_status(request: Request, db=Depends(get_db)) -> SsoStatus:
    """Should the sign-in screen offer a single-sign-on button, and what does
    it say? Unauthenticated by necessity, and tells an anonymous caller
    nothing beyond that."""
    row = _load_provider_row(db)
    if row is None or _env_disabled(request):
        return SsoStatus(enabled=False, button_label="")
    is_enabled, button_label = row[9], row[8]
    return SsoStatus(
        enabled=bool(is_enabled),
        button_label=button_label if is_enabled else "",
    )


@router.post("/auth/oidc/start", response_model=StartLoginResponse)
def start_login(request: Request, db=Depends(get_db)) -> StartLoginResponse:
    """Begin an authorization-code + PKCE sign-in.

    Generates ``state``, ``nonce``, a PKCE verifier and a browser binding
    token, stores everything but the browser token server-side, and hands
    back the provider URL to send the browser to.

    RATE LIMITED because it is unauthenticated AND expensive: it can open an
    outbound connection to the identity provider and it INSERTs a row. Every
    endpoint in this API is synchronous, so a request waiting on an
    unreachable provider is holding a worker thread — and the request that
    must never queue behind it is ``POST /auth/login``, the break-glass path
    this whole wave promises keeps working when the IdP does not.
    """
    _limit_sso(request)
    row = _load_provider_row(db)
    if row is None or not row[9] or _env_disabled(request):
        _audit_login_failure(db, request, reason="sso not enabled")
        raise HTTPException(status_code=404, detail=_SSO_UNAVAILABLE)
    config = _config_from_row(request, row, decrypt_secret=False)
    try:
        started = oidc_lib.build_authorization_request(config, _metadata(request))
    except oidc_lib.OidcError as exc:
        _audit_login_failure(db, request, reason=f"start failed: {exc.reason}")
        raise HTTPException(status_code=503, detail=oidc_lib.GENERIC_LOGIN_FAILURE)
    with db.transaction():
        # Expired rows are swept on every start, so this table stays small
        # without a scheduled job on a single-box installation.
        db.execute(_SWEEP_LOGIN_STATES)
        db.execute(
            _INSERT_LOGIN_STATE,
            (
                started.state,
                started.nonce,
                started.code_verifier,
                started.browser_binding,
                config.redirect_uri,
                started.expires_at,
            ),
        )
    return StartLoginResponse(
        authorization_url=started.authorization_url,
        state=started.state,
        browser_token=started.browser_token,
    )


_SSO_UNAVAILABLE = (
    "Single sign-on is not available on this Headway installation. Please "
    "sign in with your Headway username and password, or ask your Headway "
    "administrator."
)


@router.post("/auth/oidc/callback", response_model=CallbackResponse)
def oidc_callback(
    body: CallbackRequest, request: Request, db=Depends(get_db)
) -> CallbackResponse:
    """Finish a sign-in: consume the state, exchange the code, validate the
    ID token in full, map claims onto a role, provision if needed, and issue
    a Headway session.

    Every refusal below returns the SAME message. The reason is in the audit
    trail; the wire never says whether the account exists, whether it was
    mapped, or which check failed.

    RATE LIMITED for the same reason as ``start_login``, plus one of its own:
    a caller who reaches the code exchange makes Headway POST to the agency's
    identity provider, so an unlimited callback turns this box into a traffic
    amplifier pointed at the agency's own IdP.
    """
    _limit_sso(request)
    row = _load_provider_row(db)
    if row is None or not row[9] or _env_disabled(request):
        _audit_login_failure(db, request, reason="callback while sso not enabled")
        raise HTTPException(status_code=404, detail=_SSO_UNAVAILABLE)

    # --- consume the state, single-use, bound to this browser -------------
    with db.transaction():
        state_row = db.execute(_CONSUME_LOGIN_STATE, (body.state,)).fetchone()
    if state_row is None:
        # Unknown, already used, or expired — one reason class, because
        # telling them apart tells a replaying attacker which it was.
        _audit_login_failure(
            db, request, reason="state unknown, replayed or expired"
        )
        raise _login_refused()
    nonce, code_verifier, browser_binding, _redirect_uri = state_row
    if not secrets.compare_digest(
        oidc_lib.hash_browser_token(body.browser_token), browser_binding
    ):
        _audit_login_failure(db, request, reason="browser binding did not match")
        raise _login_refused()

    config = _config_from_row(request, row, decrypt_secret=True)
    metadata = _metadata(request)

    # --- exchange + validate ---------------------------------------------
    try:
        tokens = oidc_lib.exchange_code(
            config, metadata, code=body.code, code_verifier=code_verifier
        )
        claims = oidc_lib.validate_id_token(
            tokens["id_token"], config, metadata, expected_nonce=nonce
        )
    except oidc_lib.OidcError as exc:
        _audit_login_failure(db, request, reason=exc.reason)
        raise _login_refused()

    # --- map claims onto a role, deny-by-default --------------------------
    mapping_rows = db.execute(_SELECT_MAPPINGS).fetchall()
    mappings = [(r[1], r[2]) for r in mapping_rows]
    role, matched = resolve_role(claims.groups, mappings)
    if role is None:
        # NOTHING IS CREATED. An unmapped user does not get an account, does
        # not get viewer, does not get a row anywhere.
        _audit_login_failure(
            db,
            request,
            reason="no configured mapping matched the user's claims",
            actor=f"sso:{claims.subject}",
            detail={
                "idp_issuer": claims.issuer,
                "idp_subject": claims.subject,
                "claim_values_presented": list(claims.groups),
                "provisioned": False,
            },
        )
        raise _login_refused()

    # --- provision or synchronize ----------------------------------------
    settings = request.app.state.settings
    existing = db.execute(
        _SELECT_USER_BY_IDP, (claims.issuer, claims.subject)
    ).fetchone()

    if existing is not None and not existing[3]:
        # Deactivated: refused exactly like the local path, with the same
        # generic message. Deactivation is the existing is_active path and
        # single sign-on does not route around it.
        _audit_login_failure(
            db,
            request,
            reason="account deactivated",
            actor=existing[1],
            detail={"idp_issuer": claims.issuer, "idp_subject": claims.subject},
        )
        raise _login_refused()

    if existing is None:
        clash = db.execute(_SELECT_USER_BY_USERNAME, (claims.username,)).fetchone()
        if clash is not None:
            # A local account already owns this username. Refused: silently
            # federating it would let anyone who can create a user with the
            # right name at the IdP take over a Headway account, and it would
            # destroy the break-glass password on the way. Audited in its own
            # transaction (not the login one, which is about to abort),
            # because this is the interesting case for an administrator.
            with db.transaction():
                write_event(
                    db,
                    actor=f"sso:{claims.subject}",
                    action="sso_provisioning_refused",
                    subject_kind="auth.users",
                    subject_id=str(clash[0]),
                    detail={
                        "reason": (
                            "a local account already uses this username; "
                            "Headway will not convert a local account to a "
                            "federated one automatically"
                        ),
                        "username": claims.username,
                        "idp_issuer": claims.issuer,
                        "idp_subject": claims.subject,
                    },
                )
            raise _login_refused()

    with db.transaction():
        user_id, username, effective_role = _provision(
            db,
            existing=existing,
            issuer=claims.issuer,
            subject=claims.subject,
            username=claims.username,
            mapped_role=role,
            matched_claims=matched,
        )
        db.execute(_TOUCH_LAST_LOGIN, (user_id,))
        write_event(
            db,
            actor=username,
            action="login",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={
                "role": effective_role,
                "authenticated_via": "oidc",
                "idp_issuer": claims.issuer,
                "idp_subject": claims.subject,
                "mapped_role": role,
                "claim_values_matched": matched,
            },
        )
    # A NEW session identifier: the pre-login state row is consumed and
    # nothing the browser held before this moment carries any authority.
    token = issue_token(
        secret=settings.session_secret,
        sub=str(user_id),
        username=username,
        role=effective_role,
        ttl_seconds=settings.token_ttl_seconds,
        jti=new_session_id(),
        idp_issuer=claims.issuer,
        idp_subject=claims.subject,
    )
    return CallbackResponse(
        access_token=token,
        expires_in=settings.token_ttl_seconds,
        username=username,
        role=effective_role,
    )


def _login_refused() -> HTTPException:
    return HTTPException(status_code=401, detail=oidc_lib.GENERIC_LOGIN_FAILURE)


def _provision(
    db, *, existing, issuer: str, subject: str, username: str, mapped_role: str,
    matched_claims: list[str],
) -> tuple[str, str, str]:
    """Just-in-time provisioning and role synchronization.

    Returns ``(user_id, username, effective_role)``. Called INSIDE the
    caller's transaction so the account, the role change and the audit record
    commit together — or none of them do.

    The refusal cases (deactivated account, username already owned by a local
    account) are decided by the CALLER before this transaction opens, because
    their audit records must survive: a refusal audited inside a transaction
    that then aborts is a refusal nobody can see.

    ``existing`` is matched on issuer + subject, which is why both are
    stored — a username can be renamed at the provider, a subject cannot.
    A brand-new account is created with NO password hash (migration 0043).
    """
    if existing is not None:
        user_id, existing_username, current_role, _is_active = existing
        effective_role = _synchronized_role(
            db,
            user_id=user_id,
            username=existing_username,
            current_role=current_role,
            mapped_role=mapped_role,
            matched_claims=matched_claims,
        )
        return str(user_id), existing_username, effective_role

    created = db.execute(
        _INSERT_FEDERATED_USER, (username, mapped_role, issuer, subject)
    ).fetchone()
    if created is None:
        raise _login_refused()
    user_id = created[0]
    write_event(
        db,
        actor=username,
        action="sso_user_provisioned",
        subject_kind="auth.users",
        subject_id=str(user_id),
        detail={
            "username": username,
            "role": mapped_role,
            "idp_issuer": issuer,
            "idp_subject": subject,
            "claim_values_matched": matched_claims,
        },
    )
    return str(user_id), username, mapped_role


def _synchronized_role(
    db, *, user_id, username: str, current_role: str, mapped_role: str,
    matched_claims: list[str],
) -> str:
    """Apply the IdP's mapping to an existing federated account.

    THE ONE EXCEPTION, both ways: ``certifying_official``.

    * The IdP cannot GRANT it — ``resolve_role`` cannot return it, and the
      mapping table cannot hold it.
    * The IdP cannot REVOKE it. A user who holds ``certifying_official``
      keeps it through an SSO sign-in whose mapping says otherwise. This is
      not a convenience: if a group membership could remove it, then the set
      of people who may sign a federal submission would still be controlled
      from the directory, just by subtraction instead of addition — and a
      directory change could strand an agency with nobody able to certify,
      which is exactly what the migration-0032 lockout fail-safe exists to
      prevent. Removing it stays a deliberate, audited act inside Headway
      (POST /users/{username}/role), where the same fail-safe applies.
    """
    if current_role == mapped_role:
        return current_role
    if current_role == "certifying_official":
        # The migration-0032 counting query, run here on the FEDERATED path
        # so the audit record states plainly whether this sign-in would have
        # removed the last person able to certify. The answer does not change
        # what happens — the role is retained either way — but it is the
        # difference between "we think this is safe" and a record showing the
        # fail-safe was consulted at the moment it mattered.
        others = db.execute(_COUNT_OTHER_ACTIVE_ADMINS, (username,)).fetchone()[0]
        write_event(
            db,
            actor=username,
            action="sso_role_retained_local",
            subject_kind="auth.users",
            subject_id=str(user_id),
            detail={
                "username": username,
                "retained_role": current_role,
                "mapped_role": mapped_role,
                "reason": (
                    "the identity provider cannot grant or revoke the "
                    "certifying official role; it is granted only inside "
                    "Headway"
                ),
                "would_have_been_last_certifying_official": others == 0,
                "claim_values_matched": matched_claims,
            },
        )
        return current_role
    db.execute(_UPDATE_FEDERATED_ROLE, (mapped_role, user_id))
    write_event(
        db,
        actor=username,
        action="sso_role_synchronized",
        subject_kind="auth.users",
        subject_id=str(user_id),
        detail={
            "username": username,
            "old_role": current_role,
            "new_role": mapped_role,
            "claim_values_matched": matched_claims,
        },
    )
    return mapped_role


# ---------------------------------------------------------------------------
# The configuration surface (certifying official only, every change audited)
# ---------------------------------------------------------------------------


def _config_response(request: Request, row, **extra) -> ProviderConfigResponse:
    available = secrets_at_rest.key_available() or hasattr(
        request.app.state, "secret_key"
    )
    if row is None:
        return ProviderConfigResponse(
            configured=False,
            secret_storage_available=available,
            disabled_by_environment=_env_disabled(request),
            **extra,
        )
    (
        discovery_url, client_id, secret_encrypted, redirect_uri, groups_claim,
        username_claim, clock_skew, ca_bundle, button_label, is_enabled,
        updated_by, updated_at,
    ) = row
    return ProviderConfigResponse(
        configured=True,
        discovery_url=discovery_url,
        client_id=client_id,
        client_secret_set=bool(secret_encrypted),
        redirect_uri=redirect_uri,
        groups_claim=groups_claim,
        username_claim=username_claim,
        clock_skew_seconds=clock_skew,
        ca_bundle_path=ca_bundle,
        button_label=button_label,
        is_enabled=is_enabled,
        updated_by=updated_by,
        updated_at=updated_at,
        secret_storage_available=available,
        disabled_by_environment=_env_disabled(request),
        **extra,
    )


@router.get("/auth/oidc/config", response_model=ProviderConfigResponse)
def get_config(
    request: Request,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> ProviderConfigResponse:
    """The stored configuration. NEVER includes the client secret — there is
    no field on this model that could carry it."""
    return _config_response(request, _load_provider_row(db))


@router.put("/auth/oidc/config", response_model=UpdateProviderResponse)
def put_config(
    body: UpdateProviderRequest,
    request: Request,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> UpdateProviderResponse:
    """Save the provider configuration (certifying official only; audited).

    The client secret is encrypted before it touches the database and the
    audit record says only that it CHANGED. Passing null keeps the stored
    secret, so an admin can edit the group claim without re-entering a
    credential they were shown once.
    """
    try:
        oidc_lib.validate_discovery_url(body.discovery_url)
        oidc_lib.validate_ca_bundle_path(body.ca_bundle_path)
        _validate_redirect_uri(body.redirect_uri)
    except oidc_lib.OidcConfigurationError as exc:
        raise HTTPException(status_code=422, detail=exc.public_message)

    existing = _load_provider_row(db)
    stored_secret = existing[2] if existing else None
    secret_changed = body.client_secret is not None
    if secret_changed and body.client_secret == "":
        encrypted = None
    elif secret_changed:
        try:
            encrypted = secrets_at_rest.encrypt(
                body.client_secret,
                associated_data=secrets_at_rest.AD_OIDC_CLIENT_SECRET,
                key=secrets_at_rest.get_key(request.app),
            )
        except secrets_at_rest.SecretKeyUnavailable as exc:
            # Refuse rather than store it in the clear.
            raise HTTPException(status_code=503, detail=str(exc))
    else:
        encrypted = stored_secret

    # `encrypted` is already the secret this request will STORE: the old one
    # when unchanged, the new one when supplied, None when explicitly cleared.
    # Consulting `stored_secret` as well would let "" + is_enabled=true past
    # this guard on the strength of the secret being deleted in the same
    # statement — writing NULL and enabling SSO at once, which degrades a
    # confidential client to a public one and fails every sign-in afterwards
    # with a screen that reported success.
    if body.is_enabled and not encrypted:
        raise HTTPException(
            status_code=422,
            detail=(
                "Single sign-on cannot be turned on without a client secret. "
                "Your identity provider gave Headway one when you registered "
                "it; paste it into 'Client secret' above. If you have lost "
                "it, generate a new one at the provider — Headway cannot show "
                "you the old one, because it is stored encrypted and never "
                "displayed again."
            ),
        )

    with db.transaction():
        updated_at = db.execute(
            _UPSERT_PROVIDER,
            (
                body.discovery_url,
                body.client_id,
                encrypted,
                body.redirect_uri,
                body.groups_claim,
                body.username_claim,
                body.clock_skew_seconds,
                body.ca_bundle_path or None,
                body.button_label,
                body.is_enabled,
                identity.username,
            ),
        ).fetchone()[0]
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sso_config_changed",
            subject_kind="auth.oidc_provider",
            subject_id=None,
            detail={
                # The secret is NEVER here — only the fact that it moved.
                "client_secret_changed": secret_changed,
                "old": _auditable_config(existing),
                "new": {
                    "discovery_url": body.discovery_url,
                    "client_id": body.client_id,
                    "redirect_uri": body.redirect_uri,
                    "groups_claim": body.groups_claim,
                    "username_claim": body.username_claim,
                    "clock_skew_seconds": body.clock_skew_seconds,
                    "ca_bundle_path": body.ca_bundle_path or None,
                    "button_label": body.button_label,
                    "is_enabled": body.is_enabled,
                },
                **identity.audit_actor_detail(),
            },
        )
    # A changed provider must not be tested or used against a cached
    # discovery document from the old one.
    _metadata(request).forget(body.discovery_url)
    if existing:
        _metadata(request).forget(existing[0])
    row = _load_provider_row(db)
    return UpdateProviderResponse(
        **_config_response(request, row).model_dump(),
        audit_event_id=audit_event_id,
    )


def _auditable_config(row) -> dict | None:
    """The previous configuration for the audit detail. Never the secret."""
    if row is None:
        return None
    return {
        "discovery_url": row[0],
        "client_id": row[1],
        "client_secret_set": bool(row[2]),
        "redirect_uri": row[3],
        "groups_claim": row[4],
        "username_claim": row[5],
        "clock_skew_seconds": row[6],
        "ca_bundle_path": row[7],
        "button_label": row[8],
        "is_enabled": row[9],
    }


def _validate_redirect_uri(uri: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(uri)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        raise oidc_lib.OidcConfigurationError(
            "The sign-in return address must be a full web address, starting "
            "with https:// — it is where your identity provider sends people "
            "back to after they sign in, and it must match what you "
            "registered at the provider exactly."
        )
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and host not in oidc_lib._LOOPBACK_HOSTS:
        raise oidc_lib.OidcConfigurationError(
            "The sign-in return address must use https://, not http://. "
            "Sign-in responses travel through it, so an unencrypted address "
            "would expose them to anyone on the network."
        )


@router.post("/auth/oidc/config/test", response_model=TestConfigResponse)
def test_config(
    request: Request,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> TestConfigResponse:
    """Prove the configuration works BEFORE anyone depends on it.

    Runs the same code the sign-in path runs, in the same order, as far as it
    can go without a human at a browser: reach the discovery document over
    TLS, read the endpoints, fetch the signing keys, and prove the client id
    and secret are accepted by redeeming a deliberately invalid code (see
    ``oidc.probe_client_credentials``). Then it checks the two things that
    are correct in configuration but useless in practice: no role mappings
    (every sign-in would be refused) and sign-on left switched off.

    Each step reports pass/fail with a message written for someone who has
    never configured OIDC and does not have database access.
    """
    row = _load_provider_row(db)
    steps: list[TestStep] = []
    if row is None:
        steps.append(TestStep(
            step="configuration",
            ok=False,
            message=(
                "Nothing is configured yet. Fill in the discovery address, "
                "client id and client secret above, save, then test."
            ),
        ))
        return _finish_test(db, identity, steps)

    try:
        config = _config_from_row(request, row, decrypt_secret=True)
    except secrets_at_rest.SecretKeyUnavailable as exc:
        steps.append(TestStep(step="client secret", ok=False, message=str(exc)))
        return _finish_test(db, identity, steps)
    except secrets_at_rest.SecretDecryptionFailed as exc:
        steps.append(TestStep(step="client secret", ok=False, message=str(exc)))
        return _finish_test(db, identity, steps)

    metadata = _metadata(request)
    metadata.forget(config.discovery_url)

    # 1. Discovery over TLS.
    try:
        document = metadata.discovery(config, force=True)
    except oidc_lib.OidcError as exc:
        steps.append(TestStep(
            step="reach your identity provider", ok=False,
            message=exc.public_message,
        ))
        return _finish_test(db, identity, steps)
    steps.append(TestStep(
        step="reach your identity provider", ok=True,
        message=(
            f"Headway reached your identity provider and read its "
            f"configuration. It identifies itself as '{document['issuer']}'."
            + (
                f" The certificate was checked against '{config.ca_bundle_path}'."
                if config.ca_bundle_path
                else " Its security certificate was checked and accepted."
            )
        ),
    ))

    # 2. Signing keys (and therefore rotation readiness).
    try:
        keys = metadata._jwks_keys(config, document["jwks_uri"], force=True)
    except oidc_lib.OidcError as exc:
        steps.append(TestStep(
            step="read the signing keys", ok=False, message=exc.public_message
        ))
        return _finish_test(db, identity, steps)
    usable = [k for k in keys if k.get("kty") != "oct"]
    steps.append(TestStep(
        step="read the signing keys", ok=bool(usable),
        message=(
            f"Your provider publishes {len(usable)} signing "
            f"{'key' if len(usable) == 1 else 'keys'}. Headway re-reads them "
            f"automatically when your provider rotates them, so a rotation "
            f"will not interrupt sign-in."
            if usable else
            "Your provider published no usable signing keys, so Headway "
            "cannot verify that a sign-in really came from it."
        ),
    ))
    if not usable:
        return _finish_test(db, identity, steps)

    # 3. The credentials themselves.
    if not config.client_secret:
        steps.append(TestStep(
            step="check the client id and secret", ok=False,
            message=(
                "No client secret is stored, so Headway cannot prove it is "
                "allowed to complete a sign-in. Paste the client secret your "
                "provider gave you into the field above and save."
            ),
        ))
    else:
        try:
            ok, message = oidc_lib.probe_client_credentials(config, metadata)
        except oidc_lib.OidcError as exc:
            ok, message = False, exc.public_message
        steps.append(TestStep(
            step="check the client id and secret", ok=ok, message=message
        ))
        if not ok:
            return _finish_test(db, identity, steps)

    # 4. Would anyone actually get in?
    mapping_rows = db.execute(_SELECT_MAPPINGS).fetchall()
    steps.append(TestStep(
        step="check who would be allowed in", ok=bool(mapping_rows),
        message=(
            "No groups are mapped to Headway roles yet, so every single "
            "sign-on attempt would be refused and no accounts would be "
            "created. Add at least one mapping below."
            if not mapping_rows else
            f"{len(mapping_rows)} group "
            f"{'mapping is' if len(mapping_rows) == 1 else 'mappings are'} "
            f"configured. Anyone whose groups do not match one of them is "
            f"refused and no account is created for them."
        ),
    ))

    # 5. Is it actually switched on?
    steps.append(TestStep(
        step="single sign-on switch", ok=bool(config.is_enabled) and not _env_disabled(request),
        message=(
            "Single sign-on is switched off on this server by the "
            "HEADWAY_OIDC_DISABLED setting, so the sign-in page will not "
            "offer it. Ask whoever runs the server to remove that setting."
            if _env_disabled(request) else
            "Single sign-on is turned on. The sign-in page offers it."
            if config.is_enabled else
            "Everything above is ready, but single sign-on is still turned "
            "off, so the sign-in page does not offer it yet. Tick 'Turn "
            "single sign-on on' above and save when you are ready."
        ),
    ))
    return _finish_test(db, identity, steps)


def _finish_test(db, identity: Identity, steps: list[TestStep]) -> TestConfigResponse:
    ok = all(step.ok for step in steps)
    with db.transaction():
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sso_config_tested",
            subject_kind="auth.oidc_provider",
            subject_id=None,
            detail={
                "ok": ok,
                "steps": [
                    {"step": s.step, "ok": s.ok} for s in steps
                ],
                **identity.audit_actor_detail(),
            },
        )
    return TestConfigResponse(ok=ok, steps=steps, audit_event_id=audit_event_id)


# ---------------------------------------------------------------------------
# Claim -> role mappings
# ---------------------------------------------------------------------------


@router.get("/auth/oidc/mappings", response_model=list[RoleMapping])
def list_mappings(
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> list[RoleMapping]:
    """Every configured claim -> role grant. Certifying official only."""
    return [
        RoleMapping(
            mapping_id=str(r[0]),
            claim_value=r[1],
            headway_role=r[2],
            role_label=role_label(r[2]),
            note=r[3],
            created_by=r[4],
            created_at=r[5],
        )
        for r in db.execute(_SELECT_MAPPINGS).fetchall()
    ]


@router.post("/auth/oidc/mappings", response_model=CreateMappingResponse, status_code=201)
def create_mapping(
    body: CreateMappingRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> CreateMappingResponse:
    """Grant a Headway role to everyone carrying one exact claim value.

    ``certifying_official`` is refused here in plain language, and the
    database refuses it too (migration 0043). The message explains WHY rather
    than just saying no, because an administrator told "no" without a reason
    will look for a way around it.
    """
    if body.headway_role == "certifying_official":
        raise HTTPException(
            status_code=422,
            detail=(
                "Headway will not let your identity provider grant the "
                "certifying official role. Certifying is a legal attestation "
                "that figures sent to the federal government are correct, so "
                "who may do it has to be decided inside Headway and recorded "
                "in Headway's audit trail — not by a group membership that "
                "is changed elsewhere, by people Headway cannot see. Map "
                "this group to another role here, then make the specific "
                "people who certify into certifying officials under Admin -> "
                "Users. They will still sign in through your identity "
                "provider."
            ),
        )
    if body.headway_role not in IDP_GRANTABLE_ROLES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{body.headway_role}' is not a role Headway can grant from "
                f"a group. The choices are: "
                + ", ".join(ROLE_LABELS[r] for r in IDP_GRANTABLE_ROLES)
                + "."
            ),
        )
    claim_value = body.claim_value.strip()
    if not claim_value:
        raise HTTPException(
            status_code=422,
            detail=(
                "Enter the exact group value your identity provider sends. "
                "For Microsoft Entra ID this is usually the group's object "
                "id; for Keycloak it is usually the group's name."
            ),
        )
    with db.transaction():
        created = db.execute(
            _INSERT_MAPPING,
            (claim_value, body.headway_role, body.note or None, identity.username),
        ).fetchone()
        if created is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"'{claim_value}' is already mapped to a Headway role. "
                    f"Remove the existing mapping first if you want to change "
                    f"which role it grants — that way the change is recorded "
                    f"as two deliberate steps in the audit trail."
                ),
            )
        mapping_id, created_at = created
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sso_role_mapping_created",
            subject_kind="auth.oidc_role_mappings",
            subject_id=str(mapping_id),
            detail={
                "claim_value": claim_value,
                "headway_role": body.headway_role,
                "note": body.note or None,
                **identity.audit_actor_detail(),
            },
        )
    return CreateMappingResponse(
        mapping_id=str(mapping_id),
        claim_value=claim_value,
        headway_role=body.headway_role,
        role_label=role_label(body.headway_role),
        note=body.note or None,
        created_by=identity.username,
        created_at=created_at,
        audit_event_id=audit_event_id,
    )


@router.delete("/auth/oidc/mappings/{mapping_id}", response_model=DeleteMappingResponse)
def delete_mapping(
    mapping_id: str,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> DeleteMappingResponse:
    """Remove a grant (certifying official only; audited with what it was).

    Existing accounts are NOT deleted — removing a mapping stops future
    sign-ins for that group, and the accounts it already created are managed
    under Admin -> Users like any other. Deleting people's accounts as a side
    effect of a configuration edit would be a surprise, and a destructive one.
    """
    with db.transaction():
        removed = db.execute(_DELETE_MAPPING, (mapping_id,)).fetchone()
        if removed is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "That mapping no longer exists — someone may have removed "
                    "it already. Refresh the page to see the current list."
                ),
            )
        claim_value, headway_role = removed
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sso_role_mapping_deleted",
            subject_kind="auth.oidc_role_mappings",
            subject_id=str(mapping_id),
            detail={
                "claim_value": claim_value,
                "headway_role": headway_role,
                **identity.audit_actor_detail(),
            },
        )
    return DeleteMappingResponse(
        claim_value=claim_value,
        headway_role=headway_role,
        audit_event_id=audit_event_id,
    )
