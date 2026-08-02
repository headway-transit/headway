"""The revenue review queue: no-run boardings a human must classify, and the
justification note that makes the correction defensible (handoff 0040).

Some boardings arrive with no run assignment at all — the vehicle fired its
passenger counter while it was moving with nobody logged into a run. Most of
those are prep, pull-out and pull-in: a vehicle not in revenue service is not
carrying passengers (2026 NTD Policy Manual p. 128), so those boardings are
not unlinked passenger trips and the calculation excludes them on the
schedule's evidence. But a no-run boarding that happens in the MIDDLE of the
service day is genuinely ambiguous — it could be non-revenue prep, or it could
be an extra bus dispatch sent to recover a late route, running real riders
without a formal trip assignment. No rule in the manual separates those two,
so Headway does not guess: it HOLDS the boarding out of the reported figure
and asks a person.

This router is where that person answers. It reads the queue the calculation
wrote, and it records exactly one kind of decision: this boarding was revenue,
or it was not — **and here is why**. The justification note is required, by
this router and by the table's own CHECK constraint, because the point of the
whole wave is that the correction can be DEFENDED in a triennial review rather
than asserted.

Three refusals are load-bearing here and none of them has a bypass:

- **No blank-note path.** A verdict with no reason is rejected (422). There is
  no "classify anyway" shortcut, and no "include the pending ones" shortcut
  either — a boarding of unknown revenue status stays out of a certifiable
  figure until somebody says why it belongs in one.
- **Nothing is patched in place.** Classifying a boarding writes no
  computed.metric_values row. The verdict changes the figure only when the
  calculation is re-run and recomputes it from its inputs.
- **A certified figure is never rewritten.** If the boarding's service date
  falls inside a period whose Unlinked Passenger Trips figure is already
  certified, this router refuses (409) and says why: the certification names a
  number, and quietly changing what that number would be next time would make
  the attestation describe something that no longer exists.

Authorization mirrors the DQ resolution workflow it is built on: anyone signed
in can read the queue; classifying is data-steward-grade and every
classification lands in the audit trail inside the same transaction.
"""

from __future__ import annotations

import base64
import binascii
import datetime as dt
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from ..audit import write_event
from ..auth import Identity
from ..authz import require_at_least, require_authenticated
from ..db import get_db

router = APIRouter(tags=["revenue-review"])

#: The two answers a human may give. 'revenue' counts the boarding as an
#: unlinked passenger trip on the next run; 'non_revenue' excludes it. There
#: is deliberately no third value: "not sure" is what leaving it in the queue
#: already means, and inventing a "probably" state would put a guess into a
#: reported number.
VALID_VERDICTS = ("revenue", "non_revenue")

#: Queue filters. 'pending' is the work; 'classified' is the decision history
#: (which is also the receipt trail, so it must stay readable forever).
VALID_QUEUE_STATUSES = ("pending", "classified")

#: The metric whose figure these boardings are held out of.
REVIEWED_METRIC = "upt"

#: The finding the calculation raises for each held boarding. Classifying a
#: boarding closes its finding through the ordinary DQ resolution workflow, so
#: the two queues can never disagree about what is still open.
PENDING_ISSUE_TYPE = "boarding_pending_revenue_review"

#: One page of the queue when the caller does not ask for a size — the DQ
#: queue's number (handoff 0030), for the same reason: a screenful of work
#: that paints immediately.
DEFAULT_PAGE_LIMIT = 50

#: The hard ceiling, enforced by FastAPI (``le=``) so no value of ``limit``
#: can ask for the whole table.
MAX_PAGE_LIMIT = 200


class BoardingReview(BaseModel):
    """One boarding awaiting a decision — or the record of the decision made.

    Everything here was frozen when the calculation flagged the boarding, so
    the row reads the same years later even if the feed is re-ingested or the
    vehicle is renumbered. Nothing is re-derived at read time and no label is
    invented: an absent vehicle is served as null, not as "unknown".
    """

    passenger_event_id: str
    source_record_id: str
    service_date: dt.date
    event_timestamp: dt.datetime
    #: The feed's own vehicle identifier — for the exports that produce these
    #: rows, the fleet number a dispatcher says out loud. Null when the feed
    #: carried none.
    vehicle_id: Optional[str]
    #: Boardings recorded on this event. Never null: a NULL-count boarding has
    #: no number to classify and is warned separately.
    event_count: int
    #: Always 'pending_review' — what the calculation concluded on its own,
    #: which is that it declined to guess. Served so a reviewer reads
    #: Headway's own position instead of inferring it.
    suggested_verdict: str
    #: The calculation's own words for why it could not decide.
    suggested_reason: str
    calc_name: str
    calc_version: str
    period_start: dt.date
    period_end: dt.date
    first_seen_at: dt.datetime
    #: Null while pending; 'revenue' or 'non_revenue' once decided.
    verdict: Optional[str]
    #: The analyst's reason, in their own words. Null only while pending —
    #: there is no classified row without one.
    justification: Optional[str]
    classified_by: Optional[str]
    classified_at: Optional[dt.datetime]
    #: The data-quality finding this classification closed, when one was open.
    dq_issue_id: Optional[str]


class BoardingReviewPage(BaseModel):
    """One page of the queue, plus the truth about the rest of it."""

    boardings: list[BoardingReview]
    #: Rows matching the filter across the WHOLE queue — never a page count,
    #: so nothing that reads this response can mistake "what I loaded" for
    #: "what exists".
    total: int
    limit: int
    #: Pass back as ``cursor`` for the next page. Null on the last page.
    next_cursor: Optional[str]
    has_more: bool


class BoardingReviewCounts(BaseModel):
    """The queue-wide tally, counted by the database over exactly the rows the
    list serves — so a card can never disagree with the table below it."""

    #: Rows still awaiting a decision.
    pending: int
    #: Boardings (the sum of ``event_count``) those pending rows represent —
    #: the number actually held out of the figure, which is not the same as
    #: the number of rows.
    pending_boardings: int
    classified: int
    classified_revenue: int
    classified_non_revenue: int
    #: Boardings a human ruled INTO the figure, and out of it. These are the
    #: numbers the next calculation run will move.
    classified_revenue_boardings: int
    classified_non_revenue_boardings: int


class ClassifyRequest(BaseModel):
    """A verdict and the reason for it. The reason is not optional."""

    verdict: str
    justification: str = Field(min_length=1)

    @field_validator("verdict")
    @classmethod
    def _known_verdict(cls, v: str) -> str:
        if v not in VALID_VERDICTS:
            raise ValueError(
                f"'{v}' is not a classification Headway knows. A no-run "
                f"boarding is either revenue ('revenue' — real riders, count "
                f"it) or it is not ('non_revenue' — prep, deadhead, a "
                f"double-fired counter). If you are not sure yet, leave it in "
                f"the queue: an undecided boarding stays out of the reported "
                f"figure, which is the safe answer."
            )
        return v

    @field_validator("justification")
    @classmethod
    def _justification_says_something(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "Write why you classified this boarding the way you did — for "
                "example \"unit's counter double-fired during layover, "
                "confirmed with dispatch\" or \"extra bus sent to recover the "
                "route at 15:10, these are real riders\". This note is part "
                "of the figure's receipt: it is what lets the agency defend "
                "the correction in a triennial review instead of merely "
                "asserting it, so there is no way to record a decision "
                "without one."
            )
        return v.strip()


class ClassifyResponse(BaseModel):
    passenger_event_id: str
    verdict: str
    justification: str
    classified_by: str
    classified_at: dt.datetime
    #: The data-quality finding closed alongside this classification, or null
    #: when no open finding was found for this boarding — recorded honestly
    #: rather than papered over.
    dq_issue_id: Optional[str]
    audit_event_id: int
    #: Said out loud in the response, not just in the UI: the figure does not
    #: move until the calculation is re-run.
    recompute_required: bool = True


#: The queue columns. Ordered so one row-mapper serves every read.
_SELECT_REVIEWS = (
    "SELECT passenger_event_id, source_record_id, service_date, "
    "event_timestamp, vehicle_id, event_count, suggested_verdict, "
    "suggested_reason, calc_name, calc_version, period_start, period_end, "
    "first_seen_at, verdict, justification, classified_by, classified_at, "
    "dq_issue_id FROM dq.boarding_revenue_reviews"
)

#: Deterministic AND total, the DQ queue's discipline (handoff 0030):
#: event_timestamp alone ties (a vehicle can fire twice in the same second),
#: and passenger_event_id is the primary key, so exactly one row sorts after
#: any given row. Ascending — oldest boarding first, so new flags land at the
#: END and page positions stay stable while a calc run is writing.
_ORDER_BY = " ORDER BY event_timestamp, passenger_event_id"

_SELECT_ONE = _SELECT_REVIEWS + " WHERE passenger_event_id = %s"

#: The tally, in one pass over the same rows the list serves.
_COUNT_REVIEWS = (
    "SELECT verdict, count(*), coalesce(sum(event_count), 0) "
    "FROM dq.boarding_revenue_reviews GROUP BY verdict"
)

#: Is any Unlinked Passenger Trips figure covering this boarding's service
#: date already CERTIFIED? A certification attests to a specific number; a
#: classification that would change that number on the next run must not be
#: recorded silently behind it.
_SELECT_CERTIFIED_COVER = (
    "SELECT metric_value_id, period_start, period_end, scope "
    "FROM computed.metric_values "
    "WHERE metric = %s AND certification_status = 'certified' "
    "AND period_start <= %s AND period_end > %s "
    "ORDER BY period_start LIMIT 1"
)

#: The open finding raised for this exact boarding, found by the raw record
#: both rows cite. Scoped to the one issue_type, so this reads a handful of
#: rows and never scans the queue.
_SELECT_OPEN_FINDING = (
    "SELECT issue_id FROM dq.issues "
    "WHERE issue_type = %s AND status IN ('open', 'owned') "
    "AND %s = ANY(source_record_ids) "
    "ORDER BY created_at, issue_id LIMIT 1"
)

_RESOLVE_FINDING = (
    "UPDATE dq.issues SET status = 'resolved', resolved_at = now(), "
    "resolution = %s WHERE issue_id = %s AND status IN ('open', 'owned')"
)

#: The classification itself. The WHERE clause carries the concurrency guard:
#: only a row that is still pending can be classified, so two reviewers
#: racing produce one decision and one honest 409, never a silent overwrite.
_CLASSIFY = (
    "UPDATE dq.boarding_revenue_reviews SET verdict = %s, justification = %s, "
    "classified_by = %s, classified_at = now(), dq_issue_id = %s "
    "WHERE passenger_event_id = %s AND verdict IS NULL "
    "RETURNING classified_at"
)


def _review_from_row(r) -> BoardingReview:
    return BoardingReview(
        passenger_event_id=str(r[0]),
        source_record_id=r[1],
        service_date=r[2],
        event_timestamp=r[3],
        vehicle_id=r[4],
        event_count=r[5],
        suggested_verdict=r[6],
        suggested_reason=r[7],
        calc_name=r[8],
        calc_version=r[9],
        period_start=r[10],
        period_end=r[11],
        first_seen_at=r[12],
        verdict=r[13],
        justification=r[14],
        classified_by=r[15],
        classified_at=r[16],
        dq_issue_id=str(r[17]) if r[17] is not None else None,
    )


def _encode_cursor(event_timestamp: dt.datetime, passenger_event_id: str) -> str:
    """An opaque position in the (event_timestamp, passenger_event_id)
    ordering — base64url of ``<iso8601>|<id>``. Opaque because it is a
    position in an ordering this endpoint owns, not a contract a caller should
    build by hand."""
    raw = f"{event_timestamp.isoformat()}|{passenger_event_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> tuple[dt.datetime, str]:
    """The reverse, refusing loudly. A marker we cannot read is a 422 in plain
    words, never a silent reset to page one — quietly re-serving the first
    page would make a reviewer walking the queue believe they had seen
    boardings they never received."""
    bad = HTTPException(
        status_code=422,
        detail=(
            "That page marker is not one Headway issued. Page markers come "
            "from the 'next_cursor' field of a previous review-queue "
            "response — start again without one to read the queue from the "
            "beginning."
        ),
    )
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        timestamp_text, sep, event_id = raw.partition("|")
        if not sep or not event_id:
            raise ValueError("no separator")
        event_timestamp = dt.datetime.fromisoformat(timestamp_text)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise bad
    return event_timestamp, event_id


def _status_filter(status: Optional[str]) -> str:
    if status == "pending":
        return "verdict IS NULL"
    if status == "classified":
        return "verdict IS NOT NULL"
    return ""


@router.get("/revenue-review/boardings", response_model=BoardingReviewPage)
def list_boardings(
    status: str = Query(default="pending"),
    limit: int = Query(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT),
    cursor: Optional[str] = Query(default=None),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> BoardingReviewPage:
    """One bounded page of the revenue review queue.

    Default ``status=pending`` — the work. ``status=classified`` reads the
    decision history, which is also the receipt trail behind every corrected
    figure, so it stays readable forever. Pages are keyset-walked on
    (event_timestamp, passenger_event_id) ascending: the primary key breaks
    every tie, so a boarding can neither be skipped nor served twice while a
    calculation run flags new ones behind the reader.
    """
    if status not in VALID_QUEUE_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{status}' is not a review-queue filter Headway knows. Use "
                f"'pending' for boardings still waiting on a decision, or "
                f"'classified' for the ones already decided."
            ),
        )
    where = [_status_filter(status)]
    params: list = []

    total = db.execute(
        "SELECT count(*) FROM dq.boarding_revenue_reviews WHERE "
        + where[0],
        tuple(params),
    ).fetchone()[0]

    page_where = list(where)
    page_params = list(params)
    if cursor is not None:
        event_timestamp, event_id = _decode_cursor(cursor)
        page_where.append("(event_timestamp, passenger_event_id) > (%s, %s)")
        page_params.extend([event_timestamp, event_id])
    sql = _SELECT_REVIEWS + " WHERE " + " AND ".join(page_where) + _ORDER_BY
    sql += " LIMIT %s"
    # One row past the page: its existence IS has_more, so the answer can
    # never disagree with the rows returned.
    page_params.append(limit + 1)
    rows = db.execute(sql, tuple(page_params)).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        _encode_cursor(rows[-1][3], str(rows[-1][0])) if has_more and rows else None
    )
    return BoardingReviewPage(
        boardings=[_review_from_row(r) for r in rows],
        total=total,
        limit=limit,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/revenue-review/boardings/counts", response_model=BoardingReviewCounts
)
def count_boardings(
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> BoardingReviewCounts:
    """The queue-wide tally: how many boardings are held, and how many a human
    has already ruled in or out. Counted by the database over exactly the rows
    the list serves — registered before the ``{passenger_event_id}`` route so
    the literal path wins."""
    rows = db.execute(_COUNT_REVIEWS, ()).fetchall()
    pending = pending_boardings = 0
    revenue = non_revenue = 0
    revenue_boardings = non_revenue_boardings = 0
    for verdict, count, boardings in rows:
        count = int(count or 0)
        boardings = int(boardings or 0)
        if verdict is None:
            pending += count
            pending_boardings += boardings
        elif verdict == "revenue":
            revenue += count
            revenue_boardings += boardings
        elif verdict == "non_revenue":
            non_revenue += count
            non_revenue_boardings += boardings
    return BoardingReviewCounts(
        pending=pending,
        pending_boardings=pending_boardings,
        classified=revenue + non_revenue,
        classified_revenue=revenue,
        classified_non_revenue=non_revenue,
        classified_revenue_boardings=revenue_boardings,
        classified_non_revenue_boardings=non_revenue_boardings,
    )


def _load_review(db, passenger_event_id: str) -> BoardingReview:
    row = db.execute(_SELECT_ONE, (passenger_event_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No boarding with that identifier is in the revenue review "
                "queue. The queue is written by the calculation: a boarding "
                "appears here only after a run has held it out of the "
                "figure."
            ),
        )
    return _review_from_row(row)


@router.get(
    "/revenue-review/boardings/{passenger_event_id}",
    response_model=BoardingReview,
)
def get_boarding(
    passenger_event_id: str,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> BoardingReview:
    """One boarding by id — the deep-link target, so a finding or a receipt
    can point straight at the boarding it concerns."""
    return _load_review(db, passenger_event_id)


@router.post(
    "/revenue-review/boardings/{passenger_event_id}/classify",
    response_model=ClassifyResponse,
)
def classify_boarding(
    passenger_event_id: str,
    body: ClassifyRequest,
    request: Request,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> ClassifyResponse:
    """Record one human decision about one held boarding, with its reason.

    Data-steward-grade, exactly like resolving a data-quality issue — this IS
    a data-quality resolution, it just happens to change what the next figure
    counts. The verdict, the note, the person and the time are written
    together, the boarding's open finding is closed in the same transaction,
    and the audit event commits with them or not at all.

    Refuses loudly and specifically:

    - **404** — no such boarding in the queue.
    - **409** — already classified. A decision is not re-decided in place; the
      trail must stay honest about who said what and when.
    - **409** — the boarding falls inside an already-CERTIFIED Unlinked
      Passenger Trips period. A certification attests to a number; recording a
      change that would move that number on the next run would leave the
      attestation describing a figure nobody computed.
    - **422** — a blank justification. There is no note-free path.
    """
    with db.transaction():
        existing = _load_review(db, passenger_event_id)
        if existing.verdict is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This boarding was already classified as "
                    f"{'revenue' if existing.verdict == 'revenue' else 'non-revenue'} "
                    f"by {existing.classified_by}. A classification is not "
                    f"re-decided in place — the receipt has to stay honest "
                    f"about who said what, and when. If the decision was "
                    f"wrong, raise it with the data steward who made it and "
                    f"record the correction as its own reviewed finding."
                ),
            )
        certified = db.execute(
            _SELECT_CERTIFIED_COVER,
            (REVIEWED_METRIC, existing.service_date, existing.service_date),
        ).fetchone()
        if certified is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This boarding is on "
                    f"{existing.service_date.isoformat()}, which falls inside "
                    f"a reporting period whose Unlinked Passenger Trips "
                    f"figure has already been certified "
                    f"({certified[1].isoformat()} to {certified[2].isoformat()}, "
                    f"scope {certified[3]}). Headway will not record a "
                    f"classification that would change a certified figure the "
                    f"next time the calculation runs: somebody signed their "
                    f"name to that number, and it must keep meaning what it "
                    f"meant when they signed. If this boarding really was "
                    f"misclassified, the period has to be re-opened and "
                    f"re-certified deliberately, by a certifying official, so "
                    f"the change is visible instead of quiet."
                ),
            )
        finding = db.execute(
            _SELECT_OPEN_FINDING,
            (PENDING_ISSUE_TYPE, existing.source_record_id),
        ).fetchone()
        dq_issue_id = str(finding[0]) if finding is not None else None
        row = db.execute(
            _CLASSIFY,
            (
                body.verdict,
                body.justification,
                identity.username,
                dq_issue_id,
                passenger_event_id,
            ),
        ).fetchone()
        if row is None:
            # Somebody else classified it between the read and the write.
            raise HTTPException(
                status_code=409,
                detail=(
                    "This boarding was classified by someone else while your "
                    "decision was being recorded. Nothing was changed — "
                    "refresh the queue to see the decision that landed."
                ),
            )
        classified_at = row[0]
        if dq_issue_id is not None:
            db.execute(
                _RESOLVE_FINDING,
                (
                    _finding_resolution(
                        body.verdict, body.justification, identity.username
                    ),
                    dq_issue_id,
                ),
            )
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="boarding_revenue_classify",
            subject_kind="dq.boarding_revenue_reviews",
            subject_id=passenger_event_id,
            detail={
                "verdict": body.verdict,
                # The note is the point of the audit row, not a footnote to
                # it: an auditor reading audit.events alone must be able to
                # see WHY, without joining anywhere.
                "justification": body.justification,
                "suggested_verdict": existing.suggested_verdict,
                "service_date": existing.service_date.isoformat(),
                "vehicle_id": existing.vehicle_id,
                "event_count": existing.event_count,
                "source_record_id": existing.source_record_id,
                "dq_issue_id": dq_issue_id,
                "classified_by_role": identity.role,
                # Stated in the trail so nobody later reads this event as the
                # moment the number changed. It was not.
                "figure_recomputed": False,
            },
        )
    return ClassifyResponse(
        passenger_event_id=passenger_event_id,
        verdict=body.verdict,
        justification=body.justification,
        classified_by=identity.username,
        classified_at=classified_at,
        dq_issue_id=dq_issue_id,
        audit_event_id=audit_event_id,
    )


def _finding_resolution(verdict: str, justification: str, actor: str) -> str:
    """The resolution text written onto the boarding's data-quality finding.

    Built server-side from the decision, never free text a caller supplies for
    the finding directly — so the DQ trail and the review trail can never tell
    two different stories about the same boarding.
    """
    ruling = (
        "REVENUE — counted as unlinked passenger trips"
        if verdict == "revenue"
        else "NON-REVENUE — excluded from unlinked passenger trips"
    )
    return (
        f"Classified {ruling} by {actor} in the revenue review queue "
        f"(handoff 0040). Justification: {justification} "
        f"This decision changes no figure that has already been computed; it "
        f"takes effect the next time the calculation runs over a period "
        f"containing this boarding."
    )
