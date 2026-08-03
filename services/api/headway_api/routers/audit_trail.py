"""Reading the audit trail (handoff 0046, the `auditor` role).

The trail has been written since the first release and, until now, could only
be read with database access. That made "reads everything, including the
audit trail" impossible to honour for an auditor who has a Headway account
and nothing else — which is every external auditor.

So: one read-only, paginated, filterable endpoint, open to the two roles with
a reason to use it (``authz.require_audit_trail_reader``). It is narrower
than the rest of the read surface on purpose — the trail names what every
person did across the whole installation, and a data steward has no need to
read a colleague's activity to do their job.

WHAT IT DOES NOT DO
-------------------
It never writes. ``audit.events`` is append-only at the database level
(migration 0007 rejects UPDATE and DELETE with a trigger) and this module
only ever SELECTs, so an auditor cannot alter the record they are reviewing
even if some future bug tried to let them.

It does not decide what is sensitive by role, because the audit ``detail``
column already carries only ids and attestation text by construction
(``audit.write_event`` refuses secrets and PII by convention, enforced in
review). If that ever changes, the withholding belongs at the writer, not
here — a redaction at the reader is a filter someone can forget.

READING THE TRAIL IS ITSELF AUDITED
-----------------------------------
Every other content read in this API records that it happened, and this one
is the read that most needs to. The trail names every actor and every action
across the installation; an oversight surface that can be swept invisibly
lets the reviewed party watch the reviewer, and lets a reviewer scope a
search that nobody can later reconstruct. The recorded event carries the
filters and the number of rows returned — not the rows, which are already
in the table being read.
"""

from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..audit import write_event
from ..auth import Identity
from ..authz import require_audit_trail_reader
from ..db import get_db

router = APIRouter(tags=["audit"])

#: A page size a browser can render and a database can serve without a plan
#: change. The cursor below makes deeper history reachable a page at a time.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500


class AuditEvent(BaseModel):
    event_id: int
    #: The column is `at` in the schema (migration 0007); the API name says
    #: what it is to a reader who has never seen the table.
    occurred_at: dt.datetime
    actor: str
    action: str
    subject_kind: str | None
    subject_id: str | None
    detail: dict


class AuditPage(BaseModel):
    events: list[AuditEvent]
    #: Pass back as ``before_event_id`` for the next page. Null = the end.
    next_cursor: int | None
    #: Plain language for a screen: what this list is and is not.
    note: str


_NOTE = (
    "Headway's audit trail, newest first. Every entry was written in the same "
    "database transaction as the action it describes, so an action that is "
    "not here did not happen, and an action that happened is here. The trail "
    "cannot be edited or deleted, by anyone, including from this page."
)

#: Keyset pagination on the primary key: event_id is a monotonically
#: increasing identity column, so "the page before id N" is stable even while
#: new events are being written underneath. OFFSET would silently skip or
#: repeat rows in exactly that situation, and an audit trail that skips a row
#: is worse than no audit trail.
_SELECT_EVENTS = (
    "SELECT event_id, at, actor, action, subject_kind, subject_id, "
    "detail FROM audit.events"
)


def _detail_as_dict(value) -> dict:
    """psycopg returns JSONB as a dict; a text column comes back as a string.
    Anything unreadable becomes an explicit marker rather than an empty dict —
    silently showing "{}" for a row that has content would be a lie."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {"unreadable_detail": value}
        return parsed if isinstance(parsed, dict) else {"detail": parsed}
    if value is None:
        return {}
    return {"detail": str(value)}


@router.get("/audit/events", response_model=AuditPage)
def list_audit_events(
    actor: str | None = Query(
        default=None,
        description="Only entries by this exact username or machine key.",
    ),
    action: str | None = Query(
        default=None, description="Only entries of this exact action."
    ),
    subject_kind: str | None = Query(
        default=None,
        description="Only entries about this kind of thing, e.g. cert.certifications.",
    ),
    subject_id: str | None = Query(
        default=None, description="Only entries about this exact record."
    ),
    before_event_id: int | None = Query(
        default=None, description="Cursor from the previous page's next_cursor."
    ),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    identity: Identity = Depends(require_audit_trail_reader),
    db=Depends(get_db),
) -> AuditPage:
    """The audit trail, newest first. Auditors and certifying officials only."""
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("actor", actor),
        ("action", action),
        ("subject_kind", subject_kind),
        ("subject_id", subject_id),
    ):
        if value is not None:
            clauses.append(f"{column} = %s")
            params.append(value)
    if before_event_id is not None:
        clauses.append("event_id < %s")
        params.append(before_event_id)
    sql = _SELECT_EVENTS
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    # One more than asked for: the extra row is how we know there IS a next
    # page without a second COUNT query over an append-only table that only
    # ever grows.
    sql += " ORDER BY event_id DESC LIMIT %s"
    params.append(limit + 1)
    rows = db.execute(sql, tuple(params)).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    with db.transaction():
        write_event(
            db,
            actor=identity.username,
            action="audit_trail_read",
            subject_kind="audit.events",
            subject_id=None,
            # The filters, so a later reader can tell a scoped lookup from a
            # sweep of the whole installation, and the count, so a truncated
            # page is not mistaken for the end of the record. Never the rows.
            detail={
                "filters": {
                    k: v
                    for k, v in (
                        ("actor", actor),
                        ("action", action),
                        ("subject_kind", subject_kind),
                        ("subject_id", subject_id),
                    )
                    if v is not None
                },
                "limit": limit,
                "returned": len(rows),
                "paged": before_event_id is not None,
            },
        )
    events = [
        AuditEvent(
            event_id=r[0],
            occurred_at=r[1],
            actor=r[2],
            action=r[3],
            subject_kind=r[4],
            subject_id=r[5],
            detail=_detail_as_dict(r[6]),
        )
        for r in rows
    ]
    return AuditPage(
        events=events,
        next_cursor=events[-1].event_id if (has_more and events) else None,
        note=_NOTE,
    )
