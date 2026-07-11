"""voms_v0 — Vehicles Operated in Maximum Service, monthly (handoff 0009).

Regulatory basis (2025 NTD Monthly and Weekly Reference Policy Manual, Form
MR-20, quote verified against docs/reference/ 2026-07-11; see
REGULATORY_TRACKER.md, calc voms_v0):

- **Monthly VOMS definition** (p. 33): "VOMS is the number of revenue
  vehicles/passenger cars operated to meet the maximum service requirement
  during the month of service reported. VOMS excludes atypical days or
  one-time special events."

v0 approximation (PRE-VERIFICATION — documented divergences, tracker row
voms_v0):

- The figure is the **maximum over service days of the count of distinct
  vehicles observed in revenue service** (positions with a trip assignment —
  the same revenue-service proxy as vrm_v0/vrh_v0) on that day.
- **Day convention (documented):** a service day is the UTC calendar date of
  the position's event time — NOT an agency service day (which may span
  midnight or follow a local timezone). A documented v0 convention, carried
  by the half-open UTC period the whole calc library uses.
- Divergence (a): "maximum service requirement" is schedule-peak
  SIMULTANEITY — the largest number of vehicles in service at once. The
  day-level distinct-vehicle max counts every vehicle used at any point of
  the peak day, so it is an UPPER-BOUND proxy for the true peak (verify
  against the Policy Manual VOMS section before any figure is reportable).
- Divergence (b): the p. 33 atypical-day / special-event exclusion is NOT
  implemented — it needs an agency calendar policy (open question, owner NTD
  role).
- Divergence (c): rail VOMS counts passenger cars; GTFS-RT carries one
  vehicle per trainset (existing divergence D2).

Why this calc is BLOCKING-FREE (no coverage machinery): vrm/vrh SUM over
telemetry, so a telemetry gap corrupts the summed figure and coverage draws a
certifiability line. VOMS is a MAXIMUM of daily distinct-vehicle counts — a
within-day telemetry gap cannot inflate the count (a vehicle observed at all
that day counts once), and missing telemetry can only LOWER a day's count or
drop a day entirely, i.e. understate a maximum. An observation gap therefore
never produces an overstated VOMS; it produces a documented potential
undercount, surfaced as ONE warning finding 'voms_partial_observation' when
fewer days were observed than the period contains (never a blocking refusal —
there is no per-group figure for the coverage machinery to certify).

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input positions.
"""

from __future__ import annotations

from datetime import date, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable

from headway_calc.types import (
    SEVERITY_WARNING,
    CalcResult,
    Finding,
    VehiclePosition,
    VomsDetail,
)

CALC_NAME = "voms_v0"
CALC_VERSION = "0.1.0"
UNIT = "vehicles"

#: Quantum for the REPORTED per-day mean (0.0001, ROUND_HALF_EVEN — the same
#: engineering convention as the coverage ratios; reporting provenance only).
_MEAN_QUANTUM = Decimal("0.0001")


def _service_day_utc(position: VehiclePosition) -> date:
    """The position's service day: the UTC calendar date of its event time
    (documented v0 convention — see module docstring)."""
    return position.time.astimezone(timezone.utc).date()


def compute_voms(
    positions: Iterable[VehiclePosition],
    period_start: date,
    period_end: date,
) -> CalcResult:
    """Compute voms_v0 (version 0.1.0) — monthly VOMS, pre-verification.

    Per service day (UTC calendar date of position time — documented
    convention), counts the DISTINCT vehicle_ids with at least one in-trip
    position (trip_id not None — the v0 revenue-service proxy, as in
    vrm_v0/vrh_v0); the figure is the maximum of those daily counts over the
    half-open period [period_start, period_end). Integer value (Decimal),
    unit 'vehicles'.

    Detail (VomsDetail): days_observed, days_in_period, peak_day (the
    EARLIEST day attaining the maximum — deterministic tie-break) and a
    per_day_counts summary {min, max, mean} (mean quantized 0.0001
    ROUND_HALF_EVEN, rendered as string). ``input_record_ids`` (lineage)
    covers the peak day's in-trip position records only — the records that
    evidence the reported maximum.

    Findings: BLOCKING-FREE by design (see module docstring — an observation
    gap can only understate a maximum, never overstate it). When
    days_observed < days_in_period, ONE warning 'voms_partial_observation'
    documents the potential undercount (missing days have no records to
    cite, so the finding names the counts in its description — the
    missing-trip precedent). No positions at all yield value 0 with the same
    warning: an observed maximum of zero vehicles, never a guess.

    Refuses (ValueError) an empty or inverted period, mirroring the reader's
    half-open [start, end) rule.
    """
    if period_start >= period_end:
        raise ValueError(
            f"Refusing empty/inverted period: period_start="
            f"{period_start.isoformat()} must be strictly before period_end="
            f"{period_end.isoformat()} (half-open [start, end))."
        )
    days_in_period = (period_end - period_start).days

    # Per-day distinct vehicles + per-day record ids, deterministic order.
    vehicles_by_day: dict[date, set[str]] = {}
    records_by_day: dict[date, dict[str, None]] = {}
    for pos in sorted(
        positions, key=lambda p: (p.time, p.vehicle_id, p.source_record_id)
    ):
        if pos.trip_id is None:
            continue  # revenue-service proxy: unassigned positions not counted
        day = _service_day_utc(pos)
        vehicles_by_day.setdefault(day, set()).add(pos.vehicle_id)
        records_by_day.setdefault(day, {}).setdefault(pos.source_record_id, None)

    days_observed = len(vehicles_by_day)
    if days_observed == 0:
        value = Decimal(0)
        peak_day: date | None = None
        input_ids: tuple[str, ...] = ()
        per_day_counts: dict = {"min": None, "max": None, "mean": None}
    else:
        counts = {day: len(vehicles) for day, vehicles in vehicles_by_day.items()}
        peak = max(counts.values())
        # Deterministic tie-break: the EARLIEST day attaining the maximum.
        peak_day = min(day for day, count in counts.items() if count == peak)
        value = Decimal(peak)
        input_ids = tuple(records_by_day[peak_day])
        mean = (Decimal(sum(counts.values())) / Decimal(days_observed)).quantize(
            _MEAN_QUANTUM, rounding=ROUND_HALF_EVEN
        )
        per_day_counts = {
            "min": min(counts.values()),
            "max": peak,
            "mean": str(mean),
        }

    warnings: tuple[Finding, ...] = ()
    if days_observed < days_in_period:
        warnings = (
            Finding(
                issue_type="voms_partial_observation",
                severity=SEVERITY_WARNING,
                title=(
                    f"VOMS observed on {days_observed} of {days_in_period} "
                    f"period days: maximum may be understated"
                ),
                description=(
                    f"Only {days_observed} of the {days_in_period} days in "
                    f"[{period_start.isoformat()}, {period_end.isoformat()}) "
                    f"have at least one in-trip vehicle position; VOMS is the "
                    f"maximum of the observed daily distinct-vehicle counts, "
                    f"so an unobserved day can only mean the true monthly "
                    f"maximum is AT LEAST the reported figure (an observation "
                    f"gap understates a maximum, never overstates it — the "
                    f"reason voms_v0 carries no blocking coverage machinery). "
                    f"The figure stands as the observed maximum; resolve or "
                    f"document the unobserved days before treating it as the "
                    f"month's VOMS. Unobserved days have no position records "
                    f"to cite."
                ),
                source_record_ids=(),
            ),
        )

    detail = VomsDetail(
        days_observed=days_observed,
        days_in_period=days_in_period,
        peak_day=None if peak_day is None else peak_day.isoformat(),
        per_day_counts=per_day_counts,
    )

    return CalcResult(
        value=value,
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION,
        input_record_ids=input_ids,
        blocking_issues=(),
        warnings=warnings,
        infos=(),
        detail=detail,
    )
