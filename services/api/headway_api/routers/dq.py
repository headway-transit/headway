"""Data-quality issue workflow: list (any signed-in role) and resolve
(data steward or above), with every resolution audit-logged.

Fail-loudly is the point of this router: gaps, conflicts, and validation
failures live in dq.issues with an owner and a resolution trail — an
unexplained gap becomes a finding in an FTA triennial review.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

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


class ResolveRequest(BaseModel):
    resolution: str = Field(min_length=1)


class ResolveResponse(BaseModel):
    issue_id: str
    status: str
    resolved_at: dt.datetime
    resolution: str
    audit_event_id: int


_SELECT_ISSUES = (
    "SELECT issue_id, issue_type, severity, status, owner, title, description, "
    "source_record_ids, created_at, resolved_at, resolution FROM dq.issues"
)

_RESOLVE_ISSUE = (
    "UPDATE dq.issues SET status = 'resolved', resolved_at = now(), "
    "resolution = %s WHERE issue_id = %s AND status <> 'resolved' "
    "RETURNING issue_id, resolved_at"
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


@router.post("/dq/issues/{issue_id}/resolve", response_model=ResolveResponse)
def resolve_issue(
    issue_id: str,
    body: ResolveRequest,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> ResolveResponse:
    # One transaction: the status change and its audit event commit together.
    with db.transaction():
        row = db.execute(_RESOLVE_ISSUE, (body.resolution, issue_id)).fetchone()
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
        resolved_id, resolved_at = str(row[0]), row[1]
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="dq_resolve",
            subject_kind="dq.issues",
            subject_id=resolved_id,
            detail={"resolution": body.resolution},
        )
    return ResolveResponse(
        issue_id=resolved_id,
        status="resolved",
        resolved_at=resolved_at,
        resolution=body.resolution,
        audit_event_id=audit_event_id,
    )
