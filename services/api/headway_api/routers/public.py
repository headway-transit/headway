"""Open data: certified figures, unauthenticated (handoff 0006, point 8).

This is the transparency-view mandate in its minimal form, and the ONE
deliberate exception to "no unauthenticated endpoint" — approved by the
Security Engineer's binding design (handoff 0006, design point 8), not a
convenience. What keeps it safe:

- It serves ONLY rows with certification_status = 'certified' — figures a
  certifying official has already legally attested for public reporting.
- Values are strings (NUMERIC precision) and ``detail`` is served VERBATIM,
  including any simulated-data flags: transparency shows the flags, it never
  hides the figures.
- There is NO PII surface: aggregate metric values, units, periods, and calc
  identity only. Even the certifier's name is not served here — it lives in
  the authenticated certification record.
- Rate-limited per client IP (the same in-process token bucket as machine
  keys, with the same documented single-instance limitation).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..db import get_db
from ..machine_auth import enforce_rate_limit
from .certify import VerificationResult, verify_certification_row
from .metrics import _detail_as_dict

router = APIRouter(tags=["public"])


class PublicCertificationRef(BaseModel):
    """The public face of a certification (handoff 0019, design point 7):
    WHICH record certified the figure, WHEN, and the signing key's
    fingerprint — enough to verify tamper-evidence via
    GET /public/certifications/{id}/verify. NO certifier identity here
    (that lives in the authenticated record); a NULL fingerprint is a
    pre-signature legacy certification, honestly unsigned."""

    certification_id: str
    certified_at: dt.datetime
    key_fingerprint: Optional[str]


class PublicMetricValue(BaseModel):
    """A certified figure, publishable form. No PII, no certifier identity."""

    metric_value_id: str
    metric: str
    unit: str
    period_start: dt.date
    period_end: dt.date
    scope: str
    value: str  # NUMERIC as a string — floating point never touches a figure
    calc_name: str
    calc_version: str
    computed_at: dt.datetime
    certification_status: str  # always 'certified' here
    detail: dict[str, Any] = {}  # served verbatim, simulated flags included
    # Always 'ntd' here: OPERATIONS figures (category 'ops', handoff 0014 /
    # migration 0024) are structurally uncertifiable AND hard-excluded by
    # this router's WHERE clause — they can never be published as certified
    # open data. Served so the payload states its own category.
    category: str = "ntd"
    # The certification that covers this figure (handoff 0019, design point
    # 7). None only if the certification row is unexpectedly absent.
    certification: Optional[PublicCertificationRef] = None


_SELECT_CERTIFIED = (
    "SELECT metric_value_id, metric, unit, period_start, period_end, scope, "
    "value, calc_name, calc_version, computed_at, certification_status, "
    "detail, category FROM computed.metric_values "
    "WHERE certification_status = 'certified' "
    # The migration-0024 honesty boundary, hard-clause form: an OPERATIONS
    # figure must never surface here even if the ops-never-certified CHECK
    # were somehow bypassed — defense in depth, both layers tested.
    "AND category = 'ntd' "
    "ORDER BY period_start, metric"
)


#: Certification references for the public payload: id, timestamp, and key
#: fingerprint per covered metric_value_id. No certifier identity.
_SELECT_CERTIFICATION_REFS = (
    "SELECT certification_id, certified_at, key_fingerprint, "
    "metric_value_ids FROM cert.certifications"
)

_SELECT_CERTIFICATION_ROW = (
    "SELECT certification_id, metric_value_ids, certified_by, certified_at, "
    "attestation, canonical_document, signature, key_fingerprint "
    "FROM cert.certifications WHERE certification_id = %s"
)


def _certification_refs_by_metric_value(db) -> dict[str, PublicCertificationRef]:
    refs: dict[str, PublicCertificationRef] = {}
    for row in db.execute(_SELECT_CERTIFICATION_REFS, ()).fetchall():
        ref = PublicCertificationRef(
            certification_id=str(row[0]),
            certified_at=row[1],
            key_fingerprint=row[2],
        )
        for metric_value_id in row[3]:
            refs[str(metric_value_id)] = ref
    return refs


@router.get("/public/metrics/certified", response_model=list[PublicMetricValue])
def list_certified_values(request: Request) -> list[PublicMetricValue]:
    # UNAUTHENTICATED by design (see module docstring) — so no identity
    # dependency, and the only per-caller control is the IP token bucket.
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(request.app.state.public_rate_limiter, client_ip)
    db = get_db(request)
    rows = db.execute(_SELECT_CERTIFIED, ()).fetchall()
    certification_refs = _certification_refs_by_metric_value(db)
    return [
        PublicMetricValue(
            metric_value_id=str(r[0]),
            metric=r[1],
            unit=r[2],
            period_start=r[3],
            period_end=r[4],
            scope=r[5],
            value=str(r[6]) if isinstance(r[6], Decimal) else str(Decimal(str(r[6]))),
            calc_name=r[7],
            calc_version=r[8],
            computed_at=r[9],
            certification_status=r[10],
            detail=_detail_as_dict(r[11]),
            category=r[12],
            certification=certification_refs.get(str(r[0])),
        )
        for r in rows
    ]


@router.get(
    "/public/certifications/{certification_id}/verify",
    response_model=VerificationResult,
)
def public_verify_certification(
    certification_id: str, request: Request
) -> VerificationResult:
    """Public tamper-evidence check (handoff 0019, design point 6/7):
    re-verifies the stored certificate bytes against the stored Ed25519
    signature, server-side, and returns the verdict.

    PUBLIC-SAFE by construction: the response carries the verdict,
    algorithm, fingerprint, and timestamp — never the certifier's identity,
    never the document, never any auth material. Rate-limited per client IP
    exactly like /public/metrics/certified (which serves the
    certification_id + fingerprint this endpoint verifies)."""
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(request.app.state.public_rate_limiter, client_ip)
    db = get_db(request)
    row = db.execute(_SELECT_CERTIFICATION_ROW, (certification_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No certification with that id exists."
        )
    return verify_certification_row(request.app, row)
