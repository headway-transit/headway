"""Demand Response calculations (handoff 0013): dr_vrh_v0, dr_vrm_v0,
dr_upt_v0, dr_voms_v0, dr_pmt_v0 over canonical.dr_trips.

Regulatory basis — 2026 NTD Full Reporting Policy Manual, EXACTLY as quoted
in REGULATORY_TRACKER.md, "Verified — Demand Response / on-demand reporting
(verified 2026-07-12)" (pp. 33, 37-39, 129-139, 143-144). No regulatory
number or rule below enters from memory; every rule is one of those quotes:

- **DR revenue time (p. 129)** — THE core divergence from fixed route:
  "For DR service, revenue time includes all travel time from the point of
  the first passenger pick-up to the last passenger drop-off, as long as the
  vehicle does not return to the garage or dispatching point or have
  interruptions in service, such as lunch breaks or vehicle fueling and
  servicing." Implemented as REVENUE SPANS per (vehicle_id, service_date):
  first pickup → last dropoff, BROKEN at every trip whose
  ``interruption_after`` marker is set (lunch / fuel / garage_return /
  dispatch_return).
- **TX revenue rule (p. 129):** "agencies must report only the miles and
  hours when a transit passenger is onboard as revenue service. When a
  transit passenger is not onboard, the service is not reportable to the
  NTD." Implemented for ``tos = 'TX'`` as the UNION of passenger-onboard
  [pickup, dropoff] windows (a shared ride's overlap counts once) — empty
  inter-passenger travel, waiting, and no-show visits contribute NOTHING to
  TX figures.
- **Exhibit 36 (pp. 134-135)** — the activity classifications the span
  semantics realize, encoded verbatim in :data:`EXHIBIT_36` and golden-pinned
  row by row (tests/golden/dr_v0): notably "no-show trip ('Driver travels to
  pick up a passenger but the passenger is a no-show') → actual + REVENUE
  (yes/yes)" (revenue time YES — and UPT ZERO, the asymmetry dr_upt_v0
  pins), and empty travel between a dropoff and the next pickup → REVENUE.
- **Deadhead legs (p. 130)** — the six leg types in
  :data:`DEADHEAD_LEG_TYPES`; "FTA defines the dispatching point as the
  location where a driver receives the schedule to provide revenue service."
  Trip records carry driver-shift/dispatching-point REFERENCES only, so
  deadhead legs are CLASSIFIED (and their non-revenue status realized by the
  span semantics: travel before the first pickup and after a span break is
  simply never counted) but their durations/distances are NOT measurable
  from this contract — a documented limitation, not silent logic. "Full
  Reporters do not report deadhead for the Vanpool mode or the TX and
  Transportation Network Company (TN) TOS" (:data:`NO_DEADHEAD_TOS`).
  Fueling and lunch travel are "neither revenue nor deadhead" — the span
  break drops them from revenue by construction.
- **DR VOMS (Exhibits 38 + 40, pp. 138-139):** "The largest number of
  vehicles in revenue service at any one time during the reporting year
  (INCLUDES atypical service)" — TRUE SIMULTANEITY over the revenue
  intervals, including every day (the OPPOSITE of voms_v0's non-DR
  atypical-day exclusion — deliberately NOT reused). Exhibit 40's Happy
  Transit scenario (six unique vehicles, max four simultaneous → VOMS 4) is
  the golden.
- **DR UPT (pp. 143-144):** attendants and companions count "as long as
  they are not employees of the transit agency" (the wire contract's
  ``attendants_companions`` is non-employee by definition); ADA-related UPT
  is split out — included in the total, NEVER in the sponsored split;
  sponsored UPT (Medicaid, Meals-On-Wheels, etc.) is split out — included
  in the total. A no-show is never a boarding.
- **DR PMT:** passenger-onboard distance sums × persons per booking — the
  handoff-0013 "no load-profile path". PMT definition p. 145 ("the sum of
  the distances each passenger traveled") is quoted in the tracker's PMT
  section; the DR inputs here are the wire contract's measured onboard
  distances, never a reconstructed profile.

Fail-loudly positions (v0, all documented in the tracker rows):

- A vehicle-day with MIXED types of service, or with an interruption marked
  while a passenger was still onboard, is a contradiction: the group is
  EXCLUDED with one warning finding citing its records — the applicable
  revenue rule is never guessed.
- An UNMEASURED distance (no odometer pair, no onboard_miles) contributes 0
  and is warned — a DOCUMENTED UNDERCOUNT, never an interpolated number
  (the vrh_v0 0.3.0 'block_unavailable' precedent for
  documented-undercount-with-finding).
- Summing per-booking distances over OVERLAPPING TX bookings can OVERCOUNT
  the shared segment (p. 129 counts vehicle miles with a passenger onboard
  once): when boundary odometer readings make the exact interval measure
  possible it is used; otherwise the sum is taken AND warned.
- Simulated sources (envelope source != 'dr') always yield the
  'simulated_source_data' info finding; source_mix is always in the detail.

No completeness threshold is implemented: no missing-data threshold is
quoted for DR in the tracker's DR section, and inventing one (or borrowing
the p. 146 100%-count rule from the UPT section) would be a regulatory
number from the wrong context. The DR calcs therefore never block; every
gap is a warning with the undercount/overcount direction stated.

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input trips. Decimal end to end
(distances arrive as NUMERIC); one final quantization per figure (0.01 h /
0.01 mi, ROUND_HALF_EVEN — the vrh/vrm engineering convention).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable

from headway_calc.types import (
    SEVERITY_INFO,
    SEVERITY_WARNING,
    CalcResult,
    DrPmtDetail,
    DrServiceDetail,
    DrTrip,
    DrUptDetail,
    DrVomsDetail,
    DrVrmDetail,
    Finding,
)

#: Per-calc versions. dr_vrm_v0 and dr_voms_v0 minted 0.1.1 in the
#: 2026-07-13 hardening pass (see the REGULATORY_TRACKER.md rows and the
#: dated superseding notes on their 0.1.0 rows): the non-TX onboard-sum
#: path now merges overlapping shared-ride onboard windows before pricing,
#: and the VOMS sweep counts distinct VEHICLES covering an instant, never
#: concurrent intervals. The superseded 0.1.0 behaviors stay runnable
#: (:func:`compute_dr_vrm_v0_1_0` / :func:`compute_dr_voms_v0_1_0`) so
#: figures persisted under 0.1.0 recompute bit for bit (the tracker rule:
#: shipped versions are never deleted or rewritten).
VRH_CALC_VERSION = "0.1.0"
VRM_CALC_VERSION = "0.1.1"
UPT_CALC_VERSION = "0.1.0"
VOMS_CALC_VERSION = "0.1.1"
PMT_CALC_VERSION = "0.1.0"
VRM_CALC_VERSION_0_1_0 = "0.1.0"
VOMS_CALC_VERSION_0_1_0 = "0.1.0"

VRH_CALC_NAME = "dr_vrh_v0"
VRM_CALC_NAME = "dr_vrm_v0"
UPT_CALC_NAME = "dr_upt_v0"
VOMS_CALC_NAME = "dr_voms_v0"
PMT_CALC_NAME = "dr_pmt_v0"

#: Units follow the fixed-route calcs' vocabulary (vrm_v0/vrh_v0/upt_v0/
#: voms_v0/pmt_v0) so DR rows land in the same metric surfaces.
UNIT_HOURS = "hours"
UNIT_MILES = "miles"
UNIT_UPT = "unlinked_passenger_trips"
UNIT_VEHICLES = "vehicles"
UNIT_PMT = "passenger_miles"

_HOURS_QUANTUM = Decimal("0.01")
_MILES_QUANTUM = Decimal("0.01")
_SECONDS_PER_HOUR = Decimal(3600)

#: The envelope source of REAL dispatch feeds; anything else (e.g.
#: "dr_simulated", or a vendor push label) triggers the simulated/non-default
#: source info finding — erring toward flagging, exactly like upt_v0's
#: 'tides' rule.
_REAL_SOURCE = "dr"

#: TOS whose revenue rule is passenger-onboard-only (p. 129 TX rule, quoted
#: in the module docstring).
ONBOARD_ONLY_TOS = ("TX",)

#: "Full Reporters do not report deadhead for the Vanpool mode or the TX and
#: Transportation Network Company (TN) TOS." (p. 130, quoted in the tracker.)
#: VP is a MODE, not a DR TOS, so only TX/TN appear here.
NO_DEADHEAD_TOS = ("TX", "TN")

#: The six non-fixed-route deadhead leg types (p. 130, quoted in the
#: tracker). Trip records carry only REFERENCES (driver_shift_id /
#: dispatching_point_id), so these legs are classified, not measured — see
#: the module docstring.
DEADHEAD_LEG_TYPES = (
    "garage_to_dispatching_point",
    "garage_to_first_scheduled_pickup",
    "dispatching_point_to_first_pickup",
    "last_dropoff_to_dispatching_point",
    "last_dropoff_to_garage",
    "dispatching_point_to_garage",
)


@dataclass(frozen=True)
class Exhibit36Row:
    """One Exhibit 36 activity row (pp. 134-135), classification VERBATIM
    per the tracker's DR section. ``actual``/``revenue`` are the exhibit's
    actual-hours/revenue-hours answers; ``miles_not_applicable`` marks the
    one row the exhibit prices for hours only."""

    activity: str
    description: str
    actual: bool
    revenue: bool
    miles_not_applicable: bool = False


#: EVERY Exhibit 36 row, exactly as quoted in the tracker ("Exhibit 36
#: activity table (pp. 134-135, verbatim classifications)"). Golden-pinned
#: one-for-one in tests/golden/dr_v0; the span semantics realize each row
#: (see the fixture's BASIS.md for the row-by-row mapping).
EXHIBIT_36 = (
    Exhibit36Row(
        activity="idle_at_dispatching_point",
        description="idle at dispatching point",
        actual=False,
        revenue=False,
    ),
    Exhibit36Row(
        activity="depart_dispatch_to_pick_up_passenger",
        description="depart dispatch to pick up passenger",
        actual=True,
        revenue=False,
    ),
    Exhibit36Row(
        activity="wait_for_passenger_at_pickup",
        description="wait for passenger at pickup",
        actual=True,
        revenue=True,
        miles_not_applicable=True,
    ),
    Exhibit36Row(
        activity="empty_travel_between_dropoff_and_next_pickup",
        description=(
            "travel between dropoff and next pickup with NO passengers onboard"
        ),
        actual=True,
        revenue=True,
    ),
    Exhibit36Row(
        activity="lunch_travel_or_eating",
        description="lunch travel/eating",
        actual=False,
        revenue=False,
    ),
    Exhibit36Row(
        activity="return_to_dispatch_empty",
        description="return to dispatch empty",
        actual=True,
        revenue=False,
    ),
    Exhibit36Row(
        activity="no_show_trip",
        description=(
            "Driver travels to pick up a passenger but the passenger is a "
            "no-show"
        ),
        actual=True,
        revenue=True,
    ),
    Exhibit36Row(
        activity="fueling",
        description="fueling",
        actual=False,
        revenue=False,
    ),
)


def _hours(total_seconds: Decimal) -> Decimal:
    """Exact seconds → hours, quantized once (0.01 h, ROUND_HALF_EVEN — the
    vrh_v0 convention)."""
    return (total_seconds / _SECONDS_PER_HOUR).quantize(
        _HOURS_QUANTUM, rounding=ROUND_HALF_EVEN
    )


def _sorted_trips(trips: Iterable[DrTrip]) -> list[DrTrip]:
    """Canonical total order (matches the reader's ORDER BY): input order is
    irrelevant to the result."""
    return sorted(
        trips,
        key=lambda t: (t.pickup_timestamp, t.dr_trip_id, t.source_record_id),
    )


def _record_ids(trips: Iterable[DrTrip]) -> tuple[str, ...]:
    ids: dict[str, None] = {}
    for trip in trips:
        ids.setdefault(trip.source_record_id, None)
    return tuple(ids)


@dataclass(frozen=True)
class _Interval:
    """One revenue-service interval of a vehicle-day: a p. 129 revenue span
    (non-TX; ends because of a break or the day's last dropoff) or one
    merged passenger-onboard window (TX)."""

    start: datetime
    end: datetime
    trips: tuple[DrTrip, ...]
    break_after: str | None  # the marker that ENDED this span, or None

    @property
    def seconds(self) -> Decimal:
        return Decimal(str((self.end - self.start).total_seconds()))


@dataclass(frozen=True)
class _VehicleDay:
    """One counted (vehicle_id, service_date) group with its intervals."""

    vehicle_id: str
    service_date: object
    tos: str
    trips: tuple[DrTrip, ...]
    intervals: tuple[_Interval, ...]


def _build_intervals(group: list[DrTrip], tos: str) -> tuple[list[_Interval], str | None]:
    """Build the group's revenue intervals, or return a contradiction reason.

    Non-TX (p. 129 span rule): spans run first pickup → last dropoff and
    BREAK after every trip with an interruption marker. Contradiction: a
    marker on trip T while another trip is still onboard strictly across
    T's dropoff (an in-ride 'interruption') — the group cannot be accounted
    and is excluded by the caller.

    TX (p. 129 onboard-only rule): merged [pickup, dropoff] windows of
    completed bookings — a shared ride's overlap counts once; no-shows and
    inter-passenger time contribute nothing; interruption markers are
    irrelevant to onboard-only accounting.
    """
    if tos in ONBOARD_ONLY_TOS:
        intervals: list[_Interval] = []
        for trip in group:  # already pickup-sorted
            if trip.no_show:
                continue  # never a passenger onboard: not reportable for TX
            if intervals and trip.pickup_timestamp <= intervals[-1].end:
                last = intervals[-1]
                intervals[-1] = _Interval(
                    start=last.start,
                    end=max(last.end, trip.dropoff_timestamp),
                    trips=last.trips + (trip,),
                    break_after=None,
                )
            else:
                intervals.append(
                    _Interval(
                        start=trip.pickup_timestamp,
                        end=trip.dropoff_timestamp,
                        trips=(trip,),
                        break_after=None,
                    )
                )
        return intervals, None

    # Non-TX: contradiction check first — an interruption marked on trip T
    # while another trip is onboard strictly across T's dropoff.
    for t in group:
        if t.interruption_after == "none":
            continue
        for s in group:
            if s is t:
                continue
            if (
                s.pickup_timestamp < t.dropoff_timestamp
                and s.dropoff_timestamp > t.dropoff_timestamp
            ):
                return [], (
                    f"trip {t.dr_trip_id!r} is marked "
                    f"'{t.interruption_after}' after its dropoff at "
                    f"{t.dropoff_timestamp.isoformat()}, but trip "
                    f"{s.dr_trip_id!r} was still onboard across that instant"
                )

    # Span building: a break takes effect at the marked trip's DROPOFF (the
    # interruption starts there), not at its list position — a shared-ride
    # booking picked up before that instant still belongs to the current
    # span (the contradiction check above guarantees no trip STRADDLES the
    # break instant, so pickup-time assignment is unambiguous).
    intervals = []
    current: list[DrTrip] = []
    pending_break: tuple[str, datetime] | None = None  # (marker, break instant)
    for trip in group:  # pickup-sorted
        if pending_break is not None and trip.pickup_timestamp >= pending_break[1]:
            intervals.append(
                _Interval(
                    start=min(t.pickup_timestamp for t in current),
                    end=max(t.dropoff_timestamp for t in current),
                    trips=tuple(current),
                    break_after=pending_break[0],
                )
            )
            current = []
            pending_break = None
        current.append(trip)
        if trip.interruption_after != "none" and (
            pending_break is None or trip.dropoff_timestamp > pending_break[1]
        ):
            pending_break = (trip.interruption_after, trip.dropoff_timestamp)
    if current:
        intervals.append(
            _Interval(
                start=min(t.pickup_timestamp for t in current),
                end=max(t.dropoff_timestamp for t in current),
                trips=tuple(current),
                # A marker on the day's final activity breaks nothing: the
                # span already ends at the last dropoff (return-to-dispatch/
                # garage after it is deadhead by construction).
                break_after=None,
            )
        )
    return intervals, None


def _account(
    trips: Iterable[DrTrip],
) -> tuple[list[_VehicleDay], list[Finding], dict]:
    """Shared vehicle-day accounting for every DR calc.

    Returns (counted vehicle-days, exclusion warnings, counters). Counters:
    vehicle_days / vehicle_days_counted / vehicle_days_excluded /
    trips_counted / no_show_trips / revenue_spans / interruption_breaks /
    tos_mix / source_mix. Exclusions (mixed TOS; interruption-during-ride)
    are one warning each, citing the group's records — the group's trips
    appear in NO figure and NO lineage (the excluded-group rule).
    """
    ordered = _sorted_trips(trips)

    source_mix: dict[str, int] = {}
    for trip in ordered:
        source_mix[trip.source] = source_mix.get(trip.source, 0) + 1

    groups: dict[tuple, list[DrTrip]] = {}
    for trip in ordered:
        groups.setdefault((trip.vehicle_id, trip.service_date), []).append(trip)

    counted: list[_VehicleDay] = []
    warnings: list[Finding] = []
    counters = {
        "vehicle_days": len(groups),
        "vehicle_days_counted": 0,
        "vehicle_days_excluded": 0,
        "trips_counted": 0,
        "no_show_trips": 0,
        "revenue_spans": 0,
        "interruption_breaks": {},
        "tos_mix": {},
        "source_mix": source_mix,
    }

    for (vehicle_id, service_date), group in sorted(groups.items()):
        tos_values = sorted({t.tos for t in group})
        if len(tos_values) > 1:
            counters["vehicle_days_excluded"] += 1
            warnings.append(
                Finding(
                    issue_type="dr_mixed_tos_vehicle_day",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Vehicle {vehicle_id} on {service_date} carries "
                        f"mixed types of service ({', '.join(tos_values)}): "
                        f"vehicle-day excluded"
                    ),
                    description=(
                        f"The {len(group)} trips of vehicle {vehicle_id!r} on "
                        f"{service_date} carry more than one type of service "
                        f"({', '.join(tos_values)}). The TOS selects the "
                        f"revenue rule (p. 129 as quoted in the tracker's DR "
                        f"section: TX counts only passenger-onboard time and "
                        f"distance; DO/PT/TN count the first-pickup to "
                        f"last-dropoff span), so a mixed vehicle-day cannot "
                        f"be accounted under one rule. The vehicle-day was "
                        f"EXCLUDED from the figure — the applicable rule is "
                        f"never guessed. Its records are cited here instead "
                        f"of appearing in lineage."
                    ),
                    source_record_ids=_record_ids(group),
                )
            )
            continue
        tos = tos_values[0]
        intervals, contradiction = _build_intervals(group, tos)
        if contradiction is not None:
            counters["vehicle_days_excluded"] += 1
            warnings.append(
                Finding(
                    issue_type="dr_interruption_during_ride",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Vehicle {vehicle_id} on {service_date}: interruption "
                        f"marked while a passenger was onboard — vehicle-day "
                        f"excluded"
                    ),
                    description=(
                        f"Vehicle {vehicle_id!r} on {service_date}: "
                        f"{contradiction}. An interruption in service (p. 129 "
                        f"as quoted in the tracker's DR section) cannot occur "
                        f"while a passenger is onboard, so this vehicle-day's "
                        f"data is contradictory and was EXCLUDED from the "
                        f"figure — never repaired or guessed. Its records are "
                        f"cited here instead of appearing in lineage."
                    ),
                    source_record_ids=_record_ids(group),
                )
            )
            continue

        counters["vehicle_days_counted"] += 1
        counters["trips_counted"] += len(group)
        counters["no_show_trips"] += sum(1 for t in group if t.no_show)
        counters["revenue_spans"] += len(intervals)
        counters["tos_mix"][tos] = counters["tos_mix"].get(tos, 0) + len(group)
        for interval in intervals:
            if interval.break_after is not None:
                breaks = counters["interruption_breaks"]
                breaks[interval.break_after] = breaks.get(interval.break_after, 0) + 1
        counted.append(
            _VehicleDay(
                vehicle_id=vehicle_id,
                service_date=service_date,
                tos=tos,
                trips=tuple(group),
                intervals=tuple(intervals),
            )
        )

    return counted, warnings, counters


def _simulated_source_info(trips: list[DrTrip], source_mix: dict[str, int]) -> list[Finding]:
    """The handoff-0005 simulated-data rule applied to DR (handoff 0013):
    ONE info finding whenever any trip's source is not the real-feed default
    'dr' — erring toward flagging, exactly like upt_v0."""
    other_sources = sorted(s for s in source_mix if s != _REAL_SOURCE)
    if not other_sources:
        return []
    flagged_ids: dict[str, None] = {}
    for trip in trips:
        if trip.source != _REAL_SOURCE:
            flagged_ids.setdefault(trip.source_record_id, None)
    return [
        Finding(
            issue_type="simulated_source_data",
            severity=SEVERITY_INFO,
            title=(
                f"DR trips include non-'dr' source(s): "
                f"{', '.join(other_sources)}"
            ),
            description=(
                f"{sum(source_mix[s] for s in other_sources)} of "
                f"{len(trips)} demand-response trips carry a source other "
                f"than 'dr': "
                + ", ".join(f"{s} ({source_mix[s]} trips)" for s in other_sources)
                + ". Per the handoff-0005 simulated-data rule (applied to DR "
                "by handoff 0013), simulator output is permanently "
                "distinguishable in provenance and a certifiable figure "
                "containing simulated records is a contradiction the DQ "
                "trail must make visible: this figure is NOT certifiable or "
                "reportable. The full source mix is recorded in the metric "
                "value's detail."
            ),
            source_record_ids=tuple(flagged_ids),
        )
    ]


def _service_detail(counters: dict) -> DrServiceDetail:
    return DrServiceDetail(
        vehicle_days=counters["vehicle_days"],
        vehicle_days_counted=counters["vehicle_days_counted"],
        vehicle_days_excluded=counters["vehicle_days_excluded"],
        trips_counted=counters["trips_counted"],
        no_show_trips=counters["no_show_trips"],
        revenue_spans=counters["revenue_spans"],
        interruption_breaks=counters["interruption_breaks"],
        tos_mix=counters["tos_mix"],
        source_mix=counters["source_mix"],
    )


def compute_dr_vrh(trips: Iterable[DrTrip]) -> CalcResult:
    """dr_vrh_v0 0.1.0 — DR Vehicle Revenue Hours (Exhibit 36 semantics).

    Per counted vehicle-day, the sum of its revenue intervals' durations:
    non-TX spans run first pickup → last dropoff and break at interruption
    markers (p. 129, quoted in the module docstring); waiting at a pickup,
    empty inter-passenger travel, and no-show visits inside a span are
    revenue BY CONSTRUCTION (Exhibit 36 rows 3/4/7); everything before the
    first pickup, after the last dropoff, and across a break — the deadhead
    legs and the neither-revenue-nor-deadhead fueling/lunch travel — is
    excluded by construction. TX vehicle-days count only merged
    passenger-onboard windows (the p. 129 TX rule).

    Value: Decimal hours, one final 0.01 quantization (ROUND_HALF_EVEN).
    Never blocks (no completeness threshold is quoted for DR — module
    docstring); exclusions and simulated sources are findings. Lineage
    covers the counted groups' trip records only.
    """
    ordered = _sorted_trips(trips)
    counted, warnings, counters = _account(ordered)

    total_seconds = Decimal(0)
    input_ids: dict[str, None] = {}
    for day in counted:
        for interval in day.intervals:
            total_seconds += interval.seconds
        for record_id in _record_ids(day.trips):
            input_ids.setdefault(record_id, None)

    return CalcResult(
        value=_hours(total_seconds),
        unit=UNIT_HOURS,
        calc_name=VRH_CALC_NAME,
        calc_version=VRH_CALC_VERSION,
        input_record_ids=tuple(input_ids),
        blocking_issues=(),
        warnings=tuple(warnings),
        infos=tuple(_simulated_source_info(ordered, counters["source_mix"])),
        detail=_service_detail(counters),
    )


def _trip_onboard_distance(trip: DrTrip) -> tuple[Decimal | None, str | None]:
    """One booking's passenger-onboard distance and its source: an odometer
    pair when both readings exist (the transform quarantines decreasing
    pairs), else the exported onboard_miles, else None — UNMEASURED, never
    guessed."""
    if (
        trip.pickup_odometer_miles is not None
        and trip.dropoff_odometer_miles is not None
    ):
        return trip.dropoff_odometer_miles - trip.pickup_odometer_miles, "odometer_pair"
    if trip.onboard_miles is not None:
        return trip.onboard_miles, "onboard_miles"
    return None, None


def _merge_onboard_windows(trips: Iterable[DrTrip]) -> list[list[DrTrip]]:
    """Merge a non-TX interval's booking [pickup, dropoff] windows into
    maximal overlapping-or-touching groups (pickup-sorted input; the same
    merge rule as the TX interval builder).

    Vehicle miles are VEHICLE miles (p. 128 as quoted in the tracker:
    "the ... miles vehicles travel while in revenue service"): bookings
    sharing the vehicle over the same window must be priced ONCE, so
    pricing operates per merged window, never per booking across an
    overlap (the dr_vrm_v0 0.1.1 correction — the 0.1.0 per-booking sum
    double-counted shared rides on the onboard-sum path)."""
    windows: list[list[DrTrip]] = []
    window_end: datetime | None = None
    for trip in trips:
        if windows and window_end is not None and trip.pickup_timestamp <= window_end:
            windows[-1].append(trip)
            if trip.dropoff_timestamp > window_end:
                window_end = trip.dropoff_timestamp
        else:
            windows.append([trip])
            window_end = trip.dropoff_timestamp
    return windows


def _price_onboard_window(
    window: list[DrTrip],
) -> tuple[Decimal, str | None, int, bool]:
    """Price ONE merged onboard window: (miles, source, missing, summed).

    Precedence: the window's boundary odometer delta (first-pickup reading
    → last-dropoff reading, non-decreasing) — exact even when the window
    holds overlapping shared-ride bookings (``source = 'window_odometer'``);
    else the per-booking onboard sum: a booking with no measurable distance
    contributes 0 and is counted in ``missing`` (documented undercount,
    never a guess), and ``summed`` is True when more than one booking was
    summed — the shared segment may then be counted more than once (the
    caller warns; never silent)."""
    first = min(window, key=lambda t: (t.pickup_timestamp, t.dr_trip_id))
    last = max(window, key=lambda t: (t.dropoff_timestamp, t.dr_trip_id))
    if (
        first.pickup_odometer_miles is not None
        and last.dropoff_odometer_miles is not None
        and last.dropoff_odometer_miles >= first.pickup_odometer_miles
    ):
        return (
            last.dropoff_odometer_miles - first.pickup_odometer_miles,
            "window_odometer",
            0,
            False,
        )
    miles = Decimal(0)
    missing = 0
    for trip in window:
        distance, _source = _trip_onboard_distance(trip)
        if distance is None:
            missing += 1
        else:
            miles += distance
    return miles, None, missing, len(window) > 1


def compute_dr_vrm(trips: Iterable[DrTrip]) -> CalcResult:
    """dr_vrm_v0 0.1.1 — DR Vehicle Revenue Miles (Exhibit 36 semantics).

    Distance-source precedence per revenue interval:

    1. **Whole-interval odometer delta** — the interval's first pickup
       reading to its last dropoff reading. Exact for everything revenue
       inside the span (onboard segments AND the Exhibit-36 empty
       inter-passenger travel), and excludes interruption legs by
       construction (spans break there).
    2. **Onboard sum over MERGED windows** (the 0.1.1 correction — 0.1.0
       summed per booking and double-counted overlapping shared rides):
       the interval's booking windows are merged into
       overlapping-or-touching groups first (vehicle miles are VEHICLE
       miles — passengers sharing the vehicle do not multiply its miles).
       Each merged window prices by its boundary odometer delta when
       available; else by the per-booking sum — with a booking lacking any
       measurable distance contributing 0 + a warning (documented
       UNDERCOUNT — Exhibit 36 prices the leg as revenue) and a
       multi-booking sum warned as `dr_shared_distance_summed` (possible
       OVERCOUNT of the shared segment; 0.1.0 gated this warning to TX).
       Empty inter-passenger legs are the gaps BETWEEN merged windows,
       measurable only via an odometer pair across the gap (else warned).
       Never an interpolated number.

    TX intervals are passenger-onboard only (no empty legs). A TX interval
    holding several overlapping bookings uses the boundary odometer delta
    when available; otherwise the per-booking SUM is taken and warned — a
    possible OVERCOUNT of the shared segment (p. 129 counts vehicle miles
    with a passenger onboard once).

    Value: Decimal miles, one final 0.01 quantization. Never blocks; every
    gap is a finding with its direction stated. 0.1.0 stays runnable as
    :func:`compute_dr_vrm_v0_1_0` (tracker superseding note, 2026-07-13).
    """
    ordered = _sorted_trips(trips)
    counted, warnings, counters = _account(ordered)

    total_miles = Decimal(0)
    distance_sources: dict[str, int] = {}
    unmeasured_empty_legs = 0
    missing_onboard = 0
    tx_summed_overlaps = 0
    shared_overlaps_summed = 0
    input_ids: dict[str, None] = {}

    for day in counted:
        day_unmeasured_legs = 0
        day_missing_onboard = 0
        day_tx_overlap = 0
        day_shared_overlap = 0
        for interval in day.intervals:
            first = min(
                interval.trips, key=lambda t: (t.pickup_timestamp, t.dr_trip_id)
            )
            last = max(
                interval.trips, key=lambda t: (t.dropoff_timestamp, t.dr_trip_id)
            )
            if (
                first.pickup_odometer_miles is not None
                and last.dropoff_odometer_miles is not None
                and last.dropoff_odometer_miles >= first.pickup_odometer_miles
            ):
                total_miles += (
                    last.dropoff_odometer_miles - first.pickup_odometer_miles
                )
                distance_sources["span_odometer"] = (
                    distance_sources.get("span_odometer", 0) + 1
                )
                continue

            distance_sources["onboard_sum"] = (
                distance_sources.get("onboard_sum", 0) + 1
            )
            if day.tos in ONBOARD_ONLY_TOS:
                # TX: the interval IS one merged passenger-onboard window
                # (built that way); no empty legs exist by construction.
                if len(interval.trips) > 1:
                    day_tx_overlap += 1
                for trip in interval.trips:
                    distance, _source = _trip_onboard_distance(trip)
                    if distance is None:
                        day_missing_onboard += 1
                    else:
                        total_miles += distance
                continue

            # Non-TX onboard sum (0.1.1): merge overlapping onboard windows
            # BEFORE pricing, then price the gaps between them as the empty
            # inter-passenger legs (Exhibit 36: revenue yes/yes).
            windows = _merge_onboard_windows(interval.trips)
            for window in windows:
                miles, source, missing, summed_overlap = _price_onboard_window(
                    window
                )
                total_miles += miles
                day_missing_onboard += missing
                if source == "window_odometer":
                    distance_sources["window_odometer"] = (
                        distance_sources.get("window_odometer", 0) + 1
                    )
                if summed_overlap:
                    day_shared_overlap += 1
            for prev_window, next_window in zip(windows, windows[1:]):
                prev_last = max(
                    prev_window,
                    key=lambda t: (t.dropoff_timestamp, t.dr_trip_id),
                )
                next_first = next_window[0]
                if (
                    prev_last.dropoff_odometer_miles is not None
                    and next_first.pickup_odometer_miles is not None
                    and next_first.pickup_odometer_miles
                    >= prev_last.dropoff_odometer_miles
                ):
                    total_miles += (
                        next_first.pickup_odometer_miles
                        - prev_last.dropoff_odometer_miles
                    )
                else:
                    day_unmeasured_legs += 1

        if day_unmeasured_legs or day_missing_onboard:
            warnings.append(
                Finding(
                    issue_type="dr_distance_unmeasured",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Vehicle {day.vehicle_id} on {day.service_date}: "
                        f"{day_missing_onboard} booking(s) and "
                        f"{day_unmeasured_legs} empty leg(s) without a "
                        f"measurable distance"
                    ),
                    description=(
                        f"Vehicle {day.vehicle_id!r} on {day.service_date}: "
                        f"{day_missing_onboard} booking(s) carry no odometer "
                        f"pair and no onboard_miles, and "
                        f"{day_unmeasured_legs} empty inter-passenger leg(s) "
                        f"have no odometer pair across the gap. Exhibit 36 "
                        f"(as quoted in the tracker's DR section) prices "
                        f"empty travel between a dropoff and the next pickup "
                        f"as REVENUE miles, so these legs belong in the "
                        f"figure — they contributed 0 instead: the figure "
                        f"UNDERSTATES revenue miles for this vehicle-day. A "
                        f"distance is never interpolated; supply odometer "
                        f"readings or onboard distances to close the gap."
                    ),
                    source_record_ids=_record_ids(day.trips),
                )
            )
        if day_tx_overlap:
            warnings.append(
                Finding(
                    issue_type="dr_tx_shared_distance_summed",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Vehicle {day.vehicle_id} on {day.service_date}: "
                        f"{day_tx_overlap} shared TX interval(s) priced by "
                        f"summing per-booking distances"
                    ),
                    description=(
                        f"Vehicle {day.vehicle_id!r} on {day.service_date} "
                        f"(TX): {day_tx_overlap} merged passenger-onboard "
                        f"interval(s) hold overlapping bookings but no "
                        f"boundary odometer pair, so per-booking onboard "
                        f"distances were SUMMED. The p. 129 TX rule (quoted "
                        f"in the tracker's DR section) counts vehicle miles "
                        f"with a passenger onboard ONCE, so the sum may "
                        f"OVERCOUNT the shared segment. Supply odometer "
                        f"readings for the exact interval measure."
                    ),
                    source_record_ids=_record_ids(day.trips),
                )
            )
        if day_shared_overlap:
            warnings.append(
                Finding(
                    issue_type="dr_shared_distance_summed",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Vehicle {day.vehicle_id} on {day.service_date}: "
                        f"{day_shared_overlap} shared-ride onboard window(s) "
                        f"priced by summing per-booking distances"
                    ),
                    description=(
                        f"Vehicle {day.vehicle_id!r} on {day.service_date} "
                        f"({day.tos}): {day_shared_overlap} merged "
                        f"passenger-onboard window(s) hold overlapping "
                        f"bookings but carry no boundary odometer pair, so "
                        f"per-booking onboard distances were SUMMED. VRM "
                        f"counts the miles the VEHICLE travels in revenue "
                        f"service (p. 128 as quoted in the tracker) — "
                        f"passengers sharing the vehicle do not multiply its "
                        f"miles — so the sum may OVERCOUNT the shared "
                        f"segment. Supply odometer readings for the exact "
                        f"window measure."
                    ),
                    source_record_ids=_record_ids(day.trips),
                )
            )
        unmeasured_empty_legs += day_unmeasured_legs
        missing_onboard += day_missing_onboard
        tx_summed_overlaps += day_tx_overlap
        shared_overlaps_summed += day_shared_overlap
        for record_id in _record_ids(day.trips):
            input_ids.setdefault(record_id, None)

    base = _service_detail(counters)
    detail = DrVrmDetail(
        vehicle_days=base.vehicle_days,
        vehicle_days_counted=base.vehicle_days_counted,
        vehicle_days_excluded=base.vehicle_days_excluded,
        trips_counted=base.trips_counted,
        no_show_trips=base.no_show_trips,
        revenue_spans=base.revenue_spans,
        interruption_breaks=base.interruption_breaks,
        tos_mix=base.tos_mix,
        source_mix=base.source_mix,
        distance_sources=distance_sources,
        unmeasured_empty_legs=unmeasured_empty_legs,
        missing_onboard_distances=missing_onboard,
        tx_summed_overlap_intervals=tx_summed_overlaps,
        shared_overlap_windows_summed=shared_overlaps_summed,
    )

    return CalcResult(
        value=total_miles.quantize(_MILES_QUANTUM, rounding=ROUND_HALF_EVEN),
        unit=UNIT_MILES,
        calc_name=VRM_CALC_NAME,
        calc_version=VRM_CALC_VERSION,
        input_record_ids=tuple(input_ids),
        blocking_issues=(),
        warnings=tuple(warnings),
        infos=tuple(_simulated_source_info(ordered, counters["source_mix"])),
        detail=detail,
    )


def compute_dr_vrm_v0_1_0(trips: Iterable[DrTrip]) -> CalcResult:
    """dr_vrm_v0 0.1.0 — RETAINED RUNNABLE, SUPERSEDED by 0.1.1.

    The tracker's dated superseding note (2026-07-13, hardening pass)
    records the confirmed defect this version carries: on the onboard-sum
    path, non-TX vehicle-days price OVERLAPPING shared-ride onboard windows
    by summing per-booking distances — two passengers sharing the same
    10-mile window price 20 vehicle-miles, SILENTLY (no finding). 0.1.1
    merges overlapping onboard windows before pricing and warns wherever a
    merged window cannot be measured exactly. This function exists only so
    figures persisted under calc_version 0.1.0 stay reproducible bit for
    bit (the tracker rule: shipped versions are never deleted or
    rewritten); never run it for new figures.
    """
    ordered = _sorted_trips(trips)
    counted, warnings, counters = _account(ordered)

    total_miles = Decimal(0)
    distance_sources: dict[str, int] = {}
    unmeasured_empty_legs = 0
    missing_onboard = 0
    tx_summed_overlaps = 0
    input_ids: dict[str, None] = {}

    for day in counted:
        day_unmeasured_legs = 0
        day_missing_onboard = 0
        day_tx_overlap = 0
        for interval in day.intervals:
            first = min(
                interval.trips, key=lambda t: (t.pickup_timestamp, t.dr_trip_id)
            )
            last = max(
                interval.trips, key=lambda t: (t.dropoff_timestamp, t.dr_trip_id)
            )
            if (
                first.pickup_odometer_miles is not None
                and last.dropoff_odometer_miles is not None
                and last.dropoff_odometer_miles >= first.pickup_odometer_miles
            ):
                total_miles += (
                    last.dropoff_odometer_miles - first.pickup_odometer_miles
                )
                distance_sources["span_odometer"] = (
                    distance_sources.get("span_odometer", 0) + 1
                )
                continue

            distance_sources["onboard_sum"] = (
                distance_sources.get("onboard_sum", 0) + 1
            )
            if day.tos in ONBOARD_ONLY_TOS and len(interval.trips) > 1:
                day_tx_overlap += 1
            for trip in interval.trips:
                distance, _source = _trip_onboard_distance(trip)
                if distance is None:
                    day_missing_onboard += 1
                else:
                    total_miles += distance
            if day.tos not in ONBOARD_ONLY_TOS:
                # The superseded per-booking sum: overlapping windows are
                # NOT merged (the pinned 0.1.0 double-count). Empty legs:
                # previous running last-dropoff → next pickup, measurable
                # only via an odometer pair across the gap.
                running_end = interval.trips[0].dropoff_timestamp
                running_end_trip = interval.trips[0]
                for prev, nxt in zip(interval.trips, interval.trips[1:]):
                    if prev.dropoff_timestamp > running_end:
                        running_end = prev.dropoff_timestamp
                        running_end_trip = prev
                    if nxt.pickup_timestamp > running_end:
                        if (
                            running_end_trip.dropoff_odometer_miles is not None
                            and nxt.pickup_odometer_miles is not None
                            and nxt.pickup_odometer_miles
                            >= running_end_trip.dropoff_odometer_miles
                        ):
                            total_miles += (
                                nxt.pickup_odometer_miles
                                - running_end_trip.dropoff_odometer_miles
                            )
                        else:
                            day_unmeasured_legs += 1

        if day_unmeasured_legs or day_missing_onboard:
            warnings.append(
                Finding(
                    issue_type="dr_distance_unmeasured",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Vehicle {day.vehicle_id} on {day.service_date}: "
                        f"{day_missing_onboard} booking(s) and "
                        f"{day_unmeasured_legs} empty leg(s) without a "
                        f"measurable distance"
                    ),
                    description=(
                        f"Vehicle {day.vehicle_id!r} on {day.service_date}: "
                        f"{day_missing_onboard} booking(s) carry no odometer "
                        f"pair and no onboard_miles, and "
                        f"{day_unmeasured_legs} empty inter-passenger leg(s) "
                        f"have no odometer pair across the gap. Exhibit 36 "
                        f"(as quoted in the tracker's DR section) prices "
                        f"empty travel between a dropoff and the next pickup "
                        f"as REVENUE miles, so these legs belong in the "
                        f"figure — they contributed 0 instead: the figure "
                        f"UNDERSTATES revenue miles for this vehicle-day. A "
                        f"distance is never interpolated; supply odometer "
                        f"readings or onboard distances to close the gap."
                    ),
                    source_record_ids=_record_ids(day.trips),
                )
            )
        if day_tx_overlap:
            warnings.append(
                Finding(
                    issue_type="dr_tx_shared_distance_summed",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Vehicle {day.vehicle_id} on {day.service_date}: "
                        f"{day_tx_overlap} shared TX interval(s) priced by "
                        f"summing per-booking distances"
                    ),
                    description=(
                        f"Vehicle {day.vehicle_id!r} on {day.service_date} "
                        f"(TX): {day_tx_overlap} merged passenger-onboard "
                        f"interval(s) hold overlapping bookings but no "
                        f"boundary odometer pair, so per-booking onboard "
                        f"distances were SUMMED. The p. 129 TX rule (quoted "
                        f"in the tracker's DR section) counts vehicle miles "
                        f"with a passenger onboard ONCE, so the sum may "
                        f"OVERCOUNT the shared segment. Supply odometer "
                        f"readings for the exact interval measure."
                    ),
                    source_record_ids=_record_ids(day.trips),
                )
            )
        unmeasured_empty_legs += day_unmeasured_legs
        missing_onboard += day_missing_onboard
        tx_summed_overlaps += day_tx_overlap
        for record_id in _record_ids(day.trips):
            input_ids.setdefault(record_id, None)

    base = _service_detail(counters)
    detail = DrVrmDetail(
        vehicle_days=base.vehicle_days,
        vehicle_days_counted=base.vehicle_days_counted,
        vehicle_days_excluded=base.vehicle_days_excluded,
        trips_counted=base.trips_counted,
        no_show_trips=base.no_show_trips,
        revenue_spans=base.revenue_spans,
        interruption_breaks=base.interruption_breaks,
        tos_mix=base.tos_mix,
        source_mix=base.source_mix,
        distance_sources=distance_sources,
        unmeasured_empty_legs=unmeasured_empty_legs,
        missing_onboard_distances=missing_onboard,
        tx_summed_overlap_intervals=tx_summed_overlaps,
    )

    return CalcResult(
        value=total_miles.quantize(_MILES_QUANTUM, rounding=ROUND_HALF_EVEN),
        unit=UNIT_MILES,
        calc_name=VRM_CALC_NAME,
        calc_version=VRM_CALC_VERSION_0_1_0,
        input_record_ids=tuple(input_ids),
        blocking_issues=(),
        warnings=tuple(warnings),
        infos=tuple(_simulated_source_info(ordered, counters["source_mix"])),
        detail=detail,
    )


def compute_dr_upt(trips: Iterable[DrTrip]) -> CalcResult:
    """dr_upt_v0 0.1.0 — DR Unlinked Passenger Trips.

    Sum of riders + non-employee attendants/companions over counted,
    completed bookings (pp. 143-144, quoted in the module docstring). The
    Exhibit-36 asymmetry is structural: a NO-SHOW is revenue time in
    dr_vrh_v0 and contributes ZERO here (the wire contract pins riders =
    attendants = 0 on a no-show; the golden pins the asymmetry explicitly).

    Splits (all in the detail): ADA-related UPT — included in the total,
    NEVER in the sponsored split; sponsored UPT — included in the total,
    broken down by sponsor label. A trip flagged BOTH ada_related and
    sponsored contradicts the never-sponsored rule: ONE warning per trip,
    counted in the ADA split only.

    Lineage covers counted completed bookings' records (no-show and
    excluded-group records are cited by findings/detail instead).
    """
    ordered = _sorted_trips(trips)
    counted, warnings, counters = _account(ordered)

    upt = riders = attendants = 0
    ada_upt = sponsored_upt = 0
    sponsored_by_sponsor: dict[str, int] = {}
    conflicts = 0
    input_ids: dict[str, None] = {}

    for day in counted:
        for trip in day.trips:
            if trip.no_show:
                continue  # revenue time yes (dr_vrh) — boarding NO (Exhibit 36)
            upt += trip.persons
            riders += trip.riders
            attendants += trip.attendants_companions
            input_ids.setdefault(trip.source_record_id, None)
            if trip.ada_related and trip.sponsored:
                conflicts += 1
                ada_upt += trip.persons  # ADA wins: never in the sponsored split
                warnings.append(
                    Finding(
                        issue_type="dr_ada_sponsored_conflict",
                        severity=SEVERITY_WARNING,
                        title=(
                            f"Trip {trip.dr_trip_id} flagged both ADA-related "
                            f"and sponsored"
                        ),
                        description=(
                            f"Trip {trip.dr_trip_id!r} (vehicle "
                            f"{trip.vehicle_id!r}, {trip.service_date}) is "
                            f"flagged BOTH ada_related and sponsored "
                            f"({trip.sponsor!r}). Per the manual pp. 143-144 "
                            f"as quoted in the tracker's DR section, "
                            f"ADA-related UPT is included in the total and "
                            f"NEVER counted as sponsored — the flags "
                            f"contradict each other. The trip was counted in "
                            f"the total and in the ADA split ONLY; review "
                            f"the export's flag mapping."
                        ),
                        source_record_ids=(trip.source_record_id,),
                    )
                )
            elif trip.ada_related:
                ada_upt += trip.persons
            elif trip.sponsored:
                sponsored_upt += trip.persons
                label = trip.sponsor or "unspecified"
                sponsored_by_sponsor[label] = (
                    sponsored_by_sponsor.get(label, 0) + trip.persons
                )

    detail = DrUptDetail(
        upt=upt,
        riders=riders,
        attendants_companions=attendants,
        ada_related_upt=ada_upt,
        sponsored_upt=sponsored_upt,
        sponsored_by_sponsor=sponsored_by_sponsor,
        ada_sponsored_conflicts=conflicts,
        no_show_trips=counters["no_show_trips"],
        trips_counted=counters["trips_counted"],
        tos_mix=counters["tos_mix"],
        source_mix=counters["source_mix"],
    )

    return CalcResult(
        value=Decimal(upt),
        unit=UNIT_UPT,
        calc_name=UPT_CALC_NAME,
        calc_version=UPT_CALC_VERSION,
        input_record_ids=tuple(input_ids),
        blocking_issues=(),
        warnings=tuple(warnings),
        infos=tuple(_simulated_source_info(ordered, counters["source_mix"])),
        detail=detail,
    )


def compute_dr_voms(trips: Iterable[DrTrip]) -> CalcResult:
    """dr_voms_v0 0.1.1 — DR Vehicles Operated in Maximum Service.

    "The largest number of vehicles in revenue service at any one time
    during the reporting year (INCLUDES atypical service)" (Exhibits 38 +
    40, quoted in the tracker's DR section): TRUE SIMULTANEITY — the maximum
    over time of the count of DISTINCT VEHICLES whose revenue interval
    covers the instant. Every day counts: the atypical-day exclusion that
    voms_v0 documents for non-DR modes is deliberately NOT applied (the
    definitions are opposite; do not reuse voms_v0 for DR).

    Intervals are the same revenue intervals dr_vrh_v0 prices: non-TX spans
    (a no-show visit inside a span keeps the vehicle in revenue service) and
    TX merged passenger-onboard windows. Boundary convention (documented):
    intervals are CLOSED — a vehicle ending an interval at the same instant
    another starts counts as simultaneous at that instant.

    The 0.1.1 correction (tracker superseding note, 2026-07-13): the sweep
    counts VEHICLES, never concurrent intervals — a vehicle covered by
    several intervals at one instant (two spans touching at a break
    boundary under the closed-interval convention, or overlapping intervals
    from ADJACENT vehicle-days, e.g. a midnight-crossing trip on service
    date D overlapping D+1's first pickup) counts ONCE. The definition
    counts "vehicles in revenue service", and one vehicle is one vehicle.
    0.1.0 (retained runnable as :func:`compute_dr_voms_v0_1_0`) could
    double-count exactly those shapes.

    ``peak_start`` is the FIRST instant attaining the maximum (deterministic
    tie-break); lineage covers the trips of the intervals in service at that
    instant. Empty input yields value 0 (an observed maximum, never a guess).
    """
    ordered = _sorted_trips(trips)
    counted, warnings, counters = _account(ordered)

    events: list[tuple[datetime, int, str]] = []  # (time, +1 first, vehicle)
    for day in counted:
        for interval in day.intervals:
            events.append((interval.start, 0, day.vehicle_id))
            events.append((interval.end, 1, day.vehicle_id))
    # Starts (0) before ends (1) at equal instants: closed intervals.
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    # Sweep over DISTINCT vehicles: per vehicle, the count of its intervals
    # covering the current instant; the concurrency counter moves only on
    # 0 -> 1 (vehicle enters revenue service) and 1 -> 0 (vehicle leaves).
    covering_by_vehicle: dict[str, int] = {}
    concurrent = 0
    peak = 0
    peak_start: datetime | None = None
    for time, kind, vehicle in events:
        if kind == 0:
            covering_by_vehicle[vehicle] = covering_by_vehicle.get(vehicle, 0) + 1
            if covering_by_vehicle[vehicle] == 1:
                concurrent += 1
                if concurrent > peak:
                    peak = concurrent
                    peak_start = time
        else:
            covering_by_vehicle[vehicle] -= 1
            if covering_by_vehicle[vehicle] == 0:
                del covering_by_vehicle[vehicle]
                concurrent -= 1

    input_ids: dict[str, None] = {}
    if peak_start is not None:
        for day in counted:
            for interval in day.intervals:
                if interval.start <= peak_start <= interval.end:
                    for record_id in _record_ids(interval.trips):
                        input_ids.setdefault(record_id, None)

    detail = DrVomsDetail(
        unique_vehicles=len({day.vehicle_id for day in counted}),
        peak_vehicles=peak,
        peak_start=None if peak_start is None else peak_start.isoformat(),
        vehicle_days=counters["vehicle_days_counted"],
        includes_atypical_days=True,
        tos_mix=counters["tos_mix"],
        source_mix=counters["source_mix"],
    )

    return CalcResult(
        value=Decimal(peak),
        unit=UNIT_VEHICLES,
        calc_name=VOMS_CALC_NAME,
        calc_version=VOMS_CALC_VERSION,
        input_record_ids=tuple(input_ids),
        blocking_issues=(),
        warnings=tuple(warnings),
        infos=tuple(_simulated_source_info(ordered, counters["source_mix"])),
        detail=detail,
    )


def compute_dr_voms_v0_1_0(trips: Iterable[DrTrip]) -> CalcResult:
    """dr_voms_v0 0.1.0 — RETAINED RUNNABLE, SUPERSEDED by 0.1.1.

    The tracker's dated superseding note (2026-07-13, hardening pass)
    records the confirmed defect this version carries: the sweep counts
    concurrent INTERVALS, not distinct vehicles, so the SAME vehicle is
    double-counted where two of its revenue intervals touch at one instant
    (a span break boundary under the closed-interval convention) or overlap
    across adjacent vehicle-days (a midnight-crossing trip on service date
    D overlapping D+1's first pickup — the (vehicle_id, service_date)
    grouping yields two vehicle-days whose intervals coexist in real time).
    The Exhibit 38/40 definition counts "the largest number of VEHICLES in
    revenue service at any one time". This function exists only so figures
    persisted under calc_version 0.1.0 stay reproducible bit for bit; never
    run it for new figures.
    """
    ordered = _sorted_trips(trips)
    counted, warnings, counters = _account(ordered)

    events: list[tuple[datetime, int, str]] = []  # (time, +1 first, vehicle)
    for day in counted:
        for interval in day.intervals:
            events.append((interval.start, 0, day.vehicle_id))
            events.append((interval.end, 1, day.vehicle_id))
    # Starts (0) before ends (1) at equal instants: closed intervals.
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    concurrent = 0
    peak = 0
    peak_start: datetime | None = None
    for time, kind, _vehicle in events:
        if kind == 0:
            concurrent += 1
            if concurrent > peak:
                peak = concurrent
                peak_start = time
        else:
            concurrent -= 1

    input_ids: dict[str, None] = {}
    if peak_start is not None:
        for day in counted:
            for interval in day.intervals:
                if interval.start <= peak_start <= interval.end:
                    for record_id in _record_ids(interval.trips):
                        input_ids.setdefault(record_id, None)

    detail = DrVomsDetail(
        unique_vehicles=len({day.vehicle_id for day in counted}),
        peak_vehicles=peak,
        peak_start=None if peak_start is None else peak_start.isoformat(),
        vehicle_days=counters["vehicle_days_counted"],
        includes_atypical_days=True,
        tos_mix=counters["tos_mix"],
        source_mix=counters["source_mix"],
    )

    return CalcResult(
        value=Decimal(peak),
        unit=UNIT_VEHICLES,
        calc_name=VOMS_CALC_NAME,
        calc_version=VOMS_CALC_VERSION_0_1_0,
        input_record_ids=tuple(input_ids),
        blocking_issues=(),
        warnings=tuple(warnings),
        infos=tuple(_simulated_source_info(ordered, counters["source_mix"])),
        detail=detail,
    )


def compute_dr_pmt(trips: Iterable[DrTrip]) -> CalcResult:
    """dr_pmt_v0 0.1.0 — DR Passenger Miles Traveled (onboard-distance sums).

    Per counted completed booking: onboard distance (odometer pair, else
    onboard_miles) × persons (riders + non-employee attendants/companions).
    No load-profile reconstruction (the handoff-0013 'no load-profile
    path') — the wire contract's measured onboard distances ARE the
    per-passenger distances. A booking with no measurable distance is
    EXCLUDED with one warning (never a guessed distance); no-shows carry no
    passengers and no onboard segment. Value: Decimal miles, one final 0.01
    quantization. Persists into the existing 'pmt' metric under the DR
    mode/TOS scopes (runner wiring).
    """
    ordered = _sorted_trips(trips)
    counted, warnings, counters = _account(ordered)

    total = Decimal(0)
    trips_counted = 0
    trips_excluded = 0
    persons_counted = 0
    distance_sources: dict[str, int] = {}
    input_ids: dict[str, None] = {}

    for day in counted:
        for trip in day.trips:
            if trip.no_show:
                continue  # no passenger, no onboard segment
            distance, source = _trip_onboard_distance(trip)
            if distance is None:
                trips_excluded += 1
                warnings.append(
                    Finding(
                        issue_type="dr_onboard_distance_missing",
                        severity=SEVERITY_WARNING,
                        title=(
                            f"Trip {trip.dr_trip_id} excluded from DR PMT: "
                            f"no measurable onboard distance"
                        ),
                        description=(
                            f"Trip {trip.dr_trip_id!r} (vehicle "
                            f"{trip.vehicle_id!r}, {trip.service_date}, "
                            f"{trip.persons} person(s)) carries no odometer "
                            f"pair and no onboard_miles, so its passenger "
                            f"miles cannot be measured. The booking was "
                            f"EXCLUDED from the summed figure — the figure "
                            f"UNDERSTATES passenger miles by this booking; a "
                            f"distance is never guessed. Its record is cited "
                            f"here instead of appearing in lineage."
                        ),
                        source_record_ids=(trip.source_record_id,),
                    )
                )
                continue
            total += distance * trip.persons
            trips_counted += 1
            persons_counted += trip.persons
            distance_sources[source] = distance_sources.get(source, 0) + 1
            input_ids.setdefault(trip.source_record_id, None)

    value = total.quantize(_MILES_QUANTUM, rounding=ROUND_HALF_EVEN)
    detail = DrPmtDetail(
        passenger_miles_counted=value,
        trips_counted=trips_counted,
        trips_excluded_missing_distance=trips_excluded,
        persons_counted=persons_counted,
        no_show_trips=counters["no_show_trips"],
        distance_sources=distance_sources,
        tos_mix=counters["tos_mix"],
        source_mix=counters["source_mix"],
    )

    return CalcResult(
        value=value,
        unit=UNIT_PMT,
        calc_name=PMT_CALC_NAME,
        calc_version=PMT_CALC_VERSION,
        input_record_ids=tuple(input_ids),
        blocking_issues=(),
        warnings=tuple(warnings),
        infos=tuple(_simulated_source_info(ordered, counters["source_mix"])),
        detail=detail,
    )


# ---------------------------------------------------------------------------
# TOS scoping — input selection, not a semantics change (the handoff-0009
# mode-scoping position): each trip's TOS already selects its revenue rule
# inside the computes, so a TOS subset applies byte-identical math.
# ---------------------------------------------------------------------------


def partition_by_tos(trips: Iterable[DrTrip]) -> dict[str, list[DrTrip]]:
    """Partition trips by type of service AT VEHICLE-DAY GRANULARITY
    (sorted keys, input order kept within each bucket).

    A uniform vehicle-day's trips land in exactly their TOS bucket. A MIXED
    vehicle-day's trips land WHOLE in EVERY bucket its TOS values touch —
    deliberately: splitting the day's trips per TOS would make each subset
    look uniform and silently price a partial day under span semantics that
    assume the whole day (absent bookings would masquerade as revenue empty
    travel). Kept whole, each TOS bucket's accounting re-detects the mixed
    day and EXCLUDES it with the same warning the mode-level run raises —
    so per-TOS figures stay exactly the mode figure's TOS decomposition
    (counted groups identical; the additive metrics sum across buckets)."""
    groups: dict[tuple, list[DrTrip]] = {}
    for trip in trips:
        groups.setdefault((trip.vehicle_id, trip.service_date), []).append(trip)
    buckets: dict[str, list[DrTrip]] = {}
    for _key, group in groups.items():
        for tos in {t.tos for t in group}:
            buckets.setdefault(tos, []).extend(group)
    return {tos: buckets[tos] for tos in sorted(buckets)}


def _by_tos(compute, trips: Iterable[DrTrip]) -> dict[str, CalcResult]:
    return {
        tos: compute(subset) for tos, subset in partition_by_tos(trips).items()
    }


def compute_dr_vrh_by_tos(trips: Iterable[DrTrip]) -> dict[str, CalcResult]:
    """dr_vrh_v0 per TOS bucket (input selection; sorted keys)."""
    return _by_tos(compute_dr_vrh, trips)


def compute_dr_vrm_by_tos(trips: Iterable[DrTrip]) -> dict[str, CalcResult]:
    """dr_vrm_v0 per TOS bucket (input selection; sorted keys)."""
    return _by_tos(compute_dr_vrm, trips)


def compute_dr_upt_by_tos(trips: Iterable[DrTrip]) -> dict[str, CalcResult]:
    """dr_upt_v0 per TOS bucket (input selection; sorted keys)."""
    return _by_tos(compute_dr_upt, trips)


def compute_dr_voms_by_tos(trips: Iterable[DrTrip]) -> dict[str, CalcResult]:
    """dr_voms_v0 per TOS bucket (input selection; sorted keys). NOTE: VOMS
    is NOT additive across TOS — each bucket's peak may occur at a different
    instant, so max(per-TOS) <= mode-level <= sum(per-TOS)."""
    return _by_tos(compute_dr_voms, trips)


def compute_dr_pmt_by_tos(trips: Iterable[DrTrip]) -> dict[str, CalcResult]:
    """dr_pmt_v0 per TOS bucket (input selection; sorted keys)."""
    return _by_tos(compute_dr_pmt, trips)
