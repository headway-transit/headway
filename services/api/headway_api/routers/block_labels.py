"""Upload the agency's trip→block export and name blocks the way dispatch does.

WHY THIS IS A SCREEN AND NOT A COMMAND. The derivation has existed as
``tools/block-labels/derive.py`` since handoff 0038 and was never run, because
running it means a terminal, a database password and a Python invocation. The
person who needs it is an ITS manager who was a week into Linux when this
started and has now had three commands mangled by copy-paste in a single day.
A one-time load that decides how every future finding READS is not a good
reason to hand somebody a shell.

THE DERIVATION IS NOT REIMPLEMENTED HERE. Both this router and the CLI call
``headway_transform.block_labels``, so an agency can never get two different
answers about what a block is called depending on which door they came in.
That is why ``headway-transform`` is a dependency of this service.

PROVENANCE MATCHES THE COMMAND LINE, EXACTLY. The CLI records the file's
sha256 and the parse-config hash beside every label it writes. A label
loaded through this screen ends up on the same findings, so it carries the
same evidence — a filename alone would let two different files claim the
same provenance, and the door somebody came in should not decide how well
a federal figure's inputs are attributed.

TWO STEPS, AND THE FILE IS SENT TWICE ON PURPOSE. Preview derives and reports;
load derives again and writes. Nothing is cached between them. A cached
preview would let the file change underneath an approval — the operator would
be approving numbers that no longer describe what gets written. Re-deriving
from the exact bytes being loaded costs a second and removes the question.

WHAT IT REFUSES TO DO. Rows whose trip name will not parse, rows whose
route+start names more than one block, and blocks that two rows label
differently are all counted and reported, and NONE of them enter the mapping.
A partial mapping that is honest about its gaps is worth far more than a
complete one that guessed, because the labels end up on findings an auditor
reads.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ..audit import write_event
from ..auth import Identity
from ..authz import require_certifying_official
from ..db import get_db

router = APIRouter(tags=["admin"])

#: Where the resolution spec lives inside the image (services/api/Dockerfile
#: copies it), with the repo path as the fallback for a source checkout.
_SPEC_CANDIDATES = (
    Path("/app/adapters/tripspark/streets/resolution.v0.yaml"),
    Path(__file__).resolve().parents[4]
    / "adapters/tripspark/streets/resolution.v0.yaml",
)

#: An export bigger than this is not a trip→block mapping. The real one from
#: the partner agency was 33,202 rows / ~1 MB; ten times that is generous and
#: still bounds what one request can make this process hold.
MAX_UPLOAD_BYTES = 16 * 1024 * 1024

#: How many example rows of each problem kind travel back to the screen. The
#: COUNTS are always complete; only the examples are capped, and the response
#: says so rather than letting a reader assume they are seeing everything.
SAMPLE_CAP = 20


class ProblemRow(BaseModel):
    line: int
    trip_name: str
    block_name: str
    reason: str


class ServiceDayNote(BaseModel):
    """What the upload concluded about one of the export's service days."""

    service_day: str
    used: bool
    trips_named: int
    explanation: str


class BlockLabelPreview(BaseModel):
    #: Complete counts, never sampled.
    rows_read: int
    matched: int
    ambiguous: int
    unmatched: int
    unparseable: int
    #: Blocks that would be named, and the rows supporting them.
    labels_derived: int
    #: Blocks two rows disagreed about — excluded, never picked between.
    conflicts: int
    ambiguous_examples: list[ProblemRow] = []
    unmatched_examples: list[ProblemRow] = []
    unparseable_examples: list[ProblemRow] = []
    conflict_notes: list[str] = []
    #: One line per service day in the file, saying whether it was used to
    #: separate blocks and why. A narrowing nobody can inspect is a narrowing
    #: nobody should trust.
    service_days: list[ServiceDayNote] = []
    examples_capped_at: int = SAMPLE_CAP
    note: str


def _parse_schedule_date(raw: Optional[str]):
    """The schedule period the operator declared, or None.

    Optional on purpose: an upload without one behaves exactly as it did
    before, and the report says which service days went unpaired as a
    result — so the date is offered as a fix for a stated problem rather
    than demanded up front.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return dt.date.fromisoformat(raw.strip())
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{raw!r} is not a date Headway can read. Use the year, "
                f"month and day — for example 2026-08-01."
            ),
        )


def _spec_path() -> Path:
    for candidate in _SPEC_CANDIDATES:
        if candidate.is_file():
            return candidate
    raise HTTPException(
        status_code=503,
        detail=(
            "This installation does not carry the trip-name rules needed to "
            "read your export, so nothing can be matched. That is a packaging "
            "fault, not something you did — please report it."
        ),
    )


def _read_upload(upload: UploadFile) -> bytes:
    raw = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"That file is larger than "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB, which is far bigger "
                f"than a trip-to-block export should ever be. Check that you "
                f"sent the mapping file and not a data extract."
            ),
        )
    if not raw.strip():
        raise HTTPException(
            status_code=422,
            detail="That file is empty — nothing was uploaded to read.",
        )
    return raw


def _derive(raw: bytes):
    """Parse and derive. Both endpoints run this identical path."""
    from headway_transform.adapters.resolution import load_resolution_spec
    from headway_transform.block_labels import (
        MappingFileError,
        MappingRow,
        derive_block_labels,
        load_active_service_ids,
        load_scheduled_trips,
        pair_service_days,
    )

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=422,
            detail=(
                "That file is not plain text, so its rows cannot be read. If "
                "it was saved from a spreadsheet, save it again as CSV."
            ),
        )

    rows: list[MappingRow] = []
    for line_no, fields in enumerate(csv.reader(io.StringIO(text)), start=1):
        if not fields or not any(f.strip() for f in fields):
            continue
        if len(fields) < 2:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Line {line_no} has only one column. This file needs at "
                    f"least two: the trip name, then the block name."
                ),
            )
        trip_name, block_name = fields[0].strip(), fields[1].strip()
        # Column 3, when present, is the export's service day. It used to be
        # discarded ("extra columns are ignored"); measured 2026-08-04, it is
        # the single thing that separates a weekday block from a Saturday one.
        service_day = fields[2].strip() if len(fields) > 2 else None
        # A header row is tolerated rather than required — SSMS omits headers
        # when saving a grid, and demanding one would fail the common case.
        if line_no == 1 and trip_name.lower().replace(" ", "") == "tripname":
            continue
        if not trip_name or not block_name:
            continue
        rows.append(MappingRow(line_no=line_no, trip_name=trip_name,
                               block_name=block_name,
                               service_day=service_day or None))
    if not rows:
        raise HTTPException(
            status_code=422,
            detail=(
                "No usable rows were found. Each line needs a trip name and a "
                "block name, separated by a comma."
            ),
        )
    try:
        spec = load_resolution_spec(_spec_path())
    except MappingFileError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return (spec, rows, load_scheduled_trips, derive_block_labels,
            pair_service_days, load_active_service_ids)


def _samples(outcomes, status: str) -> list[ProblemRow]:
    return [
        ProblemRow(
            line=o.row.line_no,
            trip_name=o.row.trip_name,
            block_name=o.row.block_name,
            reason=o.reason,
        )
        for o in outcomes
        if o.status == status
    ][:SAMPLE_CAP]


def _to_preview(result, rows_read: int, note: str, pairings=None
) -> BlockLabelPreview:
    from headway_transform.block_labels import (
        AMBIGUOUS,
        MATCHED,
        UNMATCHED,
        UNPARSEABLE,
    )

    return BlockLabelPreview(
        rows_read=rows_read,
        matched=result.counts.get(MATCHED, 0),
        ambiguous=result.counts.get(AMBIGUOUS, 0),
        unmatched=result.counts.get(UNMATCHED, 0),
        unparseable=result.counts.get(UNPARSEABLE, 0),
        labels_derived=len(result.mapping),
        conflicts=len(result.conflicts),
        ambiguous_examples=_samples(result.outcomes, AMBIGUOUS),
        unmatched_examples=_samples(result.outcomes, UNMATCHED),
        unparseable_examples=_samples(result.outcomes, UNPARSEABLE),
        service_days=[
            ServiceDayNote(
                service_day=p.service_day,
                used=p.confident,
                trips_named=p.keys_in_export,
                explanation=(
                    f"Used to tell blocks apart — {p.reason}."
                    if p.confident
                    else f"Not used — {p.reason}."
                ),
            )
            for p in sorted(
                (pairings or {}).values(),
                key=lambda x: (not x.confident, x.service_day),
            )
        ],
        conflict_notes=[
            f"Block {c.block_id} was given {len(c.labels)} different names "
            f"({', '.join(sorted(c.labels))}) — left out rather than guessed at."
            for c in result.conflicts
        ],
        note=note,
    )


@router.post("/admin/block-labels/preview", response_model=BlockLabelPreview)
def preview_block_labels(
    file: UploadFile = File(...),
    schedule_date: Optional[str] = Form(default=None),
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> BlockLabelPreview:
    """Read the export and report what WOULD happen. Writes nothing."""
    raw = _read_upload(file)
    on_date = _parse_schedule_date(schedule_date)
    spec, rows, load_trips, derive, pair, load_active = _derive(raw)
    trips = load_trips(db)
    active = load_active(db, on_date) if on_date else None
    pairings = pair(spec, rows, trips, active)
    result = derive(spec, rows, trips, pairings)
    return _to_preview(
        result,
        len(rows),
        pairings=pairings,
        note=(
            "Nothing has been saved. This is what the file would do if you "
            "load it. Rows listed as ambiguous, unmatched or unreadable are "
            "left out — Headway never guesses a block's name."
        ),
    )


@router.post("/admin/block-labels/load", response_model=BlockLabelPreview)
def load_block_label_mapping(
    file: UploadFile = File(...),
    schedule_date: Optional[str] = Form(default=None),
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> BlockLabelPreview:
    """Derive again from these exact bytes and write the mapping.

    Findings raised BEFORE this load keep the names they were raised with —
    history is never rewritten (handoff 0038). Only findings raised afterwards
    read the new names.
    """
    from headway_transform.block_labels import load_block_labels

    raw = _read_upload(file)
    on_date = _parse_schedule_date(schedule_date)
    spec, rows, load_trips, derive, pair, load_active = _derive(raw)
    trips = load_trips(db)
    active = load_active(db, on_date) if on_date else None
    pairings = pair(spec, rows, trips, active)
    result = derive(spec, rows, trips, pairings)

    # The same provenance the CLI writes (tools/block-labels/derive.py): the
    # bytes' own digest, and the parse config that read them. Both are needed
    # to answer "which file named this block, and by what rules?" months later.
    digest = hashlib.sha256(raw).hexdigest()
    source = f"{file.filename or 'uploaded file'} sha256={digest}"
    derivation = (
        f"admin upload by {identity.username}: TripName parsed per "
        f"{_spec_path().name} (config {spec.spec_sha12}), matched on "
        f"(route_short_name, first scheduled departure"
        + (f", service day scoped to {on_date.isoformat()}" if on_date else "")
        + f") against "
        f"canonical.trips; only rows whose every candidate trip shares one "
        f"feed block_id landed; ambiguous/unmatched/conflicting rows "
        f"reported, never guessed (handoff 0038)."
    )

    with db.transaction():
        written = load_block_labels(
            db,
            result,
            source=source,
            derivation=derivation,
            loaded_by=identity.username,
        )
        write_event(
            db,
            actor=identity.username,
            action="block_labels_loaded",
            subject_kind="canonical.block_labels",
            subject_id=file.filename or "uploaded file",
            detail={
                "rows_read": len(rows),
                "labels_written": written,
                "matched": result.counts.get("matched", 0),
                "ambiguous": result.counts.get("ambiguous", 0),
                "unmatched": result.counts.get("unmatched", 0),
                "unparseable": result.counts.get("unparseable", 0),
                "conflicts": len(result.conflicts),
                "file_sha256": digest,
                "schedule_date": on_date.isoformat() if on_date else None,
            },
        )
    return _to_preview(
        result,
        len(rows),
        pairings=pairings,
        note=(
            f"Saved. {written} blocks will now be named the way your run board "
            f"names them, on findings raised from here on. Findings raised "
            f"before this keep the names they were raised with — Headway does "
            f"not rewrite history."
        ),
    )
