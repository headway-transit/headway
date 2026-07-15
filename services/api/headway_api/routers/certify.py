"""The certification action: authenticated, authorized, immutably audited —
and, since handoff 0019, SIGNED.

Certification is a human legally attesting the figures are correct. It is
gated to exactly the certifying_official role, and the certification row,
the status update, and the audit event commit in ONE transaction — there is
no code path that certifies silently or partially.

The signature (handoff 0019, design point B): the certifier types their
full name and title against the intent statement; the server assembles the
CANONICAL DOCUMENT (everything the signature covers: the figures with
receipt hashes, the certifier's identity and typed name/title, the
acknowledgment text, any statistician attestations the figures carry, the
timestamp — headway_api.signing documents the byte-precise
canonicalization), signs it with the installation Ed25519 key, and stores
document + signature + key fingerprint on the certification row (migration
0030). If the signing key is unavailable the certification REFUSES with a
503 — a certification is never silently recorded unsigned. Certifications
made before migration 0030 keep NULL signature columns forever: honest
history, never backfilled.

Verification: GET /certifications/{id}/verify re-verifies the STORED
document bytes against the STORED signature with the installation key, and
additionally checks the document is bound to this very row (its
certification_id and covered figure ids match) — so a swapped
document/signature pair from another record fails even though the
cryptography alone would pass. Any mutation of the stored document or
signature fails LOUDLY (the handoff-0019 tamper test pins this).

Blocking-DQ refusal (v0, deliberately simple and honest): certification is
refused if ANY category='ntd' dq.issues row with severity='blocking' is
still open or owned — 'resolved' and 'attested' (the p. 146
statistician-attestation closure, migration 0029) are the two closed
states. Lineage-scoped blocking is the NEXT increment; until then we
over-refuse rather than ever certify over an unresolved blocking gap.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import webhooks
from ..audit import write_event
from ..auth import Identity
from ..authz import require_authenticated, require_certifying_official
from ..db import get_db
from ..signing import SigningKeyUnavailable, get_signer, receipt_sha256
from .metrics import _detail_as_dict

router = APIRouter(tags=["certification"])

#: The ESIGN-style intent statement the typed name and title are entered
#: against (design point B.8 — plain language, reviewed): signing is
#: deliberate, electronic, and attributable.
INTENT_STATEMENT = (
    "By typing my full name and title and submitting, I am signing this "
    "certification electronically. I have reviewed each figure listed on "
    "this certificate, including its data-quality record and the "
    "regulatory basis shown on its receipt, and I attest that to the best "
    "of my knowledge these figures are accurate and complete. I intend "
    "this electronic signature to carry the same weight as my handwritten "
    "signature."
)

#: The honest-scope statement, ON the certificate itself (design point
#: B.8): what an installation-held key does and does not prove.
SIGNATURE_SCOPE_STATEMENT = (
    "This certificate is signed with this Headway installation's signing "
    "key. The signature proves the certified record has not been altered "
    "since it was signed (integrity) and ties the signing to this "
    "installation and the signed-in certifying official named above "
    "(attribution within this system). It is not a personal "
    "public-key-infrastructure signature: the installation, not the "
    "certifier, holds the key, so it does not by itself prove WHO pressed "
    "the button beyond this system's own login records. Personal signing "
    "keys held by each certifier (WebAuthn) are the documented next "
    "version."
)

DOCUMENT_TYPE = "headway-certification"
DOCUMENT_VERSION = 1


class CertificationRequest(BaseModel):
    metric_value_ids: list[str] = Field(min_length=1)
    attestation: str = Field(min_length=1)
    # The signature block (handoff 0019): the typed full name and title are
    # the signing ceremony's deliberate act, entered against
    # INTENT_STATEMENT (served by GET /certifications/intent for the UI).
    signer_full_name: str = Field(min_length=1)
    signer_title: str = Field(min_length=1)


class CertificationResponse(BaseModel):
    certification_id: str
    metric_value_ids: list[str]
    certified_by: str
    certified_at: dt.datetime
    attestation: str
    signer_full_name: str
    signer_title: str
    # The signature block, verbatim as stored (migration 0030).
    canonical_document: str
    signature: str
    key_fingerprint: str
    algorithm: str = "ed25519"
    audit_event_id: int


class CertificationRecord(BaseModel):
    """One certification as listed/viewed. Legacy (pre-signature) records
    carry signed=false and NULL signature fields — honest history."""

    certification_id: str
    metric_value_ids: list[str]
    certified_by: str
    certified_at: dt.datetime
    attestation: str
    signed: bool
    key_fingerprint: Optional[str]
    signer_full_name: Optional[str]
    signer_title: Optional[str]


class VerificationResult(BaseModel):
    certification_id: str
    signed: bool
    #: None for unsigned legacy records (nothing to verify); True/False
    #: otherwise.
    verified: Optional[bool]
    #: 'verified' | 'failed' | 'unsigned_legacy' | 'key_mismatch'
    verdict: str
    algorithm: str = "ed25519"
    key_fingerprint: Optional[str] = None
    certified_at: dt.datetime
    message: str


class CertificationCertificate(CertificationRecord):
    """The full certificate view (the frontend's certificate screen):
    the stored canonical document (raw signed text + parsed object), the
    signature, and a live verification result."""

    canonical_document: Optional[str]
    signature: Optional[str]
    document: Optional[dict]
    verification: VerificationResult


class IntentResponse(BaseModel):
    intent_statement: str
    scope_statement: str
    algorithm: str = "ed25519"


# category = 'ntd' (migration 0024): only NTD-pipeline findings gate
# certification. An OPERATIONS finding (e.g. an otp_v0 cadence refusal) is
# owned and workflowed like any finding, but it is not a gap in any figure
# a certifying official attests to — ops must never freeze a federal
# attestation. Closed states are 'resolved' AND 'attested' (migration 0029:
# the p. 146 statistician closure).
_COUNT_OPEN_BLOCKING = (
    "SELECT count(*) FROM dq.issues "
    "WHERE severity = 'blocking' AND status IN ('open', 'owned') "
    "AND category = 'ntd'"
)

_SELECT_TARGETS = (
    "SELECT metric_value_id, certification_status, category "
    "FROM computed.metric_values WHERE metric_value_id = ANY(%s)"
)

#: The full figure rows the canonical document covers — value served as
#: text (NUMERIC precision; floating point never touches a figure).
_SELECT_FIGURES = (
    "SELECT metric_value_id, metric, unit, period_start, period_end, scope, "
    "value, calc_name, calc_version, category, detail "
    "FROM computed.metric_values WHERE metric_value_id = ANY(%s)"
)

_INSERT_CERTIFICATION = (
    "INSERT INTO cert.certifications (certification_id, metric_value_ids, "
    "certified_by, certified_at, attestation, canonical_document, "
    "signature, key_fingerprint) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
    "RETURNING certification_id, certified_at"
)

# AND category = 'ntd': defense in depth on top of the explicit ops
# refusal below and the database's metric_values_ops_never_certified CHECK
# (migration 0024) — no code path can flip an OPERATIONS figure to
# certified.
_MARK_CERTIFIED = (
    "UPDATE computed.metric_values SET certification_status = 'certified' "
    "WHERE metric_value_id = ANY(%s) AND category = 'ntd'"
)

_CERT_COLUMNS = (
    "certification_id, metric_value_ids, certified_by, certified_at, "
    "attestation, canonical_document, signature, key_fingerprint"
)

_SELECT_CERTIFICATIONS = (
    f"SELECT {_CERT_COLUMNS} FROM cert.certifications "
    "ORDER BY certified_at, certification_id"
)

_SELECT_CERTIFICATION = (
    f"SELECT {_CERT_COLUMNS} FROM cert.certifications "
    "WHERE certification_id = %s"
)


def _value_as_text(value) -> str:
    return str(value) if isinstance(value, Decimal) else str(Decimal(str(value)))


def _figure_receipt(row) -> dict:
    """One figure exactly as the signature covers it. The receipt hash is
    SHA-256 over the canonical bytes (headway_api.signing.canonical_bytes)
    of this dict MINUS the hash key itself — independently recomputable
    from the served figure."""
    figure = {
        "metric_value_id": str(row[0]),
        "metric": row[1],
        "unit": row[2],
        "period_start": row[3].isoformat(),
        "period_end": row[4].isoformat(),
        "scope": row[5],
        "value": _value_as_text(row[6]),
        "calc_name": row[7],
        "calc_version": row[8],
        "category": row[9],
        "detail": _detail_as_dict(row[10]),
    }
    figure["receipt_sha256"] = receipt_sha256(figure)
    return figure


def _signer_identity_from_document(
    canonical_document: str | None,
) -> tuple[Optional[str], Optional[str]]:
    """The typed name/title out of a stored document; (None, None) for
    legacy unsigned records or an unparseable document (the verify
    endpoint is where unparseable screams; a list view stays serveable)."""
    if canonical_document is None:
        return None, None
    try:
        certifier = json.loads(canonical_document).get("certifier", {})
        return certifier.get("typed_full_name"), certifier.get("typed_title")
    except (ValueError, AttributeError):
        return None, None


def _record_from_row(row) -> CertificationRecord:
    name, title = _signer_identity_from_document(row[5])
    return CertificationRecord(
        certification_id=str(row[0]),
        metric_value_ids=[str(i) for i in row[1]],
        certified_by=row[2],
        certified_at=row[3],
        attestation=row[4],
        signed=row[6] is not None,
        key_fingerprint=row[7],
        signer_full_name=name,
        signer_title=title,
    )


def verify_certification_row(app, row) -> VerificationResult:
    """Re-verify one stored certification row (shared by the authenticated
    and public verify endpoints, and the certificate view).

    Row shape: the _CERT_COLUMNS order. Verdicts:

    - 'unsigned_legacy' — pre-signature record (all three columns NULL);
      nothing to verify, verified is null.
    - 'key_mismatch'    — signed by a key this installation no longer
      holds (fingerprints differ); verified false, honestly inconclusive.
    - 'verified'        — the stored bytes match the stored signature
      under the installation key AND the document is bound to this row.
    - 'failed'          — anything else: the record was altered since
      signing, or the signature is corrupt, or the document belongs to a
      different certification. LOUD.
    """
    certification_id = str(row[0])
    canonical_document, signature, key_fingerprint = row[5], row[6], row[7]
    certified_at = row[3]
    if canonical_document is None:
        return VerificationResult(
            certification_id=certification_id,
            signed=False,
            verified=None,
            verdict="unsigned_legacy",
            key_fingerprint=None,
            certified_at=certified_at,
            message=(
                "This certification was recorded before digital signatures "
                "existed in Headway (it has no signature — honest history, "
                "never backfilled). There is nothing to verify; its "
                "authenticity rests on the audit trail alone."
            ),
        )
    try:
        signer = get_signer(app)
    except SigningKeyUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if signer.key_fingerprint != key_fingerprint:
        return VerificationResult(
            certification_id=certification_id,
            signed=True,
            verified=False,
            verdict="key_mismatch",
            key_fingerprint=key_fingerprint,
            certified_at=certified_at,
            message=(
                f"This certification was signed by key {key_fingerprint}, "
                f"but this installation currently holds key "
                f"{signer.key_fingerprint}. The signature cannot be checked "
                f"with the current key — if the installation key was "
                f"rotated, verification needs the original key. Treat this "
                f"as UNVERIFIED, not as proof of tampering."
            ),
        )
    crypto_ok = signer.verify(canonical_document, signature)
    binding_ok = False
    if crypto_ok:
        try:
            document = json.loads(canonical_document)
            covered = {str(f["metric_value_id"]) for f in document["figures"]}
            binding_ok = (
                document.get("certification_id") == certification_id
                and covered == {str(i) for i in row[1]}
            )
        except (ValueError, KeyError, TypeError):
            binding_ok = False
    if crypto_ok and binding_ok:
        return VerificationResult(
            certification_id=certification_id,
            signed=True,
            verified=True,
            verdict="verified",
            key_fingerprint=key_fingerprint,
            certified_at=certified_at,
            message=(
                "Verified: the stored certificate is byte-identical to what "
                "was signed, the signature is valid under this "
                "installation's key, and the document is bound to this "
                "certification record."
            ),
        )
    return VerificationResult(
        certification_id=certification_id,
        signed=True,
        verified=False,
        verdict="failed",
        key_fingerprint=key_fingerprint,
        certified_at=certified_at,
        message=(
            "VERIFICATION FAILED: the stored certification record does not "
            "match its signature"
            + (
                ""
                if crypto_ok
                else " (the signed bytes or the signature were altered)"
            )
            + (
                " (the signed document is not bound to this certification "
                "record)"
                if crypto_ok and not binding_ok
                else ""
            )
            + ". The record has been tampered with since signing, or is "
            "corrupt. Treat these figures as UNCERTIFIED and investigate "
            "immediately — the audit trail (audit.events) records every "
            "legitimate action."
        ),
    )


@router.get("/certifications/intent", response_model=IntentResponse)
def get_intent(
    identity: Identity = Depends(require_authenticated),
) -> IntentResponse:
    """The fixed statements the signing ceremony renders: the ESIGN-style
    intent statement the typed name/title are entered against, and the
    honest-scope statement printed on the certificate."""
    return IntentResponse(
        intent_statement=INTENT_STATEMENT,
        scope_statement=SIGNATURE_SCOPE_STATEMENT,
    )


@router.post(
    "/certifications", response_model=CertificationResponse, status_code=201
)
def certify(
    body: CertificationRequest,
    request: Request,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> CertificationResponse:
    ids = [str(i) for i in body.metric_value_ids]
    # The signing key is resolved BEFORE any check or write: without it the
    # whole action refuses (503) — a certification is never recorded
    # unsigned.
    try:
        signer = get_signer(request.app)
    except SigningKeyUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Certification refused: this installation has no signing "
                "key, so a tamper-evident certificate cannot be produced. "
                "Nothing was certified. "
            )
            + str(exc),
        ) from exc
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
        categories = {str(r[0]): r[2] for r in rows}
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
        ops_targets = [i for i in ids if categories[i] != "ntd"]
        if ops_targets:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Certification refused: some of the figures you selected "
                    "are operations metrics (for example on-time performance "
                    "or headway adherence), not NTD reported figures. "
                    "Operations metrics can never be certified or submitted "
                    "— certifying one would present an internal service "
                    "measure as a federal figure. Operations metric ids: "
                    + ", ".join(ops_targets)
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
        # --- assemble and sign the canonical document (handoff 0019) -----
        figure_rows = db.execute(_SELECT_FIGURES, (ids,)).fetchall()
        figures = sorted(
            (_figure_receipt(r) for r in figure_rows),
            key=lambda f: f["metric_value_id"],
        )
        # Statistician attestations the figures carry (upt_v0/pmt_v0 0.2.0
        # detail provenance) are acknowledged ON the certificate: unique by
        # attestation_id, sorted.
        attestations_by_id: dict[str, dict] = {}
        for figure in figures:
            att = figure["detail"].get("attestation")
            if isinstance(att, dict) and att.get("attestation_id"):
                attestations_by_id.setdefault(str(att["attestation_id"]), att)
        certification_id = str(uuid.uuid4())
        certified_at = dt.datetime.now(dt.timezone.utc)
        document = {
            "document_type": DOCUMENT_TYPE,
            "document_version": DOCUMENT_VERSION,
            "certification_id": certification_id,
            "certified_at": certified_at.isoformat(),
            "certifier": {
                "username": identity.username,
                "role": identity.role,
                "typed_full_name": body.signer_full_name,
                "typed_title": body.signer_title,
            },
            "intent_statement": INTENT_STATEMENT,
            "scope_statement": SIGNATURE_SCOPE_STATEMENT,
            "attestation_text": body.attestation,
            "figures": figures,
            "statistician_attestations": [
                attestations_by_id[k] for k in sorted(attestations_by_id)
            ],
        }
        signature_b64, payload = signer.sign(document)
        canonical_text = payload.decode("utf-8")
        cert_row = db.execute(
            _INSERT_CERTIFICATION,
            (
                certification_id,
                ids,
                identity.username,
                certified_at,
                body.attestation,
                canonical_text,
                signature_b64,
                signer.key_fingerprint,
            ),
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
                "signer_full_name": body.signer_full_name,
                "signer_title": body.signer_title,
                "key_fingerprint": signer.key_fingerprint,
                "algorithm": "ed25519",
                "statistician_attestation_ids": sorted(attestations_by_id),
            },
        )
    # STRICTLY POST-COMMIT (handoff 0006, design point 7): the certification
    # transaction above is already committed; webhook delivery is best-effort
    # with one retry, audit-logged, and can never fail this response.
    webhooks.dispatch_certification_created(
        db,
        getattr(request.app.state, "webhook_sender", None),
        certification_id=certification_id,
        metric_value_ids=ids,
        certified_by=identity.username,
        certified_at=certified_at,
    )
    return CertificationResponse(
        certification_id=certification_id,
        metric_value_ids=ids,
        certified_by=identity.username,
        certified_at=certified_at,
        attestation=body.attestation,
        signer_full_name=body.signer_full_name,
        signer_title=body.signer_title,
        canonical_document=canonical_text,
        signature=signature_b64,
        key_fingerprint=signer.key_fingerprint,
        audit_event_id=audit_event_id,
    )


@router.get("/certifications", response_model=list[CertificationRecord])
def list_certifications(
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[CertificationRecord]:
    """Every certification record, oldest first (any signed-in role — the
    record view; the public surface serves fingerprints only)."""
    rows = db.execute(_SELECT_CERTIFICATIONS, ()).fetchall()
    return [_record_from_row(r) for r in rows]


@router.get(
    "/certifications/{certification_id}",
    response_model=CertificationCertificate,
)
def get_certification(
    certification_id: str,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> CertificationCertificate:
    """The certificate view: the signature block (typed name/title,
    fingerprint), everything the signature covers (the parsed document),
    the raw signed bytes, and a live verification result."""
    row = db.execute(_SELECT_CERTIFICATION, (certification_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No certification with that id exists."
        )
    record = _record_from_row(row)
    document: Optional[dict] = None
    if row[5] is not None:
        try:
            document = json.loads(row[5])
        except ValueError:
            document = None  # verification below reports the failure loudly
    return CertificationCertificate(
        **record.model_dump(),
        canonical_document=row[5],
        signature=row[6],
        document=document,
        verification=verify_certification_row(request.app, row),
    )


@router.get(
    "/certifications/{certification_id}/verify",
    response_model=VerificationResult,
)
def verify_certification(
    certification_id: str,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> VerificationResult:
    """Re-verify the stored certificate against its stored signature (any
    signed-in role). The same check, without login, is
    GET /public/certifications/{id}/verify — it serves no certifier
    identity, only the verdict and fingerprint."""
    row = db.execute(_SELECT_CERTIFICATION, (certification_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No certification with that id exists."
        )
    return verify_certification_row(request.app, row)
