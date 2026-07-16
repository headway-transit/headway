"""Per-agency settings: the ONE audited place an agency sets calc policy.

The keys are the calc policy knobs SEEDED by migration 0014 (coverage_
threshold, gap_threshold_seconds, layover_max_seconds, missing_trip_
threshold) — settings are never client-creatable, so an unknown key is a
404, not a new row. Any signed-in role may read them; changing one is gated
to exactly the certifying official (v0 admin, the machine-keys precedent),
because these knobs move the certifiability line itself.

Every value is a STRING validated against the row's ``value_type``:
'decimal' parses via Decimal (floating point never touches a policy number —
the same rule as reported figures), 'integer' must be a whole number, 'text'
any non-empty string. A value that does not parse is a plain-language 422.
Every change is audited with the old AND new value in the audit detail.

Branding keys (migration 0015, handoff 0008) carry extra rules on top of
their 'text' type: the two brand_color_* keys must be '#rrggbb' hex AND pass
the server-side WCAG AA contrast guardrail against both app surfaces
(branding.py — a failing color is a plain-language 422 naming the failing
surface and the measured ratio), and brand_logo_meta is system-maintained
(set by POST /branding/logo, never PUT directly).

DOCUMENTED LIMITATION (handoff 0002 Response): the calc runner does NOT yet
read this table — its explicit CLI flags still govern every run. Wiring
runner-reads-settings is the follow-up increment; this surface exists now so
agencies have one audited place to set policy.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..audit import write_event
from ..auth import Identity
from ..authz import require_authenticated, require_certifying_official
from ..branding import (
    BRAND_COLOR_KEYS,
    CHROME_KEYS,
    CHROME_UNSET,
    LOGO_META_KEY,
    brand_color_problem,
    chrome_pair_problem,
    chrome_value_problem,
)
from ..db import get_db

router = APIRouter(tags=["settings"])


class Setting(BaseModel):
    setting_key: str
    # Always a string, exactly as stored — a 'decimal' setting is never a
    # JSON float, for the same reason reported figures never are.
    setting_value: str
    value_type: str
    description: str
    updated_by: str
    updated_at: dt.datetime


class UpdateSettingRequest(BaseModel):
    value: str = Field(min_length=1)


class UpdateSettingResponse(Setting):
    audit_event_id: int


_SELECT_SETTINGS = (
    "SELECT setting_key, setting_value, value_type, description, "
    "updated_by, updated_at FROM app.settings"
)

_UPDATE_SETTING = (
    "UPDATE app.settings SET setting_value = %s, updated_by = %s, "
    "updated_at = now() WHERE setting_key = %s RETURNING updated_at"
)


def _setting_from_row(r) -> Setting:
    return Setting(
        setting_key=r[0],
        setting_value=r[1],
        value_type=r[2],
        description=r[3],
        updated_by=r[4],
        updated_at=r[5],
    )


def validate_value(value: str, value_type: str, setting_key: str) -> None:
    """Refuse (plain-language 422) any value that is not a valid instance of
    the setting's declared type. The stored value stays the caller's exact
    string — validation never rewrites or normalizes it."""
    if value_type == "decimal":
        try:
            parsed = Decimal(value)
        except InvalidOperation:
            parsed = None
        if parsed is None or not parsed.is_finite():
            raise HTTPException(
                status_code=422,
                detail=(
                    f"'{value}' is not a decimal number, so it cannot be the "
                    f"value of the '{setting_key}' setting. Please send a "
                    f"plain decimal number, for example '0.95'."
                ),
            )
    elif value_type == "integer":
        try:
            int(value)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"'{value}' is not a whole number, so it cannot be the "
                    f"value of the '{setting_key}' setting. Please send a "
                    f"whole number of seconds, for example '300'."
                ),
            )
    # 'text' accepts any non-empty string (the request model enforces
    # non-empty). value_type is CHECK-constrained in the database, so no
    # other branch can exist.

    # Branding keys (migration 0015) carry EXTRA rules beyond their 'text'
    # type — the accessibility guardrail (handoff 0008: you can brand it;
    # you cannot brand it inaccessible). Every other key is unchanged.
    if setting_key == LOGO_META_KEY:
        raise HTTPException(
            status_code=422,
            detail=(
                "'brand_logo_meta' is maintained by Headway when an agency "
                "logo is uploaded and cannot be edited directly. To change "
                "the logo, upload a new one via POST /branding/logo."
            ),
        )
    if setting_key in BRAND_COLOR_KEYS:
        problem = brand_color_problem(value)
        if problem is not None:
            # Hex-format or WCAG AA contrast refusal — the message names the
            # failing surface and the measured ratio (branding.py).
            raise HTTPException(status_code=422, detail=problem)
    if setting_key in CHROME_KEYS:
        problem = chrome_value_problem(value)
        if problem is not None:
            raise HTTPException(status_code=422, detail=problem)
        # The PAIR check (chrome colors render on each other, not on the
        # app's light surfaces) needs the other chrome values — it runs in
        # update_setting, against the values that would result.


def validate_chrome_change(db, setting_key: str, value: str) -> None:
    """Branding v2 pair guardrail (handoff 0017, design point 7): compute
    the WCAG AA contrast of every chrome pair AS IT WOULD BE after this
    change and refuse (plain-language 422 naming the pair and the measured
    ratio) any pair under 4.5:1. Pairs with an 'unset' side are skipped —
    an incomplete theme never applies, so it cannot render unreadably."""
    prospective: dict[str, str] = {}
    for key in CHROME_KEYS:
        if key == setting_key:
            prospective[key] = value
            continue
        row = db.execute(
            _SELECT_SETTINGS + " WHERE setting_key = %s", (key,)
        ).fetchone()
        # A database seeded before migration 0027 has no sibling rows; an
        # absent sibling is an unset one (the theme cannot apply anyway).
        prospective[key] = row[1] if row is not None else CHROME_UNSET
    problem = chrome_pair_problem(prospective)
    if problem is not None:
        raise HTTPException(status_code=422, detail=problem)


# ---------------------------------------------------------------------------
# Service-day overrides (handoff 0020, migration 0031) — the agency's
# audited day-type calendar declarations: holiday reassignments ("2026-07-03
# runs the sunday schedule" — 2026 NTD Policy Manual p. 156, quoted in
# services/calc/REGULATORY_TRACKER.md) and atypical-day flags. Per-DATE rows
# with a required reason, not settings keys (the migration documents why a
# table beats settings rows). Same audited-surface rules as settings: any
# signed-in role reads; the certifying official writes; every change lands
# in audit.events with the old AND new declaration.
# ---------------------------------------------------------------------------

_DAY_TYPES = ("weekday", "saturday", "sunday")


class ServiceDayOverride(BaseModel):
    service_date: dt.date
    assigned_day_type: str | None
    atypical: bool
    reason: str
    updated_by: str
    updated_at: dt.datetime


class PutServiceDayOverrideRequest(BaseModel):
    # None = keep the date's day-of-week schedule type (flag-only override).
    assigned_day_type: str | None = None
    atypical: bool = False
    reason: str = Field(min_length=1)


class PutServiceDayOverrideResponse(ServiceDayOverride):
    audit_event_id: int


class DeleteServiceDayOverrideResponse(BaseModel):
    service_date: dt.date
    removed: bool
    audit_event_id: int


_SELECT_SERVICE_DAYS = (
    "SELECT service_date, assigned_day_type, atypical, reason, updated_by, "
    "updated_at FROM app.service_day_overrides"
)

_UPSERT_SERVICE_DAY = (
    "INSERT INTO app.service_day_overrides "
    "(service_date, assigned_day_type, atypical, reason, updated_by) "
    "VALUES (%s, %s, %s, %s, %s) "
    "ON CONFLICT (service_date) DO UPDATE SET "
    "assigned_day_type = EXCLUDED.assigned_day_type, "
    "atypical = EXCLUDED.atypical, reason = EXCLUDED.reason, "
    "updated_by = EXCLUDED.updated_by, updated_at = now() "
    "RETURNING updated_at"
)

_DELETE_SERVICE_DAY = (
    "DELETE FROM app.service_day_overrides WHERE service_date = %s "
    "RETURNING service_date"
)


def _override_from_row(r) -> ServiceDayOverride:
    return ServiceDayOverride(
        service_date=r[0],
        assigned_day_type=r[1],
        atypical=r[2],
        reason=r[3],
        updated_by=r[4],
        updated_at=r[5],
    )


def _validate_override_body(body: PutServiceDayOverrideRequest) -> None:
    if body.assigned_day_type is not None and body.assigned_day_type not in _DAY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{body.assigned_day_type}' is not a schedule day type "
                f"Headway knows. A service day can be reassigned to "
                f"'weekday', 'saturday' or 'sunday' — the three schedule "
                f"types the NTD's Days Operated section names — or left "
                f"null to keep its day-of-week type."
            ),
        )
    if body.assigned_day_type is None and not body.atypical:
        raise HTTPException(
            status_code=422,
            detail=(
                "This override neither reassigns the day's schedule type "
                "nor flags it atypical, so it declares nothing. Set "
                "assigned_day_type (e.g. 'sunday' for a holiday that runs "
                "the Sunday schedule), set atypical to true, or delete the "
                "override instead."
            ),
        )
    if not body.reason.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "Please give a reason for this service-day declaration — "
                "for example 'Independence Day observed: Sunday schedule'. "
                "Every calendar change must be explainable."
            ),
        )


@router.get(
    "/settings/service-days", response_model=list[ServiceDayOverride]
)
def list_service_day_overrides(
    from_date: dt.date | None = None,
    to_date: dt.date | None = None,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[ServiceDayOverride]:
    """Every declared service-day override (optionally bounded to
    [from_date, to_date), half-open — the calc period convention), with its
    reason and audit attribution. Any signed-in role may read — the
    calendar policy must be visible to the people it governs."""
    sql = _SELECT_SERVICE_DAYS
    params: tuple = ()
    if from_date is not None and to_date is not None:
        sql += " WHERE service_date >= %s AND service_date < %s"
        params = (from_date, to_date)
    elif from_date is not None or to_date is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Give both from_date and to_date (a half-open range "
                "[from_date, to_date)) or neither."
            ),
        )
    rows = db.execute(sql + " ORDER BY service_date", params).fetchall()
    return [_override_from_row(r) for r in rows]


@router.put(
    "/settings/service-days/{service_date}",
    response_model=PutServiceDayOverrideResponse,
)
def put_service_day_override(
    service_date: dt.date,
    body: PutServiceDayOverrideRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> PutServiceDayOverrideResponse:
    """Declare (or replace) one service day's override — a holiday
    schedule reassignment and/or an atypical-day flag, with a required
    reason (certifying official only). The old and new declarations land
    together in the audit trail; figures already computed under the old
    declaration are untouched (each carries its governing declaration in
    its own detail)."""
    _validate_override_body(body)
    existing_row = db.execute(
        _SELECT_SERVICE_DAYS + " WHERE service_date = %s", (service_date,)
    ).fetchone()
    old = None if existing_row is None else _override_from_row(existing_row)

    with db.transaction():
        updated = db.execute(
            _UPSERT_SERVICE_DAY,
            (
                service_date,
                body.assigned_day_type,
                body.atypical,
                body.reason,
                identity.username,
            ),
        ).fetchone()
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="service_day_override_set",
            subject_kind="app.service_day_overrides",
            subject_id=service_date.isoformat(),
            detail={
                "old": (
                    None
                    if old is None
                    else {
                        "assigned_day_type": old.assigned_day_type,
                        "atypical": old.atypical,
                        "reason": old.reason,
                    }
                ),
                "new": {
                    "assigned_day_type": body.assigned_day_type,
                    "atypical": body.atypical,
                    "reason": body.reason,
                },
            },
        )
    return PutServiceDayOverrideResponse(
        service_date=service_date,
        assigned_day_type=body.assigned_day_type,
        atypical=body.atypical,
        reason=body.reason,
        updated_by=identity.username,
        updated_at=updated[0],
        audit_event_id=audit_event_id,
    )


@router.delete(
    "/settings/service-days/{service_date}",
    response_model=DeleteServiceDayOverrideResponse,
)
def delete_service_day_override(
    service_date: dt.date,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> DeleteServiceDayOverrideResponse:
    """Remove one service day's override (certifying official only): the
    date returns to its day-of-week schedule type, typical. Removing a
    declaration is a policy change too — the removed declaration lands in
    the audit trail, and figures computed under it keep their snapshot."""
    existing_row = db.execute(
        _SELECT_SERVICE_DAYS + " WHERE service_date = %s", (service_date,)
    ).fetchone()
    if existing_row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No service-day override is declared for "
                f"{service_date.isoformat()}, so there is nothing to "
                f"remove — the date already classifies by its day of week."
            ),
        )
    old = _override_from_row(existing_row)
    with db.transaction():
        db.execute(_DELETE_SERVICE_DAY, (service_date,)).fetchone()
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="service_day_override_removed",
            subject_kind="app.service_day_overrides",
            subject_id=service_date.isoformat(),
            detail={
                "old": {
                    "assigned_day_type": old.assigned_day_type,
                    "atypical": old.atypical,
                    "reason": old.reason,
                },
                "new": None,
            },
        )
    return DeleteServiceDayOverrideResponse(
        service_date=service_date,
        removed=True,
        audit_event_id=audit_event_id,
    )


@router.get("/settings", response_model=list[Setting])
def list_settings(
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[Setting]:
    """Every agency policy setting, with its plain-language description and
    who last changed it. Any signed-in role may read — policy must be
    visible to the people it governs."""
    rows = db.execute(_SELECT_SETTINGS + " ORDER BY setting_key").fetchall()
    return [_setting_from_row(r) for r in rows]


@router.put("/settings/{setting_key}", response_model=UpdateSettingResponse)
def update_setting(
    setting_key: str,
    body: UpdateSettingRequest,
    identity: Identity = Depends(require_certifying_official),
    db=Depends(get_db),
) -> UpdateSettingResponse:
    """Change one policy setting (certifying official only). The old and new
    values land together in the audit trail; the change and its audit event
    commit in one transaction."""
    row = db.execute(
        _SELECT_SETTINGS + " WHERE setting_key = %s", (setting_key,)
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{setting_key}' is not a setting Headway knows. Settings "
                f"are pre-defined policy knobs and cannot be created through "
                f"the API — GET /settings lists the ones that exist."
            ),
        )
    current = _setting_from_row(row)
    validate_value(body.value, current.value_type, setting_key)
    if setting_key in CHROME_KEYS:
        # The pairwise chrome guardrail needs the sibling values (branding
        # v2, handoff 0017): checked against the values that would result.
        validate_chrome_change(db, setting_key, body.value)

    with db.transaction():
        updated = db.execute(
            _UPDATE_SETTING, (body.value, identity.username, setting_key)
        ).fetchone()
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="setting_updated",
            subject_kind="app.settings",
            subject_id=setting_key,
            detail={
                "old_value": current.setting_value,
                "new_value": body.value,
                "value_type": current.value_type,
            },
        )
    return UpdateSettingResponse(
        setting_key=setting_key,
        setting_value=body.value,
        value_type=current.value_type,
        description=current.description,
        updated_by=identity.username,
        updated_at=updated[0],
        audit_event_id=audit_event_id,
    )
