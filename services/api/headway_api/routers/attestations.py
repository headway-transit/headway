"""Statistician attestations: entry, listing, revocation (handoff 0019, A).

The p. 146 rule (2026 NTD Policy Manual, Full Reporting — quoted verbatim in
REGULATORY_TRACKER.md): beyond 2% missing data, factoring requires "a
qualified statistician approve the factoring method". This router records
that human approval as an append-only cert.attestations row (migration
0029) so the calculation library can honor it — the calc never decides
whether a statistician approved anything; it only reads what was recorded
here, in scope, unrevoked.

ROLE CHOICE (handoff 0019 asked for "the smallest honest fit; document"):
entry and revocation are gated to **certifying_official**. The role model
(headway_api.authz) is viewer < data_steward < report_preparer <
certifying_official; recording that a qualified statistician approved a
factoring method is an accountability act of the same legal weight class as
certification — it directly changes what figures the platform will emit for
federal reporting. data_steward/report_preparer would let routine workflow
roles unlock >2% factoring; a NEW attestation-manager permission would grow
the role vocabulary for one action that in practice belongs to the same
officer who signs the report. So: certifying_official, the smallest
existing honest fit. Revisit if agencies separate the duties.

Append-only discipline: revocation, never deletion — enforced by the
migration-0029 trigger AND by this router only ever INSERTing or setting
the revocation trio. Every action is audit-logged in the same transaction.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from ..audit import write_event
from ..auth import Identity
from ..authz import require_authenticated, require_certifying_official
from ..db import get_db

router = APIRouter(tags=["attestations"])

#: The p. 146 rule covers the 100%-count UPT/PMT paths and nothing else
#: (mirror of headway_calc.attestation.ATTESTABLE_METRICS).
ATTESTABLE_METRICS = ("upt", "pmt")


class AttestationRequest(BaseModel):
    statistician_name: str = Field(min_length=1)
    statistician_credentials: str = Field(
        min_length=1,
        description=(
            "A plain-language summary of why this statistician is "
            "qualified (the manual prescribes no specific qualifications; "
            "the agency is accountable for them)."
        ),
    )
    method_description: str = Field(
        min_length=1,
        description="The approved factoring method, in the statistician's terms.",
    )
    document_reference: str = Field(
        min_length=1,
        description=(
            "External pointer to the approval document (file path, document "
            "system id). The document itself is never stored here."
        ),
    )
    metric: str
    scope_pattern: str = Field(
        min_length=1,
        description=(
            "Which figure scopes the approval covers, as an fnmatch pattern "
            "over computed.metric_values.scope: 'agency', 'mode:bus', "
            "'mode:DR:tos:*', or '*' for every scope."
        ),
    )
    period_start: dt.date
    period_end: dt.date

    @field_validator("metric")
    @classmethod
    def _metric_known(cls, v: str) -> str:
        if v not in ATTESTABLE_METRICS:
            raise ValueError(
                f"'{v}' is not a metric a statistician attestation can "
                f"cover. The 2% factoring rule applies to the 100%-count "
                f"passenger metrics only: {', '.join(ATTESTABLE_METRICS)}."
            )
        return v


class Attestation(BaseModel):
    attestation_id: str
    statistician_name: str
    statistician_credentials: str
    method_description: str
    document_reference: str
    metric: str
    scope_pattern: str
    period_start: dt.date
    period_end: dt.date
    entered_by: str
    entered_at: dt.datetime
    revoked_at: Optional[dt.datetime]
    revoked_by: Optional[str]
    revocation_reason: Optional[str]


class AttestationCreated(Attestation):
    audit_event_id: int


class RevokeRequest(BaseModel):
    reason: str = Field(min_length=1)


class AttestationRevoked(Attestation):
    audit_event_id: int


_COLUMNS = (
    "attestation_id, statistician_name, statistician_credentials, "
    "method_description, document_reference, metric, scope_pattern, "
    "period_start, period_end, entered_by, entered_at, revoked_at, "
    "revoked_by, revocation_reason"
)

_INSERT = (
    "INSERT INTO cert.attestations (statistician_name, "
    "statistician_credentials, method_description, document_reference, "
    "metric, scope_pattern, period_start, period_end, entered_by) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
    f"RETURNING {_COLUMNS}"
)

_SELECT = f"SELECT {_COLUMNS} FROM cert.attestations"

_SELECT_ONE = f"{_SELECT} WHERE attestation_id = %s"

#: Revocation is the ONE permitted mutation (the migration-0029 trigger
#: enforces exactly this shape) — all three fields together, once.
_REVOKE = (
    "UPDATE cert.attestations SET revoked_at = now(), revoked_by = %s, "
    "revocation_reason = %s "
    "WHERE attestation_id = %s AND revoked_at IS NULL "
    f"RETURNING {_COLUMNS}"
)


def _attestation_from_row(r) -> Attestation:
    return Attestation(
        attestation_id=str(r[0]),
        statistician_name=r[1],
        statistician_credentials=r[2],
        method_description=r[3],
        document_reference=r[4],
        metric=r[5],
        scope_pattern=r[6],
        period_start=r[7],
        period_end=r[8],
        entered_by=r[9],
        entered_at=r[10],
        revoked_at=r[11],
        revoked_by=r[12],
        revocation_reason=r[13],
    )


@router.post("/attestations", response_model=AttestationCreated, status_code=201)
def create_attestation(
    body: AttestationRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> AttestationCreated:
    """Record a statistician's approval (append-only, audited).

    From the next calc run onward, a >2% missing-data share on a covered
    (metric, scope, period) factors up under this attestation instead of
    refusing — and the factored figure carries the attestation's provenance
    permanently.
    """
    if body.period_end <= body.period_start:
        raise HTTPException(
            status_code=422,
            detail=(
                "The attestation's period must cover at least one day: "
                "period_end must be after period_start (the range is "
                "half-open, like every Headway reporting period)."
            ),
        )
    with db.transaction():
        row = db.execute(
            _INSERT,
            (
                body.statistician_name,
                body.statistician_credentials,
                body.method_description,
                body.document_reference,
                body.metric,
                body.scope_pattern,
                body.period_start,
                body.period_end,
                identity.username,
            ),
        ).fetchone()
        attestation = _attestation_from_row(row)
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="attestation_create",
            subject_kind="cert.attestations",
            subject_id=attestation.attestation_id,
            detail={
                "statistician_name": attestation.statistician_name,
                "statistician_credentials": attestation.statistician_credentials,
                "method_description": attestation.method_description,
                "document_reference": attestation.document_reference,
                "metric": attestation.metric,
                "scope_pattern": attestation.scope_pattern,
                "period_start": attestation.period_start.isoformat(),
                "period_end": attestation.period_end.isoformat(),
                "entered_by_role": identity.role,
            },
        )
    return AttestationCreated(
        **attestation.model_dump(), audit_event_id=audit_event_id
    )


@router.get("/attestations", response_model=list[Attestation])
def list_attestations(
    metric: Optional[str] = Query(default=None),
    include_revoked: bool = Query(default=True),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[Attestation]:
    """List attestations (any signed-in role — the record is the point).
    Revoked rows are served by default: revocation is history, not
    deletion; filter with include_revoked=false for the live set."""
    if metric is not None and metric not in ATTESTABLE_METRICS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{metric}' is not a metric attestations can cover. Valid "
                f"metrics: {', '.join(ATTESTABLE_METRICS)}."
            ),
        )
    sql = _SELECT
    clauses = []
    params: list = []
    if metric is not None:
        clauses.append("metric = %s")
        params.append(metric)
    if not include_revoked:
        clauses.append("revoked_at IS NULL")
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY entered_at, attestation_id"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [_attestation_from_row(r) for r in rows]


@router.get("/attestations/{attestation_id}", response_model=Attestation)
def get_attestation(
    attestation_id: str,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> Attestation:
    row = db.execute(_SELECT_ONE, (attestation_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No attestation with that id exists."
        )
    return _attestation_from_row(row)


@router.post(
    "/attestations/{attestation_id}/revoke",
    response_model=AttestationRevoked,
)
def revoke_attestation(
    attestation_id: str,
    body: RevokeRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> AttestationRevoked:
    """Revoke an attestation (never delete it — migration-0029 trigger).

    Figures already factored under it keep their attestation provenance
    forever (the history is honest); revocation stops FUTURE calc runs from
    factoring under it. Audited in the same transaction.
    """
    with db.transaction():
        row = db.execute(
            _REVOKE, (identity.username, body.reason, attestation_id)
        ).fetchone()
        if row is None:
            current = db.execute(_SELECT_ONE, (attestation_id,)).fetchone()
            if current is None:
                raise HTTPException(
                    status_code=404,
                    detail="No attestation with that id exists.",
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    "This attestation is already revoked. It cannot be "
                    "revoked again, and it can never be un-revoked — enter "
                    "a new attestation if the statistician approves a "
                    "method again."
                ),
            )
        attestation = _attestation_from_row(row)
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="attestation_revoke",
            subject_kind="cert.attestations",
            subject_id=attestation.attestation_id,
            detail={
                "revocation_reason": body.reason,
                "revoked_by_role": identity.role,
                "metric": attestation.metric,
                "scope_pattern": attestation.scope_pattern,
                "period_start": attestation.period_start.isoformat(),
                "period_end": attestation.period_end.isoformat(),
            },
        )
    return AttestationRevoked(
        **attestation.model_dump(), audit_event_id=audit_event_id
    )
