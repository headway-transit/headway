"""Data-quality issue workflow: list (any signed-in role) and resolve
(data steward or above), with every resolution audit-logged.

Fail-loudly is the point of this router: gaps, conflicts, and validation
failures live in dq.issues with an owner and a resolution trail — an
unexplained gap becomes a finding in an FTA triennial review.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from .. import webhooks
from ..audit import write_event
from ..auth import Identity
from ..authz import require_at_least, require_authenticated
from ..db import get_db

router = APIRouter(tags=["data-quality"])

#: 'attested' (migration 0029, handoff 0019): the closed state reserved for
#: the p. 146 >2%-missing-data refusal when a recorded statistician
#: attestation covers it — the trail says exactly WHY the gap stopped
#: blocking, instead of a generic 'resolved'. Set only via
#: POST /dq/issues/{id}/attest, referencing the attestation, audited.
VALID_STATUSES = ("open", "owned", "resolved", "attested")

#: The one issue_type the attested state applies to: the p. 146 refusal
#: (upt_v0/pmt_v0 'apc_missing_trips_above_fta_threshold').
ATTESTABLE_ISSUE_TYPE = "apc_missing_trips_above_fta_threshold"


class DqIssue(BaseModel):
    issue_id: str
    issue_type: str
    severity: str
    status: str
    owner: Optional[str]
    title: str
    description: str
    source_record_ids: Optional[list[str]]
    created_at: dt.datetime
    resolved_at: Optional[dt.datetime]
    resolution: Optional[str]
    # Migration 0016: minutes of human effort the fix took, recorded at
    # resolve time. Null when not recorded — never coalesced to zero.
    resolution_minutes: Optional[int]


class ResolveRequest(BaseModel):
    resolution: str = Field(min_length=1)
    # Optional effort measurement (migration 0016). Whole minutes, >= 0.
    resolution_minutes: Optional[int] = None

    @field_validator("resolution_minutes")
    @classmethod
    def _minutes_not_negative(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError(
                "resolution_minutes records how many minutes the fix took, "
                "so it must be a whole number of zero or more. Leave it out "
                "entirely if the effort was not measured."
            )
        return v


class ResolveResponse(BaseModel):
    issue_id: str
    status: str
    resolved_at: dt.datetime
    resolution: str
    resolution_minutes: Optional[int]
    audit_event_id: int


class AttestRequest(BaseModel):
    """Close a p. 146 refusal issue under a recorded statistician
    attestation (handoff 0019). The resolution text is built server-side
    from the attestation — the caller supplies only the reference."""

    attestation_id: str = Field(min_length=1)


class AttestResponse(BaseModel):
    issue_id: str
    status: str  # always 'attested'
    resolved_at: dt.datetime
    resolution: str
    attestation_id: str
    audit_event_id: int


_SELECT_ISSUES = (
    "SELECT issue_id, issue_type, severity, status, owner, title, description, "
    "source_record_ids, created_at, resolved_at, resolution, resolution_minutes "
    "FROM dq.issues"
)

_RESOLVE_ISSUE = (
    "UPDATE dq.issues SET status = 'resolved', resolved_at = now(), "
    "resolution = %s, resolution_minutes = %s "
    "WHERE issue_id = %s AND status IN ('open', 'owned') "
    "RETURNING issue_id, issue_type, severity, resolved_at"
)

#: The attested closure (handoff 0019): only the p. 146 refusal issue, only
#: from an open/owned state, resolution text built server-side naming the
#: attestation — never a free-text masquerade of the state.
_ATTEST_ISSUE = (
    "UPDATE dq.issues SET status = 'attested', resolved_at = now(), "
    "resolution = %s "
    "WHERE issue_id = %s AND status IN ('open', 'owned') "
    "RETURNING issue_id, issue_type, severity, resolved_at"
)

_SELECT_ATTESTATION_FOR_ISSUE = (
    "SELECT attestation_id, statistician_name, statistician_credentials, "
    "method_description, metric, scope_pattern, period_start, period_end, "
    "revoked_at FROM cert.attestations WHERE attestation_id = %s"
)

_SELECT_ISSUE_TYPE_STATUS = (
    "SELECT issue_type, status FROM dq.issues WHERE issue_id = %s"
)

_SELECT_OLD_RESOLUTION_MINUTES = (
    "SELECT resolution_minutes FROM dq.issues WHERE issue_id = %s"
)

_SELECT_ISSUE_STATUS = "SELECT status FROM dq.issues WHERE issue_id = %s"


def _issue_from_row(r) -> DqIssue:
    return DqIssue(
        issue_id=str(r[0]),
        issue_type=r[1],
        severity=r[2],
        status=r[3],
        owner=r[4],
        title=r[5],
        description=r[6],
        source_record_ids=list(r[7]) if r[7] is not None else None,
        created_at=r[8],
        resolved_at=r[9],
        resolution=r[10],
        resolution_minutes=r[11],
    )


@router.get("/dq/issues", response_model=list[DqIssue])
def list_issues(
    status: Optional[str] = Query(default=None),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[DqIssue]:
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{status}' is not a data-quality status Headway knows. "
                f"Valid statuses are: {', '.join(VALID_STATUSES)}."
            ),
        )
    sql = _SELECT_ISSUES
    params: tuple = ()
    if status is not None:
        sql += " WHERE status = %s"
        params = (status,)
    sql += " ORDER BY created_at"
    rows = db.execute(sql, params).fetchall()
    return [_issue_from_row(r) for r in rows]


class DqIssueCounts(BaseModel):
    """Counts for the /dq summary cards (handoff 0017, design point 2):
    counted over EXACTLY the rows GET /dq/issues serves under the same
    filter, so a card total can never disagree with the table below it.
    Missing severities/statuses appear as explicit zeros."""

    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]


#: Severity vocabulary as the calc/AI writers use it (headway_calc.dq).
KNOWN_SEVERITIES = ("blocking", "warning", "info")

#: The counts query: the SAME table and the SAME optional status filter as
#: GET /dq/issues, but counted by the database instead of fetching every row
#: (handoff 0023, design point 1). The previous implementation pulled all
#: rows (41,646 live) and counted in Python: ~4.6–5.9 s measured server-side;
#: this GROUP BY measured ~21 ms on the same live queue (EXPLAIN ANALYZE in
#: handoff 0023 evidence). No pre-aggregation, no staleness: every request
#: counts the live rows. A card total still can never disagree with the
#: table below it — same WHERE clause, same rows, grouped not re-derived.
_COUNT_ISSUES = "SELECT severity, status, count(*) FROM dq.issues"


@router.get("/dq/issues/counts", response_model=DqIssueCounts)
def count_issues(
    status: Optional[str] = Query(default=None),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> DqIssueCounts:
    """Severity/status counts over the same rows (and the same optional
    status filter) as GET /dq/issues — counted by the database in one
    GROUP BY over exactly the rows the list serves (handoff 0017 guarantee
    kept; handoff 0023 made the counting SQL-side for speed)."""
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{status}' is not a data-quality status Headway knows. "
                f"Valid statuses are: {', '.join(VALID_STATUSES)}."
            ),
        )
    sql = _COUNT_ISSUES
    params: tuple = ()
    if status is not None:
        sql += " WHERE status = %s"
        params = (status,)
    sql += " GROUP BY severity, status"
    rows = db.execute(sql, params).fetchall()
    by_severity = {s: 0 for s in KNOWN_SEVERITIES}
    by_status = {s: 0 for s in VALID_STATUSES}
    total = 0
    for severity, row_status, count in rows:
        # An unexpected vocabulary value still counts, honestly, under its
        # own key — never dropped, never bucketed as something else.
        by_severity[severity] = by_severity.get(severity, 0) + count
        by_status[row_status] = by_status.get(row_status, 0) + count
        total += count
    return DqIssueCounts(
        total=total, by_severity=by_severity, by_status=by_status
    )


@router.post("/dq/issues/{issue_id}/resolve", response_model=ResolveResponse)
def resolve_issue(
    issue_id: str,
    body: ResolveRequest,
    request: Request,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> ResolveResponse:
    # One transaction: the status change and its audit event commit together.
    with db.transaction():
        old_row = db.execute(
            _SELECT_OLD_RESOLUTION_MINUTES, (issue_id,)
        ).fetchone()
        old_minutes = old_row[0] if old_row is not None else None
        row = db.execute(
            _RESOLVE_ISSUE, (body.resolution, body.resolution_minutes, issue_id)
        ).fetchone()
        if row is None:
            current = db.execute(_SELECT_ISSUE_STATUS, (issue_id,)).fetchone()
            if current is None:
                raise HTTPException(
                    status_code=404,
                    detail="No data-quality issue with that id exists.",
                )
            raise HTTPException(
                status_code=409,
                detail=(
                    "This data-quality issue is already closed (resolved or "
                    "attested). It cannot be resolved again — reopening and "
                    "re-resolving would need a new issue so the history "
                    "stays honest."
                ),
            )
        resolved_id, issue_type, severity, resolved_at = (
            str(row[0]), row[1], row[2], row[3],
        )
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="dq_resolve",
            subject_kind="dq.issues",
            subject_id=resolved_id,
            detail={
                "resolution": body.resolution,
                # old→new, the settings-router precedent (migration 0016).
                "resolution_minutes_old": old_minutes,
                "resolution_minutes_new": body.resolution_minutes,
            },
        )
    # STRICTLY POST-COMMIT (the certify.py precedent, handoff 0006 design
    # point 7): the resolve transaction above is already committed; delivery
    # is best-effort with one retry, audit-logged, and can never fail this
    # response.
    webhooks.dispatch_dq_issue_resolved(
        db,
        getattr(request.app.state, "webhook_sender", None),
        issue_id=resolved_id,
        issue_type=issue_type,
        severity=severity,
        resolved_by=identity.username,
        resolution_minutes=body.resolution_minutes,
        resolved_at=resolved_at,
    )
    return ResolveResponse(
        issue_id=resolved_id,
        status="resolved",
        resolved_at=resolved_at,
        resolution=body.resolution,
        resolution_minutes=body.resolution_minutes,
        audit_event_id=audit_event_id,
    )


@router.post("/dq/issues/{issue_id}/attest", response_model=AttestResponse)
def attest_issue(
    issue_id: str,
    body: AttestRequest,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> AttestResponse:
    """Close ONE p. 146 refusal issue under a recorded statistician
    attestation — the explicit 'attested' state (handoff 0019, never a
    generic 'resolved', never a deletion).

    Refuses loudly when: the issue does not exist (404); the issue is not
    the p. 146 refusal type (409 — no other gap has a statistician cure:
    'agencies must not collect a smaller sample than the chosen sampling
    plan prescribes', 2026 NTD Policy Manual p. 149); the issue is already
    closed (409); the attestation does not exist (404) or is revoked (409).
    The resolution text is built here from the attestation record. Audited
    in the same transaction.
    """
    with db.transaction():
        att = db.execute(
            _SELECT_ATTESTATION_FOR_ISSUE, (body.attestation_id,)
        ).fetchone()
        if att is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "No attestation with that id exists. Enter the "
                    "statistician's approval first (POST /attestations)."
                ),
            )
        if att[8] is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "That attestation has been revoked, so it cannot close "
                    "this issue. A revoked approval covers nothing going "
                    "forward."
                ),
            )
        issue = db.execute(_SELECT_ISSUE_TYPE_STATUS, (issue_id,)).fetchone()
        if issue is None:
            raise HTTPException(
                status_code=404,
                detail="No data-quality issue with that id exists.",
            )
        issue_type, status = issue[0], issue[1]
        if issue_type != ATTESTABLE_ISSUE_TYPE:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Only the 2%-missing-data refusal "
                    f"({ATTESTABLE_ISSUE_TYPE}) can be closed by a "
                    "statistician attestation — that is the one gap the "
                    "manual gives a statistician-approval path (2026 NTD "
                    "Policy Manual p. 146). Every other issue keeps the "
                    "normal resolution workflow; in particular a short "
                    "sample has NO statistician cure: 'agencies must not "
                    "collect a smaller sample than the chosen sampling "
                    "plan prescribes' (p. 149)."
                ),
            )
        if status not in ("open", "owned"):
            raise HTTPException(
                status_code=409,
                detail=(
                    "This data-quality issue is already closed (resolved "
                    "or attested). Closing it again would blur the trail."
                ),
            )
        resolution = (
            f"Attested: statistician {att[1]} ({att[2]}) approved the "
            f"factoring method — {att[3]} — for metric {att[4]}, scope "
            f"pattern {att[5]!r}, period [{att[6].isoformat()}, "
            f"{att[7].isoformat()}) (attestation #{att[0]}, 2026 NTD "
            f"Policy Manual p. 146). The next calc run over a covered "
            f"period factors up under this attestation and the figure "
            f"carries its provenance."
        )
        row = db.execute(_ATTEST_ISSUE, (resolution, issue_id)).fetchone()
        if row is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This data-quality issue changed while your request "
                    "was being recorded. Nothing was changed. Please "
                    "refresh and try again."
                ),
            )
        attested_id, _type, _severity, resolved_at = (
            str(row[0]), row[1], row[2], row[3],
        )
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="dq_attest",
            subject_kind="dq.issues",
            subject_id=attested_id,
            detail={
                "attestation_id": str(att[0]),
                "resolution": resolution,
                "attested_by_role": identity.role,
            },
        )
    return AttestResponse(
        issue_id=attested_id,
        status="attested",
        resolved_at=resolved_at,
        resolution=resolution,
        attestation_id=str(att[0]),
        audit_event_id=audit_event_id,
    )
