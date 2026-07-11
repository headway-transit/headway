"""Agency branding surface (handoff 0008, pillar C).

Three endpoints:

- ``POST /branding/logo`` — certifying official only, multipart. The logo is
  whitelisted to SVG/PNG, capped at 512 KiB, stored via the ObjectStore seam
  (the ingest.py precedent — MinIO in production, a fake in tests) at the
  fixed key ``branding/logo``, its content type recorded in the app.settings
  key ``brand_logo_meta`` (migration 0015), and the change audited in the
  same transaction as the settings row.
- ``GET /branding/logo`` — UNAUTHENTICATED (the app shell and public pages
  need it before sign-in), per-IP rate limited with the same token bucket as
  the public open-data endpoint, served with the recorded content type and
  cache headers. Plain-language 404 while no logo has been uploaded.
- ``GET /branding`` — UNAUTHENTICATED JSON {display_name, primary, accent,
  has_logo} for the app shell. Colors served here have already passed the
  contrast guardrail at write time (routers/settings.py + branding.py).

SVG NOTE: SVG can carry script, and this logo is served unauthenticated from
our origin. Only a certifying official can upload one, and the response adds
``X-Content-Type-Options: nosniff`` plus (for SVG) a Content-Security-Policy
that blocks script/external loads if the file is opened directly — the app
shell itself embeds the logo via ``<img>``, which never executes SVG script.
"""

from __future__ import annotations

from typing import Optional, Protocol

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel

from ..audit import write_event
from ..auth import Identity
from ..authz import require_certifying_official
from ..branding import LOGO_META_KEY, LOGO_META_UNSET
from ..db import get_db
from ..machine_auth import enforce_rate_limit

router = APIRouter(tags=["branding"])

# One logo per agency instance (ADR-0004: one database — and one brand — per
# agency), so the object key is fixed and each upload replaces the last.
LOGO_OBJECT_KEY = "branding/logo"

# Content-type whitelist: vector or lossless raster, nothing else.
ALLOWED_LOGO_TYPES = ("image/svg+xml", "image/png")

# 512 KiB cap (handoff 0008). Above this is a 413.
MAX_LOGO_BYTES = 512 * 1024

# Served with a short public cache: logos change rarely, but a rebrand should
# propagate within minutes without cache-busting machinery.
LOGO_CACHE_CONTROL = "public, max-age=300"

# Defaults exactly as migration 0015 seeds them — used only as fallbacks so
# GET /branding stays serviceable against a database that predates 0015.
BRANDING_DEFAULTS = {
    "agency_display_name": "Transit Agency",
    "brand_color_primary": "#1a5fb4",
    "brand_color_accent": "#0b57d0",
    LOGO_META_KEY: LOGO_META_UNSET,
}

_SELECT_SETTING_VALUE = (
    "SELECT setting_key, setting_value, value_type, description, "
    "updated_by, updated_at FROM app.settings WHERE setting_key = %s"
)

_UPDATE_SETTING = (
    "UPDATE app.settings SET setting_value = %s, updated_by = %s, "
    "updated_at = now() WHERE setting_key = %s RETURNING updated_at"
)


class LogoStore(Protocol):
    """The two object-store operations branding needs. Satisfied by the same
    app.state.object_store the ingest router uses (ingest.MinioObjectStore in
    production, the fake in tests)."""

    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> Optional[bytes]: ...


class LogoUploadResponse(BaseModel):
    content_type: str
    bytes: int
    audit_event_id: int


class BrandingResponse(BaseModel):
    """What the app shell needs to brand itself. Colors here have already
    passed the WCAG AA contrast guardrail at write time."""

    display_name: str
    primary: str
    accent: str
    has_logo: bool


def _setting_value(db, key: str) -> str:
    row = db.execute(_SELECT_SETTING_VALUE, (key,)).fetchone()
    return row[1] if row is not None else BRANDING_DEFAULTS[key]


def _no_logo_404() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail=(
            "No agency logo has been uploaded to this Headway instance yet. "
            "A certifying official can upload one via POST /branding/logo."
        ),
    )


@router.post("/branding/logo", response_model=LogoUploadResponse)
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> LogoUploadResponse:
    """Upload the agency logo (certifying official only — the same role that
    owns every other branding setting). SVG or PNG, at most 512 KiB. The
    bytes go to the object store BEFORE the settings row and audit event
    commit together — the store-before-record ordering of ingest."""
    store: LogoStore | None = getattr(request.app.state, "object_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Logo storage is not configured on this Headway instance: "
                "the object store connection is missing. Nothing was stored. "
                "Please contact your Headway administrator."
            ),
        )

    content_type = (file.content_type or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_LOGO_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"'{content_type or 'unknown'}' is not a file type Headway "
                f"accepts for the agency logo. Please upload an SVG "
                f"(image/svg+xml) or PNG (image/png) file."
            ),
        )

    # Read at most one byte past the cap — enough to detect oversize without
    # buffering an arbitrarily large body.
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "This file is larger than the 512 KiB logo limit. Please "
                "export a smaller version (an SVG, or a PNG sized for the "
                "app header) and upload that instead."
            ),
        )
    if not data:
        raise HTTPException(
            status_code=422,
            detail=(
                "The uploaded logo file is empty. Please choose the SVG or "
                "PNG file and try again."
            ),
        )

    # Store BEFORE the settings/audit transaction: brand_logo_meta must never
    # point at bytes that do not exist. The key is fixed, so a retry after a
    # mid-flight failure simply overwrites.
    store.put(LOGO_OBJECT_KEY, data, content_type)

    with db.transaction():
        updated = db.execute(
            _UPDATE_SETTING, (content_type, identity.username, LOGO_META_KEY)
        ).fetchone()
        if updated is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "This Headway instance is missing its branding settings "
                    "(database migration 0015 has not been applied), so the "
                    "logo upload was not recorded. Please contact your "
                    "Headway administrator."
                ),
            )
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="branding_logo_uploaded",
            subject_kind="app.settings",
            subject_id=LOGO_META_KEY,
            detail={
                "content_type": content_type,
                "bytes": len(data),
                "object_key": LOGO_OBJECT_KEY,
            },
        )
    return LogoUploadResponse(
        content_type=content_type, bytes=len(data), audit_event_id=audit_event_id
    )


@router.get(
    "/branding/logo",
    response_class=Response,
    responses={
        200: {
            "description": "The agency logo bytes, with its stored content type.",
            "content": {"image/svg+xml": {}, "image/png": {}},
        },
        404: {"description": "No logo has been uploaded yet."},
    },
)
def get_logo(request: Request) -> Response:
    """Serve the agency logo. UNAUTHENTICATED by design — the app shell and
    public pages show it before sign-in; the only per-caller control is the
    same per-IP token bucket as the public open-data endpoint. The logo is
    the least sensitive object in the system: a public image the agency
    chose to publish."""
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(request.app.state.public_rate_limiter, client_ip)
    db = get_db(request)

    content_type = _setting_value(db, LOGO_META_KEY)
    if content_type == LOGO_META_UNSET:
        raise _no_logo_404()

    store: LogoStore | None = getattr(request.app.state, "object_store", None)
    if store is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Logo storage is not configured on this Headway instance, so "
                "the logo cannot be served. Please contact your Headway "
                "administrator."
            ),
        )
    data = store.get(LOGO_OBJECT_KEY)
    if data is None:
        # Meta says a logo exists but the object is gone — serve the same
        # plain-language 404 rather than a broken image.
        raise _no_logo_404()

    headers = {
        "Cache-Control": LOGO_CACHE_CONTROL,
        # Never let a browser second-guess the stored type.
        "X-Content-Type-Options": "nosniff",
    }
    if content_type == "image/svg+xml":
        # Defense in depth for direct navigation: SVG script/external loads
        # are blocked; <img> embedding (the app shell) is unaffected.
        headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'unsafe-inline'"
        )
    return Response(content=data, media_type=content_type, headers=headers)


@router.get("/branding", response_model=BrandingResponse)
def get_branding(request: Request) -> BrandingResponse:
    """The branding bundle for the app shell: display name, the two brand
    colors (contrast-guaranteed at write time), and whether a logo exists.
    UNAUTHENTICATED by design, per-IP rate limited — the shell brands itself
    before sign-in, and nothing here is sensitive."""
    client_ip = request.client.host if request.client else "unknown"
    enforce_rate_limit(request.app.state.public_rate_limiter, client_ip)
    db = get_db(request)
    return BrandingResponse(
        display_name=_setting_value(db, "agency_display_name"),
        primary=_setting_value(db, "brand_color_primary"),
        accent=_setting_value(db, "brand_color_accent"),
        has_logo=_setting_value(db, LOGO_META_KEY) != LOGO_META_UNSET,
    )
