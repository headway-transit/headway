"""Machine API key issuance, revocation, and listing (handoff 0006, point 4).

Admin-only: gated to the certifying_official role for v0 (a dedicated admin
role is a future increment, per the handoff). Every issuance and revocation is
audit-logged in the same transaction as the state change.

The full key appears exactly once, in the issuance response, alongside an
explicit warning. Only the SHA-256 hash is stored; the listing endpoint serves
prefixes and metadata, NEVER hashes and never key material.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..audit import write_event
from ..auth import Identity
from ..authz import require_certifying_official
from ..db import get_db
from ..machine_auth import KNOWN_SCOPES, SCOPE_INGEST_TIDES, generate_key

router = APIRouter(tags=["machine-keys"])

KEY_WARNING = (
    "Store this key now. For security, Headway keeps only a hash — this is "
    "the ONLY time the full key will ever be shown, and it cannot be "
    "recovered. If it is lost, revoke it and issue a new one."
)


class CreateKeyRequest(BaseModel):
    name: str = Field(min_length=1, description="Human label, e.g. 'APC vendor X'")
    scopes: list[str] = Field(min_length=1)
    source_label: Optional[str] = Field(
        default=None,
        description=(
            "The envelope source this key is bound to (required for ingest "
            "keys); e.g. 'tides_simulated' for a simulator key."
        ),
    )


class CreateKeyResponse(BaseModel):
    key_id: str
    key: str  # the full key — returned ONCE, never stored, never again
    warning: str
    key_prefix: str
    name: str
    scopes: list[str]
    source_label: Optional[str]
    created_at: dt.datetime


class KeyListItem(BaseModel):
    """Listing shape: prefix + metadata only — never the hash, never the key."""

    key_id: str
    name: str
    key_prefix: str
    scopes: list[str]
    source_label: Optional[str]
    created_by: str
    created_at: dt.datetime
    revoked_at: Optional[dt.datetime]


class RevokeKeyResponse(BaseModel):
    key_id: str
    revoked_at: dt.datetime
    audit_event_id: int


_INSERT_KEY = (
    "INSERT INTO auth.api_keys "
    "(name, key_hash, key_prefix, scopes, source_label, created_by) "
    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING key_id, created_at"
)

_REVOKE_KEY = (
    "UPDATE auth.api_keys SET revoked_at = now() "
    "WHERE key_id = %s AND revoked_at IS NULL RETURNING key_id, revoked_at"
)

_SELECT_KEY_EXISTS = "SELECT key_id FROM auth.api_keys WHERE key_id = %s"

_LIST_KEYS = (
    "SELECT key_id, name, key_prefix, scopes, source_label, created_by, "
    "created_at, revoked_at FROM auth.api_keys ORDER BY created_at"
)


@router.post("/machine/keys", response_model=CreateKeyResponse, status_code=201)
def issue_key(
    body: CreateKeyRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> CreateKeyResponse:
    unknown = [s for s in body.scopes if s not in KNOWN_SCOPES]
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                "These are not permissions Headway knows: "
                + ", ".join(unknown)
                + ". Valid machine permissions are: "
                + ", ".join(KNOWN_SCOPES)
                + ". Permissions are deny-by-default, so an unknown one is "
                "refused rather than silently ignored."
            ),
        )
    if SCOPE_INGEST_TIDES in body.scopes and not (body.source_label or "").strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "An ingest key must be bound to a source label (e.g. "
                "'tides_simulated' for simulator data, or the vendor's own "
                "label). Every record this key pushes is stamped with that "
                "source, so simulated and real data stay permanently "
                "distinguishable."
            ),
        )
    new_key = generate_key()
    scopes = list(dict.fromkeys(body.scopes))  # de-duplicate, keep order
    source_label = (body.source_label or "").strip() or None
    with db.transaction():
        row = db.execute(
            _INSERT_KEY,
            (
                body.name,
                new_key.key_hash,
                new_key.key_prefix,
                scopes,
                source_label,
                identity.username,
            ),
        ).fetchone()
        key_id, created_at = str(row[0]), row[1]
        write_event(
            db,
            actor=identity.username,
            action="machine_key_issued",
            subject_kind="auth.api_keys",
            subject_id=key_id,
            detail={
                # Metadata only: the key and its hash never enter the audit trail.
                "name": body.name,
                "key_prefix": new_key.key_prefix,
                "scopes": scopes,
                "source_label": source_label,
            },
        )
    return CreateKeyResponse(
        key_id=key_id,
        key=new_key.full_key,
        warning=KEY_WARNING,
        key_prefix=new_key.key_prefix,
        name=body.name,
        scopes=scopes,
        source_label=source_label,
        created_at=created_at,
    )


@router.delete("/machine/keys/{key_id}", response_model=RevokeKeyResponse)
def revoke_key(
    key_id: str,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> RevokeKeyResponse:
    # Soft revoke: the row stays forever (audit history); only revoked_at is set.
    with db.transaction():
        row = db.execute(_REVOKE_KEY, (key_id,)).fetchone()
        if row is None:
            exists = db.execute(_SELECT_KEY_EXISTS, (key_id,)).fetchone()
            if exists is None:
                raise HTTPException(
                    status_code=404,
                    detail="No machine API key with that id exists.",
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    "This machine API key is already revoked. Revocation is "
                    "permanent, so there is nothing more to do."
                ),
            )
        revoked_id, revoked_at = str(row[0]), row[1]
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="machine_key_revoked",
            subject_kind="auth.api_keys",
            subject_id=revoked_id,
            detail={},
        )
    return RevokeKeyResponse(
        key_id=revoked_id, revoked_at=revoked_at, audit_event_id=audit_event_id
    )


@router.get("/machine/keys", response_model=list[KeyListItem])
def list_keys(
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> list[KeyListItem]:
    rows = db.execute(_LIST_KEYS, ()).fetchall()
    return [
        KeyListItem(
            key_id=str(r[0]),
            name=r[1],
            key_prefix=r[2],
            scopes=list(r[3]),
            source_label=r[4],
            created_by=r[5],
            created_at=r[6],
            revoked_at=r[7],
        )
        for r in rows
    ]
