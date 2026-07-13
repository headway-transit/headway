"""NTD sampling plan workflow (handoff 0012).

- GET  /sampling/options — the plan wizard's vocabulary (modes, units per
  mode, efficiency options, frequencies) plus the §41.01/§41.03 eligibility
  guidance and the documentation-retention note.
- GET  /sampling/requirements — look up one ready-to-use table cell
  (required per-period + annual sample size, verbatim, with its citation)
  without creating anything.
- POST /sampling/plans — create a plan (data steward or above, audited).
  Required sizes come from the deterministic calc selector
  (headway_calc.sampling, sampling_v0) — this API never encodes a
  regulatory number.
- POST /sampling/plans/{id}/draws — one random-selection act per period at
  the plan's frequency: the caller provides that period's full expected
  service-unit list (§63.07); the seeded calc drawer selects WITHOUT
  replacement (§63.03); the seed, frame, and selection are all recorded.
  Audited.
- POST /sampling/plans/{id}/measurements (+ /sampling/measurements/{id}/
  supersede) — manual ride-check entry per selected unit (observed UPT and
  PMT). Append-only: corrections supersede, originals never change
  (migration 0020 enforces this with triggers). Audited.
- GET  /sampling/plans/{id}/progress — measured vs required, per draw and
  overall, with the unmeasured-unit worksheet.
- POST /sampling/plans/{id}/estimate — the §83 APTL estimate (report
  preparer or above, audited): sample APTL = sample total PMT ÷ sample
  total UPT (ratio of totals — the §83.05(b)-banned average-of-ratios is
  unconstructible in the calc API), estimated PMT = 100% UPT expansion
  factor × sample APTL. REFUSES undersampled plans (the technique must be
  followed exactly), Base-option plans (Section 70 estimation deferred),
  and never persists to computed.metric_values: the result is a SAMPLED
  ESTIMATE with its provenance label, not a computed figure.

Every regulatory sentence above is a pointer to
services/calc/REGULATORY_TRACKER.md, "Verified — NTD Sampling Manual" and
"Sampling plan tables — implementation quotes (sampling_v0)" — never a
number from memory.
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from headway_calc import sampling as sampling_calc

from ..audit import write_event
from ..auth import Identity
from ..authz import require_at_least, require_authenticated
from ..db import get_db

router = APIRouter(tags=["sampling"])

#: v0 creates APTL-without-grouping and Base plans. The grouped-APTL cells
#: exist in the selector for citation completeness, but grouped plans need
#: per-group sampling AND estimation (§43.05(a), §83.05(c)) — deferred.
CREATABLE_OPTIONS = ("aptl", "base")

_UNDERSAMPLING_CITATION = (
    "An estimate from fewer units than the plan requires does not follow "
    "the FTA-approved technique: 'If a transit agency samples, they must "
    "follow the sampling technique exactly.' and the estimate must meet "
    "'Minimum confidence of 95 percent; and Minimum precision level of "
    "±10 percent' (2026 NTD Policy Manual, Full Reporting, p. 149 — "
    "verified 2026-07-12, REGULATORY_TRACKER.md, 'Verified — Passenger "
    "Miles Traveled')."
)

_OVERSAMPLING_CITATION = (
    "Sampling more units than required is allowed only when the extra "
    "units are selected randomly (2026 NTD Policy Manual, Full Reporting, "
    "p. 149 — verified 2026-07-12). Headway's drawer extends the same "
    "seeded random order, so oversampled units are random by construction "
    "and are flagged on the draw record."
)

_MANUAL_ENTRY_CAVEAT = (
    "Sample observations are MANUALLY ENTERED ride-check data: Headway "
    "records who entered each observation and when, but cannot verify the "
    "on-board counts themselves. Corrections supersede — originals are "
    "never edited."
)

_EXPANSION_FACTOR_CAVEAT = (
    "The 100% UPT expansion factor is supplied by the caller and must be "
    "the agency's actual 100% count of UPT (§83.01(a): 'You must use your "
    "100% count of UPT as the expansion factor.'). Headway does not verify "
    "it against computed UPT figures in v0 — cross-check it against your "
    "certified UPT before using this estimate in a submission."
)

_NOT_COMPUTED_PMT = (
    "This figure is a SAMPLED ESTIMATE produced by the §83 APTL method. It "
    "is not, and is never stored as, a computed PMT measurement "
    "(computed.metric_values is untouched by this endpoint)."
)

#: Seed provenance (hardening pass 2026-07-13, migration 0022): a draw's
#: seed may be client-supplied, and the federal-evidence record must say so
#: — the drawer's DRAW_METHOD text conditions its §63.03(b)(1) randomness
#: claim on a cryptographically random seed, a premise Headway can only
#: vouch for when Headway generated the seed itself.
SEED_SOURCE_GENERATED = "generated"
SEED_SOURCE_CLIENT = "client"

_SEED_PROVENANCE_NOTES = {
    SEED_SOURCE_GENERATED: (
        "Seed provenance: seed_source='generated' — Headway generated this "
        "draw's seed from a cryptographic randomness source "
        "(secrets.token_hex) and recorded it on the draw, so the seeded "
        "ordering above is random (§63.03(b)(1)) as well as reproducible."
    ),
    SEED_SOURCE_CLIENT: (
        "Seed provenance: seed_source='client' — this draw's seed was "
        "SUPPLIED BY THE CALLER and recorded on the draw. The selection is "
        "reproducible from the recorded seed, but Headway cannot vouch that "
        "a caller-supplied seed came from a random source: the §63.03(b)(1) "
        "randomness of this draw rests on how the caller produced the seed. "
        "Keep the caller's seed-generation evidence with the plan's "
        "sampling documentation."
    ),
}


def _too_long(field_plain: str, limit: int, actual: int) -> ValueError:
    """One plain-language shape for every over-length refusal (hardening
    pass 2026-07-13: request fields bound for TEXT columns get sane caps)."""
    return ValueError(
        f"{field_plain} is {actual:,} characters long, and Headway accepts "
        f"at most {limit:,} here. Please shorten it."
    )


# --- SQL ---------------------------------------------------------------------

_INSERT_PLAN = (
    "INSERT INTO sampling.plans "
    "(report_year, mode, type_of_service, unit, efficiency_option, "
    "frequency, required_per_period, required_annual, table_citation, "
    "selector_version, created_by) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "RETURNING plan_id, status, created_at"
)

_PLAN_COLUMNS = (
    "plan_id, report_year, mode, type_of_service, unit, efficiency_option, "
    "frequency, required_per_period, required_annual, table_citation, "
    "selector_version, status, created_by, created_at"
)

_SELECT_PLANS = f"SELECT {_PLAN_COLUMNS} FROM sampling.plans"

_SELECT_PLAN_BY_ID = (
    f"SELECT {_PLAN_COLUMNS} FROM sampling.plans WHERE plan_id = %s"
)

#: The one lifecycle UPDATE migration 0020's trigger permits.
_ACTIVATE_PLAN = (
    "UPDATE sampling.plans SET status = 'active' "
    "WHERE plan_id = %s AND status = 'created' RETURNING plan_id"
)

_INSERT_DRAW = (
    "INSERT INTO sampling.draws "
    "(plan_id, period_label, service_units, selected_units, seed, "
    "seed_source, oversample_units, drawer_version, drawn_by) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "RETURNING draw_id, drawn_at"
)

_SELECT_DRAWS = (
    "SELECT draw_id, plan_id, period_label, service_units, selected_units, "
    "seed, seed_source, oversample_units, drawer_version, drawn_by, "
    "drawn_at "
    "FROM sampling.draws WHERE plan_id = %s ORDER BY drawn_at, draw_id"
)

_INSERT_MEASUREMENT = (
    "INSERT INTO sampling.measurements "
    "(plan_id, unit_id, observed_upt, observed_pmt, service_day_type, "
    "service_date, data_source, notes, entered_by) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "RETURNING measurement_id, entered_at"
)

_MEASUREMENT_COLUMNS = (
    "measurement_id, plan_id, unit_id, observed_upt, observed_pmt, "
    "service_day_type, service_date, data_source, notes, entered_by, "
    "entered_at, superseded_by"
)

_SELECT_MEASUREMENTS_FOR_PLAN = (
    f"SELECT {_MEASUREMENT_COLUMNS} FROM sampling.measurements "
    "WHERE plan_id = %s ORDER BY entered_at, measurement_id"
)

_SELECT_MEASUREMENT_BY_ID = (
    f"SELECT {_MEASUREMENT_COLUMNS} FROM sampling.measurements "
    "WHERE measurement_id = %s"
)

#: The one UPDATE migration 0020's measurement trigger permits: linking the
#: original to its replacement, exactly once. Runs BEFORE the replacement
#: insert (the superseded_by FK is DEFERRABLE, validated at commit) so the
#: one-active-per-unit unique index never sees two active rows for the same
#: (plan, unit) — found by the 2026-07-12 live walkthrough.
_LINK_MEASUREMENT_SUPERSEDED = (
    "UPDATE sampling.measurements SET superseded_by = %s "
    "WHERE measurement_id = %s AND superseded_by IS NULL "
    "RETURNING measurement_id"
)

#: Replacement insert with an API-generated id (the link above must point
#: at this id before the row exists — see _LINK_MEASUREMENT_SUPERSEDED).
_INSERT_MEASUREMENT_REPLACEMENT = (
    "INSERT INTO sampling.measurements "
    "(measurement_id, plan_id, unit_id, observed_upt, observed_pmt, "
    "service_day_type, service_date, data_source, notes, entered_by) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "RETURNING measurement_id, entered_at"
)


# --- models ------------------------------------------------------------------


class PlanCreate(BaseModel):
    report_year: int = Field(
        ge=2000,
        le=2100,
        description="The NTD report year this plan samples for.",
    )
    mode: str = Field(
        description=(
            "NTD mode code the ready-to-use plans cover: DR (demand "
            "response), VP (commuter vanpool), MB/TB (bus), CR (commuter "
            "rail), LR/HR/MR/AG (other rail)."
        )
    )
    type_of_service: str = Field(
        min_length=1,
        description=(
            "Type of service this plan samples (e.g. DO for directly "
            "operated, PT for purchased transportation). Sampling meets "
            "the FTA floor per mode AND type of service."
        ),
    )
    unit: str = Field(
        description=(
            "Unit of sampling and measurement (Table 41.01): vehicle_days, "
            "one_way_trips, round_trips, one_way_car_trips, or "
            "one_way_train_trips — must match the mode."
        )
    )
    efficiency_option: str = Field(
        description=(
            "'aptl' (report a 100% UPT count, sample average passenger "
            "trip length; for bus this is the Without Route Grouping "
            "column) or 'base' (sample both UPT and PMT; note that "
            "Base-option ESTIMATION is not yet available — Section 70)."
        )
    )
    frequency: str = Field(
        description="Sampling frequency: quarterly, monthly, or weekly."
    )

    @field_validator("type_of_service")
    @classmethod
    def _tos_bounded(cls, v: str) -> str:
        # The only PlanCreate free-text field: mode/unit/option/frequency
        # are validated against the calc selector's closed vocabulary.
        if len(v) > 50:
            raise _too_long("The type of service", 50, len(v))
        return v


class PlanRecord(BaseModel):
    plan_id: str
    report_year: int
    mode: str
    type_of_service: str
    unit: str
    efficiency_option: str
    frequency: str
    required_per_period: int
    required_annual: int
    table_citation: str
    selector_version: str
    status: str
    created_by: str
    created_at: dt.datetime


class PlanCreated(BaseModel):
    plan: PlanRecord
    guidance: list[str]
    retention_note: str
    audit_event_id: int


class DrawRequest(BaseModel):
    period_label: str = Field(
        min_length=1,
        description=(
            "Which period this draw covers at the plan's frequency (for "
            "example 2026-Q1, 2026-01, or 2026-W14). One draw per period."
        ),
    )
    service_units: list[str] = Field(
        min_length=1,
        description=(
            "ALL service units you expect to operate in this period, in "
            "the plan's unit of sampling (§63.07) — for scheduled service "
            "including trippers, shuttles, and other special operations. "
            "Use period-qualified ids (for example 2026-01-15/trip-5012) "
            "so a unit id never repeats across periods."
        ),
    )
    seed: Optional[str] = Field(
        default=None,
        min_length=8,
        description=(
            "Random seed for the draw. Leave blank to let Headway generate "
            "one from a cryptographic randomness source. Either way the "
            "seed is RECORDED on the draw so the selection can be "
            "reproduced and audited — along with seed_source ('generated' "
            "or 'client'), because Headway can only vouch for the "
            "randomness of a seed it generated itself."
        ),
    )

    @field_validator("period_label")
    @classmethod
    def _period_label_bounded(cls, v: str) -> str:
        if len(v) > 100:
            raise _too_long("The period label", 100, len(v))
        return v

    @field_validator("seed")
    @classmethod
    def _seed_bounded(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 200:
            raise _too_long("The seed", 200, len(v))
        return v

    @field_validator("service_units")
    @classmethod
    def _unit_ids_bounded(cls, v: list[str]) -> list[str]:
        for unit in v:
            if len(unit) > 500:
                raise _too_long(
                    f"Service unit id '{unit[:40]}…'", 500, len(unit)
                )
        return v
    oversample_units: int = Field(
        default=0,
        ge=0,
        description=(
            "Extra units to select BEYOND the plan's required per-period "
            "size. Oversampling is allowed only when the extra units are "
            "selected randomly — Headway draws them from the same seeded "
            "random order, and flags them on the draw record."
        ),
    )


class DrawRecord(BaseModel):
    draw_id: str
    plan_id: str
    period_label: str
    frame_size: int
    selected_units: list[str]
    seed: str
    #: 'generated' (Headway's CSPRNG) or 'client' (caller-supplied seed) —
    #: migration 0022. None only on draws recorded before seed provenance
    #: was captured (pre-0022 rows are append-only and cannot be backfilled
    #: honestly).
    seed_source: Optional[str]
    required_per_period: int
    oversample_units: int
    drawer_version: str
    drawn_by: str
    drawn_at: dt.datetime


class DrawCreated(BaseModel):
    draw: DrawRecord
    method: str
    oversampling_note: Optional[str]
    retention_note: str
    audit_event_id: int


class MeasurementCreate(BaseModel):
    unit_id: str = Field(
        min_length=1,
        description="The drawn service unit this ride check observed.",
    )
    observed_upt: int = Field(
        ge=0,
        description=(
            "Unlinked passenger trips (boardings) counted on this unit by "
            "the ride checker."
        ),
    )
    observed_pmt: str = Field(
        description=(
            "Passenger miles traveled measured on this unit, as a decimal "
            "string (values are exact decimals, never floats)."
        ),
    )
    service_day_type: Optional[str] = Field(
        default=None,
        description=(
            "Weekday, Saturday, or Sunday — required later only if you "
            "want estimates broken out by type of service day."
        ),
    )
    service_date: Optional[dt.date] = Field(
        default=None,
        description="The date the ride check was performed.",
    )
    notes: Optional[str] = None

    @field_validator("unit_id")
    @classmethod
    def _unit_id_bounded(cls, v: str) -> str:
        if len(v) > 500:
            raise _too_long("The service unit id", 500, len(v))
        return v

    @field_validator("notes")
    @classmethod
    def _notes_bounded(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 10_000:
            raise _too_long("The notes field", 10_000, len(v))
        return v

    @field_validator("observed_pmt")
    @classmethod
    def _pmt_is_a_nonnegative_decimal(cls, v: str) -> str:
        if len(v) > 50:
            raise _too_long(
                "The passenger-miles value", 50, len(v)
            )
        try:
            value = Decimal(v)
        except InvalidOperation:
            raise ValueError(
                f"'{v}' is not a number Headway understands. Please enter "
                f"passenger miles as a plain decimal, for example 41.7."
            )
        if value < 0:
            raise ValueError(
                "Passenger miles must be zero or more. Enter 0 for a unit "
                "that carried no passengers."
            )
        return v

    @field_validator("service_day_type")
    @classmethod
    def _day_type_from_vocabulary(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in sampling_calc.SERVICE_DAY_TYPES:
            raise ValueError(
                f"'{v}' is not a service-day type Headway knows. Please "
                f"pick one of: "
                f"{', '.join(sampling_calc.SERVICE_DAY_TYPES)}."
            )
        return v


class MeasurementRecord(BaseModel):
    measurement_id: str
    plan_id: str
    unit_id: str
    observed_upt: int
    # Exact NUMERIC as a JSON string, never a float (repo non-negotiable).
    observed_pmt: str
    service_day_type: Optional[str]
    service_date: Optional[dt.date]
    data_source: str
    notes: Optional[str]
    entered_by: str
    entered_at: dt.datetime
    superseded_by: Optional[str]


class MeasurementCreated(BaseModel):
    measurement: MeasurementRecord
    source_caveat: str
    retention_note: str
    audit_event_id: int


class MeasurementSupersedeRequest(MeasurementCreate):
    reason: str = Field(
        min_length=1,
        description=(
            "Why the original observation is being corrected (kept in the "
            "audit log — the original measurement itself is never edited)."
        ),
    )

    @field_validator("reason")
    @classmethod
    def _reason_bounded(cls, v: str) -> str:
        if len(v) > 5_000:
            raise _too_long("The correction reason", 5_000, len(v))
        return v


class MeasurementSuperseded(BaseModel):
    original_measurement_id: str
    replacement: MeasurementRecord
    source_caveat: str
    audit_event_id: int


class DrawProgress(BaseModel):
    period_label: str
    selected: int
    measured: int
    oversample_units: int


class PlanProgress(BaseModel):
    plan: PlanRecord
    required_per_period: int
    required_annual: int
    draws: list[DrawProgress]
    units_selected: int
    units_measured: int
    units_unmeasured: list[str]
    undersampled: bool
    undersampling_citation: str
    oversampling_citation: str
    retention_note: str


class EstimateRequest(BaseModel):
    annual_upt_100pct: str = Field(
        description=(
            "Your agency's 100% count of annual UPT for this mode and type "
            "of service — the §83.01(a) expansion factor, as a decimal "
            "string."
        )
    )
    upt_100pct_by_day_type: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "Optional: 100% UPT counts by type of service day (Weekday / "
            "Saturday / Sunday) to also get per-day-type estimates "
            "(§83.01(b)). Every measurement must then carry its "
            "service-day type."
        ),
    )

    @field_validator("annual_upt_100pct")
    @classmethod
    def _upt_is_a_decimal(cls, v: str) -> str:
        if len(v) > 50:
            raise _too_long("The 100% UPT count", 50, len(v))
        try:
            Decimal(v)
        except InvalidOperation:
            raise ValueError(
                f"'{v}' is not a number Headway understands. Please enter "
                f"the 100% UPT count as a plain number, for example 250000."
            )
        return v

    @field_validator("upt_100pct_by_day_type")
    @classmethod
    def _by_day_values_bounded(
        cls, v: Optional[dict[str, str]]
    ) -> Optional[dict[str, str]]:
        if v is not None:
            for day, count in v.items():
                if len(count) > 50:
                    raise _too_long(
                        f"The 100% UPT count for {day}", 50, len(count)
                    )
        return v


class EstimateBlock(BaseModel):
    scope: str
    sample_size: int
    sample_total_upt: int
    sample_total_pmt: str
    sample_aptl: str
    expansion_factor_upt: str
    estimated_pmt: str
    method: str


class EstimateResponse(BaseModel):
    plan_id: str
    estimate: EstimateBlock
    by_service_day: Optional[list[EstimateBlock]]
    units_measured: int
    required_annual: int
    oversampled_by: int
    caveats: list[str]
    citations: list[str]
    retention_note: str
    audit_event_id: int


class OptionsResponse(BaseModel):
    modes: dict[str, str]
    units_by_mode: dict[str, list[str]]
    efficiency_options: list[str]
    creatable_options: list[str]
    frequencies: list[str]
    service_day_types: list[str]
    eligibility_guidance: list[str]
    retention_note: str


class RequirementResponse(BaseModel):
    mode: str
    mode_group: str
    unit: str
    efficiency_option: str
    frequency: str
    required_per_period: int
    required_annual: int
    table: str
    column: str
    citation: str
    guidance: list[str]
    selector_name: str
    selector_version: str


# --- helpers -----------------------------------------------------------------


def _plan_record(row) -> PlanRecord:
    return PlanRecord(
        plan_id=str(row[0]),
        report_year=row[1],
        mode=row[2],
        type_of_service=row[3],
        unit=row[4],
        efficiency_option=row[5],
        frequency=row[6],
        required_per_period=row[7],
        required_annual=row[8],
        table_citation=row[9],
        selector_version=row[10],
        status=row[11],
        created_by=row[12],
        created_at=row[13],
    )


def _measurement_record(row) -> MeasurementRecord:
    return MeasurementRecord(
        measurement_id=str(row[0]),
        plan_id=str(row[1]),
        unit_id=row[2],
        observed_upt=row[3],
        observed_pmt=str(row[4]),
        service_day_type=row[5],
        service_date=row[6],
        data_source=row[7],
        notes=row[8],
        entered_by=row[9],
        entered_at=row[10],
        superseded_by=(str(row[11]) if row[11] is not None else None),
    )


def _plan_or_404(db, plan_id: str):
    row = db.execute(_SELECT_PLAN_BY_ID, (plan_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404, detail="No sampling plan with that id exists."
        )
    return _plan_record(row)


def _draws_for_plan(db, plan_id: str) -> list[dict]:
    rows = db.execute(_SELECT_DRAWS, (plan_id,)).fetchall()
    return [
        {
            "draw_id": str(r[0]),
            "plan_id": str(r[1]),
            "period_label": r[2],
            "service_units": list(r[3]),
            "selected_units": list(r[4]),
            "seed": r[5],
            "seed_source": r[6],
            "oversample_units": r[7],
            "drawer_version": r[8],
            "drawn_by": r[9],
            "drawn_at": r[10],
        }
        for r in rows
    ]


def _measurements_for_plan(db, plan_id: str) -> list[MeasurementRecord]:
    rows = db.execute(_SELECT_MEASUREMENTS_FOR_PLAN, (plan_id,)).fetchall()
    return [_measurement_record(r) for r in rows]


def _active_measurements(
    measurements: list[MeasurementRecord],
) -> list[MeasurementRecord]:
    return [m for m in measurements if m.superseded_by is None]


# --- endpoints ---------------------------------------------------------------


@router.get("/sampling/options", response_model=OptionsResponse)
def get_options(
    identity: Identity = Depends(require_authenticated),
) -> OptionsResponse:
    """The plan wizard's vocabulary, straight from the calc selector's
    constants (Table 41.01 / §41.07), with the eligibility guidance."""
    return OptionsResponse(
        modes={
            mode: sampling_calc._GROUP_LABELS[group]
            for mode, group in sampling_calc.MODE_GROUPS.items()
        },
        units_by_mode={
            mode: list(sampling_calc.UNITS_BY_GROUP[group])
            for mode, group in sampling_calc.MODE_GROUPS.items()
        },
        efficiency_options=list(sampling_calc.EFFICIENCY_OPTIONS),
        creatable_options=list(CREATABLE_OPTIONS),
        frequencies=list(sampling_calc.FREQUENCIES),
        service_day_types=list(sampling_calc.SERVICE_DAY_TYPES),
        eligibility_guidance=list(sampling_calc.ELIGIBILITY_GUIDANCE),
        retention_note=sampling_calc.RETENTION_NOTE,
    )


@router.get("/sampling/requirements", response_model=RequirementResponse)
def get_requirement(
    mode: str = Query(),
    unit: str = Query(),
    efficiency_option: str = Query(),
    frequency: str = Query(),
    identity: Identity = Depends(require_authenticated),
) -> RequirementResponse:
    """Look up one ready-to-use table cell (verbatim, cited) without
    creating a plan — the wizard's live preview. All encoded cells are
    readable here, including the reference-only grouped-APTL cells."""
    try:
        requirement = sampling_calc.plan_requirement(
            mode, unit, efficiency_option, frequency
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return RequirementResponse(**requirement.to_dict())


@router.post("/sampling/plans", response_model=PlanCreated, status_code=201)
def create_plan(
    body: PlanCreate,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> PlanCreated:
    """Create a sampling plan. The required sizes are the calc selector's
    verbatim table cells; the selector version is recorded on the row."""
    if body.efficiency_option not in CREATABLE_OPTIONS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{body.efficiency_option}' plans cannot be created in "
                f"Headway v0. Choose 'aptl' (without route grouping) or "
                f"'base'. The With Route Grouping option requires sampling "
                f"and estimation separately for each route group "
                f"(§43.05(a)) and the §83.05(c) weighted APTL — not yet "
                f"mechanized (handoff 0012 honest scope). You can still "
                f"READ the grouped cells via GET /sampling/requirements."
            ),
        )
    try:
        requirement = sampling_calc.plan_requirement(
            body.mode, body.unit, body.efficiency_option, body.frequency
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    selector_version = (
        f"{requirement.selector_name} {requirement.selector_version}"
    )
    with db.transaction():
        row = db.execute(
            _INSERT_PLAN,
            (
                body.report_year, body.mode, body.type_of_service,
                body.unit, body.efficiency_option, body.frequency,
                requirement.required_per_period, requirement.required_annual,
                requirement.citation, selector_version, identity.username,
            ),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=500,
                detail="The plan insert returned no id; nothing was saved.",
            )
        plan_id, status, created_at = str(row[0]), row[1], row[2]
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sampling_plan_create",
            subject_kind="sampling.plans",
            subject_id=plan_id,
            detail={
                "report_year": body.report_year,
                "mode": body.mode,
                "type_of_service": body.type_of_service,
                "unit": body.unit,
                "efficiency_option": body.efficiency_option,
                "frequency": body.frequency,
                "required_per_period": requirement.required_per_period,
                "required_annual": requirement.required_annual,
                "selector_version": selector_version,
            },
        )
    return PlanCreated(
        plan=PlanRecord(
            plan_id=plan_id,
            report_year=body.report_year,
            mode=body.mode,
            type_of_service=body.type_of_service,
            unit=body.unit,
            efficiency_option=body.efficiency_option,
            frequency=body.frequency,
            required_per_period=requirement.required_per_period,
            required_annual=requirement.required_annual,
            table_citation=requirement.citation,
            selector_version=selector_version,
            status=status,
            created_by=identity.username,
            created_at=created_at,
        ),
        guidance=list(requirement.guidance),
        retention_note=sampling_calc.RETENTION_NOTE,
        audit_event_id=audit_event_id,
    )


@router.get("/sampling/plans", response_model=list[PlanRecord])
def list_plans(
    report_year: Optional[int] = Query(default=None),
    mode: Optional[str] = Query(default=None),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[PlanRecord]:
    clauses: list[str] = []
    params: list = []
    if report_year is not None:
        clauses.append("report_year = %s")
        params.append(report_year)
    if mode is not None:
        clauses.append("mode = %s")
        params.append(mode)
    sql = _SELECT_PLANS
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY created_at, plan_id"
    return [_plan_record(r) for r in db.execute(sql, tuple(params)).fetchall()]


@router.get("/sampling/plans/{plan_id}", response_model=PlanRecord)
def get_plan(
    plan_id: str,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> PlanRecord:
    return _plan_or_404(db, plan_id)


@router.get("/sampling/plans/{plan_id}/draws", response_model=list[DrawRecord])
def list_draws(
    plan_id: str,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[DrawRecord]:
    plan = _plan_or_404(db, plan_id)
    return [
        DrawRecord(
            draw_id=d["draw_id"],
            plan_id=d["plan_id"],
            period_label=d["period_label"],
            frame_size=len(d["service_units"]),
            selected_units=d["selected_units"],
            seed=d["seed"],
            seed_source=d["seed_source"],
            required_per_period=plan.required_per_period,
            oversample_units=d["oversample_units"],
            drawer_version=d["drawer_version"],
            drawn_by=d["drawn_by"],
            drawn_at=d["drawn_at"],
        )
        for d in _draws_for_plan(db, plan_id)
    ]


@router.post(
    "/sampling/plans/{plan_id}/draws",
    response_model=DrawCreated,
    status_code=201,
)
def draw_period_sample(
    plan_id: str,
    body: DrawRequest,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> DrawCreated:
    """One random-selection act for one period: seeded, recorded, WITHOUT
    replacement (§63.03), drawn by the versioned calc drawer."""
    plan = _plan_or_404(db, plan_id)
    draws = _draws_for_plan(db, plan_id)
    if any(d["period_label"] == body.period_label for d in draws):
        raise HTTPException(
            status_code=409,
            detail=(
                f"A sample was already drawn for period "
                f"'{body.period_label}' of this plan. A draw is a "
                f"historical random-selection act and is never redone — "
                f"if it was made in error, document it and continue with "
                f"the next period."
            ),
        )
    already_listed = set()
    for d in draws:
        already_listed.update(d["service_units"])
    overlap = sorted(set(body.service_units) & already_listed)
    if overlap:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{len(overlap)} unit id(s) in this period's list were "
                f"already listed in an earlier period's draw (first few: "
                f"{', '.join(overlap[:5])}). Each service unit must be "
                f"identifiable across the year — qualify unit ids with "
                f"their period or date (the manual's own serial-number "
                f"scheme encodes the day, §63.09), so an observation can "
                f"never be attributed to two different service units."
            ),
        )
    # Seed provenance (migration 0022): 'client' when the caller supplied
    # the seed, 'generated' when Headway's CSPRNG produced it — recorded on
    # the draw, audited, and reflected in the method text, because the
    # §63.03(b)(1) randomness claim is only Headway's to make for a seed
    # Headway generated.
    if body.seed is not None:
        seed, seed_source = body.seed, SEED_SOURCE_CLIENT
    else:
        seed, seed_source = secrets.token_hex(16), SEED_SOURCE_GENERATED
    sample_size = plan.required_per_period + body.oversample_units
    try:
        draw = sampling_calc.draw_sample(
            body.service_units, sample_size, seed
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    drawer_version = f"{draw.drawer_name} {draw.drawer_version}"
    with db.transaction():
        row = db.execute(
            _INSERT_DRAW,
            (
                plan_id, body.period_label, list(body.service_units),
                list(draw.selected_units), seed, seed_source,
                body.oversample_units, drawer_version, identity.username,
            ),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=500,
                detail="The draw insert returned no id; nothing was saved.",
            )
        draw_id, drawn_at = str(row[0]), row[1]
        if plan.status == "created":
            db.execute(_ACTIVATE_PLAN, (plan_id,))
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sampling_draw_create",
            subject_kind="sampling.draws",
            subject_id=draw_id,
            detail={
                "plan_id": plan_id,
                "period_label": body.period_label,
                "frame_size": draw.frame_size,
                "sample_size": draw.sample_size,
                "oversample_units": body.oversample_units,
                "seed": seed,
                "seed_source": seed_source,
                "drawer_version": drawer_version,
            },
        )
    return DrawCreated(
        draw=DrawRecord(
            draw_id=draw_id,
            plan_id=plan_id,
            period_label=body.period_label,
            frame_size=draw.frame_size,
            selected_units=list(draw.selected_units),
            seed=seed,
            seed_source=seed_source,
            required_per_period=plan.required_per_period,
            oversample_units=body.oversample_units,
            drawer_version=drawer_version,
            drawn_by=identity.username,
            drawn_at=drawn_at,
        ),
        # The drawer's DRAW_METHOD conditions its randomness claim on a
        # cryptographically random seed; the appended provenance note says
        # whether that premise holds for THIS draw (per seed_source) —
        # never an unconditional cryptographic-randomness assertion.
        method=f"{draw.method} {_SEED_PROVENANCE_NOTES[seed_source]}",
        oversampling_note=(
            _OVERSAMPLING_CITATION if body.oversample_units > 0 else None
        ),
        retention_note=sampling_calc.RETENTION_NOTE,
        audit_event_id=audit_event_id,
    )


def _validate_measurement_unit(db, plan_id: str, unit_id: str) -> None:
    selected: set[str] = set()
    for d in _draws_for_plan(db, plan_id):
        selected.update(d["selected_units"])
    if not selected:
        raise HTTPException(
            status_code=422,
            detail=(
                "This plan has no drawn sample yet. Draw the period's "
                "sample first (POST /sampling/plans/{plan_id}/draws); "
                "measurements are recorded only for randomly selected "
                "units."
            ),
        )
    if unit_id not in selected:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Unit '{unit_id}' is not in this plan's drawn sample. "
                f"Measurements are recorded only for the randomly selected "
                f"units — measuring hand-picked extra units would not be "
                f"random sampling (oversampling is allowed only when the "
                f"extra units are selected randomly, via the draw's "
                f"oversample option)."
            ),
        )


@router.post(
    "/sampling/plans/{plan_id}/measurements",
    response_model=MeasurementCreated,
    status_code=201,
)
def create_measurement(
    plan_id: str,
    body: MeasurementCreate,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> MeasurementCreated:
    """Record one ride-check observation for one drawn unit. Append-only:
    corrections supersede."""
    _plan_or_404(db, plan_id)
    _validate_measurement_unit(db, plan_id, body.unit_id)
    active = {
        m.unit_id
        for m in _active_measurements(_measurements_for_plan(db, plan_id))
    }
    if body.unit_id in active:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Unit '{body.unit_id}' already has an observation on "
                f"file. To correct it, supersede the existing measurement "
                f"(POST /sampling/measurements/{{measurement_id}}/"
                f"supersede) — originals are never edited, so the history "
                f"stays honest."
            ),
        )
    with db.transaction():
        row = db.execute(
            _INSERT_MEASUREMENT,
            (
                plan_id, body.unit_id, body.observed_upt,
                Decimal(body.observed_pmt), body.service_day_type,
                body.service_date, "manual_ride_check", body.notes,
                identity.username,
            ),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "The measurement insert returned no id; nothing was "
                    "saved."
                ),
            )
        measurement_id, entered_at = str(row[0]), row[1]
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sampling_measurement_create",
            subject_kind="sampling.measurements",
            subject_id=measurement_id,
            detail={
                "plan_id": plan_id,
                "unit_id": body.unit_id,
                "observed_upt": body.observed_upt,
                "observed_pmt": body.observed_pmt,
                "service_day_type": body.service_day_type,
            },
        )
    return MeasurementCreated(
        measurement=MeasurementRecord(
            measurement_id=measurement_id,
            plan_id=plan_id,
            unit_id=body.unit_id,
            observed_upt=body.observed_upt,
            observed_pmt=body.observed_pmt,
            service_day_type=body.service_day_type,
            service_date=body.service_date,
            data_source="manual_ride_check",
            notes=body.notes,
            entered_by=identity.username,
            entered_at=entered_at,
            superseded_by=None,
        ),
        source_caveat=_MANUAL_ENTRY_CAVEAT,
        retention_note=sampling_calc.RETENTION_NOTE,
        audit_event_id=audit_event_id,
    )


@router.get(
    "/sampling/plans/{plan_id}/measurements",
    response_model=list[MeasurementRecord],
)
def list_measurements(
    plan_id: str,
    include_superseded: bool = Query(default=False),
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> list[MeasurementRecord]:
    _plan_or_404(db, plan_id)
    measurements = _measurements_for_plan(db, plan_id)
    if not include_superseded:
        measurements = _active_measurements(measurements)
    return measurements


@router.post(
    "/sampling/measurements/{measurement_id}/supersede",
    response_model=MeasurementSuperseded,
    status_code=201,
)
def supersede_measurement(
    measurement_id: str,
    body: MeasurementSupersedeRequest,
    identity: Identity = Depends(require_at_least("data_steward")),
    db=Depends(get_db),
) -> MeasurementSuperseded:
    """Append-only correction: enter the CORRECTED observation in full; the
    original stays untouched except for its superseded_by link (the
    migration-0017 supersede pattern; migration 0020's trigger enforces
    it)."""
    with db.transaction():
        row = db.execute(
            _SELECT_MEASUREMENT_BY_ID, (measurement_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail="No sampling measurement with that id exists.",
            )
        original = _measurement_record(row)
        if original.superseded_by is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This measurement was already corrected once. To "
                    "correct it again, supersede its replacement — every "
                    "correction stays in the chain so the history is "
                    "honest."
                ),
            )
        if body.unit_id != original.unit_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"A correction must observe the same service unit "
                    f"('{original.unit_id}'), not '{body.unit_id}'. To "
                    f"record a different unit, enter a new measurement for "
                    f"it instead."
                ),
            )
        # Link FIRST, then insert: the one-active-per-unit unique index is
        # checked per statement, so the original must leave the active set
        # before its replacement enters it. The API generates the
        # replacement id; the deferred FK validates at commit.
        replacement_id = str(uuid.uuid4())
        linked = db.execute(
            _LINK_MEASUREMENT_SUPERSEDED, (replacement_id, measurement_id)
        ).fetchone()
        if linked is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This measurement was corrected by someone else while "
                    "your correction was being saved. Nothing was changed "
                    "— please review the existing correction first."
                ),
            )
        replacement_row = db.execute(
            _INSERT_MEASUREMENT_REPLACEMENT,
            (
                replacement_id, original.plan_id, body.unit_id,
                body.observed_upt, Decimal(body.observed_pmt),
                body.service_day_type, body.service_date,
                "manual_ride_check", body.notes, identity.username,
            ),
        ).fetchone()
        if replacement_row is None:
            raise HTTPException(
                status_code=500,
                detail=(
                    "The corrected measurement insert returned no id; "
                    "nothing was saved."
                ),
            )
        entered_at = replacement_row[1]
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sampling_measurement_supersede",
            subject_kind="sampling.measurements",
            subject_id=measurement_id,
            detail={
                "plan_id": original.plan_id,
                "replacement_measurement_id": replacement_id,
                "unit_id": body.unit_id,
                "reason": body.reason,
                "observed_upt": body.observed_upt,
                "observed_pmt": body.observed_pmt,
            },
        )
    return MeasurementSuperseded(
        original_measurement_id=measurement_id,
        replacement=MeasurementRecord(
            measurement_id=replacement_id,
            plan_id=original.plan_id,
            unit_id=body.unit_id,
            observed_upt=body.observed_upt,
            observed_pmt=body.observed_pmt,
            service_day_type=body.service_day_type,
            service_date=body.service_date,
            data_source="manual_ride_check",
            notes=body.notes,
            entered_by=identity.username,
            entered_at=entered_at,
            superseded_by=None,
        ),
        source_caveat=_MANUAL_ENTRY_CAVEAT,
        audit_event_id=audit_event_id,
    )


@router.get("/sampling/plans/{plan_id}/progress", response_model=PlanProgress)
def get_progress(
    plan_id: str,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> PlanProgress:
    """Measured vs required, per draw and overall, with the worksheet of
    drawn-but-unmeasured units."""
    plan = _plan_or_404(db, plan_id)
    draws = _draws_for_plan(db, plan_id)
    active = _active_measurements(_measurements_for_plan(db, plan_id))
    measured_units = {m.unit_id for m in active}
    selected_all: list[str] = []
    draw_progress: list[DrawProgress] = []
    for d in draws:
        selected_all.extend(d["selected_units"])
        draw_progress.append(
            DrawProgress(
                period_label=d["period_label"],
                selected=len(d["selected_units"]),
                measured=sum(
                    1 for u in d["selected_units"] if u in measured_units
                ),
                oversample_units=d["oversample_units"],
            )
        )
    unmeasured = [u for u in selected_all if u not in measured_units]
    return PlanProgress(
        plan=plan,
        required_per_period=plan.required_per_period,
        required_annual=plan.required_annual,
        draws=draw_progress,
        units_selected=len(selected_all),
        units_measured=len(measured_units),
        units_unmeasured=unmeasured,
        undersampled=len(measured_units) < plan.required_annual,
        undersampling_citation=_UNDERSAMPLING_CITATION,
        oversampling_citation=_OVERSAMPLING_CITATION,
        retention_note=sampling_calc.RETENTION_NOTE,
    )


@router.post(
    "/sampling/plans/{plan_id}/estimate",
    response_model=EstimateResponse,
)
def generate_estimate(
    plan_id: str,
    body: EstimateRequest,
    identity: Identity = Depends(require_at_least("report_preparer")),
    db=Depends(get_db),
) -> EstimateResponse:
    """The §83 APTL estimate over the plan's active measurements. REFUSES
    Base-option plans and undersampled plans; the result is a SAMPLED
    ESTIMATE (provenance-labeled) and is never written to
    computed.metric_values."""
    plan = _plan_or_404(db, plan_id)
    if plan.efficiency_option != "aptl":
        raise HTTPException(
            status_code=422,
            detail=(
                "This plan uses the Base Option (both UPT and PMT sampled). "
                "Headway v0 can generate estimates only for APTL-option "
                "plans (§83); Base-option estimation follows Section 70 of "
                "the Sampling Manual and is not yet mechanized (handoff "
                "0012 honest scope). The plan's draws and measurements "
                "remain on file for when it is."
            ),
        )
    active = _active_measurements(_measurements_for_plan(db, plan_id))
    if len(active) < plan.required_annual:
        raise HTTPException(
            status_code=422,
            detail=(
                f"This plan requires {plan.required_annual} measured "
                f"units for the year ({plan.table_citation}) but only "
                f"{len(active)} have observations on file. Headway "
                f"refuses to estimate from an undersampled plan: "
                f"{_UNDERSAMPLING_CITATION} Enter the remaining "
                f"measurements (see GET /sampling/plans/{{plan_id}}/"
                f"progress for the worksheet) and try again."
            ),
        )
    observations = [
        sampling_calc.UnitObservation(
            unit_id=m.unit_id,
            observed_upt=m.observed_upt,
            observed_pmt=Decimal(m.observed_pmt),
            service_day_type=m.service_day_type,
        )
        for m in active
    ]
    try:
        annual = sampling_calc.estimate_annual_pmt(
            observations, body.annual_upt_100pct
        )
        by_day = None
        if body.upt_100pct_by_day_type is not None:
            by_day = sampling_calc.estimate_pmt_by_service_day(
                observations,
                {
                    k: Decimal(v)
                    for k, v in body.upt_100pct_by_day_type.items()
                },
            )
    except (ValueError, InvalidOperation) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    with db.transaction():
        audit_event_id = write_event(
            db,
            actor=identity.username,
            action="sampling_estimate_generate",
            subject_kind="sampling.plans",
            subject_id=plan_id,
            detail={
                "sample_size": annual.sample_size,
                "sample_total_upt": annual.sample_total_upt,
                "sample_total_pmt": str(annual.sample_total_pmt),
                "sample_aptl": str(annual.sample_aptl),
                "expansion_factor_upt": str(annual.expansion_factor_upt),
                "estimated_pmt": str(annual.estimated_pmt),
                "method": annual.method,
            },
        )
    return EstimateResponse(
        plan_id=plan_id,
        estimate=EstimateBlock(**annual.to_dict()),
        by_service_day=(
            [EstimateBlock(**e.to_dict()) for e in by_day]
            if by_day is not None
            else None
        ),
        units_measured=len(active),
        required_annual=plan.required_annual,
        oversampled_by=len(active) - plan.required_annual,
        caveats=[
            _NOT_COMPUTED_PMT,
            _MANUAL_ENTRY_CAVEAT,
            _EXPANSION_FACTOR_CAVEAT,
            _OVERSAMPLING_CITATION,
        ],
        citations=[
            (
                "Sample APTL: '"
                + sampling_calc.APTL_RATIO_OF_TOTALS_RULE
                + "' — and never the banned average: '"
                + sampling_calc.APTL_AVERAGE_OF_RATIOS_BAN
                + "' (FTA NTD Sampling Manual, 2009, §83.05(a)/(b), p. 42)."
            ),
            (
                "Expansion: 'You must use your 100% count of UPT as the "
                "expansion factor.' (§83.01(a), p. 42); annual total PMT "
                "per §83.07(a), p. 43."
            ),
            plan.table_citation,
        ],
        retention_note=sampling_calc.RETENTION_NOTE,
        audit_event_id=audit_event_id,
    )
