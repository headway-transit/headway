"""upt_v0 — Unlinked Passenger Trips from TIDES passenger events (handoff 0005).

Regulatory basis (2026 NTD Policy Manual, Full Reporting — quotes verified
against docs/reference/ 2026-07-10; see REGULATORY_TRACKER.md):

- **UPT definition** (p. 143): "Unlinked Passenger Trips (UPT) are the number
  of boardings on public transportation vehicles during the fiscal year.
  Transit agencies must count passengers each time they board vehicles, no
  matter how many vehicles they use to travel from their origin to their
  destination. If a transit vehicle changes routes while passengers are
  onboard (interlining), transit agencies should not recount the passengers.
  Employees or contractors on transit agency business are not passengers."
- **Missing-trip rule** (p. 146): "If these vehicle trips are 2 percent or
  less of the total, transit agencies should factor up the data to account
  for the missing trips. However, if the vehicle trips with missing data
  exceed 2 percent of total trips, agencies must have a qualified
  statistician approve the factoring method used to account for the missing
  percentage." The 0.02 default here is therefore a REAL FTA threshold, not
  an engineering placeholder.
- **APC validation examples** (p. 151): "agencies may flag trips or blocks
  where the difference between boardings and alightings is greater than 10
  percent, or trips where the passenger load drops below zero."

Event vocabulary — verified TIDES enum (do NOT guess; handoff 0005 open
question resolved): the ``event_type`` values below were verified 2026-07-10
against the live TIDES spec,
https://github.com/TIDES-transit/TIDES ``spec/passenger_events.schema.json``
(main branch, repo HEAD 7ddaa7ab820eeca1cc7a681ba9ae79a72ba10af1; the schema
file's last change is commit d887d42ce081f3fb6155664a3c486101d62ec52b,
2023-12-11). The enum's passenger values are exactly ``"Passenger boarded"``
and ``"Passenger alighted"``; bike events ("Individual bike boarded"/
"... alighted") are NOT passengers under the p. 143 definition and are never
counted.

v0 scope (documented approximations, mirroring vrm_v0/vrh_v0):

- Trip assignment (``trip_id`` not None, from TIDES ``trip_id_performed``) is
  the revenue-service proxy: unassigned events are excluded from the counted
  figure (consistent with the position-derived calcs; no deadhead handling).
- The missing-trip factor-up is FLEET-WIDE, not per mode/type-of-service —
  the manual speaks of totals per mode/TOS; mode-awareness is a documented
  limitation (handoff 0005 open question, owner NTD role).
- APC certification (manual pp. 147-148) is an agency workflow, not calc
  logic; simulated-source data can never yield a certifiable figure and is
  flagged per the handoff-0005 simulated-data rule.

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input events.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable

from headway_calc.types import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    CalcResult,
    Finding,
    PassengerEvent,
    UptDetail,
)

CALC_NAME = "upt_v0"
CALC_VERSION = "0.1.0"
#: 'boardings' would be ambiguous against the counted base; the persisted unit
#: names the NTD measure itself.
UNIT = "unlinked_passenger_trips"

#: Verified TIDES event_type enum values (see module docstring for the
#: citation — verified 2026-07-10, never from memory).
BOARDING_EVENT_TYPE = "Passenger boarded"
ALIGHTING_EVENT_TYPE = "Passenger alighted"

#: p. 146 missing-trip threshold: "2 percent or less of the total" may be
#: factored up; above it "agencies must have a qualified statistician approve
#: the factoring method". A REAL FTA threshold (2026 NTD Policy Manual),
#: explicit input, recorded in the run's provenance.
MISSING_TRIP_THRESHOLD: Decimal = Decimal("0.02")

#: p. 151 APC validation example: "difference between boardings and
#: alightings is greater than 10 percent". Explicit input, recorded in the
#: run's provenance.
IMBALANCE_THRESHOLD: Decimal = Decimal("0.10")

#: Quantum for the REPORTED missing share (0.0001, ROUND_HALF_EVEN — the same
#: engineering convention as the coverage ratios; the threshold COMPARISON is
#: exact, never the quantized value).
_SHARE_QUANTUM = Decimal("0.0001")

#: Quantum for the REPORTED factor (provenance only; the reported UPT value
#: is computed from the exact fraction, then quantized to whole boardings).
_FACTOR_QUANTUM = Decimal("0.000001")

#: The reported UPT quantum: whole boardings (Decimal 1, ROUND_HALF_EVEN). A
#: boarding count is integral by nature; the factor-up may produce a
#: fraction, which is rounded half-even to the nearest whole boarding — a
#: documented engineering rounding convention (the p. 146 factoring method
#: itself prescribes no rounding rule).
_UPT_QUANTUM = Decimal("1")

#: How many missing trip_ids a blocking finding names verbatim before
#: truncating (the full count is always stated).
_MISSING_TRIPS_NAMED = 20

#: The envelope source of REAL TIDES feeds; anything else (e.g.
#: "tides_simulated") triggers the simulated-source info finding.
_REAL_SOURCE = "tides"


def _sorted_events(events: Iterable[PassengerEvent]) -> list[PassengerEvent]:
    """Canonical total order (matches the reader's ORDER BY): input order is
    irrelevant to the result."""
    return sorted(
        events,
        key=lambda e: (e.event_timestamp, e.passenger_event_id, e.source_record_id),
    )


def _stop_order_key(event: PassengerEvent) -> tuple:
    """p. 151 running-load order: trip_stop_sequence, then event_timestamp.

    A NULL trip_stop_sequence (nullable in canonical.passenger_events) sorts
    AFTER all numbered stops — a documented deterministic convention;
    passenger_event_id breaks remaining ties.
    """
    return (
        event.trip_stop_sequence is None,
        event.trip_stop_sequence if event.trip_stop_sequence is not None else 0,
        event.event_timestamp,
        event.passenger_event_id,
    )


def _null_count_warning(event: PassengerEvent) -> Finding:
    role = "boarding" if event.event_type == BOARDING_EVENT_TYPE else "alighting"
    return Finding(
        issue_type="apc_null_count",
        severity=SEVERITY_WARNING,
        title=(
            f"NULL event_count on {role} event {event.passenger_event_id} "
            f"(trip {event.trip_id})"
        ),
        description=(
            f"Passenger event {event.passenger_event_id!r} (trip_id="
            f"{event.trip_id!r}, vehicle_id={event.vehicle_id!r}, "
            f"event_type={event.event_type!r}, "
            f"{event.event_timestamp.isoformat()}) carries a NULL event_count. "
            f"The TIDES schema documents a default of 1, but the handoff-0005 "
            f"contract preserves NULL as NULL — the calculation NEVER coalesces "
            f"a missing count to a guessed number: this event contributed 0 to "
            f"the {'counted UPT figure' if role == 'boarding' else 'p. 151 validation arithmetic'} "
            f"and is cited here instead of appearing in lineage."
        ),
        source_record_ids=(event.source_record_id,),
    )


def compute_upt(
    events: Iterable[PassengerEvent],
    operated_trip_ids: Iterable[str],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
) -> CalcResult:
    """Compute upt_v0 (version 0.1.0) — Unlinked Passenger Trips.

    Base count (p. 143: "the number of boardings on public transportation
    vehicles"): the sum of ``event_count`` over events whose ``event_type``
    is the verified TIDES boarding value (``"Passenger boarded"``) AND whose
    ``trip_id`` is not None — trip assignment is the v0 revenue-service
    proxy, consistent with vrm_v0/vrh_v0 (documented approximation). An
    event with ``event_count`` None contributes 0 and one warning finding
    ``'apc_null_count'`` citing the record — never a silently guessed number
    (NULL-count boarding/alighting events are cited by their warnings, not
    by lineage).

    Validations (p. 151, quoted verbatim: "agencies may flag trips or blocks
    where the difference between boardings and alightings is greater than 10
    percent, or trips where the passenger load drops below zero"):

    - per trip, |boardings - alightings| > ``imbalance_threshold`` x
      boardings -> one warning ``'apc_count_imbalance'`` citing the trip's
      boarding/alighting records (exact comparison, no quantized ratio);
    - per trip, the running load (events ordered by trip_stop_sequence then
      event_timestamp; boardings add, alightings subtract) dropping below
      zero -> one warning ``'apc_negative_load'`` citing the record at which
      the load first went negative.

    Missing-trip rule (p. 146, quoted verbatim: "If these vehicle trips are 2
    percent or less of the total, transit agencies should factor up the data
    to account for the missing trips. However, if the vehicle trips with
    missing data exceed 2 percent of total trips, agencies must have a
    qualified statistician approve the factoring method used to account for
    the missing percentage."): operated trips with ZERO passenger events are
    missing; share = missing/operated (exact comparison against
    ``missing_trip_threshold``, default 0.02 — a REAL FTA threshold).

    - share <= threshold: the value is factored up DETERMINISTICALLY per the
      FTA-sanctioned method — UPT_reported = counted x operated/(operated -
      missing), computed from the exact fraction and quantized to whole
      boardings (Decimal 1, ROUND_HALF_EVEN — documented engineering
      rounding; the manual prescribes none). The factor and all inputs are
      recorded in the detail.
    - share > threshold: ONE blocking finding
      ``'apc_missing_trips_above_fta_threshold'`` and value None — the
      statistician-approved factoring is a human workflow, never guessed.
    - zero operated trips (degenerate period): nothing operated, nothing
      missing — share 0, factor 1, the counted figure stands.

    Simulated sources (handoff 0005 binding rule): any event whose
    ``source`` != "tides" yields ONE info finding ``'simulated_source_data'``
    listing the sources; ``source_mix`` (event counts per source) is ALWAYS
    in the detail.

    ``input_record_ids`` are the distinct source_record_ids of counted
    boarding events (lineage); NULL-count events' records are cited by their
    ``apc_null_count`` warnings instead. Returns a CalcResult whose detail is
    an UptDetail (present on blocked results too — the evidence always
    travels).
    """
    missing_trip_threshold = Decimal(str(missing_trip_threshold))
    imbalance_threshold = Decimal(str(imbalance_threshold))
    ordered = _sorted_events(events)
    operated = sorted(set(operated_trip_ids))

    warnings: list[Finding] = []
    infos: list[Finding] = []

    # --- base count (p. 143) + lineage + null-count warnings ----------------
    counted_boardings = 0
    input_ids: dict[str, None] = {}
    source_mix: dict[str, int] = {}
    trips_with_any_event: set[str] = set()
    null_count_warnings: list[Finding] = []
    for event in ordered:
        source_mix[event.source] = source_mix.get(event.source, 0) + 1
        if event.trip_id is not None:
            trips_with_any_event.add(event.trip_id)
        if event.trip_id is None:
            continue  # revenue-service proxy: unassigned events not counted
        if event.event_type == BOARDING_EVENT_TYPE:
            if event.event_count is None:
                null_count_warnings.append(_null_count_warning(event))
            else:
                counted_boardings += event.event_count
                input_ids.setdefault(event.source_record_id, None)
        elif event.event_type == ALIGHTING_EVENT_TYPE:
            # Alighting counts feed the p. 151 validations below; a NULL
            # there is treated as 0 in the same never-guess spirit and is
            # warned identically.
            if event.event_count is None:
                null_count_warnings.append(_null_count_warning(event))

    # --- p. 151 validations, per trip ---------------------------------------
    by_trip: dict[str, list[PassengerEvent]] = {}
    for event in ordered:
        if event.trip_id is None:
            continue
        if event.event_type in (BOARDING_EVENT_TYPE, ALIGHTING_EVENT_TYPE):
            by_trip.setdefault(event.trip_id, []).append(event)

    imbalance_warnings: list[Finding] = []
    negative_load_warnings: list[Finding] = []
    for trip_id in sorted(by_trip):
        trip_events = by_trip[trip_id]
        boardings = sum(
            e.event_count or 0
            for e in trip_events
            if e.event_type == BOARDING_EVENT_TYPE
        )
        alightings = sum(
            e.event_count or 0
            for e in trip_events
            if e.event_type == ALIGHTING_EVENT_TYPE
        )
        trip_record_ids: dict[str, None] = {}
        for e in trip_events:
            trip_record_ids.setdefault(e.source_record_id, None)

        # "difference between boardings and alightings is greater than 10
        # percent" (of boardings) — exact integer/Decimal comparison.
        if Decimal(abs(boardings - alightings)) > imbalance_threshold * Decimal(
            boardings
        ):
            imbalance_warnings.append(
                Finding(
                    issue_type="apc_count_imbalance",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Boarding/alighting imbalance on trip {trip_id}: "
                        f"{boardings} boarded vs {alightings} alighted"
                    ),
                    description=(
                        f"Trip {trip_id!r} counted {boardings} boardings and "
                        f"{alightings} alightings: |{boardings} - {alightings}| = "
                        f"{abs(boardings - alightings)} exceeds "
                        f"{imbalance_threshold} x boardings. Flagged per the 2026 "
                        f"NTD Policy Manual p. 151 APC validation example "
                        f"('agencies may flag trips or blocks where the "
                        f"difference between boardings and alightings is greater "
                        f"than 10 percent'). The figure stands; the trip's counts "
                        f"are suspect and should be reviewed in the agency's APC "
                        f"validation workflow."
                    ),
                    source_record_ids=tuple(trip_record_ids),
                )
            )

        # "trips where the passenger load drops below zero" — running load in
        # stop-sequence order (then event time; NULL sequence sorts last).
        load = 0
        for e in sorted(trip_events, key=_stop_order_key):
            if e.event_type == BOARDING_EVENT_TYPE:
                load += e.event_count or 0
            else:
                load -= e.event_count or 0
            if load < 0:
                negative_load_warnings.append(
                    Finding(
                        issue_type="apc_negative_load",
                        severity=SEVERITY_WARNING,
                        title=(
                            f"Passenger load drops below zero on trip {trip_id} "
                            f"(load {load})"
                        ),
                        description=(
                            f"Running the boarding/alighting events of trip "
                            f"{trip_id!r} in stop-sequence order, the passenger "
                            f"load first drops below zero at event "
                            f"{e.passenger_event_id!r} (trip_stop_sequence="
                            f"{e.trip_stop_sequence!r}, "
                            f"{e.event_timestamp.isoformat()}): load {load}. "
                            f"Flagged per the 2026 NTD Policy Manual p. 151 APC "
                            f"validation example ('trips where the passenger "
                            f"load drops below zero'). The figure stands; the "
                            f"trip's counts are suspect and should be reviewed."
                        ),
                        source_record_ids=(e.source_record_id,),
                    )
                )
                break  # one finding per trip: the first drop is the evidence

    warnings.extend(null_count_warnings)
    warnings.extend(imbalance_warnings)
    warnings.extend(negative_load_warnings)

    # --- simulated-source rule (handoff 0005) --------------------------------
    simulated_sources = sorted(s for s in source_mix if s != _REAL_SOURCE)
    if simulated_sources:
        simulated_record_ids: dict[str, None] = {}
        for event in ordered:
            if event.source != _REAL_SOURCE:
                simulated_record_ids.setdefault(event.source_record_id, None)
        infos.append(
            Finding(
                issue_type="simulated_source_data",
                severity=SEVERITY_INFO,
                title=(
                    f"Passenger events include non-'tides' source(s): "
                    f"{', '.join(simulated_sources)}"
                ),
                description=(
                    f"{sum(source_mix[s] for s in simulated_sources)} of "
                    f"{len(ordered)} passenger events carry a source other than "
                    f"'tides': "
                    + ", ".join(f"{s} ({source_mix[s]} events)" for s in simulated_sources)
                    + ". Per the handoff-0005 simulated-data rule, simulator "
                    "output is permanently distinguishable in provenance and a "
                    "certifiable figure containing simulated records is a "
                    "contradiction the DQ trail must make visible: this figure "
                    "is NOT certifiable or reportable. The full source mix is "
                    "recorded in the metric value's detail."
                ),
                source_record_ids=tuple(simulated_record_ids),
            )
        )

    # --- missing-trip rule (p. 146) ------------------------------------------
    operated_count = len(operated)
    missing = [t for t in operated if t not in trips_with_any_event]
    missing_count = len(missing)
    trips_with_events_count = operated_count - missing_count
    exact_share = (
        Decimal(0)
        if operated_count == 0
        else Decimal(missing_count) / Decimal(operated_count)
    )
    missing_share = exact_share.quantize(_SHARE_QUANTUM, rounding=ROUND_HALF_EVEN)

    # Exact threshold line: missing/operated > threshold <=>
    # missing > threshold * operated (never the quantized share).
    above_threshold = Decimal(missing_count) > missing_trip_threshold * Decimal(
        operated_count
    )

    blocking_issues: tuple[Finding, ...] = ()
    factor_applied: Decimal | None = None
    value: Decimal | None = None
    if above_threshold:
        named = ", ".join(missing[:_MISSING_TRIPS_NAMED])
        if missing_count > _MISSING_TRIPS_NAMED:
            named += f", ... ({missing_count - _MISSING_TRIPS_NAMED} more)"
        blocking_issues = (
            Finding(
                issue_type="apc_missing_trips_above_fta_threshold",
                severity=SEVERITY_BLOCKING,
                title=(
                    f"Missing-trip share {missing_share} exceeds the FTA 2% "
                    f"threshold: {missing_count} of {operated_count} operated "
                    f"trips have no passenger events"
                ),
                description=(
                    f"{missing_count} of {operated_count} operated trips "
                    f"(observed in canonical.vehicle_positions) have zero "
                    f"passenger events: missing share {missing_share} exceeds "
                    f"the threshold of {missing_trip_threshold}. Per the 2026 "
                    f"NTD Policy Manual p. 146, 'if the vehicle trips with "
                    f"missing data exceed 2 percent of total trips, agencies "
                    f"must have a qualified statistician approve the factoring "
                    f"method used to account for the missing percentage' — a "
                    f"human workflow, so the calculation refuses to emit a "
                    f"value ({missing_trip_threshold} is the FTA threshold, "
                    f"not an engineering placeholder). Missing trip_ids: "
                    f"{named}."
                ),
                # Missing trips have, by definition, no passenger-event
                # records to cite; the trip ids are named in the description.
                source_record_ids=(),
            ),
        )
    else:
        # p. 146: "transit agencies should factor up the data to account for
        # the missing trips" — deterministic, FTA-sanctioned: counted x
        # operated/(operated - missing), from the EXACT fraction (the
        # quantized factor below is reporting provenance only), then
        # quantized to whole boardings.
        if missing_count == 0:
            exact_factor = Decimal(1)
            value = Decimal(counted_boardings).quantize(
                _UPT_QUANTUM, rounding=ROUND_HALF_EVEN
            )
        else:
            exact_factor = Decimal(operated_count) / Decimal(
                operated_count - missing_count
            )
            value = (
                Decimal(counted_boardings)
                * Decimal(operated_count)
                / Decimal(operated_count - missing_count)
            ).quantize(_UPT_QUANTUM, rounding=ROUND_HALF_EVEN)
        factor_applied = exact_factor.quantize(
            _FACTOR_QUANTUM, rounding=ROUND_HALF_EVEN
        )

    detail = UptDetail(
        total_boardings_counted=counted_boardings,
        operated_trips=operated_count,
        trips_with_events=trips_with_events_count,
        missing_trips=missing_count,
        missing_share=missing_share,
        factor_applied=factor_applied,
        source_mix=source_mix,
        missing_trip_threshold=missing_trip_threshold,
        imbalance_threshold=imbalance_threshold,
    )

    return CalcResult(
        value=value,
        unit=UNIT,
        calc_name=CALC_NAME,
        calc_version=CALC_VERSION,
        input_record_ids=tuple(input_ids),
        blocking_issues=blocking_issues,
        warnings=tuple(warnings),
        infos=tuple(infos),
        detail=detail,
    )
