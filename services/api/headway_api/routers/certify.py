"""The certification action: authenticated, authorized, and immutably audited.

Certification is a human legally attesting the figures are correct. It is
gated to exactly the certifying_official role, and the certification row, the
status update, and the audit event commit in ONE transaction — there is no
code path that certifies silently or partially.

Blocking-DQ refusal (v0, deliberately simple and honest): certification is
refused if ANY dq.issues row with severity='blocking' is not yet resolved —
whether or not it is linked by lineage to the figures being certified.
Lineage-scoped blocking (refuse only when a blocking issue touches the
lineage of a submitted metric value) is the NEXT increment; until then we
over-refuse rather than ever certify over an unresolved blocking gap.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..audit import write_event
from ..auth import Identity
from ..authz import require_certifying_official
from ..db import get_db

router = APIRouter(tags=["certification"])


class CertificationRequest(BaseModel):
    metric_value_ids: list[str] = Field(min_length=1)
    attestation: str = Field(min_length=1)


class CertificationResponse(BaseModel):
    certification_id: str
    metric_value_ids: list[str]
    certified_by: str
    certified_at: dt.datetime
    attestation: str
    audit_event_id: int


_COUNT_OPEN_BLOCKING = (
    "SELECT count(*) FROM dq.issues "
    "WHERE severity = 'blocking' AND status <> 'resolved'"
)

_SELECT_TARGETS = (
    "SELECT metric_value_id, certification_status "
    "FROM computed.metric_values WHERE metric_value_id = ANY(%s)"
)

_INSERT_CERTIFICATION = (
    "INSERT INTO cert.certifications (metric_value_ids, certified_by, attestation) "
    "VALUES (%s, %s, %s) RETURNING certification_id, certified_at"
)

_MARK_CERTIFIED = (
    "UPDATE computed.metric_values SET certification_status = 'certified' "
    "WHERE metric_value_id = ANY(%s)"
)


@router.post(
    "/certifications", response_model=CertificationResponse, status_code=201
)
def certify(
    body: CertificationRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> CertificationResponse:
    ids = [str(i) for i in body.metric_value_ids]
    # One transaction: refusal checks, certification insert, status update,
    # and the audit event all commit or abort together.
    with db.transaction():
        (open_blocking,) = db.execute(_COUNT_OPEN_BLOCKING, ()).fetchone()
        if open_blocking > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Certification refused: {open_blocking} blocking data-"
                    f"quality issue(s) are still unresolved. Every blocking "
                    f"issue must be resolved before any figure can be "
                    f"certified, because certifying over a known data gap "
                    f"would attest to numbers we know may be wrong."
                ),
            )
        rows = db.execute(_SELECT_TARGETS, (ids,)).fetchall()
        found = {str(r[0]): r[1] for r in rows}
        missing = [i for i in ids if i not in found]
        if missing:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Certification refused: some of the figures you selected "
                    "do not exist. Please refresh and try again. Unknown "
                    "ids: " + ", ".join(missing)
                ),
            )
        already = [i for i in ids if found[i] == "certified"]
        if already:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Certification refused: some of the figures you selected "
                    "are already certified. Certifying the same figure twice "
                    "would blur who attested to it and when. Already "
                    "certified: " + ", ".join(already)
                ),
            )
        cert_row = db.execute(
            _INSERT_CERTIFICATION, (ids, identity.username, body.attestation)
        ).fetchone()
        certification_id, certified_at = str(cert_row[0]), cert_row[1]
        updated = db.execute(_MARK_CERTIFIED, (ids,))
        if getattr(updated, "rowcount", len(ids)) != len(ids):
            # Defensive: the rows we just verified must all update. If not,
            # something changed under us — abort everything, loudly.
            raise HTTPException(
                status_code=409,
                detail=(
                    "Certification refused: the figures changed while your "
                    "certification was being recorded. Nothing was certified. "
                    "Please refresh and try again."
                ),
            )
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="certify",
            subject_kind="cert.certifications",
            subject_id=certification_id,
            detail={
                "metric_value_ids": ids,
                "attestation": body.attestation,
                "certified_by_role": identity.role,
            },
        )
    return CertificationResponse(
        certification_id=certification_id,
        metric_value_ids=ids,
        certified_by=identity.username,
        certified_at=certified_at,
        attestation=body.attestation,
        audit_event_id=audit_event_id,
    )
