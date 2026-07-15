"""MR-20 preview report: the calc library's package, served VERBATIM.

GET /reports/mr20?month=YYYY-MM assembles nothing itself — it imports
``headway_calc.mr20`` (handoff 0009) and returns exactly the package that
``build_mr20_package`` produced, serialized once with ``json.dumps`` and sent
as raw bytes. No reshaping, no re-keying, no response model: the NOT-
REPORTABLE banner, the programmatically enumerated caveats, and every
per-cell provenance field reach the web client exactly as the calc library
wrote them (this API never originates or edits a figure).

Any signed-in role may read it — the package is a preview with its own
governing caveats, not a certification surface.

DEPLOYMENT ASSUMPTION: ``headway_calc`` must be importable in the API's
environment (the shared venv installs services/calc; the api Docker image
must install services/calc too — Dockerfile follow-up, see README).
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from headway_calc import mr20, ss50

from .. import exports
from ..auth import Identity
from ..authz import require_authenticated
from ..db import get_db
from .certify import _signer_identity_from_document

router = APIRouter(tags=["reports"])

#: Certifications whose covered figures fall inside one half-open month
#: period AND still stand certified (handoff 0019, design point 7 — the
#: certificate block on the MR-20/S&S-50 "Read first" sheets).
_SELECT_PERIOD_CERTIFICATIONS = (
    "SELECT DISTINCT c.certification_id, c.certified_by, c.certified_at, "
    "c.key_fingerprint, c.canonical_document "
    "FROM cert.certifications AS c "
    "JOIN computed.metric_values AS v "
    "ON v.metric_value_id = ANY(c.metric_value_ids) "
    "WHERE v.period_start >= %s AND v.period_end <= %s "
    "AND v.certification_status = 'certified' "
    "ORDER BY c.certified_at, c.certification_id"
)


def _certificate_lines(db, month: str) -> list[str]:
    """The certificate block for one month's export banner (empty when the
    period holds no certified figures — a line is never invented). Signed
    certifications name the typed signer, timestamp and key fingerprint;
    pre-signature (legacy) certifications say so honestly."""
    period_start, period_end = mr20.month_period(month)
    rows = db.execute(
        _SELECT_PERIOD_CERTIFICATIONS, (period_start, period_end)
    ).fetchall()
    if not rows:
        return []
    lines = [
        "Certificate: figures in this period are covered by the "
        "certification(s) below. Verify any of them (tamper-evidence) at "
        "GET /public/certifications/{certification_id}/verify."
    ]
    for row in rows:
        certification_id, certified_by, certified_at = (
            str(row[0]), row[1], row[2],
        )
        key_fingerprint, canonical_document = row[3], row[4]
        if key_fingerprint is None:
            lines.append(
                f"Certification {certification_id}: certified by "
                f"{certified_by} on {certified_at.isoformat()} — recorded "
                f"before digital signatures existed (no fingerprint; "
                f"honest history, never backfilled)."
            )
            continue
        name, title = _signer_identity_from_document(canonical_document)
        signer = (
            f"{name}, {title}" if name and title else certified_by
        )
        lines.append(
            f"Certification {certification_id}: signed by {signer} on "
            f"{certified_at.isoformat()} — Ed25519 signature, key "
            f"fingerprint {key_fingerprint}."
        )
    return lines


def _month_or_422(month: str) -> None:
    """The calc library owns the month convention; we only translate its
    refusal into a plain-language 422."""
    try:
        mr20.month_period(month)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{month}' is not a month Headway understands. Please use "
                f"the form YYYY-MM — for example 2026-07 for July 2026 — "
                f"with a month number from 01 to 12."
            ),
        )


@router.get(
    "/reports/mr20",
    responses={
        200: {
            "content": {"application/json": {}},
            "description": (
                "The headway_calc.mr20 package for the month, verbatim: "
                "form/generator/period header, reportable=false + banner, "
                "programmatically enumerated caveats, and the four MR-20 "
                "data points per mode plus fleet totals, each cell carrying "
                "full provenance or an explicit null + reason."
            ),
        }
    },
)
def get_mr20_report(
    month: str = Query(
        ...,
        description="Calendar month as YYYY-MM (e.g. 2026-07), UTC, half-open period.",
    ),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> Response:
    """Serve the MR-20 preview package (NOT reportable) for one month."""
    _month_or_422(month)
    package = mr20.build_mr20_package(db, month)
    # Serialized here, once, and sent as-is: byte-identical to the package.
    return Response(
        content=json.dumps(package), media_type="application/json"
    )


@router.get(
    "/reports/mr20/export",
    response_class=Response,
    responses={
        200: {
            "description": (
                "The MR-20 preview package as a CSV or XLSX download: one "
                "row per (scope, metric) cell, values VERBATIM from the "
                "package; the NOT-REPORTABLE banner and every enumerated "
                "caveat lead the CSV and form the XLSX's first sheet."
            ),
            "content": {exports.CSV_MEDIA_TYPE: {}, exports.XLSX_MEDIA_TYPE: {}},
        }
    },
)
def export_mr20_report(
    month: str = Query(..., description="Calendar month as YYYY-MM."),
    format: str = Query(default="xlsx", pattern=exports.FORMAT_PATTERN),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> Response:
    """Download the MR-20 preview package as CSV/XLSX (handoff 0017, design
    point 5). Same package build as GET /reports/mr20; one row assembly
    feeds both formats (XLSX values byte-equal to CSV values, pinned by
    test); XLSX cells are TEXT so figures survive exactly."""
    _month_or_422(month)
    package = mr20.build_mr20_package(db, month)
    grid = exports.mr20_grid(
        package, certificate_lines=_certificate_lines(db, month)
    )
    return exports.export_response(
        grid, format, f"headway-mr20-{month}-preview"
    )


@router.get(
    "/reports/ss50/export",
    response_class=Response,
    responses={
        200: {
            "description": (
                "The S&S-50 non-major monthly summary package as a CSV or "
                "XLSX download: one row per (mode, type-of-service) cell "
                "including explicit zero rows; the NOT-REPORTABLE banner, "
                "citations, caveats and the excluded-event accounting lead "
                "the CSV and form the XLSX's first sheet."
            ),
            "content": {exports.CSV_MEDIA_TYPE: {}, exports.XLSX_MEDIA_TYPE: {}},
        }
    },
)
def export_ss50_report(
    month: str = Query(..., description="Calendar month as YYYY-MM."),
    format: str = Query(default="xlsx", pattern=exports.FORMAT_PATTERN),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> Response:
    """Download the S&S-50 preview package (headway_calc.ss50, served
    verbatim into a grid) as CSV/XLSX — handoff 0017, design point 5."""
    _month_or_422(month)
    package = ss50.build_ss50_package(db, month)
    grid = exports.ss50_grid(
        package, certificate_lines=_certificate_lines(db, month)
    )
    return exports.export_response(
        grid, format, f"headway-ss50-{month}-preview"
    )
