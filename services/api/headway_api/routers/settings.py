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
