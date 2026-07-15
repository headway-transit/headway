"""pmt_v0 — Passenger Miles Traveled from TIDES passenger events × GTFS stop
geometry (handoff 0011), plus the Exhibit 44 average-trip-length estimator.

Regulatory basis (2026 NTD Policy Manual, Full Reporting — quotes verified
against docs/reference/ 2026-07-12; see REGULATORY_TRACKER.md, "Verified —
Passenger Miles Traveled"):

- **PMT definition** (p. 145): "Passenger Miles Traveled (PMT) is the sum of
  the distances each passenger traveled during the year."
- **Missing-trip rule** (p. 146): "If these vehicle trips are 2 percent or
  less of the total, transit agencies should factor up the data to account
  for the missing trips. However, if the vehicle trips with missing data
  exceed 2 percent of total trips, agencies must have a qualified
  statistician approve the factoring method used to account for the missing
  percentage." (The same rule upt_v0 implements; 0.02 is a REAL FTA
  threshold.)
- **APC validity checks** (p. 151, the manual's own validation examples):
  "agencies may flag trips or blocks where the difference between boardings
  and alightings is greater than 10 percent, or trips where the passenger
  load drops below zero." The APC scale-up method (pp. 151-152) DISCARDS
  invalid trips before averaging — so unlike upt_v0 (where these defects
  warn but the boarding count stands), pmt_v0 EXCLUDES an invalid trip's
  load profile from the summed figure and counts it against the p. 146 rule:
  a physically meaningless load profile (negative load, unbalanced counts,
  missing counts, unplaceable events, missing geometry) must never price
  passenger miles.

Computation (per mode/TOS scoping is the runner's input selection, exactly
like the other metrics): per trip, the running passenger load by
stop_sequence (cumulative boardings − alightings from the TIDES events) ×
the distance of each segment between consecutive scheduled stops
(canonical.stop_times, migration 0019), summed over valid trips, then
factored up per p. 146.

Distance-source precedence per segment (handoff 0011, binding):

1. GTFS ``shape_dist_traveled`` deltas, when both endpoints carry a FINITE
   value (``math.isfinite`` — a non-finite value that slipped past upstream
   validation is rejected defensively, never priced), the delta is
   non-negative, AND the caller supplies the feed's
   miles-per-unit conversion (``shape_dist_unit_miles``) — the GTFS spec
   leaves shape_dist units FEED-DEFINED (they must only be consistent with
   shapes.txt), so a unit is an explicit input, never guessed; without it,
   shape data is unusable and the run says so ('shape_dist_unit_unknown').
2. Stop-to-stop haversine between the stops' coordinates — a DOCUMENTED
   DIVERGENCE: straight-line chords understate the actual path distance, so
   every figure it touches carries the 'haversine_distance_fallback' info
   finding and the segment counts in the detail.
3. Neither available under a nonzero load → the trip's geometry is
   incomplete → the trip is invalid (never a guessed distance). A segment
   whose running load is ZERO contributes exactly 0 passenger miles
   regardless of its distance, so an undeterminable distance there does not
   invalidate the trip (mathematical identity, not an approximation).

Event-to-stop placement (documented v0 join assumption — verified against
the TIDES spec 2026-07-12, TIDES-transit/TIDES
``spec/passenger_events.schema.json``, main branch): TIDES
``trip_stop_sequence`` is "The actual order of stops visited within a
performed trip. The values must start at 1 and must be consecutive along
the trip" — an ORDINAL visit index, not the GTFS ``stop_sequence`` (the
GTFS-referencing TIDES field is ``scheduled_stop_sequence``, which
canonical.passenger_events, migration 0012, does not carry). pmt_v0 places
an event by matching its ``trip_stop_sequence`` value against the trip's
scheduled ``stop_sequence`` values — exact only where the performed visit
order equals the schedule's numbering (consecutive-from-1 sequences, no
detours/skips). Where the numbering differs (e.g. MBTA rail's 1, 10,
20, ...), the events are UNPLACEABLE and the trip is invalid — the
calculation refuses to guess the mapping (live-verified 2026-07-12: every
rail/subway trip refused for exactly this reason). Closure: a
transform/schema increment carrying TIDES ``scheduled_stop_sequence`` (or
``stop_id``) onto canonical.passenger_events — handoff 0011 Response, open
question.

Lineage: input_record_ids are the passenger-event records of VALID trips
(both boardings and alightings — both sides feed the load profile); an
invalid trip's records are cited by its warning finding instead. The stop
geometry's own provenance is carried by the transform's lineage edges
(canonical.stop_times/stops row → static-feed raw record, migration 0019
note) — a documented limitation: the metric's direct edges cite events only,
matching how vrm/vrh cite positions but not the trips/routes join.

Mile arithmetic follows headway_calc.distance: float legs, ONE final Decimal
quantization (0.01 mile, ROUND_HALF_EVEN, engineering convention).

Average-trip-length estimator (Exhibit 44, pp. 154-155) — a SEPARATE pure
function family with its own provenance label, never conflated with computed
PMT: "estimate PMT data in a non-sampling year by multiplying the average
trip length from the most recent mandatory year by the UPT for the current
year", per schedule type. The worked example (verbatim, golden-pinned):
mandatory year PMT 60,000,000 / UPT 12,750,000 → ATL 4.71; next year UPT
13,400,000 → estimated PMT 63,114,000 (4.71 × 13,400,000).

Pure and deterministic: stdlib only, no network, no clock reads, no
randomness. Time comes exclusively from the input events.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Iterable

from headway_calc.attestation import (
    P146_ATTESTATION_BASIS,
    AttestationContext,
    governing_attestation,
)
from headway_calc.distance import MILES_QUANTUM, haversine_miles, miles_to_decimal
from headway_calc.types import (
    SEVERITY_BLOCKING,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    CalcResult,
    Finding,
    PassengerEvent,
    PmtDetail,
    StopTime,
)
from headway_calc.upt import (
    ALIGHTING_EVENT_TYPE,
    BOARDING_EVENT_TYPE,
    IMBALANCE_THRESHOLD,
    MISSING_TRIP_THRESHOLD,
    _sorted_events,
    _stop_order_key,
)

CALC_NAME = "pmt_v0"
#: 0.2.0 (handoff 0019): the >2% path accepts a statistician attestation
#: context, exactly as upt_v0 0.2.0 — WITH a recorded, unrevoked, in-scope
#: attestation the figure is factored up per the p. 146 sentence and carries
#: the attestation's provenance permanently; WITHOUT one, the refusal is
#: byte-for-byte 0.1.0's (regression-pinned). 0.1.0 is RETAINED runnable as
#: compute_pmt_v0_1_0 (the sscls convention).
CALC_VERSION = "0.2.0"
#: The NTD measure itself (mirrors upt_v0's unit-naming convention).
UNIT = "passenger_miles"

#: Reported-share and reported-factor quanta — the upt_v0 conventions
#: (comparison against the threshold is always exact, never quantized).
_SHARE_QUANTUM = Decimal("0.0001")
_FACTOR_QUANTUM = Decimal("0.000001")

#: How many trip_ids a finding names verbatim before truncating.
_TRIPS_NAMED = 20

#: The envelope source of REAL TIDES feeds (handoff 0005 simulated-data rule).
_REAL_SOURCE = "tides"

#: Invalid-trip reasons, in the DOCUMENTED priority order used both for
#: evaluation and for the detail's first-reason counting:
#: - 'geometry_unavailable'  — no canonical.stop_times rows for the trip;
#: - 'null_event_count'      — a passenger event with NULL event_count (a
#:   load profile over a guessed count would fabricate passenger miles;
#:   contrast upt_v0, where the NULL warns and contributes 0 to a COUNT);
#: - 'unplaceable_event'     — trip_stop_sequence NULL or absent from the
#:   trip's scheduled stop sequence (the event cannot be placed on the
#:   profile);
#: - 'count_imbalance'       — p. 151: |boardings − alightings| >
#:   imbalance_threshold × boardings;
#: - 'negative_load'         — p. 151: the running load drops below zero;
#: - 'geometry_incomplete'   — duplicate stop_sequences, or a segment under
#:   nonzero load with no usable distance source (precedence above; a
#:   non-finite shape_dist delta or leg is NOT usable — rejected
#:   defensively via math.isfinite, never priced into the figure).
INVALID_REASONS = (
    "geometry_unavailable",
    "null_event_count",
    "unplaceable_event",
    "count_imbalance",
    "negative_load",
    "geometry_incomplete",
)


def _trip_reasons_and_miles(
    trip_events: list[PassengerEvent],
    geometry: list[StopTime],
    imbalance_threshold: Decimal,
    unit_factor: float | None,
) -> tuple[list[str], float, int, int]:
    """Evaluate one trip: (reasons, miles, shape_segments, haversine_segments).

    ``reasons`` empty ⇔ the trip is valid and ``miles`` (float — final
    Decimal conversion happens once, on the fleet aggregate) is its PMT
    contribution. Segment-source counts are meaningful only for valid trips.
    """
    reasons: list[str] = []

    # 1. geometry_unavailable
    if not geometry:
        reasons.append("geometry_unavailable")

    # 2. null_event_count
    if any(e.event_count is None for e in trip_events):
        reasons.append("null_event_count")

    # 3. unplaceable_event (needs the sequence set; skip if no geometry —
    #    'geometry_unavailable' already covers the trip)
    sequences = {st.stop_sequence for st in geometry}
    if geometry and any(
        e.trip_stop_sequence is None or e.trip_stop_sequence not in sequences
        for e in trip_events
    ):
        reasons.append("unplaceable_event")

    # 4. count_imbalance (p. 151) — NULL counts as 0 here purely to keep the
    #    arithmetic total (the NULL itself already invalidated the trip).
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
    if Decimal(abs(boardings - alightings)) > imbalance_threshold * Decimal(
        boardings
    ):
        reasons.append("count_imbalance")

    # 5. negative_load (p. 151) — the upt_v0 running-load order
    #    (trip_stop_sequence, then event_timestamp; NULL sequence last).
    load = 0
    for e in sorted(trip_events, key=_stop_order_key):
        if e.event_type == BOARDING_EVENT_TYPE:
            load += e.event_count or 0
        else:
            load -= e.event_count or 0
        if load < 0:
            reasons.append("negative_load")
            break

    if reasons:
        return reasons, 0.0, 0, 0

    # 6. the distance walk — geometry_incomplete aborts, else valid.
    ordered = sorted(geometry, key=lambda st: (st.stop_sequence, st.stop_id))
    if len({st.stop_sequence for st in ordered}) != len(ordered):
        return ["geometry_incomplete"], 0.0, 0, 0

    net_by_sequence: dict[int, int] = {}
    for e in trip_events:
        assert e.trip_stop_sequence is not None  # unplaceable already checked
        delta = e.event_count or 0
        if e.event_type == ALIGHTING_EVENT_TYPE:
            delta = -delta
        net_by_sequence[e.trip_stop_sequence] = (
            net_by_sequence.get(e.trip_stop_sequence, 0) + delta
        )

    miles = 0.0
    shape_segments = 0
    haversine_segments = 0
    load = 0
    for here, there in zip(ordered, ordered[1:]):
        load += net_by_sequence.get(here.stop_sequence, 0)
        if load == 0:
            continue  # exactly 0 passenger miles — no distance needed
        leg: float | None = None
        if (
            unit_factor is not None
            and here.shape_dist_traveled is not None
            and there.shape_dist_traveled is not None
            # Defensive non-finite rejection (2026-07-13 hardening pass): an
            # inf/NaN shape_dist_traveled that slipped through upstream
            # validation must never price a segment — a non-finite value is
            # NOT a usable shape delta, so the segment falls through to the
            # haversine fallback exactly like a negative delta, and with no
            # coordinates the trip is invalid ('geometry_incomplete', the
            # established vocabulary) — never a non-finite figure.
            and math.isfinite(here.shape_dist_traveled)
            and math.isfinite(there.shape_dist_traveled)
            and there.shape_dist_traveled >= here.shape_dist_traveled
        ):
            leg = (there.shape_dist_traveled - here.shape_dist_traveled) * unit_factor
            shape_segments += 1
        elif (
            here.latitude is not None
            and here.longitude is not None
            and there.latitude is not None
            and there.longitude is not None
        ):
            leg = haversine_miles(
                here.latitude, here.longitude, there.latitude, there.longitude
            )
            haversine_segments += 1
        if leg is None or not math.isfinite(leg):
            return ["geometry_incomplete"], 0.0, 0, 0
        miles += load * leg
    if not math.isfinite(miles):  # belt-and-suspenders: never a non-finite figure
        return ["geometry_incomplete"], 0.0, 0, 0
    return [], miles, shape_segments, haversine_segments


def compute_pmt(
    events: Iterable[PassengerEvent],
    operated_trip_ids: Iterable[str],
    stop_times: Iterable[StopTime],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    shape_dist_unit_miles: Decimal | None = None,
    attestations: Iterable[AttestationContext] = (),
) -> CalcResult:
    """Compute pmt_v0 (version 0.2.0) — Passenger Miles Traveled.

    Base figure (p. 145: "the sum of the distances each passenger
    traveled"): per trip with a trip assignment (the v0 revenue-service
    proxy, as in upt_v0), the running load by stop_sequence × each segment's
    distance between consecutive scheduled stops, summed over VALID trips
    and quantized 0.01 mile ROUND_HALF_EVEN (float legs, one final Decimal —
    the vrm_v0 convention). Distance-source precedence and the invalid-trip
    reasons are documented in the module docstring / INVALID_REASONS.

    An invalid trip is EXCLUDED (one 'pmt_invalid_trip_excluded' warning per
    trip citing its event records — pp. 151-152: the scale-up method
    discards invalid trips) and, when it was operated, counts against the
    p. 146 missing-data rule together with the missing trips (operated
    trips with zero passenger events):

    - (missing + invalid operated) ≤ missing_trip_threshold × operated
      (exact comparison): the valid-trip figure is factored up
      deterministically, PMT_reported = counted × operated/(operated −
      missing − invalid_operated), quantized 0.01 mile;
    - above the threshold WITHOUT an applicable attestation: ONE blocking
      'apc_missing_trips_above_fta_threshold' finding (the same issue_type
      as upt_v0 — it is the same p. 146 rule) and value None: the
      statistician-approved factoring is a human workflow, never guessed.
      Byte-for-byte the 0.1.0 refusal (regression-pinned);
    - above the threshold WITH an applicable attestation (handoff 0019 —
      the same semantics as upt_v0 0.2.0: ``attestations`` are already
      scope/period-matched by the caller, the calc re-checks metric
      ('pmt' — mismatch raises ValueError) and revocation, the
      earliest-entered survivor governs): the SAME deterministic factor-up
      as the ≤2% branch plus ONE info finding
      ``'apc_missing_trips_attested_factor_up'`` and the attestation's
      provenance in ``detail.attestation``. Nothing else moves: invalid
      trips stay excluded and warned, simulated-source flags stand, the
      ≤2% branch ignores attestations entirely;
    - zero operated trips (degenerate period): share 0, factor 1.

    Info findings: 'simulated_source_data' exactly as upt_v0 (handoff 0005
    binding rule; source_mix always in the detail);
    'haversine_distance_fallback' whenever any counted segment was priced by
    straight-line haversine (the documented understating divergence);
    'shape_dist_unit_unknown' when shape_dist_traveled data exists but no
    ``shape_dist_unit_miles`` conversion was supplied (feed-defined units —
    never guessed).

    Returns a CalcResult whose detail is a PmtDetail (present on blocked
    results too — the evidence always travels).
    """
    missing_trip_threshold = Decimal(str(missing_trip_threshold))
    imbalance_threshold = Decimal(str(imbalance_threshold))
    if shape_dist_unit_miles is not None:
        shape_dist_unit_miles = Decimal(str(shape_dist_unit_miles))
        if not shape_dist_unit_miles > 0:
            raise ValueError(
                f"shape_dist_unit_miles must be > 0 when given; got "
                f"{shape_dist_unit_miles!r}"
            )
    unit_factor = (
        None if shape_dist_unit_miles is None else float(shape_dist_unit_miles)
    )
    ordered = _sorted_events(events)
    operated = sorted(set(operated_trip_ids))

    geometry_by_trip: dict[str, list[StopTime]] = {}
    any_shape_dist = False
    for st in stop_times:
        geometry_by_trip.setdefault(st.trip_id, []).append(st)
        if st.shape_dist_traveled is not None:
            any_shape_dist = True

    # --- source mix + per-trip passenger events ------------------------------
    source_mix: dict[str, int] = {}
    by_trip: dict[str, list[PassengerEvent]] = {}
    for event in ordered:
        source_mix[event.source] = source_mix.get(event.source, 0) + 1
        if event.trip_id is None:
            continue  # revenue-service proxy: unassigned events not counted
        if event.event_type in (BOARDING_EVENT_TYPE, ALIGHTING_EVENT_TYPE):
            by_trip.setdefault(event.trip_id, []).append(event)

    # --- per-trip validity + miles -------------------------------------------
    warnings: list[Finding] = []
    infos: list[Finding] = []
    invalid_trip_reasons: dict[str, int] = {}
    invalid_trips: set[str] = set()
    valid_trips: set[str] = set()
    total_miles = 0.0
    shape_segments = 0
    haversine_segments = 0
    input_ids: dict[str, None] = {}
    for trip_id in sorted(by_trip):
        trip_events = by_trip[trip_id]
        reasons, miles, n_shape, n_hav = _trip_reasons_and_miles(
            trip_events,
            geometry_by_trip.get(trip_id, []),
            imbalance_threshold,
            unit_factor,
        )
        if reasons:
            invalid_trips.add(trip_id)
            invalid_trip_reasons[reasons[0]] = (
                invalid_trip_reasons.get(reasons[0], 0) + 1
            )
            trip_record_ids: dict[str, None] = {}
            for e in trip_events:
                trip_record_ids.setdefault(e.source_record_id, None)
            warnings.append(
                Finding(
                    issue_type="pmt_invalid_trip_excluded",
                    severity=SEVERITY_WARNING,
                    title=(
                        f"Trip {trip_id} excluded from PMT: {reasons[0]}"
                    ),
                    description=(
                        f"Trip {trip_id!r} failed the pmt_v0 validity checks "
                        f"({', '.join(reasons)}) and its load profile was "
                        f"EXCLUDED from the summed passenger-miles figure — "
                        f"per the 2026 NTD Policy Manual pp. 151-152 APC "
                        f"scale-up discipline (invalid trips are discarded, "
                        f"the manual's own examples being 'trips or blocks "
                        f"where the difference between boardings and "
                        f"alightings is greater than 10 percent, or trips "
                        f"where the passenger load drops below zero') and "
                        f"the handoff-0011 rule that a distance or count is "
                        f"never guessed. The exclusion counts against the "
                        f"p. 146 missing-data rule when the trip was "
                        f"operated."
                    ),
                    source_record_ids=tuple(trip_record_ids),
                )
            )
        else:
            valid_trips.add(trip_id)
            total_miles += miles
            shape_segments += n_shape
            haversine_segments += n_hav
            for e in trip_events:
                input_ids.setdefault(e.source_record_id, None)

    counted = miles_to_decimal(total_miles)

    # --- simulated-source rule (handoff 0005, inherited verbatim) -------------
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
                    f"{len(ordered)} passenger events carry a source other "
                    f"than 'tides': "
                    + ", ".join(
                        f"{s} ({source_mix[s]} events)" for s in simulated_sources
                    )
                    + ". Per the handoff-0005 simulated-data rule, simulator "
                    "output is permanently distinguishable in provenance and "
                    "a certifiable figure containing simulated records is a "
                    "contradiction the DQ trail must make visible: this "
                    "figure is NOT certifiable or reportable. The full "
                    "source mix is recorded in the metric value's detail."
                ),
                source_record_ids=tuple(simulated_record_ids),
            )
        )

    # --- distance-source divergence flags --------------------------------------
    if haversine_segments:
        infos.append(
            Finding(
                issue_type="haversine_distance_fallback",
                severity=SEVERITY_INFO,
                title=(
                    f"{haversine_segments} of "
                    f"{haversine_segments + shape_segments} counted segments "
                    f"priced by stop-to-stop haversine"
                ),
                description=(
                    f"{haversine_segments} of "
                    f"{haversine_segments + shape_segments} segments in the "
                    f"summed figure had no usable GTFS shape_dist_traveled "
                    f"delta and were priced as straight-line (haversine) "
                    f"stop-to-stop distance — a DOCUMENTED DIVERGENCE "
                    f"(handoff 0011): a chord understates the actual path "
                    f"distance, so this figure UNDERSTATES passenger miles "
                    f"wherever the route curves between stops. Closure path: "
                    f"shapes.txt polyline interpolation (handoff 0011 open "
                    f"question). The figure stands; the divergence is "
                    f"recorded here and in the detail's "
                    f"distance_source_segments."
                ),
                source_record_ids=(),
            )
        )
    if any_shape_dist and unit_factor is None:
        infos.append(
            Finding(
                issue_type="shape_dist_unit_unknown",
                severity=SEVERITY_INFO,
                title=(
                    "shape_dist_traveled present but its unit was not "
                    "supplied — shape distances unused"
                ),
                description=(
                    "The stop geometry carries shape_dist_traveled values, "
                    "but the GTFS spec leaves their unit FEED-DEFINED (they "
                    "must only be consistent with shapes.txt), and no "
                    "shape_dist_unit_miles conversion was supplied to this "
                    "run. Per the never-guess rule the shape data was NOT "
                    "used; segments fell back to the flagged haversine "
                    "distance. Supply the feed's unit conversion to use the "
                    "shape deltas."
                ),
                source_record_ids=(),
            )
        )

    # --- missing-trip rule (p. 146; invalid trips count, pp. 151-152) ---------
    operated_count = len(operated)
    missing = [t for t in operated if t not in by_trip]
    missing_count = len(missing)
    invalid_operated = [t for t in operated if t in invalid_trips]
    unusable_count = missing_count + len(invalid_operated)
    exact_share = (
        Decimal(0)
        if operated_count == 0
        else Decimal(unusable_count) / Decimal(operated_count)
    )
    share = exact_share.quantize(_SHARE_QUANTUM, rounding=ROUND_HALF_EVEN)
    above_threshold = Decimal(unusable_count) > missing_trip_threshold * Decimal(
        operated_count
    )

    blocking_issues: tuple[Finding, ...] = ()
    factor_applied: Decimal | None = None
    value: Decimal | None = None
    attestation_provenance: dict | None = None
    governing = governing_attestation(attestations, "pmt")
    if above_threshold and governing is not None:
        # The p. 146 permission path (handoff 0019), exactly as upt_v0
        # 0.2.0: a recorded statistician approval factors the VALID-trip
        # figure up deterministically; the exclusions and their warnings
        # stand untouched. unusable_count > 0 here by construction.
        exact_factor = Decimal(operated_count) / Decimal(
            operated_count - unusable_count
        )
        value = (
            counted
            * Decimal(operated_count)
            / Decimal(operated_count - unusable_count)
        ).quantize(MILES_QUANTUM, rounding=ROUND_HALF_EVEN)
        factor_applied = exact_factor.quantize(
            _FACTOR_QUANTUM, rounding=ROUND_HALF_EVEN
        )
        attestation_provenance = governing.to_provenance_dict()
        infos.append(
            Finding(
                issue_type="apc_missing_trips_attested_factor_up",
                severity=SEVERITY_INFO,
                title=(
                    f"Factored beyond the 2% threshold under a "
                    f"statistician-approved method — attestation "
                    f"#{governing.attestation_id}"
                ),
                description=(
                    f"{missing_count} of {operated_count} operated trips "
                    f"(observed in canonical.vehicle_positions) have zero "
                    f"passenger events and {len(invalid_operated)} more "
                    f"failed the pp. 151-152 validity checks (their load "
                    f"profiles were discarded): missing-data share {share} "
                    f"exceeds the threshold of {missing_trip_threshold}. The "
                    f"2026 NTD Policy Manual p. 146 permits factoring here "
                    f"only with approval: '{P146_ATTESTATION_BASIS}' That "
                    f"approval is on record as attestation "
                    f"#{governing.attestation_id} — statistician "
                    f"{governing.statistician_name} "
                    f"({governing.statistician_credentials}); approved "
                    f"method: {governing.method_description}; approval "
                    f"document: {governing.document_reference}; entered by "
                    f"{governing.entered_by} at "
                    f"{governing.entered_at.isoformat()}. The valid-trip "
                    f"figure was factored up by {factor_applied} (counted x "
                    f"operated / (operated - missing - invalid_operated)) "
                    f"and carries this attestation in its detail "
                    f"permanently. Revoking the attestation never deletes "
                    f"this record; it prevents FUTURE runs from factoring "
                    f"under it."
                ),
                # Missing trips have no passenger-event records to cite;
                # invalid trips' records are cited by their own warnings.
                source_record_ids=(),
            )
        )
    elif above_threshold:
        unusable_named = missing + invalid_operated
        named = ", ".join(unusable_named[:_TRIPS_NAMED])
        if unusable_count > _TRIPS_NAMED:
            named += f", ... ({unusable_count - _TRIPS_NAMED} more)"
        blocking_issues = (
            Finding(
                issue_type="apc_missing_trips_above_fta_threshold",
                severity=SEVERITY_BLOCKING,
                title=(
                    f"Missing-or-invalid trip share {share} exceeds the FTA "
                    f"2% threshold: {missing_count} missing + "
                    f"{len(invalid_operated)} invalid of {operated_count} "
                    f"operated trips"
                ),
                description=(
                    f"{missing_count} of {operated_count} operated trips "
                    f"(observed in canonical.vehicle_positions) have zero "
                    f"passenger events and {len(invalid_operated)} more "
                    f"failed the pp. 151-152 validity checks (their load "
                    f"profiles were discarded): missing-data share {share} "
                    f"exceeds the threshold of {missing_trip_threshold}. Per "
                    f"the 2026 NTD Policy Manual p. 146, 'if the vehicle "
                    f"trips with missing data exceed 2 percent of total "
                    f"trips, agencies must have a qualified statistician "
                    f"approve the factoring method used to account for the "
                    f"missing percentage' — a human workflow, so the "
                    f"calculation refuses to emit a value "
                    f"({missing_trip_threshold} is the FTA threshold, not an "
                    f"engineering placeholder). Missing/invalid trip_ids: "
                    f"{named}."
                ),
                # Missing trips have no passenger-event records to cite;
                # invalid trips' records are cited by their own warnings.
                source_record_ids=(),
            ),
        )
    else:
        if unusable_count == 0:
            exact_factor = Decimal(1)
            value = counted
        else:
            exact_factor = Decimal(operated_count) / Decimal(
                operated_count - unusable_count
            )
            value = (
                counted
                * Decimal(operated_count)
                / Decimal(operated_count - unusable_count)
            ).quantize(MILES_QUANTUM, rounding=ROUND_HALF_EVEN)
        factor_applied = exact_factor.quantize(
            _FACTOR_QUANTUM, rounding=ROUND_HALF_EVEN
        )

    detail = PmtDetail(
        passenger_miles_counted=counted,
        operated_trips=operated_count,
        trips_with_events=len(by_trip),
        valid_trips=len(valid_trips),
        invalid_trips=len(invalid_trips),
        missing_trips=missing_count,
        invalid_trip_reasons=invalid_trip_reasons,
        missing_or_invalid_share=share,
        factor_applied=factor_applied,
        distance_source_segments={
            "shape_dist_traveled": shape_segments,
            "haversine": haversine_segments,
        },
        shape_dist_unit_miles=shape_dist_unit_miles,
        source_mix=source_mix,
        missing_trip_threshold=missing_trip_threshold,
        imbalance_threshold=imbalance_threshold,
        attestation=attestation_provenance,
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


def compute_pmt_v0_1_0(
    events: Iterable[PassengerEvent],
    operated_trip_ids: Iterable[str],
    stop_times: Iterable[StopTime],
    *,
    missing_trip_threshold: Decimal = MISSING_TRIP_THRESHOLD,
    imbalance_threshold: Decimal = IMBALANCE_THRESHOLD,
    shape_dist_unit_miles: Decimal | None = None,
) -> CalcResult:
    """pmt_v0 0.1.0, RETAINED runnable (the sscls convention — shipped
    versions stay reproducible; handoff 0019).

    0.1.0 predates statistician attestations: it is exactly compute_pmt
    with no attestation context — every output is byte-identical, because
    the 0.2.0 change is strictly additive (the attestation detail key is
    emitted only when an attestation governed, which can never happen
    here). Pinned by tests/test_pmt_attestation.py.
    """
    result = compute_pmt(
        events,
        operated_trip_ids,
        stop_times,
        missing_trip_threshold=missing_trip_threshold,
        imbalance_threshold=imbalance_threshold,
        shape_dist_unit_miles=shape_dist_unit_miles,
        attestations=(),
    )
    return dataclasses.replace(result, calc_version="0.1.0")


# ---------------------------------------------------------------------------
# Average-trip-length estimator (Exhibit 44, pp. 154-155) — ESTIMATION, never
# conflated with computed PMT.
# ---------------------------------------------------------------------------

ESTIMATOR_NAME = "pmt_atl_estimate"
ESTIMATOR_VERSION = "0.1.0"
#: The provenance label every estimate carries — an ESTIMATE by the manual's
#: average-trip-length method, cited; never a computed (measured) figure.
ESTIMATION_METHOD = (
    "estimated — average trip length method (2026 NTD Policy Manual, Full "
    "Reporting, Exhibit 44, pp. 154-155): average trip length from the most "
    "recent mandatory sampling year × current-year UPT, per schedule type"
)

#: Exhibit 44 carries average trip length at two decimals (60,000,000 /
#: 12,750,000 → 4.71), and the products are whole passenger miles.
_ATL_QUANTUM = Decimal("0.01")
_ESTIMATE_QUANTUM = Decimal("1")

#: MR-20 / Exhibit 44 schedule types.
SCHEDULE_TYPES = ("Weekday", "Saturday", "Sunday", "Annual")


@dataclass(frozen=True)
class AverageTripLengthEstimate:
    """One Exhibit 44 estimate: ESTIMATED PMT for one schedule type.

    ``method`` is the fixed provenance label (ESTIMATION_METHOD) — the
    estimate must never be presented as computed PMT.
    ``mandatory_year_pmt``/``mandatory_year_upt`` are None when the caller
    supplied the average trip length directly (an agency's recorded ATL).
    """

    schedule_type: str
    average_trip_length: Decimal
    current_year_upt: Decimal
    estimated_pmt: Decimal
    mandatory_year_pmt: Decimal | None = None
    mandatory_year_upt: Decimal | None = None
    method: str = ESTIMATION_METHOD

    def to_dict(self) -> dict:
        return {
            "schedule_type": self.schedule_type,
            "average_trip_length": str(self.average_trip_length),
            "current_year_upt": str(self.current_year_upt),
            "estimated_pmt": str(self.estimated_pmt),
            "mandatory_year_pmt": (
                None
                if self.mandatory_year_pmt is None
                else str(self.mandatory_year_pmt)
            ),
            "mandatory_year_upt": (
                None
                if self.mandatory_year_upt is None
                else str(self.mandatory_year_upt)
            ),
            "method": self.method,
        }


def average_trip_length(
    mandatory_year_pmt: Decimal | int | str,
    mandatory_year_upt: Decimal | int | str,
) -> Decimal:
    """Average trip length from a mandatory-year PMT + UPT pair.

    Exhibit 44 (p. 154): 60,000,000 / 12,750,000 → 4.71 — two decimals
    (quantized 0.01, ROUND_HALF_EVEN). Refuses (ValueError) non-positive UPT
    or negative PMT: a ratio over a degenerate pair is a guess.
    """
    pmt = Decimal(str(mandatory_year_pmt))
    upt = Decimal(str(mandatory_year_upt))
    if upt <= 0:
        raise ValueError(
            f"average_trip_length requires mandatory-year UPT > 0; got {upt}"
        )
    if pmt < 0:
        raise ValueError(
            f"average_trip_length requires mandatory-year PMT >= 0; got {pmt}"
        )
    return (pmt / upt).quantize(_ATL_QUANTUM, rounding=ROUND_HALF_EVEN)


def estimate_pmt_from_average_trip_length(
    atl: Decimal | int | str,
    current_year_upt: Decimal | int | str,
    schedule_type: str = "Annual",
) -> AverageTripLengthEstimate:
    """ESTIMATED PMT = average trip length × current-year UPT (Exhibit 44).

    The product is quantized to whole passenger miles (Decimal 1,
    ROUND_HALF_EVEN — Exhibit 44's rows are exact whole-mile products).
    Refuses (ValueError) an unknown schedule type, non-positive ATL, or
    negative UPT.
    """
    if schedule_type not in SCHEDULE_TYPES:
        raise ValueError(
            f"schedule_type must be one of {SCHEDULE_TYPES}; got "
            f"{schedule_type!r}"
        )
    atl = Decimal(str(atl))
    upt = Decimal(str(current_year_upt))
    if atl <= 0:
        raise ValueError(f"average trip length must be > 0; got {atl}")
    if upt < 0:
        raise ValueError(f"current-year UPT must be >= 0; got {upt}")
    return AverageTripLengthEstimate(
        schedule_type=schedule_type,
        average_trip_length=atl,
        current_year_upt=upt,
        estimated_pmt=(atl * upt).quantize(
            _ESTIMATE_QUANTUM, rounding=ROUND_HALF_EVEN
        ),
    )


def estimate_pmt_average_trip_length(
    mandatory_year_pmt: Decimal | int | str,
    mandatory_year_upt: Decimal | int | str,
    current_year_upt: Decimal | int | str,
    schedule_type: str = "Annual",
) -> AverageTripLengthEstimate:
    """The full Exhibit 44 flow: ATL from the mandatory-year pair, then
    ESTIMATED PMT = ATL × current-year UPT (golden-pinned to the manual's
    worked example: 60,000,000/12,750,000 → 4.71; 4.71 × 13,400,000 =
    63,114,000)."""
    atl = average_trip_length(mandatory_year_pmt, mandatory_year_upt)
    estimate = estimate_pmt_from_average_trip_length(
        atl, current_year_upt, schedule_type
    )
    return AverageTripLengthEstimate(
        schedule_type=estimate.schedule_type,
        average_trip_length=estimate.average_trip_length,
        current_year_upt=estimate.current_year_upt,
        estimated_pmt=estimate.estimated_pmt,
        mandatory_year_pmt=Decimal(str(mandatory_year_pmt)),
        mandatory_year_upt=Decimal(str(mandatory_year_upt)),
    )
