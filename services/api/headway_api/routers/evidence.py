"""The evidence bundle — what an auditor takes away (handoff 0047, design 5).

WHY THIS EXISTS
---------------
An auditor does not review a system; they review a filing, and then they leave
with the file. Everything else in this API answers a question while you are
looking at the screen. ``GET /certifications/{id}/evidence`` is the one surface
that produces a document you can carry out of the building, read next year, and
show to someone who has never heard of Headway.

So it has to be self-describing. The bundle states what it is, who it was
generated for, what it contains, what it deliberately does NOT contain, and how
to check that nobody edited it after download — without a Headway installation
to ask.

WHAT IS IN IT
-------------
- **The certification**: its signed bytes verbatim, the signature block, and
  the server-computed verification verdict (the same
  ``verify_certification_row`` the certificate screen shows — never a second
  opinion).
- **Every covered figure**: the value exactly as the calculation library
  persisted it (a JSON string of the exact NUMERIC — floating point never
  touches a reported figure), its receipt object byte-for-byte as the
  signature covers it, and whether that receipt still matches the signed
  document.
- **Every figure's lineage walk**, from ``routers.metrics.lineage_tree`` — the
  SAME walk ``GET /metrics/values/{id}/lineage`` serves, so the bundle and the
  "explain this number" screen cannot disagree.
- **Every raw-record leaf**: its id (which IS the SHA-256 of its bytes), its
  label, and its sensitivity classification.
- **A manifest**: every artifact with its SHA-256, plus ``bundle_sha256`` over
  the canonical serialization of the bundle itself.

WHAT IS DELIBERATELY NOT IN IT
------------------------------
**Labels and digests, never bulk bytes** (handoff 0047, open question 1,
decided). A raw record's id is the SHA-256 of its bytes, so the manifest
already carries every digest without re-reading a single byte. Re-reading them
would need the batched broker read handoff 0035 left unbuilt, and past the
broker's retention window most realtime leaves answer ``410 not_retained``
anyway — a bundle that stalled for minutes and then reported "unverifiable" for
most of its own contents would be worse than one that is honest about its
scope. Per-record verification stays the auditor's own deliberate action:
``POST /raw/records/{id}/verify``, which handoff 0047 made reachable by the
auditor role precisely so this is possible.

**Withheld payloads, for anyone.** Content sensitivity is evaluated through
``authz.may_read_sensitivity``, which puts an ``auditor`` at VIEWER breadth on
purpose — a paratransit pickup coordinate is a rider's home address, and an ADA
trip record discloses disability status by existing. (The API's rule is
``raw_payloads.classify`` + ``RESTRICTED_MINIMUM_ROLE``; migration 0028 is the
separate SQL-layer rule for the analyst role. Same decision, two boundaries.)
That withholding is NOT waived for an auditor, so the bundle is **role-sensitive**:
two accounts asking for the same certification can legitimately get different
``withheld`` lists. Which account it was generated for is recorded ON the
bundle, so a reader can never mistake "withheld from this reader" for "not in
the system".

TWO KINDS OF ABSENCE, NEVER MIXED
---------------------------------
- ``withheld`` — left out ON PURPOSE, by the sensitivity rule, naming the
  server's own refusal VERBATIM.
- ``gaps`` — could not be produced: a covered figure that no longer exists, a
  figure with no recorded lineage, a lineage leaf that is not in the raw-record
  index, a receipt that no longer matches the signed document.

Collapsing them would let a privacy decision read as a data defect, or a data
defect read as a privacy decision. Both readings produce a wrong finding
against an agency.

AUDIT
-----
Generating a bundle writes an append-only ``evidence_bundle_generated`` row:
actor, certification id, the counts, the ids and classifications of what was
withheld, and the bundle's own hash. Never the withheld content — the record of
a refusal must not become a copy of the thing refused.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import raw_payloads, signing
from ..audit import write_event
from ..auth import Identity
from ..authz import may_read_sensitivity, require_authenticated, role_label
from ..db import get_db
# The certification's own queries and assemblers are reused rather than
# re-stated (``certify._SELECT_CERTIFICATION``, ``_record_from_row``,
# ``_SELECT_FIGURES``, ``_figure_receipt``, ``verify_certification_row``): a
# bundle that computed a receipt hash differently from the signing path would
# report every certification as altered. Same-package internal reuse, the way
# ``certify`` already imports ``metrics._detail_as_dict``.
from . import certify, raw_records
from .metrics import LineageNode, lineage_tree

router = APIRouter(tags=["certification"])

UTC = dt.timezone.utc

BUNDLE_TYPE = "headway-evidence-bundle"
BUNDLE_VERSION = 1

#: How many raw-record leaves get a full label in one bundle.
#:
#: A single VRH figure can bottom out in over a thousand realtime frames
#: (handoff 0035 measured 1,138), and a certification covers many figures, so an
#: uncapped label list makes the response size a function of the pipeline's
#: fan-out. The cap bounds the LABELS only: every leaf's id — which is its
#: digest, and therefore the evidence — is in the lineage walk regardless, and
#: when the cap bites the bundle says so in ``gaps`` with the exact number
#: omitted and where to fetch them one at a time.
MAX_RAW_RECORD_LABELS = 5000

CANONICALIZATION = (
    "json.dumps(bundle, sort_keys=True, separators=(',', ':'), "
    "ensure_ascii=True, allow_nan=False).encode('utf-8')"
)

EXCLUDED_FIELD = "manifest.bundle_sha256"

BUNDLE_SHA256_RECIPE = (
    "To check this bundle has not been edited since Headway produced it: "
    "take this whole JSON document, delete the single field "
    "manifest.bundle_sha256 (delete the field itself — do not blank it, do "
    "not replace it with null), serialize what is left with "
    + CANONICALIZATION
    + ", and take the SHA-256 of those bytes as lowercase hex. It must equal "
    "manifest.bundle_sha256. That serialization is deterministic — object "
    "keys sorted at every level, no whitespace, every non-ASCII character "
    "escaped — so it does not matter what order your JSON library read the "
    "fields in, and it is the same recipe Headway uses for the certification "
    "signature itself (services/api/headway_api/signing.py). Every figure in "
    "this bundle is a JSON string, never a number, so no decimal rounding can "
    "change the bytes you hash."
)

SCOPE_NOTE = (
    "This bundle carries labels and digests, not stored payload bytes. Every "
    "raw source record's id IS the SHA-256 of the bytes Headway received, so "
    "the manifest already proves what each record contained without copying "
    "it here. To have Headway re-read a record's stored bytes and re-compute "
    "that hash in front of you, use POST /raw/records/{record_id}/verify on "
    "the record you care about — an auditor account may do this. Records "
    "whose bytes rode inline on the message broker may answer that the broker "
    "no longer retains them: that is a retention setting on this "
    "installation, not a failed check and not a missing record."
)

WITHHOLDING_NOTE = (
    "The 'withheld' list names everything left out of this bundle because of "
    "content sensitivity, with Headway's own reason in full. It is not an "
    "error and it is not a data gap — those are listed separately under "
    "'gaps'. Withholding depends on the account this bundle was generated "
    "for, named above: another account may receive the same certification "
    "with a shorter or longer withheld list, and that is correct."
)

CONTENTS_NOTE = (
    "The stored bytes of this record are not copied into this bundle. Its id "
    "is their SHA-256, so the id is the proof of what they were."
)


# ------------------------------------------------------------------- models


class GeneratedFor(BaseModel):
    """Who this bundle was produced for. On the bundle because withholding
    depends on it — an unattributed bundle cannot be read safely."""

    username: str
    role: str
    role_label: str
    #: 'local' or 'oidc' — the same attribution the audit trail records.
    authenticated_via: str
    idp_issuer: Optional[str] = None
    idp_subject: Optional[str] = None
    note: str


class CertificationEvidence(BaseModel):
    """The certification itself: signature block, signed bytes, live verdict."""

    certification_id: str
    certified_by: str
    certified_at: dt.datetime
    attestation: str
    signed: bool
    algorithm: str = "ed25519"
    key_fingerprint: Optional[str] = None
    signer_full_name: Optional[str] = None
    signer_title: Optional[str] = None
    #: The exact signed text, byte-for-byte as stored (migration 0030).
    canonical_document: Optional[str] = None
    signature: Optional[str] = None
    #: The same bytes parsed, for reading. Null when unparseable — the
    #: verification verdict is where that screams.
    document: Optional[dict] = None
    verification: certify.VerificationResult


class FigureEvidence(BaseModel):
    """One covered figure, verbatim as the calculation library stored it.

    ``receipt`` is the figure's receipt object exactly as the certification
    signature covers it — served whole, including its own ``receipt_sha256``
    key, so a reader can re-canonicalize and re-hash it without being told
    which fields to pick. The flat fields beside it are the same values again,
    named, so a spreadsheet or a UI does not have to reach into the receipt.
    """

    metric_value_id: str
    metric: str
    unit: str
    period_start: dt.date
    period_end: dt.date
    scope: str
    #: The exact NUMERIC as a string. Never a float, never rounded, never
    #: recomputed — this API does not originate a reported figure.
    value: str
    calc_name: str
    calc_version: str
    category: str
    detail: dict[str, Any] = {}
    receipt: dict[str, Any]
    receipt_sha256: str
    #: The receipt hash recorded INSIDE the signed document for this figure.
    #: Null for a pre-signature certification (nothing was signed).
    signed_receipt_sha256: Optional[str] = None
    #: True when the stored figure still hashes to what was signed. False is a
    #: finding and is also listed in ``gaps``. Null when nothing was signed.
    matches_signed_document: Optional[bool] = None
    #: The provenance tree (routers.metrics.lineage_tree — the same walk
    #: GET /metrics/values/{id}/lineage serves). Null only when the walk
    #: refused, in which case ``lineage_error`` carries the reason verbatim
    #: and the failure is also listed in ``gaps``.
    lineage: Optional[LineageNode] = None
    lineage_sha256: Optional[str] = None
    lineage_error: Optional[str] = None
    #: The raw-record leaves this figure's walk bottoms out in, de-duplicated
    #: and sorted. Each id is the SHA-256 of that record's bytes.
    raw_record_ids: list[str] = []


class ContentAddress(BaseModel):
    algorithm: str
    digest: str
    note: str


class EvidenceSensitivity(BaseModel):
    classification: str
    label: str
    minimum_role: str
    reason: str
    #: Whether the account named in ``generated_for`` may open this record's
    #: contents at all (through the raw-record inspector). False means the
    #: record is also in ``withheld``.
    readable_by_this_account: bool
    #: Headway's refusal, verbatim, when it is not readable. Null when it is.
    refusal: Optional[str] = None


class RawRecordEvidence(BaseModel):
    """One raw-record leaf: the label on the evidence bag, and its seal."""

    record_id: str
    content_address: ContentAddress
    source: str
    connector: str
    connector_version: str
    content_type: str
    payload_encoding: str
    fetched_at: dt.datetime
    landed_at: dt.datetime
    parse_status: str
    parse_error: Optional[str] = None
    sensitivity: EvidenceSensitivity
    #: Always false in this version — see the module docstring. Stated as a
    #: field rather than left to the reader to notice.
    contents_included: bool = False
    contents_note: str = CONTENTS_NOTE


class WithheldItem(BaseModel):
    """Something left out ON PURPOSE, by the content-sensitivity rule."""

    kind: str
    id: str
    what: str
    classification: str
    minimum_role: str
    #: Headway's own refusal, word for word. Never paraphrased: a summary of a
    #: privacy refusal is how a reviewer ends up recording the wrong reason.
    reason: str


class BundleGap(BaseModel):
    """Something that could NOT be produced. A defect or an absence — never a
    withholding, which is a different list."""

    kind: str
    id: Optional[str] = None
    what: str
    detail: str


class ManifestEntry(BaseModel):
    artifact: str
    kind: str
    #: Where the artifact sits in this document, as a dotted path.
    location: str
    sha256: str
    #: Exactly which bytes this hash covers, in words.
    digest_of: str


class Manifest(BaseModel):
    artifact_count: int
    artifacts: list[ManifestEntry]
    withheld_count: int
    gap_count: int
    canonicalization: str = CANONICALIZATION
    excluded_field: str = EXCLUDED_FIELD
    bundle_sha256_recipe: str = BUNDLE_SHA256_RECIPE
    #: SHA-256 over this whole document with this field removed. The one
    #: field the hash does not cover, because it cannot cover itself.
    bundle_sha256: str


class EvidenceBundle(BaseModel):
    bundle_type: str = BUNDLE_TYPE
    bundle_version: int = BUNDLE_VERSION
    generated_at: dt.datetime
    generated_for: GeneratedFor
    scope_note: str = SCOPE_NOTE
    withholding_note: str = WITHHOLDING_NOTE
    certification: CertificationEvidence
    figures: list[FigureEvidence]
    raw_records: list[RawRecordEvidence]
    withheld: list[WithheldItem]
    gaps: list[BundleGap]
    manifest: Manifest


# ------------------------------------------------------------------ helpers


def _sha256_json(obj) -> str:
    """SHA-256 hex over ``signing.canonical_bytes(obj)`` — the one
    canonicalization this installation uses for everything it hashes."""
    return hashlib.sha256(signing.canonical_bytes(obj)).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _leaf_record_ids(node: LineageNode, into: set[str]) -> None:
    """Every ``raw.records`` id under one lineage node. Raw records are the
    bottom of the graph (migration 0005), so these are the leaves."""
    if node.kind == "raw.records":
        into.add(node.id)
    for child in node.inputs:
        _leaf_record_ids(child, into)


def _signed_receipts(document: Optional[dict]) -> dict[str, str]:
    """metric_value_id -> receipt_sha256, read out of the signed document.

    An unparseable or oddly-shaped document yields ``{}`` rather than an
    exception: the certification's own verification verdict is where a broken
    document is reported loudly, and it is already in this bundle.
    """
    if not isinstance(document, dict):
        return {}
    figures = document.get("figures")
    if not isinstance(figures, list):
        return {}
    out: dict[str, str] = {}
    for figure in figures:
        if isinstance(figure, dict) and "metric_value_id" in figure:
            digest = figure.get("receipt_sha256")
            if isinstance(digest, str):
                out[str(figure["metric_value_id"])] = digest
    return out


def _generated_for(identity: Identity) -> GeneratedFor:
    attribution = identity.audit_actor_detail()
    return GeneratedFor(
        username=identity.username,
        role=identity.role,
        role_label=role_label(identity.role),
        authenticated_via=attribution.get("authenticated_via", "local"),
        idp_issuer=attribution.get("idp_issuer"),
        idp_subject=attribution.get("idp_subject"),
        note=(
            f"Headway produced this bundle for the account "
            f"'{identity.username}', signed in as "
            f"{role_label(identity.role)}. What may be included depends on "
            f"that account: anything withheld from it is named in 'withheld' "
            f"with the reason. If you were given this file by someone else, "
            f"read the withheld list before concluding that something is "
            f"missing from Headway — it may only be missing from this copy."
        ),
    )


# ------------------------------------------------------------------- the bundle


@router.get(
    "/certifications/{certification_id}/evidence",
    response_model=EvidenceBundle,
    summary="Downloadable evidence bundle for one certification",
)
def certification_evidence(
    certification_id: str,
    request: Request,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> EvidenceBundle:
    """A self-describing evidence bundle for one certification.

    Open to any signed-in role. The bundle is ROLE-SENSITIVE: content
    sensitivity is evaluated for the calling account through
    ``authz.may_read_sensitivity``, so an auditor — who reads at viewer
    breadth on purpose (``raw_payloads.RESTRICTED_MINIMUM_ROLE``) — receives a
    bundle whose ``withheld`` list names the rider-location records it does not
    carry, with Headway's refusal in full. Nothing withheld appears anywhere
    else in the response.

    Generating a bundle is audited. Nothing in this endpoint changes a figure,
    a certification, or a raw record.
    """
    row = db.execute(certify._SELECT_CERTIFICATION, (certification_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                "No certification with that id exists, so there is no "
                "evidence bundle to produce. Check the id on the "
                "certification list."
            ),
        )

    record = certify._record_from_row(row)
    canonical_document, signature = row[5], row[6]
    document: Optional[dict] = None
    if canonical_document is not None:
        try:
            document = json.loads(canonical_document)
        except ValueError:
            document = None  # the verdict below reports this loudly
    verification = certify.verify_certification_row(request.app, row)

    gaps: list[BundleGap] = []

    # ---- the covered figures, verbatim -----------------------------------
    covered_ids = [str(i) for i in record.metric_value_ids]
    figure_rows = db.execute(certify._SELECT_FIGURES, (covered_ids,)).fetchall()
    receipts = {
        str(r[0]): certify._figure_receipt(r)
        for r in figure_rows
    }
    signed_receipts = _signed_receipts(document)

    for missing in sorted(set(covered_ids) - set(receipts)):
        gaps.append(
            BundleGap(
                kind="covered_figure_missing",
                id=missing,
                what="A figure this certification covers is not in the database",
                detail=(
                    f"The certification record lists figure {missing} as "
                    f"covered, but no such row exists in computed."
                    f"metric_values now. The figure cannot be shown or "
                    f"re-checked. Its receipt is still inside the signed "
                    f"document above, which is the record of what was "
                    f"attested to. This is a finding worth raising with "
                    f"whoever administers this installation."
                ),
            )
        )

    figures: list[FigureEvidence] = []
    all_leaf_ids: set[str] = set()
    for metric_value_id in sorted(receipts):
        receipt = receipts[metric_value_id]
        signed_digest = signed_receipts.get(metric_value_id)
        matches = (
            None
            if signed_digest is None
            else signed_digest == receipt["receipt_sha256"]
        )
        if matches is False:
            gaps.append(
                BundleGap(
                    kind="figure_changed_since_signing",
                    id=metric_value_id,
                    what="A covered figure no longer matches the signed document",
                    detail=(
                        f"Figure {metric_value_id} as stored today hashes to "
                        f"{receipt['receipt_sha256']}, but the signed "
                        f"certification records {signed_digest} for it. The "
                        f"signature itself is checked separately (see "
                        f"certification.verification). Treat this figure as "
                        f"unproven and investigate: the certificate attests to "
                        f"the signed values, not to these."
                    ),
                )
            )

        tree: Optional[LineageNode] = None
        lineage_error: Optional[str] = None
        try:
            tree = lineage_tree(db, metric_value_id)
        except HTTPException as exc:
            # Never swallowed: the reason is carried verbatim on the figure
            # AND listed as a gap. One figure without lineage must not blank a
            # whole bundle the auditor needs for the others.
            lineage_error = str(exc.detail)
            gaps.append(
                BundleGap(
                    kind="lineage_unavailable",
                    id=metric_value_id,
                    what="A covered figure's provenance could not be walked",
                    detail=lineage_error,
                )
            )
        leaves: set[str] = set()
        if tree is not None:
            _leaf_record_ids(tree, leaves)
            all_leaf_ids |= leaves

        figures.append(
            FigureEvidence(
                metric_value_id=metric_value_id,
                metric=receipt["metric"],
                unit=receipt["unit"],
                period_start=dt.date.fromisoformat(receipt["period_start"]),
                period_end=dt.date.fromisoformat(receipt["period_end"]),
                scope=receipt["scope"],
                value=receipt["value"],
                calc_name=receipt["calc_name"],
                calc_version=receipt["calc_version"],
                category=receipt["category"],
                detail=receipt["detail"],
                receipt=receipt,
                receipt_sha256=receipt["receipt_sha256"],
                signed_receipt_sha256=signed_digest,
                matches_signed_document=matches,
                lineage=tree,
                lineage_sha256=(
                    None if tree is None else _sha256_json(tree.model_dump(mode="json"))
                ),
                lineage_error=lineage_error,
                raw_record_ids=sorted(leaves),
            )
        )

    # ---- the raw-record leaves: label, digest, classification -------------
    leaf_ids = sorted(all_leaf_ids)
    labelled_ids = leaf_ids[:MAX_RAW_RECORD_LABELS]
    if len(leaf_ids) > len(labelled_ids):
        gaps.append(
            BundleGap(
                kind="raw_record_labels_capped",
                id=None,
                what="Not every raw-record leaf is labelled in this bundle",
                detail=(
                    f"This certification's figures bottom out in "
                    f"{len(leaf_ids):,} raw source records; this bundle "
                    f"labels the first {len(labelled_ids):,} of them (sorted "
                    f"by id) so the file stays a readable size. No evidence is "
                    f"lost: every leaf's id appears in its figure's lineage "
                    f"walk above, and a raw record's id IS the SHA-256 of its "
                    f"bytes. Fetch any remaining label with "
                    f"GET /raw/records/{{record_id}}."
                ),
            )
        )

    found = raw_records.load_records(db, labelled_ids)
    raw_record_evidence: list[RawRecordEvidence] = []
    withheld: list[WithheldItem] = []
    for record_id in labelled_ids:
        raw = found.get(record_id)
        if raw is None:
            gaps.append(
                BundleGap(
                    kind="raw_record_not_in_index",
                    id=record_id,
                    what="A lineage leaf is not in the raw-record index",
                    detail=(
                        f"The provenance trail names raw record {record_id} as "
                        f"a source for a certified figure, but there is no such "
                        f"row in this installation's raw-record index. A raw "
                        f"record is supposed to be permanent, so this is a real "
                        f"finding: the evidence behind anything computed from "
                        f"it cannot be produced. Report it to whoever "
                        f"administers this installation."
                    ),
                )
            )
            continue
        sensitivity = raw_payloads.classify(raw)
        readable = may_read_sensitivity(identity.role, sensitivity.minimum_role)
        if not readable:
            withheld.append(
                WithheldItem(
                    kind="raw_record_contents",
                    id=record_id,
                    what=(
                        f"The contents of raw source record {record_id} "
                        f"({sensitivity.label}). Its label, its classification "
                        f"and its SHA-256 are included above; only the "
                        f"contents are withheld."
                    ),
                    classification=sensitivity.classification,
                    minimum_role=sensitivity.minimum_role,
                    # VERBATIM. The server's own words, not a summary of them.
                    reason=sensitivity.refusal or sensitivity.reason,
                )
            )
        raw_record_evidence.append(
            RawRecordEvidence(
                record_id=raw.record_id,
                content_address=ContentAddress(
                    algorithm=raw_records.HASH_ALGORITHM,
                    digest=raw.record_id,
                    note=raw_records.CONTENT_ADDRESS_NOTE,
                ),
                source=raw.source,
                connector=raw.connector,
                connector_version=raw.connector_version,
                content_type=raw.content_type,
                payload_encoding=raw.payload_encoding,
                fetched_at=raw.fetched_at,
                landed_at=raw.landed_at,
                parse_status=raw.parse_status,
                # Content, not metadata (migration 0028's own words), so it
                # travels with the payload it describes and not with the label.
                parse_error=raw_payloads.visible_parse_error(
                    raw.parse_error, readable=readable
                ),
                sensitivity=EvidenceSensitivity(
                    classification=sensitivity.classification,
                    label=sensitivity.label,
                    minimum_role=sensitivity.minimum_role,
                    reason=sensitivity.reason,
                    readable_by_this_account=readable,
                    refusal=None if readable else sensitivity.refusal,
                ),
            )
        )

    # ---- the manifest ------------------------------------------------------
    artifacts: list[ManifestEntry] = []
    if canonical_document is not None:
        artifacts.append(
            ManifestEntry(
                artifact="certification.canonical_document",
                kind="signed_document",
                location="certification.canonical_document",
                sha256=_sha256_text(canonical_document),
                digest_of=(
                    "The UTF-8 bytes of the certification's signed document, "
                    "exactly as stored. This is what the Ed25519 signature "
                    "covers."
                ),
            )
        )
    if signature is not None:
        artifacts.append(
            ManifestEntry(
                artifact="certification.signature",
                kind="signature",
                location="certification.signature",
                sha256=_sha256_text(signature),
                digest_of=(
                    "The ASCII bytes of the base64 Ed25519 signature as "
                    "stored."
                ),
            )
        )
    for index, figure in enumerate(figures):
        artifacts.append(
            ManifestEntry(
                artifact=f"figure:{figure.metric_value_id}:receipt",
                kind="figure_receipt",
                location=f"figures[{index}].receipt",
                sha256=figure.receipt_sha256,
                digest_of=(
                    "The canonical JSON of this figure's receipt object with "
                    "its own receipt_sha256 key removed — the same recipe as "
                    "bundle_sha256, and the same hash the signed certification "
                    "carries for this figure."
                ),
            )
        )
        if figure.lineage_sha256 is not None:
            artifacts.append(
                ManifestEntry(
                    artifact=f"figure:{figure.metric_value_id}:lineage",
                    kind="lineage_walk",
                    location=f"figures[{index}].lineage",
                    sha256=figure.lineage_sha256,
                    digest_of=(
                        "The canonical JSON of this figure's provenance tree "
                        "as served here."
                    ),
                )
            )
    for index, raw_evidence in enumerate(raw_record_evidence):
        artifacts.append(
            ManifestEntry(
                artifact=f"raw_record:{raw_evidence.record_id}",
                kind="raw_record_bytes",
                location=f"raw_records[{index}]",
                sha256=raw_evidence.record_id,
                digest_of=(
                    "The raw source record's stored bytes, exactly as "
                    "received. The record's id IS that SHA-256 (migration "
                    "0002), which is why the digest is in this bundle even "
                    "though the bytes are not."
                ),
            )
        )

    bundle = EvidenceBundle(
        generated_at=dt.datetime.now(UTC),
        generated_for=_generated_for(identity),
        certification=CertificationEvidence(
            certification_id=record.certification_id,
            certified_by=record.certified_by,
            certified_at=record.certified_at,
            attestation=record.attestation,
            signed=record.signed,
            key_fingerprint=record.key_fingerprint,
            signer_full_name=record.signer_full_name,
            signer_title=record.signer_title,
            canonical_document=canonical_document,
            signature=signature,
            document=document,
            verification=verification,
        ),
        figures=figures,
        raw_records=raw_record_evidence,
        withheld=withheld,
        gaps=gaps,
        manifest=Manifest(
            artifact_count=len(artifacts),
            artifacts=artifacts,
            withheld_count=len(withheld),
            gap_count=len(gaps),
            # Placeholder: replaced below, and excluded from its own input.
            bundle_sha256="",
        ),
    )

    # THE SEAL. Serialize the bundle exactly as it will be served, delete the
    # one field the hash cannot cover (itself), canonicalize, hash. A reader
    # runs the identical three steps on the file they downloaded.
    serialized = bundle.model_dump(mode="json")
    del serialized["manifest"]["bundle_sha256"]
    bundle.manifest.bundle_sha256 = _sha256_json(serialized)

    # Audited: who took evidence out of the building, for which certification,
    # and what this copy did not contain. Ids and classifications only — the
    # record of a refusal must never become a copy of the thing refused.
    with db.transaction():
        write_event(
            db,
            actor=identity.username,
            action="evidence_bundle_generated",
            subject_kind="cert.certifications",
            subject_id=record.certification_id,
            detail={
                "generated_for_role": identity.role,
                **identity.audit_actor_detail(),
                "figure_count": len(figures),
                "raw_record_count": len(raw_record_evidence),
                "raw_record_leaf_count": len(leaf_ids),
                "withheld_count": len(withheld),
                "withheld_record_ids": [w.id for w in withheld],
                "withheld_classifications": sorted(
                    {w.classification for w in withheld}
                ),
                "gap_count": len(gaps),
                "gap_kinds": sorted({g.kind for g in gaps}),
                "artifact_count": len(artifacts),
                "verification_verdict": verification.verdict,
                "bundle_sha256": bundle.manifest.bundle_sha256,
            },
        )
    return bundle
