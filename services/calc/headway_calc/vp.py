"""Vanpool (VP mode) calculations over the fleet-telematics contract
(handoff 0042, gated on handoff 0028's telematics wave).

Regulatory basis — 2026 NTD Full Reporting Policy Manual (identical text in
the 2025 manual), EXACTLY as quoted in REGULATORY_TRACKER.md, "Verified —
Vanpool (VP mode) reporting". No regulatory rule below enters from memory;
every rule is one of those quotes. THE INPUT IS canonical.vehicle_telematics_days
(migration 0034) — MEASURED VEHICLE MOVEMENT, subject to the honesty wall
(contracts/fleet-telematics.v0.md): telematics distance is NOT revenue miles,
engine/duty time is NOT revenue hours.

WHY EVERY VP FIGURE REFUSES IN v0 — THE HONESTY WALL MEETS THE MANUAL
--------------------------------------------------------------------

The FTA vanpool definition and revenue-service rules make telematics
distance/engine-time INSUFFICIENT to compute any certifiable VP figure. The
calc therefore REFUSES each figure with a plain-language blocking finding
naming exactly what is missing, and never guesses — while attaching a
CONTEXT detail that records the movement actually observed (honestly labelled
as NOT a reportable figure), so the refusal is auditable and the telematics
is not wasted.

- **VP VRM / VRH — the odometer is not revenue miles (p. 128, p. 122,
  p. 131).** "Actual Vehicle Revenue Hours (VRH) and Actual Vehicle Revenue
  Miles (VRM) are the hours and miles vehicles travel while in revenue
  service"; "VRM and VRH exclude the miles and hours related to ... Other
  non-revenue uses of the vehicles" (p. 128). A vanpool van is defined by
  "Use vehicles for which 80 percent of the yearly mileage comes from
  commuting" (p. 36) — the van's own definition admits up to 20% NON-commute
  personal mileage, and the van "lives at a participant's house" (the wire
  contract's honesty wall). An odometer delta is ALL of that movement.
  Crucially, the manual states VP VRM/VRH is RIDER-SELF-REPORTED, not
  sensor-derived: "For agencies that operate Vanpools, there may be times
  when passengers fail to report data for VRM and VRH for certain trips. If
  this occurs, please contact the assigned NTD analyst." (p. 131). And 100%
  counts are mandatory with NO estimation: "agencies must collect and record
  100 percent of all miles and hours vehicles travel in revenue service. FTA
  does not allow agencies to estimate these data." (p. 122). Nothing in the
  telematics contract declares which movement was revenue commuting service,
  so a VP VRM/VRH figure from telematics would be BOTH an unallowed estimate
  AND a substitution of "all movement" for "revenue service". REFUSED,
  missing: an agency-declared statement of the revenue-commuting portion of
  each vehicle-day (the handoff-0028 Open Question).

- **VP UPT — the driver-as-passenger rule needs a roster, not a sensor
  (p. 143).** "For Vanpool (VP) service, agencies generally must report the
  driver as a passenger and include the driver in UPT counts. In almost all
  cases, the Vanpool driver is unpaid and is traveling for personal reasons
  ... In the rare case when the driver is employed as a driver and not
  traveling for personal reasons, then the driver should not be counted as a
  passenger." UPT is "the number of boardings" (p. 143). Telematics measures
  DISTANCE and ENGINE TIME — it counts no boardings and knows nothing of who
  was aboard or whether the driver was a personal-reason rider or an
  employee. REFUSED, missing: passenger boarding counts and the driver's
  employment/travel-purpose status — a roster / ride record, not telematics.

- **VP VOMS — needs revenue-service simultaneity, which telematics cannot
  establish (Exhibit 38, p. 138).** For Demand Response AND Vanpool: "The
  largest number of vehicles in revenue service at any one time during the
  reporting year (includes atypical service)." VOMS counts vehicles IN
  REVENUE SERVICE simultaneously; telematics knows a vehicle MOVED, not that
  the movement was revenue commuting service. REFUSED, missing: the same
  agency revenue-service declaration VRM/VRH needs, applied to
  simultaneity — telematics movement alone is an upper bound on "vehicles
  that moved", never "vehicles in revenue service at once".

WHAT THE CALC DOES DELIVER (honestly, as CONTEXT — never a reportable figure)
-----------------------------------------------------------------------------
Every VP figure result carries a VpTelematicsDetail recording the observed
movement per basis: total distance meters and engine seconds actually
measured over the window, the count of series seen, the count UNMEASURED
(value absent — fewer than two readings, or a counter regression: stated,
never zeroed), and any cross-basis distance disagreement (Shared Constraint 7
— surfaced as a warning, never averaged away). This is the "explain the
refusal" substrate: a human sees exactly what telematics saw and exactly why
it is not yet a VP number.

Fail-loudly positions (all documented in the tracker rows):
- Every figure REFUSES with ONE blocking finding naming the missing input;
  value is None; no number is ever guessed.
- An UNMEASURED series (value absent) is counted and stated in the detail,
  never coerced to 0.
- Two distance bases on the same vehicle-day that disagree beyond
  ``basis_conflict_tolerance_meters`` raise ONE warning per vehicle-day —
  the disagreement the honesty wall keeps visible.
- Simulated sources (any '_simulated' suffix, e.g. 'samsara_simulated')
  always yield the 'simulated_source_data' info finding; source_mix is
  always in the detail. A '_simulated' source is an INDEPENDENT reason the
  figure is not certifiable, on top of the missing-revenue-declaration
  refusal.

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time and quantities come exclusively from the input rows. Decimal
end to end (SI on the wire; no premature mile/hour conversion — the refusal
happens before any conversion would).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from headway_calc.types import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    VP_MEASURE_DISTANCE,
    VP_MEASURE_ENGINE_TIME,
    CalcResult,
    Finding,
    VpTelematicsDay,
    VpTelematicsDetail,
)

#: Per-figure calc names + version. One module, four figures — every one
#: refuses in v0, so they share a version (0.1.0) that mints a new tracker
#: row when any refusal reasoning changes.
VP_VRM_CALC_NAME = "vp_vrm_v0"
VP_VRH_CALC_NAME = "vp_vrh_v0"
VP_UPT_CALC_NAME = "vp_upt_v0"
VP_VOMS_CALC_NAME = "vp_voms_v0"
VP_CALC_VERSION = "0.1.0"

#: Figure keys carried in the detail.
FIGURE_VRM = "vrm"
FIGURE_VRH = "vrh"
FIGURE_UPT = "upt"
FIGURE_VOMS = "voms"

#: Units follow the fixed-route calcs' vocabulary so a (future, reportable)
#: VP figure would land in the same metric surfaces. The refused v0 results
#: carry the unit for shape-compatibility even though value is None.
UNIT_MILES = "miles"
UNIT_HOURS = "hours"
UNIT_UPT = "unlinked_passenger_trips"
UNIT_VEHICLES = "vehicles"

#: The registered REAL telematics labels. Anything else — anything carrying a
#: '_simulated' suffix, or any other label — trips the simulated/non-real
#: source info finding (erring toward flagging, exactly like the DR/UPT
#: 'dr'/'tides' rule). Kept as a set so a second real vendor label is a
#: one-line addition.
_REAL_SOURCES = frozenset({"samsara"})

#: Default tolerance for declaring two distance bases on one vehicle-day in
#: conflict: 100 meters. An ENGINEERING PLACEHOLDER (not an FTA number) — the
#: honesty wall's point is that ANY disagreement is visible; the tolerance
#: only decides when it is worth a human's attention. Explicit input.
DEFAULT_BASIS_CONFLICT_TOLERANCE_METERS = Decimal("100")

#: Machine keys of the refusal findings — one per figure, each naming what
#: telematics cannot provide.
REFUSAL_VRM = "vp_vrm_needs_revenue_service_declaration"
REFUSAL_VRH = "vp_vrh_needs_revenue_service_declaration"
REFUSAL_UPT = "vp_upt_needs_passenger_roster"
REFUSAL_VOMS = "vp_voms_needs_revenue_service_declaration"

BASIS_CONFLICT_ISSUE = "vp_telematics_basis_conflict"
UNMEASURED_ISSUE = "vp_telematics_series_unmeasured"
SIMULATED_SOURCE_ISSUE = "simulated_source_data"


def _is_simulated(source: str) -> bool:
    """A source is simulated/non-real when it is not a registered real vendor
    label — the '_simulated' suffix is the canonical case (handoff 0005)."""
    return source not in _REAL_SOURCES


def _observed_movement(
    rows: list[VpTelematicsDay],
) -> tuple[Decimal, Decimal, dict[str, Decimal]]:
    """Sum the MEASURED movement per basis — CONTEXT only, never a reportable
    figure. Returns (total_distance_meters, total_engine_seconds, by_basis).

    An UNMEASURED series (``value is None``) contributes nothing to the sums
    and is NOT counted here as 0 movement — it is counted as unmeasured by
    the caller. The per-basis breakdown keeps every basis distinct (the
    honesty wall: no basis is ever merged into another)."""
    total_distance = Decimal(0)
    total_engine = Decimal(0)
    by_basis: dict[str, Decimal] = {}
    for row in rows:
        if row.value is None:
            continue
        by_basis[row.basis] = by_basis.get(row.basis, Decimal(0)) + row.value
        if row.measure == VP_MEASURE_DISTANCE:
            total_distance += row.value
        elif row.measure == VP_MEASURE_ENGINE_TIME:
            total_engine += row.value
    return total_distance, total_engine, by_basis


def _basis_conflict_findings(
    rows: list[VpTelematicsDay],
    tolerance_meters: Decimal,
) -> list[Finding]:
    """One warning per (vehicle_id, service_date) whose MEASURED distance
    bases disagree by more than ``tolerance_meters`` (Shared Constraint 7 —
    the AVL-vs-odometer conflict, kept visible, never averaged). Bases with an
    absent value are skipped (an unmeasured series cannot disagree)."""
    per_day: dict[tuple[str, str], dict[str, Decimal]] = {}
    per_day_ids: dict[tuple[str, str], list[str]] = {}
    for row in rows:
        if row.measure != VP_MEASURE_DISTANCE or row.value is None:
            continue
        key = (row.vehicle_id, row.service_date.isoformat())
        per_day.setdefault(key, {})[row.basis] = row.value
        per_day_ids.setdefault(key, []).append(row.source_record_id)

    findings: list[Finding] = []
    for key in sorted(per_day):
        bases = per_day[key]
        if len(bases) < 2:
            continue
        values = list(bases.values())
        spread = max(values) - min(values)
        if spread > tolerance_meters:
            vehicle_id, service_date = key
            findings.append(
                Finding(
                    issue_type=BASIS_CONFLICT_ISSUE,
                    title="Telematics distance bases disagree",
                    description=(
                        f"Vehicle {vehicle_id} on {service_date} reports "
                        f"distance on {len(bases)} bases "
                        f"({', '.join(sorted(bases))}) that disagree by "
                        f"{spread} meters (> tolerance {tolerance_meters} m). "
                        f"Shared Constraint 7: the disagreement is surfaced, "
                        f"never averaged away — a human picks which to trust."
                    ),
                    source_record_ids=tuple(sorted(set(per_day_ids[key]))),
                    severity=SEVERITY_WARNING,
                )
            )
    return findings


def _unmeasured_findings(rows: list[VpTelematicsDay]) -> list[Finding]:
    """One warning per UNMEASURED series (value absent): fewer than two
    readings, or a counter that ran backwards. Stated, never zeroed — the
    absence is visible (the fleet-telematics honesty rule)."""
    findings: list[Finding] = []
    for row in rows:
        if row.value is not None:
            continue
        findings.append(
            Finding(
                issue_type=UNMEASURED_ISSUE,
                title="Telematics series unmeasured",
                description=(
                    f"Vehicle {row.vehicle_id} on {row.service_date.isoformat()} "
                    f"has an UNMEASURED {row.measure}/{row.basis} series "
                    f"(sample_count={row.sample_count}) — fewer than two "
                    f"readings, or a counter regression. Recorded as absent, "
                    f"never as zero movement."
                ),
                source_record_ids=(row.source_record_id,),
                severity=SEVERITY_WARNING,
            )
        )
    return findings


def _source_mix(rows: list[VpTelematicsDay]) -> dict[str, int]:
    mix: dict[str, int] = {}
    for row in rows:
        mix[row.source] = mix.get(row.source, 0) + 1
    return mix


def _simulated_source_info(rows: list[VpTelematicsDay]) -> list[Finding]:
    """One info finding when ANY series comes from a simulated/non-real
    source — a certifiable VP figure containing simulated records is a
    contradiction, so this is recorded independently of the (always present)
    refusal."""
    sim_ids = tuple(row.source_record_id for row in rows if _is_simulated(row.source))
    if not sim_ids:
        return []
    labels = sorted({row.source for row in rows if _is_simulated(row.source)})
    return [
        Finding(
            issue_type=SIMULATED_SOURCE_ISSUE,
            title="Simulated telematics source",
            description=(
                f"{len(sim_ids)} telematics series came from simulated/non-real "
                f"source(s) {labels}. Even once a VP revenue-service declaration "
                f"exists, a figure over simulated data can never be certified "
                f"(handoff 0005 simulated-data rule)."
            ),
            source_record_ids=sim_ids,
            severity=SEVERITY_INFO,
        )
    ]


def _refusal_result(
    rows: list[VpTelematicsDay],
    *,
    calc_name: str,
    unit: str,
    figure: str,
    refusal_issue: str,
    refusal_title: str,
    refusal_description: str,
    tolerance_meters: Decimal,
) -> CalcResult:
    """Build the REFUSED result common to all four VP figures: value None,
    ONE blocking finding naming the missing input, plus the observed-movement
    CONTEXT detail, the basis-conflict / unmeasured warnings, and the
    simulated-source info. No number is ever emitted."""
    material = list(rows)

    total_distance, total_engine, by_basis = _observed_movement(material)
    unmeasured = [r for r in material if r.value is None]
    warnings = _basis_conflict_findings(material, tolerance_meters)
    warnings += _unmeasured_findings(material)
    infos = _simulated_source_info(material)

    # The blocking finding cites every material record — the refusal is about
    # the whole input, and citing the records lets a human see exactly what
    # was on hand when the figure refused.
    blocking = Finding(
        issue_type=refusal_issue,
        title=refusal_title,
        description=refusal_description,
        source_record_ids=tuple(r.source_record_id for r in material),
        severity=SEVERITY_BLOCKING,
    )

    detail = VpTelematicsDetail(
        figure=figure,
        reportable=False,
        refusal_reason=refusal_issue,
        vehicle_days_seen=len(material),
        vehicle_days_unmeasured=len(unmeasured),
        observed_distance_meters=(
            str(total_distance) if any(
                r.measure == VP_MEASURE_DISTANCE for r in material
            ) else None
        ),
        observed_engine_seconds=(
            str(total_engine) if any(
                r.measure == VP_MEASURE_ENGINE_TIME for r in material
            ) else None
        ),
        by_basis={k: str(v) for k, v in by_basis.items()},
        basis_conflicts=sum(
            1 for f in warnings if f.issue_type == BASIS_CONFLICT_ISSUE
        ),
        source_mix=_source_mix(material),
    )

    return CalcResult(
        value=None,
        unit=unit,
        calc_name=calc_name,
        calc_version=VP_CALC_VERSION,
        input_record_ids=(),
        blocking_issues=(blocking,),
        warnings=tuple(warnings),
        infos=tuple(infos),
        detail=detail,
    )


def compute_vp_vrm(
    rows: Iterable[VpTelematicsDay],
    *,
    basis_conflict_tolerance_meters: Decimal = DEFAULT_BASIS_CONFLICT_TOLERANCE_METERS,
) -> CalcResult:
    """vp_vrm_v0 0.1.0 — Vanpool Vehicle Revenue Miles. REFUSES.

    Telematics distance is ALL vehicle movement (p. 128 "VRM ... exclude ...
    Other non-revenue uses"; the p. 36 80%-commuting definition admits
    personal mileage). VP VRM is rider-self-reported (p. 131) and 100%-count,
    no-estimation (p. 122). Nothing in the telematics contract declares the
    revenue-commuting portion of a vehicle-day, so a VRM figure would be an
    unallowed estimate substituting all-movement for revenue service. Value
    None; the observed distance rides the detail as context."""
    return _refusal_result(
        list(rows),
        calc_name=VP_VRM_CALC_NAME,
        unit=UNIT_MILES,
        figure=FIGURE_VRM,
        refusal_issue=REFUSAL_VRM,
        refusal_title="Vanpool VRM not computable from telematics alone",
        refusal_description=(
            "Vanpool Vehicle Revenue Miles cannot be computed from fleet "
            "telematics. Telematics distance is ALL movement (revenue, "
            "deadhead, and personal use — a vanpool van is defined by only "
            "'80 percent of the yearly mileage comes from commuting', p. 36), "
            "whereas VRM is 'the ... miles vehicles travel while in revenue "
            "service' and 'exclude[s] ... Other non-revenue uses of the "
            "vehicles' (p. 128). VP VRM is rider-self-reported (p. 131) and "
            "must be a 100 percent count with no estimation (p. 122). MISSING: "
            "an agency-declared statement of the revenue-commuting portion of "
            "each vehicle-day (handoff 0028 Open Question). No figure is "
            "emitted; the observed odometer movement is recorded as context "
            "only."
        ),
        tolerance_meters=basis_conflict_tolerance_meters,
    )


def compute_vp_vrh(
    rows: Iterable[VpTelematicsDay],
    *,
    basis_conflict_tolerance_meters: Decimal = DEFAULT_BASIS_CONFLICT_TOLERANCE_METERS,
) -> CalcResult:
    """vp_vrh_v0 0.1.0 — Vanpool Vehicle Revenue Hours. REFUSES.

    Engine time is engine runtime including idling — not revenue hours; VRH
    is 'the hours ... vehicles travel while in revenue service' (p. 128) and,
    for VP, rider-self-reported (p. 131), 100%-count, no-estimation (p. 122).
    Nothing declares the revenue portion of the running time. Value None; the
    observed engine seconds ride the detail as context."""
    return _refusal_result(
        list(rows),
        calc_name=VP_VRH_CALC_NAME,
        unit=UNIT_HOURS,
        figure=FIGURE_VRH,
        refusal_issue=REFUSAL_VRH,
        refusal_title="Vanpool VRH not computable from telematics alone",
        refusal_description=(
            "Vanpool Vehicle Revenue Hours cannot be computed from fleet "
            "telematics. Engine time is engine runtime — including idling — "
            "not the 'hours ... vehicles travel while in revenue service' "
            "(p. 128); VP VRH is rider-self-reported (p. 131) and must be a "
            "100 percent count with no estimation (p. 122). MISSING: an "
            "agency-declared statement of the revenue-commuting portion of "
            "each vehicle-day (handoff 0028 Open Question). No figure is "
            "emitted; the observed engine time is recorded as context only."
        ),
        tolerance_meters=basis_conflict_tolerance_meters,
    )


def compute_vp_upt(
    rows: Iterable[VpTelematicsDay],
    *,
    basis_conflict_tolerance_meters: Decimal = DEFAULT_BASIS_CONFLICT_TOLERANCE_METERS,
) -> CalcResult:
    """vp_upt_v0 0.1.0 — Vanpool Unlinked Passenger Trips. REFUSES.

    UPT is 'the number of boardings' (p. 143); VP additionally 'must report
    the driver as a passenger ... In the rare case when the driver is
    employed as a driver ... the driver should not be counted' (p. 143).
    Telematics counts no boardings and knows nothing of who was aboard or the
    driver's employment/purpose. Value None."""
    return _refusal_result(
        list(rows),
        calc_name=VP_UPT_CALC_NAME,
        unit=UNIT_UPT,
        figure=FIGURE_UPT,
        refusal_issue=REFUSAL_UPT,
        refusal_title="Vanpool UPT not computable from telematics alone",
        refusal_description=(
            "Vanpool Unlinked Passenger Trips cannot be computed from fleet "
            "telematics. UPT is 'the number of boardings' (p. 143); Vanpool "
            "additionally 'must report the driver as a passenger and include "
            "the driver in UPT counts ... In the rare case when the driver is "
            "employed as a driver and not traveling for personal reasons, "
            "then the driver should not be counted as a passenger' (p. 143). "
            "Telematics measures distance and engine time — it counts no "
            "boardings and knows nothing of who was aboard. MISSING: passenger "
            "boarding counts and the driver's employment/travel-purpose "
            "status — a roster / ride record, not telematics. No figure is "
            "emitted."
        ),
        tolerance_meters=basis_conflict_tolerance_meters,
    )


def compute_vp_voms(
    rows: Iterable[VpTelematicsDay],
    *,
    basis_conflict_tolerance_meters: Decimal = DEFAULT_BASIS_CONFLICT_TOLERANCE_METERS,
) -> CalcResult:
    """vp_voms_v0 0.1.0 — Vanpool Vehicles Operated in Maximum Service.
    REFUSES.

    For Demand Response and Vanpool, VOMS is 'The largest number of vehicles
    in revenue service at any one time during the reporting year (includes
    atypical service)' (Exhibit 38, p. 138). Telematics knows a vehicle
    MOVED, not that the movement was revenue commuting service, so it cannot
    establish revenue-service simultaneity. Value None."""
    return _refusal_result(
        list(rows),
        calc_name=VP_VOMS_CALC_NAME,
        unit=UNIT_VEHICLES,
        figure=FIGURE_VOMS,
        refusal_issue=REFUSAL_VOMS,
        refusal_title="Vanpool VOMS not computable from telematics alone",
        refusal_description=(
            "Vanpool Vehicles Operated in Maximum Service cannot be computed "
            "from fleet telematics. For Demand Response and Vanpool, VOMS is "
            "'The largest number of vehicles in revenue service at any one "
            "time during the reporting year (includes atypical service)' "
            "(Exhibit 38, p. 138). Telematics knows a vehicle moved, not that "
            "the movement was revenue commuting service, so it cannot "
            "establish revenue-service simultaneity — the count of vehicles "
            "that moved at once is only an upper bound. MISSING: the same "
            "agency revenue-service declaration VRM/VRH needs. No figure is "
            "emitted."
        ),
        tolerance_meters=basis_conflict_tolerance_meters,
    )
