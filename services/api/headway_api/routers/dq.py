"""Data-quality issue workflow: list (any signed-in role) and resolve
(data steward or above), with every resolution audit-logged.

Fail-loudly is the point of this router: gaps, conflicts, and validation
failures live in dq.issues with an owner and a resolution trail — an
unexplained gap becomes a finding in an FTA triennial review.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
import uuid
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

#: Severity vocabulary as the calc/AI writers use it (headway_calc.dq).
KNOWN_SEVERITIES = ("blocking", "warning", "info")

#: The one issue_type the attested state applies to: the p. 146 refusal
#: (upt_v0/pmt_v0 'apc_missing_trips_above_fta_threshold').
ATTESTABLE_ISSUE_TYPE = "apc_missing_trips_above_fta_threshold"


class DqIssueSummary(BaseModel):
    """One issue as the QUEUE shows it (handoff 0030).

    Everything a steward reads in a list is here. What is deliberately NOT
    here is ``source_record_ids`` — see :class:`DqIssue`.
    """

    issue_id: str
    issue_type: str
    severity: str
    status: str
    owner: Optional[str]
    title: str
    description: str
    created_at: dt.datetime
    resolved_at: Optional[dt.datetime]
    resolution: Optional[str]
    # Migration 0016: minutes of human effort the fix took, recorded at
    # resolve time. Null when not recorded — never coalesced to zero.
    resolution_minutes: Optional[int]
    # Migration 0035 (handoff 0029): WHAT this finding is about, in the
    # agency's own vocabulary — affected trips grouped by block, each group
    # carrying its route(s) and the span from first to last scheduled
    # departure, resolved once by the calc runner and FROZEN on the row.
    # Served verbatim: the API neither re-resolves a label nor fills one in.
    #
    # Null for every finding raised before the migration, and for findings
    # about the run as a whole rather than about identifiable rows. Null is
    # the normal case, not an error — the client renders the prose
    # description exactly as it always has. Typed as a free-form object
    # because its schema is versioned INSIDE the blob (``version``): a
    # client that does not recognise the version must fall back to the same
    # null path.
    subject_context: Optional[dict] = None


class DqIssue(DqIssueSummary):
    """One issue WITH its provenance — served by ``GET /dq/issues/{id}``.

    ``source_record_ids`` is the content-addressed lineage: the raw feed
    records this finding was raised over. It is a first-class provenance
    field and it has not gone anywhere — but it is served HERE, per issue,
    not by the queue listing (handoff 0030).

    Why (measured on the live queue, 98,497 issues): the ids are 716 MB of
    the 850 MB the whole-queue listing used to return — 11.5 million
    identifiers, up to 34,835 on a single issue — for a list view that
    never displayed more than a joined string of them. Moving them to the
    per-issue endpoint is not a reduction in provenance: every row in the
    queue links to its own issue, and this endpoint answers with the
    complete, untruncated array. Nothing is summarised, sampled, or capped.
    """

    source_record_ids: Optional[list[str]]


#: How many issues one page of ``GET /dq/issues`` returns when the caller
#: does not ask for a size. Sized so the page paints immediately on the
#: live queue and a steward still sees a screenful of work.
DEFAULT_PAGE_LIMIT = 50

#: The hard ceiling on one page. Enforced by FastAPI (``le=``), so an
#: unbounded request is IMPOSSIBLE rather than discouraged: there is no
#: value of ``limit`` — absent, huge, negative, zero — that makes this
#: endpoint return the whole queue. Anything outside 1..200 is a 422.
MAX_PAGE_LIMIT = 200


class DqIssuePage(BaseModel):
    """One page of the queue, plus the truth about the rest of it.

    ``total`` is counted by the database over EXACTLY the rows this filter
    selects — the whole queue, not the page — so nothing that reads this
    response has to mistake "what I loaded" for "what exists".
    """

    issues: list[DqIssueSummary]
    #: Issues matching ``status``/``severity`` across the WHOLE queue.
    total: int
    #: The page size actually applied (the caller's, or the default).
    limit: int
    #: Pass back as ``cursor`` to get the next page. Null on the last page.
    next_cursor: Optional[str]
    #: True when more rows match beyond this page.
    has_more: bool


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


#: The queue columns (handoff 0030): everything the list shows, and NOT
#: source_record_ids — 716 MB of the 850 MB the unbounded list used to
#: return, for a field the list view only ever joined into a string.
_SELECT_ISSUES = (
    "SELECT issue_id, issue_type, severity, status, owner, title, description, "
    "created_at, resolved_at, resolution, resolution_minutes, "
    "subject_context "
    "FROM dq.issues"
)

#: The per-issue columns: the queue columns PLUS the provenance array,
#: appended LAST so one row-mapper serves both shapes (a list row is a
#: strict prefix of a detail row).
_SELECT_ISSUE_DETAIL = (
    "SELECT issue_id, issue_type, severity, status, owner, title, description, "
    "created_at, resolved_at, resolution, resolution_minutes, "
    "subject_context, source_record_ids "
    "FROM dq.issues"
)

#: Deterministic AND total (handoff 0030): ``created_at`` alone is neither —
#: the live queue holds 98,497 rows across THIRTY-ONE distinct created_at
#: values, so ties of thousands of rows would order arbitrarily and pages
#: could drop or duplicate rows between requests. ``issue_id`` is the
#: primary key, so (created_at, issue_id) is unique over the whole table:
#: exactly one row sorts after any given row. Ascending — oldest first,
#: the order the queue has always had, and the order in which new issues
#: land at the END so page positions stay stable while a run is writing.
_ORDER_BY = " ORDER BY created_at, issue_id"

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


def _summary_from_row(r) -> DqIssueSummary:
    """A queue row. Works on a detail row too — the list columns are a
    strict prefix of the detail columns."""
    return DqIssueSummary(
        issue_id=str(r[0]),
        issue_type=r[1],
        severity=r[2],
        status=r[3],
        owner=r[4],
        title=r[5],
        description=r[6],
        created_at=r[7],
        resolved_at=r[8],
        resolution=r[9],
        resolution_minutes=r[10],
        # Served exactly as stored, including NULL. The API never invents a
        # label the calc runner could not resolve.
        subject_context=r[11],
    )


def _issue_from_row(r) -> DqIssue:
    """A detail row: the queue columns plus the provenance array."""
    return DqIssue(
        **_summary_from_row(r).model_dump(),
        source_record_ids=list(r[12]) if r[12] is not None else None,
    )


def _encode_cursor(created_at: dt.datetime, issue_id) -> str:
    """An opaque position in the (created_at, issue_id) ordering.

    Base64url of ``<iso8601>|<uuid>``. Opaque because it is a position in
    an ordering this endpoint owns, not a contract a caller should build by
    hand — and it is only ever produced by this endpoint.
    """
    raw = f"{created_at.isoformat()}|{issue_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[dt.datetime, uuid.UUID]:
    """The reverse, refusing loudly.

    A cursor we cannot read is a 422 in plain words, never a silent reset
    to page one: quietly re-serving the first page would make a caller
    walking the queue believe they had seen rows they never received.
    """
    bad = HTTPException(
        status_code=422,
        detail=(
            "That page marker is not one Headway issued. Page markers come "
            "from the 'next_cursor' field of a previous /dq/issues "
            "response — start again without one to read the queue from the "
            "beginning."
        ),
    )
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        created_at_text, _, issue_id_text = raw.partition("|")
        if not issue_id_text:
            raise ValueError("no separator")
        created_at = dt.datetime.fromisoformat(created_at_text)
        issue_id = uuid.UUID(issue_id_text)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise bad
    return created_at, issue_id


def _validate_queue_filters(
    status: Optional[str], severity: Optional[str]
) -> None:
    """The queue filter vocabulary check, shared by every caller that reads
    the queue (the human endpoint and the machine mirror, handoff 0039)."""
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{status}' is not a data-quality status Headway knows. "
                f"Valid statuses are: {', '.join(VALID_STATUSES)}."
            ),
        )
    if severity is not None and severity not in KNOWN_SEVERITIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{severity}' is not a data-quality severity Headway "
                f"knows. Valid severities are: "
                f"{', '.join(KNOWN_SEVERITIES)}."
            ),
        )


def query_issue_page(
    db,
    status: Optional[str],
    severity: Optional[str],
    limit: int,
    cursor: Optional[str],
) -> DqIssuePage:
    """One bounded page of the queue, VERBATIM (handoff 0030). Factored out
    of ``list_issues`` so the machine-key mirror (handoff 0039) serves the
    EXACT same rows, total, cursor, and has_more from the same SQL — the two
    can never drift. Caller validates the filter vocabulary first."""
    where: list[str] = []
    params: list = []
    if status is not None:
        where.append("status = %s")
        params.append(status)
    if severity is not None:
        where.append("severity = %s")
        params.append(severity)
    filter_sql = (" WHERE " + " AND ".join(where)) if where else ""
    filter_params = tuple(params)

    # The total is counted, never inferred from the page — a page-derived
    # total would be exactly the "of what's loaded" lie this endpoint
    # exists to remove. Measured 19–35 ms on the live 98k-row queue.
    total = db.execute(
        "SELECT count(*) FROM dq.issues" + filter_sql, filter_params
    ).fetchone()[0]

    page_where = list(where)
    page_params = list(params)
    if cursor is not None:
        created_at, issue_id = _decode_cursor(cursor)
        # Row comparison against the FULL sort key: strictly after this
        # exact row, ties included.
        page_where.append("(created_at, issue_id) > (%s, %s)")
        page_params.extend([created_at, issue_id])
    sql = _SELECT_ISSUES
    if page_where:
        sql += " WHERE " + " AND ".join(page_where)
    sql += _ORDER_BY + " LIMIT %s"
    # One row past the page: its existence IS has_more, so no second count
    # is needed and the answer cannot disagree with the rows returned.
    page_params.append(limit + 1)
    rows = db.execute(sql, tuple(page_params)).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    issues = [_summary_from_row(r) for r in rows]
    next_cursor = (
        _encode_cursor(rows[-1][7], rows[-1][0]) if has_more and rows else None
    )
    return DqIssuePage(
        issues=issues,
        total=total,
        limit=limit,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get("/dq/issues", response_model=DqIssuePage)
def list_issues(
    status: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    cursor: Optional[str] = Query(default=None),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> DqIssuePage:
    """One BOUNDED page of the data-quality queue (handoff 0030).

    Until this wave the endpoint returned every row it had. On the live
    queue that measured **98,497 issues, 850 MB of JSON, 17 seconds**, and
    it froze the browser tab of the screen a data steward lives in. There
    is now no way to ask for that: ``limit`` defaults to 50 and is capped
    at 200, and pages are walked with the opaque ``cursor`` from the
    previous response.

    **Provenance moved, it did not go away.** ``source_record_ids`` is not
    in these rows; ``GET /dq/issues/{id}`` serves it, complete and
    untruncated, for the issue actually being worked. 716 MB of that 850 MB
    was this one field.

    **Paging is keyset, on (created_at, issue_id) ascending** — the primary
    key breaks every tie, so the ordering is total and a row can neither be
    skipped nor served twice while new findings land behind the reader.

    ``total`` is the count over the whole queue under the same filters, so
    a caller can always say what it has NOT loaded.
    """
    _validate_queue_filters(status, severity)
    return query_issue_page(db, status, severity, limit, cursor)


class DqIssueCounts(BaseModel):
    """Counts for the /dq summary cards (handoff 0017, design point 2):
    counted over EXACTLY the rows GET /dq/issues serves under the same
    filter, so a card total can never disagree with the table below it.
    Missing severities/statuses appear as explicit zeros.

    Since handoff 0030 the list endpoint serves ONE PAGE, so this endpoint
    is the only place a whole-queue tally comes from — which is what it has
    always meant. Every screen that shows a queue-wide number reads it
    here, never by counting rows it happens to have loaded.
    """

    total: int
    by_severity: dict[str, int]
    by_status: dict[str, int]
    #: Total recorded resolution effort over the same rows, in whole
    #: minutes (migration 0016). Workflow metadata a steward typed — NEVER
    #: a reported regulatory figure. Zero here means "nobody recorded any
    #: minutes", which is exactly what a sum of no measurements is; an
    #: individual unmeasured issue still carries null on its own row.
    #: Added in handoff 0030 because the /dq header used to sum this from
    #: the whole downloaded queue, and a page-sum would have silently
    #: become "effort on the 50 issues you can see".
    resolution_minutes_total: int


#: The counts query: the SAME table and the SAME optional status filter as
#: GET /dq/issues, but counted by the database instead of fetching every row
#: (handoff 0023, design point 1). The previous implementation pulled all
#: rows (41,646 live) and counted in Python: ~4.6–5.9 s measured server-side;
#: this GROUP BY measured ~21 ms on the same live queue (EXPLAIN ANALYZE in
#: handoff 0023 evidence). No pre-aggregation, no staleness: every request
#: counts the live rows. A card total still can never disagree with the
#: table below it — same WHERE clause, same rows, grouped not re-derived.
#: The effort sum rides the same single scan (handoff 0030).
_COUNT_ISSUES = (
    "SELECT severity, status, count(*), "
    "coalesce(sum(resolution_minutes), 0) FROM dq.issues"
)


def query_issue_counts(db, status: Optional[str]) -> DqIssueCounts:
    """The whole-queue severity/status tally, VERBATIM (handoff 0017/0023).
    Factored out of ``count_issues`` so the machine mirror (handoff 0039)
    counts EXACTLY the rows the list serves under the same filter — a card
    total can never disagree with the page below it, human or machine.
    Caller validates the filter vocabulary first."""
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
    minutes_total = 0
    for severity, row_status, count, minutes in rows:
        # An unexpected vocabulary value still counts, honestly, under its
        # own key — never dropped, never bucketed as something else.
        by_severity[severity] = by_severity.get(severity, 0) + count
        by_status[row_status] = by_status.get(row_status, 0) + count
        total += count
        minutes_total += int(minutes or 0)
    return DqIssueCounts(
        total=total,
        by_severity=by_severity,
        by_status=by_status,
        resolution_minutes_total=minutes_total,
    )


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
    return query_issue_counts(db, status)


@router.get("/dq/issues/{issue_id}", response_model=DqIssue)
def get_issue(
    issue_id: str,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> DqIssue:
    """One issue by id (any signed-in role) — the deep-link target (handoff
    0026): a calculation refusal links straight to the exact finding that
    blocked it, and the UI must be able to show THAT finding without
    downloading the whole queue. Registered after /dq/issues/counts so the
    literal path wins.

    Since handoff 0030 this is ALSO where ``source_record_ids`` lives —
    the complete, untruncated provenance array for this one issue. The
    queue listing no longer carries it (716 MB of an 850 MB response for a
    field a list view only joined into a string); every queue row links
    here, so the walk from a finding to its raw records is one request, not
    a 850 MB download."""
    return query_issue_detail(db, issue_id)


def query_issue_detail(db, issue_id: str) -> DqIssue:
    """One issue by id, WITH its full untruncated provenance array, VERBATIM
    (handoff 0026/0030). Factored out of ``get_issue`` so the machine mirror
    (handoff 0039) serves the identical detail row and the same plain-language
    404 for a missing or malformed id."""
    try:
        uuid.UUID(issue_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail="No data-quality issue with that id exists.",
        )
    row = db.execute(
        _SELECT_ISSUE_DETAIL + " WHERE issue_id = %s", (issue_id,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No data-quality issue with that id exists.",
        )
    return _issue_from_row(row)


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
