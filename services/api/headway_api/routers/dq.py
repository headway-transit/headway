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

VALID_STATUSES = ("open", "owned", "resolved")


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


_SELECT_ISSUES = (
    "SELECT issue_id, issue_type, severity, status, owner, title, description, "
    "source_record_ids, created_at, resolved_at, resolution, resolution_minutes "
    "FROM dq.issues"
)

_RESOLVE_ISSUE = (
    "UPDATE dq.issues SET status = 'resolved', resolved_at = now(), "
    "resolution = %s, resolution_minutes = %s "
    "WHERE issue_id = %s AND status <> 'resolved' "
    "RETURNING issue_id, issue_type, severity, resolved_at"
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


@router.get("/dq/issues/counts", response_model=DqIssueCounts)
def count_issues(
    status: Optional[str] = Query(default=None),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> DqIssueCounts:
    """Severity/status counts over the same rows (and the same optional
    status filter) as GET /dq/issues — composition of the one issues query,
    counted in the open, no new tables (handoff 0017)."""
    issues = list_issues(status=status, identity=identity, db=db)
    by_severity = {s: 0 for s in KNOWN_SEVERITIES}
    by_status = {s: 0 for s in VALID_STATUSES}
    for issue in issues:
        # An unexpected vocabulary value still counts, honestly, under its
        # own key — never dropped, never bucketed as something else.
        by_severity[issue.severity] = by_severity.get(issue.severity, 0) + 1
        by_status[issue.status] = by_status.get(issue.status, 0) + 1
    return DqIssueCounts(
        total=len(issues), by_severity=by_severity, by_status=by_status
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
                    "This data-quality issue is already resolved. It cannot "
                    "be resolved again — reopening and re-resolving would "
                    "need a new issue so the history stays honest."
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
