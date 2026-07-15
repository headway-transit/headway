"""Safety & Security event workflow (handoff 0010).

- POST /safety/events — validated manual entry (data steward or above,
  audited). The endpoint runs the deterministic classifier SYNCHRONOUSLY
  (headway_calc.sscls, sscls_v0 — calc-discipline code; this API never
  classifies anything itself) and returns the classification, the thresholds
  met, and a plain-language explanation with the tracker citation for each.
- GET /safety/events — list with filters (classification, month, mode); any
  signed-in role.
- POST /safety/events/{id}/supersede — append-only correction: a NEW event
  row is entered, classified, and linked from the original via
  superseded_by; originals are never edited or deleted (migration 0017
  enforces this with a trigger). Audited.
- GET /safety/deadlines — computed due dates: S&S-40 per open major event
  (occurred_at + 30 days — Exhibit 2, p. 4: "due no later than 30 days
  after the date of the event"); S&S-50 per month and mode, due end of the
  following month (p. 4 + Exhibit 3, p. 5), INCLUDING zero-event months for
  every operated mode ("even if no event occurs") — operated modes derive
  exactly the way the per-mode calc path derives the mode dimension
  (handoff 0009; headway_calc.ss50.SELECT_OPERATED_MODES_SQL).

Every regulatory sentence above is a pointer to
services/calc/REGULATORY_TRACKER.md, "Verified — Safety & Security
reporting (verified 2026-07-12)" — never a number from memory.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from headway_calc import sscls
from headway_calc.mr20 import month_period
from headway_calc.ss50 import SELECT_OPERATED_MODES_SQL, ss50_due_date

from ..audit import write_event
from ..auth import Identity
from ..authz import require_at_least, require_authenticated
from ..db import get_db

router = APIRouter(tags=["safety"])

UTC = dt.timezone.utc

VALID_CLASSIFICATIONS = (sscls.MAJOR, sscls.NON_MAJOR, sscls.NOT_REPORTABLE)

_SS40_CITATION = (
    "The S&S-40 Major Event Report is 'due no later than 30 days after the "
    "date of the event.' (2026 S&S Policy Manual, Exhibit 2, p. 4 — "
    "verified 2026-07-12, REGULATORY_TRACKER.md, 'Verified — Safety & "
    "Security reporting')"
)

_SS50_CITATION = (
    "The S&S-50 Non-Major Monthly Summary is submitted 'for each mode and "
    "TOS … every month, even if no event occurs', due end of the following "
    "month (January→Feb 28 … December→Jan 31). (2026 S&S Policy Manual, "
    "p. 4 + Exhibit 3, p. 5 — verified 2026-07-12, REGULATORY_TRACKER.md, "
    "'Verified — Safety & Security reporting')"
)

#: The month-bucketing convention this router shares with the S&S-50
#: generator — the SAME string headway_calc.ss50.build_ss50_summary declares
#: on its package, surfaced here so API consumers see it too (hardening
#: pass 2026-07-13: the UTC convention was declared by ss50 but invisible
#: on /safety/deadlines and /safety/events).
PERIOD_CONVENTION = "half-open [period_start, period_end), UTC, on occurred_at"

_PERIOD_NOTE = (
    "Months are bucketed by when the event occurred in Coordinated "
    "Universal Time (UTC), not local time: an event late on the last "
    "evening of a month local time may fall into the next month's bucket. "
    "Enter event times with their time zone and Headway places them "
    "consistently."
)


#: Sane caps for SafetyEventCreate's free-text fields (each lands in an
#: unbounded TEXT column — migration 0017): plain-language 422 instead of
#: accepting an arbitrarily large payload. Narrative is generous (a full
#: incident account); the rest are labels.
_TEXT_LIMITS = {
    "mode": ("The mode", 50),
    "type_of_service": ("The type of service", 50),
    "narrative": ("The narrative", 20_000),
    "location": ("The location", 1_000),
}


def _too_long(field_plain: str, limit: int, actual: int) -> ValueError:
    """One plain-language shape for every over-length refusal (hardening
    pass 2026-07-13: request fields bound for TEXT columns get sane caps)."""
    return ValueError(
        f"{field_plain} is {actual:,} characters long, and Headway accepts "
        f"at most {limit:,} here. Please shorten it — if you need to keep "
        f"more detail, attach it to the agency's own incident file and "
        f"reference it."
    )


class SafetyEventCreate(BaseModel):
    """One safety event as entered by agency staff. Field descriptions are
    plain language — the entry form asks questions, not jargon."""

    occurred_at: dt.datetime = Field(
        description="When the event happened (include the time zone)."
    )
    mode: str = Field(
        min_length=1,
        description=(
            "The ONE mode this event is reported in. If more than one mode "
            "was involved, apply the Predominant Use Rule (p. 15): rail "
            "wins over non-rail; otherwise pick the mode carrying more "
            "passengers."
        ),
    )
    type_of_service: Optional[str] = Field(
        default=None,
        description="Type of service (e.g. DO for directly operated, PT for purchased transportation).",
    )
    event_category: str
    narrative: str = Field(
        min_length=1, description="What happened, in your own words."
    )
    location: Optional[str] = None
    fatalities: int = Field(
        default=0,
        description=(
            "How many people died (confirmed within 30 days; suicides are "
            "included — Exhibit 5, p. 16). Do NOT count deaths from "
            "illness, overdose, or natural causes (p. 20); DO count a "
            "death of undetermined cause in a rail right-of-way that may "
            "be the result of collision or electrocution (p. 20)."
        ),
    )
    injuries: int = Field(
        default=0,
        description=(
            "How many people were taken directly from the scene for "
            "medical care (Exhibit 5, p. 16 — immediate transport, not "
            "later self-referral). Do NOT count transport solely for "
            "illness, natural causes, exposure, intoxication, overdose, "
            "or an unrelated mental-health evaluation, or declarations of "
            "self-harm with no evident injury (p. 22); DO count an injury "
            "the event caused, e.g. a passenger's heart attack caused by "
            "a collision (p. 22)."
        ),
    )
    property_damage_usd: Optional[Decimal] = Field(
        default=None,
        description=(
            "Estimated property damage in dollars. Sum the damage to ALL "
            "vehicles and property involved or affected — transit and "
            "non-transit — plus the cost of clearing wreckage (p. 25; "
            "e.g. a $15,000 car plus $12,000 bus damage is reported as "
            "$27,000, Example 7A). Leave blank if not yet assessed — "
            "Headway never treats unknown damage as $0."
        ),
    )
    serious_injury: bool = Field(
        default=False,
        description=(
            "Rail only: did anyone suffer a serious injury (p. 21) — "
            "hospitalization for more than 48 hours within 7 days; a "
            "fracture of any bone (except simple fractures of fingers, "
            "toes, or nose); severe hemorrhages, or nerve, muscle, or "
            "tendon damage; an internal organ; or 2nd/3rd-degree burns or "
            "burns over 5% of the body surface? Answer yes even if the "
            "person was NOT transported from the scene — serious injuries "
            "'may or may not have been transported' (p. 21)."
        ),
    )
    substantial_damage: bool = Field(
        default=False,
        description=(
            "Rail: did the damage disrupt operations AND require towing, "
            "rescue (e.g. a rescue train), on-site maintenance, or "
            "immediate removal before safe operation (p. 25)? Do NOT "
            "count cracked windows; dents, bends, or small punctures; "
            "broken lights or mirrors; or removal under the vehicle's own "
            "power for minor repair, testing, or recorder download "
            "(p. 25). For cyber events: did the intrusion disrupt "
            "operations (Scenario G, p. 19)?"
        ),
    )
    towed: bool = Field(
        default=False,
        description=(
            "Was any vehicle (transit or not) towed away from the scene? "
            "For a non-rail collision involving a transit revenue vehicle "
            "this alone makes the event reportable (p. 17); for a rail "
            "collision, a tow-away IS substantial damage (Example 7C, "
            "p. 27)."
        ),
    )
    evacuation_life_safety: bool = Field(
        default=False,
        description=(
            "Were people evacuated from a transit facility or vehicle for "
            "life-safety reasons (p. 17)?"
        ),
    )
    assault_on_worker: bool = Field(
        default=False,
        description=(
            "Was a transit worker assaulted? An injury is NOT required for "
            "this to be reportable on the S&S-50 (p. 3)."
        ),
    )
    involves_transit_vehicle: bool = False
    involves_second_rail_vehicle: bool = False
    grade_crossing: bool = Field(
        default=False,
        description=(
            "Rail: did the collision occur at a rail grade crossing or "
            "intersection (p. 17)?"
        ),
    )
    # Migration 0018 (addendum correction round).
    runaway_train: bool = Field(
        default=False,
        description=(
            "Rail: did a revenue vehicle move uncommanded, uncontrolled, "
            "or unmanned — operator incapacitated, sleeping, or absent, or "
            "an electrical, mechanical, or software failure — on the "
            "mainline, in a yard, or in a shop (p. 17)?"
        ),
    )
    evacuation_to_rail_row: bool = Field(
        default=False,
        description=(
            "Rail: did people evacuate to the controlled rail "
            "right-of-way (transit-directed or self-evacuation)? "
            "Evacuation to a platform does not count unless it was for "
            "life safety (p. 17)."
        ),
    )

    @field_validator("mode", "type_of_service", "narrative", "location")
    @classmethod
    def _free_text_bounded(cls, v: Optional[str], info) -> Optional[str]:
        plain, limit = _TEXT_LIMITS[info.field_name]
        if v is not None and len(v) > limit:
            raise _too_long(plain, limit, len(v))
        return v

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_needs_timezone(cls, v: dt.datetime) -> dt.datetime:
        if v.tzinfo is None:
            raise ValueError(
                "Please include a time zone with the event time (for "
                "example 2026-06-15T14:30:00-05:00 or ...T19:30:00Z). "
                "Without one, Headway cannot place the event in the right "
                "reporting month."
            )
        return v

    @field_validator("event_category")
    @classmethod
    def _category_from_manual_vocabulary(cls, v: str) -> str:
        if v not in sscls.EVENT_CATEGORIES:
            raise ValueError(
                f"'{v}' is not an event category Headway knows. Please "
                f"pick one of: {', '.join(sscls.EVENT_CATEGORIES)}. "
                f"('cyber' covers cyber security events — Scenario G, "
                f"p. 19; use 'other' if nothing fits and describe it in "
                f"the narrative. Note: 'other' events use the p. 22 Other "
                f"Safety Events rules — two or more injuries for the "
                f"injury threshold. A hazardous material spill or act of "
                f"God is NOT an Other Safety Event per p. 22, but Headway "
                f"v0 has no category for them yet — if you are entering "
                f"one, say so in the narrative so the classification can "
                f"be reviewed.)"
            )
        return v

    @field_validator("fatalities", "injuries")
    @classmethod
    def _counts_not_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(
                "Fatalities and injuries are counts of people, so they "
                "must be zero or more."
            )
        return v

    @field_validator("property_damage_usd")
    @classmethod
    def _damage_not_negative(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < 0:
            raise ValueError(
                "Property damage must be zero or more dollars. Leave it "
                "blank if the damage has not been assessed yet."
            )
        return v


class ThresholdExplanation(BaseModel):
    threshold: str
    plain_language: str
    citation: str


class ClassificationResult(BaseModel):
    classification: str
    thresholds_met: list[str]
    explanations: list[ThresholdExplanation]
    non_major_basis: list[ThresholdExplanation]
    effective_category: str
    is_rail_mode: bool
    summary: str
    classifier_version: str


class SafetyEventCreated(BaseModel):
    event_id: str
    entered_at: dt.datetime
    result: ClassificationResult
    audit_event_id: int


class SafetyEventSuperseded(BaseModel):
    original_event_id: str
    replacement_event_id: str
    entered_at: dt.datetime
    result: ClassificationResult
    audit_event_id: int


class SafetyEventRecord(BaseModel):
    event_id: str
    occurred_at: dt.datetime
    mode: str
    type_of_service: Optional[str]
    event_category: str
    narrative: str
    location: Optional[str]
    fatalities: int
    injuries: int
    # Exact NUMERIC as a JSON string, never a float (repo non-negotiable).
    property_damage_usd: Optional[str]
    serious_injury: bool
    substantial_damage: bool
    towed: bool
    evacuation_life_safety: bool
    assault_on_worker: bool
    involves_transit_vehicle: bool
    involves_second_rail_vehicle: bool
    grade_crossing: bool
    runaway_train: bool
    evacuation_to_rail_row: bool
    entered_by: str
    entered_at: dt.datetime
    superseded_by: Optional[str]
    classification: Optional[str]
    thresholds_met: Optional[list[str]]
    classifier_version: Optional[str]
    classified_at: Optional[dt.datetime]
    #: How the ?month= filter buckets this event — the ss50 declaration,
    #: surfaced on every record (the list response shape is an array, so
    #: the convention travels per record rather than as an envelope field).
    period_convention: str = Field(
        default=PERIOD_CONVENTION,
        description=(
            "How the month filter buckets events: " + PERIOD_CONVENTION
            + ". " + _PERIOD_NOTE
        ),
    )


class Ss40Deadline(BaseModel):
    event_id: str
    occurred_at: dt.datetime
    mode: str
    event_category: str
    due_date: dt.date


class Ss50Deadline(BaseModel):
    month: str
    mode: str
    due_date: dt.date
    non_major_event_count: int
    zero_event: bool


class DeadlinesResponse(BaseModel):
    month: str
    #: The ss50-declared month-bucketing convention, plus its plain-language
    #: reading (period_note) — surfaced so a deadlines consumer sees the
    #: same convention the S&S-50 package itself declares.
    period_convention: str
    period_note: str
    ss40: list[Ss40Deadline]
    ss40_citation: str
    ss40_note: str
    ss50: list[Ss50Deadline]
    ss50_citation: str


_INSERT_EVENT = (
    "INSERT INTO safety.events "
    "(occurred_at, mode, type_of_service, event_category, narrative, "
    "location, fatalities, injuries, property_damage_usd, serious_injury, "
    "substantial_damage, towed, evacuation_life_safety, assault_on_worker, "
    "involves_transit_vehicle, involves_second_rail_vehicle, grade_crossing, "
    "runaway_train, evacuation_to_rail_row, entered_by) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
    "%s, %s, %s, %s, %s) "
    "RETURNING event_id, entered_at"
)

#: Latest classification per event (classified_at DESC, classification_id
#: DESC tie-break — earlier rows are append-only history), wrapped so
#: callers filter on the LATEST verdict, never a stale one.
_SELECT_EVENTS_BASE = (
    "SELECT * FROM ("
    "SELECT DISTINCT ON (e.event_id) e.event_id, e.occurred_at, e.mode, "
    "e.type_of_service, e.event_category, e.narrative, e.location, "
    "e.fatalities, e.injuries, e.property_damage_usd, e.serious_injury, "
    "e.substantial_damage, e.towed, e.evacuation_life_safety, "
    "e.assault_on_worker, e.involves_transit_vehicle, "
    "e.involves_second_rail_vehicle, e.grade_crossing, e.runaway_train, "
    "e.evacuation_to_rail_row, e.entered_by, "
    "e.entered_at, e.superseded_by, c.classification, c.thresholds_met, "
    "c.classifier_version, c.classified_at "
    "FROM safety.events AS e "
    "LEFT JOIN safety.event_classifications AS c ON c.event_id = e.event_id "
    "ORDER BY e.event_id, c.classified_at DESC, c.classification_id DESC"
    ") AS latest"
)

_SELECT_SUPERSEDED_BY = (
    "SELECT superseded_by FROM safety.events WHERE event_id = %s"
)

#: The one UPDATE migration 0017's trigger permits: linking the original to
#: its replacement, exactly once.
_LINK_SUPERSEDED = (
    "UPDATE safety.events SET superseded_by = %s "
    "WHERE event_id = %s AND superseded_by IS NULL "
    "RETURNING event_id"
)


def _month_bounds_or_422(month: str) -> tuple[dt.datetime, dt.datetime]:
    try:
        period_start, period_end = month_period(month)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{month}' is not a month Headway understands. Please use "
                f"the form YYYY-MM — for example 2026-07 for July 2026 — "
                f"with a month number from 01 to 12."
            ),
        )
    return (
        dt.datetime(period_start.year, period_start.month, period_start.day, tzinfo=UTC),
        dt.datetime(period_end.year, period_end.month, period_end.day, tzinfo=UTC),
    )


def _classify_and_record(db, event_id: str, body: SafetyEventCreate) -> tuple[sscls.SsClassification, dict]:
    """Run the deterministic classifier and persist its verdict through the
    classifier's OWN writer (migration 0017's only-writer rule)."""
    event = sscls.SafetyEvent(
        event_id=event_id,
        occurred_at=body.occurred_at,
        mode=body.mode,
        event_category=body.event_category,
        fatalities=body.fatalities,
        injuries=body.injuries,
        property_damage_usd=body.property_damage_usd,
        serious_injury=body.serious_injury,
        substantial_damage=body.substantial_damage,
        towed=body.towed,
        evacuation_life_safety=body.evacuation_life_safety,
        assault_on_worker=body.assault_on_worker,
        involves_transit_vehicle=body.involves_transit_vehicle,
        involves_second_rail_vehicle=body.involves_second_rail_vehicle,
        grade_crossing=body.grade_crossing,
        type_of_service=body.type_of_service,
        runaway_train=body.runaway_train,
        evacuation_to_rail_row=body.evacuation_to_rail_row,
    )
    verdict = sscls.classify_event(event)
    sscls.record_classification(db, verdict)
    return verdict, sscls.classification_to_dict(verdict)


def _result_from_verdict(payload: dict) -> ClassificationResult:
    return ClassificationResult(
        classification=payload["classification"],
        thresholds_met=payload["thresholds_met"],
        explanations=[
            ThresholdExplanation(**e) for e in payload["explanations"]
        ],
        non_major_basis=[
            ThresholdExplanation(
                threshold=b["basis"],
                plain_language=b["plain_language"],
                citation=b["citation"],
            )
            for b in payload["non_major_basis"]
        ],
        effective_category=payload["effective_category"],
        is_rail_mode=payload["is_rail_mode"],
        summary=payload["summary"],
        classifier_version=(
            f"{payload['classifier_name']} {payload['classifier_version']}"
        ),
    )


def _insert_event(db, body: SafetyEventCreate, entered_by: str):
    row = db.execute(
        _INSERT_EVENT,
        (
            body.occurred_at, body.mode, body.type_of_service,
            body.event_category, body.narrative, body.location,
            body.fatalities, body.injuries, body.property_damage_usd,
            body.serious_injury, body.substantial_damage, body.towed,
            body.evacuation_life_safety, body.assault_on_worker,
            body.involves_transit_vehicle, body.involves_second_rail_vehicle,
            body.grade_crossing, body.runaway_train,
            body.evacuation_to_rail_row, entered_by,
        ),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=500,
            detail="The event insert returned no id; nothing was saved.",
        )
    return str(row[0]), row[1]


@router.post(
    "/safety/events", response_model=SafetyEventCreated, status_code=201
)
def create_event(
    body: SafetyEventCreate,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> SafetyEventCreated:
    """Enter one safety event; the classifier runs synchronously and the
    entry, its classification, and the audit record commit together."""
    with db.transaction():
        event_id, entered_at = _insert_event(db, body, identity.username)
        verdict, payload = _classify_and_record(db, event_id, body)
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="safety_event_create",
            subject_kind="safety.events",
            subject_id=event_id,
            detail={
                "mode": body.mode,
                "event_category": body.event_category,
                "classification": verdict.classification,
                "thresholds_met": list(verdict.thresholds_met),
                "classifier_version": (
                    f"{verdict.calc_name} {verdict.calc_version}"
                ),
            },
        )
    return SafetyEventCreated(
        event_id=event_id,
        entered_at=entered_at,
        result=_result_from_verdict(payload),
        audit_event_id=audit_event_id,
    )


@router.get("/safety/events", response_model=list[SafetyEventRecord])
def list_events(
    classification: Optional[str] = Query(default=None),
    month: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[SafetyEventRecord]:
    if classification is not None and classification not in VALID_CLASSIFICATIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{classification}' is not a classification Headway "
                f"knows. Valid classifications are: "
                f"{', '.join(VALID_CLASSIFICATIONS)}."
            ),
        )
    clauses: list[str] = []
    params: list = []
    if month is not None:
        start_dt, end_dt = _month_bounds_or_422(month)
        clauses.append("occurred_at >= %s AND occurred_at < %s")
        params.extend([start_dt, end_dt])
    if mode is not None:
        clauses.append("mode = %s")
        params.append(mode)
    if classification is not None:
        clauses.append("classification = %s")
        params.append(classification)
    sql = _SELECT_EVENTS_BASE
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY occurred_at, event_id"
    rows = db.execute(sql, tuple(params)).fetchall()
    return [
        SafetyEventRecord(
            event_id=str(r[0]),
            occurred_at=r[1],
            mode=r[2],
            type_of_service=r[3],
            event_category=r[4],
            narrative=r[5],
            location=r[6],
            fatalities=r[7],
            injuries=r[8],
            property_damage_usd=(str(r[9]) if r[9] is not None else None),
            serious_injury=r[10],
            substantial_damage=r[11],
            towed=r[12],
            evacuation_life_safety=r[13],
            assault_on_worker=r[14],
            involves_transit_vehicle=r[15],
            involves_second_rail_vehicle=r[16],
            grade_crossing=r[17],
            runaway_train=r[18],
            evacuation_to_rail_row=r[19],
            entered_by=r[20],
            entered_at=r[21],
            superseded_by=(str(r[22]) if r[22] is not None else None),
            classification=r[23],
            thresholds_met=(list(r[24]) if r[24] is not None else None),
            classifier_version=r[25],
            classified_at=r[26],
        )
        for r in rows
    ]


class SafetyEventCounts(BaseModel):
    """Counts for the /safety summary cards (handoff 0017, design point 2):
    counted over EXACTLY the rows GET /safety/events serves under the same
    filters, so a card can never disagree with the table. Classification is
    each event's LATEST verdict; an event with no classification row counts
    as 'unclassified' (never guessed); superseded events are counted
    separately AND inside their classification bucket, exactly as the list
    shows them."""

    total: int
    by_classification: dict[str, int]
    unclassified: int
    superseded: int


@router.get("/safety/events/counts", response_model=SafetyEventCounts)
def count_events(
    month: Optional[str] = Query(default=None),
    mode: Optional[str] = Query(default=None),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> SafetyEventCounts:
    """Classification counts over the same rows (and the same month/mode
    filters) as GET /safety/events — composition of the one events query,
    counted in the open, no new tables (handoff 0017)."""
    events = list_events(
        classification=None, month=month, mode=mode, identity=identity, db=db
    )
    by_classification = {c: 0 for c in VALID_CLASSIFICATIONS}
    unclassified = 0
    superseded = 0
    for event in events:
        if event.classification is None:
            unclassified += 1
        else:
            # An unexpected vocabulary value still counts under its own key.
            by_classification[event.classification] = (
                by_classification.get(event.classification, 0) + 1
            )
        if event.superseded_by is not None:
            superseded += 1
    return SafetyEventCounts(
        total=len(events),
        by_classification=by_classification,
        unclassified=unclassified,
        superseded=superseded,
    )


class SupersedeRequest(SafetyEventCreate):
    reason: str = Field(
        min_length=1,
        description=(
            "Why the original entry is being corrected (kept in the audit "
            "log — the original event itself is never edited)."
        ),
    )

    @field_validator("reason")
    @classmethod
    def _reason_bounded(cls, v: str) -> str:
        if len(v) > 5_000:
            raise _too_long("The correction reason", 5_000, len(v))
        return v


@router.post(
    "/safety/events/{event_id}/supersede",
    response_model=SafetyEventSuperseded,
    status_code=201,
)
def supersede_event(
    event_id: str,
    body: SupersedeRequest,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> SafetyEventSuperseded:
    """Append-only correction: enter the CORRECTED event in full; the
    original stays untouched except for its superseded_by link."""
    with db.transaction():
        current = db.execute(_SELECT_SUPERSEDED_BY, (event_id,)).fetchone()
        if current is None:
            raise HTTPException(
                status_code=404,
                detail="No safety event with that id exists.",
            )
        if current[0] is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This event was already corrected once. To correct it "
                    "again, supersede its replacement — every correction "
                    "stays in the chain so the history is honest."
                ),
            )
        replacement_id, entered_at = _insert_event(db, body, identity.username)
        verdict, payload = _classify_and_record(db, replacement_id, body)
        linked = db.execute(
            _LINK_SUPERSEDED, (replacement_id, event_id)
        ).fetchone()
        if linked is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This event was corrected by someone else while your "
                    "correction was being saved. Nothing was changed — "
                    "please review the existing correction first."
                ),
            )
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="safety_event_supersede",
            subject_kind="safety.events",
            subject_id=event_id,
            detail={
                "replacement_event_id": replacement_id,
                "reason": body.reason,
                "classification": verdict.classification,
                "thresholds_met": list(verdict.thresholds_met),
                "classifier_version": (
                    f"{verdict.calc_name} {verdict.calc_version}"
                ),
            },
        )
    return SafetyEventSuperseded(
        original_event_id=event_id,
        replacement_event_id=replacement_id,
        entered_at=entered_at,
        result=_result_from_verdict(payload),
        audit_event_id=audit_event_id,
    )


@router.get("/safety/deadlines", response_model=DeadlinesResponse)
def get_deadlines(
    month: Optional[str] = Query(
        default=None,
        description=(
            "Month for the S&S-50 deadline rows (YYYY-MM). Defaults to the "
            "current UTC month. S&S-40 deadlines are month-independent "
            "(every open major event is listed)."
        ),
    ),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> DeadlinesResponse:
    if month is None:
        today = dt.datetime.now(UTC).date()
        month = f"{today.year:04d}-{today.month:02d}"
    start_dt, end_dt = _month_bounds_or_422(month)

    # S&S-40: one deadline per open major event. v0 has no submission
    # tracking, so every unsuperseded major event is open by definition
    # (documented in ss40_note).
    major_rows = db.execute(
        _SELECT_EVENTS_BASE
        + " WHERE classification = %s AND superseded_by IS NULL"
        + " ORDER BY occurred_at, event_id",
        (sscls.MAJOR,),
    ).fetchall()
    ss40 = [
        Ss40Deadline(
            event_id=str(r[0]),
            occurred_at=r[1],
            mode=r[2],
            event_category=r[4],
            due_date=(r[1] + dt.timedelta(days=30)).date(),
        )
        for r in major_rows
    ]

    # S&S-50: one row per mode for the month — operated modes (the
    # handoff-0009 derivation; NULL buckets as 'unknown') UNION modes that
    # have events entered for the month, so a deadline never disappears
    # just because telemetry is missing.
    operated_rows = db.execute(
        SELECT_OPERATED_MODES_SQL, (start_dt, end_dt)
    ).fetchall()
    modes = {
        (r[0] if r[0] is not None else "unknown") for r in operated_rows
    }
    month_events = db.execute(
        _SELECT_EVENTS_BASE
        + " WHERE occurred_at >= %s AND occurred_at < %s"
        + " ORDER BY occurred_at, event_id",
        (start_dt, end_dt),
    ).fetchall()
    non_major_counts: dict[str, int] = {}
    for r in month_events:
        modes.add(r[2])
        if r[22] is None and r[23] == sscls.NON_MAJOR:  # unsuperseded, non-major
            non_major_counts[r[2]] = non_major_counts.get(r[2], 0) + 1
    due = ss50_due_date(month)
    ss50 = [
        Ss50Deadline(
            month=month,
            mode=mode,
            due_date=due,
            non_major_event_count=non_major_counts.get(mode, 0),
            zero_event=non_major_counts.get(mode, 0) == 0,
        )
        for mode in sorted(modes)
    ]

    return DeadlinesResponse(
        month=month,
        period_convention=PERIOD_CONVENTION,
        period_note=_PERIOD_NOTE,
        ss40=ss40,
        ss40_citation=_SS40_CITATION,
        ss40_note=(
            "Headway v0 has no NTD submission tracking: every major event "
            "that has not been superseded is listed as open, with its due "
            "date. Mark-as-submitted is a future increment (handoff 0010 "
            "open questions)."
        ),
        ss50=ss50,
        ss50_citation=_SS50_CITATION,
    )
