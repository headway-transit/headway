"""Settings sandbox — what-if modeling PREVIEW (handoff 0017, design point 6).

POST /sandbox/preview takes a knob set (the four seeded NTD calc-policy
knobs and/or the two OTP-window ops knobs) with proposed values and a
period, and returns the figure impact vs the CURRENT audited settings:
both variants are computed over the SAME canonical inputs by the calc
library's read-only preview entry points (headway_calc.runner
preview_period / preview_ops_period), so the delta isolates exactly the
knob change.

THE HARD WALLS (binding):

- **Changes nothing.** The preview entry points perform NO writes — no
  computed.metric_values rows, no dq.issues rows, no lineage, no commit
  (pinned by calc test; verified live by row counts). ``persisted`` is a
  constant false and the banner says so in plain language.
- **Never certifiable.** Preview results are EPHEMERAL — they exist only in
  this response, so no certification path can ever reach one. The
  alternative in the handoff (persisting previews as category='ops' rows
  tagged sandbox) was REJECTED as the larger and less honest design:
  headway_calc.persist derives ``category`` from the calc registry —
  never from a caller — precisely so figures cannot be re-labeled, and a
  sandbox would have had to break that rule to tag NTD-calc output 'ops'.
  Ephemeral previews need no exception. The migration-0024 CHECK
  (metric_values_ops_never_certified) remains the database wall behind
  everything ops-categorized that the REAL ops runner persists, proven by
  attack test.
- **Applying a knob is a different, audited act.** This endpoint changes no
  setting; the response points at the existing settings flow
  (PUT /settings/{key} — certifying official only, old→new audited).

Any signed-in role may preview: it is a read-only modeling tool over data
the same roles can already read.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from headway_calc import runner as calc_runner
from headway_calc.settings import (
    OPS_POLICY_SETTING_TYPES,
    POLICY_SETTING_TYPES,
    SettingsError,
)

from ..auth import Identity
from ..authz import require_authenticated
from ..db import get_db

router = APIRouter(tags=["sandbox"])

BANNER = (
    "MODELING PREVIEW — changes nothing. These figures were computed on the "
    "fly for this response only: no figure, data-quality issue, or setting "
    "was created or changed, nothing here is stored anywhere, and nothing "
    "here can ever be certified or reported. To actually change a policy "
    "knob, use the audited settings flow (PUT /settings/{key} — certifying "
    "official only)."
)

SETTINGS_FLOW_NOTE = (
    "Applying a knob is a separate, audited act: PUT /settings/{key} "
    "(certifying official only; the old and new values land in the audit "
    "trail). The next real calculation run then reads the changed setting."
)

#: Every previewable knob and its value type — exactly the seeded
#: app.settings knob sets the calc library reads (migrations 0014/0024).
#: imbalance_threshold is not an app.settings knob and is not previewable.
PREVIEWABLE_KNOBS: dict[str, str] = {
    **POLICY_SETTING_TYPES,
    **OPS_POLICY_SETTING_TYPES,
}


class SandboxPreviewRequest(BaseModel):
    period_start: dt.date
    period_end: dt.date
    #: Proposed knob values, keyed by settings key; values are STRINGS
    #: exactly like the settings surface (decimals parse via Decimal —
    #: floating point never touches a policy number).
    proposed: dict[str, str] = Field(min_length=1)


class PreviewSide(BaseModel):
    """One variant's outcome for one metric: the would-be value (or an
    honest refusal) plus every would-be finding. Nothing here was written
    anywhere."""

    value: Optional[str]
    blocked: bool
    findings: list[dict]
    detail: Optional[dict]


class PreviewMetricImpact(BaseModel):
    metric: str
    calc_name: str
    calc_version: str
    unit: str
    scope: str
    category: str
    baseline: PreviewSide
    proposed: PreviewSide
    #: Exact Decimal difference proposed - baseline, as a string; null when
    #: either side refused. A comparison affordance, never a figure.
    delta: Optional[str]


class PreviewSection(BaseModel):
    baseline_thresholds: dict[str, str]
    baseline_threshold_sources: dict[str, str]
    proposed_thresholds: dict[str, str]
    inputs: dict[str, int]
    metrics: list[PreviewMetricImpact]
    #: Ops only: the passage derivation's refusal accounting.
    derivation: Optional[dict] = None


class SandboxPreviewResponse(BaseModel):
    banner: str
    persisted: bool
    period_start: dt.date
    period_end: dt.date
    period_convention: str
    proposed: dict[str, str]
    settings_flow_note: str
    #: Present when any of the four NTD calc-policy knobs was proposed.
    ntd: Optional[PreviewSection] = None
    #: Present when any of the two OTP-window ops knobs was proposed.
    ops: Optional[PreviewSection] = None


def _validate_proposed(proposed: dict[str, str]) -> None:
    unknown = sorted(k for k in proposed if k not in PREVIEWABLE_KNOBS)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=(
                f"{', '.join(unknown)} is not a policy knob the sandbox can "
                f"preview. Previewable knobs are: "
                f"{', '.join(sorted(PREVIEWABLE_KNOBS))}."
            ),
        )
    for key, value in proposed.items():
        value_type = PREVIEWABLE_KNOBS[key]
        if value_type == "decimal":
            try:
                parsed = Decimal(value)
            except InvalidOperation:
                parsed = None
            if parsed is None or not parsed.is_finite():
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"'{value}' is not a decimal number, so it cannot be "
                        f"previewed as '{key}'. Please send a plain decimal "
                        f"number, for example '0.95'."
                    ),
                )
        else:
            try:
                int(value)
            except ValueError:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"'{value}' is not a whole number, so it cannot be "
                        f"previewed as '{key}'. Please send a whole number "
                        f"of seconds, for example '300'."
                    ),
                )


def _side(outcome: dict) -> PreviewSide:
    return PreviewSide(
        value=outcome["value"],
        blocked=outcome["blocked"],
        findings=outcome["findings"],
        detail=outcome["detail"],
    )


def _impacts(
    baseline_outcomes: list[dict], proposed_outcomes: list[dict], category: str
) -> list[PreviewMetricImpact]:
    impacts: list[PreviewMetricImpact] = []
    proposed_by_key = {
        (o["calc_name"], o["scope"]): o for o in proposed_outcomes
    }
    for base in baseline_outcomes:
        prop = proposed_by_key[(base["calc_name"], base["scope"])]
        delta = (
            str(Decimal(prop["value"]) - Decimal(base["value"]))
            if base["value"] is not None and prop["value"] is not None
            else None
        )
        impacts.append(
            PreviewMetricImpact(
                metric=base["metric"],
                calc_name=base["calc_name"],
                calc_version=base["calc_version"],
                unit=base["unit"],
                scope=base["scope"],
                category=category,
                baseline=_side(base),
                proposed=_side(prop),
                delta=delta,
            )
        )
    return impacts


@router.post("/sandbox/preview", response_model=SandboxPreviewResponse)
def sandbox_preview(
    body: SandboxPreviewRequest,
    identity: Identity = Depends(require_authenticated),
    db=Depends(get_db),
) -> SandboxPreviewResponse:
    """Preview the figure impact of proposed policy-knob values for one
    period — read-only, ephemeral, never certifiable (module docstring).
    Baseline = the CURRENT audited settings (app.settings, the same
    precedence a real run uses); proposed = the same computation with only
    the proposed knobs overridden."""
    if body.period_end <= body.period_start:
        raise HTTPException(
            status_code=422,
            detail=(
                "period_end must come after period_start — periods are "
                "half-open [start, end)."
            ),
        )
    _validate_proposed(body.proposed)

    ntd_knobs = {
        k: v for k, v in body.proposed.items() if k in POLICY_SETTING_TYPES
    }
    ops_knobs = {
        k: v for k, v in body.proposed.items() if k in OPS_POLICY_SETTING_TYPES
    }

    ntd_section: Optional[PreviewSection] = None
    ops_section: Optional[PreviewSection] = None
    try:
        if ntd_knobs:
            report = calc_runner.preview_period(
                db,
                body.period_start,
                body.period_end,
                [
                    calc_runner.PreviewVariant(label="baseline"),
                    calc_runner.PreviewVariant(
                        label="proposed",
                        gap_threshold_seconds=ntd_knobs.get(
                            "gap_threshold_seconds"
                        ),
                        coverage_threshold=ntd_knobs.get("coverage_threshold"),
                        layover_max_seconds=ntd_knobs.get(
                            "layover_max_seconds"
                        ),
                        missing_trip_threshold=ntd_knobs.get(
                            "missing_trip_threshold"
                        ),
                    ),
                ],
            ).to_dict()
            baseline, proposed = report["variants"]
            ntd_section = PreviewSection(
                baseline_thresholds=baseline["thresholds"],
                baseline_threshold_sources=baseline["threshold_sources"],
                proposed_thresholds=proposed["thresholds"],
                inputs={
                    "positions_loaded": report["positions_loaded"],
                    "passenger_events_loaded": report[
                        "passenger_events_loaded"
                    ],
                    "operated_trips_loaded": report["operated_trips_loaded"],
                    "stop_times_loaded": report["stop_times_loaded"],
                },
                metrics=_impacts(
                    baseline["outcomes"], proposed["outcomes"], "ntd"
                ),
            )
        if ops_knobs:
            report = calc_runner.preview_ops_period(
                db,
                body.period_start,
                body.period_end,
                [
                    calc_runner.PreviewOpsVariant(label="baseline"),
                    calc_runner.PreviewOpsVariant(
                        label="proposed",
                        otp_early_tolerance_seconds=ops_knobs.get(
                            "otp_early_tolerance_seconds"
                        ),
                        otp_late_tolerance_seconds=ops_knobs.get(
                            "otp_late_tolerance_seconds"
                        ),
                    ),
                ],
            ).to_dict()
            baseline, proposed = report["variants"]
            ops_section = PreviewSection(
                baseline_thresholds=baseline["thresholds"],
                baseline_threshold_sources=baseline["threshold_sources"],
                proposed_thresholds=proposed["thresholds"],
                inputs={
                    "positions_loaded": report["positions_loaded"],
                    "schedule_rows_loaded": report["schedule_rows_loaded"],
                    "passages_derived": report["passages_derived"],
                },
                metrics=_impacts(
                    baseline["outcomes"], proposed["outcomes"], "ops"
                ),
                derivation=report["derivation"],
            )
    except SettingsError as exc:
        # A broken settings table refuses a preview exactly like a real run:
        # the agency's stated policy is unknowable, so no baseline exists.
        raise HTTPException(status_code=503, detail=str(exc))

    return SandboxPreviewResponse(
        banner=BANNER,
        persisted=False,
        period_start=body.period_start,
        period_end=body.period_end,
        period_convention="half-open [period_start, period_end), UTC",
        proposed=dict(body.proposed),
        settings_flow_note=SETTINGS_FLOW_NOTE,
        ntd=ntd_section,
        ops=ops_section,
    )
