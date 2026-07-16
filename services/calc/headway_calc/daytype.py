"""daytype_v0 — day-type service calendar + day-type figures (handoff 0020).

Regulatory basis (2026 NTD Policy Manual, Full Reporting, printed pp.
154–156 — quotes extracted from the PDF 2026-07-15, never from memory; see
REGULATORY_TRACKER.md, "Verified — Days Operated and day-type schedules"):

- **Per-schedule Days Operated (p. 155):** "Within each of these categories,
  Full Reporters must report the total number of days operated for the
  weekday schedule, Saturday schedule, and Sunday schedule service. …
  An agency must report the number of days they operated during each
  schedule."
- **Holiday rule (p. 156):** "Transit agencies must report holiday service
  under the day that most closely reflects the service. For example, if an
  agency operates the Sunday schedule on Christmas Day, they must indicate
  that this is an additional day of Sunday service (regardless of the day on
  which the holiday falls)." — which schedule a holiday "most closely
  reflects" is the AGENCY'S declaration, recorded as an audited
  app.service_day_overrides row (migration 0031), never inferred here.
- **Partial-day rule (p. 156):** "A partial day operated counts as a day
  operated." — one observed in-trip position suffices to count a date.
- **Average schedule types (p. 154):** "… their Average Weekday Schedule,
  Average Saturday Schedule (if applicable), Average Sunday Schedule (if
  applicable), and Annual Total." — the three-schedule vocabulary
  (types.DAY_TYPES).

Three facilities, all pure/deterministic/stdlib-only:

1. **daytype_v0 0.1.0 classification** (``classify_days``): each date of a
   half-open period → weekday/saturday/sunday schedule day + atypical flag.
   Override rows govern where declared; otherwise day-of-week. Documented
   v0 divergences (tracker row daytype_v0): canonical carries no GTFS
   calendar/calendar_dates (inspected — migrations 0001–0030 create none),
   so day-of-week + declared overrides is the honest basis; and a "day" is
   the UTC calendar date (the voms_v0 convention), not an agency service
   day. The classification itself is never persisted — its name + version
   ride the consuming figures' detail JSONB (the passages-derivation
   precedent).

2. **daytype_days_operated_v0 0.1.0** (``compute_days_operated``): per day
   type, the COUNT of dates with at least one operated trip observed
   (positions with a trip assignment — the standing revenue-service proxy).
   BLOCKING-FREE (the voms_v0 argument: missing telemetry can only lower an
   observation-derived count, never inflate it); unobserved dates raise ONE
   warning 'daytype_days_unobserved' per day type (an observed LOWER BOUND,
   stated). Lineage: the earliest in-trip position record of each counted
   date — the record evidencing service that day.

3. **daytype_upt_avg_v0 0.1.0** (``compute_daytype_upt_avg``): per day type
   and split (typical always; atypical only where the agency declared
   atypical days), the mean of PER-DAY upt_v0 figures over the split's
   operated days — each day computed by the UNCHANGED headway_calc.upt
   .compute_upt (0.2.0) over that UTC date's events and operated trips
   (per-day input selection, the mode-scoping precedent; the p. 146
   missing-trip rule, p. 151 validations and simulated-source rule all
   apply PER DAY). REFUSAL DISCIPLINE IS INHERITED (binding, handoff 0020):
   a split whose ANY contributing day refuses, refuses whole — one summary
   blocking finding naming the refused dates PLUS the per-day blocking
   findings propagated date-prefixed (the same receipts); zero operated
   days refuses ('daytype_no_operated_days' — an average over nothing is
   never invented, and 0 is never a stand-in). The typical average EXCLUDES
   atypical days (a documented Headway convention pending per-form
   verification — flagged in the tracker row); an unflagged period is
   all-typical and the detail STATES it (atypical_flags_declared: false).

Statistician attestations (handoff 0019 machinery): each per-day upt_v0
computation accepts the attestations applicable to THIS result's scope over
THAT day's [d, d+1) period — the runner binds
headway_calc.attestation.applicable_attestations, so an attestation whose
scope_pattern matches (e.g. 'daytype:*' or 'mode:bus:daytype:*') and whose
declared range covers the day governs exactly like any upt_v0 run.

Persistence scopes (computed.metric_values.scope — the handoff-0001 TEXT
column, no migration): 'daytype:<type>' (+ ':atypical' for the atypical
split), and 'mode:<mode>:daytype:<type>' on the per-mode path. Metrics:
'days_operated' (unit 'days') and 'upt_avg' (unit
'unlinked_passenger_trips_per_day') — see headway_calc.persist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Callable, Iterable

from headway_calc.mode import (
    partition_events_by_mode,
    partition_positions_by_mode,
)
from headway_calc.types import (
    DAY_TYPE_SATURDAY,
    DAY_TYPE_SUNDAY,
    DAY_TYPE_WEEKDAY,
    DAY_TYPES,
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    CalcResult,
    DaysOperatedDetail,
    DaytypeUptAvgDetail,
    Finding,
    PassengerEvent,
    ServiceDayOverride,
    VehiclePosition,
)
from headway_calc.upt import (
    IMBALANCE_THRESHOLD,
    MISSING_TRIP_THRESHOLD,
    compute_upt,
)

#: The classification identity (recorded in every consuming detail; never a
#: computed.metric_values row of its own — the passages-derivation
#: precedent).
DAYTYPE_NAME = "daytype_v0"
DAYTYPE_VERSION = "0.1.0"

DAYS_OPERATED_CALC_NAME = "daytype_days_operated_v0"
DAYS_OPERATED_CALC_VERSION = "0.1.0"
DAYS_OPERATED_UNIT = "days"

UPT_AVG_CALC_NAME = "daytype_upt_avg_v0"
UPT_AVG_CALC_VERSION = "0.1.0"
UPT_AVG_UNIT = "unlinked_passenger_trips_per_day"

SPLIT_TYPICAL = "typical"
SPLIT_ATYPICAL = "atypical"

#: The reported average's quantum: 0.01, ROUND_HALF_EVEN — a documented
#: engineering convention (the manual prescribes no rounding rule for
#: schedule-type averages), applied ONCE to the exact sum/count fraction.
_AVG_QUANTUM = Decimal("0.01")

#: How many refused dates the summary blocking finding names verbatim
#: (the full count is always stated — the upt_v0 missing-trips precedent).
_REFUSED_DATES_NAMED = 20

#: The envelope source of REAL TIDES feeds (mirrors headway_calc.upt).
_REAL_SOURCE = "tides"

#: How many simulated-source records the aggregated info cites before
#: truncating (the mode-dimension precedent; full counts always stated).
_SIMULATED_RECORDS_CITED = 100


def scope_for_daytype(
    day_type: str,
    split: str = SPLIT_TYPICAL,
    mode_bucket: str | None = None,
) -> str:
    """The computed.metric_values.scope for one day-type result.

    'daytype:<type>' for the typical split (the default figure),
    'daytype:<type>:atypical' for the declared-atypical split, prefixed
    'mode:<mode>:' on the per-mode path.
    """
    base = f"daytype:{day_type}"
    if mode_bucket is not None:
        base = f"mode:{mode_bucket}:{base}"
    if split == SPLIT_ATYPICAL:
        base = f"{base}:atypical"
    return base


@dataclass(frozen=True)
class DayClass:
    """One date's daytype_v0 classification: schedule type + atypical flag
    + the override that produced it (None = plain day-of-week)."""

    day_type: str
    atypical: bool
    override: ServiceDayOverride | None


def _refuse_bad_period(period_start: date, period_end: date) -> None:
    if period_start >= period_end:
        raise ValueError(
            f"Refusing empty/inverted period: period_start="
            f"{period_start.isoformat()} must be strictly before period_end="
            f"{period_end.isoformat()} (half-open [start, end))."
        )


def _day_of_week_type(d: date) -> str:
    """Mon(0)–Fri(4) → weekday, Sat(5) → saturday, Sun(6) → sunday."""
    dow = d.weekday()
    if dow == 5:
        return DAY_TYPE_SATURDAY
    if dow == 6:
        return DAY_TYPE_SUNDAY
    return DAY_TYPE_WEEKDAY


def classify_days(
    period_start: date,
    period_end: date,
    overrides: Iterable[ServiceDayOverride],
) -> dict[date, DayClass]:
    """daytype_v0 0.1.0: classify every date of the half-open period.

    An override row for a date inside the period governs that date
    (assigned_day_type reassigns the schedule type — p. 156 holiday rule;
    atypical flags the day); every other date is its day-of-week type,
    typical. Overrides dated outside the period are ignored here (the
    reader already scopes its SELECT to the period); duplicate override
    dates are refused loudly — two declarations for one date cannot both
    govern. Deterministic: dates ascending, dict insertion order.
    """
    _refuse_bad_period(period_start, period_end)
    by_date: dict[date, ServiceDayOverride] = {}
    for override in overrides:
        if override.service_date in by_date:
            raise ValueError(
                f"Two service-day overrides declared for "
                f"{override.service_date.isoformat()} — refusing to guess "
                f"which governs (app.service_day_overrides keys on the date, "
                f"so this can only come from a broken fake/caller)."
            )
        by_date[override.service_date] = override

    classification: dict[date, DayClass] = {}
    d = period_start
    while d < period_end:
        override = by_date.get(d)
        if override is None:
            classification[d] = DayClass(_day_of_week_type(d), False, None)
        else:
            classification[d] = DayClass(
                override.assigned_day_type or _day_of_week_type(d),
                override.atypical,
                override,
            )
        d += timedelta(days=1)
    return classification


def _utc_date(ts) -> date:
    """The UTC calendar date of a timestamp (the voms_v0 day convention —
    documented divergence: not an agency service day)."""
    return ts.astimezone(timezone.utc).date()


def _operated_days(
    positions: Iterable[VehiclePosition],
) -> tuple[dict[date, list[str]], dict[date, str]]:
    """Per UTC date: the sorted distinct operated trip_ids, and the earliest
    in-trip position record (the record evidencing service that day —
    daytype_days_operated_v0's per-day lineage anchor)."""
    trips_by_day: dict[date, set[str]] = {}
    first_record_by_day: dict[date, tuple] = {}
    for pos in positions:
        if pos.trip_id is None:
            continue  # revenue-service proxy: unassigned positions not counted
        day = _utc_date(pos.time)
        trips_by_day.setdefault(day, set()).add(pos.trip_id)
        key = (pos.time, pos.vehicle_id, pos.source_record_id)
        current = first_record_by_day.get(day)
        if current is None or key < current:
            first_record_by_day[day] = key
    return (
        {day: sorted(trips) for day, trips in trips_by_day.items()},
        {day: key[2] for day, key in first_record_by_day.items()},
    )


def _overrides_applied(
    classification: dict[date, DayClass], dates: Iterable[date]
) -> tuple[dict, ...]:
    """Provenance snapshots of the overrides governing the given dates, in
    date order — the declarations ride the figure permanently."""
    snapshots = []
    for d in sorted(dates):
        cls = classification.get(d)
        if cls is not None and cls.override is not None:
            snapshots.append(cls.override.to_provenance_dict())
    return tuple(snapshots)


def compute_days_operated(
    positions: Iterable[VehiclePosition],
    period_start: date,
    period_end: date,
    overrides: Iterable[ServiceDayOverride] = (),
) -> dict[str, CalcResult]:
    """daytype_days_operated_v0 0.1.0 — one CalcResult per day type.

    Value = the count of the day type's dates (daytype_v0 classification
    over the half-open period) with at least one operated trip observed in
    the positions (p. 155 per-schedule Days Operated; p. 156 partial-day
    rule: one in-trip observation counts the date). Counts typical AND
    atypical operated days (p. 155 counts days "on which service was
    actually operated"); the split is in the detail. BLOCKING-FREE — an
    unobserved date can only understate the count; each day type with
    unobserved dates carries ONE warning 'daytype_days_unobserved' naming
    them (observed lower bound, stated, never guessed). Zero observed dates
    yield the honest observed count 0 with that warning — never a guess.

    Lineage: the earliest in-trip position record of each counted date.
    Returns {day_type: CalcResult} for all three day types, keys in
    DAY_TYPES order.
    """
    positions = list(positions)
    classification = classify_days(period_start, period_end, overrides)
    trips_by_day, first_record_by_day = _operated_days(positions)
    atypical_declared = any(c.atypical for c in classification.values())

    results: dict[str, CalcResult] = {}
    for day_type in DAY_TYPES:
        dates_of_type = sorted(
            d for d, c in classification.items() if c.day_type == day_type
        )
        operated = [d for d in dates_of_type if d in trips_by_day]
        unobserved = [d for d in dates_of_type if d not in trips_by_day]
        operated_typical = [
            d for d in operated if not classification[d].atypical
        ]
        operated_atypical = [d for d in operated if classification[d].atypical]
        atypical_dates = [
            d for d in dates_of_type if classification[d].atypical
        ]

        warnings: tuple[Finding, ...] = ()
        if unobserved:
            warnings = (
                Finding(
                    issue_type="daytype_days_unobserved",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Days Operated ({day_type} schedule) observed on "
                        f"{len(operated)} of {len(dates_of_type)} {day_type} "
                        f"dates: count is an observed lower bound"
                    ),
                    description=(
                        f"{len(unobserved)} of the {len(dates_of_type)} "
                        f"{day_type}-schedule dates in "
                        f"[{period_start.isoformat()}, "
                        f"{period_end.isoformat()}) have no in-trip vehicle "
                        f"position: "
                        + ", ".join(d.isoformat() for d in unobserved)
                        + ". The 2026 NTD Policy Manual p. 156 counts a day "
                        "operated when service was AVAILABLE even if no "
                        "rides were provided (fixed-route/DR); telemetry "
                        "presence is this calc's documented v0 proxy for "
                        "operation, so an available-but-untelemetered day "
                        "is missed here. The reported count is therefore an "
                        "observed LOWER BOUND — resolve or document the "
                        "unobserved dates before treating it as the "
                        "period's Days Operated. Unobserved dates have no "
                        "position records to cite."
                    ),
                    source_record_ids=(),
                ),
            )

        detail = DaysOperatedDetail(
            day_type=day_type,
            daytype_version=DAYTYPE_VERSION,
            days_in_period_of_type=len(dates_of_type),
            operated_dates=tuple(d.isoformat() for d in operated),
            operated_typical_dates=tuple(
                d.isoformat() for d in operated_typical
            ),
            operated_atypical_dates=tuple(
                d.isoformat() for d in operated_atypical
            ),
            unobserved_dates=tuple(d.isoformat() for d in unobserved),
            atypical_dates=tuple(d.isoformat() for d in atypical_dates),
            overrides_applied=_overrides_applied(classification, dates_of_type),
            atypical_flags_declared=atypical_declared,
        )
        results[day_type] = CalcResult(
            value=Decimal(len(operated)),
            unit=DAYS_OPERATED_UNIT,
            calc_name=DAYS_OPERATED_CALC_NAME,
            calc_version=DAYS_OPERATED_CALC_VERSION,
            input_record_ids=tuple(
                first_record_by_day[d] for d in operated
            ),
            blocking_issues=(),
            warnings=warnings,
            infos=(),
            detail=detail,
        )
    return results


def _date_prefixed(finding: Finding, day: date) -> Finding:
    """A per-day upt_v0 finding re-raised at the day-type level: same
    issue_type/severity/records, title and description carrying the service
    day — the day-level receipt travels with the aggregate."""
    return Finding(
        issue_type=finding.issue_type,
        severity=finding.severity,
        title=f"[{day.isoformat()}] {finding.title}",
        description=(
            f"On service day {day.isoformat()} (UTC date — the documented "
            f"daytype_v0 day convention): {finding.description}"
        ),
        source_record_ids=finding.source_record_ids,
    )


def compute_daytype_upt_avg(
    events: Iterable[PassengerEvent],
    positions: Iterable[VehiclePosition],
    period_start: date,
    period_end: date,
    overrides: Iterable[ServiceDayOverride] = (),
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    attestations_for_day: Callable[[str, date], tuple] | None = None,
    mode_bucket: str | None = None,
) -> dict[tuple[str, str], CalcResult]:
    """daytype_upt_avg_v0 0.1.0 — average UPT per day type and split.

    Keys: (day_type, split). The typical split is always present for all
    three day types; the atypical split appears only for day types with
    agency-declared atypical days in the period (unflagged period = all
    typical, STATED via detail.atypical_flags_declared).

    Per operated day d of the split: the UNCHANGED upt_v0 0.2.0
    ``compute_upt`` over the events whose event_timestamp falls on UTC date
    d and the operated trips observed that date (per-day input selection).
    ``attestations_for_day`` (handoff 0019) — a pure selector called with
    (scope, day) where scope is THIS result's persistence scope
    (scope_for_daytype(day_type, split, mode_bucket)), returning the
    statistician attestations applicable to that scope over [d, d+1);
    default None = no attestation context. ``mode_bucket`` names the mode
    on the per-mode path so the scope handed to the selector is the one the
    figure persists under — an attestation never leaks across scopes.

    Outcomes per split:

    - zero operated days → blocking 'daytype_no_operated_days', value None
      (an average over nothing is never invented; 0 is never a stand-in);
    - any contributing day refused (p. 146 missing share above threshold,
      no attestation) → the split refuses WHOLE: one summary blocking
      'daytype_average_over_refused_days' naming the refused dates plus
      every per-day blocking finding propagated date-prefixed — the same
      receipts, inherited (binding, handoff 0020);
    - otherwise value = sum(per-day UPT) / days, quantized 0.01
      ROUND_HALF_EVEN once from the exact fraction.

    Per-day warnings/infos propagate date-prefixed; simulated sources
    aggregate to ONE info per split (source counts always in detail's
    source_mix). Lineage: the union of the per-day counted-boarding
    records, in day order.
    """
    missing_trip_threshold = Decimal(str(missing_trip_threshold))
    imbalance_threshold = Decimal(str(imbalance_threshold))
    events = list(events)
    positions = list(positions)
    classification = classify_days(period_start, period_end, overrides)
    trips_by_day, _ = _operated_days(positions)
    atypical_declared = any(c.atypical for c in classification.values())

    events_by_day: dict[date, list[PassengerEvent]] = {}
    for event in events:
        events_by_day.setdefault(_utc_date(event.event_timestamp), []).append(
            event
        )

    results: dict[tuple[str, str], CalcResult] = {}
    for day_type in DAY_TYPES:
        dates_of_type = sorted(
            d for d, c in classification.items() if c.day_type == day_type
        )
        atypical_dates = [d for d in dates_of_type if classification[d].atypical]
        splits: list[str] = [SPLIT_TYPICAL]
        if atypical_dates:
            splits.append(SPLIT_ATYPICAL)

        for split in splits:
            if split == SPLIT_TYPICAL:
                split_dates = [
                    d for d in dates_of_type if not classification[d].atypical
                ]
            else:
                split_dates = list(atypical_dates)
            operated = [d for d in split_dates if d in trips_by_day]

            overrides_snapshot = _overrides_applied(
                classification, dates_of_type
            )
            base_detail = dict(
                day_type=day_type,
                split=split,
                daytype_version=DAYTYPE_VERSION,
                days_in_period_of_type=len(dates_of_type),
                days_operated=len(operated),
                dates=tuple(d.isoformat() for d in operated),
                missing_trip_threshold=missing_trip_threshold,
                imbalance_threshold=imbalance_threshold,
                overrides_applied=overrides_snapshot,
                atypical_dates=tuple(d.isoformat() for d in atypical_dates),
                atypical_flags_declared=atypical_declared,
            )

            if not operated:
                detail = DaytypeUptAvgDetail(
                    per_day=(),
                    sum_upt=None,
                    average=None,
                    source_mix={},
                    **base_detail,
                )
                results[(day_type, split)] = CalcResult(
                    value=None,
                    unit=UPT_AVG_UNIT,
                    calc_name=UPT_AVG_CALC_NAME,
                    calc_version=UPT_AVG_CALC_VERSION,
                    input_record_ids=(),
                    blocking_issues=(
                        Finding(
                            issue_type="daytype_no_operated_days",
                            severity=SEVERITY_BLOCKING,
                            title=(
                                f"No operated {day_type} days ({split}) in "
                                f"the period: no average exists"
                            ),
                            description=(
                                f"None of the {len(split_dates)} "
                                f"{split} {day_type}-schedule dates in "
                                f"[{period_start.isoformat()}, "
                                f"{period_end.isoformat()}) has an operated "
                                f"trip observed in "
                                f"canonical.vehicle_positions. An average "
                                f"over zero days does not exist, and 0 is "
                                f"never a stand-in for it — the figure is "
                                f"refused, never invented. If service ran "
                                f"but no telemetry landed, resolve the "
                                f"ingestion gap; if this schedule genuinely "
                                f"did not operate, the Days Operated figure "
                                f"(metric 'days_operated') states that "
                                f"honestly."
                            ),
                            source_record_ids=(),
                        ),
                    ),
                    warnings=(),
                    infos=(),
                    detail=detail,
                )
                continue

            per_day_dicts: list[dict] = []
            refused_days: list[date] = []
            blocking: list[Finding] = []
            warnings: list[Finding] = []
            infos: list[Finding] = []
            source_mix: dict[str, int] = {}
            simulated_record_ids: dict[str, None] = {}
            input_ids: dict[str, None] = {}
            exact_sum = Decimal(0)
            result_scope = scope_for_daytype(day_type, split, mode_bucket)

            for d in operated:
                day_result = compute_upt(
                    events_by_day.get(d, []),
                    trips_by_day.get(d, []),
                    missing_trip_threshold=missing_trip_threshold,
                    imbalance_threshold=imbalance_threshold,
                    attestations=(
                        ()
                        if attestations_for_day is None
                        else attestations_for_day(result_scope, d)
                    ),
                )
                day_detail = day_result.detail
                per_day = {
                    "date": d.isoformat(),
                    "value": (
                        None if day_result.value is None else str(day_result.value)
                    ),
                    "blocked": bool(day_result.blocking_issues),
                    "boardings_counted": day_detail.total_boardings_counted,
                    "operated_trips": day_detail.operated_trips,
                    "missing_trips": day_detail.missing_trips,
                    "factor_applied": (
                        None
                        if day_detail.factor_applied is None
                        else str(day_detail.factor_applied)
                    ),
                }
                if day_detail.attestation is not None:
                    per_day["attestation"] = dict(day_detail.attestation)
                per_day_dicts.append(per_day)

                for source, count in day_detail.source_mix.items():
                    source_mix[source] = source_mix.get(source, 0) + count

                if day_result.blocking_issues:
                    refused_days.append(d)
                    blocking.extend(
                        _date_prefixed(f, d) for f in day_result.blocking_issues
                    )
                else:
                    exact_sum += day_result.value
                    for record_id in day_result.input_record_ids:
                        input_ids.setdefault(record_id, None)

                warnings.extend(
                    _date_prefixed(f, d) for f in day_result.warnings
                )
                for info in day_result.infos:
                    if info.issue_type == "simulated_source_data":
                        # Aggregated below into ONE split-level info; the
                        # per-day counts live in the aggregated source_mix.
                        for record_id in info.source_record_ids:
                            if len(simulated_record_ids) < _SIMULATED_RECORDS_CITED:
                                simulated_record_ids.setdefault(record_id, None)
                    else:
                        infos.append(_date_prefixed(info, d))

            simulated_sources = sorted(
                s for s in source_mix if s != _REAL_SOURCE
            )
            if simulated_sources:
                simulated_event_count = sum(
                    source_mix[s] for s in simulated_sources
                )
                infos.append(
                    Finding(
                        issue_type="simulated_source_data",
                        severity=SEVERITY_INFO,
                        title=(
                            f"{day_type} ({split}) day-type average consumed "
                            f"non-'tides' source(s): "
                            f"{', '.join(simulated_sources)}"
                        ),
                        description=(
                            f"{simulated_event_count} of "
                            f"{sum(source_mix.values())} passenger events "
                            f"across the {len(operated)} contributing "
                            f"{day_type} days carry a source other than "
                            f"'tides': "
                            + ", ".join(
                                f"{s} ({source_mix[s]} events)"
                                for s in simulated_sources
                            )
                            + ". Per the handoff-0005 simulated-data rule "
                            "this figure is NOT certifiable or reportable; "
                            "the aggregated source mix is in the metric "
                            "value's detail. Citations list the first "
                            f"{len(simulated_record_ids)} simulated records."
                        ),
                        source_record_ids=tuple(simulated_record_ids),
                    )
                )

            value: Decimal | None
            sum_str: str | None
            avg_str: str | None
            if refused_days:
                named = ", ".join(
                    d.isoformat() for d in refused_days[:_REFUSED_DATES_NAMED]
                )
                if len(refused_days) > _REFUSED_DATES_NAMED:
                    named += (
                        f", ... ({len(refused_days) - _REFUSED_DATES_NAMED} "
                        f"more)"
                    )
                blocking.insert(
                    0,
                    Finding(
                        issue_type="daytype_average_over_refused_days",
                        severity=SEVERITY_BLOCKING,
                        title=(
                            f"Average {day_type} UPT ({split}) refused: "
                            f"{len(refused_days)} of {len(operated)} "
                            f"contributing days refused their UPT figure"
                        ),
                        description=(
                            f"The {day_type} ({split}) day-type average "
                            f"inherits upt_v0's refusal discipline (handoff "
                            f"0020, binding): {len(refused_days)} of the "
                            f"{len(operated)} operated {day_type} days in "
                            f"[{period_start.isoformat()}, "
                            f"{period_end.isoformat()}) refused a UPT "
                            f"figure — {named} — so no average over them "
                            f"exists. Each day's refusal is propagated "
                            f"alongside this finding with its own receipts "
                            f"(the p. 146 missing-data rule: above the "
                            f"threshold a qualified statistician must "
                            f"approve the factoring — a human workflow, "
                            f"never guessed). Resolve the day-level "
                            f"refusals (or record an applicable "
                            f"statistician attestation) and re-run."
                        ),
                        source_record_ids=(),
                    ),
                )
                value = None
                sum_str = None
                avg_str = None
            else:
                exact_avg = exact_sum / Decimal(len(operated))
                value = exact_avg.quantize(
                    _AVG_QUANTUM, rounding=ROUND_HALF_EVEN
                )
                sum_str = str(exact_sum)
                avg_str = str(value)

            detail = DaytypeUptAvgDetail(
                per_day=tuple(per_day_dicts),
                sum_upt=sum_str,
                average=avg_str,
                source_mix=source_mix,
                **base_detail,
            )
            results[(day_type, split)] = CalcResult(
                value=value,
                unit=UPT_AVG_UNIT,
                calc_name=UPT_AVG_CALC_NAME,
                calc_version=UPT_AVG_CALC_VERSION,
                input_record_ids=tuple(input_ids),
                blocking_issues=tuple(blocking),
                warnings=tuple(warnings),
                infos=tuple(infos),
                detail=detail,
            )
    return results


def compute_daytype_upt_avg_by_mode(
    events: Iterable[PassengerEvent],
    positions: Iterable[VehiclePosition],
    period_start: date,
    period_end: date,
    overrides: Iterable[ServiceDayOverride] = (),
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    attestations_for_day: Callable[[str, date], tuple] | None = None,
) -> dict[tuple[str, str, str], CalcResult]:
    """daytype_upt_avg_v0 per mode bucket (the handoff-0009 mode-scoping
    precedent: per-mode subsetting is INPUT SELECTION, not a semantics
    change — the calc version does not bump).

    Keys: (mode_bucket, day_type, split). Buckets are the union of the
    event buckets and the position buckets (a mode operating with zero
    events still gets results — its days refuse per day under the p. 146
    rule, the honest outcome); NULL modes bucket as 'unknown', never
    dropped. ``attestations_for_day`` receives (scope, day) exactly as in
    compute_daytype_upt_avg — the scope already carries the mode prefix
    ('mode:<mode>:daytype:<type>'), so an attestation never leaks across
    mode buckets.
    """
    positions = list(positions)
    event_buckets = partition_events_by_mode(events)
    position_buckets = partition_positions_by_mode(positions)
    results: dict[tuple[str, str, str], CalcResult] = {}
    for bucket in sorted(set(event_buckets) | set(position_buckets)):
        bucket_results = compute_daytype_upt_avg(
            event_buckets.get(bucket, []),
            position_buckets.get(bucket, []),
            period_start,
            period_end,
            overrides,
            missing_trip_threshold=missing_trip_threshold,
            imbalance_threshold=imbalance_threshold,
            attestations_for_day=attestations_for_day,
            mode_bucket=bucket,
        )
        for (day_type, split), result in bucket_results.items():
            results[(bucket, day_type, split)] = result
    return results
