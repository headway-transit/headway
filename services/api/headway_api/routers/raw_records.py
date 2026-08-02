"""The raw-record inspector — the end of the trail, with a label and a window
(handoff 0035).

WHY THIS EXISTS
---------------
First-agency UAT, the sharpest finding of the week: an ITS manager walked a
VRH figure back through its lineage to the source — exactly what this
platform is built for — and hit a wall of hashes labelled *"raw source record
as received — the end of the trail."* His verdict: **"It doesn't really
provide any data to validate or verify."**

He was right. A content address genuinely proves tamper-evidence — change
one byte and the id no longer matches — but proof you cannot INSPECT asks for
trust at the exact step where this platform must never ask for it. The chain
of custody ended in a sealed evidence bag with no label and no window. This
router is the label, the window, and the seal you can test yourself:

- ``GET /raw/records/{id}`` — the LABEL. What this record is, where it came
  from, when, how big, whether it parsed, where its bytes live. Every field
  is a column of ``raw.records`` or a measurement taken at request time; an
  absent field is served absent, never filled in.
- ``POST /raw/records/{id}/verify`` — INTEGRITY AS AN ACTION. Re-reads the
  stored bytes, re-computes the SHA-256, and reports match or mismatch with
  both digests shown. This is what turns "content-addressed and immutable"
  from a claim in a brochure into a button an auditor presses.
- ``GET /raw/records/{id}/payload`` — the WINDOW. A bounded, decoded preview
  with its caps stated: a GTFS-Realtime frame becomes its real vehicles at
  their real coordinates at that minute; a CSV becomes its first rows
  verbatim; anything else says plainly what it is and offers the bytes.
- ``GET /raw/records/{id}/download`` — THE BYTES. Exactly as stored, streamed.

WHAT IT IS NOT
--------------
Read-only, all of it. No re-parsing, no editing, no re-ingestion, no repair.
``raw.records`` is immutable at the database level (migration 0002 rejects
UPDATE and DELETE with a trigger) and this router only ever SELECTs. The
decoder set is GTFS-Realtime plus text/CSV in v0; everything else states its
type and hands over bytes rather than showing a rendering it cannot vouch
for.

AUTHORIZATION
-------------
The label and the integrity verdict are open to any signed-in role — the same
surface as the lineage walk they complete — because neither discloses payload
content, and an auditor must never be told that proving integrity is above
their pay grade. The CONTENTS are gated by the payload's own sensitivity
class (headway_api.raw_payloads.classify): demand-response payloads carry
rider pickup and dropoff coordinates, which are rider home addresses, so they
are withheld from the broadest read role exactly as migration 0028 withholds
them from the read-only analyst database role. A refusal says why, in words.

AUDIT
-----
Every look inside a raw record writes an append-only audit row — preview and
download alike, whatever the sensitivity class. This is the only surface in
Headway that serves raw record CONTENT, and "who opened the evidence, and
when" is a question an auditor is entitled to ask. Verification is audited
with its verdict. Reading the label is not audited, like every other
signed-in GET.

FAIL LOUDLY
-----------
A verification that does not match is not a 200 with a field to notice: it is
**409**, with both digests in the body, and it raises a blocking data-quality
issue against the record so it lands in the steward's queue rather than
living only on the screen of whoever happened to press the button. A record
whose bytes are missing from the object store is **404** and likewise a
blocking issue — a raw record is supposed to be permanent, so its absence is
a finding about the installation. A record whose bytes rode inline in the
ingest envelope and have aged out of the broker's retention window is **410**
and is NOT a defect: it is a deployment setting, stated plainly.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .. import raw_payloads
from ..audit import write_event
from ..auth import Identity
from ..authz import ROLE_LABELS, may_read_sensitivity, require_authenticated
from ..db import get_db
from ..raw_payloads import (
    PayloadUnavailable,
    RawRecord,
    record_from_row,
)

router = APIRouter(tags=["raw-records"])

UTC = dt.timezone.utc

#: The hash that IS the record id (migration 0002: "lowercase hex SHA-256 of
#: raw payload bytes").
HASH_ALGORITHM = "sha-256"

CONTENT_ADDRESS_NOTE = (
    "This record's id is the SHA-256 hash of the bytes exactly as they were "
    "received. Change a single byte and the hash no longer matches, which is "
    "what makes the record tamper-evident. Use Verify integrity to have "
    "Headway re-read the stored bytes and re-compute this hash in front of "
    "you."
)

IMMUTABILITY_NOTE = (
    "Raw records are never edited. The database refuses any update or delete "
    "of this row (migration 0002), and nothing in this screen can change it — "
    "everything here is read-only."
)

_SELECT_RECORD = (
    f"SELECT {raw_payloads.RECORD_COLUMNS} FROM raw.records WHERE record_id = %s"
)

_SELECT_OPEN_ISSUE = (
    "SELECT issue_id FROM dq.issues WHERE issue_type = %s "
    "AND status <> 'resolved' AND %s = ANY(source_record_ids) LIMIT 1"
)

_INSERT_ISSUE = (
    "INSERT INTO dq.issues "
    "(issue_type, severity, status, title, description, source_record_ids) "
    "VALUES (%s, %s, %s, %s, %s, %s) RETURNING issue_id"
)

ISSUE_TYPE_MISMATCH = "raw_record_integrity_mismatch"
ISSUE_TYPE_MISSING = "raw_record_payload_missing"


# ---------------------------------------------------------------------- models


class StoredBytes(BaseModel):
    """Where the payload lives and how big it is — measured, never assumed."""

    #: 'object_store' or 'ingest_envelope_stream'.
    location: str
    #: The object-store key, when the payload is an object. Null otherwise.
    object_key: Optional[str] = None
    #: Stored size in bytes when it can be read cheaply. Null is honest: for
    #: a payload carried inline on the broker, the size is measured when the
    #: payload is opened, not when the label is read.
    size_bytes: Optional[int] = None
    #: 'available' | 'missing' | 'unavailable' | 'measured_on_open'
    status: str
    note: str


class ContentAddress(BaseModel):
    algorithm: str
    digest: str
    note: str


class SensitivityBlock(BaseModel):
    classification: str
    label: str
    minimum_role: str
    reason: str
    #: Whether THIS caller may open the contents. Server-enforced; the flag
    #: exists so the UI can explain rather than dangle a button that 403s.
    preview_allowed: bool
    refusal: Optional[str] = None


class DecoderBlock(BaseModel):
    kind: str
    note: str


class RawRecordLabel(BaseModel):
    """The label on the evidence bag. Every field is a ``raw.records`` column
    or a measurement taken now; nothing is inferred."""

    record_id: str
    source: str
    simulated: bool
    connector: str
    connector_version: str
    content_type: str
    payload_encoding: str
    fetched_at: dt.datetime
    landed_at: dt.datetime
    parse_status: str
    parse_error: Optional[str] = None
    stored_bytes: StoredBytes
    content_address: ContentAddress
    sensitivity: SensitivityBlock
    decoder: DecoderBlock
    immutability_note: str


class VerificationVerdict(BaseModel):
    """The result of re-reading the bytes and re-computing their hash.

    ``result`` is the whole answer in one word and the HTTP status agrees
    with it: match is 200, mismatch is 409, and an unreadable payload is
    404/410/503 by reason. A caller that only checks the status code cannot
    mistake a failure for a pass.
    """

    record_id: str
    verified_at: dt.datetime
    result: str
    algorithm: str
    expected_digest: str
    actual_digest: Optional[str] = None
    size_bytes: Optional[int] = None
    read_from: Optional[str] = None
    reason: Optional[str] = None
    headline: str
    detail: str
    #: The blocking DQ issue this verdict raised (mismatch / missing bytes),
    #: or the open one it matched. Null when the verdict is a pass.
    dq_issue_id: Optional[str] = None


class PayloadPreview(BaseModel):
    """A bounded look inside. Every cap that applied is stated in ``caps``."""

    record_id: str
    content_type: str
    size_bytes: int
    read_from: str
    decoder: str
    decoder_note: str
    #: True when the preview shows less than the whole payload.
    truncated: bool
    truncation_note: Optional[str] = None
    caps: dict
    #: Exactly one of these is populated, per ``decoder``.
    gtfs_realtime: Optional[dict] = None
    delimited: Optional[dict] = None
    text: Optional[dict] = None
    undecoded: Optional[dict] = None
    download_note: str


# ------------------------------------------------------------------- helpers


def _load(db, record_id: str) -> RawRecord:
    row = db.execute(_SELECT_RECORD, (record_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No raw record with that id exists in this Headway "
                "installation. Check the id from the lineage trail — a raw "
                "record id is the 64-character SHA-256 of the bytes as "
                "received."
            ),
        )
    return record_from_row(row)


def _reader(request: Request):
    reader = getattr(request.app.state, "raw_payload_reader", None)
    if reader is None:
        reader = raw_payloads.payload_reader_from_env(
            getattr(request.app.state, "object_store", None)
        )
        request.app.state.raw_payload_reader = reader
    return reader


def _require_content_access(record: RawRecord, identity: Identity) -> None:
    """Server-side sensitivity gate for payload CONTENT (never client-side).

    Goes through ``authz.may_read_sensitivity`` rather than indexing
    ROLE_RANK, because not every role is ON the rank ladder. An ``auditor``
    (handoff 0046) reads at VIEWER breadth here on purpose: migration 0028
    withholds demand-response rider coordinates from the read-only analyst
    role because a paratransit pickup point is a rider's home address, and
    that withholding is not waived for an auditor. Rider privacy is not an
    auditor exception.
    """
    sensitivity = raw_payloads.classify(record)
    if not may_read_sensitivity(identity.role, sensitivity.minimum_role):
        raise HTTPException(status_code=403, detail=sensitivity.refusal)


def _write_audit(db, *, actor: str, action: str, record: RawRecord, detail: dict) -> None:
    """Inside the caller's transaction — never on its own."""
    write_event(
        db,
        actor=actor,
        action=action,
        subject_kind="raw.records",
        subject_id=record.record_id,
        detail=detail,
    )


def _audit(db, *, actor: str, action: str, record: RawRecord, detail: dict) -> None:
    with db.transaction():
        _write_audit(db, actor=actor, action=action, record=record, detail=detail)


def _raise_issue(
    db,
    *,
    issue_type: str,
    title: str,
    description: str,
    record_id: str,
) -> Optional[str]:
    """Raise (or find) the blocking DQ issue for an integrity failure.

    Idempotent on purpose: pressing Verify five times must not put five
    identical findings in the steward's queue, and an already-open finding
    is the right answer to return.
    """
    existing = db.execute(_SELECT_OPEN_ISSUE, (issue_type, record_id)).fetchone()
    if existing is not None:
        return str(existing[0])
    row = db.execute(
        _INSERT_ISSUE,
        (issue_type, "blocking", "open", title, description, [record_id]),
    ).fetchone()
    return str(row[0]) if row is not None else None


def _caps(decoder: str) -> dict:
    if decoder == raw_payloads.DECODER_GTFS_RT:
        return {
            "max_entities": raw_payloads.MAX_ENTITIES,
            "max_stop_time_updates_per_entity": raw_payloads.MAX_STOP_TIME_UPDATES,
            "max_bytes_read": raw_payloads.MAX_DECODE_BYTES,
        }
    if decoder in (raw_payloads.DECODER_DELIMITED, raw_payloads.DECODER_TEXT):
        return {
            "max_rows": raw_payloads.MAX_TEXT_ROWS,
            "max_characters_per_line": raw_payloads.MAX_LINE_CHARS,
            "max_bytes_read": raw_payloads.MAX_DECODE_BYTES,
        }
    return {"max_bytes_read": 0}


# ------------------------------------------------------------------ the label


@router.get("/raw/records/{record_id}", response_model=RawRecordLabel)
def raw_record_label(
    record_id: str,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> RawRecordLabel:
    """What this record is — the label on the evidence bag.

    Deliberately does NOT read the payload: a lineage trail can bottom out
    in dozens of raw records, and the label must stay cheap enough to show
    beside every one of them. For an object-store payload the size comes
    from a metadata call; for a payload carried inline on the broker the
    size is stated as measured-on-open rather than guessed. An object store
    that is down degrades to a label with an honest note, never to an error
    page — the record's identity does not depend on the store being up.
    """
    record = _load(db, record_id)
    sensitivity = raw_payloads.classify(record)
    decoder = raw_payloads.decoder_for(record)

    if record.payload_encoding == "object_ref":
        location = raw_payloads.LOCATION_OBJECT_STORE
        try:
            size = _reader(request).size(record)
        except PayloadUnavailable as exc:
            stored = StoredBytes(
                location=location,
                object_key=record.payload_ref,
                size_bytes=None,
                status="unavailable" if exc.reason != raw_payloads.REASON_OBJECT_MISSING
                else "missing",
                note=exc.message,
            )
        else:
            if size is None:
                stored = StoredBytes(
                    location=location,
                    object_key=record.payload_ref,
                    size_bytes=None,
                    status="measured_on_open",
                    note=(
                        "The object store did not report a size without "
                        "reading the object; the exact size is measured when "
                        "the payload is opened or verified."
                    ),
                )
            else:
                stored = StoredBytes(
                    location=location,
                    object_key=record.payload_ref,
                    size_bytes=size,
                    status="available",
                    note=(
                        "The payload is an object in this installation's "
                        "object store, at the key shown."
                    ),
                )
    else:
        stored = StoredBytes(
            location=raw_payloads.LOCATION_ENVELOPE_STREAM,
            object_key=None,
            size_bytes=None,
            status="measured_on_open",
            note=(
                "This record's bytes rode inline in the ingest envelope on "
                "the message broker rather than being written to the object "
                "store, so their size is measured when the payload is opened. "
                "The broker keeps messages for a limited window; after that "
                "the label and the trail remain, and the bytes do not."
            ),
        )

    return RawRecordLabel(
        record_id=record.record_id,
        source=record.source,
        simulated="simulated" in record.source.lower(),
        connector=record.connector,
        connector_version=record.connector_version,
        content_type=record.content_type,
        payload_encoding=record.payload_encoding,
        fetched_at=record.fetched_at,
        landed_at=record.landed_at,
        parse_status=record.parse_status,
        parse_error=record.parse_error,
        stored_bytes=stored,
        content_address=ContentAddress(
            algorithm=HASH_ALGORITHM,
            digest=record.record_id,
            note=CONTENT_ADDRESS_NOTE,
        ),
        sensitivity=SensitivityBlock(
            classification=sensitivity.classification,
            label=sensitivity.label,
            minimum_role=sensitivity.minimum_role,
            reason=sensitivity.reason,
            preview_allowed=may_read_sensitivity(
                identity.role, sensitivity.minimum_role
            ),
            refusal=(
                None
                if may_read_sensitivity(identity.role, sensitivity.minimum_role)
                else sensitivity.refusal
            ),
        ),
        decoder=DecoderBlock(kind=decoder, note=raw_payloads.decoder_note(record)),
        immutability_note=IMMUTABILITY_NOTE,
    )


# ------------------------------------------------------------------- integrity


@router.post(
    "/raw/records/{record_id}/verify",
    response_model=VerificationVerdict,
    responses={
        404: {"model": VerificationVerdict, "description": "Bytes missing from the store"},
        409: {"model": VerificationVerdict, "description": "Integrity MISMATCH"},
        410: {"model": VerificationVerdict, "description": "Bytes no longer retained"},
        503: {"model": VerificationVerdict, "description": "Storage unavailable"},
    },
)
def verify_raw_record(
    record_id: str,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
):
    """Re-read the stored bytes, re-compute their SHA-256, report the verdict.

    Open to any signed-in role, including for payloads whose CONTENTS are
    withheld: a hash discloses nothing about rider addresses, and the whole
    point of this action is that nobody has to take the integrity claim on
    trust.

    A mismatch means the stored bytes are not the bytes this record was
    created from. That is either tampering or corruption, and either way
    every figure computed from this record is in question — so it answers
    409, raises a blocking data-quality issue, and is audited.
    """
    record = _load(db, record_id)
    now = dt.datetime.now(UTC)
    try:
        handle = _reader(request).open(record)
        actual, size = raw_payloads.digest_and_size(handle.chunks)
    except PayloadUnavailable as exc:
        issue_id = None
        # The finding and its audit record commit together or not at all:
        # audit logging is never best-effort (headway_api.audit).
        with db.transaction():
            if exc.reason == raw_payloads.REASON_OBJECT_MISSING:
                issue_id = _raise_issue(
                    db,
                    issue_type=ISSUE_TYPE_MISSING,
                    title=(
                        "Raw record bytes are missing from the object store"
                    ),
                    description=(
                        f"Raw record {record.record_id} (source "
                        f"{record.source}, connector {record.connector}) is "
                        "registered in the ingest index, but its payload is "
                        "not in the object store, so its integrity cannot be "
                        "verified and the evidence behind anything computed "
                        "from it cannot be produced. Raised by an integrity "
                        "check from the raw-record inspector."
                    ),
                    record_id=record.record_id,
                )
            _write_audit(
                db,
                actor=identity.username,
                action="raw_record_verify",
                record=record,
                detail={
                    "result": (
                        "missing"
                        if exc.reason == raw_payloads.REASON_OBJECT_MISSING
                        else "unavailable"
                    ),
                    "reason": exc.reason,
                    "dq_issue_id": issue_id,
                },
            )
        verdict = VerificationVerdict(
            record_id=record.record_id,
            verified_at=now,
            result="missing" if exc.reason == raw_payloads.REASON_OBJECT_MISSING
            else "unavailable",
            algorithm=HASH_ALGORITHM,
            expected_digest=record.record_id,
            reason=exc.reason,
            headline=(
                "Headway could not read this record's bytes, so it cannot "
                "verify them."
            ),
            detail=exc.message,
            dq_issue_id=issue_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_jsonable(verdict),
        )

    matched = actual == record.record_id
    issue_id = None
    # One transaction: the finding (when there is one) and the audit record
    # of this verification commit together, or the verification fails.
    with db.transaction():
        if not matched:
            issue_id = _raise_issue(
                db,
                issue_type=ISSUE_TYPE_MISMATCH,
                title="Raw record does not match its content address",
                description=(
                    f"Raw record {record.record_id} (source {record.source}, "
                    f"connector {record.connector}) was re-read from storage "
                    f"and hashed to {actual}, which is not its id. The stored "
                    "bytes are not the bytes this record was created from, so "
                    "every figure computed from it is in question until this "
                    "is explained. Raised by an integrity check from the "
                    "raw-record inspector."
                ),
                record_id=record.record_id,
            )
        _write_audit(
            db,
            actor=identity.username,
            action="raw_record_verify",
            record=record,
            detail={
                "result": "match" if matched else "mismatch",
                "expected_digest": record.record_id,
                "actual_digest": actual,
                "read_from": handle.location,
                "dq_issue_id": issue_id,
            },
        )

    verdict = VerificationVerdict(
        record_id=record.record_id,
        verified_at=now,
        result="match" if matched else "mismatch",
        algorithm=HASH_ALGORITHM,
        expected_digest=record.record_id,
        actual_digest=actual,
        size_bytes=size,
        read_from=handle.location,
        headline=(
            "Verified: the stored bytes are unaltered."
            if matched
            else "MISMATCH: the stored bytes are NOT the bytes this record "
            "was created from."
        ),
        detail=(
            (
                f"Headway re-read all {size:,} bytes from "
                f"{'the object store' if handle.location == raw_payloads.LOCATION_OBJECT_STORE else 'the ingest envelope stream'} "
                "and re-computed their SHA-256. It matches this record's id "
                "exactly, so the bytes have not changed since Headway "
                "received them."
            )
            if matched
            else (
                f"Headway re-read all {size:,} bytes and computed "
                f"{actual}, but this record's id — the hash of the bytes as "
                f"received — is {record.record_id}. The two disagree, which "
                "means the stored copy has been altered or corrupted. Treat "
                "every figure that cites this record as unproven until "
                "someone explains the difference. A blocking data-quality "
                "issue has been raised so this cannot be quietly forgotten."
            )
        ),
        dq_issue_id=issue_id,
    )
    if matched:
        return verdict
    return JSONResponse(status_code=409, content=_jsonable(verdict))


def _jsonable(model: BaseModel) -> Any:
    return model.model_dump(mode="json")


# --------------------------------------------------------------- the window


@router.get("/raw/records/{record_id}/payload", response_model=PayloadPreview)
def raw_record_payload(
    record_id: str,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> PayloadPreview:
    """A bounded look inside the record, with the caps stated.

    This is the moment a steward sees their own bus, at that minute, at
    those coordinates, as the origin of a number. What is shown is decoded
    from the stored bytes at request time — never from a cached rendering,
    never from the normalized copy downstream — so the preview is evidence
    about the record and not about Headway's opinion of it.
    """
    record = _load(db, record_id)
    _require_content_access(record, identity)
    decoder = raw_payloads.decoder_for(record)

    if decoder == raw_payloads.DECODER_NONE:
        size = None
        try:
            size = _reader(request).size(record)
        except PayloadUnavailable as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message)
        _audit(
            db,
            actor=identity.username,
            action="raw_record_payload_preview",
            record=record,
            detail={"decoder": decoder, "bytes_read": 0},
        )
        return PayloadPreview(
            record_id=record.record_id,
            content_type=record.content_type,
            size_bytes=size or 0,
            read_from=(
                raw_payloads.LOCATION_OBJECT_STORE
                if record.payload_encoding == "object_ref"
                else raw_payloads.LOCATION_ENVELOPE_STREAM
            ),
            decoder=decoder,
            decoder_note=raw_payloads.decoder_note(record),
            truncated=True,
            truncation_note=(
                "Nothing of the contents is shown: Headway has no reader for "
                f"{record.content_type} yet. The exact bytes are available to "
                "download, and their integrity can still be verified here."
            ),
            caps=_caps(decoder),
            undecoded={
                "content_type": record.content_type,
                "reason": (
                    "Headway decodes GTFS-Realtime feeds and text files "
                    "today. For anything else it will not show you a "
                    "rendering it cannot vouch for — it hands over the exact "
                    "bytes instead."
                ),
            },
            download_note=_download_note(record),
        )

    try:
        handle = _reader(request).open(record)
        data, more = raw_payloads.read_capped(
            handle.chunks, raw_payloads.MAX_DECODE_BYTES
        )
    except PayloadUnavailable as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    size = handle.size_bytes if handle.size_bytes is not None else len(data)
    truncated = bool(more) or size > len(data)

    gtfs_realtime = delimited = text = None
    truncation_note: Optional[str] = None

    if decoder == raw_payloads.DECODER_GTFS_RT:
        if truncated:
            gtfs_realtime = {
                "decoded": False,
                "decode_error": (
                    f"This frame is {size:,} bytes, larger than the "
                    f"{raw_payloads.MAX_DECODE_BYTES:,}-byte limit this "
                    "preview reads. A feed message has to be read whole to be "
                    "decoded, so Headway will not show a partial decode. "
                    "Download the exact bytes instead — integrity can still "
                    "be verified here."
                ),
            }
            truncation_note = gtfs_realtime["decode_error"]
        else:
            gtfs_realtime = raw_payloads.decode_gtfs_realtime(data)
            shown = len(gtfs_realtime.get("entities") or [])
            total = gtfs_realtime.get("entity_count") or 0
            if gtfs_realtime.get("decoded") and total > shown:
                truncated = True
                truncation_note = (
                    f"Showing the first {shown} of {total:,} entities in this "
                    "feed message. The remaining entities are in the bytes "
                    "you can download; nothing was dropped from the record."
                )
    elif decoder == raw_payloads.DECODER_DELIMITED:
        delimited = raw_payloads.decode_delimited(data, more)
        if delimited.get("readable"):
            shown = len(delimited.get("rows") or [])
            truncated = not delimited["complete"]
            truncation_note = (
                (
                    f"Showing the first {shown} data rows after the header "
                    "row. The whole file is available to download."
                )
                if truncated
                else (
                    f"This is the whole file: a header row and {shown} data "
                    f"{'row' if shown == 1 else 'rows'}, exactly as stored."
                )
            )
    else:
        text = raw_payloads.decode_text(data, more)
        if text.get("readable"):
            shown = len(text.get("lines") or [])
            truncated = not text["complete"]
            unknown_columns = (
                " Headway does not know this file's column names from the "
                "record alone — only the registered mapping spec for this "
                "source defines them — so no column labels are shown rather "
                "than guessed ones."
                if record.content_type == "text/csv"
                else ""
            )
            truncation_note = (
                (
                    f"Showing the first {shown} lines exactly as stored."
                    + unknown_columns
                    + " The whole file is available to download."
                )
                if truncated
                else (
                    f"This is the whole file: {shown} "
                    f"{'line' if shown == 1 else 'lines'}, exactly as stored."
                    + unknown_columns
                )
            )

    _audit(
        db,
        actor=identity.username,
        action="raw_record_payload_preview",
        record=record,
        detail={
            "decoder": decoder,
            "bytes_read": len(data),
            "sensitivity": raw_payloads.classify(record).classification,
        },
    )
    return PayloadPreview(
        record_id=record.record_id,
        content_type=record.content_type,
        size_bytes=size,
        read_from=handle.location,
        decoder=decoder,
        decoder_note=raw_payloads.decoder_note(record),
        truncated=truncated,
        truncation_note=truncation_note,
        caps=_caps(decoder),
        gtfs_realtime=gtfs_realtime,
        delimited=delimited,
        text=text,
        download_note=_download_note(record),
    )


def _download_note(record: RawRecord) -> str:
    return (
        "Download gives you the exact bytes Headway received — the same bytes "
        f"whose SHA-256 is {record.record_id}. Hash the downloaded file "
        "yourself and you will get that id back."
    )


@router.get("/raw/records/{record_id}/download")
def raw_record_download(
    record_id: str,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
):
    """The exact stored bytes, streamed, with the record's own content type.

    Not truncated and not transformed: a download that altered the bytes
    would be worthless as evidence. The response carries the content address
    in a header so a downloaded file can be tied back to the record it came
    from without depending on the filename.
    """
    record = _load(db, record_id)
    _require_content_access(record, identity)
    try:
        handle = _reader(request).open(record)
    except PayloadUnavailable as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    _audit(
        db,
        actor=identity.username,
        action="raw_record_download",
        record=record,
        detail={
            "read_from": handle.location,
            "sensitivity": raw_payloads.classify(record).classification,
        },
    )
    headers = {
        "Content-Disposition": (
            f'attachment; filename="{record.record_id}{_extension(record)}"'
        ),
        "X-Headway-Record-Id": record.record_id,
        "X-Headway-Content-Address": f"{HASH_ALGORITHM}:{record.record_id}",
    }
    if handle.size_bytes is not None:
        headers["Content-Length"] = str(handle.size_bytes)
    return StreamingResponse(
        handle.chunks,
        media_type=record.content_type or "application/octet-stream",
        headers=headers,
    )


def _extension(record: RawRecord) -> str:
    """A filename suffix from the record's OWN content type — never sniffed."""
    return {
        "text/csv": ".csv",
        "text/plain": ".txt",
        "application/json": ".json",
        "application/zip": ".zip",
        "application/x-protobuf": ".pb",
    }.get(record.content_type, "")


__all__ = ["router", "ROLE_LABELS"]
